"""Iter38r-fix7 — Tests:
1. Liluvine PRO feature gating via ai_liluvine_pro flag
2. Liluvine PRO branding endpoint
3. Liluvine PRO inbound webhook (n8n/whatsapp/facebook)
4. Profile photo AI generation hits the new endpoint
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
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid, role="admin"):
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
    aid = f"fix7_adm_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "full_name": "Admin FX7", "role": "admin", "company": "FX7",
        "account_status": "active", "created_at": now,
        "features": {"ai_liluvine_pro": False, "ai_image_gen": False},
    })
    original_settings = db.settings.find_one({"_id": "global"}) or {}
    yield {"aid": aid, "tok": _forge(aid)}
    db.users.delete_many({"id": aid})
    db.liluvine_pro_sessions.delete_many({"client_id": aid})
    db.liluvine_pro_messages.delete_many({"client_id": aid})
    if original_settings:
        db.settings.replace_one({"_id": "global"}, original_settings, upsert=True)


def _h(tok): return {"Authorization": f"Bearer {tok}"}


# ====================================================================
# Feature gating
# ====================================================================
def test_chat_403_when_feature_disabled(env, db):
    db.users.update_one({"id": env["aid"]}, {"$set": {"features.ai_liluvine_pro": False}})
    r = requests.post(f"{API}/me/liluvine-pro/chat", headers=_h(env["tok"]), json={"text": "Salut"})
    assert r.status_code == 403, r.text
    assert "n'est pas activé" in r.json()["detail"]


def test_branding_endpoint_returns_defaults(env, db):
    r = requests.get(f"{API}/me/liluvine-pro/branding", headers=_h(env["tok"]))
    assert r.status_code == 200
    body = r.json()
    assert body["name"]
    assert "color" in body
    assert "avatar_url" in body


def test_branding_endpoint_returns_custom_values(env, db):
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "liluvine_pro_name": "Mon Assistant",
            "liluvine_pro_avatar_url": "https://example.com/a.png",
            "liluvine_pro_color": "indigo",
        }},
        upsert=True,
    )
    r = requests.get(f"{API}/me/liluvine-pro/branding", headers=_h(env["tok"]))
    body = r.json()
    assert body["name"] == "Mon Assistant"
    assert body["avatar_url"] == "https://example.com/a.png"
    assert body["color"] == "indigo"


# ====================================================================
# Inbound webhook
# ====================================================================
def test_inbound_webhook_rejects_bad_secret(env, db):
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"liluvine_pro_inbound_secret": "the-real-one"}},
        upsert=True,
    )
    r = requests.post(
        f"{API}/webhooks/liluvine-pro/n8n/wrong-secret",
        json={"text": "Hello", "client_id": env["aid"]},
    )
    assert r.status_code == 403


def test_inbound_webhook_rejects_bad_source(env, db):
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"liluvine_pro_inbound_secret": "s7"}},
        upsert=True,
    )
    r = requests.post(
        f"{API}/webhooks/liluvine-pro/badsource/s7",
        json={"text": "Hello", "client_id": env["aid"]},
    )
    assert r.status_code == 400


def test_inbound_urls_endpoint_generates_secret(env, db):
    db.settings.update_one({"_id": "global"}, {"$unset": {"liluvine_pro_inbound_secret": ""}}, upsert=True)
    r = requests.get(f"{API}/admin/liluvine-pro/inbound-urls", headers=_h(env["tok"]))
    assert r.status_code == 200
    body = r.json()
    assert "n8n_url" in body
    assert "whatsapp_url" in body
    assert "facebook_url" in body
    assert "custom_url" in body
    # Secret was auto-generated and stored
    s = db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_pro_inbound_secret": 1})
    assert s.get("liluvine_pro_inbound_secret")


# ====================================================================
# Profile photo endpoint — feature-gate only (no actual LLM call)
# ====================================================================
def test_profile_photo_403_when_image_gen_off(env, db):
    # Admins bypass the feature check, so use a tracked client user
    tracked_id = f"fix7_cli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": tracked_id, "email": f"{tracked_id}@t.l", "password_hash": "x",
        "full_name": "Tracked FX7", "role": "client",
        "tracked_user_id": env["aid"], "client_id": env["aid"],
        "account_status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        db.users.update_one({"id": env["aid"]}, {"$set": {"features.ai_image_gen": False}})
        client_tok = _forge(tracked_id, "client")
        r = requests.post(
            f"{API}/me/ai/generate-profile-photo",
            headers=_h(client_tok),
            json={"prompt": "Test portrait", "style": "professional"},
        )
        assert r.status_code == 403, r.text
    finally:
        db.users.delete_one({"id": tracked_id})
