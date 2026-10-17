# audit_collections_mongo.py — Lot 225 : AUDIT D'UTILISATION DES COLLECTIONS MONGODB (lecture seule, en un clic).
#
# But : savoir quelles collections ne servent plus depuis longtemps, pour libérer de la place sur un cluster plein
# (plafond de 500 collections des paliers gratuit / Flex) avant de payer un palier supérieur.
#
# Pour CHAQUE collection de CHAQUE base du cluster auquel SAWALI est connecté, on cherche :
#   - la date de création du document le plus récent (horodatage contenu dans son _id) ;
#   - la plus récente valeur des champs « date » des documents récents (updated_at, created_at, envoye_le…) :
#     détecte aussi les mises à jour ;
#   - l'utilisation des index depuis le dernier redémarrage ($indexStats, si Atlas l'autorise) : montre les LECTURES ;
#   - pour la base de SAWALI : la collection est-elle citée dans le code du serveur ? (si oui, elle n'est JAMAIS proposée
#     à la suppression, même vide : le serveur la recrée ou la lit).
# Statuts : VIDE · ACTIVE (< 90 j) · PEU ACTIVE (90 à 180 j) · INACTIVE (> 180 j) · INCONNUE (aucune date exploitable).
#
# Facultatif — inventaire des organisations, projets et clusters Atlas : variable d'environnement ATLAS_API_KEYS
# (saisie par le propriétaire dans Render), au format « clé_publique:clé_privée » ; plusieurs organisations séparées par
# des virgules. Droit « Organization Read Only » suffisant. Sans elle, l'audit du cluster courant fonctionne quand même.
#
# Règles respectées :
#   - lecture seule : aucune écriture ni suppression dans les bases auditées ;
#   - aucune nouvelle collection (cluster plein) : le dernier rapport est gardé dans la collection EXISTANTE `settings`
#     (_id « audit_mongo_collections ») ;
#   - le calcul part en ARRIÈRE-PLAN (règle 7) : le bouton répond tout de suite, l'écran suit l'avancement ;
#   - jamais de secret dans le rapport (ni chaîne de connexion, ni clé d'API) : seulement noms, comptes et dates.
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

logger = logging.getLogger(__name__)

ID_RAPPORT = "audit_mongo_collections"      # document du rapport dans la collection `settings`
SEUIL_PEU_ACTIVE_JOURS = 90                  # au-delà : « PEU ACTIVE »
SEUIL_INACTIVE_JOURS = 180                   # au-delà : « INACTIVE »
PLAFOND_PALIERS_PARTAGES = 500               # collections maximum des paliers gratuit / Flex (indicatif : un M10 n'a pas ce plafond strict)
BASES_IGNOREES = {"admin", "local", "config"}   # bases système d'Atlas
MAX_CHAMPS_DATE = 8                          # champs « date » examinés par collection
DELAI_REQUETE_MS = 8000                      # délai maximum d'une recherche (millisecondes)
MAX_DOCS_RECHERCHE_DATE = 200_000            # au-delà, on ne trie pas sur un champ date (parcours trop long)
PARALLELE = 4                                # collections analysées en même temps (ménage le cluster)
VERSIONS_API_ATLAS = ["2025-03-12", "2024-11-13", "2024-08-05"]
API_ATLAS = "https://cloud.mongodb.com/api/atlas/v2"

MOTIF_DATE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")

# État de l'analyse en cours (le serveur SAWALI tourne en une seule instance)
_ETAT: Dict[str, Any] = {"en_cours": False, "fait": 0, "total": 0, "base": "", "demarre_le": None,
                         "termine_le": None, "erreur": None}
_tache: Optional["asyncio.Task[Any]"] = None
_cache_code: Dict[str, str] = {}


# --------------------------------------------------------------------------------------------------------------------
# Outils de dates
# --------------------------------------------------------------------------------------------------------------------
def en_utc(d: Any) -> Optional[datetime]:
    """Date MongoDB ou texte ISO → date UTC « avec fuseau » ; None si la valeur n'est pas une date exploitable."""
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if isinstance(d, str) and MOTIF_DATE_ISO.match(d):
        try:
            r = datetime.fromisoformat(d.replace("Z", "+00:00"))
            return r if r.tzinfo else r.replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                return datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


