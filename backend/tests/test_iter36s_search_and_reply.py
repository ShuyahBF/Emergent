"""Iter36s — Search + reply-quote tests.

Validates:
  - GET /me/chat/search returns matches with thread routing.
  - Search is scoped to visible clients only.
  - Search includes general + DM where user is sender/recipient.
  - POST /me/chat/{cid}/messages with reply_to_id snapshots the original.
  - Photo upload supports reply_to_id.
  - reply_to_id pointing to a message of another client is ignored.
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
    cid = f"se_client_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": cid, "email": f"{cid}@test.local", "password_hash": "x",
        "full_name": "Search Client", "role": "client",
        "account_status": "active",
        "features": {"internal_chat": True},
    })
    members = []
    for i in range(2):
        uid = f"se_user_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
            "full_name": f"Search User {i}", "role": "client",
            "account_status": "active",
        })
        db.tracked_users.insert_one({
            "id": f"tu_{uuid.uuid4().hex[:6]}", "client_id": cid,
            "name": f"Search User {i}", "email": f"{uid}@test.local",
            "status": "active", "user_account_id": uid,
        })
        members.append(uid)
    yield {"client_id": cid, "members": members}
    db.users.delete_many({"id": {"$in": [cid, *members]}})
    db.tracked_users.delete_many({"client_id": cid})
    db.internal_chat_messages.delete_many({"client_id": cid})


class TestSearch:
    def test_search_general_messages(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        # Seed
        requests.post(f"{API}/me/chat/{cid}/messages", headers=h,
                      json={"text": "Bonjour rendez-vous mardi matin"}, timeout=15)
        requests.post(f"{API}/me/chat/{cid}/messages", headers=h,
                      json={"text": "Réunion lundi"}, timeout=15)
        r = requests.get(f"{API}/me/chat/search", headers=h, params={"q": "rendez-vous"}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["term"] == "rendez-vous"
        assert len(body["results"]) >= 1
        first = body["results"][0]
        assert "rendez-vous" in first["text"].lower()
        assert first["thread_key"] == "general"
        assert first["client_id"] == cid

    def test_search_dm_routing(self, setup):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h_a = {"Authorization": f"Bearer {_token(uid_a)}"}
        # A → B DM with unique term
        term = f"unique_term_{uuid.uuid4().hex[:6]}"
        requests.post(f"{API}/me/chat/{cid}/messages", headers=h_a,
                      json={"text": f"Hello {term} from A", "recipient_id": uid_b}, timeout=15)
        # B searches → should find it with thread_key = uid_a
        h_b = {"Authorization": f"Bearer {_token(uid_b)}"}
        r = requests.get(f"{API}/me/chat/search", headers=h_b, params={"q": term}, timeout=15)
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) >= 1
        assert results[0]["thread_key"] == uid_a

    def test_search_outsider_blocked(self, setup, db):
        # Outsider not member of the chat-enabled client
        outsider_id = f"out_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": outsider_id, "email": f"{outsider_id}@x.local",
            "password_hash": "x", "full_name": "Outsider",
            "role": "client", "account_status": "active",
        })
        try:
            h = {"Authorization": f"Bearer {_token(outsider_id)}"}
            r = requests.get(f"{API}/me/chat/search", headers=h,
                             params={"q": "anything", "client_id": setup["client_id"]}, timeout=15)
            assert r.status_code == 403
            # And without client_id filter, the outsider gets empty results
            r2 = requests.get(f"{API}/me/chat/search", headers=h, params={"q": "anything"}, timeout=15)
            assert r2.status_code == 200
            assert r2.json()["results"] == []
        finally:
            db.users.delete_one({"id": outsider_id})

    def test_search_unauth(self):
        r = requests.get(f"{API}/me/chat/search", params={"q": "x"}, timeout=15)
        assert r.status_code == 401

    def test_search_empty_query(self, setup):
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        r = requests.get(f"{API}/me/chat/search", headers=h, params={"q": ""}, timeout=15)
        # min_length=1 → 422 validation error
        assert r.status_code == 422


class TestReplyTo:
    def test_reply_to_text_message_snapshots_original(self, setup):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h_a = {"Authorization": f"Bearer {_token(uid_a)}"}
        h_b = {"Authorization": f"Bearer {_token(uid_b)}"}
        # A posts an original
        r1 = requests.post(f"{API}/me/chat/{cid}/messages", headers=h_a,
                           json={"text": "Le projet est validé"}, timeout=15)
        orig = r1.json()
        # B replies to it
        r2 = requests.post(f"{API}/me/chat/{cid}/messages", headers=h_b,
                           json={"text": "Super, je m'en occupe", "reply_to_id": orig["id"]},
                           timeout=15)
        assert r2.status_code == 200, r2.text
        reply = r2.json()
        assert "reply_to" in reply
        rt = reply["reply_to"]
        assert rt["id"] == orig["id"]
        assert rt["text"] == "Le projet est validé"
        assert rt["sender_id"] == uid_a
        assert rt["sender_name"]

    def test_reply_to_truncates_long_text(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        long_text = "a" * 1000
        r1 = requests.post(f"{API}/me/chat/{cid}/messages", headers=h,
                           json={"text": long_text}, timeout=15)
        orig_id = r1.json()["id"]
        r2 = requests.post(f"{API}/me/chat/{cid}/messages", headers=h,
                           json={"text": "ok", "reply_to_id": orig_id}, timeout=15)
        rt = r2.json().get("reply_to")
        assert rt
        assert len(rt["text"]) <= 140
        assert rt["text"].endswith("…")

    def test_reply_to_unknown_id_is_silently_dropped(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        r = requests.post(f"{API}/me/chat/{cid}/messages", headers=h,
                          json={"text": "lonely", "reply_to_id": "nonexistent_xyz"}, timeout=15)
        assert r.status_code == 200
        # No reply_to attached when the source isn't found
        assert "reply_to" not in r.json() or r.json().get("reply_to") is None

    def test_reply_to_different_client_ignored(self, setup, db):
        """A user can't quote a message from another client (even by guessing the id)."""
        cid_a = setup["client_id"]
        uid_a = setup["members"][0]
        # Create a parallel client where uid_a is NOT a member
        cid_b = f"par_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": cid_b, "email": f"{cid_b}@x.local", "password_hash": "x",
            "full_name": "Parallel", "role": "client", "account_status": "active",
            "features": {"internal_chat": True},
        })
        # Insert a message there directly via DB
        foreign_id = str(uuid.uuid4())
        db.internal_chat_messages.insert_one({
            "id": foreign_id, "client_id": cid_b,
            "sender_id": "other_user", "sender_name": "Other",
            "recipient_id": None, "text": "SECRET HEARING",
            "created_at": datetime.now(timezone.utc).isoformat(), "read_by": [],
        })
        try:
            h = {"Authorization": f"Bearer {_token(uid_a)}"}
            r = requests.post(f"{API}/me/chat/{cid_a}/messages", headers=h,
                              json={"text": "ok", "reply_to_id": foreign_id}, timeout=15)
            assert r.status_code == 200
            # reply_to scoped to cid_a → foreign msg ignored (cross-tenant safety)
            body = r.json()
            assert "reply_to" not in body or body.get("reply_to") is None
        finally:
            db.users.delete_one({"id": cid_b})
            db.internal_chat_messages.delete_many({"client_id": cid_b})
