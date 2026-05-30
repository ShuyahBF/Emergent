"""Iter38r-fix9g — Regression tests for the 3 bug fixes:

1. AdminSettings search now finds the 3 Liluvine sections (Auto-reply,
   Branding, KB). Each is wrapped in `<Filterable>` so the existing search
   index picks them up.
2. Eye icon visible on shared notes for admins too (frontend-only,
   covered by a presence assertion in NoteCard render — skipped here).
3. `/admin/clients-consistency` now flags tracked_users whose `client_id`
   diverges from their parent admin's canonical id.
"""
from __future__ import annotations

import os
import uuid
import datetime as dt
from pathlib import Path

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
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    ).json()
    if r.get("needs_otp"):
        r = requests.post(
            f"{API}/auth/verify-otp",
            json={"session_token": r["session_token"], "code": r["dev_otp"]},
            timeout=30,
        ).json()
    return r["access_token"]


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def admin_id(db_sync):
    return db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})["id"]


def test_consistency_scan_detects_misaligned_tracked_user(admin_h, db_sync, admin_id):
    """A tracked user attached to admin's tenant but with a wrong client_id
    must appear in the misaligned list."""
    # Ensure admin has `company` set (the scan needs it to group by company)
    existing = db_sync.users.find_one({"id": admin_id}, {"_id": 0, "company": 1})
    admin_company = (existing or {}).get("company") or "SAWALI"
    db_sync.users.update_one(
        {"id": admin_id},
        {"$set": {"company": admin_company}},
    )
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    bad_id = "fix9g_bad_" + uuid.uuid4().hex[:8]
    good_id = "fix9g_good_" + uuid.uuid4().hex[:8]
    bad_email = f"misaligned-tracker-{uuid.uuid4().hex[:6]}@sawalismartsystems.com"
    good_email = f"aligned-tracker-{uuid.uuid4().hex[:6]}@sawalismartsystems.com"

    # 1) Misaligned: client_id != parent_client_id (= admin_id)
    db_sync.users.insert_one({
        "id": bad_id, "email": bad_email, "full_name": "Bad Tracker",
        "role": "tracked", "tracked_role": "Consultation",
        "parent_client_id": admin_id, "client_id": "ZZZ_WRONG_SCOPE",
        "is_active": True, "account_status": "active",
        "created_at": now,
    })
    # 2) Aligned: client_id == parent_client_id == admin_id
    db_sync.users.insert_one({
        "id": good_id, "email": good_email, "full_name": "Good Tracker",
        "role": "tracked", "tracked_role": "Consultation",
        "parent_client_id": admin_id, "client_id": admin_id,
        "is_active": True, "account_status": "active",
        "created_at": now,
    })
    try:
        r = requests.get(f"{API}/admin/clients-consistency", headers=admin_h, timeout=30)
        assert r.status_code == 200
        body = r.json()
        # At least one group must be misaligned now
        all_misaligned = []
        for g in body.get("groups", []):
            for m in g.get("misaligned", []):
                all_misaligned.append(m.get("id"))
        assert bad_id in all_misaligned, (
            f"Expected the misaligned tracked user to be flagged. "
            f"Total misaligned reported: {body.get('misaligned_users_total')}. "
            f"All flagged ids: {all_misaligned}"
        )
        assert good_id not in all_misaligned, "Aligned tracker should not be flagged"
    finally:
        db_sync.users.delete_one({"id": bad_id})
        db_sync.users.delete_one({"id": good_id})


def test_consistency_endpoint_response_shape(admin_h):
    r = requests.get(f"{API}/admin/clients-consistency", headers=admin_h, timeout=30)
    assert r.status_code == 200
    body = r.json()
    for k in ("scanned_groups", "aligned_groups", "misaligned_groups",
              "misaligned_users_total", "groups"):
        assert k in body, f"Missing field: {k}"
    assert isinstance(body["groups"], list)
