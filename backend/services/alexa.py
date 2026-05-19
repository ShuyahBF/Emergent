"""Iter35y — Alexa Echo voice notifications via Voice Monkey (extracted from server.py).

Best-effort fire-and-forget POST whenever a subscribed event fires. Failures
are logged but never raise — Alexa is "nice to have", never critical path.

Settings keys (in db.settings, _id="global"):
  • alexa_enabled         : bool
  • alexa_webhook_url     : str   (https://api-v2.voicemonkey.io/announcement?token=...&device=...)
  • alexa_events          : list  (subset of ALEXA_EVENT_TYPES.keys())

Used by:
  • WhatsApp webhook inbound  → "wa_inbound"
  • Support load >= 6 (POST + webhook) → "support_load_critical"
  • Appointment reminder cron 24h → "appointment_due"
  • (SMS inbound not wired yet — no real receive endpoint in the codebase)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("sawali.alexa")


ALEXA_EVENT_TYPES = {
    "sms_inbound": "SMS reçu",
    "wa_inbound": "WhatsApp reçu",
    "appointment_due": "Rendez-vous imminent",
    "support_load_critical": "Niveau de support critique",
}


async def alexa_notify(db: "AsyncIOMotorDatabase", event_type: str, message: str) -> None:
    """POST to Voice Monkey when enabled and subscribed.

    Best-effort: never raises. Returns silently if disabled / not subscribed /
    URL invalid / network error.
    """
    try:
        s = await db.settings.find_one(
            {"_id": "global"},
            {"_id": 0, "alexa_enabled": 1, "alexa_webhook_url": 1, "alexa_events": 1},
        ) or {}
        if not s.get("alexa_enabled"):
            return
        url = (s.get("alexa_webhook_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return
        events = s.get("alexa_events") or []
        if event_type not in events:
            return
        payload = {
            "event": event_type,
            "event_label": ALEXA_EVENT_TYPES.get(event_type, event_type),
            "announcement": (message or "")[:200],
            "source": "sawali-portal",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        async with httpx.AsyncClient(timeout=8) as http:
            await http.post(url, json=payload, headers={"Accept": "application/json"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[alexa] notify failed: %s", exc)


def alexa_notify_async(db: "AsyncIOMotorDatabase", event_type: str, message: str) -> None:
    """Sync wrapper that schedules the async notify in the running loop."""
    try:
        asyncio.create_task(alexa_notify(db, event_type, message))
    except Exception:  # noqa: BLE001
        # No running loop (e.g. import-time) — ignore.
        pass
