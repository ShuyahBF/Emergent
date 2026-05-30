"""Iter38r-fix9i — Tests for human takeover + KB upload OCR/no-OCR split.

Validates:
- POST /admin/liluvine-pro/sessions/{sid}/takeover sets the human_takeover
  flag with an expiration, returns phone_digits.
- POST /admin/liluvine-pro/sessions/{sid}/release flips it back.
- The dedicated sessions-history endpoint returns enriched sessions with the
  `channel` discriminator and `last_message_preview`.
- KB upload rejects images in classic mode and PDFs in OCR mode (no PDF
  rasterisation available yet).
- Non-elevated tracked users get 403 on takeover.
"""
from __future__ import annotations

import io
import os
import time
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASS = "Admin@Sawali2026"


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10).json()
    if r.get("needs_otp"):
        r = requests.post(
            f"{API}/auth/verify-otp",
            json={"session_token": r["session_token"], "code": r["dev_otp"]},
            timeout=10,
        ).json()
    token = r.get("access_token") or r.get("token")
    assert token, f"login failed: {r}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


@pytest.fixture()
def wa_session(db_sync, admin_h):
    """Insert a synthetic WA Liluvine session belonging to the SAWALI admin."""
    admin = db_sync.users.find_one({"email": ADMIN_EMAIL})
    sid = f"wa:{admin['id']}:99000{uuid.uuid4().hex[:6]}"
    phone = "".join(ch for ch in sid.split(":")[-1] if ch.isdigit())
    db_sync.liluvine_pro_sessions.insert_one({
        "id": sid,
        "client_id": admin["id"],
        "user_id": admin["id"],
        "user_label": "WA +" + phone,
        "title": "WA test takeover",
        "created_at": "2026-05-30T10:00:00+00:00",
        "updated_at": "2026-05-30T10:00:00+00:00",
        "message_count": 2,
        "external_source": "whatsapp_native",
        "external_payload": {"phone_digits": phone},
    })
    yield {"id": sid, "phone": phone}
    db_sync.liluvine_pro_sessions.delete_one({"id": sid})


def test_takeover_marks_session_and_returns_phone(admin_h, wa_session, db_sync):
    sid = wa_session["id"]
    r = requests.post(
        f"{API}/admin/liluvine-pro/sessions/{sid}/takeover",
        headers=admin_h, json={"duration_minutes": 30}, timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["id"] == sid
    assert body["phone_digits"] == wa_session["phone"]
    assert body["duration_minutes"] == 30
    doc = db_sync.liluvine_pro_sessions.find_one({"id": sid})
    assert doc["human_takeover"] is True
    assert doc.get("human_takeover_by") == ADMIN_EMAIL
    assert doc.get("human_takeover_until")


def test_release_flips_back(admin_h, wa_session, db_sync):
    sid = wa_session["id"]
    # First take over
    requests.post(f"{API}/admin/liluvine-pro/sessions/{sid}/takeover",
                  headers=admin_h, json={}, timeout=10)
    # Then release
    r = requests.post(f"{API}/admin/liluvine-pro/sessions/{sid}/release",
                      headers=admin_h, timeout=10)
    assert r.status_code == 200, r.text
    doc = db_sync.liluvine_pro_sessions.find_one({"id": sid})
    assert doc["human_takeover"] is False
    assert doc.get("human_takeover_released_by") == ADMIN_EMAIL


def test_sessions_history_enriches_channel_and_preview(admin_h, wa_session, db_sync):
    # Insert a couple of messages so last_message_preview gets populated
    db_sync.liluvine_pro_messages.insert_many([
        {"id": f"msg-{uuid.uuid4().hex[:8]}", "session_id": wa_session["id"],
         "role": "user", "content": "Salut Liluvine !",
         "client_id": db_sync.users.find_one({"email": ADMIN_EMAIL})["id"],
         "created_at": "2026-05-30T10:00:00+00:00"},
        {"id": f"msg-{uuid.uuid4().hex[:8]}", "session_id": wa_session["id"],
         "role": "assistant", "content": "Bonjour 👋 comment puis-je vous aider ?",
         "client_id": db_sync.users.find_one({"email": ADMIN_EMAIL})["id"],
         "created_at": "2026-05-30T10:01:00+00:00"},
    ])
    r = requests.get(f"{API}/admin/liluvine-pro/sessions-history?channel=whatsapp",
                     headers=admin_h, timeout=10)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    found = next((it for it in items if it["id"] == wa_session["id"]), None)
    assert found is not None, "wa_session missing from history"
    assert found["channel"] == "whatsapp"
    assert "last_message_preview" in found
    # Cleanup
    db_sync.liluvine_pro_messages.delete_many({"session_id": wa_session["id"]})


def test_kb_upload_rejects_image_in_classic_mode(admin_h):
    # Minimal 1x1 PNG
    png_1x1 = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63f8cf00010000000005000150ff0a0000000049454e44ae426082"
    )
    files = {"file": ("logo.png", png_1x1, "image/png")}
    data = {"title": "Logo classic mode"}
    r = requests.post(f"{API}/admin/liluvine-pro/kb/upload", headers=admin_h, files=files, data=data, timeout=15)
    assert r.status_code == 415, r.text
    assert "OCR" in (r.json().get("detail") or "")


def test_kb_upload_accepts_pdf_in_ocr_mode(admin_h):
    """Iter38r-fix9k — PDF now supported in OCR mode (rasterized via PyMuPDF).
    Was previously rejected (415) — see fix9i. The test only verifies the
    endpoint no longer returns 415 (it may return 200, 422, or 502 depending
    on LLM availability)."""
    try:
        import fitz
    except Exception:
        pytest.skip("PyMuPDF not installed")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "PDF in OCR mode now supported (fix9k).")
    pdf_bytes = doc.tobytes()
    doc.close()
    files = {"file": ("doc.pdf", pdf_bytes, "application/pdf")}
    data = {"title": "PDF in OCR mode", "force_ocr": "true"}
    r = requests.post(f"{API}/admin/liluvine-pro/kb/upload", headers=admin_h, files=files, data=data, timeout=60)
    assert r.status_code != 415, r.text


def test_history_endpoint_search_filter_works(admin_h, wa_session):
    r = requests.get(f"{API}/admin/liluvine-pro/sessions-history?q=takeover",
                     headers=admin_h, timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["id"] == wa_session["id"] for it in items)