# --------------------------------------------------------------------------------------------------------------------
# Code du serveur : la collection est-elle citée ?
# --------------------------------------------------------------------------------------------------------------------
def _texte_code_serveur() -> str:
    """Contenu concaténé des fichiers .py du serveur (hors tests), lu une seule fois."""
    if "texte" not in _cache_code:
        racine = Path(__file__).resolve().parents[1]
        morceaux: List[str] = []
        for p in racine.rglob("*.py"):
            if "tests" in p.parts or "__pycache__" in p.parts:
                continue
            try:
                morceaux.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
        _cache_code["texte"] = "\n".join(morceaux)
    return _cache_code["texte"]


def cite_dans_le_code(nom_collection: str) -> bool:
    """Vrai si le nom apparaît comme mot entier dans le code du serveur (db.nom, db["nom"], "nom"…).
    Volontairement large : un faux « oui » évite seulement de proposer une suppression, un faux « non » serait dangereux."""
    motif = r"(?<![A-Za-z0-9_])" + re.escape(nom_collection) + r"(?![A-Za-z0-9_])"
    return re.search(motif, _texte_code_serveur()) is not None


# --------------------------------------------------------------------------------------------------------------------
# Analyse d'une collection
# --------------------------------------------------------------------------------------------------------------------
async def _dernier_par(coll, filtre: Dict[str, Any], champ: str) -> Any:
    """Plus grande valeur de `champ` (recherche triée, 1 document, durée limitée)."""
    curseur = coll.find(filtre, {champ: 1}).sort(champ, -1).limit(1)
    if hasattr(curseur, "max_time_ms"):
        curseur = curseur.max_time_ms(DELAI_REQUETE_MS)
    async for doc in curseur:
        return doc.get(champ)
    return None


async def _champs_date_recents(coll) -> List[str]:
    """Champs « date » (vraies dates ou texte ISO) repérés dans les 5 documents les plus récents (niveau 1 seulement)."""
    champs: List[str] = []
    async for doc in coll.find({}).sort("_id", -1).limit(5):
        for nom, valeur in doc.items():
            if nom != "_id" and nom not in champs and en_utc(valeur) is not None:
                champs.append(nom)
    return champs[:MAX_CHAMPS_DATE]


async def analyser_collection(base, nom: str, maintenant: datetime) -> Dict[str, Any]:
    """Indicateurs d'utilisation d'une collection (lecture seule)."""
    coll = base[nom]
    res: Dict[str, Any] = {"collection": nom, "documents": 0, "taille_mo": None, "derniere_insertion": None,
                           "champ_date": "", "derniere_date_champ": None, "acces_ops": None, "acces_depuis": None}
    res["documents"] = await coll.estimated_document_count()

    # Taille (facultatif : certains paliers refusent la commande)
    try:
        st = await base.command("collStats", nom)
        res["taille_mo"] = round((st.get("size", 0) + st.get("totalIndexSize", 0)) / 1048576, 2)
    except Exception:  # noqa: BLE001 — taille indisponible, on continue
        pass

    # Utilisation des index depuis le dernier redémarrage (reflète aussi les lectures)
    try:
        stats = await coll.aggregate([{"$indexStats": {}}]).to_list(None)
        res["acces_ops"] = sum(int((s.get("accesses") or {}).get("ops", 0)) for s in stats)
        depuis = [en_utc((s.get("accesses") or {}).get("since")) for s in stats]
        depuis = [d for d in depuis if d]
        res["acces_depuis"] = min(depuis) if depuis else None
    except Exception:  # noqa: BLE001 — $indexStats refusé sur ce palier
        pass

    if res["documents"] == 0:
        return res

    # Date de création du document le plus récent (horodatage de l'_id ObjectId)
    dernier_id = await _dernier_par(coll, {}, "_id")
    if isinstance(dernier_id, ObjectId):
        res["derniere_insertion"] = en_utc(dernier_id.generation_time)

    # Plus récente valeur parmi les champs « date » des documents récents (dates futures ignorées : échéances)
    if res["documents"] <= MAX_DOCS_RECHERCHE_DATE:
        meilleur: Tuple[Optional[datetime], str] = (None, "")
        for champ in await _champs_date_recents(coll):
            for type_bson in ("date", "string"):
                try:
                    val = await _dernier_par(coll, {champ: {"$type": type_bson}}, champ)
                except Exception:  # noqa: BLE001 — recherche trop longue ou champ non triable
                    continue
                d = en_utc(val)
                if d and d <= maintenant and (meilleur[0] is None or d > meilleur[0]):
                    meilleur = (d, champ)
        res["derniere_date_champ"], res["champ_date"] = meilleur
    return res


