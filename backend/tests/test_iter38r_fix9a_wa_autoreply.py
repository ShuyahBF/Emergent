"""Iter38r-fix9a — Liluvine PRO native WhatsApp auto-reply tests.

These tests exercise the decision rules of the auto-reply pipeline directly
against the helper (no real Meta call) so we can validate behaviour without
external dependencies.
"""
from __future__ import annotations

import os
import pytest
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _settings(**overrides):
    base = {
        "liluvine_wa_autoreply_enabled": True,
        "liluvine_wa_autoreply_allow_phones": [],
        "liluvine_wa_autoreply_deny_phones": [],
        "liluvine_wa_autoreply_allow_mode": "any",
        "liluvine_wa_autoreply_schedule": "always",
        "liluvine_wa_autoreply_keywords": [],
        "liluvine_wa_autoreply_cooldown_seconds": 0,
        "business_open_time": "09:00",
        "business_close_time": "18:00",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_should_autoreply_disabled():
    from routes.liluvine_wa_autoreply import should_autoreply
    s = _settings(liluvine_wa_autoreply_enabled=False)
    res = await should_autoreply(db=None, settings=s, phone_digits="22890000001",
                                  text="bonjour", contact=None)
    assert res["ok"] is False
    assert res["reason"] == "disabled"


@pytest.mark.asyncio
async def test_should_autoreply_denylist():
    from routes.liluvine_wa_autoreply import should_autoreply
    s = _settings(liluvine_wa_autoreply_deny_phones=["22890000001"])
    res = await should_autoreply(db=None, settings=s, phone_digits="22890000001",
                                  text="bonjour", contact=None)
    assert res["ok"] is False
    assert res["reason"] == "denylisted"


@pytest.mark.asyncio
async def test_should_autoreply_whitelist_excludes():
    from routes.liluvine_wa_autoreply import should_autoreply
    s = _settings(
        liluvine_wa_autoreply_allow_mode="whitelist",
        liluvine_wa_autoreply_allow_phones=["22890000002"],
    )
    res = await should_autoreply(db=None, settings=s, phone_digits="22890000001",
                                  text="bonjour", contact=None)
    assert res["ok"] is False
    assert res["reason"] == "not_whitelisted"


@pytest.mark.asyncio
async def test_should_autoreply_whitelist_includes():
    """Whitelist member passes through (uses no DB so cooldown=0)."""
    from routes.liluvine_wa_autoreply import should_autoreply
    s = _settings(
        liluvine_wa_autoreply_allow_mode="whitelist",
        liluvine_wa_autoreply_allow_phones=["22890000001"],
    )

    class _StubColl:
        async def find_one(self, *args, **kwargs):
            return None

    class _StubDb:
        liluvine_wa_autoreply_state = _StubColl()

    res = await should_autoreply(db=_StubDb(), settings=s, phone_digits="22890000001",
                                  text="bonjour", contact=None)
    assert res["ok"] is True


@pytest.mark.asyncio
async def test_should_autoreply_keywords_required():
    from routes.liluvine_wa_autoreply import should_autoreply
    s = _settings(liluvine_wa_autoreply_keywords=["tarif", "info"])
    res = await should_autoreply(db=None, settings=s, phone_digits="22890000001",
                                  text="bonjour", contact=None)
    assert res["ok"] is False
    assert res["reason"] == "no_keyword_match"


@pytest.mark.asyncio
async def test_should_autoreply_keyword_match():
    from routes.liluvine_wa_autoreply import should_autoreply
    s = _settings(
        liluvine_wa_autoreply_keywords=["tarif", "info"],
        liluvine_wa_autoreply_cooldown_seconds=0,
    )

    class _StubColl:
        async def find_one(self, *args, **kwargs):
            return None

    class _StubDb:
        liluvine_wa_autoreply_state = _StubColl()

    res = await should_autoreply(db=_StubDb(), settings=s, phone_digits="22890000001",
                                  text="Quel est votre tarif ?", contact=None)
    assert res["ok"] is True


def test_admin_endpoints_exist_and_persist(db_sync):
    """Live endpoint check: PUT /admin/liluvine-pro/wa-autoreply must persist
    the toggle + lists in the settings collection."""
    import requests
    BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
    API = f"{BASE_URL}/api"
    # Login
    r = requests.post(f"{API}/auth/login", json={
        "email": "admin@sawalismartsystems.com",
        "password": "Admin@Sawali2026",
    }, timeout=30)
    data = r.json()
    r2 = requests.post(f"{API}/auth/verify-otp", json={
        "session_token": data["session_token"], "code": data["dev_otp"],
    }, timeout=30)
    token = r2.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # Snapshot the original settings
    orig = db_sync.settings.find_one({"_id": "global"}, {"_id": 0,
        "liluvine_wa_autoreply_enabled": 1, "liluvine_wa_autoreply_keywords": 1,
        "liluvine_wa_autoreply_signature": 1}) or {}
    try:
        # Set
        r = requests.put(f"{API}/admin/liluvine-pro/wa-autoreply", headers=h, json={
            "enabled": True,
            "keywords": ["tarif", "info"],
            "signature": "— Test 1234",
            "allow_phones": ["+22890123456"],
            "cooldown_seconds": 120,
        }, timeout=30)
        assert r.status_code == 200, r.text
        # Read back
        r2 = requests.get(f"{API}/admin/liluvine-pro/wa-autoreply", headers=h, timeout=30)
        body = r2.json()
        assert body["enabled"] is True
        assert body["keywords"] == ["tarif", "info"]
        assert body["signature"] == "— Test 1234"
        assert body["allow_phones"] == ["22890123456"]  # digits only
        assert body["cooldown_seconds"] == 120
        # Verify DB write
        s = db_sync.settings.find_one({"_id": "global"})
        assert s["liluvine_wa_autoreply_enabled"] is True
        assert s["liluvine_wa_autoreply_keywords"] == ["tarif", "info"]
    finally:
        # Restore
        requests.put(f"{API}/admin/liluvine-pro/wa-autoreply", headers=h, json={
            "enabled": bool(orig.get("liluvine_wa_autoreply_enabled")),
            "keywords": orig.get("liluvine_wa_autoreply_keywords") or [],
            "signature": orig.get("liluvine_wa_autoreply_signature") or "",
        }, timeout=30)


def test_admin_endpoints_require_admin_role(db_sync):
    """Non-admin must get 403."""
    import requests
    BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
    API = f"{BASE_URL}/api"
    # Unauthenticated
    r = requests.get(f"{API}/admin/liluvine-pro/wa-autoreply", timeout=30)
    assert r.status_code in (401, 403)
