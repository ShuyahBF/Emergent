"""S-iter39a — Two fixes:
  (1) /me/welcome-briefing → liluvine_autoreply_today must surface counts for
      tracked-role 'Moderation' users (previously got 0 because tenant_id was
      the tracked-user's own UUID, not the parent client_id).
  (2) PUT /api/admin/clients/{id} → admin/superviseur can re-link a tenant
      account to a different canonical "client lié" via link_to_client_id.
      Empty string unlinks; UUID links.
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


# ---------------------------------------------------------------------------
# (1) Moderator-visible Liluvine counter
# ---------------------------------------------------------------------------
def test_liluvine_counter_visible_for_tracked_moderator(db_sync):
    """Create a tenant + a tracked Moderation user, insert WA auto-replies,
    log in as the moderator and assert the welcome briefing shows the counts."""
    tenant_id = str(uuid.uuid4())
    mod_id = str(uuid.uuid4())
    mod_email = f"mod-{uuid.uuid4().hex[:8]}@example.com"
    mod_password = "ModeratorPass!2026"
    inserted_msgs = []
    try:
        # Tenant (admin-class user)
        db_sync.users.insert_one({
            "id": tenant_id,
            "email": f"tenant-{uuid.uuid4().hex[:6]}@example.com",
            "full_name": "Tenant Owner",
            "password_hash": "x",  # not used (we don't log in as the tenant)
            "role": "client",
            "company": "ACME Mod Co",
            "account_status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Tracked Moderation user (real `users` row + matching tracked_users row)
        from auth import hash_password
        db_sync.users.insert_one({
            "id": mod_id,
            "email": mod_email,
            "full_name": "Le Modérateur",
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
            "name": "Le Modérateur",
            "role": "Moderation",
            "status": "active",
            "user_id": mod_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # 3 auto-reply messages today under the tenant scope
        now_iso = datetime.now(timezone.utc).isoformat()
        for _ in range(3):
            mid = f"_siter39a_{uuid.uuid4().hex[:8]}"
            db_sync.liluvine_pro_messages.insert_one({
                "id": mid,
                "session_id": f"wa:{tenant_id}:test",
                "client_id": tenant_id,
                "user_id": tenant_id,
                "role": "assistant",
                "content": "auto-reply",
                "external_source": "whatsapp_native",
                "created_at": now_iso,
            })
            inserted_msgs.append(mid)

        # Log in as the moderator and read the briefing
        tok = _login(mod_email, mod_password)
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.get(f"{API}/me/welcome-briefing", headers=h, timeout=30)
        assert r.status_code == 200, r.text
        stats = r.json()["liluvine_autoreply_today"]
        assert stats["today"] >= 3, f"moderator should see today>=3, got {stats}"
    finally:
        if inserted_msgs:
            db_sync.liluvine_pro_messages.delete_many({"id": {"$in": inserted_msgs}})
        db_sync.users.delete_many({"id": {"$in": [tenant_id, mod_id]}})
        db_sync.tracked_users.delete_many({"user_id": mod_id})


# ---------------------------------------------------------------------------
# (2) link_to_client_id editable from the tenant edit form
# ---------------------------------------------------------------------------
def test_admin_can_relink_tenant_to_canonical_client(admin_h, db_sync):
    """PUT /admin/clients/{id} with link_to_client_id=<uuid> sets
    parent_client_id + client_id. Empty string unlinks."""
    canon_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    try:
        db_sync.users.insert_one({
            "id": canon_id,
            "email": f"canon-{uuid.uuid4().hex[:6]}@example.com",
            "full_name": "Canonical Parent",
            "password_hash": "x",
            "role": "superviseur",
            "company": "Group Holding",
            "account_status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db_sync.users.insert_one({
            "id": tenant_id,
            "email": f"tenant-{uuid.uuid4().hex[:6]}@example.com",
            "full_name": "Standalone Tenant",
            "password_hash": "x",
            "role": "client",
            "company": "Tenant Co",
            "account_status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # 1) Attach: link_to_client_id = canon_id
        r = requests.put(
            f"{API}/admin/clients/{tenant_id}",
            headers=admin_h,
            json={"link_to_client_id": canon_id},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        u = db_sync.users.find_one({"id": tenant_id}, {"_id": 0, "parent_client_id": 1, "client_id": 1})
        assert u["parent_client_id"] == canon_id
        assert u["client_id"] == canon_id

        # 2) Unknown canonical → 404
        r = requests.put(
            f"{API}/admin/clients/{tenant_id}",
            headers=admin_h,
            json={"link_to_client_id": "does-not-exist"},
            timeout=30,
        )
        assert r.status_code == 404

        # 3) Self-link refused
        r = requests.put(
            f"{API}/admin/clients/{tenant_id}",
            headers=admin_h,
            json={"link_to_client_id": tenant_id},
            timeout=30,
        )
        assert r.status_code == 400

        # 4) Detach: empty string clears both fields
        r = requests.put(
            f"{API}/admin/clients/{tenant_id}",
            headers=admin_h,
            json={"link_to_client_id": ""},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        u = db_sync.users.find_one({"id": tenant_id}, {"_id": 0, "parent_client_id": 1, "client_id": 1})
        assert u["parent_client_id"] is None
        assert u["client_id"] is None
    finally:
        db_sync.users.delete_many({"id": {"$in": [canon_id, tenant_id]}})
