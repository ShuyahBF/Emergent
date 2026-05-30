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
    whatsapp: Optional[str] = Field(None, max_length=40)  # Iter37a — dedicated WhatsApp number (fallback to phone if empty)
    email: Optional[str] = Field(None, max_length=200)
    billing_address: Optional[str] = Field(None, max_length=500)
    shipping_address: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=500)
    # Iter36y — Auto-relance toggle (per business client). Default OFF.
    auto_relance_enabled: Optional[bool] = False
    # Iter37a — Preferred reminder channel: 'whatsapp' (default) | 'email' | 'both'
    relance_channel: Optional[str] = Field("whatsapp", max_length=20)


class ProductPayload(BaseModel):
    # Iter37a — SKU is now auto-generated server-side per Client Lié (tenant).
    # It is read-only post-creation. Clients may pass an empty string or omit it.
    sku: Optional[str] = Field(None, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=80)
    unit: str = Field("pièce", max_length=30)  # heure / jour / forfait / pièce
    unit_price_ht: float = Field(..., ge=0)
    tva_pct: float = Field(0, ge=0, le=100)
    stock: Optional[int] = Field(None, ge=0)  # None = non géré
    image_url: Optional[str] = Field(None, max_length=500)
    active: bool = True
    # Iter38e (B.3) — Toggle to expose this product in a future public catalog page.
    is_public: bool = False


class LegalFormPayload(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)


class ProductCategoryPayload(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)


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


# =====================================================================
# Iter37g — PDF generation for receipts + invoices (for WhatsApp templates)
# =====================================================================
def _fmt_money(n: float) -> str:
    """Format an amount with thousand separators (FR style: spaces) — no decimals."""
    return f"{round(float(n or 0)):,}".replace(",", " ")


def build_receipt_pdf(receipt: dict) -> bytes:
    """ReportLab PDF for a receipt — clean, professional, A5 portrait."""
    from reportlab.lib.pagesizes import A5
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A5,
        topMargin=24, bottomMargin=24, leftMargin=24, rightMargin=24,
        title=f"Recu {receipt.get('number', '')}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=16, textColor=colors.HexColor("#0EA5E9"), alignment=1)
    h2 = ParagraphStyle("H2", parent=styles["Heading3"], fontSize=11, spaceAfter=4)
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=12)
    muted = ParagraphStyle("Muted", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#64748b"), leading=11)

    tenant = receipt.get("tenant_snapshot") or {}
    bc = receipt.get("business_client_snapshot") or {}
    story: List[Any] = [
        Paragraph(f"<b>{tenant.get('name') or 'SAWALI SMART SYSTEMS'}</b>", title_style),
        Paragraph(tenant.get("billing_address") or "", muted),
        Spacer(1, 6),
        Paragraph("REÇU D'ENCAISSEMENT", h2),
        Paragraph(f"<b>N°</b> {receipt.get('number', '—')} &nbsp;&nbsp; <b>Date</b> : {(receipt.get('issued_at') or '')[:10]}", body),
        Spacer(1, 6),
    ]
    data = [
        ["Bénéficiaire", receipt.get("beneficiary_name") or bc.get("name") or "—"],
        ["Client en compte", bc.get("name") or "—"],
        ["Montant", f"{_fmt_money(receipt.get('amount'))} FCFA"],
        ["En lettres", receipt.get("amount_in_words") or "—"],
        ["Mode de paiement", receipt.get("payment_method_label") or "—"],
        ["Réf. paiement", receipt.get("payment_reference") or "—"],
        ["Motif", receipt.get("motif") or "—"],
    ]
    tbl = Table(data, colWidths=[110, 270])
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))
    # QR code embedded
    try:
        qr_url = receipt.get("qr_url") or ""
        if qr_url:
            png = build_qr_png(qr_url)
            qr_buf = io.BytesIO(png)
            story.append(RLImage(qr_buf, width=80, height=80, hAlign="LEFT"))
            story.append(Paragraph(f"<font color='#64748b' size='7'>Vérification : {qr_url}</font>", muted))
    except Exception:
        pass
    story.append(Spacer(1, 4))
    cancel_line = '<b><font color="#dc2626">ANNULÉ</font></b>' if receipt.get('cancelled_at') else ''
    story.append(Paragraph(
        f"Encaissé par : {receipt.get('cashier_name') or '—'}<br/>{cancel_line}",
        body,
    ))
    doc.build(story)
    return buf.getvalue()


