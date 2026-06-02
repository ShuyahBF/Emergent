"""S034 + S035 — WhatsApp Admin Cockpit (mobile command center).

When `llm_budget_wa_query_enabled` is true (the master toggle reused from
S033), the authorized admin number can send one of the following keywords
by WhatsApp to the bot and receive an instant reply / trigger an action:

CONSULTATION (S034)
    SOLDE / BUDGET             → Universal Key balance summary
    STATS / KPI                → 24h KPIs
    INCIDENTS / TICKETS        → Open support tickets (top 5)
    AIDE / HELP / MENU         → Menu of available commands

ACTIONS (S035)
    RESOLU #NNNN / FERMER #NNNN  → Close a support ticket
    MUTE / NOTIF STOP            → Mute LLM budget alerts for 24h
    UNMUTE / NOTIF ON            → Resume LLM budget alerts immediately
"""
from __future__ import annotations

import logging
import re
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
    # S035 — Action commands (single-keyword form; parametric ones handled below)
    "MUTE": "mute",
    "UNMUTE": "unmute",
}

# S035 — Parametric command patterns (regex). Matched AFTER the static
# KEYWORDS table.
RE_CLOSE_TICKET = re.compile(r"^\s*(?:RESOLU|RÉSOLU|FERMER|CLOSE)\s+#?(\S+)\s*$", re.IGNORECASE)
RE_NOTIF_STOP = re.compile(r"^\s*NOTIF\s+(STOP|OFF)\s*$", re.IGNORECASE)
RE_NOTIF_ON = re.compile(r"^\s*NOTIF\s+(ON|START|RESUME)\s*$", re.IGNORECASE)

MUTE_DURATION_HOURS = 24


def _help_text() -> str:
    return (
        "🤖 *Cockpit WhatsApp Admin — Commandes disponibles*\n"
        "\n"
        "*📊 Consultation*\n"
        "💰 *SOLDE* — Consommation Universal Key\n"
        "📊 *STATS* — KPI temps réel (24h)\n"
        "🎫 *INCIDENTS* — Tickets ouverts (top 5)\n"
        "\n"
        "*⚡ Actions*\n"
        "✅ *RESOLU #1234* — Fermer un ticket\n"
        "🔕 *NOTIF STOP* (ou MUTE) — Mettre en pause les alertes (24h)\n"
        "🔔 *NOTIF ON* (ou UNMUTE) — Réactiver les alertes\n"
        "❓ *AIDE* — Afficher ce menu\n"
        "\n"
        "_Envoyez simplement le mot-clé en majuscules ou minuscules._\n"
        "_— SAWALI Smart Systems · Cockpit S034+S035_"
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
    lines.append("💡 _Pour fermer : envoyer_ `RESOLU #NUM`")
    lines.append(f"_Snapshot {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}_")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# S035 — Action handlers
# ----------------------------------------------------------------------

async def _close_ticket_action(db, *, ticket_num: str, actor_phone: str) -> str:
    """Close a support ticket by number OR id. Returns the WhatsApp reply
    text."""
    ticket_num = (ticket_num or "").strip().lstrip("#")
    if not ticket_num:
        return "❌ Numéro de ticket manquant. Utilisez : *RESOLU #1234*"
    ticket = None
    try:
        # Try by number first (string match, case-insensitive)
        ticket = await db.support_tickets.find_one(
            {"number": {"$regex": f"^{re.escape(ticket_num)}$", "$options": "i"}},
            {"_id": 0, "id": 1, "number": 1, "status": 1, "title": 1, "contact_name": 1},
        )
        # Fallback: match by id (UUID or partial id prefix)
        if not ticket:
            ticket = await db.support_tickets.find_one(
                {"$or": [{"id": ticket_num},
                         {"id": {"$regex": f"^{re.escape(ticket_num)}", "$options": "i"}}]},
                {"_id": 0, "id": 1, "number": 1, "status": 1, "title": 1, "contact_name": 1},
            )
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] ticket lookup failed")
        return "❌ Erreur technique lors de la recherche du ticket."

    if not ticket:
        return f"❌ Ticket *#{ticket_num}* introuvable.\n\nEnvoyez *INCIDENTS* pour voir les tickets ouverts."

    if (ticket.get("status") or "").lower() not in TICKET_OPEN_STATUSES:
        return (
            f"ℹ️ Le ticket *#{ticket.get('number', ticket_num)}* est déjà *{ticket.get('status')}*.\n"
            f"_{(ticket.get('title') or '')[:80]}_"
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        await db.support_tickets.update_one(
            {"id": ticket["id"]},
            {"$set": {
                "status": "resolved",
                "resolved_at": now_iso,
                "closed_at": now_iso,
                "closed_by_wa": actor_phone,
                "closed_via": "wa_cockpit_s035",
            }},
        )
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] failed to close ticket")
        return "❌ Erreur lors de la fermeture du ticket. Réessayez plus tard."

    return (
        f"✅ *Ticket #{ticket.get('number', ticket_num)} fermé*\n"
        f"_{(ticket.get('title') or '(sans titre)')[:80]}_\n"
        f"👤 {ticket.get('contact_name') or '—'}\n"
        f"🕒 Fermé à {datetime.now(timezone.utc).strftime('%H:%M UTC')} via WhatsApp"
    )


