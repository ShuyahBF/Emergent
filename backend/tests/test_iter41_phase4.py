"""Iter41 Phase 4 (2026-02) — Tests pour le dashboard VIDAL + l'API publique HMAC."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
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


def _forge(uid, role="admin"):
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    aid = f"dash_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "admin"), aid
    db.users.delete_one({"id": aid})


# ---------------------------------------------------------------------- #
# Dashboard
# ---------------------------------------------------------------------- #
def test_vidal_usage_dashboard(db, admin_token):
    token, _ = admin_token
    # Seed some usage data
    today = datetime.now(timezone.utc).date().isoformat()
    db.vidal_usage_daily.insert_one({
        "user_id": "u1", "day": today, "count": 42,
        "updated_at": datetime.now(timezone.utc),
    })
    db.vidal_prescription_audit.insert_one({
        "user_id": "u1", "mode": "test",
        "created_at": datetime.now(timezone.utc),
        "request": {}, "response_summary": "ok",
    })
    r = requests.get(f"{API}/admin/vidal/usage?days=30",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period_days"] == 30
    assert "totals" in body
    assert body["totals"]["vidal_calls"] >= 42
    assert "daily_series" in body
    assert isinstance(body["daily_series"], list)
    assert "top_consumers" in body
    assert "by_mode" in body
    # Cleanup
    db.vidal_usage_daily.delete_many({"user_id": "u1"})
    db.vidal_prescription_audit.delete_many({"user_id": "u1"})


def test_officines_usage_dashboard(db, admin_token):
    token, _ = admin_token
    # Seed
    db.officines_audit.insert_one({
        "user_id": "u1", "product_name": "Doliprane 1g",
        "result_count": 3, "created_at": datetime.now(timezone.utc),
    })
    db.officines_public_usage.insert_one({
        "phone": "22670000000", "day": datetime.now(timezone.utc).date().isoformat(),
        "count": 5, "updated_at": datetime.now(timezone.utc),
    })
    r = requests.get(f"{API}/admin/officines/usage?days=30",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["portal_lookups"] >= 1
    assert body["totals"]["wa_aizenta_calls"] >= 5
    assert any(p["product"] == "Doliprane 1g" for p in body["top_products"])
    db.officines_audit.delete_many({"user_id": "u1"})
    db.officines_public_usage.delete_many({"phone": "22670000000"})


def test_dashboard_rbac_blocks_clients(db):
    uid = f"dash_cli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({"id": uid, "email": f"{uid}@t.l", "role": "client", "account_status": "active",
                         "created_at": datetime.now(timezone.utc).isoformat()})
    token = _forge(uid, "client")
    r = requests.get(f"{API}/admin/vidal/usage",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code in (401, 403)
    db.users.delete_one({"id": uid})


# ---------------------------------------------------------------------- #
# Public Officines Register (HMAC)
# ---------------------------------------------------------------------- #
def _sign(secret: str, ts: int, body: bytes) -> str:
    msg = f"{ts}.{body.decode()}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def test_public_officines_register_rejects_without_secret(db):
    """No HMAC secret configured → 503."""
    db.settings.update_one({"_id": "global"}, {"$set": {"officines_register_hmac_secret": ""}}, upsert=True)
    body = json.dumps({"officine_name": "Test", "inventory": []}).encode()
    ts = int(time.time())
    r = requests.post(
        f"{API}/public/officines/register",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": "x",
                 "X-Timestamp": str(ts), "X-Officine-Id": "test"},
        timeout=10,
    )
    assert r.status_code == 503
    assert "désactivé" in r.json()["detail"]


def test_public_officines_register_valid_signature(db):
    secret = f"hmac_test_{uuid.uuid4().hex}"
    db.settings.update_one({"_id": "global"},
                           {"$set": {"officines_register_hmac_secret": secret}}, upsert=True)
    body = json.dumps({
        "officine_name": "Pharma TestCity",
        "address": "123 main",
        "phone": "+22670000000",
        "city": "Ouaga",
        "country": "BF",
        "contact_email": "p@test.bf",
        "inventory": [
            {"product_name": "Doliprane 1g", "cip": "3400930471722", "price": 1500, "available": True, "stock_qty": 12},
        ],
    }).encode()
    ts = int(time.time())
    sig = _sign(secret, ts, body)
    officine_id = f"off_{uuid.uuid4().hex[:6]}"
    r = requests.post(
        f"{API}/public/officines/register",
        data=body,
        headers={"Content-Type": "application/json",
                 "X-Signature": sig, "X-Timestamp": str(ts), "X-Officine-Id": officine_id},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json()["officine_id"] == officine_id
    assert r.json()["items_received"] == 1
    # DB persisted
    doc = db.officines_inventory.find_one({"officine_id": officine_id})
    assert doc is not None
    assert doc["officine_name"] == "Pharma TestCity"
    db.officines_inventory.delete_many({"officine_id": officine_id})


def test_public_officines_register_wrong_signature(db):
    secret = f"hmac_test_{uuid.uuid4().hex}"
    db.settings.update_one({"_id": "global"},
                           {"$set": {"officines_register_hmac_secret": secret}}, upsert=True)
    body = json.dumps({"officine_name": "X", "inventory": []}).encode()
    ts = int(time.time())
    r = requests.post(
        f"{API}/public/officines/register",
        data=body,
        headers={"Content-Type": "application/json",
                 "X-Signature": "wrong_sig", "X-Timestamp": str(ts), "X-Officine-Id": "off"},
        timeout=10,
    )
    assert r.status_code == 401
    assert "Signature" in r.json()["detail"]


def test_public_officines_register_old_timestamp(db):
    secret = f"hmac_test_{uuid.uuid4().hex}"
    db.settings.update_one({"_id": "global"},
                           {"$set": {"officines_register_hmac_secret": secret}}, upsert=True)
    body = json.dumps({"officine_name": "X", "inventory": []}).encode()
    ts = int(time.time()) - 600  # 10 min ago
    sig = _sign(secret, ts, body)
    r = requests.post(
        f"{API}/public/officines/register",
        data=body,
        headers={"Content-Type": "application/json",
                 "X-Signature": sig, "X-Timestamp": str(ts), "X-Officine-Id": "off"},
        timeout=10,
    )
    assert r.status_code == 401
    assert "Timestamp" in r.json()["detail"]


def test_hmac_secret_masked_in_get_settings(db, admin_token):
    token, _ = admin_token
    db.settings.update_one({"_id": "global"},
                           {"$set": {"officines_register_hmac_secret": "super_secret_hmac"}}, upsert=True)
    r = requests.get(f"{API}/admin/settings",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    assert r.json().get("officines_register_hmac_secret") == "********"
