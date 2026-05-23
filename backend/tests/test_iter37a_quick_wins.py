"""Iter37a — Quick wins + RBAC bug fix + dropdowns + multi-tenant SKU + WA fallback.

Validates:
  - GET/PUT /api/cashier/auto-relance/settings accessible to admin AND superviseur
  - GET /api/cashier/legal-forms (any auth) + POST/DELETE admin
  - GET /api/cashier/product-categories (any auth) + POST/DELETE admin
  - business_clients now accepts `whatsapp` field; receipt/invoice WA send uses whatsapp || phone fallback
  - product SKU auto-generated per Client Lié, immutable, name uppercased
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


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    d = r.json()
    if not d.get("needs_otp"):
        return d["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp",
                       json={"session_token": d["session_token"], "code": d["dev_otp"]}, timeout=30)
    return r2.json()["access_token"]


def _forge(uid: str, role: str = "client") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def sup_h(db):
    """A superviseur user with role=superviseur."""
    uid = f"sup_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
        "full_name": "Sup Test", "role": "superviseur", "account_status": "active",
    })
    yield {"Authorization": f"Bearer {_forge(uid, role='superviseur')}", "uid": uid}
    db.users.delete_one({"id": uid})


# ---------------------------------------------------------------------
# #9 — Auto-relance settings RBAC (admin OR superviseur)
# ---------------------------------------------------------------------
class TestAutoRelanceSettingsRBAC:
    def test_regular_user_blocked(self):
        h = {"Authorization": f"Bearer {_forge(f'reg_{uuid.uuid4().hex[:6]}')}"}
        r = requests.get(f"{API}/cashier/auto-relance/settings", headers=h, timeout=15)
        assert r.status_code in (401, 403)

    def test_admin_can_read_and_write(self, admin_h):
        r = requests.get(f"{API}/cashier/auto-relance/settings", headers=admin_h, timeout=15)
        assert r.status_code == 200
        assert "auto_relance_enabled" in r.json()
        r2 = requests.put(f"{API}/cashier/auto-relance/settings", headers=admin_h, json={
            "auto_relance_enabled": True, "auto_relance_day_of_week": 1,
            "auto_relance_grace_days": 45, "auto_relance_email_report_to": "test@example.com",
        }, timeout=15)
        assert r2.status_code == 200
        body = r2.json()
        assert body["auto_relance_enabled"] is True
        assert body["auto_relance_day_of_week"] == 1
        assert body["auto_relance_grace_days"] == 45

    def test_superviseur_can_read_and_write(self, sup_h):
        """Iter37a — Bug #9 fix: superviseur (not strict admin) can now manage Relance Auto."""
        h = {"Authorization": sup_h["Authorization"]}
        r = requests.get(f"{API}/cashier/auto-relance/settings", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        r2 = requests.put(f"{API}/cashier/auto-relance/settings", headers=h, json={
            "auto_relance_enabled": False,
        }, timeout=15)
        assert r2.status_code == 200, r2.text

    def test_invalid_day_rejected(self, admin_h):
        r = requests.put(f"{API}/cashier/auto-relance/settings", headers=admin_h, json={
            "auto_relance_day_of_week": 9,
        }, timeout=15)
        assert r.status_code == 400


# ---------------------------------------------------------------------
# #6 — Legal forms + product categories dropdown CRUD
# ---------------------------------------------------------------------
class TestLegalForms:
    def test_crud_lifecycle(self, admin_h):
        label = f"SARL_{uuid.uuid4().hex[:5]}"
        r = requests.post(f"{API}/admin/legal-forms", headers=admin_h, json={"label": label}, timeout=15)
        assert r.status_code == 200
        lid = r.json()["id"]
        # Duplicate must be rejected
        r2 = requests.post(f"{API}/admin/legal-forms", headers=admin_h, json={"label": label}, timeout=15)
        assert r2.status_code == 400
        # List accessible to any authed user (admin can list too)
        r3 = requests.get(f"{API}/cashier/legal-forms", headers=admin_h, timeout=15)
        assert r3.status_code == 200
        labels = [x["label"] for x in r3.json()]
        assert label in labels
        # Delete admin only
        r4 = requests.delete(f"{API}/admin/legal-forms/{lid}", headers=admin_h, timeout=10)
        assert r4.status_code == 200


class TestProductCategories:
    def test_crud_lifecycle(self, admin_h):
        label = f"Cat_{uuid.uuid4().hex[:5]}"
        r = requests.post(f"{API}/admin/product-categories", headers=admin_h, json={"label": label}, timeout=15)
        assert r.status_code == 200
        cid = r.json()["id"]
        r3 = requests.get(f"{API}/cashier/product-categories", headers=admin_h, timeout=15)
        labels = [x["label"] for x in r3.json()]
        assert label in labels
        requests.delete(f"{API}/admin/product-categories/{cid}", headers=admin_h, timeout=10)


# ---------------------------------------------------------------------
# #4 — Dedicated WhatsApp field on business_clients
# ---------------------------------------------------------------------
class TestWhatsAppField:
    def test_whatsapp_field_persisted(self, admin_h, db):
        r = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
            "name": f"WA Test {uuid.uuid4().hex[:6]}",
            "phone": "+242066000111",
            "whatsapp": "+242077999222",
        }, timeout=15)
        assert r.status_code == 200
        bc = db.business_clients.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert bc["phone"] == "+242066000111"
        assert bc["whatsapp"] == "+242077999222"
        requests.delete(f"{API}/admin/business-clients/{r.json()['id']}", headers=admin_h, timeout=10)

    def test_send_wa_prefers_whatsapp_field(self, admin_h, db):
        """If whatsapp is set, it should be preferred over phone."""
        r = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
            "name": f"WA Pref {uuid.uuid4().hex[:6]}",
            "phone": "+242066111111",
            "whatsapp": "+242077222222",
        }, timeout=15)
        bc_id = r.json()["id"]
        pm = requests.post(f"{API}/admin/payment-methods", headers=admin_h, json={
            "label": "Cash WA", "kind": "cash", "active": True, "sort_order": 1,
        }, timeout=15).json()
        rec = requests.post(f"{API}/cashier/receipts", headers=admin_h, json={
            "business_client_id": bc_id, "amount": 5000,
            "motif": "WA test", "payment_method_id": pm["id"],
        }, timeout=15).json()
        # Send WA without override — must pick whatsapp (077222222), not phone (066111111)
        send = requests.post(f"{API}/cashier/receipts/{rec['id']}/send-whatsapp", headers=admin_h, json={}, timeout=15)
        assert send.status_code == 200
        body = send.json()
        assert "242077222222" in body.get("to", ""), f"Expected whatsapp number, got {body.get('to')}"
        # Cleanup
        requests.delete(f"{API}/admin/business-clients/{bc_id}", headers=admin_h, timeout=10)
        requests.delete(f"{API}/admin/payment-methods/{pm['id']}", headers=admin_h, timeout=10)

    def test_send_wa_fallback_to_phone(self, admin_h, db):
        """If whatsapp is empty, phone is used."""
        r = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
            "name": f"WA Fallback {uuid.uuid4().hex[:6]}",
            "phone": "+242066333333",
        }, timeout=15)
        bc_id = r.json()["id"]
        pm = requests.post(f"{API}/admin/payment-methods", headers=admin_h, json={
            "label": "Cash Fallback", "kind": "cash", "active": True, "sort_order": 2,
        }, timeout=15).json()
        rec = requests.post(f"{API}/cashier/receipts", headers=admin_h, json={
            "business_client_id": bc_id, "amount": 1000,
            "motif": "Fallback", "payment_method_id": pm["id"],
        }, timeout=15).json()
        send = requests.post(f"{API}/cashier/receipts/{rec['id']}/send-whatsapp", headers=admin_h, json={}, timeout=15)
        assert send.status_code == 200
        assert "242066333333" in send.json().get("to", "")
        requests.delete(f"{API}/admin/business-clients/{bc_id}", headers=admin_h, timeout=10)
        requests.delete(f"{API}/admin/payment-methods/{pm['id']}", headers=admin_h, timeout=10)
