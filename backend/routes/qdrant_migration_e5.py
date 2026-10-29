# qdrant_migration_e5.py — Lot 348 : recalculer une collection de la base de connaissances avec le modèle de Qdrant.
#
# Pourquoi : la base de connaissances de Liluvine utilise un modèle de recherche chargé SUR le serveur Render (≥ 1 Go de mémoire).
# Sur l'offre Starter (512 Mo) ce modèle est suspendu : la recherche sémantique de Liluvine dans la base ne répond plus. Qdrant
# Cloud Inference (modèle gratuit intfloat/multilingual-e5-small) calcule les vecteurs chez Qdrant : plus de limite de mémoire.
#
# Méthode SANS RISQUE — une COPIE, jamais une modification de l'original :
#   1. « Recalculer » : crée la collection « <nom>-e5 », y recopie CHAQUE point (même identifiant, même contenu) avec un vecteur
#      recalculé par Qdrant. Travail d'arrière-plan par lots de 32, reprenable (relancer ne crée aucun doublon).
#   2. « Basculer » : la copie prend la place de l'original dans la base de connaissances de Liluvine (l'original est mis de côté,
#      pas supprimé). « Annuler la bascule » remet l'original. Rien n'est supprimé par ce module.
# Le texte vectorisé est celui du point (`text`) ; pour une image : titre + légende + description + texte lu (comme à l'indexation).
# Les points sans texte sont comptés « sautés » (jamais perdus : ils restent dans l'original).
# État (progression) : document `qdrant_migration` de la collection `settings` (aucune nouvelle collection MongoDB).
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.migration_e5")

SUFFIXE = "-e5"
LOT_POINTS = 32
ETAT_ID = "qdrant_migration"
RESERVEES = ("wa_conversations",)      # la mémoire des conversations a déjà son propre moteur
_TACHES: set = set()


class Collection(BaseModel):
    collection: str = Field(min_length=1, max_length=64)


class Bascule(BaseModel):
    collection: str = Field(min_length=1, max_length=64)
    actif: bool = True


def nom_copie(source: str) -> str:
    return f"{source}{SUFFIXE}"


def texte_a_vectoriser(payload: Dict[str, Any]) -> str:
    """Texte qui sera vectorisé pour un point (fonction pure). Image : titre, légende, description, texte lu ; sinon `text`."""
    p = payload or {}
    if (p.get("kind") or "text") == "image":
        parts = [p.get("title"), p.get("caption"), p.get("visual_summary"), p.get("ocr_text")]
        t = "\n".join(str(x).strip() for x in parts if x and str(x).strip())
        return t or (p.get("text") or "")
    return (p.get("text") or "").strip()


async def _client(db):
    from routes.qdrant_rag import client_ia
    return await client_ia(db)


async def _maj(db, source: str, **champs):
    await db.settings.update_one({"_id": ETAT_ID}, {"$set": {f"{source}.{k}": v for k, v in champs.items()}}, upsert=True)


async def _compte(client, nom: str) -> Optional[int]:
    try:
        return (await asyncio.to_thread(lambda: client.count(nom, exact=True))).count
    except Exception:  # noqa: BLE001
        return None


async def recalculer(db, source: str) -> None:
    """Tâche d'arrière-plan : copie `source` vers `source-e5` avec des vecteurs calculés par Qdrant. Jamais d'exception non rattrapée."""
    from qdrant_client.models import Distance, PointStruct, VectorParams
    from routes.qdrant_rag import _EMBED_VECTOR_SIZE, MODELE_E5, _vider_cache_liste, doc_e5
    copie = nom_copie(source)
    try:
        client = await _client(db)
        total = await _compte(client, source) or 0
        await _maj(db, source, statut="en_cours", total=total, faits=0, saute=0, erreur=None, debut=datetime.now(timezone.utc).isoformat(), fin=None)
        if not await asyncio.to_thread(lambda: client.collection_exists(copie)):
            await asyncio.to_thread(lambda: client.create_collection(
                collection_name=copie, vectors_config=VectorParams(size=_EMBED_VECTOR_SIZE, distance=Distance.COSINE)))
        faits = saute = 0
        suite = None
        while True:
            pts, suite = await asyncio.to_thread(lambda: client.scroll(
                collection_name=source, limit=LOT_POINTS, offset=suite, with_payload=True, with_vectors=False))
            lot: List[Any] = []
            for p in pts:
                texte = texte_a_vectoriser(p.payload or {})
                if not texte:
                    saute += 1
                    continue
                lot.append(PointStruct(id=p.id, vector=doc_e5(texte), payload=p.payload or {}))
            if lot:
                await asyncio.to_thread(lambda: client.upsert(collection_name=copie, points=lot))
                faits += len(lot)
            await _maj(db, source, faits=faits, saute=saute)
            if suite is None:
                break
        # métadonnées de la copie : moteur « inference », PAS encore utilisée par Liluvine (la bascule est un geste séparé)
        await db.settings.update_one({"_id": "global"}, {"$set": {f"qdrant_collection_settings.{copie}": {
            "enabled_for_liluvine": False, "moteur": "inference", "source": source, "created_at": datetime.now(timezone.utc).isoformat(),
            "description": f"Copie de « {source} » recalculée par Qdrant (modèle {MODELE_E5})."}}}, upsert=True)
        _vider_cache_liste()
        await _maj(db, source, statut="copie_prete", fin=datetime.now(timezone.utc).isoformat(), faits=faits, saute=saute)
    except Exception as exc:  # noqa: BLE001 — l'état reste lisible et la reprise possible
        logger.warning("[migration_e5] %s : échec", source, exc_info=True)
        await _maj(db, source, statut="erreur", erreur=str(exc)[:300])


