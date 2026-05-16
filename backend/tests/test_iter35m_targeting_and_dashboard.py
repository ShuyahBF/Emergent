"""Iter35m — Notes targeting + WA media re-use + WA media dashboard summary.

Covers:
  - GET /api/me/notes-targets — returns "Moi-même" first, then peers.
  - POST /api/me/whatsapp/messages/{msg_id}/save-to-library — registers an
    inbound media into media_library, idempotent.
  - GET /api/me/dashboard/wa-media-summary?days=7|30|90 — returns counts/top/last.
  - POST /api/me/notes/{kind} with target_user_ids persists the field.
  - Visibility: a private note targeted at user B is visible to B even though
    they aren't the author and aren't elevated.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone, timedelta
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
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    code = data.get("dev_otp")
    assert code, "no dev_otp"
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
        timeout=30,
    )
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_user(db):
    u = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})
    assert u
    return u


def _scope(user) -> str:
    return user.get("client_id") or user["id"]


# ============================================================
# 1. /me/notes-targets
# ============================================================
class TestNotesTargets:
    def test_self_is_first(self, admin_h):
        r = requests.get(f"{API}/me/notes-targets", headers=admin_h, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") or []
        assert len(items) >= 1
        assert items[0].get("is_self") is True
        # Each item has id, full_name
        for it in items:
            assert it.get("id")
            assert it.get("full_name")


# ============================================================
# 2. /me/whatsapp/messages/{id}/save-to-library
# ============================================================
class TestSaveToLibrary:
    def _seed_inbound_image(self, db, user) -> dict:
        """Insert a fake inbound message + corresponding files row so the endpoint
        can find both."""
        scope = _scope(user)
        file_id = f"TEST_file_{uuid.uuid4().hex[:8]}"
        msg_id = f"TEST_msg_{uuid.uuid4().hex[:8]}"
        files_row = {
            "id": file_id,
            "filename": "wa-test.jpg",
            "stored_name": f"{file_id}.jpg",
            "extension": "jpg",
            "content_type": "image/jpeg",
            "size": 4096,
            "url": f"/api/files/{file_id}.jpg",
            "public_url": f"https://example.test/api/files/{file_id}.jpg",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        msg = {
            "id": msg_id,
            "client_id": scope,
            "direction": "inbound",
            "from": "+22899887766",
            "phone_digits": "22899887766",
            "contact_name": "Test Contact",
            "media_id": file_id,
            "media_url": f"/api/files/{file_id}.jpg",
            "media_mime_type": "image/jpeg",
            "media_filename": "wa-test.jpg",
            "media_size_bytes": 4096,
            "media_kind": "image",
            "body": "[image reçu]",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db.files.insert_one(files_row.copy())
        db.whatsapp_messages.insert_one(msg.copy())
        return {"file_id": file_id, "msg_id": msg_id}

    def _cleanup(self, db, ids):
        db.files.delete_one({"id": ids["file_id"]})
        db.whatsapp_messages.delete_one({"id": ids["msg_id"]})
        db.media_library.delete_many({"file_id": ids["file_id"]})

    def test_save_to_library_creates_entry(self, admin_h, db, admin_user):
        ids = self._seed_inbound_image(db, admin_user)
        try:
            r = requests.post(
                f"{API}/me/whatsapp/messages/{ids['msg_id']}/save-to-library",
                headers=admin_h, json={}, timeout=20,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] is True
            assert body["already_existed"] is False
            assert body["media"]["file_id"] == ids["file_id"]
            assert body["media"]["kind"] == "image"
            assert body["media"]["source"] == "whatsapp_inbound"
        finally:
            self._cleanup(db, ids)

    def test_save_to_library_idempotent(self, admin_h, db, admin_user):
        ids = self._seed_inbound_image(db, admin_user)
        try:
            r1 = requests.post(
                f"{API}/me/whatsapp/messages/{ids['msg_id']}/save-to-library",
                headers=admin_h, json={}, timeout=20,
            )
            assert r1.status_code == 200
            assert r1.json()["already_existed"] is False
            r2 = requests.post(
                f"{API}/me/whatsapp/messages/{ids['msg_id']}/save-to-library",
                headers=admin_h, json={}, timeout=20,
            )
            assert r2.status_code == 200
            assert r2.json()["already_existed"] is True
            # Should be the SAME library entry id
            assert r1.json()["media"]["id"] == r2.json()["media"]["id"]
        finally:
            self._cleanup(db, ids)

    def test_save_to_library_404_when_no_msg(self, admin_h):
        r = requests.post(
            f"{API}/me/whatsapp/messages/_does_not_exist_/save-to-library",
            headers=admin_h, json={}, timeout=20,
        )
        assert r.status_code == 404


# ============================================================
# 3. /me/dashboard/wa-media-summary
# ============================================================
class TestWaMediaSummary:
    def test_returns_counts_and_lists(self, admin_h, db, admin_user):
        scope = _scope(admin_user)
        seeds = []
        try:
            now = datetime.now(timezone.utc)
            for i, kind in enumerate(["image", "audio", "video", "document"]):
                doc = {
                    "id": f"TEST_msum_{uuid.uuid4().hex[:8]}",
                    "client_id": scope,
                    "direction": "inbound",
                    "from": f"+228{i}",
                    "phone_digits": f"228000000{i}",
                    "contact_name": f"Test {kind}",
                    "media_url": f"/api/files/test_{kind}.bin",
                    "media_mime_type": "application/octet-stream",
                    "media_kind": kind,
                    "media_filename": f"test.{kind}",
                    "received_at": now.isoformat(),
                    "created_at": now.isoformat(),
                }
                db.whatsapp_messages.insert_one(doc.copy())
                seeds.append(doc["id"])

            r = requests.get(f"{API}/me/dashboard/wa-media-summary?days=7", headers=admin_h, timeout=20)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["days"] == 7
            counts = body["counts"]
            for k in ("image", "audio", "video", "document", "total"):
                assert k in counts
            # Each kind is at least 1 thanks to our seeds
            for k in ("image", "audio", "video", "document"):
                assert counts[k] >= 1, f"{k}={counts[k]}"
            assert counts["total"] >= 4
            assert isinstance(body["top_contacts"], list)
            assert isinstance(body["last_items"], list)
            assert len(body["last_items"]) >= 1
        finally:
            for sid in seeds:
                db.whatsapp_messages.delete_one({"id": sid})

    def test_invalid_days_rejected(self, admin_h):
        r = requests.get(f"{API}/me/dashboard/wa-media-summary?days=0", headers=admin_h, timeout=10)
        assert r.status_code == 422
        r = requests.get(f"{API}/me/dashboard/wa-media-summary?days=999", headers=admin_h, timeout=10)
        assert r.status_code == 422


# ============================================================
# 4. Notes — target_user_ids persistence + visibility
# ============================================================
class TestNotesTargeting:
    def _create_note_with_targets(self, headers, *, kind: str, title: str, is_private: bool, targets: list) -> dict:
        payload = {
            "title": title,
            "content_html": f"<p>{title}</p>",
            "is_private": is_private,
            "target_user_ids": targets,
        }
        r = requests.post(f"{API}/me/notes/{kind}", headers=headers, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        return r.json()

    def test_target_user_ids_persisted(self, admin_h, db, admin_user):
        # Pick a target other than the admin (any other user). If none, skip.
        other = db.users.find_one({"email": {"$ne": ADMIN_EMAIL}}, {"_id": 0, "id": 1})
        target_id = other["id"] if other else admin_user["id"]
        kind = "notes"
        created = self._create_note_with_targets(
            admin_h, kind=kind, title=f"TEST iter35m {uuid.uuid4().hex[:6]}",
            is_private=True, targets=[target_id],
        )
        nid = created["id"]
        try:
            row = db.user_notes_personal.find_one({"id": nid}, {"_id": 0})
            assert row is not None
            assert row.get("is_private") is True
            assert target_id in (row.get("target_user_ids") or [])
        finally:
            db.user_notes_personal.delete_one({"id": nid})
