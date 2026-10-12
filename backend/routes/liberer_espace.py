# liberer_espace.py — Lot 113 : bouton unique « 🧹 Libérer l'Espace » (Paramètres, administrateur seulement).
#
# Demande du propriétaire (12/10/2026) : « Je veux un bouton 'Libérer l'Espace' qui va parcourir le cluster
# efficacement (surtout en fonction des règles R2). Il y a trop de boutons dans sauvegardes et je ne sais lequel
# utiliser. » Ce module REGROUPE, sans les dupliquer, les outils de nettoyage existants :
#   • sauvegardes de migration dans R2 (lots 47 et 107, routes/migration_programmation.py) : règle de rétention
#     `choisir_a_purger` et garde-fous `protections` ;
#   • sauvegardes quotidiennes dans R2 (lot 49, routes/sauvegarde_complete.py) : rotation 7 + 4 + 12 `retention` ;
#   • bases obsolètes du cluster Atlas principal (lot 85, routes/quota_atlas.py) : `base_protegee`, `vider_base`.
#
# Deux routes :
#   GET  /api/admin/liberer-espace/analyse   LECTURE SEULE : un plan de nettoyage (ce qui est coché par défaut,
#                                            ce qui est gardé par la règle, ce qui est protégé) + gains estimés.
#   POST /api/admin/liberer-espace/executer  {r2_prefixes, quotidiennes, bases, confirmation: "LIBERER"}
#                                            RE-VÉRIFIE toutes les protections (on ne fait jamais confiance à
#                                            l'écran), supprime, marque, renvoie un rapport détaillé + la jauge APRÈS.
#
# Règles de pré-sélection (ce que l'écran coche tout seul) :
#   - sauvegarde de migration que la rétention enregistrée supprimerait (exactement `choisir_a_purger`) → COCHÉE ;
#   - sauvegarde quotidienne au-delà de la rotation 7 quotidiennes + 4 hebdomadaires + 12 mensuelles → COCHÉE ;
#   - élément supprimable mais gardé par la règle → proposé, NON coché ;
#   - élément protégé (en cours, dernière réussie, fichiers à la racine, plus récente, nom hors motif…) → grisé ;
#   - base Atlas non protégée → proposée, JAMAIS cochée (risque de perte de données).
#
# Aucune nouvelle collection Mongo (le cluster est presque plein) : la dernière exécution est gardée dans
# db.settings {_id: "liberer_espace"}. Aucun identifiant n'est renvoyé, affiché ni journalisé.
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from routes import migration_programmation as mp
from routes import migration_render as mr
from routes import quota_atlas as qa
from routes import sauvegarde_complete as sc

logger = logging.getLogger("sawali.liberer_espace")

DOC_ID = "liberer_espace"           # dernière exécution, dans db.settings (aucune nouvelle collection)
MOT_CONFIRMATION = "LIBERER"        # à taper par l'administrateur (casse, espaces et accents tolérés)
DELAI_RAPPORT = 45                  # secondes maximum pour l'envoi du rapport (WhatsApp / e-mail)
MESSAGE_SANS_IDS = "Enregistrez les identifiants R2 dans « Sauvegardes programmées »"


def _maintenant() -> datetime:
    """Horloge (remplaçable en test)."""
    return datetime.now(timezone.utc)


def mot_confirme(saisie: Any) -> bool:
    """Vrai si l'administrateur a tapé LIBERER (« libérer », « Libérer », «  LIBÉRER  » sont acceptés)."""
    texte = unicodedata.normalize("NFKD", str(saisie or ""))
    texte = "".join(c for c in texte if not unicodedata.combining(c))     # retire les accents (É → E)
    return re.sub(r"\s+", "", texte).upper() == MOT_CONFIRMATION


def _motif(exc: BaseException) -> str:
    """Motif d'une erreur sans aucun jeton (même masquage que le lot 79.5)."""
    return sc._motif(exc, 200)


