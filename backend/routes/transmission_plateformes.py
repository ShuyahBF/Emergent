# transmission_plateformes.py — Lot 361 : transmettre un formulaire ou un sondage à une ou plusieurs PLATEFORMES (ALBARKA, e-Kol…).
#
# Les plateformes sont listées comme destinataires (en plus des contacts). Le document est envoyé par un POST SIGNÉ (même signature
# que le reste des échanges avec les plateformes : X-Timestamp + X-Signature = HMAC-SHA256(secret de l'émetteur, "<ts>.<corps>"))
# à l'adresse « url_formulaires » de l'émetteur : il « tombe » dans l'espace Formulaires / Sondages de la plateforme.
#
# Lot 368 — RETOUR DES RÉPONSES : la plateforme renvoie à SAWALI les réponses reçues à un document qu'elle a reçu
# (POST signé /api/webhook/plateforme-reponse-formulaire). Elles sont rangées dans la COPIE conservée par SAWALI (réponses du formulaire ou
# du sondage), marquées du nom de la plateforme (« ALBARKA ») : badge et filtre dans le tableau des réponses. Idempotent (même réponse = jamais
# de doublon) ; seule une plateforme à qui le document a été transmis peut y déposer des réponses.
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
from fastapi import APIRouter, Depends, HTTPException, Request
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


REPONSE_OCTETS_MAX = 100_000             # taille du JSON de réponses acceptée (une réponse plus grosse est refusée, jamais tronquée)


def _valeur_sure(v: Any) -> Any:
    """Valeur d'une réponse réduite à du texte, des nombres, des booléens ou des listes de ces valeurs (fonction pure)."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return [_valeur_sure(x) for x in v[:100] if not isinstance(x, (dict, list))]
    return str(v)[:500]


async def recevoir_reponse(db, emetteur: Dict[str, Any], corps: Dict[str, Any]) -> Dict[str, Any]:
    """Range UNE réponse venue d'une plateforme dans la copie du formulaire / sondage. Lève HTTPException (422 / 403) si refusée.
    Renvoie {ok, deja}."""
    type_doc = str(corps.get("type") or "formulaire")
    id_doc = str(corps.get("id_sawali") or "").strip()
    rep_id = str(corps.get("reponse_id") or "").strip()[:80]
    data = corps.get("data")
    if type_doc not in TYPES or not id_doc or not rep_id or not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="type, id_sawali, reponse_id et data (objet) requis")
    if len(json.dumps(data, ensure_ascii=False, default=str).encode()) > REPONSE_OCTETS_MAX:
        raise HTTPException(status_code=422, detail="réponse trop volumineuse")
    collection = TYPES[type_doc][0]
    doc = await db[collection].find_one({"id": id_doc}, {"_id": 0, "id": 1, "client_id": 1, "transmissions": 1})
    if not doc:
        raise HTTPException(status_code=422, detail="document inconnu")
    code = emetteur["code"]
    if not any(x.get("plateforme") == code and x.get("ok") for x in doc.get("transmissions") or []):
        raise HTTPException(status_code=403, detail="ce document n'a pas été transmis à cette plateforme")
    propre = {str(k)[:80]: _valeur_sure(v) for k, v in list(data.items())[:300]}
    nom_plateforme = emetteur.get("nom") or code.upper()
    ident = f"plat-{code}-{rep_id}"
    rep = corps.get("repondant") if isinstance(corps.get("repondant"), dict) else {}
    nom = str(rep.get("nom") or "").strip()[:120] or None
    email = str(rep.get("email") or "").strip()[:160] or None
    maintenant = _now()
    marque = {"via": "plateforme", "plateforme": code, "plateforme_nom": nom_plateforme}
    if type_doc == "formulaire":
        # user_id propre à la réponse : contourne l'index unique (form_id, user_id) et sert d'identifiant d'idempotence
        if await db.form_submissions.find_one({"form_id": id_doc, "user_id": ident}, {"_id": 1}):
            return {"ok": True, "deja": True}
        await db.form_submissions.insert_one({
            "id": ident, "form_id": id_doc, "client_id": doc.get("client_id"), "user_id": ident,
            "user_label": nom or email or nom_plateforme, "data": propre, "geo": None, "respondent_email": email,
            "anonymous": False, "created_at": str(corps.get("recu_le") or maintenant), "updated_at": maintenant, "revisions_count": 1, **marque})
        await db.forms.update_one({"id": id_doc}, {"$inc": {"uses_count": 1}})
    else:
        if await db.wa_survey_responses.find_one({"id": ident}, {"_id": 1}):
            return {"ok": True, "deja": True}
        await db.wa_survey_responses.insert_one({
            "id": ident, "survey_id": id_doc, "invite_id": None, "contact_id": None, "answers": propre,
            "created_at": str(corps.get("recu_le") or maintenant), "updated_at": maintenant, "revisions": 0, **marque})
    return {"ok": True, "deja": False}


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

    @router.post("/webhook/plateforme-reponse-formulaire", tags=["Plateformes — retour des réponses"])
    async def reponse_de_plateforme(request: Request):
        """Réponse à un formulaire / sondage transmis, renvoyée par la plateforme (POST signé X-Emetteur / X-Timestamp / X-Signature)."""
        from routes.contrats_plateformes import signature_valide
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) if code else None
        if not emetteur or not emetteur.get("actif", True):
            raise HTTPException(status_code=401, detail="Émetteur inconnu ou désactivé")
        brut = await request.body()
        if not signature_valide(emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", brut,
                                request.headers.get("X-Signature") or "", datetime.now(timezone.utc)):
            raise HTTPException(status_code=401, detail="Signature refusée")
        try:
            corps = json.loads(brut.decode("utf-8") or "{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="Corps JSON illisible")
        if not isinstance(corps, dict):
            raise HTTPException(status_code=400, detail="Corps JSON attendu")
        return await recevoir_reponse(db, emetteur, corps)

    @router.get("/me/transmissions/{type_doc}/{doc_id}")
    async def historique(type_doc: str, doc_id: str, user: dict = Depends(get_current_user)):
        """Historique des transmissions de ce document (les plus récentes d'abord)."""
        doc = await _document(type_doc, doc_id, user)
        return {"transmissions": list(reversed(doc.get("transmissions") or []))}

    return router
