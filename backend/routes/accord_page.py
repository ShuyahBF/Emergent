# accord_page.py — Lot 164 : PAGE WEB d'accord WhatsApp, avec un LIEN PERSONNEL par contact.
#
# Constat du propriétaire (14/10/2026) : le lien d'accord copié depuis la page Carrousel est un lien wa.me
# (« https://wa.me/<numéro>?text=OUI NOUVEAUTES »). Mis dans le bouton d'un message WhatsApp et touché sur un
# téléphone, il rouvre simplement la conversation avec le numéro de SAWALI : il n'enregistre rien tant que la
# personne n'envoie pas elle-même le mot-clé. Demande : une page SAWALI qui enregistre l'accord.
#
# En résumé (pour un développeur WinDev) :
#   - LIEN PERSONNEL : <site>/accord/<jeton>, où le jeton = identifiant du contact + signature HMAC (secret du
#     serveur). Pas de saisie de numéro, pas de nouvelle collection : le jeton ne peut pas être fabriqué ni
#     transposé à un autre contact. Il n'expire pas (la personne peut retirer son accord à tout moment).
#   - PAGE PUBLIQUE : la personne voit « <expéditeur> souhaite vous envoyer ses nouveautés par WhatsApp » et
#     choisit « Oui, j'accepte » ou « Non merci » (ou retire un accord déjà donné). C'est ELLE qui clique :
#     SAWALI ne coche jamais l'accord à sa place (règle du lot 79, loi n° 001-2021/AN).
#   - ENREGISTREMENT : même fonction que le mot-clé WhatsApp (accord_whatsapp.noter_accord), moyen « page web » ;
#     preuve ajoutée au journal `accords_whatsapp_journal` (numéro, date, moyen).
#   - CONFIDENTIALITÉ : la page ne montre que le prénom et les 2 derniers chiffres du numéro.
# Routes publiques : GET et POST /api/public/accord/{jeton}.
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel

logger = logging.getLogger("sawali.accord_page")

EXPEDITEUR_DEFAUT = "SAWALI SMART SYSTEMS"
CHEMIN_PAGE = "/accord/"
LONGUEUR_SIGNATURE = 24          # caractères hexadécimaux conservés de la signature


def _secret() -> bytes:
    """Secret de signature des liens : le même que celui des sessions (JWT_SECRET). Absent = pas de lien."""
    s = (os.environ.get("JWT_SECRET") or "").strip()
    if not s:
        raise RuntimeError("JWT_SECRET absent : impossible de signer les liens d'accord")
    return s.encode()


def _signature(contact_id: str) -> str:
    return hmac.new(_secret(), f"accord:{contact_id}".encode(), hashlib.sha256).hexdigest()[:LONGUEUR_SIGNATURE]


def creer_jeton(contact_id: str) -> str:
    """Jeton du lien personnel : identifiant du contact (base64 sans remplissage) + signature."""
    brut = base64.urlsafe_b64encode(contact_id.encode()).decode().rstrip("=")
    return f"{brut}.{_signature(contact_id)}"