# ---------------------------------------------------------------------------
# 1. Sauvegardes de MIGRATION dans R2 (lots 47 et 107)
# ---------------------------------------------------------------------------
async def _jobs_par_prefixe(bucket: str) -> Dict[str, List[dict]]:
    """Sauvegardes connues de l'historique, rangées par dossier R2 (même requête que le lot 107)."""
    jobs: Dict[str, List[dict]] = {}
    async for j in mr.db.migration_jobs.find({"cible.r2_bucket": bucket},
                                             {"_id": 0, "id": 1, "statut": 1, "programmee": 1, "cible": 1, "debut": 1}):
        jobs.setdefault((j.get("cible") or {}).get("prefixe"), []).append(j)
    return jobs


async def _contexte_migration() -> Dict[str, Any]:
    """Client R2 + bucket des sauvegardes programmées, ou {"message"} si les identifiants manquent.
    Ne lève jamais : la partie Atlas doit fonctionner même sans R2."""
    try:
        ids = await mp.charger_identifiants()
    except RuntimeError as exc:
        return {"message": f"{exc}. {MESSAGE_SANS_IDS}."}
    except Exception as exc:  # noqa: BLE001
        return {"message": f"Identifiants R2 illisibles ({_motif(exc)}). {MESSAGE_SANS_IDS}."}
    try:
        return {"r2": mp._client_r2(ids), "bucket": ids["r2_bucket"]}
    except Exception as exc:  # noqa: BLE001
        return {"message": f"Connexion à R2 impossible : {_motif(exc)}"}


def _dossier_quotidien(bucket: str) -> Optional[str]:
    """Si les sauvegardes quotidiennes (lot 49) sont rangées dans le MÊME bucket, leur dossier est protégé dans le
    bloc « migration » (il a son propre bloc, avec sa propre règle)."""
    cfg = sc.config_r2()
    if cfg and cfg.get("bucket") == bucket:
        return cfg["prefixe"].strip("/")
    return None


def _protections_migration(dossiers: List[str], jobs: Dict[str, List[dict]], bucket: str) -> Dict[str, str]:
    """Garde-fous du lot 107 (en cours, dernière réussie, racine) + dossier des sauvegardes quotidiennes."""
    raisons = mp.protections(dossiers, jobs)
    raisons.setdefault("(racine)", "fichiers hors dossier")
    quotidien = _dossier_quotidien(bucket)
    if quotidien:
        raisons[quotidien] = "sauvegardes quotidiennes (bloc dédié)"
    return raisons


def classer_migration(stats: Dict[str, Dict[str, Any]], jobs: Dict[str, List[dict]], cfg: Dict[str, Any],
                      maintenant: datetime, bucket: str) -> List[Dict[str, Any]]:
    """Classement de chaque dossier du bucket (fonction pure, testée) :
    « a_supprimer » (coché : la rétention le supprimerait), « garde » (supprimable, non coché), « protege » (grisé)."""
    dossiers = list(stats)
    a_supprimer, gardes = mp.choisir_a_purger([d for d in dossiers if d != "(racine)"], jobs, cfg, maintenant)
    a_supprimer = set(a_supprimer)
    proteges = _protections_migration(dossiers, jobs, bucket)
    lignes = []
    for d, s in stats.items():
        m = mp.RE_PREFIXE.match(d)
        date = (datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()
                if m else s.get("modifie_le"))
        connus = jobs.get(d) or []
        if d in proteges:                                   # la protection l'emporte toujours
            classe, raison = "protege", proteges[d]
        elif d in a_supprimer:
            classe, raison = "a_supprimer", (f"plus de {cfg['retention_jours']} jour(s), hors des "
                                             f"{cfg['garder_min']} dernières réussies")
        else:
            classe, raison = "garde", gardes.get(d) or "gardée par la règle"
        lignes.append({"prefixe": d, "date": date, "objets": s["objets"], "octets": s["octets"],
                       "statut": connus[-1].get("statut") if connus else None,
                       "programmee": any(j.get("programmee") for j in connus),
                       "classe": classe, "raison": raison, "coche": classe == "a_supprimer"})
    lignes.sort(key=lambda x: x["date"] or "", reverse=True)
    return lignes


