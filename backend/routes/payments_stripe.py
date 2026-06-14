"""Iter38o — Stripe Checkout for paid formations (one-time payment).

Flow:
  1. Tracked user clicks "Acheter cette formation" on `/portal/formations/{fid}`.
  2. Frontend POST /api/me/formations/{fid}/stripe/checkout with
     {origin_url: window.location.origin}.
  3. Backend:
     - Validates the formation (access == "paid", price > 0, available).
     - Reads amount from `formations` collection (NEVER from frontend).
     - Creates a Stripe Checkout Session via emergentintegrations.
     - Persists a `payment_transactions` row with status "initiated".
     - Returns {url, session_id} → frontend redirects to Stripe.
  4. After payment, Stripe redirects back to `{origin}/portal/formations/{fid}?session_id={CHECKOUT_SESSION_ID}`.
  5. Frontend polls GET /api/payments/stripe/status/{session_id} every 2s (max 5×).
  6. Webhook POST /api/webhook/stripe — confirms server-side and creates the
     enrollment idempotently.

Stripe currency: Stripe Checkout does not support XOF. We fall back to EUR
(approximate parity 1 EUR ≈ 655.957 XOF). The original XOF amount + EUR
conversion are both stored on `payment_transactions` for auditing.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("stripe_payments")

# Conversion rate used to convert XOF → EUR for Stripe.
# CFA Franc West (XOF) is pegged to EUR at exactly 655.957.
XOF_TO_EUR = 655.957


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_amount(value: float) -> float:
    """Ensure float with 2 decimals (Stripe API requirement)."""
    try:
        return float(f"{float(value):.2f}")
    except (TypeError, ValueError):
        return 0.0


# Iter43-fix16 (2026-06) — Module-scoped Pydantic model.
# Previously declared inside `setup_stripe_routes()` which broke
# FastAPI OpenAPI schema generation when combined with
# `from __future__ import annotations` (ForwardRef could not be
# resolved → /api/openapi.json returned 500).
class StripeCheckoutPayload(BaseModel):
    origin_url: str = Field(..., min_length=8, max_length=500)


def setup_stripe_routes(*, db, api, get_current_user, send_email_fn=None):
    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        logger.warning("[stripe] STRIPE_API_KEY missing — Stripe Checkout disabled")
        return

    try:
        from emergentintegrations.payments.stripe.checkout import (
            StripeCheckout, CheckoutSessionRequest,
        )
    except ImportError as exc:
        logger.error("[stripe] emergentintegrations not installed: %s", exc)
        return

    # Iter38r-fix9o (P1) — import lazy to avoid circular at module load
    try:
        from routes.product_checkout_9n import mark_public_order_paid as _mark_public_order_paid
    except Exception:
        _mark_public_order_paid = None

    @api.post("/me/formations/{fid}/stripe/checkout", tags=["Portail Client"])
    async def create_formation_checkout(
        fid: str, payload: StripeCheckoutPayload, request: Request,
        user: dict = Depends(get_current_user),
    ):
        """Crée une session Stripe Checkout pour une formation payante."""
        formation = await db.formations.find_one({"id": fid}, {"_id": 0})
        if not formation:
            raise HTTPException(status_code=404, detail="Formation introuvable")
        if not formation.get("available", True):
            raise HTTPException(status_code=400, detail="Formation indisponible")
        if formation.get("access") != "paid":
            raise HTTPException(status_code=400, detail="Cette formation est gratuite")
        price_xof = float(formation.get("price") or 0)
        if price_xof <= 0:
            raise HTTPException(status_code=400, detail="Prix non configuré pour cette formation")
        # Tracked users only (same gating as enroll)
        is_tracked = bool(user.get("tracked_user_id") or user.get("tracked_role"))
        if not is_tracked and user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Inscription réservée aux utilisateurs suivis")

        # Server-side amount (XOF → EUR for Stripe)
        amount_eur = _safe_amount(price_xof / XOF_TO_EUR)
        if amount_eur < 0.50:  # Stripe minimum amount EUR
            amount_eur = 0.50

        success_url = f"{payload.origin_url.rstrip('/')}/portal/formations/{fid}?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{payload.origin_url.rstrip('/')}/portal/formations/{fid}?canceled=1"

        # Construct webhook URL from the request's base URL (per playbook).
        host_url = str(request.base_url).rstrip("/")
        webhook_url = f"{host_url}/api/webhook/stripe"
        client = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

        metadata = {
            "kind": "formation",
            "formation_id": fid,
            "formation_name": (formation.get("name") or "")[:100],
            "user_id": user["id"],
            "user_email": user.get("email") or "",
            "price_xof": str(price_xof),
        }
        req = CheckoutSessionRequest(
            amount=amount_eur, currency="eur",
            success_url=success_url, cancel_url=cancel_url,
            metadata=metadata,
        )
        try:
            session = await client.create_checkout_session(req)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[stripe] create_checkout_session failed")
            raise HTTPException(status_code=502, detail=f"Erreur Stripe : {exc}") from exc

        # MANDATORY: persist a payment_transactions row BEFORE redirect
        await db.payment_transactions.insert_one({
            "session_id": session.session_id,
            "kind": "formation",
            "formation_id": fid,
            "user_id": user["id"],
            "user_email": user.get("email"),
            "amount": amount_eur,
            "currency": "eur",
            "amount_xof": price_xof,
            "metadata": metadata,
            "payment_status": "initiated",
            "status": "open",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        return {"url": session.url, "session_id": session.session_id}

    @api.get("/payments/stripe/status/{session_id}", tags=["Portail Client"])
    async def get_stripe_status(session_id: str, user: dict = Depends(get_current_user)):
        """Poll the checkout status. Idempotent — enrollment only created
        once even if polled in parallel."""
        tx = await db.payment_transactions.find_one(
            {"session_id": session_id}, {"_id": 0}
        )
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction introuvable")
        if tx.get("user_id") and tx["user_id"] != user["id"] and user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Accès refusé")
        # If already final, return cached state
        if tx.get("payment_status") in ("paid", "expired", "failed"):
            return {
                "status": tx.get("status"),
                "payment_status": tx.get("payment_status"),
                "amount_total": int(round(float(tx.get("amount") or 0) * 100)),
                "currency": tx.get("currency"),
                "metadata": tx.get("metadata") or {},
                "enrollment_created": bool(tx.get("enrollment_created")),
            }
        # Refresh from Stripe
        host_url = str(_make_request_base_url())
        webhook_url = f"{host_url}/api/webhook/stripe"
        client = StripeCheckout(api_key=api_key, webhook_url=webhook_url)
        try:
            status = await client.get_checkout_status(session_id)
        except Exception as exc:
            logger.exception("[stripe] get_checkout_status failed")
            raise HTTPException(status_code=502, detail=f"Erreur Stripe : {exc}") from exc

        # Persist new status — but ONLY create the enrollment once.
        new_status_payload: Dict[str, Any] = {
            "status": status.status,
            "payment_status": status.payment_status,
            "amount_total_cents": status.amount_total,
            "updated_at": _now_iso(),
        }
        enrollment_created = bool(tx.get("enrollment_created"))
        if status.payment_status == "paid" and not enrollment_created:
            await _create_enrollment_idempotent(db, tx, session_id)
            new_status_payload["enrollment_created"] = True
            enrollment_created = True
        await db.payment_transactions.update_one(
            {"session_id": session_id}, {"$set": new_status_payload}
        )
        return {
            "status": status.status,
            "payment_status": status.payment_status,
            "amount_total": status.amount_total,
            "currency": status.currency,
            "metadata": status.metadata,
            "enrollment_created": enrollment_created,
        }

    @api.post("/webhook/stripe", tags=["Payments"])
    async def stripe_webhook(request: Request):
        """Stripe webhook. Verifies signature, then finalises either a paid
        formation enrollment OR a public catalogue order (idempotent)."""
        sig = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature")
        body = await request.body()
        # Iter38r-fix9o — Resolve webhook signing secret from env or settings
        secret = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""
        if not secret:
            try:
                s = await db.settings.find_one(
                    {"_id": "global"}, {"_id": 0, "stripe_webhook_secret": 1},
                ) or {}
                secret = (s.get("stripe_webhook_secret") or "").strip()
            except Exception:
                pass
        host_url = str(request.base_url).rstrip("/")
        webhook_url = f"{host_url}/api/webhook/stripe"
        client = StripeCheckout(
            api_key=api_key, webhook_url=webhook_url,
            webhook_secret=secret or None,
        )
        try:
            event = await client.handle_webhook(body, sig)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[stripe] webhook verify failed: %s", exc)
            try:
                import uuid as _uuid
                await db.webhook_events_stripe.insert_one({
                    "id": str(_uuid.uuid4()),
                    "received_at": _now_iso(),
                    "error": str(exc)[:300],
                    "raw_signature": (sig or "")[:200],
                })
            except Exception:
                pass
            raise HTTPException(status_code=400, detail="Signature invalide")
        # Idempotency : ignore duplicate event_id
        ev_id = getattr(event, "event_id", None)
        if ev_id:
            existing = await db.webhook_events_stripe.find_one(
                {"event_id": ev_id}, {"_id": 0, "event_id": 1},
            )
            if existing:
                return {"ok": True, "idempotent": True, "event_id": ev_id}
            try:
                import uuid as _uuid
                await db.webhook_events_stripe.insert_one({
                    "id": str(_uuid.uuid4()),
                    "event_id": ev_id,
                    "event_type": getattr(event, "event_type", None),
                    "session_id": getattr(event, "session_id", None),
                    "payment_status": getattr(event, "payment_status", None),
                    "metadata": getattr(event, "metadata", {}) or {},
                    "received_at": _now_iso(),
                })
            except Exception:
                pass
        session_id = getattr(event, "session_id", None)
        payment_status = getattr(event, "payment_status", None)
        if not session_id:
            return {"ok": True}
        # 1) Formations payment path (legacy)
        tx = await db.payment_transactions.find_one(
            {"session_id": session_id}, {"_id": 0}
        )
        if tx:
            upd: Dict[str, Any] = {
                "payment_status": payment_status,
                "status": getattr(event, "event_type", None),
                "updated_at": _now_iso(),
            }
            if payment_status == "paid" and not tx.get("enrollment_created"):
                await _create_enrollment_idempotent(db, tx, session_id)
                upd["enrollment_created"] = True
            await db.payment_transactions.update_one(
                {"session_id": session_id}, {"$set": upd}
            )
            # Iter38r-fix9w — Voice notification (paid formation)
            if payment_status == "paid":
                try:
                    from routes.voice_notifications import trigger_voice_event
                    await trigger_voice_event(db, tx.get("user_id") or "", "payment_stripe_received", {
                        "amount": (tx.get("amount") or 0) / 100,
                        "currency": (tx.get("currency") or "EUR").upper(),
                        "client_name": tx.get("buyer_name") or tx.get("user_email") or "—",
                        "product_name": tx.get("formation_title") or "Formation",
                    })
                except Exception:
                    pass
            return {"ok": True, "kind": "formation"}
        # 2) Public catalogue order path (Iter38r-fix9o)
        public_order = await db.public_orders.find_one(
            {"stripe_session_id": session_id}, {"_id": 0},
        )
        if public_order and payment_status == "paid" and _mark_public_order_paid:
            await _mark_public_order_paid(db, send_email_fn, public_order)
            return {"ok": True, "kind": "public_order"}
        return {"ok": True}


async def _create_enrollment_idempotent(db, tx: Dict[str, Any], session_id: str) -> None:
    """Create the formation_enrollments row if it doesn't exist yet."""
    fid = tx.get("formation_id")
    uid = tx.get("user_id")
    if not fid or not uid:
        return
    existing = await db.formation_enrollments.find_one(
        {"formation_id": fid, "user_id": uid}, {"_id": 0, "id": 1}
    )
    if existing:
        return
    formation = await db.formations.find_one({"id": fid}, {"_id": 0}) or {}
    user = await db.users.find_one({"id": uid}, {"_id": 0, "email": 1, "full_name": 1}) or {}
    import uuid
    doc = {
        "id": str(uuid.uuid4()),
        "formation_id": fid,
        "user_id": uid,
        "user_email": user.get("email"),
        "user_name": user.get("full_name"),
        "state": "inscription",
        "credits_purchased": int(formation.get("default_credits") or 0),
        "credits_consumed": 0,
        "credits_available": int(formation.get("default_credits") or 0),
        "modules_seen": [],
        "total_time_ms": 0,
        "last_access": None,
        "paid_via": "stripe",
        "stripe_session_id": session_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.formation_enrollments.insert_one(doc)


def _make_request_base_url() -> str:
    """Cheap fallback for the polling path (which doesn't carry Request).
    Reads BACKEND_PUBLIC_URL if set, else defaults to local."""
    return os.environ.get("REACT_APP_BACKEND_URL") or os.environ.get("BACKEND_PUBLIC_URL", "http://localhost:8001")


__all__ = ["setup_stripe_routes"]
