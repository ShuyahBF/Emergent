"""Iter38r-fix9p — Backend feature gate for `ai_voice_gen`.

Verifies that the per-tenant `ai_voice_gen` toggle blocks calls to the
ElevenLabs endpoints in `/app/backend/routes/ai_media_9m.py`:
  - POST /api/me/ai/tts-elevenlabs
  - POST /api/me/ai/voices/clone

Admin / superviseur bypass the gate (same convention as ai_image_gen).
"""
from __future__ import annotations

import io
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


def _forge(uid: str, role: str = "client") -> str:
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
    admin_id = f"vp_adm_{uuid.uuid4().hex[:6]}"
    emp_id = f"vp_emp_{uuid.uuid4().hex[:6]}"
    company = f"VP-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin VP", "company": company, "role": "admin",
         "account_status": "active", "created_at": now,
         "features": {"ai_voice_gen": False}},
        {"id": emp_id, "email": f"{emp_id}@t.l", "password_hash": "x",
         "full_name": "Employee VP", "company": company, "role": "client",
         "tracked_user_id": admin_id, "parent_client_id": admin_id,
         "account_status": "active", "created_at": now},
    ])
    yield {
        "admin_id": admin_id, "admin_token": _forge(admin_id, "admin"),
        "emp_id": emp_id, "emp_token": _forge(emp_id, "client"),
        "company": company,
    }
    db.users.delete_many({"id": {"$in": [admin_id, emp_id]}})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_tts_elevenlabs_blocked_when_voice_gen_off(tenant, db):
    db.users.update_one(
        {"id": tenant["admin_id"]},
        {"$set": {"features.ai_voice_gen": False}},
    )
    r = requests.post(
        f"{API}/me/ai/tts-elevenlabs",
        headers=_h(tenant["emp_token"]),
        json={"voice_id": "dummy", "text": "Bonjour"},
    )
    assert r.status_code == 403, r.text
    assert "désactivée" in r.json().get("detail", "").lower()


def test_voice_clone_blocked_when_voice_gen_off(tenant, db):
    db.users.update_one(
        {"id": tenant["admin_id"]},
        {"$set": {"features.ai_voice_gen": False}},
    )
    # Multipart with a dummy audio file
    files = {"audio_file": ("voice.mp3", io.BytesIO(b"FAKE"), "audio/mpeg")}
    data = {"name": "My Voice", "description": ""}
    r = requests.post(
        f"{API}/me/ai/voices/clone",
        headers=_h(tenant["emp_token"]),
        files=files, data=data,
    )
    assert r.status_code == 403, r.text


def test_tts_admin_bypasses_voice_gate(tenant, db):
    """Admin must NOT be blocked even when ai_voice_gen is OFF."""
    db.users.update_one(
        {"id": tenant["admin_id"]},
        {"$set": {"features.ai_voice_gen": False}},
    )
    r = requests.post(
        f"{API}/me/ai/tts-elevenlabs",
        headers=_h(tenant["admin_token"]),
        json={"voice_id": "dummy", "text": "Bonjour"},
    )
    # Gate must be passed — any other status (502, 503 due to missing key,
    # or upstream error) is acceptable as long as it's not 403.
    assert r.status_code != 403, r.text


def test_tts_allowed_when_voice_gen_on(tenant, db):
    """When the feature is ON, the gate must not block the request."""
    db.users.update_one(
        {"id": tenant["admin_id"]},
        {"$set": {"features.ai_voice_gen": True}},
    )
    r = requests.post(
        f"{API}/me/ai/tts-elevenlabs",
        headers=_h(tenant["emp_token"]),
        json={"voice_id": "dummy", "text": "Bonjour"},
    )
    assert r.status_code != 403, r.text
