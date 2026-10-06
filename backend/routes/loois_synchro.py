# loois_synchro.py — Lot 68 : SYNCHRO DES TABLES HFSQL DES CLIENTS LOOIS VERS MONGODB.
#
# Demande du propriétaire (06/10/2026) : « Pour Loois sur e-Kol, remonte les tables Paiements et ElèveEdu. Dès qu'il
# y a un changement sur une des tables, la synchro est faite vers SAWALI. Sur SAWALI / Plateforme / Loois / Synchro
# j'édite la liste des tables que je veux remonter. Pour un client il remonte les données du fichier en JSON pour
# remplir une base MongoDB de même structure que le fichier HFSQL. » + précision : « toutes mes tables ont exactement
# la même structure, et ces structures sont stockées sur mon dépôt GitHub ».
#
# En résumé (pour un développeur WinDev) :
#   - SCHÉMA DE RÉFÉRENCE : les structures publiées par Loois sur GitHub (dépôt ShuyahBF/loois, dossier « schemas/ »)
#     sont embarquées dans backend/loois_schemas/*.json.gz (dépôt privé : aucun jeton dans le code ; script de mise à
#     jour : backend/outils/maj_schemas_loois.py). Elles donnent la liste à cocher, les colonnes, leurs types et la clé ;
#   - CONFIGURATION : une liste de tables PAR APPLICATION (valeur commune à tous les clients, site « * »), avec
#     possibilité de SURCHARGE pour un client (site = code du client envoyé par Loois). Valeurs par défaut :
#     e-Kol → Paiements, ElèveEdu ; Aizenta et Biolog → aucune (leurs envois dédiés existants restent inchangés) ;
#   - STOCKAGE : une collection MongoDB par client / application / table, « hf_<application>_<site>_<table> » ; un
#     document = une ligne HFSQL, avec les NOMS DE COLONNES EXACTS, les valeurs converties d'après le schéma de
#     référence (entiers, nombres, booléens, dates), plus « _hf_cle » (clé unique), « _hf_maj » (dernière mise à jour)
#     et « _hf_lot ». Catalogue : collection « loois_synchro_tables » (nombre de documents, dernière synchro, erreurs…) ;
#   - SÉCURITÉ : TOUTES les routes Loois exigent l'en-tête X-Cle-Loois = LOOIS_SUPPORT_CLE (données d'élèves et de
#     patients) ; seules les tables de la configuration du client sont acceptées ; tailles bornées.
#
# Routes Loois (clé obligatoire) :
#   GET  /api/loois/synchro/config?application=eKol&site=ECOLE-X&machine=PC-1   → tables à synchroniser + poste désigné
#   POST /api/loois/synchro/lot      (corps JSON, éventuellement « Content-Encoding: gzip »)  → accusé de réception
#   POST /api/loois/synchro/etat     → état des tables vu par le poste (lignes en attente, erreur, mode de détection)
# Routes d'administration (rôle admin) : /api/admin/loois-synchro/… (vue, catalogue, config, resynchroniser, données, CSV)
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import re
import secrets
import unicodedata
import zlib
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

from routes.versions_deployees import cle_valide

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
APPLICATIONS = ("eKol", "Aizenta", "Biolog")               # mêmes codes que Loois (TablesSynchronisees)
LIBELLES = {"eKol": "e-Kol", "Aizenta": "Aizenta", "Biolog": "Biolog"}
TABLES_PAR_DEFAUT = {"eKol": ["Paiements", "ElèveEdu"], "Aizenta": [], "Biolog": []}
SITE_DEFAUT = "*"                                           # configuration commune à tous les clients d'une application
DOSSIER_SCHEMAS = Path(__file__).resolve().parents[1] / "loois_schemas"

MAX_LIGNES_LOT = 1000                 # lignes (ajouts + suppressions) par morceau — Loois en envoie 500
MAX_OCTETS_COMPRESSES = 3_000_000     # corps reçu (compressé ou non)
MAX_OCTETS_LOT = 8_000_000            # corps décompressé
MAX_TEXTE = 20_000                    # longueur maximale d'un texte stocké
MAX_COLONNES = 400                    # colonnes par ligne
MAX_CLE = 500                         # longueur d'une clé de ligne
MAX_TABLES_CONFIG = 60                # tables par configuration
MAX_SITES = 500                       # clients différents (protection contre les faux sites)
MAX_DOCUMENTS_TABLE = 2_000_000       # documents par collection
POSTE_BAIL_MINUTES = 30               # un autre poste reprend la synchro si le poste désigné ne se manifeste plus
INTERVALLE_SONDAGE_DEFAUT = 5         # minutes (HFSQL Client/Serveur sans fichiers visibles)
MAX_EXPORT_CSV = 100_000

_LOT = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_MACHINE = re.compile(r"^[A-Za-z0-9 ._\-]{1,80}$")

TYPES_ENTIERS = {"tinyint", "smallint", "integer", "int", "bigint", "unsignedtinyint", "unsignedsmallint",
                 "unsignedint", "unsignedbigint"}
