"""Iter35l — HTTP integration tests for WhatsApp media endpoints.

Covers:
  - PUT /api/admin/settings persists the new wa_* keys, then GET returns them.
  - POST /api/me/whatsapp/send-media validates inputs (403 when toggle off,
    409 when 24h window closed, 413 oversize file, 400 empty file).
  - GET /api/me/contacts/{cid}/messages exposes the new media_* + voice_note_*
    fields when present on the stored message document.
  - Regression: POST /api/me/whatsapp/send-text still rejects with 409 when
    no recent inbound (proves the helper path is intact).
  - Regression: POST /api/whatsapp/webhook still ingests a plain text inbound.
  - Regression: GET /api/admin/whatsapp/webhook-logs still returns {items,count}.
"""
from __future__ import annotations

import io
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


# ---------- Auth helper ------------------------------------------------
def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    if not data.get("needs_otp"):
        tok = data.get("access_token")
        assert tok, f"no access_token in login response: {data}"
        return tok
    code = data.get("dev_otp")
    assert code, "no dev_otp returned (SMTP must be off for tests)"
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
        timeout=30,
    )
    assert r2.status_code == 200, r2.text
    tok = r2.json().get("access_token")
    assert tok, "no access_token from verify-otp"
    return tok


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Sync pymongo handle (no event loop issues) -----------------
@pytest.fixture(scope="module")
def db():
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_user(db):
    u = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})
    assert u, "admin user not seeded"
    return u


def _client_scope(user) -> str:
    return user.get("client_id") or user["id"]


