"""Iter37f — Tenant info badge endpoint (header of Caisse page)."""
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
def shared_company_users(db):
    company = f"BADGE-CO-{uuid.uuid4().hex[:6].upper()}"
    sup_id = f"sup_{uuid.uuid4().hex[:6]}"
    a_id = f"a_{uuid.uuid4().hex[:6]}"
    b_id = f"b_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@test.local", "password_hash": "x",
         "full_name": "Boss", "company": company,
         "role": "superviseur", "account_status": "active", "can_cash": True,
         "created_at": now},
        {"id": a_id, "email": f"{a_id}@test.local", "password_hash": "x",
         "full_name": "A", "company": company,
         "role": "client", "account_status": "active", "can_cash": True,
         "created_at": now},
        {"id": b_id, "email": f"{b_id}@test.local", "password_hash": "x",
         "full_name": "B", "company": company,
         "role": "client", "account_status": "active", "can_cash": True,
         "created_at": now},
    ])
    yield {"sup_id": sup_id, "a_id": a_id, "b_id": b_id, "company": company}
    db.users.delete_many({"id": {"$in": [sup_id, a_id, b_id]}})


class TestTenantInfoBadge:
    def test_returns_shape(self, shared_company_users):
        ctx = shared_company_users
        h = {"Authorization": f"Bearer {_forge(ctx['a_id'])}"}
        r = requests.get(f"{API}/cashier/tenant-info", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        # Required keys
        for k in ("tenant_id", "tenant_name", "company", "member_count",
                  "business_client_count", "product_count", "is_super_admin"):
            assert k in body, f"missing key: {k}"
        # Tenant should be the boss (canonical via shared company)
        assert body["tenant_id"] == ctx["sup_id"]
        assert body["company"] == ctx["company"]
        # 3 users share this company → member_count >= 3
        assert body["member_count"] >= 3
        assert body["is_super_admin"] is False

    def test_forbidden_without_can_cash(self, db):
        uid = f"reg_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
            "full_name": "Reg", "role": "client", "account_status": "active",
        })
        try:
            h = {"Authorization": f"Bearer {_forge(uid)}"}
            r = requests.get(f"{API}/cashier/tenant-info", headers=h, timeout=15)
            assert r.status_code == 403
        finally:
            db.users.delete_one({"id": uid})
