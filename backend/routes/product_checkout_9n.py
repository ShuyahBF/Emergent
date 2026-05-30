"""Iter38r-fix9n — Public product checkout via Stripe + Coupons.

Endpoints:
  POST /api/public/products/{id}/checkout    — anyone can buy (creates Stripe session)
  GET  /api/public/orders/{order_id}         — order status (after checkout)
  POST /api/admin/coupons                    — admin CRUD
  GET  /api/admin/coupons
  PUT  /api/admin/coupons/{id}
  DELETE /api/admin/coupons/{id}
  GET  /api/public/coupons/{code}/validate   — lookup before checkout
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import stripe  # noqa: F401  (kept for any direct call fallback)
from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout,
    CheckoutSessionRequest,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from routes._counters import gen_internal_id

logger = logging.getLogger("sawali.product_checkout_9n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CouponCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=40)
    discount_pct: Optional[int] = Field(None, ge=1, le=100)
    discount_xof: Optional[int] = Field(None, ge=1)
    valid_until: Optional[str] = None  # ISO date
    max_uses: Optional[int] = Field(None, ge=1)
    active: bool = True


class CheckoutRequest(BaseModel):
    quantity: int = Field(1, ge=1, le=100)
    coupon_code: Optional[str] = Field(None, max_length=40)
    customer_email: Optional[str] = Field(None, max_length=200)
    customer_name: Optional[str] = Field(None, max_length=200)
    return_url: Optional[str] = Field(None, max_length=300)  # frontend URL


def _stripe_key() -> str:
    k = os.environ.get("STRIPE_API_KEY")
    if not k:
        raise HTTPException(status_code=503, detail="STRIPE_API_KEY non configurée")
    return k


async def _apply_coupon(db, code: str, base_xof: int) -> Dict[str, Any]:
    """Return {ok, final_xof, discount_xof, coupon_doc} or raise 400."""
    if not code:
        return {"ok": False, "final_xof": base_xof, "discount_xof": 0, "coupon_doc": None}
    coupon = await db.coupons.find_one({"code": code.upper(), "active": True}, {"_id": 0})
    if not coupon:
        raise HTTPException(status_code=404, detail="Code promo introuvable ou inactif")
    if coupon.get("valid_until"):
        try:
            until = datetime.fromisoformat(str(coupon["valid_until"]).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > until:
                raise HTTPException(status_code=410, detail="Code promo expiré")
        except (ValueError, TypeError):
            pass
    if coupon.get("max_uses") and (coupon.get("uses") or 0) >= int(coupon["max_uses"]):
        raise HTTPException(status_code=410, detail="Code promo épuisé")
    discount_xof = 0
    if coupon.get("discount_pct"):
        discount_xof = int(round(base_xof * int(coupon["discount_pct"]) / 100))
    elif coupon.get("discount_xof"):
        discount_xof = min(int(coupon["discount_xof"]), base_xof)
    final_xof = max(0, base_xof - discount_xof)
    return {"ok": True, "final_xof": final_xof, "discount_xof": discount_xof, "coupon_doc": coupon}


async def mark_public_order_paid(db, send_email_fn, order: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotent module-level helper: mark a `public_orders` row as paid,
    increment coupon usage and send the confirmation email exactly once.
    Reused by both the polling endpoint and the Stripe webhook (which is
    registered in `payments_stripe.py`)."""
    if order.get("status") == "paid":
        return order
    order_id = order["id"]
    await db.public_orders.update_one(
        {"id": order_id, "status": {"$ne": "paid"}},
        {"$set": {
            "status": "paid",
            "paid_at": _now_iso(),
            "updated_at": _now_iso(),
        }},
    )
    order["status"] = "paid"
    # Increment coupon usage (best-effort)
    if order.get("coupon_code"):
        try:
            await db.coupons.update_one(
                {"code": order["coupon_code"]},
                {"$inc": {"uses": 1}},
            )
        except Exception:
            logger.warning("[checkout] coupon usage increment failed", exc_info=True)
    # Confirmation email (only once)
    if order.get("customer_email") and send_email_fn and not order.get("email_sent_at"):
        try:
            await send_email_fn(
                to_email=order["customer_email"],
                subject=f"SAWALI — Confirmation de commande {order_id[:8]}",
                html_body=(
                    f"<h2 style='color:#1e40af'>Merci pour votre commande !</h2>"
                    f"<p>Produit : <strong>{order.get('product_name')}</strong> × {order.get('quantity')}</p>"
                    f"<p>Montant payé : <strong>{order.get('amount_xof'):,} XOF</strong></p>"
                    f"{('<p>Code promo appliqué : ' + str(order.get('coupon_code') or '') + ' (-' + str(order.get('discount_xof') or 0) + ' XOF)</p>') if order.get('coupon_code') else ''}"
                    f"<p>Référence : <code>{order_id}</code></p>"
                    f"<p style='color:#64748b;font-size:12px'>SAWALI SMART SYSTEMS</p>"
                ),
                text_body=f"Confirmation commande {order_id}. Montant: {order.get('amount_xof')} XOF.",
            )
            await db.public_orders.update_one(
                {"id": order_id},
                {"$set": {"email_sent_at": _now_iso()}},
            )
        except Exception:
            logger.warning("[checkout] confirmation email failed")
    return order


