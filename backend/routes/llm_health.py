"""S031 + S032 — LLM health monitoring, budget-exceeded banner & burn-rate alerts.

S031 — Banner alert when the Emergent Universal Key is exhausted.
S032 — Track 24h consumption speed, project exhaustion date, and alert the
       admin via email + WhatsApp when reaching `warning_pct` / `critical_pct`
       thresholds, well before the hard exhaustion limit.

Workflow:
  1. Every LLM call wrapped via `record_llm_outcome(...)` updates the
     `llm_health_state` collection (single doc, _id="current") with status:
       - "ok"             → most recent call succeeded
       - "budget_exceeded"→ an Emergent "Budget has been exceeded" error
       - "key_missing"    → EMERGENT_LLM_KEY env missing
       - "unknown_error"  → any other LLM exception
     AND appends one entry to `llm_usage_log` (S032 — burn-rate source).
  2. A scheduled background task pings Claude Haiku 4.5 every 15 min with a
     1-token completion to detect recovery (after recharge) without waiting
     for the next real user message.
  3. `/api/admin/llm-health` returns the current state PLUS computed S032
     metrics (burn rate, % used, projected exhaustion date, status_level).
  4. Frontend banner polls this endpoint every 60 s and renders for the
     super-admin only (`admin@sawalismartsystems.com`), with 4 visual states:
     ok (hidden) | warning (amber) | critical (orange) | exhausted (rose).
  5. While the budget is exhausted: daily email reminder (S031, 23h throttle).
  6. While in warning/critical levels: daily email + WhatsApp alert to the
     super-admin (S032, 23h throttle per level).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Awaitable, Any, Dict

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger("sawali.llm_health")

SUPER_ADMIN_EMAIL = "admin@sawalismartsystems.com"
BUDGET_ERROR_RE = re.compile(r"budget\s+(?:has\s+been\s+)?exceeded.*current\s+cost[:\s]+([0-9.]+).*max\s+budget[:\s]+([0-9.]+)", re.IGNORECASE | re.DOTALL)

# S032 — Per-context estimated cost (USD) for Claude Haiku 4.5
# Anthropic pricing: $1/M input + $5/M output tokens. Numbers below assume
# typical message lengths observed in production. Override per-call via the
# `estimated_cost_usd` kwarg of `record_llm_outcome` if you have a finer count.
LLM_COST_ESTIMATES = {
    "liluvine_chat": 0.004,
    "liluvine_wa_autoreply": 0.002,
    "kb_enrich": 0.007,
    "kb_ocr": 0.005,
    "campaign_plan": 0.005,
    "ai_media": 0.010,
    "health_probe": 0.0001,
    "default": 0.002,
}

# S032 — Defaults (overridable via /admin/settings)
DEFAULT_WARNING_PCT = 80
DEFAULT_CRITICAL_PCT = 95
DEFAULT_MAX_BUDGET_USD = 3.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def record_llm_outcome(
    db,
    *,
    ok: bool,
    error: Optional[str] = None,
    context: str = "default",
    estimated_cost_usd: Optional[float] = None,
) -> None:
    """Persist the latest LLM call outcome and append a row to the
    `llm_usage_log` collection (S032 burn-rate source)."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    update = {"last_checked_at": now}
    unset_stale = None
    if ok:
        update.update({"status": "ok", "last_error_message": None})
        # Iter43-fix (2026-03) — Effacer les `current_cost` / `max_budget`
        # capturés depuis une ancienne erreur Emergent « Budget exceeded »,
        # sinon le banner reste bloqué à 100% après une recharge tant que les
        # valeurs locales du cumul mensuel sont inférieures à la valeur stale.
        unset_stale = {"current_cost": "", "max_budget": ""}
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
        ops: Dict[str, Any] = {"$set": update}
        if unset_stale:
            ops["$unset"] = unset_stale
        await db.llm_health_state.update_one(
            {"_id": "current"}, ops, upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[llm_health] failed to persist outcome")

    # S032 — log usage entry (only for successful calls + the lightweight
    # health probe; failed real calls don't bill cost on Emergent side either).
    if ok or context == "health_probe":
        cost = estimated_cost_usd if estimated_cost_usd is not None else LLM_COST_ESTIMATES.get(context, LLM_COST_ESTIMATES["default"])
        try:
            await db.llm_usage_log.insert_one({
                "ts": now_dt,
                "context": context,
                "estimated_cost_usd": float(cost),
                "ok": bool(ok),
                "month_bucket": now_dt.strftime("%Y-%m"),
            })
        except Exception:  # noqa: BLE001
            logger.exception("[llm_health] failed to log usage")


async def ping_emergent_llm(db) -> dict:
    """1-token health probe. Records outcome via record_llm_outcome and
    returns the resulting state doc."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        await record_llm_outcome(db, ok=False, error="EMERGENT_LLM_KEY missing", context="health_probe")
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
                await record_llm_outcome(db, ok=True, context="health_probe")
            else:
                await record_llm_outcome(db, ok=False, error="empty_reply", context="health_probe")
        except Exception as exc:  # noqa: BLE001
            await record_llm_outcome(db, ok=False, error=str(exc), context="health_probe")
    state = await db.llm_health_state.find_one({"_id": "current"}, {"_id": 0}) or {}
    return state


async def compute_metrics(db) -> dict:
    """S032 — Compute burn rate (24h / 1h), cumulative month spend,
    % budget used and projected exhaustion date. Returned alongside the raw
    state by /api/admin/llm-health.
    """
    now_dt = datetime.now(timezone.utc)
    state = await db.llm_health_state.find_one({"_id": "current"}, {"_id": 0}) or {}
    settings = await db.settings.find_one({"_id": "global"}) or {}

    try:
        warning_pct = int(settings.get("llm_budget_warning_pct") or DEFAULT_WARNING_PCT)
    except (TypeError, ValueError):
        warning_pct = DEFAULT_WARNING_PCT
    try:
        critical_pct = int(settings.get("llm_budget_critical_pct") or DEFAULT_CRITICAL_PCT)
    except (TypeError, ValueError):
        critical_pct = DEFAULT_CRITICAL_PCT
    try:
        configured_max = float(settings.get("llm_budget_max_usd") or DEFAULT_MAX_BUDGET_USD)
    except (TypeError, ValueError):
        configured_max = DEFAULT_MAX_BUDGET_USD

    since_24h = now_dt - timedelta(hours=24)
    since_1h = now_dt - timedelta(hours=1)

    async def _sum(match: dict) -> tuple[float, int]:
        pipeline = [
            {"$match": match},
            {"$group": {"_id": None, "sum": {"$sum": "$estimated_cost_usd"}, "count": {"$sum": 1}}},
        ]
        try:
            rows = await db.llm_usage_log.aggregate(pipeline).to_list(length=1)
            if rows:
                return float(rows[0].get("sum") or 0.0), int(rows[0].get("count") or 0)
        except Exception:  # noqa: BLE001
            logger.exception("[llm_health] usage aggregation failed")
        return 0.0, 0

    burn_24h, calls_24h = await _sum({"ts": {"$gte": since_24h}})
    burn_1h, _ = await _sum({"ts": {"$gte": since_1h}})
    cumulative_month, calls_month = await _sum({"month_bucket": now_dt.strftime("%Y-%m")})

    emergent_cost = state.get("current_cost")
    emergent_max = state.get("max_budget")
    if emergent_max and emergent_max > 0:
        max_budget = float(emergent_max)
    else:
        max_budget = configured_max
    if emergent_cost is not None:
        current_cost = float(emergent_cost)
        cost_source = "emergent_error"
    else:
        current_cost = cumulative_month
        cost_source = "local_estimate"

    pct_used = (current_cost / max_budget * 100.0) if max_budget > 0 else 0.0

    proj_days: Optional[float] = None
    proj_at: Optional[str] = None
    if burn_24h > 0 and max_budget > 0 and current_cost < max_budget:
        remaining = max(max_budget - current_cost, 0.0)
        proj_days = remaining / burn_24h
        proj_at = (now_dt + timedelta(days=proj_days)).isoformat()

    raw_status = state.get("status") or "unknown"
    if raw_status == "budget_exceeded":
        status_level = "exhausted"
    elif raw_status in ("key_missing", "unknown_error"):
        status_level = "error"
    elif pct_used >= critical_pct:
        status_level = "critical"
    elif pct_used >= warning_pct:
        status_level = "warning"
    else:
        status_level = "ok"

    return {
        "burn_rate_24h_usd": round(burn_24h, 4),
        "burn_rate_1h_usd": round(burn_1h, 4),
        "calls_24h": calls_24h,
        "cumulative_month_usd": round(cumulative_month, 4),
        "calls_month": calls_month,
        "current_cost_usd": round(current_cost, 4),
        "max_budget_usd": round(max_budget, 4),
        "pct_used": round(pct_used, 2),
        "projected_days_left": round(proj_days, 2) if proj_days is not None else None,
        "projected_exhaustion_at": proj_at,
        "warning_pct": warning_pct,
        "critical_pct": critical_pct,
        "status_level": status_level,
        "month_bucket": now_dt.strftime("%Y-%m"),
        "cost_source": cost_source,
    }


def make_router(*, db, get_current_user, send_email):
    router = APIRouter(prefix="/admin/llm-health", tags=["Admin"])

    def _is_super(user: dict) -> bool:
        return (user.get("email") or "").lower() == SUPER_ADMIN_EMAIL

    def _is_admin_or_sup(user: dict) -> bool:
        return user.get("role") in ("admin", "superviseur") \
            or user.get("tracked_role") in ("Administrateur", "Superviseur")

    async def _build_response(user: dict) -> dict:
        state = await db.llm_health_state.find_one({"_id": "current"}, {"_id": 0}) or {
            "status": "unknown",
            "last_checked_at": None,
            "last_error_message": None,
        }
        metrics = await compute_metrics(db)
        state.update(metrics)
        state["is_super_admin"] = _is_super(user)
        return state

    @router.get("")
    async def get_state(user: dict = Depends(get_current_user)):
        """Admin/Superviseur can read the state. The frontend banner uses an
        additional client-side filter so it only renders for the super-admin."""
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        return await _build_response(user)

    @router.post("/ping")
    async def manual_ping(user: dict = Depends(get_current_user)):
        """Force a fresh health probe (admin button)."""
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        await ping_emergent_llm(db)
        return await _build_response(user)

    @router.post("/reset-stale")
    async def reset_stale(user: dict = Depends(get_current_user)):
        """Iter43-fix (2026-03) — Efface manuellement les `current_cost` /
        `max_budget` figés par une ancienne erreur Emergent « Budget exceeded ».
        À utiliser quand le banner reste bloqué à 100% après une recharge
        et qu'aucun probe ne parvient à débloquer l'état.
        """
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        await db.llm_health_state.update_one(
            {"_id": "current"},
            {
                "$set": {"status": "ok", "last_error_message": None, "last_reset_at": _now_iso()},
                "$unset": {"current_cost": "", "max_budget": ""},
            },
            upsert=True,
        )
        # Lance aussi un probe pour valider que le LLM répond bien
        try:
            await ping_emergent_llm(db)
        except Exception:  # noqa: BLE001
            logger.exception("[llm_health] probe after reset failed")
        return await _build_response(user)

    @router.post("/test-summary")
    async def test_summary(user: dict = Depends(get_current_user)):
        """S033 — Manual budget test: forces a health probe AND returns the
        formatted human-readable summary (same text used by the WhatsApp
        keyword trigger). Used by the "Tester maintenant" button in
        /admin/settings.
        """
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        await ping_emergent_llm(db)
        summary_text = await build_budget_summary_text(db)
        resp = await _build_response(user)
        resp["summary_text"] = summary_text
        return resp

    @router.get("/usage-chart")
    async def usage_chart(days: int = 30, user: dict = Depends(get_current_user)):
        """S-iter39n — Daily consumption chart for the Universal Key.

        Aggregates `llm_usage_log` per day over the last `days` days and
        returns a list of `{date, cost_usd, calls, by_context}` entries
        suitable for a frontend bar/line chart. Backbone for the S032
        burn-rate dashboard.
        """
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        days = max(1, min(int(days or 30), 90))
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        pipeline = [
            {"$match": {"ts": {"$gte": since}}},
            {"$group": {
                "_id": {
                    "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
                    "context": "$context",
                },
                "cost": {"$sum": "$estimated_cost_usd"},
                "calls": {"$sum": 1},
            }},
            {"$sort": {"_id.day": 1}},
        ]
        try:
            rows = await db.llm_usage_log.aggregate(pipeline).to_list(length=10000)
        except Exception:  # noqa: BLE001
            rows = []
        # Build a day → totals map
        daily: dict[str, dict] = {}
        for r in rows:
            day = (r.get("_id") or {}).get("day") or "?"
            ctx = (r.get("_id") or {}).get("context") or "default"
            d = daily.setdefault(day, {"date": day, "cost_usd": 0.0, "calls": 0, "by_context": {}})
            d["cost_usd"] += float(r.get("cost") or 0.0)
            d["calls"] += int(r.get("calls") or 0)
            d["by_context"][ctx] = d["by_context"].get(ctx, 0.0) + float(r.get("cost") or 0.0)
        # Ensure all days are present (even with 0)
        series = []
        for i in range(days):
            day = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            row = daily.get(day) or {"date": day, "cost_usd": 0.0, "calls": 0, "by_context": {}}
            row["cost_usd"] = round(row["cost_usd"], 4)
            row["by_context"] = {k: round(v, 4) for k, v in row["by_context"].items()}
            series.append(row)
        total_cost = round(sum(r["cost_usd"] for r in series), 4)
        total_calls = sum(r["calls"] for r in series)
        return {
            "days": days,
            "series": series,
            "totals": {"cost_usd": total_cost, "calls": total_calls},
            "max_cost_usd": round(max((r["cost_usd"] for r in series), default=0), 4),
        }

    return router


async def maybe_send_budget_alert_email(db, send_email) -> bool:
    """S031 — Send a daily reminder to the super-admin while the key is down.
    Throttled to at most one email per 23 h. Skipped when S035 mute is on."""
    # S035 — Respect the WA cockpit mute toggle
    try:
        from routes.wa_admin_cockpit import alerts_are_muted
        if await alerts_are_muted(db):
            return False
    except Exception:  # noqa: BLE001
        pass
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


async def maybe_send_budget_warning_alerts(
    db,
    send_email,
    send_wa: Optional[Callable[[str, str], Awaitable[dict]]] = None,
) -> dict:
    """S032 — When the budget enters warning/critical zone (before exhaustion),
    notify the super-admin via Email and/or WhatsApp. Each level (warning,
    critical) is throttled to once per 23 h independently.

    Returns a dict {sent_email, sent_wa, level, skipped_reason}.
    """
    # S035 — Respect the WA cockpit mute toggle
    try:
        from routes.wa_admin_cockpit import alerts_are_muted
        if await alerts_are_muted(db):
            return {"sent_email": False, "sent_wa": False, "level": None, "skipped_reason": "muted_s035"}
    except Exception:  # noqa: BLE001
        pass
    metrics = await compute_metrics(db)
    level = metrics.get("status_level")
    if level not in ("warning", "critical"):
        return {"sent_email": False, "sent_wa": False, "level": level, "skipped_reason": "not_in_alert_zone"}

    settings = await db.settings.find_one({"_id": "global"}) or {}
    notify_email = settings.get("llm_budget_notify_email")
    if notify_email is None:
        notify_email = True
    notify_wa = settings.get("llm_budget_notify_wa")
    if notify_wa is None:
        notify_wa = True
    wa_phone = (settings.get("llm_budget_notify_wa_phone") or "").strip()

    state = await db.llm_health_state.find_one({"_id": "current"}, {"_id": 0}) or {}
    throttle_key = f"last_warning_alert_at_{level}"
    last_sent = state.get(throttle_key)
    if last_sent:
        try:
            ts = datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - ts < timedelta(hours=23):
                return {"sent_email": False, "sent_wa": False, "level": level, "skipped_reason": "throttled"}
        except (TypeError, ValueError):
            pass

    title_emoji = "🟠" if level == "critical" else "🟡"
    title_label = "CRITIQUE" if level == "critical" else "Avertissement"
    proj_days = metrics.get("projected_days_left")
    proj_label = f"~{proj_days:.1f} jours" if isinstance(proj_days, (int, float)) else "indéterminée"

    body_html = (
        f"<h2>{title_emoji} Universal Key Emergent — {title_label} ({metrics['pct_used']:.1f}% consommé)</h2>"
        f"<p>Le budget mensuel de la Universal Key approche de l'épuisement. "
        f"Une recharge anticipée évitera toute coupure de Liluvine PRO.</p>"
        f"<ul>"
        f"<li><strong>Consommation actuelle</strong> : "
        f"{metrics['current_cost_usd']:.2f} / {metrics['max_budget_usd']:.2f} USD "
        f"({metrics['pct_used']:.1f}%)</li>"
        f"<li><strong>Vitesse de consommation</strong> : "
        f"~{metrics['burn_rate_24h_usd']:.3f} USD / 24h "
        f"(~{metrics['burn_rate_1h_usd']:.4f} USD / 1h)</li>"
        f"<li><strong>Épuisement projeté</strong> : {proj_label}</li>"
        f"<li><strong>Appels IA (24h)</strong> : {metrics['calls_24h']}</li>"
        f"<li><strong>Source de coût</strong> : "
        f"{'Emergent (erreur budget précédente)' if metrics['cost_source'] == 'emergent_error' else 'Estimation locale du mois en cours'}</li>"
        f"</ul>"
        f"<p><strong>Action recommandée :</strong> Plateforme Emergent → "
        f"<em>Profile → Universal Key → Add Balance</em> (ou activez <em>Auto top-up</em>).</p>"
        f"<p style='color:#64748b;font-size:.85rem'>— SAWALI Smart Systems · Monitoring S032</p>"
    )

    sent_email = False
    sent_wa = False

    if notify_email:
        try:
            ok = await send_email(
                to_email=SUPER_ADMIN_EMAIL,
                subject=f"{title_emoji} Universal Key — {title_label} ({metrics['pct_used']:.0f}% consommé) — S032",
                html_body=body_html,
                text_body=re.sub(r"<[^>]+>", "", body_html),
            )
            sent_email = bool(ok)
        except Exception:  # noqa: BLE001
            logger.exception("[llm_health] S032 warning email failed")

    if notify_wa and wa_phone and send_wa:
        wa_text = (
            f"{title_emoji} *Universal Key — {title_label}*\n"
            f"Consommation : {metrics['current_cost_usd']:.2f} / {metrics['max_budget_usd']:.2f} USD "
            f"({metrics['pct_used']:.0f}%)\n"
            f"Vitesse : ~{metrics['burn_rate_24h_usd']:.3f} USD/24h\n"
            f"Épuisement projeté : {proj_label}\n\n"
            f"➡️ Emergent → Profile → Universal Key → Add Balance"
        )
        try:
            r = await send_wa(wa_phone, wa_text)
            sent_wa = bool(r.get("ok"))
        except Exception:  # noqa: BLE001
            logger.exception("[llm_health] S032 warning WA failed")

    if sent_email or sent_wa:
        await db.llm_health_state.update_one(
            {"_id": "current"},
            {"$set": {throttle_key: _now_iso()}},
            upsert=True,
        )

    return {"sent_email": sent_email, "sent_wa": sent_wa, "level": level, "skipped_reason": None}


__all__ = [
    "make_router",
    "record_llm_outcome",
    "ping_emergent_llm",
    "compute_metrics",
    "maybe_send_budget_alert_email",
    "maybe_send_budget_warning_alerts",
    "build_budget_summary_text",
    "handle_wa_budget_query",
    "SUPER_ADMIN_EMAIL",
    "LLM_COST_ESTIMATES",
]


async def build_budget_summary_text(db) -> str:
    """S033 — Format a human-readable WhatsApp/email summary of the current
    Universal Key state (used by the admin "Test maintenant" button and the
    inbound WA keyword trigger)."""
    metrics = await compute_metrics(db)
    state = await db.llm_health_state.find_one({"_id": "current"}, {"_id": 0}) or {}

    level = metrics.get("status_level", "ok")
    emoji = {
        "ok": "🟢",
        "warning": "🟡",
        "critical": "🟠",
        "exhausted": "🔴",
        "error": "⚠️",
    }.get(level, "❔")
    label = {
        "ok": "OK",
        "warning": "Avertissement",
        "critical": "CRITIQUE",
        "exhausted": "ÉPUISÉE",
        "error": "Erreur IA",
    }.get(level, level)

    proj_days = metrics.get("projected_days_left")
    if isinstance(proj_days, (int, float)):
        if proj_days < 1:
            proj_label = f"~{max(1, int(round(proj_days * 24)))}h"
        elif proj_days < 30:
            proj_label = f"~{proj_days:.1f} jours"
        else:
            proj_label = "30+ jours"
    else:
        proj_label = "indéterminée"

    src = "Emergent (vérité terrain)" if metrics.get("cost_source") == "emergent_error" else "Estimation locale"
    raw_status = state.get("status", "unknown")
    last_check = state.get("last_checked_at") or "—"

    return (
        f"{emoji} *Universal Key Emergent — {label}*\n"
        f"\n"
        f"💰 Consommation : *{metrics['current_cost_usd']:.2f} / {metrics['max_budget_usd']:.2f} USD* "
        f"({metrics['pct_used']:.1f}%)\n"
        f"📈 Vitesse 24h : ~{metrics['burn_rate_24h_usd']:.4f} USD "
        f"({metrics.get('calls_24h', 0)} appels)\n"
        f"⏱️ Vitesse 1h : ~{metrics['burn_rate_1h_usd']:.4f} USD\n"
        f"📅 Épuisement projeté : *{proj_label}*\n"
        f"🎯 Seuils : warn {metrics['warning_pct']}% / crit {metrics['critical_pct']}%\n"
        f"\n"
        f"_Source coût : {src}_\n"
        f"_Statut brut : {raw_status} — dernier check : {last_check}_\n"
        f"\n"
        f"➡️ Recharge : Emergent → Profile → Universal Key → Add Balance"
    )


async def handle_wa_budget_query(db, *, text: str, from_digits: str, send_wa) -> bool:
    """S033 — If the inbound WhatsApp message matches the configured keyword
    AND comes from the authorized number, send back the budget summary and
    return True (caller must skip persisting the message + skip auto-reply).

    Otherwise return False.

    Args:
        db: motor async db
        text: inbound text body (free-form)
        from_digits: digits-only sender phone (as stored by the webhook)
        send_wa: async callable (to_e164, text) → dict
    """
    if not text or not from_digits:
        return False
    settings = await db.settings.find_one(
        {"_id": "global"},
        {"_id": 0, "llm_budget_wa_query_enabled": 1, "llm_budget_wa_query_keyword": 1, "llm_budget_notify_wa_phone": 1},
    ) or {}
    if not settings.get("llm_budget_wa_query_enabled"):
        return False
    keyword = (settings.get("llm_budget_wa_query_keyword") or "SOLDE").strip().upper()
    if not keyword:
        return False
    if text.strip().upper() != keyword:
        return False
    # Authorize either the dedicated notify phone or super admin (best effort
    # match on the last 10 digits to tolerate +/leading zeros differences).
    authorized = (settings.get("llm_budget_notify_wa_phone") or "").strip()
    auth_digits = "".join(ch for ch in authorized if ch.isdigit())
    if auth_digits:
        if from_digits[-10:] != auth_digits[-10:]:
            logger.info("[llm_health] WA budget query from %s ignored (not authorized %s)", from_digits, auth_digits)
            return False
    summary = await build_budget_summary_text(db)
    try:
        await send_wa("+" + from_digits, summary)
    except Exception:  # noqa: BLE001
        logger.exception("[llm_health] WA budget query reply failed")
    return True
