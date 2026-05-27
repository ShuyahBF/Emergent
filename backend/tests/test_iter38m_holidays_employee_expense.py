"""Iter38m — HR Holidays + Cashier Expenses attributed to employees."""
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
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def tenant(db):
    """Create a minimal tenant with: 1 admin + 1 cashier + 1 employee user."""
    admin_id = f"hm_adm_{uuid.uuid4().hex[:6]}"
    cashier_id = f"hm_csh_{uuid.uuid4().hex[:6]}"
    emp_user_id = f"hm_emp_{uuid.uuid4().hex[:6]}"
    other_id = f"hm_oth_{uuid.uuid4().hex[:6]}"
    company = f"HOL-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin H", "company": company, "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": cashier_id, "email": f"{cashier_id}@t.l", "password_hash": "x",
         "full_name": "Cashier H", "company": company, "role": "client",
         "can_cash": True, "tracked_user_id": admin_id,
         "account_status": "active", "created_at": now},
        {"id": emp_user_id, "email": f"{emp_user_id}@t.l", "password_hash": "x",
         "full_name": "Employee H", "company": company, "role": "client",
         "tracked_user_id": admin_id,
         "account_status": "active", "created_at": now},
        {"id": other_id, "email": f"{other_id}@t.l", "password_hash": "x",
         "full_name": "Other Co", "company": f"OTHER-{uuid.uuid4().hex[:4]}",
         "role": "admin", "account_status": "active", "created_at": now},
    ])
    yield {
        "admin_id": admin_id, "admin_token": _forge(admin_id, "admin"),
        "cashier_id": cashier_id, "cashier_token": _forge(cashier_id, "client"),
        "emp_user_id": emp_user_id, "emp_token": _forge(emp_user_id, "client"),
        "other_id": other_id, "other_token": _forge(other_id, "admin"),
        "company": company,
    }
    db.users.delete_many({"id": {"$in": [admin_id, cashier_id, emp_user_id, other_id]}})
    db.hr_employees.delete_many({"tenant_id": admin_id})
    db.hr_holidays.delete_many({"tenant_id": admin_id})
    db.cashier_expenses.delete_many({"tenant_id": admin_id})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ============================================================
