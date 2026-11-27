# volumetrie_hfsql.py — Lot 482 : VOLUMÉTRIE DES TABLES HFSQL, pour dimensionner le cache MongoDB Atlas (logique pure + lecture des schémas ; sans accès réseau).
#
# Demande du propriétaire (27/11/2026) : garder dans Atlas, pendant une semaine, certaines tables d'Aizenta, Biolog et e-Kol (sorte de « streaming ») pour accélérer les réponses.
# Avant de décider quoi garder, il faut des CHIFFRES : combien de lignes par table, combien dans la dernière semaine, et quelle place cela prendrait dans Atlas.
#
# En résumé (pour un développeur WinDev) :
#   - `volumetrie_schemas.json` : pour chaque plateforme (Biolog, Aizenta, e-Kol), chaque table avec son nombre de colonnes, sa taille estimée d'une ligne dans HFSQL et dans Atlas (BSON : valeur + nom du champ + 7 octets),
#     la colonne de date probable, et le nombre de champs mémo (jamais transmis ni mis en cache). Source : les schémas de l'Explorateur de schéma de Loois (schemas/*/structure.json).
#   - l'écran (Paramètres → « 📊 Volumétrie des tables HFSQL ») demande, table par table, deux comptages en lecture seule au client choisi : `SELECT COUNT(*)` total et sur les N derniers jours ;
#   - taille estimée du cache = lignes des N jours × taille estimée d'un document Atlas. C'est une ESTIMATION (types HFSQL → octets moyens) : à confirmer avec les comptages réels.
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

_FICHIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "volumetrie_schemas.json")
_cache: Dict[str, Any] = {}
_RE_TABLE = re.compile(r"^[\w\- éèêëàâäîïôöùûüçÉÈÊËÀÂÄÎÏÔÖÙÛÜÇ]{1,80}$", re.UNICODE)
JOURS_MAX = 60


def schemas() -> Dict[str, Any]:
    """Schémas des trois plateformes (lus une fois)."""
    if not _cache:
        with open(_FICHIER, encoding="utf-8") as f:
            _cache.update(json.load(f))
    return _cache


def plateformes() -> List[Dict[str, Any]]:
    return [{"cle": k, "libelle": v["libelle"], "base_exemple": v["base_exemple"], "tables": len(v["tables"])} for k, v in schemas().items()]


def tables(plateforme: str) -> List[Dict[str, Any]]:
    """Tables d'une plateforme : nom, colonnes, octets par ligne (HFSQL et Atlas), colonne de date probable, champs mémo."""
    p = schemas().get(plateforme)
    if p is None:
        return []
    return [{"nom": t[0], "colonnes": t[1], "octets_hfsql": t[2], "octets_atlas": t[3], "colonne_date": t[4], "memos": t[5]} for t in p["tables"]]


def table_connue(plateforme: str, nom: str) -> Optional[Dict[str, Any]]:
    return next((t for t in tables(plateforme) if t["nom"] == nom), None)


def jours_valides(jours: Any) -> int:
    try:
        n = int(jours)
    except (TypeError, ValueError):
        return 7
    return max(1, min(JOURS_MAX, n))


def sql_total(table: str) -> str:
    return f"SELECT COUNT(*) FROM [{table}]"


def sql_recents(table: str, colonne: str, depuis: date) -> str:
    """Lignes dont la date est >= au jour donné (format texte « AAAAMMJJ », comme les requêtes de Loois sur VenteClinique)."""
    return f"SELECT COUNT(*) FROM [{table}] WHERE [{colonne}] >= '{depuis.strftime('%Y%m%d')}'"


def premiere_valeur(lignes: List[List[Any]]) -> Optional[int]:
    """Valeur entière de la première cellule d'un COUNT(*) ; None si illisible."""
    try:
        return int(float(str(lignes[0][0]).replace(" ", "").replace(" ", "").replace(",", ".")))
    except (IndexError, TypeError, ValueError):
        return None


def estimation_octets(lignes: Optional[int], octets_par_ligne: int) -> Optional[int]:
    return None if lignes is None else lignes * octets_par_ligne


def formater_octets(n: Optional[int]) -> str:
    if n is None:
        return "—"
    for unite, seuil in (("Go", 1 << 30), ("Mo", 1 << 20), ("Ko", 1 << 10)):
        if n >= seuil:
            return f"{n / seuil:.1f} {unite}".replace(".", ",")
    return f"{n} o"
