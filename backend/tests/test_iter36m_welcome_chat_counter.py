"""Iter36m — Welcome Briefing now includes unread chat messages since
last visit. Validates:
  - GET /me/welcome-briefing?last_seen_at=ISO returns since_last_visit.new_chat_messages_count
  - Counter increments only for messages received AND unread by current user
  - Both DM and #general messages count
  - Messages older than last_seen_at are excluded
  - Messages already read by the user are excluded
  - Sender's own messages don't count
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
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _token(uid: str, role: str = "client") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def setup(db):
    """Seed a client with chat ON + 2 bridged tracked users."""
    cid = f"wb_client_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": cid, "email": f"{cid}@test.local", "password_hash": "x",
        "full_name": "WB Client", "role": "client",
        "account_status": "active",
        "features": {"internal_chat": True},
    })
    members = []
    for i in range(2):
        uid = f"wb_user_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
            "full_name": f"WB User {i}", "role": "client",
            "account_status": "active",
        })
        db.tracked_users.insert_one({
            "id": f"tu_{uuid.uuid4().hex[:6]}", "client_id": cid,
            "name": f"WB User {i}", "email": f"{uid}@test.local",
            "status": "active", "user_account_id": uid,
        })
        members.append(uid)
    yield {"client_id": cid, "members": members}
    db.users.delete_many({"id": {"$in": [cid, *members]}})
    db.tracked_users.delete_many({"client_id": cid})
    db.internal_chat_messages.delete_many({"client_id": cid})


def _insert_msg(db, cid, sender_id, recipient_id, text, created_at, read_by=None):
    db.internal_chat_messages.insert_one({
        "id": str(uuid.uuid4()),
        "client_id": cid,
        "sender_id": sender_id,
        "sender_name": "Test",
        "recipient_id": recipient_id,
        "text": text,
        "created_at": created_at,
        "read_by": (read_by or [sender_id]),
    })


class TestWelcomeChatCounter:
    def test_dm_received_unread_after_last_seen_counts(self, setup, db):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h_b = {"Authorization": f"Bearer {_token(uid_b)}"}
        # Reference times: last_seen_at = now-2h ; message sent now-1h.
        last_seen = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        # A → B DM, not yet read by B
        _insert_msg(db, cid, uid_a, uid_b, "Hello B", recent)
        r = requests.get(
            f"{API}/me/welcome-briefing",
            headers=h_b, params={"last_seen_at": last_seen}, timeout=15,
        )
        assert r.status_code == 200, r.text
        slv = r.json()["since_last_visit"]
        assert slv is not None
        assert slv["new_chat_messages_count"] >= 1
        assert slv["total_count"] >= 1

    def test_general_received_unread_counts(self, setup, db):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h_b = {"Authorization": f"Bearer {_token(uid_b)}"}
        last_seen = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        # A → #general, NOT yet read by B (recipient_id None, sender_id != B)
        _insert_msg(db, cid, uid_a, None, "Hello équipe", recent)
        r = requests.get(
            f"{API}/me/welcome-briefing",
            headers=h_b, params={"last_seen_at": last_seen}, timeout=15,
        )
        assert r.status_code == 200, r.text
        slv = r.json()["since_last_visit"]
        assert slv["new_chat_messages_count"] >= 1

    def test_already_read_excluded(self, setup, db):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h_b = {"Authorization": f"Bearer {_token(uid_b)}"}
        last_seen = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        # Message already read by B
        _insert_msg(db, cid, uid_a, uid_b, "Déjà lu", recent, read_by=[uid_a, uid_b])
        r = requests.get(
            f"{API}/me/welcome-briefing",
            headers=h_b, params={"last_seen_at": last_seen}, timeout=15,
        )
        slv = r.json()["since_last_visit"] or {"new_chat_messages_count": 0}
        # Should NOT count this one (could be 0 if no other unread)
        # We can only assert it's not incremented unfairly; combine with previous
        # tests run in isolation. Best simple check: counter still zero in isolation.
        # To keep this test independent, clean before:
        db.internal_chat_messages.delete_many({"client_id": cid})
        _insert_msg(db, cid, uid_a, uid_b, "Déjà lu", recent, read_by=[uid_a, uid_b])
        r2 = requests.get(
            f"{API}/me/welcome-briefing",
            headers=h_b, params={"last_seen_at": last_seen}, timeout=15,
        )
        slv2 = r2.json()["since_last_visit"]
        # since_last_visit may be None if total_count==0 → that's the expected outcome
        if slv2 is not None:
            assert slv2["new_chat_messages_count"] == 0

    def test_messages_before_last_seen_excluded(self, setup, db):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h_b = {"Authorization": f"Bearer {_token(uid_b)}"}
        db.internal_chat_messages.delete_many({"client_id": cid})
        last_seen = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        _insert_msg(db, cid, uid_a, uid_b, "Vieux message", old)
        r = requests.get(
            f"{API}/me/welcome-briefing",
            headers=h_b, params={"last_seen_at": last_seen}, timeout=15,
        )
        slv = r.json()["since_last_visit"]
        # Old message before last_seen → not counted; SLV may be None when total==0
        if slv is not None:
            assert slv["new_chat_messages_count"] == 0

    def test_self_sent_messages_excluded(self, setup, db):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h_a = {"Authorization": f"Bearer {_token(uid_a)}"}
        db.internal_chat_messages.delete_many({"client_id": cid})
        last_seen = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        # A sends to general (his own message)
        _insert_msg(db, cid, uid_a, None, "Mon propre message", recent, read_by=[uid_a])
        r = requests.get(
            f"{API}/me/welcome-briefing",
            headers=h_a, params={"last_seen_at": last_seen}, timeout=15,
        )
        slv = r.json()["since_last_visit"]
        # A should NOT see his own message counted
        if slv is not None:
            assert slv["new_chat_messages_count"] == 0
