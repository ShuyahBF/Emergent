"""Lot 57.5 — « Transmission WA Universelle Liluvine », protocole v3 (côté SAWALI).

Ce module regroupe tout ce qui complète l'envoi (routes/liluvine_send_webhook.py) :

1. FICHIERS (médias et documents envoyés par les plateformes)
   - récupération du fichier (lien HTTPS ou contenu base64, 10 Mo maximum) ;
   - stockage temporaire (7 jours) dans la collection `liluvine_fichiers` ;
   - lien public à jeton GET /api/liluvine/fichier/{jeton} : WhatsApp vient y
     chercher le média, et il sert de lien de téléchargement de secours.

2. RETOURS vers la plateforme émettrice (« URL de retour » de chaque émetteur),
   signés avec la clé de la plateforme (en-têtes X-Emetteur: sawali,
   X-Timestamp, X-Signature) :
   - « statut »         : envoyé / remis / lu / échec d'un message transmis ;
   - « reponse »        : le client a répondu à un message de la plateforme ;
   - « desinscription » : le client a répondu STOP.

3. DÉSINSCRIPTION : STOP / ARRET -> plus aucun envoi de CETTE plateforme vers ce
   numéro (409) ; REPRENDRE -> réinscription.

4. ALERTE e-mail à l'administrateur en cas de série d'échecs ou de signatures
   refusées pour un émetteur (au plus une alerte par heure et par émetteur).

5. ASSISTANT DE LA PLATEFORME (lot 102, ZandGo d'abord) : quand un client écrit à SAWALI dans les 72 h
   qui suivent un message d'une plateforme dotée d'une « adresse de l'assistant », Liluvine pose la
   question à la plateforme (appel signé avec sa clé) et renvoie SA réponse au client : statut d'une
   commande, fiche d'un produit… Si la plateforme ne répond pas, Liluvine reprend la main comme avant.
   Lot 103 : à TOUT moment, un message qui commence par « ! » suivi du code de la plateforme (« !zandgo où est
   ma commande ? », « !ZandGo prix montre », casse indifférente) est posé à son assistant ; les messages suivants du même numéro
   y vont aussi pendant 30 min (session) ; « FIN » rend la main à Liluvine.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from fastapi.responses import Response

logger = logging.getLogger("sawali.liluvine_relais")

TAILLE_MAX = 10 * 1024 * 1024        # 10 Mo par fichier
DUREE_FICHIER = timedelta(days=7)     # durée de vie d'un fichier transmis
FENETRE_REPONSE = timedelta(hours=72) # une réponse est relayée si le message transmis a moins de 72 h
SEUIL_ALERTE = 5                      # échecs ou signatures refusées…
FENETRE_ALERTE = timedelta(minutes=15)  # …dans cette fenêtre -> e-mail à l'administrateur
MOTS_STOP = {"stop", "arret", "arrêt", "desinscrire", "désinscrire", "unsubscribe"}
MOTS_REPRENDRE = {"reprendre", "start"}
# Lot 103 : conversation ouverte avec l'assistant d'une plateforme par son mot-clé (« ZandGo … »)
DUREE_SESSION_ASSISTANT = timedelta(minutes=30)
MOTS_FIN_ASSISTANT = {"fin", "terminer", "terminé", "quitter"}
TYPES_MEDIA = {"document", "image", "video", "audio"}


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Fichiers
# ---------------------------------------------------------------------------
def _adresse_publique_interdite(hote: str) -> bool:
    """Protection SSRF : refuse les adresses internes (localhost, réseaux privés…)."""
    try:
        for info in socket.getaddrinfo(hote, 443):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return True
    except Exception:  # noqa: BLE001 — hôte introuvable : refusé aussi
        return True
    return False


async def recuperer_media(media: Dict[str, Any]) -> Tuple[bytes, str, str]:
    """Octets, type MIME et nom du fichier d'un « media » du protocole v3 (lève HTTPException 422)."""
    type_media = (media.get("type") or "").strip()
    if type_media not in TYPES_MEDIA:
        raise HTTPException(status_code=422, detail="media.type invalide (document, image, video ou audio)")
    url = (media.get("url") or "").strip()
    contenu = media.get("contenu_base64")
    if bool(url) == bool(contenu):
        raise HTTPException(status_code=422, detail="media : indiquer soit « url », soit « contenu_base64 »")
    nom = (media.get("nom_fichier") or "").strip()[:120] or f"fichier.{ {'image': 'jpg', 'video': 'mp4', 'audio': 'ogg'}.get(type_media, 'pdf') }"
    mime = (media.get("mime") or "").strip()[:100]
    if contenu:
        try:
            octets = base64.b64decode(contenu, validate=True)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="media.contenu_base64 illisible")
    else:
        lien = urlparse(url)
        if lien.scheme != "https" or not lien.hostname or _adresse_publique_interdite(lien.hostname):
            raise HTTPException(status_code=422, detail="media.url refusée (HTTPS public obligatoire)")
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
                async with http.stream("GET", url) as r:
                    if r.status_code != 200:
                        raise HTTPException(status_code=422, detail=f"media.url injoignable (HTTP {r.status_code})")
                    morceaux, total = [], 0
                    async for bloc in r.aiter_bytes():
                        total += len(bloc)
                        if total > TAILLE_MAX:
                            raise HTTPException(status_code=422, detail="Fichier trop volumineux (10 Mo au plus)")
                        morceaux.append(bloc)
                    octets = b"".join(morceaux)
                    mime = mime or (r.headers.get("content-type") or "").split(";")[0].strip()
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"media.url injoignable ({str(exc)[:80]})")
    if not octets:
        raise HTTPException(status_code=422, detail="Fichier vide")
    if len(octets) > TAILLE_MAX:
        raise HTTPException(status_code=422, detail="Fichier trop volumineux (10 Mo au plus)")
    return octets, mime or "application/octet-stream", nom


