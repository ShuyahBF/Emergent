"""Lot 321 — Suivi du RDV par le patient : QR code affiché sur l'écran du hall → page téléphone « /suivi-rdv ».

Le patient s'identifie avec son NUMÉRO DE TÉLÉPHONE et 2 LETTRES de ses initiales (1re lettre du nom + 1re lettre du prénom, dans un sens
ou dans l'autre). Le suivi n'est ouvert que sur une DEMI-JOURNÉE autour de SON rendez-vous : de 3 h avant à 3 h après l'heure prévue,
matin ou soir selon l'heure du RDV. La page ne montre QUE son propre rendez-vous (médecin, heure, porte, nombre de personnes avant lui) :
jamais le nom ni le téléphone d'un autre patient.
Protection : réponse unique « aucun rendez-vous trouvé » (on ne révèle jamais pourquoi), limites d'essais par adresse IP et par numéro.
Le service est ÉTEINT par défaut : Paramètres → Écrans TV → « Suivi du RDV par le patient ».
"""
from __future__ import annotations

import io
import logging
import os
import re
import time
import unicodedata
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Set
from urllib.parse import urlparse

from fastapi import Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response

logger = logging.getLogger("sawali.suivi_rdv")

AVANT_H, APRES_H = 3, 3                      # fenêtre d'accès : 3 h avant et 3 h max après l'heure du RDV
ESSAIS_ECHEC_MAX, ESSAIS_FENETRE_S = 8, 600  # 8 échecs en 10 minutes (par IP, et par numéro) → blocage temporaire
REQUETES_MAX_MIN = 30                        # 30 requêtes par minute et par IP (la page se rafraîchit toutes les 20 s)
AUCUN_RDV = "Aucun rendez-vous trouvé avec ces informations (le suivi est ouvert de 3 h avant à 3 h après l'heure de votre rendez-vous)."
ANNULES = ("cancelled", "annule", "annulé")

_echecs: Dict[str, Deque[float]] = defaultdict(deque)       # clé « ip:… » ou « tel:… » → instants des échecs récents
_requetes: Dict[str, Deque[float]] = defaultdict(deque)     # ip → instants des requêtes de la dernière minute


# ---------------- Fonctions pures (testées) ----------------
def _sans_accent(t: Any) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "")) if unicodedata.category(c) != "Mn")


def chiffres8(tel: Any) -> str:
    """8 derniers chiffres d'un numéro (« +226 70 00 11 22 » → « 70001122 ») ; vide si moins de 6 chiffres."""
    d = re.sub(r"\D", "", str(tel or ""))
    return d[-8:] if len(d) >= 6 else ""


def initiales_possibles(patient: Any) -> Set[str]:
    """Initiales acceptées pour un patient enregistré « NOM Prénoms : téléphone : reçu » : première lettre du 1er et du 2e mot,
    dans les deux sens (nom-prénom ou prénom-nom). Un patient à un seul mot : ses deux premières lettres."""
    nom = str(patient or "").split(":")[0]
    mots = [m for m in re.split(r"[\s\-'’.]+", _sans_accent(nom).upper()) if m and m.isalpha()]
    if len(mots) >= 2:
        a, b = mots[0][0], mots[1][0]
        return {a + b, b + a}
    if len(mots) == 1 and len(mots[0]) >= 2:
        return {mots[0][:2]}
    return set()


def normaliser_initiales(saisie: Any) -> str:
    """« o.a » → « OA » ; vide si ce ne sont pas exactement 2 lettres."""
    lettres = re.sub(r"[^A-Z]", "", _sans_accent(saisie).upper())
    return lettres if len(lettres) == 2 else ""


def dans_la_fenetre(debut: datetime, maintenant: datetime) -> bool:
    """Vrai de 3 h avant à 3 h après l'heure du rendez-vous."""
    return debut - timedelta(hours=AVANT_H) <= maintenant <= debut + timedelta(hours=APRES_H)


def _dt(iso: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def personnes_devant(cible: Dict[str, Any], memes_medecin: List[Dict[str, Any]], maintenant: datetime) -> int:
    """Nombre de patients avec RDV qui passent avant lui chez le même médecin.
    Le médecin utilise Avancer / Reculer → on compte ceux placés avant lui qui ne sont pas « fait » ; sinon ceux dont l'heure n'est pas encore atteinte."""
    utilise = any(d.get("etat_consult") for d in memes_medecin)
    n = 0
    for d in memes_medecin:
        if d is cible or d.get("id") == cible.get("id"):
            continue
        s, c = _dt(d.get("start_at")), _dt(cible.get("start_at"))
        if not s or not c or s >= c:
            continue
        if (d.get("etat_consult") != "fait") if utilise else (s >= maintenant):
            n += 1
    return n


def message_patient(etat: str, devant: int, heure: str, medecin: str, porte: str) -> str:
    """Phrase affichée au patient."""
    lieu = f" — {porte}" if porte else ""
    if etat == "en_cours":
        return "C'est à vous : votre consultation est en cours."
    if etat == "fait":
        return "Votre consultation est terminée. Merci de votre visite."
    base = "Vous êtes le prochain." if devant == 0 else (f"Il y a 1 personne avant vous." if devant == 1 else f"Il y a {devant} personnes avant vous.")
    return f"{base} Votre rendez-vous : {heure} avec {medecin}{lieu}."


def base_autorisee(base: str) -> Optional[str]:
    """Adresse du site pour le QR : https sur sawalismartsystems.com (ou le site déclaré par PUBLIC_BASE_URL) ; sinon None."""
    try:
        u = urlparse(str(base or ""))
    except ValueError:
        return None
    hote = (u.hostname or "").lower()
    env = urlparse(os.environ.get("PUBLIC_BASE_URL") or "").hostname or ""
    ok = hote == "sawalismartsystems.com" or hote.endswith(".sawalismartsystems.com") or (env and hote == env.lower())
    return f"https://{u.netloc}" if ok and u.scheme in ("https", "http") and hote else None


def png_qr(texte: str) -> bytes:
    import qrcode
    qr = qrcode.QRCode(version=None, box_size=10, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(texte)
    qr.make(fit=True)
    tampon = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(tampon, format="PNG")
    return tampon.getvalue()


def _purger(file: Deque[float], fenetre: float, maintenant: float) -> None:
    while file and maintenant - file[0] > fenetre:
        file.popleft()


def _ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "") or "?").split(",")[0].strip()