def classer(res: Dict[str, Any], maintenant: datetime) -> Tuple[str, Optional[int], Optional[datetime]]:
    """(statut, jours d'inactivité, dernière activité connue)."""
    if res["documents"] == 0:
        return "VIDE", None, None
    dates = [d for d in (res["derniere_insertion"], res["derniere_date_champ"]) if d]
    derniere = max(dates) if dates else None
    if derniere is None:
        return "INCONNUE", None, None
    jours = (maintenant - derniere).days
    if jours >= SEUIL_INACTIVE_JOURS:
        return "INACTIVE", jours, derniere
    if jours >= SEUIL_PEU_ACTIVE_JOURS:
        return "PEU ACTIVE", jours, derniere
    return "ACTIVE", jours, derniere


def verdict(statut: str, reference_code: Optional[bool], acces_ops: Optional[int], base_sawali: bool) -> str:
    """Conseil par collection. Une collection citée dans le code n'est jamais proposée à la suppression."""
    if statut in ("ACTIVE", "PEU ACTIVE"):
        return "À garder"
    if not base_sawali:
        # Le code d'une autre plateforme n'est pas ici : on ne peut pas affirmer qu'elle est inutile
        return "À vérifier (code d'une autre plateforme)" if statut in ("VIDE", "INACTIVE") else "À vérifier"
    if reference_code:
        return "Citée dans le code : à garder" if statut in ("VIDE", "INACTIVE") else "À vérifier"
    if statut in ("VIDE", "INACTIVE"):
        if acces_ops:
            return "Candidate (lue récemment par des index : vérifier)"
        return "Candidate à la suppression"
    return "À vérifier"


# --------------------------------------------------------------------------------------------------------------------
# Inventaire Atlas (facultatif)
# --------------------------------------------------------------------------------------------------------------------
def _hote_courant() -> str:
    """Adresse du cluster auquel SAWALI est connecté (partie après le « @ » de MONGO_URL ; sans identifiants)."""
    m = re.search(r"@([^/?]+)", os.environ.get("MONGO_URL", ""))
    return m.group(1).lower() if m else ""


def _cles_atlas() -> List[Tuple[str, str]]:
    """Paires (clé publique, clé privée) lues dans la variable d'environnement ATLAS_API_KEYS."""
    paires: List[Tuple[str, str]] = []
    for morceau in (os.environ.get("ATLAS_API_KEYS", "") or "").split(","):
        if ":" in morceau:
            pub, priv = morceau.strip().split(":", 1)
            if pub and priv:
                paires.append((pub, priv))
    return paires


