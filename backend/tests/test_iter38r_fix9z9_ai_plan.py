"""Iter38r-fix9z9 — Public AI campaign plan endpoint.

Validates:
  • POST /api/public/ads-report/{slug}/ai-plan?token=X requires valid token
  • Returns the 4 required fields (visual_hint, slogans, recommended_budget_xof, budget_justification)
  • Result is cached on the banner doc; second call within 6h returns cached=True
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
    aid = f"fz9_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "headers": {"Authorization": f"Bearer {_forge(aid, 'admin')}"}}
    db.users.delete_many({"id": aid})


def _banner(admin_h: dict) -> dict:
    r = requests.post(f"{API}/admin/ad-banners", json={
        "name": f"AIPlan {uuid.uuid4().hex[:6]}",
        "image_url": "/api/files/x", "target_url": "https://x.test",
        "placement": "public", "active": True, "budget_amount": 50000,
    }, headers=admin_h)
    assert r.status_code == 200
    return r.json()["item"]


def test_ai_plan_rejects_bad_token(admin, db):
    it = _banner(admin["headers"])
    try:
        r = requests.post(f"{API}/public/ads-report/{it['slug']}/ai-plan?token=WRONG")
        assert r.status_code == 403
    finally:
        db.ad_banners.delete_one({"id": it["id"]})


def test_ai_plan_returns_required_shape(admin, db):
    if not os.environ.get("EMERGENT_LLM_KEY"):
        pytest.skip("EMERGENT_LLM_KEY not set")
    it = _banner(admin["headers"])
    try:
        r = requests.post(f"{API}/public/ads-report/{it['slug']}/ai-plan?token={it['share_token']}", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("visual_hint"), str) and data["visual_hint"]
        assert isinstance(data.get("slogans"), list) and len(data["slogans"]) >= 1
        assert isinstance(data.get("recommended_budget_xof"), (int, float))
        assert data["recommended_budget_xof"] >= 0
        assert isinstance(data.get("budget_justification"), str) and data["budget_justification"]
        assert data["cached"] is False
        assert "based_on" in data
    finally:
        db.ad_banners.delete_one({"id": it["id"]})


def test_ai_plan_second_call_uses_cache(admin, db):
    if not os.environ.get("EMERGENT_LLM_KEY"):
        pytest.skip("EMERGENT_LLM_KEY not set")
    it = _banner(admin["headers"])
    try:
        r1 = requests.post(f"{API}/public/ads-report/{it['slug']}/ai-plan?token={it['share_token']}", timeout=60)
        assert r1.status_code == 200
        assert r1.json()["cached"] is False
        # Second call — cached
        r2 = requests.post(f"{API}/public/ads-report/{it['slug']}/ai-plan?token={it['share_token']}", timeout=10)
        assert r2.status_code == 200
        assert r2.json()["cached"] is True
        # Should be the SAME plan
        assert r2.json()["visual_hint"] == r1.json()["visual_hint"]
    finally:
        db.ad_banners.delete_one({"id": it["id"]})


def test_ai_plan_banner_not_found_returns_404():
    r = requests.post(f"{API}/public/ads-report/nonexistent-slug/ai-plan?token=foo")
    assert r.status_code == 404
