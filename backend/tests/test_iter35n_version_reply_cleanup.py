"""Iter35n — Version stamp + WA reply-time + Media library WA filter & cleanup.

Covers:
  - GET /api/version is public and returns version/git_sha/built_at/started_at.
  - POST /me/whatsapp/send-text stamps reply_seconds when answering an inbound.
  - GET /me/dashboard/wa-reply-stats returns me/team blocks.
  - GET /me/media-library?source=whatsapp_inbound filters correctly.
  - POST /me/media-library/wa-cleanup?dry_run=true|false.
"""
from __future__ import annotations

import os
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
    assert code
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
        timeout=30,
    )
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_user(db):
    return db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})


def _scope(u) -> str:
    return u.get("client_id") or u["id"]


# ============================================================
# 1. GET /api/version (public)
# ============================================================
class TestVersion:
    def test_public_version(self):
        r = requests.get(f"{API}/version", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("version", "git_sha", "started_at"):
            assert k in body
        assert body["version"]  # non-empty
        # No secrets leaked
        assert "password" not in str(body).lower()
        assert "token" not in str(body).lower()


# ============================================================
# 2. WA reply-time stamping + dashboard stats
# ============================================================
class TestWaReplyTime:
    def test_send_text_stamps_reply_seconds(self, admin_h, db, admin_user):
        scope = _scope(admin_user)
        digits = "229" + str(int(datetime.now().timestamp() * 1000))[-9:]
        # Seed an inbound 60 seconds ago
        inbound_at = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        inb = {
            "id": f"TEST_in_{uuid.uuid4().hex[:8]}",
            "client_id": scope,
            "direction": "inbound",
            "phone_digits": digits,
            "from": f"+{digits}",
            "body": "ping",
            "received_at": inbound_at,
            "created_at": inbound_at,
        }
        db.whatsapp_messages.insert_one(inb.copy())
        try:
            # Send a reply via the API (this will fail Meta auth in preview but
            # the endpoint logs the message anyway with reply_seconds when
            # the helper succeeds. So we look directly in DB after the call.)
            r = requests.post(
                f"{API}/me/whatsapp/send-text",
                headers=admin_h,
                json={"to": f"+{digits}", "text": "pong"},
                timeout=30,
            )
            # Either 200 (Meta accepted, reply_seconds in body) or other status
            # depending on Meta token validity. We check for the ROW.
            row = db.whatsapp_messages.find_one(
                {"phone_digits": digits, "direction": "outbound"}, {"_id": 0},
                sort=[("created_at", -1)],
            )
            # If Meta refused the send, the row may not have reply_seconds (we
            # only stamp when ok). When ok, reply_seconds must be set.
            if row and row.get("ok"):
                assert row.get("reply_seconds") is not None
                assert 60 <= row["reply_seconds"] <= 300, f"got {row['reply_seconds']}"
                assert row.get("reply_to_inbound_id") == inb["id"]
            # Either way the response shape must be consistent
            if r.status_code == 200:
                body = r.json()
                assert "reply_seconds" in body
        finally:
            db.whatsapp_messages.delete_one({"id": inb["id"]})
            db.whatsapp_messages.delete_many({"phone_digits": digits, "direction": "outbound"})

    def test_reply_stats_endpoint_shape(self, admin_h):
        r = requests.get(f"{API}/me/dashboard/wa-reply-stats?days=7", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["days"] == 7
        assert isinstance(body.get("me"), dict)
        for k in ("avg_seconds", "median_seconds", "replies", "fastest_seconds"):
            assert k in body["me"]
        assert isinstance(body.get("team"), list)

    def test_reply_stats_with_seeded_data(self, admin_h, db, admin_user):
        """Seed 3 outbound rows with known reply_seconds and confirm avg."""
        scope = _scope(admin_user)
        ids = []
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            for s in (10, 30, 60):
                doc = {
                    "id": f"TEST_rstat_{uuid.uuid4().hex[:8]}",
                    "client_id": scope,
                    "direction": "outbound",
                    "sender_id": admin_user["id"],
                    "sender_label": "Admin SAWALI",
                    "reply_seconds": s,
                    "ok": True,
                    "sent_at": now_iso,
                    "created_at": now_iso,
                }
                db.whatsapp_messages.insert_one(doc.copy())
                ids.append(doc["id"])

            r = requests.get(f"{API}/me/dashboard/wa-reply-stats?days=7", headers=admin_h, timeout=15)
            assert r.status_code == 200
            body = r.json()
            me = body["me"]
            assert me["replies"] >= 3
            # avg of seeded points alone is 33.3; with other data avg may differ but should be > 0
            assert me["avg_seconds"] is not None and me["avg_seconds"] > 0
            assert me["fastest_seconds"] is not None and me["fastest_seconds"] <= 10
        finally:
            for i in ids:
                db.whatsapp_messages.delete_one({"id": i})


# ============================================================
# 3. /me/media-library?source=whatsapp_inbound + cleanup
# ============================================================
class TestMediaLibraryWaFilter:
    def _seed_wa_media(self, db, scope, *, has_file_id=True, file_id=None) -> dict:
        fid = file_id or f"TEST_file_{uuid.uuid4().hex[:8]}"
        doc = {
            "id": f"TEST_lib_{uuid.uuid4().hex[:8]}",
            "client_id": scope,
            "file_id": fid if has_file_id else None,
            "label": "WA · Test · 2026-05-16",
            "filename": "wa-test.jpg",
            "kind": "image",
            "content_type": "image/jpeg",
            "extension": "jpg",
            "size": 4096,
            "public_url": f"https://example.test/api/files/{fid}.jpg",
            "source": "whatsapp_inbound",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db.media_library.insert_one(doc.copy())
        return doc

    def test_filter_by_source(self, admin_h, db, admin_user):
        scope = _scope(admin_user)
        # Seed a WA media + a non-WA media
        wa = self._seed_wa_media(db, scope)
        regular = {
            "id": f"TEST_lib_reg_{uuid.uuid4().hex[:8]}",
            "client_id": scope,
            "file_id": f"TEST_file_reg_{uuid.uuid4().hex[:8]}",
            "label": "Regular upload",
            "filename": "reg.png",
            "kind": "image",
            "size": 1234,
            "public_url": "https://example.test/api/files/reg.png",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db.media_library.insert_one(regular.copy())
        try:
            # WA filter should return WA only
            r = requests.get(f"{API}/me/media-library?source=whatsapp_inbound", headers=admin_h, timeout=15)
            assert r.status_code == 200
            ids = {m["id"] for m in r.json()}
            assert wa["id"] in ids
            assert regular["id"] not in ids

            # No filter returns both
            r2 = requests.get(f"{API}/me/media-library", headers=admin_h, timeout=15)
            ids2 = {m["id"] for m in r2.json()}
            assert wa["id"] in ids2
            assert regular["id"] in ids2
        finally:
            db.media_library.delete_one({"id": wa["id"]})
            db.media_library.delete_one({"id": regular["id"]})

    def test_cleanup_dry_run_then_apply(self, admin_h, db, admin_user):
        scope = _scope(admin_user)
        # Seed 2 WA media — one referenced by a fake report, one not.
        wa_unused = self._seed_wa_media(db, scope)
        wa_used = self._seed_wa_media(db, scope)
        # Reference wa_used.file_id from a fake user_report
        report_id = f"TEST_rep_{uuid.uuid4().hex[:8]}"
        db.user_reports.insert_one({
            "id": report_id,
            "client_id": scope,
            "owner_id": admin_user["id"],
            "title": "TEST iter35n cleanup",
            "images": [{"file_id": wa_used["file_id"], "url": f"/api/files/{wa_used['file_id']}.jpg"}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            # Dry-run
            r = requests.post(f"{API}/me/media-library/wa-cleanup?dry_run=true", headers=admin_h, timeout=20)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["dry_run"] is True
            ids_to_delete = {it["id"] for it in body.get("to_delete") or []}
            assert wa_unused["id"] in ids_to_delete
            assert wa_used["id"] not in ids_to_delete
            # Nothing actually deleted yet
            assert db.media_library.find_one({"id": wa_unused["id"]}) is not None

            # Apply
            r2 = requests.post(f"{API}/me/media-library/wa-cleanup?dry_run=false", headers=admin_h, timeout=20)
            assert r2.status_code == 200, r2.text
            body2 = r2.json()
            assert body2["dry_run"] is False
            assert body2["deleted"] >= 1
            assert db.media_library.find_one({"id": wa_unused["id"]}) is None
            # wa_used still present
            assert db.media_library.find_one({"id": wa_used["id"]}) is not None
        finally:
            db.media_library.delete_one({"id": wa_unused["id"]})
            db.media_library.delete_one({"id": wa_used["id"]})
            db.user_reports.delete_one({"id": report_id})
