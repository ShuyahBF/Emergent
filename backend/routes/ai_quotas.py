"""Iter38r-fix5 — AI Quotas & Usage Tracking per Client Lié.

Cette route gère :
  - Configuration des quotas IA par "Client Lié" (admin parent) :
      * Mode `quota`   → caps par ressource (images / vidéos / minutes transcription / tokens chat)
      * Mode `budget`  → cap global en XOF par mois
      * Mode `off`     → pas de limitation (par défaut)
  - Tracking append-only de chaque consommation IA (collection `ai_usage_events`).
  - Rollup mensuel pour quota check rapide (collection `ai_usage_monthly`).
  - Endpoints admin pour configurer + visualiser + exporter (CSV/PDF) l'historique
    cumulé par "Utilisateur Suivi".
  - Helper public `track_ai_usage()` à appeler depuis chaque endpoint IA.

Devise par défaut : **XOF** (FCFA). Tarifs par défaut configurables dans
`settings.global` :
  - `ai_cost_image_xof` (def: 25)
  - `ai_cost_video_xof` (def: 1500)
  - `ai_cost_transcription_minute_xof` (def: 6)
  - `ai_cost_1k_tokens_xof` (def: 3)
"""
from __future__ import annotations

import csv
import io
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.ai_quotas")


# ---------------- Default tariffs (XOF) ----------------
DEFAULT_COSTS_XOF = {
    "image": 25.0,            # 1 image (Gemini Nano Banana)
    "video": 1500.0,          # 1 video (Sora 2)
    "transcription": 6.0,     # per minute (Whisper)
    "chat": 3.0,              # per 1k tokens (Claude/GPT)
}

# Resource → base unit label (for CSV/PDF exports)
RESOURCE_BASE_LABEL = {
    "image": "images",
    "video": "vidéos",
    "transcription": "minutes",
    "chat": "tokens",
}

# Resource → human label
RESOURCE_FR = {
    "image": "Image",
    "video": "Vidéo",
    "transcription": "Transcription",
    "chat": "Chat IA",
}


# ============================================================
# Pydantic models
# ============================================================
class QuotaConfig(BaseModel):
    mode: Literal["off", "quota", "budget"] = "off"
    currency: str = "XOF"
    # Quota mode
    monthly_images: Optional[int] = Field(None, ge=0)
    monthly_videos: Optional[int] = Field(None, ge=0)
    monthly_transcription_minutes: Optional[float] = Field(None, ge=0)
    monthly_chat_tokens: Optional[int] = Field(None, ge=0)
    # Budget mode
    monthly_budget_xof: Optional[float] = Field(None, ge=0)
    # Alerts
    alert_warn_pct: int = Field(80, ge=1, le=99)
    block_on_limit: bool = True
    # Cost overrides (None = use global defaults)
    cost_per_image_xof: Optional[float] = Field(None, ge=0)
    cost_per_video_xof: Optional[float] = Field(None, ge=0)
    cost_per_transcription_minute_xof: Optional[float] = Field(None, ge=0)
    cost_per_1k_tokens_xof: Optional[float] = Field(None, ge=0)


