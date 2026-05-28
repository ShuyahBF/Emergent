"""Iter38r-fix8 — Verifies the storage mirror is enabled on additional upload
paths (media library, contact photo, form attachment). These paths previously
wrote to local disk only, so files would vanish after every prod redeploy.
"""
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"), override=False)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": data["dev_otp"]},
        timeout=30,
    )
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_media_library_upload_mirrors_to_remote_storage(admin_h, db):
    """POST /api/me/medias must populate storage_path on the file row."""
    payload = b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes + b"\x00" * 64
    files = {"file": (f"mlib-{uuid.uuid4().hex}.png", payload, "image/png")}
    r = requests.post(
        f"{API}/me/media-library",
        headers=admin_h,
        files=files,
        data={"label": "iter38r-fix8-test"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    media = r.json()
    fid = media["file_id"]
    try:
        row = db.files.find_one({"id": fid}, {"_id": 0})
        assert row is not None
        assert row.get("storage_path"), (
            f"storage_path empty for media library upload — mirror failed. "
            f"error={row.get('storage_error')!r}"
        )
    finally:
        try:
            (UPLOAD_DIR / (row or {}).get("stored_name", "")).unlink(missing_ok=True)
        except Exception:
            pass
        db.media_library.delete_one({"file_id": fid})
        db.files.delete_one({"id": fid})


def test_form_attachment_upload_mirrors_to_remote_storage(admin_h, db):
    """POST /api/me/forms/{form_id}/attachment must populate storage_path."""
    # Create a temp form
    r = requests.post(
        f"{API}/me/forms",
        headers=admin_h,
        json={
            "title": f"iter38r-fix8-{uuid.uuid4().hex[:6]}",
            "description": "storage mirror test",
            "fields": [{"key": "doc", "label": "Doc", "type": "file"}],
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    form_id = r.json()["id"]
    try:
        payload = b"text-file-payload-" + uuid.uuid4().bytes
        files = {"file": ("attach.txt", payload, "text/plain")}
        r2 = requests.post(
            f"{API}/me/forms/{form_id}/upload",
            headers=admin_h,
            files=files,
            timeout=60,
        )
        assert r2.status_code == 200, r2.text
        fid = r2.json()["file_id"]
        row = db.files.find_one({"id": fid}, {"_id": 0})
        assert row is not None
        assert row.get("storage_path"), (
            f"storage_path empty for form attachment — mirror failed. "
            f"error={row.get('storage_error')!r}"
        )
        try:
            (UPLOAD_DIR / row.get("stored_name", "")).unlink(missing_ok=True)
        except Exception:
            pass
        db.files.delete_one({"id": fid})
    finally:
        db.forms.delete_one({"id": form_id})


def test_contact_photo_upload_mirrors_to_remote_storage(admin_h, db):
    """POST /api/me/contacts/{cid}/photo must populate storage_path."""
    # Create a temp contact
    r = requests.post(
        f"{API}/me/contacts",
        headers=admin_h,
        json={"name": f"iter38r-fix8-{uuid.uuid4().hex[:6]}", "phone": "+22890000000"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    try:
        payload = b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes + b"\x00" * 64
        files = {"file": ("avatar.png", payload, "image/png")}
        r2 = requests.post(
            f"{API}/me/contacts/{cid}/photo",
            headers=admin_h,
            files=files,
            timeout=60,
        )
        assert r2.status_code == 200, r2.text
        photo_url = r2.json()["photo_url"]
        # Extract file_id from /api/files/{id}.ext
        fid = photo_url.rsplit("/", 1)[-1].split(".", 1)[0]
        row = db.files.find_one({"id": fid}, {"_id": 0})
        assert row is not None
        assert row.get("storage_path"), (
            f"storage_path empty for contact photo — mirror failed. "
            f"error={row.get('storage_error')!r}"
        )
        try:
            (UPLOAD_DIR / row.get("stored_name", "")).unlink(missing_ok=True)
        except Exception:
            pass
        db.files.delete_one({"id": fid})
    finally:
        db.directory_contacts.delete_one({"id": cid})
