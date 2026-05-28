"""Iter38r-fix5 — AI Quotas backend tests."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
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


@pytest.fixture
def env(db):
    admin_id = f"fix5_adm_{uuid.uuid4().hex[:6]}"
    tracked_id = f"fix5_tr_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin FX5", "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": tracked_id, "email": f"{tracked_id}@t.l", "password_hash": "x",
         "full_name": "Tracked FX5", "role": "client",
         "tracked_user_id": admin_id, "tracked_role": "Comptable",
         "client_id": admin_id, "account_status": "active",
         "created_at": now},
    ])
    yield {
        "admin_id": admin_id,
        "tracked_id": tracked_id,
        "admin_token": _forge(admin_id, "admin"),
        "tracked_token": _forge(tracked_id, "client"),
    }
    db.users.delete_many({"id": {"$in": [admin_id, tracked_id]}})
    db.ai_quotas.delete_many({"client_id": admin_id})
    db.ai_usage_events.delete_many({"client_id": admin_id})
    db.ai_usage_monthly.delete_many({"client_id": admin_id})


def _h(tok): return {"Authorization": f"Bearer {tok}"}


# ====================================================================
# Config CRUD
# ====================================================================
def test_get_default_quota_off(env):
    r = requests.get(f"{API}/admin/clients/{env['admin_id']}/ai-quota", headers=_h(env["admin_token"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config"]["mode"] == "off"
    assert body["effective_costs_xof"]["image"] > 0
    assert body["defaults"]["video"] == 1500.0


def test_put_quota_config_persisted(env, db):
    r = requests.put(
        f"{API}/admin/clients/{env['admin_id']}/ai-quota",
        headers=_h(env["admin_token"]),
        json={
            "mode": "quota",
            "monthly_images": 10,
            "monthly_videos": 2,
            "alert_warn_pct": 75,
        },
    )
    assert r.status_code == 200, r.text
    cfg = r.json()["config"]
    assert cfg["mode"] == "quota"
    assert cfg["monthly_images"] == 10
    # Re-fetch
    r2 = requests.get(f"{API}/admin/clients/{env['admin_id']}/ai-quota", headers=_h(env["admin_token"]))
    assert r2.json()["config"]["monthly_videos"] == 2


def test_put_quota_budget_mode(env):
    r = requests.put(
        f"{API}/admin/clients/{env['admin_id']}/ai-quota",
        headers=_h(env["admin_token"]),
        json={"mode": "budget", "monthly_budget_xof": 5000, "alert_warn_pct": 90},
    )
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["mode"] == "budget"
    assert cfg["monthly_budget_xof"] == 5000


# ====================================================================
# Tracking
# ====================================================================
@pytest.mark.asyncio
async def test_track_usage_increments_rollup(env, db):
    # Force-set a quota config
    db.ai_quotas.replace_one(
        {"client_id": env["admin_id"]},
        {"client_id": env["admin_id"], "mode": "off"},
        upsert=True,
    )
    from motor.motor_asyncio import AsyncIOMotorClient
    import sys
    sys.path.insert(0, "/app/backend")
    from routes.ai_quotas import track_ai_usage
    motor_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    user = await motor_db.users.find_one({"id": env["tracked_id"]}, {"_id": 0})
    res = await track_ai_usage(motor_db, user=user, resource="image", units=1, model="gemini")
    assert res["allowed"] is True
    assert res["cost_xof"] == 25.0  # default image cost
    # Check rollup
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    rollup = await motor_db.ai_usage_monthly.find_one({"_id": f"{env['admin_id']}:{ym}"}, {"_id": 0})
    assert rollup["images"] == 1
    assert rollup["total_xof"] == 25.0
    # Event was logged
    cnt = await motor_db.ai_usage_events.count_documents({"client_id": env["admin_id"], "user_id": env["tracked_id"]})
    assert cnt == 1


@pytest.mark.asyncio
async def test_quota_blocks_when_cap_reached(env, db):
    db.ai_quotas.replace_one(
        {"client_id": env["admin_id"]},
        {"client_id": env["admin_id"], "mode": "quota", "monthly_images": 2,
         "block_on_limit": True, "alert_warn_pct": 80},
        upsert=True,
    )
    db.ai_usage_monthly.delete_many({"client_id": env["admin_id"]})
    db.ai_usage_events.delete_many({"client_id": env["admin_id"]})
    # Use a fresh motor client per test to avoid event-loop reuse from server.db
    from motor.motor_asyncio import AsyncIOMotorClient
    import sys
    sys.path.insert(0, "/app/backend")
    from routes.ai_quotas import track_ai_usage
    motor_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    user = await motor_db.users.find_one({"id": env["tracked_id"]}, {"_id": 0})
    r1 = await track_ai_usage(motor_db, user=user, resource="image", units=1, model="gemini")
    r2 = await track_ai_usage(motor_db, user=user, resource="image", units=1, model="gemini")
    assert r1["allowed"] and r2["allowed"]
    r3 = await track_ai_usage(motor_db, user=user, resource="image", units=1, model="gemini")
    assert r3["allowed"] is False
    assert "Quota" in r3["reason"]


@pytest.mark.asyncio
async def test_budget_mode_blocks_correctly(env, db):
    db.ai_quotas.replace_one(
        {"client_id": env["admin_id"]},
        {"client_id": env["admin_id"], "mode": "budget", "monthly_budget_xof": 60,
         "block_on_limit": True, "alert_warn_pct": 50},
        upsert=True,
    )
    db.ai_usage_monthly.delete_many({"client_id": env["admin_id"]})
    db.ai_usage_events.delete_many({"client_id": env["admin_id"]})
    from motor.motor_asyncio import AsyncIOMotorClient
    import sys
    sys.path.insert(0, "/app/backend")
    from routes.ai_quotas import track_ai_usage
    motor_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    user = await motor_db.users.find_one({"id": env["tracked_id"]}, {"_id": 0})
    await track_ai_usage(motor_db, user=user, resource="image", units=1, model="gemini")
    await track_ai_usage(motor_db, user=user, resource="image", units=1, model="gemini")
    r3 = await track_ai_usage(motor_db, user=user, resource="image", units=1, model="gemini")
    assert r3["allowed"] is False
    assert "Budget" in r3["reason"]


# ====================================================================
# Usage breakdown + exports
# ====================================================================
def test_usage_endpoint_returns_breakdown(env, db):
    # Seed some events
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    db.ai_usage_events.insert_many([
        {"id": uuid.uuid4().hex, "client_id": env["admin_id"], "user_id": env["tracked_id"],
         "user_label": "Tracked FX5", "tracked_role": "Comptable",
         "resource": "image", "units": 3, "base": "images", "cost_xof": 75,
         "model": "gemini", "year_month": ym, "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": uuid.uuid4().hex, "client_id": env["admin_id"], "user_id": env["tracked_id"],
         "user_label": "Tracked FX5", "tracked_role": "Comptable",
         "resource": "video", "units": 1, "base": "vidéos", "cost_xof": 1500,
         "model": "sora-2", "year_month": ym, "created_at": datetime.now(timezone.utc).isoformat()},
    ])
    db.ai_usage_monthly.replace_one(
        {"_id": f"{env['admin_id']}:{ym}"},
        {"_id": f"{env['admin_id']}:{ym}", "client_id": env["admin_id"], "year_month": ym,
         "images": 3, "videos": 1, "transcription_minutes": 0, "chat_tokens": 0, "total_xof": 1575},
        upsert=True,
    )
    r = requests.get(f"{API}/admin/clients/{env['admin_id']}/ai-usage", headers=_h(env["admin_token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["rollup"]["images"] == 3
    assert body["rollup"]["videos"] == 1
    assert len(body["per_user"]) == 1
    assert body["per_user"][0]["user_id"] == env["tracked_id"]


def test_csv_export(env, db):
    r = requests.get(
        f"{API}/admin/clients/{env['admin_id']}/ai-usage/export.csv",
        headers=_h(env["admin_token"]),
    )
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "Date/Heure" in r.text
    assert "Utilisateur Suivi" in r.text


def test_csv_export_includes_total(env, db):
    r = requests.get(
        f"{API}/admin/clients/{env['admin_id']}/ai-usage/export.csv",
        headers=_h(env["admin_token"]),
    )
    assert r.status_code == 200
    assert "TOTAL" in r.text


def test_me_ai_usage_returns_status(env):
    r = requests.get(f"{API}/me/ai-usage", headers=_h(env["tracked_token"]))
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "mode" in body["status"]


def test_me_ai_usage_resolves_to_parent_admin(env, db):
    r = requests.get(f"{API}/me/ai-usage", headers=_h(env["tracked_token"]))
    assert r.json()["client_id"] == env["admin_id"]


def test_admin_only_endpoints(env, db):
    # Tracked user cannot access admin endpoint
    r = requests.get(
        f"{API}/admin/clients/{env['admin_id']}/ai-quota",
        headers=_h(env["tracked_token"]),
    )
    assert r.status_code in (401, 403)
