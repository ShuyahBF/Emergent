"""S037 — User-initiated escalation from the Liluvine PRO chat UI."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30).json()
    if not r.get("needs_otp"):
        return r["access_token"]
    return requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": r["session_token"], "code": r["dev_otp"]},
        timeout=30,
    ).json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    try:
        return asyncio.get_event_loop().run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@pytest.fixture
def async_db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _setup_escalation(async_db, *, enabled=True):
    async def go():
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "liluvine_escalation_enabled": enabled,
                "liluvine_escalation_wa_phone": "+22500000000",
                "liluvine_escalation_cooldown_minutes": 30,
            }}, upsert=True,
        )
        # Clear any leftover throttle for admin user
        await async_db.liluvine_escalations.delete_many({"throttle_key": ADMIN_EMAIL.lower()})
    _run(go())


def test_request_help_requires_note(admin_h, async_db):
    _setup_escalation(async_db)
    r = requests.post(f"{API}/me/liluvine-pro/request-help",
                      headers=admin_h, json={"note": "   "}, timeout=30)
    assert r.status_code == 400, r.text
    r2 = requests.post(f"{API}/me/liluvine-pro/request-help",
                       headers=admin_h, json={}, timeout=30)
    assert r2.status_code == 400


def test_request_help_disabled_returns_skipped(admin_h, async_db):
    _setup_escalation(async_db, enabled=False)
    r = requests.post(f"{API}/me/liluvine-pro/request-help",
                      headers=admin_h,
                      json={"note": "Aide URGENTE — client veut résilier"},
                      timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("sent") is False
    assert body.get("skipped_reason") == "disabled"


def test_request_help_sends_and_throttles(admin_h, async_db, db_sync):
    _setup_escalation(async_db, enabled=True)
    # First call → sent (or send_failed if WA not configured, but no throttle)
    r = requests.post(f"{API}/me/liluvine-pro/request-help",
                      headers=admin_h,
                      json={"note": "Demande de test S037"},
                      timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("to") == "+22500000000"
    # A log entry must have been persisted with the human initiator
    log = db_sync.liluvine_escalations.find_one(
        {"throttle_key": ADMIN_EMAIL.lower(), "initiator": "human"},
        sort=[("sent_at", -1)],
    )
    assert log is not None
    assert log.get("initiator") == "human"
    # Second call within cooldown → skipped
    r2 = requests.post(f"{API}/me/liluvine-pro/request-help",
                       headers=admin_h,
                       json={"note": "Encore une demande"},
                       timeout=30)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2.get("sent") is False
    assert body2.get("skipped_reason") == "throttled"
    # Cleanup
    db_sync.liluvine_escalations.delete_many({"throttle_key": ADMIN_EMAIL.lower()})


def test_request_help_long_note_truncated(admin_h, async_db, db_sync):
    _setup_escalation(async_db, enabled=True)
    long_note = "X" * 800
    r = requests.post(f"{API}/me/liluvine-pro/request-help",
                      headers=admin_h, json={"note": long_note}, timeout=30)
    assert r.status_code == 200, r.text
    log = db_sync.liluvine_escalations.find_one(
        {"throttle_key": ADMIN_EMAIL.lower(), "initiator": "human"},
        sort=[("sent_at", -1)],
    )
    assert log is not None
    # last_user_message capped at 400 chars + ellipsis
    assert len(log.get("last_user_message", "")) <= 410
    db_sync.liluvine_escalations.delete_many({"throttle_key": ADMIN_EMAIL.lower()})


def test_request_help_human_header_in_wa_message(async_db):
    """notify_admin(initiator='human') must use the collaborator header."""
    from routes.liluvine_escalation import notify_admin
    sent = []

    async def fake(to, text):
        sent.append({"to": to, "text": text})
        return {"ok": True}

    async def go():
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "liluvine_escalation_enabled": True,
                "liluvine_escalation_wa_phone": "+22500000000",
                "liluvine_escalation_cooldown_minutes": 30,
            }}, upsert=True,
        )
        await async_db.liluvine_escalations.delete_many({"throttle_key": "alice@example.com"})
        res = await notify_admin(
            async_db,
            contact_name="Alice Modératrice",
            contact_phone_digits="",
            last_user_message="Comment annuler une commande déjà payée ?",
            reason="Demande d'aide manuelle du collaborateur — Comment annuler une commande déjà payée ?",
            send_wa=fake,
            initiator="human",
            throttle_key="alice@example.com",
        )
        assert res["sent"] is True
        assert "Demande d'aide d'un collaborateur" in sent[0]["text"]
        assert "Collaborateur" in sent[0]["text"]
        assert "Alice Modératrice" in sent[0]["text"]

    _run(go())


def test_request_help_requires_auth():
    r = requests.post(f"{API}/me/liluvine-pro/request-help",
                      json={"note": "anonymous"}, timeout=30)
    # 401/403 either is acceptable here, just must NOT be 200/500
    assert r.status_code in (401, 403, 422), r.text
