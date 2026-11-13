"""Lot 379 — API « Ma famille » (voir services/famille.py). Authentification par appareil : en-têtes X-Famille-Compte et X-Famille-Jeton.

  POST   /api/famille/inscription                 {nom, cle_publique} -> {compte_id, jeton}   (public : crée un compte)
  POST   /api/famille/invitations                 -> {code, expire_le}
  POST   /api/famille/invitations/accepter        {code} -> {lien_id}
  GET    /api/famille/liens                       liens avec le correspondant (nom, clé publique) et l'état de vérification
  POST   /api/famille/liens/{id}/verifier         je confirme le numéro de sécurité
  DELETE /api/famille/liens/{id}                  rompt le lien (efface les messages)
  POST   /api/famille/liens/{id}/messages         {nonce, chiffre}   (lien vérifié seulement)
  GET    /api/famille/liens/{id}/messages?apres=  messages après le curseur
  PUT    /api/famille/liens/{id}/position         {nonce, chiffre} ma dernière position chiffrée (lien vérifié)
  GET    /api/famille/liens/{id}/position         la dernière position (chiffrée) de l'autre personne
  DELETE /api/famille/liens/{id}/position         j'arrête de partager (effacée)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Body, Depends, Header, HTTPException, Query

from services import famille as fam


def setup_famille_routes(app, db, get_current_user=None):
    api = app
    etat = {"index": False}

    async def _compte(x_famille_compte: Optional[str] = Header(None), x_famille_jeton: Optional[str] = Header(None)) -> dict:
        if not etat["index"]:
            etat["index"] = True
            try:
                await fam.assurer_index(db)
            except Exception:   # noqa: BLE001 — jamais bloquant
                pass
        compte = await fam.authentifier(db, x_famille_compte, x_famille_jeton)
        if not compte:
            raise HTTPException(status_code=401, detail="Compte famille non reconnu.")
        return compte

    @api.post("/famille/inscription", tags=["Ma famille"])
    async def inscription(donnees: Dict[str, Any] = Body(...)):
        try:
            return await fam.inscrire(db, donnees.get("nom"), donnees.get("cle_publique"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.post("/famille/invitations", tags=["Ma famille"])
    async def invitation(compte: dict = Depends(_compte)):
        return await fam.creer_invitation(db, compte)

    @api.post("/famille/invitations/accepter", tags=["Ma famille"])
    async def accepter(donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        try:
            return await fam.accepter_invitation(db, compte, donnees.get("code"))
        except PermissionError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.get("/famille/liens", tags=["Ma famille"])
    async def liens(compte: dict = Depends(_compte)):
        return {"liens": await fam.lister_liens(db, compte)}

    @api.post("/famille/liens/{lien_id}/verifier", tags=["Ma famille"])
    async def verifier(lien_id: str, compte: dict = Depends(_compte)):
        try:
            return await fam.confirmer_verification(db, compte, lien_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @api.delete("/famille/liens/{lien_id}", tags=["Ma famille"])
    async def rompre(lien_id: str, compte: dict = Depends(_compte)):
        try:
            await fam.supprimer_lien(db, compte, lien_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True}

    @api.post("/famille/liens/{lien_id}/messages", tags=["Ma famille"])
    async def envoyer(lien_id: str, donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        try:
            return await fam.envoyer_message(db, compte, lien_id, donnees.get("nonce"), donnees.get("chiffre"))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.get("/famille/liens/{lien_id}/messages", tags=["Ma famille"])
    async def lire(lien_id: str, apres: int = Query(0), compte: dict = Depends(_compte)):
        try:
            return {"messages": await fam.lire_messages(db, compte, lien_id, apres)}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @api.put("/famille/liens/{lien_id}/position", tags=["Ma famille"])
    async def deposer_pos(lien_id: str, donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        try:
            return await fam.deposer_position(db, compte, lien_id, donnees.get("nonce"), donnees.get("chiffre"))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.get("/famille/liens/{lien_id}/position", tags=["Ma famille"])
    async def lire_pos(lien_id: str, compte: dict = Depends(_compte)):
        try:
            return {"position": await fam.lire_position(db, compte, lien_id)}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @api.delete("/famille/liens/{lien_id}/position", tags=["Ma famille"])
    async def effacer_pos(lien_id: str, compte: dict = Depends(_compte)):
        try:
            await fam.effacer_position(db, compte, lien_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True}

    # État pour la rubrique des Paramètres (administrateur / superviseur) : COMPTAGES seulement, jamais un nom, une clé ou un message.
    if get_current_user is not None:
        @api.get("/admin/famille/etat", tags=["Ma famille"])
        async def etat_famille(user: dict = Depends(get_current_user)):
            if (user or {}).get("role") not in ("admin", "superviseur"):
                raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
            return {
                "comptes": await db.famille_comptes.count_documents({}),
                "liens": await db.famille_liens.count_documents({}),
                "liens_verifies": await db.famille_liens.count_documents({"statut": "verifie"}),
                "messages": await db.famille_messages.count_documents({}),
                "positions_partagees": await db.famille_positions.count_documents({}),
                "invitations_en_cours": await db.famille_invitations.count_documents({}),
            }
