"""Lot 34 — Fonctions activables par client, par l'Admin ET le Superviseur.

« Formulaires et Sondages » (clé `forms_surveys`) et « OCR sur Pièces » (clé
`ocr_pieces`) ne sont accessibles à un compte client, et à ses utilisateurs suivis,
que si elles sont activées sur ce compte dans SMART Communications (champ
`users.features`, comme les autres fonctions). Admin et Superviseur y ont toujours
accès. Le contrôle est fait CÔTÉ SERVEUR, le menu ne fait que le refléter.

Contrairement aux autres fonctions de SMART Communications (réservées à l'Admin),
ces deux-là peuvent aussi être activées par le Superviseur :
  GET  /api/supervision/fonctions-clients               comptes clients + état des 2 fonctions
  PUT  /api/supervision/fonctions-clients/{client_id}   {forms_surveys?, ocr_pieces?}
Chaque changement est tracé sur le compte (`features_journal`, 100 derniers).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

FONCTIONS_SUPERVISEUR = {"forms_surveys": "Formulaires et Sondages", "ocr_pieces": "OCR sur Pièces",
                         # Lot 39 — photo d'ordonnance → disponibilité dans le stock du client
                         "ordonnances_stock": "Ordonnances et stock"}
# Comptes listés : les rôles « métier » (pas l'Admin ni le Superviseur, qui ont tout).
ROLES_CLIENTS = ["client", "pharmacien", "medecin", "regulateur", "editeur_vidal", "moderateur", "moderator"]
COMPTE_PLATEFORME = "admin@sawalismartsystems.com"


class FonctionsClientUpdate(BaseModel):
    forms_surveys: Optional[bool] = None
    ocr_pieces: Optional[bool] = None
    ordonnances_stock: Optional[bool] = None


def attach_fonctions_clients_routes(*, api, db, get_current_user, get_admin_or_supervisor,
                                    normalize_features: Callable[[Any], Dict[str, Any]],
                                    now: Callable[[], str]) -> Dict[str, Any]:
    """Branche les routes du Superviseur et renvoie les outils de contrôle d'accès :
    {fonction_active, fonction_active_pour_compte, exiger_fonction}."""

    async def fonction_active(user: dict, cle: str) -> bool:
        """Fonction `cle` accessible à cet utilisateur ? Admin/Superviseur : toujours.
        Sinon : réglage du compte client dont il dépend (même règle que /me/features)."""
        if user.get("role") in ("admin", "superviseur"):
            return True
        parent_id = user.get("parent_client_id") or user.get("client_id") or user.get("id")
        parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
        return bool(normalize_features((parent or {}).get("features")).get(cle))

    async def fonction_active_pour_compte(compte_id: Optional[str], cle: str) -> bool:
        """Même contrôle à partir du compte propriétaire (liens publics d'un formulaire
        ou d'un sondage : le répondant n'est pas connecté)."""
        if not compte_id:
            return False
        compte = await db.users.find_one({"id": compte_id},
                                         {"_id": 0, "id": 1, "role": 1, "client_id": 1, "parent_client_id": 1})
        return bool(compte) and await fonction_active(compte, cle)

    def exiger_fonction(cle: str):
        """Dépendance FastAPI : utilisateur connecté ET fonction `cle` activée (sinon 403)."""
        async def dependance(user: dict = Depends(get_current_user)) -> dict:
            if not await fonction_active(user, cle):
                raise HTTPException(
                    status_code=403,
                    detail=f"La fonction « {FONCTIONS_SUPERVISEUR[cle]} » n'est pas activée pour votre compte. "
                           "Demandez son activation à votre administrateur SAWALI.")
            return user
        return dependance

    @api.get("/supervision/fonctions-clients", tags=["Admin"])
    async def lister(_: dict = Depends(get_admin_or_supervisor)):
        """Comptes clients (pas les utilisateurs suivis : ils héritent de leur client)."""
        requete = {
            "role": {"$in": ROLES_CLIENTS},
            "email": {"$nin": [COMPTE_PLATEFORME]},
            "$or": [{"parent_client_id": {"$exists": False}}, {"parent_client_id": {"$in": [None, ""]}}],
        }
        comptes = await db.users.find(requete, {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1,
                                                 "client_code": 1, "role": 1, "features": 1}).to_list(3000)
        lignes = []
        for c in comptes:
            f = normalize_features(c.get("features"))
            lignes.append({"id": c["id"], "company": c.get("company"), "full_name": c.get("full_name"),
                           "email": c.get("email"), "client_code": c.get("client_code"), "role": c.get("role"),
                           **{cle: bool(f.get(cle)) for cle in FONCTIONS_SUPERVISEUR}})
        lignes.sort(key=lambda x: (x.get("company") or x.get("full_name") or x.get("email") or "").lower())
        return {"fonctions": FONCTIONS_SUPERVISEUR, "clients": lignes}

    @api.put("/supervision/fonctions-clients/{client_id}", tags=["Admin"])
    async def modifier(client_id: str, payload: FonctionsClientUpdate, qui: dict = Depends(get_admin_or_supervisor)):
        """Active / désactive les 2 fonctions d'un client. Ne touche à AUCUNE autre
        fonction de SMART Communications (celles-ci restent réservées à l'Admin)."""
        u = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "features": 1})
        if not u:
            raise HTTPException(status_code=404, detail="Client introuvable")
        changements = payload.model_dump(exclude_none=True)
        if not changements:
            raise HTTPException(status_code=400, detail="Aucune fonction à modifier")
        features = normalize_features(u.get("features"))
        features.update({k: bool(v) for k, v in changements.items()})
        journal = [{"le": now(), "par": qui.get("email") or qui["id"], "role": qui.get("role"), "cle": k,
                    "active": bool(v)} for k, v in changements.items()]
        await db.users.update_one({"id": client_id}, {
            "$set": {"features": features, "features_updated_at": now()},
            "$push": {"features_journal": {"$each": journal, "$slice": -100}},
        })
        return {"id": client_id, **{cle: bool(features.get(cle)) for cle in FONCTIONS_SUPERVISEUR}}

    return {"fonction_active": fonction_active, "fonction_active_pour_compte": fonction_active_pour_compte,
            "exiger_fonction": exiger_fonction}
