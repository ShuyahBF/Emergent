"""Iter43-fix24az-l retest (2026-02-26) — Story Studio local media upload.

Validates the new endpoint POST /admin/story-studio/library/upload that lets
admins import a local image or video into the Story Studio library (as an
alternative to AI generation).

Test cases :
  1. Upload requires auth (401/403 without admin JWT)
  2. Upload of a valid PNG returns a `story_assets` doc with `engine="import"`
     and `status="ready"`
  3. Upload of a valid MP4 returns kind="video"
  4. Empty file body → 400
  5. Missing `file` field → 400
"""
from __future__ import annotations

import io
import os
import struct
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    admin = db.users.find_one({"email": "admin@sawalismartsystems.com"}) or db.users.find_one({"role": "admin"})
    assert admin, "No admin user found"
    return pyjwt.encode({
        "sub": admin["id"],
        "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def _tiny_png() -> bytes:
    """Minimal valid PNG (1x1 red pixel, ~68 bytes)."""
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x9c\x18\x8e\xd6"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _tiny_mp4() -> bytes:
    """Minimal MP4-like bytes with valid ftyp box."""
    ftyp = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2"
    mdat = b"\x00\x00\x00\x10mdat" + b"\x00" * 8
    return ftyp + mdat


def test_upload_requires_admin_auth():
    files = {"file": ("test.png", _tiny_png(), "image/png")}
    r = requests.post(f"{API}/admin/story-studio/library/upload", files=files, timeout=15)
    assert r.status_code in (401, 403), r.text


def test_upload_png_creates_story_asset(admin_token, db):
    files = {"file": ("dedup_test.png", _tiny_png(), "image/png")}
    data = {"title": "Iter43-fix24az-l pytest upload PNG"}
    r = requests.post(
        f"{API}/admin/story-studio/library/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files,
        data=data,
        timeout=15,
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc.get("kind") == "image", doc
    assert doc.get("engine") == "import", doc
    assert doc.get("status") == "ready", doc
    assert doc.get("file_size", 0) > 0
    assert doc.get("url", "").startswith("/admin/story-studio/library/"), doc
    # Cleanup
    aid = doc.get("id")
    if aid:
        db.story_assets.delete_one({"id": aid})


def test_upload_mp4_returns_kind_video(admin_token, db):
    files = {"file": ("dedup_test.mp4", _tiny_mp4(), "video/mp4")}
    data = {"title": "Iter43-fix24az-l pytest upload MP4"}
    r = requests.post(
        f"{API}/admin/story-studio/library/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files,
        data=data,
        timeout=15,
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc.get("kind") == "video", doc
    assert doc.get("engine") == "import", doc
    aid = doc.get("id")
    if aid:
        db.story_assets.delete_one({"id": aid})


def test_upload_missing_file_returns_400(admin_token):
    r = requests.post(
        f"{API}/admin/story-studio/library/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={"title": "no-file"},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    assert "file" in (r.json().get("detail") or "").lower(), r.json()


def test_upload_empty_body_returns_400(admin_token):
    files = {"file": ("empty.png", b"", "image/png")}
    r = requests.post(
        f"{API}/admin/story-studio/library/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files,
        timeout=15,
    )
    assert r.status_code == 400, r.text
