# liluvine_requete.py — Lot 195 : UN SEUL FLUX Liluvine → « Requêtes des clients ».
#
# Avant : un message classé « Technique » par Liluvine ouvrait un ticket (support_tickets) SANS rapport avec
# « Requêtes des clients » (numérotation REQ-…, états, lots, évaluation) : le même problème pouvait exister deux fois.
# Maintenant : à chaque classement qui relève d'une requête, Liluvine crée (ou retrouve) la requête REQ-… du client,
# liée au ticket (champ `ticket_numero`). Une seule requête par ticket : un nouveau message du même ticket s'ajoute en
# observation. Le client reçoit son lien personnel :
#   - dans Loois, sur le poste du contact, s'il a Loois installé et en ligne (carte « lien » dans le fil du poste, que
#     l'icône Loois affiche puis ouvre dans le navigateur) ;
#   - sinon par WhatsApp (le lien est ajouté à la réponse de Liluvine).
# Aucune dépendance sur le serveur : fonctions pures + accès base passé en paramètre (testable).
from __future__ import annotations

import logging
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("sawali.liluvine_requete")

ESPACE_SUPPORT_LOOIS = "support-loois"      # même espace que routes/support_loois.py (fil des postes)
POSTE_EN_LIGNE_MINUTES = 12                   # règle 4 : poste en ligne si signal < 12 min

# Catégorie du classement Liluvine (sans accent, minuscule) → catégorie de « Requêtes des clients ».
# Seules les demandes techniques deviennent des requêtes ; comptabilité, commercial, rendez-vous… restent des tickets.
_CATEGORIE_REQUETE = {"technique": "dysfonctionnement"}


def _norm(s: Any) -> str:
    """Minuscule sans accent."""
    t = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()


def categorie_requete(categorie_classement: Any) -> Optional[str]:
    """Catégorie « Requêtes des clients » pour un classement Liluvine, ou None si cela reste un simple ticket."""
    return _CATEGORIE_REQUETE.get(_norm(categorie_classement))


def texte_lien(numero: str, url: str, via_loois: bool) -> str:
    """Phrase ajoutée à la réponse de Liluvine : numéro de la requête et lien pour la préciser."""
    if via_loois:
        return (f"Votre requête {numero} est enregistrée. Un lien pour la préciser (photos, captures, message vocal) "
                f"s'affiche sur votre poste Loois : cliquez sur la notification pour l'ouvrir.")
    return f"Votre requête {numero} est enregistrée. Vous pouvez la préciser (photos, captures, message vocal) ici : {url}"


async def _lien_personnel(db, tenant_id: str, base: str) -> str:
    """URL du lien personnel (sans mot de passe) du client ; créé au besoin — même collection que le lot 86."""
    actuel = await db.requetes_liens.find_one({"tenant_id": tenant_id, "actif": True}, {"_id": 0})
    if not actuel:
        actuel = {"jeton": secrets.token_urlsafe(18), "tenant_id": tenant_id, "actif": True,
                  "cree_le": datetime.now(timezone.utc).isoformat(), "cree_par": "liluvine", "envoye_le": None}
        await db.requetes_liens.insert_one(dict(actuel))
    return f"{base.rstrip('/')}/requete/{actuel['jeton']}"


async def poste_loois_en_ligne(db, client_id: str, nom_poste: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Poste Loois du client actuellement en ligne. Si le contact a nommé son poste, c'est celui-là ; sinon, le seul poste
    en ligne du client (s'il y en a plusieurs, on ne devine pas : retour None → WhatsApp)."""
    limite = (datetime.now(timezone.utc) - timedelta(minutes=POSTE_EN_LIGNE_MINUTES)).isoformat()
    candidats = [p async for p in db.support_loois_postes.find(
        {"client_id": client_id, "dernier_contact": {"$gte": limite}}, {"_id": 0})]
    if nom_poste:
        voulu = _norm(nom_poste)
        trouves = [p for p in candidats if _norm(p.get("nom")) == voulu]
        return trouves[0] if trouves else None
    return candidats[0] if len(candidats) == 1 else None


async def deposer_lien_loois(db, poste: Dict[str, Any], numero: str, url: str) -> None:
    """Dépose une carte « lien » dans le fil du poste ; l'icône Loois la lit via GET /support-loois/etat."""
    await db.internal_chat_messages.insert_one({
        "id": str(uuid.uuid4()), "client_id": ESPACE_SUPPORT_LOOIS, "sender_id": "sawali", "sender_name": "Liluvine",
        "recipient_id": poste["id"], "systeme": True, "created_at": datetime.now(timezone.utc).isoformat(),
        "read_by": ["sawali"], "text": f"🔗 Requête {numero} : ouvrez le lien pour la préciser.",
        "lien_requete": {"numero": numero, "url": url, "ouvert": False}})


async def requete_depuis_classement(db, *, client: Dict[str, Any], contact_nom: str, categorie_classement: str,
                                    motif: str, texte: str, ticket_numero: Optional[str], base_url: str,
                                    nom_poste: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Crée (ou complète) la requête REQ-… d'un classement Liluvine.

    Renvoie {numero, url, via_loois, nouvelle} ou None si le classement n'est pas une requête / en cas d'échec.
    Jamais d'exception : la réponse WhatsApp ne doit pas dépendre de ce rangement."""
    try:
        cat = categorie_requete(categorie_classement)
        if not cat or not client or not client.get("id"):
            return None
        from routes.requetes_clients import code_client, numero_requete
        tenant_id = client["id"]
        maintenant = datetime.now(timezone.utc).isoformat()
        existante = None
        if ticket_numero:   # une seule requête par ticket
            existante = await db.requetes_clients.find_one({"tenant_id": tenant_id, "ticket_numero": ticket_numero}, {"_id": 0})
        if existante:
            await db.requetes_clients.update_one({"id": existante["id"]}, {"$push": {"observations": {
                "le": maintenant, "par": "Liluvine", "texte": f"Nouveau message du contact : {texte[:500]}"}}})
            numero, nouvelle = existante["numero"], False
        else:
            seq = (await db.counters.find_one_and_update({"_id": f"requetes_{tenant_id}"}, {"$inc": {"seq": 1}},
                                                         upsert=True, return_document=True) or {}).get("seq") or 1
            numero = numero_requete(code_client(client), seq)
            titre = (motif or texte or "Demande technique").strip()[:120]
            await db.requetes_clients.insert_one({
                "id": str(uuid.uuid4()), "numero": numero, "tenant_id": tenant_id,
                "client_nom": client.get("company") or client.get("full_name") or "",
                "auteur_id": None, "auteur_nom": f"{contact_nom or 'Contact'} (via Liluvine)", "origine": "liluvine",
                "categorie": cat, "titre": titre, "texte": (texte or motif or "")[:4000], "logiciel": "", "equipement": "",
                "ticket_numero": ticket_numero, "cree_le": maintenant, "etat": "nouvelle", "lot_id": None,
                "lot_numero": None, "observations": [],
                "historique": [{"etat": "nouvelle", "le": maintenant, "par": "Liluvine"}],
                "evaluation": None, "a_evaluer": False, "images": []})
            nouvelle = True
        url = await _lien_personnel(db, tenant_id, base_url)
        poste = await poste_loois_en_ligne(db, tenant_id, nom_poste)
        if poste and nouvelle:
            await deposer_lien_loois(db, poste, numero, url)
        return {"numero": numero, "url": url, "via_loois": bool(poste and nouvelle), "nouvelle": nouvelle}
    except Exception:  # noqa: BLE001
        logger.warning("[liluvine_requete] création de la requête impossible", exc_info=True)
        return None
