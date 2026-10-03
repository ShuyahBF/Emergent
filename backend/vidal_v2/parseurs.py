"""
backend/vidal_v2/parseurs.py
--------------------------------
Lot 56 — lecture des réponses Atom/XML de VIDAL utilisées par la
sécurisation v2, reprises de Ster (app/utils/vidal_client.py, partie
« Parsing Atom/XML VIDAL »). Lecture par expressions régulières, comme le
reste du module VIDAL de SAWALI (routes/vidal_riche.py) : si le format
diffère, on renvoie des listes vides, jamais une exception.

Différences avec l'ancien parseur SAWALI (`vidal_riche._parse_atom_entries`,
conservé tel quel pour WhatsApp) :
  - les entités HTML doublement échappées sont décodées (« R&amp;eacute; »
    devient « Ré ») AVANT de retirer les balises ;
  - la forme galénique et l'indicateur « spécialité sécurisée » sont lus ;
  - les référentiels (allergies, molécules, ALD, voies...) gardent leur
    catégorie, leur URI, leur code, leur rang et le marqueur hors AMM.

Aucune dépendance FastAPI/Mongo.
"""

import html as _html_module
import re
from typing import Optional

_ENTRY_RE = re.compile(r"<entry\b[^>]*>(.*?)</entry>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_ID_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?id>\s*(\d+)\s*</(?:[a-z][a-z0-9]*:)?id>", re.IGNORECASE)
# Repli repris de SAWALI : identifiant numérique en fin d'URI Atom (<id>…/123</id>).
_ATOM_ID_RE = re.compile(r"<id[^>]*>([^<]+)</id>", re.IGNORECASE)
_VMP_RE = re.compile(r'<(?:[a-z][a-z0-9]*:)?vmp\b[^>]*\bvidalId="(\d+)"', re.IGNORECASE)
# § forme galénique d'une spécialité quand l'API la fournit (<vidal:galenicForm vidalId="..">).
_FORME_GALENIQUE_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?galenicForm\b([^>]*)>([^<]*)</", re.IGNORECASE)
_VIDAL_ID_ATTR_RE = re.compile(r'vidalId="(\d+)"', re.IGNORECASE)
# § MI VIDAL §6.4.2 : <vidal:safetyAlert>false</...> = spécialité que VIDAL ne sécurise pas.
_SAFETY_ALERT_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?safetyAlert>\s*(true|false)\s*<", re.IGNORECASE)


def texte_vidal(brut: Optional[str]) -> Optional[str]:
    """Texte lisible : décode D'ABORD les entités (deux passes), retire ENSUITE les balises."""
    if brut is None:
        return None
    texte = _html_module.unescape(_html_module.unescape(brut.strip()))
    return _TAG_STRIP_RE.sub("", texte).strip()


def _identifiant(bloc: str) -> Optional[str]:
    """Identifiant VIDAL d'une entrée : <vidal:id>, sinon fin numérique de l'URI Atom."""
    m = _ID_RE.search(bloc)
    if m:
        return m.group(1)
    atome = _ATOM_ID_RE.search(bloc)
    if atome:
        fin = re.search(r"(\d+)\s*$", atome.group(1))
        if fin:
            return fin.group(1)
    return None


def parser_entrees_atom(raw: Optional[str]) -> list[dict]:
    """{title, vidal_id, vmp_id, galenic_form, galenic_form_id, safety_alert} pour chaque <entry>."""
    items: list[dict] = []
    if not isinstance(raw, str) or "<entry" not in raw:
        return items
    for bloc in _ENTRY_RE.findall(raw):
        titre_m = _TITLE_RE.search(bloc)
        titre = texte_vidal(titre_m.group(1)) if titre_m else ""
        if not titre:
            continue
        vmp_m = _VMP_RE.search(bloc)
        forme_m = _FORME_GALENIQUE_RE.search(bloc)
        forme_id_m = _VIDAL_ID_ATTR_RE.search(forme_m.group(1)) if forme_m else None
        securite_m = _SAFETY_ALERT_RE.search(bloc)
        items.append({
            "title": titre, "vidal_id": _identifiant(bloc), "vmp_id": vmp_m.group(1) if vmp_m else None,
            "galenic_form": texte_vidal(forme_m.group(2)) if forme_m else None,
            "galenic_form_id": forme_id_m.group(1) if forme_id_m else None,
            "safety_alert": (securite_m.group(1).lower() == "true") if securite_m else None,
        })
    return items


_ENTREE_CATEGORIE_RE = re.compile(r'<entry\b([^>]*)>(.*?)</entry>', re.DOTALL | re.IGNORECASE)
_CATEGORIE_ATTR_RE = re.compile(r'categories="([^"]*)"', re.IGNORECASE)
_URI_RE = re.compile(r"<id>\s*(vidal://[a-z_]+/\d+)\s*</id>", re.IGNORECASE)
_CODE_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?code>\s*([^<]+?)\s*</", re.IGNORECASE)
_RANKING_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?ranking>\s*(\d+)\s*<", re.IGNORECASE)
_HORS_AMM_RE = re.compile(r"<(?:[a-z][a-z0-9]*:)?outOfSPC>\s*(true|false)\s*<", re.IGNORECASE)
_INDICATEUR_RE = re.compile(r'<(?:[a-z][a-z0-9]*:)?indicator\b[^>]*\bvidalId="(\d+)"[^>]*>([^<]*)</', re.IGNORECASE)


def parser_entrees_categorisees(raw: Optional[str]) -> list[dict]:
    """
    Référentiels VIDAL : chaque <entry> avec sa catégorie (vidal:categories :
    ALLERGY, MOLECULE, ALD, ROUTE...), son URI (<id>vidal://…</id>), son code
    (<vidal:code>, ALD), son rang (<vidal:ranking>, voies) et le marqueur hors
    AMM (<vidal:outOfSPC>).
    """
    items: list[dict] = []
    if not isinstance(raw, str) or "<entry" not in raw:
        return items
    for attributs, bloc in _ENTREE_CATEGORIE_RE.findall(raw):
        titre_m = _TITLE_RE.search(bloc)
        titre = texte_vidal(titre_m.group(1)) if titre_m else ""
        if not titre:
            continue
        cat_m, uri_m = _CATEGORIE_ATTR_RE.search(attributs), _URI_RE.search(bloc)
        code_m, rang_m, hors_m = _CODE_RE.search(bloc), _RANKING_RE.search(bloc), _HORS_AMM_RE.search(bloc)
        items.append({
            "title": titre, "categorie": cat_m.group(1).upper() if cat_m else None,
            "vidal_id": _identifiant(bloc), "uri": uri_m.group(1) if uri_m else None,
            "code": code_m.group(1) if code_m else None,
            "ranking": int(rang_m.group(1)) if rang_m else None,
            "hors_amm": (hors_m.group(1).lower() == "true") if hors_m else False,
        })
    return items


def parser_indicateurs(raw: Optional[str]) -> list[dict]:
    """§ MI VIDAL §4.7.1 : indicateurs d'un médicament -> [{id, label}] (<vidal:indicator vidalId=...>, sinon entrées)."""
    if not isinstance(raw, str):
        return []
    trouves = {i: texte_vidal(l) for i, l in _INDICATEUR_RE.findall(raw)}
    if not trouves:
        trouves = {e["vidal_id"]: e["title"] for e in parser_entrees_atom(raw) if e.get("vidal_id")}
    return [{"id": i, "label": l} for i, l in trouves.items()]
