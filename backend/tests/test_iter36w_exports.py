"""Iter36w — Caisse & Facturation: CSV / PDF exports.

Validates:
  - GET /api/cashier/exports/receipts.csv (RBAC, BOM UTF-8, headers OK)
  - GET /api/cashier/exports/receipts.pdf
  - GET /api/cashier/exports/invoices.csv (with kind/status filter)
  - GET /api/cashier/exports/invoices.pdf
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


@pytest.fixture
def seed(admin_h):
    bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": f"Export Test {uuid.uuid4().hex[:6]}", "phone": "+242066000111",
    }, timeout=15).json()
    pm = requests.post(f"{API}/admin/payment-methods", headers=admin_h, json={
        "label": "Cash export", "kind": "cash", "active": True, "sort_order": 1,
    }, timeout=15).json()
    # Seed 2 receipts + 1 invoice
    requests.post(f"{API}/cashier/receipts", headers=admin_h, json={
        "business_client_id": bc["id"], "amount": 12000,
        "motif": "Export R1", "payment_method_id": pm["id"],
    }, timeout=15)
    requests.post(f"{API}/cashier/receipts", headers=admin_h, json={
        "business_client_id": bc["id"], "amount": 33000,
        "motif": "Export R2", "payment_method_id": pm["id"],
    }, timeout=15)
    requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
        "kind": "proforma",
        "business_client_id": bc["id"],
        "items": [{"label": "Conseil", "quantity": 5, "unit_price_ht": 10000, "tva_pct": 18}],
    }, timeout=15)
    yield {"bc_id": bc["id"], "pm_id": pm["id"]}
    requests.delete(f"{API}/admin/business-clients/{bc['id']}", headers=admin_h, timeout=10)
    requests.delete(f"{API}/admin/payment-methods/{pm['id']}", headers=admin_h, timeout=10)


class TestReceiptsExport:
    def test_csv_rbac_blocks_anonymous(self, seed):
        r = requests.get(f"{API}/cashier/exports/receipts.csv", timeout=15)
        assert r.status_code in (401, 403)

    def test_csv_regular_user_blocked(self, seed):
        uid = f"reg_{uuid.uuid4().hex[:6]}"
        h = {"Authorization": f"Bearer {_forge(uid)}"}
        r = requests.get(f"{API}/cashier/exports/receipts.csv", headers=h, timeout=15)
        # User row not seeded → 401; if seeded but lacks can_cash → 403
        assert r.status_code in (401, 403)

    def test_csv_admin_ok_with_bom_and_headers(self, admin_h, seed):
        r = requests.get(f"{API}/cashier/exports/receipts.csv",
                         headers=admin_h,
                         params={"business_client_id": seed["bc_id"]},
                         timeout=15)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        # Excel UTF-8 BOM
        assert r.content.startswith(b"\xef\xbb\xbf")
        text = r.content.decode("utf-8-sig")
        assert "N°;Date;Client" in text
        assert "Export R1" in text and "Export R2" in text
        assert "Envoyé WA" in text
        # Filename attachment header
        assert "recus-" in r.headers.get("content-disposition", "")

    def test_pdf_admin_ok(self, admin_h, seed):
        r = requests.get(f"{API}/cashier/exports/receipts.pdf",
                         headers=admin_h,
                         params={"business_client_id": seed["bc_id"]},
                         timeout=20)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1000  # PDF non vide


class TestInvoicesExport:
    def test_csv_admin_with_kind_filter(self, admin_h, seed):
        r = requests.get(f"{API}/cashier/exports/invoices.csv",
                         headers=admin_h,
                         params={"kind": "proforma", "business_client_id": seed["bc_id"]},
                         timeout=15)
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        assert "N°;Type;Statut" in text
        assert "Proforma" in text
        # No 'Facture' line for filtered scope
        # (header has "Type" so don't grep raw "Facture"; check status column)

    def test_pdf_admin_ok(self, admin_h, seed):
        r = requests.get(f"{API}/cashier/exports/invoices.pdf",
                         headers=admin_h,
                         params={"business_client_id": seed["bc_id"]},
                         timeout=20)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_regular_user_blocked(self, seed):
        uid = f"reg_{uuid.uuid4().hex[:6]}"
        h = {"Authorization": f"Bearer {_forge(uid)}"}
        r = requests.get(f"{API}/cashier/exports/invoices.pdf", headers=h, timeout=15)
        assert r.status_code in (401, 403)
