# contacts_plateformes.py — Lot 161 : SAWALI RÉCUPÈRE LES CONTACTS DES PLATEFORMES (ZandGo, portail e-Kol, adLyn, …)
# et les range dans un GROUPE par plateforme (« Plateforme adLyn »…), pour des messages WhatsApp de masse ou des carrousels.
#
# Demande du propriétaire (14/10/2026) : « Faire récupérer par SAWALI la liste des contacts des différentes plateformes
# pour les mettre dans des groupes spécifiques à la plateforme ».
#
# En résumé (pour un développeur WinDev) :
#   - CHAQUE PLATEFORME expose UNE route de lecture seule : GET <adresse>/api/sawali/contacts?limite=500&page=1
#     SIGNÉE par SAWALI avec une clé partagée (même mécanisme que l'export e-Kol) :
#         X-Timestamp = horodatage Unix (secondes), valable 5 minutes ;
#         X-Signature = HMAC-SHA256(clé, "<horodatage>.GET <chemin>?<requête>") en hexadécimal.
#     Réponse : {"plateforme": "...", "page": 1, "pages": 3, "total": 1234,
#                "contacts": [{"id", "nom", "telephone", "role"?, "societe"?, "email"?, "accepte_whatsapp"?, "accepte_le"?}]}
#   - SAWALI (une fois par jour à 03 h 20, et à la demande) lit toutes les pages et, dans l'ANNUAIRE du propriétaire
#     (collection directory_contacts, AUCUNE nouvelle collection : le cluster est à sa limite de 500) :
#       * crée les contacts nouveaux (champ source_plateforme + id_externe), met à jour nom / société / e-mail ;
#       * adopte un contact déjà présent avec le même numéro (ses 8 derniers chiffres) sans le modifier ;
#       * remplit le groupe « Plateforme <nom> » (collection contact_groups, champ source_plateforme) ; un contact que la
#         plateforme ne renvoie plus (compte supprimé) sort du groupe mais reste dans l'annuaire.
#   - CONSENTEMENT : une plateforme ne coche JAMAIS « accepté » à la place de la personne. Un contact importé n'est
#     destinataire d'un carrousel qu'après son propre accord (lot 79 : bouton, mot-clé OUI NOUVEAUTES) ; il est ajouté
#     comme consentant SEULEMENT si la plateforme envoie accepte_whatsapp = vrai (case cochée à l'inscription, avec sa
#     date). Un RETRAIT donné sur la plateforme (accepte_whatsapp = faux) est transmis de la même façon et coupe les envois.
#     Le choix le plus RÉCENT gagne (comparaison des dates) : un STOP reçu sur WhatsApp n'est jamais écrasé par un ancien accord.
#   - CLÉ : variable d'environnement SAWALI CONTACTS_HMAC_<PLATEFORME> (ex. CONTACTS_HMAC_ZANDGO), saisie par le
#     propriétaire sur Render, JAMAIS dans la base ni dans Git ; la même valeur sert de SAWALI_CONTACTS_HMAC sur la plateforme.
#   - Réglages (adresse, activation, dernier résultat) : db.settings {_id: "contacts_plateformes"}.
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.contacts_plateformes")

