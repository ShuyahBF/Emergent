# index_mongo_recommandes.py — Lot 272 : INDEX MONGODB RECOMMANDÉS, créés en un clic (Paramètres, administrateur principal).
#
# Constat (conseiller de performance d'Atlas, 21/10/2026) : le cluster n'est pas trop petit (disque à 23 %, aucune alerte),
# mais quelques requêtes parcourent TOUTE la collection faute d'index : export paginé des tables e-Kol
# (hf_ekol_<école>_<table>), journaux, messages WhatsApp. Ajouter ces index coûte moins cher qu'un palier Atlas supérieur.
#
# Cet écran : liste les index recommandés, indique pour chacun s'il est PRÉSENT, MANQUANT ou si la collection n'existe pas,
# puis crée les index manquants EN ARRIÈRE-PLAN (règle 7) sur demande.
# Règles respectées :
#   - liste fermée et relue : on ne crée QUE ces index (jamais une demande libre venue de l'écran) ;
#   - aucune nouvelle collection (cluster plein) : seulement des index sur des collections existantes ;
#   - jamais de suppression ni de modification de données ; un index déjà présent n'est pas recréé ;
#   - la construction se fait sur le serveur MongoDB sans bloquer les lectures/écritures (MongoDB 4.2+) ; à lancer de
#     préférence hors des heures de pointe ;
#   - accès réservé à l'administrateur principal (information d'infrastructure).
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)

# Index recommandés : (collection, clés, raison). Les clés sont dans l'ordre exact proposé par Atlas.
# Les 5 suggestions d'Atlas de faible poids (whatsapp_messages sur id / to / to_number / phone_digits, planning_appointments)
# ne sont volontairement pas proposées : elles ralentiraient chaque écriture pour un gain minime.
_HF = [("_hf_maj", 1), ("_hf_cle", 1)]
INDEX_RECOMMANDES: List[Dict[str, Any]] = [
    {"collection": "hf_ekol_ECOLE_DES_METIERS_NotesExamens", "cles": _HF, "raison": "Export paginé e-Kol : sans index, chaque page parcourt toute la table (le plus lent du cluster)"},
    {"collection": "hf_ekol_ECOLE_DES_METIERS_Paiements", "cles": _HF, "raison": "Export paginé e-Kol (paiements des élèves)"},
    {"collection": "hf_ekol_ECOLE_DES_METIERS_EleveEdu", "cles": _HF, "raison": "Export paginé e-Kol (élèves)"},
    {"collection": "hf_ekol_ECOLE_DES_METIERS_Inscription", "cles": _HF, "raison": "Export paginé e-Kol (inscriptions)"},
    {"collection": "hf_ekol_ECOLE_DES_METIERS_MatieresClasse", "cles": _HF, "raison": "Export paginé e-Kol (matières par classe)"},
    {"collection": "hf_ekol_ECOLE_DES_METIERS_Examens", "cles": _HF, "raison": "Export paginé e-Kol (examens)"},
    {"collection": "visits", "cles": [("id", 1)], "raison": "Recherche d'une visite par identifiant"},
    {"collection": "incidents_webhook_log", "cles": [("created_at", 1)], "raison": "Tri et purge du journal des incidents par date"},
    {"collection": "whatsapp_messages", "cles": [("contact_id", 1), ("client_id", 1), ("created_at", 1)], "raison": "Fil de messages d'un contact (Centre de messagerie)"},
    {"collection": "whatsapp_messages", "cles": [("client_id", 1), ("created_at", 1), ("phone_digits", 1)], "raison": "Messages d'un client par numéro et par date"},
]

# État de la création en cours (le serveur SAWALI tourne en une seule instance)
_ETAT: Dict[str, Any] = {"en_cours": False, "fait": 0, "total": 0, "courant": "", "demarre_le": None, "termine_le": None,
                         "crees": 0, "erreurs": []}
_tache: Optional["asyncio.Task[Any]"] = None


def identifiant(rec: Dict[str, Any]) -> str:
    """Identifiant stable d'une recommandation : « collection:champ1+champ2 »."""
    return f"{rec['collection']}:{'+'.join(c for c, _ in rec['cles'])}"


