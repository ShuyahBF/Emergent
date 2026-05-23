"""Iter36x — Relance des factures impayées (bulk WhatsApp reminder)."""
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
    d = r.json()
    if not d.get("needs_otp"):
        return d["access_token"]
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": d["session_token"], "code": d["dev_otp"]},
        timeout=30,
    )
    return r2.json()["access_token"]


def _forge(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "client",
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
def overdue_setup(admin_h, db):
    """Seed: 1 business client + 2 invoices, one overdue, one fresh."""
    bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": f"Relance Test {uuid.uuid4().hex[:6]}", "phone": "+242066999222",
    }, timeout=15).json()
    # Create an invoice + manually push due_date to the past
    inv_overdue = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
        "kind": "invoice",
        "business_client_id": bc["id"],
        "items": [{"label": "Audit", "quantity": 1, "unit_price_ht": 80000, "tva_pct": 18}],
        "due_date": (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d"),
    }, timeout=15).json()
    # Create one with future due_date (NOT overdue)
    inv_fresh = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
        "kind": "invoice",
        "business_client_id": bc["id"],
        "items": [{"label": "Conseil", "quantity": 1, "unit_price_ht": 30000, "tva_pct": 18}],
        "due_date": (datetime.now(timezone.utc) + timedelta(days=15)).strftime("%Y-%m-%d"),
    }, timeout=15).json()
    yield {"bc_id": bc["id"], "overdue_id": inv_overdue["id"], "fresh_id": inv_fresh["id"]}
    db.invoices.delete_one({"id": inv_overdue["id"]})
    db.invoices.delete_one({"id": inv_fresh["id"]})
    requests.delete(f"{API}/admin/business-clients/{bc['id']}", headers=admin_h, timeout=10)


class TestOverdueCount:
    def test_count_regular_user_blocked(self, overdue_setup):
        uid = f"reg_{uuid.uuid4().hex[:6]}"
        h = {"Authorization": f"Bearer {_forge(uid)}"}
        r = requests.get(f"{API}/cashier/overdue/count", headers=h, timeout=15)
        assert r.status_code in (401, 403)

    def test_count_includes_overdue_excludes_fresh(self, admin_h, overdue_setup):
        r = requests.get(f"{API}/cashier/overdue/count", headers=admin_h, params={"grace_days": 30}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["count"] >= 1
        assert body["grace_days"] == 30


class TestRelanceBulk:
    def test_dry_run_returns_results_without_persisting(self, admin_h, overdue_setup, db):
        r = requests.post(f"{API}/cashier/overdue/relance", headers=admin_h, json={
            "grace_days": 30, "dry_run": True,
            "ids": [overdue_setup["overdue_id"]],
        }, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True
        assert body["total"] >= 1
        # No reminder field persisted in dry-run
        inv = db.invoices.find_one({"id": overdue_setup["overdue_id"]}, {"_id": 0})
        assert inv.get("last_reminder_at") is None
        assert "reminders_count" not in inv or inv["reminders_count"] == 0

    def test_real_relance_persists_reminder_fields(self, admin_h, overdue_setup, db):
        r = requests.post(f"{API}/cashier/overdue/relance", headers=admin_h, json={
            "grace_days": 30, "dry_run": False,
            "ids": [overdue_setup["overdue_id"]],
        }, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 1
        # WhatsApp may or may not be configured — but reminder fields ONLY appear when ok=True
        # Verify the result entry is present
        assert len(body["results"]) == 1
        res = body["results"][0]
        assert res["id"] == overdue_setup["overdue_id"]
        if res.get("ok"):
            inv = db.invoices.find_one({"id": overdue_setup["overdue_id"]}, {"_id": 0})
            assert inv.get("last_reminder_at")
            assert inv.get("reminders_count", 0) >= 1
        else:
            # Graceful failure (WA non configuré) — still recorded as ko
            assert res.get("error") or res.get("skipped")

    def test_fresh_invoice_not_targeted(self, admin_h, overdue_setup):
        r = requests.post(f"{API}/cashier/overdue/relance", headers=admin_h, json={
            "grace_days": 30, "dry_run": True,
        }, timeout=20)
        body = r.json()
        # The "fresh" invoice (future due_date) MUST NOT appear in results
        ids = [x["id"] for x in body["results"]]
        assert overdue_setup["fresh_id"] not in ids

    def test_no_phone_skipped(self, admin_h, db):
        """Invoice for a business_client with no phone — should be skipped, not failed."""
        bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
            "name": f"NoPhoneRelance {uuid.uuid4().hex[:6]}",
        }, timeout=15).json()
        inv = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
            "kind": "invoice",
            "business_client_id": bc["id"],
            "items": [{"label": "Test", "quantity": 1, "unit_price_ht": 10000, "tva_pct": 18}],
            "due_date": (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d"),
        }, timeout=15).json()
        try:
            r = requests.post(f"{API}/cashier/overdue/relance", headers=admin_h, json={
                "grace_days": 30, "dry_run": False, "ids": [inv["id"]],
            }, timeout=20)
            body = r.json()
            assert body["skipped_no_phone"] >= 1
            res0 = next((x for x in body["results"] if x["id"] == inv["id"]), None)
            assert res0 is not None
            assert res0.get("skipped") == "no_phone"
        finally:
            db.invoices.delete_one({"id": inv["id"]})
            requests.delete(f"{API}/admin/business-clients/{bc['id']}", headers=admin_h, timeout=10)
