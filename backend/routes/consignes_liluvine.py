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
import commande_hfsql_wa as chw
import raccourcis_hfsql as rh
import consignes_masse as cm
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


class ApercuMasse(BaseModel):
    message: str = Field(min_length=5, max_length=1000)
    rdv_du: str = ""                           # AAAA-MM-JJ
    rdv_au: str = ""


class ConfirmationMasse(BaseModel):
    apercu_id: str = Field(min_length=4, max_length=40)
    empreinte: str = Field(min_length=8, max_length=64)       # celle de l'aperçu que la personne a VU


class ModeleMasse(BaseModel):
    nom: str = Field(default="", max_length=120)
    langue: str = Field(default="fr", max_length=10)


class SoumissionModele(BaseModel):
    nom: str = Field(default="", max_length=120)             # vide = nom par défaut (cm.MODELE_NOM)


class RaccourciHfsql(BaseModel):
    nom: str = Field(default="", max_length=80)
    sql: str = Field(default="", max_length=4100)
    zone: str = Field(default="", max_length=40)
    confirmer: bool = False


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

    # ---- Lot 456 : envois en masse — APERÇU (rien ne part) puis CONFIRMATION (liée à l'aperçu vu) puis envoi en arrière-plan
    @api.post("/admin/liluvine-consignes/masse/apercu", tags=["Liluvine — consignes"])
    async def masse_apercu(payload: ApercuMasse, user: dict = Depends(get_current_user)):
        await _autoriser(user)
        try:
            ap = await cm.apercu(db, payload.message, payload.rdv_du, payload.rdv_au, _par(user))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"id": ap["id"], "empreinte": ap["empreinte"], "message": ap["message"], "du": ap["du"], "au": ap["au"], "total": len(ap["destinataires"]),
                "exclus": ap["exclus"], "expire_le": ap["expire_le"],
                "destinataires": [{"nom": d["nom"], "telephone": cm.masquer(d["telephone"]), "quand": d["quand"]} for d in ap["destinataires"]]}

    @api.post("/admin/liluvine-consignes/masse/confirmer", tags=["Liluvine — consignes"])
    async def masse_confirmer(payload: ConfirmationMasse, user: dict = Depends(get_current_user)):
        await _autoriser(user)

        envoyeur, fenetre, modeleur = cm.envoyeurs_serveur()

        try:
            lot = await cm.confirmer(db, payload.apercu_id, payload.empreinte, _par(user), envoyeur, fenetre, modeleur=modeleur)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "lot": lot}

    @api.get("/admin/liluvine-consignes/masse/modele", tags=["Liluvine — consignes"])
    async def masse_modele(user: dict = Depends(get_current_user)):
        """Modèle Meta réglé + le texte à SOUMETTRE à Meta (nom, catégorie, corps, bouton « Bien reçu »)."""
        await _autoriser(user)
        return {"modele": await cm.lire_modele(db), "soumission": await cm.lire_soumission(db),
                "a_soumettre": {"nom": cm.MODELE_NOM, "categorie": "UTILITY", "langue": "fr", "corps": cm.MODELE_CORPS, "bouton": cm.MODELE_BOUTON, "exemples": cm.MODELE_EXEMPLES}}

    # ---- Lot 460 : soumettre le modèle à Meta depuis SAWALI et suivre son statut (administrateur SEUL ; Meta n'est interrogé que par ces deux boutons)
    @api.post("/admin/liluvine-consignes/masse/modele/soumettre", tags=["Liluvine — consignes"])
    async def masse_modele_soumettre(payload: SoumissionModele, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        try:
            return {"ok": True, "soumission": await cm.soumettre_modele(db, payload.nom or None)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.get("/admin/liluvine-consignes/masse/modele/statut", tags=["Liluvine — consignes"])
    async def masse_modele_statut(nom: str = "", user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        try:
            return {"ok": True, "soumission": await cm.statut_modele(db, nom or None)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.put("/admin/liluvine-consignes/masse/modele", tags=["Liluvine — consignes"])
    async def masse_regler_modele(payload: ModeleMasse, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        try:
            return {"ok": True, "modele": await cm.regler_modele(db, payload.nom, payload.langue)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.get("/admin/liluvine-consignes/masse/envois", tags=["Liluvine — consignes"])
    async def masse_envois(user: dict = Depends(get_current_user)):
        await _autoriser(user)
        return {"envois": await cm.lots(db)}

    # ---- Lot 458 : Commande HFSQL distante via Liluvine — numéros autorisés (ADMINISTRATEUR SEUL : touche des données réelles) et journal
    @api.get("/admin/liluvine-hfsql-acces", tags=["Liluvine — consignes"])
    async def hfsql_acces(user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return {"acces": await chw.lister_acces(db), "maximum": chw.MAX_ACCES, "journal": (await chw.journal(db))[:50]}

    @api.put("/admin/liluvine-hfsql-acces", tags=["Liluvine — consignes"])
    async def hfsql_regler_acces(payload: ListeAcces, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return {"ok": True, "acces": await chw.enregistrer_acces(db, payload.acces)}

    # ---- Lot 459 : raccourcis de commandes HFSQL avec paramètres {nom} (administrateur SEUL)
    @api.get("/admin/liluvine-hfsql-raccourcis", tags=["Liluvine — consignes"])
    async def hfsql_raccourcis(user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return {"raccourcis": await rh.lister(db), "maximum": rh.MAX_RACCOURCIS}

    @api.post("/admin/liluvine-hfsql-raccourcis", tags=["Liluvine — consignes"], status_code=201)
    async def hfsql_raccourci_creer(payload: RaccourciHfsql, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        try:
            return {"raccourci": await rh.creer(db, payload.nom, payload.sql, payload.zone, payload.confirmer, _par(user))}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.put("/admin/liluvine-hfsql-raccourcis/{identifiant}", tags=["Liluvine — consignes"])
    async def hfsql_raccourci_modifier(identifiant: str, payload: RaccourciHfsql, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        try:
            return {"raccourci": await rh.modifier(db, identifiant, payload.nom, payload.sql, payload.zone, payload.confirmer)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.delete("/admin/liluvine-hfsql-raccourcis/{identifiant}", tags=["Liluvine — consignes"])
    async def hfsql_raccourci_supprimer(identifiant: str, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        if not await rh.supprimer(db, identifiant):
            raise HTTPException(status_code=404, detail="Raccourci introuvable.")
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
