# accord_whatsapp.py — Lot 79 : accord (consentement) WhatsApp des destinataires, recueilli par la personne ELLE-MÊME.
#
# Règle WhatsApp et loi n° 001-2021/AN (Burkina Faso) : un message marketing (ex. carrousel) ne part qu'à une
# personne qui a accepté d'en recevoir. Personne ne coche « accepté » à sa place : l'accord vient de son propre
# téléphone, de trois façons :
#   1. bouton « Oui, j'accepte » d'une demande envoyée par SAWALI — seulement si la personne a écrit à ce numéro
#      depuis moins de 24 h (fenêtre de conversation WhatsApp : message libre permis, sans modèle Meta) ;
#   2. mot-clé envoyé par la personne : « OUI NOUVEAUTES » (accord) ou « STOP » (retrait) — via le lien
#      wa.me ou le QR code affiché sur la page Carrousel (comptoir, affiche, réseaux sociaux) ;
#   3. bouton « Non merci » ou « STOP » : l'accord est retiré.
# Chaque accord / retrait est tracé dans `accords_whatsapp_journal` (preuve : numéro, date, moyen, numéro SAWALI).
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.accord_whatsapp")

# Identifiants des boutons de la demande d'accord (renvoyés par WhatsApp quand la personne touche le bouton)
BOUTON_OUI = "accord_wa:oui"
BOUTON_NON = "accord_wa:non"
# Mot-clé du lien / QR code d'accord (texte pré-rempli dans WhatsApp)
MOT_CLE_ACCORD = "OUI NOUVEAUTES"
TEXTE_DEMANDE = ("Bonjour ! Souhaitez-vous recevoir nos nouveautés et offres sur WhatsApp ?\n"
                 "Vous pourrez arrêter à tout moment en écrivant STOP.")
REPONSE_OUI = ("Merci ! Votre accord est enregistré : vous recevrez nos nouveautés sur WhatsApp. "
               "Écrivez STOP à tout moment pour ne plus rien recevoir.")
REPONSE_NON = "C'est noté : vous ne recevrez plus nos nouveautés sur WhatsApp. Écrivez OUI NOUVEAUTES pour changer d'avis."