def lire_jeton(jeton: str) -> Optional[str]:
    """Identifiant du contact si la signature est bonne, None sinon (jeton falsifié ou mal recopié)."""
    try:
        brut, sig = (jeton or "").split(".", 1)
        contact_id = base64.urlsafe_b64decode(brut + "=" * (-len(brut) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    return contact_id if contact_id and hmac.compare_digest(sig, _signature(contact_id)) else None


def lien_personnel(base: str, contact_id: str) -> str:
    return f"{base.rstrip('/')}{CHEMIN_PAGE}{creer_jeton(contact_id)}"


def _prenom(nom: Optional[str]) -> str:
    """Premier mot du nom (jamais le nom complet sur une page publique)."""
    mots = (nom or "").split()
    return mots[0][:30] if mots else ""


class ChoixIn(BaseModel):
    accepte: bool


def setup_accord_page_routes(*, db, api) -> None:
    """Branche les routes publiques du lot 164 (appelée depuis server_parts/p20)."""
    from fastapi import HTTPException

    # Fiches qui peuvent porter un lien d'accord : contacts de l'annuaire, utilisateurs suivis, comptes clients
    # (collection, champ du nom, champs du numéro) — mêmes fiches que la liste des destinataires du carrousel
    FICHES = (("directory_contacts", "name", ("whatsapp", "phone")),
              ("tracked_users", "name", ("whatsapp_number", "phone")),
              ("users", "full_name", ("whatsapp_number", "phone")))

    async def _contact(jeton: str) -> Dict[str, Any]:
        """Fiche normalisée {id, nom, numero, client_id, accepte_whatsapp, accepte_whatsapp_le, _coll}."""
        contact_id = lire_jeton(jeton)
        if not contact_id:
            raise HTTPException(status_code=404, detail="Lien d'accord invalide ou incomplet")
        for coll, champ_nom, champs_num in FICHES:
            c = await db[coll].find_one({"id": contact_id}, {"_id": 0, "id": 1, champ_nom: 1, "client_id": 1,
                                                              "accepte_whatsapp": 1, "accepte_whatsapp_le": 1,
                                                              **{k: 1 for k in champs_num}})
            if c:
                numero = next((c[k] for k in champs_num if c.get(k)), "")
                return {"id": c["id"], "nom": c.get(champ_nom) or "", "numero": numero,
                        "client_id": c.get("client_id") if coll != "users" else None,
                        "accepte_whatsapp": c.get("accepte_whatsapp"), "accepte_whatsapp_le": c.get("accepte_whatsapp_le"),
                        "_coll": coll}
        raise HTTPException(status_code=404, detail="Contact introuvable")

    async def _expediteur(c: Dict[str, Any]) -> str:
        """Nom de l'expéditeur : la société du client propriétaire du carnet, sinon SAWALI."""
        cid = c.get("client_id")
        if cid:
            u = await db.users.find_one({"id": cid}, {"_id": 0, "company": 1, "role": 1})
            if u and u.get("role") != "admin" and (u.get("company") or "").strip():
                return u["company"].strip()[:80]
        return EXPEDITEUR_DEFAUT

    @api.get("/public/accord/{jeton}", tags=["Public — Accord WhatsApp"])
    async def lire(jeton: str):
        """Ce que la page affiche : prénom, expéditeur, 2 derniers chiffres du numéro et accord actuel."""
        c = await _contact(jeton)
        chiffres = re.sub(r"\D", "", c["numero"])
        return {"prenom": _prenom(c["nom"]), "expediteur": await _expediteur(c), "fin_numero": chiffres[-2:],
                "accepte": c.get("accepte_whatsapp"), "accepte_le": c.get("accepte_whatsapp_le")}

    @api.post("/public/accord/{jeton}", tags=["Public — Accord WhatsApp"])
    async def choisir(jeton: str, choix: ChoixIn):
        """La personne accepte ou retire son accord : enregistré comme un mot-clé WhatsApp, moyen « page web »."""
        from routes import accord_whatsapp as aw
        c = await _contact(jeton)
        chiffres = re.sub(r"\D", "", c["numero"])
        if len(chiffres) < 8:
            raise HTTPException(status_code=422, detail="Ce contact n'a pas de numéro WhatsApp")
        # Numéro WhatsApp qui envoie pour ce carnet (client avec son propre numéro) : même portée que le mot-clé
        numero_recu = None
        if c.get("client_id"):
            t = await db.tenant_smart_comm.find_one({"tenant_id": c["client_id"]}, {"_id": 0, "wa_phone_number_id": 1})
            numero_recu = ((t or {}).get("wa_phone_number_id") or "").strip() or None
        await aw.noter_accord(db, chiffres, choix.accepte, numero_recu=numero_recu, moyen="page web")
        # Si la portée du numéro n'a retrouvé aucune fiche (carnet à part), la fiche du lien est notée quand même
        await db[c["_coll"]].update_one({"id": c["id"], "accepte_whatsapp": {"$ne": choix.accepte}}, {"$set": {
            "accepte_whatsapp": choix.accepte,
            "accepte_whatsapp_le": datetime.now(timezone.utc).isoformat() if choix.accepte else None,
            "accepte_whatsapp_par": "la personne elle-même (page web)", "accepte_whatsapp_moyen": "page web"}})
        return {"ok": True, "accepte": choix.accepte,
                "message": aw.REPONSE_OUI if choix.accepte else aw.REPONSE_NON}
