"""Lot 289 — Écrans TV (Smart TV, webOS…) : page plein écran qui affiche en direct le fil du Centre de Messagerie
et les demandes de support d'un client, sans aucun bouton.

Comment ça marche (pour un développeur WinDev) :
  1. La page publique /tv s'ouvre dans le navigateur de la télé : elle fabrique un secret, le garde dans la télé et
     affiche un CODE à 6 caractères (le serveur ne garde que l'empreinte du secret, jamais le secret).
  2. L'administrateur saisit ce code dans Paramètres → « 📺 Écrans TV », choisit le client et les contenus : la télé
     est « appairée » et reçoit son flux toutes les quelques secondes avec son secret.
  3. L'administrateur peut renommer, modifier les contenus ou RÉVOQUER un écran à tout moment.

Données dans `settings.global` (aucune nouvelle collection) : `tv_ecrans` (écrans appairés) et `tv_appairages`
(codes en attente, 15 minutes, 20 au plus).
Confidentialité : les numéros de téléphone sont masqués (nom du contact, sinon « •••• 1234 »).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.ecran_tv")

VALIDITE_CODE_MIN = 15           # un code d'appairage n'est valable que 15 minutes
MAX_APPAIRAGES = 20              # codes en attente conservés au plus
MAX_MESSAGES = 30                # messages renvoyés à la télé (fil en direct)
MAX_FILS = 12                    # conversations renvoyées à la télé
FENETRE_FILS = 200               # messages récents examinés pour former les conversations
JOURS_NON_LUS = 30               # les non-lus comptés remontent à 30 jours au plus
MAX_TICKETS = 12                 # demandes de support renvoyées
ALPHABET_CODE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # sans I, L, O, 0, 1 : lisible de loin sur une télé
MODULES = ("messagerie", "support")                 # contenus possibles (le hall viendra dans un prochain lot)
STATUTS_OUVERTS = ("open", "in_progress", "suspended")


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def empreinte(secret: str) -> str:
    """Empreinte SHA-256 d'un secret : c'est la seule chose gardée côté serveur."""
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def nouveau_code() -> str:
    """Code d'appairage à 6 caractères lisibles (ex. K7MQ4X)."""
    return "".join(secrets.choice(ALPHABET_CODE) for _ in range(6))


def masquer_numero(chiffres: str) -> str:
    """« 22670001122 » → « •••• 1122 » : seuls les 4 derniers chiffres restent visibles."""
    c = "".join(ch for ch in str(chiffres or "") if ch.isdigit())
    return f"•••• {c[-4:]}" if len(c) >= 4 else "Contact"


def cle_fil(doc: Dict[str, Any]) -> str:
    """Clé d'une conversation : la fiche contact si elle existe, sinon une empreinte des 8 derniers chiffres du numéro."""
    if doc.get("contact_id"):
        return str(doc["contact_id"])
    chiffres = "".join(c for c in str(doc.get("phone_digits") or doc.get("from") or doc.get("to") or "") if c.isdigit())
    # Jamais de chiffres du numéro dans le flux envoyé à la télé : on n'expose qu'une empreinte
    return "t" + hashlib.sha1(chiffres[-8:].encode("utf-8")).hexdigest()[:10] if chiffres else "inconnu"


def forme_fils(docs: List[Dict[str, Any]], non_lus: Dict[str, int], noms: Dict[str, str]) -> List[Dict[str, Any]]:
    """Conversations à afficher : nom du contact (sinon numéro masqué), dernier message, heure et nombre de messages NON LUS.
    `docs` : messages récents, du plus récent au plus ancien. `non_lus` : clé de conversation → nombre de non-lus."""
    fils: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        cle = cle_fil(d)
        if cle in fils:
            continue                                             # le premier rencontré est le plus récent
        m = forme_message(d)
        nom = d.get("contact_name") or noms.get(cle) or d.get("from_profile_name") or masquer_numero(d.get("phone_digits") or d.get("from") or d.get("to"))
        fils[cle] = {"cle": cle, "nom": str(nom)[:60], "dernier": m["texte"][:100], "sens": m["sens"], "date": m["date"], "non_lus": 0}
    for cle, n in non_lus.items():
        if cle in fils:
            fils[cle]["non_lus"] = n
    return list(fils.values())[:MAX_FILS]


