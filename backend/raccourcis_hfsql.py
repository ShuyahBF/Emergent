"""raccourcis_hfsql.py — RACCOURCIS DE COMMANDES SQL DISTANTES AVEC PARAMÈTRES (lot 459, propriétaire 25/11/2026).

Une commande SQL distante déjà exécutée avec succès peut devenir un RACCOURCI : les valeurs qui changent d'une fois à l'autre sont écrites entre accolades, comme dans HFSQL :
    UPDATE VenteClinique SET Mag = {vStatut} WHERE Référence = {RefNum}
Lancé (par WhatsApp, via Liluvine), le raccourci détecte ses paramètres DANS L'ORDRE D'APPARITION (vStatut puis RefNum), demande leurs valeurs une à une, exécute la commande et renvoie le résultat.

SÉCURITÉ (règle 21) : une valeur saisie ne peut JAMAIS changer la nature de la commande :
  - hors apostrophes, un nombre reste un nombre, NULL reste NULL, tout autre texte est mis entre apostrophes (apostrophes doublées) ;
  - dans des apostrophes déjà écrites par le modèle, les apostrophes de la valeur sont doublées ;
  - 200 caractères au plus, pas de retour à la ligne, pas d'accolade ;
  - la commande RÉSOLUE repasse par les contrôles « Prudent » (`loois_sql_distant.verifier`) : une seule instruction, UPDATE / DELETE avec WHERE, aucune modification de structure.
Stockage : une fiche de `settings` (`liluvine_hfsql_raccourcis`), 20 raccourcis au plus (le propriétaire en veut au moins 10), aucune nouvelle collection.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ID_FICHE = "liluvine_hfsql_raccourcis"
MAX_RACCOURCIS = 20
NOM_MIN, NOM_MAX = 2, 40
VALEUR_MAX = 200
RE_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]{0,29})\}")
RE_NOMBRE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def parametres(sql: str) -> List[str]:
    """Noms des paramètres dans l'ORDRE D'APPARITION, sans doublon (un paramètre répété demande une seule valeur)."""
    vus: List[str] = []
    for m in RE_PARAM.finditer(str(sql or "")):
        if m.group(1) not in vus:
            vus.append(m.group(1))
    return vus


def _normaliser_nom(texte: Any) -> str:
    t = unicodedata.normalize("NFD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def valider_modele(nom: Any, sql: Any, zone: Any = "") -> Tuple[Optional[Dict[str, Any]], str]:
    """(raccourci propre, raison du refus). Le modèle est contrôlé en remplaçant chaque {paramètre} par une valeur plausible."""
    from routes.loois_sql_distant import verifier
    n = re.sub(r"\s+", " ", str(nom or "")).strip()
    if not (NOM_MIN <= len(n) <= NOM_MAX):
        return None, f"Donnez un nom de {NOM_MIN} à {NOM_MAX} caractères."
    texte = str(sql or "").strip()
    while texte.endswith(";"):
        texte = texte[:-1].rstrip()
    if not texte:
        return None, "La commande est vide."
    if "{" in RE_PARAM.sub("", texte) or "}" in RE_PARAM.sub("", texte):
        return None, "Accolade mal écrite : un paramètre s'écrit {NomDuParametre} (lettres, chiffres et _, sans espace)."
    essai = RE_PARAM.sub("0", texte)
    ok, nature, raison = verifier(essai)
    if not ok:
        return None, raison
    z = re.sub(r"\s+", "", str(zone or "")).lstrip("/")
    if z and not re.fullmatch(r"(?:(?:docx|doc|ekol)=)?[A-Za-z0-9_-]{1,20}", z, re.I):
        return None, "Zone invalide (ex. docx=CMC)."
    return {"nom": n, "sql": texte, "zone": z, "nature": nature, "parametres": parametres(texte)}, ""


def valider_valeur(nom: str, valeur: Any) -> str:
    """Valeur propre d'un paramètre (rognée) ou ValueError : vide, trop longue, retour à la ligne ou accolade. Appelée dès la réception de chaque valeur."""
    v = str(valeur or "").strip()
    if not v:
        raise ValueError(f"La valeur de {nom} est vide.")
    if len(v) > VALEUR_MAX:
        raise ValueError(f"La valeur de {nom} est trop longue ({VALEUR_MAX} caractères au plus).")
    if any(ord(ch) < 32 for ch in v) or "{" in v or "}" in v:
        raise ValueError(f"La valeur de {nom} contient un caractère refusé (retour à la ligne ou accolade).")
    return v