async def _appel_atlas(client, chemin: str, auth, etat: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Appelle l'API Atlas ; essaie d'autres versions de l'API si la première est refusée (406)."""
    versions = [etat["version"]] if etat.get("version") else VERSIONS_API_ATLAS
    for v in versions:
        r = await client.get(API_ATLAS + chemin, auth=auth, params={"itemsPerPage": 500},
                             headers={"Accept": f"application/vnd.atlas.{v}+json"})
        if r.status_code == 406:
            continue
        if r.status_code == 200:
            etat["version"] = v
            return r.json()
        return None
    return None


async def inventaire_atlas() -> Dict[str, Any]:
    """Organisations › projets › clusters visibles avec les clés d'API configurées."""
    cles = _cles_atlas()
    if not cles:
        return {"configure": False, "clusters": [], "erreurs": []}
    import httpx
    hote_courant = _hote_courant()
    clusters: List[Dict[str, Any]] = []
    erreurs: List[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for pub, priv in cles:
            auth = httpx.DigestAuth(pub, priv)
            etat: Dict[str, str] = {}
            try:
                orgs = await _appel_atlas(client, "/orgs", auth, etat)
                noms_orgs = {o["id"]: o.get("name", o["id"]) for o in (orgs or {}).get("results", [])}
                projets = await _appel_atlas(client, "/groups", auth, etat)
                if projets is None:
                    erreurs.append("Une clé d'API Atlas a été refusée (vérifiez ses droits et la liste d'adresses autorisées).")
                    continue
                for p in projets.get("results", []):
                    nom_org = noms_orgs.get(p.get("orgId"), p.get("orgId", "?"))
                    for c in (await _appel_atlas(client, f"/groups/{p['id']}/clusters", auth, etat) or {}).get("results", []):
                        specs = ((c.get("replicationSpecs") or [{}])[0].get("regionConfigs") or [{}])[0]
                        palier = (specs.get("electableSpecs") or {}).get("instanceSize") \
                            or (c.get("providerSettings") or {}).get("instanceSizeName") or "?"
                        hote = ((c.get("connectionStrings") or {}).get("standardSrv") or "").replace("mongodb+srv://", "").lower()
                        clusters.append({"organisation": nom_org, "projet": p.get("name", ""), "cluster": c.get("name", ""),
                                         "palier": str(palier), "hote": hote, "courant": bool(hote) and hote == hote_courant})
                    for c in (await _appel_atlas(client, f"/groups/{p['id']}/flexClusters", auth, etat) or {}).get("results", []):
                        hote = ((c.get("connectionStrings") or {}).get("standardSrv") or "").replace("mongodb+srv://", "").lower()
                        clusters.append({"organisation": nom_org, "projet": p.get("name", ""), "cluster": c.get("name", ""),
                                         "palier": "FLEX", "hote": hote, "courant": bool(hote) and hote == hote_courant})
            except Exception as e:  # noqa: BLE001 — l'inventaire Atlas ne bloque jamais l'audit
                logger.warning("audit_mongo: inventaire Atlas indisponible (%s)", type(e).__name__)
                erreurs.append("Atlas injoignable pour une des clés d'API.")
    return {"configure": True, "clusters": clusters, "erreurs": erreurs}


# --------------------------------------------------------------------------------------------------------------------
# Audit complet du cluster courant
# --------------------------------------------------------------------------------------------------------------------
async def auditer(db, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Parcourt toutes les bases et collections du cluster auquel `db` est connectée. Met à jour _ETAT pendant le calcul."""
    maintenant = maintenant or datetime.now(timezone.utc)
    client = db.client
    nom_base_sawali = db.name
    try:
        bases = [b for b in await client.list_database_names() if b not in BASES_IGNOREES]
    except Exception:  # noqa: BLE001 — droit « listDatabases » absent : on audite la base de SAWALI seule
        bases = [nom_base_sawali]
    if nom_base_sawali not in bases:
        bases.append(nom_base_sawali)

    # Liste de toutes les collections (pour connaître le total avant de commencer)
    plan: List[Tuple[str, str]] = []
    for nom_base in sorted(bases):
        try:
            for nom in sorted(await client[nom_base].list_collection_names()):
                if not nom.startswith("system."):
                    plan.append((nom_base, nom))
        except Exception as e:  # noqa: BLE001
            logger.warning("audit_mongo: base %s illisible (%s)", nom_base, type(e).__name__)
    _ETAT.update(total=len(plan), fait=0)

    sem = asyncio.Semaphore(PARALLELE)
    lignes: List[Dict[str, Any]] = []

    async def une(nom_base: str, nom: str) -> None:
        async with sem:
            _ETAT["base"] = nom_base
            try:
                res = await analyser_collection(client[nom_base], nom, maintenant)
            except Exception as e:  # noqa: BLE001 — une collection illisible n'arrête pas l'audit
                logger.warning("audit_mongo: %s.%s illisible (%s)", nom_base, nom, type(e).__name__)
                _ETAT["fait"] += 1
                return
            statut, jours, derniere = classer(res, maintenant)
            sur_base_sawali = nom_base == nom_base_sawali
            reference = cite_dans_le_code(nom) if sur_base_sawali else None
            lignes.append({
                "base": nom_base, "collection": nom, "documents": res["documents"], "taille_mo": res["taille_mo"],
                "derniere_insertion": _iso(res["derniere_insertion"]), "champ_date": res["champ_date"],
                "derniere_date_champ": _iso(res["derniere_date_champ"]), "derniere_activite": _iso(derniere),
                "jours_inactivite": jours, "acces_index_ops": res["acces_ops"], "acces_index_depuis": _iso(res["acces_depuis"]),
                "statut": statut, "reference_code": reference,
                "verdict": verdict(statut, reference, res["acces_ops"], sur_base_sawali),
            })
            _ETAT["fait"] += 1

    await asyncio.gather(*(une(b, n) for b, n in plan))
    lignes.sort(key=lambda l: (l["base"], l["collection"]))
    return {"genere_le": _iso(maintenant), "base_sawali": nom_base_sawali, "lignes": lignes, "resume": resume(lignes)}


def resume(lignes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Totaux : par statut, par base, collections candidates à la suppression, plafond du palier."""
    par_statut: Dict[str, int] = {}
    par_base: Dict[str, Dict[str, int]] = {}
    for l in lignes:
        par_statut[l["statut"]] = par_statut.get(l["statut"], 0) + 1
        b = par_base.setdefault(l["base"], {"collections": 0, "documents": 0, "candidates": 0})
        b["collections"] += 1
        b["documents"] += l["documents"] or 0
        if l["verdict"].startswith("Candidate"):
            b["candidates"] += 1
    total = len(lignes)
    return {"total_collections": total, "plafond": PLAFOND_PALIERS_PARTAGES,
            "par_statut": par_statut, "par_base": par_base,
            "candidates": sum(1 for l in lignes if l["verdict"].startswith("Candidate")),
            "a_verifier": sum(1 for l in lignes if l["verdict"].startswith("À vérifier"))}


async def _lancer_audit(db) -> None:
    """Tâche de fond : audit + inventaire Atlas, puis enregistrement du rapport dans `settings`."""
    _ETAT.update(en_cours=True, erreur=None, demarre_le=_iso(datetime.now(timezone.utc)), termine_le=None, fait=0, total=0, base="")
    try:
        rapport = await auditer(db)
        rapport["atlas"] = await inventaire_atlas()
        rapport["hote_courant"] = _hote_courant()
        await db.settings.update_one({"_id": ID_RAPPORT}, {"$set": {"rapport": rapport}}, upsert=True)
    except Exception as e:  # noqa: BLE001
        logger.exception("audit_mongo: échec")
        _ETAT["erreur"] = f"Audit interrompu ({type(e).__name__})"
    finally:
        _ETAT.update(en_cours=False, termine_le=_iso(datetime.now(timezone.utc)))


def csv_rapport(rapport: Dict[str, Any]) -> str:
    """Rapport en CSV (séparateur « ; », ouvrable dans Excel)."""
    colonnes = ["base", "collection", "statut", "verdict", "documents", "taille_mo", "derniere_activite", "jours_inactivite",
                "derniere_insertion", "champ_date", "derniere_date_champ", "acces_index_ops", "acces_index_depuis", "reference_code"]
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(colonnes)
    for l in rapport.get("lignes", []):
        w.writerow([("oui" if l.get(c) else "non") if c == "reference_code" and l.get(c) is not None
                    else ("" if l.get(c) is None else l.get(c)) for c in colonnes])
    return "﻿" + sortie.getvalue()      # BOM : accents corrects dans Excel


# --------------------------------------------------------------------------------------------------------------------
# Routes (administrateur principal seulement : information d'infrastructure)
# --------------------------------------------------------------------------------------------------------------------
def make_audit_mongo_router(*, db, get_super_admin) -> APIRouter:
    router = APIRouter()

    @router.post("/admin/audit-mongo/lancer", tags=["Admin — Audit MongoDB"])
    async def lancer(_: dict = Depends(get_super_admin)):
        """Lance l'audit en arrière-plan et répond tout de suite (jamais de longue attente dans la requête)."""
        global _tache
        if _ETAT["en_cours"]:
            return {"deja_en_cours": True, **_ETAT}
        _ETAT.update(en_cours=True)
        _tache = asyncio.create_task(_lancer_audit(db))
        return {"deja_en_cours": False, **_ETAT}

    @router.get("/admin/audit-mongo/etat", tags=["Admin — Audit MongoDB"])
    async def etat(_: dict = Depends(get_super_admin)):
        """Avancement de l'analyse (collections traitées / total)."""
        return dict(_ETAT)

    @router.get("/admin/audit-mongo/rapport", tags=["Admin — Audit MongoDB"])
    async def rapport(_: dict = Depends(get_super_admin)):
        """Dernier rapport enregistré (None si aucun audit n'a encore été lancé)."""
        doc = await db.settings.find_one({"_id": ID_RAPPORT}) or {}
        return {"rapport": doc.get("rapport"), "atlas_configure": bool(_cles_atlas()), "hote_courant": _hote_courant()}

    @router.get("/admin/audit-mongo/rapport.csv", tags=["Admin — Audit MongoDB"])
    async def rapport_csv(_: dict = Depends(get_super_admin)):
        doc = await db.settings.find_one({"_id": ID_RAPPORT}) or {}
        if not doc.get("rapport"):
            raise HTTPException(404, "Aucun rapport : lancez d'abord l'analyse.")
        return Response(content=csv_rapport(doc["rapport"]).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="audit_collections_mongodb.csv"'})

    return router
