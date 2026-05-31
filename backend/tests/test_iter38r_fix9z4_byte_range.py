"""Iter38r-fix9z4 — Strict HTTP byte-range support for video playback.

Browsers (Chromium, Safari) require HTTP 206 Partial Content responses
with a correct Content-Range header to play <video> elements. The previous
`FileResponse` returned 200 + full body even when a Range header was sent,
which caused MEDIA_ERR_SRC_NOT_SUPPORTED in <video>. This test enforces
the new behaviour.
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
    aid = f"fz4_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "token": _forge(aid, "admin")}
    db.users.delete_many({"id": aid})


def _upload_video(token: str, size: int = 5000) -> tuple[str, int]:
    # Pad an mp4-ish ftyp header to reach `size` bytes.
    head = b"\x00\x00\x00\x1cftypmp42\x00\x00\x00\x00mp42isomavc1\x00\x00"
    data = head + b"\x00" * (size - len(head))
    assert len(data) == size
    r = requests.post(
        f"{API}/admin/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("stream.mp4", data, "video/mp4")},
    )
    assert r.status_code == 200, r.text
    return r.json()["url"], size


def test_range_specific_bytes_returns_206(admin):
    url, total = _upload_video(admin["token"], size=5000)
    r = requests.get(f"{BASE_URL}{url}", headers={"Range": "bytes=0-100"})
    assert r.status_code == 206, f"expected 206, got {r.status_code} ({r.headers})"
    assert r.headers.get("content-range") == f"bytes 0-100/{total}"
    assert r.headers.get("content-length") == "101"
    assert r.headers.get("accept-ranges") == "bytes"
    assert len(r.content) == 101


def test_range_open_ended_returns_206_full_remainder(admin):
    """Browsers send `Range: bytes=0-` (open-ended). Must return 206 + full body."""
    url, total = _upload_video(admin["token"], size=4096)
    r = requests.get(f"{BASE_URL}{url}", headers={"Range": "bytes=0-"})
    assert r.status_code == 206
    assert r.headers.get("content-range") == f"bytes 0-{total - 1}/{total}"
    assert r.headers.get("content-length") == str(total)
    assert len(r.content) == total


def test_range_suffix_request_returns_206(admin):
    """Range: bytes=1000-2000 returns the middle slice with proper headers."""
    url, total = _upload_video(admin["token"], size=5000)
    r = requests.get(f"{BASE_URL}{url}", headers={"Range": "bytes=1000-2000"})
    assert r.status_code == 206
    assert r.headers.get("content-range") == f"bytes 1000-2000/{total}"
    assert len(r.content) == 1001


def test_no_range_returns_200_full_body_with_content_length(admin):
    """A plain GET (no Range header) must return 200 with the entire file."""
    url, total = _upload_video(admin["token"], size=3000)
    r = requests.get(f"{BASE_URL}{url}")
    assert r.status_code == 200
    assert r.headers.get("content-length") == str(total)
    assert r.headers.get("accept-ranges") == "bytes"
    assert (r.headers.get("content-disposition") or "").lower().startswith("inline")
    assert len(r.content) == total


def test_range_out_of_bounds_returns_416(admin):
    url, total = _upload_video(admin["token"], size=2048)
    r = requests.get(f"{BASE_URL}{url}", headers={"Range": f"bytes={total + 100}-{total + 200}"})
    assert r.status_code == 416
    assert r.headers.get("content-range") == f"bytes */{total}"


def test_inline_disposition_preserved_on_range(admin):
    """Range responses for media must keep Content-Disposition: inline."""
    url, _ = _upload_video(admin["token"], size=2000)
    r = requests.get(f"{BASE_URL}{url}", headers={"Range": "bytes=0-50"})
    assert r.status_code == 206
    disp = (r.headers.get("content-disposition") or "").lower()
    assert disp.startswith("inline"), f"expected inline, got {disp!r}"
