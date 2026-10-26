"""Lot 320 — Choix du service par TROIS BOUTONS WhatsApp : « Avec contrat » · « Sans contrat » · « En express ».

Liluvine termine sa réponse par le marqueur `[NIVEAUX]` quand le contact demande une intervention : le marqueur est retiré du texte et
les trois boutons sont envoyés juste après (WhatsApp admet 3 boutons de réponse au plus, titres de 20 caractères).
Le clic est traité ICI, sans passer par l'IA (réponse déterministe, jamais inventée) :
  - « Avec contrat » : Liluvine VÉRIFIE le contrat du client du contact (même règle que la puce de contrat) et répond :
      contrat valide → numéro, échéance, durée restante, services suspendus éventuels, délai du niveau « contrat » ;
      contrat en retard / expiré / absent → le dit clairement (sans montant) et propose « Sans contrat » ou « En express » ;
  - « Sans contrat » : niveau standard et son délai ;
  - « En express » : délai et tarif (forfait par intervention du client, « à préciser » si 0) ; la demande est confirmée par le contact,
    puis Liluvine prévient le propriétaire (marqueur [ESCALATE], lot 316).
Rien n'est annoncé tant que Paramètres → « Niveaux de service » n'est pas activé avec ses trois délais.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from routes.niveaux_service import normaliser_config
from routes.niveaux_service_liluvine import forfait_du_client, texte_forfait

logger = logging.getLogger("sawali.niveaux_boutons")

MARQUEUR = "[NIVEAUX]"
PREFIXE = "niv:"
BOUTONS: List[Tuple[str, str]] = [("niv:contrat", "Avec contrat"), ("niv:standard", "Sans contrat"), ("niv:express", "En express")]
TEXTE_CHOIX = "Quel service souhaitez-vous ? Touchez un bouton :"


def retirer_marqueur(reply: str) -> Tuple[str, bool]:
    """Retire `[NIVEAUX]` du texte de Liluvine ; renvoie (texte propre, marqueur présent)."""
    texte = str(reply or "")
    present = MARQUEUR in texte
    return re.sub(r"\s*\[NIVEAUX\]\s*", "\n", texte).strip() if present else texte, present


def _date_fr(iso: Any) -> str:
    """« 2027-03-31 » → « 31/03/2027 » (vide si absent)."""
    t = str(iso or "")[:10]
    return f"{t[8:10]}/{t[5:7]}/{t[:4]}" if re.match(r"^\d{4}-\d{2}-\d{2}$", t) else ""


def texte_contrat(fiche: Dict[str, Any], niveau: Dict[str, str]) -> Tuple[str, bool]:
    """Réponse au bouton « Avec contrat » d'après la fiche du contrat. Renvoie (texte, contrat_applicable). Jamais de montant."""
    etat = fiche.get("etat")
    numero = f" n° {fiche['numero']}" if fiche.get("numero") else ""
    if etat == "valide":
        infos = []
        if fiche.get("fin"):
            infos.append(f"valable jusqu'au {_date_fr(fiche['fin'])}")
        if fiche.get("mois_restants") is not None:
            infos.append(f"{fiche['mois_restants']} mois restants")
        if fiche.get("echeance_prochaine"):
            infos.append(f"prochaine échéance le {_date_fr(fiche['echeance_prochaine'])}")
        txt = f"✅ Votre contrat{numero} est valide" + (" (" + ", ".join(infos) + ")" if infos else "") + "."
        if fiche.get("services_suspendus"):
            txt += f" Services suspendus : {', '.join(fiche['services_suspendus'])}."
        txt += f"\n{niveau['libelle']} : {niveau['description']} — délai de prise en charge : {niveau['delai']}.".replace(" :  —", " :")
        return txt + "\nDécrivez votre demande en une phrase (problème, poste ou logiciel concerné).", True
    if etat == "retard":
        jours = fiche.get("jours_retard")
        motif = f" (échéance dépassée de {jours} jour(s))" if isinstance(jours, int) and jours > 0 else ""
        return (f"⚠️ Votre contrat{numero} est en retard de paiement{motif} : le niveau « contrat » n'est pas applicable pour le moment. "
                "Régularisez-le pour le retrouver, ou choisissez un autre service :"), False
    raison = (fiche.get("statut_libelle") or "").strip()
    return ("Je ne trouve pas de contrat valide à votre nom" + (f" ({raison.lower()})" if raison and raison != "Aucun contrat" else "") +
            ". Vous pouvez choisir un autre service :"), False


