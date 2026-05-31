"""Iter38r-fix9w — Ad Banners Monetization.

Lets the admin (super-admin or per-tenant) sell advertising slots that
display at the top of public pages and/or the Espace Loois portal.

Data model (`ad_banners` collection)
------------------------------------
{
  id: str,
  tenant_id: str,                       # owning admin (usually SAWALI super-admin)
  name: str,                            # campaign label
  advertiser_name: str,                 # who's paying
  image_url: str,                       # banner asset URL (external or /api/uploads/…)
  target_url: str,                      # landing URL when banner is clicked
  placement: "public" | "portal" | "both",
  animated: bool,                       # CSS slide/fade vs static
  active: bool,
  budget_amount: float,                 # total paid in `currency`
  currency: str = "XOF",
  cost_per_impression: float = 0,
  cost_per_click: float = 0,
  total_impressions: int = 0,
  total_clicks: int = 0,
  amount_spent: float = 0,
  paid: bool,
  payment_date: ISO | None,
  expiration_date: "YYYY-MM-DD" | None,
  start_date: "YYYY-MM-DD" | None,
  daily_stats: [{date, impressions, clicks, spent}],
  created_at: ISO,
  updated_at: ISO,
  notes: str,
}

Public endpoints
----------------
GET    /api/public/ad-banners/active?placement=public|portal   serve weighted-random active banner (rotation)
POST   /api/public/ad-banners/{id}/impression                  bump impression counter
POST   /api/public/ad-banners/{id}/click                       bump click counter

Admin endpoints
---------------
GET    /api/admin/ad-banners
POST   /api/admin/ad-banners
PUT    /api/admin/ad-banners/{id}
DELETE /api/admin/ad-banners/{id}
POST   /api/admin/ad-banners/{id}/toggle-paid
GET    /api/admin/ad-banners/{id}/stats
"""
from __future__ import annotations

import logging
import random
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.ad_banners")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


# Iter38r-fix9y — Slug + share-token helpers for public stats pages
def _slugify(value: str) -> str:
    """Lowercase + strip accents + replace non-alnum with hyphens. Truncated to 50 chars."""
    if not value:
        return "banner"
    # Strip accents: é → e, à → a, etc.
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in normalized if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return s[:50] or "banner"


async def _ensure_unique_slug(db, base: str, banner_id: str) -> str:
    """Append `-2`, `-3`, … until the slug is unique across `ad_banners`."""
    slug = _slugify(base)
    candidate = slug
    i = 2
    while True:
        existing = await db.ad_banners.find_one(
            {"slug": candidate, "id": {"$ne": banner_id}},
            {"_id": 0, "id": 1},
        )
        if not existing:
            return candidate
        candidate = f"{slug}-{i}"
        i += 1


def _is_expired(b: Dict[str, Any]) -> bool:
    exp = (b.get("expiration_date") or "").strip()
    if not exp:
        return False
    try:
        return date.fromisoformat(exp) < date.today()
    except ValueError:
        return False


def _budget_exhausted(b: Dict[str, Any]) -> bool:
    budget = float(b.get("budget_amount") or 0)
    spent = float(b.get("amount_spent") or 0)
    return budget > 0 and spent >= budget


def _is_started(b: Dict[str, Any]) -> bool:
    sd = (b.get("start_date") or "").strip()
    if not sd:
        return True
    try:
        return date.fromisoformat(sd) <= date.today()
    except ValueError:
        return True


