"""Lot 451 — RECHERCHE PLEIN TEXTE dans les rapports, suivis, notes et tâches (tableau de bord du portail).

Ce fichier ne contient que de la LOGIQUE PURE (aucun accès à la base) : il est testé seul (tests/test_recherche_documents.py).
Pour un développeur WinDev : ce sont des « procédures globales » de traitement de texte.
  - `motif_sans_accents`  : transforme le texte cherché en expression de recherche qui ignore majuscules ET accents (« reunion » trouve « Réunion ») ;
  - `texte_brut`          : retire la mise en forme HTML d'un contenu pour ne garder que le texte lisible ;
  - `analyser_document`   : cherche le texte dans les champs d'un document et rend le nombre d'occurrences et un EXTRAIT autour de la première.
"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Any, Optional

# Types de documents cherchés : clé de l'API (celle de /me/notes/{kind}) → libellé affiché
TYPES = {"reports": "Rapport", "suivis": "Suivi", "notes": "Note", "tasks": "Tâche"}

LONGUEUR_MIN = 2          # en dessous, la recherche ramènerait presque tout
LONGUEUR_MAX = 80
MAX_PAR_TYPE = 50         # résultats au plus par type de document (les plus récents d'abord)
CONTEXTE = 70             # caractères gardés avant et après l'occurrence dans l'extrait

# Lettres dont les variantes accentuées doivent être trouvées ensemble
_VARIANTES = {
    "a": "aàâäáãå", "c": "cç", "e": "eéèêë", "i": "iîïíì", "n": "nñ",
    "o": "oôöóòõ", "u": "uùûüú", "y": "yÿý",
}


def sans_accents(texte: str) -> str:
    """« Réunion ÉTÉ » → « Reunion ETE » (les accents sont retirés, la casse est gardée)."""
    return "".join(c for c in unicodedata.normalize("NFD", texte or "") if unicodedata.category(c) != "Mn")


def nettoyer_requete(q: Optional[str]) -> str:
    """Texte cherché remis au propre : espaces réduits, longueur bornée. Chaîne vide si trop court."""
    propre = re.sub(r"\s+", " ", (q or "").strip())[:LONGUEUR_MAX]
    return propre if len(propre) >= LONGUEUR_MIN else ""


def motif_sans_accents(q: str) -> str:
    """Expression régulière (texte) qui trouve `q` sans tenir compte des accents ; les caractères spéciaux de `q` sont neutralisés
    (l'utilisateur ne peut pas injecter sa propre expression). Un espace accepte un ou plusieurs blancs."""
    morceaux = []
    for c in sans_accents(q).lower():
        if c.isspace():
            morceaux.append(r"\s+")
        elif c in _VARIANTES:
            morceaux.append("[" + _VARIANTES[c] + "]")
        else:
            morceaux.append(re.escape(c))
    return "".join(morceaux)


def compiler(q: str) -> re.Pattern:
    """Expression compilée pour chercher côté Python (sans casse, sans accents)."""
    return re.compile(motif_sans_accents(q), re.IGNORECASE)


_BALISE_BLOC = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|td|th|table|blockquote)\b[^>]*>", re.IGNORECASE)
_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_BALISE = re.compile(r"<[^>]+>")


def texte_brut(contenu_html: Optional[str]) -> str:
    """Texte lisible d'un contenu HTML : balises retirées (une fin de paragraphe devient un espace), entités décodées (&amp; → &), blancs réduits."""
    t = _SCRIPT.sub(" ", contenu_html or "")
    t = _BALISE_BLOC.sub(" ", t)
    t = _BALISE.sub("", t)
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def champs_cherches(doc: dict) -> list[tuple[str, str]]:
    """Champs d'un document où l'on cherche, dans l'ordre d'importance : (libellé du champ, texte)."""
    champs = [
        ("Titre", str(doc.get("title") or "")),
        ("Contenu", texte_brut(doc.get("content_html"))),
        ("Liste de la tâche", " · ".join(str((it or {}).get("text") or (it or {}).get("label") or "") for it in (doc.get("task_items") or []) if isinstance(it, dict))),
        ("Note vocale (transcription)", str(doc.get("voice_note_transcript") or "")),
        ("Étiquettes", " · ".join(str(t) for t in (doc.get("tags") or []))),
        ("Numéro", str(doc.get("numero") or "")),
    ]
    return [(nom, texte) for nom, texte in champs if texte.strip()]


def extrait(texte: str, debut: int, fin: int) -> dict:
    """Extrait autour de l'occurrence [debut, fin[ : texte avant, texte trouvé, texte après (avec « … » quand c'est coupé)."""
    a = max(0, debut - CONTEXTE)
    b = min(len(texte), fin + CONTEXTE)
    return {
        "avant": ("… " if a > 0 else "") + texte[a:debut].lstrip(),
        "trouve": texte[debut:fin],
        "apres": texte[fin:b].rstrip() + (" …" if b < len(texte) else ""),
    }


def analyser_document(doc: dict, motif: re.Pattern) -> Optional[dict]:
    """Cherche dans le TEXTE LISIBLE du document. Rend None si rien n'est trouvé (ex. le mot n'était présent que dans une balise HTML),
    sinon {occurrences, champ, extrait} : nombre total d'occurrences, champ de la première et extrait autour d'elle."""
    total = 0
    premier: Optional[dict] = None
    for nom, texte in champs_cherches(doc):
        trouves = list(motif.finditer(texte))
        if not trouves:
            continue
        total += len(trouves)
        if premier is None:
            premier = {"champ": nom, "extrait": extrait(texte, trouves[0].start(), trouves[0].end())}
    if premier is None:
        return None
    return {"occurrences": total, **premier}


def filtre_mongo(q: str) -> dict[str, Any]:
    """Filtre MongoDB qui présélectionne les documents contenant `q` (sans casse ni accents) dans l'un des champs cherchés.
    La vérification fine (texte lisible, extrait) est refaite ensuite par `analyser_document`."""
    rx = {"$regex": motif_sans_accents(q), "$options": "i"}
    return {"$or": [
        {"title": rx}, {"content_html": rx}, {"numero": rx}, {"tags": rx},
        {"voice_note_transcript": rx}, {"task_items.text": rx}, {"task_items.label": rx},
    ]}


def resume_resultat(kind: str, doc: dict, analyse: dict) -> dict:
    """Ligne de la liste de résultats : type, date et heure, extrait, auteur. Jamais le contenu entier (il est lu à l'ouverture)."""
    return {
        "kind": kind, "type": TYPES.get(kind, kind), "id": doc.get("id"), "numero": doc.get("numero"),
        "titre": doc.get("title") or "", "cree_le": doc.get("created_at"),
        "auteur": doc.get("owner_name") or doc.get("owner_email") or "",
        "champ": analyse["champ"], "extrait": analyse["extrait"], "occurrences": analyse["occurrences"],
    }


# Champs rendus à l'ouverture d'un résultat (lecture seule) : ni adresse IP, ni navigateur, ni images
CHAMPS_LECTURE = ("id", "kind", "numero", "title", "content_html", "tags", "created_at", "updated_at", "owner_name", "owner_email",
                  "owner_role", "event_date", "task_items", "voice_note_transcript", "is_private")


def document_lecture(kind: str, doc: dict) -> dict:
    """Document complet pour la fenêtre de lecture : seulement les champs utiles à la lecture."""
    sortie = {c: doc.get(c) for c in CHAMPS_LECTURE}
    sortie["kind"] = kind
    sortie["type"] = TYPES.get(kind, kind)
    sortie["nb_images"] = len(doc.get("images") or [])
    return sortie
