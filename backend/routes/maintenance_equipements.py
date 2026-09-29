"""Lot 41 — Maintenance des équipements confiés.

Un client confie un matériel (ordinateur, imprimante, onduleur…) pour réparation. Chaque
dépôt est une FICHE :
  - numéro automatique MNT-<CODE>-<AAAA>-0001 (par client et par année) ;
  - client (contact de l'annuaire ou saisi librement, avec téléphone) ;
  - date de réception, type de matériel (liste extensible par client), marque / modèle /
    numéro de série, état du matériel à la réception (mauvais, moyen, bon), motif ;
  - diagnostic, remplacement de pièces nécessaire (oui / non + pièces), observations ;
  - date d'entrée en atelier, date de sortie (restitution) ; statut suivi : reçu, en
    diagnostic, en réparation, prêt, rendu.

Fonction activable « Maintenance des équipements » (clé `maintenance_equipements`), par
l'Admin ou le Superviseur (SMART Communications), contrôlée côté serveur.

  GET    /api/me/maintenance                 fiches (filtres q, statut, type)
  POST   /api/me/maintenance                 nouvelle fiche (numéro automatique)
  GET    /api/me/maintenance/{id}            une fiche
  PUT    /api/me/maintenance/{id}            modification (diagnostic, pièces, sortie…)
  DELETE /api/me/maintenance/{id}            suppression (Admin, Superviseur ou compte client)
  GET    /api/me/maintenance-types           types de matériel (liste par défaut + ajouts)
  POST   /api/me/maintenance-types           {libelle} : nouveau type
  DELETE /api/me/maintenance-types/{id}

Collections : maintenance_fiches, maintenance_types, compteurs.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

CLE_FONCTION = "maintenance_equipements"
TYPES_PAR_DEFAUT = ["Ordinateur portable", "Ordinateur de bureau", "Imprimante", "Onduleur", "Écran",
                    "Téléphone", "Tablette", "Serveur", "Équipement réseau", "Autre"]
ETATS = ("mauvais", "moyen", "bon")
STATUTS = ("recu", "diagnostic", "reparation", "pret", "rendu")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


class FicheIn(BaseModel):
    contact_id: Optional[str] = None
    client_nom: Optional[str] = Field(None, max_length=160)
    client_telephone: Optional[str] = Field(None, max_length=40)
    date_reception: Optional[str] = None
    type_materiel: str = Field(..., min_length=1, max_length=80)
    marque_modele: Optional[str] = Field(None, max_length=160)
    numero_serie: Optional[str] = Field(None, max_length=80)
    etat_materiel: Literal["mauvais", "moyen", "bon"] = "moyen"
    motif: str = Field(..., min_length=1, max_length=2000)
    diagnostic: Optional[str] = Field(None, max_length=4000)
    remplacement_pieces: bool = False
    pieces: Optional[str] = Field(None, max_length=2000)
    observations: Optional[str] = Field(None, max_length=2000)
    date_entree: Optional[str] = None
    date_sortie: Optional[str] = None
    statut: Optional[Literal["recu", "diagnostic", "reparation", "pret", "rendu"]] = None


class TypeIn(BaseModel):
    libelle: str = Field(..., min_length=2, max_length=80)


def statut_de(fiche: Dict[str, Any]) -> str:
    """Statut affiché : « rendu » dès qu'une date de sortie est portée ; sinon celui choisi."""
    if fiche.get("date_sortie"):
        return "rendu"
    return fiche.get("statut") if fiche.get("statut") in STATUTS[:-1] else "recu"


