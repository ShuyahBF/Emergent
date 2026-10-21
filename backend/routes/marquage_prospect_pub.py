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


# ---------------------------------------------------------------------------
# Lot 276 — contacts des « Ad Auto-Replies » de Liluvine (Paramètres → Liluvine Reactions & Ad Auto-Replies)
# ---------------------------------------------------------------------------
async def modele_pour_texte(db, texte: Optional[str]) -> Optional[Dict[str, Any]]:
    """Modèle de réponse aux publicités (liluvine_ad_templates) qui correspond au texte, avec le même seuil de
    similarité que la réponse automatique ; None sans correspondance. Lectures seules."""
    texte = (texte or "").strip()
    if not texte:
        return None
    from routes.liluvine_reactions import _match_ad_template
    reglages = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_reactions_config": 1}) or {}
    seuil = int((reglages.get("liluvine_reactions_config") or {}).get("fuzzy_threshold") or 70)
    modeles = [t async for t in db.liluvine_ad_templates.find({}, {"_id": 0})]
    return _match_ad_template(texte, modeles, seuil)


async def marquer_numero_inconnu(db, chiffres: Optional[str]) -> int:
    """Expéditeur sans fiche : son encadré « à importer » est marqué ; la fiche créée à l'import portera l'étiquette."""
    if not chiffres:
        return 0
    res = await db.wa_pending_imports.update_many({"phone_digits": chiffres}, {"$set": {"prospect_pub": True}})
    return res.modified_count


async def point_prospects_publicite(db, perimetre: list, depuis: str, limite: int = 15) -> Dict[str, Any]:
    """Le point de Liluvine à la connexion : réponses reçues aux publicités depuis `depuis` (ISO), par modèle, et les
    derniers contacts concernés (nom, numéro, modèle, date). Lectures seules, bornées (aucune boucle par contact)."""
    filtre = {"kind": "ad_template", "created_at": {"$gte": depuis}}
    if perimetre:
        filtre["tenant_id"] = {"$in": list(perimetre)}
    lignes = [x async for x in db.liluvine_contact_interactions.find(filtre, {"_id": 0}).sort("created_at", -1).limit(500)]
    par_modele: Dict[str, int] = {}
    contacts: Dict[str, Dict[str, Any]] = {}
    for x in lignes:
        nom_modele = x.get("template_name") or "Modèle"
        par_modele[nom_modele] = par_modele.get(nom_modele, 0) + 1
        cle = x.get("contact_id") or x.get("phone_digits") or x.get("id")
        if cle not in contacts:                      # lignes triées du plus récent au plus ancien
            contacts[cle] = {"contact_id": x.get("contact_id"), "nom": x.get("contact_name") or f"+{x.get('phone_digits') or ''}",
                             "telephone": x.get("phone_digits"), "modele": nom_modele, "le": x.get("created_at"),
                             "message": (x.get("inbound_text") or "")[:80]}
    return {"total": len(lignes), "contacts": len(contacts), "depuis": depuis,
            "par_modele": [{"modele": k, "nombre": v} for k, v in sorted(par_modele.items(), key=lambda kv: -kv[1])],
            "derniers": list(contacts.values())[:limite]}
