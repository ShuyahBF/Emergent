"""Lot 39 — Stock des produits par client/dépôt et vérification des ordonnances.

Stock (collection `stock_produits`, module `stock_produits`) :
  GET  /api/stock-produits/depots          dépôts du client connecté (PHL : PPH et PLB)
  GET  /api/stock-produits?depot=&q=       produits du client connecté (filtrés par SON code client)
  POST /api/stock-produits/sync            envoi quotidien du service Loois (jeton X-Sync-Token,
                                           variable STOCK_SYNC_TOKEN) — upsert par code client + dépôt

Ordonnances (collection `ordonnances_stock`) — le pharmacien photographie une ordonnance :
  POST /api/ordonnances-stock              photos (ou PDF) → lecture IA des lignes prescrites,
                                           rapprochement avec le stock du client, disponibilité
  GET  /api/ordonnances-stock              ordonnances du client (les plus récentes d'abord)
  GET  /api/ordonnances-stock/{id}         détail, disponibilités recalculées à chaque lecture
  PUT  /api/ordonnances-stock/{id}/lignes/{n}              choix du produit / quantité (le pharmacien décide)
  POST /api/ordonnances-stock/{id}/lignes/{n}/equivalents  équivalents VIDAL (même DCI + dosage,
                                                           regroupement VMP) présents dans le stock
  POST /api/ordonnances-stock/{id}/reserver                réserve les quantités disponibles
  POST /api/ordonnances-stock/{id}/reservations/{rid}/{vendue|annuler}
  DELETE /api/ordonnances-stock/{id}       supprime l'ordonnance (réservations actives annulées)

Confidentialité : la photo n'est PAS conservée, et la lecture IA ne renvoie ni le
nom du patient ni celui du prescripteur (seules les lignes de médicaments).
Disponible = stock (salle + magasin) − réservations actives non expirées.
Accès : fonction « Ordonnances et stock » (clé `ordonnances_stock`) activée pour le
client dans SMART Communications ; Admin et Superviseur y ont toujours accès.
Lot 54 — rôle « Auxiliaire en Pharmacie » : scan + OCR uniquement (POST /ordonnances-stock),
historique de SES ordonnances scannées (GET /ordonnances-stock, GET /ordonnances-stock/{id}),
sans stock, disponibilités ni réservations ; toutes les autres routes de ce module → 403.
"""
from __future__ import annotations

import asyncio
import difflib
import hmac
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Depends, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

import roles_restreints
import stock_produits as sp

logger = logging.getLogger("sawali.ordonnances_stock")

TAG = "Portail — Ordonnances et stock"
CLE_FONCTION = "ordonnances_stock"
MAX_PHOTOS = 4
MAX_OCTETS = 20 * 1024 * 1024
MAX_PRODUITS_SYNC = 20000
RESERVATION_HEURES = 48          # durée d'une réservation (réglage `ordonnance_reservation_heures`)
SEUIL_SUR = 0.72                 # score au-delà duquel le produit est retenu d'office…
MARGE_SUR = 0.08                 # …s'il devance nettement le 2e candidat

SYSTEM_PROMPT = """Tu es l'assistant de pharmacie de SAWALI SMART SYSTEMS. Tu lis la photo
d'une ORDONNANCE (souvent manuscrite) pour qu'un pharmacien vérifie la disponibilité
des médicaments dans son stock.

Réponds UNIQUEMENT avec un objet JSON strict, sans texte avant ou après ni bloc de code :
{
  "date_ordonnance": "<JJ/MM/AAAA si lisible, sinon null>",
  "lignes": [
    {"nom": "<nom commercial ou DCI tel qu'écrit, sans le dosage>",
     "dosage": "<dosage écrit (ex. « 1 g », « 500 mg », « 5 mg/ml »), ou null>",
     "forme": "<forme (comprimé, sirop, injectable, pommade…), ou null>",
     "quantite": <nombre de boîtes / unités à délivrer si écrit (ex. « QSP 1 mois » → null), sinon null>,
     "posologie": "<posologie recopiée, ou null>",
     "incertain": <true si écriture douteuse>,
     "note": "<explication si incertain, sinon null>"}
  ]
}

Règles :
- Une entrée par médicament ou dispositif prescrit, dans l'ordre de l'ordonnance.
- NE RECOPIE JAMAIS le nom, l'âge, l'adresse ou le téléphone du patient, ni le nom du prescripteur.
- Nom illisible : recopie ce que tu lis avec incertain=true ; n'invente pas de médicament.
"""

