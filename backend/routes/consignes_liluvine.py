# routes/consignes_liluvine.py — CONSIGNES À LILUVINE (lot 454). Règles et stockage : voir backend/consignes_liluvine.py.
#   GET    /admin/liluvine-consignes               consignes (actives et récentes)       administrateur, superviseur (élément « consignes » partagé)
#   POST   /admin/liluvine-consignes/interpreter   la phrase est comprise ET MONTRÉE, rien n'est activé
#   POST   /admin/liluvine-consignes               la personne VALIDE : la consigne devient active
#   POST   /admin/liluvine-consignes/{id}/arreter  arrêt immédiat
#   GET/PUT /admin/liluvine-consignes/acces        numéros WhatsApp autorisés à donner des consignes (par client / tenant)   administrateur SEUL
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import consignes_liluvine as cl
from routes.liluvine_partage import est_admin, verifier_element


# Modèles au NIVEAU DU MODULE (FastAPI ne retrouve pas ceux déclarés dans une fonction)
class PhraseConsigne(BaseModel):
    texte: str = Field(min_length=3, max_length=cl.MAX_TEXTE)


class ValidationConsigne(BaseModel):
    texte: str = Field(default="", max_length=cl.MAX_TEXTE)
    nature: str = "reponse"
    resume: str = Field(default="", max_length=300)
    instruction: str = Field(default="", max_length=cl.MAX_TEXTE)
    debut: str = ""
    fin: str = ""
    creneau_debut: str = ""                    # blocage : heure du jour de début (« 12:00 »)
    creneau_fin: str = ""


class ListeAcces(BaseModel):
    acces: List[Any] = Field(default_factory=list)


def setup_consignes_liluvine_routes(*, db, api, get_current_user) -> None:
    async def _autoriser(user: dict) -> None:
        """Administrateur toujours ; superviseur seulement si l'administrateur lui a partagé « Consignes à Liluvine »."""
        if est_admin(user):
            return
        if user.get("role") != "superviseur" and user.get("tracked_role") != "Superviseur":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur et au superviseur")
        await verifier_element(db, user, "consignes")

    def _par(user: dict) -> str:
        return user.get("full_name") or user.get("email") or ""

    @api.get("/admin/liluvine-consignes", tags=["Liluvine — consignes"])
    async def liste(user: dict = Depends(get_current_user)):
        await _autoriser(user)
        consignes = await cl.charger(db)
        for c in consignes:
            c["active_maintenant"] = cl.est_active(c)
        consignes.sort(key=lambda c: c.get("creee_le") or "", reverse=True)
        return {"consignes": consignes[:100], "natures": cl.NATURES, "appliquees": list(cl.NATURES_APPLIQUEES), "maximum": cl.MAX_CONSIGNES}

    @api.post("/admin/liluvine-consignes/interpreter", tags=["Liluvine — consignes"])
    async def interpreter(payload: PhraseConsigne, user: dict = Depends(get_current_user)):
        """Comprend la phrase et la MONTRE. Rien n'est enregistré ni activé tant que la personne n'a pas validé."""
        await _autoriser(user)
        try:
            return await cl.interpreter(payload.texte)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.post("/admin/liluvine-consignes", tags=["Liluvine — consignes"])
    async def valider(payload: ValidationConsigne, user: dict = Depends(get_current_user)):
        """La personne a lu la proposition (et pu changer les dates) et la valide : la consigne devient active."""
        await _autoriser(user)
        try:
            fiche = await cl.creer(db, payload.model_dump(), payload.texte, _par(user))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "consigne": fiche}

    @api.post("/admin/liluvine-consignes/{identifiant}/arreter", tags=["Liluvine — consignes"])
    async def arreter(identifiant: str, user: dict = Depends(get_current_user)):
        await _autoriser(user)
        if not await cl.arreter(db, identifiant, _par(user)):
            raise HTTPException(status_code=404, detail="Consigne introuvable ou déjà arrêtée")
        return {"ok": True}

    @api.get("/admin/liluvine-consignes-acces", tags=["Liluvine — consignes"])
    async def acces(user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return {"acces": await cl.lister_acces(db), "maximum": cl.MAX_ACCES}

    @api.put("/admin/liluvine-consignes-acces", tags=["Liluvine — consignes"])
    async def regler_acces(payload: ListeAcces, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return {"ok": True, "acces": await cl.enregistrer_acces(db, payload.acces)}
