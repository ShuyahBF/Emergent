"""Iter38r-fix9z6 — A/B testing + expiration reminder cron.

Validates:
  • Banner creation accepts ab_enabled + variant_b_* + advertiser_email + reminder fields
  • Public /api/public/ad-banners/active includes active_variant key
  • POST /impression?variant=b bumps total_impressions_b (not _a)
  • POST /click?variant=b returns variant_b_target_url
  • Stats endpoint returns ab.variant_a / ab.variant_b / ab.winner
  • process_expiration_reminders() sends 1 email per banner within window,
    is idempotent (does not re-send on second run), and skips banners
    outside the window or with reminder disabled.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
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
    aid = f"fz6_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "token": _forge(aid, "admin"), "headers": {"Authorization": f"Bearer {_forge(aid, 'admin')}"}}
    db.users.delete_many({"id": aid})


def _create_ab(admin_h: dict, db, ab=True) -> dict:
    payload = {
        "name": f"AB {uuid.uuid4().hex[:6]}",
        "image_url": "/api/files/img-a",
        "target_url": "https://example.com/a",
        "media_kind": "image",
        "placement": "public",
        "active": True,
        "ab_enabled": ab,
        "variant_b_image_url": "/api/files/img-b",
        "variant_b_media_kind": "image",
        "variant_b_target_url": "https://example.com/b",
    }
    r = requests.post(f"{API}/admin/ad-banners", json=payload, headers=admin_h)
    assert r.status_code == 200, r.text
    return r.json()["item"]


# -------------------------- A/B TESTING --------------------------

def test_ab_create_persists_variant_b_and_zero_counters(admin, db):
    item = _create_ab(admin["headers"], db, ab=True)
    try:
        assert item["ab_enabled"] is True
        assert item["variant_b_image_url"] == "/api/files/img-b"
        assert item["variant_b_target_url"] == "https://example.com/b"
        assert item["total_impressions_a"] == 0
        assert item["total_impressions_b"] == 0
        assert item["total_clicks_a"] == 0
        assert item["total_clicks_b"] == 0
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_ab_impression_variant_b_only_bumps_b(admin, db):
    item = _create_ab(admin["headers"], db, ab=True)
    try:
        r = requests.post(f"{API}/public/ad-banners/{item['id']}/impression?variant=b")
        assert r.status_code == 200, r.text
        r2 = requests.post(f"{API}/public/ad-banners/{item['id']}/impression?variant=a")
        assert r2.status_code == 200
        fresh = db.ad_banners.find_one({"id": item["id"]}, {"_id": 0})
        assert fresh["total_impressions_b"] == 1
        assert fresh["total_impressions_a"] == 1
        assert fresh["total_impressions"] == 2
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_ab_click_variant_b_returns_variant_b_target(admin, db):
    item = _create_ab(admin["headers"], db, ab=True)
    try:
        r = requests.post(f"{API}/public/ad-banners/{item['id']}/click?variant=b")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["target_url"] == "https://example.com/b"
        fresh = db.ad_banners.find_one({"id": item["id"]}, {"_id": 0})
        assert fresh["total_clicks_b"] == 1
        assert fresh["total_clicks_a"] == 0
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_ab_invalid_variant_param_rejected():
    r = requests.post(f"{API}/public/ad-banners/x/impression?variant=z")
    assert r.status_code in (400, 422)


def test_ab_stats_endpoint_returns_per_variant_breakdown_and_winner(admin, db):
    item = _create_ab(admin["headers"], db, ab=True)
    try:
        # Simulate 40 impressions + 5 clicks on A, 40 imps + 2 clicks on B
        for _ in range(40):
            requests.post(f"{API}/public/ad-banners/{item['id']}/impression?variant=a")
            requests.post(f"{API}/public/ad-banners/{item['id']}/impression?variant=b")
        for _ in range(5):
            requests.post(f"{API}/public/ad-banners/{item['id']}/click?variant=a")
        for _ in range(2):
            requests.post(f"{API}/public/ad-banners/{item['id']}/click?variant=b")

        r = requests.get(f"{API}/admin/ad-banners/{item['id']}/stats", headers=admin["headers"])
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["ab"]["enabled"] is True
        assert s["ab"]["variant_a"]["impressions"] == 40
        assert s["ab"]["variant_a"]["clicks"] == 5
        assert s["ab"]["variant_b"]["impressions"] == 40
        assert s["ab"]["variant_b"]["clicks"] == 2
        assert s["ab"]["variant_a"]["ctr_pct"] > s["ab"]["variant_b"]["ctr_pct"]
        assert s["ab"]["winner"] == "a"
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_ab_disabled_returns_only_variant_a(admin, db):
    item = _create_ab(admin["headers"], db, ab=False)
    try:
        # Even with ab_enabled=False, public view should return variant a
        r = requests.get(f"{API}/public/ad-banners/active?placement=public")
        assert r.status_code == 200
        b = r.json().get("banner")
        if b and b.get("id") == item["id"]:
            assert b["active_variant"] == "a"
            assert b["image_url"] == "/api/files/img-a"
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


# -------------------------- REMINDER CRON --------------------------

@pytest.mark.asyncio
async def test_expiration_reminder_sends_within_window_idempotent():
    """End-to-end test of process_expiration_reminders using a stub sender."""
    import sys
    sys.path.insert(0, "/app/backend")
    from routes.ad_banners import process_expiration_reminders
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db_ = mongo[os.environ["DB_NAME"]]

    today = date.today()
    in_2_days = (today + timedelta(days=2)).isoformat()
    in_10_days = (today + timedelta(days=10)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()

    # 3 banners: 1 within window, 1 outside, 1 with reminder disabled
    banners = [
        {"id": str(uuid.uuid4()), "name": "Win", "slug": "win", "share_token": "tw",
         "advertiser_email": "win@x.com", "advertiser_name": "Win",
         "expiration_date": in_2_days,
         "reminder_email_enabled": True, "reminder_days_before": 3,
         "currency": "XOF", "budget_amount": 1000, "amount_spent": 200,
         "total_impressions": 100, "total_clicks": 5},
        {"id": str(uuid.uuid4()), "name": "Far", "slug": "far", "share_token": "tf",
         "advertiser_email": "far@x.com",
         "expiration_date": in_10_days,
         "reminder_email_enabled": True, "reminder_days_before": 3,
         "currency": "XOF"},
        {"id": str(uuid.uuid4()), "name": "Off", "slug": "off", "share_token": "to",
         "advertiser_email": "off@x.com",
         "expiration_date": in_2_days,
         "reminder_email_enabled": False, "reminder_days_before": 3,
         "currency": "XOF"},
        # Past expiration → must skip
        {"id": str(uuid.uuid4()), "name": "Old", "slug": "old", "share_token": "told",
         "advertiser_email": "old@x.com",
         "expiration_date": yesterday,
         "reminder_email_enabled": True, "reminder_days_before": 3,
         "currency": "XOF"},
    ]
    inserted_ids = [b["id"] for b in banners]
    await db_.ad_banners.insert_many([b.copy() for b in banners])
    try:
        captured = []
        async def stub_send(to, subject, html, text):
            captured.append({"to": to, "subject": subject, "text": text[:80]})
            return True

        res = await process_expiration_reminders(
            db_,
            send_email_fn=stub_send,
            public_base_url="https://example.com",
        )
        assert len(res["sent"]) == 1, res
        assert res["sent"][0]["to_email"] == "win@x.com"
        assert "email" in res["sent"][0]["channels"]
        assert len(captured) == 1
        assert "Win" in captured[0]["subject"]

        # Second run → 0 sent (idempotent)
        captured.clear()
        res2 = await process_expiration_reminders(
            db_,
            send_email_fn=stub_send,
            public_base_url="https://example.com",
        )
        assert len(res2["sent"]) == 0
        assert len(captured) == 0
        # Banner should be skipped because already sent
        assert any(s.get("reason") == "already_sent" for s in res2["skipped"])
    finally:
        await db_.ad_banners.delete_many({"id": {"$in": inserted_ids}})


def test_admin_can_trigger_reminder_cron_manually(admin):
    r = requests.post(f"{API}/admin/ad-banners/run-reminder-cron", headers=admin["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert "sent" in data and "skipped" in data and "errored" in data
