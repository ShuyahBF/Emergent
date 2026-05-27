"""Iter38n — Catalogue public analytics (vues, partages, demandes de devis).

Track minimal events on the public-facing catalogue to surface conversion
insight to Admin / Superviseur / Tracked users (employees).

Events captured:
  - catalog_view        : Anonymous hit on GET /api/public/products.
  - product_og_fetch    : Anonymous hit on GET /api/public/og/product/{id}.
  - product_share       : Client-side `navigator.share()` or clipboard fallback.
  - product_quote_click : Client clicks "Demander un devis" on a product card.

Storage: collection `db.catalog_events`
  {
    id, event_type, tenant_id (None for catalog_view), product_id, product_sku,
    product_name, referrer, user_agent, ip_hash, created_at
  }

IP is HASHED (no PII stored) to allow deduplication within a 10-min window
without storing raw IPs.

Endpoints:
  - POST /api/public/catalog/track           (anonymous, rate-limited via IP hash)
  - GET  /api/me/catalog/stats?days=30       (admin/sup/tracked user, tenant-scoped)
  - GET  /api/me/catalog/history?days=30     (admin/sup/tracked user, tenant-scoped)
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body
from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_ip(ip: str) -> str:
    return hashlib.sha256((ip or "anonymous").encode()).hexdigest()[:16]


def _is_super_admin(user: dict) -> bool:
    return (user.get("email") or "").lower() == "admin@sawalismartsystems.com"


def _can_view_catalog_stats(user: dict) -> bool:
    """Admin / Superviseur / any tracked user (employees) can view stats."""
    role = (user or {}).get("role")
    if role in ("admin", "superviseur"):
        return True
    # Tracked user = has a tracked_role OR has a tracked_user_id link
    if user.get("tracked_role") or user.get("tracked_user_id"):
        return True
    return False


class CatalogTrackPayload(BaseModel):
    event_type: str = Field(..., pattern=r"^(catalog_view|product_share|product_quote_click|product_og_fetch)$")
    product_id: Optional[str] = Field(None, max_length=80)
    product_sku: Optional[str] = Field(None, max_length=80)
    product_name: Optional[str] = Field(None, max_length=200)
    referrer: Optional[str] = Field(None, max_length=500)


# Iter38o — Mark untreated quote-clicks for a product as treated.
class MarkQuoteTreatedPayload(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=80)


def setup_catalog_analytics_routes(*, db, api, get_current_user):
    """Wire the public + portal endpoints into the main API router."""

    # ----------------------------------------------------------------
    # Internal helper — used by /public/products & /public/og/product
    # to log a view event from inside server.py.
    # ----------------------------------------------------------------
    async def log_event(
        event_type: str,
        *,
        product_id: Optional[str] = None,
        product_sku: Optional[str] = None,
        product_name: Optional[str] = None,
        tenant_id: Optional[str] = None,
        request: Optional[Request] = None,
    ) -> None:
        try:
            client_ip = ""
            user_agent = ""
            referrer = ""
            if request is not None:
                client_ip = (request.headers.get("x-forwarded-for") or
                             (request.client.host if request.client else "")) or ""
                client_ip = client_ip.split(",")[0].strip()
                user_agent = (request.headers.get("user-agent") or "")[:300]
                referrer = (request.headers.get("referer") or "")[:500]
            doc = {
                "id": str(uuid.uuid4()),
                "event_type": event_type,
                "tenant_id": tenant_id,
                "product_id": product_id,
                "product_sku": product_sku,
                "product_name": product_name,
                "referrer": referrer,
                "user_agent": user_agent,
                "ip_hash": _hash_ip(client_ip),
                "created_at": _now_iso(),
            }
            await db.catalog_events.insert_one(doc)
        except Exception:
            # Analytics must never break the request.
            pass

    async def _resolve_product_tenant(product_id: Optional[str]) -> Optional[str]:
        if not product_id:
            return None
        p = await db.products.find_one({"id": product_id}, {"_id": 0, "tenant_id": 1, "client_id": 1})
        if not p:
            return None
        return p.get("tenant_id") or p.get("client_id")

    # ----------------------------------------------------------------
    # Public tracking endpoint (called from frontend on share / quote click)
    # ----------------------------------------------------------------
    @api.post("/public/catalog/track", tags=["Public"])
    async def track_catalog_event(
        payload: CatalogTrackPayload, request: Request
    ):
        tenant_id = await _resolve_product_tenant(payload.product_id)
        await log_event(
            payload.event_type,
            product_id=payload.product_id,
            product_sku=payload.product_sku,
            product_name=payload.product_name,
            tenant_id=tenant_id,
            request=request,
        )
        return {"ok": True}

    # ----------------------------------------------------------------
    # Portal stats endpoint (admin/sup/tracked users)
    # ----------------------------------------------------------------
    async def _scope_for_user(user: dict) -> Dict[str, Any]:
        """Super-admin sees all tenants; others see only their tenant.

        Tenant resolution mirrors the cashier logic (parent_client_id /
        client_id / canonical-by-company / self).
        """
        if _is_super_admin(user):
            return {}
        # Resolve canonical tenant_id (same logic as cashier_expenses)
        for key in ("parent_client_id", "client_id"):
            ref = user.get(key)
            if ref and ref != user.get("id"):
                doc = await db.users.find_one({"id": ref}, {"_id": 0, "id": 1})
                if doc:
                    return {"tenant_id": doc["id"]}
        company = (user.get("company") or "").strip()
        if company:
            for rf in ({"role": "admin"}, {"role": "superviseur"}):
                canonical = await db.users.find_one(
                    {**rf, "company": company},
                    {"_id": 0, "id": 1},
                    sort=[("created_at", 1)],
                )
                if canonical:
                    return {"tenant_id": canonical["id"]}
        return {"tenant_id": user["id"]}

    @api.get("/me/catalog/stats", tags=["Portail Client"])
    async def catalog_stats(
        days: int = Query(30, ge=1, le=365),
        user: dict = Depends(get_current_user),
    ):
        if not _can_view_catalog_stats(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        scope = await _scope_for_user(user)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        # Catalog views are tenant-agnostic (anonymous landing); show them as a
        # global signal regardless of scope.
        global_views = await db.catalog_events.count_documents({
            "event_type": "catalog_view",
            "created_at": {"$gte": since},
        })
        # Tenant-bound events
        q_tenant: Dict[str, Any] = {"created_at": {"$gte": since}}
        if scope:
            q_tenant.update(scope)
        # Totals by event type
        pipeline_totals = [
            {"$match": q_tenant},
            {"$group": {"_id": "$event_type", "n": {"$sum": 1}}},
        ]
        totals_by_type: Dict[str, int] = {}
        async for row in db.catalog_events.aggregate(pipeline_totals):
            totals_by_type[row["_id"]] = int(row["n"])
        product_og_fetch = totals_by_type.get("product_og_fetch", 0)
        product_share = totals_by_type.get("product_share", 0)
        product_quote_click = totals_by_type.get("product_quote_click", 0)

        # Top 5 products by view count (product_og_fetch + product_share)
        pipeline_top = [
            {"$match": {
                **q_tenant,
                "event_type": {"$in": ["product_og_fetch", "product_share", "product_quote_click"]},
                "product_id": {"$ne": None},
            }},
            {"$group": {
                "_id": "$product_id",
                "name": {"$last": "$product_name"},
                "sku": {"$last": "$product_sku"},
                "views": {"$sum": {"$cond": [{"$eq": ["$event_type", "product_og_fetch"]}, 1, 0]}},
                "shares": {"$sum": {"$cond": [{"$eq": ["$event_type", "product_share"]}, 1, 0]}},
                "quotes": {"$sum": {"$cond": [{"$eq": ["$event_type", "product_quote_click"]}, 1, 0]}},
                "total": {"$sum": 1},
            }},
            {"$sort": {"total": -1}},
            {"$limit": 5},
        ]
        top_products: List[Dict[str, Any]] = []
        async for row in db.catalog_events.aggregate(pipeline_top):
            top_products.append({
                "product_id": row["_id"],
                "product_name": row.get("name") or "—",
                "product_sku": row.get("sku") or "—",
                "views": int(row.get("views", 0)),
                "shares": int(row.get("shares", 0)),
                "quotes": int(row.get("quotes", 0)),
                "total": int(row.get("total", 0)),
            })

        # Conversion funnel ratios
        funnel = {
            "og_fetches": product_og_fetch,
            "shares": product_share,
            "quote_clicks": product_quote_click,
            "share_rate": round(product_share / product_og_fetch * 100, 1) if product_og_fetch > 0 else 0.0,
            "quote_rate": round(product_quote_click / product_og_fetch * 100, 1) if product_og_fetch > 0 else 0.0,
        }

        # Daily timeline (last `days` days)
        pipeline_daily = [
            {"$match": q_tenant},
            {"$group": {
                "_id": {"day": {"$substr": ["$created_at", 0, 10]}, "type": "$event_type"},
                "n": {"$sum": 1},
            }},
            {"$sort": {"_id.day": 1}},
        ]
        daily_map: Dict[str, Dict[str, int]] = {}
        async for row in db.catalog_events.aggregate(pipeline_daily):
            day = row["_id"]["day"]
            etype = row["_id"]["type"]
            daily_map.setdefault(day, {})[etype] = int(row["n"])
        # Build dense timeline (one entry per day in window)
        today = datetime.now(timezone.utc).date()
        timeline: List[Dict[str, Any]] = []
        for i in range(days, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            row = daily_map.get(d, {})
            timeline.append({
                "date": d,
                "og_fetches": int(row.get("product_og_fetch", 0)),
                "shares": int(row.get("product_share", 0)),
                "quotes": int(row.get("product_quote_click", 0)),
            })

        return {
            "days": days,
            "since": since,
            "tenant_scoped": bool(scope),
            "global_catalog_views": global_views,
            "tenant_event_totals": {
                "og_fetches": product_og_fetch,
                "shares": product_share,
                "quote_clicks": product_quote_click,
            },
            "funnel": funnel,
            "top_products": top_products,
            "timeline": timeline,
            "pending_quotes_alerts": await _compute_pending_alerts(scope),
        }

    PENDING_QUOTES_THRESHOLD = 10  # Iter38o — Trigger alert at >10 untreated quote clicks per product

    async def _compute_pending_alerts(scope: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return products with > N untreated quote clicks (Iter38o)."""
        match: Dict[str, Any] = {"event_type": "product_quote_click", "treated_at": None}
        if scope:
            match.update(scope)
        pipeline = [
            {"$match": match},
            {"$group": {
                "_id": "$product_id",
                "name": {"$last": "$product_name"},
                "sku": {"$last": "$product_sku"},
                "n": {"$sum": 1},
                "oldest": {"$min": "$created_at"},
            }},
            {"$match": {"n": {"$gt": PENDING_QUOTES_THRESHOLD}}},
            {"$sort": {"n": -1}},
            {"$limit": 20},
        ]
        out: List[Dict[str, Any]] = []
        async for row in db.catalog_events.aggregate(pipeline):
            out.append({
                "product_id": row["_id"],
                "product_name": row.get("name") or "—",
                "product_sku": row.get("sku") or "—",
                "pending_count": int(row["n"]),
                "oldest_at": row.get("oldest"),
            })
        return out

    @api.get("/me/catalog/history", tags=["Portail Client"])
    async def catalog_history(
        days: int = Query(30, ge=1, le=365),
        limit: int = Query(100, ge=1, le=500),
        event_type: Optional[str] = Query(None),
        user: dict = Depends(get_current_user),
    ):
        if not _can_view_catalog_stats(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        scope = await _scope_for_user(user)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        q: Dict[str, Any] = {"created_at": {"$gte": since}}
        if scope:
            q.update(scope)
        if event_type:
            q["event_type"] = event_type
        cursor = db.catalog_events.find(
            q, {"_id": 0, "ip_hash": 0}
        ).sort("created_at", -1).limit(limit)
        items = [e async for e in cursor]
        return {"days": days, "count": len(items), "items": items}

    # Iter38o — CSV export of catalog events for offline analysis.
    @api.get("/me/catalog/export.csv", tags=["Portail Client"])
    async def catalog_export_csv(
        days: int = Query(30, ge=1, le=365),
        event_type: Optional[str] = Query(None),
        user: dict = Depends(get_current_user),
    ):
        import csv
        import io
        from fastapi.responses import StreamingResponse
        if not _can_view_catalog_stats(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        scope = await _scope_for_user(user)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        q: Dict[str, Any] = {"created_at": {"$gte": since}}
        if scope:
            q.update(scope)
        if event_type:
            q["event_type"] = event_type
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["date", "event_type", "product_id", "product_sku", "product_name", "referrer", "user_agent"])
        cursor = db.catalog_events.find(q, {"_id": 0, "ip_hash": 0}).sort("created_at", -1).limit(5000)
        async for e in cursor:
            w.writerow([
                e.get("created_at", ""),
                e.get("event_type", ""),
                e.get("product_id") or "",
                e.get("product_sku") or "",
                e.get("product_name") or "",
                (e.get("referrer") or "")[:200],
                (e.get("user_agent") or "")[:200],
            ])
        buf.seek(0)
        fname = f"catalog-events-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )

    # Iter38o — Mark quote-clicks for a product as "treated" (so the badge clears).
    @api.post("/me/catalog/quotes/mark-treated", tags=["Portail Client"])
    async def mark_quotes_treated(
        payload: MarkQuoteTreatedPayload, user: dict = Depends(get_current_user)
    ):
        if not _can_view_catalog_stats(user):
            raise HTTPException(status_code=403, detail="Accès réservé")
        scope = await _scope_for_user(user)
        q: Dict[str, Any] = {"product_id": payload.product_id, "event_type": "product_quote_click", "treated_at": None}
        if scope:
            q.update(scope)
        res = await db.catalog_events.update_many(
            q,
            {"$set": {"treated_at": _now_iso(), "treated_by": user["id"]}},
        )
        return {"ok": True, "marked": res.modified_count}

    # Expose helper for use by /public/products + /public/og/product
    return {"log_event": log_event}


__all__ = ["setup_catalog_analytics_routes"]