def _public_view(b: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelist of fields safely exposed to anonymous visitors."""
    return {
        "id": b.get("id"),
        "name": b.get("name"),
        "image_url": b.get("image_url"),
        "target_url": b.get("target_url"),
        "advertiser_name": b.get("advertiser_name"),
        "animated": bool(b.get("animated", False)),
        "placement": b.get("placement"),
    }


def _admin_view(b: Dict[str, Any]) -> Dict[str, Any]:
    b = {k: v for k, v in b.items() if k != "_id"}
    budget = float(b.get("budget_amount") or 0)
    spent = float(b.get("amount_spent") or 0)
    b["progress_pct"] = round((spent / budget) * 100, 1) if budget else 0.0
    b["is_expired"] = _is_expired(b)
    b["is_budget_exhausted"] = _budget_exhausted(b)
    b["is_currently_active"] = bool(
        b.get("active") and _is_started(b) and not _is_expired(b) and not _budget_exhausted(b)
    )
    # Iter38r-fix9y — Public stats share URL (relative path; frontend prefixes its origin)
    if b.get("slug") and b.get("share_token"):
        b["share_path"] = f"/ads/{b['slug']}?token={b['share_token']}"
    else:
        b["share_path"] = None
    return b


class AdBannerPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    advertiser_name: str = Field("", max_length=120)
    image_url: str = Field(..., min_length=4, max_length=600)
    target_url: str = Field(..., min_length=4, max_length=600)
    placement: str = Field("both", pattern="^(public|portal|both)$")
    animated: bool = False
    active: bool = True
    budget_amount: float = Field(0, ge=0)
    currency: str = Field("XOF", min_length=2, max_length=8)
    cost_per_impression: float = Field(0, ge=0)
    cost_per_click: float = Field(0, ge=0)
    paid: bool = False
    payment_date: Optional[str] = None
    expiration_date: Optional[str] = None
    start_date: Optional[str] = None
    notes: Optional[str] = Field("", max_length=500)


class AdBannerUpdate(BaseModel):
    name: Optional[str] = None
    advertiser_name: Optional[str] = None
    image_url: Optional[str] = None
    target_url: Optional[str] = None
    placement: Optional[str] = None
    animated: Optional[bool] = None
    active: Optional[bool] = None
    budget_amount: Optional[float] = None
    currency: Optional[str] = None
    cost_per_impression: Optional[float] = None
    cost_per_click: Optional[float] = None
    paid: Optional[bool] = None
    payment_date: Optional[str] = None
    expiration_date: Optional[str] = None
    start_date: Optional[str] = None
    notes: Optional[str] = None


async def _bump_daily_stat(db, banner_id: str, field: str, amount: float = 1.0) -> None:
    """Increment today's row in the daily_stats embedded array (upsert pattern)."""
    today = _today_iso()
    # Try $inc on existing day
    res = await db.ad_banners.update_one(
        {"id": banner_id, "daily_stats.date": today},
        {"$inc": {f"daily_stats.$.{field}": amount}},
    )
    if res.matched_count == 0:
        # First action today — push a new row
        await db.ad_banners.update_one(
            {"id": banner_id},
            {"$push": {"daily_stats": {"date": today, "impressions": 0, "clicks": 0, "spent": 0.0,
                                         field: amount}}},
        )


def setup_ad_banners_routes(app, db, get_current_user):
    api: APIRouter = app

    def _ensure_admin(user: dict) -> None:
        if (user or {}).get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    # =====================================================================
    # PUBLIC — banner rotation + tracking
    # =====================================================================
    @api.get("/public/ad-banners/active", tags=["Public — Ad Banners"])
    async def public_pick_banner(placement: str = Query("public", pattern="^(public|portal)$")):
        """Return ONE active banner suitable for `placement` (weighted random).
        Returns 204 No Content when no banner is currently active."""
        q = {"active": True, "placement": {"$in": [placement, "both"]}}
        cursor = db.ad_banners.find(q, {"_id": 0})
        candidates = await cursor.to_list(200)
        # Filter out expired / exhausted / not-started
        ready = [
            b for b in candidates
            if not _is_expired(b) and not _budget_exhausted(b) and _is_started(b)
        ]
        if not ready:
            return {"banner": None}
        # Weighted random: banners with more remaining budget get higher weight.
        # If no budget defined, all have weight 1.
        weights = []
        for b in ready:
            budget = float(b.get("budget_amount") or 0)
            spent = float(b.get("amount_spent") or 0)
            remaining = max(budget - spent, 0)
            weights.append(remaining if budget > 0 else 1.0)
        if all(w == 0 for w in weights):
            weights = [1.0] * len(ready)
        chosen = random.choices(ready, weights=weights, k=1)[0]
        return {"banner": _public_view(chosen)}

    @api.post("/public/ad-banners/{banner_id}/impression", tags=["Public — Ad Banners"])
    async def public_impression(banner_id: str):
        b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        if not b.get("active"):
            return {"ok": False, "reason": "inactive"}
        if _is_expired(b) or _budget_exhausted(b) or not _is_started(b):
            return {"ok": False, "reason": "not_currently_active"}
        cpi = float(b.get("cost_per_impression") or 0)
        await db.ad_banners.update_one(
            {"id": banner_id},
            {"$inc": {"total_impressions": 1, "amount_spent": cpi},
             "$set": {"updated_at": _now_iso()}},
        )
        await _bump_daily_stat(db, banner_id, "impressions", 1)
        if cpi:
            await _bump_daily_stat(db, banner_id, "spent", cpi)
        # Auto-pause if budget now exhausted
        fresh = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if fresh and _budget_exhausted(fresh):
            await db.ad_banners.update_one(
                {"id": banner_id},
                {"$set": {"active": False, "auto_paused_at": _now_iso(),
                          "auto_paused_reason": "budget_exhausted"}},
            )
        return {"ok": True}

    @api.post("/public/ad-banners/{banner_id}/click", tags=["Public — Ad Banners"])
    async def public_click(banner_id: str):
        b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        cpc = float(b.get("cost_per_click") or 0)
        await db.ad_banners.update_one(
            {"id": banner_id},
            {"$inc": {"total_clicks": 1, "amount_spent": cpc},
             "$set": {"updated_at": _now_iso()}},
        )
        await _bump_daily_stat(db, banner_id, "clicks", 1)
        if cpc:
            await _bump_daily_stat(db, banner_id, "spent", cpc)
        # Auto-pause if budget exhausted after this click
        fresh = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if fresh and _budget_exhausted(fresh):
            await db.ad_banners.update_one(
                {"id": banner_id},
                {"$set": {"active": False, "auto_paused_at": _now_iso(),
                          "auto_paused_reason": "budget_exhausted"}},
            )
        return {"ok": True, "target_url": (b.get("target_url") or "")}

    # =====================================================================
    # ADMIN — CRUD
    # =====================================================================
    @api.get("/admin/ad-banners", tags=["Admin — Ad Banners"])
    async def list_banners(user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        cursor = db.ad_banners.find({}, {"_id": 0}).sort("created_at", -1)
        items = await cursor.to_list(500)
        return {"items": [_admin_view(b) for b in items], "count": len(items)}

    @api.post("/admin/ad-banners", tags=["Admin — Ad Banners"])
    async def create_banner(payload: AdBannerPayload, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = user.get("client_id") or user.get("parent_client_id") or user["id"]
        banner_id = str(uuid.uuid4())
        slug = await _ensure_unique_slug(db, payload.name, banner_id)
        doc = {
            "id": banner_id,
            "tenant_id": tid,
            "name": payload.name.strip(),
            "advertiser_name": (payload.advertiser_name or "").strip(),
            "image_url": payload.image_url.strip(),
            "target_url": payload.target_url.strip(),
            "placement": payload.placement,
            "animated": payload.animated,
            "active": payload.active,
            "budget_amount": float(payload.budget_amount),
            "currency": payload.currency.upper(),
            "cost_per_impression": float(payload.cost_per_impression),
            "cost_per_click": float(payload.cost_per_click),
            "total_impressions": 0,
            "total_clicks": 0,
            "amount_spent": 0.0,
            "paid": payload.paid,
            "payment_date": payload.payment_date,
            "expiration_date": payload.expiration_date,
            "start_date": payload.start_date,
            "daily_stats": [],
            "notes": (payload.notes or "").strip(),
            # Iter38r-fix9y — Public stats share fields
            "slug": slug,
            "share_token": secrets.token_urlsafe(16),
            "created_by": user.get("email"),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.ad_banners.insert_one(doc.copy())
        return {"ok": True, "item": _admin_view(doc)}

    @api.put("/admin/ad-banners/{banner_id}", tags=["Admin — Ad Banners"])
    async def update_banner(banner_id: str, payload: AdBannerUpdate, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        d = payload.dict(exclude_unset=True)
        update: Dict[str, Any] = {"updated_at": _now_iso()}
        for k, v in d.items():
            if isinstance(v, str):
                v = v.strip()
            update[k] = v
        # Iter38r-fix9y — If the name changes, regenerate a unique slug
        if "name" in update and update["name"]:
            update["slug"] = await _ensure_unique_slug(db, update["name"], banner_id)
        res = await db.ad_banners.update_one({"id": banner_id}, {"$set": update})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        # Iter38r-fix9y — Backfill share_token on legacy rows that lack one
        fresh = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if fresh and not fresh.get("share_token"):
            await db.ad_banners.update_one(
                {"id": banner_id},
                {"$set": {"share_token": secrets.token_urlsafe(16)}},
            )
            fresh = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        return {"ok": True, "item": _admin_view(fresh)}

    @api.post("/admin/ad-banners/{banner_id}/rotate-token", tags=["Admin — Ad Banners"])
    async def rotate_share_token(banner_id: str, user: dict = Depends(get_current_user)):
        """Regenerate the share_token (invalidates previously shared URLs)."""
        _ensure_admin(user)
        new_token = secrets.token_urlsafe(16)
        res = await db.ad_banners.update_one(
            {"id": banner_id},
            {"$set": {"share_token": new_token, "updated_at": _now_iso()}},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        return {"ok": True, "share_token": new_token}

    @api.delete("/admin/ad-banners/{banner_id}", tags=["Admin — Ad Banners"])
    async def delete_banner(banner_id: str, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        res = await db.ad_banners.delete_one({"id": banner_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        return {"ok": True}

    @api.post("/admin/ad-banners/{banner_id}/toggle-paid", tags=["Admin — Ad Banners"])
    async def toggle_paid(banner_id: str, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        new_paid = not bool(b.get("paid"))
        update = {
            "paid": new_paid,
            "payment_date": _today_iso() if new_paid else None,
            "updated_at": _now_iso(),
        }
        await db.ad_banners.update_one({"id": banner_id}, {"$set": update})
        return {"ok": True, "paid": new_paid}

    @api.get("/admin/ad-banners/{banner_id}/stats", tags=["Admin — Ad Banners"])
    async def banner_stats(banner_id: str, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        daily = sorted((b.get("daily_stats") or []), key=lambda r: r.get("date") or "")
        ctr = 0.0
        imp = int(b.get("total_impressions") or 0)
        clicks = int(b.get("total_clicks") or 0)
        if imp > 0:
            ctr = round((clicks / imp) * 100, 2)
        return {
            "id": banner_id,
            "totals": {
                "impressions": imp,
                "clicks": clicks,
                "amount_spent": float(b.get("amount_spent") or 0),
                "ctr_pct": ctr,
            },
            "daily": daily,
            "budget_amount": float(b.get("budget_amount") or 0),
            "remaining_budget": max(0.0, float(b.get("budget_amount") or 0) - float(b.get("amount_spent") or 0)),
            "is_currently_active": _admin_view(b)["is_currently_active"],
        }

    @api.get("/public/ads-report/{slug}", tags=["Public — Ad Banners"])
    async def public_ads_report(slug: str, token: str = Query(..., min_length=1)):
        """Iter38r-fix9y — Public live report for an advertiser. Requires the
        slug + share_token couple (set when the banner is created and
        invalidatable via /admin/ad-banners/{id}/rotate-token). Returns only
        the fields safe to share with the advertiser (no costs the admin paid,
        no internal IDs)."""
        b = await db.ad_banners.find_one({"slug": slug}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        if (b.get("share_token") or "") != token:
            raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
        budget = float(b.get("budget_amount") or 0)
        spent = float(b.get("amount_spent") or 0)
        imp = int(b.get("total_impressions") or 0)
        clicks = int(b.get("total_clicks") or 0)
        ctr = round((clicks / imp) * 100, 2) if imp else 0.0
        daily = sorted((b.get("daily_stats") or []), key=lambda r: r.get("date") or "")
        return {
            "name": b.get("name"),
            "advertiser_name": b.get("advertiser_name") or "",
            "image_url": b.get("image_url"),
            "target_url": b.get("target_url"),
            "animated": bool(b.get("animated")),
            "placement": b.get("placement"),
            "currency": b.get("currency") or "XOF",
            "start_date": b.get("start_date"),
            "expiration_date": b.get("expiration_date"),
            "is_currently_active": _admin_view(b)["is_currently_active"],
            "totals": {
                "impressions": imp,
                "clicks": clicks,
                "ctr_pct": ctr,
                "amount_spent": spent,
            },
            "budget": {
                "amount": budget,
                "remaining": max(0.0, budget - spent),
                "progress_pct": round((spent / budget) * 100, 1) if budget else 0.0,
            },
            "daily": daily[-90:],  # last 90 days
            "generated_at": _now_iso(),
        }

    return api
