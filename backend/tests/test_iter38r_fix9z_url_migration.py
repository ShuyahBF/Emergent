"""Iter38r-fix9z — Strip absolute origins from ad_banners URLs."""
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
    admin = f"fz_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin, "email": f"{admin}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"admin": admin, "token": _forge(admin, "admin")}
    db.users.delete_many({"id": admin})
    db.ad_banners.delete_many({"tenant_id": admin})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_fix_urls_strips_preview_origin(tenant, db):
    """A banner saved with absolute preview origin must be cleaned."""
    bid = str(uuid.uuid4())
    db.ad_banners.insert_one({
        "id": bid, "tenant_id": tenant["admin"],
        "name": "Legacy", "slug": "legacy",
        "image_url": "https://sawali-portal.preview.emergentagent.com/api/files/abc123",
        "target_url": "https://sawali-portal.preview.emergentagent.com/api/files/abc123",
        "placement": "public", "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.post(f"{API}/admin/ad-banners/fix-urls", headers=_h(tenant["token"]))
    assert r.status_code == 200, r.text
    assert r.json()["fixed_banners"] >= 1
    after = db.ad_banners.find_one({"id": bid})
    assert after["image_url"] == "/api/files/abc123"
    assert after["target_url"] == "/api/files/abc123"


def test_fix_urls_leaves_external_links_untouched(tenant, db):
    """External URLs (https://example.com/x.jpg) must NOT be modified."""
    bid = str(uuid.uuid4())
    external = "https://example.com/banner.png"
    db.ad_banners.insert_one({
        "id": bid, "tenant_id": tenant["admin"],
        "name": "External", "slug": "external",
        "image_url": external, "target_url": "https://acme.com/promo",
        "placement": "public", "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    requests.post(f"{API}/admin/ad-banners/fix-urls", headers=_h(tenant["token"]))
    after = db.ad_banners.find_one({"id": bid})
    assert after["image_url"] == external
    assert after["target_url"] == "https://acme.com/promo"


def test_fix_urls_handles_production_origin_too(tenant, db):
    """Production origin (sawalismartsystems.com) must be stripped too."""
    bid = str(uuid.uuid4())
    db.ad_banners.insert_one({
        "id": bid, "tenant_id": tenant["admin"],
        "name": "Prod", "slug": "prod-leg",
        "image_url": "https://sawalismartsystems.com/api/files/xyz789",
        "target_url": "https://sawalismartsystems.com/api/files/xyz789",
        "placement": "both", "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    requests.post(f"{API}/admin/ad-banners/fix-urls", headers=_h(tenant["token"]))
    after = db.ad_banners.find_one({"id": bid})
    assert after["image_url"] == "/api/files/xyz789"