ID_REGLAGE = "contacts_plateformes"
CHEMIN = "/api/sawali/contacts"
PAR_PAGE = 500
PAGES_MAX = 40                      # 20 000 contacts au plus par plateforme et par passage
DELAI_SECONDES = 30
# Plateformes connues (adresse vide = à saisir). id = identifiant technique stable ; nom = libellé du groupe.
CATALOGUE = [
    {"id": "zandgo", "nom": "ZandGo", "url": "https://api.zandgo.shop"},
    {"id": "ekol", "nom": "Portail e-Kol", "url": ""},
    {"id": "adlyn", "nom": "adLyn", "url": ""},
    {"id": "beauthentik", "nom": "beAuthentik", "url": ""},
    {"id": "ster", "nom": "Ster", "url": ""},
    {"id": "albarka", "nom": "ALBARKA", "url": ""},
]
COULEURS = ["#0ea5e9", "#22c55e", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6", "#6366f1"]


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------------------------------- clé et signature
def variable_cle(pid: str) -> str:
    """Nom de la variable d'environnement qui porte la clé : « adlyn » → CONTACTS_HMAC_ADLYN."""
    return "CONTACTS_HMAC_" + re.sub(r"[^A-Z0-9]+", "_", pid.upper()).strip("_")


def cle_saisie(pid: str) -> bool:
    return bool((os.environ.get(variable_cle(pid)) or "").strip())


def signer(cle: str, horodatage: str, chemin: str, requete: str) -> str:
    """HMAC-SHA256 hexadécimal de « <horodatage>.GET <chemin>?<requête> » (même calcul que l'export e-Kol)."""
    cible = f"{chemin}?{requete}" if requete else chemin
    return hmac.new(cle.encode("utf-8"), f"{horodatage}.GET {cible}".encode("utf-8"), hashlib.sha256).hexdigest()


def adresse_acceptee(url: str) -> bool:
    """https obligatoire, jamais une adresse locale ou privée (le serveur appelle cette adresse)."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    if p.scheme != "https" or not p.hostname or p.hostname.lower() in ("localhost",) or p.hostname.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(p.hostname)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return True          # un nom de domaine


# ------------------------------------------------------------------------------------------- contacts
def chiffres(brut: Any) -> str:
    return re.sub(r"\D", "", str(brut or ""))


def motif_numero(brut: Any) -> Optional[str]:
    """Expression régulière qui retrouve un numéro sous n'importe quelle forme, à partir de ses 8 derniers chiffres."""
    fin = chiffres(brut)[-8:]
    return (r"\D*".join(fin) + r"\D*$") if len(fin) == 8 else None


def _plus_recent(nouvelle: Optional[str], ancienne: Optional[str]) -> bool:
    """La date du choix reçu est-elle plus récente que celle déjà enregistrée ? Sans date reçue : seulement s'il n'y a
    encore aucune date enregistrée. Dates illisibles : on ne change rien (prudence)."""
    if not ancienne:
        return True
    if not nouvelle:
        return False
    try:
        a = datetime.fromisoformat(str(nouvelle).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(ancienne).replace("Z", "+00:00"))
        a = a if a.tzinfo else a.replace(tzinfo=timezone.utc)
        b = b if b.tzinfo else b.replace(tzinfo=timezone.utc)
        return a > b
    except ValueError:
        return False


def normaliser_contact(c: Dict[str, Any], nom_plateforme: str) -> Optional[Dict[str, Any]]:
    """Contact reçu → champs utiles, ou None s'il n'a ni numéro valable ni identifiant."""
    tel = chiffres(c.get("telephone"))
    if len(tel) < 8 or not str(c.get("id") or "").strip():
        return None
    nom = " ".join(str(c.get("nom") or "").split())[:120] or f"Contact {nom_plateforme}"
    role = " ".join(str(c.get("role") or "").split())[:60]
    return {"id_externe": str(c["id"]).strip()[:80], "nom": nom, "telephone": tel,
            "societe": " ".join(str(c.get("societe") or "").split())[:120] or (f"{nom_plateforme} · {role}" if role else nom_plateforme),
            "email": str(c.get("email") or "").strip()[:160] or None,
            # Accord (vrai), retrait (faux) ou rien (None) : seuls de vrais booléens comptent ; « accepte_le » = date de ce choix
            "accepte": c["accepte_whatsapp"] if isinstance(c.get("accepte_whatsapp"), bool) else None,
            "accepte_le": str(c.get("accepte_le") or "")[:40] or None}


# ------------------------------------------------------------------------------------------- appel HTTP
async def appeler_plateforme(url: str, entetes: Dict[str, str]) -> Dict[str, Any]:
    """Une page de contacts d'une plateforme (lève RuntimeError avec un message lisible en cas de refus)."""
    import httpx
    async with httpx.AsyncClient(timeout=DELAI_SECONDES) as client:
        r = await client.get(url, headers=entetes)
    if r.status_code == 401:
        raise RuntimeError("La plateforme refuse la signature : la clé doit être la même des deux côtés.")
    if r.status_code == 503:
        raise RuntimeError("Export désactivé sur la plateforme : saisir SAWALI_CONTACTS_HMAC sur son serveur.")
    if r.status_code == 404:
        raise RuntimeError("La plateforme n'expose pas encore /api/sawali/contacts.")
    if r.status_code >= 400:
        raise RuntimeError(f"La plateforme a répondu HTTP {r.status_code}.")
    return r.json()


async def lire_contacts(plateforme: Dict[str, Any], appeler: Callable[[str, Dict[str, str]], Awaitable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Toutes les pages de contacts d'une plateforme (signées une à une)."""
    cle = (os.environ.get(variable_cle(plateforme["id"])) or "").strip()
    if not cle:
        raise RuntimeError(f"Clé absente : saisir la variable {variable_cle(plateforme['id'])} sur le serveur SAWALI.")
    base = plateforme["url"].rstrip("/")
    contacts: List[Dict[str, Any]] = []
    page = 1
    while page <= PAGES_MAX:
        requete = f"limite={PAR_PAGE}&page={page}"
        ts = str(int(time.time()))
        rep = await appeler(f"{base}{CHEMIN}?{requete}", {"X-Timestamp": ts, "X-Signature": signer(cle, ts, CHEMIN, requete)})
        contacts += rep.get("contacts") or []
        if page >= int(rep.get("pages") or 1):
            break
        page += 1
    return contacts


# ------------------------------------------------------------------------------------------- réglages
async def lire_reglages(db) -> Dict[str, Any]:
    doc = await db.settings.find_one({"_id": ID_REGLAGE}) or {}
    plateformes = {p["id"]: {**p, "actif": False} for p in CATALOGUE}
    for pid, p in (doc.get("plateformes") or {}).items():
        plateformes[pid] = {**plateformes.get(pid, {"id": pid, "nom": pid, "url": ""}), **p, "id": pid}
    return {"proprietaire_id": doc.get("proprietaire_id"), "plateformes": plateformes}


async def _enregistrer_plateforme(db, pid: str, champs: Dict[str, Any], proprietaire_id: Optional[str] = None) -> None:
    maj = {f"plateformes.{pid}.{k}": v for k, v in champs.items()}
    if proprietaire_id:
        maj["proprietaire_id"] = proprietaire_id
    await db.settings.update_one({"_id": ID_REGLAGE}, {"$set": maj}, upsert=True)


# ------------------------------------------------------------------------------------------- synchronisation
async def synchroniser(db, pid: str, appeler: Optional[Callable] = None, attribuer_code: Optional[Callable] = None) -> Dict[str, Any]:
    """Lit les contacts d'UNE plateforme et met à jour l'annuaire et le groupe « Plateforme <nom> ». Renvoie le bilan
    (jamais d'exception : une erreur est gardée dans le résultat et renvoyée au tableau des Paramètres)."""
    r = await lire_reglages(db)
    p = r["plateformes"].get(pid)
    bilan: Dict[str, Any] = {"le": _maintenant(), "ok": False}
    if not p or not p.get("url"):
        bilan["erreur"] = "Adresse de la plateforme non renseignée."
    elif not r["proprietaire_id"]:
        bilan["erreur"] = "Propriétaire de l'annuaire inconnu : enregistrez d'abord la plateforme depuis les Paramètres."
    else:
        try:
            recus = await lire_contacts(p, appeler or appeler_plateforme)
            bilan.update(await _appliquer(db, p, r["proprietaire_id"], recus, attribuer_code))
            bilan["ok"] = True
        except Exception as exc:  # noqa: BLE001 — l'erreur est montrée à l'administrateur, jamais bloquante
            bilan["erreur"] = str(exc)[:300] if isinstance(exc, RuntimeError) else f"Lecture impossible ({type(exc).__name__})."
            logger.warning("[contacts_plateformes] %s : %s", pid, type(exc).__name__)
    await _enregistrer_plateforme(db, pid, {"derniere_sync": bilan["le"], "resultat": bilan})
    return bilan


async def _appliquer(db, p: Dict[str, Any], scope: str, recus: List[Dict[str, Any]], attribuer_code: Optional[Callable]) -> Dict[str, Any]:
    """Écrit les contacts reçus : création, mise à jour, adoption, groupe. Voir l'en-tête pour les règles."""
    bilan = {"recus": len(recus), "crees": 0, "mis_a_jour": 0, "adoptes": 0, "sans_numero": 0, "retires_du_groupe": 0, "consentants": 0}
    ids_groupe: List[str] = []
    proprietaire = await db.users.find_one({"id": scope}, {"_id": 0, "id": 1, "full_name": 1, "email": 1}) or {}
    for brut in recus:
        c = normaliser_contact(brut, p["nom"])
        if not c:
            bilan["sans_numero"] += 1
            continue
        existant = await db.directory_contacts.find_one(
            {"client_id": scope, "source_plateforme": p["id"], "id_externe": c["id_externe"]}, {"_id": 0})
        if not existant:
            motif = motif_numero(c["telephone"])
            if motif:     # même personne déjà dans l'annuaire (autre source) : adoptée sans modification
                existant = await db.directory_contacts.find_one(
                    {"client_id": scope, "$or": [{"whatsapp": {"$regex": motif}}, {"phone": {"$regex": motif}}]}, {"_id": 0})
                if existant:
                    bilan["adoptes"] += 1
        if existant:
            if existant.get("source_plateforme") == p["id"]:
                maj = {k: v for k, v in (("name", c["nom"]), ("company", c["societe"]), ("email", c["email"]), ("whatsapp", c["telephone"])) if v and existant.get(k) != v}
                if maj:
                    await db.directory_contacts.update_one({"id": existant["id"]}, {"$set": {**maj, "updated_at": _maintenant()}})
                    bilan["mis_a_jour"] += 1
            cid = existant["id"]
            deja = existant
        else:
            doc = {"id": str(uuid.uuid4()), "client_id": scope, "owner_id": scope,
                   "owner_label": proprietaire.get("full_name") or proprietaire.get("email") or "Synchro plateformes",
                   "name": c["nom"], "company": c["societe"], "whatsapp": c["telephone"], "phone": c["telephone"],
                   "email": c["email"], "tags": [p["nom"]], "shared": True, "source_plateforme": p["id"],
                   "id_externe": c["id_externe"], "created_at": _maintenant(), "updated_at": _maintenant()}
            if attribuer_code:
                try:
                    doc["unique_code"] = await attribuer_code({"id": scope})
                except Exception:  # noqa: BLE001 — le code manquant est attribué au prochain démarrage
                    pass
            await db.directory_contacts.insert_one(dict(doc))
            bilan["crees"] += 1
            cid, deja = doc["id"], doc
        # Consentement : le choix le plus RÉCENT gagne. Un accord ou un retrait donné sur la plateforme s'applique seulement
        # si sa date est connue ET plus récente que l'état déjà enregistré dans SAWALI (un STOP reçu sur WhatsApp n'est donc
        # jamais écrasé par un ancien accord) ; sans date, il ne s'applique qu'à une fiche qui n'a encore aucun choix.
        etat = deja.get("accepte_whatsapp")
        if c["accepte"] is not None and c["accepte"] is not bool(etat) and _plus_recent(c["accepte_le"], deja.get("accepte_whatsapp_le")):
            await db.directory_contacts.update_one({"id": cid}, {"$set": {
                "accepte_whatsapp": c["accepte"], "accepte_whatsapp_le": c["accepte_le"] or _maintenant(),
                "accepte_whatsapp_moyen": f"plateforme : {p['nom']}" + ("" if c["accepte"] else " (retrait)")}})
            etat = c["accepte"]
            bilan["retraits" if not c["accepte"] else "accords"] = bilan.get("retraits" if not c["accepte"] else "accords", 0) + 1
        if etat:
            bilan["consentants"] += 1
        ids_groupe.append(cid)
    # Groupe « Plateforme <nom> » : contenu = contacts renvoyés cette fois
    nom_groupe = f"Plateforme {p['nom']}"
    groupe = await db.contact_groups.find_one({"client_id": scope, "source_plateforme": p["id"]}, {"_id": 0})
    ids_groupe = list(dict.fromkeys(ids_groupe))
    if groupe:
        bilan["retires_du_groupe"] = len(set(groupe.get("contact_ids") or []) - set(ids_groupe))
        await db.contact_groups.update_one({"id": groupe["id"]}, {"$set": {"contact_ids": ids_groupe, "updated_at": _maintenant()}})
    else:
        await db.contact_groups.insert_one({
            "id": str(uuid.uuid4()), "client_id": scope, "name": nom_groupe, "color": COULEURS[sum(map(ord, p["id"])) % len(COULEURS)],
            "description": f"Contacts de la plateforme {p['nom']} (synchronisés par SAWALI, ne pas modifier à la main).",
            "contact_ids": ids_groupe, "source_plateforme": p["id"], "owner_id": scope, "shared_with_tenant": False,
            "editable_by_tenant": False, "created_by": "synchro", "created_at": _maintenant(), "updated_at": _maintenant()})
    bilan["dans_le_groupe"] = len(ids_groupe)
    return bilan


async def synchroniser_tout(db, attribuer_code: Optional[Callable] = None) -> Dict[str, Any]:
    """Tâche quotidienne : toutes les plateformes ACTIVES (une erreur n'arrête pas les autres)."""
    r = await lire_reglages(db)
    return {pid: await synchroniser(db, pid, attribuer_code=attribuer_code) for pid, p in r["plateformes"].items() if p.get("actif") and p.get("url")}


# ------------------------------------------------------------------------------------------- routes
class PlateformeIn(BaseModel):
    """Adresse et activation d'une plateforme (modèle au niveau du module : FastAPI doit pouvoir le résoudre)."""
    url: str = Field(default="", max_length=200)
    actif: bool = False
    nom: Optional[str] = Field(default=None, max_length=60)


def setup_contacts_plateformes_routes(*, db, api, get_current_admin, attribuer_code=None) -> None:
    from fastapi import Depends, HTTPException

    async def _etat() -> Dict[str, Any]:
        r = await lire_reglages(db)
        lignes = []
        for pid, p in r["plateformes"].items():
            groupe = await db.contact_groups.find_one({"client_id": r["proprietaire_id"], "source_plateforme": pid}, {"_id": 0, "contact_ids": 1, "id": 1}) if r["proprietaire_id"] else None
            ids = (groupe or {}).get("contact_ids") or []
            consentants = await db.directory_contacts.count_documents({"id": {"$in": ids}, "accepte_whatsapp": True}) if ids else 0
            lignes.append({"id": pid, "nom": p["nom"], "url": p.get("url") or "", "actif": bool(p.get("actif")),
                           "variable": variable_cle(pid), "cle_saisie": cle_saisie(pid), "derniere_sync": p.get("derniere_sync"),
                           "resultat": p.get("resultat"), "contacts": len(ids), "consentants": consentants, "groupe_id": (groupe or {}).get("id")})
        return {"plateformes": lignes, "chemin": CHEMIN}

    @api.get("/admin/contacts-plateformes", tags=["Admin — Contacts des plateformes"])
    async def lire(_: dict = Depends(get_current_admin)):
        """Plateformes (adresse, activation, état de la clé), dernier résultat, nombre de contacts et de consentants."""
        return await _etat()

    @api.put("/admin/contacts-plateformes/{pid}", tags=["Admin — Contacts des plateformes"])
    async def ecrire(pid: str, data: PlateformeIn, admin: dict = Depends(get_current_admin)):
        """Adresse et activation d'une plateforme (le compte qui enregistre devient propriétaire de l'annuaire)."""
        if not re.fullmatch(r"[a-z0-9_-]{2,30}", pid):
            raise HTTPException(status_code=422, detail="Identifiant de plateforme invalide")
        url = (data.url or "").strip().rstrip("/")
        if url and not adresse_acceptee(url):
            raise HTTPException(status_code=422, detail="Adresse https publique requise (ex. https://api.zandgo.shop)")
        if data.actif and not url:
            raise HTTPException(status_code=422, detail="Renseignez l'adresse avant d'activer la plateforme")
        champs: Dict[str, Any] = {"url": url, "actif": bool(data.actif)}
        r = await lire_reglages(db)
        champs["nom"] = (data.nom or "").strip() or r["plateformes"].get(pid, {}).get("nom") or pid
        await _enregistrer_plateforme(db, pid, champs, proprietaire_id=admin.get("id"))
        return await _etat()

    @api.post("/admin/contacts-plateformes/{pid}/synchroniser", tags=["Admin — Contacts des plateformes"])
    async def lancer(pid: str, _: dict = Depends(get_current_admin)):
        """Synchronise tout de suite cette plateforme ; renvoie le bilan (ou le motif de l'échec)."""
        r = await lire_reglages(db)
        if pid not in r["plateformes"]:
            raise HTTPException(status_code=404, detail="Plateforme inconnue")
        bilan = await synchroniser(db, pid, attribuer_code=attribuer_code)
        return {"bilan": bilan, **await _etat()}