def setup_product_checkout_routes(app, db, get_current_user, send_email_fn):
    api: APIRouter = app

    async def _mark_order_paid(order: Dict[str, Any]) -> Dict[str, Any]:
        return await mark_public_order_paid(db, send_email_fn, order)

    @api.post("/public/products/{product_id}/checkout", tags=["Public"])
    async def public_product_checkout(product_id: str, payload: CheckoutRequest, request: Request):
        product = await db.products.find_one(
            {"id": product_id, "is_public": True, "active": True, "deleted_at": None},
            {"_id": 0},
        )
        if not product:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        unit_price_xof = int(round(float(product.get("unit_price_ht") or 0)))
        tva_pct = int(product.get("tva_pct") or 0)
        # Apply VAT to final unit price (TTC)
        unit_price_ttc = int(round(unit_price_xof * (1 + tva_pct / 100)))
        base_xof = unit_price_ttc * payload.quantity
        if base_xof <= 0:
            raise HTTPException(status_code=400, detail="Produit non commercialisable (prix 0)")
        # Coupon
        coupon_info = {"ok": False, "final_xof": base_xof, "discount_xof": 0, "coupon_doc": None}
        if payload.coupon_code:
            coupon_info = await _apply_coupon(db, payload.coupon_code, base_xof)
        amount_xof = coupon_info["final_xof"]
        # Build the order doc BEFORE the Stripe call (resilient against network errors)
        order_id = str(uuid.uuid4())
        # Iter38r-fix9o — Internal sequential number for invoicing/reporting
        internal_no = await gen_internal_id(db, "ORD")
        order_doc = {
            "id": order_id,
            "internal_no": internal_no,
            "kind": "public_product",
            "product_id": product_id,
            "product_name": product.get("name"),
            "product_sku": product.get("sku"),
            "quantity": payload.quantity,
            "unit_price_xof": unit_price_ttc,
            "base_xof": base_xof,
            "discount_xof": coupon_info["discount_xof"],
            "amount_xof": amount_xof,
            "currency": "XOF",
            "coupon_code": (payload.coupon_code or "").upper() or None,
            "customer_email": payload.customer_email,
            "customer_name": payload.customer_name,
            "status": "pending",
            "stripe_session_id": None,
            "tenant_id": product.get("tenant_id") or product.get("client_id"),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.public_orders.insert_one(order_doc.copy())
        # Build Stripe session via emergentintegrations
        base_return = (payload.return_url or "").rstrip("/") or str(request.base_url).rstrip("/")
        success_url = f"{base_return}/checkout/success?order_id={order_id}&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_return}/checkout/cancel?order_id={order_id}"
        host_url = str(request.base_url)
        webhook_url = f"{host_url.rstrip('/')}/api/webhook/stripe"
        try:
            sc = StripeCheckout(api_key=_stripe_key(), webhook_url=webhook_url)
            # XOF is a 0-decimal Stripe currency — still pass as float (Stripe rounds to int internally)
            checkout_req = CheckoutSessionRequest(
                amount=float(amount_xof),
                currency="xof",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "order_id": order_id,
                    "product_id": product_id,
                    "quantity": str(payload.quantity),
                    "coupon_code": (payload.coupon_code or "").upper(),
                    "discount_xof": str(coupon_info["discount_xof"]),
                    "customer_email": payload.customer_email or "",
                },
            )
            session = await sc.create_checkout_session(checkout_req)
            session_id = session.session_id
            session_url = session.url
        except Exception as exc:  # noqa: BLE001
            logger.exception("[checkout] stripe session create failed")
            await db.public_orders.update_one(
                {"id": order_id},
                {"$set": {"status": "failed", "error": str(exc)[:300], "updated_at": _now_iso()}},
            )
            raise HTTPException(status_code=502, detail=f"Stripe error: {str(exc)[:200]}")
        await db.public_orders.update_one(
            {"id": order_id},
            {"$set": {
                "stripe_session_id": session_id,
                "checkout_url": session_url,
                "updated_at": _now_iso(),
            }},
        )
        # Also persist into the shared payment_transactions collection
        await db.payment_transactions.insert_one({
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "order_id": order_id,
            "amount": float(amount_xof),
            "currency": "xof",
            "payment_status": "pending",
            "metadata": {"order_id": order_id, "product_id": product_id},
            "created_at": _now_iso(),
        })
        return {
            "ok": True,
            "order_id": order_id,
            "checkout_url": session_url,
            "amount_xof": amount_xof,
            "discount_xof": coupon_info["discount_xof"],
        }

    @api.get("/public/orders/{order_id}", tags=["Public"])
    async def public_order_status(order_id: str):
        order = await db.public_orders.find_one({"id": order_id}, {"_id": 0})
        if not order:
            raise HTTPException(status_code=404, detail="Commande introuvable")
        # If still pending and we have a Stripe session, refresh status.
        # Iter38r-fix9o (P1) — Webhook is the primary trigger now; this poll
        # path remains as a safety net for delayed/missed webhooks.
        if order.get("status") == "pending" and order.get("stripe_session_id"):
            try:
                sc = StripeCheckout(api_key=_stripe_key(), webhook_url="")
                status = await sc.get_checkout_status(order["stripe_session_id"])
                if status.payment_status == "paid":
                    order = await _mark_order_paid(order)
            except Exception:
                logger.warning("[checkout] stripe session retrieve failed", exc_info=True)
        return order

    # ---------------- Stripe Webhook ----------------
    # NOTE: The actual `/api/webhook/stripe` endpoint is registered by
    # `routes/payments_stripe.py` (it predates this module and also handles
    # Formations payments). That handler now calls `mark_public_order_paid`
    # from this module to finalise catalogue orders. Idempotency + event
    # logging are also implemented there.

    # ---------------- Coupons (admin only) ----------------
    async def _ensure_admin(user: dict):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    @api.get("/admin/stripe/webhook-events", tags=["Admin — Stripe"])
    async def list_webhook_events(limit: int = 20, user: dict = Depends(get_current_user)):
        await _ensure_admin(user)
        cap = min(max(int(limit), 1), 100)
        items = await db.webhook_events_stripe.find(
            {}, {"_id": 0, "raw_signature": 0},
        ).sort("received_at", -1).limit(cap).to_list(cap)
        return {"items": items, "count": len(items)}

    @api.post("/admin/coupons", tags=["Admin — Coupons"])
    async def create_coupon(payload: CouponCreate, user: dict = Depends(get_current_user)):
        await _ensure_admin(user)
        if not (payload.discount_pct or payload.discount_xof):
            raise HTTPException(status_code=400, detail="discount_pct ou discount_xof requis")
        code = payload.code.strip().upper()
        existing = await db.coupons.find_one({"code": code}, {"_id": 0, "code": 1})
        if existing:
            raise HTTPException(status_code=409, detail="Ce code existe déjà")
        doc = {
            "id": str(uuid.uuid4()),
            "code": code,
            "discount_pct": payload.discount_pct,
            "discount_xof": payload.discount_xof,
            "valid_until": payload.valid_until,
            "max_uses": payload.max_uses,
            "uses": 0,
            "active": payload.active,
            "created_by": user.get("email"),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.coupons.insert_one(doc.copy())
        return doc

    @api.get("/admin/coupons", tags=["Admin — Coupons"])
    async def list_coupons(user: dict = Depends(get_current_user)):
        await _ensure_admin(user)
        items = await db.coupons.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
        return {"items": items, "count": len(items)}

    @api.put("/admin/coupons/{coupon_id}", tags=["Admin — Coupons"])
    async def update_coupon(coupon_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        await _ensure_admin(user)
        allowed = {"discount_pct", "discount_xof", "valid_until", "max_uses", "active"}
        update = {k: v for k, v in payload.items() if k in allowed}
        update["updated_at"] = _now_iso()
        r = await db.coupons.update_one({"id": coupon_id}, {"$set": update})
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Coupon introuvable")
        return {"ok": True, "updated": list(update.keys())}

    @api.delete("/admin/coupons/{coupon_id}", tags=["Admin — Coupons"])
    async def delete_coupon(coupon_id: str, user: dict = Depends(get_current_user)):
        await _ensure_admin(user)
        r = await db.coupons.delete_one({"id": coupon_id})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Coupon introuvable")
        return {"ok": True}

    @api.get("/public/coupons/{code}/validate", tags=["Public"])
    async def validate_coupon(code: str, amount: int):
        """Validate a coupon for a given XOF amount (UX preview before checkout)."""
        try:
            info = await _apply_coupon(db, code, max(0, int(amount)))
        except HTTPException:
            raise
        return {
            "ok": info["ok"],
            "discount_xof": info["discount_xof"],
            "final_xof": info["final_xof"],
        }

    return api
