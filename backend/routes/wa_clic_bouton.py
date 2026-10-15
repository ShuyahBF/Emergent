# wa_clic_bouton.py — Lot 207 : TOUT clic sur un bouton d'un message de SAWALI reçoit une réponse immédiate.
#
# Constat (15/10/2026) : une personne a cliqué deux fois sur « Confirmer » en 20 minutes sans aucune réponse. La réponse
# automatique passait par l'IA de Liluvine, soumise à de nombreuses conditions (prise en main humaine, périmètre, réglages…) :
# un clic pouvait donc rester sans réponse. Ici, pour CHAQUE clic sur un bouton (modèle, carrousel, formulaire, sondage,
# requête client, campagne… — le message d'origine peut être n'importe lequel), l'accusé est DÉTERMINISTE :
#   - il remercie la personne en citant le bouton touché ;
#   - il rappelle la publication d'origine quand le message cité est retrouvé (lot 199) ;
#   - il invite à écrire sa question s'il y en a une ;
#   - un seul accusé toutes les 10 minutes par numéro (pas de rafale si la personne touche plusieurs boutons).
# Les clics qui sont des accords ou des refus (demande d'accord de SAWALI) sont traités AVANT, par le webhook.
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("sawali.clic_bouton")

DELAI_ACCUSE_MINUTES = 10
MODELE_DEFAUT = "Merci pour votre réponse « {bouton} » 🙏 Elle est bien enregistrée{contexte}. Si vous avez une question, écrivez-la ici : nous vous répondons."


def clic_bouton(doc: Dict[str, Any]) -> bool:
    """Le message reçu est un clic sur un bouton (modèle ou message interactif) avec un libellé lisible."""
    return (doc.get("message_type") in ("button", "interactive")) and bool((doc.get("body") or "").strip())


def texte_accuse(modele: Optional[str], bouton: str, contexte: Optional[Dict[str, Any]]) -> str:
    """Texte de l'accusé : `{bouton}` = libellé touché, `{contexte}` = « (à propos de : sondage « Titre ») » si connu. Fonction pure."""
    suite = ""
    if contexte and contexte.get("cite") and contexte.get("titre"):
        suite = f" (à propos de : {contexte.get('type') or 'message'} « {str(contexte['titre'])[:80]} »)"
    brut = (modele or "").strip() or MODELE_DEFAUT
    return brut.replace("{bouton}", (bouton or "").strip()[:60]).replace("{contexte}", suite)[:900]


async def accuser_clic(db, *, inbound_doc: Dict[str, Any], wa_send_text, reglages: Optional[Dict[str, Any]] = None,
                       maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Envoie l'accusé de réception d'un clic (et le journalise dans la conversation). Jamais d'exception."""
    try:
        if not clic_bouton(inbound_doc):
            return {"ok": False, "reason": "pas_un_clic"}
        tel = "".join(ch for ch in str(inbound_doc.get("phone_digits") or inbound_doc.get("from") or "") if ch.isdigit())
        if len(tel) < 8:
            return {"ok": False, "reason": "numero_inconnu"}
        maintenant = maintenant or datetime.now(timezone.utc)
        limite = (maintenant - timedelta(minutes=DELAI_ACCUSE_MINUTES)).isoformat()
        deja = await db.whatsapp_messages.find_one(
            {"direction": "outbound", "ai_source": "clic_bouton", "phone_digits": {"$regex": tel[-8:] + "$"}, "created_at": {"$gte": limite}},
            {"_id": 1})
        if deja:
            return {"ok": False, "reason": "deja_accuse"}
        from routes.wa_publication_contexte import contexte_reponse
        ctx = await contexte_reponse(db, inbound_doc)
        texte = texte_accuse((reglages or {}).get("liluvine_wa_clic_bouton_reponse"), inbound_doc.get("body") or "", ctx)
        a = inbound_doc.get("from") or f"+{tel}"
        res = await wa_send_text(a, texte)
        ok = bool((res or {}).get("ok"))
        await db.whatsapp_messages.insert_one({
            "id": secrets.token_hex(12), "client_id": inbound_doc.get("client_id"), "direction": "outbound", "to": a,
            "phone_digits": tel, "contact_id": inbound_doc.get("contact_id"), "body": texte, "message_type": "text",
            "auto_reply": True, "ai_generated": False, "ai_source": "clic_bouton", "sender_label": "Accusé de réception",
            "reply_to_message_id": inbound_doc.get("wa_message_id"), "ok": ok, "status": (res or {}).get("status"),
            "wa_message_id": (res or {}).get("message_id"), "message_id": (res or {}).get("message_id"),
            "wa_status": "sent" if ok else "failed", "created_at": maintenant.isoformat(), "sent_at": maintenant.isoformat()})
        logger.info("[clic_bouton] accusé %s pour …%s (bouton « %s »%s)", "envoyé" if ok else "ÉCHEC", tel[-4:],
                    (inbound_doc.get("body") or "")[:30], f", origine : {ctx.get('type')}" if ctx else "")
        return {"ok": ok, "reason": "clic_bouton_accuse", "origine": (ctx or {}).get("type")}
    except Exception:  # noqa: BLE001 — un accusé raté ne doit jamais bloquer la réception
        logger.warning("[clic_bouton] accusé impossible", exc_info=True)
        return {"ok": False, "reason": "erreur"}
