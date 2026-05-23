"""Iter36u — Caisse & Facturation module (MVP).

Schemas + endpoints for:
  - business_clients (clients en compte / prospects) — distinct from users.role=client
  - products (catalog)
  - payment_methods (customizable, admin-managed)
  - receipts (encaissements with QR + watermark + WhatsApp delivery)
  - invoices (proforma / facture, items, discount, lifecycle, QR)

Security:
  - Admin/Superviseur: full CRUD on business_clients/products/payment_methods,
    can invoice/cancel; admin can also flag users.can_cash=True.
  - users.can_cash=True (any role): can create receipts and invoices,
    cannot cancel an invoice, can mark as paid -> auto-generates receipt.
  - Public verification endpoint /api/public/verify/{token} returns minimal
    info (no PII beyond the document) for QR scanning.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import qrcode
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from num2words import num2words

log = logging.getLogger("sawali.cashier")


# =====================================================================
# Pydantic models
# =====================================================================
class BusinessClientPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    # Iter36u — Pro fields (per user choice 5b)
    legal_form: Optional[str] = Field(None, max_length=80)  # SARL, SA, ...
    nif: Optional[str] = Field(None, max_length=40)  # numéro d'identification fiscale
    ifu: Optional[str] = Field(None, max_length=40)  # autre code fiscal régional
    rccm: Optional[str] = Field(None, max_length=40)
    phone: Optional[str] = Field(None, max_length=40)
    email: Optional[str] = Field(None, max_length=200)
    billing_address: Optional[str] = Field(None, max_length=500)
    shipping_address: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=500)


class ProductPayload(BaseModel):
    sku: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=80)
    unit: str = Field("pièce", max_length=30)  # heure / jour / forfait / pièce
    unit_price_ht: float = Field(..., ge=0)
    tva_pct: float = Field(0, ge=0, le=100)
    stock: Optional[int] = Field(None, ge=0)  # None = non géré
    image_url: Optional[str] = Field(None, max_length=500)
    active: bool = True


class PaymentMethodPayload(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    kind: str = Field("electronic")  # 'cash' | 'check' | 'electronic'
    active: bool = True
    sort_order: int = 0


class ReceiptItemRef(BaseModel):
    invoice_id: Optional[str] = None  # if generated from an invoice


class ReceiptPayload(BaseModel):
    business_client_id: str = Field(..., min_length=1)
    beneficiary_name: Optional[str] = Field(None, max_length=200)
    amount: float = Field(..., gt=0)
    motif: str = Field(..., min_length=1, max_length=500)
    payment_method_id: str = Field(..., min_length=1)
    payment_reference: Optional[str] = Field(None, max_length=200)
    related_invoice_id: Optional[str] = None


class InvoiceItemPayload(BaseModel):
    product_id: Optional[str] = None
    label: str = Field(..., min_length=1, max_length=300)
    quantity: float = Field(..., gt=0)
    unit_price_ht: float = Field(..., ge=0)
    tva_pct: float = Field(0, ge=0, le=100)
    unit: Optional[str] = Field(None, max_length=30)


class InvoicePayload(BaseModel):
    kind: str = Field("invoice")  # 'proforma' | 'invoice'
    business_client_id: str = Field(..., min_length=1)
    billing_address: Optional[str] = Field(None, max_length=500)
    shipping_address: Optional[str] = Field(None, max_length=500)
    items: List[InvoiceItemPayload] = Field(..., min_items=1, max_items=200)
    discount_kind: str = Field("none")  # 'none' | 'value' | 'percent'
    discount_value: float = Field(0, ge=0)
    notes: Optional[str] = Field(None, max_length=1000)
    due_date: Optional[str] = None  # ISO date


class InvoicePatchPayload(BaseModel):
    """Lifecycle transitions: proforma->invoice, issued->paid, issued->cancelled."""
    kind: Optional[str] = None  # convert proforma -> invoice
    status: Optional[str] = None  # 'paid' | 'cancelled'
    payment_method_id: Optional[str] = None
    payment_reference: Optional[str] = None


# =====================================================================
# Helpers
# =====================================================================
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(s: str, max_len: int = 30) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s or "doc")[:max_len]


def amount_to_words_fr(amount: float, currency_label: str = "francs CFA") -> str:
    """Convert a positive amount into spelled-out French text (XOF default)."""
    try:
        whole = int(round(amount))
        words = num2words(whole, lang="fr").replace("-", " ")
        return f"{words} {currency_label}".strip()
    except Exception:
        return f"{amount} {currency_label}"


def build_qr_png(payload: str) -> bytes:
    """Return PNG bytes for a QR code carrying `payload` (URL or string)."""
    qr = qrcode.QRCode(version=None, box_size=8, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _is_admin_or_supervisor(user: dict) -> bool:
    role = (user or {}).get("role")
    return role in ("admin", "superviseur")


def _can_invoice(user: dict) -> bool:
    """Admin/Superviseur OR users.can_cash=True can invoice."""
    return _is_admin_or_supervisor(user) or bool((user or {}).get("can_cash"))


def _can_cancel_invoice(user: dict) -> bool:
    """Iter36u — Choice 2c: only admin/superviseur can cancel."""
    return _is_admin_or_supervisor(user)


def _public_base_url(db_settings: Optional[dict]) -> str:
    if db_settings and db_settings.get("public_base_url"):
        return str(db_settings["public_base_url"]).rstrip("/")
    return (os.environ.get("PUBLIC_BASE_URL") or "https://sawalismartsystems.com").rstrip("/")


# =====================================================================
# Router factory
# =====================================================================
def make_router(*, db, get_current_user, get_current_admin, get_current_supervisor):
    router = APIRouter(tags=["Caisse & Facturation"])

    async def _next_year_seq(collection_name: str, year: int) -> int:
        """Atomic monotonic counter per (collection, year)."""
        res = await db.counters.find_one_and_update(
            {"_id": f"{collection_name}:{year}"},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=True,
        )
        return int((res or {}).get("value", 1))

    async def _settings() -> Optional[dict]:
        return await db.app_settings.find_one({"_id": "default"}, {"_id": 0})

    async def _resolve_payment_method(pm_id: str) -> Optional[dict]:
        pm = await db.payment_methods.find_one({"id": pm_id, "active": True}, {"_id": 0})
        return pm

    async def _build_verify_url(token: str) -> str:
        settings = await _settings()
        base = _public_base_url(settings)
        return f"{base}/verify/{token}"

    # ----------------------------------------------------------------
    # Business clients (clients en compte)
    # ----------------------------------------------------------------
    @router.get("/admin/business-clients")
    async def list_business_clients(_: dict = Depends(get_current_supervisor)):
        cursor = db.business_clients.find({"deleted_at": None}, {"_id": 0}).sort("name", 1)
        return [c async for c in cursor]

    @router.post("/admin/business-clients")
    async def create_business_client(payload: BusinessClientPayload, user: dict = Depends(get_current_supervisor)):
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "balance": 0.0,
            "created_at": _now_iso(),
            "created_by": user["id"],
            "deleted_at": None,
        })
        await db.business_clients.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/admin/business-clients/{cid}")
    async def update_business_client(cid: str, payload: BusinessClientPayload, _: dict = Depends(get_current_supervisor)):
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        updates["updated_at"] = _now_iso()
        res = await db.business_clients.update_one({"id": cid, "deleted_at": None}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Client introuvable")
        c = await db.business_clients.find_one({"id": cid}, {"_id": 0})
        return c

    @router.delete("/admin/business-clients/{cid}")
    async def delete_business_client(cid: str, _: dict = Depends(get_current_supervisor)):
        res = await db.business_clients.update_one({"id": cid}, {"$set": {"deleted_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Client introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # Products (catalogue)
    # ----------------------------------------------------------------
    @router.get("/admin/products")
    async def list_products(_: dict = Depends(get_current_supervisor)):
        cursor = db.products.find({"deleted_at": None}, {"_id": 0}).sort("name", 1)
        return [p async for p in cursor]

    @router.post("/admin/products")
    async def create_product(payload: ProductPayload, user: dict = Depends(get_current_supervisor)):
        # SKU unique among non-deleted
        existing = await db.products.find_one({"sku": payload.sku, "deleted_at": None}, {"_id": 0, "id": 1})
        if existing:
            raise HTTPException(status_code=400, detail=f"SKU déjà utilisé ({payload.sku})")
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "created_at": _now_iso(),
            "created_by": user["id"],
            "deleted_at": None,
        })
        await db.products.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/admin/products/{pid}")
    async def update_product(pid: str, payload: ProductPayload, _: dict = Depends(get_current_supervisor)):
        updates = payload.model_dump()
        updates["updated_at"] = _now_iso()
        res = await db.products.update_one({"id": pid, "deleted_at": None}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        return await db.products.find_one({"id": pid}, {"_id": 0})

    @router.delete("/admin/products/{pid}")
    async def delete_product(pid: str, _: dict = Depends(get_current_supervisor)):
        res = await db.products.update_one({"id": pid}, {"$set": {"deleted_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # Payment methods (admin-only CRUD; everyone can list active)
    # ----------------------------------------------------------------
    @router.get("/payment-methods")
    async def list_payment_methods(user: dict = Depends(get_current_user)):
        cursor = db.payment_methods.find({"active": True}, {"_id": 0}).sort("sort_order", 1)
        return [p async for p in cursor]

    @router.post("/admin/payment-methods")
    async def create_payment_method(payload: PaymentMethodPayload, user: dict = Depends(get_current_supervisor)):
        doc = payload.model_dump()
        doc.update({"id": str(uuid.uuid4()), "created_at": _now_iso(), "created_by": user["id"]})
        await db.payment_methods.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/admin/payment-methods/{pid}")
    async def update_payment_method(pid: str, payload: PaymentMethodPayload, _: dict = Depends(get_current_supervisor)):
        updates = payload.model_dump()
        updates["updated_at"] = _now_iso()
        res = await db.payment_methods.update_one({"id": pid}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Mode de paiement introuvable")
        return await db.payment_methods.find_one({"id": pid}, {"_id": 0})

    @router.delete("/admin/payment-methods/{pid}")
    async def delete_payment_method(pid: str, _: dict = Depends(get_current_supervisor)):
        res = await db.payment_methods.update_one({"id": pid}, {"$set": {"active": False, "deleted_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Mode de paiement introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # users.can_cash flag — admin/supervisor only
    # ----------------------------------------------------------------
    @router.patch("/admin/users/{uid}/can-cash")
    async def set_user_can_cash(uid: str, payload: dict = Body(...), _: dict = Depends(get_current_supervisor)):
        flag = bool(payload.get("can_cash"))
        res = await db.users.update_one({"id": uid}, {"$set": {"can_cash": flag, "can_cash_updated_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        return {"ok": True, "can_cash": flag}

    @router.get("/admin/users/can-cash")
    async def list_cashier_users(_: dict = Depends(get_current_supervisor)):
        cursor = db.users.find(
            {"can_cash": True, "account_status": {"$ne": "deleted"}},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1},
        )
        return [u async for u in cursor]

    # ----------------------------------------------------------------
    # Receipts
    # ----------------------------------------------------------------
    @router.post("/cashier/receipts")
    async def create_receipt(payload: ReceiptPayload, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Vous n'avez pas l'autorisation d'encaisser.")
        bc = await db.business_clients.find_one({"id": payload.business_client_id, "deleted_at": None}, {"_id": 0})
        if not bc:
            raise HTTPException(status_code=404, detail="Client en compte introuvable")
        pm = await _resolve_payment_method(payload.payment_method_id)
        if not pm:
            raise HTTPException(status_code=400, detail="Mode de paiement invalide ou inactif")
        year = datetime.now(timezone.utc).year
        seq = await _next_year_seq("receipts", year)
        number = f"R-{year}-{seq:04d}"
        token = secrets.token_urlsafe(24)
        doc = {
            "id": str(uuid.uuid4()),
            "number": number,
            "year": year,
            "seq": seq,
            "business_client_id": bc["id"],
            "business_client_snapshot": {
                "name": bc.get("name"),
                "billing_address": bc.get("billing_address"),
                "nif": bc.get("nif"),
                "rccm": bc.get("rccm"),
            },
            "beneficiary_name": payload.beneficiary_name or bc.get("name"),
            "amount": float(payload.amount),
            "amount_in_words": amount_to_words_fr(float(payload.amount)),
            "motif": payload.motif,
            "payment_method_id": pm["id"],
            "payment_method_label": pm.get("label"),
            "payment_method_kind": pm.get("kind"),
            "payment_reference": payload.payment_reference,
            "related_invoice_id": payload.related_invoice_id,
            "cashier_id": user["id"],
            "cashier_name": user.get("full_name") or user.get("email"),
            "issued_at": _now_iso(),
            "qr_token": token,
            "qr_url": await _build_verify_url(token),
            "cancelled_at": None,
        }
        await db.receipts.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.get("/cashier/receipts")
    async def list_receipts(
        limit: int = Query(50, ge=1, le=200),
        business_client_id: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        q: Dict[str, Any] = {}
        if business_client_id:
            q["business_client_id"] = business_client_id
        cursor = db.receipts.find(q, {"_id": 0}).sort("issued_at", -1).limit(limit)
        return [r async for r in cursor]

    @router.get("/cashier/receipts/{rid}")
    async def get_receipt(rid: str, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        r = await db.receipts.find_one({"id": rid}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Reçu introuvable")
        return r

    @router.get("/cashier/receipts/{rid}/qr.png")
    async def receipt_qr_png(rid: str, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        r = await db.receipts.find_one({"id": rid}, {"_id": 0, "qr_url": 1})
        if not r:
            raise HTTPException(status_code=404, detail="Reçu introuvable")
        png = build_qr_png(r["qr_url"])
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    # ----------------------------------------------------------------
    # Invoices (proforma / facture)
    # ----------------------------------------------------------------
    def _compute_invoice_totals(items: List[dict], discount_kind: str, discount_value: float) -> dict:
        subtotal_ht = 0.0
        total_tva = 0.0
        for it in items:
            line_ht = float(it["quantity"]) * float(it["unit_price_ht"])
            line_tva = line_ht * float(it.get("tva_pct") or 0) / 100.0
            it["line_total_ht"] = round(line_ht, 2)
            it["line_total_tva"] = round(line_tva, 2)
            it["line_total_ttc"] = round(line_ht + line_tva, 2)
            subtotal_ht += line_ht
            total_tva += line_tva
        total_ttc = subtotal_ht + total_tva
        discount_amount = 0.0
        if discount_kind == "value":
            discount_amount = min(float(discount_value), total_ttc)
        elif discount_kind == "percent":
            discount_amount = total_ttc * min(float(discount_value), 100) / 100.0
        net_to_pay = round(total_ttc - discount_amount, 2)
        return {
            "subtotal_ht": round(subtotal_ht, 2),
            "total_tva": round(total_tva, 2),
            "total_ttc": round(total_ttc, 2),
            "discount_amount": round(discount_amount, 2),
            "net_to_pay": net_to_pay,
        }

    @router.post("/cashier/invoices")
    async def create_invoice(payload: InvoicePayload, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Vous n'avez pas l'autorisation de facturer.")
        if payload.kind not in ("proforma", "invoice"):
            raise HTTPException(status_code=400, detail="kind doit être 'proforma' ou 'invoice'")
        if payload.discount_kind not in ("none", "value", "percent"):
            raise HTTPException(status_code=400, detail="discount_kind invalide")
        bc = await db.business_clients.find_one({"id": payload.business_client_id, "deleted_at": None}, {"_id": 0})
        if not bc:
            raise HTTPException(status_code=404, detail="Client en compte introuvable")
        items = [it.model_dump() for it in payload.items]
        totals = _compute_invoice_totals(items, payload.discount_kind, payload.discount_value)
        year = datetime.now(timezone.utc).year
        prefix = "FP" if payload.kind == "proforma" else "F"
        seq = await _next_year_seq(f"invoices:{payload.kind}", year)
        number = f"{prefix}-{year}-{seq:04d}"
        token = secrets.token_urlsafe(24)
        doc = {
            "id": str(uuid.uuid4()),
            "number": number,
            "year": year,
            "seq": seq,
            "kind": payload.kind,
            "status": "issued",
            "business_client_id": bc["id"],
            "business_client_snapshot": {
                "name": bc.get("name"),
                "billing_address": payload.billing_address or bc.get("billing_address"),
                "shipping_address": payload.shipping_address or bc.get("shipping_address"),
                "nif": bc.get("nif"),
                "rccm": bc.get("rccm"),
                "phone": bc.get("phone"),
                "email": bc.get("email"),
            },
            "items": items,
            **totals,
            "discount_kind": payload.discount_kind,
            "discount_value": float(payload.discount_value),
            "amount_in_words": amount_to_words_fr(totals["net_to_pay"]),
            "notes": payload.notes,
            "due_date": payload.due_date,
            "created_by": user["id"],
            "created_by_name": user.get("full_name") or user.get("email"),
            "created_at": _now_iso(),
            "paid_at": None,
            "paid_via_receipt_id": None,
            "cancelled_at": None,
            "qr_token": token,
            "qr_url": await _build_verify_url(token),
        }
        await db.invoices.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.get("/cashier/invoices")
    async def list_invoices(
        kind: Optional[str] = None,
        status: Optional[str] = None,
        business_client_id: Optional[str] = None,
        limit: int = Query(50, ge=1, le=200),
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        q: Dict[str, Any] = {}
        if kind:
            q["kind"] = kind
        if status:
            q["status"] = status
        if business_client_id:
            q["business_client_id"] = business_client_id
        cursor = db.invoices.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
        return [i async for i in cursor]

    @router.get("/cashier/invoices/{iid}")
    async def get_invoice(iid: str, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        i = await db.invoices.find_one({"id": iid}, {"_id": 0})
        if not i:
            raise HTTPException(status_code=404, detail="Document introuvable")
        return i

    @router.get("/cashier/invoices/{iid}/qr.png")
    async def invoice_qr_png(iid: str, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        i = await db.invoices.find_one({"id": iid}, {"_id": 0, "qr_url": 1})
        if not i:
            raise HTTPException(status_code=404, detail="Document introuvable")
        return Response(content=build_qr_png(i["qr_url"]), media_type="image/png")

    @router.patch("/cashier/invoices/{iid}")
    async def patch_invoice(iid: str, payload: InvoicePatchPayload, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
        if not inv:
            raise HTTPException(status_code=404, detail="Document introuvable")
        updates: Dict[str, Any] = {}
        generated_receipt: Optional[dict] = None
        # 1) Convert proforma -> invoice (re-number)
        if payload.kind and payload.kind != inv["kind"]:
            if inv["kind"] != "proforma" or payload.kind != "invoice":
                raise HTTPException(status_code=400, detail="Conversion uniquement: proforma → facture")
            if inv["status"] == "cancelled":
                raise HTTPException(status_code=400, detail="Document annulé")
            year = datetime.now(timezone.utc).year
            seq = await _next_year_seq("invoices:invoice", year)
            updates["kind"] = "invoice"
            updates["year"] = year
            updates["seq"] = seq
            updates["number"] = f"F-{year}-{seq:04d}"
            updates["converted_from"] = inv["number"]
            updates["converted_at"] = _now_iso()
        # 2) Status transitions
        if payload.status:
            if payload.status not in ("paid", "cancelled"):
                raise HTTPException(status_code=400, detail="status doit être 'paid' ou 'cancelled'")
            current = updates.get("status") or inv["status"]
            if current == "paid" and payload.status == "cancelled":
                raise HTTPException(status_code=400, detail="Impossible d'annuler une facture déjà réglée")
            if payload.status == "cancelled":
                if not _can_cancel_invoice(user):
                    raise HTTPException(status_code=403, detail="Seuls Admin/Superviseur peuvent annuler")
                updates["status"] = "cancelled"
                updates["cancelled_at"] = _now_iso()
                updates["cancelled_by"] = user["id"]
            elif payload.status == "paid":
                # Must reach invoice kind first
                eff_kind = updates.get("kind") or inv["kind"]
                if eff_kind != "invoice":
                    raise HTTPException(status_code=400, detail="Convertissez en facture avant règlement")
                if not payload.payment_method_id:
                    raise HTTPException(status_code=400, detail="payment_method_id requis pour règlement")
                pm = await _resolve_payment_method(payload.payment_method_id)
                if not pm:
                    raise HTTPException(status_code=400, detail="Mode de paiement invalide")
                updates["status"] = "paid"
                updates["paid_at"] = _now_iso()
                updates["paid_by"] = user["id"]
                updates["paid_method_id"] = pm["id"]
                updates["paid_method_label"] = pm.get("label")
                updates["paid_reference"] = payload.payment_reference
                # Auto-generate the receipt
                year = datetime.now(timezone.utc).year
                rseq = await _next_year_seq("receipts", year)
                rnumber = f"R-{year}-{rseq:04d}"
                rtoken = secrets.token_urlsafe(24)
                rdoc = {
                    "id": str(uuid.uuid4()),
                    "number": rnumber,
                    "year": year,
                    "seq": rseq,
                    "business_client_id": inv["business_client_id"],
                    "business_client_snapshot": inv.get("business_client_snapshot"),
                    "beneficiary_name": (inv.get("business_client_snapshot") or {}).get("name"),
                    "amount": float(inv["net_to_pay"]),
                    "amount_in_words": amount_to_words_fr(float(inv["net_to_pay"])),
                    "motif": f"Règlement {updates.get('number', inv['number'])}",
                    "payment_method_id": pm["id"],
                    "payment_method_label": pm.get("label"),
                    "payment_method_kind": pm.get("kind"),
                    "payment_reference": payload.payment_reference,
                    "related_invoice_id": inv["id"],
                    "cashier_id": user["id"],
                    "cashier_name": user.get("full_name") or user.get("email"),
                    "issued_at": _now_iso(),
                    "qr_token": rtoken,
                    "qr_url": await _build_verify_url(rtoken),
                    "cancelled_at": None,
                }
                await db.receipts.insert_one(rdoc.copy())
                rdoc.pop("_id", None)
                updates["paid_via_receipt_id"] = rdoc["id"]
                generated_receipt = rdoc
        if updates:
            await db.invoices.update_one({"id": iid}, {"$set": updates})
        updated = await db.invoices.find_one({"id": iid}, {"_id": 0})
        return {"invoice": updated, "generated_receipt": generated_receipt}

    @router.post("/cashier/invoices/{iid}/receipt")
    async def generate_receipt_from_invoice(iid: str, payload: ReceiptPayload, user: dict = Depends(get_current_user)):
        """Explicit receipt generation for an ALREADY-paid invoice (reprint)."""
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
        if not inv:
            raise HTTPException(status_code=404, detail="Document introuvable")
        if inv["status"] != "paid":
            raise HTTPException(status_code=400, detail="Facture non réglée")
        # Re-use create_receipt logic (with related_invoice_id forced)
        payload.related_invoice_id = iid
        payload.business_client_id = inv["business_client_id"]
        return await create_receipt(payload, user)

    # ----------------------------------------------------------------
    # Public QR verification — minimal info, no auth
    # ----------------------------------------------------------------
    @router.get("/public/verify/{token}")
    async def public_verify(token: str):
        # Receipt?
        r = await db.receipts.find_one({"qr_token": token}, {"_id": 0})
        if r:
            return {
                "type": "receipt",
                "number": r["number"],
                "amount": r["amount"],
                "amount_in_words": r.get("amount_in_words"),
                "issued_at": r["issued_at"],
                "payment_method": r.get("payment_method_label"),
                "beneficiary": r.get("beneficiary_name"),
                "business_client": (r.get("business_client_snapshot") or {}).get("name"),
                "cancelled": bool(r.get("cancelled_at")),
                "motif": r.get("motif"),
            }
        i = await db.invoices.find_one({"qr_token": token}, {"_id": 0})
        if i:
            return {
                "type": i["kind"],  # 'proforma' or 'invoice'
                "number": i["number"],
                "net_to_pay": i.get("net_to_pay"),
                "amount_in_words": i.get("amount_in_words"),
                "status": i["status"],
                "issued_at": i["created_at"],
                "business_client": (i.get("business_client_snapshot") or {}).get("name"),
                "items_count": len(i.get("items") or []),
            }
        raise HTTPException(status_code=404, detail="Document introuvable")

    return router