async def analyser_migration(maintenant: datetime) -> Dict[str, Any]:
    """Bloc « Sauvegardes R2 de migration » : UN seul parcours paginé du bucket (_inventaire_bucket)."""
    ctx = await _contexte_migration()
    if "message" in ctx:
        return {"disponible": False, "message": ctx["message"], "elements": [], "octets_total": 0}
    bucket = ctx["bucket"]
    try:
        stats = await asyncio.to_thread(mp._inventaire_bucket, ctx["r2"], bucket)
    except Exception as exc:  # noqa: BLE001
        return {"disponible": False, "bucket": bucket, "elements": [], "octets_total": 0,
                "message": f"Lecture du bucket R2 impossible : {_motif(exc)}"}
    cfg = await mp.lire_reglage()
    elements = classer_migration(stats, await _jobs_par_prefixe(bucket), cfg, maintenant, bucket)
    return {"disponible": True, "bucket": bucket, "elements": elements,
            "octets_total": sum(e["octets"] for e in elements),
            "regle": f"Rétention {cfg['retention_jours']} jour(s), {cfg['garder_min']} dernière(s) réussie(s) "
                     f"toujours gardée(s)" + ("" if cfg["purge_manuelles"] else ", sauvegardes manuelles non purgées")}


# ---------------------------------------------------------------------------
# 2. Sauvegardes QUOTIDIENNES dans R2 (lot 49)
# ---------------------------------------------------------------------------
def classer_quotidiennes(objets: List[Dict[str, Any]], prefixe: str) -> List[Dict[str, Any]]:
    """Classement des sauvegardes quotidiennes (fonction pure, testée) : au-delà de la rotation → coché ;
    gardée par la rotation → non coché ; la plus récente et tout nom hors motif → protégés."""
    decision = sc.retention([o["cle"] for o in objets])
    datees = sorted(((sc.date_de_cle(o["cle"]), o["cle"]) for o in objets if sc.date_de_cle(o["cle"])), reverse=True)
    plus_recente = datees[0][1] if datees else None
    a_supprimer = set(decision["supprimer"])
    lignes = []
    for o in objets:
        cle, date = o["cle"], sc.date_de_cle(o["cle"])
        if not date or not cle.startswith(prefixe):
            classe, raison = "protege", "nom hors motif (jamais supprimé)"
        elif cle == plus_recente:
            classe, raison = "protege", "la plus récente"
        elif cle in a_supprimer:
            classe, raison = "a_supprimer", "au-delà de la rotation 7 quotidiennes + 4 hebdomadaires + 12 mensuelles"
        else:
            classe, raison = "garde", "gardée : " + ", ".join(decision["garder"].get(cle) or ["rotation"])
        lignes.append({"cle": cle, "nom": cle.rsplit("/", 1)[-1], "date": date.isoformat() if date else None,
                       "octets": int(o.get("taille") or 0), "classe": classe, "raison": raison,
                       "coche": classe == "a_supprimer"})
    lignes.sort(key=lambda x: x["date"] or "", reverse=True)
    return lignes


async def analyser_quotidiennes() -> Dict[str, Any]:
    """Bloc « Sauvegardes quotidiennes » : un listage paginé du dossier des sauvegardes (lot 49)."""
    cfg = sc.config_r2()
    if not cfg:
        return {"disponible": False, "elements": [], "octets_total": 0,
                "message": "Sauvegardes quotidiennes R2 non configurées (variables R2_SAUVEGARDES_* ou R2_STOCKS_*)"}
    try:
        objets = await asyncio.to_thread(sc._lister_r2, sc._FABRIQUE_R2["client"](cfg), cfg)
    except Exception as exc:  # noqa: BLE001
        return {"disponible": False, "bucket": cfg["bucket"], "elements": [], "octets_total": 0,
                "message": f"Lecture de R2 impossible : {_motif(exc)}"}
    elements = classer_quotidiennes(objets, cfg["prefixe"])
    return {"disponible": True, "bucket": cfg["bucket"], "prefixe": cfg["prefixe"], "elements": elements,
            "octets_total": sum(e["octets"] for e in elements),
            "regle": "Rotation : 7 quotidiennes + 4 hebdomadaires + 12 mensuelles ; la plus récente toujours gardée"}


