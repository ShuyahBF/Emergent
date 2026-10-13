# ekol_enrolement.py — Lot 137 : ENRÔLEMENT D'UNE ÉCOLE e-Kol EN UN GESTE (SAWALI pilote, le portail obéit).
#
# Demande du propriétaire (13/10/2026) : « 10 écoles nouvelles à enrôler chaque mois, c'est très fastidieux : que SAWALI,
# qui pilote toutes ces plateformes, factorise et réalise ces manœuvres ».
#
# En résumé (pour un développeur WinDev) :
#   AVANT : créer la clé de l'école dans SAWALI, noter son code, aller dans le portail e-Kol → Paramètres → Écoles pour
#           saisir le MÊME code, cocher les tables, saisir la clé sur le poste de l'école… (trois outils, un code à recopier).
#   MAINTENANT : une fiche « code + nom + ville » dans SAWALI → Paramètres → « 🎓 Portail e-Kol » fait, d'un coup :
#     1. la CLÉ de l'école (application eKol, liste de tables COMMUNE réglée une fois pour toutes dans Synchro) ;
#     2. l'ÉCOLE dans le portail, avec le même code, par un appel SIGNÉ (EKOL_PORTAIL_HMAC) → plus de code à recopier ;
#     3. le SUIVI école par école : clé créée, clé utilisée, poste vu, premier envoi reçu, école enregistrée au portail,
#        premier import réussi ; la première étape non faite est montrée en clair.
#   Reste manuel (sur place) : saisir la clé sur le poste de l'école (lien « Clé client Loois » ou « Loois.exe /ekol -msc »).
#
# Configuration : EKOL_PORTAIL_HMAC (clé partagée, déjà en place) et EKOL_PORTAIL_URL (adresse du backend du portail ;
# par défaut https://ekol-portail-backend.onrender.com). Jamais de secret dans le code ni dans les réponses.
#
# Routes (administrateur seulement) :
#   POST /api/admin/ekol-enrolement                  {code, nom, ville?} → clé (UNE fois), fiche, résultat côté portail
#   POST /api/admin/ekol-enrolement/{code}/portail   (re)enregistre l'école dans le portail (si le portail était injoignable)
#   GET  /api/admin/ekol-enrolement                  écoles enrôlées + checklist d'avancement (état du portail inclus)
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import Depends, HTTPException, Request

from routes import loois_cles_clients as cles
from routes.loois_synchro import code_site

logger = logging.getLogger("sawali.ekol_enrolement")

APPLICATION = "eKol"
URL_PORTAIL_DEFAUT = "https://ekol-portail-backend.onrender.com"
DELAI_PORTAIL_S = 12                    # un portail lent ne doit jamais bloquer la page des Paramètres
MAX_ECOLES = 2000

# Transport HTTP de remplacement (tests) : None en production
_transport: Optional[httpx.AsyncBaseTransport] = None


def cle_partagee() -> str:
    return os.environ.get("EKOL_PORTAIL_HMAC", "").strip()


def url_portail() -> str:
    return (os.environ.get("EKOL_PORTAIL_URL") or URL_PORTAIL_DEFAUT).strip().rstrip("/")


def signer(cle: str, horodatage: str, corps: bytes) -> str:
    """HMAC-SHA256 hexadécimal de « <horodatage>.<corps brut> » (même calcul que le portail)."""
    return hmac.new(cle.encode(), horodatage.encode() + b"." + corps, hashlib.sha256).hexdigest()


