# vip_contrat.py — Lot 158 : la ligne « Liluvine VIP » est réservée aux clients dont le contrat est valide.
#
# Demande du propriétaire (14/10/2026) : « aucun client en retard ne peut utiliser Liluvine VIP. Liluvine répond
# automatiquement : "Transfert de votre message aux agents de SAWALI. Les messages prioritaires VIP ne sont plus
# disponibles pour cette ligne." Rendre le message paramétrable et activable. Dans la conversation WhatsApp, avant la
# réponse, on doit pouvoir choisir le canal. Si on choisit "Liluvine VIP" alors que le client n'a pas de contrat valide,
# forcer la réponse sur la ligne standard avec une notification à l'utilisateur. »
#
# En résumé (pour un développeur WinDev) :
#   - RÉGLAGES (db.settings {_id:"global"}, Paramètres → « 💬 Ligne VIP — contrat valide ») :
#       wa_vip_controle_actif     : bool, désactivé par défaut (rien ne change tant qu'il n'est pas activé)
#       wa_vip_message_refus      : texte envoyé au client qui écrit sur la ligne VIP sans contrat valide
#       wa_vip_notification       : texte montré à l'utilisateur quand la réponse est forcée sur la ligne standard
#   - « CONTRAT VALIDE » = la puce VERTE du Centre de messagerie (lot 120). Le contact est relié à son client par la
#     même logique que la puce (société d'abord, puis e-mail, puis téléphone). Orange (retard) et rouge (aucun
#     contrat) = NON valide. Un contact NON ANALYSABLE (sans société, ou interne à SAWALI) n'est pas bloqué.
#   - MESSAGE REÇU sur la ligne VIP d'un client sans contrat valide : le message reste dans la boîte de SAWALI (les
#     agents le voient) ; Liluvine n'y répond pas elle-même mais envoie le texte ci-dessus, depuis la ligne VIP, au plus
#     une fois toutes les 6 heures par numéro.
#   - RÉPONSE d'un agent : le canal se choisit dans la conversation. « Liluvine VIP » choisi (ou imposé par la règle de
#     montant du contrat) pour un client sans contrat valide → le message part de la ligne STANDARD et l'agent est
#     prévenu par le texte de notification.
#   - LIMITE DE WHATSAPP : un texte libre n'est accepté que dans la fenêtre de 24 h ouverte AVEC LE NUMÉRO que le
#     client a écrit. Si le client n'a écrit que sur la ligne VIP, une réponse libre depuis la ligne standard peut être
#     refusée par WhatsApp (il faut alors un modèle approuvé) : l'erreur de WhatsApp est alors affichée telle quelle.
#
# Routes : GET/PUT /api/admin/whatsapp/vip-controle (réglages) ; GET /api/me/whatsapp/canal-vip (état pour un contact).
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.vip_contrat")

MESSAGE_REFUS_DEFAUT = ("Transfert de votre message aux agents de SAWALI. "
                        "Les messages prioritaires VIP ne sont plus disponibles pour cette ligne.")
NOTIFICATION_DEFAUT = ("Le contrat de ce client n'est pas valide : la ligne VIP lui est fermée. "
                       "Votre message est parti depuis la ligne standard.")
INTERVALLE_REFUS_HEURES = 6              # un seul texte de refus par numéro pendant ce délai
DUREE_CACHE_S = 60.0

_cache: Dict[str, Any] = {"lu_a": 0.0, "index": None, "internes": set()}


