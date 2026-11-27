# sonde_communaute.py — Lot 485 : ESPACE COMMUN de la sonde réseau (logique PURE : zones de 2 km, cellules d'agrégation, jetons, synthèse).
#
# Principe (décisions du propriétaire, 27/11/2026) :
#   - Gmail OBLIGATOIRE : chaque téléphone s'identifie par un compte Google (flux OpenID Connect déjà en place, cible « sonde ») ;
#   - consentement écrit à la première utilisation (version gardée) : sans accord, pas de connexion ;
#   - le LIEU n'est jamais précis : le téléphone envoie le centre d'une zone de 2 km (grille de 0,02°), le serveur la recalcule et ne garde JAMAIS
#     une position plus fine ; le partage du lieu est activé par défaut et désactivable sur le téléphone ;
#   - SAWALI ne garde PAS les mesures une à une : il additionne dans des CELLULES (jour × zone × type de connexion × opérateur), ce qui suffit pour la
#     synthèse par lieu, type de connexion et opérateur, et ne permet pas de suivre une personne.
# Stockage : deux fiches de `settings` (`sonde_participants`, `sonde_communaute`), aucune nouvelle collection (cluster MongoDB plein, règle du propriétaire).
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

DOC_PARTICIPANTS = "sonde_participants"
DOC_COMMUNAUTE = "sonde_communaute"
CONSENTEMENT_VERSION = 2            # change quand le texte du consentement change : les téléphones le redemandent
# Version 2 (27/11/2026, décision du propriétaire) : le partage du lieu approximatif devient PERMANENT et non modifiable dans l'application (Sonde Réseau 1.7).
# Transition : la version 1 (texte « vous pouvez le désactiver », applications 1.5 et 1.6) reste ACCEPTÉE pour ne pas couper les téléphones déjà inscrits ;
# les nouvelles applications exigent la version 2. À retirer de CONSENTEMENTS_ACCEPTES quand plus aucune application 1.5 / 1.6 n'est utilisée.
CONSENTEMENTS_ACCEPTES = (1, 2)
PAS_ZONE = 0.02                     # degrés : ≈ 2,2 km de côté (grille fixe, identique sur le téléphone et sur le serveur)
MAX_APPAREILS = 3                   # appareils actifs par participant (le plus ancien est remplacé)
MAX_PARTICIPANTS = 3000
MAX_CELLULES = 8000                 # une cellule ≈ 300 octets : 2,4 Mo au plus dans la fiche
CONSERVATION_JOURS = 120            # les cellules plus anciennes sont purgées
DELAI_MIN_S = 50                    # un même appareil n'envoie pas plus d'une mesure toutes les 50 s
MAX_PAR_JOUR = 400                  # mesures par participant et par jour (une surveillance toutes les 5 min en fait 288)
TYPES = ("wifi", "mobile")


def maintenant_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------------------------------------------------------------- lieu
def zone(lat: Optional[float], lon: Optional[float]) -> Optional[Tuple[str, float, float]]:
    """Zone de 2 km contenant le point : (clé, latitude du centre, longitude du centre), ou None si pas de lieu / lieu invalide.
    Le serveur recalcule TOUJOURS la zone : même si un téléphone envoie une position précise, seule la zone est gardée."""
    if lat is None or lon is None:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    iy, ix = round(lat / PAS_ZONE), round(lon / PAS_ZONE)
    return f"z{iy}_{ix}".replace("-", "m"), round(iy * PAS_ZONE, 2), round(ix * PAS_ZONE, 2)


def slug(texte: Optional[str], defaut: str = "inconnu") -> str:
    """Texte sûr comme morceau de clé Mongo (pas de point, de $ ni d'espace) : minuscules, chiffres et soulignés, 24 caractères."""
    propre = re.sub(r"[^0-9a-z]+", "_", str(texte or "").strip().lower()).strip("_")[:24]
    return propre or defaut


def cle_cellule(jour: str, cle_zone: Optional[str], type_connexion: str, operateur: Optional[str]) -> str:
    return "__".join([jour.replace("-", ""), cle_zone or "sans", type_connexion if type_connexion in TYPES else "mobile", slug(operateur)])


def lire_cle(cle: str) -> Dict[str, str]:
    """Inverse de cle_cellule (jour AAAAMMJJ, zone, type, opérateur sous forme de slug)."""
    jour, cle_zone, type_connexion, operateur = (cle.split("__") + ["", "", "", ""])[:4]
    return {"jour": jour, "zone": cle_zone, "type": type_connexion, "operateur": operateur}


# ------------------------------------------------------------------------------------------------------------------------ cellules
def increments(m: Dict[str, Any]) -> Dict[str, float]:
    """Ce qu'une mesure AJOUTE à sa cellule (opérateur Mongo $inc) : compteurs et sommes, jamais la mesure elle-même."""
    inc: Dict[str, float] = {"n": 1, "essais": int(m["essais"]), "perdus": int(m["perdus"]),
                             "https_ok": int(m.get("https_ok") or 0), "https_total": int(m.get("https_total") or 0)}
    for cle, somme, compte in (("latence_moy_ms", "lat_somme", "lat_n"), ("debit_desc_mbps", "desc_somme", "desc_n"), ("debit_mont_mbps", "mont_somme", "mont_n")):
        if m.get(cle) is not None:
            inc[somme] = float(m[cle]); inc[compte] = 1
    return inc


