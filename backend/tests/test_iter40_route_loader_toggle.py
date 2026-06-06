"""Iter40-route-loader (S051) — Admin toggle for GlobalRouteLoader.

Validates:
 - GET /api/public/ui-flags is anonymous and returns the loader flag (default true)
 - PUT /api/admin/settings accepts global_route_loader_enabled
 - When set to false, the public endpoint reflects it
 - Endpoint never exposes secrets
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
    admin_id = f"rl_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin")
    db.users.delete_one({"id": admin_id})


def test_ui_flags_endpoint_is_anonymous():
    """GET /public/ui-flags must work without any auth header."""
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "global_route_loader_enabled" in body
    assert isinstance(body["global_route_loader_enabled"], bool)


def test_ui_flags_default_loader_enabled_when_unset(admin, db):
    """When the setting has never been written, the default is true (enabled)."""
    # Reset to None (delete the key if present)
    db.settings.update_one({"_id": "global"}, {"$unset": {"global_route_loader_enabled": ""}})
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    assert r.status_code == 200
    assert r.json()["global_route_loader_enabled"] is True


def test_admin_can_toggle_loader_off(admin, db):
    """Setting global_route_loader_enabled to false makes the public endpoint
    return false. Setting it back to true restores the default."""
    headers = {"Authorization": f"Bearer {admin}"}
    # Turn OFF
    r = requests.put(f"{API}/admin/settings",
                     json={"global_route_loader_enabled": False},
                     headers=headers, timeout=10)
    assert r.status_code == 200, r.text
    r2 = requests.get(f"{API}/public/ui-flags", timeout=10)
    assert r2.status_code == 200
    assert r2.json()["global_route_loader_enabled"] is False
    # Turn back ON
    r = requests.put(f"{API}/admin/settings",
                     json={"global_route_loader_enabled": True},
                     headers=headers, timeout=10)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/public/ui-flags", timeout=10)
    assert r2.json()["global_route_loader_enabled"] is True


def test_ui_flags_never_exposes_secrets():
    """Belt & suspenders: the public payload must contain ONLY display flags."""
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    body = r.json()
    # Allowed keys are explicit. No surprise field with secrets.
    allowed = {
        "global_route_loader_enabled", "download_gauge_enabled",
        "public_brand_name", "public_brand_color", "public_brand_text_color",
        "public_logo_url", "public_hero_tagline",
        "public_bg_mode", "public_bg_color", "public_bg_image_url", "public_bg_image_position",
        "portal_bg_mode", "portal_bg_color", "portal_bg_image_url", "portal_bg_image_position",
        # S057 — habillage complet
        "sidebar_bg_color", "sidebar_text_color", "sidebar_accent_color",
        "login_bg_mode", "login_bg_color", "login_bg_image_url", "login_text_color",
        "login_card_bg", "login_card_text_color", "login_button_bg", "login_button_text_color",
        "public_blocks_theme",
    }
    leaked = set(body.keys()) - allowed
    assert not leaked, f"Unexpected keys in /public/ui-flags: {leaked}"
    # Verify no key with a sensitive name pattern slipped through
    for k in body:
        kl = k.lower()
        for bad in ("password", "secret", "token", "smtp", "stripe", "pawapay", "openai", "client_secret"):
            assert bad not in kl, f"Suspicious key in /public/ui-flags: {k}"


def test_ui_flags_branding_fields_default_null():
    """Brand fields are null/None when never configured."""
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    body = r.json()
    # All four branding keys must be present (even if null)
    for k in ("public_brand_name", "public_brand_color", "public_logo_url", "public_hero_tagline"):
        assert k in body


def test_admin_can_set_branding_fields(admin, db):
    """PUT branding fields and verify they are echoed by the public endpoint."""
    headers = {"Authorization": f"Bearer {admin}"}
    r = requests.put(
        f"{API}/admin/settings",
        json={
            "public_brand_name": "Test Brand SA",
            "public_brand_color": "#FF6B35",
            "public_logo_url": "https://example.com/logo.svg",
            "public_hero_tagline": "Notre accroche test",
        }, headers=headers, timeout=10,
    )
    assert r.status_code == 200, r.text
    r2 = requests.get(f"{API}/public/ui-flags", timeout=10)
    body = r2.json()
    assert body["public_brand_name"] == "Test Brand SA"
    assert body["public_brand_color"] == "#FF6B35"
    assert body["public_logo_url"] == "https://example.com/logo.svg"
    assert body["public_hero_tagline"] == "Notre accroche test"
    # Cleanup
    db.settings.update_one(
        {"_id": "global"},
        {"$unset": {
            "public_brand_name": "", "public_brand_color": "",
            "public_logo_url": "", "public_hero_tagline": "",
        }},
    )


def test_empty_branding_strings_normalized_to_null(admin, db):
    """Empty strings are normalized to null in the public response."""
    headers = {"Authorization": f"Bearer {admin}"}
    # Set blanks (whitespace-only)
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "public_brand_name": "   ",
            "public_brand_color": "",
            "public_logo_url": "",
            "public_hero_tagline": "",
        }},
        upsert=True,
    )
    r = requests.get(f"{API}/public/ui-flags", timeout=10)
    body = r.json()
    assert body["public_brand_name"] is None
    assert body["public_brand_color"] is None
    assert body["public_logo_url"] is None
    assert body["public_hero_tagline"] is None


def test_admin_settings_get_returns_the_flag(admin, db):
    """GET /admin/settings should include global_route_loader_enabled after it's been set."""
    headers = {"Authorization": f"Bearer {admin}"}
    requests.put(f"{API}/admin/settings",
                 json={"global_route_loader_enabled": False},
                 headers=headers, timeout=10)
    r = requests.get(f"{API}/admin/settings", headers=headers, timeout=10)
    assert r.status_code == 200
    assert r.json()["global_route_loader_enabled"] is False
    # cleanup
    requests.put(f"{API}/admin/settings",
                 json={"global_route_loader_enabled": True},
                 headers=headers, timeout=10)
