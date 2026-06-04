"""Iter40-hr-fixed — `fixed` (forfaitaire) pay type for HR employees.

Use case: an agent hired late in the month, contractor on a flat fee,
trial period, or any employee whose payment should NOT vary with the
hours worked. The base_salary is paid in full each month, regardless of
hours_worked or unjustified absences.

Validates:
 - POST /hr/employees accepts pay_type="fixed"
 - PUT /hr/employees/{id} accepts pay_type="fixed"
 - Invalid pay_type rejected (HTTP 422)
 - GET /hr/employees/{id}/timesheet?month=YYYY-MM returns computed_gross == base_salary
   (not prorated, even with 0 hours worked)
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


def _forge(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def admin(db):
    admin_id = f"hrfx_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin"), admin_id
    db.users.delete_one({"id": admin_id})
    db.hr_employees.delete_many({"tenant_id": admin_id})


@pytest.fixture
def employee_user(db, admin):
    _, admin_id = admin
    user_id = f"hrfx_usr_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": user_id, "email": f"{user_id}@t.l", "password_hash": "x",
        "role": "team", "account_status": "active",
        "full_name": "Test Agent Forfaitaire",
        # Tenant scoping: hr.py resolves tenant from parent_client_id
        "parent_client_id": admin_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield user_id
    db.users.delete_one({"id": user_id})


def test_create_employee_with_fixed_pay_type(admin, employee_user, db):
    token, _ = admin
    r = requests.post(
        f"{API}/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_id": employee_user,
            "base_salary": 150000,
            "pay_type": "fixed",
            "currency": "XOF",
            "monthly_hours_baseline": 160,
            "job_title": "Consultant forfait",
        }, timeout=15,
    )
    assert r.status_code == 200, r.text
    emp = r.json()
    assert emp["pay_type"] == "fixed"
    assert emp["base_salary"] == 150000


def test_invalid_pay_type_rejected(admin, employee_user):
    token, _ = admin
    r = requests.post(
        f"{API}/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_id": employee_user,
            "base_salary": 100000, "pay_type": "weekly", "currency": "XOF",
        }, timeout=10,
    )
    assert r.status_code == 422


def test_update_employee_to_fixed(admin, employee_user, db):
    """Existing monthly employee can be switched to fixed."""
    token, admin_id = admin
    r = requests.post(
        f"{API}/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": employee_user, "base_salary": 200000, "pay_type": "monthly",
              "currency": "XOF", "monthly_hours_baseline": 160},
        timeout=10,
    )
    assert r.status_code == 200
    eid = r.json()["id"]
    r2 = requests.patch(
        f"{API}/hr/employees/{eid}",
        headers={"Authorization": f"Bearer {token}"},
        json={"pay_type": "fixed"}, timeout=10,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["pay_type"] == "fixed"


def test_fixed_timesheet_returns_full_base_salary_with_zero_hours(admin, employee_user, db):
    """The core use case: agent hired late in the month, no hours yet, but
    should still receive the full forfait amount."""
    token, admin_id = admin
    # Create the fixed employee
    r = requests.post(
        f"{API}/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_id": employee_user, "base_salary": 100000, "pay_type": "fixed",
            "currency": "XOF", "monthly_hours_baseline": 160,
        }, timeout=10,
    )
    assert r.status_code == 200
    eid = r.json()["id"]
    # Query the current month's timesheet — no presence has been logged
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    r2 = requests.get(
        f"{API}/hr/employees/{eid}/timesheet?month={month}",
        headers={"Authorization": f"Bearer {token}"}, timeout=15,
    )
    assert r2.status_code == 200, r2.text
    totals = r2.json()["totals"]
    assert totals["pay_type"] == "fixed"
    assert totals["base_salary"] == 100000
    # Critical assertion: with 0 hours_worked, fixed mode still pays the full amount
    assert totals["hours_worked"] == 0
    assert totals["computed_gross"] == 100000, (
        f"Fixed pay_type must pay full base_salary regardless of hours; got {totals['computed_gross']}"
    )


def test_monthly_with_zero_hours_returns_zero(admin, employee_user, db):
    """Regression: monthly mode still prorates (= 0 with 0 hours). Ensures
    we didn't accidentally break the existing behaviour."""
    token, admin_id = admin
    r = requests.post(
        f"{API}/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_id": employee_user, "base_salary": 100000, "pay_type": "monthly",
            "currency": "XOF", "monthly_hours_baseline": 160,
        }, timeout=10,
    )
    eid = r.json()["id"]
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    r2 = requests.get(
        f"{API}/hr/employees/{eid}/timesheet?month={month}",
        headers={"Authorization": f"Bearer {token}"}, timeout=15,
    )
    totals = r2.json()["totals"]
    assert totals["pay_type"] == "monthly"
    assert totals["computed_gross"] == 0, (
        f"Monthly mode must prorate (=0 when 0 hours); got {totals['computed_gross']}"
    )