async def _mute_alerts_action(db) -> str:
    """Pause LLM budget alerts (S032 + S031 daily email) for 24h."""
    until = datetime.now(timezone.utc) + timedelta(hours=MUTE_DURATION_HOURS)
    until_iso = until.isoformat()
    try:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"llm_alerts_muted_until": until_iso}},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] mute persist failed")
        return "❌ Erreur lors de l'activation du silencieux."
    return (
        f"🔕 *Alertes Universal Key mises en pause*\n"
        f"Reprise automatique : *{until.strftime('%d/%m/%Y %H:%M UTC')}*\n"
        f"(soit dans {MUTE_DURATION_HOURS}h)\n"
        f"\n"
        f"Envoyez *NOTIF ON* pour réactiver immédiatement."
    )


async def _unmute_alerts_action(db) -> str:
    """Resume LLM budget alerts immediately."""
    try:
        await db.settings.update_one(
            {"_id": "global"},
            {"$unset": {"llm_alerts_muted_until": ""}},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] unmute persist failed")
        return "❌ Erreur lors de la réactivation des alertes."
    return "🔔 *Alertes Universal Key réactivées.*\nLe cron de surveillance reprendra ses contrôles toutes les 15 min."


async def alerts_are_muted(db) -> bool:
    """Helper used by S031/S032 alert senders to check the mute state."""
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "llm_alerts_muted_until": 1}) or {}
    raw = settings.get("llm_alerts_muted_until")
    if not raw:
        return False
    try:
        until = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < until
    except (TypeError, ValueError):
        return False


# ----------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------

def _resolve_static_keyword(text: str) -> Optional[str]:
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
    """S034 + S035 — Inbound WhatsApp dispatcher for the admin cockpit.

    Returns True when the message matched a command (caller must skip
    persistence + auto-reply). Returns False otherwise.
    """
    # Auth check FIRST so we can short-circuit on disabled toggle or
    # unauthorized phone before pattern matching.
    settings = await db.settings.find_one(
        {"_id": "global"},
        {"_id": 0, "llm_budget_wa_query_enabled": 1, "llm_budget_notify_wa_phone": 1},
    ) or {}
    if not settings.get("llm_budget_wa_query_enabled"):
        return False
    authorized = (settings.get("llm_budget_notify_wa_phone") or "").strip()
    auth_digits = "".join(ch for ch in authorized if ch.isdigit())
    if auth_digits and (from_digits or "")[-10:] != auth_digits[-10:]:
        return False

    # 1. Try static keywords
    handler_key = _resolve_static_keyword(text)
    reply: Optional[str] = None
    try:
        if handler_key == "balance":
            reply = await build_balance_text()
        elif handler_key == "stats":
            reply = await _build_stats_text(db)
        elif handler_key == "incidents":
            reply = await _build_incidents_text(db)
        elif handler_key == "help":
            reply = _help_text()
        elif handler_key == "mute":
            reply = await _mute_alerts_action(db)
        elif handler_key == "unmute":
            reply = await _unmute_alerts_action(db)
        else:
            # 2. Try parametric commands
            m = RE_CLOSE_TICKET.match(text or "")
            if m:
                reply = await _close_ticket_action(db, ticket_num=m.group(1), actor_phone="+" + from_digits)
            elif RE_NOTIF_STOP.match(text or ""):
                reply = await _mute_alerts_action(db)
            elif RE_NOTIF_ON.match(text or ""):
                reply = await _unmute_alerts_action(db)
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] failed to build reply for text=%r", text)
        return False

    if reply is None:
        return False

    try:
        await send_wa("+" + from_digits, reply)
    except Exception:  # noqa: BLE001
        logger.exception("[cockpit] send_wa failed")
    return True


__all__ = [
    "handle_wa_admin_command",
    "alerts_are_muted",
    "KEYWORDS",
    "_help_text",
]
