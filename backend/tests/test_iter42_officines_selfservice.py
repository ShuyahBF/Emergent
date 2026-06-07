"""Iter42 (2026-02) — Tests for Self-Service Portal pour Officines.

Couvre :
  - Inscription publique (status=pending) + protection doublons
  - Validation admin (approve/suspend/reactivate/link-client)
  - OTP request/verify (channel WA — mocké côté admin via collection directe)
  - Magic link request/callback
  - Inventaire CRUD scoped par officine (isolation)
  - HMAC regenerate (one-shot display)
  - Exports CSV
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
def clean_officines(db):
    """Cleanup helper: remove test officines after each test."""
    created_ids = []
    yield created_ids
    if created_ids:
        db.officines.delete_many({"id": {"$in": created_ids}})
        db.officine_otp_codes.delete_many({"officine_id": {"$in": created_ids}})
        db.officine_magic_tokens.delete_many({"officine_id": {"$in": created_ids}})
        db.officine_inventory_items.delete_many({"officine_id": {"$in": created_ids}})
        db.officine_audit_log.delete_many({"officine_id": {"$in": created_ids}})
        db.officines_secrets.delete_many({"officine_id": {"$in": created_ids}})


# --------------------------------------------------------------------------- #
# 1. Inscription publique
# --------------------------------------------------------------------------- #
def test_register_creates_pending_officine(clean_officines):
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22501{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "Pharmacie Test",
        "email": email,
        "phone": phone,
        "city": "Abidjan",
        "country": "CI",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "pending"
    assert body["officine_id"]
    clean_officines.append(body["officine_id"])


def test_register_rejects_duplicates(clean_officines):
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22502{uuid.uuid4().int % 10000000:07d}"
    payload = {"name": "Dupe", "email": email, "phone": phone}
    r1 = requests.post(f"{API}/officines-portal/register", json=payload)
    assert r1.status_code == 200
    clean_officines.append(r1.json()["officine_id"])
    r2 = requests.post(f"{API}/officines-portal/register", json=payload)
    assert r2.status_code == 409


# --------------------------------------------------------------------------- #
# 2. Validation admin
# --------------------------------------------------------------------------- #
def test_admin_can_approve_suspend_reactivate(admin_token, clean_officines):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22503{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "Approve", "email": email, "phone": phone,
    })
    assert r.status_code == 200
    oid = r.json()["officine_id"]
    clean_officines.append(oid)

    # Liste pending
    rl = requests.get(f"{API}/admin/officines-registry?status=pending", headers=H)
    assert rl.status_code == 200
    assert any(it["id"] == oid for it in rl.json()["items"])

    # Approve
    ra = requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)
    assert ra.status_code == 200
    assert ra.json()["status"] == "active"

    # Detail
    rd = requests.get(f"{API}/admin/officines-registry/{oid}", headers=H)
    assert rd.status_code == 200
    assert rd.json()["officine"]["status"] == "active"

    # Suspend
    rs = requests.post(f"{API}/admin/officines-registry/{oid}/suspend", headers=H)
    assert rs.status_code == 200
    assert rs.json()["status"] == "suspended"

    # Reactivate
    rr = requests.post(f"{API}/admin/officines-registry/{oid}/reactivate", headers=H)
    assert rr.status_code == 200
    assert rr.json()["status"] == "active"


def test_admin_link_unlink_client(admin_token, db, clean_officines):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    # Crée un client CRM factice
    cid = f"cli_{uuid.uuid4().hex[:8]}"
    cemail = f"{cid}@crmtest.com"
    db.users.insert_one({
        "id": cid, "email": cemail, "full_name": "Linked Client",
        "role": "client", "account_status": "active", "password_hash": "x",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        # Crée + approuve une officine
        email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
        phone = f"+22504{uuid.uuid4().int % 10000000:07d}"
        r = requests.post(f"{API}/officines-portal/register", json={
            "name": "Linked", "email": email, "phone": phone,
        })
        oid = r.json()["officine_id"]
        clean_officines.append(oid)
        requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)

        # Link
        rl = requests.post(
            f"{API}/admin/officines-registry/{oid}/link-client",
            headers=H, json={"client_email": cemail},
        )
        assert rl.status_code == 200, rl.text
        assert rl.json()["linked_client"]["id"] == cid

        # Verify in DB
        doc = db.officines.find_one({"id": oid})
        assert doc.get("linked_client_id") == cid

        # Unlink
        ru = requests.post(
            f"{API}/admin/officines-registry/{oid}/unlink-client", headers=H,
        )
        assert ru.status_code == 200
        doc = db.officines.find_one({"id": oid})
        assert doc.get("linked_client_id") is None
    finally:
        db.users.delete_one({"id": cid})


# --------------------------------------------------------------------------- #
# 3. OTP flow (canal "wa" peut échouer si WA non configuré ; on teste le
#    chemin verify-otp en insérant directement un code en base).
# --------------------------------------------------------------------------- #
def test_otp_verify_returns_jwt(admin_token, db, clean_officines):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22505{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "OTP", "email": email, "phone": phone,
    })
    oid = r.json()["officine_id"]
    clean_officines.append(oid)
    requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)

    # Inject OTP directly
    code = "123456"
    db.officine_otp_codes.insert_one({
        "officine_id": oid, "channel": "wa",
        "code_hash": _sha(code),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "attempts": 0,
        "created_at": datetime.now(timezone.utc),
    })

    # Verify with email
    rv = requests.post(f"{API}/officines-portal/auth/verify-otp", json={
        "identifier": email, "code": code,
    })
    assert rv.status_code == 200, rv.text
    body = rv.json()
    assert body["token"] and body["officine"]["id"] == oid


def test_otp_invalid_code_increments_attempts(admin_token, db, clean_officines):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22506{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "OTPbad", "email": email, "phone": phone,
    })
    oid = r.json()["officine_id"]
    clean_officines.append(oid)
    requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)
    db.officine_otp_codes.insert_one({
        "officine_id": oid, "channel": "wa",
        "code_hash": _sha("000000"),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "attempts": 0, "created_at": datetime.now(timezone.utc),
    })
    rv = requests.post(f"{API}/officines-portal/auth/verify-otp", json={
        "identifier": email, "code": "999999",
    })
    assert rv.status_code == 401
    rec = db.officine_otp_codes.find_one({"officine_id": oid})
    assert rec["attempts"] == 1


# --------------------------------------------------------------------------- #
# 4. Magic link callback (insertion directe pour éviter l'envoi email réel)
# --------------------------------------------------------------------------- #
def test_magic_link_callback_returns_jwt(admin_token, db, clean_officines):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22507{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "Magic", "email": email, "phone": phone,
    })
    oid = r.json()["officine_id"]
    clean_officines.append(oid)
    requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)

    raw_token = "magic_" + uuid.uuid4().hex
    db.officine_magic_tokens.insert_one({
        "id": str(uuid.uuid4()), "officine_id": oid,
        "token_hash": _sha(raw_token),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "consumed_at": None,
        "created_at": datetime.now(timezone.utc),
    })
    rc = requests.get(f"{API}/officines-portal/auth/magic-callback?token={raw_token}")
    assert rc.status_code == 200
    assert rc.json()["token"]


def test_magic_link_consumed_only_once(admin_token, db, clean_officines):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22508{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "MagicOnce", "email": email, "phone": phone,
    })
    oid = r.json()["officine_id"]
    clean_officines.append(oid)
    requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)
    raw = "tk_" + uuid.uuid4().hex
    db.officine_magic_tokens.insert_one({
        "id": str(uuid.uuid4()), "officine_id": oid,
        "token_hash": _sha(raw),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "consumed_at": None,
        "created_at": datetime.now(timezone.utc),
    })
    r1 = requests.get(f"{API}/officines-portal/auth/magic-callback?token={raw}")
    assert r1.status_code == 200
    r2 = requests.get(f"{API}/officines-portal/auth/magic-callback?token={raw}")
    assert r2.status_code == 410


# --------------------------------------------------------------------------- #
# 5. Inventory CRUD + isolation
# --------------------------------------------------------------------------- #
def test_inventory_crud_and_isolation(admin_token, db, clean_officines):
    token_adm, _ = admin_token
    H = {"Authorization": f"Bearer {token_adm}"}
    # Crée 2 officines approuvées
    ids = []
    for i in range(2):
        email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
        phone = f"+22509{uuid.uuid4().int % 10000000:07d}"
        r = requests.post(f"{API}/officines-portal/register", json={
            "name": f"Inv{i}", "email": email, "phone": phone,
        })
        oid = r.json()["officine_id"]
        ids.append(oid)
        clean_officines.append(oid)
        requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)
    t0 = _forge_officine(ids[0])
    t1 = _forge_officine(ids[1])
    H0 = {"Authorization": f"Bearer {t0}"}
    H1 = {"Authorization": f"Bearer {t1}"}

    # Create item dans officine 0
    rc = requests.post(f"{API}/officines-portal/inventory", headers=H0, json={
        "cip": "3400930123456",
        "product_name": "Doliprane 1000mg",
        "lot_number": "LOT-A1",
        "expiry_date": "2027-12-31",
        "quantity": 50,
        "unit_price": 1200.50,
        "currency": "XOF",
        "available": True,
    })
    assert rc.status_code == 200
    item_id = rc.json()["item"]["id"]

    # Officine 1 ne voit pas
    rl1 = requests.get(f"{API}/officines-portal/inventory", headers=H1).json()
    assert rl1["count"] == 0
    # Officine 0 voit
    rl0 = requests.get(f"{API}/officines-portal/inventory", headers=H0).json()
    assert rl0["count"] == 1

    # Update
    ru = requests.put(f"{API}/officines-portal/inventory/{item_id}", headers=H0, json={
        "cip": "3400930123456", "product_name": "Doliprane 1000mg",
        "lot_number": "LOT-A1", "expiry_date": "2027-12-31",
        "quantity": 99, "unit_price": 1200.50, "currency": "XOF",
        "available": True,
    })
    assert ru.status_code == 200
    assert ru.json()["item"]["quantity"] == 99

    # Officine 1 ne peut PAS modifier
    rb = requests.put(f"{API}/officines-portal/inventory/{item_id}", headers=H1, json={
        "product_name": "Hack", "quantity": 0,
    })
    assert rb.status_code == 404

    # Delete
    rd = requests.delete(f"{API}/officines-portal/inventory/{item_id}", headers=H0)
    assert rd.status_code == 200


# --------------------------------------------------------------------------- #
# 6. Regenerate HMAC secret
# --------------------------------------------------------------------------- #
def test_regenerate_secret_returns_once(admin_token, db, clean_officines):
    token_adm, _ = admin_token
    H = {"Authorization": f"Bearer {token_adm}"}
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22500{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "Secret", "email": email, "phone": phone,
    })
    oid = r.json()["officine_id"]
    clean_officines.append(oid)
    requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)
    tok = _forge_officine(oid)
    HO = {"Authorization": f"Bearer {tok}"}
    rs = requests.post(f"{API}/officines-portal/me/regenerate-secret", headers=HO)
    assert rs.status_code == 200
    secret = rs.json()["secret"]
    assert isinstance(secret, str) and len(secret) > 20

    # Vérifie en DB
    saved = db.officines_secrets.find_one({"officine_id": oid, "revoked_at": None})
    assert saved and saved["secret"] == secret


# --------------------------------------------------------------------------- #
# 7. CSV exports
# --------------------------------------------------------------------------- #
def test_inventory_csv_export(admin_token, db, clean_officines):
    token_adm, _ = admin_token
    H = {"Authorization": f"Bearer {token_adm}"}
    email = f"off+{uuid.uuid4().hex[:8]}@officinetest.com"
    phone = f"+22510{uuid.uuid4().int % 10000000:07d}"
    r = requests.post(f"{API}/officines-portal/register", json={
        "name": "CSV", "email": email, "phone": phone,
    })
    oid = r.json()["officine_id"]
    clean_officines.append(oid)
    requests.post(f"{API}/admin/officines-registry/{oid}/approve", headers=H)
    tok = _forge_officine(oid)
    HO = {"Authorization": f"Bearer {tok}"}
    requests.post(f"{API}/officines-portal/inventory", headers=HO, json={
        "product_name": "Aspégic 500", "quantity": 25, "unit_price": 800,
        "lot_number": "L42", "expiry_date": "2028-01-31",
    })
    r2 = requests.get(f"{API}/officines-portal/inventory/export.csv", headers=HO)
    assert r2.status_code == 200
    assert "Aspégic 500" in r2.text
    assert "cip,product_name" in r2.text


# --------------------------------------------------------------------------- #
# 8. Unauthenticated access denied
# --------------------------------------------------------------------------- #
def test_unauth_endpoints_reject():
    for method, url in [
        ("get", f"{API}/officines-portal/me"),
        ("get", f"{API}/officines-portal/inventory"),
        ("post", f"{API}/officines-portal/inventory"),
    ]:
        r = requests.request(method, url, json={} if method == "post" else None)
        assert r.status_code in (401, 403)
