"""Iter36k — WebSocket end-to-end test for internal chat.

Verifies that:
  - Two users (members of the same client with chat enabled) can connect
    in parallel via wss://...
  - A REST-sent message is broadcasted via WS to BOTH users (incl. sender).
  - The hello/ping/pong flow works.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
import websockets
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/ws/chat"
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
    """Seed a client with chat enabled + 2 tracked users (bridged)."""
    cid = f"ws_client_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": cid, "email": f"{cid}@test.local", "password_hash": "x",
        "full_name": "WS Client", "role": "client",
        "account_status": "active",
        "features": {"internal_chat": True},
    })
    members = []
    for i in range(2):
        uid = f"ws_user_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
            "full_name": f"WS User {i}", "role": "client",
            "account_status": "active",
        })
        db.tracked_users.insert_one({
            "id": f"tu_{uuid.uuid4().hex[:6]}", "client_id": cid,
            "name": f"WS User {i}", "email": f"{uid}@test.local",
            "status": "active", "user_account_id": uid,
        })
        members.append(uid)
    yield {"client_id": cid, "members": members}
    db.users.delete_many({"id": {"$in": [cid, *members]}})
    db.tracked_users.delete_many({"client_id": cid})
    db.internal_chat_messages.delete_many({"client_id": cid})


@pytest.mark.asyncio
async def test_ws_hello_and_ping(setup):
    uid = setup["members"][0]
    url = f"{WS_URL}?token={_token(uid)}"
    async with websockets.connect(url, open_timeout=10) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert hello["type"] == "hello"
        assert hello["user_id"] == uid
        await ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert pong["type"] == "pong"


@pytest.mark.asyncio
async def test_ws_message_broadcast_to_both_users(setup):
    """User A sends via REST → both A and B receive a WS push."""
    cid = setup["client_id"]
    uid_a, uid_b = setup["members"]
    url_a = f"{WS_URL}?token={_token(uid_a)}"
    url_b = f"{WS_URL}?token={_token(uid_b)}"
    async with websockets.connect(url_a, open_timeout=10) as ws_a, \
               websockets.connect(url_b, open_timeout=10) as ws_b:
        # Drain hello frames
        await asyncio.wait_for(ws_a.recv(), timeout=5)
        await asyncio.wait_for(ws_b.recv(), timeout=5)
        # Send via REST as A
        h_a = {"Authorization": f"Bearer {_token(uid_a)}"}
        r = requests.post(f"{API}/me/chat/{cid}/messages", headers=h_a,
                          json={"text": "Bonjour B via WS"}, timeout=15)
        assert r.status_code == 200, r.text
        msg_id = r.json()["id"]
        # Both A and B receive a "message" event
        a_evt = json.loads(await asyncio.wait_for(ws_a.recv(), timeout=5))
        b_evt = json.loads(await asyncio.wait_for(ws_b.recv(), timeout=5))
        assert a_evt["type"] == "message"
        assert b_evt["type"] == "message"
        assert a_evt["message"]["id"] == msg_id
        assert b_evt["message"]["id"] == msg_id
        assert b_evt["client_id"] == cid


@pytest.mark.asyncio
async def test_ws_invalid_token_rejected(setup):
    url = f"{WS_URL}?token=bogus.token.value"
    with pytest.raises(Exception):
        async with websockets.connect(url, open_timeout=5) as ws:
            # Server should close after sending an error
            await asyncio.wait_for(ws.recv(), timeout=5)
            # Server closes; next recv raises
            await asyncio.wait_for(ws.recv(), timeout=5)