_INDEX_CREE = False


async def stocker_fichier(db, octets: bytes, mime: str, nom: str, emetteur: str) -> str:
    """Garde le fichier 7 jours et renvoie son jeton (lien public non devinable)."""
    global _INDEX_CREE
    if not _INDEX_CREE:
        # Index d'expiration : MongoDB supprime seul les fichiers après « expire_le »
        try:
            await db.liluvine_fichiers.create_index("expire_le", expireAfterSeconds=0)
            await db.liluvine_fichiers.create_index("jeton", unique=True)
        except Exception:  # noqa: BLE001
            pass
        _INDEX_CREE = True
    jeton = secrets.token_urlsafe(24)
    await db.liluvine_fichiers.insert_one({
        "jeton": jeton, "contenu": octets, "mime": mime, "nom": nom, "emetteur": emetteur,
        "taille": len(octets), "cree_le": _maintenant().isoformat(),
        "expire_le": _maintenant() + DUREE_FICHIER,
    })
    return jeton


async def url_publique(db) -> str:
    """Adresse publique du serveur SAWALI (Paramètres, sinon variables d'environnement)."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "public_base_url": 1}) or {}
    base = (s.get("public_base_url") or os.environ.get("PUBLIC_BASE_URL") or os.environ.get("BACKEND_PUBLIC_URL")
            or os.environ.get("REACT_APP_BACKEND_URL") or "").strip().rstrip("/")
    return base


async def lien_fichier(db, jeton: str) -> str:
    return f"{await url_publique(db)}/api/liluvine/fichier/{jeton}"


def attach_liluvine_fichiers_route(*, api, db):
    """Route publique de téléchargement d'un fichier transmis (jeton, 7 jours)."""

    @api.get("/liluvine/fichier/{jeton}", tags=["Liluvine — Webhook"])
    async def telecharger(jeton: str):
        doc = await db.liluvine_fichiers.find_one({"jeton": jeton})
        expire = (doc or {}).get("expire_le")
        if expire is not None and expire.tzinfo is None:
            expire = expire.replace(tzinfo=timezone.utc)
        if not doc or (expire and expire < _maintenant()):
            raise HTTPException(status_code=404, detail="Fichier introuvable ou expiré")
        nom = (doc.get("nom") or "fichier").replace('"', "")
        return Response(content=bytes(doc["contenu"]), media_type=doc.get("mime") or "application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="{nom}"', "Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------------------
# 2. Retours signés vers la plateforme émettrice
# ---------------------------------------------------------------------------
async def _poster_retour(db, emetteur: Dict[str, Any], corps: Dict[str, Any]) -> bool:
    """POST signé vers l'URL de retour de l'émetteur ; un nouvel essai en cas d'échec réseau / 5xx."""
    url = (emetteur.get("url_retour") or "").strip()
    cle = (emetteur.get("secret") or "").encode()
    if not url or not cle:
        return False
    brut = json.dumps(corps, ensure_ascii=False)
    for essai in range(2):
        ts = str(int(time.time()))
        signature = hmac.new(cle, f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.post(url, content=brut.encode(), headers={
                    "Content-Type": "application/json", "X-Emetteur": "sawali",
                    "X-Timestamp": ts, "X-Signature": signature})
            if r.status_code < 300:
                await db.liluvine_emetteurs.update_one({"code": emetteur["code"]},
                                                       {"$set": {"dernier_retour_ok": _maintenant().isoformat()}})
                return True
            if r.status_code < 500:
                break  # refus définitif (signature, route absente…) : pas de nouvel essai
        except Exception:  # noqa: BLE001
            pass
        if essai == 0:
            await asyncio.sleep(2)
    await db.liluvine_emetteurs.update_one({"code": emetteur["code"]}, {"$set": {
        "dernier_retour_echec": _maintenant().isoformat(), "dernier_retour_type": corps.get("type")}})
    await noter_incident(db, emetteur["code"], "retour_refuse")
    return False


def envoyer_retour(db, emetteur: Dict[str, Any], corps: Dict[str, Any]) -> None:
    """Envoi du retour en tâche de fond : ne ralentit jamais le webhook Meta."""
    if not (emetteur or {}).get("url_retour"):
        return
    try:
        asyncio.get_running_loop().create_task(_poster_retour(db, emetteur, corps))
    except RuntimeError:  # pas de boucle (tests synchrones) : on ignore
        pass


async def mettre_a_jour_statut(db, message_id: str, statut: str, erreur: Optional[str] = None) -> None:
    """Statut WhatsApp (sent/delivered/read/failed) d'un message transmis -> journal + retour."""
    if not message_id:
        return
    trans = await db.liluvine_transmissions.find_one({"message_id": message_id}, {"_id": 0})
    if not trans:
        return
    await db.liluvine_transmissions.update_one({"message_id": message_id}, {"$set": {
        "statut": statut, "statut_le": _maintenant().isoformat(), **({"erreur_remise": erreur} if erreur else {})}})
    if statut == "failed":
        await noter_incident(db, trans.get("emetteur") or "liluvine", "remise_echouee")
    emetteur = await db.liluvine_emetteurs.find_one({"code": trans.get("emetteur")}, {"_id": 0})
    if emetteur:
        envoyer_retour(db, emetteur, {"type": "statut", "id": trans.get("id_externe"), "message_id": message_id,
                                      "statut": statut, "erreur": erreur, "date": _maintenant().isoformat()})


# ---------------------------------------------------------------------------
# 5. Assistant de la plateforme (lot 102)
# ---------------------------------------------------------------------------
async def interroger_assistant(db, emetteur: Dict[str, Any], numero: str, texte: str) -> Optional[Dict[str, Any]]:
    """Pose la question du client à l'assistant de la plateforme (POST signé, 12 s au plus).
    Renvoie la réponse JSON ({"reponse": …, "intention": …}) ou None si la plateforme ne répond pas."""
    url = (emetteur.get("url_assistant") or "").strip()
    cle = (emetteur.get("secret") or "").encode()
    if not url or not cle:
        return None
    brut = json.dumps({"telephone": numero, "texte": texte[:500]}, ensure_ascii=False)
    ts = str(int(time.time()))
    signature = hmac.new(cle, f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=12) as http:
            r = await http.post(url, content=brut.encode(), headers={
                "Content-Type": "application/json", "X-Emetteur": "sawali", "X-Timestamp": ts, "X-Signature": signature})
        if r.status_code < 300:
            donnees = r.json()
            if isinstance(donnees, dict) and str(donnees.get("reponse") or "").strip():
                return donnees
    except Exception:  # noqa: BLE001
        logger.warning("[liluvine_relais] assistant %s injoignable", emetteur.get("code"), exc_info=True)
    await noter_incident(db, emetteur.get("code") or "?", "assistant_injoignable")
    return None


# ---------------------------------------------------------------------------
# 3. Messages entrants : réponses relayées, STOP / REPRENDRE
# ---------------------------------------------------------------------------
def _chiffres(numero: str) -> str:
    return "".join(c for c in (numero or "") if c.isdigit())


async def est_desinscrit(db, emetteur: str, numero: str) -> bool:
    return bool(await db.liluvine_desinscriptions.find_one(
        {"emetteur": emetteur, "numero": _chiffres(numero), "actif": True}))


def _sans_accents(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def detecter_mot_cle(texte: str, emetteurs: list) -> Optional[Tuple[Dict[str, Any], str]]:
    """Lot 103 : (émetteur, question sans la commande) si le message commence par « ! » suivi du code ou du nom
    d'une plateforme dotée d'un assistant (« !zandgo … », « !ZandGo: … », quelle que soit la casse), sinon None."""
    brut = (texte or "").strip()
    if not brut.startswith("!"):
        return None                           # demande du propriétaire (10/10/2026) : commande « ! » obligatoire
    brut = brut[1:].lstrip()
    bas = _sans_accents(brut.lower())
    decale = 0
    for e in emetteurs:
        for mot in {(e.get("code") or "").lower(), _sans_accents((e.get("nom") or "").lower())}:
            mot = mot.strip()
            if len(mot) < 3 or not bas.startswith(mot):
                continue
            suite = bas[len(mot):]
            if suite and suite[0].isalnum():
                continue                      # « zandgoo » ou « zandgomania » : pas le mot-clé
            question = brut[decale + len(mot):].lstrip(" :,-–—!?.").strip()
            return e, question
    return None


async def _repondre_par_assistant(db, emetteur: Dict[str, Any], de: str, chiffres: str, question: str,
                                  send_text) -> Optional[Dict[str, Any]]:
    """Pose la question à l'assistant, envoie sa réponse au client, journalise ; None si pas de réponse."""
    code = emetteur.get("code")
    rep = await interroger_assistant(db, emetteur, chiffres, question)
    if not rep:
        return None
    envoi = await send_text(de, str(rep["reponse"])[:3800])
    await db.liluvine_assistant_journal.insert_one({
        "emetteur": code, "numero": chiffres, "question": question[:500], "intention": rep.get("intention"),
        "envoye": bool((envoi or {}).get("ok")) if isinstance(envoi, dict) else True, "date": _maintenant().isoformat()})
    return {"traite": True, "action": "reponse_assistant", "emetteur": code, "nom": emetteur.get("nom") or code,
            "reponse": str(rep["reponse"])[:3800],
            "message_id": (envoi or {}).get("message_id") if isinstance(envoi, dict) else None}


async def _session_assistant(db, de: str, chiffres: str, texte: str, send_text) -> Optional[Dict[str, Any]]:
    """Lot 103 : mot-clé d'une plateforme, ou session ouverte avec son assistant (30 min). None = pas concerné."""
    emetteurs = [e async for e in db.liluvine_emetteurs.find(
        {"url_assistant": {"$nin": [None, ""]}, "actif": {"$ne": False}}, {"_id": 0})]
    if not emetteurs:
        return None
    maintenant = _maintenant()
    trouve = detecter_mot_cle(texte, emetteurs)
    if trouve:
        emetteur, question = trouve
    else:
        session = await db.liluvine_assistant_sessions.find_one(
            {"numero": chiffres, "jusqu_a": {"$gt": maintenant.isoformat()}}, {"_id": 0})
        emetteur = next((e for e in emetteurs if session and e["code"] == session["emetteur"]), None)
        if not emetteur:
            return None
        question = texte.strip()
        nom = emetteur.get("nom") or emetteur["code"]
        # « FIN » : la conversation avec la plateforme s'arrête, Liluvine reprend la main
        if _sans_accents(question.lower()).rstrip(".!") in MOTS_FIN_ASSISTANT:
            await db.liluvine_assistant_sessions.delete_one({"numero": chiffres})
            await send_text(de, f"✅ Conversation avec {nom} terminée. Écrivez « !{emetteur['code']} » suivi de votre question pour la reprendre.")
            return {"traite": True, "action": "fin_assistant", "emetteur": emetteur["code"]}
    resultat = await _repondre_par_assistant(db, emetteur, de, chiffres, question or "aide", send_text)
    if resultat:
        await db.liluvine_assistant_sessions.update_one({"numero": chiffres}, {"$set": {
            "emetteur": emetteur["code"], "jusqu_a": (maintenant + DUREE_SESSION_ASSISTANT).isoformat(),
            "maj_le": maintenant.isoformat()}}, upsert=True)
    return resultat


async def traiter_message_entrant(db, *, de: str, type_message: str, texte: Optional[str],
                                  fichier_local: Optional[str] = None, mime: Optional[str] = None,
                                  nom_fichier: Optional[str] = None, cite_message_id: Optional[str] = None,
                                  send_text=None) -> Dict[str, Any]:
    """Appelée pour chaque message WhatsApp reçu par SAWALI.

    Renvoie {"traite": True, ...} quand le message concerne une plateforme émettrice
    (réponse relayée, STOP, REPRENDRE) : Liluvine ne répond alors pas elle-même.
    """
    chiffres = _chiffres(de)
    if not chiffres:
        return {"traite": False}
    # Lot 103 : mot-clé d'une plateforme (« ZandGo … ») ou session ouverte avec son assistant
    if type_message == "text" and (texte or "").strip() and send_text \
            and (texte or "").strip().lower().rstrip(".!") not in (MOTS_STOP | MOTS_REPRENDRE):
        par_mot_cle = await _session_assistant(db, de, chiffres, texte, send_text)
        if par_mot_cle:
            return par_mot_cle
    # Dernière transmission vers ce numéro (ou celle citée par le client)
    trans = None
    if cite_message_id:
        trans = await db.liluvine_transmissions.find_one({"message_id": cite_message_id, "ok": True}, {"_id": 0})
    if not trans:
        limite = (_maintenant() - FENETRE_REPONSE).isoformat()
        trans = await db.liluvine_transmissions.find_one(
            {"to": {"$regex": chiffres + "$"}, "ok": True, "emetteur": {"$ne": "liluvine"}, "date": {"$gte": limite}},
            {"_id": 0}, sort=[("date", -1)])
        # Un message plus récent de SAWALI elle-même vers ce numéro : la conversation lui appartient
        if trans and not cite_message_id:
            plus_recent = await db.whatsapp_messages.find_one(
                {"direction": "outbound", "created_at": {"$gt": trans["date"]},
                 "assistant_plateforme": {"$exists": False},          # lot 102 : réponses de l'assistant exclues
                 "$or": [{"phone_digits": chiffres}, {"to": {"$regex": chiffres + "$"}}]},
                {"_id": 1})
            if plus_recent:
                return {"traite": False}
    if not trans:
        return {"traite": False}
    code = trans.get("emetteur")
    emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) or {}
    nom = emetteur.get("nom") or code
    mot = (texte or "").strip().lower().rstrip(".!")

    # STOP : désinscription de CETTE plateforme
    if type_message == "text" and mot in MOTS_STOP:
        await db.liluvine_desinscriptions.update_one(
            {"emetteur": code, "numero": chiffres},
            {"$set": {"actif": True, "date": _maintenant().isoformat()}}, upsert=True)
        if send_text:
            await send_text(de, f"✅ Vous ne recevrez plus de messages de {nom} par ce numéro. "
                                f"Pour vous réinscrire, répondez REPRENDRE.")
        envoyer_retour(db, emetteur, {"type": "desinscription", "de": "+" + chiffres, "date": _maintenant().isoformat()})
        return {"traite": True, "action": "desinscription", "emetteur": code}

    # REPRENDRE : réinscription
    if type_message == "text" and mot in MOTS_REPRENDRE:
        r = await db.liluvine_desinscriptions.update_one({"emetteur": code, "numero": chiffres, "actif": True},
                                                         {"$set": {"actif": False, "reprise_le": _maintenant().isoformat()}})
        if r.modified_count and send_text:
            await send_text(de, f"✅ C'est noté : vous recevrez de nouveau les messages de {nom}.")
        return {"traite": bool(r.modified_count), "action": "reinscription", "emetteur": code}

    # Lot 102 — assistant de la plateforme : la question du client (texte) lui est posée et SA réponse
    # est renvoyée au client (ZandGo : statut des commandes de CE numéro, fiches produits…).
    if (type_message == "text" and (texte or "").strip() and emetteur.get("url_assistant")
            and emetteur.get("actif", True) is not False and send_text):
        resultat = await _repondre_par_assistant(db, emetteur, de, chiffres, texte.strip(), send_text)
        if resultat:
            return resultat

    # Lot 83 (08/10/2026) — « tous mes autres messages à ce numéro sont lus aussi par ALBARKA » :
    # seule une RÉPONSE CITÉE (« Répondre » sur le message de la plateforme) est relayée. Un message
    # libre reste à SAWALI, même peu après une transmission (STOP / REPRENDRE restent reconnus ci-dessus).
    if not cite_message_id or trans.get("message_id") != cite_message_id:
        return {"traite": False}
    # Lot 84 — réglage « Réponses des clients : non transmises » : la réponse reste à SAWALI (étiquetée),
    # rien n'est envoyé à la plateforme, et Liluvine ne répond pas à sa place.
    if emetteur.get("reponses_transmises") is False:
        return {"traite": True, "action": "reponse_non_transmise", "emetteur": code, "nom": nom}
    # Réponse du client : relayée à la plateforme (si elle a une URL de retour)
    if not emetteur.get("url_retour"):
        return {"traite": False}
    media = None
    if fichier_local and os.path.exists(fichier_local):
        try:
            with open(fichier_local, "rb") as f:
                octets = f.read()
            if len(octets) <= TAILLE_MAX:
                jeton = await stocker_fichier(db, octets, mime or "application/octet-stream",
                                              nom_fichier or os.path.basename(fichier_local), code)
                media = {"type": type_message, "url_temporaire": await lien_fichier(db, jeton),
                         "mime": mime, "nom_fichier": nom_fichier or os.path.basename(fichier_local)}
        except Exception:  # noqa: BLE001
            logger.warning("[liluvine_relais] média de la réponse non relayé", exc_info=True)
    corps = {"type": "reponse", "id_origine": trans.get("id_externe"), "de": "+" + chiffres,
             "texte": texte or "", "media": media, "date": _maintenant().isoformat()}
    await db.liluvine_reponses.insert_one({**corps, "emetteur": code, "relaye_le": _maintenant().isoformat()})
    envoyer_retour(db, emetteur, corps)
    return {"traite": True, "action": "reponse_relayee", "emetteur": code, "nom": nom}


# ---------------------------------------------------------------------------
# 4. Alerte e-mail sur série d'incidents
# ---------------------------------------------------------------------------
async def noter_incident(db, emetteur: str, motif: str) -> None:
    """Note un incident (signature refusée, envoi ou remise en échec, retour refusé) ;
    au-delà du seuil dans la fenêtre, e-mail à l'administrateur (1 fois par heure au plus)."""
    try:
        maintenant = _maintenant()
        await db.liluvine_incidents.insert_one({"emetteur": emetteur, "motif": motif, "date": maintenant.isoformat()})
        nb = await db.liluvine_incidents.count_documents(
            {"emetteur": emetteur, "date": {"$gte": (maintenant - FENETRE_ALERTE).isoformat()}})
        if nb < SEUIL_ALERTE:
            return
        cle = f"alerte:{emetteur}"
        deja = await db.liluvine_alertes.find_one({"_id": cle})
        if deja and deja.get("date", "") >= (maintenant - timedelta(hours=1)).isoformat():
            return
        await db.liluvine_alertes.update_one({"_id": cle}, {"$set": {"date": maintenant.isoformat()}}, upsert=True)
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_transmission_email_alerte": 1, "admin_email": 1}) or {}
        destinataire = (s.get("liluvine_transmission_email_alerte") or s.get("admin_email")
                        or os.environ.get("SUPER_ADMIN_EMAIL") or "").strip()
        if not destinataire:
            return
        motifs = {}
        async for i in db.liluvine_incidents.find(
                {"emetteur": emetteur, "date": {"$gte": (maintenant - FENETRE_ALERTE).isoformat()}}, {"_id": 0, "motif": 1}):
            motifs[i["motif"]] = motifs.get(i["motif"], 0) + 1
        detail = "".join(f"<li>{m} : {n}</li>" for m, n in motifs.items())
        from email_service import send_email
        await send_email(
            destinataire, f"⚠️ Transmission WA Universelle : incidents pour « {emetteur} »",
            f"<p>{nb} incidents en 15 minutes pour l'émetteur <b>{emetteur}</b> :</p><ul>{detail}</ul>"
            f"<p>Vérifier la clé (LILUVINE_WA_HMAC), l'URL de retour et le journal dans "
            f"SAWALI → Paramètres → Transmission WA Universelle.</p>",
            f"{nb} incidents en 15 minutes pour l'émetteur {emetteur}.")
    except Exception:  # noqa: BLE001 — une alerte ne bloque jamais rien
        logger.warning("[liluvine_relais] alerte impossible", exc_info=True)


__all__ = ["recuperer_media", "stocker_fichier", "lien_fichier", "url_publique", "attach_liluvine_fichiers_route",
           "envoyer_retour", "mettre_a_jour_statut", "traiter_message_entrant", "est_desinscrit", "noter_incident",
           "TAILLE_MAX"]
