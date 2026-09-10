"""Agents Liluvine (signature nominative des réponses auto-WhatsApp).

Le client veut jusqu'à 5 agents, chacun avec un prénom et un rôle/spécialité
100% paramétrable par l'admin (ex: Awa:Secrétaire, Robert:Comptable,
Gaspard:Technicien, Gédéon:Commercial). Quand l'IA (Claude, via
`liluvine_wa_autoreply.autoreply_to_inbound`) génère une réponse à un message
libre (PAS une commande `!...`), l'agent dont la spécialité correspond le
mieux au contenu du message signe la réponse à sa place — même si c'est bien
l'IA qui a exécuté le prompt système et rédigé le texte.

Important : les commandes `!...` ne passent JAMAIS par cette signature — elles
sont interceptées et traitées avant `should_autoreply` (voir
`liluvine_wa_autoreply.py`), donc avant tout appel à `match_agent_for_message`.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.liluvine.agents")

MAX_AGENTS = 5

# Mots-clés SANS accent (comparés à normalize(specialite) et normalize(message),
# qui retirent tous deux systématiquement les accents — voir _normalize_text).
# Piège déjà rencontré côté mockup site-meetafrican : des clés accentuées ne
# matchaient jamais car normalize() les avait déjà désaccentuées des deux côtés.
_ROLE_KEYWORDS: Dict[str, List[str]] = {
    "secretaire": [
        "rdv", "rendez-vous", "rendezvous", "planning", "disponibilite",
        "horaire", "horaires", "agenda", "secretariat",
    ],
    "comptable": [
        "facture", "factures", "paiement", "paiements", "reglement",
        "comptabilite", "solde", "recu", "quittance",
    ],
    "technicien": [
        "probleme", "panne", "bug", "erreur", "installation", "reparation",
        "technique", "depannage", "ne fonctionne pas", "marche pas",
    ],
    "commercial": [
        "prix", "tarif", "tarifs", "devis", "commande", "acheter", "achat",
        "vente", "produit", "disponible", "stock", "combien",
    ],
}


def _normalize_text(s: Optional[str]) -> str:
    """Minuscule + suppression des accents (NFD), pour un matching insensible
    aux accents des deux côtés (spécialité déclarée par l'admin ET message
    reçu de l'utilisateur)."""
    if not s:
        return ""
    nfd = unicodedata.normalize("NFD", s)
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    return stripped.lower()


def _keywords_for_specialite(specialite: str) -> List[str]:
    norm = _normalize_text(specialite)
    for role_key, keywords in _ROLE_KEYWORDS.items():
        if role_key in norm or norm in role_key:
            return keywords
    return []


def match_agent_for_message(agents: List[Dict[str, Any]], message: str) -> Optional[Dict[str, Any]]:
    """Retourne l'agent dont la spécialité correspond le mieux au message, ou
    None si aucun agent configuré ou aucun mot-clé ne matche (dans ce cas
    l'appelant garde sa signature générique par défaut — jamais de repli
    arbitraire sur agents[0])."""
    if not agents:
        return None
    norm_msg = _normalize_text(message)
    if not norm_msg:
        return None
    best_agent: Optional[Dict[str, Any]] = None
    best_score = 0
    for agent in agents:
        keywords = _keywords_for_specialite(agent.get("specialite") or "")
        if not keywords:
            continue
        score = sum(1 for kw in keywords if kw in norm_msg)
        if score > best_score:
            best_score, best_agent = score, agent
    return best_agent if best_score > 0 else None


def build_signature(agent: Dict[str, Any]) -> str:
    prenom = (agent.get("prenom") or "").strip()
    specialite = (agent.get("specialite") or "").strip()
    if specialite:
        return f"— {prenom} ({specialite}), assistant Liluvine 🤖"
    return f"— {prenom}, assistant Liluvine 🤖"


async def get_agents(db) -> List[Dict[str, Any]]:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_agents": 1}) or {}
    return s.get("liluvine_agents") or []


async def save_agents(db, agents: List[Dict[str, Any]]) -> None:
    if len(agents) > MAX_AGENTS:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_AGENTS} agents.")
    await db.settings.update_one(
        {"_id": "global"}, {"$set": {"liluvine_agents": agents}}, upsert=True,
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class AgentPayload(BaseModel):
    prenom: str = Field(..., min_length=1, max_length=40)
    specialite: str = Field(..., min_length=1, max_length=60)


class AgentsPayload(BaseModel):
    agents: List[AgentPayload]


# ---------------------------------------------------------------------------
# Route attachment
# ---------------------------------------------------------------------------
def attach_liluvine_agents_routes(api, db, get_current_admin):
    """Mount `/api/admin/liluvine/agents` (GET + PUT)."""

    @api.get("/admin/liluvine/agents", tags=["Admin — Liluvine"])
    async def list_agents(_: dict = Depends(get_current_admin)):
        return {"agents": await get_agents(db), "max_agents": MAX_AGENTS}

    @api.put("/admin/liluvine/agents", tags=["Admin — Liluvine"])
    async def replace_agents(payload: AgentsPayload = Body(...), _: dict = Depends(get_current_admin)):
        if len(payload.agents) > MAX_AGENTS:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_AGENTS} agents.")
        agents = [a.model_dump() for a in payload.agents]
        await save_agents(db, agents)
        return {"ok": True, "count": len(agents)}

    logger.info("[liluvine_agents] routes mounted under /api/admin/liluvine/agents")
