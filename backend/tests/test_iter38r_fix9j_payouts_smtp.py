"""Iter38r-fix9j — Tests for PawaPay Payouts (v2) and SMTP from_name."""
from __future__ import annotations

import os
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


@pytest.fixture()
def pawapay_enabled(db_sync):
    """Ensure PawaPay is enabled with a sandbox token configured for tests."""
    s = db_sync.settings.find_one({"_id": "global"}) or {}
    needs = {
        "pawapay_enabled": True,
        "pawapay_environment": "sandbox",
    }
    db_sync.settings.update_one({"_id": "global"}, {"$set": needs}, upsert=True)
    # Add a fake sandbox token if absent so we can at least reach the network branch
    if not s.get("pawapay_api_token_sandbox") and not s.get("pawapay_api_token"):
        db_sync.settings.update_one(
            {"_id": "global"},
            {"$set": {"pawapay_api_token_sandbox": "fake-token-test-iter38r-fix9j"}},
        )
        yield True
        db_sync.settings.update_one(
            {"_id": "global"},
            {"$unset": {"pawapay_api_token_sandbox": ""}},
        )
    else:
        yield True


def test_payout_requires_pawapay_enabled(admin_h, db_sync):
    # Disable then call → 503
    db_sync.settings.update_one({"_id": "global"}, {"$set": {"pawapay_enabled": False}})
    r = requests.post(
        f"{API}/me/payments/pawapay/payout", headers=admin_h,
        json={"amount": 1000, "msisdn": "22670000000", "provider": "ORANGE_BFA"},
        timeout=15,
    )
    assert r.status_code == 503
    db_sync.settings.update_one({"_id": "global"}, {"$set": {"pawapay_enabled": True}})


def test_payout_validates_msisdn(admin_h, pawapay_enabled):
    r = requests.post(
        f"{API}/me/payments/pawapay/payout", headers=admin_h,
        json={"amount": 1000, "msisdn": "123", "provider": "ORANGE_BFA"},
        timeout=15,
    )
    # Pydantic min_length=8 → 422
    assert r.status_code in (400, 422), r.text


def test_payout_creates_pending_record_on_network_or_4xx(admin_h, pawapay_enabled, db_sync):
    """With a FAKE sandbox token, the call to PawaPay will get 4xx — but
    crucially, we STORE the record BEFORE the API call, and we don't mark it
    FAILED on ambiguous errors (defensive handling)."""
    msisdn = f"2267000{uuid.uuid4().hex[:4]}".replace("a", "0").replace("b", "1").replace("c", "2").replace("d", "3").replace("e", "4").replace("f", "5")
    msisdn = "".join(ch for ch in msisdn if ch.isdigit())[:11]
    r = requests.post(
        f"{API}/me/payments/pawapay/payout", headers=admin_h,
        json={"amount": 500, "msisdn": msisdn, "provider": "ORANGE_BFA",
              "customer_message": "Test fix9j"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    pid = r.json()["payout_id"]
    # Record must exist in DB
    doc = db_sync.pawapay_payouts.find_one({"id": pid})
    assert doc is not None
    assert doc["amount_xof"] == 500
    assert doc["provider"] == "ORANGE_BFA"
    assert doc["currency"] == "XOF"
    # Status is either FAILED (clean 4xx with failureReason) or PENDING (ambiguous)
    assert doc["status"] in ("PENDING", "FAILED")
    # Cleanup
    db_sync.pawapay_payouts.delete_one({"id": pid})


def test_payout_list_returns_kpis(admin_h, db_sync):
    # Seed 3 records
    admin = db_sync.users.find_one({"email": ADMIN_EMAIL})
    ids = []
    for st, amt in [("COMPLETED", 1000), ("FAILED", 500), ("PENDING", 750)]:
        pid = str(uuid.uuid4())
        ids.append(pid)
        db_sync.pawapay_payouts.insert_one({
            "id": pid, "payout_id": pid, "client_id": admin["id"],
            "tenant_id": admin["id"], "status": st, "provider": "MOOV_BFA",
            "amount_xof": amt, "currency": "XOF", "country": "BFA",
            "phone_digits": "22670000000", "amount": str(amt),
            "created_at": "2026-05-30T18:00:00+00:00",
            "updated_at": "2026-05-30T18:00:00+00:00",
        })
    r = requests.get(f"{API}/me/payments/pawapay/payouts", headers=admin_h, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["kpis"]["total"] >= 3
    assert body["kpis"]["completed"] >= 1
    assert body["kpis"]["failed"] >= 1
    assert body["kpis"]["pending"] >= 1
    db_sync.pawapay_payouts.delete_many({"id": {"$in": ids}})


def test_webhook_requires_secret(admin_h):
    r = requests.post(f"{API}/webhooks/pawapay/payouts/wrong-secret",
                      json={"payoutId": "abc", "status": "COMPLETED"}, timeout=10)
    assert r.status_code == 403


def test_webhook_with_valid_secret_updates_status(admin_h, db_sync):
    # Set a known secret
    db_sync.settings.update_one(
        {"_id": "global"},
        {"$set": {"pawapay_callback_secret": "test-secret-fix9j-iter38r"}},
    )
    admin = db_sync.users.find_one({"email": ADMIN_EMAIL})
    pid = str(uuid.uuid4())
    db_sync.pawapay_payouts.insert_one({
        "id": pid, "payout_id": pid, "client_id": admin["id"],
        "tenant_id": admin["id"], "status": "PENDING", "provider": "ORANGE_BFA",
        "amount_xof": 2500, "currency": "XOF", "country": "BFA",
        "phone_digits": "22670000000", "amount": "2500",
        "created_at": "2026-05-30T18:00:00+00:00",
        "updated_at": "2026-05-30T18:00:00+00:00",
    })
    r = requests.post(
        f"{API}/webhooks/pawapay/payouts/test-secret-fix9j-iter38r",
        json={"payoutId": pid, "status": "COMPLETED"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 1
    doc = db_sync.pawapay_payouts.find_one({"id": pid})
    assert doc["status"] == "COMPLETED"
    # Idempotency: same callback again should change nothing
    r2 = requests.post(
        f"{API}/webhooks/pawapay/payouts/test-secret-fix9j-iter38r",
        json={"payoutId": pid, "status": "COMPLETED"}, timeout=10,
    )
    assert r2.json()["applied"] == 0
    db_sync.pawapay_payouts.delete_one({"id": pid})


def test_smtp_from_name_persists(admin_h, db_sync):
    """smtp_from_name should be a writable settings key (fix9j)."""
    payload = {"smtp_from_name": "SAWALI Test From Name"}
    r = requests.put(f"{API}/admin/settings", headers=admin_h, json=payload, timeout=10)
    # 200 expected — settings endpoint accepts the new key
    assert r.status_code == 200, r.text
    s = db_sync.settings.find_one({"_id": "global"})
    assert s.get("smtp_from_name") == "SAWALI Test From Name"
