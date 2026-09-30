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

Lot 43 :
  - client = COMPTE CLIENT (tenant) pour l'Admin et le Superviseur ; son téléphone est
    celui qui reçoit les alertes et messages de la société (`whatsapp_number`, sinon
    `phone`). Les autres comptes gardent leurs contacts d'annuaire ;
  - prix du diagnostic (10 000 F par défaut, modifiable) et équipe (texte libre) ;
  - photos de l'équipement ou des pièces (annotées dans le navigateur avant l'envoi),
    téléchargeables ;
  - envoi de la fiche par WhatsApp (texte + photos si le contact a écrit dans les 24 h,
    sinon modèle Meta, la 1re photo en en-tête image si le modèle en a une) ;
  - lien de paiement Mobile Money (montant du diagnostic par défaut) et « Facturer »
    (facture ou proforma dans la Caisse).

  GET    /api/me/maintenance                 fiches (filtres q, statut, type)
  POST   /api/me/maintenance                 nouvelle fiche (numéro automatique)
  GET    /api/me/maintenance/{id}            une fiche
  PUT    /api/me/maintenance/{id}            modification (diagnostic, pièces, sortie…)
  DELETE /api/me/maintenance/{id}            suppression (Admin, Superviseur ou compte client)
  GET    /api/me/maintenance-types           types de matériel (liste par défaut + ajouts)
  POST   /api/me/maintenance-types           {libelle} : nouveau type
  DELETE /api/me/maintenance-types/{id}
  GET    /api/me/maintenance-clients            clients proposés (comptes clients ou contacts)
  POST   /api/me/maintenance/{id}/photos        photo (JPEG / PNG, 5 Mo) — lot 43
  DELETE /api/me/maintenance/{id}/photos/{pid}
  POST   /api/me/maintenance/{id}/whatsapp      envoi de la fiche (et des photos) par WhatsApp
  POST   /api/me/maintenance/{id}/lien-paiement lien de paiement Mobile Money
  POST   /api/me/maintenance/{id}/facturer      facture (ou proforma) dans la Caisse

Collections : maintenance_fiches, maintenance_types, compteurs (+ payment_links, invoices).
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

from fastapi import Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

CLE_FONCTION = "maintenance_equipements"
TYPES_PAR_DEFAUT = ["Ordinateur portable", "Ordinateur de bureau", "Imprimante", "Onduleur", "Écran",
                    "Téléphone", "Tablette", "Serveur", "Équipement réseau", "Autre"]
ETATS = ("mauvais", "moyen", "bon")
STATUTS = ("recu", "diagnostic", "reparation", "pret", "rendu")
LIBELLES_STATUT = {"recu": "Reçu", "diagnostic": "En diagnostic", "reparation": "En réparation",
                   "pret": "Prêt à rendre", "rendu": "Rendu"}
PRIX_DIAGNOSTIC_DEFAUT = 10000                 # lot 43 : FCFA, modifiable sur chaque fiche
PHOTOS_MAX = 12
PHOTO_MAX_OCTETS = 5 * 1024 * 1024             # limite Meta d'une image WhatsApp
TYPES_PHOTO = {"image/jpeg": "jpg", "image/png": "png"}
ROLES_COMPTES = ["client", "pharmacien", "medecin", "regulateur", "editeur_vidal", "moderateur", "moderator"]


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


class FicheIn(BaseModel):
    compte_client_id: Optional[str] = None              # lot 43 : compte client (tenant)
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
    prix_diagnostic: int = Field(PRIX_DIAGNOSTIC_DEFAUT, ge=0, le=100_000_000)   # lot 43
    equipe: Optional[str] = Field(None, max_length=300)                          # lot 43 : noms, texte libre


class EnvoiWhatsAppIn(BaseModel):
    """Lot 43 — envoi de la fiche : texte libre (fenêtre de 24 h) ou modèle Meta."""
    mode: Literal["auto", "text", "template"] = "auto"
    message: Optional[str] = Field(None, max_length=3000)
    photos: bool = True
    inclure_lien_paiement: bool = True
    template_name: Optional[str] = None
    language_code: Optional[str] = "fr"
    variables: List[str] = Field(default_factory=list)
    header_text: Optional[str] = None
    header_image: bool = False                          # en-tête image du modèle = 1re photo
    button_specs: Optional[List[Dict[str, Any]]] = None


