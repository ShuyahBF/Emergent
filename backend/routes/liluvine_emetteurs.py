"""Lot 57.4 — « Transmission WA Universelle Liluvine » : gestion des plateformes
émettrices (une clé HMAC propre à chacune) et journal des transmissions.

Routes (administrateur SAWALI) :
    GET    /api/admin/liluvine-emetteurs                 liste (jamais les clés) + envois du jour
    POST   /api/admin/liluvine-emetteurs                 créer {code, nom, quota_jour} -> clé affichée UNE fois
    POST   /api/admin/liluvine-emetteurs/{code}/regenerer nouvelle clé -> affichée UNE fois
    PATCH  /api/admin/liluvine-emetteurs/{code}          {nom, actif, quota_jour}
    DELETE /api/admin/liluvine-emetteurs/{code}
    GET    /api/admin/liluvine-transmissions?limite=100  journal (sans le texte des messages)

La clé n'est renvoyée qu'au moment de sa création / régénération, pour être
copiée dans la variable d'environnement LILUVINE_WA_HMAC de la plateforme.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

CODE_VALIDE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,29}$")   # ex. ster, adlyn, albarka, beauthentik


class NouvelEmetteur(BaseModel):
    code: str
    nom: str
    quota_jour: Optional[int] = 500


class ModifEmetteur(BaseModel):
    nom: Optional[str] = None
    actif: Optional[bool] = None
    quota_jour: Optional[int] = None


def _nouvelle_cle() -> str:
    """Clé aléatoire forte : 48 octets -> 64 caractères (base64 URL)."""
    return secrets.token_urlsafe(48)


def make_liluvine_emetteurs_router(*, db, get_current_admin) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["Liluvine — Transmission WA Universelle"])

    @router.get("/liluvine-emetteurs")
    async def lister(admin: dict = Depends(get_current_admin)):
        """Plateformes émettrices, sans leurs clés, avec le nombre d'envois réussis du jour."""
        debut_jour = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        sortie = []
        async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "secret": 0}).sort("code", 1):
            e["envois_du_jour"] = await db.liluvine_transmissions.count_documents(
                {"emetteur": e["code"], "ok": True, "date": {"$gte": debut_jour}})
            sortie.append(e)
        return {"emetteurs": sortie}

    @router.post("/liluvine-emetteurs")
    async def creer(donnees: NouvelEmetteur = Body(...), admin: dict = Depends(get_current_admin)):
        """Nouvelle plateforme émettrice : la clé est renvoyée cette seule fois."""
        code = donnees.code.strip().lower()
        if not CODE_VALIDE.match(code):
            raise HTTPException(status_code=422, detail="Code invalide (minuscules, chiffres, - ou _ ; 2 à 30 caractères)")
        if await db.liluvine_emetteurs.find_one({"code": code}):
            raise HTTPException(status_code=409, detail="Ce code existe déjà")
        cle = _nouvelle_cle()
        maintenant = datetime.now(timezone.utc).isoformat()
        await db.liluvine_emetteurs.insert_one({
            "code": code, "nom": donnees.nom.strip()[:60] or code, "secret": cle, "actif": True,
            "quota_jour": max(1, int(donnees.quota_jour or 500)), "cree_le": maintenant,
            "cle_regeneree_le": maintenant, "cree_par": admin.get("email"),
        })
        return {"code": code, "cle": cle}

    @router.post("/liluvine-emetteurs/{code}/regenerer")
    async def regenerer(code: str, admin: dict = Depends(get_current_admin)):
        """Nouvelle clé : l'ancienne cesse aussitôt de fonctionner."""
        cle = _nouvelle_cle()
        r = await db.liluvine_emetteurs.update_one(
            {"code": code}, {"$set": {"secret": cle, "cle_regeneree_le": datetime.now(timezone.utc).isoformat(),
                                      "cle_regeneree_par": admin.get("email")}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Émetteur introuvable")
        return {"code": code, "cle": cle}

    @router.patch("/liluvine-emetteurs/{code}")
    async def modifier(code: str, donnees: ModifEmetteur = Body(...), admin: dict = Depends(get_current_admin)):
        """Nom, activation / désactivation, quota journalier."""
        changements = {}
        if donnees.nom is not None:
            changements["nom"] = donnees.nom.strip()[:60] or code
        if donnees.actif is not None:
            changements["actif"] = bool(donnees.actif)
        if donnees.quota_jour is not None:
            changements["quota_jour"] = max(1, int(donnees.quota_jour))
        if not changements:
            return {"ok": True}
        r = await db.liluvine_emetteurs.update_one({"code": code}, {"$set": changements})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Émetteur introuvable")
        return {"ok": True}

    @router.delete("/liluvine-emetteurs/{code}")
    async def supprimer(code: str, admin: dict = Depends(get_current_admin)):
        r = await db.liluvine_emetteurs.delete_one({"code": code})
        if not r.deleted_count:
            raise HTTPException(status_code=404, detail="Émetteur introuvable")
        return {"ok": True}

    @router.get("/liluvine-transmissions")
    async def journal(limite: int = 100, admin: dict = Depends(get_current_admin)):
        """Dernières transmissions (le texte des messages n'est jamais conservé)."""
        limite = max(1, min(int(limite), 500))
        lignes = await db.liluvine_transmissions.find({}, {"_id": 0}).sort("date", -1).to_list(limite)
        return {"transmissions": lignes}

    return router


__all__ = ["make_liluvine_emetteurs_router"]
