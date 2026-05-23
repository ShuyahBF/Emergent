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
from datetime import datetime, timezone, timedelta
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
    # Iter36y — Auto-relance toggle (per business client). Default OFF.
    auto_relance_enabled: Optional[bool] = False


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


def _normalize_phone_e164(raw: str) -> str:
    """Strip everything but digits; preserve leading + if present."""
    if not raw:
        return ""
    s = str(raw).strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D+", "", s)
    return f"+{digits}" if plus else digits


def _public_base_url(db_settings: Optional[dict]) -> str:
    if db_settings and db_settings.get("public_base_url"):
        return str(db_settings["public_base_url"]).rstrip("/")
    return (os.environ.get("PUBLIC_BASE_URL") or "https://sawalismartsystems.com").rstrip("/")


# =====================================================================
# Router factory
# =====================================================================
def make_router(*, db, get_current_user, get_current_admin, get_current_supervisor, wa_send_text=None, send_email=None):
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
                "phone": bc.get("phone"),
                "email": bc.get("email"),
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

    # Iter36v — Send receipt to client via WhatsApp (1-click)
    @router.post("/cashier/receipts/{rid}/send-whatsapp")
    async def receipt_send_whatsapp(
        rid: str,
        payload: dict = Body(default_factory=dict),
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        r = await db.receipts.find_one({"id": rid}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Reçu introuvable")
        if wa_send_text is None:
            raise HTTPException(status_code=503, detail="Envoi WhatsApp non configuré côté serveur")
        # Resolve recipient phone (override > snapshot > business_client doc)
        phone = (payload or {}).get("phone")
        if not phone:
            phone = (r.get("business_client_snapshot") or {}).get("phone")
        if not phone:
            bc = await db.business_clients.find_one({"id": r.get("business_client_id")}, {"_id": 0, "phone": 1}) or {}
            phone = bc.get("phone")
        if not phone:
            raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp pour ce client en compte")
        to_e164 = _normalize_phone_e164(phone)
        text = (
            f"📄 Reçu d'encaissement *{r['number']}*\n"
            f"Bénéficiaire : {r.get('beneficiary_name') or (r.get('business_client_snapshot') or {}).get('name')}\n"
            f"Montant : {float(r.get('amount') or 0):,.0f} FCFA\n"
            f"({r.get('amount_in_words') or ''})\n"
            f"Mode : {r.get('payment_method_label')}\n"
            f"Motif : {r.get('motif')}\n"
            f"Vérification : {r.get('qr_url')}"
        ).replace(",", " ")
        result = await wa_send_text(to_e164, text)
        if not result.get("ok"):
            return {
                "ok": False,
                "to": to_e164,
                "error": result.get("error") or "Échec WhatsApp",
                "status": result.get("status"),
                "fallback_wa_link": f"https://wa.me/{re.sub(r'[^0-9]', '', to_e164)}?text={text}",
            }
        await db.receipts.update_one(
            {"id": rid},
            {"$set": {
                "whatsapp_sent_at": _now_iso(),
                "whatsapp_message_id": result.get("message_id"),
                "whatsapp_to": to_e164,
                "whatsapp_sent_by": user["id"],
            }},
        )
        return {"ok": True, "to": to_e164, "message_id": result.get("message_id")}

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

    # Iter36v — Send invoice/proforma to client via WhatsApp (1-click)
    @router.post("/cashier/invoices/{iid}/send-whatsapp")
    async def invoice_send_whatsapp(
        iid: str,
        payload: dict = Body(default_factory=dict),
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
        if not inv:
            raise HTTPException(status_code=404, detail="Document introuvable")
        if wa_send_text is None:
            raise HTTPException(status_code=503, detail="Envoi WhatsApp non configuré côté serveur")
        phone = (payload or {}).get("phone") or (inv.get("business_client_snapshot") or {}).get("phone")
        if not phone:
            bc = await db.business_clients.find_one({"id": inv.get("business_client_id")}, {"_id": 0, "phone": 1}) or {}
            phone = bc.get("phone")
        if not phone:
            raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp pour ce client en compte")
        to_e164 = _normalize_phone_e164(phone)
        label = "Proforma" if inv.get("kind") == "proforma" else "Facture"
        status_label = {"issued": "Émise", "paid": "Réglée", "cancelled": "Annulée"}.get(inv.get("status") or "issued", inv.get("status") or "")
        text = (
            f"📑 {label} *{inv.get('number')}*\n"
            f"Client : {(inv.get('business_client_snapshot') or {}).get('name')}\n"
            f"Net à payer : {float(inv.get('net_to_pay') or 0):,.0f} FCFA\n"
            f"({inv.get('amount_in_words') or ''})\n"
            f"Statut : {status_label}\n"
            f"Vérification : {inv.get('qr_url')}"
        ).replace(",", " ")
        result = await wa_send_text(to_e164, text)
        if not result.get("ok"):
            return {
                "ok": False,
                "to": to_e164,
                "error": result.get("error") or "Échec WhatsApp",
                "status": result.get("status"),
                "fallback_wa_link": f"https://wa.me/{re.sub(r'[^0-9]', '', to_e164)}?text={text}",
            }
        await db.invoices.update_one(
            {"id": iid},
            {"$set": {
                "whatsapp_sent_at": _now_iso(),
                "whatsapp_message_id": result.get("message_id"),
                "whatsapp_to": to_e164,
                "whatsapp_sent_by": user["id"],
            }},
        )
        return {"ok": True, "to": to_e164, "message_id": result.get("message_id")}

    # =================================================================
    # Iter36x — Relance des factures impayées (bulk WhatsApp)
    # An invoice is considered "overdue" when:
    #   - kind == "invoice" AND status == "issued"  (not paid, not cancelled)
    #   - AND ( due_date set AND in the past )
    #     OR  ( due_date missing AND created more than `grace_days` ago )
    # =================================================================
    def _build_overdue_query(grace_days: int) -> Dict[str, Any]:
        today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, grace_days))).isoformat()
        return {
            "kind": "invoice",
            "status": "issued",
            "$or": [
                {"due_date": {"$nin": [None, ""], "$lt": today_iso}},
                {"due_date": {"$in": [None, ""]}, "created_at": {"$lt": cutoff}},
                {"due_date": {"$exists": False}, "created_at": {"$lt": cutoff}},
            ],
        }

    @router.get("/cashier/overdue/count")
    async def invoices_overdue_count(
        grace_days: int = Query(30, ge=0, le=365),
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        q = _build_overdue_query(grace_days)
        count = await db.invoices.count_documents(q)
        return {"count": count, "grace_days": grace_days}

    @router.post("/cashier/overdue/relance")
    async def invoices_relance_overdue(
        payload: dict = Body(default_factory=dict),
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        grace_days = int((payload or {}).get("grace_days") or 30)
        dry_run = bool((payload or {}).get("dry_run") or False)
        ids: Optional[List[str]] = (payload or {}).get("ids")
        q = _build_overdue_query(grace_days)
        if ids:
            q["id"] = {"$in": list(ids)}
        cursor = db.invoices.find(q, {"_id": 0}).sort("due_date", 1).limit(500)
        invoices = [i async for i in cursor]
        results: List[Dict[str, Any]] = []
        sent_ok = 0
        sent_ko = 0
        skipped_no_phone = 0
        for inv in invoices:
            iid = inv["id"]
            number = inv.get("number")
            phone = (inv.get("business_client_snapshot") or {}).get("phone")
            if not phone:
                bc = await db.business_clients.find_one({"id": inv.get("business_client_id")}, {"_id": 0, "phone": 1}) or {}
                phone = bc.get("phone")
            if not phone:
                skipped_no_phone += 1
                results.append({"id": iid, "number": number, "ok": False, "skipped": "no_phone"})
                continue
            to_e164 = _normalize_phone_e164(phone)
            if dry_run:
                results.append({"id": iid, "number": number, "ok": True, "dry_run": True, "to": to_e164})
                continue
            if wa_send_text is None:
                sent_ko += 1
                results.append({"id": iid, "number": number, "ok": False, "error": "WA non configuré"})
                continue
            client_name = (inv.get("business_client_snapshot") or {}).get("name") or "Cher client"
            net = float(inv.get("net_to_pay") or 0)
            due = inv.get("due_date") or "—"
            text = (
                f"🔔 Rappel — Facture *{number}*\n"
                f"Bonjour {client_name},\n"
                f"Cette facture de *{net:,.0f} FCFA* est arrivée à échéance le *{due}* "
                f"et n'a pas encore été réglée à ce jour.\n"
                f"Vérification : {inv.get('qr_url')}\n"
                f"Merci de procéder au règlement dès que possible. "
                f"L'équipe SAWALI."
            ).replace(",", " ")
            res = await wa_send_text(to_e164, text)
            if res.get("ok"):
                sent_ok += 1
                await db.invoices.update_one(
                    {"id": iid},
                    {"$set": {
                        "last_reminder_at": _now_iso(),
                        "last_reminder_message_id": res.get("message_id"),
                        "last_reminder_to": to_e164,
                        "last_reminder_by": user["id"],
                    }, "$inc": {"reminders_count": 1}},
                )
                results.append({"id": iid, "number": number, "ok": True, "to": to_e164})
            else:
                sent_ko += 1
                results.append({
                    "id": iid, "number": number, "ok": False,
                    "error": res.get("error"), "status": res.get("status"),
                })
        return {
            "total": len(invoices),
            "sent_ok": sent_ok,
            "sent_ko": sent_ko,
            "skipped_no_phone": skipped_no_phone,
            "dry_run": dry_run,
            "grace_days": grace_days,
            "results": results,
        }

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

    # =================================================================
    # Iter36w — CSV / PDF exports for receipts & invoices
    # =================================================================
    def _csv_response(rows: List[List[Any]], filename: str) -> Response:
        import csv as _csv
        buf = io.StringIO()
        buf.write("\ufeff")  # Excel UTF-8 BOM
        writer = _csv.writer(buf, delimiter=";")
        for row in rows:
            writer.writerow(row)
        return Response(
            content=buf.getvalue().encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def _fmt_dt(iso: Optional[str]) -> str:
        if not iso:
            return ""
        try:
            return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
        except Exception:
            return str(iso)[:16]

    def _pdf_response(title: str, header: List[str], rows: List[List[str]], filename: str, totals_line: Optional[str] = None) -> Response:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                                topMargin=24, bottomMargin=24, leftMargin=24, rightMargin=24, title=title)
        styles = getSampleStyleSheet()
        now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M")
        story: List[Any] = [
            Paragraph(f"<b>SAWALI Smart Systems — {title}</b>", styles["Title"]),
            Paragraph(f"Généré le {now_str} — {len(rows)} ligne(s)", styles["Normal"]),
            Spacer(1, 10),
        ]
        if totals_line:
            story.append(Paragraph(totals_line, styles["Normal"]))
            story.append(Spacer(1, 8))
        data: List[List[str]] = [header] + rows
        tbl = Table(data, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E90FF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(tbl)
        doc.build(story)
        return Response(
            content=buf.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def _query_receipts(business_client_id: Optional[str], limit: int) -> List[dict]:
        q: Dict[str, Any] = {}
        if business_client_id:
            q["business_client_id"] = business_client_id
        return await db.receipts.find(q, {"_id": 0}).sort("issued_at", -1).limit(limit).to_list(limit)

    async def _query_invoices(kind: Optional[str], status: Optional[str], business_client_id: Optional[str], limit: int) -> List[dict]:
        q: Dict[str, Any] = {}
        if kind:
            q["kind"] = kind
        if status:
            q["status"] = status
        if business_client_id:
            q["business_client_id"] = business_client_id
        return await db.invoices.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)

    @router.get("/cashier/exports/receipts.csv")
    async def export_receipts_csv(
        limit: int = Query(500, ge=1, le=2000),
        business_client_id: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        items = await _query_receipts(business_client_id, limit)
        rows: List[List[Any]] = [["N°", "Date", "Client en compte", "Bénéficiaire", "Motif",
                                  "Montant (FCFA)", "Mode de paiement", "Référence",
                                  "Caissier", "Envoyé WA", "Annulé"]]
        for r in items:
            rows.append([
                r.get("number") or "",
                _fmt_dt(r.get("issued_at")),
                (r.get("business_client_snapshot") or {}).get("name") or "",
                r.get("beneficiary_name") or "",
                (r.get("motif") or "").replace("\n", " "),
                f"{float(r.get('amount') or 0):.0f}",
                r.get("payment_method_label") or "",
                r.get("payment_reference") or "",
                r.get("cashier_name") or "",
                _fmt_dt(r.get("whatsapp_sent_at")) or "—",
                _fmt_dt(r.get("cancelled_at")) or "",
            ])
        fname = f"recus-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
        return _csv_response(rows, fname)

    @router.get("/cashier/exports/receipts.pdf")
    async def export_receipts_pdf(
        limit: int = Query(500, ge=1, le=2000),
        business_client_id: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        items = await _query_receipts(business_client_id, limit)
        rows: List[List[str]] = []
        total = 0.0
        active = 0
        for r in items:
            amount = float(r.get("amount") or 0)
            if not r.get("cancelled_at"):
                total += amount
                active += 1
            rows.append([
                str(r.get("number") or ""),
                _fmt_dt(r.get("issued_at")),
                ((r.get("business_client_snapshot") or {}).get("name") or "")[:38],
                (r.get("motif") or "")[:42],
                f"{amount:,.0f}".replace(",", " "),
                (r.get("payment_method_label") or "")[:22],
                (r.get("cashier_name") or "")[:22],
                "✓ " + _fmt_dt(r.get("whatsapp_sent_at")) if r.get("whatsapp_sent_at") else "—",
                "ANNULÉ" if r.get("cancelled_at") else "",
            ])
        header = ["N°", "Date", "Client", "Motif", "Montant", "Paiement", "Caissier", "WA", "Statut"]
        totals = f"<b>Total encaissé (non annulé)</b> : {total:,.0f} FCFA — {active} reçu(s) actifs sur {len(items)} listés.".replace(",", " ")
        fname = f"recus-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.pdf"
        return _pdf_response("Liste des reçus d'encaissement", header, rows, fname, totals_line=totals)

    @router.get("/cashier/exports/invoices.csv")
    async def export_invoices_csv(
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = Query(500, ge=1, le=2000),
        business_client_id: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        items = await _query_invoices(kind, status, business_client_id, limit)
        rows: List[List[Any]] = [["N°", "Type", "Statut", "Date", "Client", "NIF/RCCM",
                                  "Sous-total HT", "TVA", "Total TTC", "Remise", "Net à payer",
                                  "Réglé via", "Envoyé WA", "Annulé"]]
        for i in items:
            snap = i.get("business_client_snapshot") or {}
            rows.append([
                i.get("number") or "",
                "Proforma" if i.get("kind") == "proforma" else "Facture",
                {"issued": "Émis", "paid": "Réglée", "cancelled": "Annulée"}.get(i.get("status") or "issued", i.get("status") or ""),
                _fmt_dt(i.get("created_at")),
                snap.get("name") or "",
                " / ".join([x for x in [snap.get("nif"), snap.get("rccm")] if x]),
                f"{float(i.get('subtotal_ht') or 0):.0f}",
                f"{float(i.get('total_tva') or 0):.0f}",
                f"{float(i.get('total_ttc') or 0):.0f}",
                f"{float(i.get('discount_value') or 0):.0f} ({i.get('discount_kind') or 'none'})",
                f"{float(i.get('net_to_pay') or 0):.0f}",
                i.get("paid_method_label") or "",
                _fmt_dt(i.get("whatsapp_sent_at")) or "—",
                _fmt_dt(i.get("cancelled_at")) or "",
            ])
        fname = f"factures-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
        return _csv_response(rows, fname)

    @router.get("/cashier/exports/invoices.pdf")
    async def export_invoices_pdf(
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = Query(500, ge=1, le=2000),
        business_client_id: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        items = await _query_invoices(kind, status, business_client_id, limit)
        rows: List[List[str]] = []
        total_due = 0.0
        total_paid = 0.0
        for i in items:
            net = float(i.get("net_to_pay") or 0)
            if i.get("status") == "paid":
                total_paid += net
            elif i.get("status") == "issued":
                total_due += net
            rows.append([
                str(i.get("number") or ""),
                "Proforma" if i.get("kind") == "proforma" else "Facture",
                {"issued": "Émis", "paid": "Réglée", "cancelled": "Annulée"}.get(i.get("status") or "issued", "")[:10],
                _fmt_dt(i.get("created_at")),
                ((i.get("business_client_snapshot") or {}).get("name") or "")[:30],
                f"{float(i.get('total_ttc') or 0):,.0f}".replace(",", " "),
                f"{net:,.0f}".replace(",", " "),
                "✓ " + _fmt_dt(i.get("whatsapp_sent_at")) if i.get("whatsapp_sent_at") else "—",
            ])
        header = ["N°", "Type", "Statut", "Date", "Client", "TTC", "Net à payer", "WA"]
        totals = (
            f"<b>Encaissé</b> : {total_paid:,.0f} FCFA &nbsp;&nbsp; "
            f"<b>En attente</b> : {total_due:,.0f} FCFA &nbsp;&nbsp; "
            f"<b>Lignes</b> : {len(items)}"
        ).replace(",", " ")
        fname = f"factures-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.pdf"
        return _pdf_response("Liste des factures & proformas", header, rows, fname, totals_line=totals)

    # =================================================================
    # Iter36y — Auto-relance quotidienne (cron + email rapport)
    # =================================================================
    async def _send_one_reminder(inv: dict, actor_id: Optional[str]) -> dict:
        phone = (inv.get("business_client_snapshot") or {}).get("phone")
        if not phone:
            bc = await db.business_clients.find_one({"id": inv.get("business_client_id")}, {"_id": 0, "phone": 1}) or {}
            phone = bc.get("phone")
        if not phone:
            return {"id": inv["id"], "number": inv.get("number"), "ok": False, "skipped": "no_phone"}
        to_e164 = _normalize_phone_e164(phone)
        if wa_send_text is None:
            return {"id": inv["id"], "number": inv.get("number"), "ok": False, "error": "WA non configuré"}
        client_name = (inv.get("business_client_snapshot") or {}).get("name") or "Cher client"
        net = float(inv.get("net_to_pay") or 0)
        due = inv.get("due_date") or "—"
        text = (
            f"🔔 Rappel — Facture *{inv.get('number')}*\n"
            f"Bonjour {client_name},\n"
            f"Cette facture de *{net:,.0f} FCFA* est arrivée à échéance le *{due}* "
            f"et n'a pas encore été réglée à ce jour.\n"
            f"Vérification : {inv.get('qr_url')}\n"
            f"Merci de procéder au règlement dès que possible. "
            f"L'équipe SAWALI."
        ).replace(",", " ")
        res = await wa_send_text(to_e164, text)
        if not res.get("ok"):
            return {"id": inv["id"], "number": inv.get("number"), "ok": False,
                    "error": res.get("error"), "status": res.get("status")}
        await db.invoices.update_one(
            {"id": inv["id"]},
            {"$set": {
                "last_reminder_at": _now_iso(),
                "last_reminder_message_id": res.get("message_id"),
                "last_reminder_to": to_e164,
                "last_reminder_by": actor_id or "cron:auto-relance",
            }, "$inc": {"reminders_count": 1}},
        )
        return {"id": inv["id"], "number": inv.get("number"), "ok": True, "to": to_e164}

    async def run_auto_relance(triggered_by: str = "cron") -> Dict[str, Any]:
        """Iter36y — Execute the auto-relance round.
        Reads global settings:
          - auto_relance_enabled (master, default False)
          - auto_relance_day_of_week (0=Mon..6=Sun, default 0)
          - auto_relance_grace_days (default 30)
          - auto_relance_email_report_to (admin recipient)
        Only acts on business_clients with `auto_relance_enabled=True`.
        Today must match `auto_relance_day_of_week` when triggered by cron;
        manual triggers bypass the weekday check.
        """
        settings_doc = await db.settings.find_one({"_id": "global"}) or {}
        is_manual = triggered_by.startswith("manual")
        if not settings_doc.get("auto_relance_enabled") and not is_manual:
            return {"skipped": True, "reason": "master_disabled", "triggered_by": triggered_by}
        cfg_dow = int(settings_doc.get("auto_relance_day_of_week", 0) or 0)
        grace_days = int(settings_doc.get("auto_relance_grace_days", 30) or 30)
        recipient = settings_doc.get("auto_relance_email_report_to") or settings_doc.get("health_email_to")
        # Weekday check (only for cron trigger). 0=Mon..6=Sun.
        if not is_manual and datetime.now(timezone.utc).weekday() != cfg_dow:
            return {"skipped": True, "reason": "not_today_dow",
                    "configured_dow": cfg_dow,
                    "today_dow": datetime.now(timezone.utc).weekday()}
        # Resolve eligible business_clients
        eligible_bcs = await db.business_clients.find(
            {"auto_relance_enabled": True, "deleted_at": None},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(2000)
        if not eligible_bcs:
            run_doc = {
                "id": str(uuid.uuid4()),
                "triggered_by": triggered_by,
                "started_at": _now_iso(),
                "ended_at": _now_iso(),
                "skipped": True,
                "reason": "no_eligible_business_clients",
                "grace_days": grace_days,
            }
            await db.auto_relance_runs.insert_one(run_doc.copy())
            run_doc.pop("_id", None)
            return run_doc
        bc_ids = [bc["id"] for bc in eligible_bcs]
        q = _build_overdue_query(grace_days)
        q["business_client_id"] = {"$in": bc_ids}
        invoices = await db.invoices.find(q, {"_id": 0}).sort("due_date", 1).limit(2000).to_list(2000)
        results: List[Dict[str, Any]] = []
        sent_ok = 0
        sent_ko = 0
        skipped_no_phone = 0
        for inv in invoices:
            r = await _send_one_reminder(inv, actor_id=f"{triggered_by}")
            results.append(r)
            if r.get("ok"):
                sent_ok += 1
            elif r.get("skipped") == "no_phone":
                skipped_no_phone += 1
            else:
                sent_ko += 1
        run_doc = {
            "id": str(uuid.uuid4()),
            "triggered_by": triggered_by,
            "started_at": _now_iso(),
            "ended_at": _now_iso(),
            "total": len(invoices),
            "sent_ok": sent_ok,
            "sent_ko": sent_ko,
            "skipped_no_phone": skipped_no_phone,
            "grace_days": grace_days,
            "business_clients_count": len(eligible_bcs),
            "email_report": {"sent": False, "to": recipient, "error": None},
        }
        # Email report (best-effort)
        if recipient and send_email is not None:
            try:
                rows_html = "".join(
                    f"<tr><td>{r.get('number','')}</td><td>{r.get('to','')}</td>"
                    f"<td style='color:{'#16a34a' if r.get('ok') else '#dc2626'}'>"
                    f"{'OK' if r.get('ok') else (r.get('skipped') or r.get('error') or 'KO')}</td></tr>"
                    for r in results[:50]
                )
                html = (
                    f"<h2>SAWALI — Rapport de relance automatique</h2>"
                    f"<p><b>Déclencheur</b> : {triggered_by}<br>"
                    f"<b>Date</b> : {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}<br>"
                    f"<b>Clients en compte ciblés</b> : {len(eligible_bcs)}<br>"
                    f"<b>Factures relancées</b> : {len(invoices)} "
                    f"(✓ {sent_ok} envoyée(s), ✗ {sent_ko} échec(s), ⊝ {skipped_no_phone} sans n°)</p>"
                    f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:sans-serif;font-size:13px'>"
                    f"<thead><tr style='background:#1E90FF;color:white'><th>N° facture</th><th>Destinataire</th><th>Statut</th></tr></thead>"
                    f"<tbody>{rows_html}</tbody></table>"
                    f"<p style='color:#64748b;font-size:11px'>SAWALI Smart Systems — auto_relance_runs id: {run_doc['id']}</p>"
                )
                text = (
                    f"SAWALI — Relance auto ({triggered_by})\n"
                    f"Clients ciblés : {len(eligible_bcs)} — Factures relancées : {len(invoices)}\n"
                    f"OK : {sent_ok} | KO : {sent_ko} | Sans n° : {skipped_no_phone}\n"
                )
                ok = await send_email(recipient, f"[SAWALI] Relance auto — {sent_ok} OK / {sent_ko} KO", html, text)
                run_doc["email_report"]["sent"] = bool(ok)
                if not ok:
                    run_doc["email_report"]["error"] = "send_email returned False"
            except Exception as exc:  # noqa: BLE001
                run_doc["email_report"]["error"] = str(exc)[:200]
        await db.auto_relance_runs.insert_one(run_doc.copy())
        run_doc.pop("_id", None)
        run_doc["results"] = results  # included in response (not in db doc to keep it small)
        return run_doc

    @router.post("/cashier/overdue/relance-auto-run")
    async def relance_auto_run(user: dict = Depends(get_current_supervisor)):
        """Iter36y — Trigger the auto-relance flow manually (admin/superviseur)."""
        return await run_auto_relance(triggered_by=f"manual:{user.get('email') or user['id']}")

    @router.get("/cashier/overdue/relance-history")
    async def relance_history(limit: int = Query(20, ge=1, le=200), _: dict = Depends(get_current_supervisor)):
        cursor = db.auto_relance_runs.find({}, {"_id": 0}).sort("started_at", -1).limit(limit)
        return [r async for r in cursor]

    # =================================================================
    # Iter36z — KPIs dashboard (Facturation header)
    # =================================================================
    @router.get("/cashier/kpis")
    async def invoices_kpis(user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        ninety_days_ago = (now - timedelta(days=90)).isoformat()
        # 1) Encaissé ce mois (status=paid AND paid_at >= month_start)
        paid_cursor = db.invoices.find(
            {"kind": "invoice", "status": "paid", "paid_at": {"$gte": month_start}},
            {"_id": 0, "net_to_pay": 1},
        )
        paid_amount = 0.0
        paid_count = 0
        async for inv in paid_cursor:
            paid_amount += float(inv.get("net_to_pay") or 0)
            paid_count += 1
        # 2) Restant à encaisser (status=issued)
        due_cursor = db.invoices.find(
            {"kind": "invoice", "status": "issued"},
            {"_id": 0, "net_to_pay": 1},
        )
        due_amount = 0.0
        due_count = 0
        async for inv in due_cursor:
            due_amount += float(inv.get("net_to_pay") or 0)
            due_count += 1
        # 3) Délai moyen de paiement (en jours) — sur les factures payées des 90 derniers jours
        recent_paid_cursor = db.invoices.find(
            {"kind": "invoice", "status": "paid", "paid_at": {"$gte": ninety_days_ago}},
            {"_id": 0, "created_at": 1, "paid_at": 1},
        )
        deltas: List[float] = []
        async for inv in recent_paid_cursor:
            try:
                c = datetime.fromisoformat(str(inv["created_at"]).replace("Z", "+00:00"))
                p = datetime.fromisoformat(str(inv["paid_at"]).replace("Z", "+00:00"))
                deltas.append((p - c).total_seconds() / 86400.0)
            except Exception:
                continue
        avg_days = round(sum(deltas) / len(deltas), 1) if deltas else None
        # 4) Top 3 "mauvais payeurs" — agrégat par business_client sur les factures issued
        today_iso = now.strftime("%Y-%m-%d")
        bad_payers_pipeline = [
            {"$match": {"kind": "invoice", "status": "issued"}},
            {"$group": {
                "_id": "$business_client_id",
                "unpaid_amount": {"$sum": "$net_to_pay"},
                "unpaid_count": {"$sum": 1},
                "name": {"$first": "$business_client_snapshot.name"},
                "earliest_due": {"$min": "$due_date"},
            }},
            {"$sort": {"unpaid_amount": -1}},
            {"$limit": 3},
        ]
        top_bad_payers: List[Dict[str, Any]] = []
        async for row in db.invoices.aggregate(bad_payers_pipeline):
            bc_id = row.get("_id")
            avg_overdue_days = None
            ed = row.get("earliest_due")
            if ed and isinstance(ed, str):
                try:
                    due_dt = datetime.strptime(ed[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    diff = (now - due_dt).days
                    if diff > 0:
                        avg_overdue_days = diff
                except Exception:
                    pass
            top_bad_payers.append({
                "business_client_id": bc_id,
                "name": row.get("name") or "—",
                "unpaid_amount": float(row.get("unpaid_amount") or 0),
                "unpaid_count": int(row.get("unpaid_count") or 0),
                "oldest_overdue_days": avg_overdue_days,
            })
        return {
            "encaisse_this_month": {"amount": paid_amount, "count": paid_count,
                                    "period_start": month_start, "currency": "XOF"},
            "restant_a_encaisser": {"amount": due_amount, "count": due_count, "currency": "XOF"},
            "delai_moyen_jours": avg_days,
            "delai_moyen_sample_size": len(deltas),
            "top_bad_payers": top_bad_payers,
            "as_of": _now_iso(),
        }

    return router, run_auto_relance
