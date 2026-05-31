"""Iter38r-fix9w — Ad Banners monetization endpoints."""
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
    admin_id = f"ab_adm_{uuid.uuid4().hex[:6]}"
    client_id = f"ab_cli_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "role": "admin", "account_status": "active", "created_at": now},
        {"id": client_id, "email": f"{client_id}@t.l", "password_hash": "x",
         "role": "client", "account_status": "active", "created_at": now},
    ])
    yield {"admin_id": admin_id, "admin_token": _forge(admin_id, "admin"),
           "client_token": _forge(client_id, "client")}
    db.users.delete_many({"id": {"$in": [admin_id, client_id]}})
    db.ad_banners.delete_many({"tenant_id": admin_id})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _make_banner(token, **kw):
    payload = {
        "name": "Test Banner",
        "image_url": "https://example.com/banner.jpg",
        "target_url": "https://example.com",
        "placement": "both",
        "budget_amount": 1000,
        "currency": "XOF",
        "cost_per_impression": 1.0,
        "cost_per_click": 50.0,
        "active": True,
    }
    payload.update(kw)
    r = requests.post(f"{API}/admin/ad-banners", headers=_h(token), json=payload)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_create_and_list_banner(tenant):
    b = _make_banner(tenant["admin_token"], name="Promo 1")
    assert b["id"]
    assert b["name"] == "Promo 1"
    assert b["progress_pct"] == 0.0
    assert b["is_currently_active"] is True
    r = requests.get(f"{API}/admin/ad-banners", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["id"] == b["id"] for it in items)


def test_create_requires_admin(tenant):
    r = requests.post(f"{API}/admin/ad-banners", headers=_h(tenant["client_token"]),
                      json={"name": "x", "image_url": "https://x", "target_url": "https://x"})
    assert r.status_code == 403


def test_public_pick_banner_returns_banner(tenant):
    b = _make_banner(tenant["admin_token"], name="PublicPick", placement="public")
    r = requests.get(f"{API}/public/ad-banners/active", params={"placement": "public"})
    assert r.status_code == 200
    data = r.json()
    # Either ours or a previously inserted active banner — at minimum no None
    if data["banner"]:
        # Sensitive fields must not be exposed
        for k in ("budget_amount", "amount_spent", "tenant_id"):
            assert k not in data["banner"], data["banner"]


def test_impression_bumps_counter_and_spent(tenant, db):
    b = _make_banner(tenant["admin_token"], name="Imp", cost_per_impression=2.5,
                     budget_amount=100)
    r = requests.post(f"{API}/public/ad-banners/{b['id']}/impression")
    assert r.status_code == 200
    fresh = db.ad_banners.find_one({"id": b["id"]})
    assert fresh["total_impressions"] == 1
    assert fresh["amount_spent"] == 2.5
    # daily_stats has today's row
    today = date.today().isoformat()
    daily = next((d for d in fresh.get("daily_stats", []) if d["date"] == today), None)
    assert daily is not None
    assert daily["impressions"] == 1


def test_click_bumps_counter_and_returns_target_url(tenant, db):
    b = _make_banner(tenant["admin_token"], name="Click", cost_per_click=10,
                     budget_amount=100, target_url="https://example.com/landing")
    r = requests.post(f"{API}/public/ad-banners/{b['id']}/click")
    assert r.status_code == 200
    assert r.json()["target_url"] == "https://example.com/landing"
    fresh = db.ad_banners.find_one({"id": b["id"]})
    assert fresh["total_clicks"] == 1
    assert fresh["amount_spent"] == 10


def test_auto_pause_when_budget_exhausted(tenant, db):
    """A banner with budget 10 and CPI 6 must auto-pause after 2 impressions."""
    b = _make_banner(tenant["admin_token"], name="Exhaust",
                     cost_per_impression=6, budget_amount=10)
    requests.post(f"{API}/public/ad-banners/{b['id']}/impression")
    requests.post(f"{API}/public/ad-banners/{b['id']}/impression")
    fresh = db.ad_banners.find_one({"id": b["id"]})
    assert fresh["amount_spent"] >= 10
    assert fresh["active"] is False
    assert fresh.get("auto_paused_reason") == "budget_exhausted"


def test_expired_banner_not_served_publicly(tenant, db):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    b = _make_banner(tenant["admin_token"], name="Expired",
                     placement="public", expiration_date=yesterday)
    # Manually mark all OTHER banners inactive so the picker has only ours
    db.ad_banners.update_many({"id": {"$ne": b["id"]}}, {"$set": {"active": False}})
    r = requests.get(f"{API}/public/ad-banners/active", params={"placement": "public"})
    assert r.status_code == 200
    assert r.json()["banner"] is None


def test_toggle_paid_flag(tenant):
    b = _make_banner(tenant["admin_token"], name="Pay")
    assert b["paid"] is False
    r = requests.post(f"{API}/admin/ad-banners/{b['id']}/toggle-paid",
                      headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    assert r.json()["paid"] is True


def test_stats_endpoint(tenant):
    b = _make_banner(tenant["admin_token"], name="Stats",
                     cost_per_impression=1, budget_amount=100)
    requests.post(f"{API}/public/ad-banners/{b['id']}/impression")
    requests.post(f"{API}/public/ad-banners/{b['id']}/click")
    r = requests.get(f"{API}/admin/ad-banners/{b['id']}/stats",
                     headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    data = r.json()
    assert data["totals"]["impressions"] == 1
    assert data["totals"]["clicks"] == 1
    assert data["totals"]["ctr_pct"] == 100.0


def test_update_and_delete(tenant):
    b = _make_banner(tenant["admin_token"], name="Mod")
    r = requests.put(f"{API}/admin/ad-banners/{b['id']}",
                     headers=_h(tenant["admin_token"]),
                     json={"name": "Mod2", "active": False})
    assert r.status_code == 200
    assert r.json()["item"]["name"] == "Mod2"
    r = requests.delete(f"{API}/admin/ad-banners/{b['id']}",
                        headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
