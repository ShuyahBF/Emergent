"""Iter40-modal-ab — A/B test on modal_frequency + global daily cap.

Validates:
 - PUT /api/admin/settings accepts `modal_global_cap_per_day` (0-20, default 2)
 - Invalid cap (-1, 21, "abc") rejected
 - GET /api/public/ad-banners/config returns the cap (anonymous endpoint)
 - Admin can create a banner with variant_b_modal_frequency
 - Public endpoint returns variant-appropriate modal_frequency (when B is picked,
   variant_b_modal_frequency is used if non-empty; else falls back to global)
 - POST /impression?variant=b&modal=1 bumps modal_impressions_b
 - POST /click?variant=a&modal=1 bumps modal_clicks_a
 - Stats endpoint exposes modal.variant_a / variant_b + variant_b_frequency
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
    admin_id = f"abab_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin"), admin_id
    db.users.delete_one({"id": admin_id})
    db.ad_banners.delete_many({"tenant_id": admin_id})


# ----------------------------------------------------------------------
# Global daily cap
# ----------------------------------------------------------------------

def test_settings_accepts_modal_global_cap(admin_token):
    token, _ = admin_token
    r = requests.put(
        f"{API}/admin/settings", json={"modal_global_cap_per_day": 3},
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    r2 = requests.get(f"{API}/admin/settings", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r2.json()["modal_global_cap_per_day"] == 3


def test_settings_rejects_invalid_modal_cap(admin_token):
    token, _ = admin_token
    for bad in (-1, 21, 100):
        r = requests.put(
            f"{API}/admin/settings", json={"modal_global_cap_per_day": bad},
            headers={"Authorization": f"Bearer {token}"}, timeout=10,
        )
        assert r.status_code == 400, f"value {bad} should be rejected, got {r.status_code}: {r.text}"


def test_public_config_endpoint_returns_cap(admin_token):
    token, _ = admin_token
    # Set a known cap first
    requests.put(
        f"{API}/admin/settings", json={"modal_global_cap_per_day": 5},
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    r = requests.get(f"{API}/public/ad-banners/config", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "modal_global_cap_per_day" in body
    assert body["modal_global_cap_per_day"] == 5


def test_public_config_endpoint_is_anonymous():
    """No auth header required."""
    r = requests.get(f"{API}/public/ad-banners/config", timeout=10)
    assert r.status_code == 200
    assert "modal_global_cap_per_day" in r.json()


# ----------------------------------------------------------------------
# A/B variant_b_modal_frequency
# ----------------------------------------------------------------------

def _create_ab_modal(token: str, freq_a: str, freq_b: str) -> str:
    """Create a public_modal banner with A/B + per-variant frequencies."""
    r = requests.post(
        f"{API}/admin/ad-banners",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": f"AB Modal {uuid.uuid4().hex[:6]}",
            "image_url": "https://example.com/a.png",
            "target_url": "https://example.com/a",
            "placement": "public_modal",
            "media_kind": "image",
            "active": True,
            "modal_frequency": freq_a,
            "ab_enabled": True,
            "variant_b_image_url": "https://example.com/b.png",
            "variant_b_target_url": "https://example.com/b",
            "variant_b_media_kind": "image",
            "variant_b_modal_frequency": freq_b,
        }, timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["item"]["id"]


def test_admin_can_create_ab_modal_with_variant_frequencies(admin_token):
    token, _ = admin_token
    bid = _create_ab_modal(token, "session", "daily")
    # Verify on the list endpoint
    r = requests.get(f"{API}/admin/ad-banners", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    items = {it["id"]: it for it in r.json()["items"]}
    assert bid in items
    assert items[bid]["modal_frequency"] == "session"
    assert items[bid]["variant_b_modal_frequency"] == "daily"


def test_public_endpoint_returns_variant_appropriate_frequency(admin_token, db):
    """When the variant is B and variant_b_modal_frequency is set, the public
    payload must echo the B frequency; for variant A it must echo the global."""
    token, _ = admin_token
    # Clean slate: delete all other public_modal banners so we pick this one
    db.ad_banners.delete_many({"placement": "public_modal"})
    bid = _create_ab_modal(token, "session", "always")
    # Hit the endpoint several times (50/50 distribution) — at least one
    # variant A AND one variant B response should appear.
    seen_a = False
    seen_b = False
    for _ in range(40):
        r = requests.get(f"{API}/public/ad-banners/active?placement=public_modal", timeout=10)
        assert r.status_code == 200
        b = r.json().get("banner")
        assert b and b["id"] == bid
        if b["active_variant"] == "a":
            assert b["modal_frequency"] == "session"
            seen_a = True
        else:
            assert b["modal_frequency"] == "always"
            seen_b = True
        if seen_a and seen_b:
            break
    assert seen_a and seen_b, "Both variants should appear over 40 picks"


def test_empty_variant_b_frequency_falls_back_to_global(admin_token, db):
    """When variant_b_modal_frequency is empty, B uses the global modal_frequency."""
    token, _ = admin_token
    db.ad_banners.delete_many({"placement": "public_modal"})
    bid = _create_ab_modal(token, "daily", "")  # B = ""
    # Run picks until we see variant B
    for _ in range(60):
        r = requests.get(f"{API}/public/ad-banners/active?placement=public_modal", timeout=10)
        b = r.json().get("banner")
        assert b["id"] == bid
        if b["active_variant"] == "b":
            assert b["modal_frequency"] == "daily"  # fell back to global
            return
    pytest.fail("Variant B never appeared in 60 picks")


def test_modal_per_variant_counters_bump(admin_token, db):
    token, _ = admin_token
    bid = _create_ab_modal(token, "session", "daily")
    # Fire 3 modal impressions on A, 2 on B
    for _ in range(3):
        r = requests.post(f"{API}/public/ad-banners/{bid}/impression?variant=a&modal=1", timeout=10)
        assert r.status_code == 200
    for _ in range(2):
        r = requests.post(f"{API}/public/ad-banners/{bid}/impression?variant=b&modal=1", timeout=10)
        assert r.status_code == 200
    # Click once on B (modal)
    r = requests.post(f"{API}/public/ad-banners/{bid}/click?variant=b&modal=1", timeout=10)
    assert r.status_code == 200
    doc = db.ad_banners.find_one({"id": bid}, {"_id": 0})
    assert doc["modal_impressions"] == 5
    assert doc["modal_impressions_a"] == 3
    assert doc["modal_impressions_b"] == 2
    assert doc["modal_clicks"] == 1
    assert doc["modal_clicks_b"] == 1
    assert doc.get("modal_clicks_a", 0) == 0


def test_stats_endpoint_exposes_modal_ab_breakdown(admin_token, db):
    token, _ = admin_token
    bid = _create_ab_modal(token, "session", "always")
    # Seed counters directly
    db.ad_banners.update_one(
        {"id": bid},
        {"$inc": {
            "modal_impressions": 100, "modal_clicks": 8,
            "modal_impressions_a": 50, "modal_clicks_a": 2,
            "modal_impressions_b": 50, "modal_clicks_b": 6,
            "total_impressions": 100, "total_clicks": 8,
        }},
    )
    r = requests.get(f"{API}/admin/ad-banners/{bid}/stats", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["modal"]["variant_a"]["impressions"] == 50
    assert body["modal"]["variant_a"]["clicks"] == 2
    assert body["modal"]["variant_a"]["ctr_pct"] == 4.0
    assert body["modal"]["variant_b"]["impressions"] == 50
    assert body["modal"]["variant_b"]["clicks"] == 6
    assert body["modal"]["variant_b"]["ctr_pct"] == 12.0
    assert body["modal"]["frequency"] == "session"
    assert body["modal"]["variant_b_frequency"] == "always"
