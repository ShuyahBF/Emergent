"""Iter38r-fix9e — Tests for Liluvine PRO branding admin endpoints and the
realtime auto-reply feed (`/me/liluvine-pro/autoreply-feed`).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30).json()
    if not r.get("needs_otp"):
        return r["access_token"]
    return requests.post(f"{API}/auth/verify-otp", json={
        "session_token": r["session_token"], "code": r["dev_otp"],
    }, timeout=30).json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_id(db_sync):
    return db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})["id"]


def test_branding_get_default(admin_h):
    r = requests.get(f"{API}/admin/liluvine-pro/branding", headers=admin_h, timeout=30)
    assert r.status_code == 200
    body = r.json()
    for k in ("name", "avatar_url", "color", "tagline"):
        assert k in body


def test_branding_put_persists(admin_h, db_sync):
    # Snapshot
    orig = db_sync.settings.find_one({"_id": "global"}, {
        "_id": 0, "liluvine_pro_name": 1, "liluvine_pro_color": 1, "liluvine_pro_tagline": 1
    }) or {}
    try:
        marker = f"Sawali Test {uuid.uuid4().hex[:6]}"
        r = requests.put(f"{API}/admin/liluvine-pro/branding", headers=admin_h, json={
            "name": marker, "color": "emerald", "tagline": "Tagline test",
        }, timeout=30)
        assert r.status_code == 200, r.text
        # Verify GET
        body = requests.get(f"{API}/admin/liluvine-pro/branding", headers=admin_h, timeout=30).json()
        assert body["name"] == marker
        assert body["color"] == "emerald"
        assert body["tagline"] == "Tagline test"
        # Verify the public branding endpoint reflects it
        pub = requests.get(f"{API}/me/liluvine-pro/branding", headers=admin_h, timeout=30).json()
        assert pub["name"] == marker
        assert pub["color"] == "emerald"
    finally:
        requests.put(f"{API}/admin/liluvine-pro/branding", headers=admin_h, json={
            "name": orig.get("liluvine_pro_name") or "Liluvine PRO",
            "color": orig.get("liluvine_pro_color") or "fuchsia",
            "tagline": orig.get("liluvine_pro_tagline") or "",
        }, timeout=30)


def test_branding_rejects_invalid_color(admin_h):
    r = requests.put(f"{API}/admin/liluvine-pro/branding", headers=admin_h, json={
        "color": "neon_purple_invalid"
    }, timeout=30)
    assert r.status_code == 422


def test_branding_requires_admin():
    r = requests.get(f"{API}/admin/liluvine-pro/branding", timeout=30)
    assert r.status_code in (401, 403)


def test_autoreply_feed_initial_empty(admin_h):
    """The feed endpoint should always respond 200 even when no events exist."""
    r = requests.get(f"{API}/me/liluvine-pro/autoreply-feed", headers=admin_h, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "server_now" in body
    assert isinstance(body["items"], list)


def test_autoreply_feed_returns_recent_events(admin_h, db_sync, admin_id):
    """Insert a fake event, fetch the feed without `since`, and verify it appears."""
    mid = f"_test_fix9e_{uuid.uuid4().hex[:8]}"
    sid = f"_test_sess_fix9e_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db_sync.liluvine_pro_sessions.insert_one({
        "id": sid, "client_id": admin_id, "user_label": "WA +22890999000",
        "external_payload": {"phone_digits": "22890999000"},
        "external_source": "whatsapp_native", "created_at": now, "updated_at": now,
        "message_count": 1, "title": "test",
    })
    db_sync.liluvine_pro_messages.insert_one({
        "id": mid, "session_id": sid, "client_id": admin_id, "user_id": admin_id,
        "role": "assistant", "content": "Bonjour ! Voici votre tarif…",
        "external_source": "whatsapp_native", "created_at": now,
    })
    try:
        r = requests.get(f"{API}/me/liluvine-pro/autoreply-feed", headers=admin_h, timeout=30)
        assert r.status_code == 200
        body = r.json()
        # Should include our event
        ids = [i["id"] for i in body["items"]]
        assert mid in ids, f"Inserted event missing — got: {ids}"
        item = next(i for i in body["items"] if i["id"] == mid)
        assert item["contact_label"] == "WA +22890999000"
        assert item["phone_digits"] == "22890999000"
        assert "Bonjour" in item["content_preview"]
    finally:
        db_sync.liluvine_pro_messages.delete_one({"id": mid})
        db_sync.liluvine_pro_sessions.delete_one({"id": sid})


def test_autoreply_feed_since_filter(admin_h, db_sync, admin_id):
    """With a `since` in the future, the feed must return zero items."""
    future = "2999-01-01T00:00:00+00:00"
    r = requests.get(f"{API}/me/liluvine-pro/autoreply-feed?since={future}", headers=admin_h, timeout=30)
    assert r.status_code == 200
    assert r.json()["items"] == []
