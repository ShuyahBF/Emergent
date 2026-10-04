"""« Transmission WA Universelle Liluvine » (lot 57.3, à partir du webhook du
lot Liluvine 2026-09) — webhook entrant HMAC-signé permettant aux autres
plateformes (Ster, adLyn, ALBARKA, beAuthentik…) d'envoyer un message WhatsApp
par la ligne de SAWALI / Liluvine, sans compte utilisateur.

Body attendu (JSON) :
    {"to": "+22670000000", "message": "texte à envoyer", "source": "ster"}
  - to      : numéro WhatsApp du destinataire (format international) ;
              facultatif : à défaut, numéro par défaut des Paramètres ;
  - message : texte à envoyer (obligatoire, 4 096 caractères au plus) ;
  - source  : nom de la plateforme qui envoie (facultatif, pour le journal).
Chaque envoi est noté dans la collection `liluvine_transmissions`.

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
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import Body, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("sawali.liluvine_send_webhook")


class LiluvineSendPayload(BaseModel):
    message: str
    to: Optional[str] = None       # numéro WhatsApp du destinataire (facultatif)
    source: Optional[str] = None   # plateforme émettrice (facultatif, journal)


def normaliser_numero(brut: str) -> Optional[str]:
    """« +226 70 00 00 00 » -> « +22670000000 » ; None si ce n'est pas un numéro
    international plausible (8 à 15 chiffres, préfixe + ou 00 accepté)."""
    chiffres = re.sub(r"[\s.\-()]", "", brut or "")
    if chiffres.startswith("00"):
        chiffres = "+" + chiffres[2:]
    if not re.fullmatch(r"\+?\d{8,15}", chiffres):
        return None
    return chiffres if chiffres.startswith("+") else "+" + chiffres


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

        # Destinataire : « to » du corps (signé), sinon le numéro par défaut des Paramètres
        if payload.to:
            target_number = normaliser_numero(payload.to)
            if not target_number:
                raise HTTPException(status_code=422, detail="Numéro « to » invalide (format international attendu, ex. +22670000000)")
        else:
            target_number = normaliser_numero(s.get("liluvine_send_webhook_target_number") or "")
            if not target_number:
                raise HTTPException(status_code=422, detail="Aucun destinataire : champ « to » absent et pas de numéro par défaut configuré.")
        message = (payload.message or "").strip()
        if not message:
            raise HTTPException(status_code=422, detail="Message vide")
        if len(message) > 4096:
            raise HTTPException(status_code=422, detail="Message trop long (4 096 caractères au plus)")
        source = (payload.source or "").strip()[:40] or "inconnue"

        result = await wa_send_text(target_number, message)
        # Journal de la Transmission WA Universelle (sans le texte du message)
        try:
            await db.liluvine_transmissions.insert_one({
                "date": datetime.now(timezone.utc).isoformat(), "source": source, "to": target_number,
                "ok": bool(result.get("ok")), "message_id": result.get("message_id"),
                "erreur": None if result.get("ok") else str(result.get("error") or "inconnu")[:300],
                "longueur": len(message),
            })
        except Exception:  # noqa: BLE001 — le journal ne bloque jamais l'envoi
            logger.exception("[liluvine_send_webhook] journal indisponible")
        if not result.get("ok"):
            logger.warning("[liluvine_send_webhook] échec envoi WA (source %s) vers %s: %s", source, target_number, result.get("error"))
            raise HTTPException(status_code=502, detail=f"Échec envoi WhatsApp : {result.get('error') or 'inconnu'}")
        return {"ok": True, "to": target_number, "source": source, "message_id": result.get("message_id")}

    logger.info("[liluvine_send_webhook] route mounted at POST /api/webhook/liluvine-send")


__all__ = ["attach_liluvine_send_webhook_routes", "LiluvineSendPayload", "normaliser_numero"]
