"""Iter38r-fix9x — Voice Monkey provider for voice notifications."""
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
def tenant(db):
    admin_id = f"vx_adm_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active", "created_at": now,
    })
    yield {"admin_id": admin_id, "admin_token": _forge(admin_id, "admin")}
    db.users.delete_many({"id": admin_id})
    db.voice_notifications_config.delete_one({"_id": admin_id})
    db.voice_notifications_log.delete_many({"tenant_id": admin_id})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_config_accepts_provider_voice_monkey(tenant):
    r = requests.put(
        f"{API}/admin/voice-notifications/config",
        headers=_h(tenant["admin_token"]),
        json={
            "enabled": True,
            "provider": "voice_monkey",
            "voice_monkey_url": "https://api-v2.voicemonkey.io/announcement?token=fake&device=bureau",
        },
    )
    assert r.status_code == 200, r.text
    g = requests.get(f"{API}/admin/voice-notifications/config", headers=_h(tenant["admin_token"])).json()
    assert g["provider"] == "voice_monkey"
    assert g["voice_monkey_url_set"] is True
    # The raw URL must NOT leak (token is embedded)
    assert "fake" not in str(g) or "…" in g["voice_monkey_url_masked"]


def test_config_rejects_invalid_provider(tenant):
    r = requests.put(
        f"{API}/admin/voice-notifications/config",
        headers=_h(tenant["admin_token"]),
        json={"provider": "amazon_polly"},
    )
    assert r.status_code == 400


def test_test_endpoint_voice_monkey_502_when_unreachable(tenant):
    requests.put(
        f"{API}/admin/voice-notifications/config",
        headers=_h(tenant["admin_token"]),
        json={
            "enabled": True,
            "provider": "voice_monkey",
            "voice_monkey_url": "http://127.0.0.1:9/announce",  # closed port
        },
    )
    r = requests.post(
        f"{API}/admin/voice-notifications/test",
        headers=_h(tenant["admin_token"]),
        json={"message": "Hello VM"},
    )
    assert r.status_code == 502
    assert "Voice Monkey".lower() in r.json()["detail"].lower()


def test_test_endpoint_voice_monkey_400_when_url_missing(tenant, db):
    # Provider = voice_monkey but no URL saved yet
    db.voice_notifications_config.update_one(
        {"_id": tenant["admin_id"]},
        {"$set": {"enabled": True, "provider": "voice_monkey", "voice_monkey_url": ""}},
        upsert=True,
    )
    r = requests.post(
        f"{API}/admin/voice-notifications/test",
        headers=_h(tenant["admin_token"]),
        json={"message": "x"},
    )
    assert r.status_code == 400
