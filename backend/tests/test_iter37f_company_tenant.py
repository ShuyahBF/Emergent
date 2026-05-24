"""Iter37f — Tenant resolution via shared `company` name (production scenario).

Bug context: in production, `support@sawalismartsystems.com` and
`rabo.f@sawalismartsystems.com` both belong to "SAWALI SMART SYSTEMS"
but had no explicit `parent_client_id` link, so each became its own tenant
and they didn't share Caisse data.

Fix: `_resolve_client_lie` now falls back to looking up a canonical user
(admin > superviseur > oldest active) sharing the same `company` name.
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
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    d = r.json()
    if not d.get("needs_otp"):
        return d["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp",
                       json={"session_token": d["session_token"], "code": d["dev_otp"]}, timeout=30)
    return r2.json()["access_token"]


def _forge(uid: str, role: str = "client") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def shared_company_users(db):
    """3 users sharing 'COMPANY-XYZ': 1 superviseur (canonical) + 2 plain clients
    with NO parent_client_id (the prod scenario)."""
    company = f"COMPANY-{uuid.uuid4().hex[:6].upper()}"
    sup_id = f"sup_{uuid.uuid4().hex[:6]}"
    user_a = f"emp_a_{uuid.uuid4().hex[:6]}"
    user_b = f"emp_b_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@test.local", "password_hash": "x",
         "full_name": "Boss", "company": company,
         "role": "superviseur", "account_status": "active", "can_cash": True,
         "created_at": now},
        # NO parent_client_id — just shared company. This is the prod bug.
        {"id": user_a, "email": f"{user_a}@test.local", "password_hash": "x",
         "full_name": "Employee A", "company": company,
         "role": "client", "account_status": "active", "can_cash": True,
         "created_at": now},
        {"id": user_b, "email": f"{user_b}@test.local", "password_hash": "x",
         "full_name": "Employee B", "company": company,
         "role": "client", "account_status": "active", "can_cash": True,
         "created_at": now},
    ])
    yield {"company": company, "sup_id": sup_id, "user_a": user_a, "user_b": user_b}
    db.users.delete_many({"id": {"$in": [sup_id, user_a, user_b]}})
    db.business_clients.delete_many({"tenant_id": sup_id})
    db.products.delete_many({"tenant_id": sup_id})
    db.receipts.delete_many({"tenant_id": sup_id})
    db.invoices.delete_many({"tenant_id": sup_id})
    db.payment_methods.delete_many({"tenant_id": sup_id})


class TestCompanyBasedTenantResolution:
    def test_users_sharing_company_share_business_clients(self, shared_company_users):
        ctx = shared_company_users
        sup_h = {"Authorization": f"Bearer {_forge(ctx['sup_id'], role='superviseur')}"}
        ah = {"Authorization": f"Bearer {_forge(ctx['user_a'])}"}
        bh = {"Authorization": f"Bearer {_forge(ctx['user_b'])}"}
        # Superviseur creates a business_client → should be tagged with sup's tenant
        bc = requests.post(f"{API}/admin/business-clients", headers=sup_h, json={
            "name": f"SHARED-{uuid.uuid4().hex[:6]}", "phone": "+22612345678",
        }, timeout=15)
        assert bc.status_code == 200, bc.text
        bc_id = bc.json()["id"]
        # Employee A reads via the cashier UI flow → must see the bc
        # (the cashier list endpoint requires supervisor, so test via receipts which use a scoped lookup)
        # Use the receipt creation path: it queries business_clients with the scope filter.
        # First create a payment method (sup-only)
        pm = requests.post(f"{API}/admin/payment-methods", headers=sup_h, json={
            "label": "Cash X", "kind": "cash", "active": True, "sort_order": 1,
        }, timeout=15)
        assert pm.status_code == 200, pm.text
        pm_id = pm.json()["id"]
        # Employee A tries to issue a receipt on the bc the boss created
        rr = requests.post(f"{API}/cashier/receipts", headers=ah, json={
            "business_client_id": bc_id, "amount": 1000, "motif": "test shared",
            "payment_method_id": pm_id,
        }, timeout=15)
        assert rr.status_code == 200, (
            f"Employee A must see boss's business_client via shared `company`, "
            f"got {rr.status_code}: {rr.text}"
        )
        # Employee B lists receipts → must see what A just created
        lr = requests.get(f"{API}/cashier/receipts", headers=bh, timeout=15)
        assert lr.status_code == 200
        assert any(x["id"] == rr.json()["id"] for x in lr.json()), \
            "Employee B must see Employee A's receipt (same company tenant)"

    def test_different_company_isolated(self, shared_company_users, db):
        """A user with a DIFFERENT company name must NOT see this tenant's data."""
        ctx = shared_company_users
        sup_h = {"Authorization": f"Bearer {_forge(ctx['sup_id'], role='superviseur')}"}
        # Boss creates a bc
        bc = requests.post(f"{API}/admin/business-clients", headers=sup_h, json={
            "name": f"ISO-{uuid.uuid4().hex[:6]}", "phone": "+22600000000",
        }, timeout=15)
        bc_id = bc.json()["id"]
        # Create a 3rd user in a DIFFERENT company
        outsider_id = f"outsider_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": outsider_id, "email": f"{outsider_id}@test.local",
            "password_hash": "x", "full_name": "Outsider",
            "company": f"DIFFERENT-{uuid.uuid4().hex[:6].upper()}",
            "role": "superviseur", "account_status": "active", "can_cash": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            oh = {"Authorization": f"Bearer {_forge(outsider_id, role='superviseur')}"}
            r = requests.get(f"{API}/admin/business-clients", headers=oh, timeout=15)
            ids = {x["id"] for x in r.json()}
            assert bc_id not in ids, "Outsider with different company MUST NOT see this tenant's bc"
        finally:
            db.users.delete_one({"id": outsider_id})


