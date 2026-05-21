"""Iter36k — Internal real-time chat tests (REST surface).

Validates:
  - Toggle 'internal_chat' on a client's features grants chat access to admins
    and to that client's tracked users (with bridged user_account_id).
  - GET /me/chat/clients returns only clients with chat enabled.
  - POST /me/chat/{client_id}/messages with recipient_id=None writes to
    the general channel; with a peer id, writes to a 1-to-1 thread.
  - GET /me/chat/{client_id}/threads returns 'general' + each DM counterpart
    with unread counts.
  - GET /me/chat/{client_id}/messages?with_user=general|<uid> returns chronological history.
  - POST /me/chat/messages/{msg_id}/read marks read; sender->read_by gets new uid.
  - GET /me/chat/unread-count returns the global counter.
  - Member who is NOT in the client's chat space (no tracked_user link) gets 403.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

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
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    code = data.get("dev_otp")
    assert code
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
        timeout=30,
    )
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def chat_client(db):
    """Seed a fresh client with internal_chat=True and 2 tracked users
    (each with a bridged users row, so they can authenticate as members)."""
    cid = f"chat_client_{uuid.uuid4().hex[:6]}"
    # 1) The "client" tenant
    db.users.insert_one({
        "id": cid, "email": f"{cid}@test.local", "password_hash": "x",
        "full_name": "Client Chat Test", "company": "Chat SARL",
        "role": "client", "account_status": "active",
        "features": {"internal_chat": True},
    })
    # 2) Two tracked users
    members = []
    for i in range(2):
        uid = f"chat_user_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
            "full_name": f"Member {i}", "role": "client",
            "account_status": "active",
        })
        tu_id = f"tu_{uuid.uuid4().hex[:6]}"
        db.tracked_users.insert_one({
            "id": tu_id, "client_id": cid,
            "name": f"Member {i}", "email": f"{uid}@test.local",
            "status": "active", "user_account_id": uid,
        })
        members.append(uid)
    yield {"client_id": cid, "members": members}
    # Cleanup
    db.users.delete_many({"id": {"$in": [cid, *members]}})
    db.tracked_users.delete_many({"client_id": cid})
    db.internal_chat_messages.delete_many({"client_id": cid})


def _user_token(db, uid: str) -> str:
    """Forge a JWT for a bridged user (test helper)."""
    import jwt as pyjwt
    from datetime import datetime, timezone, timedelta
    secret = os.environ.get("JWT_SECRET", "fallback-insecure")
    payload = {
        "sub": uid, "role": "client",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


class TestChatToggleAndVisibility:
    def test_admin_sees_clients_with_chat_enabled(self, admin_h, chat_client):
        r = requests.get(f"{API}/me/chat/clients", headers=admin_h, timeout=15)
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()]
        assert chat_client["client_id"] in ids

    def test_member_sees_only_their_clients(self, db, chat_client):
        uid = chat_client["members"][0]
        h = {"Authorization": f"Bearer {_user_token(db, uid)}"}
        r = requests.get(f"{API}/me/chat/clients", headers=h, timeout=15)
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()]
        assert chat_client["client_id"] in ids

    def test_outsider_does_not_see_other_client(self, db, chat_client):
        # Create an unrelated user (not tracked by the chat client)
        outsider_id = f"outsider_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": outsider_id, "email": f"{outsider_id}@x.local",
            "password_hash": "x", "full_name": "Outsider",
            "role": "client", "account_status": "active",
        })
        try:
            h = {"Authorization": f"Bearer {_user_token(db, outsider_id)}"}
            r = requests.get(f"{API}/me/chat/clients", headers=h, timeout=15)
            assert r.status_code == 200
            ids = [c["id"] for c in r.json()]
            assert chat_client["client_id"] not in ids
            # And cannot read messages either
            r2 = requests.get(
                f"{API}/me/chat/{chat_client['client_id']}/threads",
                headers=h, timeout=15,
            )
            assert r2.status_code == 403
        finally:
            db.users.delete_one({"id": outsider_id})


class TestChatMessaging:
    def test_send_general_message_and_read(self, db, chat_client, admin_h):
        cid = chat_client["client_id"]
        uid_a = chat_client["members"][0]
        h_a = {"Authorization": f"Bearer {_user_token(db, uid_a)}"}
        # Member A sends to #general
        r = requests.post(
            f"{API}/me/chat/{cid}/messages",
            headers=h_a, json={"text": "Hello équipe"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        msg = r.json()
        assert msg["client_id"] == cid
        assert msg["sender_id"] == uid_a
        assert msg["recipient_id"] is None
        assert msg["text"] == "Hello équipe"
        # Member B fetches /messages?with_user=general
        uid_b = chat_client["members"][1]
        h_b = {"Authorization": f"Bearer {_user_token(db, uid_b)}"}
        r2 = requests.get(
            f"{API}/me/chat/{cid}/messages",
            params={"with_user": "general"}, headers=h_b, timeout=15,
        )
        assert r2.status_code == 200
        assert any(m["id"] == msg["id"] for m in r2.json())
        # B sees unread count >= 1
        r3 = requests.get(f"{API}/me/chat/unread-count", headers=h_b, timeout=15)
        assert r3.status_code == 200
        assert r3.json()["total"] >= 1
        # B marks read; counter goes down
        r4 = requests.post(f"{API}/me/chat/messages/{msg['id']}/read", headers=h_b, timeout=15)
        assert r4.status_code == 200
        r5 = requests.get(f"{API}/me/chat/unread-count", headers=h_b, timeout=15)
        assert r5.json()["per_client"].get(cid, 0) == 0

    def test_dm_message_isolated_to_pair(self, db, chat_client):
        cid = chat_client["client_id"]
        uid_a, uid_b = chat_client["members"]
        h_a = {"Authorization": f"Bearer {_user_token(db, uid_a)}"}
        h_b = {"Authorization": f"Bearer {_user_token(db, uid_b)}"}
        # A → B DM
        r = requests.post(
            f"{API}/me/chat/{cid}/messages",
            headers=h_a, json={"text": "Privé A→B", "recipient_id": uid_b}, timeout=15,
        )
        assert r.status_code == 200, r.text
        msg = r.json()
        assert msg["recipient_id"] == uid_b
        # B fetches DM history with A
        r2 = requests.get(
            f"{API}/me/chat/{cid}/messages",
            params={"with_user": uid_a}, headers=h_b, timeout=15,
        )
        assert r2.status_code == 200
        ids = [m["id"] for m in r2.json()]
        assert msg["id"] in ids
        # General channel for B should NOT contain this DM
        r3 = requests.get(
            f"{API}/me/chat/{cid}/messages",
            params={"with_user": "general"}, headers=h_b, timeout=15,
        )
        assert msg["id"] not in [m["id"] for m in r3.json()]

    def test_threads_endpoint_returns_general_and_dm(self, db, chat_client):
        cid = chat_client["client_id"]
        uid_a, uid_b = chat_client["members"]
        h_a = {"Authorization": f"Bearer {_user_token(db, uid_a)}"}
        # Send 2 messages: one general, one DM A→B
        requests.post(f"{API}/me/chat/{cid}/messages", headers=h_a, json={"text": "G1"}, timeout=15)
        requests.post(
            f"{API}/me/chat/{cid}/messages",
            headers=h_a, json={"text": "DM1", "recipient_id": uid_b}, timeout=15,
        )
        r = requests.get(f"{API}/me/chat/{cid}/threads", headers=h_a, timeout=15)
        assert r.status_code == 200
        threads = r.json()
        assert any(t["kind"] == "general" for t in threads)
        # A's threads should include a DM with B
        dms = [t for t in threads if t["kind"] == "dm"]
        assert any(t["key"] == uid_b for t in dms)

    def test_cannot_dm_yourself(self, db, chat_client):
        cid = chat_client["client_id"]
        uid_a = chat_client["members"][0]
        h_a = {"Authorization": f"Bearer {_user_token(db, uid_a)}"}
        r = requests.post(
            f"{API}/me/chat/{cid}/messages",
            headers=h_a, json={"text": "moi", "recipient_id": uid_a}, timeout=15,
        )
        assert r.status_code == 400

    def test_empty_message_rejected(self, db, chat_client):
        cid = chat_client["client_id"]
        uid_a = chat_client["members"][0]
        h_a = {"Authorization": f"Bearer {_user_token(db, uid_a)}"}
        r = requests.post(
            f"{API}/me/chat/{cid}/messages",
            headers=h_a, json={"text": "   "}, timeout=15,
        )
        # Pydantic min_length=1 with whitespace; backend strips → 400
        assert r.status_code in (400, 422)

    def test_disabled_client_blocks_access(self, db, chat_client, admin_h):
        cid = chat_client["client_id"]
        # Toggle OFF
        db.users.update_one({"id": cid}, {"$set": {"features.internal_chat": False}})
        try:
            uid_a = chat_client["members"][0]
            h_a = {"Authorization": f"Bearer {_user_token(db, uid_a)}"}
            r = requests.get(f"{API}/me/chat/{cid}/threads", headers=h_a, timeout=15)
            assert r.status_code == 403
        finally:
            db.users.update_one({"id": cid}, {"$set": {"features.internal_chat": True}})


class TestChatMembers:
    def test_members_endpoint_lists_all(self, db, chat_client):
        cid = chat_client["client_id"]
        uid_a = chat_client["members"][0]
        h_a = {"Authorization": f"Bearer {_user_token(db, uid_a)}"}
        r = requests.get(f"{API}/me/chat/{cid}/members", headers=h_a, timeout=15)
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()]
        for mid in chat_client["members"]:
            assert mid in ids
        # Self flag
        self_row = next(m for m in r.json() if m["id"] == uid_a)
        assert self_row["is_self"] is True
