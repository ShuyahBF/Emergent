"""S-iter39m — Bug fix : tickets created from the bubble must be visible.

Regression : an admin (company="SAWALI") creating a ticket on a client with
a different company never sees it back in `/me/tickets` because the listing
filtered by `_resolve_visible_client_ids` which only includes same-company
users. Fix : admin/superviseur now see all tickets.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30).json()
    if not r.get("needs_otp"):
        return r["access_token"]
    return requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": r["session_token"], "code": r["dev_otp"]},
        timeout=30,
    ).json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_admin_sees_ticket_for_other_company_client(admin_h, db_sync):
    """Create a client with a DIFFERENT company from the admin, then open
    a ticket on it via /me/tickets. The admin must see it back in
    GET /me/tickets."""
    # 1. Seed a client (role=client) with a clearly different company
    target_id = str(uuid.uuid4())
    db_sync.users.insert_one({
        "id": target_id,
        "email": f"client-{uuid.uuid4().hex[:6]}@other-company.test",
        "full_name": "Client Boulangerie XYZ",
        "company": "Boulangerie XYZ SARL",
        "password_hash": "x",
        "role": "client",
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        # 2. Admin creates a ticket on that client via /me/tickets (bubble path)
        payload = {
            "client_id": target_id,
            "reason": f"Test bubble bug {uuid.uuid4().hex[:6]}",
            "contact_name": "Rapporteur Test",
            "contact_phone": "+225 0102030405",
            "incident_at": datetime.now(timezone.utc).isoformat(),
        }
        r = requests.post(f"{API}/me/tickets", headers=admin_h, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        try:
            # 3. Admin must see it back in /me/tickets
            r2 = requests.get(f"{API}/me/tickets", headers=admin_h, params={"limit": 1000}, timeout=30)
            assert r2.status_code == 200, r2.text
            items = r2.json()
            assert isinstance(items, list)
            ids = [t.get("id") for t in items]
            assert tid in ids, f"Ticket {tid} created on cross-company client not visible! Got {len(items)} tickets."
        finally:
            db_sync.support_tickets.delete_one({"id": tid})
    finally:
        db_sync.users.delete_one({"id": target_id})
