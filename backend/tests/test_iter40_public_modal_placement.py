"""Iter40-modal — `public_modal` placement for ad banners.

Validates:
 - Admin can create banners with placement="public_modal".
 - GET /api/public/ad-banners/active?placement=public_modal returns ONLY
   banners with placement exactly "public_modal" (no leakage from
   "public"/"both" placements).
 - The endpoint picks one of the modal banners (random).
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
    admin_id = f"abm_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    token = _forge(admin_id, "admin")
    yield token, admin_id
    db.users.delete_one({"id": admin_id})
    db.ad_banners.delete_many({"tenant_id": admin_id})


def test_admin_can_create_public_modal_banner(admin_token, db):
    token, _ = admin_token
    r = requests.post(
        f"{API}/admin/ad-banners",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": f"Modal Test {uuid.uuid4().hex[:6]}",
            "advertiser_name": "TestCorp",
            "image_url": "https://example.com/banner-modal.png",
            "target_url": "https://example.com/lp",
            "placement": "public_modal",
            "media_kind": "image",
            "active": True,
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["placement"] == "public_modal"


def test_public_modal_endpoint_returns_only_modal_banners(admin_token, db):
    token, admin_id = admin_token
    # Create one regular public banner and one modal banner
    headers = {"Authorization": f"Bearer {token}"}
    r1 = requests.post(f"{API}/admin/ad-banners", headers=headers, json={
        "name": f"Top Slot {uuid.uuid4().hex[:6]}",
        "image_url": "https://example.com/top.png",
        "target_url": "https://example.com/top",
        "placement": "public",
        "media_kind": "image",
        "active": True,
    }, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/admin/ad-banners", headers=headers, json={
        "name": f"Modal {uuid.uuid4().hex[:6]}",
        "image_url": "https://example.com/modal.png",
        "target_url": "https://example.com/modal",
        "placement": "public_modal",
        "media_kind": "image",
        "active": True,
    }, timeout=15)
    assert r2.status_code == 200
    modal_id = r2.json()["item"]["id"]

    # Call the public endpoint for the modal placement
    r = requests.get(f"{API}/public/ad-banners/active?placement=public_modal", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("banner") is not None, "Expected at least one public_modal banner"
    assert body["banner"]["placement"] == "public_modal"
    # The returned id must NEVER be the top-slot banner
    assert body["banner"]["id"] == modal_id


def test_public_endpoint_top_slot_excludes_modal_banners(admin_token, db):
    """A banner whose placement is "public_modal" must NOT be served on the
    regular top-of-page slot (placement="public")."""
    token, _ = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    # Create ONLY a public_modal banner
    r = requests.post(f"{API}/admin/ad-banners", headers=headers, json={
        "name": f"ModalOnly {uuid.uuid4().hex[:6]}",
        "image_url": "https://example.com/m.png",
        "target_url": "https://example.com/lp",
        "placement": "public_modal",
        "media_kind": "image",
        "active": True,
    }, timeout=15)
    assert r.status_code == 200
    modal_id = r.json()["item"]["id"]

    r = requests.get(f"{API}/public/ad-banners/active?placement=public", timeout=15)
    assert r.status_code == 200
    body = r.json()
    # Either no banner at all, or the banner returned is NOT our modal-only one
    if body.get("banner"):
        assert body["banner"]["id"] != modal_id
        assert body["banner"]["placement"] != "public_modal"


def test_invalid_placement_query_rejected():
    r = requests.get(f"{API}/public/ad-banners/active?placement=garbage", timeout=10)
    # FastAPI returns 422 for query pattern violations
    assert r.status_code == 422
