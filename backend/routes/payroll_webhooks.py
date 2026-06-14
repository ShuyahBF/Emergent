"""Iter38d — Payroll Webhooks (n8n integration).

Two webhooks per tenant:
  • Outbound (push to n8n): send the monthly payroll as JSON,
    line per employee. Triggered manually (button) OR by CRON on the
    1st of each month at 03:00 UTC for the previous month.
  • Inbound (receive from n8n): n8n returns processed data (net override,
    comment) per employee matricule + month. Authenticated by HMAC-SHA256
    over (timestamp + body) with anti-replay (timestamp must be within
    5 minutes of server time, and signature unique per request).

Settings stored in db.tenant_webhooks:
    {
      "tenant_id": <id>,
      "outbound_url": "https://n8n.example.com/webhook/payroll",
      "outbound_secret": "<HMAC secret>",
      "outbound_enabled": true,
      "outbound_auto_monthly": true,
      "inbound_secret": "<HMAC secret>",
      "inbound_enabled": true,
      "updated_at": "...",
    }

Audit trail: db.payroll_webhook_log
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field


log = logging.getLogger("sawali.payroll_webhooks")
REPLAY_WINDOW_SECONDS = 300  # 5 minutes


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebhookConfigPayload(BaseModel):
    outbound_url: Optional[str] = Field(None, max_length=500)
    outbound_enabled: Optional[bool] = None
    outbound_auto_monthly: Optional[bool] = None
    rotate_outbound_secret: Optional[bool] = False
    inbound_enabled: Optional[bool] = None
    rotate_inbound_secret: Optional[bool] = False


class PayrollPatchLine(BaseModel):
    matricule: str = Field(..., min_length=1)
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    net_override: Optional[float] = Field(None, ge=0)
    comment: Optional[str] = Field(None, max_length=1000)


class PayrollInboundPayload(BaseModel):
    lines: List[PayrollPatchLine] = Field(default_factory=list, max_length=500)


def _hmac_sign(secret: str, ts: str, body: bytes) -> str:
    msg = ts.encode() + b"." + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def make_router(*, db, get_current_user, get_current_admin, compute_payslip):
    """compute_payslip(user, eid, month) -> dict, injected from hr module."""
    router = APIRouter(tags=["Webhooks Paie"])

    async def _resolve_tenant_id(user: dict) -> str:
        for key in ("parent_client_id", "client_id"):
            ref = user.get(key)
            if ref and ref != user.get("id"):
                doc = await db.users.find_one({"id": ref}, {"_id": 0, "id": 1})
                if doc:
                    return doc["id"]
        company = (user.get("company") or "").strip()
        if company:
            for role_filter in (
                {"role": "admin"},
                {"role": "superviseur"},
                {"account_status": {"$ne": "deleted"}},
            ):
                canonical = await db.users.find_one(
                    {**role_filter, "company": company},
                    {"_id": 0, "id": 1},
                    sort=[("created_at", 1)],
                )
                if canonical:
                    return canonical["id"]
        return user["id"]

    async def _config(tenant_id: str) -> dict:
        return await db.tenant_webhooks.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}

    async def _log_event(tenant_id: str, direction: str, status: str, payload: dict):
        try:
            await db.payroll_webhook_log.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "direction": direction,
                "status": status,
                "payload": payload,
                "created_at": _now_iso(),
            })
        except Exception as ex:
            log.warning("Failed to log webhook event: %s", ex)

    # ----------------------------------------------------------------
    # Admin: GET / PATCH config
    # ----------------------------------------------------------------
    @router.get("/admin/payroll-webhooks/config")
    async def get_config(user: dict = Depends(get_current_admin)):
        tid = await _resolve_tenant_id(user)
        cfg = await _config(tid)
        # Don't expose full secrets — only short prefixes
        def _mask(s):
            return f"{(s or '')[:8]}…{(s or '')[-4:]}" if s else None
        return {
            "tenant_id": tid,
            "outbound_url": cfg.get("outbound_url") or "",
            "outbound_enabled": bool(cfg.get("outbound_enabled")),
            "outbound_auto_monthly": bool(cfg.get("outbound_auto_monthly")),
            "outbound_secret_preview": _mask(cfg.get("outbound_secret")),
            "outbound_secret_set": bool(cfg.get("outbound_secret")),
            "inbound_enabled": bool(cfg.get("inbound_enabled")),
            "inbound_secret_preview": _mask(cfg.get("inbound_secret")),
            "inbound_secret_set": bool(cfg.get("inbound_secret")),
            "updated_at": cfg.get("updated_at"),
        }

    @router.patch("/admin/payroll-webhooks/config")
    async def update_config(payload: WebhookConfigPayload, user: dict = Depends(get_current_admin)):
        tid = await _resolve_tenant_id(user)
        cfg = await _config(tid)
        updates: Dict[str, Any] = {"tenant_id": tid, "updated_at": _now_iso()}
        if payload.outbound_url is not None:
            updates["outbound_url"] = payload.outbound_url.strip()
        if payload.outbound_enabled is not None:
            updates["outbound_enabled"] = bool(payload.outbound_enabled)
        if payload.outbound_auto_monthly is not None:
            updates["outbound_auto_monthly"] = bool(payload.outbound_auto_monthly)
        if payload.inbound_enabled is not None:
            updates["inbound_enabled"] = bool(payload.inbound_enabled)
        new_outbound_secret = None
        new_inbound_secret = None
        if payload.rotate_outbound_secret or not cfg.get("outbound_secret"):
            new_outbound_secret = secrets.token_urlsafe(32)
            updates["outbound_secret"] = new_outbound_secret
        if payload.rotate_inbound_secret or not cfg.get("inbound_secret"):
            new_inbound_secret = secrets.token_urlsafe(32)
            updates["inbound_secret"] = new_inbound_secret
        await db.tenant_webhooks.update_one(
            {"tenant_id": tid}, {"$set": updates}, upsert=True
        )
        out = await get_config(user)  # type: ignore[arg-type]
        # When rotating, return the FULL new secret ONCE so admin can copy it
        if new_outbound_secret:
            out["new_outbound_secret"] = new_outbound_secret
        if new_inbound_secret:
            out["new_inbound_secret"] = new_inbound_secret
        return out

    # ----------------------------------------------------------------
    # Outbound — build payload + send
    # ----------------------------------------------------------------
    async def _build_outbound_payload(user: dict, month: str) -> dict:
        """Aggregate every employee's payslip into one JSON for the tenant."""
        tid = await _resolve_tenant_id(user)
        cursor = db.hr_employees.find(
            {"tenant_id": tid, "deleted_at": None}, {"_id": 0}
        )
        emps = [e async for e in cursor]
        lines = []
        for emp in emps:
            try:
                ps = await compute_payslip(user, emp["id"], month)
                lines.append({
                    "matricule": emp.get("matricule"),
                    "employee_id": emp["id"],
                    "user_id": emp.get("user_id"),
                    "full_name": emp.get("name_snapshot"),
                    "email": emp.get("email_snapshot"),
                    "job_title": emp.get("job_title"),
                    "department": emp.get("department"),
                    "currency": emp.get("currency") or "XOF",
                    "pay_type": emp.get("pay_type"),
                    "month": month,
                    "hours_worked": ps.get("hours_worked"),
                    "expected_hours": ps.get("expected_hours"),
                    "gross": ps.get("gross"),
                    "absence_deduction": ps.get("absence_deduction"),
                    "gross_after_absence": ps.get("gross_after_absence"),
                    "taxes": ps.get("taxes"),
                    "total_taxes": ps.get("total_taxes"),
                    "advances": ps.get("advances"),
                    "advances_deduction": ps.get("advances_deduction"),
                    "late_expenses_deduction": ps.get("late_expenses_deduction"),
                    "net": ps.get("net"),
                })
            except Exception as ex:
                log.warning("Failed to compute payslip for %s: %s", emp.get("id"), ex)
                continue
        return {
            "tenant_id": tid,
            "month": month,
            "generated_at": _now_iso(),
            "employee_count": len(lines),
            "lines": lines,
        }

    async def _dispatch_outbound(tenant_id: str, payload: dict) -> dict:
        cfg = await db.tenant_webhooks.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
        if not cfg.get("outbound_enabled"):
            return {"ok": False, "reason": "outbound_disabled"}
        url = cfg.get("outbound_url")
        secret = cfg.get("outbound_secret")
        if not url or not secret:
            return {"ok": False, "reason": "outbound_url_or_secret_missing"}
        body = json.dumps(payload).encode()
        ts = str(int(time.time()))
        sig = _hmac_sign(secret, ts, body)
        headers = {
            "Content-Type": "application/json",
            "X-Sawali-Timestamp": ts,
            "X-Sawali-Signature": f"sha256={sig}",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(url, content=body, headers=headers)
            status_code = r.status_code
            ok = 200 <= status_code < 300
            await _log_event(tenant_id, "outbound", "ok" if ok else "ko", {
                "month": payload.get("month"),
                "employee_count": payload.get("employee_count"),
                "http_status": status_code,
                "response": (r.text or "")[:500],
                "url": url,
            })
            return {"ok": ok, "http_status": status_code, "response": (r.text or "")[:500]}
        except Exception as ex:
            await _log_event(tenant_id, "outbound", "error", {
                "month": payload.get("month"), "error": str(ex), "url": url,
            })
            return {"ok": False, "error": str(ex)}

    @router.post("/admin/payroll-webhooks/outbound/test")
    async def trigger_outbound(month: str, user: dict = Depends(get_current_admin)):
        if not (month and len(month) == 7 and month[4] == "-"):
            raise HTTPException(status_code=400, detail="Format mois: YYYY-MM")
        tid = await _resolve_tenant_id(user)
        payload = await _build_outbound_payload(user, month)
        result = await _dispatch_outbound(tid, payload)
        return {"month": month, "payload_size": len(payload.get("lines", [])), "dispatch": result}

    @router.get("/admin/payroll-webhooks/outbound/preview")
    async def preview_outbound(month: str, user: dict = Depends(get_current_admin)):
        """Renvoie le JSON qui serait envoyé — utile pour revue avant expédition."""
        if not (month and len(month) == 7 and month[4] == "-"):
            raise HTTPException(status_code=400, detail="Format mois: YYYY-MM")
        return await _build_outbound_payload(user, month)

    # ----------------------------------------------------------------
    # Inbound — receive payroll patches from n8n (HMAC + anti-replay)
    # ----------------------------------------------------------------
    @router.post("/webhooks/n8n/payroll/{tenant_id}")
    async def receive_inbound(tenant_id: str, request: Request):
        cfg = await db.tenant_webhooks.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
        if not cfg.get("inbound_enabled"):
            await _log_event(tenant_id, "inbound", "disabled", {})
            raise HTTPException(status_code=403, detail="Inbound webhook disabled")
        secret = cfg.get("inbound_secret")
        if not secret:
            raise HTTPException(status_code=500, detail="Inbound secret not configured")
        ts = request.headers.get("X-Sawali-Timestamp") or ""
        sig_header = request.headers.get("X-Sawali-Signature") or ""
        # Anti-replay
        try:
            ts_int = int(ts)
        except (TypeError, ValueError):
            await _log_event(tenant_id, "inbound", "bad_ts", {"ts": ts})
            raise HTTPException(status_code=401, detail="Invalid timestamp")
        now = int(time.time())
        if abs(now - ts_int) > REPLAY_WINDOW_SECONDS:
            await _log_event(tenant_id, "inbound", "expired", {"ts": ts, "now": now})
            raise HTTPException(status_code=401, detail="Timestamp outside the 5-minute window")
        body = await request.body()
        expected = _hmac_sign(secret, ts, body)
        provided = sig_header.split("=", 1)[-1] if "=" in sig_header else sig_header
        if not hmac.compare_digest(expected, provided):
            await _log_event(tenant_id, "inbound", "bad_sig", {"ts": ts})
            raise HTTPException(status_code=401, detail="Invalid signature")
        # Anti-replay: ensure this signature wasn't already processed
        already = await db.payroll_webhook_seen.find_one({"sig": provided, "tenant_id": tenant_id})
        if already:
            await _log_event(tenant_id, "inbound", "replay", {"sig_prefix": provided[:12]})
            raise HTTPException(status_code=409, detail="Replay detected")
        # Parse JSON
        try:
            raw = json.loads(body.decode())
            payload = PayrollInboundPayload.model_validate(raw)
        except Exception as ex:
            await _log_event(tenant_id, "inbound", "bad_body", {"error": str(ex)})
            raise HTTPException(status_code=400, detail=f"Invalid payload: {ex}")
        # Apply patches per (matricule, month) into db.payroll_overrides
        applied = 0
        not_found = []
        for line in payload.lines:
            emp = await db.hr_employees.find_one(
                {"tenant_id": tenant_id, "matricule": line.matricule, "deleted_at": None},
                {"_id": 0, "id": 1, "matricule": 1},
            )
            if not emp:
                not_found.append(line.matricule)
                continue
            await db.payroll_overrides.update_one(
                {"tenant_id": tenant_id, "employee_id": emp["id"], "month": line.month},
                {"$set": {
                    "tenant_id": tenant_id,
                    "employee_id": emp["id"],
                    "matricule": line.matricule,
                    "month": line.month,
                    "net_override": line.net_override,
                    "comment": line.comment,
                    "updated_at": _now_iso(),
                    "source": "n8n_webhook",
                }},
                upsert=True,
            )
            applied += 1
        # Mark this signature as seen (TTL 1 hour)
        await db.payroll_webhook_seen.insert_one({
            "sig": provided, "tenant_id": tenant_id,
            "created_at": datetime.now(timezone.utc),
        })
        await _log_event(tenant_id, "inbound", "applied", {
            "applied": applied, "not_found": not_found[:20],
        })
        return {"ok": True, "applied": applied, "not_found": not_found}

    # ----------------------------------------------------------------
    # Audit log
    # ----------------------------------------------------------------
    @router.get("/admin/payroll-webhooks/log")
    async def list_log(limit: int = 50, user: dict = Depends(get_current_admin)):
        tid = await _resolve_tenant_id(user)
        cursor = (
            db.payroll_webhook_log.find({"tenant_id": tid}, {"_id": 0})
            .sort("created_at", -1).limit(max(1, min(limit, 500)))
        )
        return [r async for r in cursor]

    # ----------------------------------------------------------------
    # Helpers exposed to scheduler
    # ----------------------------------------------------------------
    async def _scheduled_auto_dispatch():
        """Runs daily; on the 1st of the month, dispatch previous month
        outbound webhook for every tenant that opted in (outbound_auto_monthly)."""
        now = datetime.now(timezone.utc)
        if now.day != 1:
            return {"skipped": True, "reason": "not_first_of_month"}
        # Previous month
        if now.month == 1:
            month = f"{now.year - 1}-12"
        else:
            month = f"{now.year}-{(now.month - 1):02d}"
        cursor = db.tenant_webhooks.find(
            {"outbound_enabled": True, "outbound_auto_monthly": True}, {"_id": 0}
        )
        results = []
        async for cfg in cursor:
            tid = cfg.get("tenant_id")
            if not tid:
                continue
            owner = await db.users.find_one({"id": tid}, {"_id": 0})
            if not owner:
                continue
            try:
                payload = await _build_outbound_payload(owner, month)
                disp = await _dispatch_outbound(tid, payload)
                results.append({"tenant_id": tid, "month": month, "ok": disp.get("ok")})
            except Exception as ex:
                results.append({"tenant_id": tid, "month": month, "error": str(ex)})
        return {"month": month, "results": results}

    router._scheduled_auto_dispatch = _scheduled_auto_dispatch  # type: ignore[attr-defined]
    return router


__all__ = ["make_router"]
