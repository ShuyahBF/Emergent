"""S034 — WhatsApp Admin Cockpit (mobile command center).

When `llm_budget_wa_query_enabled` is true (the master toggle reused from
S033), the authorized admin number can send one of the following keywords
by WhatsApp to the bot and receive an instant reply:

    SOLDE       → Universal Key Emergent balance summary (S033 / S032)
    STATS       → 24h KPIs: WA inbound/outbound, SMS, contacts, etc.
    INCIDENTS   → Open support tickets (5 most recent)
    AIDE / HELP → Menu of available commands

The trigger message is never persisted nor forwarded to Liluvine PRO so
the cockpit feels completely separate from the conversation flow.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("sawali.wa_admin_cockpit")

# Set of open ticket statuses — kept in sync with backend/server.py
TICKET_OPEN_STATUSES = {"open", "in_progress", "suspended"}

# Keyword → handler key (case-insensitive). Multiple keywords can point to
# the same handler (e.g. AIDE and HELP).
KEYWORDS: dict[str, str] = {
    "SOLDE": "balance",
    "BUDGET": "balance",
    "STATS": "stats",
    "KPI": "stats",
    "INCIDENTS": "incidents",
    "TICKETS": "incidents",
    "AIDE": "help",
    "HELP": "help",
    "MENU": "help",
}


def _help_text() -> str:
    return (
        "🤖 *Cockpit WhatsApp Admin — Commandes disponibles*\n"
        "\n"
        "💰 *SOLDE* — Solde et vitesse de consommation Universal Key\n"
        "📊 *STATS* — KPI temps réel (24h) : WA, SMS, contacts\n"
        "🎫 *INCIDENTS* — Tickets de support ouverts (top 5)\n"
        "❓ *AIDE* — Afficher ce menu\n"
        "\n"
        "_Envoyez simplement le mot-clé en majuscules ou minuscules._\n"
        "_— SAWALI Smart Systems · Cockpit S034_"
    )


async def _build_stats_text(db) -> str:
    """Build the STATS reply: WA in/out 24h, SMS sent 24h, total contacts,
    open tickets count."""
    now = datetime.now(timezone.utc)
    since_24h_iso = (now - timedelta(hours=24)).isoformat()

    async def _safe_count(coll, q):
        try:
            return await coll.count_documents(q)
        except Exception:  # noqa: BLE001
            logger.exception("[cockpit] count failed on %s", coll.name)
            return 0

    wa_in_24h = await _safe_count(db.whatsapp_messages, {"direction": "inbound", "received_at": {"$gte": since_24h_iso}})
    wa_out_24h = await _safe_count(db.whatsapp_messages, {"direction": "outbound", "created_at": {"$gte": since_24h_iso}})
    sms_24h = await _safe_count(db.sms_messages, {"created_at": {"$gte": since_24h_iso}})
    contacts_total = await _safe_count(db.directory_contacts, {})
    tickets_open = await _safe_count(db.support_tickets, {
        "status": {"$in": list(TICKET_OPEN_STATUSES)},
        "archived_at": {"$in": [None, ""]},
    })
    appointments_today = 0
    try:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999000).isoformat()
        appointments_today = await db.appointments.count_documents({
            "starts_at": {"$gte": today_start, "$lte": today_end},
            "status": {"$nin": ["cancelled", "canceled"]},
        })
    except Exception:  # noqa: BLE001
        pass

    return (
        "📊 *STATS temps réel (dernières 24h)*\n"
        "\n"
        f"💬 WhatsApp reçus : *{wa_in_24h}*\n"
        f"📤 WhatsApp envoyés : *{wa_out_24h}*\n"
        f"📱 SMS envoyés : *{sms_24h}*\n"
        f"📅 Rendez-vous aujourd'hui : *{appointments_today}*\n"
        f"🎫 Tickets ouverts : *{tickets_open}*\n"
        f"👥 Contacts en base : *{contacts_total}*\n"
        "\n"
        f"_Snapshot {now.strftime('%d/%m/%Y %H:%M UTC')}_"
    )


async def _build_incidents_text(db) -> str:
    """List the 5 most recent open support tickets."""
    try:
        cursor = db.support_tickets.find(
            {"status": {"$in": list(TICKET_OPEN_STATUSES)},
             "archived_at": {"$in": [None, ""]}},
            {"_id": 0, "id": 1, "number": 1, "status": 1, "priority": 1,
             "title": 1, "contact_name": 1, "opened_at": 1},
        ).sort("opened_at", -1).limit(5)
        items = await cursor.to_list(length=5)
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] failed to fetch open tickets")
        items = []

    total = await db.support_tickets.count_documents({
        "status": {"$in": list(TICKET_OPEN_STATUSES)},
        "archived_at": {"$in": [None, ""]},
    })

    if not items:
        return (
            "🎫 *Tickets de support — État*\n"
            "\n"
            "✅ Aucun ticket ouvert. Tous les incidents sont traités !\n"
            "\n"
            f"_Snapshot {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}_"
        )

    pri_emoji = {"critical": "🔴", "high": "🟠", "normal": "🟡", "low": "🔵"}
    status_label = {"open": "ouvert", "in_progress": "en cours", "suspended": "suspendu"}
    lines = [f"🎫 *Tickets de support — {total} ouvert(s) (top 5)*", ""]
    for it in items:
        pri = (it.get("priority") or "normal").lower()
        st = (it.get("status") or "open").lower()
        num = it.get("number") or it.get("id", "?")[:8]
        title = (it.get("title") or "(sans titre)")[:60]
        contact = it.get("contact_name") or "—"
        opened = it.get("opened_at", "")
        opened_short = opened[:16].replace("T", " ") if isinstance(opened, str) else ""
        lines.append(f"{pri_emoji.get(pri, '⚪')} *#{num}* · {status_label.get(st, st)}")
        lines.append(f"   _{title}_")
        lines.append(f"   👤 {contact} · 🕒 {opened_short}")
    lines.append("")
    lines.append(f"_Snapshot {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}_")
    return "\n".join(lines)


def _resolve_keyword(text: str) -> Optional[str]:
    norm = (text or "").strip().upper()
    return KEYWORDS.get(norm)


async def handle_wa_admin_command(
    db,
    *,
    text: str,
    from_digits: str,
    send_wa: Callable[[str, str], Awaitable[dict]],
    build_balance_text: Callable[[], Awaitable[str]],
) -> bool:
    """S034 — Inbound WhatsApp dispatcher for the admin cockpit.

    Args:
        db: motor async db.
        text: inbound message body (free-form).
        from_digits: digits-only sender phone.
        send_wa: async callable (to_e164, text) → dict.
        build_balance_text: async callable returning the SOLDE summary
            (injected — points to llm_health.build_budget_summary_text).

    Returns True when the message matched a command and was handled (caller
    must skip persistence + auto-reply). Returns False otherwise.
    """
    handler_key = _resolve_keyword(text)
    if not handler_key:
        return False

    settings = await db.settings.find_one(
        {"_id": "global"},
        {"_id": 0, "llm_budget_wa_query_enabled": 1, "llm_budget_notify_wa_phone": 1},
    ) or {}
    if not settings.get("llm_budget_wa_query_enabled"):
        return False

    authorized = (settings.get("llm_budget_notify_wa_phone") or "").strip()
    auth_digits = "".join(ch for ch in authorized if ch.isdigit())
    if auth_digits:
        if (from_digits or "")[-10:] != auth_digits[-10:]:
            logger.info("[cockpit] command %s from %s ignored (not authorized %s)",
                        handler_key, from_digits, auth_digits)
            return False

    # Build reply
    try:
        if handler_key == "balance":
            reply = await build_balance_text()
        elif handler_key == "stats":
            reply = await _build_stats_text(db)
        elif handler_key == "incidents":
            reply = await _build_incidents_text(db)
        elif handler_key == "help":
            reply = _help_text()
        else:
            return False
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] failed to build reply for %s", handler_key)
        return False

    try:
        await send_wa("+" + from_digits, reply)
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] send_wa failed")
    return True


__all__ = ["handle_wa_admin_command", "KEYWORDS", "_help_text"]