TYPES_REELS = {"numeric", "decimal", "double", "single", "float", "real", "currency", "money"}
TYPES_BOOLEENS = {"boolean", "bool", "bit"}
TYPES_DATES = {"dbdate", "date"}
TYPES_DATES_HEURES = {"dbtimestamp", "datetime", "timestamp", "filetime"}
TYPES_HEURES = {"dbtime", "time"}
TYPES_BINAIRES = {"binary", "varbinary", "longvarbinary", "image"}


def _maintenant() -> datetime:
    """Date et heure actuelles (UTC)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Noms : application, site, collection (logique pure, testée)
# ---------------------------------------------------------------------------
def sans_accents(texte: str) -> str:
    """« ElèveEdu » → « EleveEdu »."""
    return "".join(c for c in unicodedata.normalize("NFD", texte or "") if unicodedata.category(c) != "Mn")


def normaliser(texte: str) -> str:
    """Nom comparable : sans accents, casse, espaces ni ponctuation (« Libellé » = « LIBELLE »)."""
    return "".join(c for c in sans_accents(texte).upper() if c.isalnum())


def normaliser_application(application: Any) -> Optional[str]:
    """« e-Kol », « EKOL », « ekol » → « eKol » ; application inconnue → None."""
    cle = normaliser(str(application or ""))
    return next((a for a in APPLICATIONS if a.upper() == cle), None)


def code_site(texte: Any) -> str:
    """Même règle que Loois (SynchroTablesLogique.CodeSite) : « Lycée Privé X » → « LYCEE-PRIVE-X », 40 caractères au plus."""
    sortie: List[str] = []
    for c in sans_accents(str(texte or "")).upper():
        if ("A" <= c <= "Z") or ("0" <= c <= "9"):
            sortie.append(c)
        elif sortie and sortie[-1] != "-":
            sortie.append("-")
    code = "".join(sortie).strip("-")
    return code[:40].rstrip("-")


def _morceau_nom(texte: str) -> str:
    """Morceau sûr d'un nom de collection : lettres, chiffres et « _ »."""
    return re.sub(r"[^A-Za-z0-9]+", "_", sans_accents(texte)).strip("_") or "x"


def nom_collection(application: str, site: str, table: str) -> str:
    """Collection MongoDB d'une table d'un client : « hf_ekol_ECOLE_X_EleveEdu » (120 caractères au plus)."""
    return f"hf_{_morceau_nom(application).lower()}_{_morceau_nom(site)}_{_morceau_nom(table)}"[:120]


def cle_mongo(nom: str) -> str:
    """Nom de colonne HFSQL conservé TEL QUEL, sauf les caractères interdits par MongoDB (« . » et « $ » initial)."""
    nom = (nom or "").replace(".", "_").replace("\x00", "")
    return ("_" + nom[1:]) if nom.startswith("$") else (nom or "_")


# ---------------------------------------------------------------------------
# Schémas de référence (copie embarquée des structures publiées sur GitHub)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8)
def charger_schema(application: str) -> Dict[str, Any]:
    """Schéma de référence d'une application : {application, base, genere_le, source, tables:[{nom, colonnes}]}.
    Fichier absent ou illisible → schéma vide (la page l'indique ; aucune table ne peut alors être choisie)."""
    try:
        donnees = gzip.decompress((DOSSIER_SCHEMAS / f"{application}.json.gz").read_bytes())
        schema = json.loads(donnees.decode("utf-8"))
        schema["_index"] = {normaliser(t["nom"]): t for t in schema.get("tables", [])}
        return schema
    except (OSError, ValueError):
        return {"application": application, "tables": [], "_index": {}}


def table_reference(application: str, table: str) -> Optional[Dict[str, Any]]:
    """Table du schéma de référence (comparaison sans casse ni accents), ou None."""
    return charger_schema(application)["_index"].get(normaliser(table))


def detecter_cle(table: str, colonnes: List[Dict[str, Any]]) -> List[str]:
    """Même règle que Loois (SynchroTablesLogique.DetecterCle) : « ID » + table, puis « ID… » qui commence le nom
    de la table (le plus long), puis première colonne « ID… » entière ; sinon [] (empreinte de la ligne)."""
    t = normaliser(table)
    for c in colonnes:
        if normaliser(c["nom"]) == "ID" + t:
            return [c["nom"]]
    meilleure = None
    for c in colonnes:
        n = normaliser(c["nom"])
        if n.startswith("ID") and len(n) > 3 and t.startswith(n[2:]) and (meilleure is None or len(n) > len(normaliser(meilleure))):
            meilleure = c["nom"]
    if meilleure:
        return [meilleure]
    if colonnes and normaliser(colonnes[0]["nom"]).startswith("ID") and (colonnes[0].get("type") or "").lower() in TYPES_ENTIERS:
        return [colonnes[0]["nom"]]
    return []


def colonnes_binaires(colonnes: List[Dict[str, Any]]) -> List[str]:
    """Colonnes binaires (photos, images, PDF) : jamais remontées."""
    return [c["nom"] for c in colonnes if (c.get("type") or "").lower() in TYPES_BINAIRES]


