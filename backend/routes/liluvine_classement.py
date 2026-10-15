"""Lot 181 — Classement des conversations WhatsApp par Liluvine.

Pendant une conversation, Liluvine classe la demande dans une catégorie (Technique, Comptabilité, Commercial…), ouvre un
ticket dont le motif résume brièvement ce qu'elle a compris, puis annonce qu'elle met le correspondant en relation avec
l'un de ses assistants IA (prénom + fonction, ceux de « Agents Liluvine »).

Mécanique : Liluvine termine sa réponse par un marqueur `[CLASSE: <catégorie> | <motif>]` (comme `[ESCALATE: …]`) quand
elle a compris la demande ; le marqueur est retiré du message envoyé. Si la catégorie n'est pas claire, elle pose UNE
question en proposant les catégories (les « options »). Toutes les fonctions ci-dessous sont pures (sans base ni réseau).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

CATEGORIES_DEFAUT = ["Technique", "Comptabilité", "Commercial", "Secrétariat / rendez-vous", "Autre"]
MAX_CATEGORIES = 8
# Une conversation déjà classée n'est pas re-classée (ni re-présentée) pendant cette durée.
DUREE_CLASSEE_HEURES = 6

_MARQUEUR = re.compile(r"\[\s*CLASSE\s*:\s*([^\]|]+?)\s*(?:\|\s*([^\]]*?))?\s*\]", re.IGNORECASE)

# Catégorie (sans accent) → racine de la spécialité de l'assistant qui la traite (voir liluvine_agents._ROLE_KEYWORDS).
_ROLE_PAR_CATEGORIE = {
    "technique": "technicien", "comptabilite": "comptable", "commercial": "commercial",
    "secretariat": "secretaire", "rendez-vous": "secretaire",
}


def _norm(s: Any) -> str:
    """Minuscule sans accents (comparaison tolérante)."""
    nfd = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def categories(settings_doc: Optional[Dict[str, Any]]) -> List[str]:
    """Catégories réglées dans les Paramètres (une par entrée, 8 au plus), sinon la liste par défaut."""
    brut = (settings_doc or {}).get("liluvine_classement_categories")
    if isinstance(brut, str):
        brut = brut.splitlines()
    liste = [str(c).strip()[:40] for c in (brut or []) if str(c).strip()]
    return liste[:MAX_CATEGORIES] or list(CATEGORIES_DEFAUT)


def actif(settings_doc: Optional[Dict[str, Any]]) -> bool:
    """Le classement est actif par défaut ; réglable dans les Paramètres."""
    return (settings_doc or {}).get("liluvine_classement_actif") is not False


def consignes_classement(cats: List[str], deja_classe: Optional[str] = None) -> str:
    """Consignes ajoutées au prompt de Liluvine pour qu'elle classe la demande et pose le marqueur."""
    if deja_classe:
        return (f"\n\n[Classement de la conversation]\nCette conversation est DÉJÀ classée « {deja_classe} » et le correspondant "
                "a déjà été mis en relation avec un assistant : ne le remets pas en relation, n'écris aucun marqueur CLASSE ; "
                "aide-le directement.")
    return (
        "\n\n[Classement de la conversation]\n"
        f"Catégories possibles : {', '.join(cats)}.\n"
        "- Quand tu as compris ce que le correspondant demande ET dans quelle catégorie cela se range, termine ta réponse par "
        "le marqueur exact [CLASSE: <catégorie> | <motif en 12 mots maximum>] (catégorie recopiée telle quelle dans la liste).\n"
        "- Avec le marqueur, écris la réponse à la demande tirée UNIQUEMENT de la base de connaissances (sans rien inventer ; "
        "si elle n'y figure pas, dis-le et propose un conseiller humain) : la phrase de mise en relation avec l'assistant et "
        "le numéro de ticket sont ajoutés automatiquement, ne les écris pas.\n"
        "- Si la catégorie n'est pas claire, pose UNE seule question courte en proposant ces catégories, sans marqueur.\n"
        "- Pas de marqueur pour une simple salutation ou une question d'information : seulement pour une demande à traiter."
    )


def extraire_classement(reply: str, cats: List[str]) -> Tuple[str, Optional[Dict[str, str]]]:
    """Retire le marqueur [CLASSE: …] de la réponse → (texte nettoyé, {"categorie", "motif"} ou None).
    La catégorie est ramenée à la liste réglée (« Autre » si elle n'y figure pas)."""
    m = _MARQUEUR.search(reply or "")
    if not m:
        return (reply or "").strip(), None
    texte = _MARQUEUR.sub("", reply).strip()
    demandee = _norm(m.group(1))
    choisie = next((c for c in cats if _norm(c) == demandee), None) \
        or next((c for c in cats if demandee and (demandee in _norm(c) or _norm(c) in demandee)), None) \
        or next((c for c in cats if _norm(c) == "autre"), "Autre")
    motif = re.sub(r"\s+", " ", (m.group(2) or "").strip())[:120] or "Demande d'assistance"
    return texte, {"categorie": choisie, "motif": motif}


def agent_pour_categorie(agents: List[Dict[str, Any]], categorie: str) -> Optional[Dict[str, Any]]:
    """Assistant IA (parmi les 5 de « Agents Liluvine ») dont la spécialité correspond à la catégorie, ou None."""
    cat = _norm(categorie)
    racine = next((r for k, r in _ROLE_PAR_CATEGORIE.items() if k in cat), "")
    for a in agents or []:
        spe = _norm(a.get("specialite"))
        if not spe:
            continue
        if (racine and (racine in spe or spe in racine)) or cat in spe or spe in cat:
            return a
    return None


def texte_mise_en_relation(agent: Optional[Dict[str, Any]], motif: str, ticket_numero: Optional[str]) -> str:
    """Message envoyé au correspondant : ce que Liluvine a compris, le ticket, puis la mise en relation (prénom + fonction)."""
    lignes = [f"Merci, j'ai bien compris votre demande : {motif}."]
    if ticket_numero:
        lignes.append(f"Un ticket a été ouvert (n° {ticket_numero}).")
    if agent and (agent.get("prenom") or "").strip():
        fonction = (agent.get("specialite") or "").strip()
        qui = f"{agent['prenom'].strip()} ({fonction})" if fonction else agent["prenom"].strip()
        lignes.append(f"Je vous mets en relation avec {qui}, votre assistant IA.")
    else:
        lignes.append("Je vous mets en relation avec votre assistant IA.")
    return "\n".join(lignes)
