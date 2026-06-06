"""S057 Day 3+ (2026-02) — Habillage complet (Sidebar/Login/Blocs publics).

Validates :
 - Settings model accepts all 15+ new theme fields
 - /api/public/ui-flags exposes them (anonymously, no auth)
 - PUT /admin/settings persists them
 - public_blocks_theme nested dict is preserved
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
def admin_token(db):
    aid = f"s057_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "admin"), aid
    db.users.delete_one({"id": aid})


def test_admin_can_set_all_theming_fields(db, admin_token):
    token, _ = admin_token
    payload = {
        "sidebar_bg_color": "#123456",
        "sidebar_text_color": "#abcdef",
        "sidebar_accent_color": "#fe9000",
        "login_bg_mode": "color",
        "login_bg_color": "#111111",
        "login_bg_image_url": "https://example.com/bg.webp",
        "login_text_color": "#eeeeee",
        "login_card_bg": "#f0f0f0",
        "login_card_text_color": "#222222",
        "login_button_bg": "#00ff00",
        "login_button_text_color": "#000000",
        "public_blocks_theme": {
            "hero": {"bg_color": "#001020", "text_color": "#ffffff"},
            "missions": {"bg_color": "#102030"},
            "specialisations": {"text_color": "#fcd34d"},
        },
    }
    r = requests.put(f"{API}/admin/settings", json=payload,
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    # DB persistence
    s = db.settings.find_one({"_id": "global"})
    assert s["sidebar_bg_color"] == "#123456"
    assert s["login_button_bg"] == "#00ff00"
    assert s["public_blocks_theme"]["hero"]["bg_color"] == "#001020"
    assert s["public_blocks_theme"]["missions"]["bg_color"] == "#102030"


def test_ui_flags_exposes_theming_anonymously(db, admin_token):
    """The /public/ui-flags endpoint must return the new fields without auth."""
    token, _ = admin_token
    requests.put(f"{API}/admin/settings", json={
        "sidebar_bg_color": "#789abc",
        "login_card_bg": "#fefefe",
        "public_blocks_theme": {"hero": {"bg_color": "#abcdef"}},
    }, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    # NO auth header
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sidebar_bg_color"] == "#789abc"
    assert body["login_card_bg"] == "#fefefe"
    assert isinstance(body["public_blocks_theme"], dict)
    assert body["public_blocks_theme"]["hero"]["bg_color"] == "#abcdef"


def test_ui_flags_returns_null_when_unset(db):
    """When no theming is set, ui-flags returns null for the key (not crash)."""
    db.settings.update_one({"_id": "global"}, {"$unset": {"sidebar_bg_color": "", "login_card_bg": ""}})
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "sidebar_bg_color" in body
    assert body["sidebar_bg_color"] is None


def test_ui_flags_no_other_settings_leaked(db, admin_token):
    """The ui-flags endpoint must NOT expose any sensitive setting."""
    token, _ = admin_token
    db.settings.update_one({"_id": "global"}, {"$set": {
        "smtp_password": "supersecret-leaked-test",
        "openai_api_key": "sk-test-leaked",
    }})
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    body = r.json()
    assert "smtp_password" not in body
    assert "openai_api_key" not in body
    # Confirm the leaked values aren't anywhere in the response body
    raw = r.text
    assert "supersecret-leaked-test" not in raw
    assert "sk-test-leaked" not in raw
