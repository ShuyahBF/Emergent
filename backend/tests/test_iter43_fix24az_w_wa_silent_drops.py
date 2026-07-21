"""Iter43-fix24az-w (2026-07-22) — WhatsApp silent-drop monitoring & alerts.

Verifies :
  1. GET /api/admin/wa-silent-drops/stats returns the expected shape with
     defaults when no config has been saved.
  2. PUT /api/admin/wa-silent-drops/config persists all fields (enabled,
     threshold, window/cooldown minutes, emails, wa_phones) — with proper
     sanitisation (invalid emails/phones dropped).
  3. GET /api/admin/wa-silent-drops lists inserted drop records.
  4. POST /api/admin/wa-silent-drops/test-alert returns per-recipient results
     even when no send channels are configured.
  5. DELETE /api/admin/wa-silent-drops purges all records.
  6. The observer callback `record_and_notify` inserts a drop doc when
     invoked with a silent-drop context.
  7. When the number of drops in the window exceeds the threshold and alerts
     are enabled, `record_and_notify` fires the injected send_email + wa_send
     callables (verified via mocked spies).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    u = db.users.find_one({"email": "admin@sawalismartsystems.com"})
    return pyjwt.encode({
        "sub": u["id"], "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(autouse=True)
def _cleanup(db):
    """Reset config + drops before each test to avoid cross-pollution."""
    db.settings.update_one(
        {"_id": "global"},
        {"$unset": {
            "wa_alert_enabled": "", "wa_alert_threshold": "",
            "wa_alert_window_minutes": "", "wa_alert_cooldown_minutes": "",
            "wa_alert_emails": "", "wa_alert_wa_phones": "",
            "wa_alert_last_sent_at": "",
        }},
    )
    db.wa_silent_drops.delete_many({})
    yield
    db.wa_silent_drops.delete_many({})


# =============================================================================
# 1. GET /stats — shape + defaults
# =============================================================================
def test_stats_default_shape(admin_token, db):
    r = requests.get(f"{API}/admin/wa-silent-drops/stats", headers=h(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_15m"] == 0
    assert body["last_1h"] == 0
    assert body["last_24h"] == 0
    assert body["threshold_reached"] is False
    cfg = body["config"]
    assert cfg["enabled"] is False
    assert cfg["threshold"] == 5
    assert cfg["window_minutes"] == 15
    assert cfg["cooldown_minutes"] == 60
    assert cfg["emails"] == []
    assert cfg["wa_phones"] == []


# =============================================================================
# 2. PUT /config — persists + sanitises
# =============================================================================
def test_update_config_persists_and_sanitises(admin_token, db):
    r = requests.put(
        f"{API}/admin/wa-silent-drops/config",
        headers=h(admin_token),
        json={
            "enabled": True,
            "threshold": 8,
            "window_minutes": 20,
            "cooldown_minutes": 45,
            "emails": [
                "ops@sawalismartsystems.com",
                "invalid-email",           # dropped (no @)
                "another@example.com",
                "no-domain@",              # dropped (no . after @)
            ],
            "wa_phones": [
                "+226 70 00 11 22",         # kept — 12 digits (>=6)
                "12345",                    # dropped (too short)
                "228 90-12-34-56",          # kept — 11 digits
            ],
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["threshold"] == 8
    assert body["window_minutes"] == 20
    assert body["cooldown_minutes"] == 45
    assert body["emails"] == ["ops@sawalismartsystems.com", "another@example.com"]
    assert body["wa_phones"] == ["22670001122", "22890123456"]


def test_update_config_rejects_empty_payload(admin_token, db):
    r = requests.put(
        f"{API}/admin/wa-silent-drops/config",
        headers=h(admin_token), json={}, timeout=15,
    )
    assert r.status_code == 400
    assert "champ" in r.json()["detail"].lower()


def test_update_config_validates_ranges(admin_token, db):
    r = requests.put(
        f"{API}/admin/wa-silent-drops/config",
        headers=h(admin_token),
        json={"threshold": 0, "window_minutes": 15},
        timeout=15,
    )
    # threshold < 1 → 422 (pydantic ge=1)
    assert r.status_code == 422


# =============================================================================
# 3. GET / — list drops
# =============================================================================
def test_list_drops_returns_records(admin_token, db):
    # Insert 3 synthetic drops
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.wa_silent_drops.insert_one({
            "id": f"drop-test-{i}",
            "to": f"22670001{i:03d}",
            "chunk_index": 1, "chunk_total": 1,
            "chunk_length": 100 + i,
            "chunk_preview": f"Test preview {i}",
            "http_status": 200,
            "kind": "silent_drop_no_message_id",
            "raw": "{}",
            "created_at": (now - timedelta(minutes=i)).isoformat(),
        })
    r = requests.get(f"{API}/admin/wa-silent-drops?limit=10",
                     headers=h(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 3
    # Sorted by created_at DESC
    ids = [d["id"] for d in body["drops"] if d["id"].startswith("drop-test-")]
    assert ids == ["drop-test-0", "drop-test-1", "drop-test-2"]


# =============================================================================
# 4. POST /test-alert — returns per-recipient results
# =============================================================================
def test_test_alert_with_no_recipients(admin_token, db):
    r = requests.post(f"{API}/admin/wa-silent-drops/test-alert",
                      headers=h(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipients_total"] == 0
    assert body["email_results"] == []
    assert body["wa_results"] == []


def test_test_alert_returns_recipient_results(admin_token, db):
    # Configure recipients (fake — no real delivery expected but the route
    # attempts and reports back).
    requests.put(
        f"{API}/admin/wa-silent-drops/config",
        headers=h(admin_token),
        json={
            "enabled": True, "threshold": 3, "window_minutes": 10,
            "cooldown_minutes": 60,
            "emails": ["fake+silentdrop@example.com"],
            "wa_phones": ["22699999999"],
        },
        timeout=15,
    )
    r = requests.post(f"{API}/admin/wa-silent-drops/test-alert",
                      headers=h(admin_token), timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipients_total"] == 2
    assert len(body["email_results"]) == 1
    assert body["email_results"][0]["email"] == "fake+silentdrop@example.com"
    assert len(body["wa_results"]) == 1
    assert body["wa_results"][0]["phone"] == "22699999999"
    # Each result must have an `ok` boolean regardless of actual delivery.
    for res in body["email_results"] + body["wa_results"]:
        assert "ok" in res


# =============================================================================
# 5. DELETE / — purge
# =============================================================================
def test_delete_purges_all_drops(admin_token, db):
    db.wa_silent_drops.insert_many([
        {"id": "d1", "to": "22670001", "chunk_index": 1, "chunk_total": 1,
         "chunk_length": 100, "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": "d2", "to": "22670002", "chunk_index": 1, "chunk_total": 1,
         "chunk_length": 200, "created_at": datetime.now(timezone.utc).isoformat()},
    ])
    r = requests.delete(f"{API}/admin/wa-silent-drops",
                        headers=h(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] >= 2
    # Verify empty
    r2 = requests.get(f"{API}/admin/wa-silent-drops",
                      headers=h(admin_token), timeout=15)
    assert r2.json()["count"] == 0


# =============================================================================
# 6/7. Observer + threshold trigger (unit)
# =============================================================================
def _fresh_async_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_observer_inserts_drop_and_fires_alert_when_threshold_met(db):
    """Unit test on the returned `record_and_notify` callable. We spy on
    the send_email / wa_send_text callables to verify they're invoked."""
    from routes.wa_silent_drops import setup_wa_silent_drops_routes

    # Reset config → enabled with a very low threshold so we trip it in-test
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "wa_alert_enabled": True,
            "wa_alert_threshold": 2,
            "wa_alert_window_minutes": 60,
            "wa_alert_cooldown_minutes": 60,
            "wa_alert_emails": ["ops@example.com"],
            "wa_alert_wa_phones": ["22670001111"],
        },
         "$unset": {"wa_alert_last_sent_at": ""}},
        upsert=True,
    )
    db.wa_silent_drops.delete_many({})

    email_calls = []
    wa_calls = []

    async def _mock_send_email(*, to, subject, body):
        email_calls.append({"to": to, "subject": subject})
        return True

    async def _mock_wa_send_text(to_e164, text):
        wa_calls.append({"to": to_e164, "text_prefix": text[:50]})
        return {"ok": True, "message_id": f"wamid-mock-{len(wa_calls)}"}

    # Minimal stub API — we don't need to register routes for the observer.
    class _StubApi:
        def get(self, *a, **k):
            def deco(fn): return fn
            return deco
        put = post = delete = get

    helpers = setup_wa_silent_drops_routes(
        api=_StubApi(),
        db=_fresh_async_db(),
        get_current_admin=lambda: {},
        send_email_fn=_mock_send_email,
        wa_send_text_fn=_mock_wa_send_text,
    )
    record_and_notify = helpers["record_and_notify"]

    async def _run():
        # First drop → below threshold, no alert.
        await record_and_notify({
            "to": "22670001234", "chunk_index": 1, "chunk_total": 1,
            "chunk_length": 100, "chunk_preview": "hello",
            "http_status": 200, "raw": "{}",
            "at": datetime.now(timezone.utc).isoformat(),
        })
        # Second drop → hits threshold=2, alert fires.
        await record_and_notify({
            "to": "22670001234", "chunk_index": 1, "chunk_total": 1,
            "chunk_length": 200, "chunk_preview": "world",
            "http_status": 200, "raw": "{}",
            "at": datetime.now(timezone.utc).isoformat(),
        })

    _run_async(_run())

    # Both drops persisted
    assert db.wa_silent_drops.count_documents({}) == 2
    # Alert fired once (2nd drop triggered it — 1st alone was below threshold)
    assert len(email_calls) == 1, f"email_calls={email_calls}"
    assert email_calls[0]["to"] == "ops@example.com"
    assert "silent drop" in email_calls[0]["subject"].lower()
    assert len(wa_calls) == 1, f"wa_calls={wa_calls}"
    assert wa_calls[0]["to"] == "+22670001111"
    # last_sent_at was persisted → cooldown active
    s = db.settings.find_one({"_id": "global"})
    assert s.get("wa_alert_last_sent_at")