def _jour_depuis(cle: str) -> Optional[datetime]:
    try:
        return datetime.strptime(lire_cle(cle)["jour"], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def cles_a_purger(cellules: Dict[str, Any], maintenant: Optional[datetime] = None) -> List[str]:
    """Cellules plus anciennes que la durée de conservation (à supprimer)."""
    limite = (maintenant or datetime.now(timezone.utc)) - timedelta(days=CONSERVATION_JOURS)
    return [c for c in cellules if (_jour_depuis(c) or limite) < limite]


def _niveau(perte: Optional[float], desc: Optional[float]) -> str:
    """Même verdict que la sonde du propriétaire (sonde_reseau.verdict) : critique ≥ 10 % de perte, attention ≥ 2 % ou débit < 5 Mb/s."""
    if perte is None:
        return "inconnu"
    if perte >= 10.0:
        return "critique"
    if perte >= 2.0 or (desc is not None and desc < 5.0):
        return "attention"
    return "ok"


def _fiche(c: Dict[str, Any]) -> Dict[str, Any]:
    """Statistiques d'un total de cellules."""
    n = int(c.get("n", 0)); essais = int(c.get("essais", 0)); perdus = int(c.get("perdus", 0))
    moy = lambda s, k: round(c[s] / c[k], 1) if c.get(k) else None          # noqa: E731
    perte = round(perdus * 100.0 / essais, 1) if essais else None
    desc = moy("desc_somme", "desc_n")
    https_t = int(c.get("https_total", 0))
    return {"mesures": n, "essais": essais, "perdus": perdus, "perte_pct": perte, "latence_moy_ms": moy("lat_somme", "lat_n"),
            "debit_desc_mbps": desc, "debit_mont_mbps": moy("mont_somme", "mont_n"),
            "https_pct": round(int(c.get("https_ok", 0)) * 100.0 / https_t, 1) if https_t else None, "niveau": _niveau(perte, desc)}


def _ajouter(total: Dict[str, float], cellule: Dict[str, Any]) -> None:
    for k in ("n", "essais", "perdus", "https_ok", "https_total", "lat_somme", "lat_n", "desc_somme", "desc_n", "mont_somme", "mont_n"):
        total[k] = total.get(k, 0) + (cellule.get(k) or 0)


def synthese(cellules: Dict[str, Any], jours: int, type_connexion: str = "", operateur: str = "", zones: Optional[Dict[str, Any]] = None,
             maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Synthèse de l'espace commun sur les `jours` derniers jours : lignes par (zone, type de connexion, opérateur), totaux par type et par opérateur,
    listes de choix pour les filtres. `zones` = { clé de zone : {lat, lon} } (centres, gardés à côté des cellules)."""
    limite = (maintenant or datetime.now(timezone.utc)) - timedelta(days=jours)
    lignes: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    par_type: Dict[str, Dict[str, float]] = {}
    par_operateur: Dict[str, Dict[str, float]] = {}
    general: Dict[str, float] = {}
    derniere: Dict[Tuple[str, str, str], str] = {}
    operateurs, types = set(), set()
    for cle, c in cellules.items():
        d = lire_cle(cle); jour = _jour_depuis(cle)
        if jour is None or jour < limite.replace(hour=0, minute=0, second=0, microsecond=0):
            continue
        operateurs.add(d["operateur"]); types.add(d["type"])
        if type_connexion and d["type"] != type_connexion:
            continue
        if operateur and d["operateur"] != slug(operateur):
            continue
        k = (d["zone"], d["type"], d["operateur"])
        _ajouter(lignes.setdefault(k, {}), c); _ajouter(par_type.setdefault(d["type"], {}), c)
        _ajouter(par_operateur.setdefault(d["operateur"], {}), c); _ajouter(general, c)
        derniere[k] = max(derniere.get(k, ""), d["jour"])
    zones = zones or {}
    rows = []
    for (cz, t, o), tot in lignes.items():
        z = zones.get(cz) or {}
        rows.append({"zone": cz, "lat": z.get("lat"), "lon": z.get("lon"), "type": t, "operateur": o, "dernier_jour": derniere[(cz, t, o)], **_fiche(tot)})
    rows.sort(key=lambda r: -r["mesures"])
    return {"jours": jours, "resume": _fiche(general), "lignes": rows,
            "par_type": {t: _fiche(v) for t, v in sorted(par_type.items())}, "par_operateur": {o: _fiche(v) for o, v in sorted(par_operateur.items())},
            "operateurs": sorted(operateurs), "types": sorted(types)}


# ------------------------------------------------------------------------------------------------------------------------ jetons
def identifiant_participant(sub: str) -> str:
    """Identifiant interne stable du participant (empreinte de l'identité Google : l'identité elle-même n'est pas une clé de fiche)."""
    return hashlib.sha256(str(sub).encode()).hexdigest()[:20]


def nouveau_jeton() -> Tuple[str, str]:
    """Jeton d'appareil remis au téléphone + son empreinte (seule l'empreinte est gardée en base)."""
    clair = "sd_" + secrets.token_urlsafe(32)
    return clair, empreinte_jeton(clair)


def empreinte_jeton(jeton: str) -> str:
    return hashlib.sha256(str(jeton).encode()).hexdigest()


def jeton_depuis_en_tete(autorisation: Optional[str]) -> Optional[str]:
    """Extrait le jeton de « Authorization: Bearer <jeton> » ; None si absent ou mal formé."""
    if not autorisation:
        return None
    morceaux = autorisation.strip().split(" ", 1)
    if len(morceaux) != 2 or morceaux[0].lower() != "bearer" or not morceaux[1].startswith("sd_"):
        return None
    return morceaux[1].strip()
