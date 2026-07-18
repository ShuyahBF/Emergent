"""Iter80 — validate /me/media-library upload for image PNG (used by MediaGenerator + MetaIntegration frontend components)."""
from __future__ import annotations

import io, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _tiny_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x9c\x18\x8e\xd6"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


@pytest.fixture(scope="module")
def admin_token():
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    admin = db.users.find_one({"email": "admin@sawalismartsystems.com"})
    assert admin
    return pyjwt.encode({
        "sub": admin["id"], "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def test_me_media_library_upload_png(admin_token):
    files = {"file": ("iter80_test.png", _tiny_png(), "image/png")}
    data = {"label": "iter80 pytest upload"}
    r = requests.post(f"{API}/me/media-library", headers={"Authorization": f"Bearer {admin_token}"}, files=files, data=data, timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc.get("id"), doc
    assert doc.get("kind") == "image", doc
    assert doc.get("public_url") or doc.get("url"), doc
    assert doc.get("file_id"), doc


def test_version_has_x_process_time_header():
    r = requests.get(f"{API}/version", timeout=10)
    assert r.status_code == 200, r.text
    val = r.headers.get("x-process-time") or r.headers.get("X-Process-Time")
    assert val is not None, dict(r.headers)
    assert float(val) >= 0
