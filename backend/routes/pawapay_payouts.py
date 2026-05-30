"""Iter38r-fix9j — PawaPay Payouts (v2) for Burkina Faso.

Sends Mobile Money FROM the SAWALI PawaPay wallet TO end-users (suppliers,
employees, refunds…). Companion to the existing deposits / payment-page flow.

Endpoints (admin/superviseur/comptable only) :
  POST   /api/me/payments/pawapay/payout            — initiate
  GET    /api/me/payments/pawapay/payout/{id}       — status (with refresh option)
  GET    /api/me/payments/pawapay/payouts           — list recent payouts
  POST   /api/webhooks/pawapay/payouts/{secret}     — async callback

Design follows the PawaPay v2 spec :
  - payoutId is a merchant-generated UUIDv4 and is stored BEFORE the API call
  - We never mark a payout FAILED on a network error → leave PENDING and let
    the recheck cycle reconcile (admin can also trigger a manual refresh)
  - failureReason {failureCode, failureMessage} is persisted verbatim
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from routes._counters import gen_internal_id

logger = logging.getLogger("sawali.pawapay_payouts")

PAWAPAY_HOSTS = {
    "sandbox": "https://api.sandbox.pawapay.io",
    "production": "https://api.pawapay.io",
}

# Allowed FCFA currencies for the BFA zone (used for validation)
BFA_CURRENCY = "XOF"

# Burkina Faso providers (v2 codes). Real codes are confirmed via
# /v2/active-conf?country=BFA&operationType=PAYOUT — we hardcode the common
# ones for the dropdown but accept any returned by active-conf at runtime.
BFA_PROVIDERS = ["ORANGE_BFA", "MOOV_BFA", "TELECEL_BFA"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _active_token(s: Dict[str, Any]) -> Optional[str]:
    env = (s.get("pawapay_environment") or "sandbox").lower()
    if env == "production":
        return s.get("pawapay_api_token_production") or s.get("pawapay_api_token")
    return s.get("pawapay_api_token_sandbox") or s.get("pawapay_api_token")


def _base_url(s: Dict[str, Any]) -> str:
    env = (s.get("pawapay_environment") or "sandbox").lower()
    return PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])


class PayoutCreate(BaseModel):
    amount: float = Field(..., gt=0)
    msisdn: str = Field(..., min_length=8, max_length=20)
    provider: str = Field(..., min_length=3, max_length=40)
    customer_message: Optional[str] = Field(None, max_length=160)
    # Optional link to a business object (paie/facture/depense)
    related_kind: Optional[str] = Field(None, max_length=20)  # payroll | expense | refund
    related_id: Optional[str] = Field(None, max_length=64)
    country: Optional[str] = Field("BFA", min_length=3, max_length=3)


def setup_pawapay_payout_routes(app, db, get_current_user):
    api: APIRouter = app

    async def _ensure_can_pay(user: dict) -> Dict[str, Any]:
        """Iter38r-fix9o — admin/superviseur/comptable/caissier (from /portal/cash) OK."""
        role = (user.get("role") or "").lower()
        tracked = (user.get("tracked_role") or "").lower()
        allowed = {"admin", "superviseur", "comptable", "caissier"}
        if role not in allowed and tracked not in allowed:
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs / comptables / caissiers")
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("pawapay_enabled"):
            raise HTTPException(status_code=503, detail="PawaPay non activé dans les paramètres")
        if not _active_token(s):
            raise HTTPException(
                status_code=503,
                detail=f"Token API PawaPay {s.get('pawapay_environment') or 'sandbox'} manquant",
            )
        return s

    @api.post("/me/payments/pawapay/payout", tags=["Portail Client — PawaPay Payouts"])
    async def create_payout(payload: PayoutCreate, request: Request, user: dict = Depends(get_current_user)):
        s = await _ensure_can_pay(user)
        token = _active_token(s)
        # Sanitize MSISDN
        msisdn_digits = _digits(payload.msisdn)
        if len(msisdn_digits) < 8:
            raise HTTPException(status_code=400, detail="Numéro destinataire invalide")
        # Format amount with 0 decimals for XOF (PawaPay BFA providers: decimalsInAmount=NONE)
        amount_int = int(round(payload.amount))
        if amount_int <= 0:
            raise HTTPException(status_code=400, detail="Montant invalide")
        # Provider sanity check (allow any in case of new code, but warn if unknown)
        provider = payload.provider.strip().upper()
        if not provider:
            raise HTTPException(status_code=400, detail="Opérateur (provider) requis")

        payout_id = str(uuid.uuid4())
        # Iter38r-fix9o — Internal sequential number for accounting traceability
        internal_no = await gen_internal_id(db, "PAY")
        scope_uid = user.get("client_id") or user["id"]
        doc = {
            "id": payout_id,
            "payout_id": payout_id,
            "internal_no": internal_no,
            "client_id": scope_uid,
            "tenant_id": scope_uid,
            "created_by": user.get("email"),
            "created_by_id": user.get("id"),
            "country": (payload.country or "BFA").upper(),
            "currency": BFA_CURRENCY,
            "provider": provider,
            "phone_digits": msisdn_digits,
            "amount": str(amount_int),
            "amount_xof": amount_int,
            "customer_message": payload.customer_message,
            "related_kind": payload.related_kind,
            "related_id": payload.related_id,
            "status": "PENDING",
            "failure_code": None,
            "failure_message": None,
            "initiation_response": None,
            "last_callback_payload": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.pawapay_payouts.insert_one(doc.copy())

        # Build v2 request
        body = {
            "payoutId": payout_id,
            "amount": str(amount_int),
            "currency": BFA_CURRENCY,
            "recipient": {
                "type": "MMO",
                "accountDetails": {
                    "phoneNumber": msisdn_digits,
                    "provider": provider,
                },
            },
        }
        if payload.customer_message:
            body["customerMessage"] = payload.customer_message[:22]  # safe truncation

        url = f"{_base_url(s)}/v2/payouts"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        initiation_response: Optional[Dict[str, Any]] = None
        new_status = "PENDING"
        failure_code = None
        failure_message = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(url, json=body, headers=headers)
                try:
                    initiation_response = r.json()
                except Exception:
                    initiation_response = {"raw": r.text[:1000]}
                if r.status_code >= 500:
                    logger.warning("PawaPay payouts 5xx (left PENDING): %s %s", r.status_code, r.text[:200])
                elif r.status_code == 403:
                    new_status = "FAILED"
                    failure_code = "PAYOUTS_NOT_ALLOWED"
                    failure_message = "Payouts non activés pour ce provider sur ce compte"
                elif r.status_code >= 400:
                    # Other 4xx — surface the failureReason if present
                    fr = (initiation_response or {}).get("failureReason") or {}
                    if fr:
                        new_status = "FAILED"
                        failure_code = fr.get("failureCode") or "REJECTED"
                        failure_message = fr.get("failureMessage") or r.text[:200]
                    else:
                        # No clear status → leave PENDING per defensive guidance
                        logger.warning("PawaPay payouts 4xx ambiguous (left PENDING): %s", r.text[:200])
                else:
                    api_status = (initiation_response or {}).get("status")
                    if api_status:
                        new_status = api_status
                    fr = (initiation_response or {}).get("failureReason") or {}
                    if fr:
                        failure_code = fr.get("failureCode")
                        failure_message = fr.get("failureMessage")
        except httpx.HTTPError as exc:
            # Network error → leave PENDING and rely on recheck cycle
            logger.warning("PawaPay payouts network error (left PENDING): %s", exc)

        update = {
            "status": new_status,
            "failure_code": failure_code,
            "failure_message": failure_message,
            "initiation_response": initiation_response,
            "updated_at": _now_iso(),
        }
        await db.pawapay_payouts.update_one({"id": payout_id}, {"$set": update})
        return {"ok": True, "payout_id": payout_id, **{k: v for k, v in update.items() if k != "initiation_response"}}

    @api.get("/me/payments/pawapay/payout/{pid}", tags=["Portail Client — PawaPay Payouts"])
    async def get_payout(pid: str, refresh: bool = False, user: dict = Depends(get_current_user)):
        scope_uid = user.get("client_id") or user["id"]
        # Allow admins to see any tenant's payout under their scope
        doc = await db.pawapay_payouts.find_one(
            {"id": pid, "client_id": scope_uid},
            {"_id": 0},
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Payout introuvable")
        if not refresh or doc["status"] in ("COMPLETED", "FAILED"):
            return doc
        # Refresh from PawaPay
        s = await _ensure_can_pay(user)
        token = _active_token(s)
        url = f"{_base_url(s)}/v2/payouts/{pid}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                data = r.json() if r.status_code < 500 else {"raw": r.text[:200]}
        except httpx.HTTPError:
            return doc  # leave as-is, recheck later
        update: Dict[str, Any] = {"updated_at": _now_iso(), "last_status_check": data}
        if r.status_code == 404:
            # PawaPay reports NOT_FOUND → final failure per their guidance
            update["status"] = "FAILED"
            update["failure_code"] = "NOT_FOUND"
            update["failure_message"] = "Payout introuvable côté PawaPay"
        else:
            st = data.get("status")
            if st:
                update["status"] = st
            fr = data.get("failureReason") or {}
            if fr:
                update["failure_code"] = fr.get("failureCode")
                update["failure_message"] = fr.get("failureMessage")
        await db.pawapay_payouts.update_one({"id": pid}, {"$set": update})
        doc.update(update)
        return doc

    @api.get("/me/payments/pawapay/payouts", tags=["Portail Client — PawaPay Payouts"])
    async def list_payouts(limit: int = 100, user: dict = Depends(get_current_user)):
        scope_uid = user.get("client_id") or user["id"]
        cap = min(max(limit, 1), 500)
        cur = db.pawapay_payouts.find(
            {"client_id": scope_uid},
            {"_id": 0},
        ).sort("created_at", -1).limit(cap)
        items = await cur.to_list(cap)
        # KPIs
        kpi = {"total": 0, "completed": 0, "failed": 0, "pending": 0, "xof_completed": 0}
        for it in items:
            kpi["total"] += 1
            st = (it.get("status") or "").upper()
            if st == "COMPLETED":
                kpi["completed"] += 1
                kpi["xof_completed"] += int(it.get("amount_xof") or 0)
            elif st == "FAILED":
                kpi["failed"] += 1
            else:
                kpi["pending"] += 1
        return {"items": items, "kpis": kpi}

    @api.post("/webhooks/pawapay/payouts/{secret}", tags=["Webhooks"])
    async def webhook_payouts(secret: str, request: Request):
        s = await db.settings.find_one({"_id": "global"}) or {}
        expected = s.get("pawapay_callback_secret") or ""
        if not expected or secret != expected:
            raise HTTPException(status_code=403, detail="callback secret invalide")
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="payload invalide")
        events = payload if isinstance(payload, list) else [payload]
        applied = 0
        for event in events:
            pid = event.get("payoutId") or event.get("payout_id")
            if not pid:
                continue
            existing = await db.pawapay_payouts.find_one({"id": pid}, {"_id": 0, "status": 1, "failure_code": 1})
            if not existing:
                # Log orphan callback
                await db.wa_webhook_logs.insert_one({
                    "id": secrets.token_urlsafe(8),
                    "topic": "pawapay_payout_orphan",
                    "payload": event,
                    "created_at": _now_iso(),
                })
                continue
            status = event.get("status")
            fr = event.get("failureReason") or {}
            failure_code = fr.get("failureCode")
            failure_message = fr.get("failureMessage")
            # Idempotency: skip if nothing changed
            if existing.get("status") == status and existing.get("failure_code") == failure_code:
                continue
            await db.pawapay_payouts.update_one(
                {"id": pid},
                {"$set": {
                    "status": status,
                    "failure_code": failure_code,
                    "failure_message": failure_message,
                    "last_callback_payload": event,
                    "updated_at": _now_iso(),
                }},
            )
            applied += 1
        return {"ok": True, "applied": applied, "count": len(events)}

    return api
