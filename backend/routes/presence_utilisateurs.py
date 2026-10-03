"""Lot 54 — Pastille de présence sur la page « Utilisateurs suivis ».

  GET /api/admin/tracked-users/presence?client_id=   (Admin)
      → {"seuils": {...}, "maintenant": iso, "items": {tracked_user_id: {etat, derniere_activite, sessions}}}

Source : les sessions des comptes du lot 50 (`sessions_comptes` : session ouverte, non expirée).
L'activité retenue est la dernière INTERACTION de l'utilisateur (`derniere_interaction` : souris,
clavier, défilement, toucher, signalés par le navigateur au plus une fois par minute via
POST /api/me/activite), à défaut l'ouverture de la session. `derniere_activite` n'est pas
utilisée : elle avance aussi avec les sondages automatiques des pages (messages non lus…), qui
garderaient en vert un onglet resté ouvert sans personne devant. Précision : environ une minute.

Seuils (définis ici, en secondes) :
  - VERT   : au moins une session ouverte ET dernière activité il y a ≤ 5 min ;
  - ORANGE : session ouverte, aucune activité depuis plus de 5 min et jusqu'à 10 min ;
  - ROUGE  : plus de 10 min sans activité (5 min au-delà du seuil orange), ou aucune session
             ouverte (déconnecté, session fermée ou expirée), ou aucun compte de connexion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from auth import get_current_admin
from db import db

router = APIRouter(tags=["Utilisateurs suivis — présence (lot 54)"])

SEUIL_ORANGE_S = 5 * 60            # au-delà : connecté mais inactif (orange)
SEUIL_ROUGE_S = SEUIL_ORANGE_S + 5 * 60   # au-delà : rouge (10 min sans activité)
VERT, ORANGE, ROUGE = "vert", "orange", "rouge"


def _date(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def etat(derniere_activite: Any, connecte: bool, maintenant: Optional[datetime] = None) -> str:
    """Couleur de la pastille pour une dernière activité donnée."""
    if not connecte:
        return ROUGE
    d = _date(derniere_activite)
    if d is None:
        return ROUGE
    ecart = ((maintenant or datetime.now(timezone.utc)) - d).total_seconds()
    if ecart <= SEUIL_ORANGE_S:
        return VERT
    if ecart <= SEUIL_ROUGE_S:
        return ORANGE
    return ROUGE


async def presence(user_ids: List[str], maintenant: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """Par compte : sessions ouvertes et dernière activité la plus récente."""
    maintenant = maintenant or datetime.now(timezone.utc)
    out: Dict[str, Dict[str, Any]] = {}
    ids = [u for u in dict.fromkeys(user_ids) if u]
    if not ids:
        return out
    curseur = db.sessions_comptes.find(
        {"user_id": {"$in": ids}, "fermee_le": None, "expire_a": {"$gt": maintenant}},
        {"_id": 0, "user_id": 1, "derniere_interaction": 1, "ouverte_le": 1})
    async for s in curseur:
        p = out.setdefault(s["user_id"], {"sessions": 0, "derniere_activite": None})
        p["sessions"] += 1
        d = _date(s.get("derniere_interaction") or s.get("ouverte_le"))
        actuel = _date(p["derniere_activite"])
        if d and (actuel is None or d > actuel):
            p["derniere_activite"] = d.isoformat()
    for uid in ids:
        p = out.setdefault(uid, {"sessions": 0, "derniere_activite": None})
        p["etat"] = etat(p["derniere_activite"], p["sessions"] > 0, maintenant)
    return out


@router.get("/admin/tracked-users/presence")
async def presence_utilisateurs_suivis(client_id: Optional[str] = None, _: dict = Depends(get_current_admin)):
    maintenant = datetime.now(timezone.utc)
    q = {"client_id": client_id} if client_id else {}
    suivis = await db.tracked_users.find(q, {"_id": 0, "id": 1, "user_account_id": 1, "user_id": 1}).to_list(5000)
    comptes = {t["id"]: (t.get("user_account_id") or t.get("user_id")) for t in suivis}
    par_compte = await presence([c for c in comptes.values() if c], maintenant)
    items = {}
    for tid, compte in comptes.items():
        p = par_compte.get(compte) if compte else None
        items[tid] = {"etat": (p or {}).get("etat", ROUGE), "derniere_activite": (p or {}).get("derniere_activite"),
                      "sessions": (p or {}).get("sessions", 0), "compte": bool(compte)}
    return {"maintenant": maintenant.isoformat(), "items": items,
            "seuils": {"orange_apres_s": SEUIL_ORANGE_S, "rouge_apres_s": SEUIL_ROUGE_S}}