# ============================================================
# Helpers (importable from server.py)
# ============================================================
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _year_month(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    return f"{d.year:04d}-{d.month:02d}"


async def _load_costs(db, client_id: str) -> Dict[str, float]:
    """Effective per-unit cost in XOF, applying per-client overrides on top
    of global settings, falling back to hard defaults."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    cfg = await db.ai_quotas.find_one({"client_id": client_id}, {"_id": 0}) or {}

    def _pick(key_cfg: str, key_glob: str, default: float) -> float:
        v = cfg.get(key_cfg)
        if v is not None:
            return float(v)
        v = s.get(key_glob)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return default

    return {
        "image": _pick("cost_per_image_xof", "ai_cost_image_xof", DEFAULT_COSTS_XOF["image"]),
        "video": _pick("cost_per_video_xof", "ai_cost_video_xof", DEFAULT_COSTS_XOF["video"]),
        "transcription": _pick(
            "cost_per_transcription_minute_xof",
            "ai_cost_transcription_minute_xof",
            DEFAULT_COSTS_XOF["transcription"],
        ),
        "chat": _pick("cost_per_1k_tokens_xof", "ai_cost_1k_tokens_xof", DEFAULT_COSTS_XOF["chat"]),
    }


def _estimate_cost_xof(resource: str, units: float, costs: Dict[str, float]) -> float:
    """Convert a resource consumption (units) into an XOF cost."""
    cost_per_unit = costs.get(resource, 0.0)
    if resource == "chat":
        # `units` is the token count; cost is per 1k tokens.
        return round((units / 1000.0) * cost_per_unit, 2)
    return round(units * cost_per_unit, 2)


async def _get_rollup(db, client_id: str, ym: Optional[str] = None) -> Dict[str, Any]:
    ym = ym or _year_month()
    doc = await db.ai_usage_monthly.find_one({"_id": f"{client_id}:{ym}"}, {"_id": 0})
    if not doc:
        return {
            "client_id": client_id, "year_month": ym,
            "images": 0, "videos": 0, "transcription_minutes": 0.0,
            "chat_tokens": 0, "total_xof": 0.0,
        }
    return doc


async def _quota_status(db, client_id: str) -> Dict[str, Any]:
    """Returns (config + current usage + warn/block flags) for this month."""
    cfg = await db.ai_quotas.find_one({"client_id": client_id}, {"_id": 0}) or {}
    mode = cfg.get("mode") or "off"
    rollup = await _get_rollup(db, client_id)
    warn_pct = int(cfg.get("alert_warn_pct") or 80)
    status: Dict[str, Any] = {
        "mode": mode,
        "config": cfg,
        "usage": rollup,
        "limits": {},     # resource → {used, limit, pct, warn, blocked}
        "budget": None,   # mode=budget only
        "any_warn": False,
        "any_blocked": False,
    }
    if mode == "off":
        return status
    if mode == "quota":
        pairs = [
            ("image", "monthly_images", "images"),
            ("video", "monthly_videos", "videos"),
            ("transcription", "monthly_transcription_minutes", "transcription_minutes"),
            ("chat", "monthly_chat_tokens", "chat_tokens"),
        ]
        for res, cap_key, used_key in pairs:
            cap = cfg.get(cap_key)
            used = rollup.get(used_key, 0)
            if cap is None or cap <= 0:
                status["limits"][res] = {"used": used, "limit": None, "pct": 0, "warn": False, "blocked": False}
                continue
            pct = round((used / cap) * 100, 1) if cap else 0
            warn = pct >= warn_pct
            blocked = used >= cap
            status["limits"][res] = {
                "used": used, "limit": cap, "pct": pct,
                "warn": warn, "blocked": blocked,
            }
            if warn: status["any_warn"] = True
            if blocked: status["any_blocked"] = True
    elif mode == "budget":
        cap = cfg.get("monthly_budget_xof")
        used = rollup.get("total_xof", 0.0)
        pct = round((used / cap) * 100, 1) if cap else 0
        status["budget"] = {
            "limit_xof": cap, "used_xof": used, "pct": pct,
            "warn": cap and pct >= warn_pct,
            "blocked": cap and used >= cap,
        }
        if status["budget"]["warn"]: status["any_warn"] = True
        if status["budget"]["blocked"]: status["any_blocked"] = True
    return status


async def _resolve_tracked_admin(db, user: dict) -> str:
    """Find the 'Client Lié' (parent admin) for this user. Admins/sups are
    their own client. Tracked users inherit from `tracked_user_id`."""
    if user.get("role") in ("admin", "superviseur"):
        return user["id"]
    return user.get("tracked_user_id") or user.get("client_id") or user["id"]


async def track_ai_usage(
    db,
    *,
    user: dict,
    resource: str,
    units: float,
    model: str,
    metadata: Optional[Dict[str, Any]] = None,
    pre_check: bool = False,
) -> Dict[str, Any]:
    """Append a usage event AND increment the monthly rollup.

    Renvoie :
      {
        "allowed": bool,         # False only when block_on_limit AND already over
        "reason": str | None,    # human-readable blocking reason
        "warn": bool,            # true if this consumption crossed the warn threshold
        "cost_xof": float,
        "rollup": {...},
      }

    Call this BEFORE the AI call (pre_check=True, units=expected) to abort
    early when the user would exceed the cap, AND AFTER the call to log the
    actual consumption (pre_check=False).
    """
    client_id = await _resolve_tracked_admin(db, user)
    costs = await _load_costs(db, client_id)
    cost_xof = _estimate_cost_xof(resource, units, costs)
    status_before = await _quota_status(db, client_id)
    cfg = status_before["config"]
    mode = status_before["mode"]
    blocked = False
    reason = None
    if mode != "off" and cfg.get("block_on_limit", True):
        # Project what the usage WOULD be after this consumption
        rollup = status_before["usage"]
        proj = dict(rollup)
        if resource == "image":         proj["images"] = (proj.get("images") or 0) + units
        elif resource == "video":       proj["videos"] = (proj.get("videos") or 0) + units
        elif resource == "transcription": proj["transcription_minutes"] = (proj.get("transcription_minutes") or 0) + units
        elif resource == "chat":        proj["chat_tokens"] = (proj.get("chat_tokens") or 0) + units
        proj["total_xof"] = (proj.get("total_xof") or 0) + cost_xof
        if mode == "quota":
            cap_key = {"image": "monthly_images", "video": "monthly_videos",
                       "transcription": "monthly_transcription_minutes",
                       "chat": "monthly_chat_tokens"}[resource]
            used_key = {"image": "images", "video": "videos",
                        "transcription": "transcription_minutes",
                        "chat": "chat_tokens"}[resource]
            cap = cfg.get(cap_key)
            if cap is not None and cap > 0 and proj.get(used_key, 0) > cap:
                blocked = True
                reason = f"Quota mensuel {RESOURCE_FR[resource]} atteint ({cap} {RESOURCE_BASE_LABEL[resource]})."
        elif mode == "budget":
            cap = cfg.get("monthly_budget_xof")
            if cap is not None and cap > 0 and proj["total_xof"] > cap:
                blocked = True
                reason = f"Budget mensuel IA atteint ({int(cap)} XOF)."
    if blocked:
        return {"allowed": False, "reason": reason, "warn": False, "cost_xof": cost_xof, "rollup": status_before["usage"]}
    if pre_check:
        # Don't actually log — just say "ok, you can proceed".
        return {"allowed": True, "reason": None, "warn": False, "cost_xof": cost_xof, "rollup": status_before["usage"]}
    # ---- Persist the event + bump the rollup ----
    ym = _year_month()
    event = {
        "id": secrets.token_urlsafe(12),
        "client_id": client_id,
        "user_id": user.get("id"),
        "user_label": user.get("full_name") or user.get("email") or "—",
        "tracked_role": user.get("tracked_role"),
        "resource": resource,
        "units": units,
        "base": RESOURCE_BASE_LABEL.get(resource, resource),
        "cost_xof": cost_xof,
        "model": model,
        "metadata": metadata or {},
        "year_month": ym,
        "created_at": _now(),
    }
    try:
        await db.ai_usage_events.insert_one(event.copy())
    except Exception:
        logger.exception("[ai-quota] failed to log event")
    inc: Dict[str, float] = {"total_xof": cost_xof}
    if resource == "image":         inc["images"] = float(units)
    elif resource == "video":       inc["videos"] = float(units)
    elif resource == "transcription": inc["transcription_minutes"] = float(units)
    elif resource == "chat":        inc["chat_tokens"] = float(units)
    try:
        await db.ai_usage_monthly.update_one(
            {"_id": f"{client_id}:{ym}"},
            {"$inc": inc,
             "$set": {"client_id": client_id, "year_month": ym, "updated_at": _now()}},
            upsert=True,
        )
    except Exception:
        logger.exception("[ai-quota] failed to bump rollup")
    # Warn detection (after the bump)
    status_after = await _quota_status(db, client_id)
    warn = status_after["any_warn"] and not status_before["any_warn"]
    return {"allowed": True, "reason": None, "warn": warn, "cost_xof": cost_xof, "rollup": status_after["usage"]}


# ============================================================
# Router setup
# ============================================================
def setup_ai_quotas_routes(*, db, api, get_current_user, get_current_admin):
    """Mount AI quota + usage endpoints. Idempotent (safe to call once)."""

    # ----------------------------------------------------------
    # Admin — configuration per Client Lié
    # ----------------------------------------------------------
    @api.get("/admin/clients/{client_id}/ai-quota", tags=["Admin — IA Quotas"])
    async def get_ai_quota(client_id: str, _: dict = Depends(get_current_admin)):
        cfg = await db.ai_quotas.find_one({"client_id": client_id}, {"_id": 0}) or {}
        if not cfg:
            cfg = {"client_id": client_id, "mode": "off", "currency": "XOF",
                   "alert_warn_pct": 80, "block_on_limit": True}
        costs = await _load_costs(db, client_id)
        return {"config": cfg, "effective_costs_xof": costs, "defaults": DEFAULT_COSTS_XOF}

    @api.put("/admin/clients/{client_id}/ai-quota", tags=["Admin — IA Quotas"])
    async def put_ai_quota(client_id: str, payload: QuotaConfig, user: dict = Depends(get_current_admin)):
        client = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "role": 1})
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")
        update = payload.model_dump(exclude_none=True)
        update["client_id"] = client_id
        update["updated_at"] = _now()
        update["updated_by_id"] = user["id"]
        await db.ai_quotas.update_one({"client_id": client_id}, {"$set": update}, upsert=True)
        cfg = await db.ai_quotas.find_one({"client_id": client_id}, {"_id": 0})
        return {"ok": True, "config": cfg}

    # ----------------------------------------------------------
    # Admin — current usage with breakdown
    # ----------------------------------------------------------
    @api.get("/admin/clients/{client_id}/ai-usage", tags=["Admin — IA Quotas"])
    async def get_ai_usage(
        client_id: str,
        year_month: Optional[str] = Query(None, alias="month"),
        _: dict = Depends(get_current_admin),
    ):
        ym = year_month or _year_month()
        rollup = await _get_rollup(db, client_id, ym)
        status = await _quota_status(db, client_id)
        # Breakdown per user (this month) via aggregation
        pipeline = [
            {"$match": {"client_id": client_id, "year_month": ym}},
            {"$group": {
                "_id": {"user_id": "$user_id", "resource": "$resource"},
                "units": {"$sum": "$units"},
                "cost_xof": {"$sum": "$cost_xof"},
                "user_label": {"$first": "$user_label"},
                "tracked_role": {"$first": "$tracked_role"},
            }},
        ]
        cursor = db.ai_usage_events.aggregate(pipeline)
        per_user_map: Dict[str, Dict[str, Any]] = {}
        async for row in cursor:
            uid = row["_id"]["user_id"]
            res = row["_id"]["resource"]
            entry = per_user_map.setdefault(uid, {
                "user_id": uid,
                "user_label": row.get("user_label") or "—",
                "tracked_role": row.get("tracked_role"),
                "by_resource": {},
                "total_xof": 0.0,
            })
            entry["by_resource"][res] = {"units": row["units"], "cost_xof": row["cost_xof"]}
            entry["total_xof"] += row["cost_xof"]
        per_user = list(per_user_map.values())
        per_user.sort(key=lambda x: x["total_xof"], reverse=True)
        return {
            "client_id": client_id,
            "year_month": ym,
            "rollup": rollup,
            "status": status,
            "per_user": per_user,
        }

    # ----------------------------------------------------------
    # Admin — CSV export (history)
    # ----------------------------------------------------------
    @api.get("/admin/clients/{client_id}/ai-usage/export.csv", tags=["Admin — IA Quotas"])
    async def export_ai_usage_csv(
        client_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        _: dict = Depends(get_current_admin),
    ):
        match: Dict[str, Any] = {"client_id": client_id}
        rng: Dict[str, str] = {}
        if date_from: rng["$gte"] = date_from
        if date_to: rng["$lte"] = date_to + "T23:59:59Z"
        if rng:
            match["created_at"] = rng
        cursor = db.ai_usage_events.find(match, {"_id": 0}).sort("created_at", 1)
        events = await cursor.to_list(50000)
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow([
            "Date/Heure", "Utilisateur Suivi", "Rôle", "Ressource",
            "Unités consommées", "Base", "Coût (XOF)", "Modèle",
        ])
        for ev in events:
            writer.writerow([
                ev.get("created_at") or "",
                ev.get("user_label") or "—",
                ev.get("tracked_role") or "",
                RESOURCE_FR.get(ev.get("resource"), ev.get("resource") or ""),
                ev.get("units") or 0,
                ev.get("base") or "",
                ev.get("cost_xof") or 0,
                ev.get("model") or "",
            ])
        # Totals
        total_xof = sum(ev.get("cost_xof") or 0 for ev in events)
        writer.writerow([])
        writer.writerow(["TOTAL", "", "", "", "", "", round(total_xof, 2), ""])
        data = buf.getvalue().encode("utf-8-sig")  # BOM for Excel
        filename = f"ai-usage-{client_id[:8]}-{date_from or 'all'}-{date_to or 'all'}.csv"
        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ----------------------------------------------------------
    # Admin — PDF export (lazy import of reportlab)
    # ----------------------------------------------------------
    @api.get("/admin/clients/{client_id}/ai-usage/export.pdf", tags=["Admin — IA Quotas"])
    async def export_ai_usage_pdf(
        client_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        _: dict = Depends(get_current_admin),
    ):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        except ImportError:
            raise HTTPException(status_code=503, detail="reportlab non installé sur le serveur.")
        match: Dict[str, Any] = {"client_id": client_id}
        rng: Dict[str, str] = {}
        if date_from: rng["$gte"] = date_from
        if date_to: rng["$lte"] = date_to + "T23:59:59Z"
        if rng: match["created_at"] = rng
        events = await db.ai_usage_events.find(match, {"_id": 0}).sort("created_at", 1).to_list(50000)
        client = await db.users.find_one({"id": client_id}, {"_id": 0, "full_name": 1, "company": 1, "email": 1}) or {}
        client_label = client.get("company") or client.get("full_name") or client.get("email") or client_id
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title="Rapport Consommation IA SAWALI")
        styles = getSampleStyleSheet()
        story = [
            Paragraph(f"<b>Rapport Consommation IA</b> — {client_label}", styles["Title"]),
            Paragraph(f"Période : {date_from or '—'} → {date_to or '—'}", styles["Normal"]),
            Spacer(1, 12),
        ]
        rows = [["Date/Heure", "Utilisateur Suivi", "Ressource", "Unités", "Base", "Coût (XOF)", "Modèle"]]
        total = 0.0
        for ev in events:
            rows.append([
                (ev.get("created_at") or "")[:19].replace("T", " "),
                (ev.get("user_label") or "—")[:24],
                RESOURCE_FR.get(ev.get("resource"), ev.get("resource") or ""),
                f"{ev.get('units') or 0:g}",
                ev.get("base") or "",
                f"{ev.get('cost_xof') or 0:.2f}",
                (ev.get("model") or "")[:22],
            ])
            total += ev.get("cost_xof") or 0
        rows.append(["", "", "", "", "", "TOTAL", f"{total:.2f} XOF"])
        tbl = Table(rows, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0E1F3D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ALIGN", (3, 1), (3, -1), "RIGHT"),
            ("ALIGN", (5, 1), (5, -1), "RIGHT"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#1E90FF")),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]))
        story.append(tbl)
        doc.build(story)
        buf.seek(0)
        return StreamingResponse(
            buf, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="ai-usage-{client_id[:8]}.pdf"'},
        )

    # ----------------------------------------------------------
    # User-facing — read-only view of own current usage + alerts
    # ----------------------------------------------------------
    @api.get("/me/ai-usage", tags=["Portail Client — IA"])
    async def me_ai_usage(user: dict = Depends(get_current_user)):
        client_id = await _resolve_tracked_admin(db, user)
        status = await _quota_status(db, client_id)
        return {"status": status, "client_id": client_id}

    # ----------------------------------------------------------
    # Iter38r-fix9z5 — Admin Dashboard: cross-tenant monthly cost chart
    # Returns the last N months of TOTAL AI spend across all tenants
    # (sum of `total_xof` in `ai_usage_monthly`).
    # ----------------------------------------------------------
    @api.get("/admin/ai-costs/monthly", tags=["Admin — IA Quotas"])
    async def ai_costs_monthly(
        months: int = Query(12, ge=1, le=36),
        _: dict = Depends(get_current_admin),
    ):
        # Build the list of year_months to include (newest first → oldest last in chart)
        from datetime import datetime as _dt
        now = _dt.now(timezone.utc)
        wanted = []
        y, m = now.year, now.month
        for _i in range(months):
            wanted.append(f"{y:04d}-{m:02d}")
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        wanted_set = set(wanted)

        pipeline = [
            {"$match": {"year_month": {"$in": list(wanted_set)}}},
            {"$group": {
                "_id": "$year_month",
                "total_xof": {"$sum": "$total_xof"},
                "images": {"$sum": "$images"},
                "videos": {"$sum": "$videos"},
                "transcription_minutes": {"$sum": "$transcription_minutes"},
                "chat_tokens": {"$sum": "$chat_tokens"},
                "tenant_count": {"$addToSet": "$client_id"},
            }},
        ]
        cursor = db.ai_usage_monthly.aggregate(pipeline)
        rows: Dict[str, Dict[str, Any]] = {}
        async for r in cursor:
            ym = r["_id"]
            rows[ym] = {
                "year_month": ym,
                "total_xof": float(r.get("total_xof") or 0),
                "images": int(r.get("images") or 0),
                "videos": int(r.get("videos") or 0),
                "transcription_minutes": float(r.get("transcription_minutes") or 0),
                "chat_tokens": int(r.get("chat_tokens") or 0),
                "tenant_count": len(r.get("tenant_count") or []),
            }
        # Build the full series in chronological order (oldest → newest), zero-filled
        series = []
        for ym in reversed(wanted):
            series.append(rows.get(ym, {
                "year_month": ym, "total_xof": 0.0,
                "images": 0, "videos": 0,
                "transcription_minutes": 0.0, "chat_tokens": 0,
                "tenant_count": 0,
            }))
        total_period = sum(r["total_xof"] for r in series)
        avg_monthly = total_period / max(len(series), 1)
        return {
            "months_requested": months,
            "series": series,
            "totals": {
                "period_xof": total_period,
                "average_monthly_xof": avg_monthly,
            },
            "currency": "XOF",
        }
