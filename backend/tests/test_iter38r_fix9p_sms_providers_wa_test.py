"""Iter38r-fix9p — Tests for the SMS-by-provider details endpoint
+ the WA OTP test-send admin endpoint."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

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


# ---------- /admin/usage/sms-providers ----------

def test_sms_providers_returns_items(admin_h):
    r = requests.get(f"{API}/admin/usage/sms-providers?days=30", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period_days"] == 30
    assert "items" in body
    for it in body["items"]:
        for k in ("provider", "sent_ok", "sent_ko", "total", "estimated_cost", "unit_cost"):
            assert k in it


def test_sms_providers_clamps_days(admin_h):
    r = requests.get(f"{API}/admin/usage/sms-providers?days=9999", headers=admin_h, timeout=15)
    assert r.status_code == 200
    assert r.json()["period_days"] == 365


def test_sms_providers_requires_admin():
    r = requests.get(f"{API}/admin/usage/sms-providers", timeout=10)
    assert r.status_code in (401, 403)


def test_sms_providers_computes_cost(admin_h, db_sync):
    """When sms_unit_cost_<provider> is set, the response includes estimated_cost."""
    # Set a fake unit cost for ORANGE
    s = db_sync.settings.find_one({"_id": "global"}) or {}
    prev = s.get("sms_unit_cost_orange")
    db_sync.settings.update_one(
        {"_id": "global"}, {"$set": {"sms_unit_cost_orange": 25.0}}, upsert=True,
    )
    try:
        # Seed 3 successful SMS via ORANGE in the last 5 days
        ids = []
        for i in range(3):
            sid = str(uuid.uuid4())
            ids.append(sid)
            now = (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat()
            db_sync.sms_messages.insert_one({
                "id": sid, "provider": "orange", "status": "sent",
                "to": "+22670000000", "client_id": "test_cost",
                "created_at": now, "sent_at": now,
            })
        r = requests.get(f"{API}/admin/usage/sms-providers?days=7", headers=admin_h, timeout=15)
        assert r.status_code == 200
        orange = next((it for it in r.json()["items"] if it["provider"].upper() == "ORANGE"), None)
        assert orange is not None
        assert orange["unit_cost"] == 25.0
        assert orange["estimated_cost"] >= 25.0 * 3
        assert orange["sent_ok"] >= 3
    finally:
        # Cleanup
        db_sync.sms_messages.delete_many({"id": {"$in": ids}})
        db_sync.settings.update_one(
            {"_id": "global"}, {"$set": {"sms_unit_cost_orange": prev or 0}},
        )


def test_sms_providers_last_failure_surfaced(admin_h, db_sync):
    """A recent failed SMS appears in last_failure."""
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db_sync.sms_messages.insert_one({
        "id": sid, "provider": "moov", "status": "failed",
        "to": "+22670000999", "client_id": "test_lf",
        "error_message": "Network timeout (test)",
        "created_at": now,
    })
    try:
        r = requests.get(f"{API}/admin/usage/sms-providers?days=1", headers=admin_h, timeout=15)
        assert r.status_code == 200
        moov = next((it for it in r.json()["items"] if it["provider"].upper() == "MOOV"), None)
        assert moov is not None
        assert moov["last_failure"] is not None
        assert "timeout" in (moov["last_failure"].get("error_message") or "").lower()
    finally:
        db_sync.sms_messages.delete_one({"id": sid})


# ---------- /admin/wa-otp/test ----------

def test_wa_otp_test_requires_admin():
    r = requests.post(f"{API}/admin/wa-otp/test", json={"msisdn": "22670000000"}, timeout=10)
    assert r.status_code in (401, 403)


def test_wa_otp_test_validates_msisdn(admin_h):
    r = requests.post(f"{API}/admin/wa-otp/test", headers=admin_h, json={"msisdn": "123"}, timeout=10)
    assert r.status_code == 400


def test_wa_otp_test_needs_template(admin_h, db_sync):
    s = db_sync.settings.find_one({"_id": "global"}) or {}
    prev_tpl = s.get("wa_otp_template")
    db_sync.settings.update_one(
        {"_id": "global"}, {"$set": {"wa_otp_template": ""}}, upsert=True,
    )
    try:
        r = requests.post(f"{API}/admin/wa-otp/test", headers=admin_h,
                          json={"msisdn": "22670000000"}, timeout=10)
        # 503 if no WA config OR 400 if no template
        assert r.status_code in (400, 503)
    finally:
        if prev_tpl is not None:
            db_sync.settings.update_one(
                {"_id": "global"}, {"$set": {"wa_otp_template": prev_tpl}},
            )