# P1.1 — HR Holidays
# ============================================================
def test_holidays_list_empty(tenant):
    r = requests.get(f"{API}/hr/holidays?year=2026", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    assert r.json() == []


def test_holidays_import_bf_year(tenant, db):
    r = requests.post(
        f"{API}/hr/holidays/import?year=2026&country=BF",
        headers=_h(tenant["admin_token"]),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["country"] == "BF"
    assert data["year"] == 2026
    assert data["created_count"] >= 8
    # Verify well-known BF holidays
    labels = {h["label"] for h in data["created"]}
    assert "Jour de l'An" in labels
    assert "Fête de l'Indépendance" in labels
    assert "Noël" in labels
    # Year-substituted dates
    dates = {h["date"] for h in data["created"]}
    assert "2026-01-01" in dates
    assert "2026-08-05" in dates  # BF Independence Day
    assert "2026-12-25" in dates


def test_holidays_import_is_idempotent(tenant):
    requests.post(
        f"{API}/hr/holidays/import?year=2026&country=BF",
        headers=_h(tenant["admin_token"]),
    )
    # Re-import should not duplicate
    r = requests.post(
        f"{API}/hr/holidays/import?year=2026&country=BF",
        headers=_h(tenant["admin_token"]),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["created_count"] == 0
    assert data["skipped_count"] >= 8


def test_holidays_crud(tenant):
    # Create custom holiday
    r = requests.post(
        f"{API}/hr/holidays",
        headers=_h(tenant["admin_token"]),
        json={"date": "2026-06-10", "label": "Aïd el-Fitr (estimation)",
              "holiday_type": "religious", "is_paid": True},
    )
    assert r.status_code == 200, r.text
    hid = r.json()["id"]
    # Update label
    r = requests.patch(
        f"{API}/hr/holidays/{hid}",
        headers=_h(tenant["admin_token"]),
        json={"label": "Aïd el-Fitr", "date": "2026-06-12"},
    )
    assert r.status_code == 200
    assert r.json()["label"] == "Aïd el-Fitr"
    assert r.json()["date"] == "2026-06-12"
    # Delete
    r = requests.delete(f"{API}/hr/holidays/{hid}", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200


def test_holidays_tenant_isolated(tenant):
    # Admin from another company cannot see this tenant's holidays
    requests.post(
        f"{API}/hr/holidays/import?year=2026&country=BF",
        headers=_h(tenant["admin_token"]),
    )
    r = requests.get(
        f"{API}/hr/holidays?year=2026", headers=_h(tenant["other_token"])
    )
    assert r.status_code == 200
    # No holidays for other tenant
    assert all("Independance" not in h.get("label", "") for h in r.json())


def test_holidays_regular_user_forbidden(tenant):
    r = requests.get(f"{API}/hr/holidays?year=2026", headers=_h(tenant["emp_token"]))
    # Regular user (not admin/sup/Comptable) → 403
    assert r.status_code == 403


# ============================================================
# P1.2 — Expenses attributed to Employees
# ============================================================
def test_expense_employees_list(tenant, db):
    # Enroll the employee
    db.hr_employees.insert_one({
        "id": f"emp_{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant["admin_id"],
        "user_id": tenant["emp_user_id"],
        "email_snapshot": f"{tenant['emp_user_id']}@t.l",
        "name_snapshot": "Employee H",
        "matricule": "MAT-HOL-00001",
        "pay_type": "monthly",
        "base_salary": 100000,
        "currency": "XOF",
        "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.get(
        f"{API}/cashier/expenses/employees-list", headers=_h(tenant["cashier_token"])
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 1
    names = {i["name"] for i in items}
    assert "Employee H" in names


def test_expense_with_employee_attribution(tenant, db):
    # Enroll employee first
    eid = f"emp_{uuid.uuid4().hex[:8]}"
    db.hr_employees.insert_one({
        "id": eid,
        "tenant_id": tenant["admin_id"],
        "user_id": tenant["emp_user_id"],
        "email_snapshot": f"{tenant['emp_user_id']}@t.l",
        "name_snapshot": "Employee H",
        "matricule": "MAT-HOL-00001",
        "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Cashier creates an expense ATTRIBUTED to employee
    r = requests.post(
        f"{API}/cashier/expenses",
        headers=_h(tenant["cashier_token"]),
        json={
            "amount": 25000, "currency": "XOF", "method": "cash",
            "motif": "Avance pour mission terrain",
            "attribution_type": "employee", "employee_id": eid,
        },
    )
    assert r.status_code == 200, r.text
    exp = r.json()
    assert exp["attribution_type"] == "employee"
    assert exp["employee_id"] == eid
    assert exp["employee_user_id"] == tenant["emp_user_id"]
    assert exp["employee_name_snapshot"] == "Employee H"


def test_expense_employee_attribution_validates(tenant):
    # Missing employee_id when type=employee → 400
    r = requests.post(
        f"{API}/cashier/expenses",
        headers=_h(tenant["cashier_token"]),
        json={
            "amount": 10000, "method": "cash", "motif": "Test",
            "attribution_type": "employee",
        },
    )
    assert r.status_code == 400
    # Unknown employee_id → 404
    r = requests.post(
        f"{API}/cashier/expenses",
        headers=_h(tenant["cashier_token"]),
        json={
            "amount": 10000, "method": "cash", "motif": "Test",
            "attribution_type": "employee", "employee_id": "does-not-exist",
        },
    )
    assert r.status_code == 404


def test_employee_dashboard_card_includes_attributed_expense(tenant, db):
    # Enroll employee + create an expense attributed to them
    eid = f"emp_{uuid.uuid4().hex[:8]}"
    db.hr_employees.insert_one({
        "id": eid,
        "tenant_id": tenant["admin_id"],
        "user_id": tenant["emp_user_id"],
        "email_snapshot": f"{tenant['emp_user_id']}@t.l",
        "name_snapshot": "Employee H",
        "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Admin creates an expense for the employee
    r = requests.post(
        f"{API}/cashier/expenses",
        headers=_h(tenant["admin_token"]),
        json={
            "amount": 18000, "method": "cash", "motif": "Frais déplacement",
            "attribution_type": "employee", "employee_id": eid,
        },
    )
    assert r.status_code == 200
    # Employee opens their dashboard card → sees the expense
    r = requests.get(
        f"{API}/cashier/expenses/me/dashboard-card",
        headers=_h(tenant["emp_token"]),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] >= 1
    assert data["total_unjustified"] >= 18000


def test_third_party_attribution_default(tenant):
    # Default attribution_type should still be "third_party"
    r = requests.post(
        f"{API}/cashier/expenses",
        headers=_h(tenant["cashier_token"]),
        json={
            "amount": 5000, "method": "cash", "motif": "Café équipe",
            "payee": "Supermarché XYZ",
        },
    )
    assert r.status_code == 200
    exp = r.json()
    assert exp["attribution_type"] == "third_party"
    assert exp["employee_user_id"] is None


def test_welcome_briefing_includes_attributed_expenses(tenant, db):
    """Iter38m — Welcome briefing for the employee should include attributed
    expenses (employee_user_id == me), not just those they created."""
    eid = f"emp_{uuid.uuid4().hex[:8]}"
    db.hr_employees.insert_one({
        "id": eid,
        "tenant_id": tenant["admin_id"],
        "user_id": tenant["emp_user_id"],
        "email_snapshot": f"{tenant['emp_user_id']}@t.l",
        "name_snapshot": "Employee H",
        "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Admin creates an expense attributed to employee
    requests.post(
        f"{API}/cashier/expenses",
        headers=_h(tenant["admin_token"]),
        json={
            "amount": 12000, "method": "cash", "motif": "Mission Banfora",
            "attribution_type": "employee", "employee_id": eid,
        },
    )
    # Hit welcome briefing as the employee
    r = requests.get(f"{API}/me/welcome-briefing", headers=_h(tenant["emp_token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    rem = data.get("expense_reminder")
    assert rem is not None, f"expense_reminder missing in welcome briefing: {data}"
    assert rem["count"] >= 1
    assert rem["total_unjustified"] >= 12000
