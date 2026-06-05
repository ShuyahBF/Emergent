"""Iter40-ui-flags-bg (S057) — Public/portal themed background fields.

Validates:
 - GET /api/public/ui-flags exposes the 8 new background fields (4 public + 4 portal)
 - Default values are sensible: mode="default", position="cover"
 - Admin can PUT each scope independently
 - Empty strings are normalized to None for image_url and color
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
def admin(db):
    admin_id = f"bg_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin")
    db.users.delete_one({"id": admin_id})


def test_ui_flags_exposes_bg_defaults():
    """All 8 bg fields are present in the anonymous endpoint with sensible defaults."""
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    assert r.status_code == 200
    body = r.json()
    for key in (
        "public_bg_mode", "public_bg_color", "public_bg_image_url", "public_bg_image_position",
        "portal_bg_mode", "portal_bg_color", "portal_bg_image_url", "portal_bg_image_position",
    ):
        assert key in body, f"missing {key}"
    # Defaults
    assert body["public_bg_mode"] in ("default", "color", "image")
    assert body["public_bg_image_position"] in ("cover", "contain", "center", "repeat")


def test_admin_sets_public_color_bg(admin, db):
    """Public background mode=color is persisted and echoed."""
    headers = {"Authorization": f"Bearer {admin}"}
    r = requests.put(f"{API}/admin/settings",
                     json={"public_bg_mode": "color", "public_bg_color": "#0F172A"},
                     headers=headers, timeout=10)
    assert r.status_code == 200, r.text
    r2 = requests.get(f"{API}/public/ui-flags", timeout=10)
    body = r2.json()
    assert body["public_bg_mode"] == "color"
    assert body["public_bg_color"] == "#0F172A"
    # Cleanup
    requests.put(f"{API}/admin/settings",
                 json={"public_bg_mode": "default", "public_bg_color": ""},
                 headers=headers, timeout=10)


def test_admin_sets_portal_image_bg(admin, db):
    """Portal background mode=image with position is persisted and echoed.
    Public scope remains unchanged."""
    headers = {"Authorization": f"Bearer {admin}"}
    r = requests.put(f"{API}/admin/settings", json={
        "portal_bg_mode": "image",
        "portal_bg_image_url": "https://example.com/pattern.png",
        "portal_bg_image_position": "repeat",
    }, headers=headers, timeout=10)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/public/ui-flags", timeout=10)
    body = r2.json()
    assert body["portal_bg_mode"] == "image"
    assert body["portal_bg_image_url"] == "https://example.com/pattern.png"
    assert body["portal_bg_image_position"] == "repeat"
    # Public scope must NOT have been touched
    assert body["public_bg_mode"] == "default"
    # Cleanup
    requests.put(f"{API}/admin/settings", json={
        "portal_bg_mode": "default", "portal_bg_image_url": "", "portal_bg_image_position": "cover",
    }, headers=headers, timeout=10)


def test_empty_strings_normalized_to_null(admin, db):
    """Empty strings for color/image_url are normalized to None in the response."""
    headers = {"Authorization": f"Bearer {admin}"}
    db.settings.update_one({"_id": "global"}, {"$set": {
        "public_bg_color": "   ", "public_bg_image_url": "",
        "portal_bg_color": "", "portal_bg_image_url": "",
    }}, upsert=True)
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    body = r.json()
    assert body["public_bg_color"] is None
    assert body["public_bg_image_url"] is None
    assert body["portal_bg_color"] is None
    assert body["portal_bg_image_url"] is None
