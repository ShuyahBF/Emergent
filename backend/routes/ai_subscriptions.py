"""Iter38r-fix9u — AI Subscription Renewal Reminders.

Tracks the user's external AI / SaaS subscriptions (Emergent, Claude Haiku
PRO, OpenAI, ElevenLabs, fal.ai…) and reminds them by WhatsApp + Email when
the renewal date approaches.

Data model (`ai_subscriptions` collection)
------------------------------------------
{
  id: str (uuid),
  tenant_id: str,             # owning admin user id
  name: str,                  # "Claude Haiku 4.5 PRO"
  active: bool,
  monthly_cost: float,        # in `currency` (default USD)
  currency: str = "USD",
  subscription_date: "YYYY-MM-DD",
  period_days: int = 30,      # days between renewals
  reminder_days_before: int = 5,
  next_renewal_date: "YYYY-MM-DD",  # auto-computed
  last_reminder_at: ISO datetime | None,
  notify_email: str | None,
  notify_whatsapp: str | None,  # E.164 (e.g. "+22670000000")
  notes: str = "",
  created_at: ISO, updated_at: ISO,
}

Endpoints
---------
GET    /api/admin/ai-subscriptions            list
POST   /api/admin/ai-subscriptions            create
PUT    /api/admin/ai-subscriptions/{id}       update
DELETE /api/admin/ai-subscriptions/{id}       delete
POST   /api/admin/ai-subscriptions/{id}/send-reminder   manual trigger

The daily scheduler (cron at 08:00 Africa/Abidjan) calls
`process_due_reminders(db, send_email, send_wa)` which:
  - recomputes next_renewal_date for each active sub
  - sends WhatsApp + Email when `days_until_renewal <= reminder_days_before`
  - records `last_reminder_at` to avoid spamming
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.ai_subscriptions")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def _compute_next_renewal(subscription_date: str, period_days: int) -> Optional[str]:
    """Compute the next renewal date strictly in the future (or today).

    Adds `period_days` until the resulting date is >= today. Returns ISO
    YYYY-MM-DD or None on bad input.
    """
    d = _parse_date(subscription_date)
    if not d or period_days <= 0:
        return None
    today = date.today()
    if d >= today:
        return d.isoformat()
    # Advance by full periods
    delta = (today - d).days
    periods_passed = (delta // period_days) + 1
    nxt = d + timedelta(days=period_days * periods_passed)
    return nxt.isoformat()


def _serialize(sub: Dict[str, Any]) -> Dict[str, Any]:
    """Strip Mongo internals + recompute volatile fields for the API response."""
    sub = {k: v for k, v in sub.items() if k != "_id"}
    nxt = _compute_next_renewal(
        sub.get("subscription_date") or "",
        int(sub.get("period_days") or 30),
    )
    sub["next_renewal_date"] = nxt
    if nxt:
        try:
            sub["days_until_renewal"] = (date.fromisoformat(nxt) - date.today()).days
        except ValueError:
            sub["days_until_renewal"] = None
    else:
        sub["days_until_renewal"] = None
    return sub


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------
class SubscriptionPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    active: bool = True
    monthly_cost: float = Field(0, ge=0)
    currency: str = Field("USD", min_length=2, max_length=8)
    subscription_date: str = Field(..., min_length=10, max_length=10)  # YYYY-MM-DD
    period_days: int = Field(30, ge=1, le=365)
    reminder_days_before: int = Field(5, ge=0, le=90)
    notify_email: Optional[str] = Field(None, max_length=200)
    notify_whatsapp: Optional[str] = Field(None, max_length=30)
    notes: Optional[str] = Field("", max_length=500)


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    active: Optional[bool] = None
    monthly_cost: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = None
    subscription_date: Optional[str] = None
    period_days: Optional[int] = Field(None, ge=1, le=365)
    reminder_days_before: Optional[int] = Field(None, ge=0, le=90)
    notify_email: Optional[str] = None
    notify_whatsapp: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Reminder dispatcher (called by scheduler + manual trigger)
# ---------------------------------------------------------------------------
async def _send_reminder_for(
    db,
    sub: Dict[str, Any],
    *,
    send_email_fn: Optional[Callable] = None,
    send_whatsapp_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    name = sub.get("name", "?")
    nxt = _compute_next_renewal(sub.get("subscription_date") or "", int(sub.get("period_days") or 30))
    days = None
    if nxt:
        try:
            days = (date.fromisoformat(nxt) - date.today()).days
        except ValueError:
            days = None
    cost = sub.get("monthly_cost") or 0
    currency = sub.get("currency") or "USD"
    msg = (
        f"🔔 Rappel d'abonnement IA — SAWALI\n\n"
        f"• Outil : {name}\n"
        f"• Renouvellement : {nxt or '?'} "
        f"({'dans ' + str(days) + ' jour(s)' if days is not None else 'date inconnue'})\n"
        f"• Coût mensuel : {cost} {currency}\n\n"
        f"Pensez à anticiper le paiement pour éviter l'interruption du service."
    )
    sent = {"email": False, "whatsapp": False}
    email_to = (sub.get("notify_email") or "").strip()
    if email_to and send_email_fn:
        try:
            await send_email_fn(
                to=email_to,
                subject=f"[SAWALI] Renouvellement {name} dans {days} jour(s)",
                body_text=msg,
            )
            sent["email"] = True
        except Exception:
            logger.exception("[ai_subs] email reminder failed for %s", name)
    wa_to = (sub.get("notify_whatsapp") or "").strip()
    if wa_to and send_whatsapp_fn:
        try:
            await send_whatsapp_fn(to=wa_to, body=msg)
            sent["whatsapp"] = True
        except Exception:
            logger.exception("[ai_subs] WA reminder failed for %s", name)
    await db.ai_subscriptions.update_one(
        {"id": sub["id"]},
        {"$set": {"last_reminder_at": _now_iso()}},
    )
    return sent


async def process_due_reminders(
    db,
    *,
    send_email_fn: Optional[Callable] = None,
    send_whatsapp_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Iter38r-fix9u — Run by the daily scheduler. Scans all active subscriptions
    and dispatches reminders for those within their reminder window. Idempotent
    on a given day (skips subs already reminded < 18 h ago).
    """
    today = date.today()
    cursor = db.ai_subscriptions.find({"active": True}, {"_id": 0})
    items = await cursor.to_list(2000)
    dispatched = 0
    for sub in items:
        nxt = _compute_next_renewal(
            sub.get("subscription_date") or "",
            int(sub.get("period_days") or 30),
        )
        if not nxt:
            continue
        try:
            days = (date.fromisoformat(nxt) - today).days
        except ValueError:
            continue
        if days < 0 or days > int(sub.get("reminder_days_before") or 5):
            continue
        # Idempotency: skip if already reminded in the last 18 hours
        last = sub.get("last_reminder_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < 18 * 3600:
                    continue
            except (TypeError, ValueError):
                pass
        await _send_reminder_for(db, sub, send_email_fn=send_email_fn, send_whatsapp_fn=send_whatsapp_fn)
        dispatched += 1
    logger.info("[ai_subs] daily reminders dispatched=%s scanned=%s", dispatched, len(items))
    return {"scanned": len(items), "dispatched": dispatched, "date": today.isoformat()}


# ---------------------------------------------------------------------------
# Route setup
# ---------------------------------------------------------------------------
def setup_ai_subscriptions_routes(
    app,
    db,
    get_current_user,
    *,
    send_email_fn: Optional[Callable] = None,
    send_whatsapp_fn: Optional[Callable] = None,
):
    api: APIRouter = app

    def _ensure_admin(user: dict) -> None:
        if (user or {}).get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    def _tenant_id(user: dict) -> str:
        return user.get("client_id") or user.get("parent_client_id") or user["id"]

    @api.get("/admin/ai-subscriptions", tags=["Admin — Abonnements IA"])
    async def list_subs(user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        cursor = db.ai_subscriptions.find({"tenant_id": tid}, {"_id": 0}).sort("subscription_date", 1)
        items = await cursor.to_list(500)
        return {"items": [_serialize(s) for s in items], "count": len(items)}

    @api.post("/admin/ai-subscriptions", tags=["Admin — Abonnements IA"])
    async def create_sub(payload: SubscriptionPayload, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        if not _parse_date(payload.subscription_date):
            raise HTTPException(status_code=400, detail="Date de souscription invalide (YYYY-MM-DD)")
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": tid,
            "name": payload.name.strip(),
            "active": payload.active,
            "monthly_cost": float(payload.monthly_cost),
            "currency": payload.currency.upper().strip(),
            "subscription_date": payload.subscription_date,
            "period_days": int(payload.period_days),
            "reminder_days_before": int(payload.reminder_days_before),
            "notify_email": (payload.notify_email or "").strip() or None,
            "notify_whatsapp": (payload.notify_whatsapp or "").strip() or None,
            "notes": (payload.notes or "").strip(),
            "last_reminder_at": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.ai_subscriptions.insert_one(doc.copy())
        return {"ok": True, "item": _serialize(doc)}

    @api.put("/admin/ai-subscriptions/{sub_id}", tags=["Admin — Abonnements IA"])
    async def update_sub(sub_id: str, payload: SubscriptionUpdate, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        existing = await db.ai_subscriptions.find_one({"id": sub_id, "tenant_id": tid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Abonnement introuvable")
        update: Dict[str, Any] = {"updated_at": _now_iso()}
        d = payload.dict(exclude_unset=True)
        if "subscription_date" in d and d["subscription_date"]:
            if not _parse_date(d["subscription_date"]):
                raise HTTPException(status_code=400, detail="Date de souscription invalide (YYYY-MM-DD)")
        for k in ("name", "active", "monthly_cost", "currency", "subscription_date",
                  "period_days", "reminder_days_before", "notify_email",
                  "notify_whatsapp", "notes"):
            if k in d:
                v = d[k]
                if isinstance(v, str):
                    v = v.strip() or None
                update[k] = v
        await db.ai_subscriptions.update_one({"id": sub_id, "tenant_id": tid}, {"$set": update})
        doc = await db.ai_subscriptions.find_one({"id": sub_id, "tenant_id": tid}, {"_id": 0})
        return {"ok": True, "item": _serialize(doc)}

    @api.delete("/admin/ai-subscriptions/{sub_id}", tags=["Admin — Abonnements IA"])
    async def delete_sub(sub_id: str, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        res = await db.ai_subscriptions.delete_one({"id": sub_id, "tenant_id": tid})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Abonnement introuvable")
        return {"ok": True}

    @api.post("/admin/ai-subscriptions/{sub_id}/send-reminder", tags=["Admin — Abonnements IA"])
    async def trigger_reminder(sub_id: str, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        sub = await db.ai_subscriptions.find_one({"id": sub_id, "tenant_id": tid}, {"_id": 0})
        if not sub:
            raise HTTPException(status_code=404, detail="Abonnement introuvable")
        result = await _send_reminder_for(
            db, sub,
            send_email_fn=send_email_fn,
            send_whatsapp_fn=send_whatsapp_fn,
        )
        return {"ok": True, "sent": result}

    return api