def reglages(settings_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Réglages du contrôle VIP, avec les valeurs par défaut (contrôle désactivé)."""
    s = settings_doc or {}
    return {
        "actif": bool(s.get("wa_vip_controle_actif")),
        "message": (str(s.get("wa_vip_message_refus") or "").strip() or MESSAGE_REFUS_DEFAUT)[:1000],
        "notification": (str(s.get("wa_vip_notification") or "").strip() or NOTIFICATION_DEFAUT)[:500],
    }


def contrat_valide(etat: Optional[str]) -> bool:
    """Logique pure : seule la puce VERTE (« valide ») ouvre la ligne VIP. None = contact non analysable : non bloqué."""
    return etat is None or etat == "valide"


async def _index_comptes(db):
    """Index des comptes clients (une lecture groupée, mémorisée 60 s) + identifiants du locataire SAWALI lui-même."""
    from routes.puce_contrat import CHAMPS_CLIENT, IndexComptes, _email_super_admin
    if _cache["index"] is not None and time.monotonic() - _cache["lu_a"] < DUREE_CACHE_S:
        return _cache["index"], _cache["internes"]
    comptes = await db.users.find({}, CHAMPS_CLIENT).to_list(50000)
    sa = await db.users.find_one({"email": _email_super_admin()}, {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1}) or {}
    internes = {v for v in (sa.get("id"), sa.get("client_id"), sa.get("parent_client_id")) if v}
    _cache.update(index=IndexComptes(comptes), internes=internes, lu_a=time.monotonic())
    return _cache["index"], internes


def vider_cache() -> None:
    _cache.update(index=None, lu_a=0.0, internes=set())


async def _contact_du_numero(db, telephone: Any) -> Optional[Dict[str, Any]]:
    """Fiche contact d'un numéro (8 derniers chiffres), avec les champs qui servent à retrouver son client."""
    import re
    chiffres = re.sub(r"\D", "", str(telephone or ""))
    if len(chiffres) < 6:
        return None
    fin = chiffres[-8:]
    return await db.directory_contacts.find_one(
        {"$or": [{"whatsapp": {"$regex": re.escape(fin)}}, {"phone": {"$regex": re.escape(fin)}}]},
        {"_id": 0, "id": 1, "client_id": 1, "email": 1, "phone": 1, "whatsapp": 1, "company": 1, "wa_ligne": 1})


async def etat_contrat_contact(db, contact: Optional[Dict[str, Any]], settings_doc: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """État du contrat du client d'un contact : « valide » | « retard » | « aucun », ou None (non analysable).
    Même logique que la puce du Centre de messagerie (routes/puce_contrat.py)."""
    from routes.puce_contrat import SEUIL_RETARD_DEFAUT, a_une_societe, est_interne, fiche_contrat
    if not contact or not a_une_societe(contact):
        return None
    index, internes = await _index_comptes(db)
    client, critere = index.client_du_contact(contact)
    if est_interne(client, internes, []):
        if critere == "societe":
            return None                       # la société est SAWALI elle-même : pas de contrat à vérifier
        client = None                          # relié à l'équipe seulement par e-mail / téléphone : sans contrat
    try:
        seuil = int((settings_doc or {}).get("contract_overdue_days_default") or SEUIL_RETARD_DEFAUT)
    except (TypeError, ValueError):
        seuil = SEUIL_RETARD_DEFAUT
    return fiche_contrat(client, datetime.now(timezone.utc).date(), seuil).get("etat")


async def acces_vip(db, settings_doc: Dict[str, Any], *, telephone: Any = None,
                    contact: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Le client de ce contact / numéro peut-il utiliser la ligne VIP ?
    → {controle_actif, autorise, etat}. Contrôle désactivé ⇒ toujours autorisé."""
    r = reglages(settings_doc)
    if not r["actif"]:
        return {"controle_actif": False, "autorise": True, "etat": None}
    if contact is None:
        contact = await _contact_du_numero(db, telephone)
    etat = await etat_contrat_contact(db, contact, settings_doc)
    return {"controle_actif": True, "autorise": contrat_valide(etat), "etat": etat}


async def traiter_message_entrant(db, settings_doc: Dict[str, Any], *, numero_recu: Optional[str], chiffres: str,
                                  contact: Optional[Dict[str, Any]], envoyer_texte: Callable[..., Awaitable[Any]],
                                  nom_contact: Optional[str] = None) -> Dict[str, Any]:
    """Message reçu : s'il arrive sur la ligne VIP d'un client sans contrat valide, envoie le texte de refus (depuis la
    ligne VIP, une fois toutes les 6 h par numéro). Renvoie {refuse: bool, texte_envoye: bool, etat}.
    Jamais d'exception : une erreur laisse Liluvine répondre comme avant."""
    resultat = {"refuse": False, "texte_envoye": False, "etat": None}
    try:
        r = reglages(settings_doc)
        if not r["actif"]:
            return resultat
        from routes.numeros_wa import cle_de_numero, ligne_par_cle
        ligne = ligne_par_cle(settings_doc, cle_de_numero(settings_doc, numero_recu))
        if not ligne or not ligne.get("vip"):
            return resultat                    # message reçu sur une autre ligne : rien à contrôler
        acces = await acces_vip(db, settings_doc, telephone=chiffres, contact=contact)
        resultat["etat"] = acces["etat"]
        if acces["autorise"]:
            return resultat
        resultat["refuse"] = True
        limite = (datetime.now(timezone.utc) - timedelta(hours=INTERVALLE_REFUS_HEURES)).isoformat()
        deja = await db.wa_vip_refus.find_one({"chiffres": chiffres, "le": {"$gte": limite}}, {"_id": 1})
        if deja:
            return resultat                    # déjà informé récemment : pas de répétition
        texte = r["message"].replace("{nom}", (nom_contact or "").strip() or "")
        envoi = await envoyer_texte(f"+{chiffres}" if not str(chiffres).startswith("+") else chiffres, texte)
        ok = bool((envoi or {}).get("ok")) if isinstance(envoi, dict) else bool(envoi)
        await db.wa_vip_refus.insert_one({"id": uuid.uuid4().hex, "chiffres": chiffres, "le": datetime.now(timezone.utc).isoformat(),
                                          "etat": acces["etat"], "ok": ok})
        resultat["texte_envoye"] = ok
    except Exception:  # noqa: BLE001 — jamais bloquant pour la réception
        logger.warning("[vip_contrat] traitement du message entrant impossible", exc_info=True)
    return resultat


async def choisir_canal(db, settings_doc: Dict[str, Any], *, user: Optional[Dict[str, Any]], telephone: Any,
                        contact_id: Optional[str], demande: Optional[str]) -> Dict[str, Any]:
    """Canal (ligne WhatsApp) choisi par l'agent dans la conversation, après contrôle.
    → {cle, libelle, force, avertissement} ; cle = None si rien n'est demandé (règles habituelles de numero_envoi).
      - ligne inconnue ou non autorisée à cet utilisateur : ignorée (règles habituelles) ;
      - ligne VIP demandée pour un client sans contrat valide (contrôle activé) : forcée sur la ligne STANDARD, avec le
        texte de notification à montrer à l'agent."""
    from routes.numeros_wa import LIGNE_PRINCIPALE, ligne_par_cle, lignes_autorisees
    vide = {"cle": None, "libelle": None, "force": False, "avertissement": None}
    ligne = ligne_par_cle(settings_doc, demande)
    if not ligne:
        return vide
    autorisees = lignes_autorisees(user, settings_doc)
    if autorisees is not None and ligne["cle"] not in autorisees:
        return vide
    if ligne.get("vip"):
        contact = None
        if contact_id:
            contact = await db.directory_contacts.find_one(
                {"id": contact_id}, {"_id": 0, "id": 1, "client_id": 1, "email": 1, "phone": 1, "whatsapp": 1, "company": 1})
        acces = await acces_vip(db, settings_doc, telephone=telephone, contact=contact)
        if not acces["autorise"]:
            standard = ligne_par_cle(settings_doc, LIGNE_PRINCIPALE) or {}
            return {"cle": LIGNE_PRINCIPALE, "libelle": standard.get("libelle"), "force": True,
                    "avertissement": reglages(settings_doc)["notification"]}
    return {"cle": ligne["cle"], "libelle": ligne.get("libelle"), "force": False, "avertissement": None}


class ReglagesVipIn(BaseModel):
    actif: bool = False
    message: str = Field(default="", max_length=1000)
    notification: str = Field(default="", max_length=500)


def setup_vip_contrat_routes(*, db, api, get_current_user, get_current_admin) -> None:
    """Branche les routes du lot 158 (appelée depuis server_parts/p20)."""
    from fastapi import Depends

    async def _etat_reglages() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        r = reglages(s)
        from routes.numeros_wa import ligne_vip
        vip = ligne_vip(s)
        return {**r, "message_defaut": MESSAGE_REFUS_DEFAUT, "notification_defaut": NOTIFICATION_DEFAUT,
                "ligne_vip": (vip or {}).get("libelle"), "intervalle_heures": INTERVALLE_REFUS_HEURES}

    @api.get("/admin/whatsapp/vip-controle", tags=["Admin — WhatsApp"])
    async def lire_reglages(_: dict = Depends(get_current_admin)):
        """Réglages du contrôle « ligne VIP réservée aux contrats valides »."""
        return await _etat_reglages()

    @api.put("/admin/whatsapp/vip-controle", tags=["Admin — WhatsApp"])
    async def ecrire_reglages(data: ReglagesVipIn, _: dict = Depends(get_current_admin)):
        """Active / désactive le contrôle et fixe les deux textes (vide = texte par défaut)."""
        await db.settings.update_one({"_id": "global"}, {"$set": {
            "wa_vip_controle_actif": bool(data.actif),
            "wa_vip_message_refus": data.message.strip(),
            "wa_vip_notification": data.notification.strip()}}, upsert=True)
        return await _etat_reglages()

    @api.get("/me/whatsapp/canal-vip", tags=["Portail Client"])
    async def canal_vip(contact_id: Optional[str] = None, telephone: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
        """État de la ligne VIP pour un contact (conversation) : {controle_actif, autorise, etat, notification}.
        Sert au Centre de messagerie à prévenir l'agent avant l'envoi. Aucune donnée de contrat détaillée."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        contact = None
        if contact_id:
            contact = await db.directory_contacts.find_one(
                {"id": contact_id}, {"_id": 0, "id": 1, "client_id": 1, "email": 1, "phone": 1, "whatsapp": 1, "company": 1})
        acces = await acces_vip(db, s, telephone=telephone or (contact or {}).get("whatsapp"), contact=contact)
        return {**acces, "notification": reglages(s)["notification"]}
