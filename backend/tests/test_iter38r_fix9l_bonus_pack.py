"""Iter38r-fix9l — Tests for the bonus pack (WA tasks digest, Liluvine
weekly digest, GDPR anonymization + Export my data)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

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
        r = requests.post(f"{API}/auth/verify-otp",
                          json={"session_token": r["session_token"], "code": r["dev_otp"]},
                          timeout=10).json()
    token = r.get("access_token") or r.get("token")
    assert token, f"login failed: {r}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


# ============================================================
# parse_task_ack — pure function tests (no API call needed)
# ============================================================
def test_parse_task_ack_recognizes_ok_pattern():
    from routes.bonus_pack_9l import parse_task_ack
    assert parse_task_ack("OK 1,3,5") == [1, 3, 5]
    assert parse_task_ack("FAIT 2 5") == [2, 5]
    assert parse_task_ack("Done :1,3") == [1, 3]
    assert parse_task_ack("✅ 1 2 3") == [1, 2, 3]


def test_parse_task_ack_rejects_non_ack_messages():
    from routes.bonus_pack_9l import parse_task_ack
    # No keyword → empty
    assert parse_task_ack("J'ai 3 enfants") == []
    assert parse_task_ack("") == []
    assert parse_task_ack("Bonjour") == []


def test_parse_task_ack_dedupes_and_orders():
    from routes.bonus_pack_9l import parse_task_ack
    assert parse_task_ack("OK 1, 3, 1") == [1, 3]


# ============================================================
# WA Tasks digest opt-in
# ============================================================
def test_me_wa_tasks_digest_get_default(admin_h):
    r = requests.get(f"{API}/me/wa-tasks-digest", headers=admin_h, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body
    assert "hour" in body


def test_me_wa_tasks_digest_put_persists(admin_h, db_sync):
    r = requests.put(f"{API}/me/wa-tasks-digest", headers=admin_h, json={"enabled": True, "hour": 9}, timeout=10)
    assert r.status_code == 200
    u = db_sync.users.find_one({"email": ADMIN_EMAIL})
    assert u["wa_tasks_digest_enabled"] is True
    assert u["wa_tasks_digest_hour"] == 9
    # Reset
    requests.put(f"{API}/me/wa-tasks-digest", headers=admin_h, json={"enabled": False, "hour": 7}, timeout=10)


def test_me_wa_tasks_digest_validates_hour(admin_h):
    r = requests.put(f"{API}/me/wa-tasks-digest", headers=admin_h, json={"enabled": True, "hour": 25}, timeout=10)
    assert r.status_code == 400


# ============================================================
# GDPR Export
# ============================================================
def test_me_gdpr_export_returns_user_payload(admin_h):
    r = requests.get(f"{API}/me/gdpr/export", headers=admin_h, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "generated_at" in body
    assert body["user"]["email"] == ADMIN_EMAIL
    # password_hash must NOT be in the export
    assert "password_hash" not in body["user"]
    # Standard arrays
    assert isinstance(body.get("contacts"), list)
    assert isinstance(body.get("whatsapp_messages"), dict)
    assert isinstance(body.get("tasks"), list)
    assert isinstance(body.get("notes"), list)


# ============================================================
# Admin run-now endpoints (just verify they hit the right code path —
# they may report 0 sent on empty test data, which is fine).
# ============================================================
def test_admin_run_wa_digest_endpoint_works(admin_h, db_sync):
    db_sync.settings.update_one({"_id": "global"}, {"$set": {"wa_tasks_digest_enabled": True}})
    r = requests.post(f"{API}/admin/wa-tasks-digest/run-now", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "sent" in body
    db_sync.settings.update_one({"_id": "global"}, {"$set": {"wa_tasks_digest_enabled": False}})


def test_admin_run_liluvine_weekly_digest_endpoint_works(admin_h, db_sync):
    db_sync.settings.update_one({"_id": "global"}, {"$set": {"liluvine_weekly_digest_enabled": True}})
    # SMTP send can take 10-15s per admin → use generous timeout
    r = requests.post(f"{API}/admin/liluvine-weekly-digest/run-now", headers=admin_h, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    db_sync.settings.update_one({"_id": "global"}, {"$set": {"liluvine_weekly_digest_enabled": False}})


def test_admin_gdpr_anonymize_now_endpoint_skips_when_disabled(admin_h, db_sync):
    db_sync.settings.update_one({"_id": "global"}, {"$set": {"gdpr_auto_anonymize_enabled": False}})
    r = requests.post(f"{API}/admin/gdpr/anonymize-now", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("skipped_reason") == "disabled"


def test_admin_gdpr_anonymize_dry_run_when_enabled(admin_h, db_sync):
    db_sync.settings.update_one({"_id": "global"}, {"$set": {
        "gdpr_auto_anonymize_enabled": True,
        "gdpr_contact_inactive_months": 24,
        "gdpr_msg_retention_months": 12,
        "gdpr_log_retention_days": 90,
    }})
    r = requests.post(f"{API}/admin/gdpr/anonymize-now", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "contacts_deleted" in body
    assert "wa_messages_anonymized" in body
    assert "access_logs_deleted" in body
    # Reset
    db_sync.settings.update_one({"_id": "global"}, {"$set": {"gdpr_auto_anonymize_enabled": False}})


# ============================================================
# Task ack flow — directly via the helper (avoiding the WA webhook)
# ============================================================
def test_apply_task_ack_marks_items_done(db_sync):
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from routes.bonus_pack_9l import apply_task_ack_for_user

    async_cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    async_db = async_cli[os.environ["DB_NAME"]]

    admin = db_sync.users.find_one({"email": ADMIN_EMAIL})
    note_id = str(uuid.uuid4())
    item1_id = str(uuid.uuid4())
    item2_id = str(uuid.uuid4())
    db_sync.user_tasks_personal.insert_one({
        "id": note_id, "kind": "tasks", "owner_id": admin["id"],
        "title": "Test ack", "task_items": [
            {"id": item1_id, "text": "Item A", "done": False, "order": 0},
            {"id": item2_id, "text": "Item B", "done": False, "order": 1},
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    db_sync.wa_tasks_digest_state.update_one(
        {"user_id": admin["id"]},
        {"$set": {
            "user_id": admin["id"],
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "items": [
                {"n": 1, "note_id": note_id, "item_id": item1_id, "item_text": "Item A"},
                {"n": 2, "note_id": note_id, "item_id": item2_id, "item_text": "Item B"},
            ],
        }},
        upsert=True,
    )
    result = asyncio.new_event_loop().run_until_complete(
        apply_task_ack_for_user(async_db, admin["id"], [1])
    )
    assert result["matched"] == 1
    assert note_id in result["updated_notes"]
    refreshed = db_sync.user_tasks_personal.find_one({"id": note_id})
    items = {it["id"]: it for it in refreshed["task_items"]}
    assert items[item1_id]["done"] is True
    assert items[item2_id]["done"] is False
    # Cleanup
    db_sync.user_tasks_personal.delete_one({"id": note_id})
    db_sync.wa_tasks_digest_state.delete_one({"user_id": admin["id"]})
    async_cli.close()
