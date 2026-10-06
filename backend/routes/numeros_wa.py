# numeros_wa.py — Lot 59 : plusieurs numéros WhatsApp pour la plateforme SAWALI
# (« lignes » Liluvine : ex. « Liluvine Standard » = numéro principal, « Liluvine VIP »).
#
# Principe (tout est lu dans db.settings {_id:"global"}, modifiable dans
# Administration → Paramètres → WhatsApp Business API) :
#   - la ligne PRINCIPALE = le numéro déjà configuré (wa_phone_number_id),
#     libellé wa_principal_libelle (défaut « Liluvine Standard ») ;
#   - les lignes SUPPLÉMENTAIRES = liste wa_numeros :
#       [{"id": "<Phone Number ID Meta>", "libelle": "Liluvine VIP",
#         "telephone": "+226 73 88 49 99", "vip": true, "prospects": false,
#         "complement_prompt": "..."}]
#     (même compte WhatsApp, donc même jeton : aucun secret dans cette liste) ;
#   - règle VIP : un contact dont l'entreprise (tenant) a un « Montant du contrat »
#     ≥ wa_seuil_vip est servi par la ligne VIP.
#
# Choix du numéro qui ENVOIE un message (fonction numero_envoi), par priorité :
#   1. réponse à un message reçu : le numéro qui a reçu ce message (variable de
#      contexte posée par le webhook) — le client reçoit la réponse du même numéro ;
#   2. dernier message reçu de ce correspondant depuis moins de 24 h (fenêtre de
#      conversation Meta, liée au numéro) ;
#   3. ligne affectée à la main sur la fiche du contact (wa_ligne) ;
#   4. règle VIP (montant du contrat) ;
#   5. sinon la ligne principale.
#
# Visibilité dans le Centre de messagerie : chaque utilisateur peut être limité à
# certaines lignes (champ wa_lignes_autorisees sur l'utilisateur ; vide ou absent =
# toutes les lignes). Une conversation appartient à la ligne calculée ci-dessus
# voir la classe VisibiliteLignes.
from __future__ import annotations

import contextvars
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

# Identifiant logique de la ligne principale (le Phone Number ID réel peut changer
# dans les paramètres sans casser les affectations déjà faites).
LIGNE_PRINCIPALE = "principal"

# Numéro (Phone Number ID Meta) qui a reçu le message en cours de traitement.
# Posé par le webhook pour chaque lot de messages : toutes les réponses envoyées
# pendant ce traitement (Liluvine, commandes, accusés…) partent de ce numéro.
_numero_recu: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("numero_wa_recu", default=None)


def definir_numero_recu(phone_number_id: Optional[str]):
    """Mémorise le numéro qui a reçu le message en cours (retourne le jeton de remise à zéro)."""
    return _numero_recu.set((phone_number_id or "").strip() or None)


def retablir_numero_recu(jeton) -> None:
    """Remet la variable de contexte dans son état précédent (fin du traitement)."""
    try:
        _numero_recu.reset(jeton)
    except Exception:  # noqa: BLE001
        _numero_recu.set(None)


def numero_recu_courant() -> Optional[str]:
    """Numéro qui a reçu le message en cours de traitement (None hors webhook)."""
    return _numero_recu.get()


def _chiffres(valeur: Any) -> str:
    """Garde uniquement les chiffres d'un numéro de téléphone."""
    return re.sub(r"\D", "", str(valeur or ""))


