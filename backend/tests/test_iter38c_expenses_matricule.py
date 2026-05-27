"""Iter38c — Cashier Expenses + Auto-matricule + Tracked-user dashboard card."""
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
    admin_id = f"exp_adm_{uuid.uuid4().hex[:6]}"
    sup_id = f"exp_sup_{uuid.uuid4().hex[:6]}"
    cashier_id = f"exp_csh_{uuid.uuid4().hex[:6]}"
    other_id = f"exp_oth_{uuid.uuid4().hex[:6]}"
    company = f"EXP-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin Co", "company": company, "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
         "full_name": "Sup Co", "company": company, "role": "superviseur",
         "account_status": "active", "created_at": now},
        {"id": cashier_id, "email": f"{cashier_id}@t.l", "password_hash": "x",
         "full_name": "Caissier Co", "company": company, "parent_client_id": admin_id,
         "role": "client", "can_cash": True,
         "tracked_user_id": f"tu_{uuid.uuid4().hex[:6]}", "tracked_role": "Caissier",
         "account_status": "active", "created_at": now},
        {"id": other_id, "email": f"{other_id}@t.l", "password_hash": "x",
         "full_name": "Outsider", "company": f"OTHER-{uuid.uuid4().hex[:4]}",
         "role": "admin", "account_status": "active", "created_at": now},
    ])
    # Set the global settings deadline to 1 hour for fast testing (we'll reset)
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"expense_justification_deadline_hours": 72}},
        upsert=True,
    )
    yield {
        "admin_id": admin_id,
        "sup_id": sup_id,
        "cashier_id": cashier_id,
        "other_id": other_id,
        "company": company,
        "ah": {"Authorization": f"Bearer {_forge(admin_id, role='admin')}"},
        "sh": {"Authorization": f"Bearer {_forge(sup_id)}"},
        "csh": {"Authorization": f"Bearer {_forge(cashier_id, role='client')}"},
        "oh": {"Authorization": f"Bearer {_forge(other_id, role='admin')}"},
    }
    db.users.delete_many({"id": {"$in": [admin_id, sup_id, cashier_id, other_id]}})
    db.cashier_expenses.delete_many({"tenant_id": {"$in": [admin_id, other_id]}})
    db.hr_employees.delete_many({"tenant_id": {"$in": [admin_id, other_id]}})
    db.employee_matricule_counters.delete_many({"tenant_id": {"$in": [admin_id, other_id]}})


