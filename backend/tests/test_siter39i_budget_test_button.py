"""S033 — Manual budget test button + WhatsApp keyword query."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
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


def _run(coro):
    try:
        return asyncio.get_event_loop().run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def test_test_summary_endpoint_returns_summary_text(admin_h):
    """POST /admin/llm-health/test-summary must include `summary_text`
    (the WA-formatted block) on top of the full S032 metrics."""
    r = requests.post(f"{API}/admin/llm-health/test-summary", headers=admin_h, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "summary_text" in body, body
    assert "Universal Key" in body["summary_text"]
    assert "USD" in body["summary_text"]
    assert "Add Balance" in body["summary_text"]
    # Standard S032 metrics still present
    assert "status_level" in body
    assert "pct_used" in body


def test_test_summary_blocked_for_non_admin(db_sync):
    """Tracked Moderation user must NOT be able to call /test-summary."""
    from datetime import datetime, timezone
    tenant_id = str(uuid.uuid4())
    mod_id = str(uuid.uuid4())
    mod_email = f"testsum-{uuid.uuid4().hex[:6]}@example.com"
    mod_password = "TestSum!2026"
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
        r = requests.post(f"{API}/admin/llm-health/test-summary", headers=h, timeout=30)
        assert r.status_code == 403, r.text
    finally:
        db_sync.users.delete_many({"id": {"$in": [tenant_id, mod_id]}})
        db_sync.tracked_users.delete_many({"user_id": mod_id})


def test_handle_wa_budget_query_authorized():
    """When the keyword + authorized phone match, the WA sender must be
    invoked and the helper must return True (caller skips persisting)."""
    from routes.llm_health import handle_wa_budget_query

    async def go():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "llm_budget_wa_query_enabled": True,
                "llm_budget_wa_query_keyword": "SOLDE",
                "llm_budget_notify_wa_phone": "+22501020304",
            }}, upsert=True,
        )
        sent = []

        async def fake_wa(to, text):
            sent.append({"to": to, "text": text})
            return {"ok": True}

        # Exact match, last 10 digits aligned
        ok = await handle_wa_budget_query(
            async_db, text="solde", from_digits="22501020304", send_wa=fake_wa,
        )
        assert ok is True
        assert len(sent) == 1
        assert "Universal Key" in sent[0]["text"]
        # Cleanup
        await async_db.settings.update_one(
            {"_id": "global"}, {"$set": {"llm_budget_wa_query_enabled": False}},
        )

    _run(go())


def test_handle_wa_budget_query_disabled_returns_false():
    """When the toggle is disabled, the helper must return False even if
    the keyword/phone match."""
    from routes.llm_health import handle_wa_budget_query

    async def go():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "llm_budget_wa_query_enabled": False,
                "llm_budget_wa_query_keyword": "SOLDE",
                "llm_budget_notify_wa_phone": "+22501020304",
            }}, upsert=True,
        )
        sent = []

        async def fake_wa(to, text):
            sent.append(text)
            return {"ok": True}

        ok = await handle_wa_budget_query(
            async_db, text="SOLDE", from_digits="22501020304", send_wa=fake_wa,
        )
        assert ok is False
        assert sent == []

    _run(go())


def test_handle_wa_budget_query_unauthorized_phone():
    """Even with the right keyword, an unauthorized phone must NOT trigger
    a reply."""
    from routes.llm_health import handle_wa_budget_query

    async def go():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "llm_budget_wa_query_enabled": True,
                "llm_budget_wa_query_keyword": "SOLDE",
                "llm_budget_notify_wa_phone": "+22501020304",
            }}, upsert=True,
        )
        sent = []

        async def fake_wa(to, text):
            sent.append(text)
            return {"ok": True}

        ok = await handle_wa_budget_query(
            async_db, text="SOLDE", from_digits="22599887766", send_wa=fake_wa,
        )
        assert ok is False
        assert sent == []

        # Cleanup
        await async_db.settings.update_one(
            {"_id": "global"}, {"$set": {"llm_budget_wa_query_enabled": False}},
        )

    _run(go())


def test_keyword_setting_normalized_uppercase(admin_h):
    """PUT /admin/settings must uppercase the keyword and reject long ones."""
    # Lowercase → uppercased
    r = requests.put(f"{API}/admin/settings", headers=admin_h,
                     json={"llm_budget_wa_query_keyword": "  budget  "}, timeout=30)
    assert r.status_code == 200, r.text
    # Verify stored value
    r = requests.get(f"{API}/admin/settings", headers=admin_h, timeout=30).json()
    assert r.get("llm_budget_wa_query_keyword") == "BUDGET"

    # Too long → 400
    r = requests.put(f"{API}/admin/settings", headers=admin_h,
                     json={"llm_budget_wa_query_keyword": "X" * 33}, timeout=30)
    assert r.status_code == 400

    # Restore default
    requests.put(f"{API}/admin/settings", headers=admin_h,
                 json={"llm_budget_wa_query_keyword": "SOLDE", "llm_budget_wa_query_enabled": False}, timeout=30)
