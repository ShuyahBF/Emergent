"""Iter37f — Welcome briefing unread WhatsApp/SMS count must be bounded.

Bug from prod: even after reading a WA message, the welcome briefing kept
showing the same count (e.g. "5 messages non lus" while only 1 today).
Root cause: query counted ALL inbound messages with read_by_us_at=None,
no time bound. Legacy data accumulates forever.

Fix: bound by last_seen_at (sent by the frontend from localStorage) or
fallback to last 7 days.
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


def _forge(uid: str, role: str = "superviseur") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(autouse=True)
def reset_welcome_mode(db):
    """Ensure each test starts with welcome_unread_mode=bounded (default)."""
    db.settings.update_one({"_id": "global"}, {"$unset": {"welcome_unread_mode": ""}}, upsert=True)
    yield
    db.settings.update_one({"_id": "global"}, {"$unset": {"welcome_unread_mode": ""}})


@pytest.fixture
def user_with_wa_messages(db):
    """Seed a supervisor + WA messages: 1 from today (unread), 1 from 30 days ago (unread)."""
    uid = f"sup_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
        "full_name": "Test Sup", "role": "superviseur",
        "account_status": "active", "company": f"CO-{uuid.uuid4().hex[:6]}",
        "created_at": now.isoformat(),
    })
    # Old message (30 days ago, unread)
    old_id = f"wa_old_{uuid.uuid4().hex[:6]}"
    db.whatsapp_messages.insert_one({
        "id": old_id,
        "client_id": uid,
        "direction": "inbound",
        "read_by_us_at": None,
        "received_at": (now - timedelta(days=30)).isoformat(),
        "from": "+22612345678", "body": "old msg",
    })
    # Recent message (today, unread)
    new_id = f"wa_new_{uuid.uuid4().hex[:6]}"
    db.whatsapp_messages.insert_one({
        "id": new_id,
        "client_id": uid,
        "direction": "inbound",
        "read_by_us_at": None,
        "received_at": now.isoformat(),
        "from": "+22612345678", "body": "new msg",
    })
    yield {"uid": uid, "old_id": old_id, "new_id": new_id, "now": now}
    db.users.delete_one({"id": uid})
    db.whatsapp_messages.delete_many({"id": {"$in": [old_id, new_id]}})


class TestUnreadBoundedByLastSeen:
    def test_unread_uses_7day_window_when_no_last_seen(self, user_with_wa_messages):
        """Without last_seen_at, only counts last 7 days → 1 unread (not 2)."""
        ctx = user_with_wa_messages
        h = {"Authorization": f"Bearer {_forge(ctx['uid'])}"}
        r = requests.get(f"{API}/me/welcome-briefing", headers=h, timeout=20)
        assert r.status_code == 200, r.text
        unread = r.json()["unread_messages"]
        # The 30-days-old message must be excluded
        assert unread["whatsapp"] == 1, f"Expected 1 (today only), got {unread['whatsapp']}"
        assert unread["total"] == 1

    def test_unread_bounded_by_last_seen_at(self, user_with_wa_messages):
        """With last_seen_at = 2h ago, only counts msgs received after that → 1."""
        ctx = user_with_wa_messages
        h = {"Authorization": f"Bearer {_forge(ctx['uid'])}"}
        # Pretend we last visited 2 hours ago: the 30-days-old + today-just-now
        # are filtered (>= 2h ago window keeps "today's" msg if it's < 2h old).
        two_hours_ago = (ctx["now"] - timedelta(hours=2)).isoformat()
        r = requests.get(f"{API}/me/welcome-briefing",
                         params={"last_seen_at": two_hours_ago}, headers=h, timeout=20)
        assert r.status_code == 200, r.text
        unread = r.json()["unread_messages"]
        # Today's msg (received_at = now) is >= two_hours_ago → counted
        # Old msg (30d ago) is < two_hours_ago → excluded
        assert unread["whatsapp"] == 1, f"Expected 1, got {unread['whatsapp']}"

    def test_unread_with_future_last_seen_returns_zero(self, user_with_wa_messages):
        """If last_seen_at is in the future, no msg qualifies → 0."""
        ctx = user_with_wa_messages
        h = {"Authorization": f"Bearer {_forge(ctx['uid'])}"}
        tomorrow = (ctx["now"] + timedelta(days=1)).isoformat()
        r = requests.get(f"{API}/me/welcome-briefing",
                         params={"last_seen_at": tomorrow}, headers=h, timeout=20)
        assert r.status_code == 200, r.text
        unread = r.json()["unread_messages"]
        assert unread["whatsapp"] == 0
        assert unread["total"] == 0


class TestUnreadAdminConfigurableMode:
    def test_lifetime_mode_counts_all_unread(self, user_with_wa_messages, db):
        """When welcome_unread_mode=lifetime, both old and new unread msgs count."""
        ctx = user_with_wa_messages
        db.settings.update_one({"_id": "global"}, {"$set": {"welcome_unread_mode": "lifetime"}}, upsert=True)
        try:
            h = {"Authorization": f"Bearer {_forge(ctx['uid'])}"}
            r = requests.get(f"{API}/me/welcome-briefing", headers=h, timeout=20)
            assert r.status_code == 200, r.text
            unread = r.json()["unread_messages"]
            # Both old (30d) AND new (today) count
            assert unread["whatsapp"] == 2, f"lifetime should count both, got {unread['whatsapp']}"
        finally:
            db.settings.update_one({"_id": "global"}, {"$unset": {"welcome_unread_mode": ""}})

    def test_bounded_mode_explicit_matches_default(self, user_with_wa_messages, db):
        """Explicit welcome_unread_mode=bounded behaves like the default."""
        ctx = user_with_wa_messages
        db.settings.update_one({"_id": "global"}, {"$set": {"welcome_unread_mode": "bounded"}}, upsert=True)
        try:
            h = {"Authorization": f"Bearer {_forge(ctx['uid'])}"}
            r = requests.get(f"{API}/me/welcome-briefing", headers=h, timeout=20)
            assert r.status_code == 200, r.text
            unread = r.json()["unread_messages"]
            assert unread["whatsapp"] == 1
        finally:
            db.settings.update_one({"_id": "global"}, {"$unset": {"welcome_unread_mode": ""}})

    def test_invalid_mode_rejected_at_settings_put(self):
        """PUT /admin/settings with invalid welcome_unread_mode → 400."""
        # Need admin token
        r = requests.post(f"{API}/auth/login",
                          json={"email": "admin@sawalismartsystems.com",
                                "password": "Admin@Sawali2026"}, timeout=20)
        d = r.json()
        tok = d.get("access_token")
        if not tok:
            v = requests.post(f"{API}/auth/verify-otp",
                              json={"session_token": d["session_token"], "code": d["dev_otp"]}, timeout=20)
            tok = v.json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.put(f"{API}/admin/settings",
                         json={"welcome_unread_mode": "bogus"}, headers=h, timeout=15)
        assert r.status_code == 400
