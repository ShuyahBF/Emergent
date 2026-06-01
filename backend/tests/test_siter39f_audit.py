"""S029 — Audit journal for download-approval requests (admin-only)."""
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


def test_audit_endpoint_returns_counters_and_items(admin_h, db_sync):
    """Insert 3 sample approval rows in different statuses, then call the
    audit endpoint and assert filters + counters work."""
    sentinel = f"s029-{uuid.uuid4().hex[:6]}"
    inserted = []
    try:
        # Seed: 1 pending, 1 approved, 1 denied — all carrying the sentinel
        now = datetime.now(timezone.utc).isoformat()
        for st in ("pending", "approved", "denied"):
            t = uuid.uuid4().hex
            db_sync.download_approvals.insert_one({
                "id": t, "token": t,
                "requester_id": "test-user",
                "requester_email": f"{sentinel}-{st}@example.com",
                "requester_name": f"{sentinel} {st}",
                "resource_label": f"Test doc {sentinel}",
                "resource_url": "https://example.com/x.pdf",
                "status": st,
                "created_at": now,
                "decided_at": now if st != "pending" else None,
                "decided_via": "magic_link" if st != "pending" else None,
                "decided_by_phone": "+22500000001" if st != "pending" else None,
                "wa_send_status": "text_sent",
            })
            inserted.append(t)

        # 1) Default (all) — counters expose all 5 statuses
        r = requests.get(f"{API}/me/download-requests/admin/audit", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "items" in payload and "counters" in payload
        for k in ("pending", "approved", "denied", "expired", "cancelled"):
            assert k in payload["counters"]

        # Our 3 seeded rows must be in the items list
        labels = [it["resource_label"] for it in payload["items"]]
        assert any(sentinel in (lbl or "") for lbl in labels)

        # 2) status=approved filter — items should contain only approved
        r = requests.get(f"{API}/me/download-requests/admin/audit", headers=admin_h, params={"status": "approved"}, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(it["status"] == "approved" for it in items)

        # 3) free-text q matches sentinel
        r = requests.get(f"{API}/me/download-requests/admin/audit", headers=admin_h, params={"q": sentinel}, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 3
        assert {it["status"] for it in items} == {"pending", "approved", "denied"}

        # 4) Invalid status returns 400
        r = requests.get(f"{API}/me/download-requests/admin/audit", headers=admin_h, params={"status": "haxxor"}, timeout=30)
        assert r.status_code == 400
    finally:
        if inserted:
            db_sync.download_approvals.delete_many({"id": {"$in": inserted}})


def test_audit_endpoint_blocks_non_admin(db_sync):
    tenant_id = str(uuid.uuid4())
    mod_id = str(uuid.uuid4())
    mod_email = f"audit-mod-{uuid.uuid4().hex[:6]}@example.com"
    mod_password = "AuditModBlocked!2026"
    try:
        from auth import hash_password
        db_sync.users.insert_one({
            "id": tenant_id, "email": f"t-{uuid.uuid4().hex[:6]}@example.com",
            "full_name": "Tenant", "password_hash": "x", "role": "client",
            "account_status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db_sync.users.insert_one({
            "id": mod_id, "email": mod_email, "full_name": "Mod",
            "password_hash": hash_password(mod_password),
            "role": "client", "tracked_role": "Moderation",
            "parent_client_id": tenant_id, "client_id": tenant_id,
            "account_status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db_sync.tracked_users.insert_one({
            "id": str(uuid.uuid4()), "client_id": tenant_id, "email": mod_email,
            "name": "Mod", "role": "Moderation", "status": "active", "user_id": mod_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        tok = _login(mod_email, mod_password)
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.get(f"{API}/me/download-requests/admin/audit", headers=h, timeout=30)
        assert r.status_code == 403, r.text
    finally:
        db_sync.users.delete_many({"id": {"$in": [tenant_id, mod_id]}})
        db_sync.tracked_users.delete_many({"user_id": mod_id})
