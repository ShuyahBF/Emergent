"""Iter35o-fix — Regression: ticket creation must work on WhatsApp-imported
contacts that live in `directory_contacts` (not `contacts`)."""
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


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data["dev_otp"]}, timeout=30)
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_user(db):
    return db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})


def test_ticket_creation_works_for_directory_contact(admin_h, db, admin_user):
    """A contact imported from WhatsApp lives in `directory_contacts`. The
    'Générer un ticket' button used to return 404 — this confirms the fix."""
    scope = admin_user.get("client_id") or admin_user["id"]
    cid = f"TEST_dc_{uuid.uuid4().hex[:8]}"
    db.directory_contacts.insert_one({
        "id": cid, "client_id": scope, "name": "WhatsApp Import Test",
        "whatsapp": "+22899880011", "phone": "+22899880011",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(
            f"{API}/me/contacts/{cid}/ticket",
            headers=admin_h, json={"motif": "Reçu via WA"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["ticket"]["contact_id"] == cid
        # Active-ticket endpoint must also resolve the directory_contact
        r2 = requests.get(f"{API}/me/contacts/{cid}/active-ticket", headers=admin_h, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["active"] is True
    finally:
        db.directory_contacts.delete_one({"id": cid})
        db.support_tickets.delete_many({"contact_id": cid})
