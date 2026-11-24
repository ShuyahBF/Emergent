# routes/liste_noire_wa.py — routes de la LISTE NOIRE WhatsApp (lot 453). Règles et stockage : voir backend/liste_noire_wa.py.
#   POST   /me/wa/liste-noire           bloquer un contact (administrateur, depuis le Centre de Messagerie)
#   GET    /me/wa/liste-noire/etat      ce numéro est-il bloqué ? (réponse : un booléen seulement ; la liste n'est jamais exposée ici)
#   GET    /admin/wa/liste-noire        la liste complète (administrateur, Paramètres uniquement)
#   DELETE /admin/wa/liste-noire/{cle}  débloquer (administrateur, Paramètres uniquement)
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import liste_noire_wa

ROLES_ADMIN = ("admin", "super_admin")


# Modèle au NIVEAU DU MODULE : FastAPI ne retrouve pas les modèles déclarés dans une fonction (annotations différées)
class BlocageContact(BaseModel):
    telephone: str = Field(min_length=6, max_length=30)
    nom: Optional[str] = Field(default="", max_length=120)
    contact_id: Optional[str] = None
    motif: Optional[str] = Field(default="", max_length=300)


def setup_liste_noire_wa_routes(*, db, api, get_current_user) -> None:
    def _admin(user: dict) -> None:
        if user.get("role") not in ROLES_ADMIN:
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    @api.post("/me/wa/liste-noire", tags=["Liste noire WhatsApp"])
    async def bloquer(payload: BlocageContact, user: dict = Depends(get_current_user)):
        """Bloque un contact sur TOUTES les lignes : plus aucun message sortant, plus de réponse d'agent IA, messages reçus retenus."""
        _admin(user)
        try:
            entree = await liste_noire_wa.bloquer(db, payload.telephone, nom=payload.nom or "", contact_id=payload.contact_id,
                                                  motif=payload.motif or "", par=user.get("full_name") or user.get("email") or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "bloque": True, "nom": entree["nom"]}

    @api.get("/me/wa/liste-noire/etat", tags=["Liste noire WhatsApp"])
    async def etat(telephone: str, user: dict = Depends(get_current_user)):
        """Un seul booléen : la liste elle-même n'est visible que dans les Paramètres."""
        _admin(user)
        return {"bloque": await liste_noire_wa.est_bloque(db, telephone)}

    @api.get("/admin/wa/liste-noire", tags=["Liste noire WhatsApp"])
    async def liste(user: dict = Depends(get_current_user)):
        _admin(user)
        entrees = await liste_noire_wa.lister(db)
        return {"total": len(entrees), "maximum": liste_noire_wa.MAX_ENTREES, "entrees": entrees}

    @api.delete("/admin/wa/liste-noire/{cle}", tags=["Liste noire WhatsApp"])
    async def debloquer(cle: str, user: dict = Depends(get_current_user)):
        _admin(user)
        if not await liste_noire_wa.debloquer(db, cle):
            raise HTTPException(status_code=404, detail="Ce numéro n'est pas dans la liste noire")
        return {"ok": True}
