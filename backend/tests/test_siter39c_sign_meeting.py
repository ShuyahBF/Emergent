"""S017 — Signature électronique des PV.

Tests:
  - Admin signs → fields set, GET returns signed_at + signed_by_*.
  - Signed PV: PUT returns 423 LOCKED, DELETE returns 423 LOCKED.
  - Re-signing is idempotent.
  - Unsign reverts → PUT/DELETE work again.
  - Tracked Moderation user CANNOT sign (only admin/sup or tracked Admin/Sup).
  - PDF rendering still works on signed PV (smoke test on bytes prefix).
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


def test_sign_lock_unsign_cycle(admin_h, db_sync):
    created_ids = []
    try:
        # 1) Create a PV
        r = requests.post(f"{API}/me/meetings", headers=admin_h, json={
            "meeting_date": "2026-02-20",
            "started_at": "2026-02-20T10:00:00Z",
            "title": f"PV sign test {uuid.uuid4().hex[:6]}",
            "body_html": "<p>Body for signing</p>",
        }, timeout=30)
        assert r.status_code == 201, r.text
        m = r.json()
        created_ids.append(m["id"])
        assert m.get("signed_at") in (None, "")

        # 2) Sign it
        r = requests.post(f"{API}/me/meetings/{m['id']}/sign", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        signed = r.json()
        assert signed["signed_at"]
        assert signed["signed_by_email"] == ADMIN_EMAIL.lower()

        # 3) PUT now locked
        r = requests.put(f"{API}/me/meetings/{m['id']}", headers=admin_h, json={"title": "Hack"}, timeout=30)
        assert r.status_code == 423, r.text

        # 4) DELETE now locked
        r = requests.delete(f"{API}/me/meetings/{m['id']}", headers=admin_h, timeout=30)
        assert r.status_code == 423, r.text

        # 5) Re-sign is idempotent
        r = requests.post(f"{API}/me/meetings/{m['id']}/sign", headers=admin_h, timeout=30)
        assert r.status_code == 200
        # signed_at should stay the same (idempotent path returns the existing doc)
        assert r.json()["signed_at"] == signed["signed_at"]

        # 6) PDF still works
        r = requests.get(f"{API}/me/meetings/{m['id']}/pdf", headers=admin_h, timeout=30)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

        # 7) Unsign → editable again
        r = requests.post(f"{API}/me/meetings/{m['id']}/unsign", headers=admin_h, timeout=30)
        assert r.status_code == 200
        assert r.json()["signed_at"] is None

        # 8) PUT works again
        r = requests.put(f"{API}/me/meetings/{m['id']}", headers=admin_h, json={"title": "After unsign"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "After unsign"
    finally:
        if created_ids:
            db_sync.meeting_minutes.delete_many({"id": {"$in": created_ids}})


def test_moderator_cannot_sign(db_sync):
    """Tracked Moderation user cannot sign PVs (admin/sup or tracked
    Admin/Sup only — `_can_delete` rule)."""
    tenant_id = str(uuid.uuid4())
    mod_id = str(uuid.uuid4())
    mod_email = f"mod-sign-{uuid.uuid4().hex[:6]}@example.com"
    mod_password = "ModeratorSign!2026"
    pv_id = str(uuid.uuid4())
    try:
        from auth import hash_password
        db_sync.users.insert_one({
            "id": tenant_id,
            "email": f"t-{uuid.uuid4().hex[:6]}@example.com",
            "full_name": "Tenant",
            "password_hash": "x",
            "role": "client",
            "company": "SignCo",
            "account_status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db_sync.users.insert_one({
            "id": mod_id,
            "email": mod_email,
            "full_name": "Mod",
            "password_hash": hash_password(mod_password),
            "role": "client",
            "tracked_role": "Moderation",
            "parent_client_id": tenant_id,
            "client_id": tenant_id,
            "account_status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db_sync.tracked_users.insert_one({
            "id": str(uuid.uuid4()),
            "client_id": tenant_id,
            "email": mod_email,
            "name": "Mod",
            "role": "Moderation",
            "status": "active",
            "user_id": mod_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # PV under the tenant
        db_sync.meeting_minutes.insert_one({
            "id": pv_id,
            "tenant_id": tenant_id,
            "numero": "PV-2026-999",
            "meeting_date": "2026-02-20",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "title": "Test mod cannot sign",
            "body_html": "",
            "attendees": None,
            "author_id": tenant_id,
            "author_name": "Tenant",
            "author_email": f"t-x@example.com",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "deleted_at": None,
        })
        tok = _login(mod_email, mod_password)
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.post(f"{API}/me/meetings/{pv_id}/sign", headers=h, timeout=30)
        assert r.status_code == 403, r.text
    finally:
        db_sync.users.delete_many({"id": {"$in": [tenant_id, mod_id]}})
        db_sync.tracked_users.delete_many({"user_id": mod_id})
        db_sync.meeting_minutes.delete_one({"id": pv_id})
