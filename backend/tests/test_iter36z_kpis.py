"""Iter36z — KPIs dashboard for Facturation header."""
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


def _forge(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "client",
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
def seeded_invoices(admin_h, db):
    """Seed 2 business clients + invoices in various states."""
    bc1 = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": f"KPI Bad Payer {uuid.uuid4().hex[:6]}", "phone": "+242066444111",
    }, timeout=15).json()
    bc2 = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": f"KPI Good Payer {uuid.uuid4().hex[:6]}", "phone": "+242066444222",
    }, timeout=15).json()
    # 1) Big unpaid (overdue 60 days) for bc1
    inv_due_big = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
        "kind": "invoice",
        "business_client_id": bc1["id"],
        "items": [{"label": "Big", "quantity": 1, "unit_price_ht": 500000, "tva_pct": 18}],
        "due_date": (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d"),
    }, timeout=15).json()
    # 2) Paid this month — go through proforma → invoice → paid lifecycle
    # Simulate by direct DB insertion of a paid invoice this month
    iid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db.invoices.insert_one({
        "id": iid,
        "kind": "invoice",
        "status": "paid",
        "number": f"F-{now.year}-9999",
        "year": now.year, "seq": 9999,
        "business_client_id": bc2["id"],
        "business_client_snapshot": {"name": bc2["name"]},
        "items": [],
        "subtotal_ht": 100000, "total_tva": 18000, "total_ttc": 118000,
        "discount_kind": "none", "discount_value": 0,
        "net_to_pay": 118000,
        "amount_in_words": "cent dix-huit mille francs CFA",
        "created_at": now.replace(day=1).isoformat(),  # ≥ month_start ✓
        "paid_at": now.isoformat(),
        "paid_method_label": "Espèces",
    })
    # 3) Small unpaid for bc2
    inv_due_small = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
        "kind": "invoice",
        "business_client_id": bc2["id"],
        "items": [{"label": "Small", "quantity": 1, "unit_price_ht": 10000, "tva_pct": 18}],
        "due_date": (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d"),
    }, timeout=15).json()
    yield {
        "bc1_id": bc1["id"], "bc2_id": bc2["id"],
        "due_big_id": inv_due_big["id"], "paid_id": iid, "due_small_id": inv_due_small["id"],
        "bc1_name": bc1["name"], "bc2_name": bc2["name"],
    }
    # Cleanup
    db.invoices.delete_one({"id": iid})
    db.invoices.delete_one({"id": inv_due_big["id"]})
    db.invoices.delete_one({"id": inv_due_small["id"]})
    requests.delete(f"{API}/admin/business-clients/{bc1['id']}", headers=admin_h, timeout=10)
    requests.delete(f"{API}/admin/business-clients/{bc2['id']}", headers=admin_h, timeout=10)


class TestKpis:
    def test_regular_user_blocked(self, seeded_invoices):
        uid = f"reg_{uuid.uuid4().hex[:6]}"
        h = {"Authorization": f"Bearer {_forge(uid)}"}
        r = requests.get(f"{API}/cashier/kpis", headers=h, timeout=15)
        assert r.status_code in (401, 403)

    def test_schema_shape(self, admin_h, seeded_invoices):
        r = requests.get(f"{API}/cashier/kpis", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        # Mandatory keys
        for k in ("encaisse_this_month", "restant_a_encaisser", "delai_moyen_jours",
                  "delai_moyen_sample_size", "top_bad_payers", "as_of"):
            assert k in body, f"missing key {k}"
        assert "amount" in body["encaisse_this_month"]
        assert "count" in body["encaisse_this_month"]
        assert "currency" in body["encaisse_this_month"]
        assert "amount" in body["restant_a_encaisser"]
        assert "count" in body["restant_a_encaisser"]

    def test_paid_this_month_includes_seeded(self, admin_h, seeded_invoices):
        r = requests.get(f"{API}/cashier/kpis", headers=admin_h, timeout=15)
        body = r.json()
        # Our seeded paid invoice = 118000, should be at least counted
        assert body["encaisse_this_month"]["amount"] >= 118000
        assert body["encaisse_this_month"]["count"] >= 1

    def test_outstanding_includes_unpaid(self, admin_h, seeded_invoices):
        r = requests.get(f"{API}/cashier/kpis", headers=admin_h, timeout=15)
        body = r.json()
        # Big + small unpaid = 590000 + 11800 = 601800 minimum
        assert body["restant_a_encaisser"]["amount"] >= 601800
        assert body["restant_a_encaisser"]["count"] >= 2

    def test_top_bad_payers_includes_biggest(self, admin_h, seeded_invoices):
        r = requests.get(f"{API}/cashier/kpis", headers=admin_h, timeout=15)
        body = r.json()
        top = body["top_bad_payers"]
        assert isinstance(top, list)
        assert len(top) >= 1
        # The biggest unpaid (590000 TTC = 590000) should be in top
        names = [t["name"] for t in top]
        assert seeded_invoices["bc1_name"] in names
        # Verify shape of each entry
        for t in top:
            assert "business_client_id" in t
            assert "name" in t
            assert "unpaid_amount" in t
            assert "unpaid_count" in t

    def test_avg_payment_delay_nullable(self, admin_h, seeded_invoices):
        r = requests.get(f"{API}/cashier/kpis", headers=admin_h, timeout=15)
        body = r.json()
        # The seeded paid invoice has created_at on day-1 of month; paid today
        # Therefore delai >= 0
        if body["delai_moyen_jours"] is not None:
            assert body["delai_moyen_jours"] >= 0
        assert body["delai_moyen_sample_size"] >= 0
