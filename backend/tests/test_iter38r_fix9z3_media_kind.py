"""Iter38r-fix9z3 — media_kind field on ad banners (image vs video)."""
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


@pytest.fixture
def admin():
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    aid = f"mk_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "token": _forge(aid, "admin"), "db": db}
    db.users.delete_many({"id": aid})
    db.ad_banners.delete_many({"tenant_id": aid})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_create_with_media_kind_video(admin):
    r = requests.post(
        f"{API}/admin/ad-banners",
        headers=_h(admin["token"]),
        json={
            "name": "Video Banner",
            "image_url": "/api/files/abc-extensionless",
            "media_kind": "video",
            "target_url": "/api/files/abc-extensionless",
            "placement": "public",
            "active": True,
        },
    )
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["media_kind"] == "video"


def test_create_rejects_invalid_media_kind(admin):
    r = requests.post(
        f"{API}/admin/ad-banners",
        headers=_h(admin["token"]),
        json={
            "name": "Bad",
            "image_url": "/api/files/x",
            "media_kind": "audio",
            "target_url": "/api/files/x",
        },
    )
    assert r.status_code == 422


def test_public_endpoint_exposes_media_kind(admin):
    """The /public/ad-banners/active endpoint must include media_kind."""
    # Deactivate other banners so our test banner is picked
    admin["db"].ad_banners.update_many({"id": {"$exists": True}}, {"$set": {"active": False}})
    requests.post(
        f"{API}/admin/ad-banners",
        headers=_h(admin["token"]),
        json={
            "name": "MK Public Test",
            "image_url": "/api/files/test-mk",
            "media_kind": "video",
            "target_url": "/api/files/test-mk",
            "placement": "public",
            "active": True,
        },
    )
    r = requests.get(f"{API}/public/ad-banners/active", params={"placement": "public"})
    assert r.status_code == 200
    banner = r.json().get("banner")
    assert banner is not None
    assert "media_kind" in banner
    assert banner["media_kind"] == "video"


def test_legacy_banner_defaults_to_image(admin):
    """A banner created before the field existed must default to media_kind='image'."""
    bid = str(uuid.uuid4())
    admin["db"].ad_banners.insert_one({
        "id": bid, "tenant_id": admin["id"],
        "name": "Legacy", "slug": f"legacy-{bid[:6]}",
        "image_url": "/api/files/old-banner",
        "target_url": "/api/files/old-banner",
        "placement": "public", "active": True, "share_token": "tok_legacy_12345",
        "created_at": datetime.now(timezone.utc).isoformat(),
        # No media_kind field !
    })
    # Public report should default to image
    r = requests.get(
        f"{API}/public/ads-report/legacy-{bid[:6]}",
        params={"token": "tok_legacy_12345"},
    )
    assert r.status_code == 200
    assert r.json()["media_kind"] == "image"