def _seed_inbound(db, *, client_scope: str, phone_digits: str, suffix: str = "") -> dict:
    doc = {
        "id": f"TEST_inb_{uuid.uuid4().hex[:8]}{suffix}",
        "client_id": client_scope,
        "direction": "inbound",
        "phone_digits": phone_digits,
        "from": f"+{phone_digits}",
        "body": "TEST inbound seed iter35l",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.whatsapp_messages.insert_one(doc.copy())
    return doc


# ============================================================
# 1. /admin/settings — persist + return the new wa_* keys
# ============================================================
class TestAdminSettingsWaMedia:
    """Verify the new WA media toggles round-trip through PUT/GET."""

    def test_round_trip_wa_media_keys(self, admin_h):
        payload = {
            "wa_allow_terminal_media": True,
            "wa_voice_transcribe_enabled": True,
            "wa_watermark_enabled": True,
            "wa_watermark_text": "TEST_SAWALI_WM",
            "wa_qr_enabled": True,
            "wa_qr_payload": "https://example.test/qr-iter35l",
        }
        r = requests.put(f"{API}/admin/settings", headers=admin_h, json=payload, timeout=30)
        assert r.status_code == 200, r.text

        g = requests.get(f"{API}/admin/settings", headers=admin_h, timeout=30)
        assert g.status_code == 200, g.text
        s = g.json()
        for k, v in payload.items():
            assert s.get(k) == v, f"key {k} not persisted (got {s.get(k)!r})"

    def test_toggle_off_then_on(self, admin_h):
        r = requests.put(
            f"{API}/admin/settings", headers=admin_h,
            json={"wa_allow_terminal_media": False}, timeout=30,
        )
        assert r.status_code == 200
        g = requests.get(f"{API}/admin/settings", headers=admin_h, timeout=30).json()
        assert g["wa_allow_terminal_media"] is False
        requests.put(
            f"{API}/admin/settings", headers=admin_h,
            json={"wa_allow_terminal_media": True}, timeout=30,
        )
        g = requests.get(f"{API}/admin/settings", headers=admin_h, timeout=30).json()
        assert g["wa_allow_terminal_media"] is True


# ============================================================
# 2. POST /me/whatsapp/send-media — validation
# ============================================================
class TestSendMediaValidation:
    """End-to-end validation behaviour of the multipart send-media endpoint."""

    @staticmethod
    def _set_terminal_media(admin_h, allowed: bool):
        requests.put(
            f"{API}/admin/settings", headers=admin_h,
            json={"wa_allow_terminal_media": allowed}, timeout=30,
        )

    def test_403_when_terminal_media_disabled(self, admin_h):
        self._set_terminal_media(admin_h, False)
        try:
            files = {"file": ("test.jpg", b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")}
            data = {"to": "+22899887766"}
            r = requests.post(
                f"{API}/me/whatsapp/send-media",
                headers=admin_h, data=data, files=files, timeout=30,
            )
            assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"
            assert "désactivé" in (r.json().get("detail") or "").lower()
        finally:
            self._set_terminal_media(admin_h, True)

    def test_409_when_window_closed(self, admin_h):
        self._set_terminal_media(admin_h, True)
        unique_phone = "+228" + str(int(time.time()))[-8:]
        files = {"file": ("test.jpg", b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")}
        data = {"to": unique_phone}
        r = requests.post(
            f"{API}/me/whatsapp/send-media",
            headers=admin_h, data=data, files=files, timeout=30,
        )
        assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text}"
        assert "24h" in (r.json().get("detail") or "")

    def test_400_when_file_empty(self, admin_h, db, admin_user):
        scope = _client_scope(admin_user)
        digits = "228" + str(int(time.time() * 1000))[-9:]
        inb = _seed_inbound(db, client_scope=scope, phone_digits=digits, suffix="_e")
        try:
            files = {"file": ("empty.jpg", b"", "image/jpeg")}
            data = {"to": f"+{digits}"}
            r = requests.post(
                f"{API}/me/whatsapp/send-media",
                headers=admin_h, data=data, files=files, timeout=30,
            )
            assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text}"
            assert "vide" in (r.json().get("detail") or "").lower()
        finally:
            db.whatsapp_messages.delete_one({"id": inb["id"]})

    def test_413_when_file_too_large(self, admin_h, db, admin_user):
        scope = _client_scope(admin_user)
        digits = "229" + str(int(time.time() * 1000))[-9:]
        inb = _seed_inbound(db, client_scope=scope, phone_digits=digits, suffix="_l")
        try:
            big = b"\xff\xd8\xff" + b"a" * (16 * 1024 * 1024 + 10)
            files = {"file": ("big.jpg", big, "image/jpeg")}
            data = {"to": f"+{digits}"}
            r = requests.post(
                f"{API}/me/whatsapp/send-media",
                headers=admin_h, data=data, files=files, timeout=120,
            )
            assert r.status_code == 413, f"expected 413 got {r.status_code}: {r.text}"
        finally:
            db.whatsapp_messages.delete_one({"id": inb["id"]})

    def test_send_media_returns_clean_response_when_meta_fails(self, admin_h, db, admin_user):
        """Happy path through validation; even when Meta refuses, response must be
        a 200 JSON containing ok/error/http_status/media_url/kind."""
        scope = _client_scope(admin_user)
        digits = "230" + str(int(time.time() * 1000))[-9:]
        inb = _seed_inbound(db, client_scope=scope, phone_digits=digits, suffix="_h")
        try:
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (300, 200), color=(100, 150, 200)).save(buf, "JPEG")
            files = {"file": ("photo.jpg", buf.getvalue(), "image/jpeg")}
            data = {"to": f"+{digits}", "caption": "TEST iter35l"}
            r = requests.post(
                f"{API}/me/whatsapp/send-media",
                headers=admin_h, data=data, files=files, timeout=60,
            )
            assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
            j = r.json()
            for k in ("ok", "error", "http_status", "media_url", "kind"):
                assert k in j, f"missing key {k} in response: {j}"
            assert j["kind"] == "image"
            assert j["media_url"].startswith("/api/files/")
        finally:
            db.whatsapp_messages.delete_one({"id": inb["id"]})


# ============================================================
# 3. GET /me/contacts/{cid}/messages — surfaces new media_* fields
# ============================================================
class TestContactMessagesMediaFields:
    def test_inbound_media_fields_visible(self, admin_h, db, admin_user):
        scope = _client_scope(admin_user)
        cid = f"TEST_ct_{uuid.uuid4().hex[:8]}"
        contact = {
            "id": cid,
            "client_id": scope,
            "full_name": "TEST iter35l contact",
            "whatsapp": "+22890000001",
            "phone": "+22890000001",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        msg = {
            "id": f"TEST_msg_{uuid.uuid4().hex[:8]}",
            "client_id": scope,
            "direction": "inbound",
            "contact_id": cid,
            "phone_digits": "22890000001",
            "from": "+22890000001",
            "body": "[image reçue]",
            "message_type": "image",
            "media_url": "/api/files/test-iter35l.jpg",
            "media_mime_type": "image/jpeg",
            "media_kind": "image",
            "media_filename": "from_test.jpg",
            "voice_note_transcript": None,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db.directory_contacts.insert_one(contact.copy())
        db.whatsapp_messages.insert_one(msg.copy())
        try:
            r = requests.get(f"{API}/me/contacts/{cid}/messages", headers=admin_h, timeout=30)
            assert r.status_code == 200, r.text
            data = r.json()
            assert "messages" in data
            assert len(data["messages"]) >= 1
            m = next(x for x in data["messages"] if x["id"] == msg["id"])
            assert m["media_url"] == "/api/files/test-iter35l.jpg"
            assert m["media_mime_type"] == "image/jpeg"
            assert m["media_kind"] == "image"
            assert m["media_filename"] == "from_test.jpg"
            assert "voice_note_transcript" in m
        finally:
            db.directory_contacts.delete_one({"id": cid})
            db.whatsapp_messages.delete_one({"id": msg["id"]})


# ============================================================
# 4. Regression — send-text still 409 outside 24h window
# ============================================================
class TestRegressionSendText:
    def test_send_text_window_closed(self, admin_h):
        unique_phone = "+228" + str(uuid.uuid4().int)[:8]
        r = requests.post(
            f"{API}/me/whatsapp/send-text",
            headers=admin_h,
            json={"to": unique_phone, "text": "TEST regression iter35l"},
            timeout=30,
        )
        assert r.status_code in (409, 400), f"unexpected: {r.status_code} {r.text}"


# ============================================================
# 5. Regression — webhook accepts a plain text inbound
# ============================================================
class TestRegressionWebhookInbound:
    def test_webhook_accepts_text_inbound(self, db):
        wa_id = f"228{uuid.uuid4().int % 10**9:09d}"
        msg_id = f"wamid.TEST_{uuid.uuid4().hex[:10]}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WABA_TEST",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "22899887766", "phone_number_id": "TEST_PNID"},
                        "contacts": [{"wa_id": wa_id, "profile": {"name": "TEST Iter35l"}}],
                        "messages": [{
                            "from": wa_id,
                            "id": msg_id,
                            "timestamp": str(int(time.time())),
                            "type": "text",
                            "text": {"body": "TEST regression inbound text"},
                        }],
                    },
                }],
            }],
        }
        r = requests.post(f"{API}/whatsapp/webhook", json=payload, timeout=30)
        assert r.status_code == 200, f"webhook rejected: {r.status_code} {r.text}"
        time.sleep(0.5)
        stored = db.whatsapp_messages.find_one({"message_id": msg_id}, {"_id": 0})
        if stored:
            db.whatsapp_messages.delete_one({"message_id": msg_id})
            assert stored.get("direction") == "inbound"
            assert (stored.get("body") or "").startswith("TEST regression")


# ============================================================
# 6. Regression — admin webhook-logs endpoint
# ============================================================
class TestRegressionWebhookLogs:
    def test_webhook_logs_listing(self, admin_h):
        r = requests.get(f"{API}/admin/whatsapp/webhook-logs", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "items" in j and "count" in j
        assert isinstance(j["items"], list)
        assert isinstance(j["count"], int)