def setup_suivi_rdv_routes(*, db, api, get_current_admin):
    async def _actif() -> bool:
        s = await db.settings.find_one({"_id": "global"}, {"suivi_rdv": 1}) or {}
        return bool((s.get("suivi_rdv") or {}).get("actif"))

    @api.get("/suivi-rdv/info", tags=["Suivi RDV patient"])
    async def suivi_info():
        """Le service est-il ouvert ? (la page affiche le formulaire ou un message)"""
        return {"actif": await _actif()}

    @api.post("/suivi-rdv/etat", tags=["Suivi RDV patient"])
    async def suivi_etat(request: Request, corps: Dict[str, Any] = Body(...)):
        """Téléphone + 2 lettres d'initiales → l'état de SON rendez-vous (dans la fenêtre de 3 h avant / 3 h après) ou 404 uniforme."""
        if not await _actif():
            raise HTTPException(status_code=403, detail="Ce service n'est pas disponible pour le moment.")
        t = time.monotonic()
        ip = _ip(request)
        _purger(_requetes[ip], 60, t)
        _requetes[ip].append(t)
        tel, ini = chiffres8(corps.get("telephone")), normaliser_initiales(corps.get("initiales"))
        cles = [f"ip:{ip}"] + ([f"tel:{tel}"] if tel else [])
        for c in cles:
            _purger(_echecs[c], ESSAIS_FENETRE_S, t)
        if len(_requetes[ip]) > REQUETES_MAX_MIN or any(len(_echecs[c]) >= ESSAIS_ECHEC_MAX for c in cles):
            raise HTTPException(status_code=429, detail="Trop d'essais : réessayez dans quelques minutes.")

        async def refuser():
            for c in cles:
                _echecs[c].append(t)
            raise HTTPException(status_code=404, detail=AUCUN_RDV)

        if not tel or not ini:
            await refuser()
        maintenant = datetime.now(timezone.utc)
        bas, haut = (maintenant - timedelta(hours=APRES_H)).isoformat(), (maintenant + timedelta(hours=AVANT_H)).isoformat()
        docs = await db.planning_appointments.find(
            {"start_at": {"$gte": bas, "$lte": haut}, "is_rdv": {"$ne": 0}},
            {"_id": 0, "id": 1, "medecin": 1, "start_at": 1, "status": 1, "patient": 1, "patient_phone": 1, "etat_consult": 1}).to_list(3000)
        docs = [d for d in docs if str(d.get("status") or "").lower() not in ANNULES]
        trouves = [d for d in docs if chiffres8(d.get("patient_phone")) == tel and ini in initiales_possibles(d.get("patient"))]
        if not trouves:
            await refuser()
        cible = min(trouves, key=lambda d: abs((_dt(d["start_at"]) - maintenant).total_seconds()))
        debut = _dt(cible["start_at"])
        if not dans_la_fenetre(debut, maintenant):
            await refuser()
        medecin = str(cible.get("medecin") or "").strip() or "—"
        memes = [d for d in docs if str(d.get("medecin") or "").strip() == medecin]
        devant = personnes_devant(cible, memes, maintenant)
        etat = "en_cours" if cible.get("etat_consult") == "en_cours" else ("fait" if cible.get("etat_consult") == "fait" else "attente")
        s = await db.settings.find_one({"_id": "global"}, {"tv_portes": 1}) or {}
        porte = next((str(p.get("porte") or "") for p in (s.get("tv_portes") or []) if str(p.get("medecin") or "").lower() == medecin.lower()), "")
        heure = debut.strftime("%H:%M")
        return {"medecin": medecin, "porte": porte, "heure": heure, "debut": debut.isoformat(), "etat": etat, "devant": devant,
                "message": message_patient(etat, devant, heure, medecin, porte), "maintenant": maintenant.isoformat(),
                "valide_jusqua": (debut + timedelta(hours=APRES_H)).isoformat()}

    @api.get("/suivi-rdv/qr.png", tags=["Suivi RDV patient"])
    async def suivi_qr(base: str = Query("", max_length=200)):
        """QR code (PNG) qui ouvre la page de suivi ; l'adresse du site doit être celle de SAWALI (jamais un site quelconque)."""
        site = base_autorisee(base)
        if not site:
            raise HTTPException(status_code=400, detail="Adresse de site non autorisée")
        return Response(content=png_qr(f"{site}/suivi-rdv"), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

    @api.get("/admin/suivi-rdv", tags=["Admin — Suivi RDV patient"])
    async def admin_suivi_lire(user: dict = Depends(get_current_admin)):
        return {"actif": await _actif(), "avant_h": AVANT_H, "apres_h": APRES_H}

    @api.put("/admin/suivi-rdv", tags=["Admin — Suivi RDV patient"])
    async def admin_suivi_ecrire(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        actif = bool(corps.get("actif"))
        await db.settings.update_one({"_id": "global"}, {"$set": {"suivi_rdv": {"actif": actif}}}, upsert=True)
        return {"actif": actif}