class LienPaiementIn(BaseModel):
    montant: Optional[int] = Field(None, gt=0, le=100_000_000)   # par défaut : prix du diagnostic


class FacturerIn(BaseModel):
    kind: Literal["invoice", "proforma"] = "invoice"
    lignes: List[Dict[str, Any]] = Field(default_factory=list)  # {label, quantity, unit_price_ht} en plus du diagnostic


class TypeIn(BaseModel):
    libelle: str = Field(..., min_length=2, max_length=80)


def statut_de(fiche: Dict[str, Any]) -> str:
    """Statut affiché : « rendu » dès qu'une date de sortie est portée ; sinon celui choisi."""
    if fiche.get("date_sortie"):
        return "rendu"
    return fiche.get("statut") if fiche.get("statut") in STATUTS[:-1] else "recu"


def montant_fr(n: Any) -> str:
    """10000 -> « 10 000 » (espaces des milliers)."""
    try:
        return f"{int(round(float(n or 0))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def texte_fiche(f: Dict[str, Any], lien_paiement: Optional[str] = None) -> str:
    """Lot 43 — résumé de la fiche envoyé par WhatsApp."""
    lignes = [f"🛠️ *Fiche de maintenance {f.get('numero')}*",
              f"Client : {f.get('client_nom') or '—'}",
              f"Matériel : {f.get('type_materiel')}" + (f" — {f['marque_modele']}" if f.get("marque_modele") else ""),
              ]
    if f.get("numero_serie"):
        lignes.append(f"N° de série : {f['numero_serie']}")
    lignes += [f"Reçu le : {(f.get('date_reception') or '')[:10]}",
               f"État à la réception : {dict(zip(ETATS, ('Mauvais', 'Moyen', 'Bon'))).get(f.get('etat_materiel'), '—')}",
               f"Motif : {f.get('motif')}",
               f"Statut : {LIBELLES_STATUT.get(statut_de(f), '—')}"]
    if f.get("diagnostic"):
        lignes.append(f"Diagnostic : {f['diagnostic']}")
    if f.get("remplacement_pieces"):
        lignes.append(f"Pièces à remplacer : {f.get('pieces') or 'oui'}")
    if f.get("equipe"):
        lignes.append(f"Équipe : {f['equipe']}")
    if f.get("date_sortie"):
        lignes.append(f"Restitué le : {f['date_sortie'][:10]}")
    lignes.append(f"Prix du diagnostic : *{montant_fr(f.get('prix_diagnostic'))} FCFA*")
    if f.get("observations"):
        lignes.append(f"Observations : {f['observations']}")
    if lien_paiement:
        lignes.append(f"\n💳 Payer par Mobile Money : {lien_paiement}")
    return "\n".join(lignes)


