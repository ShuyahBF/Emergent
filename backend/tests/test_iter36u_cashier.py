"""Iter36u — Caisse & Facturation tests."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    if not d.get("needs_otp"):
        return d["access_token"]
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": d["session_token"], "code": d["dev_otp"]},
        timeout=30,
    )
    return r2.json()["access_token"]


def _forge(uid: str, role: str = "client") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def cashier_user(db):
    """Non-elevated user with can_cash=True (sharing tenant with admin)."""
    # Iter37e — Multi-tenant: link to admin tenant so seed data is visible.
    admin_doc = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    admin_id = admin_doc["id"] if admin_doc else None
    uid = f"cashier_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
        "full_name": "Test Cashier", "role": "client",
        "account_status": "active", "can_cash": True,
        "parent_client_id": admin_id,
    })
    yield uid
    db.users.delete_one({"id": uid})


@pytest.fixture
def regular_user(db):
    """Non-elevated user WITHOUT can_cash → must be blocked."""
    admin_doc = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    admin_id = admin_doc["id"] if admin_doc else None
    uid = f"reg_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
        "full_name": "Regular", "role": "client", "account_status": "active",
        "parent_client_id": admin_id,  # Iter37e
    })
    yield uid
    db.users.delete_one({"id": uid})


@pytest.fixture
def seed(admin_h):
    """Create a business client, a product, and a payment method via API."""
    bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": "ACME SARL Test",
        "nif": "1234567890",
        "rccm": "CG-BZV-2026-B-001",
        "billing_address": "12 Av. de la Paix, Brazzaville",
        "shipping_address": "12 Av. de la Paix, Brazzaville",
        "phone": "+242066123456",
        "email": "billing@acme.test",
    }, timeout=15)
    assert bc.status_code == 200, bc.text
    bc_id = bc.json()["id"]

    pm = requests.post(f"{API}/admin/payment-methods", headers=admin_h, json={
        "label": "Espèces (test)", "kind": "cash", "active": True, "sort_order": 1,
    }, timeout=15)
    assert pm.status_code == 200
    pm_id = pm.json()["id"]

    prod = requests.post(f"{API}/admin/products", headers=admin_h, json={
        "sku": f"SKU-{uuid.uuid4().hex[:6]}",
        "name": "Maintenance horaire",
        "unit": "heure", "unit_price_ht": 25000, "tva_pct": 18.0,
    }, timeout=15)
    assert prod.status_code == 200
    prod_id = prod.json()["id"]
    yield {"bc_id": bc_id, "pm_id": pm_id, "prod_id": prod_id}
    # Cleanup
    requests.delete(f"{API}/admin/business-clients/{bc_id}", headers=admin_h, timeout=10)
    requests.delete(f"{API}/admin/payment-methods/{pm_id}", headers=admin_h, timeout=10)
    requests.delete(f"{API}/admin/products/{prod_id}", headers=admin_h, timeout=10)


class TestPermissions:
    def test_regular_user_cannot_create_receipt(self, regular_user, seed):
        h = {"Authorization": f"Bearer {_forge(regular_user)}"}
        r = requests.post(f"{API}/cashier/receipts", headers=h, json={
            "business_client_id": seed["bc_id"], "amount": 1000,
            "motif": "test", "payment_method_id": seed["pm_id"],
        }, timeout=15)
        assert r.status_code == 403

    def test_cashier_user_can_create_receipt(self, cashier_user, seed):
        h = {"Authorization": f"Bearer {_forge(cashier_user)}"}
        r = requests.post(f"{API}/cashier/receipts", headers=h, json={
            "business_client_id": seed["bc_id"], "amount": 50000,
            "motif": "Acompte chantier", "payment_method_id": seed["pm_id"],
        }, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["number"].startswith("R-")
        assert body["amount"] == 50000
        assert body["amount_in_words"]  # spelled-out
        assert "cinquante mille" in body["amount_in_words"]
        assert body["qr_url"].endswith(body["qr_token"])

    def test_can_cash_endpoint_admin_only(self, regular_user):
        h = {"Authorization": f"Bearer {_forge(regular_user)}"}
        r = requests.patch(f"{API}/admin/users/{regular_user}/can-cash",
                           headers=h, json={"can_cash": True}, timeout=15)
        assert r.status_code == 403


class TestReceiptLifecycle:
    def test_receipt_qr_png_returns_image(self, admin_h, seed):
        r = requests.post(f"{API}/cashier/receipts", headers=admin_h, json={
            "business_client_id": seed["bc_id"], "amount": 25000,
            "motif": "Solde mai", "payment_method_id": seed["pm_id"],
        }, timeout=15)
        rid = r.json()["id"]
        q = requests.get(f"{API}/cashier/receipts/{rid}/qr.png", headers=admin_h, timeout=15)
        assert q.status_code == 200
        assert q.headers["Content-Type"] == "image/png"
        assert len(q.content) > 200

    def test_public_qr_verify(self, admin_h, seed):
        r = requests.post(f"{API}/cashier/receipts", headers=admin_h, json={
            "business_client_id": seed["bc_id"], "amount": 15000,
            "motif": "Vérification QR", "payment_method_id": seed["pm_id"],
        }, timeout=15)
        token = r.json()["qr_token"]
        v = requests.get(f"{API}/public/verify/{token}", timeout=15)
        assert v.status_code == 200
        body = v.json()
        assert body["type"] == "receipt"
        assert body["amount"] == 15000
        assert body["payment_method"]
        assert body["amount_in_words"]


class TestInvoiceLifecycle:
    def test_create_proforma_with_discount_percent(self, admin_h, seed):
        r = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
            "kind": "proforma",
            "business_client_id": seed["bc_id"],
            "items": [
                {"label": "Conseil", "quantity": 10, "unit_price_ht": 10000, "tva_pct": 18},
                {"label": "Hébergement", "quantity": 1, "unit_price_ht": 50000, "tva_pct": 0},
            ],
            "discount_kind": "percent", "discount_value": 10,
        }, timeout=15)
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["kind"] == "proforma"
        assert inv["status"] == "issued"
        assert inv["number"].startswith("FP-")
        # 10*10000 + 1*50000 = 150000 HT
        # TVA = 10000*10*0.18 = 18000
        # TTC = 168000  → -10% = 151200 net
        assert inv["subtotal_ht"] == 150000
        assert inv["total_tva"] == 18000
        assert inv["total_ttc"] == 168000
        assert abs(inv["net_to_pay"] - 151200) < 1
        assert inv["amount_in_words"]

    def test_convert_proforma_to_invoice_then_pay_generates_receipt(self, admin_h, seed):
        # 1) Proforma
        r1 = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
            "kind": "proforma",
            "business_client_id": seed["bc_id"],
            "items": [{"label": "Audit", "quantity": 1, "unit_price_ht": 100000, "tva_pct": 18}],
            "discount_kind": "none", "discount_value": 0,
        }, timeout=15)
        inv = r1.json()
        iid = inv["id"]
        prof_number = inv["number"]
        # 2) Convert to invoice
        r2 = requests.patch(f"{API}/cashier/invoices/{iid}", headers=admin_h, json={"kind": "invoice"}, timeout=15)
        assert r2.status_code == 200
        out = r2.json()["invoice"]
        assert out["kind"] == "invoice"
        assert out["number"].startswith("F-")
        assert out["converted_from"] == prof_number
        # 3) Pay → auto-generates receipt
        r3 = requests.patch(f"{API}/cashier/invoices/{iid}", headers=admin_h, json={
            "status": "paid", "payment_method_id": seed["pm_id"], "payment_reference": "REF-001"
        }, timeout=15)
        assert r3.status_code == 200, r3.text
        body = r3.json()
        assert body["invoice"]["status"] == "paid"
        assert body["invoice"]["paid_via_receipt_id"]
        assert body["generated_receipt"] is not None
        assert body["generated_receipt"]["related_invoice_id"] == iid

    def test_cannot_pay_proforma_without_converting(self, admin_h, seed):
        r1 = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
            "kind": "proforma",
            "business_client_id": seed["bc_id"],
            "items": [{"label": "X", "quantity": 1, "unit_price_ht": 10000, "tva_pct": 0}],
            "discount_kind": "none", "discount_value": 0,
        }, timeout=15)
        iid = r1.json()["id"]
        r2 = requests.patch(f"{API}/cashier/invoices/{iid}", headers=admin_h, json={
            "status": "paid", "payment_method_id": seed["pm_id"],
        }, timeout=15)
        assert r2.status_code == 400
        assert "Convertissez" in r2.text or "facture" in r2.text.lower()

    def test_cashier_cannot_cancel_invoice(self, cashier_user, admin_h, seed):
        r1 = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
            "kind": "invoice",
            "business_client_id": seed["bc_id"],
            "items": [{"label": "X", "quantity": 1, "unit_price_ht": 10000, "tva_pct": 0}],
            "discount_kind": "none", "discount_value": 0,
        }, timeout=15)
        iid = r1.json()["id"]
        h_c = {"Authorization": f"Bearer {_forge(cashier_user)}"}
        r2 = requests.patch(f"{API}/cashier/invoices/{iid}", headers=h_c, json={"status": "cancelled"}, timeout=15)
        assert r2.status_code == 403

    def test_cannot_cancel_paid_invoice(self, admin_h, seed):
        r1 = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
            "kind": "invoice",
            "business_client_id": seed["bc_id"],
            "items": [{"label": "Y", "quantity": 1, "unit_price_ht": 5000, "tva_pct": 0}],
            "discount_kind": "none", "discount_value": 0,
        }, timeout=15)
        iid = r1.json()["id"]
        # Pay
        requests.patch(f"{API}/cashier/invoices/{iid}", headers=admin_h, json={
            "status": "paid", "payment_method_id": seed["pm_id"],
        }, timeout=15)
        # Try cancel
        r2 = requests.patch(f"{API}/cashier/invoices/{iid}", headers=admin_h, json={"status": "cancelled"}, timeout=15)
        assert r2.status_code == 400


class TestProducts:
    def test_sku_auto_generated_per_tenant(self, admin_h, seed):
        """Iter37a — SKU is now auto-generated, RO, and includes the Client Lié (tenant) prefix."""
        r1 = requests.post(f"{API}/admin/products", headers=admin_h, json={
            "name": f"Product 1 {uuid.uuid4().hex[:5]}", "unit_price_ht": 1000,
        }, timeout=15)
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1["sku"]  # auto-generated, non-empty
        # Pattern: {TENANT_SLUG}-{8 digit seq}
        import re as _re
        assert _re.match(r"^[A-Z0-9 ]+-\d{8}$", body1["sku"]), f"Unexpected SKU: {body1['sku']}"
        # Product name MUST be uppercased (Iter37a)
        assert body1["name"].isupper() or " " in body1["name"]
        # Cleanup
        requests.delete(f"{API}/admin/products/{body1['id']}", headers=admin_h, timeout=10)

    def test_sku_immutable_on_update(self, admin_h, seed):
        """Even when client sends a new SKU on PATCH, the original must be preserved."""
        r1 = requests.post(f"{API}/admin/products", headers=admin_h, json={
            "name": f"Imm {uuid.uuid4().hex[:5]}", "unit_price_ht": 500,
        }, timeout=15)
        pid = r1.json()["id"]
        original_sku = r1.json()["sku"]
        r2 = requests.patch(f"{API}/admin/products/{pid}", headers=admin_h, json={
            "sku": "HACKED-00000001", "name": "imm renamed", "unit_price_ht": 600,
        }, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["sku"] == original_sku
        # And name still UPPERCASED
        assert r2.json()["name"] == "IMM RENAMED"
        requests.delete(f"{API}/admin/products/{pid}", headers=admin_h, timeout=10)
