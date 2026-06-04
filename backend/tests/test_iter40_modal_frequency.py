"""Iter40-modal-frequency — Modal frequency setting + dedicated modal counters.

Validates:
 - Admin can set `modal_frequency` to "session" | "daily" | "always" on a
   public_modal banner (default = "session" when omitted).
 - Invalid `modal_frequency` is rejected (422).
 - Public endpoint echoes `modal_frequency` so the frontend can decide.
 - POST /impression?modal=1 bumps both global AND `modal_impressions`.
 - POST /click?modal=1 bumps both global AND `modal_clicks`.
 - GET /admin/ad-banners/{id}/stats exposes a `modal` block (impressions,
   clicks, ctr_pct, frequency).
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
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
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
def admin_token(db):
    admin_id = f"abmf_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin"), admin_id
    db.users.delete_one({"id": admin_id})
    db.ad_banners.delete_many({"tenant_id": admin_id})


def _create_modal(token: str, freq: str = "session") -> str:
    """Create a public_modal banner with the given frequency, return its id."""
    body = {
        "name": f"ModalFreq {uuid.uuid4().hex[:6]}",
        "image_url": "https://example.com/m.png",
        "target_url": "https://example.com/lp",
        "placement": "public_modal",
        "media_kind": "image",
        "active": True,
        "modal_frequency": freq,
    }
    r = requests.post(
        f"{API}/admin/ad-banners",
        headers={"Authorization": f"Bearer {token}"},
        json=body, timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["item"]["id"]


def test_default_modal_frequency_is_session(admin_token, db):
    """Creating a public_modal banner without modal_frequency defaults to 'session'."""
    token, _ = admin_token
    r = requests.post(
        f"{API}/admin/ad-banners",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": f"DefaultFreq {uuid.uuid4().hex[:6]}",
            "image_url": "https://example.com/d.png",
            "target_url": "https://example.com/lp",
            "placement": "public_modal",
            "media_kind": "image",
            "active": True,
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["item"]["modal_frequency"] == "session"


def test_modal_frequency_accepts_all_three_values(admin_token):
    token, _ = admin_token
    for freq in ("session", "daily", "always"):
        bid = _create_modal(token, freq=freq)
        assert bid


def test_modal_frequency_rejects_invalid(admin_token):
    token, _ = admin_token
    r = requests.post(
        f"{API}/admin/ad-banners",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Bad",
            "image_url": "https://example.com/x.png",
            "target_url": "https://example.com/x",
            "placement": "public_modal",
            "media_kind": "image",
            "modal_frequency": "weekly",  # not allowed
        }, timeout=10,
    )
    assert r.status_code == 422


def test_public_endpoint_echoes_modal_frequency(admin_token, db):
    token, _ = admin_token
    bid = _create_modal(token, freq="daily")
    r = requests.get(f"{API}/public/ad-banners/active?placement=public_modal", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("banner") is not None
    # We're not guaranteed to get THIS specific banner (random pick) but
    # the field must be present.
    assert "modal_frequency" in body["banner"]
    # Cleanup — delete the banner directly so the daily fixture stays clean
    db.ad_banners.delete_one({"id": bid})


def test_impression_modal_flag_bumps_modal_counter(admin_token, db):
    token, _ = admin_token
    bid = _create_modal(token, freq="session")
    # Fire a modal impression
    r = requests.post(f"{API}/public/ad-banners/{bid}/impression?variant=a&modal=1", timeout=10)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True
    # Verify both counters bumped
    doc = db.ad_banners.find_one({"id": bid}, {"_id": 0})
    assert doc["total_impressions"] == 1
    assert doc["modal_impressions"] == 1
    # Now fire a normal (non-modal) impression — only global bumps
    requests.post(f"{API}/public/ad-banners/{bid}/impression?variant=a&modal=0", timeout=10)
    doc = db.ad_banners.find_one({"id": bid}, {"_id": 0})
    assert doc["total_impressions"] == 2
    assert doc["modal_impressions"] == 1  # unchanged


def test_click_modal_flag_bumps_modal_counter(admin_token, db):
    token, _ = admin_token
    bid = _create_modal(token, freq="always")
    r = requests.post(f"{API}/public/ad-banners/{bid}/click?variant=a&modal=1", timeout=10)
    assert r.status_code == 200
    assert r.json().get("ok") is True
    doc = db.ad_banners.find_one({"id": bid}, {"_id": 0})
    assert doc["total_clicks"] == 1
    assert doc["modal_clicks"] == 1


def test_stats_endpoint_exposes_modal_block(admin_token, db):
    token, admin_id = admin_token
    bid = _create_modal(token, freq="daily")
    # Pre-populate counters
    db.ad_banners.update_one(
        {"id": bid},
        {"$inc": {"modal_impressions": 10, "modal_clicks": 2,
                  "total_impressions": 10, "total_clicks": 2}},
    )
    r = requests.get(
        f"{API}/admin/ad-banners/{bid}/stats",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "modal" in body
    assert body["modal"]["impressions"] == 10
    assert body["modal"]["clicks"] == 2
    assert body["modal"]["ctr_pct"] == 20.0
    assert body["modal"]["frequency"] == "daily"
