"""Iter38r-fix9y — Public live report for ad banners."""
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
def tenant(db):
    admin = f"sh_adm_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "id": admin, "email": f"{admin}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active", "created_at": now,
    })
    yield {"admin": admin, "token": _forge(admin, "admin")}
    db.users.delete_many({"id": admin})
    db.ad_banners.delete_many({"tenant_id": admin})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _make(token, **kw):
    payload = {
        "name": kw.pop("name", f"Promo {uuid.uuid4().hex[:4]}"),
        "image_url": "https://example.com/x.jpg",
        "target_url": "https://example.com",
        "placement": "public",
        "budget_amount": 1000, "currency": "XOF",
        "cost_per_impression": 1, "cost_per_click": 50,
        "active": True,
    }
    payload.update(kw)
    r = requests.post(f"{API}/admin/ad-banners", headers=_h(token), json=payload)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_create_generates_slug_and_share_token(tenant):
    b = _make(tenant["token"], name="Annonce Été Plage 2026")
    assert b["slug"] == "annonce-ete-plage-2026"
    assert b["share_token"]
    assert len(b["share_token"]) > 15
    assert b["share_path"] == f"/ads/annonce-ete-plage-2026?token={b['share_token']}"


def test_slug_collision_appends_suffix(tenant):
    _make(tenant["token"], name="Test Unique Slug")
    b2 = _make(tenant["token"], name="Test Unique Slug")
    assert b2["slug"] == "test-unique-slug-2"


def test_public_report_requires_token(tenant):
    b = _make(tenant["token"], name="Report A")
    # Wrong token
    r = requests.get(f"{API}/public/ads-report/{b['slug']}", params={"token": "wrong"})
    assert r.status_code == 403
    # Missing token
    r2 = requests.get(f"{API}/public/ads-report/{b['slug']}")
    assert r2.status_code == 422  # FastAPI validation


def test_public_report_returns_stats(tenant):
    b = _make(tenant["token"], name="Report B",
              cost_per_impression=2, budget_amount=100,
              advertiser_name="Acme Corp")
    # Fire one impression and one click
    requests.post(f"{API}/public/ad-banners/{b['id']}/impression")
    requests.post(f"{API}/public/ad-banners/{b['id']}/click")
    # Now read the public report
    r = requests.get(f"{API}/public/ads-report/{b['slug']}", params={"token": b["share_token"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Report B"
    assert data["advertiser_name"] == "Acme Corp"
    assert data["totals"]["impressions"] == 1
    assert data["totals"]["clicks"] == 1
    assert data["totals"]["ctr_pct"] == 100.0
    assert data["budget"]["amount"] == 100
    assert data["budget"]["remaining"] >= 0
    # The sensitive admin-only fields must NOT leak
    for k in ("tenant_id", "id", "cost_per_impression", "cost_per_click", "paid", "notes"):
        assert k not in data, f"{k} leaked"


def test_rotate_token_invalidates_old_link(tenant):
    b = _make(tenant["token"], name="Report C")
    old_token = b["share_token"]
    r = requests.post(f"{API}/admin/ad-banners/{b['id']}/rotate-token",
                      headers=_h(tenant["token"]))
    assert r.status_code == 200
    new_token = r.json()["share_token"]
    assert new_token != old_token
    # Old token must now 403
    r_old = requests.get(f"{API}/public/ads-report/{b['slug']}", params={"token": old_token})
    assert r_old.status_code == 403
    # New token must work
    r_new = requests.get(f"{API}/public/ads-report/{b['slug']}", params={"token": new_token})
    assert r_new.status_code == 200


def test_update_renames_slug(tenant):
    b = _make(tenant["token"], name="Old Name")
    r = requests.put(f"{API}/admin/ad-banners/{b['id']}",
                     headers=_h(tenant["token"]),
                     json={"name": "Brand New Name"})
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["slug"] == "brand-new-name"
    assert item["share_path"].startswith("/ads/brand-new-name?token=")
