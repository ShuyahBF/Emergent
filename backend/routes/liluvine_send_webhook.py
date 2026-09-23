"""Lot Liluvine (2026-09, point 6) — Webhook entrant HMAC-signé permettant à
un système tiers (Liluvine ou autre) de déclencher l'envoi d'un message
WhatsApp via SAWALI, sans authentification utilisateur classique.

Body attendu (JSON simple) :
    {"message": "texte à envoyer"}

Header layout (même pattern que routes/vidal_dashboard.py::public_register) :
    X-Timestamp:   epoch seconds (±5 min)
    X-Signature:   sha256 HMAC = hexdigest( secret, f"{ts}.{raw_body}" )

Le numéro WhatsApp destinataire et le secret HMAC sont paramétrables par
l'admin dans AdminSettings (settings.global.liluvine_send_webhook_target_number
et .liluvine_send_webhook_hmac_secret — ce dernier ne doit jamais être
renvoyé en clair, voir GET_MASK_FIELDS dans routes/admin_settings.py).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import Body, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("sawali.liluvine_send_webhook")


class LiluvineSendPayload(BaseModel):
    message: str


def attach_liluvine_send_webhook_routes(*, api, db, wa_send_text):

    @api.post("/webhook/liluvine-send", tags=["Liluvine — Webhook"])
    async def liluvine_send(
        request: Request,
        payload: LiluvineSendPayload = Body(...),
        x_signature: str = Header(..., alias="X-Signature"),
        x_timestamp: str = Header(..., alias="X-Timestamp"),
    ):
        s = await db.settings.find_one(
            {"_id": "global"},
            {"_id": 0, "liluvine_send_webhook_hmac_secret": 1, "liluvine_send_webhook_target_number": 1},
        ) or {}
        secret = (s.get("liluvine_send_webhook_hmac_secret") or "").encode()
        if not secret:
            raise HTTPException(status_code=503, detail="Webhook Liluvine désactivé (secret HMAC non configuré).")
        target_number = (s.get("liluvine_send_webhook_target_number") or "").strip()
        if not target_number:
            raise HTTPException(status_code=503, detail="Webhook Liluvine désactivé (numéro WA cible non configuré).")

        # Timestamp window (±300 s) — anti-rejeu.
        try:
            ts = int(x_timestamp)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-Timestamp invalide")
        now = int(datetime.now(timezone.utc).timestamp())
        if abs(now - ts) > 300:
            raise HTTPException(status_code=401, detail="Timestamp expiré (±5 min)")

        # Signature check (sur le corps brut, avant parsing Pydantic).
        raw_body = await request.body()
        msg = f"{ts}.{raw_body.decode('utf-8', errors='replace')}".encode()
        expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_signature):
            raise HTTPException(status_code=401, detail="Signature HMAC invalide")

        result = await wa_send_text(target_number, payload.message)
        if not result.get("ok"):
            logger.warning("[liluvine_send_webhook] échec envoi WA vers %s: %s", target_number, result.get("error"))
            raise HTTPException(status_code=502, detail=f"Échec envoi WhatsApp : {result.get('error') or 'inconnu'}")
        return {"ok": True, "to": target_number, "message_id": result.get("message_id")}

    logger.info("[liluvine_send_webhook] route mounted at POST /api/webhook/liluvine-send")


__all__ = ["attach_liluvine_send_webhook_routes", "LiluvineSendPayload"]