# ---------------------------------------------------------------------------
# 3. Bases du cluster ATLAS principal (lot 85)
# ---------------------------------------------------------------------------
async def _documents(client, nom: str) -> int:
    """Nombre approximatif de documents d'une base (estimation rapide, collection par collection)."""
    total = 0
    for c in await client[nom].list_collection_names():
        try:
            total += int(await client[nom][c].estimated_document_count() or 0)
        except Exception:  # noqa: BLE001 — une collection illisible ne bloque pas l'analyse
            pass
    return total


async def analyser_atlas(db, client, base_courante: str) -> Dict[str, Any]:
    """Bases NON protégées (copies, essais, restes de migration) : proposées, jamais cochées. Bases protégées à part."""
    compte = await qa.compter(client, base_courante)
    autres = await qa.bases_protegees_reglage(db)
    bases, protegees = [], []
    for b in compte["bases"]:
        if qa.base_protegee(b["nom"], base_courante, autres):
            protegees.append({"nom": b["nom"], "collections": b["collections"], "raison": "base en service"})
            continue
        bases.append({"nom": b["nom"], "collections": b["collections"], "documents": await _documents(client, b["nom"]),
                      "classe": "garde", "coche": False,
                      "raison": f"libère {b['collections']} collection(s) — à vérifier avant de supprimer"})
    return {"bases": bases, "protegees": protegees, "methode": compte["methode"], "erreur": compte["erreur"]}


