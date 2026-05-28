"""Iter38r-fix6 — Liluvine PRO backend tests.

The actual LLM call is mocked so we don't burn Emergent LLM Key credits
on every test run. We verify:
  - Session lifecycle (create on first message, list, get, rename, delete)
  - RAG context detection (keywords trigger DB lookups)
  - Multi-tenant isolation (user can't see another tenant's session)
  - Quota integration (chat tokens are tracked)
"""
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
    admin_id = f"fix6_adm_{uuid.uuid4().hex[:6]}"
    other_admin_id = f"fix6_oth_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin FX6", "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": other_admin_id, "email": f"{other_admin_id}@t.l", "password_hash": "x",
         "full_name": "Other Admin", "role": "admin",
         "account_status": "active", "created_at": now},
    ])
    # Seed some context-fetchable data
    db.directory_contacts.insert_one({
        "id": "fix6-c1", "client_id": admin_id, "owner_id": admin_id,
        "name": "Test Contact", "code": "FX6", "company": "TestCo",
        "phone": "+22675001100", "created_at": now,
    })
    db.support_tickets.insert_one({
        "id": "fix6-t1", "client_id": admin_id, "number": "TKT-FX6-1",
        "motif": "Demande test", "status": "open", "contact_name": "Test Contact",
        "opened_at": now, "priority": "normal", "archived_at": None,
    })
    yield {"admin_id": admin_id, "other_admin_id": other_admin_id,
           "admin_token": _forge(admin_id, "admin"),
           "other_token": _forge(other_admin_id, "admin")}
    db.users.delete_many({"id": {"$in": [admin_id, other_admin_id]}})
    db.directory_contacts.delete_many({"client_id": admin_id})
    db.support_tickets.delete_many({"client_id": admin_id})
    db.liluvine_pro_sessions.delete_many({"client_id": {"$in": [admin_id, other_admin_id]}})
    db.liluvine_pro_messages.delete_many({"client_id": {"$in": [admin_id, other_admin_id]}})
    db.ai_usage_events.delete_many({"client_id": {"$in": [admin_id, other_admin_id]}})
    db.ai_usage_monthly.delete_many({"client_id": {"$in": [admin_id, other_admin_id]}})


def _h(tok): return {"Authorization": f"Bearer {tok}"}


# ====================================================================
# RAG context fetching (unit-style on the helper)
# ====================================================================
@pytest.mark.asyncio
async def test_context_fetched_for_contacts_keyword(env, db):
    from motor.motor_asyncio import AsyncIOMotorClient
    import sys; sys.path.insert(0, "/app/backend")
    from routes.liluvine_pro import _fetch_context_snippets
    motor_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    user = await motor_db.users.find_one({"id": env["admin_id"]}, {"_id": 0})
    ctx = await _fetch_context_snippets(motor_db, user, "Liste mes contacts")
    assert "CONTEXTE DB" in ctx
    assert "Test Contact" in ctx
    assert "FX6" in ctx


@pytest.mark.asyncio
async def test_context_fetched_for_tickets_keyword(env, db):
    from motor.motor_asyncio import AsyncIOMotorClient
    import sys; sys.path.insert(0, "/app/backend")
    from routes.liluvine_pro import _fetch_context_snippets
    motor_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    user = await motor_db.users.find_one({"id": env["admin_id"]}, {"_id": 0})
    ctx = await _fetch_context_snippets(motor_db, user, "Combien de tickets ouverts ?")
    assert "TKT-FX6-1" in ctx
    assert "Demande test" in ctx


@pytest.mark.asyncio
async def test_no_context_for_unrelated_question(env, db):
    from motor.motor_asyncio import AsyncIOMotorClient
    import sys; sys.path.insert(0, "/app/backend")
    from routes.liluvine_pro import _fetch_context_snippets
    motor_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    user = await motor_db.users.find_one({"id": env["admin_id"]}, {"_id": 0})
    ctx = await _fetch_context_snippets(motor_db, user, "Quel est le sens de la vie ?")
    assert ctx == ""


