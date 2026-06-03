"""S-iter39s (2026-02) — GRH Primes (bonuses) & Indemnités (allowances).

End-to-end HTTP tests:
  * CRUD allowances (create, list, patch, toggle active, delete)
  * CRUD bonuses for a specific month (create, list, delete)
  * Payslip integration: gross + allowances + bonuses are summed, taxes
    apply on the new gross_with_gains, net reflects the new total.
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


def _forge(uid: str, role: str = "superviseur") -> str:
    return pyjwt.encode(
        {
            "sub": uid,
            "role": role,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def tenant(db):
    sup_id = f"hr3sup_{uuid.uuid4().hex[:6]}"
    cli_id = f"hr3cli_{uuid.uuid4().hex[:6]}"
    company = f"GRH3-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
         "full_name": "Boss S39s", "company": company, "role": "superviseur",
         "account_status": "active", "created_at": now},
        {"id": cli_id, "email": f"{cli_id}@t.l", "password_hash": "x",
         "full_name": "Alice S39s", "company": company, "parent_client_id": sup_id,
         "role": "client", "account_status": "active", "created_at": now},
    ])
    sh = {"Authorization": f"Bearer {_forge(sup_id)}"}
    emp = requests.post(
        f"{API}/hr/employees", headers=sh,
        json={"user_id": cli_id, "base_salary": 200000, "pay_type": "monthly",
              "monthly_hours_baseline": 160, "currency": "XOF"},
        timeout=15,
    ).json()
    yield {"sup_id": sup_id, "cli_id": cli_id, "sh": sh, "emp": emp, "company": company}
    db.users.delete_many({"id": {"$in": [sup_id, cli_id]}})
    db.hr_employees.delete_many({"tenant_id": sup_id})
    db.hr_allowances.delete_many({"tenant_id": sup_id})
    db.hr_bonuses.delete_many({"tenant_id": sup_id})


# =====================================================================
# Allowances CRUD
# =====================================================================
def test_allowance_full_crud(tenant):
    eid = tenant["emp"]["id"]
    sh = tenant["sh"]

    # Empty list at start
    r = requests.get(f"{API}/hr/employees/{eid}/allowances", headers=sh, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json() == []

    # Create
    r = requests.post(
        f"{API}/hr/employees/{eid}/allowances", headers=sh,
        json={"label": "Indemnité transport", "amount": 25000, "active": True, "notes": "Bus + taxi"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    al = r.json()
    assert al["id"] and al["label"] == "Indemnité transport" and al["amount"] == 25000
    aid = al["id"]

    # Patch (amount + label)
    r = requests.patch(f"{API}/hr/allowances/{aid}", headers=sh,
                       json={"amount": 30000, "label": "Indemnité transport (révisée)"}, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 30000
    assert "révisée" in r.json()["label"]

    # Toggle inactive
    r = requests.patch(f"{API}/hr/allowances/{aid}", headers=sh,
                       json={"active": False}, timeout=10)
    assert r.status_code == 200
    assert r.json()["active"] is False

    # Delete
    r = requests.delete(f"{API}/hr/allowances/{aid}", headers=sh, timeout=10)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Confirm gone
    r = requests.get(f"{API}/hr/employees/{eid}/allowances", headers=sh, timeout=10)
    assert r.json() == []


def test_allowance_404_on_unknown_employee(tenant):
    sh = tenant["sh"]
    r = requests.post(
        f"{API}/hr/employees/UNKNOWN/allowances", headers=sh,
        json={"label": "X", "amount": 10}, timeout=10,
    )
    assert r.status_code == 404


# =====================================================================
# Bonuses CRUD
# =====================================================================
def test_bonus_full_crud(tenant):
    eid = tenant["emp"]["id"]
    sh = tenant["sh"]
    month = "2026-02"
    other_month = "2026-03"

    # Create two bonuses in Feb, one in March
    payloads = [
        {"month": month, "label": "Prime de rendement", "amount": 40000},
        {"month": month, "label": "Prime exceptionnelle", "amount": 15000},
        {"month": other_month, "label": "Prime de Noël", "amount": 100000},
    ]
    ids = []
    for p in payloads:
        r = requests.post(f"{API}/hr/employees/{eid}/bonuses", headers=sh, json=p, timeout=10)
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])

    # Filter by month
    r = requests.get(f"{API}/hr/employees/{eid}/bonuses?month={month}", headers=sh, timeout=10)
    assert r.status_code == 200
    feb = r.json()
    assert len(feb) == 2
    labels = sorted(b["label"] for b in feb)
    assert labels == ["Prime de rendement", "Prime exceptionnelle"]

    # No filter → all 3
    r = requests.get(f"{API}/hr/employees/{eid}/bonuses", headers=sh, timeout=10)
    assert len(r.json()) == 3

    # Delete one
    r = requests.delete(f"{API}/hr/bonuses/{ids[0]}", headers=sh, timeout=10)
    assert r.status_code == 200

    # Confirm 1 left for Feb
    r = requests.get(f"{API}/hr/employees/{eid}/bonuses?month={month}", headers=sh, timeout=10)
    assert len(r.json()) == 1


# =====================================================================
# Payslip integration
# =====================================================================
def test_payslip_includes_allowances_and_bonuses(tenant):
    """Payslip must include allowances + bonuses, gross_with_gains must
    equal gross + total_allowances + total_bonuses, and net must reflect
    the new total minus deductions."""
    eid = tenant["emp"]["id"]
    sh = tenant["sh"]
    month = "2026-04"

    # Add 2 active allowances + 1 inactive (should be ignored)
    requests.post(f"{API}/hr/employees/{eid}/allowances", headers=sh,
                  json={"label": "Transport", "amount": 20000, "active": True}, timeout=10)
    requests.post(f"{API}/hr/employees/{eid}/allowances", headers=sh,
                  json={"label": "Logement", "amount": 50000, "active": True}, timeout=10)
    requests.post(f"{API}/hr/employees/{eid}/allowances", headers=sh,
                  json={"label": "Désactivée", "amount": 99999, "active": False}, timeout=10)
    # Add 2 bonuses for the target month + 1 for another month (must be ignored)
    requests.post(f"{API}/hr/employees/{eid}/bonuses", headers=sh,
                  json={"month": month, "label": "Rendement", "amount": 30000}, timeout=10)
    requests.post(f"{API}/hr/employees/{eid}/bonuses", headers=sh,
                  json={"month": month, "label": "Performance", "amount": 10000}, timeout=10)
    requests.post(f"{API}/hr/employees/{eid}/bonuses", headers=sh,
                  json={"month": "2026-05", "label": "Ne doit pas compter", "amount": 999999}, timeout=10)

    r = requests.get(f"{API}/hr/employees/{eid}/payslip?month={month}", headers=sh, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["allowances"]) == 2, "Inactive allowance must be excluded"
    assert data["total_allowances"] == 70000
    assert len(data["bonuses"]) == 2, "Other-month bonus must be excluded"
    assert data["total_bonuses"] == 40000
    assert data["gross_with_gains"] == round(data["gross"] + 70000 + 40000, 2)
    # Net: with no taxes/advances/late expenses/absences, net == gross_with_gains
    # (gross might be 0 if no timesheet, that's fine — we test the addition)
    expected_net = round(
        data["gross_with_gains"]
        - data["absence_deduction"]
        - data["total_taxes"]
        - data["advances_deduction"]
        - float(data.get("late_expenses_deduction") or 0),
        2,
    )
    assert data["net"] == expected_net


def test_payslip_no_allowances_no_bonuses_returns_zero_sums(tenant):
    """Backward compat — payslip without any allowance/bonus."""
    eid = tenant["emp"]["id"]
    sh = tenant["sh"]
    r = requests.get(f"{API}/hr/employees/{eid}/payslip?month=2026-06", headers=sh, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["allowances"] == []
    assert data["bonuses"] == []
    assert data["total_allowances"] == 0
    assert data["total_bonuses"] == 0
    assert data["gross_with_gains"] == data["gross"]