def attach_maintenance_routes(*, api, db, get_current_user, fonction_active=None,
                              slugify_code: Callable[[str], str] = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())[:4] or "CLI",
                              is_admin_like: Callable[[dict], bool] = lambda u: u.get("role") in ("admin", "superviseur"),
                              ) -> Dict[str, Any]:

    def _tenant(user: dict) -> str:
        return user.get("parent_client_id") or user.get("client_id") or user["id"]

    async def utilisateur(user: dict = Depends(get_current_user)) -> dict:
        if fonction_active is not None and not await fonction_active(user, CLE_FONCTION):
            raise HTTPException(status_code=403, detail="La fonction « Maintenance des équipements » n'est pas activée "
                                                        "pour votre compte. Demandez son activation à votre "
                                                        "administrateur SAWALI.")
        return user

    def _perimetre(user: dict) -> Dict[str, Any]:
        return {} if is_admin_like(user) else {"tenant_id": _tenant(user)}

    async def _numero(tenant_id: str) -> str:
        compte = await db.users.find_one({"id": tenant_id}, {"_id": 0, "client_code": 1, "company": 1,
                                                             "full_name": 1}) or {}
        code = compte.get("client_code") or slugify_code(compte.get("company") or compte.get("full_name") or "CLI")
        annee = datetime.now(timezone.utc).year
        c = await db.compteurs.find_one_and_update({"_id": f"maintenance:{tenant_id}:{annee}"}, {"$inc": {"n": 1}},
                                                   upsert=True, return_document=True)
        n = (c or {}).get("n") or 1
        return f"MNT-{code}-{annee}-{n:04d}"

    async def _client(user: dict, data: FicheIn) -> Dict[str, Any]:
        """Client de la fiche : contact de l'annuaire du client connecté, ou saisi librement."""
        if data.contact_id:
            q = {"id": data.contact_id}
            if not is_admin_like(user):
                q["client_id"] = {"$in": list({_tenant(user), user.get("client_id"), user["id"]} - {None})}
            c = await db.directory_contacts.find_one(q, {"_id": 0, "id": 1, "name": 1, "company": 1,
                                                         "phone": 1, "whatsapp": 1})
            if not c:
                raise HTTPException(status_code=400, detail="Contact introuvable dans votre annuaire")
            return {"contact_id": c["id"], "client_nom": c.get("name") or c.get("company") or "",
                    "client_telephone": data.client_telephone or c.get("whatsapp") or c.get("phone") or ""}
        if not (data.client_nom or "").strip():
            raise HTTPException(status_code=400, detail="Indiquez le client (contact ou nom)")
        return {"contact_id": None, "client_nom": data.client_nom.strip(),
                "client_telephone": (data.client_telephone or "").strip()}

    async def _fiche(user: dict, fid: str) -> Dict[str, Any]:
        f = await db.maintenance_fiches.find_one({"id": fid, **_perimetre(user)}, {"_id": 0})
        if not f:
            raise HTTPException(status_code=404, detail="Fiche introuvable")
        return f

    def _champs(data: FicheIn) -> Dict[str, Any]:
        d = data.model_dump(exclude={"contact_id", "client_nom", "client_telephone"})
        for k in ("marque_modele", "numero_serie", "diagnostic", "pieces", "observations"):
            d[k] = (d.get(k) or "").strip() or None
        d["type_materiel"] = d["type_materiel"].strip()
        d["motif"] = d["motif"].strip()
        if d.get("date_sortie") and d.get("date_entree") and d["date_sortie"] < d["date_entree"]:
            raise HTTPException(status_code=400, detail="La date de sortie précède la date d'entrée")
        return d

    # ---- Types de matériel ----------------------------------------------------------
    @api.get("/me/maintenance-types", tags=["Maintenance"])
    async def types(user: dict = Depends(utilisateur)):
        ajoutes = await db.maintenance_types.find({"tenant_id": _tenant(user)}, {"_id": 0}).sort("libelle", 1).to_list(200)
        return {"defaut": TYPES_PAR_DEFAUT, "ajoutes": ajoutes,
                "tous": TYPES_PAR_DEFAUT[:-1] + [t["libelle"] for t in ajoutes] + TYPES_PAR_DEFAUT[-1:]}

    @api.post("/me/maintenance-types", tags=["Maintenance"])
    async def ajouter_type(data: TypeIn, user: dict = Depends(utilisateur)):
        libelle = data.libelle.strip()
        existe = [t.lower() for t in TYPES_PAR_DEFAUT] + [
            t["libelle"].lower() async for t in db.maintenance_types.find({"tenant_id": _tenant(user)}, {"libelle": 1})]
        if libelle.lower() in existe:
            raise HTTPException(status_code=409, detail="Ce type existe déjà")
        doc = {"id": secrets.token_hex(6), "tenant_id": _tenant(user), "libelle": libelle, "cree_le": _maintenant()}
        await db.maintenance_types.insert_one(dict(doc))
        return doc

    @api.delete("/me/maintenance-types/{tid}", tags=["Maintenance"])
    async def supprimer_type(tid: str, user: dict = Depends(utilisateur)):
        r = await db.maintenance_types.delete_one({"id": tid, "tenant_id": _tenant(user)})
        if not r.deleted_count:
            raise HTTPException(status_code=404, detail="Type introuvable")
        return {"ok": True}

    # ---- Fiches -------------------------------------------------------------------------
    @api.get("/me/maintenance", tags=["Maintenance"])
    async def lister(q: Optional[str] = None, statut: Optional[str] = None, type_materiel: Optional[str] = None,
                     user: dict = Depends(utilisateur)):
        filtre: Dict[str, Any] = dict(_perimetre(user))
        if type_materiel:
            filtre["type_materiel"] = type_materiel
        if q and q.strip():
            motif = {"$regex": re.escape(q.strip()), "$options": "i"}
            filtre["$or"] = [{"numero": motif}, {"client_nom": motif}, {"client_telephone": motif},
                             {"marque_modele": motif}, {"numero_serie": motif}, {"motif": motif}]
        fiches = await db.maintenance_fiches.find(filtre, {"_id": 0}).sort("date_reception", -1).to_list(1000)
        for f in fiches:
            f["statut"] = statut_de(f)
        if statut:
            fiches = [f for f in fiches if f["statut"] == statut]
        compte = {s: 0 for s in STATUTS}
        for f in fiches:
            compte[f["statut"]] += 1
        return {"fiches": fiches, "compte": compte}

    @api.post("/me/maintenance", tags=["Maintenance"])
    async def creer(data: FicheIn, user: dict = Depends(utilisateur)):
        tenant_id = _tenant(user)
        doc = {"id": secrets.token_hex(8), "tenant_id": tenant_id, "numero": await _numero(tenant_id),
               **await _client(user, data), **_champs(data),
               "cree_par": user.get("full_name") or user.get("email") or user["id"], "cree_le": _maintenant(),
               "maj_le": _maintenant()}
        doc["date_reception"] = doc.get("date_reception") or _maintenant()[:10]
        doc["statut"] = statut_de(doc)
        await db.maintenance_fiches.insert_one(dict(doc))
        return doc

    @api.get("/me/maintenance/{fid}", tags=["Maintenance"])
    async def lire(fid: str, user: dict = Depends(utilisateur)):
        f = await _fiche(user, fid)
        f["statut"] = statut_de(f)
        return f

    @api.put("/me/maintenance/{fid}", tags=["Maintenance"])
    async def modifier(fid: str, data: FicheIn, user: dict = Depends(utilisateur)):
        await _fiche(user, fid)
        maj = {**await _client(user, data), **_champs(data), "maj_le": _maintenant(),
               "maj_par": user.get("full_name") or user.get("email") or user["id"]}
        maj["statut"] = statut_de(maj)
        await db.maintenance_fiches.update_one({"id": fid}, {"$set": maj})
        return await lire(fid, user)

    @api.delete("/me/maintenance/{fid}", tags=["Maintenance"])
    async def supprimer(fid: str, user: dict = Depends(utilisateur)):
        f = await _fiche(user, fid)
        if not (is_admin_like(user) or user["id"] == f["tenant_id"]):
            raise HTTPException(status_code=403, detail="Seul le compte client ou l'Admin peut supprimer une fiche")
        await db.maintenance_fiches.delete_one({"id": fid})
        return {"ok": True}

    return {"statut_de": statut_de}
