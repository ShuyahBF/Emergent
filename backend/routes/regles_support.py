"""Lot 98 — Règles des réponses de Liluvine et de Claude au support (propriétaire, 10/10/2026).

  1. Les utilisateurs ne sont pas des utilisateurs avertis : réponses COURTES, sans procédure à nombreux clics.
  2. Toujours répondre, quitte à poser 1 ou 2 questions d'éclaircissement : c'est un dialogue (1 à 2 échanges), on
     avance selon ses réponses ; s'il ne répond plus, on abandonne.
  3. Liluvine a 5 assistants (Paramètres → agents de Liluvine : prénom + spécialité). Selon le sujet, la réponse
     porte en en-tête la PASTILLE de l'assistant concerné (ex. facturation, contrat → le comptable).
  4. Claude ne donne que des réponses techniques ; quand Liluvine ne sait pas répondre, Claude l'assiste SANS lire
     le dépôt de code (support_loois_sessions.reponse_liluvine_detail).

Ce module regroupe le texte des règles (ajouté aux consignes des modèles) et le calcul de la pastille.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Nombre maximal d'échanges d'éclaircissement avant de passer à la suite (règle 2)
TOURS_PRECISIONS_MAX = 2

REGLES_REPONSE = (
    "\n\nRÈGLES DE RÉPONSE (obligatoires) :\n"
    "1. Ton interlocuteur n'est pas un utilisateur averti : réponds en 2 ou 3 phrases courtes, avec des mots simples. "
    "Jamais de longue procédure ni de manipulation à nombreux clics (une ou deux actions simples au plus).\n"
    "2. Réponds toujours. Si la demande n'est pas claire, pose au plus 2 questions d'éclaircissement, puis avance selon "
    "ses réponses : c'est un dialogue court, pas un exposé.\n"
)


async def pastille(db, *textes: str, defaut_technique: bool = False) -> Optional[Dict[str, str]]:
    """Assistant de Liluvine concerné par le sujet (mots-clés de sa spécialité, d'abord dans la question puis dans la
    réponse) ; à défaut, le technicien si la réponse est technique (Claude). None si aucun assistant ne convient."""
    from routes.liluvine_agents import _normalize_text, get_agents, match_agent_for_message
    try:
        agents = await get_agents(db)
    except Exception:  # noqa: BLE001
        return None
    if not agents:
        return None
    for texte in textes:
        agent = match_agent_for_message(agents, texte or "")
        if agent:
            return {"prenom": str(agent.get("prenom") or ""), "specialite": str(agent.get("specialite") or "")}
    if defaut_technique:
        tech = next((a for a in agents if "techn" in _normalize_text(a.get("specialite"))), None)
        if tech:
            return {"prenom": str(tech.get("prenom") or ""), "specialite": str(tech.get("specialite") or "")}
    return None


def nom_affiche(nom_base: str, p: Optional[Dict[str, str]]) -> str:
    """Nom de l'expéditeur avec la pastille : « 🤖 Liluvine · Robert (Comptable) » (inchangé sans pastille)."""
    if not p or not p.get("prenom"):
        return nom_base
    return f"{nom_base} · {p['prenom']}" + (f" ({p['specialite']})" if p.get("specialite") else "")
