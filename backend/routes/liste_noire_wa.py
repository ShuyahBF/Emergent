# routes/liste_noire_wa.py — routes de la LISTE NOIRE WhatsApp (lot 453). Règles et stockage : voir backend/liste_noire_wa.py.
#   POST   /me/wa/liste-noire           bloquer un contact (administrateur ou superviseur, depuis le Centre de Messagerie)
#   GET    /me/wa/liste-noire/etat      ce numéro est-il bloqué ? (réponse : un booléen seulement ; la liste n'est jamais exposée ici)
#   GET    /admin/wa/liste-noire        la liste complète (administrateur et superviseur, Paramètres uniquement)
#   DELETE /admin/wa/liste-noire/{cle}  débloquer (administrateur et superviseur, Paramètres uniquement)
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import liste_noire_wa

ROLES_BLOCAGE = ("admin", "super_admin", "superviseur")     # blocage, liste et déblocage : administrateur ET superviseur
TRACKED_BLOCAGE = ("Administrateur", "Superviseur")         # utilisateurs suivis de ces rôles


# Modèle au NIVEAU DU MODULE : FastAPI ne retrouve pas les modèles déclarés dans une fonction (annotations différées)
class BlocageContact(BaseModel):
    telephone: str = Field(min_length=6, max_length=30)
    nom: Optional[str] = Field(default="", max_length=120)
    contact_id: Optional[str] = None
    motif: Optional[str] = Field(default="", max_length=300)


def setup_liste_noire_wa_routes(*, db, api, get_current_user) -> None:
    def _peut_bloquer(user: dict) -> None:
        """Administrateur ET superviseur (le Centre de Messagerie est celui du superviseur) : bloquent, voient la liste (Paramètres) et débloquent."""
        if user.get("role") not in ROLES_BLOCAGE and user.get("tracked_role") not in TRACKED_BLOCAGE:
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur et au superviseur")

    @api.post("/me/wa/liste-noire", tags=["Liste noire WhatsApp"])
    async def bloquer(payload: BlocageContact, user: dict = Depends(get_current_user)):
        """Bloque un contact sur TOUTES les lignes : plus aucun message sortant, plus de réponse d'agent IA, messages reçus retenus."""
        _peut_bloquer(user)
        try:
            entree = await liste_noire_wa.bloquer(db, payload.telephone, nom=payload.nom or "", contact_id=payload.contact_id,
                                                  motif=payload.motif or "", par=user.get("full_name") or user.get("email") or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "bloque": True, "nom": entree["nom"]}

    @api.get("/me/wa/liste-noire/etat", tags=["Liste noire WhatsApp"])
    async def etat(telephone: str, user: dict = Depends(get_current_user)):
        """Un seul booléen : la liste elle-même n'est visible que dans les Paramètres."""
        _peut_bloquer(user)
        return {"bloque": await liste_noire_wa.est_bloque(db, telephone)}

    @api.get("/admin/wa/liste-noire", tags=["Liste noire WhatsApp"])
    async def liste(user: dict = Depends(get_current_user)):
        _peut_bloquer(user)
        entrees = await liste_noire_wa.lister(db)
        return {"total": len(entrees), "maximum": liste_noire_wa.MAX_ENTREES, "entrees": entrees}

    @api.delete("/admin/wa/liste-noire/{cle}", tags=["Liste noire WhatsApp"])
    async def debloquer(cle: str, user: dict = Depends(get_current_user)):
        _peut_bloquer(user)
        if not await liste_noire_wa.debloquer(db, cle):
            raise HTTPException(status_code=404, detail="Ce numéro n'est pas dans la liste noire")
        return {"ok": True}
