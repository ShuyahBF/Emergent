"""Iter42d extra tests:
  - PUT /api/amm/{id} normalizes country_code
  - Bug fix #4: GET /api/admin/clients includes pharmacien/regulateur/medecin/editeur_vidal roles
"""
from __future__ import annotations

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
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge_admin(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    aid = f"iter42dx_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@admintest.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge_admin(aid), aid
    db.users.delete_one({"id": aid})


def test_update_amm_normalizes_country_code(db, admin_token):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    db.settings.update_one({"_id": "global"}, {"$set": {"amm_default_country": "BF"}}, upsert=True)
    suffix = uuid.uuid4().hex[:6]
    # Create
    r = requests.post(f"{API}/amm", headers=H, json={
        "product_name": f"PutTest-{suffix}",
    })
    assert r.status_code == 200, r.text
    amm = r.json()["amm"]
    amm_id = amm["id"]
    try:
        # PUT with lowercase country
        r2 = requests.put(f"{API}/amm/{amm_id}", headers=H, json={"country_code": "ci"})
        assert r2.status_code == 200, r2.text
        updated = r2.json().get("amm") or r2.json()
        # Re-fetch from DB to confirm persistence
        doc = db.amm_numbers.find_one({"id": amm_id})
        assert doc is not None
        assert doc.get("country_code") == "CI", f"Expected CI, got {doc.get('country_code')}"
    finally:
        db.amm_numbers.delete_one({"id": amm_id})


def test_admin_clients_includes_business_roles(db, admin_token):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    suffix = uuid.uuid4().hex[:8]
    pharm_id = f"phar_{suffix}"
    db.users.insert_one({
        "id": pharm_id,
        "email": f"pharma_{suffix}@admintest.com",
        "password_hash": "x",
        "role": "pharmacien",
        "account_status": "active",
        "name": "Pharma TestUser",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.get(f"{API}/admin/clients", headers=H)
        assert r.status_code == 200, r.text
        data = r.json()
        items = data if isinstance(data, list) else (data.get("items") or data.get("clients") or [])
        found = any((u.get("id") == pharm_id) or (u.get("email", "").startswith(f"pharma_{suffix}")) for u in items)
        assert found, f"Pharmacien user {pharm_id} should appear in /admin/clients but didn't. Got {len(items)} items"
    finally:
        db.users.delete_one({"id": pharm_id})
