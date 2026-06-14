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

import asyncio
import logging
import os
import random
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, date, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
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
    # Iter40-modal-ab — A/B on modal_frequency: variant B can override.
    # When the random variant pick lands on B and a variant_b_modal_frequency is
    # defined, use it; otherwise fall back to the global modal_frequency.
    modal_frequency = b.get("modal_frequency") or "session"
    if b.get("ab_enabled") and (b.get("variant_b_image_url") or "").strip():
        if random.random() < 0.5:
            active_variant = "b"
            image_url = b.get("variant_b_image_url")
            target_url = b.get("variant_b_target_url") or b.get("target_url")
            media_kind = b.get("variant_b_media_kind") or "image"
            if (b.get("variant_b_modal_frequency") or "").strip():
                modal_frequency = b.get("variant_b_modal_frequency")
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
        # Iter40-modal — Modal display frequency (consumed by PublicAdModal)
        "modal_frequency": modal_frequency,
    }


def _modal_variant_stats(b: Dict[str, Any], variant: str) -> Dict[str, Any]:
    """Iter40-modal-ab — Modal-channel counters for a single A/B variant."""
    imp = int(b.get(f"modal_impressions_{variant}") or 0)
    clk = int(b.get(f"modal_clicks_{variant}") or 0)
    return {
        "impressions": imp,
        "clicks": clk,
        "ctr_pct": round((clk / imp) * 100, 2) if imp else 0.0,
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
    send_whatsapp_fn=None,
) -> Dict[str, Any]:
    """Dispatch reminder emails (and optionally WhatsApp messages) for
    campaigns nearing expiration.

    Parameters
    ----------
    db : AsyncIOMotorDatabase
    send_email_fn : async callable(to: str, subject: str, html: str, text: str) -> bool
    public_base_url : Base URL for building the share link (e.g. https://sawalismartsystems.com)
    today_iso : Override today for tests (YYYY-MM-DD)
    send_whatsapp_fn : Optional async callable(to: str, text: str) -> dict | bool
        When provided AND a banner has `reminder_wa_enabled=True` AND a valid
        `advertiser_phone`, a WhatsApp message is sent in addition to the email.
    """
    if today_iso:
        today = date.fromisoformat(today_iso)
    else:
        today = datetime.now(timezone.utc).date()

    # Iter38r-fix9z7 — Include WA-only-enabled banners (no email required if WA is on)
    cursor = db.ad_banners.find(
        {
            "$or": [
                {"reminder_email_enabled": True},
                {"reminder_wa_enabled": True},
            ],
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
        # Iter38r-fix9z7 — Track per-channel delivery (email + WhatsApp).
        delivered_channels: List[str] = []
        email_to = (b.get("advertiser_email") or "").strip()
        wa_to = (b.get("advertiser_phone") or "").strip()

        # Send email if enabled + recipient available
        if b.get("reminder_email_enabled") and email_to:
            try:
                ok = await send_email_fn(email_to, subject, html, text)
                if ok:
                    delivered_channels.append("email")
                else:
                    errored.append({"id": b.get("id"), "channel": "email", "reason": "send_email_returned_false"})
            except Exception as exc:  # noqa: BLE001
                errored.append({"id": b.get("id"), "channel": "email", "reason": str(exc)})

        # Send WhatsApp if enabled + sender function provided + phone available
        if b.get("reminder_wa_enabled") and send_whatsapp_fn is not None and wa_to:
            wa_text = (
                f"📊 SAWALI — Votre campagne « {b.get('name')} » "
                + ("expire aujourd'hui" if days_until == 0 else f"expire dans {days_until} jour(s)")
                + f" (le {b.get('expiration_date')}).\n\n"
                f"Bilan en cours :\n"
                f"• Affichages : {imp}\n"
                f"• Clics : {clicks}\n"
                f"• CTR : {ctr}%\n"
                f"• Budget restant : {int(remaining)} {currency}\n\n"
                f"Consultez votre rapport et demandez un renouvellement en 1 clic :\n{share_link}"
            )
            try:
                wa_res = await send_whatsapp_fn(wa_to, wa_text)
                # Accept both bool and dict returns (consistent with _wa_send_text)
                if wa_res:
                    delivered_channels.append("wa")
                else:
                    errored.append({"id": b.get("id"), "channel": "wa", "reason": "send_wa_returned_falsy"})
            except Exception as exc:  # noqa: BLE001
                errored.append({"id": b.get("id"), "channel": "wa", "reason": str(exc)})

        if delivered_channels:
            await db.ad_banners.update_one(
                {"id": b.get("id")},
                {"$set": {
                    "reminder_last_sent_for": marker,
                    "reminder_last_sent_at": _now_iso(),
                    "reminder_last_channels": delivered_channels,
                }},
            )
            sent.append({
                "id": b.get("id"),
                "to_email": email_to if "email" in delivered_channels else None,
                "to_wa": wa_to if "wa" in delivered_channels else None,
                "channels": delivered_channels,
                "days_until": days_until,
            })

    return {"sent": sent, "skipped": skipped, "errored": errored, "ran_at": _now_iso()}


class AdBannerPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    advertiser_name: str = Field("", max_length=120)
    image_url: str = Field(..., min_length=4, max_length=600)
    # Iter38r-fix9z3 — Explicit media kind so /api/files/{id} URLs (no extension)
    # are correctly rendered as <img> or <video> on the frontend.
    media_kind: str = Field("image", pattern="^(image|video)$")
    target_url: str = Field(..., min_length=4, max_length=600)
    placement: str = Field("both", pattern="^(public|portal|both|public_modal)$")
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
    # Iter40-modal — Frequency of modal display (only used when placement=public_modal)
    # session: once per session (default), daily: once per day, always: every page load
    modal_frequency: str = Field("session", pattern="^(session|daily|always)$")
    # Iter40-modal-ab — Optional per-variant override of modal_frequency when
    # A/B testing is enabled. Empty = use global modal_frequency for both variants.
    variant_b_modal_frequency: str = Field("", max_length=12)
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
    # Iter38r-fix9z7 — WhatsApp reminder (in addition to email)
    reminder_wa_enabled: bool = False
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
    # Iter40-modal — Modal frequency
    modal_frequency: Optional[str] = Field(None, pattern="^(session|daily|always)$")
    variant_b_modal_frequency: Optional[str] = Field(None, max_length=12)
    # Iter38r-fix9z6 — A/B testing + advertiser contact + reminder
    ab_enabled: Optional[bool] = None
    variant_b_image_url: Optional[str] = None
    variant_b_media_kind: Optional[str] = Field(None, pattern="^(image|video)$")
    variant_b_target_url: Optional[str] = None
    advertiser_email: Optional[str] = None
    advertiser_phone: Optional[str] = None
    reminder_email_enabled: Optional[bool] = None
    reminder_wa_enabled: Optional[bool] = None
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


# Iter38r-fix9z8 — Self-service advertiser portal payloads (module scope so
# FastAPI body inference works correctly).
class CheckoutPayload(BaseModel):
    amount_xof: float = Field(..., gt=0)
    duration_days: int = Field(30, ge=1, le=730)
    origin_url: str = Field(..., min_length=8, max_length=500)
    contact_email: str = Field("", max_length=200)
    contact_name: str = Field("", max_length=120)


class MediaUpdatePayload(BaseModel):
    image_url: Optional[str] = Field(None, max_length=600)
    media_kind: Optional[str] = Field(None, pattern="^(image|video)$")
    target_url: Optional[str] = Field(None, max_length=600)
    variant_b_image_url: Optional[str] = Field(None, max_length=600)
    variant_b_media_kind: Optional[str] = Field(None, pattern="^(image|video)$")
    variant_b_target_url: Optional[str] = Field(None, max_length=600)


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


def setup_ad_banners_routes(app, db, get_current_user, wa_send_text=None):
    api: APIRouter = app

    def _ensure_admin(user: dict) -> None:
        if (user or {}).get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    # =====================================================================
    # Iter38r-fix9z7 — Live admin dashboard hub: broadcasts every impression
    # and click to all connected admin WebSocket clients in real time.
    # =====================================================================
    class AdLiveHub:
        def __init__(self):
            self._conns: List[WebSocket] = []
            self._lock = asyncio.Lock()

        async def connect(self, ws: WebSocket) -> None:
            async with self._lock:
                self._conns.append(ws)

        async def disconnect(self, ws: WebSocket) -> None:
            async with self._lock:
                try:
                    self._conns.remove(ws)
                except ValueError:
                    pass

        async def broadcast(self, payload: dict) -> None:
            dead = []
            for ws in list(self._conns):
                try:
                    await ws.send_json(payload)
                except Exception:  # noqa: BLE001
                    dead.append(ws)
            for ws in dead:
                await self.disconnect(ws)

    live_hub = AdLiveHub()

    async def _broadcast_event(event: str, banner_id: str, variant: str, banner: Dict[str, Any]):
        try:
            await live_hub.broadcast({
                "event": event,
                "banner_id": banner_id,
                "name": banner.get("name"),
                "advertiser_name": banner.get("advertiser_name") or "",
                "variant": variant,
                "total_impressions": int(banner.get("total_impressions") or 0),
                "total_clicks": int(banner.get("total_clicks") or 0),
                "total_impressions_a": int(banner.get("total_impressions_a") or 0),
                "total_impressions_b": int(banner.get("total_impressions_b") or 0),
                "total_clicks_a": int(banner.get("total_clicks_a") or 0),
                "total_clicks_b": int(banner.get("total_clicks_b") or 0),
                "amount_spent": float(banner.get("amount_spent") or 0),
                "ts": _now_iso(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("ad live broadcast failed: %s", exc)

    # =====================================================================
    # PUBLIC — banner rotation + tracking
    # =====================================================================
    @api.get("/public/ad-banners/active", tags=["Public — Ad Banners"])
    async def public_pick_banner(placement: str = Query("public", pattern="^(public|portal|public_modal)$")):
        """Return ONE active banner suitable for `placement` (weighted random).
        Returns 204 No Content when no banner is currently active.

        Iter40-modal — When placement="public_modal", banners must be EXACTLY
        of placement "public_modal" (these are reserved for the random popup
        modal shown on public-page load — not mixed with the top-of-page slot)."""
        if placement == "public_modal":
            q = {"active": True, "placement": "public_modal"}
        else:
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

    # Iter40-modal — Public config endpoint exposed to anonymous visitors.
    # Returns the global daily cap so PublicAdModal can enforce a maximum
    # number of popup modals per visitor across all `public_modal` banners.
    @api.get("/public/ad-banners/config", tags=["Public — Ad Banners"])
    async def public_ad_config():
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        cap = s.get("modal_global_cap_per_day")
        if cap is None:
            cap = 2  # default
        try:
            cap = max(0, min(20, int(cap)))
        except (TypeError, ValueError):
            cap = 2
        return {"modal_global_cap_per_day": cap}

    @api.post("/public/ad-banners/{banner_id}/impression", tags=["Public — Ad Banners"])
    async def public_impression(
        banner_id: str,
        variant: str = Query("a", pattern="^(a|b)$"),
        modal: int = Query(0, ge=0, le=1),
    ):
        b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        if not b.get("active"):
            return {"ok": False, "reason": "inactive"}
        if _is_expired(b) or _budget_exhausted(b) or not _is_started(b):
            return {"ok": False, "reason": "not_currently_active"}
        cpi = float(b.get("cost_per_impression") or 0)
        # Iter38r-fix9z6 — Bump per-variant + global counters
        # Iter40-modal — When modal=1, also bump modal_impressions
        inc = {"total_impressions": 1, "amount_spent": cpi, f"total_impressions_{variant}": 1}
        if modal:
            inc["modal_impressions"] = 1
            inc[f"modal_impressions_{variant}"] = 1
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
        # Iter38r-fix9z7 — Broadcast to live admin dashboard
        if fresh:
            await _broadcast_event("impression", banner_id, variant, fresh)
        return {"ok": True}

    @api.post("/public/ad-banners/{banner_id}/click", tags=["Public — Ad Banners"])
    async def public_click(
        banner_id: str,
        variant: str = Query("a", pattern="^(a|b)$"),
        modal: int = Query(0, ge=0, le=1),
    ):
        b = await db.ad_banners.find_one({"id": banner_id}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        cpc = float(b.get("cost_per_click") or 0)
        inc = {"total_clicks": 1, "amount_spent": cpc, f"total_clicks_{variant}": 1}
        if modal:
            inc["modal_clicks"] = 1
            inc[f"modal_clicks_{variant}"] = 1
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
        # Iter38r-fix9z7 — Broadcast to live admin dashboard
        if fresh:
            await _broadcast_event("click", banner_id, variant, fresh)
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
            # Iter40-modal — Modal display frequency + dedicated counters
            "modal_frequency": payload.modal_frequency,
            "variant_b_modal_frequency": (payload.variant_b_modal_frequency or "").strip(),
            "modal_impressions": 0,
            "modal_clicks": 0,
            # Iter40-modal-ab — Per-variant modal counters
            "modal_impressions_a": 0,
            "modal_clicks_a": 0,
            "modal_impressions_b": 0,
            "modal_clicks_b": 0,
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
            "reminder_wa_enabled": bool(payload.reminder_wa_enabled),
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
            # Iter40-modal — Dedicated modal counters (CTR included)
            "modal": {
                "impressions": int(b.get("modal_impressions") or 0),
                "clicks": int(b.get("modal_clicks") or 0),
                "ctr_pct": (
                    round((int(b.get("modal_clicks") or 0) / int(b.get("modal_impressions") or 0)) * 100, 2)
                    if int(b.get("modal_impressions") or 0) else 0.0
                ),
                "frequency": b.get("modal_frequency") or "session",
                # Iter40-modal-ab — Per-variant breakdown for the modal channel
                "variant_a": _modal_variant_stats(b, "a"),
                "variant_b": _modal_variant_stats(b, "b"),
                "variant_b_frequency": b.get("variant_b_modal_frequency") or "",
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
        """Iter38r-fix9y — Rapport public en direct pour un annonceur. Nécessite le
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
            send_whatsapp_fn=wa_send_text,
        )
        return res

    # =====================================================================
    # Iter38r-fix9z8 — Self-service advertiser portal
    # Public endpoints (slug + share_token authenticated) that let the
    # advertiser:
    #   • Pay online for a campaign renewal via Stripe Checkout
    #   • Update their media (image/video) + target URL
    # Both endpoints validate slug+token like the public report endpoint.
    # =====================================================================
    XOF_TO_EUR = 655.957  # CFA franc — fixed parity

    @api.post("/public/ads-report/{slug}/checkout", tags=["Public — Ad Banners"])
    async def public_create_checkout(slug: str, payload: CheckoutPayload, token: str = Query(..., min_length=1)):
        """Crée une session Stripe Checkout pour le renouvellement de la campagne.

        Idempotent w.r.t. session_id (returned to the caller). On success
        webhook/poll-status will extend the banner expiration_date by
        `duration_days` and top up `budget_amount` by `amount_xof`.
        """
        b = await db.ad_banners.find_one({"slug": slug}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        if (b.get("share_token") or "") != token:
            raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
        try:
            from emergentintegrations.payments.stripe.checkout import (
                StripeCheckout,
                CheckoutSessionRequest,
            )
        except ImportError as exc:
            logger.error("[ads] emergentintegrations not installed: %s", exc)
            raise HTTPException(status_code=500, detail="Module paiement indisponible") from exc

        # Resolve Stripe API key from env (same source as payments_stripe.py)
        api_key = (
            os.environ.get("STRIPE_API_KEY")
            or os.environ.get("STRIPE_SECRET_KEY")
            or ""
        )
        if not api_key:
            raise HTTPException(status_code=500, detail="Stripe non configuré")

        # XOF → EUR for Stripe (XOF is not a supported currency on Stripe)
        amount_eur = round(payload.amount_xof / XOF_TO_EUR, 2)
        if amount_eur < 0.50:
            amount_eur = 0.50

        origin = payload.origin_url.rstrip("/")
        success_url = f"{origin}/ads/{slug}?token={token}&session_id={{CHECKOUT_SESSION_ID}}&renew=ok"
        cancel_url = f"{origin}/ads/{slug}?token={token}&renew=canceled"
        webhook_url = f"{origin}/api/webhook/stripe"
        client = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

        metadata = {
            "kind": "ad_renewal",
            "banner_id": b.get("id"),
            "slug": slug,
            "amount_xof": str(payload.amount_xof),
            "duration_days": str(payload.duration_days),
            "contact_email": payload.contact_email,
        }
        req = CheckoutSessionRequest(
            amount=amount_eur, currency="eur",
            success_url=success_url, cancel_url=cancel_url,
            metadata=metadata,
        )
        try:
            session = await client.create_checkout_session(req)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[ads] create_checkout_session failed")
            raise HTTPException(status_code=502, detail=f"Erreur Stripe : {exc}") from exc

        await db.ad_renewals.insert_one({
            "id": str(uuid.uuid4()),
            "banner_id": b.get("id"),
            "slug": slug,
            "session_id": session.session_id,
            "amount_xof": float(payload.amount_xof),
            "amount_eur": amount_eur,
            "duration_days": int(payload.duration_days),
            "contact_email": payload.contact_email.strip(),
            "contact_name": payload.contact_name.strip(),
            "currency": "eur",
            "payment_status": "initiated",
            "renewal_applied": False,
            "metadata": metadata,
            "created_at": _now_iso(),
        })
        return {"url": session.url, "session_id": session.session_id}

    @api.get("/public/ads-report/{slug}/payment-status/{session_id}", tags=["Public — Ad Banners"])
    async def public_payment_status(slug: str, session_id: str, token: str = Query(..., min_length=1)):
        """Poll endpoint. Confirms the Stripe session and, on first paid
        observation, atomically extends the campaign's expiration + budget."""
        renewal = await db.ad_renewals.find_one({"slug": slug, "session_id": session_id}, {"_id": 0})
        if not renewal:
            raise HTTPException(status_code=404, detail="Transaction introuvable")
        b = await db.ad_banners.find_one({"slug": slug}, {"_id": 0})
        if not b or (b.get("share_token") or "") != token:
            raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
        # Already finalised → return cached
        if renewal.get("payment_status") == "paid":
            return {
                "payment_status": "paid",
                "renewal_applied": bool(renewal.get("renewal_applied")),
                "amount_xof": renewal.get("amount_xof"),
                "duration_days": renewal.get("duration_days"),
            }
        try:
            from emergentintegrations.payments.stripe.checkout import StripeCheckout
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="Module paiement indisponible") from exc
        api_key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY") or ""
        if not api_key:
            raise HTTPException(status_code=500, detail="Stripe non configuré")
        client = StripeCheckout(api_key=api_key, webhook_url="")
        try:
            status = await client.get_checkout_status(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[ads] get_checkout_status failed")
            raise HTTPException(status_code=502, detail=f"Erreur Stripe : {exc}") from exc
        upd = {
            "payment_status": status.payment_status,
            "stripe_status": status.status,
            "updated_at": _now_iso(),
        }
        applied = renewal.get("renewal_applied", False)
        if status.payment_status == "paid" and not applied:
            # Atomic CAS — only the first observer flips renewal_applied
            cas = await db.ad_renewals.update_one(
                {"session_id": session_id, "renewal_applied": {"$ne": True}},
                {"$set": {"renewal_applied": True, "applied_at": _now_iso(), **upd}},
            )
            if cas.modified_count == 1:
                # Extend the banner: budget top-up + expiration date extension
                duration = int(renewal.get("duration_days") or 30)
                amount_xof = float(renewal.get("amount_xof") or 0)
                today_d = datetime.now(timezone.utc).date()
                try:
                    current_exp = date.fromisoformat((b.get("expiration_date") or "")[:10])
                except (ValueError, TypeError):
                    current_exp = today_d
                base = current_exp if current_exp >= today_d else today_d
                new_exp = (base + timedelta(days=duration)).isoformat()
                await db.ad_banners.update_one(
                    {"id": b["id"]},
                    {
                        "$inc": {"budget_amount": amount_xof},
                        "$set": {
                            "expiration_date": new_exp,
                            "active": True,
                            "auto_paused_at": None,
                            "auto_paused_reason": None,
                            "reminder_last_sent_for": None,  # reset so a new reminder can fire
                            "updated_at": _now_iso(),
                        },
                    },
                )
                applied = True
            else:
                applied = True  # someone else won the race; we still report applied
        else:
            await db.ad_renewals.update_one(
                {"session_id": session_id},
                {"$set": upd},
            )
        return {
            "payment_status": status.payment_status,
            "renewal_applied": applied,
            "amount_xof": renewal.get("amount_xof"),
            "duration_days": renewal.get("duration_days"),
        }

    @api.put("/public/ads-report/{slug}/media", tags=["Public — Ad Banners"])
    async def public_update_media(slug: str, payload: MediaUpdatePayload, token: str = Query(..., min_length=1)):
        """Self-service media update. The advertiser uploads via the admin
        public-upload endpoint then PUTs the resulting `/api/files/{id}` URL
        here. Only `image_url`, `media_kind`, `target_url`, plus the variant_b
        equivalents can be changed — nothing else (preserves admin-set budget,
        placement, sizing, etc.)."""
        b = await db.ad_banners.find_one({"slug": slug}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        if (b.get("share_token") or "") != token:
            raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
        update_doc: Dict[str, Any] = {}
        for field in ("image_url", "media_kind", "target_url",
                      "variant_b_image_url", "variant_b_media_kind", "variant_b_target_url"):
            val = getattr(payload, field)
            if val is not None:
                update_doc[field] = val.strip() if isinstance(val, str) else val
        if not update_doc:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update_doc["updated_at"] = _now_iso()
        update_doc["last_self_service_update_at"] = _now_iso()
        await db.ad_banners.update_one({"id": b["id"]}, {"$set": update_doc})
        # Log to a lightweight audit collection for the admin
        await db.ad_self_service_updates.insert_one({
            "id": str(uuid.uuid4()),
            "banner_id": b["id"],
            "slug": slug,
            "fields": list(update_doc.keys()),
            "at": _now_iso(),
        })
        return {"ok": True, "updated_fields": list(update_doc.keys())}

    # =====================================================================
    # Iter38r-fix9z9 — AI Campaign Plan
    # Public endpoint validated by slug+share_token. Asks Claude Haiku 4.5
    # to analyse the campaign's current performance (impressions, clicks,
    # CTR, A/B variant comparison, budget pacing) and produce 3 concrete
    # recommendations:
    #   1. Visual improvement hint (description text — the user can then
    #      use the existing AI Media Generator to actually create the image)
    #   2. 3 alternative slogans / CTAs
    #   3. Optimal budget recommendation with justification
    # Cached for 6 hours per banner to control LLM cost.
    # =====================================================================
    @api.post("/public/ads-report/{slug}/ai-plan", tags=["Public — Ad Banners"])
    async def public_ai_campaign_plan(slug: str, token: str = Query(..., min_length=1)):
        b = await db.ad_banners.find_one({"slug": slug}, {"_id": 0})
        if not b:
            raise HTTPException(status_code=404, detail="Bannière introuvable")
        if (b.get("share_token") or "") != token:
            raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
        # Cache check (6h)
        cached = b.get("ai_plan") or {}
        cache_age_ok = False
        if cached.get("generated_at"):
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["generated_at"])).total_seconds()
                cache_age_ok = age < 6 * 3600
            except (ValueError, TypeError):
                cache_age_ok = False
        if cache_age_ok:
            return {**cached, "cached": True}

        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="Module IA non configuré")
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"emergentintegrations indisponible : {exc}") from exc

        imp = int(b.get("total_impressions") or 0)
        clicks = int(b.get("total_clicks") or 0)
        ctr = round((clicks / imp) * 100, 2) if imp else 0.0
        budget = float(b.get("budget_amount") or 0)
        spent = float(b.get("amount_spent") or 0)
        currency = b.get("currency") or "XOF"
        ab_block = ""
        if b.get("ab_enabled"):
            imp_a = int(b.get("total_impressions_a") or 0)
            imp_b = int(b.get("total_impressions_b") or 0)
            clk_a = int(b.get("total_clicks_a") or 0)
            clk_b = int(b.get("total_clicks_b") or 0)
            ctr_a = round((clk_a / imp_a) * 100, 2) if imp_a else 0.0
            ctr_b = round((clk_b / imp_b) * 100, 2) if imp_b else 0.0
            ab_block = (
                f"Test A/B ACTIF :\n"
                f"  • Variante A : {imp_a} affichages, {clk_a} clics, CTR {ctr_a}%\n"
                f"  • Variante B : {imp_b} affichages, {clk_b} clics, CTR {ctr_b}%\n"
            )
        prompt = (
            f"Tu es un expert en marketing digital et régie publicitaire. Analyse les performances "
            f"de la campagne SAWALI suivante et fournis un plan d'optimisation concret, en français.\n\n"
            f"=== DONNÉES CAMPAGNE ===\n"
            f"Nom : {b.get('name')}\n"
            f"Annonceur : {b.get('advertiser_name') or 'Non renseigné'}\n"
            f"Type de média : {b.get('media_kind') or 'image'}\n"
            f"URL cible : {b.get('target_url')}\n"
            f"Placement : {b.get('placement')}\n"
            f"Affichages totaux : {imp}\n"
            f"Clics totaux : {clicks}\n"
            f"CTR : {ctr}%\n"
            f"Budget alloué : {int(budget)} {currency} (dépensé : {int(spent)} {currency})\n"
            f"{ab_block}"
            f"\nRéponds STRICTEMENT au format JSON suivant (sans markdown, sans ```), "
            f"avec ces 4 clés exactes :\n"
            "{\n"
            '  "visual_hint": "Une suggestion concrète de visuel à essayer (1-2 phrases, descriptif pour Gemini Nano Banana)",\n'
            '  "slogans": ["3 slogans/CTA alternatifs en français, courts et accrocheurs"],\n'
            '  "recommended_budget_xof": un nombre (budget mensuel optimal en XOF),\n'
            '  "budget_justification": "1-2 phrases expliquant pourquoi ce budget"\n'
            "}\n"
            "Si le CTR est <0.5%, recommande surtout un changement de visuel. "
            "Si CTR >2%, recommande surtout d'augmenter le budget. Entre les deux, recommande de tester des slogans alternatifs."
        )
        chat = LlmChat(
            api_key=api_key,
            session_id=f"ad-plan-{b.get('id')}-{uuid.uuid4().hex[:6]}",
            system_message="Tu es un expert marketing senior. Tu réponds toujours en JSON valide, sans markdown.",
        ).with_model("anthropic", "claude-haiku-4-5-20251001")
        try:
            raw = await chat.send_message(UserMessage(text=prompt))
        except Exception as exc:  # noqa: BLE001
            logger.exception("[ads] ai-plan llm call failed")
            raise HTTPException(status_code=502, detail=f"Erreur IA : {str(exc)[:200]}") from exc
        import json as _json
        parsed: Dict[str, Any] = {}
        try:
            # Strip optional markdown fences if model returned them
            text = (raw or "").strip()
            if text.startswith("```"):
                text = text.strip("`").lstrip("json").strip()
            parsed = _json.loads(text)
        except Exception:  # noqa: BLE001
            # Try to extract a JSON object from anywhere in the text
            import re
            m = re.search(r"\{.*\}", raw or "", re.S)
            if m:
                try:
                    parsed = _json.loads(m.group(0))
                except Exception:  # noqa: BLE001
                    parsed = {}
        if not parsed:
            raise HTTPException(status_code=502, detail="Réponse IA non parsable")

        result = {
            "visual_hint": (parsed.get("visual_hint") or "").strip(),
            "slogans": [s.strip() for s in (parsed.get("slogans") or []) if isinstance(s, str)][:5],
            "recommended_budget_xof": float(parsed.get("recommended_budget_xof") or 0),
            "budget_justification": (parsed.get("budget_justification") or "").strip(),
            "generated_at": _now_iso(),
            "based_on": {
                "impressions": imp, "clicks": clicks, "ctr_pct": ctr,
                "current_budget": budget, "ab_enabled": bool(b.get("ab_enabled")),
            },
        }
        # Cache on the banner doc
        await db.ad_banners.update_one(
            {"id": b["id"]},
            {"$set": {"ai_plan": result, "ai_plan_updated_at": _now_iso()}},
        )
        return {**result, "cached": False}

    # =====================================================================
    # Iter38r-fix9z7 — Live WebSocket endpoint for the admin dashboard.
    # Auth via ?token=<JWT> (same pattern as /api/ws/chat). The endpoint:
    #   • Sends an initial "snapshot" with every active banner's totals
    #   • Pushes "impression" / "click" events as they happen
    # Clients can ignore events for banners they're not tracking.
    # =====================================================================
    @api.websocket("/ws/ad-banners-live")
    async def ws_ad_banners_live(websocket: WebSocket, token: str = Query(..., min_length=1)):
        try:
            from auth import decode_token as _decode  # type: ignore
            payload = _decode(token)
            uid = (payload or {}).get("sub")
            user = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "role": 1, "account_status": 1})
            if not user or user.get("role") not in ("admin", "superviseur") or user.get("account_status") != "active":
                await websocket.close(code=4401)
                return
        except Exception:  # noqa: BLE001
            await websocket.close(code=4401)
            return
        await websocket.accept()
        await live_hub.connect(websocket)
        try:
            # Initial snapshot — all active banners with current totals
            cursor = db.ad_banners.find({}, {"_id": 0})
            items = []
            async for b in cursor:
                if not b.get("active"):
                    continue
                items.append({
                    "id": b.get("id"),
                    "name": b.get("name"),
                    "advertiser_name": b.get("advertiser_name") or "",
                    "placement": b.get("placement"),
                    "media_kind": b.get("media_kind") or "image",
                    "image_url": b.get("image_url"),
                    "ab_enabled": bool(b.get("ab_enabled")),
                    "total_impressions": int(b.get("total_impressions") or 0),
                    "total_clicks": int(b.get("total_clicks") or 0),
                    "total_impressions_a": int(b.get("total_impressions_a") or 0),
                    "total_impressions_b": int(b.get("total_impressions_b") or 0),
                    "total_clicks_a": int(b.get("total_clicks_a") or 0),
                    "total_clicks_b": int(b.get("total_clicks_b") or 0),
                    "amount_spent": float(b.get("amount_spent") or 0),
                    "budget_amount": float(b.get("budget_amount") or 0),
                })
            await websocket.send_json({"event": "snapshot", "items": items, "ts": _now_iso()})
            # Keep alive — read & discard pings until disconnect
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_json({"event": "pong", "ts": _now_iso()})
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("ad-banners-live socket error: %s", exc)
        finally:
            await live_hub.disconnect(websocket)

    return api
