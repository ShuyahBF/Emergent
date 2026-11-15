"""Lot 412 — Vidéos en streaming sur les écrans TV (Smart TV), pilotées depuis le téléphone.

Comment ça marche (pour un développeur WinDev) :
  1. La vidéo est chargée dans la « Bibliothèque de médias » de SAWALI (déjà en place : fichiers stockés dans Cloudflare R2, 200 Mo au plus).
  2. La télé est déjà appairée (Paramètres → « 📺 Écrans TV ») ; l'administrateur coche le contenu « Vidéos » pour cet écran.
  3. Depuis son téléphone, l'administrateur ouvre la « télécommande vidéo », choisit l'écran et la vidéo : « Lire », pause, ±10 s, position, arrêt.
     Chaque ordre est numéroté ; la page de la télé demande « y a-t-il un ordre plus récent que le n° N ? » toutes les 2 secondes (comme pour son flux).
  4. La vidéo arrive en STREAMING : la télé lit une adresse signée (valable 6 h, liée à CET écran et à CETTE vidéo) ; le serveur répond par morceaux
     (en-têtes « Range » du lecteur vidéo de la télé), sans jamais charger tout le fichier en mémoire. La télé renvoie sa position pour la télécommande.

Données dans `settings` (aucune nouvelle collection : le cluster MongoDB est plein) : un document « tv-video:<id écran> » par écran
{seq, commande, etat}. Aucun secret en base : la signature des adresses est calculée avec le secret du serveur (JWT_SECRET).
Formats : MP4 (H.264 + AAC) lu partout ; MKV / MOV / WebM dépendent de la télé (la télécommande le rappelle).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Optional, Tuple

from pymongo import ReturnDocument
from fastapi import Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from routes.ecran_tv import empreinte

logger = logging.getLogger("sawali.tv_video")

PREFIXE = "tv-video:"
VALIDITE_ADRESSE_H = 6                 # l'adresse signée du flux dure 6 heures (un film)
ACTIONS = ("lire", "pause", "reprendre", "avancer", "reculer", "position", "stop")
DELTA_MAX_S = 600                      # un saut d'avance / de recul : 10 minutes au plus
TAILLE_MORCEAU = 256 * 1024            # morceaux envoyés à la télé
EN_LIGNE_S = 60                        # écran « en ligne » s'il a été vu depuis moins de 60 secondes


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _secret_serveur() -> bytes:
    return (os.environ.get("JWT_SECRET") or "fallback-insecure").encode("utf-8")


def signer(ecran_id: str, media_id: str, expire: int) -> str:
    """Signature de l'adresse du flux : HMAC-SHA256(écran | vidéo | expiration)."""
    return hmac.new(_secret_serveur(), f"{ecran_id}|{media_id}|{expire}".encode("utf-8"), hashlib.sha256).hexdigest()[:40]


