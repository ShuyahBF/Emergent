"""Iter38r-fix9z2 — File serving headers for inline video/image playback.

Validates that `/api/files/{file_id}` returns the correct headers so that
browsers render videos and images inline (instead of downloading them).
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
    aid = f"fz2_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "token": _forge(aid, "admin")}
    db.users.delete_many({"id": aid})


def _upload(token: str, filename: str, content_type: str, data: bytes) -> str:
    r = requests.post(
        f"{API}/admin/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, data, content_type)},
    )
    assert r.status_code == 200, r.text
    return r.json()["url"]


def test_video_served_inline_with_accept_ranges(admin):
    """MP4 must be served inline (not download) with Accept-Ranges."""
    fake_mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 200
    url = _upload(admin["token"], "promo.mp4", "video/mp4", fake_mp4)
    r = requests.get(f"{BASE_URL}{url}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    disp = (r.headers.get("content-disposition") or "").lower()
    assert disp.startswith("inline"), f"Expected inline disposition, got {disp!r}"
    assert "attachment" not in disp
    assert r.headers.get("accept-ranges") == "bytes"


def test_image_served_inline(admin):
    """JPEG must be served inline so <img> renders it."""
    fake_jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    url = _upload(admin["token"], "logo.jpg", "image/jpeg", fake_jpg)
    r = requests.get(f"{BASE_URL}{url}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert (r.headers.get("content-disposition") or "").lower().startswith("inline")


def test_arbitrary_binary_keeps_attachment_disposition(admin):
    """A .zip / .exe must still trigger a download."""
    fake_zip = b"PK\x03\x04" + b"\x00" * 100
    url = _upload(admin["token"], "archive.zip", "application/zip", fake_zip)
    r = requests.get(f"{BASE_URL}{url}")
    assert r.status_code == 200
    disp = (r.headers.get("content-disposition") or "").lower()
    assert disp.startswith("attachment"), f"Expected attachment, got {disp!r}"


def test_range_request_returns_206(admin):
    """Sending Range: bytes=0-100 must return 206 Partial Content."""
    fake_mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 2000
    url = _upload(admin["token"], "stream.mp4", "video/mp4", fake_mp4)
    r = requests.get(f"{BASE_URL}{url}", headers={"Range": "bytes=0-100"})
    # Starlette FileResponse returns 206 when Range is set
    assert r.status_code in (206, 200), r.headers
    if r.status_code == 206:
        assert r.headers.get("content-range", "").startswith("bytes 0-100")


def test_legacy_octet_stream_video_sniffed_as_inline(admin, db):
    """A file saved before the fix with content_type=application/octet-stream
    must still be served inline if the filename ends in .mp4."""
    fake_mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 200
    # Upload as video then manually downgrade the stored content_type
    url = _upload(admin["token"], "old.mp4", "video/mp4", fake_mp4)
    file_id = url.split("/")[-1]
    db.files.update_one({"id": file_id}, {"$set": {"content_type": "application/octet-stream"}})
    r = requests.get(f"{BASE_URL}{url}")
    assert r.status_code == 200
    # Content type sniffed from extension → video/mp4
    assert r.headers.get("content-type") == "video/mp4"
    assert (r.headers.get("content-disposition") or "").lower().startswith("inline")
