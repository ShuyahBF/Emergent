"""Iter38r-fix9z7 — WhatsApp reminder channel + live admin WebSocket.

Validates:
  • process_expiration_reminders() routes to send_email_fn AND send_whatsapp_fn
    when both reminder_email_enabled + reminder_wa_enabled are on
  • A banner with only reminder_wa_enabled=True (no email) still triggers WA
  • Banner that's WA-only without phone is gracefully skipped
  • WebSocket /api/ws/ad-banners-live sends a snapshot on connect and
    broadcasts a real-time "impression" event when /impression is called.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
import websockets
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
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
    aid = f"fz7_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "token": _forge(aid, "admin"), "headers": {"Authorization": f"Bearer {_forge(aid, 'admin')}"}}
    db.users.delete_many({"id": aid})


# -------------------------- WHATSAPP REMINDER --------------------------

@pytest.mark.asyncio
async def test_reminder_sends_email_and_wa_when_both_enabled():
    import sys
    sys.path.insert(0, "/app/backend")
    from routes.ad_banners import process_expiration_reminders
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db_ = mongo[os.environ["DB_NAME"]]
    today = date.today()
    in_2 = (today + timedelta(days=2)).isoformat()

    banner = {
        "id": str(uuid.uuid4()), "name": "Both", "slug": "both", "share_token": "tk",
        "advertiser_email": "both@x.com", "advertiser_phone": "+22500001111",
        "advertiser_name": "Both", "expiration_date": in_2,
        "reminder_email_enabled": True, "reminder_wa_enabled": True,
        "reminder_days_before": 3, "currency": "XOF",
    }
    await db_.ad_banners.insert_one(banner.copy())
    try:
        emails, wa_msgs = [], []
        async def stub_email(to, s, h, t):
            emails.append(to); return True
        async def stub_wa(to, text):
            wa_msgs.append({"to": to, "text": text}); return {"ok": True}

        res = await process_expiration_reminders(
            db_, send_email_fn=stub_email, send_whatsapp_fn=stub_wa,
            public_base_url="https://example.com",
        )
        assert len(res["sent"]) == 1
        ch = res["sent"][0]["channels"]
        assert "email" in ch and "wa" in ch
        assert emails == ["both@x.com"]
        assert wa_msgs[0]["to"] == "+22500001111"
        assert "Both" in wa_msgs[0]["text"]
        assert "https://example.com/ads/both?token=tk" in wa_msgs[0]["text"]
    finally:
        await db_.ad_banners.delete_one({"id": banner["id"]})


@pytest.mark.asyncio
async def test_reminder_wa_only_no_email_required():
    import sys
    sys.path.insert(0, "/app/backend")
    from routes.ad_banners import process_expiration_reminders
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db_ = mongo[os.environ["DB_NAME"]]
    today = date.today()
    in_1 = (today + timedelta(days=1)).isoformat()

    banner = {
        "id": str(uuid.uuid4()), "name": "WAOnly", "slug": "waonly", "share_token": "twk",
        "advertiser_email": "", "advertiser_phone": "+22500002222",
        "expiration_date": in_1,
        "reminder_email_enabled": False, "reminder_wa_enabled": True,
        "reminder_days_before": 3, "currency": "XOF",
    }
    await db_.ad_banners.insert_one(banner.copy())
    try:
        wa_msgs = []
        async def stub_email(to, s, h, t):
            return True  # should NOT be called
        async def stub_wa(to, text):
            wa_msgs.append(to); return True

        res = await process_expiration_reminders(
            db_, send_email_fn=stub_email, send_whatsapp_fn=stub_wa,
            public_base_url="https://example.com",
        )
        assert len(res["sent"]) == 1
        assert res["sent"][0]["channels"] == ["wa"]
        assert res["sent"][0]["to_email"] is None
        assert res["sent"][0]["to_wa"] == "+22500002222"
        assert len(wa_msgs) == 1
    finally:
        await db_.ad_banners.delete_one({"id": banner["id"]})


@pytest.mark.asyncio
async def test_reminder_wa_enabled_but_no_phone_is_skipped_silently():
    import sys
    sys.path.insert(0, "/app/backend")
    from routes.ad_banners import process_expiration_reminders
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db_ = mongo[os.environ["DB_NAME"]]
    today = date.today()
    in_2 = (today + timedelta(days=2)).isoformat()

    banner = {
        "id": str(uuid.uuid4()), "name": "NoChan", "slug": "noc", "share_token": "tnoc",
        "advertiser_email": "", "advertiser_phone": "",
        "expiration_date": in_2,
        "reminder_email_enabled": False, "reminder_wa_enabled": True,
        "reminder_days_before": 3, "currency": "XOF",
    }
    await db_.ad_banners.insert_one(banner.copy())
    try:
        async def stub_email(*a, **k): return True
        async def stub_wa(*a, **k): return True

        res = await process_expiration_reminders(
            db_, send_email_fn=stub_email, send_whatsapp_fn=stub_wa,
        )
        # No channels delivered → no row in sent
        assert all(s["channels"] for s in res["sent"]), res
    finally:
        await db_.ad_banners.delete_one({"id": banner["id"]})


# -------------------------- WEBSOCKET LIVE --------------------------

@pytest.mark.asyncio
async def test_ws_ad_banners_live_snapshot_and_broadcast(admin, db):
    """Connect to /api/ws/ad-banners-live, expect snapshot + impression event."""
    banner = {
        "id": str(uuid.uuid4()), "name": "WS Test", "advertiser_name": "WS",
        "image_url": "/api/files/x", "target_url": "https://x.test",
        "media_kind": "image", "active": True, "placement": "public",
        "total_impressions": 0, "total_clicks": 0,
        "total_impressions_a": 0, "total_impressions_b": 0,
        "total_clicks_a": 0, "total_clicks_b": 0,
        "amount_spent": 0, "budget_amount": 1000, "currency": "XOF",
        "ab_enabled": False, "slug": "wstest", "share_token": "stws",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.ad_banners.insert_one(banner.copy())
    ws_url = f"{WS_BASE}/api/ws/ad-banners-live?token={admin['token']}"
    try:
        async with websockets.connect(ws_url) as ws:
            # 1) Expect a snapshot first
            snap_msg = await asyncio.wait_for(ws.recv(), timeout=5)
            snap = json.loads(snap_msg)
            assert snap["event"] == "snapshot"
            assert isinstance(snap["items"], list)
            ids = [i["id"] for i in snap["items"]]
            assert banner["id"] in ids
            # 2) Trigger an impression
            r = requests.post(f"{API}/public/ad-banners/{banner['id']}/impression?variant=a")
            assert r.status_code == 200
            # 3) Receive the broadcast
            evt_msg = await asyncio.wait_for(ws.recv(), timeout=5)
            evt = json.loads(evt_msg)
            assert evt["event"] == "impression"
            assert evt["banner_id"] == banner["id"]
            assert evt["variant"] == "a"
            assert evt["total_impressions"] == 1
            assert evt["total_impressions_a"] == 1
            assert evt["total_impressions_b"] == 0
            # 4) And on click
            r2 = requests.post(f"{API}/public/ad-banners/{banner['id']}/click?variant=b")
            assert r2.status_code == 200
            evt2_msg = await asyncio.wait_for(ws.recv(), timeout=5)
            evt2 = json.loads(evt2_msg)
            assert evt2["event"] == "click"
            assert evt2["variant"] == "b"
            assert evt2["total_clicks_b"] == 1
    finally:
        db.ad_banners.delete_one({"id": banner["id"]})


@pytest.mark.asyncio
async def test_ws_rejects_invalid_token():
    ws_url = f"{WS_BASE}/api/ws/ad-banners-live?token=invalid.jwt.token"
    with pytest.raises(Exception):
        async with websockets.connect(ws_url) as ws:
            await asyncio.wait_for(ws.recv(), timeout=3)


@pytest.mark.asyncio
async def test_ws_rejects_non_admin(db):
    uid = f"u_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        tok = _forge(uid, "client")
        ws_url = f"{WS_BASE}/api/ws/ad-banners-live?token={tok}"
        with pytest.raises(Exception):
            async with websockets.connect(ws_url) as ws:
                await asyncio.wait_for(ws.recv(), timeout=3)
    finally:
        db.users.delete_one({"id": uid})