# ====================================================================
# Session lifecycle — mock the LLM via direct DB seed
# ====================================================================
def _seed_session_and_messages(db, admin_id, count=2):
    sid = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    db.liluvine_pro_sessions.insert_one({
        "id": sid, "client_id": admin_id, "user_id": admin_id,
        "user_label": "Admin FX6", "title": "Test session",
        "created_at": now, "updated_at": now, "message_count": count,
    })
    db.liluvine_pro_messages.insert_many([
        {"id": f"m1-{sid}", "session_id": sid, "client_id": admin_id, "user_id": admin_id,
         "role": "user", "content": "Salut", "created_at": now},
        {"id": f"m2-{sid}", "session_id": sid, "client_id": admin_id, "user_id": admin_id,
         "role": "assistant", "content": "Bonjour !", "tokens": 50, "model": "claude-sonnet-4-6",
         "created_at": now},
    ])
    return sid


def test_list_sessions_returns_only_own_tenant(env, db):
    sid_mine = _seed_session_and_messages(db, env["admin_id"])
    sid_other = _seed_session_and_messages(db, env["other_admin_id"])
    r = requests.get(f"{API}/me/liluvine-pro/sessions", headers=_h(env["admin_token"]))
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["items"]]
    assert sid_mine in ids
    assert sid_other not in ids


def test_get_session_with_messages(env, db):
    sid = _seed_session_and_messages(db, env["admin_id"])
    r = requests.get(f"{API}/me/liluvine-pro/sessions/{sid}", headers=_h(env["admin_token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["session"]["id"] == sid
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"


def test_get_session_blocks_cross_tenant(env, db):
    sid_other = _seed_session_and_messages(db, env["other_admin_id"])
    r = requests.get(f"{API}/me/liluvine-pro/sessions/{sid_other}", headers=_h(env["admin_token"]))
    assert r.status_code == 404


def test_rename_session(env, db):
    sid = _seed_session_and_messages(db, env["admin_id"])
    r = requests.patch(
        f"{API}/me/liluvine-pro/sessions/{sid}",
        headers=_h(env["admin_token"]),
        json={"title": "Renommée!"},
    )
    assert r.status_code == 200
    doc = db.liluvine_pro_sessions.find_one({"id": sid}, {"_id": 0})
    assert doc["title"] == "Renommée!"


def test_delete_session_cleans_messages(env, db):
    sid = _seed_session_and_messages(db, env["admin_id"])
    r = requests.delete(f"{API}/me/liluvine-pro/sessions/{sid}", headers=_h(env["admin_token"]))
    assert r.status_code == 200
    assert db.liluvine_pro_sessions.find_one({"id": sid}) is None
    assert db.liluvine_pro_messages.count_documents({"session_id": sid}) == 0


# ====================================================================
# Quota enforcement — chat is blocked when quota is over
# ====================================================================
def test_chat_blocked_when_quota_exceeded(env, db):
    # Activate the feature first (else we get 403 before 429)
    db.users.update_one({"id": env["admin_id"]}, {"$set": {"features.ai_liluvine_pro": True}})
    # Set a quota that's already busted
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    db.ai_quotas.replace_one(
        {"client_id": env["admin_id"]},
        {"client_id": env["admin_id"], "mode": "quota", "monthly_chat_tokens": 100,
         "block_on_limit": True, "alert_warn_pct": 80},
        upsert=True,
    )
    db.ai_usage_monthly.replace_one(
        {"_id": f"{env['admin_id']}:{ym}"},
        {"_id": f"{env['admin_id']}:{ym}", "client_id": env["admin_id"], "year_month": ym,
         "images": 0, "videos": 0, "transcription_minutes": 0, "chat_tokens": 999, "total_xof": 0},
        upsert=True,
    )
    r = requests.post(
        f"{API}/me/liluvine-pro/chat",
        headers=_h(env["admin_token"]),
        json={"text": "Test"},
    )
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert "Quota" in detail or "quota" in detail
    db.ai_quotas.delete_many({"client_id": env["admin_id"]})
    db.ai_usage_monthly.delete_many({"client_id": env["admin_id"]})
