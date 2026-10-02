"""Lot 51 — Cycle de vie du non-renouvellement (super-admin SAWALI uniquement).

  GET  /api/admin/cycle-vie                          réglages, clients en retard / suspendus / archivés
                                                     (calendrier de chaque étape), dernière exécution
  PUT  /api/admin/cycle-vie/reglages                 {actif, simulation, conservation_jours,
                                                      frais_montant, frais_devise}
  POST /api/admin/cycle-vie/simuler                  liste de ce qui serait fait aujourd'hui (sans effet,
                                                     même interrupteur désactivé)
  POST /api/admin/cycle-vie/lancer                   exécution immédiate (tâche de fond ; interrupteur et
                                                     mode simulation respectés)
  POST /api/admin/cycle-vie/{client_id}/lever-suspension
  POST /api/admin/cycle-vie/{client_id}/reouvrir     {confirmation: "REOUVRIR", mot_de_passe, frais_encaisses,
                                                      reference}
  GET  /api/admin/cycle-vie/journal                  (?client_id=)

La logique est dans backend/cycle_vie_abonnements.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import cycle_vie_abonnements as cv
from auth import get_super_admin, verify_password
from db import db

router = APIRouter(prefix="/admin/cycle-vie", tags=["Cycle de vie des abonnements (lot 51)"])


class ReglagesIn(BaseModel):
    actif: Optional[bool] = None
    simulation: Optional[bool] = None
    conservation_jours: Optional[int] = Field(None, ge=cv.CONSERVATION_MIN, le=cv.CONSERVATION_MAX)
    frais_montant: Optional[float] = Field(None, ge=0)
    frais_devise: Optional[str] = Field(None, max_length=8)


class ReouvertureIn(BaseModel):
    confirmation: str
    mot_de_passe: str
    frais_encaisses: bool = False
    reference: Optional[str] = Field(None, max_length=120)


@router.get("")
async def route_vue(_: dict = Depends(get_super_admin)):
    return await cv.vue_admin()


@router.put("/reglages")
async def route_reglages(corps: ReglagesIn, adm: dict = Depends(get_super_admin)):
    avant = await cv.reglages()
    apres = await cv.definir_reglages(**corps.model_dump())
    changes = {k: {"avant": avant[k], "apres": apres[k]} for k in apres if avant[k] != apres[k]}
    if changes:
        await cv.journaliser("REGLAGES", None, adm, changements=changes)
    return apres


@router.post("/simuler")
async def route_simuler(adm: dict = Depends(get_super_admin)):
    return await cv.executer(f"simulation manuelle ({adm.get('email')})", simulation=True)


@router.post("/lancer")
async def route_lancer(adm: dict = Depends(get_super_admin)):
    reg = await cv.reglages()
    if not reg["actif"]:
        raise HTTPException(409, "Interrupteur « Cycle de vie automatique » désactivé : utilisez « Simuler maintenant »")
    if not cv.lancer_en_fond(f"lancement manuel ({adm.get('email')})"):
        raise HTTPException(409, "Une exécution est déjà en cours")
    return {"lance": True, "simulation": reg["simulation"]}


@router.get("/journal")
async def route_journal(client_id: Optional[str] = None, _: dict = Depends(get_super_admin)):
    return {"journal": await cv.journal(client_id)}


@router.post("/{client_id}/lever-suspension")
async def route_lever(client_id: str, adm: dict = Depends(get_super_admin)):
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client or cv.cycle_de(client).get("statut") != cv.SUSPENDU:
        raise HTTPException(409, "Ce client n'est pas suspendu (un client archivé se rouvre par « Réouvrir »)")
    await cv.lever_suspension(client, "levée par le super-admin", par=adm)
    return {"ok": True}


@router.post("/{client_id}/reouvrir")
async def route_reouvrir(client_id: str, corps: ReouvertureIn, adm: dict = Depends(get_super_admin)):
    if (corps.confirmation or "").strip() != "REOUVRIR":
        raise HTTPException(400, "Tapez REOUVRIR (en majuscules) pour confirmer la réouverture")
    doc = await db.users.find_one({"id": adm.get("id")}, {"_id": 0, "password_hash": 1})
    if not doc or not verify_password(corps.mot_de_passe or "", str(doc.get("password_hash") or "")):
        raise HTTPException(403, "Mot de passe incorrect")
    reg = await cv.reglages()
    if reg["frais_reouverture"]["montant"] > 0 and not corps.frais_encaisses:
        frais = reg["frais_reouverture"]
        raise HTTPException(400, f"Cochez « Frais de réouverture encaissés » ({frais['montant']:g} {frais['devise']})")
    return await cv.reouvrir(client_id, adm, corps.reference or "")
