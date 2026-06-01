"""S-iter39b — Liluvine PRO takeover RBAC for tracked Moderation users.

Confirms that a tracked user with `tracked_role="Moderation"` is allowed
to call /admin/liluvine-pro/sessions/{id}/takeover (previously rejected
because the role-set used "moderateur" but the stored value is "Moderation").
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30).json()
    if not r.get("needs_otp"):
        return r["access_token"]
    return requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": r["session_token"], "code": r["dev_otp"]},
        timeout=30,
    ).json()["access_token"]


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_tracked_moderation_can_takeover(db_sync):
    tenant_id = str(uuid.uuid4())
    mod_id = str(uuid.uuid4())
    mod_email = f"mod-takeover-{uuid.uuid4().hex[:6]}@example.com"
    mod_password = "ModerationTakeover!2026"
    sess_id = f"wa:{tenant_id}:{uuid.uuid4().hex[:6]}"
    try:
        from auth import hash_password
        db_sync.users.insert_one({
            "id": tenant_id,
            "email": f"tenant-{uuid.uuid4().hex[:6]}@example.com",
            "full_name": "Tenant",
            "password_hash": "x",
            "role": "client",
            "company": "Takeover Co",
            "account_status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db_sync.users.insert_one({
            "id": mod_id,
            "email": mod_email,
            "full_name": "Mod Takeover",
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
            "name": "Mod Takeover",
            "role": "Moderation",
            "status": "active",
            "user_id": mod_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Liluvine session under the tenant
        db_sync.liluvine_pro_sessions.insert_one({
            "id": sess_id,
            "client_id": tenant_id,
            "user_id": tenant_id,
            "title": "Test WA session",
            "external_source": "whatsapp_native",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message_count": 0,
            "human_takeover": False,
        })
        tok = _login(mod_email, mod_password)
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.post(
            f"{API}/admin/liluvine-pro/sessions/{sess_id}/takeover",
            headers=h, json={"duration_minutes": 30}, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("human_takeover_until")  # takeover was applied
        # Confirm DB state
        s = db_sync.liluvine_pro_sessions.find_one({"id": sess_id}, {"_id": 0, "human_takeover": 1})
        assert s.get("human_takeover") is True

        # Release
        r = requests.post(
            f"{API}/admin/liluvine-pro/sessions/{sess_id}/release",
            headers=h, json={}, timeout=30,
        )
        assert r.status_code == 200, r.text
    finally:
        db_sync.users.delete_many({"id": {"$in": [tenant_id, mod_id]}})
        db_sync.tracked_users.delete_many({"user_id": mod_id})
        db_sync.liluvine_pro_sessions.delete_one({"id": sess_id})