def forme_message(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Message prêt à afficher : jamais de numéro complet, texte raccourci, libellé pour image/vocal/document."""
    corps = str(doc.get("body") or "").strip()
    type_msg = doc.get("message_type") or "text"
    if not corps:
        corps = {"image": "📷 Image", "audio": "🎤 Message vocal", "voice": "🎤 Message vocal", "document": "📄 Document",
                 "video": "🎬 Vidéo", "sticker": "🙂 Autocollant", "location": "📍 Position"}.get(type_msg, "…")
    nom = doc.get("contact_name") or doc.get("from_profile_name") or masquer_numero(doc.get("phone_digits") or doc.get("from") or doc.get("to"))
    return {"id": doc.get("id"), "sens": "entrant" if doc.get("direction") == "inbound" else "sortant", "fil": cle_fil(doc),
            "nom": str(nom)[:60], "texte": corps[:240], "date": doc.get("received_at") or doc.get("sent_at") or doc.get("created_at")}


def forme_ticket(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Demande de support prête à afficher (numéro, motif, contact, état, date d'ouverture)."""
    return {"id": doc.get("id"), "numero": doc.get("number"), "motif": str(doc.get("motif") or "")[:140],
            "contact": str(doc.get("contact_name") or "")[:60], "statut": doc.get("status"), "date": doc.get("opened_at")}


def modules_valides(brut: Any) -> Dict[str, bool]:
    """Ne garde que les contenus connus ; absent = non."""
    brut = brut if isinstance(brut, dict) else {}
    return {m: bool(brut.get(m)) for m in MODULES}


class AppairageDemande(BaseModel):
    secret: str = Field(..., min_length=16, max_length=128, description="Secret fabriqué par la télé (jamais stocké en clair)")


class EcranAppairage(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)
    nom: str = Field(..., min_length=1, max_length=60)
    client_id: str = Field(..., min_length=1, max_length=64)
    modules: Optional[Dict[str, bool]] = None


class EcranModif(BaseModel):
    nom: Optional[str] = Field(None, max_length=60)
    client_id: Optional[str] = Field(None, max_length=64)
    modules: Optional[Dict[str, bool]] = None


def setup_ecran_tv_routes(*, db, api, get_current_admin, resolve_visible_client_ids=None):
    """Monte les routes : publiques (/tv/…, protégées par le secret de la télé) et administrateur (/admin/tv/…)."""

    async def _perimetre(client_id: str) -> List[str]:
        """Identifiants dont les messages et tickets appartiennent à ce client : MÊME périmètre que le Centre de Messagerie
        (le compte, son client rattaché, et les comptes de la même société). Lot 298 : avant, seul l'identifiant exact du compte
        choisi était lu, donc l'écran restait vide quand les messages étaient rangés sous un autre compte de la même société."""
        if resolve_visible_client_ids is None:
            return [client_id]
        compte = await db.users.find_one({"id": client_id}, {"_id": 0})
        if not compte:
            return [client_id]
        ids = await resolve_visible_client_ids(compte)
        return list(dict.fromkeys([client_id, *ids]))

    async def _reglages() -> Dict[str, Any]:
        return await db.settings.find_one({"_id": "global"}, {"tv_ecrans": 1, "tv_appairages": 1}) or {}

    # ---------------- Côté télé (public) ----------------
    @api.post("/tv/appairage", tags=["Écran TV"])
    async def tv_demander_appairage(payload: AppairageDemande):
        """La télé demande un code. Elle envoie son secret ; le serveur n'en garde que l'empreinte."""
        limite = (_maintenant() - timedelta(minutes=VALIDITE_CODE_MIN)).isoformat()
        entree = {"id": uuid.uuid4().hex, "code": nouveau_code(), "empreinte": empreinte(payload.secret), "cree_le": _maintenant().isoformat()}
        # On retire les codes périmés puis on ajoute celui-ci en gardant les 20 plus récents
        await db.settings.update_one({"_id": "global"}, {"$pull": {"tv_appairages": {"cree_le": {"$lt": limite}}}}, upsert=True)
        await db.settings.update_one({"_id": "global"}, {"$push": {"tv_appairages": {"$each": [entree], "$slice": -MAX_APPAIRAGES}}})
        return {"appairage_id": entree["id"], "code": entree["code"], "valide_minutes": VALIDITE_CODE_MIN}

    @api.get("/tv/appairage/{appairage_id}", tags=["Écran TV"])
    async def tv_etat_appairage(appairage_id: str, x_tv_secret: str = Header(default="")):
        """La télé attend l'accord de l'administrateur : « attente », « ok » (appairée) ou « expire » (redemander un code)."""
        s = await _reglages()
        h = empreinte(x_tv_secret)
        if any(e.get("empreinte") == h for e in s.get("tv_ecrans") or []):
            return {"etat": "ok"}
        limite = (_maintenant() - timedelta(minutes=VALIDITE_CODE_MIN)).isoformat()
        for a in s.get("tv_appairages") or []:
            if a.get("id") == appairage_id and a.get("empreinte") == h and a.get("cree_le", "") >= limite:
                return {"etat": "attente"}
        return {"etat": "expire"}

    async def _ecran_de_la_tele(secret: str) -> Dict[str, Any]:
        """Retrouve l'écran appairé par l'empreinte de son secret ; sinon 401 (la télé redemande un code)."""
        if not secret:
            raise HTTPException(status_code=401, detail="Écran non appairé")
        h = empreinte(secret)
        s = await _reglages()   # la liste des écrans est minuscule : on la filtre ici
        ecran = next((e for e in s.get("tv_ecrans") or [] if e.get("empreinte") == h), None)
        if not ecran:
            raise HTTPException(status_code=401, detail="Écran non appairé ou révoqué")
        return ecran

    @api.get("/tv/flux", tags=["Écran TV"])
    async def tv_flux(x_tv_secret: str = Header(default="")):
        """Contenu à afficher : derniers messages du client et demandes de support ouvertes (selon les contenus choisis)."""
        ecran = await _ecran_de_la_tele(x_tv_secret)
        modules = modules_valides(ecran.get("modules"))
        ids = await _perimetre(ecran.get("client_id"))
        flux: Dict[str, Any] = {"ecran": {"nom": ecran.get("nom"), "modules": modules}, "maintenant": _maintenant().isoformat()}
        if modules["messagerie"]:
            docs = await db.whatsapp_messages.find(
                {"client_id": {"$in": ids}},
                {"_id": 0, "id": 1, "direction": 1, "body": 1, "message_type": 1, "contact_id": 1, "contact_name": 1, "from_profile_name": 1,
                 "phone_digits": 1, "from": 1, "to": 1, "received_at": 1, "sent_at": 1, "created_at": 1},
            ).sort("created_at", -1).to_list(FENETRE_FILS)
            # Noms des contacts : celui du message, sinon la fiche du carnet (UNE lecture pour tous les contacts concernés)
            ids_contacts = list({d["contact_id"] for d in docs if d.get("contact_id") and not d.get("contact_name")})
            noms = {}
            if ids_contacts:
                async for c in db.directory_contacts.find({"id": {"$in": ids_contacts}}, {"_id": 0, "id": 1, "name": 1}):
                    noms[c["id"]] = c.get("name") or ""
            for d in docs:
                if not d.get("contact_name") and noms.get(d.get("contact_id")):
                    d["contact_name"] = noms[d["contact_id"]]
            # Non-lus par conversation (même critère que le Centre de Messagerie : entrant, « read_by_us_at » vide), UNE agrégation
            depuis = (_maintenant() - timedelta(days=JOURS_NON_LUS)).isoformat()
            non_lus: Dict[str, int] = {}
            async for d in db.whatsapp_messages.find(
                    {"client_id": {"$in": ids}, "direction": "inbound", "read_by_us_at": None, "created_at": {"$gte": depuis}},
                    {"_id": 0, "contact_id": 1, "phone_digits": 1, "from": 1}).limit(5000):
                cle = cle_fil(d)
                non_lus[cle] = non_lus.get(cle, 0) + 1
            flux["fils"] = forme_fils(docs, non_lus, {})
            flux["non_lus_total"] = sum(non_lus.values())
            flux["messages"] = [forme_message(d) for d in reversed(docs[:MAX_MESSAGES])]   # du plus ancien au plus récent : le nouveau arrive en bas
        if modules["support"]:
            docs = await db.support_tickets.find(
                {"client_id": {"$in": ids}, "status": {"$in": list(STATUTS_OUVERTS)}},
                {"_id": 0, "id": 1, "number": 1, "motif": 1, "contact_name": 1, "status": 1, "opened_at": 1},
            ).sort("opened_at", -1).to_list(MAX_TICKETS)
            flux["support"] = [forme_ticket(d) for d in docs]
        # « Vu le » : écrit au plus une fois par minute (pas une écriture à chaque rafraîchissement)
        vu = ecran.get("vu_le") or ""
        if not vu or vu < (_maintenant() - timedelta(minutes=1)).isoformat():
            await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran["id"]}, {"$set": {"tv_ecrans.$.vu_le": _maintenant().isoformat()}})
        return flux

    # ---------------- Côté administrateur ----------------
    @api.get("/admin/tv/ecrans", tags=["Admin — Écrans TV"])
    async def admin_tv_liste(user: dict = Depends(get_current_admin)):
        s = await _reglages()
        return {"ecrans": [{k: v for k, v in e.items() if k != "empreinte"} for e in s.get("tv_ecrans") or []]}

    @api.post("/admin/tv/appairer", tags=["Admin — Écrans TV"])
    async def admin_tv_appairer(payload: EcranAppairage, user: dict = Depends(get_current_admin)):
        """Associe le code affiché par la télé à un client et à des contenus."""
        s = await _reglages()
        limite = (_maintenant() - timedelta(minutes=VALIDITE_CODE_MIN)).isoformat()
        code = payload.code.strip().upper().replace(" ", "").replace("-", "")
        appairage = next((a for a in s.get("tv_appairages") or [] if a.get("code") == code and a.get("cree_le", "") >= limite), None)
        if not appairage:
            raise HTTPException(status_code=404, detail="Code inconnu ou expiré : relancez la page /tv sur la télé pour obtenir un nouveau code.")
        client = await db.users.find_one({"id": payload.client_id}, {"_id": 0, "id": 1, "company": 1, "full_name": 1})
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")
        ecran = {"id": uuid.uuid4().hex, "nom": payload.nom.strip(), "client_id": payload.client_id,
                 "client_nom": client.get("company") or client.get("full_name") or "",
                 "modules": modules_valides(payload.modules or {"messagerie": True, "support": True}),
                 "empreinte": appairage["empreinte"], "cree_le": _maintenant().isoformat(), "cree_par": user.get("email"), "vu_le": None}
        await db.settings.update_one({"_id": "global"}, {"$push": {"tv_ecrans": ecran}, "$pull": {"tv_appairages": {"id": appairage["id"]}}})
        return {"ok": True, "ecran": {k: v for k, v in ecran.items() if k != "empreinte"}}

    @api.put("/admin/tv/ecrans/{ecran_id}", tags=["Admin — Écrans TV"])
    async def admin_tv_modifier(ecran_id: str, payload: EcranModif, user: dict = Depends(get_current_admin)):
        champs: Dict[str, Any] = {}
        if payload.nom is not None and payload.nom.strip():
            champs["tv_ecrans.$.nom"] = payload.nom.strip()
        if payload.client_id:
            client = await db.users.find_one({"id": payload.client_id}, {"_id": 0, "company": 1, "full_name": 1})
            if not client:
                raise HTTPException(status_code=404, detail="Client introuvable")
            champs["tv_ecrans.$.client_id"] = payload.client_id
            champs["tv_ecrans.$.client_nom"] = client.get("company") or client.get("full_name") or ""
        if payload.modules is not None:
            champs["tv_ecrans.$.modules"] = modules_valides(payload.modules)
        if not champs:
            return {"ok": True}
        res = await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran_id}, {"$set": champs})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Écran introuvable")
        return {"ok": True}

    @api.delete("/admin/tv/ecrans/{ecran_id}", tags=["Admin — Écrans TV"])
    async def admin_tv_revoquer(ecran_id: str, user: dict = Depends(get_current_admin)):
        """Révoque l'écran : sa télé est refusée à son prochain rafraîchissement et redemande un code."""
        res = await db.settings.update_one({"_id": "global"}, {"$pull": {"tv_ecrans": {"id": ecran_id}}})
        if res.modified_count == 0:
            raise HTTPException(status_code=404, detail="Écran introuvable")
        return {"ok": True}
