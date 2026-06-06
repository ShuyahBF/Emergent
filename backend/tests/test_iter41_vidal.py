"""Iter41 (2026-02) — VIDAL module tests.

Validates :
 - Admin can GET/PUT /admin/vidal/config (mask + persistence)
 - Non-admin gets 403
 - GET /vidal/quota/me returns the per-user counter
 - GET /vidal/search returns 503 when disabled and 503 when no credentials
 - Mode switch (test/production) selects the correct base url / app_id / app_key
 - Cache helper hits and respects TTL
 - Quota enforcement returns 429 above the configured ceiling
 - VIDAL secret fields are MASKED in GET /admin/settings
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
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


@pytest.fixture(scope="module")
def amotor():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    aid = f"vidal_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "admin"), aid
    db.users.delete_one({"id": aid})


@pytest.fixture(scope="module")
def client_token(db):
    uid = f"vidal_cli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(uid, "client"), uid
    db.users.delete_one({"id": uid})


def test_admin_can_set_and_get_vidal_config(db, admin_token):
    token, _ = admin_token
    payload = {
        "enabled": True,
        "mode": "test",
        "test_base_url": "https://api-test.vidal.net/rest/api",
        "test_app_id": "demo_app_id_test",
        "test_app_key": "demo_secret_key_test",
        "prod_base_url": "https://api.vidal.net/rest/api",
        "prod_app_id": "demo_app_id_prod",
        "prod_app_key": "demo_secret_key_prod",
        "cache_ttl_hours": 24,
        "quota_per_user_per_day": 100,
        "http_timeout": 10,
    }
    r = requests.put(f"{API}/admin/vidal/config", json=payload,
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text

    # GET masks the keys but echoes the rest
    r2 = requests.get(f"{API}/admin/vidal/config",
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r2.status_code == 200
    body = r2.json()
    assert body["enabled"] is True
    assert body["mode"] == "test"
    assert body["test_app_id"] == "demo_app_id_test"
    assert body["test_app_key"] == "********"
    assert body["prod_app_key"] == "********"
    assert body["cache_ttl_hours"] == 24
    assert body["quota_per_user_per_day"] == 100

    # DB persistence (sensitive fields stored raw, masked only on the wire)
    s = db.settings.find_one({"_id": "global"})
    assert s["vidal_test_app_key"] == "demo_secret_key_test"
    assert s["vidal_prod_app_id"] == "demo_app_id_prod"


def test_client_cannot_access_admin_config(client_token):
    token, _ = client_token
    r = requests.get(f"{API}/admin/vidal/config",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code in (401, 403), r.text


def test_quota_me_returns_counter(client_token):
    token, _ = client_token
    r = requests.get(f"{API}/vidal/quota/me",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "used" in body and "limit" in body and "mode" in body


def test_search_blocked_when_disabled(db, admin_token):
    """Disabling VIDAL should make every endpoint return 503 (admin bypasses tenant gate)."""
    atoken, aid = admin_token
    requests.put(f"{API}/admin/vidal/config", json={"enabled": False},
                 headers={"Authorization": f"Bearer {atoken}"}, timeout=10)
    # Admin bypasses the tenant gate so we hit the global enabled check (503)
    r = requests.get(f"{API}/vidal/search?q=doliprane&filter=product",
                     headers={"Authorization": f"Bearer {atoken}"}, timeout=10)
    assert r.status_code == 503
    assert "VIDAL" in r.json()["detail"]
    requests.put(f"{API}/admin/vidal/config", json={"enabled": True},
                 headers={"Authorization": f"Bearer {atoken}"}, timeout=10)


def test_search_blocked_when_credentials_missing(db, admin_token):
    """Wipe app_id/app_key for the active mode → expect 503 with credential error."""
    atoken, _ = admin_token
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"vidal_test_app_id": "", "vidal_test_app_key": "", "vidal_mode": "test"}},
    )
    # Admin bypasses tenant gate to test the credentials check
    r = requests.get(f"{API}/vidal/search?q=doliprane&filter=product",
                     headers={"Authorization": f"Bearer {atoken}"}, timeout=10)
    assert r.status_code == 503
    assert "Identifiants VIDAL" in r.json()["detail"]
    requests.put(f"{API}/admin/vidal/config", json={
        "test_app_id": "demo_app_id_test", "test_app_key": "demo_secret_key_test",
    }, headers={"Authorization": f"Bearer {atoken}"}, timeout=10)


def test_mode_switch_changes_active_credentials(db, admin_token):
    """Switching `vidal_mode` flips which app_id/app_key are loaded."""
    atoken, _ = admin_token
    requests.put(f"{API}/admin/vidal/config", json={
        "test_app_id": "demo_app_id_test",
        "test_app_key": "demo_secret_key_test",
        "prod_app_id": "demo_app_id_prod",
        "prod_app_key": "demo_secret_key_prod",
        "mode": "production",
    }, headers={"Authorization": f"Bearer {atoken}"}, timeout=10)

    from routes.vidal import _load_config

    async def _run_prod():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            return await _load_config(client[os.environ["DB_NAME"]])
        finally:
            client.close()

    cfg = asyncio.run(_run_prod())
    assert cfg["mode"] == "production"
    assert cfg["app_id"] == "demo_app_id_prod"
    assert cfg["app_key"] == "demo_secret_key_prod"
    assert "vidal.net" in cfg["base_url"]

    requests.put(f"{API}/admin/vidal/config", json={"mode": "test"},
                 headers={"Authorization": f"Bearer {atoken}"}, timeout=10)

    async def _run_test():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            return await _load_config(client[os.environ["DB_NAME"]])
        finally:
            client.close()

    cfg2 = asyncio.run(_run_test())
    assert cfg2["mode"] == "test"
    assert cfg2["app_id"] == "demo_app_id_test"


def test_cache_get_set_respects_ttl():
    from routes.vidal import _cache_get, _cache_set, _cache_key

    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            adb = client[os.environ["DB_NAME"]]
            key = _cache_key("test", "GET", "/products", {"q": "test"})
            await adb.vidal_cache.delete_one({"_id": key})
            await _cache_set(adb, key, {"hello": "world"})
            got = await _cache_get(adb, key, ttl_hours=24)
            assert got == {"hello": "world"}
            none = await _cache_get(adb, key, ttl_hours=0)
            assert none is None
            await adb.vidal_cache.delete_one({"_id": key})
        finally:
            client.close()

    asyncio.run(run())


def test_quota_enforcement_returns_429(db, admin_token, client_token):
    """Set quota to 1, then expect 429 from the helper above the ceiling."""
    atoken, _ = admin_token
    ctoken, cid = client_token
    requests.put(f"{API}/admin/vidal/config", json={
        "quota_per_user_per_day": 1, "test_app_id": "x", "test_app_key": "y",
    }, headers={"Authorization": f"Bearer {atoken}"}, timeout=10)

    today = datetime.now(timezone.utc).date().isoformat()
    db.vidal_usage_daily.delete_many({"user_id": cid, "day": today})
    db.vidal_usage_daily.insert_one({"user_id": cid, "day": today, "count": 1,
                                     "updated_at": datetime.now(timezone.utc)})

    r = requests.get(f"{API}/vidal/quota/me",
                     headers={"Authorization": f"Bearer {ctoken}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 1
    assert body["used"] >= 1

    from routes.vidal import _quota_check_and_increment, _load_config
    from fastapi import HTTPException

    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            adb = client[os.environ["DB_NAME"]]
            cfg = await _load_config(adb)
            await _quota_check_and_increment(adb, cid, cfg)
        finally:
            client.close()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == 429

    requests.put(f"{API}/admin/vidal/config", json={"quota_per_user_per_day": 200},
                 headers={"Authorization": f"Bearer {atoken}"}, timeout=10)
    db.vidal_usage_daily.delete_many({"user_id": cid})


def test_get_admin_settings_masks_vidal_keys(db, admin_token):
    """GET /admin/settings must mask vidal_test_app_key and vidal_prod_app_key."""
    atoken, _ = admin_token
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "vidal_test_app_key": "supersecretTEST",
            "vidal_prod_app_key": "supersecretPROD",
        }},
    )
    r = requests.get(f"{API}/admin/settings",
                     headers={"Authorization": f"Bearer {atoken}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("vidal_test_app_key") == "********"
    assert body.get("vidal_prod_app_key") == "********"
