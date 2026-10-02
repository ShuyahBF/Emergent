"""Lot 50 — Maintenance de la plateforme (déconnexion programmée de tous les utilisateurs).

- GET  /api/maintenance/etat                          : état PUBLIC et léger, interrogé par le
                                                        site toutes les 15 s ;
- GET  /api/admin/deconnexion-generale                : état complet + journal (super-admin) ;
- POST /api/admin/deconnexion-generale                : annoncer une déconnexion ;
- POST /api/admin/deconnexion-generale/annuler        : annuler avant l'échéance ;
- POST /api/admin/deconnexion-generale/reactiver      : rétablir les connexions.

Les actions sont réservées au super-admin SAWALI (SUPER_ADMIN_EMAIL) : un Admin de client
(rôle `admin` rattaché à un client) ne peut pas déconnecter toute la plateforme.
La logique (phases, blocage des sessions) est dans backend/maintenance_plateforme.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

import maintenance_plateforme as service
from auth import get_super_admin

public = APIRouter(prefix="/maintenance", tags=["Maintenance de la plateforme (public)"])
admin = APIRouter(prefix="/admin/deconnexion-generale", tags=["Maintenance de la plateforme (super-admin)"])


@public.get("/etat")
async def etat():
    """État de la maintenance pour tous les visiteurs (sans auteur ni journal), avec l'heure
    du serveur pour caler le décompte du navigateur."""
    return service.etat_public(await service.lire_document())


class Annonce(BaseModel):
    message: str = Field(..., max_length=service.MESSAGE_MAX)
    duree_minutes: int = Field(service.DUREE_DEFAUT, ge=service.DUREE_MIN, le=service.DUREE_MAX)
    part_verrouillage: int = Field(service.PART_VERROUILLAGE_DEFAUT, ge=0, le=100)

    @field_validator("message")
    @classmethod
    def _message_non_vide(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("message obligatoire")
        return v


async def _etat_complet(doc: dict) -> dict:
    return {**service.etat_public(doc), "annonce_par": doc.get("annonce_par") if doc.get("actif") else None,
            "sessions_valides_apres": doc.get("sessions_valides_apres"), "journal": await service.journal()}


@admin.get("")
async def lire(_: dict = Depends(get_super_admin)):
    return await _etat_complet(await service.lire_document(cache=False))


@admin.post("")
async def annoncer(payload: Annonce, adm: dict = Depends(get_super_admin)):
    return await _etat_complet(await service.annoncer(payload.message, payload.duree_minutes,
                                                      payload.part_verrouillage, adm))


@admin.post("/annuler")
async def annuler(adm: dict = Depends(get_super_admin)):
    return await _etat_complet(await service.annuler(adm))


@admin.post("/reactiver")
async def reactiver(adm: dict = Depends(get_super_admin)):
    return await _etat_complet(await service.reactiver(adm))