def signature_valide(ecran_id: str, media_id: str, expire: int, signature: str) -> bool:
    if expire < int(_maintenant().timestamp()):
        return False
    return hmac.compare_digest(signer(ecran_id, media_id, expire), signature or "")


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def lire_en_tete_range(valeur: Optional[str], taille: int) -> Optional[Tuple[int, int]]:
    """« bytes=0-1023 » → (0, 1023) ; « bytes=500- » → (500, fin) ; « bytes=-500 » → les 500 derniers octets ; None si absent ;
    ValueError si invalide ou hors du fichier (le serveur répond alors 416)."""
    if not valeur:
        return None
    m = _RANGE.match(valeur.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise ValueError("Range invalide")
    if m.group(1) == "":
        n = int(m.group(2))
        if n == 0:
            raise ValueError("Range vide")
        return max(0, taille - n), taille - 1
    debut = int(m.group(1)); fin = int(m.group(2)) if m.group(2) else taille - 1
    fin = min(fin, taille - 1)
    if debut >= taille or debut > fin:
        raise ValueError("Range hors du fichier")
    return debut, fin


def _ouvrir_plage(chemin: str, debut: int, fin: int) -> Iterator[bytes]:
    """Octets [debut, fin] du fichier stocké, par morceaux. R2 : lecture partielle (Range) ; sinon repli sur la lecture complète (fichiers ≤ 200 Mo)."""
    import storage as stockage
    cfg = stockage.config_r2()
    if cfg:
        client = stockage._client(cfg)
        for cle in stockage.cles_r2_lecture(chemin, cfg):
            try:
                rep = client.get_object(Bucket=cfg["bucket"], Key=cle, Range=f"bytes={debut}-{fin}")
            except Exception:  # noqa: BLE001 — clé absente : on essaie la forme suivante
                continue
            return rep["Body"].iter_chunks(TAILLE_MORCEAU)
    donnees, _ = stockage.fetch_bytes(chemin)
    return (donnees[i:min(i + TAILLE_MORCEAU, fin + 1)] for i in range(debut, fin + 1, TAILLE_MORCEAU))


def setup_tv_video_routes(*, db, api, get_current_admin):
    async def _ecran_de_la_tele(secret: str) -> Dict[str, Any]:
        """Écran appairé retrouvé par l'empreinte du secret de la télé (même méthode que les autres routes /tv/…)."""
        if not secret:
            raise HTTPException(status_code=401, detail="Écran non appairé")
        g = await db.settings.find_one({"_id": "global"}, {"tv_ecrans": 1}) or {}
        h = empreinte(secret)
        ecran = next((e for e in g.get("tv_ecrans") or [] if e.get("empreinte") == h), None)
        if not ecran:
            raise HTTPException(status_code=401, detail="Écran non appairé ou révoqué")
        return ecran

    async def _doc(ecran_id: str) -> Dict[str, Any]:
        d = await db.settings.find_one({"_id": PREFIXE + ecran_id}) or {"_id": PREFIXE + ecran_id}
        d.setdefault("seq", 0); d.setdefault("commande", None); d.setdefault("etat", None)       # l'état peut exister avant le premier ordre
        return d

    async def _media_video(media_id: str) -> Dict[str, Any]:
        m = await db.media_library.find_one({"id": media_id, "kind": "video", "is_deleted": {"$ne": True}}, {"_id": 0})
        if not m or not m.get("storage_path"):
            raise HTTPException(status_code=404, detail="Vidéo introuvable")
        return m

    def _url_flux(ecran_id: str, media_id: str) -> str:
        expire = int((_maintenant() + timedelta(hours=VALIDITE_ADRESSE_H)).timestamp())
        return f"/api/tv/video/flux/{media_id}?e={ecran_id}&x={expire}&s={signer(ecran_id, media_id, expire)}"

    # ------------------------------------------------------------------ côté télé
    @api.get("/tv/video/commande", tags=["Écran TV — Vidéo"])
    async def tv_commande(seq: int = Query(0), x_tv_secret: str = Header(default="")):
        """Interrogée toutes les 2 s par la page de la télé : rend l'ordre le plus récent s'il est plus récent que `seq`."""
        ecran = await _ecran_de_la_tele(x_tv_secret)
        if not (ecran.get("modules") or {}).get("video"):
            raise HTTPException(status_code=403, detail="Le contenu « Vidéos » n'est pas activé pour cet écran")
        d = await _doc(ecran["id"])
        if d["seq"] <= seq or not d.get("commande"):
            return {"seq": d["seq"], "commande": None}
        c = dict(d["commande"])
        if c.get("action") == "lire" and c.get("video_id"):
            c["url"] = _url_flux(ecran["id"], c["video_id"])
        return {"seq": d["seq"], "commande": c}

    @api.post("/tv/video/etat", tags=["Écran TV — Vidéo"])
    async def tv_etat(corps: Dict[str, Any] = Body(...), x_tv_secret: str = Header(default="")):
        """La télé renvoie ce qu'elle lit (position, durée) : la télécommande l'affiche."""
        ecran = await _ecran_de_la_tele(x_tv_secret)
        etat = {"lecture": str(corps.get("lecture") or "arret")[:12], "video_id": str(corps.get("video_id") or "")[:60],
                "position": max(0.0, float(corps.get("position") or 0)), "duree": max(0.0, float(corps.get("duree") or 0)),
                "erreur": str(corps.get("erreur") or "")[:160], "maj": _maintenant().isoformat()}
        await db.settings.update_one({"_id": PREFIXE + ecran["id"]}, {"$set": {"etat": etat}}, upsert=True)
        return {"ok": True}

    @api.get("/tv/video/flux/{media_id}", tags=["Écran TV — Vidéo"])
    async def tv_flux(media_id: str, request: Request, e: str = Query(...), x: int = Query(...), s: str = Query(...)):
        """Streaming de la vidéo, avec « Range » (avance rapide, reprise). L'adresse est signée : liée à l'écran et à la vidéo, valable 6 h."""
        if not signature_valide(e, media_id, x, s):
            raise HTTPException(status_code=403, detail="Adresse expirée ou invalide")
        m = await _media_video(media_id)
        taille = int(m.get("size") or 0)
        if taille <= 0:
            raise HTTPException(status_code=404, detail="Vidéo vide")
        try:
            plage = lire_en_tete_range(request.headers.get("range"), taille)
        except ValueError:
            return StreamingResponse(iter(()), status_code=416, headers={"Content-Range": f"bytes */{taille}"})
        debut, fin = plage if plage else (0, taille - 1)
        entetes = {"Accept-Ranges": "bytes", "Content-Length": str(fin - debut + 1), "Cache-Control": "private, max-age=0"}
        if plage:
            entetes["Content-Range"] = f"bytes {debut}-{fin}/{taille}"
        return StreamingResponse(_ouvrir_plage(m["storage_path"], debut, fin), status_code=206 if plage else 200,
                                 media_type=m.get("content_type") or "video/mp4", headers=entetes)

    # ------------------------------------------------------------------ côté administrateur (télécommande)
    @api.get("/admin/tv/video/ecrans", tags=["Admin — Vidéo TV"])
    async def admin_ecrans(user: dict = Depends(get_current_admin)):
        """Écrans appairés qui ont le contenu « Vidéos », avec leur état (en ligne ? que lisent-ils ?)."""
        g = await db.settings.find_one({"_id": "global"}, {"tv_ecrans": 1}) or {}
        limite = (_maintenant() - timedelta(seconds=EN_LIGNE_S)).isoformat()
        sortie = []
        for e in g.get("tv_ecrans") or []:
            if not (e.get("modules") or {}).get("video"):
                continue
            d = await _doc(e["id"])
            etat = d.get("etat") or {}
            sortie.append({"id": e["id"], "nom": e.get("nom") or "Écran", "client_nom": e.get("client_nom") or "",
                           "en_ligne": bool(etat.get("maj") and etat["maj"] >= limite) or bool(e.get("vu_le") and e["vu_le"] >= limite), "etat": etat or None, "seq": d["seq"]})
        return {"ecrans": sortie}

    @api.get("/admin/tv/video/videos", tags=["Admin — Vidéo TV"])
    async def admin_videos(user: dict = Depends(get_current_admin)):
        """Vidéos de la bibliothèque de médias (celles qu'on peut envoyer sur la télé)."""
        cur = db.media_library.find({"kind": "video", "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "title": 1, "size": 1, "content_type": 1, "filename": 1, "created_at": 1}).sort("created_at", -1).limit(200)
        return {"videos": await cur.to_list(length=200)}

    @api.get("/admin/tv/video/etat/{ecran_id}", tags=["Admin — Vidéo TV"])
    async def admin_etat(ecran_id: str, user: dict = Depends(get_current_admin)):
        d = await _doc(ecran_id)
        return {"seq": d["seq"], "commande": d.get("commande"), "etat": d.get("etat")}

    @api.post("/admin/tv/video/commande", tags=["Admin — Vidéo TV"])
    async def admin_commande(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Envoie un ordre à la télé : lire (vidéo), pause, reprendre, avancer / reculer (delta en secondes), position (secondes), stop."""
        ecran_id = str(corps.get("ecran_id") or "")
        action = str(corps.get("action") or "")
        if action not in ACTIONS:
            raise HTTPException(status_code=422, detail="Action inconnue")
        g = await db.settings.find_one({"_id": "global"}, {"tv_ecrans": 1}) or {}
        ecran = next((e for e in g.get("tv_ecrans") or [] if e.get("id") == ecran_id), None)
        if not ecran:
            raise HTTPException(status_code=404, detail="Écran introuvable")
        if not (ecran.get("modules") or {}).get("video"):
            raise HTTPException(status_code=409, detail="Cochez d'abord le contenu « Vidéos » pour cet écran (Paramètres → Écrans TV)")
        ordre: Dict[str, Any] = {"action": action, "par": user.get("email") or "", "le": _maintenant().isoformat()}
        if action == "lire":
            m = await _media_video(str(corps.get("video_id") or ""))
            ordre.update({"video_id": m["id"], "titre": m.get("title") or m.get("filename") or "Vidéo"})
        elif action in ("avancer", "reculer"):
            ordre["delta"] = max(1, min(int(corps.get("delta") or 10), DELTA_MAX_S))
        elif action == "position":
            ordre["position"] = max(0.0, float(corps.get("position") or 0))
        r = await db.settings.find_one_and_update({"_id": PREFIXE + ecran_id}, {"$inc": {"seq": 1}, "$set": {"commande": ordre}}, upsert=True, return_document=ReturnDocument.AFTER)
        return {"ok": True, "seq": (r or {}).get("seq", 1)}