class TestAdminBackfillEndpoint:
    def test_admin_can_trigger_backfill(self, admin_h, db, shared_company_users):
        """The admin endpoint /admin/cashier/backfill-tenants must:
        - Be admin-only (already enforced).
        - Run without error and return stats + canonical sample."""
        # Seed a legacy doc with WRONG tenant_id (e.g. set to user_a directly)
        # to verify rewrite=true consolidates it onto the canonical (sup_id).
        ctx = shared_company_users
        wrong_bc_id = f"wrong_{uuid.uuid4().hex[:6]}"
        db.business_clients.insert_one({
            "id": wrong_bc_id, "name": "LEGACY-WRONG-TENANT",
            "tenant_id": ctx["user_a"],  # wrong — should be sup_id (canonical)
            "created_by": ctx["user_a"],
            "deleted_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.post(f"{API}/admin/cashier/backfill-tenants", headers=admin_h,
                              json={"rewrite": True}, timeout=30)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] is True
            assert isinstance(body["rows_updated"], dict)
            assert "business_clients" in body["rows_updated"]
            assert isinstance(body["canonical_users_sample"], list)
            # The wrongly-tagged bc must now point to the canonical sup_id
            updated = db.business_clients.find_one({"id": wrong_bc_id}, {"_id": 0, "tenant_id": 1})
            assert updated["tenant_id"] == ctx["sup_id"], (
                f"After backfill rewrite, tenant_id should be canonical "
                f"sup_id={ctx['sup_id']}, got {updated['tenant_id']}"
            )
        finally:
            db.business_clients.delete_one({"id": wrong_bc_id})

    def test_backfill_forbidden_for_non_admin(self, db):
        uid = f"reg_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
            "full_name": "Reg", "role": "client", "account_status": "active",
        })
        try:
            h = {"Authorization": f"Bearer {_forge(uid)}"}
            r = requests.post(f"{API}/admin/cashier/backfill-tenants", headers=h, json={}, timeout=15)
            assert r.status_code in (401, 403)
        finally:
            db.users.delete_one({"id": uid})