# ---------------------------------------------------------------------------
# Conversion des valeurs d'après le schéma de référence (logique pure, testée)
# ---------------------------------------------------------------------------
def _date(valeur: str, avec_heure: bool) -> datetime:
    """« 2026-10-06 » ou « 2026-10-06T08:30:00 » → datetime (sans fuseau : heure du poste = heure de Ouagadougou = UTC)."""
    texte = valeur.strip().replace(" ", "T")
    d = datetime.fromisoformat(texte[:19] if avec_heure else texte[:10])
    return d.replace(tzinfo=None)


def convertir_valeur(valeur: Any, type_hf: str) -> Tuple[Any, bool]:
    """Valeur JSON reçue → valeur MongoDB du bon type. Renvoie (valeur, ok) ; ok = False si la conversion a échoué
    (la valeur est alors gardée telle quelle, en texte, et comptée comme anomalie)."""
    if valeur is None:
        return None, True
    t = (type_hf or "").lower()
    try:
        if t in TYPES_ENTIERS:
            if isinstance(valeur, bool):
                return int(valeur), True
            if isinstance(valeur, (int, float)) and float(valeur).is_integer():
                return int(valeur), True
            texte = str(valeur).strip()
            return (int(texte), True) if re.fullmatch(r"-?\d{1,19}", texte) else (int(float(texte)), True)
        if t in TYPES_REELS:
            n = float(str(valeur).replace(",", ".")) if not isinstance(valeur, (int, float)) else float(valeur)
            return (n, True) if math.isfinite(n) else (None, False)
        if t in TYPES_BOOLEENS:
            if isinstance(valeur, bool):
                return valeur, True
            texte = str(valeur).strip().lower()
            if texte in ("1", "true", "vrai", "oui"):
                return True, True
            if texte in ("0", "false", "faux", "non", ""):
                return False, True
            return str(valeur), False
        if t in TYPES_DATES:
            return _date(str(valeur), False), True
        if t in TYPES_DATES_HEURES:
            return _date(str(valeur), True), True
        if t in TYPES_HEURES or t in ("char", "wchar", "varchar", "varwchar", "longvarchar", "longvarwchar", "bstr", "guid"):
            return (valeur if isinstance(valeur, str) else str(valeur))[:MAX_TEXTE], True
    except (ValueError, TypeError, OverflowError):
        return (str(valeur)[:MAX_TEXTE] if not isinstance(valeur, (dict, list)) else None), False
    # Type inconnu (schéma Aizenta incomplet…) : valeur simple gardée telle quelle
    if isinstance(valeur, str):
        return valeur[:MAX_TEXTE], True
    if isinstance(valeur, (bool, int)):
        return valeur, True
    if isinstance(valeur, float):
        return (valeur, True) if math.isfinite(valeur) else (None, False)
    return None, False


def convertir_ligne(ligne: Dict[str, Any], colonnes_ref: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], int, List[str]]:
    """Ligne reçue → document MongoDB. Renvoie (document, anomalies de conversion, colonnes absentes du schéma).
    Colonnes binaires du schéma écartées ; colonnes inconnues gardées (valeur simple) et signalées."""
    types = {normaliser(c["nom"]): (c.get("type") or "") for c in colonnes_ref}
    doc: Dict[str, Any] = {}
    anomalies = 0
    inconnues: List[str] = []
    for nom, valeur in list(ligne.items())[:MAX_COLONNES]:
        if not isinstance(nom, str) or not nom or nom.startswith("_hf_"):
            continue
        type_hf = types.get(normaliser(nom))
        if type_hf is None and colonnes_ref:
            inconnues.append(nom)
        if (type_hf or "").lower() in TYPES_BINAIRES:
            continue
        if isinstance(valeur, (dict, list)):
            anomalies += 1
            continue
        converti, ok = convertir_valeur(valeur, type_hf or "")
        if not ok:
            anomalies += 1
        doc[cle_mongo(nom)] = converti
    return doc, anomalies, inconnues


# ---------------------------------------------------------------------------
# Configuration (logique pure, testée)
# ---------------------------------------------------------------------------
def config_par_defaut(application: str) -> Dict[str, Any]:
    """Configuration intégrée d'une application (utilisée tant que le propriétaire n'a rien enregistré)."""
    return {"application": application, "site": SITE_DEFAUT, "actif": bool(TABLES_PAR_DEFAUT.get(application)),
            "tables": [{"nom": n, "cle": [], "colonnes_ignorees": []} for n in TABLES_PAR_DEFAUT.get(application, [])],
            "intervalle_sondage_minutes": INTERVALLE_SONDAGE_DEFAUT, "integree": True}


