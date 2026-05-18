"""Iter35q — Emergent Object Storage persistence (admin_upload + serve_file + rehydrate)."""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data["dev_otp"]}, timeout=30)
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_upload_mirrors_to_remote_storage(admin_h, db):
    """A fresh admin upload must populate `storage_path` in the DB row."""
    payload = b"%PDF-1.4 fake test pdf body " + uuid.uuid4().bytes
    files = {"file": ("test_iter35q.pdf", payload, "application/pdf")}
    r = requests.post(f"{API}/admin/upload", headers=admin_h, files=files, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    fid = body["id"]
    try:
        row = db.files.find_one({"id": fid}, {"_id": 0})
        assert row is not None
        assert row.get("storage_path"), f"storage_path empty — mirror failed. error={row.get('storage_error')!r}"
        # And the public URL still works
        r2 = requests.get(f"{API}/files/{fid}.pdf", timeout=30)
        assert r2.status_code == 200
        assert r2.content == payload
    finally:
        # Cleanup: remove disk + DB row
        try:
            (UPLOAD_DIR / row["stored_name"]).unlink(missing_ok=True)
        except Exception:
            pass
        db.files.delete_one({"id": fid})


def test_rehydrate_when_disk_file_missing(admin_h, db):
    """Simulate a production redeploy: upload, delete local file, request
    again — the endpoint must rehydrate from remote storage."""
    payload = b"rehydrate-payload-" + uuid.uuid4().bytes
    files = {"file": ("rehy.bin", payload, "application/octet-stream")}
    r = requests.post(f"{API}/admin/upload", headers=admin_h, files=files, timeout=60)
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    stored_name = r.json()["stored_name"]
    target = UPLOAD_DIR / stored_name
    try:
        # Verify upload + presence
        assert target.exists()
        row = db.files.find_one({"id": fid}, {"_id": 0})
        assert row.get("storage_path"), "remote mirror missing"
        # Simulate disk loss
        target.unlink()
        assert not target.exists()
        # Re-request → must succeed via rehydrate
        r2 = requests.get(f"{API}/files/{fid}.bin", timeout=30)
        assert r2.status_code == 200, r2.text
        assert r2.content == payload
        # The rehydrate path should also restore the file on disk
        assert target.exists()
    finally:
        target.unlink(missing_ok=True)
        db.files.delete_one({"id": fid})


def test_orphans_endpoint_returns_shape(admin_h):
    r = requests.get(f"{API}/admin/files/orphans", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "count" in body and isinstance(body["count"], int)
    assert isinstance(body.get("items"), list)
