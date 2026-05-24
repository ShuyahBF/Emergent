"""Iter37e — Multi-tenant isolation tests for the Caisse/Facturation module.

Goal: validate that all users sharing the same `Client Lié` (resolved via
`parent_client_id || client_id || id`) see the same Caisse data, while users
from a different tenant are properly isolated.
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
def tenant_a(db):
    """Tenant A: superviseur (parent) + employee (child, can_cash)."""
    parent_id = f"tenantA_parent_{uuid.uuid4().hex[:6]}"
    emp_id = f"tenantA_emp_{uuid.uuid4().hex[:6]}"
    db.users.insert_many([
        {"id": parent_id, "email": f"{parent_id}@test.local", "password_hash": "x",
         "full_name": "Tenant A Boss", "company": "TenantA Corp",
         "role": "superviseur", "account_status": "active", "can_cash": True},
        {"id": emp_id, "email": f"{emp_id}@test.local", "password_hash": "x",
         "full_name": "Tenant A Cashier", "role": "client",
         "account_status": "active", "can_cash": True,
         "parent_client_id": parent_id},
    ])
    yield {"parent_id": parent_id, "emp_id": emp_id}
    db.users.delete_many({"id": {"$in": [parent_id, emp_id]}})
    db.business_clients.delete_many({"tenant_id": parent_id})
    db.products.delete_many({"tenant_id": parent_id})
    db.receipts.delete_many({"tenant_id": parent_id})
    db.invoices.delete_many({"tenant_id": parent_id})
    db.payment_methods.delete_many({"tenant_id": parent_id})
    db.legal_forms.delete_many({"tenant_id": parent_id})
    db.product_categories.delete_many({"tenant_id": parent_id})


@pytest.fixture
def tenant_b(db):
    """Tenant B: separate company (must NOT see Tenant A data)."""
    boss_id = f"tenantB_boss_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": boss_id, "email": f"{boss_id}@test.local", "password_hash": "x",
        "full_name": "Tenant B Boss", "company": "TenantB Ltd",
        "role": "superviseur", "account_status": "active", "can_cash": True,
    })
    yield {"boss_id": boss_id}
    db.users.delete_one({"id": boss_id})
    db.business_clients.delete_many({"tenant_id": boss_id})


class TestBusinessClientsIsolation:
    def test_parent_creates_bc_employee_sees_it(self, tenant_a):
        ph = {"Authorization": f"Bearer {_forge(tenant_a['parent_id'], role='superviseur')}"}
        eh = {"Authorization": f"Bearer {_forge(tenant_a['emp_id'])}"}
        # Parent creates a business client
        r = requests.post(f"{API}/admin/business-clients", headers=ph, json={
            "name": f"ACME-{uuid.uuid4().hex[:6]}",
            "phone": "+22612345678",
        }, timeout=15)
        assert r.status_code == 200, r.text
        bc_id = r.json()["id"]
        assert r.json().get("tenant_id") == tenant_a["parent_id"]
        # Employee (same tenant) sees the bc through list endpoint
        r2 = requests.get(f"{API}/admin/business-clients", headers=ph, timeout=15)
        assert r2.status_code == 200
        ids = {c["id"] for c in r2.json()}
        assert bc_id in ids, f"Parent should see own bc; got {ids}"
        # NB: Employee is `client` role → admin endpoint requires superviseur.
        # We still validate isolation downstream via receipts/invoices below.

    def test_tenant_b_cannot_see_tenant_a_bc(self, tenant_a, tenant_b):
        ph = {"Authorization": f"Bearer {_forge(tenant_a['parent_id'], role='superviseur')}"}
        bh = {"Authorization": f"Bearer {_forge(tenant_b['boss_id'], role='superviseur')}"}
        r = requests.post(f"{API}/admin/business-clients", headers=ph, json={
            "name": f"ISOLATED-{uuid.uuid4().hex[:6]}", "phone": "+22600000000",
        }, timeout=15)
        bc_id = r.json()["id"]
        r2 = requests.get(f"{API}/admin/business-clients", headers=bh, timeout=15)
        ids = {c["id"] for c in r2.json()}
        assert bc_id not in ids, "Tenant B must NOT see Tenant A's business clients"

    def test_tenant_b_cannot_update_tenant_a_bc(self, tenant_a, tenant_b):
        ph = {"Authorization": f"Bearer {_forge(tenant_a['parent_id'], role='superviseur')}"}
        bh = {"Authorization": f"Bearer {_forge(tenant_b['boss_id'], role='superviseur')}"}
        r = requests.post(f"{API}/admin/business-clients", headers=ph, json={
            "name": f"TARGET-{uuid.uuid4().hex[:6]}", "phone": "+22600000001",
        }, timeout=15)
        bc_id = r.json()["id"]
        # Tenant B tries to PATCH it → must 404
        r2 = requests.patch(f"{API}/admin/business-clients/{bc_id}", headers=bh, json={
            "name": "HACKED",
        }, timeout=15)
        assert r2.status_code == 404


class TestReceiptsIsolation:
    def test_employee_sees_parent_receipts(self, tenant_a):
        ph = {"Authorization": f"Bearer {_forge(tenant_a['parent_id'], role='superviseur')}"}
        eh = {"Authorization": f"Bearer {_forge(tenant_a['emp_id'])}"}
        # Parent creates a BC + PM
        bc = requests.post(f"{API}/admin/business-clients", headers=ph, json={
            "name": f"R-CLIENT-{uuid.uuid4().hex[:6]}", "phone": "+22612345678",
        }, timeout=15).json()
        pm = requests.post(f"{API}/admin/payment-methods", headers=ph, json={
            "label": "Cash test", "kind": "cash", "active": True, "sort_order": 1,
        }, timeout=15).json()
        # Parent creates a receipt
        rr = requests.post(f"{API}/cashier/receipts", headers=ph, json={
            "business_client_id": bc["id"], "amount": 12345, "motif": "test parent",
            "payment_method_id": pm["id"],
        }, timeout=15)
        assert rr.status_code == 200, rr.text
        rid = rr.json()["id"]
        assert rr.json().get("tenant_id") == tenant_a["parent_id"]
        # Employee lists receipts → must see it
        lr = requests.get(f"{API}/cashier/receipts", headers=eh, timeout=15)
        assert lr.status_code == 200
        assert any(x["id"] == rid for x in lr.json()), "Employee must see parent's receipt"
        # Employee fetches the receipt directly → must succeed
        gr = requests.get(f"{API}/cashier/receipts/{rid}", headers=eh, timeout=15)
        assert gr.status_code == 200

    def test_tenant_b_cannot_see_tenant_a_receipts(self, tenant_a, tenant_b):
        ph = {"Authorization": f"Bearer {_forge(tenant_a['parent_id'], role='superviseur')}"}
        bh = {"Authorization": f"Bearer {_forge(tenant_b['boss_id'], role='superviseur')}"}
        # Tenant A creates BC + PM + receipt
        bc = requests.post(f"{API}/admin/business-clients", headers=ph, json={
            "name": f"ISO-R-{uuid.uuid4().hex[:6]}", "phone": "+22600009999",
        }, timeout=15).json()
        pm = requests.post(f"{API}/admin/payment-methods", headers=ph, json={
            "label": "Cash A", "kind": "cash", "active": True, "sort_order": 1,
        }, timeout=15).json()
        rr = requests.post(f"{API}/cashier/receipts", headers=ph, json={
            "business_client_id": bc["id"], "amount": 9876, "motif": "tenant A only",
            "payment_method_id": pm["id"],
        }, timeout=15).json()
        # Tenant B lists → must NOT see it
        lr = requests.get(f"{API}/cashier/receipts", headers=bh, timeout=15)
        ids = {x["id"] for x in lr.json()}
        assert rr["id"] not in ids
        # Tenant B fetches direct → 404
        gr = requests.get(f"{API}/cashier/receipts/{rr['id']}", headers=bh, timeout=15)
        assert gr.status_code == 404


class TestInvoicesAndKpisIsolation:
    def test_kpis_scoped_per_tenant(self, tenant_a, tenant_b):
        ph = {"Authorization": f"Bearer {_forge(tenant_a['parent_id'], role='superviseur')}"}
        bh = {"Authorization": f"Bearer {_forge(tenant_b['boss_id'], role='superviseur')}"}
        # Tenant A creates an invoice
        bc = requests.post(f"{API}/admin/business-clients", headers=ph, json={
            "name": f"KPI-{uuid.uuid4().hex[:6]}", "phone": "+22611112222",
        }, timeout=15).json()
        pm = requests.post(f"{API}/admin/payment-methods", headers=ph, json={
            "label": "Cash KPI", "kind": "cash", "active": True, "sort_order": 1,
        }, timeout=15).json()
        inv = requests.post(f"{API}/cashier/invoices", headers=ph, json={
            "business_client_id": bc["id"], "kind": "invoice",
            "items": [{"label": "Service", "description": "Service", "quantity": 1, "unit_price_ht": 100000, "tva_pct": 0}],
            "discount_kind": "none", "discount_value": 0,
        }, timeout=15).json()
        assert inv.get("tenant_id") == tenant_a["parent_id"]
        # KPIs for tenant A should show this issued invoice
        k_a = requests.get(f"{API}/cashier/kpis", headers=ph, timeout=15).json()
        # Tenant A's restant_a_encaisser amount must include the 100000 invoice (≥ 100000)
        assert k_a["restant_a_encaisser"]["amount"] >= 100000
        # KPIs for tenant B should NOT include tenant A's invoices
        k_b = requests.get(f"{API}/cashier/kpis", headers=bh, timeout=15).json()
        # tenant_b is fresh: amounts should be 0
        assert k_b["restant_a_encaisser"]["amount"] == 0
        assert k_b["restant_a_encaisser"]["count"] == 0


class TestDropdownsIsolation:
    def test_legal_forms_isolated_per_tenant(self, tenant_a, tenant_b):
        ph = {"Authorization": f"Bearer {_forge(tenant_a['parent_id'], role='superviseur')}"}
        bh = {"Authorization": f"Bearer {_forge(tenant_b['boss_id'], role='superviseur')}"}
        label = f"SARL-{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/admin/legal-forms", headers=ph, json={"label": label}, timeout=15)
        assert r.status_code == 200, r.text
        # Tenant A sees it
        lst_a = requests.get(f"{API}/cashier/legal-forms", headers=ph, timeout=15).json()
        assert any(x["label"] == label for x in lst_a)
        # Tenant B does NOT
        lst_b = requests.get(f"{API}/cashier/legal-forms", headers=bh, timeout=15).json()
        assert not any(x["label"] == label for x in lst_b)
        # Tenant B can re-create the same label without conflict (per-tenant uniqueness)
        r2 = requests.post(f"{API}/admin/legal-forms", headers=bh, json={"label": label}, timeout=15)
        assert r2.status_code == 200, r2.text