async def appeler_portail(chemin: str, corps: Dict[str, Any]) -> Tuple[bool, Any]:
    """POST signé vers le portail. Renvoie (ok, réponse JSON ou message d'erreur en français). Ne lève jamais."""
    cle = cle_partagee()
    if not cle:
        return False, "EKOL_PORTAIL_HMAC n'est pas saisie sur SAWALI (Render → sawali-backend → Environment)."
    brut = json.dumps(corps, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    try:
        async with httpx.AsyncClient(timeout=DELAI_PORTAIL_S, transport=_transport) as client:
            r = await client.post(url_portail() + chemin, content=brut, headers={
                "X-Timestamp": ts, "X-Signature": signer(cle, ts, brut), "Content-Type": "application/json"})
    except Exception as exc:  # noqa: BLE001 — portail injoignable, lent, adresse fausse…
        return False, f"Portail injoignable : {str(exc)[:120] or type(exc).__name__}."
    if r.status_code == 401:
        return False, "Le portail refuse la signature : EKOL_PORTAIL_HMAC doit être la même valeur des deux côtés."
    if r.status_code == 503:
        return False, "EKOL_PORTAIL_HMAC n'est pas saisie sur le portail e-Kol."
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        return False, f"Le portail a répondu {r.status_code}" + (f" : {detail}" if isinstance(detail, str) else ".")
    try:
        return True, r.json()
    except Exception:  # noqa: BLE001
        return False, "Réponse illisible du portail."


def etapes(code: str, cle: Optional[Dict[str, Any]], poste_vu: Optional[str], tables_recues: int,
           portail: Optional[Tuple[bool, Any]]) -> List[Dict[str, Any]]:
    """Checklist d'avancement d'une école (fonction pure, testée). Chaque étape : cle, libelle, fait, detail.
    `portail` = (ok, réponse de /import-ekol/ecole/etat ou message d'erreur) ou None (non interrogé)."""
    etat_portail = portail[1] if portail and portail[0] and isinstance(portail[1], dict) else {}
    liste = [
        {"cle": "cle", "libelle": "Clé de l'école créée", "fait": bool(cle and cle.get("actif")),
         "detail": "" if cle and cle.get("actif") else ("clé révoquée : la réactiver ou la régénérer" if cle else "aucune clé : refaire l'enrôlement")},
        {"cle": "cle_utilisee", "libelle": "Clé saisie sur le poste de l'école", "fait": bool(cle and cle.get("derniere_utilisation")),
         "detail": "" if cle and cle.get("derniere_utilisation") else "saisir la clé sur le poste : lien « Clé client Loois » ou Loois.exe /ekol -msc"},
        {"cle": "poste", "libelle": "Poste de l'école vu par SAWALI", "fait": bool(poste_vu),
         "detail": "" if poste_vu else "l'icône Loois doit tourner sur un poste de l'école (Loois.exe /zone)"},
        {"cle": "envoi", "libelle": "Premier envoi de données reçu", "fait": tables_recues > 0,
         "detail": f"{tables_recues} table(s) reçue(s)" if tables_recues else "aucune table reçue : voir le journal de Loois sur le poste"},
        {"cle": "portail", "libelle": "École enregistrée dans le portail", "fait": bool(etat_portail.get("enregistree")),
         "detail": "" if etat_portail.get("enregistree") else (portail[1] if portail and not portail[0] else "pas encore enregistrée : bouton « Réessayer »")},
        {"cle": "import", "libelle": "Premier import au portail réussi", "fait": bool(etat_portail.get("lignes")),
         "detail": (f"{etat_portail.get('lignes')} ligne(s) importée(s)" if etat_portail.get("lignes")
                    else (etat_portail.get("erreur") or "en attente (l'import se fait toutes les 10 minutes)"))},
    ]
    return liste


def prochaine_action(liste: List[Dict[str, Any]]) -> Optional[str]:
    """Première étape non faite (texte clair), ou None si tout est fait."""
    for e in liste:
        if not e["fait"]:
            return f"{e['libelle']} : {e['detail']}" if e["detail"] else e["libelle"]
    return None


def setup_ekol_enrolement_routes(*, db, api, get_current_user) -> None:
    """Branche les routes d'enrôlement sur le routeur /api de SAWALI."""

    def admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    async def enregistrer_au_portail(enr: Dict[str, Any]) -> Tuple[bool, Any]:
        ok, rep = await appeler_portail("/api/import-ekol/ecole", {"site": enr["code"], "nom": enr["nom"], "ville": enr.get("ville")})
        await db.ekol_enrolements.update_one(
            {"code": enr["code"]}, {"$set": {"portail_ok": bool(ok), "portail_message": "" if ok else str(rep),
                                             "portail_le": datetime.now(timezone.utc).isoformat()}})
        return ok, rep

    @api.post("/admin/ekol-enrolement", tags=["Portail e-Kol"])
    async def enroler(request: Request, user: dict = Depends(get_current_user)):
        """Enrôle une école : clé + école du portail. La clé en clair n'est renvoyée QU'UNE FOIS (à la création)."""
        admin(user)
        try:
            corps = await request.json()
            code = code_site(corps.get("code") or corps.get("nom"))
            nom = str(corps.get("nom") or "").strip()[:120]
            ville = str(corps.get("ville") or "").strip()[:80] or None
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        if len(code) < 2 or len(nom) < 2:
            raise HTTPException(status_code=422, detail="Code du site et nom de l'école (2 caractères au moins) obligatoires")
        if await db.ekol_enrolements.count_documents({}) >= MAX_ECOLES:
            raise HTTPException(status_code=429, detail="trop d'écoles enrôlées")
        # 1. Clé de l'école (une clé par école ; si elle existe déjà, elle n'est ni changée ni réaffichée)
        existante = await db.loois_cles_clients.find_one({"code": code}, {"_id": 0, "id": 1, "actif": 1})
        cle_claire = None
        if not existante:
            try:
                propre = cles.nettoyer_fiche({"code": code, "libelle": nom, "applications": [APPLICATION]}, creation=True)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            cle_claire, _ = await cles.creer_fiche_cle(db, propre, cles_auteur(user))
        elif APPLICATION not in ((await db.loois_cles_clients.find_one({"code": code}, {"_id": 0, "applications": 1})) or {}).get("applications", [APPLICATION]):
            await db.loois_cles_clients.update_one({"code": code}, {"$addToSet": {"applications": APPLICATION}})
        # 2. Fiche d'enrôlement (suivi) puis école du portail
        await db.ekol_enrolements.update_one(
            {"code": code}, {"$set": {"code": code, "nom": nom, "ville": ville},
                             "$setOnInsert": {"cree_le": datetime.now(timezone.utc).isoformat(), "cree_par": cles_auteur(user)}}, upsert=True)
        enr = await db.ekol_enrolements.find_one({"code": code}, {"_id": 0})
        ok, rep = await enregistrer_au_portail(enr)
        return {"ok": True, "code": code, "cle": cle_claire, "cle_deja_existante": bool(existante),
                "portail": {"ok": bool(ok), "message": "École enregistrée dans le portail." if ok else str(rep)}}

    @api.post("/admin/ekol-enrolement/{code}/portail", tags=["Portail e-Kol"])
    async def reessayer_portail(code: str, user: dict = Depends(get_current_user)):
        """(Re)enregistre l'école dans le portail (portail injoignable ou clé partagée corrigée entre-temps)."""
        admin(user)
        enr = await db.ekol_enrolements.find_one({"code": code_site(code)}, {"_id": 0})
        if not enr:
            raise HTTPException(status_code=404, detail="École non enrôlée")
        ok, rep = await enregistrer_au_portail(enr)
        return {"ok": bool(ok), "message": "École enregistrée dans le portail." if ok else str(rep)}

    @api.get("/admin/ekol-enrolement", tags=["Portail e-Kol"])
    async def suivi(user: dict = Depends(get_current_user)):
        """Écoles enrôlées avec leur checklist d'avancement (l'état du portail est lu en parallèle, 12 s au plus)."""
        admin(user)
        liste = [e async for e in db.ekol_enrolements.find({}, {"_id": 0}).sort("cree_le", -1).limit(MAX_ECOLES)]

        async def une(e: Dict[str, Any]) -> Dict[str, Any]:
            code = e["code"]
            cle = await db.loois_cles_clients.find_one({"code": code}, {"_id": 0, "actif": 1, "derniere_utilisation": 1, "prefixe": 1})
            poste = await db.loois_synchro_postes.find_one({"application": APPLICATION, "site": code}, {"_id": 0, "vu_le": 1, "machine": 1})
            recues = await db.loois_synchro_tables.count_documents({"application": APPLICATION, "site": code, "nb_documents": {"$gt": 0}})
            portail = await appeler_portail("/api/import-ekol/ecole/etat", {"site": code})
            steps = etapes(code, cle, (poste or {}).get("vu_le"), recues, portail)
            return {**e, "etapes": steps, "prochaine_action": prochaine_action(steps), "complete": all(s["fait"] for s in steps),
                    "poste": (poste or {}).get("machine")}

        return {"cle_partagee": bool(cle_partagee()), "ecoles": list(await asyncio.gather(*(une(e) for e in liste)))}


def cles_auteur(user: dict) -> str:
    return user.get("full_name") or user.get("email") or "admin"
