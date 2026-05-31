"""Iter38r-fix9v — Clients page filters + WA login dedup tracking.

Tests:
  - GET /admin/clients?source=wa_otp_login filters correctly
  - GET /admin/clients?sort_by=created_at&sort_order=desc sorts correctly
  - WA OTP verify: when user already exists, do NOT create a duplicate
    AND last_wa_login_at is updated
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
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def setup(db):
    admin = f"v_adm_{uuid.uuid4().hex[:6]}"
    wa = f"v_wa_{uuid.uuid4().hex[:6]}"
    other = f"v_oth_{uuid.uuid4().hex[:6]}"
    older = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    newer = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin, "email": f"{admin}@t.l", "password_hash": "x",
         "role": "admin", "account_status": "active", "created_at": newer},
        {"id": wa, "email": f"{wa}@demo.sawalismartsystems.com",
         "password_hash": "x", "role": "client", "account_status": "active",
         "source": "wa_otp_login", "created_at": newer},
        {"id": other, "email": f"{other}@t.l", "password_hash": "x",
         "role": "client", "account_status": "active", "created_at": older},
    ])
    yield {"admin": admin, "wa": wa, "other": other,
           "admin_token": _forge(admin, "admin"),
           "older": older, "newer": newer}
    db.users.delete_many({"id": {"$in": [admin, wa, other]}})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_clients_filter_by_source_wa_otp(setup):
    r = requests.get(
        f"{API}/admin/clients",
        headers=_h(setup["admin_token"]),
        params={"source": "wa_otp_login"},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    ids = {it["id"] for it in items}
    assert setup["wa"] in ids
    # The non-WA client must NOT be in the result
    assert setup["other"] not in ids
    # Every returned row has source = wa_otp_login
    assert all(it.get("source") == "wa_otp_login" for it in items)


def test_clients_sort_by_created_at_desc(setup):
    r = requests.get(
        f"{API}/admin/clients",
        headers=_h(setup["admin_token"]),
        params={"sort_by": "created_at", "sort_order": "desc"},
    )
    assert r.status_code == 200
    items = r.json()
    # Find the index of our two test users
    idx_newer = next((i for i, it in enumerate(items) if it["id"] == setup["wa"]), -1)
    idx_older = next((i for i, it in enumerate(items) if it["id"] == setup["other"]), -1)
    assert idx_newer < idx_older  # newer comes first


def test_clients_sort_by_full_name_alpha(setup, db):
    """Alphabetical sort by full_name asc."""
    # Set predictable names on our test users
    db.users.update_one({"id": setup["wa"]}, {"$set": {"full_name": "Alpha User"}})
    db.users.update_one({"id": setup["other"]}, {"$set": {"full_name": "Zulu User"}})
    r = requests.get(
        f"{API}/admin/clients",
        headers=_h(setup["admin_token"]),
        params={"sort_by": "full_name", "sort_order": "asc"},
    )
    items = r.json()
    idx_a = next((i for i, it in enumerate(items) if it["id"] == setup["wa"]), -1)
    idx_z = next((i for i, it in enumerate(items) if it["id"] == setup["other"]), -1)
    assert idx_a < idx_z


def test_wa_login_dedup_for_existing_user(setup, db):
    """If a user already exists with the requested WhatsApp number,
    /auth/wa-otp/verify must reuse that account (no duplicate creation)
    and refresh last_wa_login_at.
    """
    # Set up an existing user with a phone
    msisdn = "22699887766"
    existing_id = f"dup_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": existing_id,
        "email": f"{existing_id}@t.l",
        "password_hash": "x",
        "role": "admin",
        "account_status": "active",
        "whatsapp": f"+{msisdn}",
        "phone_digits": msisdn,
        "full_name": "Existing Tenant",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Inject a valid OTP request manually
    db.wa_otp_requests.delete_many({"msisdn": msisdn})
    db.wa_otp_requests.insert_one({
        "msisdn": msisdn,
        "code": "123456",
        "attempts": 0,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Verify
    before_count = db.users.count_documents({"phone_digits": msisdn})
    r = requests.post(
        f"{API}/auth/wa-otp/verify",
        json={"msisdn": msisdn, "code": "123456"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["id"] == existing_id
    assert data["user"]["role"] == "admin"
    assert data["user"]["is_demo"] is False
    # No duplicate user was created
    after_count = db.users.count_documents({"phone_digits": msisdn})
    assert after_count == before_count == 1
    # last_wa_login_at is set
    fresh = db.users.find_one({"id": existing_id})
    assert fresh.get("last_wa_login_at")
    # Cleanup
    db.users.delete_one({"id": existing_id})
