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
import os
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
    """Whitelist of fields safely exposed to anonymous visitors.

    Iter38r-fix9z6 — When A/B testing is enabled, randomly pick variant
    A or B with 50/50 weighting and return its `image_url`+`target_url`+
    `media_kind`. The chosen variant is echoed back as `active_variant`
    so the frontend can attribute the impression/click to the right side.
    """
    active_variant = "a"
    image_url = b.get("image_url")
    target_url = b.get("target_url")
    media_kind = b.get("media_kind") or "image"
    if b.get("ab_enabled") and (b.get("variant_b_image_url") or "").strip():
        if random.random() < 0.5:
            active_variant = "b"
            image_url = b.get("variant_b_image_url")
            target_url = b.get("variant_b_target_url") or b.get("target_url")
            media_kind = b.get("variant_b_media_kind") or "image"
    return {
        "id": b.get("id"),
        "name": b.get("name"),
        "image_url": image_url,
        "target_url": target_url,
        "advertiser_name": b.get("advertiser_name"),
        "animated": bool(b.get("animated", False)),
        "placement": b.get("placement"),
        # Iter38r-fix9z3 — Tells the frontend whether to render <img> or <video>
        "media_kind": media_kind,
        # Iter38r-fix9z5 — Display sizing
        "display_mode": b.get("display_mode") or "auto",
        "aspect_ratio": b.get("aspect_ratio") or "16:9",
        "width_pct": int(b.get("width_pct") or 100),
        "height_px": int(b.get("height_px") or 80),
        "width_px": int(b.get("width_px") or 728),
        "object_fit": b.get("object_fit") or "cover",
        # Iter38r-fix9z6 — A/B
        "active_variant": active_variant,
        "ab_enabled": bool(b.get("ab_enabled")),
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


# Iter38r-fix9z6 — Expiration reminder cron.
# Scans every banner with `reminder_email_enabled=True` and an `expiration_date`
# falling within the next `reminder_days_before` days (default 3). Sends ONE
# email per (banner, expiration_date, days_before) tuple — tracked via the
# `reminder_last_sent_for` field to ensure idempotency.
async def process_expiration_reminders(
    db,
    send_email_fn,
    public_base_url: str = "",
    today_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatch reminder emails for campaigns nearing expiration.

    Parameters
    ----------
    db : AsyncIOMotorDatabase
    send_email_fn : async callable(to: str, subject: str, html: str, text: str) -> bool
    public_base_url : Base URL for building the share link (e.g. https://sawalismartsystems.com)
    today_iso : Override today for tests (YYYY-MM-DD)
    """
    if today_iso:
        today = date.fromisoformat(today_iso)
    else:
        today = datetime.now(timezone.utc).date()

    cursor = db.ad_banners.find(
        {
            "reminder_email_enabled": True,
            "advertiser_email": {"$nin": [None, ""]},
            "expiration_date": {"$nin": [None, ""]},
        },
        {"_id": 0},
    )
    sent: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errored: List[Dict[str, Any]] = []
    async for b in cursor:
        try:
            exp = date.fromisoformat((b.get("expiration_date") or "").strip()[:10])
        except (ValueError, TypeError):
            continue
        days_until = (exp - today).days
        threshold = int(b.get("reminder_days_before") or 3)
        # Only fire when the expiration is within [0, threshold] days from today
        # (covers the day-of-expiration too).
        if days_until < 0 or days_until > threshold:
            continue
        marker = f"{b.get('expiration_date')}|{threshold}"
        if (b.get("reminder_last_sent_for") or "") == marker:
            skipped.append({"id": b.get("id"), "reason": "already_sent", "marker": marker})
            continue
        # Build email content
        share_path = "/ads/{}?token={}".format(b.get("slug") or "", b.get("share_token") or "")
        share_link = f"{public_base_url.rstrip('/')}{share_path}" if public_base_url else share_path
        currency = b.get("currency") or "XOF"
        budget = float(b.get("budget_amount") or 0)
        spent = float(b.get("amount_spent") or 0)
        remaining = max(0.0, budget - spent)
        imp = int(b.get("total_impressions") or 0)
        clicks = int(b.get("total_clicks") or 0)
        ctr = round((clicks / imp) * 100, 2) if imp else 0.0
        subject = (
            f"Votre campagne « {b.get('name')} » expire "
            + ("aujourd'hui" if days_until == 0 else f"dans {days_until} jour{'s' if days_until > 1 else ''}")
        )
        adv = (b.get("advertiser_name") or "").strip() or "Cher annonceur"
        text = (
            f"Bonjour {adv},\n\n"
            f"Votre campagne publicitaire « {b.get('name')} » sur SAWALI "
            f"{'expire aujourd''hui' if days_until == 0 else f'expire dans {days_until} jour(s)'} "
            f"(le {b.get('expiration_date')}).\n\n"
            f"Bilan en cours :\n"
            f"  • Affichages : {imp:,}\n"
            f"  • Clics : {clicks:,}\n"
            f"  • CTR : {ctr}%\n"
            f"  • Budget : {int(budget):,} {currency} (restant : {int(remaining):,} {currency})\n\n"
            f"Vous pouvez consulter les statistiques détaillées et demander un renouvellement "
            f"en un clic ici :\n{share_link}\n\n"
            f"À très bientôt,\nL'équipe SAWALI Smart Systems"
        ).replace(",", " ")  # FR thousand separator
        html = f"""
        <div style="font-family:system-ui,sans-serif;max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:14px;border:1px solid #e2e8f0">
          <h1 style="font-size:18px;color:#0f172a;margin:0 0 6px">Votre campagne expire bientôt</h1>
          <p style="color:#475569;margin:0 0 16px">Bonjour {adv}, votre campagne <strong>{b.get('name')}</strong> sur SAWALI {'expire aujourd&#39;hui' if days_until == 0 else f'expire dans <strong>{days_until} jour(s)</strong>'} (le {b.get('expiration_date')}).</p>
          <table style="width:100%;font-size:13px;border-collapse:collapse;margin-bottom:16px">
            <tr><td style="padding:6px 0;color:#64748b">Affichages</td><td style="text-align:right;font-variant-numeric:tabular-nums"><strong>{imp:,}</strong></td></tr>
            <tr><td style="padding:6px 0;color:#64748b">Clics</td><td style="text-align:right;font-variant-numeric:tabular-nums"><strong>{clicks:,}</strong></td></tr>
            <tr><td style="padding:6px 0;color:#64748b">CTR</td><td style="text-align:right"><strong>{ctr}%</strong></td></tr>
            <tr><td style="padding:6px 0;color:#64748b">Budget restant</td><td style="text-align:right;font-variant-numeric:tabular-nums"><strong>{int(remaining):,} {currency}</strong></td></tr>
          </table>
          <a href="{share_link}" style="display:inline-block;background:#c026d3;color:#fff;padding:11px 18px;border-radius:10px;text-decoration:none;font-weight:600">Voir les statistiques + Renouveler</a>
          <p style="color:#94a3b8;font-size:11px;margin-top:18px">SAWALI Smart Systems · Régie publicitaire</p>
        </div>
        """.replace("{:,}", "{}")
        try:
            ok = await send_email_fn(b.get("advertiser_email"), subject, html, text)
            if ok:
                await db.ad_banners.update_one(
                    {"id": b.get("id")},
                    {"$set": {
                        "reminder_last_sent_for": marker,
                        "reminder_last_sent_at": _now_iso(),
                    }},
                )
                sent.append({"id": b.get("id"), "to": b.get("advertiser_email"), "days_until": days_until})
            else:
                errored.append({"id": b.get("id"), "reason": "send_email_returned_false"})
        except Exception as exc:  # noqa: BLE001
            errored.append({"id": b.get("id"), "reason": str(exc)})

    return {"sent": sent, "skipped": skipped, "errored": errored, "ran_at": _now_iso()}


class AdBannerPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    advertiser_name: str = Field("", max_length=120)
    image_url: str = Field(..., min_length=4, max_length=600)
    # Iter38r-fix9z3 — Explicit media kind so /api/files/{id} URLs (no extension)
    # are correctly rendered as <img> or <video> on the frontend.
    media_kind: str = Field("image", pattern="^(image|video)$")
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
    # Iter38r-fix9z5 — Display sizing controls.
    # display_mode: auto (responsive 64/80px), ratio (% width × aspect), percentage (% width + fixed height), fixed (fixed px)
    display_mode: str = Field("auto", pattern="^(auto|ratio|percentage|fixed)$")
    aspect_ratio: str = Field("16:9", max_length=12)  # only used when display_mode=ratio. Format "W:H"
    width_pct: int = Field(100, ge=10, le=100)         # used in percentage / ratio modes
    height_px: int = Field(80, ge=20, le=1200)         # used in percentage / fixed modes
    width_px: int = Field(728, ge=50, le=2400)         # used in fixed mode
    object_fit: str = Field("cover", pattern="^(cover|contain|fill)$")
    # Iter38r-fix9z6 — A/B testing (2-variant rotation). When ab_enabled,
    # the rotation picks variant_a (image_url/target_url) or variant_b
    # (variant_b_*) with 50/50 weighting. Per-variant counters live in
    # total_impressions_a/b + total_clicks_a/b.
    ab_enabled: bool = False
    variant_b_image_url: str = Field("", max_length=600)
    variant_b_media_kind: str = Field("image", pattern="^(image|video)$")
    variant_b_target_url: str = Field("", max_length=600)
    # Iter38r-fix9z6 — Optional advertiser contact (used by the renewal
    # reminder email cron) + reminder toggle.
    advertiser_email: str = Field("", max_length=200)
    advertiser_phone: str = Field("", max_length=40)
    reminder_email_enabled: bool = True
    reminder_days_before: int = Field(3, ge=1, le=30)


class AdBannerUpdate(BaseModel):
    name: Optional[str] = None
    advertiser_name: Optional[str] = None
    image_url: Optional[str] = None
    media_kind: Optional[str] = Field(None, pattern="^(image|video)$")
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
    # Iter38r-fix9z5 — Display sizing controls (all optional on update)
    display_mode: Optional[str] = Field(None, pattern="^(auto|ratio|percentage|fixed)$")
    aspect_ratio: Optional[str] = Field(None, max_length=12)
    width_pct: Optional[int] = Field(None, ge=10, le=100)
    height_px: Optional[int] = Field(None, ge=20, le=1200)
    width_px: Optional[int] = Field(None, ge=50, le=2400)
    object_fit: Optional[str] = Field(None, pattern="^(cover|contain|fill)$")
    # Iter38r-fix9z6 — A/B testing + advertiser contact + reminder
    ab_enabled: Optional[bool] = None
    variant_b_image_url: Optional[str] = None
    variant_b_media_kind: Optional[str] = Field(None, pattern="^(image|video)$")
    variant_b_target_url: Optional[str] = None
    advertiser_email: Optional[str] = None
    advertiser_phone: Optional[str] = None
    reminder_email_enabled: Optional[bool] = None
    reminder_days_before: Optional[int] = Field(None, ge=1, le=30)


# Iter38r-fix9z5 — Renewal request payload (must be at module scope so
# FastAPI recognises it as a request body, not a query parameter).
class RenewRequestPayload(BaseModel):
    contact_name: str = Field("", max_length=120)
    contact_email: str = Field("", max_length=200)
    contact_phone: str = Field("", max_length=40)
    new_budget: float = Field(0, ge=0)
    target_duration_days: int = Field(0, ge=0, le=730)
    message: str = Field("", max_length=2000)


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
    async def public_impression(banner_id: str, variant: str = Query("a", pattern="^(a|b)$")):
        b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        if not b.get("active"):
            return {"ok": False, "reason": "inactive"}
        if _is_expired(b) or _budget_exhausted(b) or not _is_started(b):
            return {"ok": False, "reason": "not_currently_active"}
        cpi = float(b.get("cost_per_impression") or 0)
        # Iter38r-fix9z6 — Bump per-variant + global counters
        inc = {"total_impressions": 1, "amount_spent": cpi, f"total_impressions_{variant}": 1}
        await db.ad_banners.update_one(
            {"id": banner_id},
            {"$inc": inc, "$set": {"updated_at": _now_iso()}},
        )
        await _bump_daily_stat(db, banner_id, "impressions", 1)
        await _bump_daily_stat(db, banner_id, f"impressions_{variant}", 1)
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
    async def public_click(banner_id: str, variant: str = Query("a", pattern="^(a|b)$")):
        b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        cpc = float(b.get("cost_per_click") or 0)
        inc = {"total_clicks": 1, "amount_spent": cpc, f"total_clicks_{variant}": 1}
        await db.ad_banners.update_one(
            {"id": banner_id},
            {"$inc": inc, "$set": {"updated_at": _now_iso()}},
        )
        await _bump_daily_stat(db, banner_id, "clicks", 1)
        await _bump_daily_stat(db, banner_id, f"clicks_{variant}", 1)
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
        # Iter38r-fix9z6 — Return the proper target url for the variant
        if variant == "b" and (b.get("variant_b_target_url") or "").strip():
            target = b.get("variant_b_target_url")
        else:
            target = b.get("target_url") or ""
        return {"ok": True, "target_url": target}

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
            "media_kind": payload.media_kind,
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
            # Iter38r-fix9z5 — Display sizing
            "display_mode": payload.display_mode,
            "aspect_ratio": payload.aspect_ratio.strip() or "16:9",
            "width_pct": int(payload.width_pct),
            "height_px": int(payload.height_px),
            "width_px": int(payload.width_px),
            "object_fit": payload.object_fit,
            # Iter38r-fix9z6 — A/B + reminders
            "ab_enabled": bool(payload.ab_enabled),
            "variant_b_image_url": (payload.variant_b_image_url or "").strip(),
            "variant_b_media_kind": payload.variant_b_media_kind,
            "variant_b_target_url": (payload.variant_b_target_url or "").strip(),
            "total_impressions_a": 0,
            "total_clicks_a": 0,
            "total_impressions_b": 0,
            "total_clicks_b": 0,
            "advertiser_email": (payload.advertiser_email or "").strip(),
            "advertiser_phone": (payload.advertiser_phone or "").strip(),
            "reminder_email_enabled": bool(payload.reminder_email_enabled),
            "reminder_days_before": int(payload.reminder_days_before),
            "reminder_last_sent_for": None,  # tracks (expiration_date, days_before) couple sent
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

    # Iter38r-fix9z — One-shot migration: strip any saved absolute origin from
    # image_url / target_url so that the same DB row works in both preview and
    # production. Detects URLs starting with http(s):// and ending with the
    # backend's served path "/api/files/...".
    @api.post("/admin/ad-banners/fix-urls", tags=["Admin — Ad Banners"])
    async def fix_absolute_urls(user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        fixed = 0
        cursor = db.ad_banners.find({}, {"_id": 0, "id": 1, "image_url": 1, "target_url": 1})
        rows = await cursor.to_list(2000)
        for r in rows:
            patch = {}
            for field in ("image_url", "target_url"):
                v = (r.get(field) or "")
                # Match: protocol://host/api/files/XXX  →  /api/files/XXX
                m = re.match(r"^https?://[^/]+(/api/files/.+)$", v)
                if m:
                    patch[field] = m.group(1)
            if patch:
                patch["updated_at"] = _now_iso()
                await db.ad_banners.update_one({"id": r["id"]}, {"$set": patch})
                fixed += 1
        return {"ok": True, "fixed_banners": fixed, "scanned": len(rows)}

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
        # Iter38r-fix9z6 — A/B breakdown + winner detection (best CTR with ≥30 impressions)
        imp_a = int(b.get("total_impressions_a") or 0)
        imp_b = int(b.get("total_impressions_b") or 0)
        clk_a = int(b.get("total_clicks_a") or 0)
        clk_b = int(b.get("total_clicks_b") or 0)
        ctr_a = round((clk_a / imp_a) * 100, 2) if imp_a else 0.0
        ctr_b = round((clk_b / imp_b) * 100, 2) if imp_b else 0.0
        winner = None
        if imp_a >= 30 and imp_b >= 30 and ctr_a != ctr_b:
            winner = "a" if ctr_a > ctr_b else "b"
        return {
            "id": banner_id,
            "totals": {
                "impressions": imp,
                "clicks": clicks,
                "amount_spent": float(b.get("amount_spent") or 0),
                "ctr_pct": ctr,
            },
            "ab": {
                "enabled": bool(b.get("ab_enabled")),
                "variant_a": {"impressions": imp_a, "clicks": clk_a, "ctr_pct": ctr_a},
                "variant_b": {"impressions": imp_b, "clicks": clk_b, "ctr_pct": ctr_b},
                "winner": winner,
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
            "media_kind": b.get("media_kind") or "image",
            "animated": bool(b.get("animated")),
            "placement": b.get("placement"),
            "currency": b.get("currency") or "XOF",
            "start_date": b.get("start_date"),
            "expiration_date": b.get("expiration_date"),
            "is_currently_active": _admin_view(b)["is_currently_active"],
            # Iter38r-fix9z5 — Sizing controls echoed back so the preview in
            # the public report matches the live banner.
            "display_mode": b.get("display_mode") or "auto",
            "aspect_ratio": b.get("aspect_ratio") or "16:9",
            "width_pct": int(b.get("width_pct") or 100),
            "height_px": int(b.get("height_px") or 80),
            "width_px": int(b.get("width_px") or 728),
            "object_fit": b.get("object_fit") or "cover",
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

    # Iter38r-fix9z5 — "Renew campaign" endpoint. Lets the advertiser
    # request a renewal of their campaign from the public report page,
    # validated via slug+share_token. Creates a row in `ad_renewal_requests`
    # so the admin sees it in their inbox without exposing internal IDs.
    @api.post("/public/ads-report/{slug}/renew", tags=["Public — Ad Banners"])
    async def public_renew_campaign(slug: str, payload: RenewRequestPayload, token: str = Query(..., min_length=1)):
        b = await db.ad_banners.find_one({"slug": slug}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        if (b.get("share_token") or "") != token:
            raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
        if not (payload.contact_email or payload.contact_phone):
            raise HTTPException(status_code=400, detail="Email ou téléphone requis")
        doc = {
            "id": str(uuid.uuid4()),
            "banner_id": b.get("id"),
            "banner_name": b.get("name"),
            "advertiser_name": b.get("advertiser_name") or "",
            "contact_name": payload.contact_name.strip(),
            "contact_email": payload.contact_email.strip(),
            "contact_phone": payload.contact_phone.strip(),
            "current_budget": float(b.get("budget_amount") or 0),
            "current_spent": float(b.get("amount_spent") or 0),
            "new_budget": float(payload.new_budget),
            "target_duration_days": int(payload.target_duration_days),
            "message": payload.message.strip(),
            "currency": b.get("currency") or "XOF",
            "tenant_id": b.get("tenant_id"),
            "status": "new",
            "created_at": _now_iso(),
        }
        await db.ad_renewal_requests.insert_one(doc.copy())
        return {"ok": True, "id": doc["id"]}

    @api.get("/admin/ad-renewal-requests", tags=["Admin — Ad Banners"])
    async def list_renewal_requests(user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        cursor = db.ad_renewal_requests.find({}, {"_id": 0}).sort("created_at", -1)
        items = await cursor.to_list(500)
        return {"items": items, "count": len(items)}

    @api.post("/admin/ad-renewal-requests/{req_id}/mark-handled", tags=["Admin — Ad Banners"])
    async def mark_renewal_handled(req_id: str, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        res = await db.ad_renewal_requests.update_one(
            {"id": req_id},
            {"$set": {"status": "handled", "handled_by": user.get("email"), "handled_at": _now_iso()}},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        return {"ok": True}

    # Iter38r-fix9z6 — Manual trigger for the expiration-reminder cron.
    # Lets admins fire reminders on-demand (handy for first deploy or testing).
    @api.post("/admin/ad-banners/run-reminder-cron", tags=["Admin — Ad Banners"])
    async def run_reminder_cron_now(
        send_email_fn=Body(None),  # noqa: B008 — injected via app.state
        user: dict = Depends(get_current_user),
    ):
        _ensure_admin(user)
        # Import inside the request to avoid circular import at startup
        try:
            from email_service import send_email as _send_email
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Module email indisponible : {exc}")
        public_base = (
            (await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}).get("public_base_url")
            or os.environ.get("PUBLIC_BASE_URL")
            or os.environ.get("REACT_APP_BACKEND_URL")
            or ""
        )
        res = await process_expiration_reminders(
            db,
            send_email_fn=_send_email,
            public_base_url=public_base,
        )
        return res

    return api