def attach_maintenance_routes(*, api, db, get_current_user, fonction_active=None,
                              slugify_code: Callable[[str], str] = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())[:4] or "CLI",
                              is_admin_like: Callable[[dict], bool] = lambda u: u.get("role") in ("admin", "superviseur"),
                              # Lot 43 — branchements (facultatifs : sans eux, la fonction répond 503)
                              save_and_log=None,               # stockage des photos (routes object storage)
                              base_publique: Callable[[], str] = lambda: "",
                              wa_send_text=None, wa_send_media=None, wa_send_template=None,
                              build_components=None, fenetres_ouvertes=None,   # async ([chiffres]) -> set
                              gen_slug=None, mnos_du_compte=None,             # async (compte_id) -> [MNO]
                              paiements_autorises=None,                       # async (user) -> bool
                              create_invoice_for_client=None,
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
        """Client de la fiche : compte client (Admin / Superviseur, lot 43), contact de
        l'annuaire du client connecté, ou saisi librement."""
        if data.compte_client_id:
            if not is_admin_like(user):
                raise HTTPException(status_code=403, detail="Seuls l'Admin et le Superviseur choisissent un compte client")
            u = await db.users.find_one({"id": data.compte_client_id}, {"_id": 0, "id": 1, "company": 1, "full_name": 1,
                                                                        "email": 1, "whatsapp_number": 1, "phone": 1})
            if not u:
                raise HTTPException(status_code=400, detail="Compte client introuvable")
            return {"compte_client_id": u["id"], "contact_id": None,
                    "client_nom": u.get("company") or u.get("full_name") or u.get("email") or "",
                    # numéro qui reçoit les alertes et messages de la société
                    "client_telephone": data.client_telephone or u.get("whatsapp_number") or u.get("phone") or ""}
        if data.contact_id:
            q = {"id": data.contact_id}
            if not is_admin_like(user):
                q["client_id"] = {"$in": list({_tenant(user), user.get("client_id"), user["id"]} - {None})}
            c = await db.directory_contacts.find_one(q, {"_id": 0, "id": 1, "name": 1, "company": 1,
                                                         "phone": 1, "whatsapp": 1})
            if not c:
                raise HTTPException(status_code=400, detail="Contact introuvable dans votre annuaire")
            return {"compte_client_id": None, "contact_id": c["id"], "client_nom": c.get("name") or c.get("company") or "",
                    "client_telephone": data.client_telephone or c.get("whatsapp") or c.get("phone") or ""}
        if not (data.client_nom or "").strip():
            raise HTTPException(status_code=400, detail="Indiquez le client (contact ou nom)")
        return {"compte_client_id": None, "contact_id": None, "client_nom": data.client_nom.strip(),
                "client_telephone": (data.client_telephone or "").strip()}

    async def _fiche(user: dict, fid: str) -> Dict[str, Any]:
        f = await db.maintenance_fiches.find_one({"id": fid, **_perimetre(user)}, {"_id": 0})
        if not f:
            raise HTTPException(status_code=404, detail="Fiche introuvable")
        return f

    async def _etat_paiement(fiches: List[Dict[str, Any]]) -> None:
        """Lot 43 — `lien_paiement.paye` : le lien de paiement de la fiche a-t-il été utilisé ?"""
        ids = [f["lien_paiement"]["id"] for f in fiches if (f.get("lien_paiement") or {}).get("id")]
        if not ids:
            return
        payes = {l["id"] async for l in db.payment_links.find({"id": {"$in": ids}, "uses_count": {"$gte": 1}},
                                                              {"_id": 0, "id": 1})}
        for f in fiches:
            if f.get("lien_paiement"):
                f["lien_paiement"]["paye"] = f["lien_paiement"].get("id") in payes

    def _champs(data: FicheIn) -> Dict[str, Any]:
        d = data.model_dump(exclude={"compte_client_id", "contact_id", "client_nom", "client_telephone"})
        for k in ("marque_modele", "numero_serie", "diagnostic", "pieces", "observations", "equipe"):
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
        await _etat_paiement(fiches)
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
        await _etat_paiement([f])
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

    # ---- Lot 43 : clients proposés -----------------------------------------------------
    @api.get("/me/maintenance-clients", tags=["Maintenance"])
    async def clients(user: dict = Depends(utilisateur)):
        """Admin / Superviseur : comptes clients (tenants), avec le numéro qui reçoit les
        alertes de la société. Autres comptes : les contacts de leur annuaire."""
        if is_admin_like(user):
            comptes = await db.users.find(
                {"role": {"$in": ROLES_COMPTES},
                 "$or": [{"parent_client_id": {"$exists": False}}, {"parent_client_id": {"$in": [None, ""]}}]},
                {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1, "client_code": 1,
                 "whatsapp_number": 1, "phone": 1}).to_list(3000)
            items = [{"type": "compte", "id": c["id"], "nom": c.get("company") or c.get("full_name") or c.get("email") or "",
                      "code": c.get("client_code") or "", "telephone": c.get("whatsapp_number") or c.get("phone") or ""}
                     for c in comptes]
        else:
            ids = list({_tenant(user), user.get("client_id"), user["id"]} - {None})
            contacts = await db.directory_contacts.find({"client_id": {"$in": ids}},
                                                        {"_id": 0, "id": 1, "name": 1, "company": 1, "whatsapp": 1,
                                                         "phone": 1}).to_list(5000)
            items = [{"type": "contact", "id": c["id"], "nom": c.get("name") or c.get("company") or "",
                      "code": c.get("company") or "", "telephone": c.get("whatsapp") or c.get("phone") or ""}
                     for c in contacts]
        items.sort(key=lambda x: (x["nom"] or "").lower())
        return {"type": "compte" if is_admin_like(user) else "contact", "items": items}

    # ---- Lot 43 : photos -----------------------------------------------------------------
    @api.post("/me/maintenance/{fid}/photos", tags=["Maintenance"])
    async def ajouter_photo(fid: str, fichier: UploadFile = File(...), user: dict = Depends(utilisateur)):
        if save_and_log is None:
            raise HTTPException(status_code=503, detail="Stockage des photos indisponible")
        f = await _fiche(user, fid)
        if len(f.get("photos") or []) >= PHOTOS_MAX:
            raise HTTPException(status_code=400, detail=f"{PHOTOS_MAX} photos au maximum par fiche")
        ext = TYPES_PHOTO.get((fichier.content_type or "").lower())
        if not ext:
            raise HTTPException(status_code=400, detail="Photo JPEG ou PNG uniquement (formats acceptés par WhatsApp)")
        data = await fichier.read(PHOTO_MAX_OCTETS + 1)
        if len(data) > PHOTO_MAX_OCTETS:
            raise HTTPException(status_code=400, detail="Photo trop lourde : 5 Mo au maximum")
        saved = await save_and_log(db, data=data, kind="maintenance", tenant_id=f["tenant_id"], ext=ext,
                                   content_type=fichier.content_type, original_filename=fichier.filename,
                                   user_id=user.get("id"))
        # Adresse publique (https) : affichée et téléchargeable dans le portail, lue par WhatsApp
        url = saved["url"] if saved["url"].startswith("http") else base_publique().rstrip("/") + saved["url"]
        photo = {"id": secrets.token_hex(6), "url": url, "nom": (fichier.filename or f"photo.{ext}")[:120],
                 "ajoutee_le": _maintenant(), "par": user.get("full_name") or user.get("email")}
        await db.maintenance_fiches.update_one({"id": fid}, {"$push": {"photos": photo}, "$set": {"maj_le": _maintenant()}})
        return photo

    @api.delete("/me/maintenance/{fid}/photos/{pid}", tags=["Maintenance"])
    async def supprimer_photo(fid: str, pid: str, user: dict = Depends(utilisateur)):
        await _fiche(user, fid)
        await db.maintenance_fiches.update_one({"id": fid}, {"$pull": {"photos": {"id": pid}}})
        return {"ok": True}

    def _url(u: str) -> str:
        """Adresse publique (https) d'un fichier : WhatsApp la télécharge lui-même."""
        if not u or u.startswith("http"):
            return u
        return base_publique().rstrip("/") + u

    # ---- Lot 43 : lien de paiement ---------------------------------------------------------
    async def _lien_paiement(user: dict, f: Dict[str, Any], montant: Optional[int]) -> Dict[str, Any]:
        if gen_slug is None:
            raise HTTPException(status_code=503, detail="Liens de paiement indisponibles")
        if paiements_autorises is not None and not await paiements_autorises(user):
            raise HTTPException(status_code=403, detail="Paiements non autorisés pour votre compte")
        montant = int(montant or f.get("prix_diagnostic") or 0)
        if montant <= 0:
            raise HTTPException(status_code=400, detail="Indiquez un prix de diagnostic ou un montant")
        mnos = list(await mnos_du_compte(f["tenant_id"])) if mnos_du_compte else []
        if not mnos:
            raise HTTPException(status_code=400, detail="Aucun opérateur Mobile Money configuré pour ce compte")
        slug = None
        for _ in range(8):
            c = gen_slug(8)
            if not await db.payment_links.find_one({"slug": c}, {"_id": 1}):
                slug = c
                break
        if not slug:
            raise HTTPException(status_code=500, detail="Impossible de créer le lien, réessayez")
        doc = {"id": secrets.token_hex(8), "slug": slug, "client_id": f["tenant_id"], "owner_user_id": user["id"],
               "owner_email": user.get("email"), "owner_label": user.get("full_name") or user.get("email"),
               "label": f"Maintenance {f['numero']}", "amount": float(montant), "currency": "XOF",
               "description": f"Diagnostic {f.get('type_materiel')} — fiche {f['numero']}"[:200],
               "allowed_mnos": mnos, "expires_at": None, "max_uses": 1, "uses_count": 0, "disabled": False,
               "maintenance_fiche_id": f["id"], "prefill_phone": f.get("client_telephone") or "",
               "prefill_name": f.get("client_nom") or "", "created_at": _maintenant(), "updated_at": _maintenant()}
        await db.payment_links.insert_one(dict(doc))
        lien = {"id": doc["id"], "slug": slug, "url": f"{base_publique().rstrip('/')}/pay/{slug}", "montant": montant,
                "cree_le": _maintenant()}
        await db.maintenance_fiches.update_one({"id": f["id"]}, {"$set": {"lien_paiement": lien}})
        return lien

    @api.post("/me/maintenance/{fid}/lien-paiement", tags=["Maintenance"])
    async def creer_lien_paiement(fid: str, data: LienPaiementIn, user: dict = Depends(utilisateur)):
        return await _lien_paiement(user, await _fiche(user, fid), data.montant)

    # ---- Lot 43 : envoi par WhatsApp --------------------------------------------------------
    @api.post("/me/maintenance/{fid}/whatsapp", tags=["Maintenance"])
    async def envoyer_whatsapp(fid: str, data: EnvoiWhatsAppIn, user: dict = Depends(utilisateur)):
        if wa_send_text is None:
            raise HTTPException(status_code=503, detail="WhatsApp indisponible")
        f = await _fiche(user, fid)
        tel = (f.get("client_telephone") or "").strip()
        chiffres = "".join(ch for ch in tel if ch.isdigit())
        if len(chiffres) < 8:
            raise HTTPException(status_code=400, detail="Numéro WhatsApp du client manquant sur la fiche")
        lien = (f.get("lien_paiement") or {}).get("url") if data.inclure_lien_paiement else None
        ouverte = chiffres in (await fenetres_ouvertes([chiffres]) if fenetres_ouvertes else set())
        mode = data.mode if data.mode != "auto" else ("text" if ouverte else "template")
        photos = [p for p in (f.get("photos") or [])] if data.photos else []
        rapport: Dict[str, Any] = {"mode": mode, "fenetre_ouverte": ouverte, "texte": False, "photos_envoyees": 0,
                                   "photos_non_envoyees": 0, "erreurs": []}
        if mode == "text":
            if not ouverte:
                raise HTTPException(status_code=400, detail=(
                    "Fenêtre de 24 h fermée : ce client ne vous a pas écrit récemment. Choisissez un modèle Meta."))
            corps = (data.message or "").strip() or texte_fiche(f, lien)
            r = await wa_send_text(tel, corps)
            rapport["texte"] = bool(r.get("ok"))
            if not r.get("ok"):
                raise HTTPException(status_code=502, detail=f"Envoi refusé par WhatsApp : {r.get('error')}")
            for i, p in enumerate(photos, 1):
                rm = await wa_send_media(tel, "image", public_url=_url(p["url"]),
                                         caption=f"{f['numero']} — photo {i}/{len(photos)}") if wa_send_media else {"ok": False}
                if rm.get("ok"):
                    rapport["photos_envoyees"] += 1
                else:
                    rapport["erreurs"].append(f"Photo {i} : {rm.get('error') or 'non envoyée'}")
        else:
            if not data.template_name or wa_send_template is None or build_components is None:
                raise HTTPException(status_code=400, detail=(
                    "Fenêtre de 24 h fermée : choisissez un modèle Meta approuvé pour envoyer la fiche"))
            ctx = {"numero": f["numero"], "client": f.get("client_nom") or "", "full_name": f.get("client_nom") or "",
                   "materiel": f"{f.get('type_materiel')}" + (f" {f['marque_modele']}" if f.get("marque_modele") else ""),
                   "statut": LIBELLES_STATUT.get(statut_de(f), ""), "diagnostic": f.get("diagnostic") or "",
                   "prix": f"{montant_fr(f.get('prix_diagnostic'))} FCFA", "equipe": f.get("equipe") or "",
                   "lien_paiement": lien or "", "motif": f.get("motif") or ""}
            if data.header_image and not photos:
                # Meta refuse un modèle à en-tête image envoyé sans image : message clair avant l'envoi
                raise HTTPException(status_code=400, detail=(
                    "Ce modèle a un en-tête image, mais la fiche n'a aucune photo (ou « Joindre les photos » "
                    "est décoché). Ajoutez une photo à la fiche, ou choisissez un modèle sans en-tête image "
                    "(ex. sawali_fiche_maintenance_texte)."))
            entete = {"kind": "image", "link": _url(photos[0]["url"])} if data.header_image else None
            comps = build_components(data.variables or [], ctx, header_text=data.header_text,
                                     header_media=entete, button_specs=data.button_specs)
            r = await wa_send_template(tel, data.template_name, data.language_code or "fr", comps)
            if not r.get("ok"):
                raise HTTPException(status_code=502, detail=f"Envoi refusé par WhatsApp : {r.get('error')}")
            rapport["texte"] = True
            rapport["photos_envoyees"] = 1 if entete else 0
            # Hors fenêtre de 24 h, WhatsApp refuse les images libres : elles partiront à la
            # prochaine réponse du client (nouvel envoi en message libre).
            rapport["photos_non_envoyees"] = len(photos) - rapport["photos_envoyees"]
        trace = {"le": _maintenant(), "par": user.get("full_name") or user.get("email"), "mode": mode,
                 "photos": rapport["photos_envoyees"], "modele": data.template_name if mode == "template" else None}
        await db.maintenance_fiches.update_one({"id": fid}, {"$push": {"envois_whatsapp": {"$each": [trace], "$slice": -30}}})
        try:
            await db.whatsapp_messages.insert_one({
                "id": secrets.token_hex(12), "client_id": f["tenant_id"], "direction": "outbound",
                "sender_id": user["id"], "sender_label": user.get("full_name") or user.get("email"),
                "to": tel, "phone_digits": chiffres, "message_type": "text" if mode == "text" else "template",
                "template_name": data.template_name if mode == "template" else None,
                "body": texte_fiche(f, lien) if mode == "text" else f"[Maintenance] {f['numero']}",
                "maintenance_fiche_id": fid, "ok": True, "wa_status": "sent", "sent_at": _maintenant(),
                "created_at": _maintenant()})
        except Exception:  # noqa: BLE001 — la trace ne bloque pas l'envoi
            pass
        return rapport

    # ---- Lot 43 : facturation (Caisse) --------------------------------------------------------
    @api.post("/me/maintenance/{fid}/facturer", tags=["Maintenance"])
    async def facturer(fid: str, data: FacturerIn, user: dict = Depends(utilisateur)):
        if create_invoice_for_client is None:
            raise HTTPException(status_code=503, detail="Caisse indisponible")
        f = await _fiche(user, fid)
        if data.kind == "invoice" and (f.get("facture") or {}).get("kind") == "invoice":
            raise HTTPException(status_code=409, detail=f"Fiche déjà facturée ({f['facture']['numero']})")
        lignes = []
        if f.get("prix_diagnostic"):
            lignes.append({"label": f"Diagnostic {f.get('type_materiel')}"
                                    + (f" {f['marque_modele']}" if f.get("marque_modele") else "") + f" — fiche {f['numero']}",
                           "quantity": 1, "unit_price_ht": float(f["prix_diagnostic"]), "tva_pct": 0})
        for l in data.lignes[:30]:
            try:
                lignes.append({"label": str(l["label"]).strip()[:300], "quantity": float(l.get("quantity") or 1),
                               "unit_price_ht": float(l["unit_price_ht"]), "tva_pct": float(l.get("tva_pct") or 0)})
            except (KeyError, TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Ligne de facture invalide (libellé et prix obligatoires)")
        if not lignes:
            raise HTTPException(status_code=400, detail="Rien à facturer : indiquez un prix de diagnostic ou des lignes")
        if f.get("compte_client_id"):
            client = await db.users.find_one({"id": f["compte_client_id"]}, {"_id": 0}) or {}
        else:
            # Client sans compte : fiche client de la Caisse créée à partir de la fiche
            client = {}
        client = {"id": client.get("id") or f.get("contact_id") or f"maintenance-{f['id']}",
                  "company": client.get("company") or f.get("client_nom"), "full_name": client.get("full_name"),
                  "email": client.get("email"), "phone": client.get("phone") or f.get("client_telephone"),
                  "whatsapp": client.get("whatsapp_number") or f.get("client_telephone"),
                  **{k: client.get(k) for k in ("billing_address", "city", "nif", "ifu", "rccm") if client.get(k)}}
        facture = await create_invoice_for_client(user, client, lignes, notes=f"Maintenance — fiche {f['numero']}",
                                                  kind=data.kind, source="maintenance")
        ref = {"id": facture["id"], "numero": facture.get("number"), "kind": data.kind,
               "montant": facture.get("net_to_pay"), "le": _maintenant()}
        await db.maintenance_fiches.update_one({"id": fid}, {"$set": {"facture": ref}})
        return ref

    return {"statut_de": statut_de}