StatutFn = Callable[..., Awaitable[Any]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


# ---------------------------------------------------------------------------
# Rapprochement ligne prescrite → produit du stock
# ---------------------------------------------------------------------------
_DOSE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(MG|G|ML|UI|MCG|µG|%)")


def _doses(texte: str) -> set:
    """Dosages normalisés en mg quand c'est possible : « 1G » et « 1000MG » → {"1000MG"}."""
    out = set()
    for val, unite in _DOSE_RE.findall(sp.normaliser(texte).replace(" ", "")):
        v = float(val.replace(",", "."))
        if unite == "G":
            v, unite = v * 1000, "MG"
        if unite in ("MCG", "µG"):
            v, unite = v / 1000, "MG"
        out.add(f"{v:g}{unite}")
    return out


def _mots(texte: str) -> List[str]:
    return [m for m in re.split(r"[^A-Z0-9]+", sp.normaliser(texte)) if len(m) >= 3 and not m.isdigit()]


def rapprocher(ligne: dict, produits: List[dict]) -> Dict[str, Any]:
    """Candidats du stock pour une ligne lue sur l'ordonnance (les meilleurs d'abord) et
    produit retenu d'office s'il n'y a pas de doute. Un produit n'est candidat que s'il
    partage le PREMIER mot significatif du nom prescrit (nom commercial ou DCI)."""
    nom = str(ligne.get("nom") or "")
    mots = _mots(nom)
    if not mots:
        return {"candidats": [], "produit_id": None, "confiance": "aucun"}
    premier = mots[0]
    doses_lues = _doses(f"{nom} {ligne.get('dosage') or ''}")
    cible = sp.normaliser(f"{nom} {ligne.get('dosage') or ''}")
    scores = []
    for p in produits:
        mots_p = _mots(p.get("libelle"))
        if not any(m == premier or difflib.SequenceMatcher(None, m, premier).ratio() >= 0.85 for m in mots_p[:3]):
            continue
        s = difflib.SequenceMatcher(None, cible, p.get("libelle_norm") or sp.normaliser(p.get("libelle"))).ratio()
        doses_p = _doses(p.get("libelle") or "")
        if doses_lues and doses_p:
            s += 0.25 if doses_lues & doses_p else -0.25      # dosage identique / différent
        scores.append((round(s, 3), p))
    scores.sort(key=lambda t: -t[0])
    candidats = [{"produit_id": p["id"], "score": s} for s, p in scores[:5]]
    if not scores:
        return {"candidats": [], "produit_id": None, "confiance": "aucun"}
    meilleur = scores[0][0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    sur = meilleur >= SEUIL_SUR and meilleur - second >= MARGE_SUR
    if not doses_lues and len(scores) > 1:
        sur = False          # plusieurs présentations et aucun dosage lu : le pharmacien choisit
    return {"candidats": candidats, "produit_id": scores[0][1]["id"] if sur else None,
            "confiance": "sure" if sur else "a_confirmer"}


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------
class ProduitSync(BaseModel):
    code_produit: str = Field(..., min_length=1, max_length=64)
    libelle: str = Field(..., min_length=1, max_length=300)
    mesure: Optional[str] = None
    cip: Optional[str] = None
    prix_public: Optional[float] = None
    isalle: int = 0
    imagasin: int = 0
    peremption: Optional[str] = None


class StockSync(BaseModel):
    code_client: str = Field(..., min_length=2, max_length=16)
    code_depot: str = Field(..., min_length=2, max_length=16)
    complet: bool = False            # True : la liste envoyée est TOUT le stock du dépôt
    produits: List[ProduitSync] = Field(..., max_length=MAX_PRODUITS_SYNC)


class ChoixLigne(BaseModel):
    produit_id: Optional[str] = None     # None : aucun produit (ligne « non délivrée »)
    quantite: Optional[int] = Field(None, ge=1, le=1000)


def attach_ordonnances_stock_routes(*, api, db, get_current_user, fonction_active=None,
                                    vidal_rechercher: Optional[StatutFn] = None,
                                    vidal_equivalents: Optional[StatutFn] = None,
                                    lire_ordonnance: Optional[StatutFn] = None) -> Dict[str, Any]:
    """Branche les routes. `vidal_rechercher(user, q)` / `vidal_equivalents(user, vmp_id)` :
    fonctions du module VIDAL (routes/vidal_fiche.py) ; `lire_ordonnance(images) -> dict` :
    lecture IA (par défaut ocr_core, clé ANTHROPIC_API_KEY), remplaçable pour les tests."""

    # --- Accès ---------------------------------------------------------------------
    def _staff(user: dict) -> bool:
        return (user.get("role") or "") in ("admin", "superviseur")

    def _tenant_id(user: dict) -> str:
        for k in ("parent_client_id", "client_id"):
            if user.get(k) and user.get(k) != user.get("id"):
                return user[k]
        return user["id"]

    async def utilisateur(user: dict = Depends(get_current_user)) -> dict:
        if fonction_active is not None and not await fonction_active(user, CLE_FONCTION):
            raise HTTPException(status_code=403, detail="La fonction « Ordonnances et stock » n'est pas activée "
                                                        "pour votre compte. Demandez son activation à votre "
                                                        "administrateur SAWALI.")
        return user

    async def gestionnaire(user: dict = Depends(utilisateur)) -> dict:
        """Lot 54 — routes de stock et de réservation : refusées à l'Auxiliaire en Pharmacie."""
        if roles_restreints.est_auxiliaire(user):
            raise HTTPException(status_code=403, detail="Le rôle « Auxiliaire en Pharmacie » permet uniquement "
                                                        "de scanner des ordonnances et de lancer l'OCR.")
        return user

    def _vue_ocr(ordo: dict) -> dict:
        """Lot 54 — vue de l'Auxiliaire en Pharmacie : lecture OCR seule (ni stock, ni réservation)."""
        return {"id": ordo["id"], "code_client": ordo.get("code_client"), "cree_le": ordo.get("cree_le"),
                "date_ordonnance": ordo.get("date_ordonnance"), "ocr_seulement": True,
                "lignes": [{"index": i, **{k: l.get(k) for k in ("nom", "dosage", "forme", "quantite", "posologie",
                                                                 "incertain", "note")}}
                           for i, l in enumerate(ordo.get("lignes") or [])]}

    async def _code_client(user: dict, demande: Optional[str] = None) -> str:
        """Code du client dont on lit le stock : TOUJOURS celui du compte connecté ; seuls
        l'Admin et le Superviseur peuvent en choisir un autre."""
        if _staff(user) and demande:
            return demande.strip().upper()
        tenant = await db.users.find_one({"id": _tenant_id(user)}, {"_id": 0, "client_code": 1}) or {}
        code = (tenant.get("client_code") or "").strip().upper()
        if not code:
            raise HTTPException(status_code=400, detail="Aucun code client n'est associé à votre compte")
        return code

    async def _duree_reservation() -> int:
        s = await db.settings.find_one({"_id": "global"}, {"ordonnance_reservation_heures": 1}) or {}
        try:
            return max(1, int(s.get("ordonnance_reservation_heures") or RESERVATION_HEURES))
        except (TypeError, ValueError):
            return RESERVATION_HEURES

    async def _reserve(produit_ids: List[str], sauf_ordonnance: Optional[str] = None) -> Dict[str, int]:
        """Quantités réservées (actives, non expirées) par produit."""
        q: Dict[str, Any] = {"produit_id": {"$in": produit_ids}, "statut": "active", "expire_le": {"$gt": _iso(_now())}}
        if sauf_ordonnance:
            q["ordonnance_id"] = {"$ne": sauf_ordonnance}
        out: Dict[str, int] = {}
        for r in await db.stock_reservations.find(q, {"_id": 0}).to_list(5000):
            out[r["produit_id"]] = out.get(r["produit_id"], 0) + int(r["quantite"])
        return out

    # --- Stock ---------------------------------------------------------------------
    @api.get("/stock-produits/depots", tags=[TAG])
    async def depots(code_client: Optional[str] = None, user: dict = Depends(gestionnaire)):
        code = await _code_client(user, code_client)
        rows = await db.stock_produits.aggregate([
            {"$match": {"code_client": code}},
            {"$group": {"_id": "$code_depot", "produits": {"$sum": 1}, "maj_le": {"$max": "$maj_le"}}},
            {"$sort": {"_id": 1}},
        ]).to_list(50)
        return {"code_client": code, "depots": [{"code_depot": r["_id"], "produits": r["produits"],
                                                 "maj_le": r["maj_le"]} for r in rows]}

    @api.get("/stock-produits", tags=[TAG])
    async def lister_stock(depot: Optional[str] = None, q: Optional[str] = None, code_client: Optional[str] = None,
                           disponibles: bool = False, limit: int = Query(100, ge=1, le=1000),
                           user: dict = Depends(gestionnaire)):
        code = await _code_client(user, code_client)
        filtre: Dict[str, Any] = {"code_client": code}
        if depot:
            filtre["code_depot"] = depot.strip().upper()
        if q:
            filtre["libelle_norm"] = {"$regex": re.escape(sp.normaliser(q))}
        if disponibles:
            filtre["stock"] = {"$gt": 0}
        rows = await db.stock_produits.find(filtre, {"_id": 0}).sort("libelle_norm", 1).to_list(limit)
        reserve = await _reserve([r["id"] for r in rows])
        for r in rows:
            r["reserve"] = reserve.get(r["id"], 0)
            r["disponible"] = max(0, (r.get("stock") or 0) - r["reserve"])
            r["alerte_peremption"] = sp.alerte_peremption(r.get("peremption"))
        return {"code_client": code, "produits": rows}

    @api.post("/stock-produits/sync", tags=[TAG])
    async def synchroniser(payload: StockSync, x_sync_token: Optional[str] = Header(None)):
        """Envoi quotidien du service Loois : le stock HFSQL d'un dépôt d'un client.
        Authentification par jeton partagé (en-tête X-Sync-Token = STOCK_SYNC_TOKEN)."""
        attendu = (os.environ.get("STOCK_SYNC_TOKEN") or "").strip()
        if not attendu:
            raise HTTPException(status_code=503, detail="Synchronisation du stock non configurée (STOCK_SYNC_TOKEN)")
        if not x_sync_token or not hmac.compare_digest(x_sync_token.strip(), attendu):
            raise HTTPException(status_code=401, detail="Jeton de synchronisation invalide")
        code_client, code_depot = payload.code_client.strip().upper(), payload.code_depot.strip().upper()
        if payload.complet and not payload.produits:
            raise HTTPException(status_code=400, detail="Envoi complet sans aucun produit : refusé")
        maintenant = _iso(_now())
        lignes = [sp.document_produit(p.model_dump(), code_client=code_client, code_depot=code_depot,
                                      source="loois", maintenant=maintenant) for p in payload.produits]
        res = await sp.enregistrer(db, lignes)
        retires = 0
        if payload.complet:
            codes = [l["code_produit"] for l in lignes]
            r = await db.stock_produits.delete_many({"code_client": code_client, "code_depot": code_depot,
                                                     "code_produit": {"$nin": codes}})
            retires = r.deleted_count
        journal = {"id": str(uuid.uuid4()), "code_client": code_client, "code_depot": code_depot,
                   "produits": len(lignes), "retires": retires, "complet": payload.complet,
                   "supabase": res["supabase"]["etat"], "le": maintenant}
        await db.stock_sync_journal.insert_one(dict(journal))
        return journal

    # --- Ordonnances : lecture et rapprochement -------------------------------------
    async def _lire(images: List[bytes]) -> dict:
        if lire_ordonnance is not None:
            return await lire_ordonnance(images)
        import ocr_core
        from ocr_core.engine import call_llm, parse_json
        from ocr_core.models import compute_cost, get_model
        model = get_model(ocr_core.default_model_id())
        reply, tin, tout = await call_llm(model, SYSTEM_PROMPT, "", images, "ordonnance")
        lu = parse_json(reply)
        lu["_cout"] = {"model": model.id, "input_tokens": tin, "output_tokens": tout,
                       "cost_xof": compute_cost(model, tin, tout)[1]}
        return lu

    async def _produits(code_client: str, depots: List[str]) -> List[dict]:
        filtre: Dict[str, Any] = {"code_client": code_client}
        if depots:
            filtre["code_depot"] = {"$in": depots}
        return await db.stock_produits.find(filtre, {"_id": 0}).to_list(20000)

    async def _vue(ordo: dict) -> dict:
        """Disponibilités recalculées (stock et réservations bougent entre deux lectures)."""
        ids = {c["produit_id"] for l in ordo["lignes"] for c in l.get("candidats", [])}
        ids |= {l["produit_id"] for l in ordo["lignes"] if l.get("produit_id")}
        ids |= {e["produit_id"] for l in ordo["lignes"] for e in (l.get("equivalents") or [])}
        produits = {p["id"]: p for p in await db.stock_produits.find({"id": {"$in": list(ids)}}, {"_id": 0}).to_list(5000)}
        reserve_autres = await _reserve(list(ids), sauf_ordonnance=ordo["id"])
        mes_resa = {r["produit_id"]: r for r in await db.stock_reservations.find(
            {"ordonnance_id": ordo["id"], "statut": "active", "expire_le": {"$gt": _iso(_now())}}, {"_id": 0}).to_list(200)}

        def fiche(pid: Optional[str]) -> Optional[dict]:
            p = produits.get(pid) if pid else None
            if not p:
                return None
            return {"produit_id": p["id"], "code_depot": p["code_depot"], "libelle": p["libelle"],
                    "mesure": p.get("mesure"), "prix_public": p.get("prix_public"), "isalle": p.get("isalle"),
                    "imagasin": p.get("imagasin"), "stock": p.get("stock"), "compte": p.get("compte"),
                    "reserve_autres": reserve_autres.get(p["id"], 0),
                    "disponible": max(0, (p.get("stock") or 0) - reserve_autres.get(p["id"], 0)),
                    "peremption": p.get("peremption"), "alerte_peremption": sp.alerte_peremption(p.get("peremption")),
                    "maj_le": p.get("maj_le"), "source": p.get("source")}

        lignes = []
        for i, l in enumerate(ordo["lignes"]):
            demande = l.get("quantite") or 1
            choisi = fiche(l.get("produit_id"))
            statut = sp.statut_disponibilite(produits.get(l.get("produit_id")),
                                            reserve_autres.get(l.get("produit_id"), 0), demande) \
                if l.get("produit_id") else ("a_confirmer" if l.get("candidats") else "absent")
            lignes.append({**{k: v for k, v in l.items() if k not in ("candidats", "equivalents")}, "index": i,
                           "demande": demande, "produit": choisi, "statut": statut,
                           "candidats": [dict(fiche(c["produit_id"]) or {}, score=c["score"])
                                         for c in l.get("candidats", []) if c["produit_id"] in produits],
                           "equivalents": [dict(fiche(e["produit_id"]) or {}, titre_vidal=e.get("titre_vidal"))
                                           for e in (l.get("equivalents") or []) if e["produit_id"] in produits],
                           "equivalents_etat": l.get("equivalents_etat"),
                           "reservation": mes_resa.get(l.get("produit_id"))})
        return {**{k: v for k, v in ordo.items() if not k.startswith("_")}, "lignes": lignes}

    async def _ordonnance(ordo_id: str, user: dict) -> dict:
        ordo = await db.ordonnances_stock.find_one({"id": ordo_id}, {"_id": 0})
        if not ordo:
            raise HTTPException(status_code=404, detail="Ordonnance introuvable")
        if not _staff(user) and ordo["tenant_id"] != _tenant_id(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        # Lot 54 — l'Auxiliaire en Pharmacie ne voit que les ordonnances qu'il a scannées
        if roles_restreints.est_auxiliaire(user) and ordo.get("cree_par") != user["id"]:
            raise HTTPException(status_code=403, detail="Accès refusé")
        return ordo

    @api.post("/ordonnances-stock", tags=[TAG])
    async def analyser(photos: List[UploadFile] = File(...), depots: Optional[str] = Form(None),
                       code_client: Optional[str] = Form(None), user: dict = Depends(utilisateur)):
        if not photos or len(photos) > MAX_PHOTOS:
            raise HTTPException(status_code=400, detail=f"Déposez de 1 à {MAX_PHOTOS} photos de l'ordonnance")
        code = await _code_client(user, code_client)
        liste_depots = [d.strip().upper() for d in (depots or "").split(",") if d.strip()]
        from ocr_core.prepare import IMAGE_MIMES, shrink_image
        import ocr_pointage
        images: List[bytes] = []
        for n, f in enumerate(photos, 1):
            data = await f.read()
            if len(data) > MAX_OCTETS:
                raise HTTPException(status_code=413, detail=f"Photo n°{n} trop volumineuse (max 20 Mo)")
            ct = (f.content_type or "").lower()
            if ct == "application/pdf":
                images += await asyncio.to_thread(ocr_pointage.pages_en_images, data, ct)
            elif ct in IMAGE_MIMES:
                images.append(await asyncio.to_thread(shrink_image, data))
            else:
                raise HTTPException(status_code=400, detail=f"Photo n°{n} : JPG, PNG, WEBP ou PDF attendu")
        try:
            lu = await _lire(images[:MAX_PHOTOS])
        except Exception as exc:  # noqa: BLE001 — réseau, quota, réponse illisible
            logger.exception("[ordonnances_stock] lecture IA impossible")
            raise HTTPException(status_code=502, detail=f"Lecture de l'ordonnance impossible : {exc}") from exc
        produits = await _produits(code, liste_depots)
        lignes = []
        for l in (lu.get("lignes") or [])[:40]:
            ligne = {k: l.get(k) for k in ("nom", "dosage", "forme", "posologie", "incertain", "note")}
            try:
                ligne["quantite"] = int(l["quantite"]) if l.get("quantite") not in (None, "") else None
            except (TypeError, ValueError):
                ligne["quantite"] = None
            ligne.update(rapprocher(ligne, produits))
            lignes.append(ligne)
        if _staff(user):   # l'Admin travaille pour le compte du client qui porte ce code
            compte = await db.users.find_one({"client_code": {"$in": [code, code.lower()]}}, {"_id": 0, "id": 1}) or {}
            tenant_id = compte.get("id") or code
        else:
            tenant_id = _tenant_id(user)
        ordo = {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
                "code_client": code, "depots": liste_depots, "date_ordonnance": lu.get("date_ordonnance"),
                "lignes": lignes, "cree_par": user["id"], "cree_le": _iso(_now()),
                "stock_vide": not produits, "_cout": lu.get("_cout")}
        await db.ordonnances_stock.insert_one(dict(ordo))
        if roles_restreints.est_auxiliaire(user):
            return _vue_ocr(ordo)
        return await _vue(ordo)

    @api.get("/ordonnances-stock", tags=[TAG])
    async def lister(user: dict = Depends(utilisateur)):
        q = {} if _staff(user) else {"tenant_id": _tenant_id(user)}
        if roles_restreints.est_auxiliaire(user):   # lot 54 : historique de SES scans uniquement
            q["cree_par"] = user["id"]
        rows = await db.ordonnances_stock.find(q, {"_id": 0, "_cout": 0}).sort("cree_le", -1).to_list(100)
        return [{"id": r["id"], "code_client": r["code_client"], "cree_le": r["cree_le"],
                 "date_ordonnance": r.get("date_ordonnance"), "lignes": len(r["lignes"]),
                 "noms": [l.get("nom") for l in r["lignes"]][:6]} for r in rows]

    @api.get("/ordonnances-stock/{ordo_id}", tags=[TAG])
    async def detail(ordo_id: str, user: dict = Depends(utilisateur)):
        ordo = await _ordonnance(ordo_id, user)
        if roles_restreints.est_auxiliaire(user):
            return _vue_ocr(ordo)
        return await _vue(ordo)

    @api.put("/ordonnances-stock/{ordo_id}/lignes/{n}", tags=[TAG])
    async def choisir(ordo_id: str, n: int, choix: ChoixLigne, user: dict = Depends(gestionnaire)):
        ordo = await _ordonnance(ordo_id, user)
        if not 0 <= n < len(ordo["lignes"]):
            raise HTTPException(status_code=404, detail="Ligne introuvable")
        if choix.produit_id:
            p = await db.stock_produits.find_one({"id": choix.produit_id, "code_client": ordo["code_client"]}, {"_id": 0, "id": 1})
            if not p:
                raise HTTPException(status_code=400, detail="Produit absent du stock de ce client")
        maj = {f"lignes.{n}.produit_id": choix.produit_id, f"lignes.{n}.confiance": "choisi"}
        if choix.quantite:
            maj[f"lignes.{n}.quantite"] = choix.quantite
        await db.ordonnances_stock.update_one({"id": ordo_id}, {"$set": maj})
        return await _vue(await _ordonnance(ordo_id, user))

    @api.post("/ordonnances-stock/{ordo_id}/lignes/{n}/equivalents", tags=[TAG])
    async def equivalents(ordo_id: str, n: int, user: dict = Depends(gestionnaire)):
        """Équivalents VIDAL (regroupement VMP : même DCI et dosage) présents dans le stock."""
        ordo = await _ordonnance(ordo_id, user)
        if not 0 <= n < len(ordo["lignes"]):
            raise HTTPException(status_code=404, detail="Ligne introuvable")
        ligne = ordo["lignes"][n]
        etat, trouves = "ok", []
        if vidal_rechercher is None or vidal_equivalents is None:
            etat = "vidal_indisponible"
        else:
            try:
                res = await vidal_rechercher(user, f"{ligne.get('nom') or ''} {ligne.get('dosage') or ''}".strip())
                resultats = [r for r in (res.get("results") or []) if r.get("vmp_id")]
                if not resultats:
                    etat = "vidal_aucun_resultat"
                else:
                    eq = await vidal_equivalents(user, resultats[0]["vmp_id"])
                    titres = [resultats[0].get("title")] + [e.get("title") for e in (eq.get("equivalents") or [])]
                    produits = await _produits(ordo["code_client"], ordo.get("depots") or [])
                    vus = set()
                    for titre in [t for t in titres if t]:
                        r = rapprocher({"nom": titre}, produits)
                        pid = r["produit_id"] or (r["candidats"][0]["produit_id"]
                                                  if r["candidats"] and r["candidats"][0]["score"] >= 0.6 else None)
                        if pid and pid not in vus and pid != ligne.get("produit_id"):
                            vus.add(pid)
                            trouves.append({"produit_id": pid, "titre_vidal": titre})
                    if not trouves:
                        etat = "aucun_en_stock"
            except HTTPException as exc:
                etat = "vidal_refuse" if exc.status_code in (401, 403) else "vidal_erreur"
            except Exception:  # noqa: BLE001
                logger.exception("[ordonnances_stock] équivalents VIDAL impossibles")
                etat = "vidal_erreur"
        await db.ordonnances_stock.update_one({"id": ordo_id}, {"$set": {
            f"lignes.{n}.equivalents": trouves, f"lignes.{n}.equivalents_etat": etat}})
        return await _vue(await _ordonnance(ordo_id, user))

    # --- Réservations ---------------------------------------------------------------
    @api.post("/ordonnances-stock/{ordo_id}/reserver", tags=[TAG])
    async def reserver(ordo_id: str, user: dict = Depends(gestionnaire)):
        """Réserve, pour chaque ligne dont le produit est choisi, min(demandé, disponible).
        Une ligne déjà réservée pour ce produit n'est pas réservée deux fois ; un produit
        dont la péremption est dépassée n'est jamais réservé."""
        vue = await _vue(await _ordonnance(ordo_id, user))
        heures = await _duree_reservation()
        creees = []
        for l in vue["lignes"]:
            p = l.get("produit")
            if not p or l.get("reservation") or not p.get("compte") or p.get("alerte_peremption") == "perime":
                continue
            q = min(l["demande"], p["disponible"])
            if q <= 0:
                continue
            r = {"id": str(uuid.uuid4()), "ordonnance_id": ordo_id, "produit_id": p["produit_id"],
                 "code_client": vue["code_client"], "code_depot": p["code_depot"], "libelle": p["libelle"],
                 "quantite": q, "statut": "active", "cree_par": user["id"], "cree_le": _iso(_now()),
                 "expire_le": _iso(_now() + timedelta(hours=heures))}
            await db.stock_reservations.insert_one(dict(r))
            creees.append(r)
        return {"reservations": creees, "ordonnance": await _vue(await _ordonnance(ordo_id, user))}

    @api.post("/ordonnances-stock/{ordo_id}/reservations/{rid}/{action}", tags=[TAG])
    async def cloturer(ordo_id: str, rid: str, action: str, user: dict = Depends(gestionnaire)):
        if action not in ("vendue", "annuler"):
            raise HTTPException(status_code=400, detail="Action attendue : vendue ou annuler")
        await _ordonnance(ordo_id, user)
        r = await db.stock_reservations.update_one(
            {"id": rid, "ordonnance_id": ordo_id, "statut": "active"},
            {"$set": {"statut": "vendue" if action == "vendue" else "annulee", "cloture_par": user["id"],
                      "cloture_le": _iso(_now())}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Réservation introuvable ou déjà clôturée")
        return await _vue(await _ordonnance(ordo_id, user))

    @api.delete("/ordonnances-stock/{ordo_id}", tags=[TAG])
    async def supprimer(ordo_id: str, user: dict = Depends(gestionnaire)):
        await _ordonnance(ordo_id, user)
        await db.stock_reservations.update_many({"ordonnance_id": ordo_id, "statut": "active"},
                                                {"$set": {"statut": "annulee", "cloture_le": _iso(_now())}})
        await db.ordonnances_stock.delete_one({"id": ordo_id})
        return {"ok": True}

    return {"rapprocher": rapprocher}
