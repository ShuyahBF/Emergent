# marquage_prospect_pub.py — Lot 275 : Liluvine marque « Prospect » les contacts qui répondent à une publicité Facebook.
#
# Qui répond à une publicité ? Un message est une réponse à une publicité Facebook/Instagram quand :
#   1. il porte l'objet « referral » de Meta (clic sur une publicité Click-to-WhatsApp : titre, texte et lien de la
#      publicité, ctwa_clid) ; OU
#   2. il arrive sur une ligne WhatsApp cochée « prospects » (le numéro des publicités, Paramètres → WhatsApp).
# Dans ces deux cas, en plus des autres règles (réponse avec le prompt « prospects », aucune donnée du client), le contact
# reçoit l'étiquette « prospect » : c'est le bouton « Prospect » du Centre de messagerie, posé automatiquement.
#   - contact connu          : l'étiquette est ajoutée à sa fiche (jamais retirée, jamais en double) ;
#   - expéditeur inconnu     : l'encadré « à importer » est marqué ; à l'import, la fiche créée porte l'étiquette ;
#   - jamais pour un utilisateur du système (équipe, clients de la plateforme : fiche liée à un compte).
# Réglage (Paramètres → Auto-réponse WhatsApp → Prospects) : liluvine_wa_prospect_pub_marquage, activé par défaut.
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("sawali.marquage_prospect_pub")

ETIQUETTE = "prospect"


def actif(reglages: Optional[Dict[str, Any]]) -> bool:
    """Marquage automatique activé (défaut : oui)."""
    return (reglages or {}).get("liluvine_wa_prospect_pub_marquage") is not False


def reponse_publicitaire(msg: Optional[Dict[str, Any]], sur_ligne_prospects: bool = False) -> bool:
    """Vrai si le message répond à une publicité : objet « referral » de Meta, ou ligne « prospects ». Fonction pure."""
    referral = (msg or {}).get("referral")
    return bool(referral) or bool(sur_ligne_prospects)


async def marquer_contact(db, contact_id: Optional[str]) -> bool:
    """Ajoute l'étiquette « prospect » à la fiche (sans doublon, hors utilisateurs du système). Renvoie vrai si posée."""
    if not contact_id:
        return False
    res = await db.directory_contacts.update_one(
        {"id": contact_id, "wa_user_link": {"$in": [None, ""]}, "tags": {"$nin": [ETIQUETTE, "utilisateur-système"]}},
        {"$addToSet": {"tags": ETIQUETTE}})
    return bool(res.modified_count)
