"""S031 — LLM health monitoring & budget-exceeded detection."""
from __future__ import annotations

import os
import uuid
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


def test_budget_regex_parses_actual_emergent_error():
    """Make sure the regex in routes/llm_health.py extracts the cost
    figures from the EXACT error string returned by Emergent's LLM proxy
    when the budget is exhausted."""
    from routes.llm_health import BUDGET_ERROR_RE
    samples = [
        "ChatError('Failed to generate chat completion: litellm.BadRequestError: OpenAIException - Budget has been exceeded! Current cost: 3.0010292500920266, Max budget: 3.0')",
        "Budget has been exceeded! Current cost: 5.4, Max budget: 5.0",
        "litellm.BadRequestError: budget exceeded current cost: 1.23, max budget: 1.0",
    ]
    for s in samples:
        m = BUDGET_ERROR_RE.search(s)
        assert m, f"regex failed on: {s!r}"
        cost = float(m.group(1))
        maxb = float(m.group(2))
        assert cost >= 0 and maxb > 0
        assert cost >= maxb  # budget exceeded means cost >= max


def test_admin_can_read_llm_health(admin_h):
    """GET /admin/llm-health returns the current state for admin/sup."""
    r = requests.get(f"{API}/admin/llm-health", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "status" in body
    # super admin flag must be True for the seed admin
    assert body.get("is_super_admin") is True


def test_non_admin_blocked(db_sync):
    """A tracked Moderation user must NOT be able to read /admin/llm-health."""
    from datetime import datetime, timezone
    tenant_id = str(uuid.uuid4())
    mod_id = str(uuid.uuid4())
    mod_email = f"healthmod-{uuid.uuid4().hex[:6]}@example.com"
    mod_password = "HealthMod!2026"
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
        r = requests.get(f"{API}/admin/llm-health", headers=h, timeout=30)
        assert r.status_code == 403, r.text
    finally:
        db_sync.users.delete_many({"id": {"$in": [tenant_id, mod_id]}})
        db_sync.tracked_users.delete_many({"user_id": mod_id})


def test_record_outcome_updates_state(admin_h, db_sync):
    """record_llm_outcome must persist status transitions properly."""
    import asyncio
    from routes.llm_health import record_llm_outcome
    from motor.motor_asyncio import AsyncIOMotorClient
    async def _run():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        # Simulate a budget-exceeded outcome
        await record_llm_outcome(async_db, ok=False, error="Budget has been exceeded! Current cost: 3.5, Max budget: 3.0")
        s = await async_db.llm_health_state.find_one({"_id": "current"})
        assert s["status"] == "budget_exceeded"
        assert abs(s.get("current_cost", 0) - 3.5) < 0.01
        assert abs(s.get("max_budget", 0) - 3.0) < 0.01
        # Now a success
        await record_llm_outcome(async_db, ok=True)
        s = await async_db.llm_health_state.find_one({"_id": "current"})
        assert s["status"] == "ok"
    asyncio.get_event_loop().run_until_complete(_run()) if asyncio._get_running_loop() is None else asyncio.run(_run())


def test_ping_endpoint_responds(admin_h):
    """POST /admin/llm-health/ping must return a state object (status depends
    on whether the Universal Key is currently funded — both ok and
    budget_exceeded are acceptable)."""
    r = requests.post(f"{API}/admin/llm-health/ping", headers=admin_h, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") in ("ok", "budget_exceeded", "key_missing", "unknown_error")
    assert body.get("is_super_admin") is True
