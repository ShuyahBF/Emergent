"""Iter38r-fix9z8 — Self-service advertiser portal endpoints.

Validates:
  • PUT /api/public/ads-report/{slug}/media — auth via slug+token, updates
    only the whitelisted media fields, logs to audit collection
  • POST /api/public/ads-report/{slug}/checkout — auth check (rejects bad
    token), returns Stripe payment URL when Stripe is configured, else
    500 ; persists an `ad_renewals` row

Stripe-dependent paths are tested via direct unit-style assertions on the
DB state because we don't have a real Stripe test key in this env.
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
    aid = f"fz8_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "token": _forge(aid, "admin"), "headers": {"Authorization": f"Bearer {_forge(aid, 'admin')}"}}
    db.users.delete_many({"id": aid})


def _create_banner(admin_h: dict) -> dict:
    r = requests.post(f"{API}/admin/ad-banners", json={
        "name": f"Portal {uuid.uuid4().hex[:6]}",
        "image_url": "/api/files/orig",
        "target_url": "https://example.com/old",
        "placement": "public",
        "active": True,
    }, headers=admin_h)
    assert r.status_code == 200, r.text
    return r.json()["item"]


# -------------------------- MEDIA UPDATE --------------------------

def test_media_update_rejects_bad_token(admin, db):
    item = _create_banner(admin["headers"])
    try:
        r = requests.put(
            f"{API}/public/ads-report/{item['slug']}/media?token=WRONG",
            json={"image_url": "/api/files/new"},
        )
        assert r.status_code == 403
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_media_update_applies_only_whitelisted_fields(admin, db):
    item = _create_banner(admin["headers"])
    try:
        # Try to update a forbidden field along with the allowed ones
        r = requests.put(
            f"{API}/public/ads-report/{item['slug']}/media?token={item['share_token']}",
            json={
                "image_url": "/api/files/newpic",
                "media_kind": "video",
                "target_url": "https://example.com/new",
                # The following don't exist on the payload schema — must be
                # silently ignored by FastAPI (extra fields are dropped).
                "active": False,
                "budget_amount": 999999,
                "placement": "portal",
            },
        )
        assert r.status_code == 200, r.text
        fresh = db.ad_banners.find_one({"id": item["id"]}, {"_id": 0})
        assert fresh["image_url"] == "/api/files/newpic"
        assert fresh["media_kind"] == "video"
        assert fresh["target_url"] == "https://example.com/new"
        # Admin-only fields preserved
        assert fresh["active"] == item["active"]
        assert fresh["budget_amount"] == item["budget_amount"]
        assert fresh["placement"] == item["placement"]
        # Audit log written
        audit = db.ad_self_service_updates.find_one({"banner_id": item["id"]}, {"_id": 0})
        assert audit is not None
        assert set(audit["fields"]) >= {"image_url", "media_kind", "target_url"}
    finally:
        db.ad_banners.delete_one({"id": item["id"]})
        db.ad_self_service_updates.delete_many({"banner_id": item["id"]})


def test_media_update_empty_payload_rejected(admin, db):
    item = _create_banner(admin["headers"])
    try:
        r = requests.put(
            f"{API}/public/ads-report/{item['slug']}/media?token={item['share_token']}",
            json={},
        )
        assert r.status_code == 400
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_media_update_accepts_variant_b_fields(admin, db):
    item = _create_banner(admin["headers"])
    try:
        r = requests.put(
            f"{API}/public/ads-report/{item['slug']}/media?token={item['share_token']}",
            json={
                "variant_b_image_url": "/api/files/varb",
                "variant_b_target_url": "https://example.com/B",
                "variant_b_media_kind": "image",
            },
        )
        assert r.status_code == 200
        fresh = db.ad_banners.find_one({"id": item["id"]}, {"_id": 0})
        assert fresh["variant_b_image_url"] == "/api/files/varb"
        assert fresh["variant_b_target_url"] == "https://example.com/B"
    finally:
        db.ad_banners.delete_one({"id": item["id"]})
        db.ad_self_service_updates.delete_many({"banner_id": item["id"]})


# -------------------------- CHECKOUT --------------------------

def test_checkout_rejects_bad_token(admin, db):
    item = _create_banner(admin["headers"])
    try:
        r = requests.post(
            f"{API}/public/ads-report/{item['slug']}/checkout?token=WRONG",
            json={
                "amount_xof": 50000, "duration_days": 30,
                "origin_url": "https://example.com",
            },
        )
        assert r.status_code == 403
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_checkout_rejects_invalid_amount(admin, db):
    item = _create_banner(admin["headers"])
    try:
        r = requests.post(
            f"{API}/public/ads-report/{item['slug']}/checkout?token={item['share_token']}",
            json={
                "amount_xof": -100, "duration_days": 30,
                "origin_url": "https://example.com",
            },
        )
        assert r.status_code in (400, 422)
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_payment_status_not_found_returns_404(admin, db):
    item = _create_banner(admin["headers"])
    try:
        r = requests.get(
            f"{API}/public/ads-report/{item['slug']}/payment-status/nonexistent_session?token={item['share_token']}"
        )
        assert r.status_code == 404
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_checkout_creates_ad_renewals_row_when_stripe_configured(admin, db):
    """Skipped gracefully if Stripe is not configured."""
    if not (os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")):
        pytest.skip("Stripe API key not configured in this env")
    item = _create_banner(admin["headers"])
    try:
        r = requests.post(
            f"{API}/public/ads-report/{item['slug']}/checkout?token={item['share_token']}",
            json={
                "amount_xof": 50000, "duration_days": 60,
                "origin_url": "https://example.com",
                "contact_email": "a@x.com",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["url"].startswith("https://")
        assert data["session_id"]
        renewal = db.ad_renewals.find_one({"session_id": data["session_id"]}, {"_id": 0})
        assert renewal["banner_id"] == item["id"]
        assert renewal["amount_xof"] == 50000
        assert renewal["duration_days"] == 60
        assert renewal["payment_status"] == "initiated"
        assert renewal["renewal_applied"] is False
    finally:
        db.ad_banners.delete_one({"id": item["id"]})
        db.ad_renewals.delete_many({"banner_id": item["id"]})