# ---------------------------------------------------------------------------
# Analyse complète (lecture seule)
# ---------------------------------------------------------------------------
async def analyser(db, client, base_courante: str, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Plan de nettoyage complet + jauge actuelle + gains de la sélection par défaut. Ne supprime RIEN."""
    maintenant = maintenant or _maintenant()
    migration = await analyser_migration(maintenant)
    quotidiennes = await analyser_quotidiennes()
    try:
        atlas = await analyser_atlas(db, client, base_courante)
    except Exception as exc:  # noqa: BLE001
        atlas = {"bases": [], "protegees": [], "erreur": f"Analyse du cluster impossible : {_motif(exc)}"}
    try:
        jauge = await qa.mesurer(db, client, base_courante)
    except Exception as exc:  # noqa: BLE001
        jauge = {"erreur": f"Mesure indisponible : {_motif(exc)}"}
    coches = [e for e in migration["elements"] + quotidiennes["elements"] if e["coche"]]
    suivi = await db.settings.find_one({"_id": DOC_ID}, {"_id": 0, "derniere_execution": 1}) or {}
    return {
        "le": maintenant.isoformat(),
        "migration": migration, "quotidiennes": quotidiennes, "atlas": atlas, "jauge": jauge,
        "synthese": {
            "octets_r2": migration["octets_total"] + quotidiennes["octets_total"],
            "octets_liberes": sum(e["octets"] for e in coches),
            "elements_coches": len(coches),
            "collections_liberees": sum(b["collections"] for b in atlas["bases"] if b.get("coche")),
            "collections_liberables": sum(b["collections"] for b in atlas["bases"]),
        },
        "derniere_execution": suivi.get("derniere_execution"),
    }


# ---------------------------------------------------------------------------
# Exécution (suppression après re-vérification complète)
# ---------------------------------------------------------------------------
class ExecutionIn(BaseModel):
    r2_prefixes: List[str] = Field(default_factory=list, max_length=200)    # dossiers de migration
    quotidiennes: List[str] = Field(default_factory=list, max_length=2000)  # clés des sauvegardes quotidiennes
    bases: List[str] = Field(default_factory=list, max_length=20)           # bases Atlas
    confirmation: str = ""


async def _verifier_migration(prefixes: List[str]) -> Dict[str, Any]:
    """Re-vérification des dossiers de migration demandés ; lève 400/404/409 au moindre doute."""
    if not prefixes:
        return {}
    ctx = await _contexte_migration()
    if "message" in ctx:
        raise HTTPException(400, ctx["message"])
    r2, bucket = ctx["r2"], ctx["bucket"]
    try:
        existants = await asyncio.to_thread(mp._lister_prefixes, r2, bucket)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Lecture du bucket R2 impossible : {_motif(exc)}")
    jobs = await _jobs_par_prefixe(bucket)
    proteges = _protections_migration(existants, jobs, bucket)
    for p in prefixes:
        if p in proteges:
            raise HTTPException(409, f"Sauvegarde {p} protégée ({proteges[p]}) : rien n'a été supprimé")
        if p not in existants:
            raise HTTPException(404, f"Sauvegarde introuvable dans R2 : {p} (rien n'a été supprimé)")
    return {"r2": r2, "bucket": bucket}


async def _verifier_quotidiennes(cles: List[str]) -> Dict[str, Any]:
    """Re-vérification des sauvegardes quotidiennes demandées (jamais la plus récente ni un nom hors motif)."""
    if not cles:
        return {}
    cfg = sc.config_r2()
    if not cfg:
        raise HTTPException(400, "Sauvegardes quotidiennes R2 non configurées")
    try:
        client = sc._FABRIQUE_R2["client"](cfg)
        objets = await asyncio.to_thread(sc._lister_r2, client, cfg)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Lecture de R2 impossible : {_motif(exc)}")
    lignes = {e["cle"]: e for e in classer_quotidiennes(objets, cfg["prefixe"])}
    for c in cles:
        if c not in lignes:
            raise HTTPException(404, f"Sauvegarde quotidienne introuvable : {c} (rien n'a été supprimé)")
        if lignes[c]["classe"] == "protege":
            raise HTTPException(409, f"Sauvegarde {lignes[c]['nom']} protégée ({lignes[c]['raison']}) : "
                                     "rien n'a été supprimé")
    return {"client": client, "cfg": cfg, "tailles": {c: lignes[c]["octets"] for c in cles}}


async def _verifier_bases(db, client, base_courante: str, bases: List[str]) -> None:
    """Re-vérification des bases demandées (liste fixe + réglage atlas_bases_protegees + base de SAWALI)."""
    if not bases:
        return
    autres = await qa.bases_protegees_reglage(db)
    for nom in bases:
        if qa.base_protegee(nom, base_courante, autres) or nom in qa.BASES_IGNOREES:
            raise HTTPException(409, f"La base « {nom} » est en service : suppression refusée (rien n'a été supprimé)")
    existantes = await client.list_database_names()
    for nom in bases:
        if nom not in existantes:
            raise HTTPException(404, f"Base introuvable : {nom} (rien n'a été supprimé)")


def _supprimer_cles(client, bucket: str, cles: List[str]) -> List[str]:
    """Supprime des objets R2 par lots de 1000 → clés en erreur."""
    erreurs: List[str] = []
    for i in range(0, len(cles), 1000):
        rep = client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": c} for c in cles[i:i + 1000]],
                                                           "Quiet": True})
        erreurs += [e.get("Key") for e in (rep or {}).get("Errors") or []]
    return erreurs


def _taille(o: int) -> str:
    return mp._taille(o)


def texte_rapport(r: Dict[str, Any]) -> str:
    """Rapport « 🤖 Liluvine » envoyé à l'administrateur (WhatsApp ou e-mail)."""
    lignes = ["🤖 Liluvine — Libération d'espace",
              f"Par {r['par']} le {r['le'][:16].replace('T', ' ')} (UTC)",
              f"R2 : {_taille(r['octets_liberes'])} libéré(s) · Atlas : {r['collections_liberees']} collection(s) libérée(s)"]
    if r.get("jauge_apres", {}).get("total") is not None:
        j = r["jauge_apres"]
        lignes.append(f"Cluster Atlas : {j['total']}/{j['limite']} collections ({j['pourcentage']} %)")
    for e in r["elements"]:
        etat = "✅" if e["ok"] else "❌"
        detail = _taille(e.get("octets") or 0) if e["type"] != "base" else f"{e.get('collections', 0)} collection(s)"
        lignes.append(f"  {etat} {e['libelle']} : {detail}" + (f" — {e['erreur']}" if e.get("erreur") else ""))
    if r["erreurs"]:
        lignes.append(f"⚠️ {r['erreurs']} élément(s) en erreur")
    return "\n".join(lignes)


async def executer(db, client, base_courante: str, corps: ExecutionIn, user: Dict[str, Any],
                   maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Supprime la sélection après RE-VÉRIFICATION complète (rien n'est supprimé si un seul élément est refusé)."""
    if not mot_confirme(corps.confirmation):
        raise HTTPException(400, "Tapez LIBERER pour confirmer la suppression définitive")
    prefixes = list(dict.fromkeys(corps.r2_prefixes))       # sans doublon, ordre conservé
    cles = list(dict.fromkeys(corps.quotidiennes))
    bases = list(dict.fromkeys(corps.bases))
    if not (prefixes or cles or bases):
        raise HTTPException(400, "Rien n'est sélectionné")
    maintenant = maintenant or _maintenant()
    par = user.get("email", "")

    # 1. Toutes les vérifications AVANT la moindre suppression
    mig = await _verifier_migration(prefixes)
    quo = await _verifier_quotidiennes(cles)
    await _verifier_bases(db, client, base_courante, bases)
    logger.warning("[liberer-espace] lancé par %s : %d sauvegarde(s) de migration, %d quotidienne(s), %d base(s)",
                   par, len(prefixes), len(cles), len(bases))

    elements: List[Dict[str, Any]] = []
    # 2. Sauvegardes de migration : même suppression et même marquage que le lot 107
    for p in prefixes:
        try:
            objets, octets, erreurs = await asyncio.to_thread(mp._supprimer_prefixe, mig["r2"], mig["bucket"], p)
            await mr.db.migration_jobs.update_many(
                {"cible.prefixe": p, "cible.r2_bucket": mig["bucket"]},
                {"$set": {"purgee": erreurs == 0, "purgee_le": maintenant.isoformat(),
                          "purge": {"objets": objets, "octets": octets, "erreurs": erreurs, "manuelle": True,
                                    "par": par, "outil": "liberer_espace"}}})
            elements.append({"type": "migration", "libelle": p, "ok": erreurs == 0, "objets": objets, "octets": octets,
                             "erreur": f"{erreurs} fichier(s) non supprimé(s)" if erreurs else None})
        except Exception as exc:  # noqa: BLE001 — on continue avec les autres
            elements.append({"type": "migration", "libelle": p, "ok": False, "objets": 0, "octets": 0,
                             "erreur": _motif(exc)})
        logger.info("[liberer-espace] migration %s par %s : %s", p, par, elements[-1])
    # 3. Sauvegardes quotidiennes : suppression des objets choisis
    if cles:
        try:
            en_erreur = set(await asyncio.to_thread(_supprimer_cles, quo["client"], quo["cfg"]["bucket"], cles))
            erreur_globale = None
        except Exception as exc:  # noqa: BLE001
            en_erreur, erreur_globale = set(cles), _motif(exc)
        for c in cles:
            ok = c not in en_erreur
            elements.append({"type": "quotidienne", "libelle": c.rsplit("/", 1)[-1], "ok": ok,
                             "octets": quo["tailles"][c] if ok else 0,
                             "erreur": None if ok else (erreur_globale or "non supprimée par R2")})
        logger.info("[liberer-espace] %d sauvegarde(s) quotidienne(s) par %s, %d en erreur", len(cles), par, len(en_erreur))
    # 4. Bases Atlas : suppression collection par collection (fonction du lot 85)
    for nom in bases:
        try:
            supprimees, refusees = await qa.vider_base(client, nom)
            if supprimees:
                await qa.noter_purge(db, nom, supprimees, par)
            elements.append({"type": "base", "libelle": nom, "ok": not refusees, "collections": supprimees,
                             "erreur": (f"{len(refusees)} collection(s) refusée(s) : {', '.join(refusees[:5])}"
                                        if refusees else None)})
        except Exception as exc:  # noqa: BLE001
            elements.append({"type": "base", "libelle": nom, "ok": False, "collections": 0, "erreur": _motif(exc)})
        logger.warning("[liberer-espace] base %s purgée par %s : %s", nom, par, elements[-1])

    # 5. Jauge APRÈS, trace de la dernière exécution, rapport à l'administrateur
    try:
        jauge = await qa.mesurer(db, client, base_courante)
    except Exception as exc:  # noqa: BLE001
        jauge = {"erreur": f"Mesure indisponible : {_motif(exc)}"}
    rapport = {"le": maintenant.isoformat(), "par": par, "elements": elements,
               "octets_liberes": sum(e.get("octets") or 0 for e in elements),
               "collections_liberees": sum(e.get("collections") or 0 for e in elements),
               "erreurs": sum(1 for e in elements if not e["ok"]), "jauge_apres": jauge}
    trace = {k: rapport[k] for k in ("le", "par", "octets_liberes", "collections_liberees", "erreurs")}
    trace["elements"] = len(elements)
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"derniere_execution": trace}}, upsert=True)
    try:
        cfg = await mp.lire_reglage()
        rapport["rapport"] = await asyncio.wait_for(
            mp.envoyer_rapport("Libération d'espace", texte_rapport(rapport), cfg, important=True, maintenant=maintenant),
            timeout=DELAI_RAPPORT)
    except Exception as exc:  # noqa: BLE001 — l'envoi du rapport ne doit jamais faire échouer la libération
        logger.warning("[liberer-espace] rapport non envoyé : %s", type(exc).__name__)
        rapport["rapport"] = {"envoye": False, "erreur": "envoi du rapport impossible"}
    logger.warning("[liberer-espace] terminé par %s : %s octet(s) R2, %s collection(s), %s erreur(s)",
                   par, rapport["octets_liberes"], rapport["collections_liberees"], rapport["erreurs"])
    return rapport


# ---------------------------------------------------------------------------
# Routes (branchées dans server_parts/p20_branchement_routeurs.py)
# ---------------------------------------------------------------------------
def _admin_strict(user: dict) -> None:
    """Administrateur SAWALI seulement (même contrôle que la suppression de base du lot 85)."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur")


def setup_liberer_espace_routes(*, db, client, api, get_current_user, base_courante: str) -> None:
    """Routes du bouton « 🧹 Libérer l'Espace »."""

    @api.get("/admin/liberer-espace/analyse", tags=["Admin — Santé"])
    async def route_analyse(user: dict = Depends(get_current_user)):
        """Plan de nettoyage (lecture seule) : R2 de migration, R2 quotidiennes, bases Atlas non protégées."""
        _admin_strict(user)
        return await analyser(db, client, base_courante)

    @api.post("/admin/liberer-espace/executer", tags=["Admin — Santé"])
    async def route_executer(corps: ExecutionIn, user: dict = Depends(get_current_user)):
        """Suppression de la sélection, après confirmation LIBERER et re-vérification de toutes les protections."""
        _admin_strict(user)
        return await executer(db, client, base_courante, corps, user)