def nom_index(rec: Dict[str, Any]) -> str:
    """Nom de l'index créé (lisible dans Atlas)."""
    return "sawali_" + "_".join(c for c, _ in rec["cles"])


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


async def constater(db) -> List[Dict[str, Any]]:
    """État de chaque index recommandé : présent, manquant ou collection absente (lecture seule)."""
    existantes = set(await db.list_collection_names())
    lignes: List[Dict[str, Any]] = []
    for rec in INDEX_RECOMMANDES:
        ligne = {"id": identifiant(rec), "collection": rec["collection"], "cles": [c for c, _ in rec["cles"]],
                 "raison": rec["raison"], "documents": None, "statut": "collection_absente"}
        if rec["collection"] in existantes:
            coll = db[rec["collection"]]
            ligne["documents"] = await coll.estimated_document_count()
            infos = await coll.index_information()
            present = any([(c, int(s)) for c, s in (i.get("key") or [])] == [(c, int(s)) for c, s in rec["cles"]] for i in infos.values())
            ligne["statut"] = "present" if present else "manquant"
        lignes.append(ligne)
    return lignes


async def _creer(db, ids: List[str]) -> None:
    """Tâche de fond : crée les index demandés, un par un (ménage le cluster)."""
    par_id = {identifiant(r): r for r in INDEX_RECOMMANDES}
    _ETAT.update(en_cours=True, fait=0, total=len(ids), courant="", crees=0, erreurs=[],
                 demarre_le=_iso(datetime.now(timezone.utc)), termine_le=None)
    try:
        for i in ids:
            rec = par_id[i]
            _ETAT["courant"] = rec["collection"]
            try:
                await db[rec["collection"]].create_index(rec["cles"], name=nom_index(rec))
                _ETAT["crees"] += 1
            except Exception as e:  # noqa: BLE001 — une erreur n'arrête pas les autres ; jamais de détail technique sensible
                logger.warning("index_mongo: échec sur %s (%s)", i, type(e).__name__)
                _ETAT["erreurs"].append({"id": i, "erreur": f"Création impossible ({type(e).__name__})"})
            _ETAT["fait"] += 1
    finally:
        _ETAT.update(en_cours=False, courant="", termine_le=_iso(datetime.now(timezone.utc)))


def make_index_mongo_router(*, db, get_super_admin) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/index-mongo/etat", tags=["Admin — Index MongoDB"])
    async def etat(_: dict = Depends(get_super_admin)):
        """Index recommandés avec leur état réel + avancement d'une création éventuellement en cours (lecture seule)."""
        lignes = await constater(db)
        return {"index": lignes, "manquants": sum(1 for l in lignes if l["statut"] == "manquant"), "creation": dict(_ETAT)}

    @router.post("/admin/index-mongo/creer", tags=["Admin — Index MongoDB"])
    async def creer(corps: Dict[str, Any] = Body(default_factory=dict), _: dict = Depends(get_super_admin)):
        """Crée en arrière-plan les index MANQUANTS (tous, ou ceux de `ids`) et répond tout de suite."""
        global _tache
        if _ETAT["en_cours"]:
            return {"deja_en_cours": True, **_ETAT}
        connus = {identifiant(r) for r in INDEX_RECOMMANDES}
        demandes = corps.get("ids")
        if demandes is not None:
            if not isinstance(demandes, list) or any(not isinstance(x, str) or x not in connus for x in demandes):
                raise HTTPException(status_code=422, detail="Index inconnu : seuls les index de la liste peuvent être créés")
        manquants = [l["id"] for l in await constater(db) if l["statut"] == "manquant" and (demandes is None or l["id"] in demandes)]
        if not manquants:
            return {"deja_en_cours": False, "rien_a_creer": True, **_ETAT}
        _ETAT.update(en_cours=True)
        _tache = asyncio.create_task(_creer(db, manquants))
        return {"deja_en_cours": False, "rien_a_creer": False, **_ETAT}

    return router