def test_observer_respects_cooldown(db):
    """If cooldown hasn't elapsed since last alert, no new alert is sent
    even when threshold is met."""
    from routes.wa_silent_drops import setup_wa_silent_drops_routes

    # Set config: threshold=1 (always trip), cooldown=60min, last_sent 1 min ago
    just_now = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "wa_alert_enabled": True, "wa_alert_threshold": 1,
            "wa_alert_window_minutes": 60, "wa_alert_cooldown_minutes": 60,
            "wa_alert_emails": ["ops@example.com"],
            "wa_alert_wa_phones": [],
            "wa_alert_last_sent_at": just_now,
        }},
        upsert=True,
    )
    db.wa_silent_drops.delete_many({})

    email_calls = []

    async def _mock_send_email(*, to, subject, body):
        email_calls.append({"to": to})
        return True

    class _StubApi:
        def get(self, *a, **k):
            def deco(fn): return fn
            return deco
        put = post = delete = get

    helpers = setup_wa_silent_drops_routes(
        api=_StubApi(), db=_fresh_async_db(),
        get_current_admin=lambda: {},
        send_email_fn=_mock_send_email, wa_send_text_fn=None,
    )
    record_and_notify = helpers["record_and_notify"]

    async def _run():
        await record_and_notify({
            "to": "22670001234", "chunk_index": 1, "chunk_total": 1,
            "chunk_length": 100, "chunk_preview": "cooldown-test",
            "http_status": 200, "raw": "{}",
            "at": datetime.now(timezone.utc).isoformat(),
        })

    _run_async(_run())
    # Drop persisted, but NO alert sent (cooldown active)
    assert db.wa_silent_drops.count_documents({}) == 1
    assert email_calls == [], f"Expected no alerts during cooldown, got {email_calls}"


