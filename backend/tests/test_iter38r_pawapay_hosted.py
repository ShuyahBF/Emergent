"""Iter38r — PawaPay Hosted Payment Page flow.

Tests the new /me/payments/pawapay/payment-page endpoint, the legacy
/deposit forwarder, and the admin pawapay_fix_msisdn toggle.

We do NOT hit PawaPay's real sandbox here — we exercise the input
validation, feature-flag gating, document persistence and the
admin toggle. The actual PawaPay HTTP call is short-circuited
by disabling `pawapay_enabled` for the "rejection" paths, while
the "happy path" only requires a fake token + we tolerate the 502
that PawaPay's sandbox returns for unknown tokens (we still
assert the payment doc was persisted with status=failed).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def env(db):
    admin_id = f"r_adm_{uuid.uuid4().hex[:6]}"
    client_id = f"r_cli_{uuid.uuid4().hex[:6]}"
    company = f"R-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin R", "company": company, "role": "admin",
         "account_status": "active", "created_at": now,
         "features": {"payments": True},
         "whatsapp": "+22675001122"},
        {"id": client_id, "email": f"{client_id}@t.l", "password_hash": "x",
         "full_name": "Regular R", "company": company, "role": "client",
         "tracked_user_id": admin_id, "client_id": admin_id,
         "account_status": "active", "created_at": now},
    ])
    # Snapshot existing settings to restore later
    original = db.settings.find_one({"_id": "global"}) or {}
    yield {
        "admin_id": admin_id, "client_id": client_id,
        "admin_token": _forge(admin_id, "admin"),
        "client_token": _forge(client_id, "client"),
        "original_settings": original,
    }
    db.users.delete_many({"id": {"$in": [admin_id, client_id]}})
    db.payments.delete_many({"user_id": {"$in": [admin_id, client_id]}})
    # Restore settings exactly
    if original:
        db.settings.replace_one({"_id": "global"}, original, upsert=True)
    else:
        db.settings.delete_one({"_id": "global"})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _disable_pawapay(db):
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"pawapay_enabled": False}},
        upsert=True,
    )


def _enable_pawapay_no_token(db):
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"pawapay_enabled": True,
                  "pawapay_environment": "sandbox",
                  "pawapay_api_token_sandbox": "",
                  "pawapay_api_token": "",
                  "pawapay_country": "BFA"}},
        upsert=True,
    )


def _enable_pawapay_with_fake_token(db):
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"pawapay_enabled": True,
                  "pawapay_environment": "sandbox",
                  "pawapay_api_token_sandbox": "fake-token-iter38r-test",
                  "pawapay_country": "BFA",
                  "pawapay_fix_msisdn_default": True}},
        upsert=True,
    )


# ====================================================================
# Payment Page endpoint — gating
# ====================================================================
def test_payment_page_503_when_disabled(env, db):
    _disable_pawapay(db)
    r = requests.post(f"{API}/me/payments/pawapay/payment-page",
                      headers=_h(env["admin_token"]),
                      json={"amount": 1000})
    assert r.status_code == 503
    assert "pawapay" in r.json()["detail"].lower()


def test_payment_page_503_when_no_token(env, db):
    _enable_pawapay_no_token(db)
    r = requests.post(f"{API}/me/payments/pawapay/payment-page",
                      headers=_h(env["admin_token"]),
                      json={"amount": 1000})
    assert r.status_code == 503
    assert "clé api" in r.json()["detail"].lower() or "token" in r.json()["detail"].lower()


def test_payment_page_403_for_client_without_feature(env, db):
    _enable_pawapay_with_fake_token(db)
    # Disable payments on the parent (admin)
    db.users.update_one(
        {"id": env["admin_id"]},
        {"$set": {"features": {"payments": False}}},
    )
    r = requests.post(f"{API}/me/payments/pawapay/payment-page",
                      headers=_h(env["client_token"]),
                      json={"amount": 1000})
    assert r.status_code == 403
    # Restore
    db.users.update_one(
        {"id": env["admin_id"]},
        {"$set": {"features": {"payments": True}}},
    )


# ====================================================================
# Payment Page endpoint — happy / failure persistence
# ====================================================================
def test_payment_page_persists_doc_even_when_pawapay_rejects(env, db):
    """When PawaPay rejects (fake token), we still must have persisted a
    payments row with flow=payment_page so reconciliation works."""
    _enable_pawapay_with_fake_token(db)
    r = requests.post(f"{API}/me/payments/pawapay/payment-page",
                      headers=_h(env["admin_token"]),
                      json={"amount": 500, "country": "BFA", "reason": "Test38r"})
    # Either PawaPay's sandbox refused (502) or, very rarely, accepted (200).
    assert r.status_code in (200, 502), r.text
    # In either case, a payment doc must exist for this admin
    doc = db.payments.find_one(
        {"user_id": env["admin_id"], "flow": "payment_page"},
        sort=[("created_at", -1)],
    )
    assert doc is not None, "Payment doc should be persisted before calling PawaPay"
    assert doc["amount"] == 500.0
    assert doc["currency"] == "XOF"
    assert doc["country"] == "BFA"
    if r.status_code == 502:
        assert doc["status"] == "failed"
        assert doc["api_status"] == "PAYMENT_PAGE_REJECTED"
    else:
        # 200 — must contain redirect_url
        body = r.json()
        assert body["deposit_id"]
        assert body["redirect_url"]
        assert body["return_url"]


def test_payment_page_uses_whatsapp_when_fix_msisdn_true(env, db):
    """admin.whatsapp = +22675001122 → msisdn must be pre-fixed (digits only)."""
    _enable_pawapay_with_fake_token(db)
    db.users.update_one({"id": env["admin_id"]}, {"$set": {"pawapay_fix_msisdn": True}})
    r = requests.post(f"{API}/me/payments/pawapay/payment-page",
                      headers=_h(env["admin_token"]),
                      json={"amount": 500})
    assert r.status_code in (200, 502)
    doc = db.payments.find_one(
        {"user_id": env["admin_id"], "flow": "payment_page"},
        sort=[("created_at", -1)],
    )
    assert doc is not None
    assert doc["msisdn"] == "22675001122"


def test_payment_page_leaves_msisdn_blank_when_fix_disabled(env, db):
    _enable_pawapay_with_fake_token(db)
    db.users.update_one({"id": env["admin_id"]}, {"$set": {"pawapay_fix_msisdn": False}})
    r = requests.post(f"{API}/me/payments/pawapay/payment-page",
                      headers=_h(env["admin_token"]),
                      json={"amount": 500})
    assert r.status_code in (200, 502)
    doc = db.payments.find_one(
        {"user_id": env["admin_id"], "flow": "payment_page"},
        sort=[("created_at", -1)],
    )
    assert doc is not None
    assert doc["msisdn"] is None


def test_payment_page_uses_default_origin_in_return_url(env, db):
    _enable_pawapay_with_fake_token(db)
    r = requests.post(f"{API}/me/payments/pawapay/payment-page",
                      headers=_h(env["admin_token"]),
                      json={"amount": 500})
    assert r.status_code in (200, 502)
    doc = db.payments.find_one(
        {"user_id": env["admin_id"], "flow": "payment_page"},
        sort=[("created_at", -1)],
    )
    assert doc is not None
    assert doc["return_url"]
    assert "/portal/payments/return" in doc["return_url"]
    assert "depositId=" in doc["return_url"]


# ====================================================================
# Legacy /deposit endpoint — must forward to payment-page
# ====================================================================
def test_legacy_deposit_forwards_to_payment_page(env, db):
    _enable_pawapay_with_fake_token(db)
    r = requests.post(f"{API}/me/payments/pawapay/deposit",
                      headers=_h(env["admin_token"]),
                      json={"amount": 750, "mno": "ORANGE", "msisdn": "+22675223344"})
    assert r.status_code in (200, 502), r.text
    if r.status_code == 200:
        body = r.json()
        assert body.get("deprecated") is True
        assert body.get("redirect_url")
    # Persisted doc must have flow=payment_page (NOT direct deposit)
    doc = db.payments.find_one(
        {"user_id": env["admin_id"]},
        sort=[("created_at", -1)],
    )
    assert doc is not None
    assert doc["flow"] == "payment_page"


# ====================================================================
# Admin pawapay_fix_msisdn toggle
# ====================================================================
def test_admin_get_features_returns_fix_msisdn(env, db):
    db.users.update_one({"id": env["admin_id"]}, {"$set": {"pawapay_fix_msisdn": True}})
    r = requests.get(f"{API}/admin/clients/{env['admin_id']}/features",
                     headers=_h(env["admin_token"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "pawapay_fix_msisdn" in body
    assert body["pawapay_fix_msisdn"] is True


def test_admin_put_features_updates_fix_msisdn(env, db):
    r = requests.put(f"{API}/admin/clients/{env['admin_id']}/features",
                     headers=_h(env["admin_token"]),
                     json={"pawapay_fix_msisdn": False})
    assert r.status_code == 200, r.text
    assert r.json()["pawapay_fix_msisdn"] is False
    u = db.users.find_one({"id": env["admin_id"]}, {"_id": 0, "pawapay_fix_msisdn": 1})
    assert u["pawapay_fix_msisdn"] is False


def test_admin_put_features_can_set_fix_msisdn_true(env, db):
    db.users.update_one({"id": env["admin_id"]}, {"$set": {"pawapay_fix_msisdn": False}})
    r = requests.put(f"{API}/admin/clients/{env['admin_id']}/features",
                     headers=_h(env["admin_token"]),
                     json={"pawapay_fix_msisdn": True})
    assert r.status_code == 200
    assert r.json()["pawapay_fix_msisdn"] is True


# ====================================================================
# Polling endpoint
# ====================================================================
def test_polling_returns_404_for_unknown_deposit(env, db):
    r = requests.get(f"{API}/me/payments/does-not-exist-{uuid.uuid4().hex[:6]}",
                     headers=_h(env["admin_token"]))
    assert r.status_code == 404


def test_polling_returns_doc_when_already_final(env, db):
    """If a payment row is already final (completed/failed), the endpoint
    must just return it without trying to refresh from PawaPay."""
    deposit_id = f"dep_{uuid.uuid4().hex[:8]}"
    db.payments.insert_one({
        "id": uuid.uuid4().hex,
        "deposit_id": deposit_id,
        "client_id": env["admin_id"],
        "user_id": env["admin_id"],
        "status": "completed",
        "amount": 1000.0,
        "currency": "XOF",
        "flow": "payment_page",
        "environment": "sandbox",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.get(f"{API}/me/payments/{deposit_id}",
                     headers=_h(env["admin_token"]))
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    db.payments.delete_one({"deposit_id": deposit_id})


def test_polling_blocks_other_user(env, db):
    deposit_id = f"dep_{uuid.uuid4().hex[:8]}"
    other_id = f"r_other_{uuid.uuid4().hex[:6]}"
    db.payments.insert_one({
        "id": uuid.uuid4().hex,
        "deposit_id": deposit_id,
        "client_id": other_id,
        "user_id": other_id,
        "status": "pending",
        "flow": "payment_page",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.get(f"{API}/me/payments/{deposit_id}",
                     headers=_h(env["client_token"]))
    assert r.status_code == 403
    db.payments.delete_one({"deposit_id": deposit_id})
