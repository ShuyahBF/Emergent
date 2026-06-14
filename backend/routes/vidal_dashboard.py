"""Iter41 Phase 4 (2026-02) — VIDAL usage dashboard + public officines inscription API.

Two value-add features :

  1. **Usage dashboard** (`GET /api/admin/vidal/usage`) — counts daily VIDAL
     consumption per user/day, top searches over the last 30 days, top
     consumers, prescription alerts triggered, and a 30-day series for a
     chart in AdminSettings.

  2. **Public Officines inscription API** (`POST /api/public/officines/register`)
     — HMAC-signed endpoint allowing officines themselves to declare their
     inventory. The signature is computed over the request body using a shared
     secret stored in `settings.global.officines_register_hmac_secret`.
     Replay-protection : `X-Timestamp` header must be within ±5 minutes.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger("sawali.vidal_dashboard")


# --------------------------------------------------------------------------- #
# VIDAL Usage Dashboard
# --------------------------------------------------------------------------- #
def attach_vidal_dashboard_routes(*, api, db, get_current_admin):

    @api.get("/admin/vidal/usage", tags=["Admin — VIDAL"])
    async def vidal_usage(
        days: int = Query(30, ge=1, le=365),
        user: dict = Depends(get_current_admin),
    ):
        """Renvoie l'usage VIDAL agrégé pour les `days` derniers jours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        # 1. Daily totals (sum over all users per day)
        daily_pipeline = [
            {"$match": {"day": {"$gte": cutoff}}},
            {"$group": {"_id": "$day", "total": {"$sum": "$count"}, "unique_users": {"$addToSet": "$user_id"}}},
            {"$project": {"_id": 0, "day": "$_id", "total": 1, "unique_users": {"$size": "$unique_users"}}},
            {"$sort": {"day": 1}},
        ]
        daily = await db.vidal_usage_daily.aggregate(daily_pipeline).to_list(400)

        # 2. Top consumers (by user, last `days`)
        top_pipeline = [
            {"$match": {"day": {"$gte": cutoff}}},
            {"$group": {"_id": "$user_id", "total": {"$sum": "$count"}}},
            {"$sort": {"total": -1}},
            {"$limit": 10},
        ]
        raw_top = await db.vidal_usage_daily.aggregate(top_pipeline).to_list(10)
        # Enrich with user emails
        top: List[Dict[str, Any]] = []
        for row in raw_top:
            u = await db.users.find_one({"id": row["_id"]}, {"_id": 0, "email": 1, "full_name": 1, "role": 1, "company": 1}) or {}
            top.append({
                "user_id": row["_id"],
                "email": u.get("email"),
                "full_name": u.get("full_name"),
                "role": u.get("role"),
                "company": u.get("company"),
                "total": row["total"],
            })

        # 3. Prescription audit totals
        prescription_count = await db.vidal_prescription_audit.count_documents({
            "created_at": {"$gte": datetime.now(timezone.utc) - timedelta(days=days)},
        })

        # 4. Distribution by mode (test vs prod)
        mode_pipeline = [
            {"$match": {"created_at": {"$gte": datetime.now(timezone.utc) - timedelta(days=days)}}},
            {"$group": {"_id": "$mode", "count": {"$sum": 1}}},
        ]
        modes = await db.vidal_prescription_audit.aggregate(mode_pipeline).to_list(10)
        mode_map = {m["_id"] or "unknown": m["count"] for m in modes}

        # 5. Total counts
        total_calls = sum(d["total"] for d in daily)
        total_unique_users = len({u["user_id"] for u in top}) if top else 0

        # 6. Cache hit rate (from cache collection size — heuristic)
        cache_size = await db.vidal_cache.count_documents({})

        return {
            "period_days": days,
            "totals": {
                "vidal_calls": total_calls,
                "unique_users": total_unique_users,
                "prescription_alerts": prescription_count,
                "cache_entries": cache_size,
            },
            "daily_series": daily,
            "top_consumers": top,
            "by_mode": mode_map,
        }

    @api.get("/admin/officines/usage", tags=["Admin — VIDAL"])
    async def officines_usage(
        days: int = Query(30, ge=1, le=365),
        user: dict = Depends(get_current_admin),
    ):
        """Renvoie l'usage de l'API officines : top recherches, consommation publique !aizenta."""
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff_dt.date().isoformat()

        # Lookups (authenticated portal)
        portal_count = await db.officines_audit.count_documents({"created_at": {"$gte": cutoff_dt}})

        # Top products searched
        top_pipeline = [
            {"$match": {"created_at": {"$gte": cutoff_dt}}},
            {"$group": {"_id": "$product_name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_products = await db.officines_audit.aggregate(top_pipeline).to_list(10)

        # Public WA usage
        wa_pipeline = [
            {"$match": {"day": {"$gte": cutoff_iso}}},
            {"$group": {"_id": "$day", "total": {"$sum": "$count"}, "unique_phones": {"$addToSet": "$phone"}}},
            {"$project": {"_id": 0, "day": "$_id", "total": 1, "unique_phones": {"$size": "$unique_phones"}}},
            {"$sort": {"day": 1}},
        ]
        wa_daily = await db.officines_public_usage.aggregate(wa_pipeline).to_list(400)
        wa_total = sum(d["total"] for d in wa_daily)

        # Registered officines (HMAC-signed inscriptions)
        registered = await db.officines_inventory.count_documents({})

        return {
            "period_days": days,
            "totals": {
                "portal_lookups": portal_count,
                "wa_aizenta_calls": wa_total,
                "registered_officines_products": registered,
            },
            "top_products": [{"product": p["_id"], "count": p["count"]} for p in top_products],
            "wa_daily_series": wa_daily,
        }

    logger.info("[vidal_dashboard] routes mounted under /api/admin/{vidal,officines}/usage")


# --------------------------------------------------------------------------- #
# Public Officines Inscription API (HMAC-signed)
# --------------------------------------------------------------------------- #
class OfficineRegisterPayload(BaseModel):
    officine_name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    contact_email: Optional[str] = None
    inventory: List[Dict[str, Any]]  # [{product_name, cip?, price?, available?, stock_qty?}]


def attach_public_officines_routes(*, api, db):

    @api.post("/public/officines/register", tags=["Officines — Public"])
    async def public_register(
        request: Request,
        payload: OfficineRegisterPayload = Body(...),
        x_signature: str = Header(..., alias="X-Signature"),
        x_timestamp: str = Header(..., alias="X-Timestamp"),
        x_officine_id: str = Header(..., alias="X-Officine-Id"),
    ):
        """Lets an officine declare its inventory. The body must be HMAC-signed
        with the shared secret published to the officine on enrollment.

        Header layout :
          X-Officine-Id: opaque identifier supplied to the officine
          X-Timestamp:   epoch seconds (±5 min)
          X-Signature:   sha256 HMAC = hexdigest( secret, f"{ts}.{body_raw}" )
        """
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "officines_register_hmac_secret": 1}) or {}
        secret = (s.get("officines_register_hmac_secret") or "").encode()
        if not secret:
            raise HTTPException(status_code=503, detail="Service d'inscription désactivé (secret HMAC non configuré).")

        # Timestamp window (±300 s)
        try:
            ts = int(x_timestamp)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-Timestamp invalide")
        now = int(datetime.now(timezone.utc).timestamp())
        if abs(now - ts) > 300:
            raise HTTPException(status_code=401, detail="Timestamp expiré (±5 min)")

        # Signature check (over raw body)
        raw_body = await request.body()
        msg = f"{ts}.{raw_body.decode('utf-8', errors='replace')}".encode()
        expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_signature):
            raise HTTPException(status_code=401, detail="Signature HMAC invalide")

        # Persist
        doc = {
            "officine_id": x_officine_id,
            "officine_name": payload.officine_name,
            "address": payload.address,
            "phone": payload.phone,
            "city": payload.city,
            "country": payload.country,
            "contact_email": payload.contact_email,
            "inventory_count": len(payload.inventory),
            "registered_at": datetime.now(timezone.utc),
            "raw_inventory": payload.inventory[:500],  # cap to 500 items per call
        }
        await db.officines_inventory.update_one(
            {"officine_id": x_officine_id},
            {"$set": doc, "$inc": {"updates_count": 1}},
            upsert=True,
        )
        return {"ok": True, "officine_id": x_officine_id, "items_received": len(payload.inventory)}

    logger.info("[public_officines] HMAC-signed register endpoint mounted under /api/public/officines/register")
