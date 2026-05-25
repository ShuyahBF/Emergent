"""Iter37f — Tenant ACL on PATCH/DELETE /admin/products and PATCH /admin/users/{uid}/can-cash.

Bug: a supervisor of one tenant could modify/delete products of another tenant
if they knew the id. Same for flipping can_cash flag on a user of another tenant.
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
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid: str, role: str = "superviseur") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def two_tenants(db):
    """Tenant A sup + 1 user; Tenant B sup."""
    sup_a = f"supA_{uuid.uuid4().hex[:6]}"
    user_a = f"uA_{uuid.uuid4().hex[:6]}"
    sup_b = f"supB_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_a, "email": f"{sup_a}@test.local", "password_hash": "x",
         "full_name": "Sup A", "company": f"CO-A-{uuid.uuid4().hex[:4]}",
         "role": "superviseur", "account_status": "active", "can_cash": True,
         "created_at": now},
        {"id": user_a, "email": f"{user_a}@test.local", "password_hash": "x",
         "full_name": "User A", "parent_client_id": sup_a,
         "role": "client", "account_status": "active",
         "created_at": now},
        {"id": sup_b, "email": f"{sup_b}@test.local", "password_hash": "x",
         "full_name": "Sup B", "company": f"CO-B-{uuid.uuid4().hex[:4]}",
         "role": "superviseur", "account_status": "active", "can_cash": True,
         "created_at": now},
    ])
    yield {"sup_a": sup_a, "user_a": user_a, "sup_b": sup_b}
    db.users.delete_many({"id": {"$in": [sup_a, user_a, sup_b]}})
    db.products.delete_many({"tenant_id": {"$in": [sup_a, sup_b]}})


class TestProductTenantAcl:
    def test_sup_b_cannot_patch_sup_a_product(self, two_tenants):
        ah = {"Authorization": f"Bearer {_forge(two_tenants['sup_a'])}"}
        bh = {"Authorization": f"Bearer {_forge(two_tenants['sup_b'])}"}
        # Sup A creates a product
        r = requests.post(f"{API}/admin/products", headers=ah, json={
            "name": "PRODUCT-X", "unit_price_ht": 1000, "tva_pct": 0,
            "unit": "pc", "active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        # Sup B tries to PATCH → must 404
        r2 = requests.patch(f"{API}/admin/products/{pid}", headers=bh, json={
            "name": "HACKED", "unit_price_ht": 99999, "tva_pct": 0,
            "unit": "pc", "active": True,
        }, timeout=15)
        assert r2.status_code == 404, f"Cross-tenant PATCH must 404, got {r2.status_code}"

    def test_sup_b_cannot_delete_sup_a_product(self, two_tenants):
        ah = {"Authorization": f"Bearer {_forge(two_tenants['sup_a'])}"}
        bh = {"Authorization": f"Bearer {_forge(two_tenants['sup_b'])}"}
        r = requests.post(f"{API}/admin/products", headers=ah, json={
            "name": "PRODUCT-Y", "unit_price_ht": 500, "tva_pct": 0,
            "unit": "pc", "active": True,
        }, timeout=15)
        pid = r.json()["id"]
        r2 = requests.delete(f"{API}/admin/products/{pid}", headers=bh, timeout=15)
        assert r2.status_code == 404


class TestCanCashTenantAcl:
    def test_sup_b_cannot_flip_user_a_can_cash(self, two_tenants):
        bh = {"Authorization": f"Bearer {_forge(two_tenants['sup_b'])}"}
        # Sup B tries to flip user_a (belongs to tenant A) → 404
        r = requests.patch(f"{API}/admin/users/{two_tenants['user_a']}/can-cash",
                           headers=bh, json={"can_cash": True}, timeout=15)
        assert r.status_code == 404, f"Cross-tenant can_cash flip must 404, got {r.status_code}: {r.text}"

    def test_sup_a_can_flip_own_user(self, two_tenants):
        ah = {"Authorization": f"Bearer {_forge(two_tenants['sup_a'])}"}
        r = requests.patch(f"{API}/admin/users/{two_tenants['user_a']}/can-cash",
                           headers=ah, json={"can_cash": True}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["can_cash"] is True
