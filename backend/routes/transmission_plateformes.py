# transmission_plateformes.py — Lot 361 : transmettre un formulaire ou un sondage à une ou plusieurs PLATEFORMES (ALBARKA, e-Kol…).
#
# Les plateformes sont listées comme destinataires (en plus des contacts). Le document est envoyé par un POST SIGNÉ (même signature
# que le reste des échanges avec les plateformes : X-Timestamp + X-Signature = HMAC-SHA256(secret de l'émetteur, "<ts>.<corps>"))
# à l'adresse « url_formulaires » de l'émetteur : il « tombe » dans l'espace Formulaires / Sondages de la plateforme.
#
# Une COPIE reste dans SAWALI (le document n'est jamais déplacé) avec l'HISTORIQUE DES TRANSMISSIONS (champ `transmissions` du document :
# plateforme, date, résultat, auteur). Chaque transmission est aussi inscrite au journal `liluvine_transmissions` (mode « formulaire » /
# « sondage », ligne de la plateforme) : elle est ainsi comptée dans « Autres travaux IA » de l'impression des envois par ligne
# (routes/alertes_plateformes.py). Aucune nouvelle collection MongoDB (cluster plein).
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.transmission_plateformes")

# type de document → (collection, libellé)
TYPES: Dict[str, tuple] = {"formulaire": ("forms", "Formulaire"), "sondage": ("wa_surveys", "Sondage")}
TAILLE_MAX = 500_000                      # octets de JSON au plus (un document plus gros est refusé, jamais tronqué)
CHAMPS_INTERNES = {"_id", "client_id", "tenant_id", "owner_id", "created_by_id", "transmissions", "access_client_ids"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def corps_transmis(type_doc: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Contenu envoyé à la plateforme (fonction pure) : le document SANS ses champs internes de SAWALI."""
    contenu = {k: v for k, v in (doc or {}).items() if k not in CHAMPS_INTERNES}
    return {"type": type_doc, "id_sawali": doc.get("id"), "titre": doc.get("title") or doc.get("name") or "",
            "transmis_le": _now(), "source": "SAWALI", "document": contenu}


def signer(secret: bytes, brut: str, ts: str) -> str:
    """Signature HMAC-SHA256 de « <ts>.<corps> » (fonction pure)."""
    return hmac.new(secret, f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()


async def poster(emetteur: Dict[str, Any], corps: Dict[str, Any]) -> Dict[str, Any]:
    """POST signé vers l'espace Formulaires de la plateforme ; un nouvel essai en cas d'erreur réseau / 5xx. Renvoie {ok, http, erreur}."""
    url = (emetteur.get("url_formulaires") or "").strip()
    secret = (emetteur.get("secret") or "").encode()
    if not url:
        return {"ok": False, "http": None, "erreur": "cette plateforme n'a pas d'adresse de réception des formulaires"}
    if not secret:
        return {"ok": False, "http": None, "erreur": "clé de la plateforme absente"}
    brut = json.dumps(corps, ensure_ascii=False, default=str)
    if len(brut.encode()) > TAILLE_MAX:
        return {"ok": False, "http": None, "erreur": "document trop volumineux pour être transmis"}
    derniere = "injoignable"
    http_code = None
    for essai in range(2):
        ts = str(int(time.time()))
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.post(url, content=brut.encode(), headers={
                    "Content-Type": "application/json", "X-Emetteur": "sawali", "X-Timestamp": ts, "X-Signature": signer(secret, brut, ts)})
            http_code = r.status_code
            if r.status_code < 300:
                return {"ok": True, "http": r.status_code, "erreur": None}
            derniere = f"refusé par la plateforme (HTTP {r.status_code})"
            if r.status_code < 500:
                break                              # refus définitif (signature, route absente…) : pas de nouvel essai
        except Exception as exc:  # noqa: BLE001
            derniere = f"plateforme injoignable ({exc.__class__.__name__})"
        if essai == 0:
            import asyncio
            await asyncio.sleep(2)
    return {"ok": False, "http": http_code, "erreur": derniere}


async def transmettre(db, type_doc: str, doc: Dict[str, Any], emetteur: Dict[str, Any], par: str) -> Dict[str, Any]:
    """Transmet UN document à UNE plateforme, puis inscrit le résultat à l'historique du document et au journal (comptage par ligne)."""
    collection = TYPES[type_doc][0]
    res = await poster(emetteur, corps_transmis(type_doc, doc))
    ligne = str(emetteur.get("ligne") or "").strip() or None          # ligne WhatsApp dédiée de la plateforme (Phone Number ID)
    entree = {"plateforme": emetteur.get("code"), "nom": emetteur.get("nom"), "le": _now(), "ok": res["ok"], "erreur": res["erreur"],
              "http": res["http"], "par": par}
    await db[collection].update_one({"id": doc["id"]}, {"$push": {"transmissions": {"$each": [entree], "$slice": -200}}})
    try:
        await db.liluvine_transmissions.insert_one({
            "date": entree["le"], "emetteur": emetteur.get("code"), "source": f"{TYPES[type_doc][1]} « {doc.get('title') or ''} »"[:120],
            "id_externe": doc["id"], "to": None, "mode": type_doc, "ok": res["ok"], "erreur": res["erreur"], "longueur": 0, "ligne": ligne})
    except Exception:  # noqa: BLE001 — le journal ne bloque jamais la transmission
        logger.warning("[transmission_plateformes] journal indisponible", exc_info=True)
    return entree


class Demande(BaseModel):
    plateformes: List[str] = Field(min_length=1, max_length=20)      # codes des émetteurs


def make_router(*, db, get_current_user, is_admin_like):
    router = APIRouter(tags=["Transmission aux plateformes (lot 361)"])

    async def _document(type_doc: str, doc_id: str, user: dict) -> Dict[str, Any]:
        if type_doc not in TYPES:
            raise HTTPException(status_code=404, detail="Type inconnu (formulaire ou sondage)")
        doc = await db[TYPES[type_doc][0]].find_one({"id": doc_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail=f"{TYPES[type_doc][1]} introuvable")
        if not is_admin_like(user) and doc.get("client_id") not in {user.get("client_id"), user["id"]}:
            raise HTTPException(status_code=403, detail="Seul le propriétaire du document peut le transmettre")
        return doc

    @router.get("/me/transmissions/plateformes")
    async def plateformes(user: dict = Depends(get_current_user)):
        """Plateformes proposées comme destinataires (en plus des contacts) : actives, avec ou sans adresse de réception."""
        if not is_admin_like(user):                 # les plateformes sont gérées par SAWALI : liste réservée à l'Admin / Superviseur
            return {"plateformes": []}
        lignes = await db.liluvine_emetteurs.find({"actif": True}, {"_id": 0, "code": 1, "nom": 1, "url_formulaires": 1}).to_list(100)
        return {"plateformes": [{"code": e["code"], "nom": e.get("nom") or e["code"], "recoit_formulaires": bool(e.get("url_formulaires"))}
                                for e in lignes]}

    @router.post("/me/transmissions/{type_doc}/{doc_id}")
    async def envoyer(type_doc: str, doc_id: str, demande: Demande, user: dict = Depends(get_current_user)):
        """Transmet le document aux plateformes choisies ; une copie reste dans SAWALI avec l'historique."""
        if not is_admin_like(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur et au superviseur")
        doc = await _document(type_doc, doc_id, user)
        resultats = []
        for code in dict.fromkeys(demande.plateformes):
            emetteur = await db.liluvine_emetteurs.find_one({"code": code, "actif": True}, {"_id": 0})
            if not emetteur:
                resultats.append({"plateforme": code, "ok": False, "erreur": "plateforme inconnue ou désactivée"})
                continue
            resultats.append(await transmettre(db, type_doc, doc, emetteur, user.get("email") or user["id"]))
        return {"ok": all(r["ok"] for r in resultats), "resultats": resultats}

    @router.get("/me/transmissions/{type_doc}/{doc_id}")
    async def historique(type_doc: str, doc_id: str, user: dict = Depends(get_current_user)):
        """Historique des transmissions de ce document (les plus récentes d'abord)."""
        doc = await _document(type_doc, doc_id, user)
        return {"transmissions": list(reversed(doc.get("transmissions") or []))}

    return router
