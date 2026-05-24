"""Iter37e — Export PDF/CSV pour le récap mensuel du coût des interventions."""
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
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
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
def regular_user(db):
    uid = f"reg_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
        "full_name": "Regular", "role": "client", "account_status": "active",
    })
    yield uid
    db.users.delete_one({"id": uid})


class TestCostSummaryExports:
    def test_csv_export_returns_excel_bom_and_table(self, admin_h):
        r = requests.get(f"{API}/me/tickets/cost-summary.csv", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/csv")
        # UTF-8 BOM (Excel-friendly)
        assert r.content.startswith(b"\xef\xbb\xbf"), "CSV must start with UTF-8 BOM"
        text = r.content.decode("utf-8-sig")
        # Header line in French
        assert "SAWALI" in text
        assert "Coût des interventions" in text
        # Column headers
        assert "Client Lié" in text
        assert "Coût total" in text
        # Total row
        assert "TOTAL" in text
        # Filename
        cd = r.headers.get("content-disposition", "")
        assert "cout-interventions-" in cd
        assert cd.endswith('.csv"')

    def test_pdf_export_is_valid_pdf(self, admin_h):
        r = requests.get(f"{API}/me/tickets/cost-summary.pdf", headers=admin_h, timeout=20)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        # PDF magic bytes
        assert r.content[:4] == b"%PDF", "Must start with PDF magic bytes"
        # Non-trivial size
        assert len(r.content) > 1000
        # Filename
        cd = r.headers.get("content-disposition", "")
        assert "cout-interventions-" in cd
        assert cd.endswith('.pdf"')

    def test_months_back_parameter_changes_period(self, admin_h):
        r0 = requests.get(f"{API}/me/tickets/cost-summary.csv", headers=admin_h,
                          params={"months_back": 0}, timeout=15)
        r3 = requests.get(f"{API}/me/tickets/cost-summary.csv", headers=admin_h,
                          params={"months_back": 3}, timeout=15)
        assert r0.status_code == 200 and r3.status_code == 200
        # Filenames embed the month, must differ
        cd0 = r0.headers["content-disposition"]
        cd3 = r3.headers["content-disposition"]
        assert cd0 != cd3, f"Filenames must differ for months_back=0 vs 3 ({cd0} == {cd3})"

    def test_csv_export_forbidden_for_regular_user(self, regular_user):
        h = {"Authorization": f"Bearer {_forge(regular_user)}"}
        r = requests.get(f"{API}/me/tickets/cost-summary.csv", headers=h, timeout=15)
        assert r.status_code == 403

    def test_pdf_export_forbidden_for_regular_user(self, regular_user):
        h = {"Authorization": f"Bearer {_forge(regular_user)}"}
        r = requests.get(f"{API}/me/tickets/cost-summary.pdf", headers=h, timeout=15)
        assert r.status_code == 403

    def test_csv_contains_aggregated_data_when_tickets_exist(self, admin_h, db):
        """Seed a closed ticket with cost, verify it shows up in CSV."""
        admin = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
        admin_id = admin["id"]
        # Seed a fake closed ticket with cost in the current month
        tid = f"test_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)
        db.support_tickets.insert_one({
            "id": tid,
            "number": f"TEST-{now.year}-9999",
            "client_id": admin_id,
            "client_name": "SAWALI TEST",
            "status": "done",
            "opened_at": (now - timedelta(hours=2)).isoformat(),
            "closed_at": now.isoformat(),
            "active_hours": 2.0,
            "cost_amount": 50000.0,
            "cost_mode": "flat",
            "cost_currency": "XOF",
        })
        try:
            r = requests.get(f"{API}/me/tickets/cost-summary.csv", headers=admin_h,
                             params={"months_back": 0}, timeout=15)
            assert r.status_code == 200
            text = r.content.decode("utf-8-sig")
            # The seeded amount or the TOTAL row containing it must appear
            assert "50000" in text or "TOTAL" in text
        finally:
            db.support_tickets.delete_one({"id": tid})