def _normaliser(texte: str) -> str:
    """Majuscules, sans accents ni ponctuation, espaces simples (« Oui, nouveautés ! » → « OUI NOUVEAUTES »)."""
    t = unicodedata.normalize("NFKD", texte or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    return " ".join(t.split())


def intention(texte: Optional[str], bouton_id: Optional[str] = None) -> Optional[bool]:
    """True = accord, False = retrait, None = message ordinaire (rien à faire).
    Volontairement strict : un simple « oui » dans une conversation ne vaut PAS accord marketing."""
    if bouton_id == BOUTON_OUI:
        return True
    if bouton_id == BOUTON_NON:
        return False
    t = _normaliser(texte or "")
    if t in {"OUI NOUVEAUTES", "OUI NOUVEAUTE", "JACCEPTE LES NOUVEAUTES", "J ACCEPTE LES NOUVEAUTES"}:
        return True
    if t in {"STOP", "STOP NOUVEAUTES", "STOP NOUVEAUTE", "ARRET", "DESABONNER", "DESINSCRIRE"}:
        return False
    return None


def motif_numero(chiffres: str) -> Optional[str]:
    """Expression régulière qui retrouve un numéro enregistré sous n'importe quelle forme
    (« +226 76 11 11 11 », « 76111111 », « 0022676111111 ») à partir de ses 8 derniers chiffres."""
    fin = re.sub(r"\D", "", chiffres or "")[-8:]
    if len(fin) < 8:
        return None
    return r"\D*".join(fin) + r"\D*$"


async def _tenant_du_numero(db, numero_recu: Optional[str]) -> Optional[str]:
    """Client propriétaire du numéro WhatsApp qui a reçu le message (None = numéro de la plateforme SAWALI)."""
    if not numero_recu:
        return None
    doc = await db.tenant_smart_comm.find_one({"wa_phone_number_id": numero_recu}, {"_id": 0, "tenant_id": 1})
    return (doc or {}).get("tenant_id")


async def noter_accord(db, chiffres: str, accepte: bool, *, numero_recu: Optional[str], moyen: str) -> int:
    """Enregistre l'accord (ou son retrait) sur toutes les fiches de cette personne qui relèvent du numéro
    WhatsApp concerné : numéro d'un client → ses contacts et utilisateurs suivis ; numéro SAWALI → les fiches
    des clients sans numéro propre, et les comptes clients. Renvoie le nombre de fiches mises à jour."""
    motif = motif_numero(chiffres)
    if not motif:
        return 0
    maintenant = datetime.now(timezone.utc).isoformat()
    maj = {"accepte_whatsapp": accepte, "accepte_whatsapp_le": maintenant if accepte else None,
           "accepte_whatsapp_par": f"la personne elle-même ({moyen})", "accepte_whatsapp_moyen": moyen}
    tenant = await _tenant_du_numero(db, numero_recu)
    if tenant:
        portee: Dict[str, Any] = {"client_id": tenant}
    else:
        # Numéro de la plateforme : jamais les fiches d'un client qui envoie depuis SON numéro
        propres = [d["tenant_id"] async for d in db.tenant_smart_comm.find(
            {"wa_phone_number_id": {"$nin": [None, ""]}}, {"_id": 0, "tenant_id": 1}) if d.get("tenant_id")]
        portee = {"client_id": {"$nin": propres}} if propres else {}
    n = 0
    for coll, champs in ((db.directory_contacts, ("whatsapp", "phone")), (db.tracked_users, ("whatsapp_number", "phone"))):
        res = await coll.update_many({**portee, "$or": [{c: {"$regex": motif}} for c in champs]}, {"$set": maj})
        n += res.modified_count
    if not tenant:
        res = await db.users.update_many({"$or": [{"whatsapp_number": {"$regex": motif}}, {"phone": {"$regex": motif}}]},
                                         {"$set": maj})
        n += res.modified_count
    # Preuve : journal des accords (jamais modifié ensuite)
    await db.accords_whatsapp_journal.insert_one({
        "telephone": re.sub(r"\D", "", chiffres or ""), "accepte": accepte, "moyen": moyen,
        "numero_recu": numero_recu, "tenant_id": tenant, "fiches": n, "le": maintenant})
    logger.info("[accord_wa] %s via %s : %d fiche(s)", "accord" if accepte else "retrait", moyen, n)
    return n


async def traiter_message_entrant(db, chiffres: str, texte: Optional[str], bouton_id: Optional[str],
                                  numero_recu: Optional[str]) -> Optional[Tuple[str, Optional[str]]]:
    """Appelé par le webhook WhatsApp pour chaque message reçu. Si c'est un accord ou un retrait :
    l'enregistre et renvoie (texte de confirmation, client propriétaire du numéro) ; sinon None."""
    choix = intention(texte, bouton_id)
    if choix is None:
        return None
    moyen = "bouton" if bouton_id else "mot-clé"
    await noter_accord(db, chiffres, choix, numero_recu=numero_recu, moyen=moyen)
    return (REPONSE_OUI if choix else REPONSE_NON), await _tenant_du_numero(db, numero_recu)


async def fenetre_ouverte(db, chiffres: str, numero_id: Optional[str], maintenant: Optional[datetime] = None) -> bool:
    """La personne a-t-elle écrit à ce numéro SAWALI depuis moins de 24 h ? (message libre permis par WhatsApp)"""
    motif = motif_numero(chiffres)
    if not motif:
        return False
    depuis = ((maintenant or datetime.now(timezone.utc)) - timedelta(hours=24)).isoformat()
    filtre: Dict[str, Any] = {"direction": "inbound", "created_at": {"$gte": depuis}, "phone_digits": {"$regex": motif}}
    if numero_id:
        filtre["$or"] = [{"wa_numero_id": numero_id}, {"wa_numero_id": None}, {"wa_numero_id": {"$exists": False}}]
    return bool(await db.whatsapp_messages.find_one(filtre, {"_id": 1}))


def corps_demande(telephone: str, texte: str = TEXTE_DEMANDE) -> Dict[str, Any]:
    """Message WhatsApp interactif à 2 boutons (« Oui, j'accepte » / « Non merci »)."""
    return {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": telephone, "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texte[:1024]},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": BOUTON_OUI, "title": "Oui, j'accepte"}},
                {"type": "reply", "reply": {"id": BOUTON_NON, "title": "Non merci"}},
            ]},
        },
    }


def lien_accord(numero_affiche: str) -> str:
    """Lien wa.me qui ouvre WhatsApp avec « OUI NOUVEAUTES » pré-rempli (à afficher en QR code)."""
    chiffres = re.sub(r"\D", "", numero_affiche or "")
    return f"https://wa.me/{chiffres}?text=OUI%20NOUVEAUTES" if chiffres else ""


async def envoyer_demandes(db, personnes: List[dict], creds: Dict[str, Any], version: str = "v22.0",
                           http=None) -> Dict[str, Any]:
    """Envoie la demande d'accord aux personnes dont la fenêtre de 24 h est ouverte ; les autres sont listées
    (il faut alors leur donner le lien / QR code d'accord)."""
    import httpx
    jeton, numero = (creds.get("access_token") or "").strip(), (creds.get("phone_number_id") or "").strip()
    if not jeton or not numero:
        return {"envoyees": 0, "fenetre_fermee": [], "erreurs": ["WhatsApp n'est pas configuré"]}
    envoyees, fermees, erreurs = 0, [], []
    proprietaire = http is None
    http = http or httpx.AsyncClient(timeout=12)
    try:
        for p in personnes:
            tel = re.sub(r"\D", "", p.get("telephone") or "")
            if not await fenetre_ouverte(db, tel, numero):
                fermees.append(p.get("nom") or tel)
                continue
            try:
                r = await http.post(f"https://graph.facebook.com/{version}/{numero}/messages", json=corps_demande(tel),
                                    headers={"Authorization": f"Bearer {jeton}"})
                if r.status_code < 300:
                    envoyees += 1
                else:
                    erreurs.append(f"{p.get('nom') or tel} : HTTP {r.status_code}")
            except httpx.HTTPError as exc:
                erreurs.append(f"{p.get('nom') or tel} : {type(exc).__name__}")
    finally:
        if proprietaire:
            await http.aclose()
    return {"envoyees": envoyees, "fenetre_fermee": fermees, "erreurs": erreurs}
