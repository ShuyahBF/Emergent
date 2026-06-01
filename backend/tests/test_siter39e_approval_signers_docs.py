"""S-iter39e — S025 download approval + S026 signers notification + admin docs."""
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


# --------------------------------------------------------------
# S025 — Download approval workflow
# --------------------------------------------------------------
def test_admin_bypasses_approval(admin_h, db_sync):
    """Admins/Superviseurs bypass the gate and get direct=true immediately."""
    r = requests.post(f"{API}/me/download-requests", headers=admin_h, json={
        "resource_label": "Test admin bypass",
        "resource_url": "https://example.com/file.pdf",
    }, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["direct"] is True


def test_non_admin_workflow_pending_then_magic_link_approve(db_sync):
    """A non-admin user creates a request → pending status, then the
    public magic-link approves it → next poll returns 'approved'."""
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    email = f"u-{uuid.uuid4().hex[:8]}@example.com"
    password = "MagicLinkTest!2026"

    # Configure global settings for download approval (no template → fallback text)
    db_sync.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "download_approval_enabled": True,
            "download_approval_whatsapp": "+22500000000",
            "download_pending_message": "TEST — En attente...",
        }},
        upsert=True,
    )

    try:
        from auth import hash_password
        db_sync.users.insert_one({
            "id": tenant_id,
            "email": f"t-{uuid.uuid4().hex[:6]}@example.com",
            "full_name": "Tenant",
            "password_hash": "x",
            "role": "client",
            "account_status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db_sync.users.insert_one({
            "id": user_id,
            "email": email,
            "full_name": "Joe Tester",
            "password_hash": hash_password(password),
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
            "email": email,
            "name": "Joe Tester",
            "role": "Moderation",
            "status": "active",
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        tok = _login(email, password)
        h = {"Authorization": f"Bearer {tok}"}

        # 1) Create request — must return pending + token
        r = requests.post(f"{API}/me/download-requests", headers=h, json={
            "resource_label": "Confidential file",
            "resource_url": "https://example.com/file.pdf",
        }, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        token = body["token"]
        assert token and len(token) >= 6
        assert body["status"] == "pending"
        assert body["pending_message"] == "TEST — En attente..."

        # 2) Poll status — pending
        r = requests.get(f"{API}/me/download-requests/{token}", headers=h, timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

        # 3) Approve via magic link (public endpoint, no auth)
        r = requests.get(f"{API}/wa-action/{token}/approve", timeout=30, allow_redirects=False)
        assert r.status_code == 200, r.text

        # 4) Poll again — approved
        r = requests.get(f"{API}/me/download-requests/{token}", headers=h, timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

        # 5) Deny path with a SECOND request
        r = requests.post(f"{API}/me/download-requests", headers=h, json={
            "resource_label": "Another file",
            "resource_url": "https://example.com/file2.pdf",
        }, timeout=30)
        token2 = r.json()["token"]
        requests.get(f"{API}/wa-action/{token2}/deny", timeout=30, allow_redirects=False)
        r = requests.get(f"{API}/me/download-requests/{token2}", headers=h, timeout=30)
        assert r.json()["status"] == "denied"

        # 6) Cancel from requester
        r = requests.post(f"{API}/me/download-requests", headers=h, json={
            "resource_label": "Cancel test",
            "resource_url": "https://example.com/file3.pdf",
        }, timeout=30)
        token3 = r.json()["token"]
        r = requests.post(f"{API}/me/download-requests/{token3}/cancel", headers=h, timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
    finally:
        db_sync.users.delete_many({"id": {"$in": [tenant_id, user_id]}})
        db_sync.tracked_users.delete_many({"user_id": user_id})
        db_sync.download_approvals.delete_many({"requester_id": user_id})
        db_sync.settings.update_one(
            {"_id": "global"},
            {"$unset": {
                "download_approval_enabled": "",
                "download_approval_whatsapp": "",
                "download_pending_message": "",
            }},
        )


def test_settings_validation_signers_channel(admin_h):
    """meeting_signers_notify_channel only accepts none|email|wa|both."""
    r = requests.put(f"{API}/admin/settings", headers=admin_h, json={"meeting_signers_notify_channel": "smoke"}, timeout=30)
    assert r.status_code == 400, r.text
    for ch in ("none", "email", "wa", "both"):
        r = requests.put(f"{API}/admin/settings", headers=admin_h, json={"meeting_signers_notify_channel": ch}, timeout=30)
        assert r.status_code == 200, r.text


def test_public_docs_includes_admin_settings_reference():
    r = requests.get(f"{API}/public/docs", timeout=30)
    assert r.status_code == 200
    slugs = [d["slug"] for d in r.json()["items"]]
    assert "admin-settings-reference" in slugs
    # Download works
    r = requests.get(f"{API}/public/docs/admin-settings-reference", timeout=30)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
