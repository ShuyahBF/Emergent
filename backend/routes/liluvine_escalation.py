"""S036 — Liluvine PRO escalation to admin via WhatsApp.

When Liluvine PRO answers a contact via WhatsApp auto-reply, she may emit
the marker `[ESCALATE: <reason>]` at the END of her reply to signal she's
stuck and needs a human. This module:

  1. Parses the marker out of the reply
  2. Strips it from the user-facing message
  3. Sends a contextual WhatsApp notification to the admin (configurable
     phone, fallback to `llm_budget_notify_wa_phone`) with:
       • Contact name + phone
       • Last user message
       • Reason Liluvine emitted
       • Conversation snippet (last 3 messages)
  4. Throttles : at most 1 escalation per (phone) per 30 min to avoid spam

Settings (admin-configurable in /admin/settings) :
  - `liluvine_escalation_enabled`         bool, default False
  - `liluvine_escalation_wa_phone`        E.164, fallback to llm_budget_notify_wa_phone
  - `liluvine_escalation_cooldown_minutes` int, default 30
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Awaitable, Callable, Optional, Tuple

logger = logging.getLogger("sawali.liluvine_escalation")

# Markers Liluvine can emit at the end of her reply. Tolerant of accents,
# brackets, spacing and reason payload.
ESCALATE_RE = re.compile(
    r"\[\s*ESCALATE\s*:?\s*(?P<reason>[^\]]{0,300})\]",
    re.IGNORECASE,
)

ESCALATE_PROMPT_HINT = (
    "\n\n[IMPORTANT — Escalade vers un humain]\n"
    "Si tu ne peux pas répondre, si la question dépasse tes compétences, si "
    "elle demande une action sensible (modification de compte, paiement, plainte "
    "urgente), ou si tu détectes de la frustration/urgence, termine TON message "
    "par ce marqueur EXACT sur une nouvelle ligne (l'utilisateur ne le verra pas) :\n"
    "[ESCALATE: <raison courte en 1 phrase>]\n"
    "Exemple : [ESCALATE: client demande remboursement, hors de mes capacités]"
)


def strip_escalation_marker(reply: str) -> Tuple[str, Optional[str]]:
    """Remove the `[ESCALATE: ...]` marker from a reply.

    Returns (cleaned_reply, reason_or_None). When no marker is found,
    reason is None and the reply is unchanged.
    """
    if not reply:
        return reply, None
    m = ESCALATE_RE.search(reply)
    if not m:
        return reply, None
    reason = (m.group("reason") or "").strip()
    cleaned = ESCALATE_RE.sub("", reply).rstrip()
    return cleaned, reason or "Raison non précisée"


async def _resolve_admin_phone(settings: dict) -> Optional[str]:
    phone = (settings.get("liluvine_escalation_wa_phone") or "").strip()
    if not phone:
        phone = (settings.get("llm_budget_notify_wa_phone") or "").strip()
    return phone or None


async def _is_throttled(db, *, throttle_key: str, cooldown_min: int) -> bool:
    """Return True when an escalation was already sent for this key
    (contact_phone or user email/id) within the configured cooldown."""
    if not throttle_key:
        return False
    last = await db.liluvine_escalations.find_one(
        {"throttle_key": throttle_key},
        sort=[("sent_at", -1)],
        projection={"_id": 0, "sent_at": 1},
    )
    if not last:
        return False
    raw = last.get("sent_at")
    try:
        if isinstance(raw, datetime):
            ts = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return datetime.now(timezone.utc) - ts < timedelta(minutes=max(1, cooldown_min))


async def notify_admin(
    db,
    *,
    contact_name: Optional[str],
    contact_phone_digits: str,
    last_user_message: str,
    reason: str,
    send_wa: Callable[[str, str], Awaitable[dict]],
    session_id: Optional[str] = None,
    history: Optional[list] = None,
    initiator: str = "liluvine",
    throttle_key: Optional[str] = None,
) -> dict:
    """Send a WhatsApp escalation message to the configured admin.

    Args:
        initiator: "liluvine" (auto-escalation via [ESCALATE] marker) or
            "human" (S037 — portal user clicked "Demander de l'aide").
        throttle_key: Override the throttle key. Default is the
            contact_phone_digits, but for human-initiated escalations we
            usually want to throttle per user (email or id) instead.

    Returns a dict {sent, skipped_reason, to}.
    """
    settings = await db.settings.find_one(
        {"_id": "global"},
        {"_id": 0,
         "liluvine_escalation_enabled": 1,
         "liluvine_escalation_wa_phone": 1,
         "liluvine_escalation_cooldown_minutes": 1,
         "llm_budget_notify_wa_phone": 1},
    ) or {}

    if not settings.get("liluvine_escalation_enabled"):
        return {"sent": False, "skipped_reason": "disabled", "to": None}

    admin_phone = await _resolve_admin_phone(settings)
    if not admin_phone:
        return {"sent": False, "skipped_reason": "no_admin_phone", "to": None}

    cooldown = int(settings.get("liluvine_escalation_cooldown_minutes") or 30)
    effective_throttle_key = (throttle_key or contact_phone_digits or "").strip()
    if await _is_throttled(db, throttle_key=effective_throttle_key, cooldown_min=cooldown):
        return {"sent": False, "skipped_reason": "throttled", "to": admin_phone}

    # Build a compact context block
    name = (contact_name or "").strip() or (f"+{contact_phone_digits}" if contact_phone_digits else "Contact inconnu")
    last_msg = (last_user_message or "").strip()
    if len(last_msg) > 400:
        last_msg = last_msg[:400] + "…"
    reason_clean = (reason or "Raison non précisée")[:240]

    snippet_lines = []
    if history:
        for h in history[-3:]:
            who = "👤" if (h.get("role") or "").lower() == "user" else "🤖"
            t = (h.get("text") or h.get("content") or "")[:140]
            if t:
                snippet_lines.append(f"{who} {t}")
    snippet_block = ("\n".join(snippet_lines) + "\n") if snippet_lines else ""

    # S037 — Differentiate the WA header by initiator so admins know
    # whether the IA flagged itself OR a human asked for help.
    if initiator == "human":
        header = "🙋 *Demande d'aide d'un collaborateur*"
        contact_label = "👤 *Collaborateur :*"
        phone_label = "📧 *Identifiant :*" if not contact_phone_digits else "📱 *Téléphone :*"
        phone_value = contact_phone_digits or (throttle_key or "—")
    else:
        header = "🆘 *Liluvine PRO demande de l'aide*"
        contact_label = "👤 *Contact :*"
        phone_label = "📱 *Téléphone :*"
        phone_value = f"+{contact_phone_digits}" if contact_phone_digits else "—"

    body = (
        f"{header}\n"
        "\n"
        f"{contact_label} {name}\n"
        f"{phone_label} {phone_value}\n"
        f"🧠 *Raison :* {reason_clean}\n"
        "\n"
        f"💬 *Dernier message :*\n_{last_msg}_\n"
    )
    if snippet_block:
        body += f"\n*Extrait de conversation :*\n{snippet_block}"
    body += (
        "\n➡️ Ouvrez l'historique pour reprendre la conversation : "
        "Liluvine PRO → Historique"
    )

    sent_ok = False
    try:
        res = await send_wa(admin_phone, body)
        sent_ok = bool(res and res.get("ok"))
    except Exception:  # noqa: BLE001
        logger.exception("[liluvine_escalation] send_wa failed")

    try:
        await db.liluvine_escalations.insert_one({
            "sent_at": datetime.now(timezone.utc),
            "contact_phone_digits": contact_phone_digits,
            "contact_name": contact_name,
            "reason": reason_clean,
            "last_user_message": last_msg,
            "admin_phone": admin_phone,
            "session_id": session_id,
            "sent_ok": sent_ok,
            "initiator": initiator,
            "throttle_key": effective_throttle_key,
        })
    except Exception:  # noqa: BLE001
        logger.exception("[liluvine_escalation] persist log failed")

    return {
        "sent": sent_ok,
        "skipped_reason": None if sent_ok else "send_failed",
        "to": admin_phone,
    }


__all__ = [
    "ESCALATE_RE",
    "ESCALATE_PROMPT_HINT",
    "strip_escalation_marker",
    "notify_admin",
]