def build_invoice_pdf(invoice: dict) -> bytes:
    """ReportLab PDF for a proforma/invoice — A4 portrait, items table, totals."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    kind = invoice.get("kind") or "invoice"
    label = "FACTURE" if kind == "invoice" else "PROFORMA"
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=28, bottomMargin=28, leftMargin=28, rightMargin=28,
        title=f"{label} {invoice.get('number', '')}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=18, textColor=colors.HexColor("#0EA5E9"), alignment=0)
    h2 = ParagraphStyle("H2", parent=styles["Heading3"], fontSize=12, spaceAfter=4)
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=12)
    muted = ParagraphStyle("Muted", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#64748b"), leading=11)

    tenant = invoice.get("tenant_snapshot") or {}
    bc = invoice.get("business_client_snapshot") or {}
    story: List[Any] = [
        Paragraph(f"<b>{tenant.get('name') or 'SAWALI SMART SYSTEMS'}</b>", title_style),
        Paragraph(tenant.get("billing_address") or "", muted),
        Spacer(1, 8),
        Paragraph(f"{label} N° {invoice.get('number', '—')}", h2),
        Paragraph(
            f"<b>Date</b> : {(invoice.get('created_at') or '')[:10]} &nbsp;&nbsp; "
            f"<b>Statut</b> : {(invoice.get('status') or 'issued').upper()} &nbsp;&nbsp; "
            f"<b>Échéance</b> : {invoice.get('due_date') or '—'}", body,
        ),
        Spacer(1, 8),
        Paragraph(f"<b>Client</b> : {bc.get('name') or '—'}", body),
        Paragraph(f"<font color='#64748b'>{bc.get('billing_address') or ''}</font>", muted),
        Spacer(1, 10),
    ]

    items = invoice.get("items") or []
    if items:
        item_rows = [["Désignation", "Qté", "PU HT", "TVA %", "Total TTC"]]
        for it in items:
            item_rows.append([
                (it.get("label") or it.get("description") or "")[:60],
                str(it.get("quantity") or ""),
                _fmt_money(it.get("unit_price_ht")),
                f"{it.get('tva_pct') or 0}%",
                _fmt_money(it.get("line_total_ttc")),
            ])
        itbl = Table(item_rows, colWidths=[210, 50, 80, 50, 90], repeatRows=1)
        itbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0EA5E9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(itbl)
        story.append(Spacer(1, 8))

    totals_rows = [
        ["Sous-total HT", f"{_fmt_money(invoice.get('subtotal_ht'))} FCFA"],
        ["TVA", f"{_fmt_money(invoice.get('total_tva'))} FCFA"],
        ["Remise", f"{_fmt_money(invoice.get('discount_amount'))} FCFA"],
        ["Net à payer", f"{_fmt_money(invoice.get('net_to_pay'))} FCFA"],
    ]
    ttbl = Table(totals_rows, colWidths=[120, 100], hAlign="RIGHT")
    ttbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fef3c7")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#94a3b8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ttbl)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<i>{invoice.get('amount_in_words') or ''}</i>", muted))
    if invoice.get("notes"):
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>Note</b> : {invoice.get('notes')}", body))
    # QR
    try:
        qr_url = invoice.get("qr_url") or ""
        if qr_url:
            story.append(Spacer(1, 10))
            png = build_qr_png(qr_url)
            qr_buf = io.BytesIO(png)
            story.append(RLImage(qr_buf, width=70, height=70, hAlign="LEFT"))
            story.append(Paragraph(f"<font color='#64748b' size='7'>Vérification : {qr_url}</font>", muted))
    except Exception:
        pass
    doc.build(story)
    return buf.getvalue()



def _is_super_admin(user: dict) -> bool:
    """Iter37e — SAWALI super-admin (sees data across all tenants)."""
    return (user.get("email") or "").lower() == "admin@sawalismartsystems.com"


def _is_admin_or_supervisor(user: dict) -> bool:
    role = (user or {}).get("role")
    return role in ("admin", "superviseur")


def _can_invoice(user: dict) -> bool:
    """Admin/Superviseur OR users.can_cash=True can invoice."""
    return _is_admin_or_supervisor(user) or bool((user or {}).get("can_cash"))


def _is_comptable(user: dict) -> bool:
    """Iter38 — Comptable tracked role (Caisse read-only + GRH write)."""
    return (user.get("tracked_role") or "") == "Comptable"


def _can_view_cashier(user: dict) -> bool:
    """Iter38 — Read-only access for Comptable, plus all _can_invoice roles."""
    return _can_invoice(user) or _is_comptable(user)


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


def _pick_wa_phone(snapshot: Optional[dict], live_bc: Optional[dict]) -> Optional[str]:
    """Iter37a — Prefer dedicated `whatsapp` over `phone` (snapshot first, then live)."""
    for src in (snapshot or {}, live_bc or {}):
        v = src.get("whatsapp") or src.get("phone")
        if v:
            return v
    return None


def _public_base_url(db_settings: Optional[dict]) -> str:
    # 1. Explicit DB setting wins.
    if db_settings and db_settings.get("public_base_url"):
        return str(db_settings["public_base_url"]).rstrip("/")
    # 2. Env var — but reject preview/dev URLs so receipts generated in the
    #    preview environment do NOT bake preview hostnames into the QR.
    env_url = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env_url and ".preview.emergentagent.com" not in env_url and ".localhost" not in env_url:
        return env_url
    # 3. Safe default: production domain.
    return "https://sawalismartsystems.com"


# =====================================================================
# Iter37e/f — Tenant backfill (idempotent, runs at startup AND on demand).
# Assigns `tenant_id` to legacy docs. Resolution order:
#   1) doc.client_id (legacy field already storing the tenant)
#   2) creator.parent_client_id || creator.client_id || creator.id
#   3) Iter37f — Canonical user matching creator.company (admin > sup > oldest)
# Set `rewrite=True` to RE-evaluate all docs (e.g. after upgrading the
# resolution logic). This is what fixes prod users who weren't sharing data
# because they had separate `tenant_id` values written by an earlier run.
# =====================================================================
async def backfill_tenant_ids(db, *, rewrite: bool = False) -> Dict[str, int]:
    """Idempotent: assign tenant_id to legacy Caisse docs.

    Args:
      rewrite: when True, recompute tenant_id for EVERY doc (overwriting
        any previously assigned value). Used after upgrading the tenant
        resolution to consolidate split tenants caused by mis-linked users.

    Returns a dict {collection_name: rows_updated}.
    """
    stats: Dict[str, int] = {}
    user_cache: Dict[str, Optional[str]] = {}
    company_cache: Dict[str, Optional[str]] = {}

    async def _canonical_by_company(company: str) -> Optional[str]:
        if not company:
            return None
        key = company.strip().lower()
        if key in company_cache:
            return company_cache[key]
        for role_filter in (
            {"role": "admin"},
            {"role": "superviseur"},
            {"account_status": {"$ne": "deleted"}},
        ):
            canonical = await db.users.find_one(
                {**role_filter, "company": company.strip()},
                {"_id": 0, "id": 1},
                sort=[("created_at", 1)],
            )
            if canonical:
                company_cache[key] = canonical.get("id")
                return canonical.get("id")
        company_cache[key] = None
        return None

    async def _tenant_for(uid: Optional[str]) -> Optional[str]:
        if not uid:
            return None
        if uid in user_cache:
            return user_cache[uid]
        u = await db.users.find_one(
            {"id": uid},
            {"_id": 0, "id": 1, "parent_client_id": 1, "client_id": 1, "company": 1},
        )
        if not u:
            user_cache[uid] = uid  # fallback to creator id
            return uid
        # Try parent_client_id / client_id pointing to another user
        for key in ("parent_client_id", "client_id"):
            ref = u.get(key)
            if ref and ref != uid:
                user_cache[uid] = ref
                return ref
        # Iter37f — Resolve canonical by company
        canon = await _canonical_by_company(u.get("company") or "")
        if canon:
            user_cache[uid] = canon
            return canon
        user_cache[uid] = uid
        return uid

    collections = ("business_clients", "receipts", "invoices",
                   "legal_forms", "product_categories", "payment_methods")
    for cname in collections:
        coll = db[cname]
        n = 0
        query = {} if rewrite else {"tenant_id": {"$exists": False}}
        cursor = coll.find(
            query,
            {"_id": 0, "id": 1, "created_by": 1, "client_id": 1, "tenant_id": 1},
        )
        async for doc in cursor:
            # Compute the canonical tenant
            tid = doc.get("client_id") or await _tenant_for(doc.get("created_by"))
            # Promote via creator → canonical (in case client_id was the creator's own id)
            if tid and rewrite:
                resolved = await _tenant_for(tid)
                if resolved:
                    tid = resolved
            if tid and (rewrite or tid != doc.get("tenant_id")):
                await coll.update_one({"id": doc["id"]}, {"$set": {"tenant_id": tid}})
                n += 1
        stats[cname] = n
    # Products: ensure tenant_id == client_id (already populated)
    n_products = 0
    pq = {} if rewrite else {"tenant_id": {"$exists": False}, "client_id": {"$ne": None}}
    cursor = db.products.find(pq, {"_id": 0, "id": 1, "client_id": 1, "tenant_id": 1})
    async for doc in cursor:
        tid = await _tenant_for(doc.get("client_id")) if rewrite else doc.get("client_id")
        if tid and (rewrite or tid != doc.get("tenant_id")):
            await db.products.update_one({"id": doc["id"]}, {"$set": {"tenant_id": tid}})
            n_products += 1
    stats["products"] = n_products
    return stats


# =====================================================================
# Router factory
# =====================================================================
def make_router(*, db, get_current_user, get_current_admin, get_current_supervisor, wa_send_text=None, wa_send_template=None, send_email=None):
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

    async def _resolve_payment_method(pm_id: str, user: Optional[dict] = None) -> Optional[dict]:
        # Iter37e — Tenant scoping (best-effort: caller may pass user for strict check)
        q: Dict[str, Any] = {"id": pm_id, "active": True}
        if user is not None and not _is_super_admin(user):
            tid = await _tenant_id_of(user)
            q["$or"] = [{"tenant_id": tid}, {"tenant_id": {"$exists": False}}]
        pm = await db.payment_methods.find_one(q, {"_id": 0})
        return pm

    async def _build_verify_url(token: str) -> str:
        settings = await _settings()
        base = _public_base_url(settings)
        return f"{base}/verify/{token}"

    # ----------------------------------------------------------------
    # Iter38j — Backfill: rewrite qr_url base for existing receipts/invoices
    # when the admin updates `public_base_url` after the docs were generated
    # with a stale (preview) hostname.
    # ----------------------------------------------------------------
    @router.post("/admin/cashier/qr/rewrite-base-url")
    async def rewrite_qr_base_url(payload: dict = Body(default_factory=dict), user: dict = Depends(get_current_admin)):
        new_base = (payload.get("new_base") or "").strip().rstrip("/")
        if not new_base:
            settings = await _settings()
            new_base = _public_base_url(settings)
        if not new_base.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="new_base doit commencer par http(s)://")
        # Rewrite by computing a new URL via the existing path component
        updated = {"receipts": 0, "invoices": 0}
        for col, key in (("receipts", "receipts"), ("invoices", "invoices")):
            async for d in db[col].find({"qr_url": {"$regex": "/verify/"}}, {"_id": 0, "id": 1, "qr_url": 1}):
                old = d.get("qr_url") or ""
                # Split at /verify/ to extract the token
                if "/verify/" not in old:
                    continue
                token = old.split("/verify/", 1)[1]
                new_url = f"{new_base}/verify/{token}"
                if new_url != old:
                    await db[col].update_one({"id": d["id"]}, {"$set": {"qr_url": new_url}})
                    updated[key] += 1
        return {"ok": True, "new_base": new_base, "updated": updated}

    # ----------------------------------------------------------------
    # Business clients (clients en compte)
    # ----------------------------------------------------------------
    @router.get("/admin/business-clients")
    async def list_business_clients(user: dict = Depends(get_current_user)):
        # Iter37f — Read access for any cashier user (can_cash=true). Writes stay supervisor-only.
        if not _can_view_cashier(user) and user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Accès refusé")
        # Iter37e — Tenant scope
        scope = await _scoped_filter(user)
        cursor = db.business_clients.find({**scope, "deleted_at": None}, {"_id": 0}).sort("name", 1)
        return [c async for c in cursor]

    @router.post("/admin/business-clients")
    async def create_business_client(payload: BusinessClientPayload, user: dict = Depends(get_current_supervisor)):
        # Iter38r-fix9o — Generate immutable internal client_no (e.g. CLI-25-000123)
        from routes._counters import gen_internal_id  # local import to avoid cycles
        client_no = await gen_internal_id(db, "CLI")
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "client_no": client_no,
            "balance": 0.0,
            "created_at": _now_iso(),
            "created_by": user["id"],
            "tenant_id": await _tenant_id_of(user),  # Iter37e
            "deleted_at": None,
        })
        await db.business_clients.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/admin/business-clients/{cid}")
    async def update_business_client(cid: str, payload: BusinessClientPayload, user: dict = Depends(get_current_supervisor)):
        # Iter37e — Verify tenant access
        existing = await db.business_clients.find_one({"id": cid, "deleted_at": None}, {"_id": 0, "tenant_id": 1})
        await _ensure_tenant_access(user, existing)
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        updates["updated_at"] = _now_iso()
        res = await db.business_clients.update_one({"id": cid, "deleted_at": None}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Client introuvable")
        c = await db.business_clients.find_one({"id": cid}, {"_id": 0})
        return c

    @router.delete("/admin/business-clients/{cid}")
    async def delete_business_client(cid: str, user: dict = Depends(get_current_supervisor)):
        # Iter37e — Verify tenant access
        existing = await db.business_clients.find_one({"id": cid}, {"_id": 0, "tenant_id": 1})
        await _ensure_tenant_access(user, existing)
        res = await db.business_clients.update_one({"id": cid}, {"$set": {"deleted_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Client introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # Products (catalogue)
    # ----------------------------------------------------------------
    # ----------------------------------------------------------------
    # Iter37a — Helpers for Client Lié (tenant) resolution
    # Resolves to the user's own row OR parent_client_id row (db.users)
    # ----------------------------------------------------------------
    async def _resolve_client_lie(user: dict) -> dict:
        """Return the tenant (Client Lié) for a given user as a dict.
        Resolution order:
          1) user.parent_client_id → db.users row (canonical tenant)
          2) user.client_id → db.users row
          3) Iter37f — Same `company` name → canonical admin/superviseur of that company
          4) user itself (synthetic doc)
        """
        for key in ("parent_client_id", "client_id"):
            ref_id = user.get(key)
            if ref_id and ref_id != user.get("id"):
                doc = await db.users.find_one({"id": ref_id}, {"_id": 0})
                if doc:
                    return {
                        "id": doc.get("id"),
                        "name": doc.get("company") or doc.get("full_name") or "SAWALI",
                        "logo_url": doc.get("logo_url"),
                        "billing_address": doc.get("billing_address") or doc.get("city"),
                        "phone": doc.get("phone"),
                        "email": doc.get("email"),
                    }
        # Iter37f — Fallback: resolve by `company` name. Two users sharing the
        # same company become the SAME tenant, anchored on the canonical user
        # (preferred: admin > superviseur > oldest active user with that company).
        company = (user.get("company") or "").strip()
        if company:
            # Lookup canonical: admin first, then superviseur, then oldest active
            for role_filter in (
                {"role": "admin"},
                {"role": "superviseur"},
                {"account_status": {"$ne": "deleted"}},
            ):
                canonical = await db.users.find_one(
                    {**role_filter, "company": company},
                    {"_id": 0},
                    sort=[("created_at", 1)],
                )
                if canonical:
                    return {
                        "id": canonical.get("id"),
                        "name": canonical.get("company") or canonical.get("full_name") or "SAWALI",
                        "logo_url": canonical.get("logo_url"),
                        "billing_address": canonical.get("billing_address") or canonical.get("city"),
                        "phone": canonical.get("phone"),
                        "email": canonical.get("email"),
                    }
        return {
            "id": user.get("id"),
            "name": user.get("company") or user.get("full_name") or "SAWALI",
            "logo_url": user.get("logo_url"),
            "billing_address": user.get("billing_address") or user.get("city"),
            "phone": user.get("phone"),
            "email": user.get("email"),
        }

    async def _generate_product_sku(client_lie: dict) -> str:
        slug = _slugify(client_lie.get("name") or "SAWALI", max_len=20).upper().replace("-", " ")
        # Atomic counter per Client Lié
        counter = await db.product_sku_counters.find_one_and_update(
            {"client_id": client_lie["id"]},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        seq = int(counter.get("seq", 1))
        return f"{slug}-{seq:08d}"

    # ----------------------------------------------------------------
    # Iter37e — Tenant scoping helpers (multi-tenant Caisse).
    # All users sharing the same Client Lié (parent_client_id || client_id || id)
    # see the same data: business_clients, products, receipts, invoices,
    # legal_forms, product_categories, payment_methods.
    # Super-admin (admin@sawalismartsystems.com) bypasses the filter.
    # ----------------------------------------------------------------
    async def _tenant_id_of(user: dict) -> str:
        cl = await _resolve_client_lie(user)
        return cl["id"]

    async def _scoped_filter(user: dict, *, field: str = "tenant_id") -> Dict[str, Any]:
        """Return the Mongo filter to scope a collection to the user's tenant.
        - Super-admin: empty (no filter).
        - Others: tenant_id == user's Client Lié id.
        Legacy docs without tenant_id are auto-backfilled at startup, so
        a strict equality filter is safe in steady state.
        """
        if _is_super_admin(user):
            return {}
        tid = await _tenant_id_of(user)
        return {field: tid}

    async def _ensure_tenant_access(user: dict, doc: Optional[dict]) -> None:
        """Raise 404 if the doc is not visible from the user's tenant."""
        if doc is None:
            raise HTTPException(status_code=404, detail="Document introuvable")
        if _is_super_admin(user):
            return
        tid = await _tenant_id_of(user)
        doc_tid = doc.get("tenant_id")
        if doc_tid is None or doc_tid == tid:
            return
        raise HTTPException(status_code=404, detail="Document introuvable")

    @router.get("/admin/products")
    async def list_products(user: dict = Depends(get_current_user)):
        # Iter37f — Read access for any cashier user (can_cash=true). Writes stay supervisor-only.
        if not _can_view_cashier(user) and user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Accès refusé")
        # Iter37a/e — Filter by current user's Client Lié (multi-tenant catalog).
        q: Dict[str, Any] = {"deleted_at": None}
        if not _is_super_admin(user):
            tid = await _tenant_id_of(user)
            # `client_id` was the original tenant key; tenant_id is the new canonical.
            q["$or"] = [{"client_id": tid}, {"tenant_id": tid}]
        cursor = db.products.find(q, {"_id": 0}).sort("name", 1)
        return [p async for p in cursor]

    @router.post("/admin/products")
    async def create_product(payload: ProductPayload, user: dict = Depends(get_current_supervisor)):
        client_lie = await _resolve_client_lie(user)
        # Iter37a — Auto-generate SKU (server-side, per tenant). Ignore client-supplied SKU.
        sku = await _generate_product_sku(client_lie)
        doc = payload.model_dump()
        # Iter37a — Force product name UPPERCASE
        doc["name"] = (doc.get("name") or "").upper().strip()
        doc["sku"] = sku
        doc.update({
            "id": str(uuid.uuid4()),
            "client_id": client_lie["id"],
            "tenant_id": client_lie["id"],  # Iter37e — canonical tenant key
            "created_at": _now_iso(),
            "created_by": user["id"],
            "deleted_at": None,
        })
        await db.products.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/admin/products/{pid}")
    async def update_product(pid: str, payload: ProductPayload, user: dict = Depends(get_current_supervisor)):
        # Iter37a — Never let the client modify the SKU; preserve existing one.
        existing = await db.products.find_one({"id": pid, "deleted_at": None}, {"_id": 0, "sku": 1, "client_id": 1, "tenant_id": 1})
        if not existing:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        # Iter37f — Tenant ACL: refuse if the product belongs to another tenant.
        if not _is_super_admin(user):
            tid = await _tenant_id_of(user)
            owner_tid = existing.get("tenant_id") or existing.get("client_id")
            if owner_tid and owner_tid != tid:
                raise HTTPException(status_code=404, detail="Produit introuvable")
        updates = payload.model_dump()
        updates["sku"] = existing["sku"]  # immutable
        updates["name"] = (updates.get("name") or "").upper().strip()
        updates["updated_at"] = _now_iso()
        res = await db.products.update_one({"id": pid, "deleted_at": None}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        return await db.products.find_one({"id": pid}, {"_id": 0})

    @router.delete("/admin/products/{pid}")
    async def delete_product(pid: str, user: dict = Depends(get_current_supervisor)):
        # Iter37f — Tenant ACL
        existing = await db.products.find_one({"id": pid}, {"_id": 0, "client_id": 1, "tenant_id": 1})
        if not existing:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        if not _is_super_admin(user):
            tid = await _tenant_id_of(user)
            owner_tid = existing.get("tenant_id") or existing.get("client_id")
            if owner_tid and owner_tid != tid:
                raise HTTPException(status_code=404, detail="Produit introuvable")
        res = await db.products.update_one({"id": pid}, {"$set": {"deleted_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # NOTE Iter38k — `/cashier/products/generate-icon` is now implemented in
    # routes/ai_media.py (real Gemini Nano Banana call via Emergent LLM Key).
    # ----------------------------------------------------------------

    # ----------------------------------------------------------------
    # Payment methods (admin-only CRUD; everyone can list active)
    # ----------------------------------------------------------------
    @router.get("/payment-methods")
    async def list_payment_methods(user: dict = Depends(get_current_user)):
        # Iter37e — Tenant scope
        scope = await _scoped_filter(user)
        cursor = db.payment_methods.find({**scope, "active": True}, {"_id": 0}).sort("sort_order", 1)
        return [p async for p in cursor]

    @router.post("/admin/payment-methods")
    async def create_payment_method(payload: PaymentMethodPayload, user: dict = Depends(get_current_supervisor)):
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "created_at": _now_iso(),
            "created_by": user["id"],
            "tenant_id": await _tenant_id_of(user),  # Iter37e
        })
        await db.payment_methods.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/admin/payment-methods/{pid}")
    async def update_payment_method(pid: str, payload: PaymentMethodPayload, user: dict = Depends(get_current_supervisor)):
        existing = await db.payment_methods.find_one({"id": pid}, {"_id": 0, "tenant_id": 1})
        await _ensure_tenant_access(user, existing)
        updates = payload.model_dump()
        updates["updated_at"] = _now_iso()
        res = await db.payment_methods.update_one({"id": pid}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Mode de paiement introuvable")
        return await db.payment_methods.find_one({"id": pid}, {"_id": 0})

    @router.delete("/admin/payment-methods/{pid}")
    async def delete_payment_method(pid: str, user: dict = Depends(get_current_supervisor)):
        existing = await db.payment_methods.find_one({"id": pid}, {"_id": 0, "tenant_id": 1})
        await _ensure_tenant_access(user, existing)
        res = await db.payment_methods.update_one({"id": pid}, {"$set": {"active": False, "deleted_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Mode de paiement introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # Iter37b — CSV import for business_clients and products
    # Field order (semicolon separator, UTF-8, no header row required):
    #   - business_clients: name;legal_form;nif;ifu;rccm;phone;whatsapp;email;billing_address;shipping_address;notes
    #   - products:         name;category;unit;unit_price_ht;tva_pct;stock;description;active
    # Empty cells become None. Products' SKU is auto-generated (immutable).
    # Product names are uppercased automatically.
    # ----------------------------------------------------------------
    BUSINESS_CSV_ORDER = [
        "name", "legal_form", "nif", "ifu", "rccm", "phone", "whatsapp", "email",
        "billing_address", "shipping_address", "notes",
    ]
    PRODUCT_CSV_ORDER = [
        "name", "category", "unit", "unit_price_ht", "tva_pct", "stock", "description", "active",
    ]

    def _parse_csv_payload(raw: bytes) -> List[List[str]]:
        import csv as _csv
        text = raw.decode("utf-8-sig", errors="replace")  # strip BOM
        # Auto-detect delimiter (; or , or \t)
        first_line = text.splitlines()[0] if text else ""
        delim = ";" if ";" in first_line else ("," if "," in first_line else "\t")
        reader = _csv.reader(io.StringIO(text), delimiter=delim, quotechar='"')
        rows = []
        for raw_row in reader:
            if not raw_row or all(not c.strip() for c in raw_row):
                continue
            rows.append([c.strip() for c in raw_row])
        return rows

    def _is_header_row(row: List[str], expected_cols: List[str]) -> bool:
        # Header row if first cell matches one of the expected col names case-insensitive
        return row and row[0].strip().lower() in {c.lower() for c in expected_cols}

    @router.get("/cashier/import/business-clients/fields")
    async def get_business_csv_fields(_: dict = Depends(get_current_supervisor)):
        return {
            "order": BUSINESS_CSV_ORDER,
            "delimiter": ";",
            "encoding": "UTF-8 (BOM accepté)",
            "sample": ";".join(BUSINESS_CSV_ORDER),
            "note": "Une ligne par client. La 1re ligne peut être l'en-tête (ignorée si elle commence par 'name'). Les cellules vides deviennent NULL.",
        }

    @router.get("/cashier/import/products/fields")
    async def get_product_csv_fields(_: dict = Depends(get_current_supervisor)):
        return {
            "order": PRODUCT_CSV_ORDER,
            "delimiter": ";",
            "encoding": "UTF-8 (BOM accepté)",
            "sample": ";".join(PRODUCT_CSV_ORDER),
            "note": "Le SKU est auto-généré. Le nom est mis en MAJUSCULES automatiquement. Une ligne par produit.",
        }

    @router.post("/cashier/import/business-clients")
    async def import_business_clients(payload: dict = Body(...), user: dict = Depends(get_current_supervisor)):
        raw = (payload or {}).get("csv", "")
        if not raw:
            raise HTTPException(status_code=400, detail="Champ 'csv' manquant")
        rows = _parse_csv_payload(raw.encode("utf-8") if isinstance(raw, str) else raw)
        if not rows:
            raise HTTPException(status_code=400, detail="CSV vide")
        if _is_header_row(rows[0], BUSINESS_CSV_ORDER):
            rows = rows[1:]
        tid = await _tenant_id_of(user)  # Iter37e
        created = 0
        skipped = 0
        errors: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows, start=1):
            # Pad/truncate row to expected length
            row = (row + [""] * len(BUSINESS_CSV_ORDER))[: len(BUSINESS_CSV_ORDER)]
            data = {k: (v.strip() if v else None) for k, v in zip(BUSINESS_CSV_ORDER, row)}
            if not data.get("name"):
                errors.append({"line": idx, "error": "Nom manquant"})
                continue
            # Iter37e — Dedup per tenant
            existing = await db.business_clients.find_one(
                {"name": data["name"], "deleted_at": None, "tenant_id": tid},
                {"_id": 0, "id": 1},
            )
            if existing:
                skipped += 1
                continue
            doc = {
                "id": str(uuid.uuid4()),
                **data,
                "auto_relance_enabled": False,
                "relance_channel": "whatsapp",
                "tenant_id": tid,  # Iter37e
                "created_at": _now_iso(),
                "created_by": user["id"],
                "deleted_at": None,
            }
            try:
                await db.business_clients.insert_one(doc.copy())
                created += 1
            except Exception as exc:  # noqa: BLE001
                errors.append({"line": idx, "error": str(exc)[:200]})
        return {"created": created, "skipped_duplicates": skipped, "errors": errors, "total_lines": len(rows)}

    @router.post("/cashier/import/products")
    async def import_products(payload: dict = Body(...), user: dict = Depends(get_current_supervisor)):
        raw = (payload or {}).get("csv", "")
        if not raw:
            raise HTTPException(status_code=400, detail="Champ 'csv' manquant")
        rows = _parse_csv_payload(raw.encode("utf-8") if isinstance(raw, str) else raw)
        if not rows:
            raise HTTPException(status_code=400, detail="CSV vide")
        if _is_header_row(rows[0], PRODUCT_CSV_ORDER):
            rows = rows[1:]
        client_lie = await _resolve_client_lie(user)
        created = 0
        errors: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows, start=1):
            row = (row + [""] * len(PRODUCT_CSV_ORDER))[: len(PRODUCT_CSV_ORDER)]
            data = {k: (v.strip() if v else None) for k, v in zip(PRODUCT_CSV_ORDER, row)}
            if not data.get("name"):
                errors.append({"line": idx, "error": "Nom manquant"})
                continue
            try:
                sku = await _generate_product_sku(client_lie)
                doc = {
                    "id": str(uuid.uuid4()),
                    "sku": sku,
                    "name": data["name"].upper(),
                    "description": data.get("description"),
                    "category": data.get("category"),
                    "unit": (data.get("unit") or "pièce").lower(),
                    "unit_price_ht": float(data["unit_price_ht"] or 0),
                    "tva_pct": float(data["tva_pct"] or 0),
                    "stock": int(data["stock"]) if data.get("stock") else None,
                    "image_url": None,
                    "active": (data.get("active") or "true").strip().lower() not in ("false", "0", "no", "non"),
                    "client_id": client_lie["id"],
                    "tenant_id": client_lie["id"],  # Iter37e
                    "created_at": _now_iso(),
                    "created_by": user["id"],
                    "deleted_at": None,
                }
                await db.products.insert_one(doc.copy())
                created += 1
            except Exception as exc:  # noqa: BLE001
                errors.append({"line": idx, "error": str(exc)[:200]})
        return {"created": created, "errors": errors, "total_lines": len(rows)}

    # ----------------------------------------------------------------
    # users.can_cash flag — admin/supervisor only
    # ----------------------------------------------------------------
    @router.patch("/admin/users/{uid}/can-cash")
    async def set_user_can_cash(uid: str, payload: dict = Body(...), user: dict = Depends(get_current_supervisor)):
        # Iter37f — Tenant ACL: a supervisor can only flip can_cash on users
        # belonging to their tenant. Super-admin bypasses.
        target = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "parent_client_id": 1, "client_id": 1, "company": 1})
        if not target:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        if not _is_super_admin(user):
            actor_tid = await _tenant_id_of(user)
            # Resolve the target's tenant the same way
            target_tid = await _tenant_id_of(target)
            if target_tid != actor_tid:
                raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        flag = bool(payload.get("can_cash"))
        res = await db.users.update_one({"id": uid}, {"$set": {"can_cash": flag, "can_cash_updated_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        return {"ok": True, "can_cash": flag}

    # ----------------------------------------------------------------
    # Iter37a — Legal forms (admin-managed dropdown for business_clients)
    # ----------------------------------------------------------------
    @router.get("/cashier/legal-forms")
    async def list_legal_forms(user: dict = Depends(get_current_user)):
        # Iter37e — Tenant scope
        scope = await _scoped_filter(user)
        cursor = db.legal_forms.find({**scope, "deleted_at": None}, {"_id": 0}).sort("sort_order", 1)
        return [r async for r in cursor]

    @router.post("/admin/legal-forms")
    async def create_legal_form(payload: LegalFormPayload, user: dict = Depends(get_current_supervisor)):
        label = payload.label.strip()
        tid = await _tenant_id_of(user)  # Iter37e
        existing = await db.legal_forms.find_one({"label": label, "deleted_at": None, "tenant_id": tid}, {"_id": 0, "id": 1})
        if existing:
            raise HTTPException(status_code=400, detail=f"Forme juridique déjà présente ({label})")
        last = await db.legal_forms.find({"deleted_at": None, "tenant_id": tid}, {"_id": 0, "sort_order": 1}).sort("sort_order", -1).limit(1).to_list(1)
        next_order = (last[0]["sort_order"] + 1) if last else 0
        doc = {
            "id": str(uuid.uuid4()),
            "label": label,
            "sort_order": next_order,
            "tenant_id": tid,  # Iter37e
            "created_at": _now_iso(),
            "created_by": user["id"],
            "deleted_at": None,
        }
        await db.legal_forms.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.delete("/admin/legal-forms/{lid}")
    async def delete_legal_form(lid: str, user: dict = Depends(get_current_supervisor)):
        existing = await db.legal_forms.find_one({"id": lid}, {"_id": 0, "tenant_id": 1})
        await _ensure_tenant_access(user, existing)
        res = await db.legal_forms.update_one({"id": lid}, {"$set": {"deleted_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Forme juridique introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # Iter37a — Product categories (admin-managed dropdown for products)
    # ----------------------------------------------------------------
    @router.get("/cashier/product-categories")
    async def list_product_categories(user: dict = Depends(get_current_user)):
        # Iter37e — Tenant scope
        scope = await _scoped_filter(user)
        cursor = db.product_categories.find({**scope, "deleted_at": None}, {"_id": 0}).sort("sort_order", 1)
        return [r async for r in cursor]

    @router.post("/admin/product-categories")
    async def create_product_category(payload: ProductCategoryPayload, user: dict = Depends(get_current_supervisor)):
        label = payload.label.strip()
        tid = await _tenant_id_of(user)  # Iter37e
        existing = await db.product_categories.find_one({"label": label, "deleted_at": None, "tenant_id": tid}, {"_id": 0, "id": 1})
        if existing:
            raise HTTPException(status_code=400, detail=f"Catégorie déjà présente ({label})")
        last = await db.product_categories.find({"deleted_at": None, "tenant_id": tid}, {"_id": 0, "sort_order": 1}).sort("sort_order", -1).limit(1).to_list(1)
        next_order = (last[0]["sort_order"] + 1) if last else 0
        doc = {
            "id": str(uuid.uuid4()),
            "label": label,
            "sort_order": next_order,
            "tenant_id": tid,  # Iter37e
            "created_at": _now_iso(),
            "created_by": user["id"],
            "deleted_at": None,
        }
        await db.product_categories.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.delete("/admin/product-categories/{cid}")
    async def delete_product_category(cid: str, user: dict = Depends(get_current_supervisor)):
        existing = await db.product_categories.find_one({"id": cid}, {"_id": 0, "tenant_id": 1})
        await _ensure_tenant_access(user, existing)
        res = await db.product_categories.update_one({"id": cid}, {"$set": {"deleted_at": _now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Catégorie introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # Iter37a — Dedicated Auto-Relance settings endpoint (admin+sup).
    # The global /admin/settings PUT requires strict admin (touches SMTP/etc.)
    # whereas relance config should be accessible to superviseur as well.
    # ----------------------------------------------------------------
    _AUTO_RELANCE_KEYS = (
        "auto_relance_enabled", "auto_relance_day_of_week",
        "auto_relance_grace_days", "auto_relance_email_report_to",
    )

    @router.get("/cashier/auto-relance/settings")
    async def get_auto_relance_settings(_: dict = Depends(get_current_supervisor)):
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {k: s.get(k) for k in _AUTO_RELANCE_KEYS}

    @router.put("/cashier/auto-relance/settings")
    async def update_auto_relance_settings(payload: dict = Body(...), _: dict = Depends(get_current_supervisor)):
        # Whitelist + light validation
        update: Dict[str, Any] = {}
        if "auto_relance_enabled" in payload:
            update["auto_relance_enabled"] = bool(payload["auto_relance_enabled"])
        if "auto_relance_day_of_week" in payload:
            v = int(payload["auto_relance_day_of_week"])
            if v < 0 or v > 6:
                raise HTTPException(status_code=400, detail="Jour invalide (0=Lundi..6=Dimanche)")
            update["auto_relance_day_of_week"] = v
        if "auto_relance_grace_days" in payload:
            v = int(payload["auto_relance_grace_days"])
            if v < 0 or v > 365:
                raise HTTPException(status_code=400, detail="Délai invalide (0-365 jours)")
            update["auto_relance_grace_days"] = v
        if "auto_relance_email_report_to" in payload:
            update["auto_relance_email_report_to"] = (payload["auto_relance_email_report_to"] or "").strip() or None
        if not update:
            raise HTTPException(status_code=400, detail="Aucun paramètre fourni")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {k: s.get(k) for k in _AUTO_RELANCE_KEYS}

    @router.get("/admin/users/can-cash")
    async def list_cashier_users(user: dict = Depends(get_current_supervisor)):
        # Iter37e — Restrict to users of the same tenant
        q: Dict[str, Any] = {"can_cash": True, "account_status": {"$ne": "deleted"}}
        if not _is_super_admin(user):
            tid = await _tenant_id_of(user)
            q["$or"] = [
                {"id": tid},
                {"parent_client_id": tid},
                {"client_id": tid},
            ]
        cursor = db.users.find(
            q,
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1},
        )
        return [u async for u in cursor]

    # ----------------------------------------------------------------
    # Iter37f — Tenant info badge (header of Caisse page).
    # Tells the user how many colleagues share the same Caisse space.
    # ----------------------------------------------------------------
    @router.get("/cashier/tenant-info")
    async def cashier_tenant_info(user: dict = Depends(get_current_user)):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        cl = await _resolve_client_lie(user)
        tid = cl["id"]
        # Count users sharing this tenant (parent_client_id, client_id, id match,
        # OR same `company` field as the tenant's canonical user)
        canonical = await db.users.find_one({"id": tid}, {"_id": 0, "company": 1, "email": 1, "full_name": 1, "role": 1})
        company = (canonical or {}).get("company")
        or_conditions: List[Dict[str, Any]] = [
            {"id": tid},
            {"parent_client_id": tid},
            {"client_id": tid},
        ]
        if company:
            or_conditions.append({"company": company})
        member_count = await db.users.count_documents({
            "$or": or_conditions,
            "account_status": {"$ne": "deleted"},
        })
        # Caisse stats for this tenant
        scope = {"tenant_id": tid} if not _is_super_admin(user) else {}
        bc_count = await db.business_clients.count_documents({**scope, "deleted_at": None})
        product_count = await db.products.count_documents({**scope, "deleted_at": None})
        return {
            "tenant_id": tid,
            "tenant_name": cl.get("name"),
            "canonical_email": (canonical or {}).get("email"),
            "canonical_role": (canonical or {}).get("role"),
            "company": company,
            "member_count": member_count,
            "business_client_count": bc_count,
            "product_count": product_count,
            "is_super_admin": _is_super_admin(user),
        }

    # ----------------------------------------------------------------
    # Receipts
    # ----------------------------------------------------------------
    @router.post("/cashier/receipts")
    async def create_receipt(payload: ReceiptPayload, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Vous n'avez pas l'autorisation d'encaisser.")
        # Iter37e — Verify bc belongs to user's tenant
        scope = await _scoped_filter(user)
        bc = await db.business_clients.find_one(
            {**scope, "id": payload.business_client_id, "deleted_at": None},
            {"_id": 0},
        )
        if not bc:
            raise HTTPException(status_code=404, detail="Client en compte introuvable")
        pm = await _resolve_payment_method(payload.payment_method_id, user=user)
        if not pm:
            raise HTTPException(status_code=400, detail="Mode de paiement invalide ou inactif")
        year = datetime.now(timezone.utc).year
        seq = await _next_year_seq("receipts", year)
        number = f"R-{year}-{seq:04d}"
        token = secrets.token_urlsafe(24)
        tid = await _tenant_id_of(user)  # Iter37e
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
                "whatsapp": bc.get("whatsapp"),
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
            "tenant_id": tid,  # Iter37e
            # Iter37b — Snapshot of the tenant (Client Lié) header for print
            "tenant_snapshot": await _resolve_client_lie(user),
        }
        await db.receipts.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.get("/cashier/receipts")
    async def list_receipts(
        limit: int = Query(50, ge=1, le=200),
        business_client_id: Optional[str] = None,
        include_deleted: bool = Query(False),  # Iter37h.A — show trashed docs
        user: dict = Depends(get_current_user),
    ):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        # Iter37e — Tenant scope; Iter37h — exclude soft-deleted by default
        q: Dict[str, Any] = await _scoped_filter(user)
        if not include_deleted:
            q["deleted_at"] = None
        if business_client_id:
            q["business_client_id"] = business_client_id
        cursor = db.receipts.find(q, {"_id": 0}).sort("issued_at", -1).limit(limit)
        return [r async for r in cursor]

    @router.get("/cashier/receipts/{rid}")
    async def get_receipt(rid: str, user: dict = Depends(get_current_user)):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        r = await db.receipts.find_one({"id": rid}, {"_id": 0})
        await _ensure_tenant_access(user, r)  # Iter37e
        return r

    @router.get("/cashier/receipts/{rid}/qr.png")
    async def receipt_qr_png(rid: str, user: dict = Depends(get_current_user)):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        r = await db.receipts.find_one({"id": rid}, {"_id": 0, "qr_url": 1, "tenant_id": 1})
        await _ensure_tenant_access(user, r)  # Iter37e
        png = build_qr_png(r["qr_url"])
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    # Iter36v — Send receipt to client via WhatsApp (1-click)
    # Iter37g — Now uses a Meta template (`confirmation_paiement_avecrecu` by
    # default) with the receipt PDF attached as DOCUMENT header. Falls back
    # to free-form text when no template is configured.
    @router.post("/cashier/receipts/{rid}/send-whatsapp")
    async def receipt_send_whatsapp(
        rid: str,
        payload: dict = Body(default_factory=dict),
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        r = await db.receipts.find_one({"id": rid}, {"_id": 0})
        await _ensure_tenant_access(user, r)  # Iter37e
        if wa_send_text is None and wa_send_template is None:
            raise HTTPException(status_code=503, detail="Envoi WhatsApp non configuré côté serveur")
        # Resolve recipient phone (override > snapshot.whatsapp/phone > live bc.whatsapp/phone)
        phone = (payload or {}).get("phone")
        if not phone:
            bc_live = await db.business_clients.find_one({"id": r.get("business_client_id")}, {"_id": 0, "whatsapp": 1, "phone": 1}) or {}
            phone = _pick_wa_phone(r.get("business_client_snapshot"), bc_live)
        if not phone:
            raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp pour ce client en compte")
        to_e164 = _normalize_phone_e164(phone)

        # Iter37g — Build the template path
        settings_doc = await db.settings.find_one({"_id": "global"}) or {}
        tpl_name = (settings_doc.get("wa_template_receipt_name") or "confirmation_paiement_avecrecu").strip()
        tpl_lang = (settings_doc.get("wa_template_receipt_language") or settings_doc.get("wa_default_language") or "fr").strip()
        # Build the public PDF URL using the QR token (no auth required)
        base = _public_base_url(settings_doc).rstrip("/")
        pdf_url = f"{base}/api/public/receipt-pdf/{r['qr_token']}"
        client_name = (r.get("business_client_snapshot") or {}).get("name") or r.get("beneficiary_name") or "Client"
        amount_str = f"{_fmt_money(r.get('amount'))} FCFA"
        receipt_no = r.get("number") or "—"
        # Template components: HEADER (document) + BODY (text params).
        # The 4 body params follow a defensive ordering [1: name, 2: number,
        # 3: amount, 4: motif] — the user can adjust the template definition
        # in Meta to match this.
        components = [
            {"type": "header", "parameters": [
                {"type": "document", "document": {"link": pdf_url, "filename": f"Recu-{receipt_no}.pdf"}},
            ]},
            {"type": "body", "parameters": [
                {"type": "text", "text": client_name},
                {"type": "text", "text": receipt_no},
                {"type": "text", "text": amount_str},
                {"type": "text", "text": (r.get("motif") or "—")[:60]},
            ]},
        ]
        force_text = bool((payload or {}).get("force_text"))
        use_template = (wa_send_template is not None) and not force_text
        if use_template:
            result = await wa_send_template(to_e164, tpl_name, tpl_lang, components)
            # If Meta rejects the template (param mismatch, not approved, etc.),
            # automatically retry with body-only params (no header attachment),
            # then fall back to free-form text within the 24h session window.
            if not result.get("ok") and wa_send_template is not None:
                # Retry without header (in case template has no document header)
                result_body = await wa_send_template(to_e164, tpl_name, tpl_lang, [components[1]])
                if result_body.get("ok"):
                    result = result_body
                elif wa_send_text is not None:
                    text = (
                        f"📄 Reçu *{receipt_no}*\n"
                        f"Bénéficiaire : {client_name}\n"
                        f"Montant : {amount_str}\n"
                        f"Motif : {r.get('motif') or '—'}\n"
                        f"PDF : {pdf_url}"
                    )
                    fb = await wa_send_text(to_e164, text)
                    if fb.get("ok"):
                        result = fb
        else:
            text = (
                f"📄 Reçu *{receipt_no}*\n"
                f"Bénéficiaire : {client_name}\n"
                f"Montant : {amount_str}\n"
                f"Motif : {r.get('motif') or '—'}\n"
                f"PDF : {pdf_url}"
            )
            result = await wa_send_text(to_e164, text)
        if not result.get("ok"):
            # Iter38e — Persist last failed attempt for visibility (B.1)
            await db.receipts.update_one(
                {"id": rid},
                {"$set": {
                    "whatsapp_last_attempt_at": _now_iso(),
                    "whatsapp_last_status": "ko",
                    "whatsapp_last_error": (result.get("error") or "Échec WhatsApp")[:500],
                    "whatsapp_last_to": to_e164,
                }},
            )
            return {
                "ok": False,
                "to": to_e164,
                "error": result.get("error") or "Échec WhatsApp",
                "status": result.get("status"),
                "template_name": tpl_name if use_template else None,
                "fallback_wa_link": f"https://wa.me/{re.sub(r'[^0-9]', '', to_e164)}?text={pdf_url}",
            }
        await db.receipts.update_one(
            {"id": rid},
            {"$set": {
                "whatsapp_sent_at": _now_iso(),
                "whatsapp_message_id": result.get("message_id"),
                "whatsapp_to": to_e164,
                "whatsapp_sent_by": user["id"],
                "whatsapp_template_name": tpl_name if use_template else None,
                "whatsapp_pdf_url": pdf_url,
                # Iter38e — track last successful attempt + clear previous error
                "whatsapp_last_attempt_at": _now_iso(),
                "whatsapp_last_status": "ok",
                "whatsapp_last_error": None,
                "whatsapp_last_to": to_e164,
            }},
        )
        return {
            "ok": True, "to": to_e164, "message_id": result.get("message_id"),
            "template_name": tpl_name if use_template else None,
            "pdf_url": pdf_url,
        }

    # ----------------------------------------------------------------
    # Invoices (proforma / facture)
    # ----------------------------------------------------------------
    async def _bump_products_last_used(items: List[dict], tenant_id: str) -> None:
        """Iter38e (B.2) — Update last_used_at on each referenced product when
        used in a *real* invoice (not proforma). Proformas never call this.
        Silently ignores items without a product_id or non-matching tenant.
        """
        try:
            pids = list({(it.get("product_id") or "").strip() for it in items if it.get("product_id")})
            pids = [p for p in pids if p]
            if not pids:
                return
            now_iso = _now_iso()
            q = {
                "id": {"$in": pids},
                "deleted_at": None,
                "$or": [{"client_id": tenant_id}, {"tenant_id": tenant_id}],
            }
            await db.products.update_many(q, {"$set": {"last_used_at": now_iso}})
        except Exception:
            # Never block the invoice flow on this side-effect.
            pass

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
        # Iter37e — Tenant scope check on business_client
        scope = await _scoped_filter(user)
        bc = await db.business_clients.find_one(
            {**scope, "id": payload.business_client_id, "deleted_at": None},
            {"_id": 0},
        )
        if not bc:
            raise HTTPException(status_code=404, detail="Client en compte introuvable")
        items = [it.model_dump() for it in payload.items]
        totals = _compute_invoice_totals(items, payload.discount_kind, payload.discount_value)
        year = datetime.now(timezone.utc).year
        prefix = "FP" if payload.kind == "proforma" else "F"
        seq = await _next_year_seq(f"invoices:{payload.kind}", year)
        number = f"{prefix}-{year}-{seq:04d}"
        token = secrets.token_urlsafe(24)
        tid = await _tenant_id_of(user)  # Iter37e
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
                "whatsapp": bc.get("whatsapp"),
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
            "tenant_id": tid,  # Iter37e
            # Iter37b — Tenant header snapshot
            "tenant_snapshot": await _resolve_client_lie(user),
        }
        await db.invoices.insert_one(doc.copy())
        doc.pop("_id", None)
        # Iter38e (B.2) — Stamp products' last_used_at only for real invoices (not proformas).
        if payload.kind == "invoice":
            await _bump_products_last_used(items, tid)
        return doc

    @router.get("/cashier/invoices")
    async def list_invoices(
        kind: Optional[str] = None,
        status: Optional[str] = None,
        business_client_id: Optional[str] = None,
        include_deleted: bool = Query(False),  # Iter37h.A — show trashed docs
        limit: int = Query(50, ge=1, le=200),
        user: dict = Depends(get_current_user),
    ):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        # Iter37e — Tenant scope; Iter37h — exclude soft-deleted by default
        q: Dict[str, Any] = await _scoped_filter(user)
        if not include_deleted:
            q["deleted_at"] = None
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
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        i = await db.invoices.find_one({"id": iid}, {"_id": 0})
        await _ensure_tenant_access(user, i)  # Iter37e
        return i

    @router.get("/cashier/invoices/{iid}/qr.png")
    async def invoice_qr_png(iid: str, user: dict = Depends(get_current_user)):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        i = await db.invoices.find_one({"id": iid}, {"_id": 0, "qr_url": 1, "tenant_id": 1})
        await _ensure_tenant_access(user, i)  # Iter37e
        return Response(content=build_qr_png(i["qr_url"]), media_type="image/png")

    # Iter36v — Send invoice/proforma to client via WhatsApp (1-click)
    # Iter37g — Now uses a Meta template (`document_piecejointe_facturation`
    # by default) with the invoice PDF attached as DOCUMENT header.
    @router.post("/cashier/invoices/{iid}/send-whatsapp")
    async def invoice_send_whatsapp(
        iid: str,
        payload: dict = Body(default_factory=dict),
        user: dict = Depends(get_current_user),
    ):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
        await _ensure_tenant_access(user, inv)  # Iter37e
        if wa_send_text is None and wa_send_template is None:
            raise HTTPException(status_code=503, detail="Envoi WhatsApp non configuré côté serveur")
        phone = (payload or {}).get("phone")
        if not phone:
            bc_live = await db.business_clients.find_one({"id": inv.get("business_client_id")}, {"_id": 0, "whatsapp": 1, "phone": 1}) or {}
            phone = _pick_wa_phone(inv.get("business_client_snapshot"), bc_live)
        if not phone:
            raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp pour ce client en compte")
        to_e164 = _normalize_phone_e164(phone)
        label = "Proforma" if inv.get("kind") == "proforma" else "Facture"

        # Iter37g — Build the template path
        settings_doc = await db.settings.find_one({"_id": "global"}) or {}
        tpl_name = (settings_doc.get("wa_template_invoice_name") or "document_piecejointe_facturation").strip()
        tpl_lang = (settings_doc.get("wa_template_invoice_language") or settings_doc.get("wa_default_language") or "fr").strip()
        base = _public_base_url(settings_doc).rstrip("/")
        pdf_url = f"{base}/api/public/invoice-pdf/{inv['qr_token']}"
        client_name = (inv.get("business_client_snapshot") or {}).get("name") or "Client"
        amount_str = f"{_fmt_money(inv.get('net_to_pay'))} FCFA"
        doc_no = inv.get("number") or "—"
        components = [
            {"type": "header", "parameters": [
                {"type": "document", "document": {"link": pdf_url, "filename": f"{label}-{doc_no}.pdf"}},
            ]},
            {"type": "body", "parameters": [
                {"type": "text", "text": client_name},
                {"type": "text", "text": label},
                {"type": "text", "text": doc_no},
                {"type": "text", "text": amount_str},
            ]},
        ]
        force_text = bool((payload or {}).get("force_text"))
        use_template = (wa_send_template is not None) and not force_text
        if use_template:
            result = await wa_send_template(to_e164, tpl_name, tpl_lang, components)
            if not result.get("ok") and wa_send_template is not None:
                result_body = await wa_send_template(to_e164, tpl_name, tpl_lang, [components[1]])
                if result_body.get("ok"):
                    result = result_body
                elif wa_send_text is not None:
                    text = (
                        f"📑 {label} *{doc_no}*\n"
                        f"Client : {client_name}\n"
                        f"Net à payer : {amount_str}\n"
                        f"PDF : {pdf_url}"
                    )
                    fb = await wa_send_text(to_e164, text)
                    if fb.get("ok"):
                        result = fb
        else:
            text = (
                f"📑 {label} *{doc_no}*\n"
                f"Client : {client_name}\n"
                f"Net à payer : {amount_str}\n"
                f"PDF : {pdf_url}"
            )
            result = await wa_send_text(to_e164, text)
        if not result.get("ok"):
            # Iter38e — Persist last failed attempt (B.1)
            await db.invoices.update_one(
                {"id": iid},
                {"$set": {
                    "whatsapp_last_attempt_at": _now_iso(),
                    "whatsapp_last_status": "ko",
                    "whatsapp_last_error": (result.get("error") or "Échec WhatsApp")[:500],
                    "whatsapp_last_to": to_e164,
                }},
            )
            return {
                "ok": False,
                "to": to_e164,
                "error": result.get("error") or "Échec WhatsApp",
                "status": result.get("status"),
                "template_name": tpl_name if use_template else None,
                "fallback_wa_link": f"https://wa.me/{re.sub(r'[^0-9]', '', to_e164)}?text={pdf_url}",
            }
        await db.invoices.update_one(
            {"id": iid},
            {"$set": {
                "whatsapp_sent_at": _now_iso(),
                "whatsapp_message_id": result.get("message_id"),
                "whatsapp_to": to_e164,
                "whatsapp_sent_by": user["id"],
                "whatsapp_template_name": tpl_name if use_template else None,
                "whatsapp_pdf_url": pdf_url,
                # Iter38e — track last successful attempt + clear previous error
                "whatsapp_last_attempt_at": _now_iso(),
                "whatsapp_last_status": "ok",
                "whatsapp_last_error": None,
                "whatsapp_last_to": to_e164,
            }},
        )
        return {
            "ok": True, "to": to_e164, "message_id": result.get("message_id"),
            "template_name": tpl_name if use_template else None,
            "pdf_url": pdf_url,
        }

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
            "deleted_at": None,  # Iter37h — exclude soft-deleted
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
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        q = _build_overdue_query(grace_days)
        # Iter37e — Tenant scope
        scope = await _scoped_filter(user)
        q.update(scope)
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
        # Iter37e — Tenant scope
        scope = await _scoped_filter(user)
        q.update(scope)
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
            bc_live = await db.business_clients.find_one({"id": inv.get("business_client_id")}, {"_id": 0, "whatsapp": 1, "phone": 1}) or {}
            phone = _pick_wa_phone(inv.get("business_client_snapshot"), bc_live)
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
        await _ensure_tenant_access(user, inv)  # Iter37e
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
            # Iter38e (B.2) — Stamp products as used now that this is a real invoice.
            await _bump_products_last_used(inv.get("items") or [], inv.get("tenant_id") or await _tenant_id_of(user))
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
                pm = await _resolve_payment_method(payload.payment_method_id, user=user)
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
                    "tenant_id": inv.get("tenant_id") or await _tenant_id_of(user),  # Iter37e
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
        await _ensure_tenant_access(user, inv)  # Iter37e
        if inv["status"] != "paid":
            raise HTTPException(status_code=400, detail="Facture non réglée")
        # Re-use create_receipt logic (with related_invoice_id forced)
        payload.related_invoice_id = iid
        payload.business_client_id = inv["business_client_id"]
        return await create_receipt(payload, user)

    # =================================================================
    # Iter37h — DELETE receipt / invoice / proforma (admin or superviseur only)
    # Iter37h.A — Two stages: trash (soft) + purge (hard, irreversible).
    # By default DELETE is "trash" (visible in the recycle bin with restore).
    # `?purge=true` permanently removes the document.
    # =================================================================
    @router.delete("/cashier/receipts/{rid}")
    async def delete_receipt(
        rid: str,
        purge: bool = Query(False),
        user: dict = Depends(get_current_supervisor),
    ):
        r = await db.receipts.find_one({"id": rid}, {"_id": 0, "tenant_id": 1, "deleted_at": 1})
        await _ensure_tenant_access(user, r)
        if purge:
            await db.receipts.delete_one({"id": rid})
            return {"ok": True, "purged": True}
        if r.get("deleted_at"):
            return {"ok": True, "already_in_trash": True}
        await db.receipts.update_one({"id": rid}, {"$set": {
            "deleted_at": _now_iso(),
            "deleted_by": user["id"],
            "deleted_by_name": user.get("full_name") or user.get("email"),
        }})
        return {"ok": True, "trashed": True}

    @router.post("/cashier/receipts/{rid}/restore")
    async def restore_receipt(rid: str, user: dict = Depends(get_current_supervisor)):
        r = await db.receipts.find_one({"id": rid}, {"_id": 0, "tenant_id": 1, "deleted_at": 1})
        await _ensure_tenant_access(user, r)
        if not r.get("deleted_at"):
            return {"ok": True, "already_active": True}
        await db.receipts.update_one({"id": rid}, {"$set": {
            "deleted_at": None, "deleted_by": None, "deleted_by_name": None,
            "restored_at": _now_iso(),
            "restored_by": user["id"],
            "restored_by_name": user.get("full_name") or user.get("email"),
        }})
        return {"ok": True}

    @router.delete("/cashier/invoices/{iid}")
    async def delete_invoice(
        iid: str,
        purge: bool = Query(False),
        user: dict = Depends(get_current_supervisor),
    ):
        inv = await db.invoices.find_one({"id": iid}, {"_id": 0, "tenant_id": 1, "deleted_at": 1, "kind": 1})
        await _ensure_tenant_access(user, inv)
        if purge:
            await db.invoices.delete_one({"id": iid})
            return {"ok": True, "purged": True, "kind": inv.get("kind")}
        if inv.get("deleted_at"):
            return {"ok": True, "already_in_trash": True}
        await db.invoices.update_one({"id": iid}, {"$set": {
            "deleted_at": _now_iso(),
            "deleted_by": user["id"],
            "deleted_by_name": user.get("full_name") or user.get("email"),
        }})
        return {"ok": True, "trashed": True, "kind": inv.get("kind")}

    @router.post("/cashier/invoices/{iid}/restore")
    async def restore_invoice(iid: str, user: dict = Depends(get_current_supervisor)):
        inv = await db.invoices.find_one({"id": iid}, {"_id": 0, "tenant_id": 1, "deleted_at": 1})
        await _ensure_tenant_access(user, inv)
        if not inv.get("deleted_at"):
            return {"ok": True, "already_active": True}
        await db.invoices.update_one({"id": iid}, {"$set": {
            "deleted_at": None, "deleted_by": None, "deleted_by_name": None,
            "restored_at": _now_iso(),
            "restored_by": user["id"],
            "restored_by_name": user.get("full_name") or user.get("email"),
        }})
        return {"ok": True}

    # =================================================================
    # Iter37h — Duplicate an invoice/proforma (items only, no client)
    # Returns a DRAFT payload (not persisted) the frontend uses to
    # pre-fill the New Invoice form.
    # =================================================================
    @router.post("/cashier/invoices/{iid}/duplicate")
    async def duplicate_invoice(iid: str, user: dict = Depends(get_current_user)):
        if not _can_invoice(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        src = await db.invoices.find_one({"id": iid}, {"_id": 0})
        await _ensure_tenant_access(user, src)
        # Iter37h.A — Strip SKU/product_id/code so the duplicated lines don't
        # carry over the original product reference (minimize duplication errors).
        items = [
            {k: v for k, v in (it or {}).items() if k in (
                "label", "description", "quantity", "unit_price_ht", "tva_pct",
            ) and k not in ("sku", "product_id", "code")}
            for it in (src.get("items") or [])
        ]
        return {
            "ok": True,
            "draft": {
                "kind": src.get("kind") or "invoice",
                "business_client_id": None,  # User must pick a client
                "items": items,
                "discount_kind": src.get("discount_kind") or "none",
                "discount_value": float(src.get("discount_value") or 0),
                "notes": src.get("notes") or "",
                "due_date": None,  # Always reset due date
            },
            "source_id": src.get("id"),
            "source_number": src.get("number"),
        }


    # ----------------------------------------------------------------
    # Public QR verification — minimal info, no auth
    # ----------------------------------------------------------------
    @router.get("/public/verify/{token}")
    async def public_verify(token: str):        # Receipt?
        r = await db.receipts.find_one({"qr_token": token, "deleted_at": None}, {"_id": 0})
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
        i = await db.invoices.find_one({"qr_token": token, "deleted_at": None}, {"_id": 0})
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

    # ----------------------------------------------------------------
    # Iter37g — Public PDF download via QR token (used by WhatsApp templates
    # as the DOCUMENT header URL). The token grants read-only access; no
    # other auth is required so Meta's CDN can fetch the file.
    # ----------------------------------------------------------------
    @router.get("/public/receipt-pdf/{token}")
    async def public_receipt_pdf(token: str):
        r = await db.receipts.find_one({"qr_token": token, "deleted_at": None}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Reçu introuvable")
        pdf = build_receipt_pdf(r)
        filename = f"recu-{r.get('number') or token[:6]}.pdf"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "public, max-age=300",
            },
        )

    @router.get("/public/invoice-pdf/{token}")
    async def public_invoice_pdf(token: str):
        i = await db.invoices.find_one({"qr_token": token, "deleted_at": None}, {"_id": 0})
        if not i:
            raise HTTPException(status_code=404, detail="Document introuvable")
        pdf = build_invoice_pdf(i)
        kind_lbl = "facture" if (i.get("kind") == "invoice") else "proforma"
        filename = f"{kind_lbl}-{i.get('number') or token[:6]}.pdf"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "public, max-age=300",
            },
        )

    # Authenticated PDF endpoints (same content, but require auth + tenant scope)
    @router.get("/cashier/receipts/{rid}/pdf")
    async def receipt_pdf(rid: str, user: dict = Depends(get_current_user)):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        r = await db.receipts.find_one({"id": rid}, {"_id": 0})
        await _ensure_tenant_access(user, r)
        pdf = build_receipt_pdf(r)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="recu-{r.get("number") or rid[:6]}.pdf"'},
        )

    @router.get("/cashier/invoices/{iid}/pdf")
    async def invoice_pdf(iid: str, user: dict = Depends(get_current_user)):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        i = await db.invoices.find_one({"id": iid}, {"_id": 0})
        await _ensure_tenant_access(user, i)
        pdf = build_invoice_pdf(i)
        kind_lbl = "facture" if (i.get("kind") == "invoice") else "proforma"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{kind_lbl}-{i.get("number") or iid[:6]}.pdf"'},
        )

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

    async def _query_receipts(business_client_id: Optional[str], limit: int, user: Optional[dict] = None) -> List[dict]:
        # Iter37e — Tenant scope
        q: Dict[str, Any] = {}
        if user is not None:
            q.update(await _scoped_filter(user))
        if business_client_id:
            q["business_client_id"] = business_client_id
        return await db.receipts.find(q, {"_id": 0}).sort("issued_at", -1).limit(limit).to_list(limit)

    async def _query_invoices(kind: Optional[str], status: Optional[str], business_client_id: Optional[str], limit: int, user: Optional[dict] = None) -> List[dict]:
        # Iter37e — Tenant scope
        q: Dict[str, Any] = {}
        if user is not None:
            q.update(await _scoped_filter(user))
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
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        items = await _query_receipts(business_client_id, limit, user=user)
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
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        items = await _query_receipts(business_client_id, limit, user=user)
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
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        items = await _query_invoices(kind, status, business_client_id, limit, user=user)
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
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        items = await _query_invoices(kind, status, business_client_id, limit, user=user)
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
        bc_live = await db.business_clients.find_one({"id": inv.get("business_client_id")}, {"_id": 0, "whatsapp": 1, "phone": 1}) or {}
        phone = _pick_wa_phone(inv.get("business_client_snapshot"), bc_live)
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

    async def run_auto_relance(triggered_by: str = "cron", tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Iter36y — Execute the auto-relance round.
        Reads global settings:
          - auto_relance_enabled (master, default False)
          - auto_relance_day_of_week (0=Mon..6=Sun, default 0)
          - auto_relance_grace_days (default 30)
          - auto_relance_email_report_to (admin recipient)
        Only acts on business_clients with `auto_relance_enabled=True`.
        Today must match `auto_relance_day_of_week` when triggered by cron;
        manual triggers bypass the weekday check.

        Iter37f — `tenant_id` (optional) restricts the run to one tenant when
        triggered manually. Cron passes None and acts globally.
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
        # Resolve eligible business_clients (filtered by tenant when manual)
        bc_query: Dict[str, Any] = {"auto_relance_enabled": True, "deleted_at": None}
        if tenant_id:
            bc_query["tenant_id"] = tenant_id
        eligible_bcs = await db.business_clients.find(
            bc_query,
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(2000)
        if not eligible_bcs:
            run_doc = {
                "id": str(uuid.uuid4()),
                "triggered_by": triggered_by,
                "tenant_id": tenant_id,  # Iter37f
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
            "tenant_id": tenant_id,  # Iter37f
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
        """Iter36y — Trigger the auto-relance flow manually (admin/superviseur).
        Iter37f — Tagged with triggering user's tenant for per-tenant history filter."""
        triggered_tid = await _tenant_id_of(user)
        return await run_auto_relance(
            triggered_by=f"manual:{user.get('email') or user['id']}",
            tenant_id=triggered_tid,
        )

    @router.get("/cashier/overdue/relance-history")
    async def relance_history(limit: int = Query(20, ge=1, le=200), user: dict = Depends(get_current_supervisor)):
        # Iter37f — Filter history per tenant (super-admin sees all)
        q: Dict[str, Any] = {}
        if not _is_super_admin(user):
            tid = await _tenant_id_of(user)
            # Match runs tagged with this tenant OR legacy runs without tag
            q["$or"] = [{"tenant_id": tid}, {"tenant_id": {"$exists": False}}]
        cursor = db.auto_relance_runs.find(q, {"_id": 0}).sort("started_at", -1).limit(limit)
        return [r async for r in cursor]

    # =================================================================
    # Iter36z — KPIs dashboard (Facturation header)
    # =================================================================
    @router.get("/cashier/kpis")
    async def invoices_kpis(user: dict = Depends(get_current_user)):
        if not _can_view_cashier(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        # Iter37e — Tenant scope applied on every aggregation
        tenant_scope = await _scoped_filter(user)
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        ninety_days_ago = (now - timedelta(days=90)).isoformat()
        # 1) Encaissé ce mois (status=paid AND paid_at >= month_start)
        paid_cursor = db.invoices.find(
            {**tenant_scope, "kind": "invoice", "status": "paid", "deleted_at": None, "paid_at": {"$gte": month_start}},
            {"_id": 0, "net_to_pay": 1},
        )
        paid_amount = 0.0
        paid_count = 0
        async for inv in paid_cursor:
            paid_amount += float(inv.get("net_to_pay") or 0)
            paid_count += 1
        # 2) Restant à encaisser (status=issued)
        due_cursor = db.invoices.find(
            {**tenant_scope, "kind": "invoice", "status": "issued", "deleted_at": None},
            {"_id": 0, "net_to_pay": 1},
        )
        due_amount = 0.0
        due_count = 0
        async for inv in due_cursor:
            due_amount += float(inv.get("net_to_pay") or 0)
            due_count += 1
        # 3) Délai moyen de paiement (en jours) — sur les factures payées des 90 derniers jours
        recent_paid_cursor = db.invoices.find(
            {**tenant_scope, "kind": "invoice", "status": "paid", "deleted_at": None, "paid_at": {"$gte": ninety_days_ago}},
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
        bad_payers_pipeline = [
            {"$match": {**tenant_scope, "kind": "invoice", "status": "issued", "deleted_at": None}},
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

    # =================================================================
    # Iter37f — Admin endpoint: recompute tenant_id on existing docs.
    # Use this after redeploying the multi-tenant fix to consolidate
    # users who shared a `company` name but had no parent_client_id link.
    # Safe to run multiple times (idempotent — only writes when value changes).
    # =================================================================
    @router.post("/admin/cashier/backfill-tenants")
    async def admin_backfill_tenants(
        payload: dict = Body(default_factory=dict),
        user: dict = Depends(get_current_admin),
    ):
        """Recompute tenant_id on all Caisse docs using the latest resolution logic.
        Body: `{"rewrite": true}` to overwrite existing tenant_id (default true here,
        because the typical use case is to consolidate split tenants).
        """
        rewrite = bool((payload or {}).get("rewrite", True))
        stats = await backfill_tenant_ids(db, rewrite=rewrite)
        # Report which users (top 5) the system considers canonical per company
        sample = []
        async for u in db.users.find(
            {"role": {"$in": ["admin", "superviseur"]}, "company": {"$ne": None}},
            {"_id": 0, "id": 1, "email": 1, "company": 1, "role": 1},
        ).limit(20):
            sample.append(u)
        return {
            "ok": True,
            "rewrite": rewrite,
            "rows_updated": stats,
            "triggered_by": user.get("email"),
            "at": _now_iso(),
            "canonical_users_sample": sample,
        }

    return router, run_auto_relance
