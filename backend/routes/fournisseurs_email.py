"""Lot 52 — Service d'envoi des e-mails de la plateforme (super-admin SAWALI uniquement).

  GET  /api/admin/email-fournisseur            réglages (jamais de clé : `a_cle: true/false`),
                                               service effectif, aides, avertissement SMTP
  PUT  /api/admin/email-fournisseur            {fournisseur, actif, expediteur, nom_affiche, cle,
                                                zeptomail_hote, smtp: {hote, port, utilisateur,
                                                mot_de_passe, starttls}} ; champ secret vide = conservé
  POST /api/admin/email-fournisseur/essai      {destinataire?} : essai avec les réglages ENREGISTRÉS,
                                               renvoie le message d'erreur du fournisseur
  GET  /api/admin/email-fournisseur/journal    modifications (qui, quand, quel fournisseur) et derniers envois

La logique est dans backend/email_fournisseurs.py ; l'envoi dans backend/email_service.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import email_fournisseurs as ef
import email_service
from auth import get_super_admin

router = APIRouter(prefix="/admin/email-fournisseur", tags=["Service d'envoi des e-mails (lot 52)"])


class SmtpIn(BaseModel):
    hote: Optional[str] = Field(None, max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    utilisateur: Optional[str] = Field(None, max_length=255)
    mot_de_passe: Optional[str] = Field(None, max_length=1000)
    starttls: Optional[bool] = None


class ReglagesIn(BaseModel):
    fournisseur: Optional[str] = Field(None, max_length=20)
    actif: Optional[bool] = None
    expediteur: Optional[str] = Field(None, max_length=254)
    nom_affiche: Optional[str] = Field(None, max_length=200)
    cle: Optional[str] = Field(None, max_length=1000)
    zeptomail_hote: Optional[str] = Field(None, max_length=40)
    smtp: Optional[SmtpIn] = None


class EssaiIn(BaseModel):
    destinataire: Optional[str] = Field(None, max_length=254)


@router.get("")
async def route_vue(_: dict = Depends(get_super_admin)):
    return await ef.vue_publique()


@router.put("")
async def route_enregistrer(corps: ReglagesIn, adm: dict = Depends(get_super_admin)):
    try:
        return await ef.enregistrer(corps.model_dump(), adm)
    except ef.ReglagesInvalides as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/essai")
async def route_essai(corps: EssaiIn, adm: dict = Depends(get_super_admin)):
    """Essai avec les réglages enregistrés : le message d'erreur du fournisseur est renvoyé tel quel."""
    dest = (corps.destinataire or adm.get("email") or "").strip()
    if not ef.adresse_valide(dest):
        raise HTTPException(status_code=400, detail="Adresse du destinataire invalide")
    cfg = await ef.configuration_effective()
    if not cfg.get("fournisseur"):
        await ef.journaliser_envoi(ef.NON_CONFIGURE, None, dest, "Essai", cfg.get("raison"), origine="essai")
        return {"ok": False, "fournisseur": None, "destinataire": dest,
                "erreur": cfg.get("raison") or "Aucun service d'envoi configuré"}
    sujet = "Essai d'envoi SAWALI"
    texte = (f"Ceci est un e-mail d'essai envoyé par {ef.LIBELLES[cfg['fournisseur']]} depuis les Paramètres "
             "de SAWALI. Aucune action n'est attendue.")
    html = f"<p>{texte}</p>"
    try:
        res = await email_service.envoyer_avec_config(cfg, dest, sujet, html, texte, timeout_s=20.0)
    except Exception as exc:  # noqa: BLE001 — message du fournisseur affiché (jamais la clé)
        await ef.journaliser_envoi(ef.ECHEC, cfg["fournisseur"], dest, sujet, str(exc), origine="essai")
        return {"ok": False, "fournisseur": cfg["fournisseur"], "source": cfg.get("source"),
                "destinataire": dest, "erreur": str(exc)[:ef.LONGUEUR_ERREUR]}
    await ef.journaliser_envoi(ef.ENVOYE, cfg["fournisseur"], dest, sujet, origine="essai")
    return {"ok": True, "fournisseur": cfg["fournisseur"], "source": cfg.get("source"), "destinataire": dest,
            "id": res.get("id")}


@router.get("/journal")
async def route_journal(limite: int = 50, _: dict = Depends(get_super_admin)):
    return await ef.journal(limite)