def config_effective(application: str, defaut: Optional[Dict[str, Any]], surcharge: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Configuration appliquée à un client : sa surcharge si elle existe, sinon la valeur commune de l'application,
    sinon la configuration intégrée. Renvoie aussi « origine » (client / application / integree)."""
    if surcharge:
        return {**surcharge, "origine": "client"}
    if defaut:
        return {**defaut, "origine": "application"}
    return {**config_par_defaut(application), "origine": "integree"}


def nettoyer_config(application: str, corps: Dict[str, Any]) -> Dict[str, Any]:
    """Valide une configuration saisie sur la page Synchro. Lève ValueError (message clair) si une table n'existe
    pas dans le schéma de référence, si une colonne clé n'existe pas, ou si la liste est trop longue."""
    tables_recues = corps.get("tables") or []
    if not isinstance(tables_recues, list):
        raise ValueError("liste de tables attendue")
    if len(tables_recues) > MAX_TABLES_CONFIG:
        raise ValueError(f"{MAX_TABLES_CONFIG} tables au plus")
    tables: List[Dict[str, Any]] = []
    vues = set()
    for t in tables_recues:
        nom = (t.get("nom") if isinstance(t, dict) else t) or ""
        ref = table_reference(application, str(nom))
        if not ref:
            raise ValueError(f"table « {nom} » inconnue du schéma de référence {LIBELLES[application]}")
        if normaliser(ref["nom"]) in vues:
            continue
        vues.add(normaliser(ref["nom"]))
        noms_ref = {normaliser(c["nom"]): c["nom"] for c in ref.get("colonnes", [])}
        def colonnes_existantes(liste: Any, quoi: str) -> List[str]:
            sortie = []
            for c in (liste or []) if isinstance(liste, list) else []:
                reel = noms_ref.get(normaliser(str(c)))
                if noms_ref and not reel:
                    raise ValueError(f"{quoi} « {c} » absente de la table {ref['nom']}")
                sortie.append(reel or str(c))
            return sortie[:10] if quoi == "colonne clé" else sortie[:100]
        tables.append({"nom": ref["nom"],
                       "cle": colonnes_existantes(t.get("cle") if isinstance(t, dict) else None, "colonne clé"),
                       "colonnes_ignorees": colonnes_existantes(t.get("colonnes_ignorees") if isinstance(t, dict) else None, "colonne")})
    try:
        intervalle = int(corps.get("intervalle_sondage_minutes") or INTERVALLE_SONDAGE_DEFAUT)
    except (TypeError, ValueError):
        intervalle = INTERVALLE_SONDAGE_DEFAUT
    return {"actif": bool(corps.get("actif", True)), "tables": tables,
            "intervalle_sondage_minutes": max(1, min(120, intervalle))}


def tables_pour_loois(application: str, config: Dict[str, Any], jetons: Dict[str, str]) -> List[Dict[str, Any]]:
    """Tables envoyées à Loois : nom exact, clé (choisie, sinon détectée sur le schéma de référence), colonnes
    ignorées (choisies + binaires du schéma) et jeton « Resynchroniser tout »."""
    sortie = []
    for t in config.get("tables") or []:
        ref = table_reference(application, t["nom"]) or {"nom": t["nom"], "colonnes": []}
        colonnes = ref.get("colonnes", [])
        ignorees = list(dict.fromkeys((t.get("colonnes_ignorees") or []) + colonnes_binaires(colonnes)))
        sortie.append({"nom": ref["nom"], "cle": t.get("cle") or detecter_cle(ref["nom"], colonnes),
                       "colonnes_ignorees": ignorees, "resynchro_jeton": jetons.get(normaliser(ref["nom"]), "")})
    return sortie


def valider_lot(corps: Any) -> Dict[str, Any]:
    """Logique pure (testée) : morceau reçu de Loois, nettoyé. Lève ValueError si un champ manque ou dépasse."""
    if not isinstance(corps, dict):
        raise ValueError("objet JSON attendu")
    application = normaliser_application(corps.get("application"))
    if not application:
        raise ValueError("application inconnue")
    site = code_site(corps.get("site"))
    if not site:
        raise ValueError("site manquant")
    table = str(corps.get("table") or "").strip()
    if not table or len(table) > 120:
        raise ValueError("table manquante")
    lot = str(corps.get("lot") or "")
    if not _LOT.match(lot):
        raise ValueError("numéro de lot invalide")
    sequence = corps.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence <= 1_000_000:
        raise ValueError("séquence invalide")
    upserts = corps.get("upserts") or []
    suppressions = corps.get("suppressions") or []
    if not isinstance(upserts, list) or not isinstance(suppressions, list):
        raise ValueError("listes upserts / suppressions attendues")
    if len(upserts) + len(suppressions) > MAX_LIGNES_LOT:
        raise ValueError(f"{MAX_LIGNES_LOT} lignes au plus par morceau")
    propres = []
    for u in upserts:
        if not isinstance(u, dict) or not isinstance(u.get("ligne"), dict):
            raise ValueError("ligne invalide")
        cle = str(u.get("cle") or "")
        if not cle or len(cle) > MAX_CLE:
            raise ValueError("clé de ligne invalide")
        propres.append({"cle": cle, "ligne": u["ligne"]})
    cles_suppr = [str(s) for s in suppressions if isinstance(s, (str, int)) and str(s) and len(str(s)) <= MAX_CLE]
    machine = str(corps.get("machine") or "").strip()[:80]
    try:
        lignes_source = max(0, int(corps.get("lignes_source") or 0))
    except (TypeError, ValueError):
        lignes_source = 0
    return {"application": application, "site": site, "table": table, "lot": lot, "sequence": sequence,
            "complet": bool(corps.get("complet")), "fin": bool(corps.get("fin")), "machine": machine,
            "cle": [str(c)[:120] for c in (corps.get("cle") or []) if isinstance(c, str)][:10],
            "lignes_source": lignes_source, "upserts": propres, "suppressions": cles_suppr}


def lire_corps(brut: bytes, encodage: Optional[str]) -> Any:
    """Corps reçu → JSON ; « Content-Encoding: gzip » décompressé avec une limite (protection « bombe gzip »).
    Lève ValueError si trop gros ou illisible."""
    if len(brut) > MAX_OCTETS_COMPRESSES:
        raise ValueError("corps trop volumineux")
    if (encodage or "").lower().strip() == "gzip":
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        brut = d.decompress(brut, MAX_OCTETS_LOT + 1)
        if len(brut) > MAX_OCTETS_LOT or d.unconsumed_tail:
            raise ValueError("morceau décompressé trop volumineux")
    elif len(brut) > MAX_OCTETS_LOT:
        raise ValueError("corps trop volumineux")
    try:
        return json.loads(brut.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("JSON illisible") from exc


def json_sur(valeur: Any) -> Any:
    """Document MongoDB → JSON (dates en texte ISO, identifiants retirés)."""
    if isinstance(valeur, datetime):
        return valeur.isoformat()
    if isinstance(valeur, dict):
        return {k: json_sur(v) for k, v in valeur.items() if k != "_id"}
    if isinstance(valeur, list):
        return [json_sur(v) for v in valeur]
    return valeur


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def setup_loois_synchro_routes(*, db, api, get_current_user) -> None:
    """Branche les routes du lot 68 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException
    from fastapi.responses import Response
    from pymongo import DeleteMany, ReplaceOne

    index_crees: set = set()   # collections dont l'index « _hf_cle » est déjà créé (dans ce processus)

    def verifier_cle(request: Request) -> None:
        """Clé du support OBLIGATOIRE (données d'élèves / patients)."""
        if not cle_valide(request.headers.get("X-Cle-Loois")):
            raise HTTPException(status_code=401, detail="clé du support Loois absente ou refusée")

    def admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    def application_ou_422(valeur: Any) -> str:
        app = normaliser_application(valeur)
        if not app:
            raise HTTPException(status_code=422, detail="application inconnue (eKol, Aizenta ou Biolog)")
        return app

    async def lire_config(application: str, site: str) -> Dict[str, Any]:
        """Configuration effective d'un client (surcharge, sinon valeur commune, sinon intégrée)."""
        defaut = await db.loois_synchro_config.find_one({"application": application, "site": SITE_DEFAUT}, {"_id": 0})
        surcharge = None
        if site != SITE_DEFAUT:
            surcharge = await db.loois_synchro_config.find_one({"application": application, "site": site}, {"_id": 0})
        return config_effective(application, defaut, surcharge)

    async def jetons_resynchro(application: str, site: str) -> Dict[str, str]:
        """Jetons « Resynchroniser tout » des tables du client (table normalisée → jeton)."""
        jetons = {}
        async for e in db.loois_synchro_tables.find({"application": application, "site": site},
                                                    {"_id": 0, "table": 1, "resynchro_jeton": 1}):
            if e.get("resynchro_jeton"):
                jetons[normaliser(e["table"])] = e["resynchro_jeton"]
        return jetons

    # ------------------------------------------------------------------ Loois
    @api.get("/loois/synchro/config", tags=["Loois synchro"])
    async def config_loois(request: Request, application: str, site: str, machine: str = ""):
        """Tables à synchroniser pour ce client + poste désigné (un seul poste synchronise un site à la fois)."""
        verifier_cle(request)
        app = application_ou_422(application)
        code = code_site(site)
        if not code:
            raise HTTPException(status_code=422, detail="site manquant")
        poste = machine.strip()[:80]
        if poste and not _MACHINE.match(poste):
            raise HTTPException(status_code=422, detail="nom de machine invalide")
        config = await lire_config(app, code)
        maintenant = _maintenant()
        # Poste désigné : le premier qui se présente ; un autre prend le relais après POSTE_BAIL_MINUTES de silence
        cle_poste = {"application": app, "site": code}
        bail = await db.loois_synchro_postes.find_one(cle_poste, {"_id": 0})
        if not bail and await db.loois_synchro_postes.count_documents({}) >= MAX_SITES:
            raise HTTPException(status_code=429, detail="trop de sites enregistrés")
        poste_actif = False
        designe = (bail or {}).get("machine") or ""
        if poste:
            expire = True
            try:
                expire = datetime.fromisoformat((bail or {}).get("vu_le") or "") < maintenant - timedelta(minutes=POSTE_BAIL_MINUTES)
            except ValueError:
                pass
            if not bail or designe.upper() == poste.upper() or expire:
                poste_actif, designe = True, poste
                await db.loois_synchro_postes.update_one(cle_poste, {"$set": {**cle_poste, "machine": poste, "vu_le": maintenant.isoformat()},
                                                                     "$setOnInsert": {"premiere_fois": maintenant.isoformat()}}, upsert=True)
        schema = charger_schema(app)
        return {"application": app, "site": code, "actif": bool(config.get("actif")) and bool(config.get("tables")),
                "poste_actif": poste_actif, "poste_designe": designe,
                "intervalle_sondage_minutes": config.get("intervalle_sondage_minutes") or INTERVALLE_SONDAGE_DEFAUT,
                "origine": config.get("origine"), "schema_genere_le": schema.get("genere_le"),
                "tables": tables_pour_loois(app, config, await jetons_resynchro(app, code))}

    @api.post("/loois/synchro/lot", tags=["Loois synchro"])
    async def recevoir_lot(request: Request):
        """Un morceau de différences (ajouts / modifications / suppressions). Idempotent : (lot, séquence) déjà reçu →
        même réponse, rien n'est rejoué."""
        verifier_cle(request)
        try:
            lot = valider_lot(lire_corps(await request.body(), request.headers.get("Content-Encoding")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        app, site = lot["application"], lot["site"]
        config = await lire_config(app, site)
        if not config.get("actif"):
            raise HTTPException(status_code=403, detail="synchro désactivée pour ce client")
        table_cfg = next((t for t in config.get("tables") or [] if normaliser(t["nom"]) == normaliser(lot["table"])), None)
        if not table_cfg:
            raise HTTPException(status_code=403, detail=f"table « {lot['table']} » non configurée pour ce client")
        table = table_cfg["nom"]
        id_lot = f"{app}|{site}|{normaliser(table)}|{lot['lot']}|{lot['sequence']}"
        deja = await db.loois_synchro_lots.find_one({"id": id_lot}, {"_id": 0, "resultat": 1})
        if deja:
            return {**(deja.get("resultat") or {}), "deja_recu": True}

        if "loois_synchro_lots" not in index_crees:
            # Accusés de réception gardés 30 jours (suffisant pour rejouer un renvoi), puis effacés par MongoDB
            try:
                await db.loois_synchro_lots.create_index("id", unique=True)
                await db.loois_synchro_lots.create_index("recu_le", expireAfterSeconds=30 * 24 * 3600)
            except Exception:  # noqa: BLE001
                pass
            index_crees.add("loois_synchro_lots")
        collection_nom = nom_collection(app, site, table)
        collection = db[collection_nom]
        if collection_nom not in index_crees:
            try:
                await collection.create_index("_hf_cle", unique=True)
                await collection.create_index("_hf_complet")
            except Exception:  # noqa: BLE001 — index déjà présent ou base simulée
                pass
            index_crees.add(collection_nom)
        if lot["upserts"] and await collection.estimated_document_count() + len(lot["upserts"]) > MAX_DOCUMENTS_TABLE:
            raise HTTPException(status_code=413, detail=f"plus de {MAX_DOCUMENTS_TABLE} lignes pour cette table")

        ref = table_reference(app, table) or {"colonnes": []}
        maintenant = _maintenant()
        operations, anomalies, inconnues = [], 0, set()
        for u in lot["upserts"]:
            doc, n, inc = convertir_ligne(u["ligne"], ref.get("colonnes", []))
            anomalies += n
            inconnues.update(inc)
            doc.update({"_hf_cle": u["cle"], "_hf_maj": maintenant, "_hf_lot": lot["lot"]})
            if lot["complet"]:
                doc["_hf_complet"] = lot["lot"]
            operations.append(ReplaceOne({"_hf_cle": u["cle"]}, doc, upsert=True))
        if lot["suppressions"]:
            operations.append(DeleteMany({"_hf_cle": {"$in": lot["suppressions"]}}))
        supprimees = 0
        if operations:
            resultat_bulk = await collection.bulk_write(operations, ordered=True)
            supprimees = resultat_bulk.deleted_count
        retirees = 0
        if lot["complet"] and lot["fin"]:
            # Fin d'un envoi complet : les lignes qui n'ont pas été renvoyées n'existent plus dans HFSQL
            retirees = (await collection.delete_many({"_hf_complet": {"$ne": lot["lot"]}})).deleted_count
        nb_documents = await collection.count_documents({})
        resultat = {"ok": True, "upserts": len(lot["upserts"]), "suppressions": supprimees, "retirees": retirees,
                    "nb_documents": nb_documents, "anomalies": anomalies}
        cle_cat = {"application": app, "site": site, "table": table}
        await db.loois_synchro_tables.update_one(cle_cat, {
            "$set": {**cle_cat, "collection": collection_nom, "cle_colonnes": lot["cle"], "nb_documents": nb_documents,
                     "derniere_synchro": maintenant.isoformat(), "derniere_machine": lot["machine"],
                     "lignes_source": lot["lignes_source"], "dernier_lot": lot["lot"], "derniere_erreur": None},
            "$inc": {"anomalies_conversion": anomalies, "lignes_recues": len(lot["upserts"])},
            "$addToSet": {"colonnes_inconnues": {"$each": sorted(inconnues)[:50]}},
            "$setOnInsert": {"premiere_synchro": maintenant.isoformat()},
        }, upsert=True)
        await db.loois_synchro_lots.insert_one({"id": id_lot, "resultat": resultat, "recu_le": maintenant})
        return {**resultat, "deja_recu": False}

    @api.post("/loois/synchro/etat", tags=["Loois synchro"])
    async def etat_loois(request: Request):
        """État vu par le poste (lignes en attente, erreur, mode de détection) — affiché sur la page Synchro."""
        verifier_cle(request)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        app = application_ou_422((corps or {}).get("application"))
        site = code_site((corps or {}).get("site"))
        if not site:
            raise HTTPException(status_code=422, detail="site manquant")
        config = await lire_config(app, site)
        configurees = {normaliser(t["nom"]): t["nom"] for t in config.get("tables") or []}
        maj = 0
        for t in ((corps or {}).get("tables") or [])[:MAX_TABLES_CONFIG]:
            if not isinstance(t, dict) or normaliser(str(t.get("nom") or "")) not in configurees:
                continue
            table = configurees[normaliser(str(t["nom"]))]
            cle_cat = {"application": app, "site": site, "table": table}
            try:
                en_attente = max(0, int(t.get("en_attente") or 0))
            except (TypeError, ValueError):
                en_attente = 0
            await db.loois_synchro_tables.update_one(cle_cat, {"$set": {
                **cle_cat, "collection": nom_collection(app, site, table), "en_attente": en_attente,
                "erreur_poste": (str(t.get("erreur") or "")[:300] or None),
                "mode_detection": str(t.get("mode_detection") or "")[:20] or None,
                "derniere_verification": str(t.get("derniere_verification") or "")[:40] or None,
                "machine_etat": str((corps or {}).get("machine") or "")[:80], "etat_recu_le": _maintenant().isoformat()}}, upsert=True)
            maj += 1
        return {"ok": True, "tables": maj}

    # ------------------------------------------------------------------ Administration
    @api.get("/admin/loois-synchro/catalogue", tags=["Loois synchro"])
    async def catalogue(application: str, table: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Schéma de référence : liste des tables (nom, nombre de colonnes, clé détectée) ; avec « table », ses colonnes."""
        admin(user)
        app = application_ou_422(application)
        schema = charger_schema(app)
        if table:
            ref = table_reference(app, table)
            if not ref:
                raise HTTPException(status_code=404, detail="table inconnue")
            return {**{k: v for k, v in ref.items()}, "cle_detectee": detecter_cle(ref["nom"], ref.get("colonnes", []))}
        return {"application": app, "libelle": LIBELLES[app], "base": schema.get("base"), "genere_le": schema.get("genere_le"),
                "source": schema.get("source"),
                "tables": [{"nom": t["nom"], "nb_colonnes": len(t.get("colonnes", [])),
                            "cle_detectee": detecter_cle(t["nom"], t.get("colonnes", [])),
                            "binaires": colonnes_binaires(t.get("colonnes", []))} for t in schema.get("tables", [])]}

    @api.get("/admin/loois-synchro/vue", tags=["Loois synchro"])
    async def vue(application: str, user: dict = Depends(get_current_user)):
        """Page Synchro : configuration commune, clients connus (surcharges, poste désigné, état de chaque table)."""
        admin(user)
        app = application_ou_422(application)
        defaut = await db.loois_synchro_config.find_one({"application": app, "site": SITE_DEFAUT}, {"_id": 0})
        surcharges = {c["site"]: c async for c in db.loois_synchro_config.find({"application": app, "site": {"$ne": SITE_DEFAUT}}, {"_id": 0})}
        postes = {p["site"]: p async for p in db.loois_synchro_postes.find({"application": app}, {"_id": 0})}
        etats: Dict[str, List[Dict[str, Any]]] = {}
        async for e in db.loois_synchro_tables.find({"application": app}, {"_id": 0}):
            etats.setdefault(e["site"], []).append(e)
        sites = sorted(set(surcharges) | set(postes) | set(etats))
        clients = []
        for s in sites:
            effective = config_effective(app, defaut, surcharges.get(s))
            configurees = [t["nom"] for t in effective.get("tables") or []]
            par_table = {normaliser(e["table"]): e for e in etats.get(s, [])}
            clients.append({
                "site": s, "surcharge": surcharges.get(s), "origine": effective["origine"], "actif": bool(effective.get("actif")),
                "poste": postes.get(s),
                "tables": [{**(par_table.get(normaliser(n)) or {"table": n, "collection": nom_collection(app, s, n)}), "configuree": True}
                           for n in configurees]
                          + [{**e, "configuree": False} for k, e in par_table.items() if k not in {normaliser(n) for n in configurees}],
            })
        return {"application": app, "libelle": LIBELLES[app], "defaut": config_effective(app, defaut, None),
                "defaut_integre": config_par_defaut(app), "clients": clients, "poste_bail_minutes": POSTE_BAIL_MINUTES}

    @api.put("/admin/loois-synchro/config", tags=["Loois synchro"])
    async def enregistrer_config(request: Request, user: dict = Depends(get_current_user)):
        """Enregistre la liste des tables d'une application (site « * » = tous les clients) ou d'un client."""
        admin(user)
        corps = await request.json()
        app = application_ou_422((corps or {}).get("application"))
        site = SITE_DEFAUT if (corps or {}).get("site") in (None, "", SITE_DEFAUT) else code_site(corps.get("site"))
        if not site:
            raise HTTPException(status_code=422, detail="code client invalide")
        try:
            propre = nettoyer_config(app, corps or {})
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        doc = {"application": app, "site": site, **propre, "maj_le": _maintenant().isoformat(),
               "maj_par": user.get("full_name") or user.get("email") or user.get("id")}
        await db.loois_synchro_config.update_one({"application": app, "site": site}, {"$set": doc}, upsert=True)
        return {"ok": True, "config": doc}

    @api.delete("/admin/loois-synchro/config", tags=["Loois synchro"])
    async def supprimer_config(application: str, site: str, user: dict = Depends(get_current_user)):
        """Retire la surcharge d'un client (il reprend la liste commune) ; site « * » = retour à la liste intégrée."""
        admin(user)
        app = application_ou_422(application)
        code = SITE_DEFAUT if site == SITE_DEFAUT else code_site(site)
        r = await db.loois_synchro_config.delete_one({"application": app, "site": code})
        return {"ok": True, "supprimee": r.deleted_count}

    @api.post("/admin/loois-synchro/resynchroniser", tags=["Loois synchro"])
    async def resynchroniser(request: Request, user: dict = Depends(get_current_user)):
        """« Resynchroniser tout » : nouveau jeton → Loois renvoie la (ou les) table(s) en entier au prochain passage."""
        admin(user)
        corps = await request.json()
        app = application_ou_422((corps or {}).get("application"))
        site = code_site((corps or {}).get("site"))
        if not site:
            raise HTTPException(status_code=422, detail="code client attendu")
        config = await lire_config(app, site)
        tables = [t["nom"] for t in config.get("tables") or []]
        if (corps or {}).get("table"):
            tables = [n for n in tables if normaliser(n) == normaliser(str(corps["table"]))]
            if not tables:
                raise HTTPException(status_code=404, detail="table non configurée pour ce client")
        jeton = secrets.token_hex(8)
        for n in tables:
            cle_cat = {"application": app, "site": site, "table": n}
            await db.loois_synchro_tables.update_one(cle_cat, {"$set": {**cle_cat, "collection": nom_collection(app, site, n),
                                                                        "resynchro_jeton": jeton, "resynchro_demandee_le": _maintenant().isoformat()}},
                                                     upsert=True)
        return {"ok": True, "tables": tables, "jeton": jeton}

    async def requete_donnees(app: str, site: str, table: str, recherche: str) -> Tuple[Any, Dict[str, Any], List[str]]:
        """Collection, filtre de recherche et colonnes affichées (ordre du schéma de référence)."""
        ref = table_reference(app, table) or {"nom": table, "colonnes": []}
        collection = db[nom_collection(app, site, ref["nom"])]
        colonnes = [cle_mongo(c["nom"]) for c in ref.get("colonnes", []) if (c.get("type") or "").lower() not in TYPES_BINAIRES]
        if not colonnes:   # schéma inconnu : colonnes du premier document
            premier = await collection.find_one({}, {"_id": 0})
            colonnes = [k for k in (premier or {}) if not k.startswith("_hf_")]
        filtre: Dict[str, Any] = {}
        texte = (recherche or "").strip()[:100]
        if texte:
            motif = {"$regex": re.escape(texte), "$options": "i"}
            textes = [cle_mongo(c["nom"]) for c in ref.get("colonnes", []) if (c.get("type") or "").lower() in ("char", "wchar", "")][:40]
            filtre = {"$or": [{c: motif} for c in (textes or colonnes[:40])] + [{"_hf_cle": motif}]}
        return collection, filtre, colonnes

    @api.get("/admin/loois-synchro/donnees", tags=["Loois synchro"])
    async def donnees(application: str, site: str, table: str, page: int = 1, par_page: int = 50, recherche: str = "",
                      user: dict = Depends(get_current_user)):
        """Lecture seule : documents d'une table d'un client, paginés, avec recherche."""
        admin(user)
        app = application_ou_422(application)
        code = code_site(site)
        collection, filtre, colonnes = await requete_donnees(app, code, table, recherche)
        par_page = max(1, min(200, par_page))
        page = max(1, page)
        total = await collection.count_documents(filtre)
        docs = [json_sur(d) async for d in collection.find(filtre, {"_id": 0}).sort("_hf_cle", 1).skip((page - 1) * par_page).limit(par_page)]
        return {"application": app, "site": code, "table": table, "collection": nom_collection(app, code, table),
                "colonnes": colonnes, "total": total, "page": page, "par_page": par_page, "documents": docs}

    @api.get("/admin/loois-synchro/export-csv", tags=["Loois synchro"])
    async def export_csv(application: str, site: str, table: str, recherche: str = "", user: dict = Depends(get_current_user)):
        """Export CSV (séparateur « ; », UTF-8 avec BOM pour Excel) des documents filtrés."""
        admin(user)
        app = application_ou_422(application)
        code = code_site(site)
        collection, filtre, colonnes = await requete_donnees(app, code, table, recherche)
        sortie = io.StringIO()
        ecrivain = csv.writer(sortie, delimiter=";")
        ecrivain.writerow(colonnes + ["_hf_cle", "_hf_maj"])
        async for d in collection.find(filtre, {"_id": 0}).sort("_hf_cle", 1).limit(MAX_EXPORT_CSV):
            d = json_sur(d)
            ecrivain.writerow(["" if d.get(c) is None else d.get(c) for c in colonnes + ["_hf_cle", "_hf_maj"]])
        nom = f"{nom_collection(app, code, table)}.csv"
        return Response(content="﻿" + sortie.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nom}"'})