def texte_choix(choix: str, config: Dict[str, Any], fiche: Dict[str, Any], forfait: Any) -> Tuple[str, bool]:
    """Texte à envoyer pour un clic (`contrat` | `standard` | `express`) et si les 3 boutons doivent être reproposés."""
    n = config["niveaux"]
    if choix == "contrat":
        txt, ok = texte_contrat(fiche, n["contrat"])
        return txt, not ok
    if choix == "standard":
        return (f"{n['standard']['libelle']} : {n['standard']['description']} — délai de prise en charge : {n['standard']['delai']}.\n"
                "Décrivez votre demande en une phrase (problème, poste ou logiciel concerné).").replace(" :  —", " :"), False
    e = n["express"]
    return (f"⚡ {e['libelle']} : {e['description']} — délai : {e['delai']} — tarif : {texte_forfait(forfait)}.\n"
            "Pour lancer l'intervention EXPRESS, répondez OUI et décrivez le problème en une phrase."), False


async def fiche_du_contact(db, contact: Optional[Dict[str, Any]], settings_doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """(fiche du contrat, client) du contact — même liaison et même règle que la puce de contrat et le contrôle VIP."""
    from routes.puce_contrat import SEUIL_RETARD_DEFAUT, a_une_societe, est_interne, fiche_contrat
    from routes.vip_contrat import _index_comptes
    client = None
    if contact and a_une_societe(contact):
        index, internes = await _index_comptes(db)
        client, critere = index.client_du_contact(contact)
        if est_interne(client, internes, []):
            client = None
    try:
        seuil = int((settings_doc or {}).get("contract_overdue_days_default") or SEUIL_RETARD_DEFAUT)
    except (TypeError, ValueError):
        seuil = SEUIL_RETARD_DEFAUT
    return fiche_contrat(client, datetime.now(timezone.utc).date(), seuil), client


async def traiter_clic(db, *, bouton_id: str, chiffres: str, destinataire: str, wa_send_text, wa_send_boutons,
                       tenant_id: Optional[str] = None) -> bool:
    """Traite le clic sur l'un des 3 boutons ; True si le clic était le nôtre (et traité). Jamais d'exception."""
    if not str(bouton_id or "").startswith(PREFIXE):
        return False
    try:
        choix = bouton_id[len(PREFIXE):]
        if choix not in ("contrat", "standard", "express"):
            return False
        s = await db.settings.find_one({"_id": "global"}) or {}
        config = normaliser_config(s.get("niveaux_service"))
        if not config["configure"]:
            return False                                           # rubrique non activée : le clic retombe dans l'accusé habituel
        from routes.vip_contrat import _contact_du_numero
        contact = await _contact_du_numero(db, chiffres)
        fiche, client = await fiche_du_contact(db, contact, s)
        forfait = await forfait_du_client(db, client) if choix == "express" else None
        texte, reproposer = texte_choix(choix, config, fiche, forfait)
        envoi = await wa_send_text(destinataire, texte, tenant_id=tenant_id) if tenant_id else await wa_send_text(destinataire, texte)
        maintenant = datetime.now(timezone.utc).isoformat()
        await db.whatsapp_messages.insert_one({
            "id": secrets.token_hex(12), "client_id": (contact or {}).get("client_id"), "direction": "outbound", "to": destinataire,
            "phone_digits": chiffres, "contact_id": (contact or {}).get("id"), "body": texte, "message_type": "text",
            "auto_reply": True, "ai_generated": False, "ai_source": "niveaux_boutons", "sender_label": "Niveaux de service",
            "ok": bool((envoi or {}).get("ok")), "wa_message_id": (envoi or {}).get("message_id"), "message_id": (envoi or {}).get("message_id"),
            "wa_status": "sent" if (envoi or {}).get("ok") else "failed", "created_at": maintenant, "sent_at": maintenant})
        if reproposer and wa_send_boutons:
            await wa_send_boutons(destinataire, TEXTE_CHOIX)
        return True
    except Exception:  # noqa: BLE001 — un clic non traité retombe dans l'accusé de réception habituel
        logger.warning("[niveaux_boutons] clic non traité", exc_info=True)
        return False
