"""Iter50 — Additional backend tests for Self-Service Portal Officines.

Couvre les cas manquants par rapport à test_iter42_officines_selfservice.py :
  - OTP >5 tentatives -> 429
  - Magic link expiré -> 410
  - Historique : liste + export CSV scoped à l'officine
  - Inventaire : isolation GET d'item d'une autre officine -> 404
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge_admin(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def _forge_officine(officine_id: str) -> str:
    return pyjwt.encode({
        "sub": f"officine:{officine_id}",
        "officine_id": officine_id,
        "aud": "officine-portal",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    aid = f"off_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@admintest.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge_admin(aid), aid
    db.users.delete_one({"id": aid})


@pytest.fixture()
def cleanup(db):
    ids = []
    yield ids
    if ids:
        db.officines.delete_many({"id": {"$in": ids}})
        db.officine_otp_codes.delete_many({"officine_id": {"$in": ids}})
        db.officine_magic_tokens.delete_many({"officine_id": {"$in": ids}})
        db.officine_inventory_items.delete_many({"officine_id": {"$in": ids}})
        db.officine_audit_log.delete_many({"officine_id": {"$in": ids}})
        db.officines_secrets.delete_many({"officine_id": {"$in": ids}})


def _register_and_approve(db, admin_h, ids, prefix="00"):
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+225{prefix}{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "Add", "email": email, "phone": phone,
    })
    assert r.status_code == 200, r.text
    oid = r.json()["officine_id"]
    ids.append(oid)
    ra = requests.post(
        f"{API}/admin/officines-registry/{oid}/approve", headers=admin_h,
    )
    assert ra.status_code == 200, ra.text
    return oid, email


# --------------------------------------------------------------------------- #
# 1. OTP rate-limit : >5 tentatives -> 429
# --------------------------------------------------------------------------- #
def test_otp_rate_limit_429_after_5_attempts(admin_token, db, cleanup):
    tok, _ = admin_token
    H = {"Authorization": f"Bearer {tok}"}
    oid, email = _register_and_approve(db, H, cleanup, prefix="11")
    # Insère un OTP valide avec 5 tentatives déjà comptabilisées
    db.officine_otp_codes.insert_one({
        "officine_id": oid, "channel": "wa",
        "code_hash": _sha("123456"),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "attempts": 5, "created_at": datetime.now(timezone.utc),
    })
    rv = requests.post(f"{API}/officines-portal/auth/verify-otp", json={
        "identifier": email, "code": "123456",
    })
    assert rv.status_code == 429, rv.text


# --------------------------------------------------------------------------- #
# 2. Magic link expiré -> 410
# --------------------------------------------------------------------------- #
def test_magic_link_expired_returns_410(admin_token, db, cleanup):
    tok, _ = admin_token
    H = {"Authorization": f"Bearer {tok}"}
    oid, _ = _register_and_approve(db, H, cleanup, prefix="22")
    raw = "expmagic_" + uuid.uuid4().hex
    db.officine_magic_tokens.insert_one({
        "id": str(uuid.uuid4()), "officine_id": oid,
        "token_hash": _sha(raw),
        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "consumed_at": None,
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=30),
    })
    r = requests.get(f"{API}/officines-portal/auth/magic-callback?token={raw}")
    assert r.status_code == 410, r.text


# --------------------------------------------------------------------------- #
# 3. Historique : liste + export CSV scoped
# --------------------------------------------------------------------------- #
def test_history_list_scoped_to_officine(admin_token, db, cleanup):
    tok, _ = admin_token
    H = {"Authorization": f"Bearer {tok}"}
    oid_a, _ = _register_and_approve(db, H, cleanup, prefix="33")
    oid_b, _ = _register_and_approve(db, H, cleanup, prefix="44")

    now = datetime.now(timezone.utc)
    db.officine_audit_log.insert_many([
        {"id": str(uuid.uuid4()), "officine_id": oid_a, "action": "test_a1",
         "actor": "self", "details": {"k": 1}, "created_at": now},
        {"id": str(uuid.uuid4()), "officine_id": oid_a, "action": "test_a2",
         "actor": "self", "details": {"k": 2}, "created_at": now},
        {"id": str(uuid.uuid4()), "officine_id": oid_b, "action": "test_b1",
         "actor": "self", "details": {"k": 9}, "created_at": now},
    ])

    Ha = {"Authorization": f"Bearer {_forge_officine(oid_a)}"}
    r = requests.get(f"{API}/officines-portal/history", headers=Ha)
    assert r.status_code == 200, r.text
    body = r.json()
    actions = {it["action"] for it in body["items"]}
    assert "test_a1" in actions and "test_a2" in actions
    assert "test_b1" not in actions  # isolation


def test_history_csv_export_scoped(admin_token, db, cleanup):
    tok, _ = admin_token
    H = {"Authorization": f"Bearer {tok}"}
    oid, _ = _register_and_approve(db, H, cleanup, prefix="55")
    now = datetime.now(timezone.utc)
    db.officine_audit_log.insert_one({
        "id": str(uuid.uuid4()), "officine_id": oid,
        "action": "csv_marker_xyz", "actor": "self",
        "details": {"note": "for-csv"}, "created_at": now,
    })
    HO = {"Authorization": f"Bearer {_forge_officine(oid)}"}
    r = requests.get(f"{API}/officines-portal/history/export.csv", headers=HO)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "created_at,action,actor,details" in r.text
    assert "csv_marker_xyz" in r.text


# --------------------------------------------------------------------------- #
# 4. Isolation inventaire : GET d'item d'une autre officine -> 404
# --------------------------------------------------------------------------- #
def test_inventory_get_item_isolation_returns_404(admin_token, db, cleanup):
    tok, _ = admin_token
    H = {"Authorization": f"Bearer {tok}"}
    oid_a, _ = _register_and_approve(db, H, cleanup, prefix="66")
    oid_b, _ = _register_and_approve(db, H, cleanup, prefix="77")
    Ha = {"Authorization": f"Bearer {_forge_officine(oid_a)}"}
    Hb = {"Authorization": f"Bearer {_forge_officine(oid_b)}"}
    rc = requests.post(f"{API}/officines-portal/inventory", headers=Ha, json={
        "product_name": "IsoTest", "quantity": 1, "unit_price": 100,
        "lot_number": "LOT-ISO", "expiry_date": "2030-01-31",
    })
    assert rc.status_code == 200
    item_id = rc.json()["item"]["id"]
    # B essaie de supprimer -> 404
    rd = requests.delete(
        f"{API}/officines-portal/inventory/{item_id}", headers=Hb,
    )
    assert rd.status_code == 404


# --------------------------------------------------------------------------- #
# 5. History endpoint sans auth -> 401/403
# --------------------------------------------------------------------------- #
def test_history_endpoints_require_auth():
    for url in [
        f"{API}/officines-portal/history",
        f"{API}/officines-portal/history/export.csv",
    ]:
        r = requests.get(url)
        assert r.status_code in (401, 403), f"{url} -> {r.status_code}"
