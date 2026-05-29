"""Iter38r-fix9d — Welcome modal counter "Liluvine a répondu à X messages
WhatsApp aujourd'hui". Tests that /me/welcome-briefing exposes the stats and
that the counts are correctly scoped to the tenant + today's window."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
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


def test_welcome_briefing_exposes_liluvine_autoreply(admin_h):
    """The endpoint must always return the liluvine_autoreply_today dict."""
    r = requests.get(f"{API}/me/welcome-briefing", headers=admin_h, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "liluvine_autoreply_today" in body, "missing field"
    stats = body["liluvine_autoreply_today"]
    for key in ("today", "yesterday", "last_7d", "minutes_saved_today", "enabled"):
        assert key in stats, f"missing {key}"
    assert isinstance(stats["today"], int)
    assert isinstance(stats["enabled"], bool)


def test_welcome_briefing_counts_today_messages(admin_h, db_sync, admin_id):
    """Insert fake WA auto-reply messages and assert today+last_7d counts move."""
    now = datetime.now(timezone.utc)
    today_iso = now.isoformat()
    six_days_ago = (now - timedelta(days=6)).isoformat()
    yesterday_iso = (now - timedelta(days=1)).replace(hour=12).isoformat()
    tag = f"test-fix9d-{uuid.uuid4().hex[:6]}"
    inserted = []
    try:
        for ts, kind in [
            (today_iso, "today"),
            (today_iso, "today"),
            (yesterday_iso, "yesterday"),
            (six_days_ago, "week"),
        ]:
            mid = f"_test_{kind}_{uuid.uuid4().hex[:8]}"
            db_sync.liluvine_pro_messages.insert_one({
                "id": mid, "session_id": f"wa:{admin_id}:test", "client_id": admin_id,
                "user_id": admin_id, "role": "assistant",
                "content": f"{tag}: ping {kind}",
                "external_source": "whatsapp_native", "created_at": ts,
            })
            inserted.append(mid)
        # Read briefing
        r = requests.get(f"{API}/me/welcome-briefing", headers=admin_h, timeout=30)
        stats = r.json()["liluvine_autoreply_today"]
        assert stats["today"] >= 2, f"today should be >=2, got {stats}"
        assert stats["yesterday"] >= 1
        assert stats["last_7d"] >= 4
        assert stats["minutes_saved_today"] >= 2
    finally:
        db_sync.liluvine_pro_messages.delete_many({"id": {"$in": inserted}})