# ========================================================================
# Auto-matricule
# ========================================================================
def test_employee_gets_auto_matricule(tenant):
    r = requests.post(
        f"{API}/hr/employees", headers=tenant["sh"],
        json={"user_id": tenant["cashier_id"], "base_salary": 100000, "pay_type": "monthly"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    emp = r.json()
    assert emp.get("matricule"), "Matricule should be auto-generated"
    assert emp["matricule"].startswith("MAT-")
    assert emp["matricule"].endswith("00001")  # First in this tenant


def test_matricule_increments_per_tenant(tenant, db):
    # Add 2 more users in the same tenant
    a = f"e2_{uuid.uuid4().hex[:6]}"
    b = f"e2_{uuid.uuid4().hex[:6]}"
    db.users.insert_many([
        {"id": a, "email": f"{a}@t.l", "password_hash": "x", "full_name": "Alice",
         "company": tenant["company"], "parent_client_id": tenant["admin_id"],
         "role": "client", "account_status": "active",
         "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": b, "email": f"{b}@t.l", "password_hash": "x", "full_name": "Bob",
         "company": tenant["company"], "parent_client_id": tenant["admin_id"],
         "role": "client", "account_status": "active",
         "created_at": datetime.now(timezone.utc).isoformat()},
    ])
    # First one in this tenant
    r1 = requests.post(f"{API}/hr/employees", headers=tenant["sh"],
                       json={"user_id": a, "base_salary": 100000, "pay_type": "monthly"},
                       timeout=15)
    r2 = requests.post(f"{API}/hr/employees", headers=tenant["sh"],
                       json={"user_id": b, "base_salary": 100000, "pay_type": "monthly"},
                       timeout=15)
    assert r1.json()["matricule"].endswith("00001")
    assert r2.json()["matricule"].endswith("00002")
    db.users.delete_many({"id": {"$in": [a, b]}})


def test_backfill_matricules(tenant, db):
    # Insert an employee bypassing API (no matricule)
    eid = str(uuid.uuid4())
    db.hr_employees.insert_one({
        "id": eid, "tenant_id": tenant["admin_id"], "user_id": tenant["cashier_id"],
        "name_snapshot": "Legacy User", "email_snapshot": "legacy@t.l",
        "base_salary": 0, "pay_type": "monthly", "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.post(f"{API}/hr/employees/backfill-matricules", headers=tenant["ah"], timeout=15)
    assert r.status_code == 200
    out = r.json()
    assert out["count"] >= 1
    # Verify matricule was assigned
    e = db.hr_employees.find_one({"id": eid}, {"_id": 0})
    assert e.get("matricule")


# ========================================================================
# Cashier Expenses CRUD + permissions
# ========================================================================
def test_can_cash_can_create_expense(tenant):
    r = requests.post(
        f"{API}/cashier/expenses", headers=tenant["csh"],
        json={"amount": 5000, "method": "cash", "motif": "Achat consommables", "currency": "XOF"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["amount"] == 5000
    assert e["method"] == "cash"
    assert e["is_justified"] is False
    assert e["created_by"] == tenant["cashier_id"]
    assert e["deadline_at"] is not None  # because deadline_hours > 0


def test_admin_can_edit_and_delete_only(tenant):
    cr = requests.post(
        f"{API}/cashier/expenses", headers=tenant["csh"],
        json={"amount": 3000, "method": "check", "motif": "Frais bureau"},
        timeout=10,
    )
    eid = cr.json()["id"]
    # Iter38o — Cashier (creator) CAN edit while not justified
    r1 = requests.patch(f"{API}/cashier/expenses/{eid}", headers=tenant["csh"],
                        json={"amount": 4000}, timeout=10)
    assert r1.status_code == 200
    assert r1.json()["amount"] == 4000
    # Sup CAN edit (treated as admin/sup tier)
    r2 = requests.patch(f"{API}/cashier/expenses/{eid}", headers=tenant["sh"],
                        json={"amount": 4200}, timeout=10)
    assert r2.status_code == 200
    # Admin can edit as well
    r3 = requests.patch(f"{API}/cashier/expenses/{eid}", headers=tenant["ah"],
                        json={"amount": 4500, "motif": "Frais bureau (corrigé)"}, timeout=10)
    assert r3.status_code == 200
    assert r3.json()["amount"] == 4500
    # Sup cannot delete (admin only)
    rd1 = requests.delete(f"{API}/cashier/expenses/{eid}", headers=tenant["sh"], timeout=10)
    assert rd1.status_code == 403
    # Admin can delete (soft)
    rd2 = requests.delete(f"{API}/cashier/expenses/{eid}", headers=tenant["ah"], timeout=10)
    assert rd2.status_code == 200


def test_justify_within_deadline_accepted(tenant):
    cr = requests.post(
        f"{API}/cashier/expenses", headers=tenant["csh"],
        json={"amount": 2000, "method": "cash", "motif": "Carburant"},
        timeout=10,
    )
    eid = cr.json()["id"]
    # Justify immediately
    rj = requests.post(
        f"{API}/cashier/expenses/{eid}/justify", headers=tenant["csh"],
        json={"justification_text": "Facture station Total fournie"}, timeout=10,
    )
    assert rj.status_code == 200, rj.text
    out = rj.json()
    assert out["is_justified"] is True
    assert out["justified_by"] == tenant["cashier_id"]
    assert out["justified_at"] is not None
    # Cannot re-justify
    rj2 = requests.post(f"{API}/cashier/expenses/{eid}/justify",
                        headers=tenant["csh"], json={}, timeout=10)
    assert rj2.status_code == 400


def test_justify_after_deadline_rejected(tenant, db):
    # Create expense, then backdate created_at to be older than 72h
    cr = requests.post(
        f"{API}/cashier/expenses", headers=tenant["csh"],
        json={"amount": 1500, "method": "cash", "motif": "Retard test"},
        timeout=10,
    )
    eid = cr.json()["id"]
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
    db.cashier_expenses.update_one({"id": eid}, {"$set": {"created_at": old_ts}})
    # Cashier tries to justify → 400
    rj = requests.post(f"{API}/cashier/expenses/{eid}/justify", headers=tenant["csh"],
                       json={"justification_text": "Trop tard"}, timeout=10)
    assert rj.status_code == 400
    assert "Délai" in rj.json().get("detail", "")
    # Admin can FORCE
    rj2 = requests.post(f"{API}/cashier/expenses/{eid}/justify", headers=tenant["ah"],
                        json={"justification_text": "Admin force", "force": True}, timeout=10)
    assert rj2.status_code == 200
    assert rj2.json()["is_justified"] is True
    assert rj2.json()["forced_justification"] is True


def test_deadline_zero_means_unlimited(tenant, db):
    db.settings.update_one({"_id": "global"},
                           {"$set": {"expense_justification_deadline_hours": 0}},
                           upsert=True)
    cr = requests.post(
        f"{API}/cashier/expenses", headers=tenant["csh"],
        json={"amount": 500, "method": "cash", "motif": "Test no limit"},
        timeout=10,
    )
    eid = cr.json()["id"]
    # Backdate by 1 year
    very_old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    db.cashier_expenses.update_one({"id": eid}, {"$set": {"created_at": very_old}})
    rj = requests.post(f"{API}/cashier/expenses/{eid}/justify", headers=tenant["csh"],
                       json={"justification_text": "Toujours OK"}, timeout=10)
    assert rj.status_code == 200, rj.text
    # Reset
    db.settings.update_one({"_id": "global"},
                           {"$set": {"expense_justification_deadline_hours": 72}})


def test_monthly_summary_and_tenant_isolation(tenant):
    today = datetime.now(timezone.utc)
    month = today.strftime("%Y-%m")
    # Create 2 expenses
    for amount in (1000, 2500):
        requests.post(f"{API}/cashier/expenses", headers=tenant["csh"],
                      json={"amount": amount, "method": "cash", "motif": "Test mensuel",
                            "expense_date": today.date().isoformat()},
                      timeout=10)
    r = requests.get(f"{API}/cashier/expenses/monthly-summary?month={month}",
                     headers=tenant["sh"], timeout=10)
    assert r.status_code == 200
    s = r.json()
    assert s["count"] >= 2
    assert s["deadline_hours"] == 72
    # The 'other' tenant must NOT see these
    r2 = requests.get(f"{API}/cashier/expenses/monthly-summary?month={month}",
                      headers=tenant["oh"], timeout=10)
    assert r2.json()["count"] == 0


# ========================================================================
# Late-unjustified → Dashboard card for tracked user
# ========================================================================
def test_my_dashboard_card_counts_unjustified_and_late(tenant, db):
    # Reset deadline to 72h
    db.settings.update_one({"_id": "global"},
                           {"$set": {"expense_justification_deadline_hours": 72}}, upsert=True)
    # Create 2 fresh expenses
    requests.post(f"{API}/cashier/expenses", headers=tenant["csh"],
                  json={"amount": 1000, "method": "cash", "motif": "X"}, timeout=10)
    cr = requests.post(f"{API}/cashier/expenses", headers=tenant["csh"],
                       json={"amount": 4000, "method": "cash", "motif": "Y old"}, timeout=10)
    eid = cr.json()["id"]
    # Backdate to be late
    old = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
    db.cashier_expenses.update_one({"id": eid}, {"$set": {"created_at": old}})
    r = requests.get(f"{API}/cashier/expenses/me/dashboard-card", headers=tenant["csh"], timeout=10)
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["count"] >= 2
    assert card["late_unjustified"] >= 4000
    assert card["deadline_hours"] == 72


# ========================================================================
# Payslip integration — late expenses deducted from net
# ========================================================================
def test_payslip_includes_late_expense_deduction(tenant, db):
    # Reset deadline
    db.settings.update_one({"_id": "global"},
                           {"$set": {"expense_justification_deadline_hours": 72}}, upsert=True)
    # Ensure an employee exists for the cashier user
    # (test_employee_gets_auto_matricule already created one; we reuse)
    emps = requests.get(f"{API}/hr/employees", headers=tenant["sh"], timeout=10).json()
    emp = next((e for e in emps if e.get("user_id") == tenant["cashier_id"]), None)
    if not emp:
        emp = requests.post(f"{API}/hr/employees", headers=tenant["sh"],
                            json={"user_id": tenant["cashier_id"],
                                  "base_salary": 100000, "pay_type": "monthly"},
                            timeout=15).json()
    today = datetime.now(timezone.utc)
    month = today.strftime("%Y-%m")
    # Add a late-unjustified expense by the cashier
    cr = requests.post(f"{API}/cashier/expenses", headers=tenant["csh"],
                       json={"amount": 7500, "method": "cash", "motif": "Z late",
                             "expense_date": today.date().isoformat()},
                       timeout=10)
    eid = cr.json()["id"]
    old = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
    db.cashier_expenses.update_one({"id": eid}, {"$set": {"created_at": old}})
    # Compute payslip
    r = requests.get(
        f"{API}/hr/employees/{emp['id']}/payslip?month={month}",
        headers=tenant["sh"], timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["late_expenses_deduction"] >= 7500.0
    # PDF still generates
    pdf = requests.get(
        f"{API}/hr/employees/{emp['id']}/payslip.pdf?month={month}",
        headers=tenant["sh"], timeout=15,
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    # Matricule must appear in employee block
    assert data["employee"].get("matricule")
