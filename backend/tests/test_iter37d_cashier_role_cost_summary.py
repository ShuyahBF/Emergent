"""Iter37d — can_cash flag via /admin/clients + Monthly cost aggregate endpoint."""
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
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    d = r.json()
    if not d.get("needs_otp"):
        return d["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": d["session_token"], "code": d["dev_otp"]}, timeout=30)
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
def fresh_user(db, admin_h):
    """Create a regular client user."""
    payload = {
        "email": f"u_{uuid.uuid4().hex[:6]}@example.com",
        "full_name": "Test Cashier Flag",
        "password": "TempPass1!",
        "role": "client",
        "company": "FlagTest",
    }
    r = requests.post(f"{API}/admin/clients", headers=admin_h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    yield uid
    requests.delete(f"{API}/admin/clients/{uid}", headers=admin_h, timeout=10)


class TestCanCashViaClientUpdate:
    def test_set_can_cash_via_put_clients(self, admin_h, fresh_user, db):
        # Toggle ON via PUT /admin/clients/{uid}
        r = requests.put(f"{API}/admin/clients/{fresh_user}", headers=admin_h,
                         json={"can_cash": True}, timeout=15)
        assert r.status_code == 200, r.text
        u = db.users.find_one({"id": fresh_user}, {"_id": 0, "can_cash": 1})
        assert u["can_cash"] is True
        # Toggle OFF
        r2 = requests.put(f"{API}/admin/clients/{fresh_user}", headers=admin_h,
                          json={"can_cash": False}, timeout=15)
        assert r2.status_code == 200
        u = db.users.find_one({"id": fresh_user}, {"_id": 0, "can_cash": 1})
        assert u["can_cash"] is False

    def test_auth_me_reflects_can_cash(self, admin_h, fresh_user, db):
        # Enable cash flag
        requests.put(f"{API}/admin/clients/{fresh_user}", headers=admin_h,
                     json={"can_cash": True}, timeout=15)
        h = {"Authorization": f"Bearer {_forge(fresh_user, role='client')}"}
        r = requests.get(f"{API}/auth/me", headers=h, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("can_cash") is True


class TestTicketsCostSummary:
    def test_regular_user_blocked(self, fresh_user):
        h = {"Authorization": f"Bearer {_forge(fresh_user, role='client')}"}
        r = requests.get(f"{API}/me/tickets/cost-summary", headers=h, timeout=15)
        assert r.status_code in (401, 403)

    def test_admin_gets_shape(self, admin_h):
        r = requests.get(f"{API}/me/tickets/cost-summary", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("month", "period_start", "period_end", "currency",
                  "grand_total", "grand_hours", "grand_count", "by_client"):
            assert k in body
        assert body["currency"] == "XOF"
        assert isinstance(body["by_client"], list)

    def test_aggregates_closed_tickets(self, admin_h, db):
        # Seed 2 closed tickets in current month
        admin_doc = db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "id": 1}) or {}
        client_id = admin_doc.get("id")
        now = datetime.now(timezone.utc)
        ids = []
        for cost in (20000, 35000):
            tid = str(uuid.uuid4())
            db.support_tickets.insert_one({
                "id": tid, "client_id": client_id,
                "number": f"TKT-{now.year}-9999",
                "status": "done",
                "opened_at": (now - timedelta(hours=2)).isoformat(),
                "closed_at": now.isoformat(),
                "cost_amount": cost, "cost_mode": "hourly",
                "active_hours": 2.0,
            })
            ids.append(tid)
        try:
            r = requests.get(f"{API}/me/tickets/cost-summary", headers=admin_h, timeout=15)
            body = r.json()
            # At least our 2 tickets contribute (others may exist)
            assert body["grand_total"] >= 55000
            assert body["grand_count"] >= 2
        finally:
            for tid in ids:
                db.support_tickets.delete_one({"id": tid})

    def test_months_back_param(self, admin_h):
        r = requests.get(f"{API}/me/tickets/cost-summary", headers=admin_h, params={"months_back": 2}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        # Should resolve a month ≠ current
        assert body["month"] != datetime.now(timezone.utc).strftime("%Y-%m")