def lignes_configurees(settings_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Toutes les lignes WhatsApp de la plateforme, la principale en premier.

    Chaque ligne : {cle, phone_number_id, libelle, telephone, vip, prospects, complement_prompt, principale}.
    `cle` = identifiant stable utilisé pour les affectations et les droits
    (« principal » pour la ligne principale, sinon le Phone Number ID).
    """
    s = settings_doc or {}
    lignes: List[Dict[str, Any]] = [{
        "cle": LIGNE_PRINCIPALE,
        "phone_number_id": (s.get("wa_phone_number_id") or "").strip(),
        "libelle": (s.get("wa_principal_libelle") or "").strip() or "Liluvine Standard",
        "telephone": (s.get("wa_principal_telephone") or "").strip(),
        "vip": False,
        "prospects": False,
        "complement_prompt": "",
        "principale": True,
    }]
    vus = {lignes[0]["phone_number_id"]} if lignes[0]["phone_number_id"] else set()
    for brut in s.get("wa_numeros") or []:
        if not isinstance(brut, dict):
            continue
        pid = str(brut.get("id") or brut.get("phone_number_id") or "").strip()
        if not pid or pid in vus:
            continue          # ligne incomplète ou doublon du principal : ignorée
        vus.add(pid)
        lignes.append({
            "cle": pid,
            "phone_number_id": pid,
            "libelle": (str(brut.get("libelle") or "").strip() or f"Ligne {pid[-4:]}"),
            "telephone": str(brut.get("telephone") or "").strip(),
            "vip": bool(brut.get("vip")),
            # Ligne « prospects » (ex. numéro des publicités Meta) : Liluvine y répond
            # avec le prompt prospects, quel que soit l'expéditeur.
            "prospects": bool(brut.get("prospects")),
            "complement_prompt": str(brut.get("complement_prompt") or "").strip(),
            "principale": False,
        })
    return lignes


def ligne_par_cle(settings_doc: Dict[str, Any], cle: Optional[str]) -> Optional[Dict[str, Any]]:
    """Retrouve une ligne par sa clé (« principal » ou Phone Number ID)."""
    cle = (cle or "").strip()
    if not cle:
        return None
    for ligne in lignes_configurees(settings_doc):
        if ligne["cle"] == cle or (ligne["phone_number_id"] and ligne["phone_number_id"] == cle):
            return ligne
    return None


def cle_de_numero(settings_doc: Dict[str, Any], phone_number_id: Optional[str]) -> Optional[str]:
    """Clé de ligne correspondant à un Phone Number ID Meta (None si numéro inconnu)."""
    pid = (phone_number_id or "").strip()
    if not pid:
        return None
    for ligne in lignes_configurees(settings_doc):
        if ligne["phone_number_id"] == pid:
            return ligne["cle"]
    return None


def ligne_vip(settings_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Première ligne marquée VIP (None s'il n'y en a pas)."""
    return next((l for l in lignes_configurees(settings_doc) if l["vip"]), None)


def seuil_vip(settings_doc: Dict[str, Any]) -> Optional[float]:
    """Montant de contrat à partir duquel un client passe sur la ligne VIP (None = règle désactivée)."""
    brut = (settings_doc or {}).get("wa_seuil_vip")
    if brut in (None, ""):
        return None
    try:
        valeur = float(brut)
    except (TypeError, ValueError):
        return None
    return valeur if valeur > 0 else None


def lignes_autorisees(utilisateur: Optional[Dict[str, Any]], settings_doc: Dict[str, Any]) -> Optional[Set[str]]:
    """Lignes que l'utilisateur peut voir dans le Centre de messagerie.

    None = toutes (pas de restriction : champ absent ou liste vide).
    Le super-administrateur de la plateforme voit toujours tout.
    """
    u = utilisateur or {}
    # Administrateurs et superviseurs voient toujours toutes les boîtes (toutes les lignes)
    if (u.get("role") in ("super_admin", "admin", "superviseur")
            or u.get("tracked_role") in ("Superviseur", "Administrateur")
            or u.get("email") == "admin@sawalismartsystems.com"):
        return None
    brut = u.get("wa_lignes_autorisees")
    if not brut:
        return None
    existantes = {l["cle"] for l in lignes_configurees(settings_doc)}
    autorisees = {str(x).strip() for x in brut if str(x).strip() in existantes}
    # Toutes les lignes cochées = aucune restriction réelle
    if not autorisees or autorisees >= existantes:
        return None
    return autorisees


async def _contact_du_telephone(db, chiffres: str) -> Optional[Dict[str, Any]]:
    """Fiche contact correspondant à un numéro (recherche sur les 8 derniers chiffres)."""
    if len(chiffres) < 6:
        return None
    fin = chiffres[-8:]
    return await db.directory_contacts.find_one(
        {"$or": [{"whatsapp": {"$regex": re.escape(fin)}}, {"phone": {"$regex": re.escape(fin)}}]},
        {"_id": 0, "id": 1, "client_id": 1, "wa_ligne": 1},
    )


async def _cle_du_dernier_message_recu(db, chiffres: str, settings_doc: Dict[str, Any],
                                       depuis_heures: Optional[int] = 24) -> Optional[str]:
    """Ligne sur laquelle ce correspondant a écrit en dernier (dans la fenêtre donnée)."""
    if not chiffres:
        return None
    filtre: Dict[str, Any] = {"direction": "inbound", "phone_digits": chiffres, "wa_numero_id": {"$nin": [None, ""]}}
    if depuis_heures:
        limite = (datetime.now(timezone.utc) - timedelta(hours=depuis_heures)).isoformat()
        filtre["created_at"] = {"$gte": limite}
    dernier = await db.whatsapp_messages.find_one(filtre, {"_id": 0, "wa_numero_id": 1}, sort=[("created_at", -1)])
    return cle_de_numero(settings_doc, (dernier or {}).get("wa_numero_id"))


async def cle_par_regle_vip(db, contact: Optional[Dict[str, Any]], settings_doc: Dict[str, Any]) -> Optional[str]:
    """Ligne VIP si l'entreprise du contact a un montant de contrat ≥ seuil VIP, sinon None."""
    vip = ligne_vip(settings_doc)
    seuil = seuil_vip(settings_doc)
    tenant_id = (contact or {}).get("client_id")
    if not vip or seuil is None or not tenant_id:
        return None
    tenant = await db.users.find_one({"id": tenant_id}, {"_id": 0, "contract_amount": 1})
    try:
        montant = float((tenant or {}).get("contract_amount"))
    except (TypeError, ValueError):
        return None
    return vip["cle"] if montant >= seuil else None


async def cle_ligne_conversation(db, telephone: Any, settings_doc: Dict[str, Any],
                                 contact: Optional[Dict[str, Any]] = None) -> str:
    """Ligne à laquelle appartient la conversation avec ce numéro (étapes 2 à 5).

    Sert à la fois au choix du numéro d'envoi et à la visibilité dans le
    Centre de messagerie.
    """
    chiffres = _chiffres(telephone)
    cle = await _cle_du_dernier_message_recu(db, chiffres, settings_doc, 24)
    if cle:
        return cle
    if contact is None:
        contact = await _contact_du_telephone(db, chiffres)
    manuelle = ligne_par_cle(settings_doc, (contact or {}).get("wa_ligne"))
    if manuelle:
        return manuelle["cle"]
    return (await cle_par_regle_vip(db, contact, settings_doc)) or LIGNE_PRINCIPALE


def numero_reponse(settings_doc: Dict[str, Any]) -> str:
    """Phone Number ID pour une RÉPONSE immédiate (sans base) : le numéro qui a reçu
    le message en cours, sinon le numéro principal."""
    principal = ((settings_doc or {}).get("wa_phone_number_id") or "").strip()
    ligne = ligne_par_cle(settings_doc or {}, cle_de_numero(settings_doc or {}, numero_recu_courant()))
    return ((ligne or {}).get("phone_number_id") or principal)


async def numero_envoi(db, telephone: Any, settings_doc: Dict[str, Any]) -> str:
    """Phone Number ID Meta à utiliser pour écrire à ce numéro (voir l'en-tête du fichier)."""
    principal = (settings_doc.get("wa_phone_number_id") or "").strip()
    # 1. Réponse à un message reçu : on répond depuis le numéro qui l'a reçu
    recu = cle_de_numero(settings_doc, numero_recu_courant())
    if recu:
        return ligne_par_cle(settings_doc, recu)["phone_number_id"] or principal
    # Une seule ligne configurée : inutile d'interroger la base
    if len(lignes_configurees(settings_doc)) < 2:
        return principal
    try:
        cle = await cle_ligne_conversation(db, telephone, settings_doc)
    except Exception:  # noqa: BLE001 — en cas de doute, la ligne principale
        return principal
    ligne = ligne_par_cle(settings_doc, cle)
    return ((ligne or {}).get("phone_number_id") or principal)


class VisibiliteLignes:
    """Visibilité des conversations par ligne pour UN utilisateur (Centre de messagerie).

    Calculée une fois par requête (quelques lectures groupées), puis interrogée
    pour chaque contact ou numéro. Ligne d'une conversation, par priorité :
      1. affectation manuelle sur la fiche du contact (wa_ligne) ;
      2. règle VIP (montant du contrat de l'entreprise du contact ≥ seuil) ;
      3. numéro sur lequel le correspondant a écrit en dernier ;
      4. sinon la ligne principale.
    (La catégorie du client passe avant le numéro utilisé : un client VIP qui
    écrit sur le numéro Standard reste réservé aux utilisateurs autorisés VIP.)
    """

    def __init__(self, settings_doc: Dict[str, Any], autorisees: Optional[Set[str]]):
        self.settings = settings_doc or {}
        self.autorisees = autorisees          # None = l'utilisateur voit tout
        self.derniere_ligne: Dict[str, str] = {}   # 8 derniers chiffres → clé de ligne
        self.tenants_vip: Set[str] = set()
        self.cle_vip: Optional[str] = None

    @property
    def restreint(self) -> bool:
        """Vrai si l'utilisateur ne voit qu'une partie des lignes."""
        return self.autorisees is not None

    @classmethod
    async def charger(cls, db, utilisateur: Optional[Dict[str, Any]],
                      settings_doc: Optional[Dict[str, Any]] = None,
                      complet: bool = False) -> "VisibiliteLignes":
        """Prépare la visibilité de cet utilisateur.

        Sans restriction, aucune lecture n'est faite, sauf si `complet` est demandé
        (pour afficher la ligne de chaque contact) et que plusieurs lignes existent.
        """
        if settings_doc is None:
            settings_doc = await db.settings.find_one({"_id": "global"}) or {}
        vis = cls(settings_doc, lignes_autorisees(utilisateur, settings_doc))
        plusieurs = len(lignes_configurees(settings_doc)) > 1
        if not vis.restreint and not (complet and plusieurs):
            return vis
        # Dernier numéro SAWALI sur lequel chaque correspondant a écrit
        pipeline = [
            {"$match": {"direction": "inbound", "wa_numero_id": {"$nin": [None, ""]}}},
            {"$sort": {"created_at": -1}},
            {"$group": {"_id": "$phone_digits", "numero": {"$first": "$wa_numero_id"}}},
        ]
        async for ligne in db.whatsapp_messages.aggregate(pipeline):
            cle = cle_de_numero(settings_doc, ligne.get("numero"))
            fin = _chiffres(ligne.get("_id"))[-8:]
            if cle and fin and fin not in vis.derniere_ligne:
                vis.derniere_ligne[fin] = cle
        # Entreprises (tenants) dont le montant de contrat atteint le seuil VIP
        vip, seuil = ligne_vip(settings_doc), seuil_vip(settings_doc)
        if vip and seuil is not None:
            vis.cle_vip = vip["cle"]
            async for t in db.users.find({"contract_amount": {"$gte": seuil}}, {"_id": 0, "id": 1}):
                if t.get("id"):
                    vis.tenants_vip.add(t["id"])
        return vis

    def cle_contact(self, contact: Optional[Dict[str, Any]], telephone: Any = None) -> str:
        """Ligne de la conversation avec ce contact (ou ce numéro sans fiche)."""
        c = contact or {}
        manuelle = ligne_par_cle(self.settings, c.get("wa_ligne"))
        if manuelle:
            return manuelle["cle"]
        if self.cle_vip and c.get("client_id") in self.tenants_vip:
            return self.cle_vip
        for tel in (telephone, c.get("whatsapp"), c.get("phone")):
            fin = _chiffres(tel)[-8:]
            if fin and fin in self.derniere_ligne:
                return self.derniere_ligne[fin]
        return LIGNE_PRINCIPALE

    def contact_visible(self, contact: Optional[Dict[str, Any]], telephone: Any = None) -> bool:
        """Vrai si l'utilisateur peut voir la conversation avec ce contact / ce numéro."""
        if not self.restreint:
            return True
        return self.cle_contact(contact, telephone) in self.autorisees


def ligne_recue_prospects(settings_doc: Dict[str, Any]) -> bool:
    """Vrai si le message en cours est arrivé sur une ligne « prospects » (ex. publicités)."""
    ligne = ligne_par_cle(settings_doc or {}, cle_de_numero(settings_doc or {}, numero_recu_courant()))
    return bool(ligne and ligne.get("prospects"))


async def complement_prompt_ligne(settings_doc: Dict[str, Any]) -> str:
    """Consignes supplémentaires de la ligne qui a reçu le message (ex. accueil VIP), ou ""."""
    ligne = ligne_par_cle(settings_doc, cle_de_numero(settings_doc, numero_recu_courant()))
    if not ligne or ligne["principale"] or not ligne["complement_prompt"]:
        return ""
    return f"\n\n[Ligne WhatsApp « {ligne['libelle']} »]\n{ligne['complement_prompt']}"


async def telephone_visible(db, utilisateur: Optional[Dict[str, Any]], telephone: Any,
                            contact: Optional[Dict[str, Any]] = None) -> bool:
    """Vrai si l'utilisateur peut voir / écrire à ce correspondant (contrôle avant envoi)."""
    vis = await VisibiliteLignes.charger(db, utilisateur)
    if not vis.restreint:
        return True
    if contact is None:
        contact = await _contact_du_telephone(db, _chiffres(telephone))
    return vis.contact_visible(contact, telephone)


async def exiger_telephone_visible(db, utilisateur: Optional[Dict[str, Any]], telephone: Any,
                                   contact_id: Optional[str] = None) -> None:
    """Refuse (403) un envoi vers un correspondant d'une ligne non autorisée à l'utilisateur."""
    vis = await VisibiliteLignes.charger(db, utilisateur)
    if not vis.restreint:
        return
    contact = None
    if contact_id:
        contact = await db.directory_contacts.find_one(
            {"id": contact_id}, {"_id": 0, "id": 1, "client_id": 1, "wa_ligne": 1, "whatsapp": 1, "phone": 1})
    if contact is None:
        contact = await _contact_du_telephone(db, _chiffres(telephone))
    if not vis.contact_visible(contact, telephone):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Ce correspondant dépend d'une ligne WhatsApp qui ne vous est pas attribuée")
