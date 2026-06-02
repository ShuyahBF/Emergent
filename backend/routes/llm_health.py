"""S031 — LLM health monitoring & budget-exceeded banner.

Workflow:
  1. Every LLM call wrapped via `record_llm_outcome(...)` updates the
     `llm_health_state` collection (single doc, _id="current") with status:
       - "ok"             → most recent call succeeded
       - "budget_exceeded"→ an Emergent "Budget has been exceeded" error
       - "key_missing"    → EMERGENT_LLM_KEY env missing
       - "unknown_error"  → any other LLM exception
  2. A scheduled background task pings Claude Haiku 4.5 every 15 min with a
     1-token completion to detect recovery (after recharge) without waiting
     for the next real user message.
  3. `/api/admin/llm-health` returns the current state (admin/sup only).
  4. Frontend banner polls this endpoint every 60 s and renders for the
     super-admin only (`admin@sawalismartsystems.com`).
  5. While down: a daily email is sent to the super-admin reminding them to
     recharge — at most once per 23 h.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger("sawali.llm_health")

SUPER_ADMIN_EMAIL = "admin@sawalismartsystems.com"
BUDGET_ERROR_RE = re.compile(r"budget\s+(?:has\s+been\s+)?exceeded.*current\s+cost[:\s]+([0-9.]+).*max\s+budget[:\s]+([0-9.]+)", re.IGNORECASE | re.DOTALL)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def record_llm_outcome(db, *, ok: bool, error: Optional[str] = None) -> None:
    """Persist the latest LLM call outcome. Call this from every LLM
    wrapper after success or failure."""
    now = _now_iso()
    update = {"last_checked_at": now}
    if ok:
        update.update({"status": "ok", "last_error_message": None})
    else:
        msg = (error or "")[:600]
        update["last_error_message"] = msg
        m = BUDGET_ERROR_RE.search(msg)
        if m:
            try:
                update["current_cost"] = float(m.group(1))
                update["max_budget"] = float(m.group(2))
            except ValueError:
                pass
            update["status"] = "budget_exceeded"
        elif "EMERGENT_LLM_KEY missing" in msg or "llm_key_missing" in msg:
            update["status"] = "key_missing"
        else:
            update["status"] = "unknown_error"
    try:
        await db.llm_health_state.update_one(
            {"_id": "current"}, {"$set": update}, upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[llm_health] failed to persist outcome")


async def ping_emergent_llm(db) -> dict:
    """1-token health probe. Records outcome via record_llm_outcome and
    returns the resulting state doc."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        await record_llm_outcome(db, ok=False, error="EMERGENT_LLM_KEY missing")
    else:
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=api_key,
                session_id="health-probe",
                system_message="Réponds en 1 mot.",
            ).with_model("anthropic", "claude-haiku-4-5-20251001")
            r = await chat.send_message(UserMessage(text="ok"))
            if r:
                await record_llm_outcome(db, ok=True)
            else:
                await record_llm_outcome(db, ok=False, error="empty_reply")
        except Exception as exc:  # noqa: BLE001
            await record_llm_outcome(db, ok=False, error=str(exc))
    state = await db.llm_health_state.find_one({"_id": "current"}, {"_id": 0}) or {}
    return state


def make_router(*, db, get_current_user, send_email):
    router = APIRouter(prefix="/admin/llm-health", tags=["Admin"])

    def _is_super(user: dict) -> bool:
        return (user.get("email") or "").lower() == SUPER_ADMIN_EMAIL

    def _is_admin_or_sup(user: dict) -> bool:
        return user.get("role") in ("admin", "superviseur") \
            or user.get("tracked_role") in ("Administrateur", "Superviseur")

    @router.get("")
    async def get_state(user: dict = Depends(get_current_user)):
        """Admin/Superviseur can read the state. The frontend banner uses an
        additional client-side filter so it only renders for the super-admin."""
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        state = await db.llm_health_state.find_one({"_id": "current"}, {"_id": 0}) or {
            "status": "unknown",
            "last_checked_at": None,
            "last_error_message": None,
        }
        state["is_super_admin"] = _is_super(user)
        return state

    @router.post("/ping")
    async def manual_ping(user: dict = Depends(get_current_user)):
        """Force a fresh health probe (admin button)."""
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        state = await ping_emergent_llm(db)
        state["is_super_admin"] = _is_super(user)
        return state

    return router


async def maybe_send_budget_alert_email(db, send_email) -> bool:
    """Send a daily reminder to the super-admin while the key is down.
    Throttled to at most one email per 23 h."""
    state = await db.llm_health_state.find_one({"_id": "current"}, {"_id": 0}) or {}
    if state.get("status") != "budget_exceeded":
        return False
    last_sent = state.get("last_alert_email_at")
    if last_sent:
        try:
            ts = datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - ts < timedelta(hours=23):
                return False
        except (TypeError, ValueError):
            pass
    current = state.get("current_cost", "?")
    maxb = state.get("max_budget", "?")
    body = (
        f"<h2>⚠️ Universal Key Emergent épuisée</h2>"
        f"<p>L'application Loois n'arrive plus à appeler les modèles IA (Liluvine PRO, "
        f"auto-réponse WhatsApp, OCR KB, AI Campaign Planner, Plan IA).</p>"
        f"<p><strong>Solde courant :</strong> {current} / {maxb} USD</p>"
        f"<p><strong>Pour rétablir le service :</strong></p>"
        f"<ol>"
        f"<li>Connectez-vous à la plateforme Emergent</li>"
        f"<li>Allez dans <strong>Profile → Universal Key</strong></li>"
        f"<li>Cliquez sur <strong>Add Balance</strong> (ou activez <em>Auto top-up</em>)</li>"
        f"</ol>"
        f"<p>Le service redémarre automatiquement dès la recharge — aucun redéploiement nécessaire.</p>"
        f"<p style='color:#64748b;font-size:.85rem'>— SAWALI Smart Systems · Monitoring S031</p>"
    )
    try:
        ok = await send_email(
            to_email=SUPER_ADMIN_EMAIL,
            subject="⚠️ Universal Key Emergent épuisée — Liluvine PRO indisponible",
            html_body=body,
            text_body=re.sub(r"<[^>]+>", "", body),
        )
        if ok:
            await db.llm_health_state.update_one(
                {"_id": "current"},
                {"$set": {"last_alert_email_at": _now_iso()}},
            )
            return True
    except Exception:  # noqa: BLE001
        logger.exception("[llm_health] daily alert email failed")
    return False


__all__ = ["make_router", "record_llm_outcome", "ping_emergent_llm", "maybe_send_budget_alert_email", "SUPER_ADMIN_EMAIL"]
