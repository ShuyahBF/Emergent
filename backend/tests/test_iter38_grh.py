"""Iter38 — GRH module: Personnel, Salaires, Présence (Phases 1+2+3)."""
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


def _forge(uid: str, role: str = "superviseur") -> str:
    return pyjwt.encode(
        {
            "sub": uid,
            "role": role,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int(
                (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
            ),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def hr_tenant(db):
    """Tenant with 1 sup (admin of GRH), 1 client (eligible employee),
    1 client+tracked Comptable, 1 client in another tenant (isolation test)."""
    sup_id = f"hrsup_{uuid.uuid4().hex[:6]}"
    company = f"GRH-{uuid.uuid4().hex[:4]}"
    cli_id = f"hrcli_{uuid.uuid4().hex[:6]}"
    cpt_id = f"hrcpt_{uuid.uuid4().hex[:6]}"
    other_id = f"hrother_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many(
        [
            {
                "id": sup_id,
                "email": f"{sup_id}@test.local",
                "password_hash": "x",
                "full_name": "Boss GRH",
                "company": company,
                "role": "superviseur",
                "account_status": "active",
                "created_at": now,
            },
            {
                "id": cli_id,
                "email": f"{cli_id}@test.local",
                "password_hash": "x",
                "full_name": "Employee Alice",
                "company": company,
                "parent_client_id": sup_id,
                "role": "client",
                "account_status": "active",
                "created_at": now,
            },
            {
                "id": cpt_id,
                "email": f"{cpt_id}@test.local",
                "password_hash": "x",
                "full_name": "Comptable Carol",
                "company": company,
                "parent_client_id": sup_id,
                "role": "client",
                "tracked_role": "Comptable",
                "tracked_user_id": f"tu_{uuid.uuid4().hex[:6]}",
                "account_status": "active",
                "created_at": now,
            },
            {
                "id": other_id,
                "email": f"{other_id}@test.local",
                "password_hash": "x",
                "full_name": "Other Tenant Bob",
                "company": f"OTHER-{uuid.uuid4().hex[:4]}",
                "role": "superviseur",
                "account_status": "active",
                "created_at": now,
            },
        ]
    )
    yield {
        "sup_id": sup_id,
        "cli_id": cli_id,
        "cpt_id": cpt_id,
        "other_id": other_id,
        "company": company,
        "sup_h": {"Authorization": f"Bearer {_forge(sup_id)}"},
        "cpt_h": {"Authorization": f"Bearer {_forge(cpt_id, role='client')}"},
        "cli_h": {"Authorization": f"Bearer {_forge(cli_id, role='client')}"},
        "other_h": {"Authorization": f"Bearer {_forge(other_id)}"},
    }
    db.users.delete_many(
        {"id": {"$in": [sup_id, cli_id, cpt_id, other_id]}}
    )
    db.hr_employees.delete_many({"tenant_id": {"$in": [sup_id, other_id]}})
    db.access_logs.delete_many({"user_id": {"$in": [sup_id, cli_id, cpt_id]}})


# =====================================================================
# Phase 1 — Personnel CRUD + Comptable access
# =====================================================================
def test_eligible_users_lists_tenant_members_only(hr_tenant):
    r = requests.get(f"{API}/hr/eligible-users", headers=hr_tenant["sup_h"], timeout=15)
    assert r.status_code == 200, r.text
    items = r.json()
    ids = {u["id"] for u in items}
    assert hr_tenant["sup_id"] in ids
    assert hr_tenant["cli_id"] in ids
    assert hr_tenant["cpt_id"] in ids
    assert hr_tenant["other_id"] not in ids


def test_comptable_can_access_hr(hr_tenant):
    r = requests.get(f"{API}/hr/eligible-users", headers=hr_tenant["cpt_h"], timeout=15)
    assert r.status_code == 200


def test_regular_client_cannot_access_hr(hr_tenant):
    r = requests.get(f"{API}/hr/employees", headers=hr_tenant["cli_h"], timeout=15)
    assert r.status_code == 403


def test_create_employee_and_idempotence(hr_tenant):
    payload = {
        "user_id": hr_tenant["cli_id"],
        "base_salary": 250000,
        "pay_type": "monthly",
        "currency": "XOF",
        "monthly_hours_baseline": 160,
        "job_title": "Technicien support",
    }
    r = requests.post(f"{API}/hr/employees", headers=hr_tenant["sup_h"], json=payload, timeout=15)
    assert r.status_code == 200, r.text
    emp = r.json()
    assert emp["user_id"] == hr_tenant["cli_id"]
    assert emp["tenant_id"] == hr_tenant["sup_id"]
    assert emp["base_salary"] == 250000
    assert emp["deleted_at"] is None
    # Idempotence — second insert must conflict
    r2 = requests.post(f"{API}/hr/employees", headers=hr_tenant["sup_h"], json=payload, timeout=15)
    assert r2.status_code == 409


def test_create_employee_cross_tenant_blocked(hr_tenant):
    # other_id tries to enroll cli_id (different tenant)
    payload = {
        "user_id": hr_tenant["cli_id"],
        "base_salary": 100000,
        "pay_type": "monthly",
        "currency": "XOF",
    }
    r = requests.post(f"{API}/hr/employees", headers=hr_tenant["other_h"], json=payload, timeout=15)
    assert r.status_code == 404


def test_list_employees_tenant_scoped(hr_tenant):
    # enroll the cli first
    requests.post(
        f"{API}/hr/employees",
        headers=hr_tenant["sup_h"],
        json={"user_id": hr_tenant["cli_id"], "base_salary": 200000, "pay_type": "monthly"},
        timeout=15,
    )
    r = requests.get(f"{API}/hr/employees", headers=hr_tenant["sup_h"], timeout=15)
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    assert all(it["tenant_id"] == hr_tenant["sup_id"] for it in items)
    # The other tenant must NOT see this employee
    r2 = requests.get(f"{API}/hr/employees", headers=hr_tenant["other_h"], timeout=15)
    assert r2.status_code == 200
    other_items = r2.json()
    assert all(it["tenant_id"] != hr_tenant["sup_id"] for it in other_items)


def test_update_and_soft_delete_employee(hr_tenant):
    create = requests.post(
        f"{API}/hr/employees",
        headers=hr_tenant["sup_h"],
        json={"user_id": hr_tenant["cli_id"], "base_salary": 200000, "pay_type": "monthly"},
        timeout=15,
    ).json()
    eid = create["id"]
    # Update salary
    upd = requests.patch(
        f"{API}/hr/employees/{eid}",
        headers=hr_tenant["sup_h"],
        json={"base_salary": 300000, "job_title": "Senior"},
        timeout=15,
    )
    assert upd.status_code == 200
    assert upd.json()["base_salary"] == 300000
    assert upd.json()["job_title"] == "Senior"
    # Soft delete
    dr = requests.delete(f"{API}/hr/employees/{eid}", headers=hr_tenant["sup_h"], timeout=15)
    assert dr.status_code == 200
    # Hidden by default
    items = requests.get(f"{API}/hr/employees", headers=hr_tenant["sup_h"], timeout=15).json()
    assert all(it["id"] != eid for it in items)
    # Visible with include_deleted=true
    items_all = requests.get(
        f"{API}/hr/employees?include_deleted=true",
        headers=hr_tenant["sup_h"],
        timeout=15,
    ).json()
    assert any(it["id"] == eid and it["deleted_at"] is not None for it in items_all)
    # Restore
    rr = requests.post(
        f"{API}/hr/employees/{eid}/restore", headers=hr_tenant["sup_h"], timeout=15
    )
    assert rr.status_code == 200
    assert rr.json()["deleted_at"] is None


# =====================================================================
# Phase 3 — Timesheet
# =====================================================================
def test_timesheet_from_access_logs(hr_tenant, db):
    create = requests.post(
        f"{API}/hr/employees",
        headers=hr_tenant["sup_h"],
        json={
            "user_id": hr_tenant["cli_id"],
            "base_salary": 160000,
            "pay_type": "monthly",
            "monthly_hours_baseline": 160,
        },
        timeout=15,
    ).json()
    eid = create["id"]
    now = datetime.now(timezone.utc)
    year_month = now.strftime("%Y-%m")
    # Inject 2 access_logs entries on day D-1 and D-2: first/last
    base = datetime(now.year, now.month, max(1, min(15, now.day)), tzinfo=timezone.utc)
    day_a = base - timedelta(days=2)
    day_b = base - timedelta(days=1)
    rows = [
        {
            "id": f"al_{uuid.uuid4().hex[:6]}",
            "user_id": hr_tenant["cli_id"],
            "user_email": f"{hr_tenant['cli_id']}@test.local",
            "module": "x",
            "page": "/portal",
            "created_at": (day_a.replace(hour=8, minute=0)).isoformat(),
        },
        {
            "id": f"al_{uuid.uuid4().hex[:6]}",
            "user_id": hr_tenant["cli_id"],
            "user_email": f"{hr_tenant['cli_id']}@test.local",
            "module": "x",
            "page": "/portal",
            "created_at": (day_a.replace(hour=17, minute=0)).isoformat(),
        },
        {
            "id": f"al_{uuid.uuid4().hex[:6]}",
            "user_id": hr_tenant["cli_id"],
            "user_email": f"{hr_tenant['cli_id']}@test.local",
            "module": "x",
            "page": "/portal",
            "created_at": (day_b.replace(hour=9, minute=30)).isoformat(),
        },
        {
            "id": f"al_{uuid.uuid4().hex[:6]}",
            "user_id": hr_tenant["cli_id"],
            "user_email": f"{hr_tenant['cli_id']}@test.local",
            "module": "x",
            "page": "/portal",
            "created_at": (day_b.replace(hour=15, minute=30)).isoformat(),
        },
    ]
    db.access_logs.insert_many(rows)
    r = requests.get(
        f"{API}/hr/employees/{eid}/timesheet?month={year_month}",
        headers=hr_tenant["sup_h"],
        timeout=15,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["totals"]["days_worked"] == 2
    # Day A: 9h, Day B: 6h → total 15h
    assert abs(out["totals"]["hours_worked"] - 15.0) < 0.05
    assert out["totals"]["expected_hours"] == 160
    # Computed gross (monthly) = 160000 * 15/160 = 15000
    assert abs(out["totals"]["computed_gross"] - 15000.0) < 0.5


def test_timesheet_hourly_pay(hr_tenant, db):
    # Create new employee enrolled on sup_id (so eligibility check passes)
    create = requests.post(
        f"{API}/hr/employees",
        headers=hr_tenant["sup_h"],
        json={
            "user_id": hr_tenant["cpt_id"],
            "base_salary": 0,
            "pay_type": "hourly",
            "hourly_rate": 5000,
        },
        timeout=15,
    ).json()
    eid = create["id"]
    now = datetime.now(timezone.utc)
    year_month = now.strftime("%Y-%m")
    base = datetime(now.year, now.month, 5, tzinfo=timezone.utc)
    rows = [
        {
            "id": f"al_{uuid.uuid4().hex[:6]}",
            "user_id": hr_tenant["cpt_id"],
            "user_email": f"{hr_tenant['cpt_id']}@test.local",
            "module": "x",
            "page": "/p",
            "created_at": (base.replace(hour=8)).isoformat(),
        },
        {
            "id": f"al_{uuid.uuid4().hex[:6]}",
            "user_id": hr_tenant["cpt_id"],
            "user_email": f"{hr_tenant['cpt_id']}@test.local",
            "module": "x",
            "page": "/p",
            "created_at": (base.replace(hour=12)).isoformat(),
        },
    ]
    db.access_logs.insert_many(rows)
    r = requests.get(
        f"{API}/hr/employees/{eid}/timesheet?month={year_month}",
        headers=hr_tenant["sup_h"],
        timeout=15,
    )
    assert r.status_code == 200
    out = r.json()
    assert abs(out["totals"]["hours_worked"] - 4.0) < 0.05
    # 4 hours * 5000 = 20000
    assert abs(out["totals"]["computed_gross"] - 20000.0) < 0.5


# =====================================================================
# Comptable: Caisse READ + GRH WRITE
# =====================================================================
def test_comptable_read_cashier_lists(hr_tenant):
    # Business clients GET (line 556 — uses _can_view_cashier now)
    r = requests.get(
        f"{API}/admin/business-clients", headers=hr_tenant["cpt_h"], timeout=15
    )
    assert r.status_code == 200, r.text
    # Products GET
    r2 = requests.get(
        f"{API}/admin/products", headers=hr_tenant["cpt_h"], timeout=15
    )
    assert r2.status_code == 200


def test_comptable_cannot_write_cashier(hr_tenant):
    # Should NOT be able to create a business client (sup-only endpoint)
    r = requests.post(
        f"{API}/admin/business-clients",
        headers=hr_tenant["cpt_h"],
        json={"name": "Should fail"},
        timeout=15,
    )
    assert r.status_code in (401, 403)
