# wa_origine_reponse.py — Lot 198 : retrouver le message auquel un client répond (bouton de modèle, réponse citée).
#
# Le client répond « en citant » un message : WhatsApp ne donne que l'identifiant (wamid) du message d'origine.
# Retrouvé ici dans, par ordre :
#   1. db.whatsapp_messages  — messages envoyés depuis SAWALI (champ wa_message_id ou message_id) ;
#   2. db.liluvine_transmissions — messages envoyés par une PLATEFORME externe via /api/webhook/liluvine-send
#      (adLyn, e-Kol, rendez-vous…). Son journal garde la plateforme, le mode et la date, mais volontairement PAS le
#      texte (confidentialité) : l'aperçu dit donc quelle plateforme a écrit, sans le contenu.
# Aucune nouvelle collection : seulement des lectures de collections existantes.
from __future__ import annotations

from typing import Any, Dict, Iterable


def apercu_message(m: Dict[str, Any]) -> Dict[str, Any]:
    """Aperçu d'un message de whatsapp_messages (texte, modèle, date)."""
    texte = (m.get("template_rendered_body") or m.get("body") or m.get("media_caption")
             or (f"[{m['media_kind']}]" if m.get("media_kind") else "") or "")
    return {"sens": m.get("direction") or "outbound", "modele": m.get("template_name") or None,
            "texte": str(texte)[:300], "le": m.get("sent_at") or m.get("created_at"), "plateforme": None}


def apercu_transmission(t: Dict[str, Any]) -> Dict[str, Any]:
    """Aperçu d'un envoi fait par une plateforme externe (le texte n'est pas conservé dans ce journal)."""
    nom = t.get("emetteur") or t.get("source") or "plateforme externe"
    mode = {"modele": "modèle", "otp": "code de confirmation"}.get(t.get("mode"), "message")
    return {"sens": "outbound", "modele": None, "plateforme": str(nom),
            "texte": f"Envoyé par la plateforme « {nom} » ({mode}). Le texte n'est pas conservé.", "le": t.get("date")}


async def apercus_origines(db, identifiants: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """{wamid → aperçu} pour les identifiants retrouvés (lecture en bloc : une requête par collection)."""
    ids = [i for i in {str(x) for x in identifiants if x}]
    trouves: Dict[str, Dict[str, Any]] = {}
    if not ids:
        return trouves
    async for m in db.whatsapp_messages.find({"$or": [{"wa_message_id": {"$in": ids}}, {"message_id": {"$in": ids}}]},
                                            {"_id": 0}):
        for cle in (m.get("wa_message_id"), m.get("message_id")):
            if cle in ids and cle not in trouves:
                trouves[cle] = apercu_message(m)
    restants = [i for i in ids if i not in trouves]
    if restants:
        async for t in db.liluvine_transmissions.find({"message_id": {"$in": restants}}, {"_id": 0}):
            trouves.setdefault(t.get("message_id"), apercu_transmission(t))
    return trouves