async def basculer(db, source: str, actif: bool) -> Dict[str, Any]:
    """Bascule : la copie remplace l'original dans la base de connaissances de Liluvine (ou l'inverse). Rien n'est supprimé."""
    from routes.qdrant_rag import _vider_cache_liste
    copie = nom_copie(source)
    s = await db.settings.find_one({"_id": "global"}) or {}
    meta = s.get("qdrant_collection_settings") or {}
    if copie not in meta:
        raise HTTPException(status_code=409, detail="La copie recalculée n'existe pas encore : lancez d'abord « Recalculer ».")
    etat = (await db.settings.find_one({"_id": ETAT_ID}) or {}).get(source) or {}
    if actif and etat.get("statut") != "copie_prete":
        raise HTTPException(status_code=409, detail="La copie n'est pas terminée : attendez la fin du recalcul.")
    original_actif = bool((meta.get(source) or {}).get("enabled_for_liluvine"))
    if actif:
        # la copie prend l'état « utilisée » de l'original ; l'original est mis de côté (on retient s'il était utilisé)
        await db.settings.update_one({"_id": "global"}, {"$set": {
            f"qdrant_collection_settings.{copie}.enabled_for_liluvine": original_actif or bool(etat.get("original_etait_actif")),
            f"qdrant_collection_settings.{source}.enabled_for_liluvine": False}})
        await _maj(db, source, bascule=True, original_etait_actif=original_actif or bool(etat.get("original_etait_actif")))
    else:
        retour = bool(etat.get("original_etait_actif", True))
        await db.settings.update_one({"_id": "global"}, {"$set": {
            f"qdrant_collection_settings.{copie}.enabled_for_liluvine": False,
            f"qdrant_collection_settings.{source}.enabled_for_liluvine": retour}})
        await _maj(db, source, bascule=False)
    _vider_cache_liste()
    return {"ok": True, "bascule": actif}


def make_router(*, db, get_current_user):
    router = APIRouter(prefix="/admin/qdrant/recalcul-e5", tags=["Admin — Qdrant : recalcul avec le modèle de Qdrant"])

    def _gate(user: dict):
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")

    @router.get("/etat")
    async def etat(user: dict = Depends(get_current_user)):
        """Une ligne par collection d'origine : points, moteur, avancement du recalcul, bascule."""
        _gate(user)
        from routes.qdrant_rag import list_collections
        suivi = await db.settings.find_one({"_id": ETAT_ID}) or {}
        toutes = await list_collections(db)
        copies = {c["name"]: c for c in toutes}
        lignes = []
        for c in toutes:
            nom = c["name"]
            if nom in RESERVEES or nom.endswith(SUFFIXE) or c.get("moteur") == "inference":
                continue
            e = suivi.get(nom) or {}
            lignes.append({
                "collection": nom, "points": c.get("vectors_count"), "utilisee_par_liluvine": c.get("enabled_for_liluvine"),
                "statut": e.get("statut") or ("copie_prete" if nom_copie(nom) in copies else "jamais"),
                "total": e.get("total"), "faits": e.get("faits"), "saute": e.get("saute"), "erreur": e.get("erreur"),
                "copie": nom_copie(nom) if nom_copie(nom) in copies else None,
                "points_copie": (copies.get(nom_copie(nom)) or {}).get("vectors_count"), "bascule": bool(e.get("bascule")),
            })
        return {"collections": lignes, "en_cours": any(l["statut"] == "en_cours" for l in lignes)}

    @router.post("/demarrer")
    async def demarrer(corps: Collection, user: dict = Depends(get_current_user)):
        """Lance (ou reprend) le recalcul d'une collection, en arrière-plan."""
        _gate(user)
        nom = corps.collection
        if nom in RESERVEES or nom.endswith(SUFFIXE) or not re.fullmatch(r"[a-zA-Z0-9_\-]{1,64}", nom):
            raise HTTPException(status_code=422, detail="Collection non concernée")
        from routes.qdrant_rag import list_collections
        if nom not in {c["name"] for c in await list_collections(db)}:
            raise HTTPException(status_code=404, detail="Collection introuvable")
        suivi = await db.settings.find_one({"_id": ETAT_ID}) or {}
        if any((v or {}).get("statut") == "en_cours" for v in suivi.values() if isinstance(v, dict)) and _TACHES:
            raise HTTPException(status_code=409, detail="Un recalcul est déjà en cours : attendez sa fin.")
        tache = asyncio.create_task(recalculer(db, nom))
        _TACHES.add(tache)
        tache.add_done_callback(_TACHES.discard)
        return {"ok": True, "demarre": nom}

    @router.post("/basculer")
    async def basculer_route(corps: Bascule, user: dict = Depends(get_current_user)):
        """La copie remplace l'original dans la base de Liluvine (actif = true) ou l'original est remis (false)."""
        _gate(user)
        return await basculer(db, corps.collection, corps.actif)

    return router
