"""Iter41 Phase 3 (2026-02) — Synthèse Liluvine programmée

Two entry points :
  1. **Scheduled cron** (registered by `server.py` APScheduler) at the
     `synthese_hour` configured in AdminSettings. Generates the daily synthèse
     and dispatches to email + WhatsApp depending on `synthese_channels`.
  2. **WhatsApp command** `!synthese [début] [fin]` — manual on-demand
     synthèse for a date range (default = today).

Date parsing accepts (case-insensitive) :
  - ISO (`AAAA-MM-JJ`)
  - French (`JJ/MM/AAAA`)
  - Keywords : `aujourd'hui`, `hier`, `semaine`, `mois`
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.synthese")


SYNTHESE_CMD_RE = re.compile(r"^[!/]\s*synth[èe]se(?:\s+(.+))?\s*$", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Date parsing
# --------------------------------------------------------------------------- #
def _parse_date_token(token: str, fallback: date) -> date:
    """Parse a single date token. Returns `fallback` on any failure."""
    if not token:
        return fallback
    t = token.strip().lower()
    today = date.today()
    if t in ("aujourd'hui", "aujourdhui", "today"):
        return today
    if t in ("hier", "yesterday"):
        return today - timedelta(days=1)
    if t in ("semaine", "week"):
        return today - timedelta(days=7)
    if t in ("mois", "month"):
        return today - timedelta(days=30)
    # ISO YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return fallback
    # French JJ/MM/AAAA
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return fallback
    return fallback


def parse_synthese_args(arg_string: str) -> Tuple[date, date]:
    """Parse `[début] [fin]` arguments. Returns (start, end) — both
    default to today when missing/invalid."""
    today = date.today()
    if not arg_string:
        return today, today
    parts = arg_string.strip().split()
    if len(parts) == 1:
        d = _parse_date_token(parts[0], today)
        return d, d
    start = _parse_date_token(parts[0], today)
    end = _parse_date_token(parts[1], start)
    if end < start:
        start, end = end, start
    return start, end


# --------------------------------------------------------------------------- #
# Context builder (hybrid : prompt + structured KPIs)
# --------------------------------------------------------------------------- #
async def _gather_kpis(db, scope_uid: str, start: date, end: date) -> Dict[str, Any]:
    """Aggregate a small structured snapshot of the activity for the given
    date range. Designed to be cheap (single-tenant scope, count_documents)."""
    start_iso = start.isoformat()
    end_iso = (end + timedelta(days=1)).isoformat()  # exclusive upper bound
    kpi: Dict[str, Any] = {"period": {"start": start_iso, "end": end_iso}}

    async def _count(col: str, query: Dict[str, Any]) -> int:
        try:
            return await db[col].count_documents(query)
        except Exception:  # noqa: BLE001
            return 0

    # Common date filter on created_at strings
    drange = {"created_at": {"$gte": start_iso, "$lt": end_iso}}
    tenant_filter = {"client_id": scope_uid} if scope_uid else {}
    full = {**tenant_filter, **drange}

    kpi["counts"] = {
        "new_contacts": await _count("directory_contacts", full),
        "new_tickets": await _count("tickets", {**tenant_filter, "created_at": drange["created_at"]}),
        "appointments": await _count("appointments", full),
        "rapports": await _count("rapports", full),
        "suivis": await _count("suivis", full),
        "sms_sent": await _count("sms_outbox", full),
        "wa_sent": await _count("wa_outbox", full),
        "invoices": await _count("invoices", full),
        "payments": await _count("payments", full),
    }
    # Last 5 tickets summary
    try:
        cursor = db.tickets.find({**tenant_filter, "created_at": drange["created_at"]}, {"_id": 0}).sort("created_at", -1).limit(5)
        tickets = []
        async for t in cursor:
            tickets.append({"id": t.get("id"), "title": t.get("title") or t.get("motif"), "status": t.get("status"), "created_at": t.get("created_at")})
        kpi["recent_tickets"] = tickets
    except Exception:  # noqa: BLE001
        kpi["recent_tickets"] = []
    return kpi


def _build_prompt(custom_prompt: str, kpis: Dict[str, Any], start: date, end: date) -> str:
    """Combine the user's custom prompt with the structured KPI block."""
    base = custom_prompt or (
        "Tu es Liluvine. Synthétise l'activité de l'établissement sur la période "
        "indiquée en 5-8 puces actionnables. Mets en gras les points critiques."
    )
    period_label = f"du {start.isoformat()} au {end.isoformat()}" if start != end else f"le {start.isoformat()}"
    return (
        f"{base}\n\n"
        f"[CONTEXTE STRUCTURÉ — {period_label}]\n"
        f"{kpis}\n"
        f"[FIN CONTEXTE]\n\n"
        f"Génère la synthèse en français."
    )