def resoudre(sql: str, valeurs: Dict[str, str]) -> str:
    """Remplace chaque {paramètre} par sa valeur, de façon SÛRE (voir l'en-tête). Lève ValueError si une valeur manque ou est refusée."""
    sortie: List[str] = []
    dans_apostrophes = False
    i = 0
    while i < len(sql):
        c = sql[i]
        if c == "'":
            if dans_apostrophes and i + 1 < len(sql) and sql[i + 1] == "'":      # apostrophe doublée DANS un texte : on reste dedans
                sortie.append("''")
                i += 2
                continue
            dans_apostrophes = not dans_apostrophes
            sortie.append(c)
            i += 1
            continue
        m = RE_PARAM.match(sql, i) if c == "{" else None
        if m:
            nom = m.group(1)
            if nom not in valeurs:
                raise ValueError(f"Valeur manquante pour {nom}.")
            v = valider_valeur(nom, valeurs[nom])
            if dans_apostrophes:
                sortie.append(v.replace("'", "''"))                              # le modèle a déjà ses apostrophes : on double celles de la valeur
            elif RE_NOMBRE.match(v):
                sortie.append(v.replace(",", "."))
            elif v.upper() == "NULL":
                sortie.append("NULL")
            else:
                sortie.append("'" + v.replace("'", "''") + "'")
            i = m.end()
            continue
        sortie.append(c)
        i += 1
    return "".join(sortie)


async def lister(db) -> List[Dict[str, Any]]:
    return list((await db["settings"].find_one({"_id": ID_FICHE}) or {}).get("raccourcis") or [])


async def _ecrire(db, liste: List[Dict[str, Any]]) -> None:
    await db["settings"].update_one({"_id": ID_FICHE}, {"$set": {"raccourcis": liste[:MAX_RACCOURCIS]}}, upsert=True)


async def creer(db, nom: Any, sql: Any, zone: Any = "", confirmer: bool = False, par: str = "") -> Dict[str, Any]:
    """Crée un raccourci. ValueError avec la raison si le modèle est refusé, si le nom existe déjà ou si la limite est atteinte."""
    propre, raison = valider_modele(nom, sql, zone)
    if not propre:
        raise ValueError(raison)
    liste = await lister(db)
    if len(liste) >= MAX_RACCOURCIS:
        raise ValueError(f"Limite atteinte : {MAX_RACCOURCIS} raccourcis au plus. Supprimez-en un d'abord.")
    if any(_normaliser_nom(r["nom"]) == _normaliser_nom(propre["nom"]) for r in liste):
        raise ValueError("Un raccourci porte déjà ce nom.")
    fiche = {"id": secrets.token_hex(4), **propre, "confirmer": bool(confirmer), "cree_par": str(par)[:120], "cree_le": datetime.now(timezone.utc).isoformat()}
    liste.append(fiche)
    await _ecrire(db, liste)
    return fiche


async def modifier(db, identifiant: str, nom: Any, sql: Any, zone: Any = "", confirmer: bool = False) -> Dict[str, Any]:
    propre, raison = valider_modele(nom, sql, zone)
    if not propre:
        raise ValueError(raison)
    liste = await lister(db)
    cible = next((r for r in liste if r["id"] == identifiant), None)
    if not cible:
        raise ValueError("Raccourci introuvable.")
    if any(r["id"] != identifiant and _normaliser_nom(r["nom"]) == _normaliser_nom(propre["nom"]) for r in liste):
        raise ValueError("Un autre raccourci porte déjà ce nom.")
    cible.update(propre)
    cible["confirmer"] = bool(confirmer)
    await _ecrire(db, liste)
    return cible


async def supprimer(db, identifiant: str) -> bool:
    liste = await lister(db)
    reste = [r for r in liste if r["id"] != identifiant]
    if len(reste) == len(liste):
        return False
    await _ecrire(db, reste)
    return True


def trouver(liste: List[Dict[str, Any]], reference: str) -> Optional[Dict[str, Any]]:
    """Retrouve un raccourci par son NUMÉRO dans la liste (1, 2, 3…) ou par son NOM (sans accents ni casse ; un début de nom suffit s'il est sans ambiguïté)."""
    ref = str(reference or "").strip()
    if ref.isdigit():
        n = int(ref)
        return liste[n - 1] if 1 <= n <= len(liste) else None
    cle = _normaliser_nom(ref)
    if not cle:
        return None
    exacts = [r for r in liste if _normaliser_nom(r["nom"]) == cle]
    if exacts:
        return exacts[0]
    debuts = [r for r in liste if _normaliser_nom(r["nom"]).startswith(cle)]
    return debuts[0] if len(debuts) == 1 else None
