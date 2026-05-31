"""Iter38r-fix9z5 — Ad banner sizing controls + renewal + AI cost chart.

Tests the new admin/public endpoints introduced this iteration:
  • banner sizing fields persisted + returned in public + admin views
  • POST /api/public/ads-report/{slug}/renew creates ad_renewal_requests
  • GET /api/admin/ad-renewal-requests lists pending requests
  • POST /api/admin/ad-renewal-requests/{id}/mark-handled transitions status
  • GET /api/admin/ai-costs/monthly returns zero-filled monthly series
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
    aid = f"fz5_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "token": _forge(aid, "admin"), "headers": {"Authorization": f"Bearer {_forge(aid, 'admin')}"}}
    db.users.delete_many({"id": aid})


def _create_banner(admin_h: dict, extras: dict | None = None) -> dict:
    payload = {
        "name": f"Test {uuid.uuid4().hex[:6]}",
        "image_url": "/api/files/test-id",
        "target_url": "https://example.com",
        "placement": "public",
        "active": True,
    }
    if extras:
        payload.update(extras)
    r = requests.post(f"{API}/admin/ad-banners", json=payload, headers=admin_h)
    assert r.status_code == 200, r.text
    return r.json()["item"]


# -------------------------- SIZING FIELDS --------------------------

def test_banner_create_defaults_sizing_fields(admin, db):
    item = _create_banner(admin["headers"])
    try:
        assert item["display_mode"] == "auto"
        assert item["aspect_ratio"] == "16:9"
        assert item["width_pct"] == 100
        assert item["height_px"] == 80
        assert item["width_px"] == 728
        assert item["object_fit"] == "cover"
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_banner_create_with_custom_sizing(admin, db):
    item = _create_banner(admin["headers"], {
        "display_mode": "ratio",
        "aspect_ratio": "21:9",
        "width_pct": 80,
        "object_fit": "contain",
    })
    try:
        assert item["display_mode"] == "ratio"
        assert item["aspect_ratio"] == "21:9"
        assert item["width_pct"] == 80
        assert item["object_fit"] == "contain"
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_banner_update_sizing_fields(admin, db):
    item = _create_banner(admin["headers"])
    try:
        r = requests.put(
            f"{API}/admin/ad-banners/{item['id']}",
            json={"display_mode": "fixed", "width_px": 1200, "height_px": 250, "object_fit": "fill"},
            headers=admin["headers"],
        )
        assert r.status_code == 200, r.text
        updated = r.json()["item"]
        assert updated["display_mode"] == "fixed"
        assert updated["width_px"] == 1200
        assert updated["height_px"] == 250
        assert updated["object_fit"] == "fill"
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


def test_banner_sizing_validation_rejects_invalid_mode(admin):
    r = requests.post(
        f"{API}/admin/ad-banners",
        json={
            "name": "x", "image_url": "/api/files/x", "target_url": "https://x",
            "display_mode": "totally_invalid",
        },
        headers=admin["headers"],
    )
    assert r.status_code in (400, 422)


def test_public_banner_returns_sizing_for_renderer(admin, db):
    item = _create_banner(admin["headers"], {
        "display_mode": "percentage", "width_pct": 75, "height_px": 120,
        "object_fit": "contain",
    })
    try:
        r = requests.get(f"{API}/public/ad-banners/active?placement=public")
        assert r.status_code == 200, r.text
        b = r.json().get("banner")
        # Banner may or may not be ours (rotation), but if it is, fields should be set.
        if b and b.get("id") == item["id"]:
            assert b["display_mode"] == "percentage"
            assert b["width_pct"] == 75
            assert b["height_px"] == 120
            assert b["object_fit"] == "contain"
    finally:
        db.ad_banners.delete_one({"id": item["id"]})


# -------------------------- RENEWAL ENDPOINTS --------------------------

def test_renewal_request_creates_row_and_admin_can_handle(admin, db):
    item = _create_banner(admin["headers"])
    slug = item["slug"]
    token = item["share_token"]
    try:
        # 1) Bad token → 403
        r_bad = requests.post(
            f"{API}/public/ads-report/{slug}/renew?token=WRONG",
            json={"contact_email": "x@x.com", "new_budget": 5000, "target_duration_days": 30},
        )
        assert r_bad.status_code == 403

        # 2) Missing contact → 400
        r_nocontact = requests.post(
            f"{API}/public/ads-report/{slug}/renew?token={token}",
            json={"new_budget": 5000},
        )
        assert r_nocontact.status_code == 400

        # 3) Happy path
        r = requests.post(
            f"{API}/public/ads-report/{slug}/renew?token={token}",
            json={
                "contact_name": "Jean Test",
                "contact_email": "test@example.com",
                "contact_phone": "+22500112233",
                "new_budget": 50000,
                "target_duration_days": 60,
                "message": "On veut prolonger 2 mois",
            },
        )
        assert r.status_code == 200, r.text
        req_id = r.json()["id"]

        # 4) Admin sees it
        r_list = requests.get(f"{API}/admin/ad-renewal-requests", headers=admin["headers"])
        assert r_list.status_code == 200
        items = r_list.json()["items"]
        ours = next((x for x in items if x["id"] == req_id), None)
        assert ours is not None, items
        assert ours["status"] == "new"
        assert ours["banner_name"] == item["name"]
        assert ours["new_budget"] == 50000
        assert ours["target_duration_days"] == 60

        # 5) Admin marks handled
        r_h = requests.post(f"{API}/admin/ad-renewal-requests/{req_id}/mark-handled", headers=admin["headers"])
        assert r_h.status_code == 200

        # 6) Status flipped
        r_list2 = requests.get(f"{API}/admin/ad-renewal-requests", headers=admin["headers"])
        ours2 = next((x for x in r_list2.json()["items"] if x["id"] == req_id), None)
        assert ours2["status"] == "handled"
    finally:
        db.ad_banners.delete_one({"id": item["id"]})
        db.ad_renewal_requests.delete_many({"banner_id": item["id"]})


# -------------------------- AI MONTHLY COST CHART --------------------------

def test_ai_costs_monthly_returns_zero_filled_series(admin):
    r = requests.get(f"{API}/admin/ai-costs/monthly?months=6", headers=admin["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["months_requested"] == 6
    assert len(data["series"]) == 6
    # Series must be chronologically ordered (oldest first)
    months = [s["year_month"] for s in data["series"]]
    assert months == sorted(months), months
    for s in data["series"]:
        assert "year_month" in s
        assert "total_xof" in s
        assert "tenant_count" in s
    assert "totals" in data
    assert data["currency"] == "XOF"


def test_ai_costs_monthly_validates_range(admin):
    r = requests.get(f"{API}/admin/ai-costs/monthly?months=999", headers=admin["headers"])
    assert r.status_code in (400, 422)


def test_ai_costs_monthly_requires_admin():
    r = requests.get(f"{API}/admin/ai-costs/monthly?months=3")
    assert r.status_code in (401, 403)