async def _call_liluvine(db, full_prompt: str) -> str:
    """Send the synthèse prompt to Liluvine and return the plain-text reply."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        import os
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            return "❌ EMERGENT_LLM_KEY absent — impossible de générer la synthèse."
        chat = (
            LlmChat(api_key=api_key, session_id="synthese-cron", system_message="Tu es Liluvine, assistante SAWALI.")
            .with_model("anthropic", "claude-sonnet-4-5-20250929")
        )
        msg = UserMessage(text=full_prompt)
        reply = await chat.send_message(msg)
        return str(reply)[:5000]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[synthese] LLM call failed", exc_info=True)
        return f"❌ Erreur génération synthèse : {str(exc)[:200]}"


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #
async def build_synthese(db, *, start: date, end: date, scope_uid: Optional[str] = None) -> str:
    """Generate a synthèse text for the given period. Used by both the cron
    and the WhatsApp command."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "synthese_prompt": 1}) or {}
    kpis = await _gather_kpis(db, scope_uid or "", start, end)
    prompt = _build_prompt(s.get("synthese_prompt") or "", kpis, start, end)
    return await _call_liluvine(db, prompt)


async def detect_and_handle_synthese_command(
    db, *, message_text: str, from_phone: str,
) -> Optional[Dict[str, Any]]:
    """Returns None if not a !synthese command, otherwise {ok, user_reply}."""
    m = SYNTHESE_CMD_RE.match(message_text or "")
    if not m:
        return None
    args = (m.group(1) or "").strip()
    start, end = parse_synthese_args(args)
    text = await build_synthese(db, start=start, end=end)
    period = f"{start.isoformat()} → {end.isoformat()}" if start != end else start.isoformat()
    return {
        "ok": True, "command": "synthese",
        "user_reply": f"📊 *Synthèse {period}*\n\n{text}",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
    }


async def _dispatch_email(db, body: str) -> bool:
    """Send the synthèse by email. Returns True on success."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    to = (s.get("synthese_email_to") or "").strip()
    if not to:
        return False
    try:
        # Reuse the platform's existing email helper if available
        from routes.email_outbox import send_email_simple  # type: ignore
        await send_email_simple(
            to=to,
            subject=f"📊 Synthèse SAWALI — {datetime.now(timezone.utc).strftime('%d/%m/%Y')}",
            html=f"<pre style='font-family:monospace;white-space:pre-wrap'>{body}</pre>",
        )
        return True
    except Exception:  # noqa: BLE001
        logger.warning("[synthese] email dispatch failed", exc_info=True)
        return False


async def _dispatch_wa(db, body: str) -> bool:
    """Send the synthèse over WhatsApp to the configured number."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    to = (s.get("synthese_wa_to") or "").strip()
    if not to:
        return False
    try:
        # Use the bare-bones WA sender exposed by server.py
        import importlib
        srv = importlib.import_module("server")
        send = getattr(srv, "_wa_send_text", None)
        if not send:
            return False
        await send(to, body[:4000])  # WA caps around 4096 chars
        return True
    except Exception:  # noqa: BLE001
        logger.warning("[synthese] WA dispatch failed", exc_info=True)
        return False


async def run_scheduled_synthese(db) -> Dict[str, Any]:
    """Top-level cron — checks enabled flag and dispatches. Idempotent."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    if not s.get("synthese_enabled"):
        return {"skipped": True, "reason": "synthese disabled"}
    channels = (s.get("synthese_channels") or "both").lower()
    today = date.today()
    body = await build_synthese(db, start=today, end=today)
    sent_email = False
    sent_wa = False
    if channels in ("email", "both"):
        sent_email = await _dispatch_email(db, body)
    if channels in ("wa", "both"):
        sent_wa = await _dispatch_wa(db, body)
    return {
        "ok": True,
        "channels": channels,
        "sent_email": sent_email,
        "sent_wa": sent_wa,
        "preview": body[:300],
    }