def test_observer_noop_when_alerts_disabled(db):
    """When wa_alert_enabled is False, observer still records the drop but
    never fires an alert regardless of threshold."""
    from routes.wa_silent_drops import setup_wa_silent_drops_routes

    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "wa_alert_enabled": False,
            "wa_alert_threshold": 1,
            "wa_alert_emails": ["ops@example.com"],
        }, "$unset": {"wa_alert_last_sent_at": ""}},
        upsert=True,
    )
    db.wa_silent_drops.delete_many({})

    email_calls = []

    async def _mock_send_email(*, to, subject, body):
        email_calls.append(to)
        return True

    class _StubApi:
        def get(self, *a, **k):
            def deco(fn): return fn
            return deco
        put = post = delete = get

    helpers = setup_wa_silent_drops_routes(
        api=_StubApi(), db=_fresh_async_db(),
        get_current_admin=lambda: {},
        send_email_fn=_mock_send_email, wa_send_text_fn=None,
    )

    async def _run():
        await helpers["record_and_notify"]({
            "to": "22670001234", "chunk_index": 1, "chunk_total": 1,
            "chunk_length": 100, "chunk_preview": "disabled-test",
            "http_status": 200, "raw": "{}",
            "at": datetime.now(timezone.utc).isoformat(),
        })

    _run_async(_run())
    assert db.wa_silent_drops.count_documents({}) == 1
    assert email_calls == []
