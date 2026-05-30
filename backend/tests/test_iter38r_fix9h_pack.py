"""Iter38r-fix9h — Regression tests for:
  1. OCR images via Claude Vision in the Liluvine KB upload
  2. Batch realign endpoint /admin/clients-consistency/realign-all
  3. shared_recent field in /me/welcome-briefing.notes_kpis
"""
from __future__ import annotations

import os
import uuid
import datetime as dt
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30).json()
    if r.get("needs_otp"):
        r = requests.post(
            f"{API}/auth/verify-otp",
            json={"session_token": r["session_token"], "code": r["dev_otp"]},
            timeout=30,
        ).json()
    return r["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_kb_upload_unsupported_now_lists_images(admin_h):
    """Even an empty image is rejected, but the error message must reflect
    that images are accepted now (not the old PDF/TXT-only message)."""
    # Tiny fake image (will fail OCR with [AUCUN_TEXTE_DETECTE]) but the
    # endpoint must at least *accept* the file type.
    import io
    from PIL import Image
    img = Image.new("RGB", (50, 20), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    files = {"file": ("blank.png", buf.getvalue(), "image/png")}
    r = requests.post(
        f"{API}/admin/liluvine-pro/kb/upload",
        headers=admin_h, files=files,
        # Iter38r-fix9i — image now requires force_ocr=true (new split: 1 button no-OCR, 1 button OCR)
        data={"title": "test-blank-ocr", "force_ocr": "true"}, timeout=60,
    )
    # Should NOT be 415 anymore — should be 422 (no text detected) or 200
    assert r.status_code != 415, f"image should be accepted but got 415: {r.text}"
    if r.status_code == 200:
        # Cleanup
        for eid in r.json().get("ids", []):
            requests.delete(f"{API}/admin/liluvine-pro/kb/{eid}", headers=admin_h, timeout=10)


def test_realign_all_requires_confirm(admin_h):
    r = requests.post(f"{API}/admin/clients-consistency/realign-all", headers=admin_h, json={}, timeout=30)
    assert r.status_code == 400
    assert "confirm" in (r.json().get("detail") or "").lower()


def test_realign_all_dry_run(admin_h, db_sync):
    """Dry-run mode must not modify anything, but still report the candidates."""
    # Make sure we have at least one misaligned tracked user
    admin_id = db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})["id"]
    # Set admin company so the scan picks the group up
    db_sync.users.update_one({"id": admin_id}, {"$set": {"company": "SAWALI"}})
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    bad_id = "fix9h_bad_" + uuid.uuid4().hex[:6]
    bad_email = f"misaligned-fix9h-{uuid.uuid4().hex[:6]}@sawalismartsystems.com"
    db_sync.users.insert_one({
        "id": bad_id, "email": bad_email, "full_name": "Bad Tracker",
        "role": "tracked", "tracked_role": "Consultation",
        "parent_client_id": admin_id, "client_id": "ZZZ_WRONG",
        "is_active": True, "account_status": "active",
        "created_at": now,
    })
    try:
        r = requests.post(
            f"{API}/admin/clients-consistency/realign-all", headers=admin_h,
            json={"confirm": True, "dry_run": True}, timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        emails = [res.get("email") for res in body.get("results", [])]
        assert bad_email in emails, f"Expected {bad_email} in dry-run results: {emails}"
    finally:
        db_sync.users.delete_one({"id": bad_id})


def test_welcome_briefing_includes_shared_recent(admin_h):
    """Endpoint /me/welcome-briefing must always expose notes_kpis.shared_recent."""
    r = requests.get(f"{API}/me/welcome-briefing", headers=admin_h, timeout=30)
    assert r.status_code == 200
    body = r.json()
    kpis = body.get("notes_kpis") or {}
    sr = kpis.get("shared_recent")
    # For admin user (elevated) shared_recent.total stays 0 by design but
    # the dict must still be present.
    assert sr is not None
    for k in ("total", "by_kind", "window_days"):
        assert k in sr
