"""Iter37f — Cashiers (can_cash=true, role=client) must READ /admin/business-clients
and /admin/products. Writes still supervisor-only.

Bug from prod: rabo.f@ (role=client, can_cash=true) saw empty lists even after
multi-tenant fix because the GET endpoints required `get_current_supervisor`.
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


def _forge(uid: str, role: str = "client") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def trio(db):
    """sup (canonical) + cashier (role=client, can_cash=true) + outsider."""
    company = f"CA-{uuid.uuid4().hex[:6].upper()}"
    sup_id = f"sup_{uuid.uuid4().hex[:6]}"
    cashier_id = f"ca_{uuid.uuid4().hex[:6]}"
    outsider_id = f"out_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@test.local", "password_hash": "x",
         "full_name": "Boss", "company": company,
         "role": "superviseur", "account_status": "active", "can_cash": True,
         "created_at": now},
        # The prod case: client role, can_cash=true, same company
        {"id": cashier_id, "email": f"{cashier_id}@test.local", "password_hash": "x",
         "full_name": "Cashier rabo.f-style", "company": company,
         "role": "client", "account_status": "active", "can_cash": True,
         "created_at": now},
        # Outsider with NO can_cash → must still get 403
        {"id": outsider_id, "email": f"{outsider_id}@test.local", "password_hash": "x",
         "full_name": "No Cash", "company": company,
         "role": "client", "account_status": "active",
         "created_at": now},
    ])
    yield {"company": company, "sup_id": sup_id, "cashier_id": cashier_id, "outsider_id": outsider_id}
    db.users.delete_many({"id": {"$in": [sup_id, cashier_id, outsider_id]}})
    db.business_clients.delete_many({"tenant_id": sup_id})
    db.products.delete_many({"tenant_id": sup_id})


class TestCashierReadAccess:
    def test_cashier_can_read_business_clients(self, trio):
        sup_h = {"Authorization": f"Bearer {_forge(trio['sup_id'], role='superviseur')}"}
        ca_h = {"Authorization": f"Bearer {_forge(trio['cashier_id'])}"}
        # Sup creates a bc
        r = requests.post(f"{API}/admin/business-clients", headers=sup_h, json={
            "name": f"CLIENT-{uuid.uuid4().hex[:6]}", "phone": "+22600000001",
        }, timeout=15)
        assert r.status_code == 200, r.text
        bc_id = r.json()["id"]
        # Cashier (client+can_cash) MUST be able to list (used to fail 403)
        lr = requests.get(f"{API}/admin/business-clients", headers=ca_h, timeout=15)
        assert lr.status_code == 200, f"Cashier must read /admin/business-clients, got {lr.status_code}: {lr.text}"
        ids = {x["id"] for x in lr.json()}
        assert bc_id in ids, "Cashier should see the bc the sup created (same tenant)"

    def test_cashier_can_read_products(self, trio):
        ca_h = {"Authorization": f"Bearer {_forge(trio['cashier_id'])}"}
        lr = requests.get(f"{API}/admin/products", headers=ca_h, timeout=15)
        assert lr.status_code == 200, f"Cashier must read /admin/products, got {lr.status_code}: {lr.text}"

    def test_cashier_cannot_create_business_client(self, trio):
        """Writes still supervisor-only — regression guard."""
        ca_h = {"Authorization": f"Bearer {_forge(trio['cashier_id'])}"}
        r = requests.post(f"{API}/admin/business-clients", headers=ca_h, json={
            "name": "SHOULD-FAIL", "phone": "+22600000000",
        }, timeout=15)
        assert r.status_code in (401, 403), f"Cashier should NOT create bc, got {r.status_code}"

    def test_non_cashier_client_still_forbidden(self, trio):
        """A regular client WITHOUT can_cash must NOT read these lists."""
        oh = {"Authorization": f"Bearer {_forge(trio['outsider_id'])}"}
        r = requests.get(f"{API}/admin/business-clients", headers=oh, timeout=15)
        assert r.status_code == 403
        r2 = requests.get(f"{API}/admin/products", headers=oh, timeout=15)
        assert r2.status_code == 403
