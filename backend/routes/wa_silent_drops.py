"""Iter43-fix24az-w (2026-07-22) — WhatsApp silent-drop monitoring & alerts.

Records `_wa_send_text` outcomes where Meta returned HTTP 2xx but no
`message_id` (silent drop — payload rejected by the client with no error).
Exposes admin endpoints to list/inspect drops and configure alerting.

Threshold-based alerts : when the count of drops within the configured
`window_minutes` exceeds `threshold`, an alert is sent by email + WhatsApp
to the configured admin recipients. A `cooldown_minutes` prevents alert
spam (default 60 min).

Settings are stored in `db.settings._id="global"` under keys :
  - `wa_alert_enabled` (bool, default False)
  - `wa_alert_threshold` (int, default 5)
  - `wa_alert_window_minutes` (int, default 15)
  - `wa_alert_cooldown_minutes` (int, default 60)
  - `wa_alert_emails` (list[str], recipients for email alerts)
  - `wa_alert_wa_phones` (list[str], recipients for WhatsApp alerts, E.164)
  - `wa_alert_last_sent_at` (iso str, auto-managed)

Drop records are stored in `db.wa_silent_drops` with fields :
  - id, to, chunk_index, chunk_total, chunk_length, chunk_preview,
    http_status, kind, raw (short), created_at
Records are TTL-expired after 30 days.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.wa_silent_drops")

DEFAULT_THRESHOLD = 5
DEFAULT_WINDOW_MIN = 15
DEFAULT_COOLDOWN_MIN = 60
_TTL_DAYS = 30
_MAX_LIST = 100


class WaAlertConfigUpdate(BaseModel):
    """Admin-editable alert configuration."""
    enabled: Optional[bool] = None
    threshold: Optional[int] = Field(default=None, ge=1, le=1000)
    window_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    cooldown_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    emails: Optional[List[str]] = None
    wa_phones: Optional[List[str]] = None


def _clean_phones(phones: Optional[List[str]]) -> List[str]:
    """Keep only digits (>=6 chars) — same rule as WaSilentPhonesSection."""
    if not phones:
        return []
    out = []
    for p in phones:
        digits = "".join(ch for ch in str(p) if ch.isdigit())
        if len(digits) >= 6:
            out.append(digits)
    return out


def _clean_emails(emails: Optional[List[str]]) -> List[str]:
    if not emails:
        return []
    out = []
    for e in emails:
        e = str(e).strip().lower()
        if "@" in e and "." in e.split("@", 1)[1]:
            out.append(e)
    return out


def setup_wa_silent_drops_routes(
    *,
    api,
    db,
    get_current_admin,
    send_email_fn=None,
    wa_send_text_fn=None,
):
    """Wire the wa-silent-drops endpoints + return a bound `record_and_notify`
    coroutine to be passed as `on_silent_drop` to `attach_whatsapp_helpers`."""

    async def _load_config() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "enabled": bool(s.get("wa_alert_enabled", False)),
            "threshold": int(s.get("wa_alert_threshold", DEFAULT_THRESHOLD)),
            "window_minutes": int(s.get("wa_alert_window_minutes", DEFAULT_WINDOW_MIN)),
            "cooldown_minutes": int(s.get("wa_alert_cooldown_minutes", DEFAULT_COOLDOWN_MIN)),
            "emails": s.get("wa_alert_emails") or [],
            "wa_phones": s.get("wa_alert_wa_phones") or [],
            "last_sent_at": s.get("wa_alert_last_sent_at"),
        }

    async def _ensure_ttl_index():
        try:
            await db.wa_silent_drops.create_index(
                "created_at",
                expireAfterSeconds=_TTL_DAYS * 24 * 3600,
            )
        except Exception:  # noqa: BLE001
            # Index may already exist with different options — safe to ignore.
            pass

    async def _count_recent(minutes: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        return await db.wa_silent_drops.count_documents({"created_at": {"$gte": cutoff}})

    async def record_and_notify(ctx: Dict[str, Any]) -> None:
        """Called by `_wa_send_text` on silent-drop detection. Records the
        event + (if enabled) fires an alert when the threshold is exceeded
        and the cooldown has elapsed."""
        try:
            await _ensure_ttl_index()
            doc = {
                "id": f"drop-{datetime.now(timezone.utc).timestamp():.6f}",
                "to": ctx.get("to"),
                "chunk_index": int(ctx.get("chunk_index") or 0),
                "chunk_total": int(ctx.get("chunk_total") or 1),
                "chunk_length": int(ctx.get("chunk_length") or 0),
                "chunk_preview": (ctx.get("chunk_preview") or "")[:200],
                "http_status": ctx.get("http_status"),
                "kind": ctx.get("kind") or "silent_drop_no_message_id",
                "raw": str(ctx.get("raw") or "")[:800],
                "created_at": ctx.get("at") or datetime.now(timezone.utc).isoformat(),
            }
            await db.wa_silent_drops.insert_one(doc)
        except Exception:  # noqa: BLE001
            logger.exception("[wa_silent_drops] failed to insert drop record")
            return

        # Threshold check + notification
        try:
            cfg = await _load_config()
            if not cfg["enabled"]:
                return
            recent = await _count_recent(cfg["window_minutes"])
            if recent < cfg["threshold"]:
                return
            # Cooldown
            last_sent = cfg["last_sent_at"]
            if last_sent:
                try:
                    last_dt = datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
                    elapsed_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                    if elapsed_min < cfg["cooldown_minutes"]:
                        logger.info(
                            "[wa_silent_drops] threshold met (%d>=%d) but cooldown active (%.1fm/%dm)",
                            recent, cfg["threshold"], elapsed_min, cfg["cooldown_minutes"],
                        )
                        return
                except Exception:  # noqa: BLE001
                    pass
            # Send alerts
            subject = f"[SAWALI] WhatsApp silent drops : {recent} en {cfg['window_minutes']}min"
            body = (
                f"⚠️ Alerte silent-drop WhatsApp\n\n"
                f"{recent} messages WhatsApp ont été rejetés silencieusement par Meta "
                f"(2xx sans message_id) dans les {cfg['window_minutes']} dernières minutes.\n"
                f"Seuil configuré : {cfg['threshold']}\n\n"
                f"Causes possibles : token expiré, template non approuvé, quota dépassé, "
                f"payload > 4096 chars sans découpe, format invalide.\n\n"
                f"Consultez /admin/settings → WhatsApp Silent Drops pour les 100 derniers événements."
            )
            sent_any = False
            if send_email_fn is not None:
                for email in _clean_emails(cfg["emails"]):
                    try:
                        ok = await send_email_fn(to=email, subject=subject, body=body)
                        sent_any = sent_any or bool(ok)
                    except Exception:  # noqa: BLE001
                        logger.exception("[wa_silent_drops] email alert failed for %s", email)
            if wa_send_text_fn is not None:
                for phone in _clean_phones(cfg["wa_phones"]):
                    try:
                        res = await wa_send_text_fn(f"+{phone}", body)
                        if isinstance(res, dict) and res.get("ok"):
                            sent_any = True
                    except Exception:  # noqa: BLE001
                        logger.exception("[wa_silent_drops] WA alert failed for %s", phone)
            if sent_any:
                await db.settings.update_one(
                    {"_id": "global"},
                    {"$set": {"wa_alert_last_sent_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True,
                )
                logger.warning(
                    "[wa_silent_drops] ALERT SENT — %d drops in %dm (threshold=%d)",
                    recent, cfg["window_minutes"], cfg["threshold"],
                )
        except Exception:  # noqa: BLE001
            logger.exception("[wa_silent_drops] threshold-check pipeline failed")

    # -------------------------------------------------------------------
    # Admin endpoints
    # -------------------------------------------------------------------
    @api.get("/admin/wa-silent-drops", tags=["WhatsApp"])
    async def list_drops(
        limit: int = Query(50, ge=1, le=_MAX_LIST),
        _admin: dict = Depends(get_current_admin),
    ):
        cursor = db.wa_silent_drops.find(
            {}, {"_id": 0},
        ).sort("created_at", -1).limit(limit)
        drops = [d async for d in cursor]
        return {"drops": drops, "count": len(drops)}

    @api.get("/admin/wa-silent-drops/stats", tags=["WhatsApp"])
    async def drops_stats(_admin: dict = Depends(get_current_admin)):
        cfg = await _load_config()
        stats = {
            "last_15m": await _count_recent(15),
            "last_1h": await _count_recent(60),
            "last_24h": await _count_recent(24 * 60),
            "config": cfg,
        }
        cfg_window = cfg["window_minutes"]
        stats["current_window_count"] = await _count_recent(cfg_window)
        stats["threshold_reached"] = stats["current_window_count"] >= cfg["threshold"]
        return stats

    @api.put("/admin/wa-silent-drops/config", tags=["WhatsApp"])
    async def update_config(
        payload: WaAlertConfigUpdate,
        _admin: dict = Depends(get_current_admin),
    ):
        updates: Dict[str, Any] = {}
        if payload.enabled is not None:
            updates["wa_alert_enabled"] = bool(payload.enabled)
        if payload.threshold is not None:
            updates["wa_alert_threshold"] = int(payload.threshold)
        if payload.window_minutes is not None:
            updates["wa_alert_window_minutes"] = int(payload.window_minutes)
        if payload.cooldown_minutes is not None:
            updates["wa_alert_cooldown_minutes"] = int(payload.cooldown_minutes)
        if payload.emails is not None:
            updates["wa_alert_emails"] = _clean_emails(payload.emails)
        if payload.wa_phones is not None:
            updates["wa_alert_wa_phones"] = _clean_phones(payload.wa_phones)
        if not updates:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        await db.settings.update_one({"_id": "global"}, {"$set": updates}, upsert=True)
        return await _load_config()

    @api.post("/admin/wa-silent-drops/test-alert", tags=["WhatsApp"])
    async def test_alert(_admin: dict = Depends(get_current_admin)):
        """Send a test alert to every configured recipient (bypasses threshold
        + cooldown). Returns per-recipient delivery status."""
        cfg = await _load_config()
        subject = "[SAWALI] Test — Alerte silent-drop WhatsApp"
        body = (
            "Ceci est un TEST de l'alerte silent-drop WhatsApp (aucun drop réel).\n\n"
            f"Config actuelle : seuil={cfg['threshold']}, fenêtre={cfg['window_minutes']}min, "
            f"cooldown={cfg['cooldown_minutes']}min, activé={cfg['enabled']}.\n\n"
            "Si vous recevez ce message, votre configuration est opérationnelle. ✅"
        )
        email_results = []
        for email in _clean_emails(cfg["emails"]):
            try:
                ok = await send_email_fn(to=email, subject=subject, body=body) if send_email_fn else False
                email_results.append({"email": email, "ok": bool(ok)})
            except Exception as exc:  # noqa: BLE001
                email_results.append({"email": email, "ok": False, "error": str(exc)[:200]})
        wa_results = []
        for phone in _clean_phones(cfg["wa_phones"]):
            try:
                res = await wa_send_text_fn(f"+{phone}", body) if wa_send_text_fn else {"ok": False}
                wa_results.append({"phone": phone, "ok": bool(res.get("ok")) if isinstance(res, dict) else False,
                                   "message_id": res.get("message_id") if isinstance(res, dict) else None,
                                   "error": res.get("error") if isinstance(res, dict) else None})
            except Exception as exc:  # noqa: BLE001
                wa_results.append({"phone": phone, "ok": False, "error": str(exc)[:200]})
        return {
            "config": cfg,
            "email_results": email_results,
            "wa_results": wa_results,
            "recipients_total": len(email_results) + len(wa_results),
        }

    @api.delete("/admin/wa-silent-drops", tags=["WhatsApp"])
    async def clear_drops(_admin: dict = Depends(get_current_admin)):
        """Purge all recorded drops (audit/reset)."""
        res = await db.wa_silent_drops.delete_many({})
        return {"deleted": res.deleted_count}

    logger.info("[wa_silent_drops] routes registered (list/stats/config/test-alert/clear)")
    return {"record_and_notify": record_and_notify}
