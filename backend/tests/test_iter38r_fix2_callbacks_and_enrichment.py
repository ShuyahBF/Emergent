"""Iter38r-fix2 — Provider/phoneNumber enrichment + callback URLs.

Validates:
- _pawapay_split_provider() parses ORANGE_BFA, MTN_MOMO_ZMB, TELECEL_BFA correctly
- /admin/pawapay/callback-urls auto-generates secret and returns 3 URLs
- Polling and webhooks persist provider + extract MNO short code
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
    admin_id = f"fix2_adm_{uuid.uuid4().hex[:6]}"
    company = f"FX2-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "full_name": "Admin FX2", "company": company, "role": "admin",
        "account_status": "active", "created_at": now,
    })
    original = db.settings.find_one({"_id": "global"}) or {}
    yield {"admin_id": admin_id, "admin_token": _forge(admin_id, "admin")}
    db.users.delete_many({"id": admin_id})
    db.payments.delete_many({"user_id": admin_id})
    if original:
        db.settings.replace_one({"_id": "global"}, original, upsert=True)
    else:
        db.settings.delete_one({"_id": "global"})


def _h(tok): return {"Authorization": f"Bearer {tok}"}


# ====================================================================
# Provider parser unit-style tests
# ====================================================================
def test_split_provider_orange_bfa():
    import sys; sys.path.insert(0, "/app/backend")
    import importlib; server = importlib.import_module("server")
    assert server._pawapay_split_provider("ORANGE_BFA") == ("ORANGE", "BFA")
    assert server._pawapay_split_provider("MOOV_BFA") == ("MOOV", "BFA")
    assert server._pawapay_split_provider("TELECEL_BFA") == ("TELECEL", "BFA")
    assert server._pawapay_split_provider("MTN_MOMO_ZMB") == ("MTN", "ZMB")
    assert server._pawapay_split_provider("AIRTEL_MONEY_UGA") == ("AIRTEL", "UGA")
    assert server._pawapay_split_provider("") == (None, None)
    assert server._pawapay_split_provider(None) == (None, None)


# ====================================================================
# /admin/pawapay/callback-urls
# ====================================================================
def test_callback_urls_endpoint_returns_three_urls(env, db):
    # Pre-set a known secret
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"pawapay_callback_secret": "known-secret-iter38r-fix2"}},
        upsert=True,
    )
    r = requests.get(f"{API}/admin/pawapay/callback-urls", headers=_h(env["admin_token"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "deposits_url" in body
    assert "refunds_url" in body
    assert "legacy_url" in body
    assert body["deposits_url"].endswith("/api/webhooks/pawapay/deposits/known-secret-iter38r-fix2")
    assert body["refunds_url"].endswith("/api/webhooks/pawapay/refunds/known-secret-iter38r-fix2")
    assert body["legacy_url"].endswith("/api/webhooks/pawapay/known-secret-iter38r-fix2")
    assert body["secret_preview"]  # masked


def test_callback_urls_auto_generates_missing_secret(env, db):
    # Ensure secret is absent
    db.settings.update_one(
        {"_id": "global"},
        {"$unset": {"pawapay_callback_secret": ""}},
        upsert=True,
    )
    r = requests.get(f"{API}/admin/pawapay/callback-urls", headers=_h(env["admin_token"]))
    assert r.status_code == 200
    body = r.json()
    # Re-read from DB and confirm a non-empty secret now exists
    s = db.settings.find_one({"_id": "global"}, {"_id": 0, "pawapay_callback_secret": 1})
    assert s and s.get("pawapay_callback_secret")
    assert len(s["pawapay_callback_secret"]) >= 32
    # And URLs match
    assert s["pawapay_callback_secret"] in body["deposits_url"]


def test_callback_urls_requires_admin(env, db):
    # Create a separate non-admin user
    client_id = f"fix2_cli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": client_id, "email": f"{client_id}@t.l", "password_hash": "x",
        "full_name": "Client FX2", "role": "client",
        "account_status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        client_token = _forge(client_id, "client")
        r = requests.get(f"{API}/admin/pawapay/callback-urls", headers=_h(client_token))
        assert r.status_code in (401, 403)
    finally:
        db.users.delete_one({"id": client_id})


# ====================================================================
# Webhook deposits/refunds — both routes accepted
# ====================================================================
def _seed_secret(db, secret="seed-secret-fix2"):
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"pawapay_callback_secret": secret}},
        upsert=True,
    )
    return secret


def test_webhook_deposits_route_accepts(env, db):
    secret = _seed_secret(db)
    deposit_id = f"d_{uuid.uuid4().hex[:8]}"
    db.payments.insert_one({
        "id": uuid.uuid4().hex, "deposit_id": deposit_id,
        "client_id": env["admin_id"], "user_id": env["admin_id"],
        "status": "pending", "flow": "payment_page",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.post(
        f"{API}/webhooks/pawapay/deposits/{secret}",
        json={"depositId": deposit_id, "status": "COMPLETED", "provider": "ORANGE_BFA",
              "phoneNumber": "22675001122", "respondedTimestamp": "2026-05-28T10:00:00Z"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
    assert r.json()["op"] == "deposit"
    # Check enrichment
    doc = db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
    assert doc["mno"] == "ORANGE"
    assert doc["provider"] == "ORANGE_BFA"
    assert doc["last_webhook_op"] == "deposit"
    assert doc["msisdn_from_webhook"] == "22675001122"


def test_webhook_refunds_route_accepts(env, db):
    secret = _seed_secret(db)
    deposit_id = f"d_{uuid.uuid4().hex[:8]}"
    db.payments.insert_one({
        "id": uuid.uuid4().hex, "deposit_id": deposit_id,
        "client_id": env["admin_id"], "user_id": env["admin_id"],
        "status": "completed", "flow": "payment_page",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.post(
        f"{API}/webhooks/pawapay/refunds/{secret}",
        json={"depositId": deposit_id, "status": "COMPLETED", "provider": "MOOV_BFA"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["op"] == "refund"
    doc = db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
    assert doc["last_webhook_op"] == "refund"
    assert doc["mno"] == "MOOV"


def test_webhook_rejects_invalid_secret(env, db):
    _seed_secret(db, "real-secret")
    r = requests.post(
        f"{API}/webhooks/pawapay/deposits/wrong-secret",
        json={"depositId": "x", "status": "COMPLETED"},
    )
    assert r.status_code == 403


def test_legacy_webhook_still_works(env, db):
    secret = _seed_secret(db)
    deposit_id = f"d_{uuid.uuid4().hex[:8]}"
    db.payments.insert_one({
        "id": uuid.uuid4().hex, "deposit_id": deposit_id,
        "client_id": env["admin_id"], "user_id": env["admin_id"],
        "status": "pending", "flow": "payment_page",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.post(
        f"{API}/webhooks/pawapay/{secret}",
        json={"depositId": deposit_id, "status": "COMPLETED", "provider": "TELECEL_BFA"},
    )
    assert r.status_code == 200
    # Auto-detected as deposit (no refundId)
    assert r.json()["op"] == "deposit"
    doc = db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
    assert doc["mno"] == "TELECEL"
