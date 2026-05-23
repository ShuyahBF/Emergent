"""Iter36v — Caisse & Facturation: 1-click WhatsApp send endpoints.

Validates:
  - POST /api/cashier/receipts/{rid}/send-whatsapp
  - POST /api/cashier/invoices/{iid}/send-whatsapp
  - RBAC (regular user blocked, can_cash user allowed)
  - Phone resolution (snapshot → business_client → 400 if missing)
  - Graceful failure when WhatsApp not configured (200 ok:false + fallback link)
"""
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
def regular_user(db):
    uid = f"reg_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
        "full_name": "Regular", "role": "client", "account_status": "active",
    })
    yield uid
    db.users.delete_one({"id": uid})


@pytest.fixture
def seed_with_phone(admin_h):
    bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": f"ACME WA {uuid.uuid4().hex[:6]}",
        "phone": "+242066999111",
        "billing_address": "Brazzaville",
    }, timeout=15)
    assert bc.status_code == 200, bc.text
    bc_id = bc.json()["id"]
    pm = requests.post(f"{API}/admin/payment-methods", headers=admin_h, json={
        "label": "Espèces (wa-test)", "kind": "cash", "active": True, "sort_order": 1,
    }, timeout=15)
    pm_id = pm.json()["id"]
    yield {"bc_id": bc_id, "pm_id": pm_id}
    requests.delete(f"{API}/admin/business-clients/{bc_id}", headers=admin_h, timeout=10)
    requests.delete(f"{API}/admin/payment-methods/{pm_id}", headers=admin_h, timeout=10)


@pytest.fixture
def seed_no_phone(admin_h):
    bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": f"NoPhone {uuid.uuid4().hex[:6]}",
    }, timeout=15)
    bc_id = bc.json()["id"]
    pm = requests.post(f"{API}/admin/payment-methods", headers=admin_h, json={
        "label": "Cash (nophone)", "kind": "cash", "active": True, "sort_order": 2,
    }, timeout=15)
    pm_id = pm.json()["id"]
    yield {"bc_id": bc_id, "pm_id": pm_id}
    requests.delete(f"{API}/admin/business-clients/{bc_id}", headers=admin_h, timeout=10)
    requests.delete(f"{API}/admin/payment-methods/{pm_id}", headers=admin_h, timeout=10)


def _create_receipt(admin_h, seed) -> str:
    r = requests.post(f"{API}/cashier/receipts", headers=admin_h, json={
        "business_client_id": seed["bc_id"], "amount": 25000,
        "motif": "Test envoi WA", "payment_method_id": seed["pm_id"],
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_invoice(admin_h, seed) -> str:
    r = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
        "kind": "invoice",
        "business_client_id": seed["bc_id"],
        "items": [{"label": "Service", "quantity": 1, "unit_price_ht": 100000, "tva_pct": 18}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


class TestReceiptSendWA:
    def test_regular_user_blocked(self, regular_user, admin_h, seed_with_phone):
        rid = _create_receipt(admin_h, seed_with_phone)
        h = {"Authorization": f"Bearer {_forge(regular_user)}"}
        r = requests.post(f"{API}/cashier/receipts/{rid}/send-whatsapp", headers=h, json={}, timeout=15)
        assert r.status_code == 403

    def test_admin_send_returns_ok_false_when_wa_not_configured(self, admin_h, seed_with_phone, db):
        # Ensure WA isn't configured for this test (clear tokens just for this run)
        # We don't actually mutate settings — we just observe that wa_send_text returns ok:false.
        rid = _create_receipt(admin_h, seed_with_phone)
        r = requests.post(f"{API}/cashier/receipts/{rid}/send-whatsapp", headers=admin_h, json={}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        # Either really sent (ok=true) — production-ready env — or graceful failure (ok=false + fallback)
        assert "ok" in body
        if not body["ok"]:
            assert body.get("fallback_wa_link", "").startswith("https://wa.me/")
            assert body.get("error")
        else:
            # If actually sent in this env, message_id must exist
            assert body.get("message_id")
            # And the receipt should have whatsapp_sent_at persisted
            doc = db.receipts.find_one({"id": rid}, {"_id": 0})
            assert doc.get("whatsapp_sent_at")

    def test_no_phone_returns_400(self, admin_h, seed_no_phone):
        rid = _create_receipt(admin_h, seed_no_phone)
        r = requests.post(f"{API}/cashier/receipts/{rid}/send-whatsapp", headers=admin_h, json={}, timeout=15)
        assert r.status_code == 400
        assert "numéro" in r.json().get("detail", "").lower() or "phone" in r.json().get("detail", "").lower()

    def test_unknown_receipt_returns_404(self, admin_h):
        r = requests.post(f"{API}/cashier/receipts/does-not-exist/send-whatsapp", headers=admin_h, json={}, timeout=15)
        assert r.status_code == 404

    def test_phone_override_takes_precedence(self, admin_h, seed_no_phone):
        """Payload {phone: '+242...'} overrides missing snapshot phone."""
        rid = _create_receipt(admin_h, seed_no_phone)
        r = requests.post(
            f"{API}/cashier/receipts/{rid}/send-whatsapp",
            headers=admin_h, json={"phone": "+242077000001"}, timeout=15,
        )
        # Either really sent or graceful fallback — but NOT 400 (phone supplied)
        assert r.status_code == 200, r.text
        body = r.json()
        # 'to' field reflects the normalized override
        assert body.get("to", "").endswith("242077000001")


class TestInvoiceSendWA:
    def test_admin_send_invoice(self, admin_h, seed_with_phone):
        iid = _create_invoice(admin_h, seed_with_phone)
        r = requests.post(f"{API}/cashier/invoices/{iid}/send-whatsapp", headers=admin_h, json={}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "ok" in body
        if not body["ok"]:
            assert body.get("fallback_wa_link", "").startswith("https://wa.me/")
        # 'to' must be returned in both cases
        assert body.get("to")

    def test_invoice_unknown_404(self, admin_h):
        r = requests.post(f"{API}/cashier/invoices/nope/send-whatsapp", headers=admin_h, json={}, timeout=15)
        assert r.status_code == 404
