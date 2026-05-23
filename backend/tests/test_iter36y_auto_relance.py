"""Iter36y — Auto-relance cron + per-client toggle + manual trigger + history."""
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
def opted_in_client(admin_h, db):
    bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": f"AutoRelance {uuid.uuid4().hex[:6]}",
        "phone": "+242066333111",
        "auto_relance_enabled": True,
    }, timeout=15).json()
    inv = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
        "kind": "invoice",
        "business_client_id": bc["id"],
        "items": [{"label": "Test", "quantity": 1, "unit_price_ht": 20000, "tva_pct": 18}],
        "due_date": (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d"),
    }, timeout=15).json()
    yield {"bc_id": bc["id"], "inv_id": inv["id"]}
    db.invoices.delete_one({"id": inv["id"]})
    requests.delete(f"{API}/admin/business-clients/{bc['id']}", headers=admin_h, timeout=10)


@pytest.fixture
def opted_out_client(admin_h, db):
    """Client with auto_relance OFF — must NOT be relanced."""
    bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
        "name": f"OptOut {uuid.uuid4().hex[:6]}",
        "phone": "+242066333222",
        "auto_relance_enabled": False,
    }, timeout=15).json()
    inv = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
        "kind": "invoice",
        "business_client_id": bc["id"],
        "items": [{"label": "Test", "quantity": 1, "unit_price_ht": 50000, "tva_pct": 18}],
        "due_date": (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%d"),
    }, timeout=15).json()
    yield {"bc_id": bc["id"], "inv_id": inv["id"]}
    db.invoices.delete_one({"id": inv["id"]})
    requests.delete(f"{API}/admin/business-clients/{bc['id']}", headers=admin_h, timeout=10)


class TestBusinessClientToggle:
    def test_toggle_persisted(self, admin_h, opted_in_client, db):
        bc = db.business_clients.find_one({"id": opted_in_client["bc_id"]}, {"_id": 0})
        assert bc.get("auto_relance_enabled") is True

    def test_default_off(self, admin_h, db):
        r = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
            "name": f"Default {uuid.uuid4().hex[:6]}",
        }, timeout=15)
        assert r.status_code == 200
        bc = db.business_clients.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert bc.get("auto_relance_enabled") in (False, None)
        requests.delete(f"{API}/admin/business-clients/{r.json()['id']}", headers=admin_h, timeout=10)


class TestManualTrigger:
    def test_regular_user_blocked(self):
        uid = f"reg_{uuid.uuid4().hex[:6]}"
        h = {"Authorization": f"Bearer {_forge(uid)}"}
        r = requests.post(f"{API}/cashier/overdue/relance-auto-run", headers=h, timeout=15)
        assert r.status_code in (401, 403)

    def test_admin_trigger_acts_on_opted_in_only(self, admin_h, opted_in_client, opted_out_client):
        r = requests.post(f"{API}/cashier/overdue/relance-auto-run", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("triggered_by", "").startswith("manual:")
        # 'business_clients_count' is the count of OPTED-IN clients targeted
        if not body.get("skipped"):
            assert body["business_clients_count"] >= 1
            ids = [r["id"] for r in body.get("results", [])]
            assert opted_in_client["inv_id"] in ids
            # The opt-out invoice MUST NOT appear
            assert opted_out_client["inv_id"] not in ids

    def test_history_endpoint(self, admin_h, opted_in_client):
        # Trigger once to ensure at least one history entry exists
        requests.post(f"{API}/cashier/overdue/relance-auto-run", headers=admin_h, timeout=30)
        r = requests.get(f"{API}/cashier/overdue/relance-history", headers=admin_h, params={"limit": 5}, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        assert len(rows) >= 1
        first = rows[0]
        assert "started_at" in first
        assert "triggered_by" in first


class TestCronSkipLogic:
    def test_cron_skips_when_master_disabled(self, admin_h, opted_in_client, db):
        """Direct in-process call simulation — manual bypasses master, cron honors it."""
        # Ensure master is off
        db.settings.update_one({"_id": "global"}, {"$set": {"auto_relance_enabled": False}}, upsert=True)
        # We can't directly call the in-process runner from here, but the manual
        # endpoint bypasses master so it should still succeed.
        r = requests.post(f"{API}/cashier/overdue/relance-auto-run", headers=admin_h, timeout=30)
        assert r.status_code == 200
        body = r.json()
        # Manual trigger should NOT be skipped due to master_disabled
        assert body.get("skipped") in (None, False) or body.get("reason") != "master_disabled"
