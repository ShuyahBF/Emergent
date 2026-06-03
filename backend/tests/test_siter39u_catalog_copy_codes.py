"""0-3 (2026-02) — GRH Pay Catalog + Copy primes/indemnités between agents +
auto-generated codes (IND-NNNN / PRM-NNNN / CAT-NNNN).
"""
from __future__ import annotations

import os
import re
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
            "sub": uid, "role": role,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        },
        JWT_SECRET, algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def tenant_two_emps(db):
    """Create tenant + 2 employees for copy tests."""
    sup_id = f"hr0sup_{uuid.uuid4().hex[:6]}"
    cli1 = f"hr0cli1_{uuid.uuid4().hex[:6]}"
    cli2 = f"hr0cli2_{uuid.uuid4().hex[:6]}"
    company = f"GRH0-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
         "full_name": "Boss 0-3", "company": company, "role": "superviseur",
         "account_status": "active", "created_at": now},
        {"id": cli1, "email": f"{cli1}@t.l", "password_hash": "x",
         "full_name": "Alice", "company": company, "parent_client_id": sup_id,
         "role": "client", "account_status": "active", "created_at": now},
        {"id": cli2, "email": f"{cli2}@t.l", "password_hash": "x",
         "full_name": "Bob", "company": company, "parent_client_id": sup_id,
         "role": "client", "account_status": "active", "created_at": now},
    ])
    sh = {"Authorization": f"Bearer {_forge(sup_id)}"}
    e1 = requests.post(f"{API}/hr/employees", headers=sh,
        json={"user_id": cli1, "base_salary": 200000, "pay_type": "monthly",
              "monthly_hours_baseline": 160, "currency": "XOF"}, timeout=15).json()
    e2 = requests.post(f"{API}/hr/employees", headers=sh,
        json={"user_id": cli2, "base_salary": 250000, "pay_type": "monthly",
              "monthly_hours_baseline": 160, "currency": "XOF"}, timeout=15).json()
    yield {"sup_id": sup_id, "sh": sh, "e1": e1, "e2": e2, "company": company}
    db.users.delete_many({"id": {"$in": [sup_id, cli1, cli2]}})
    for coll in ["hr_employees", "hr_allowances", "hr_bonuses", "hr_pay_catalog"]:
        db[coll].delete_many({"tenant_id": sup_id})


# =====================================================================
# Auto codes — IND-NNNN / PRM-NNNN
# =====================================================================
def test_auto_code_on_allowance_creation(tenant_two_emps):
    eid = tenant_two_emps["e1"]["id"]
    sh = tenant_two_emps["sh"]
    r1 = requests.post(f"{API}/hr/employees/{eid}/allowances", headers=sh,
        json={"label": "Transport", "amount": 10000}, timeout=10)
    r2 = requests.post(f"{API}/hr/employees/{eid}/allowances", headers=sh,
        json={"label": "Logement", "amount": 30000}, timeout=10)
    assert r1.status_code == 200 and r2.status_code == 200
    c1, c2 = r1.json()["code"], r2.json()["code"]
    assert re.match(r"^IND-\d{4}$", c1), f"Expected IND-NNNN, got {c1}"
    assert re.match(r"^IND-\d{4}$", c2), f"Expected IND-NNNN, got {c2}"
    # Codes must increment
    n1 = int(c1.split("-")[1])
    n2 = int(c2.split("-")[1])
    assert n2 == n1 + 1


def test_auto_code_on_bonus_creation(tenant_two_emps):
    eid = tenant_two_emps["e1"]["id"]
    sh = tenant_two_emps["sh"]
    r = requests.post(f"{API}/hr/employees/{eid}/bonuses", headers=sh,
        json={"month": "2026-03", "label": "Rendement", "amount": 25000}, timeout=10)
    assert r.status_code == 200
    assert re.match(r"^PRM-\d{4}$", r.json()["code"])


# =====================================================================
# Pay catalog — CRUD
# =====================================================================
def test_pay_catalog_crud_full(tenant_two_emps):
    sh = tenant_two_emps["sh"]
    # Empty
    r = requests.get(f"{API}/hr/pay-catalog", headers=sh, timeout=10)
    assert r.status_code == 200 and r.json() == []
    # Create allowance template
    r = requests.post(f"{API}/hr/pay-catalog", headers=sh, json={
        "kind": "allowance", "label": "Indemnité Carburant",
        "default_amount": 15000, "currency": "XOF", "description": "5 000 FCFA / semaine"}, timeout=10)
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["code"].startswith("CAT-")
    assert item["kind"] == "allowance"
    cid = item["id"]
    # Create bonus template
    r2 = requests.post(f"{API}/hr/pay-catalog", headers=sh, json={
        "kind": "bonus", "label": "Prime de rendement Q1",
        "default_amount": 50000, "currency": "XOF"}, timeout=10)
    assert r2.status_code == 200
    assert r2.json()["code"].startswith("PRMC-")
    # Filter by kind
    r = requests.get(f"{API}/hr/pay-catalog?kind=allowance", headers=sh, timeout=10)
    assert len(r.json()) == 1
    r = requests.get(f"{API}/hr/pay-catalog?kind=bonus", headers=sh, timeout=10)
    assert len(r.json()) == 1
    # Patch
    r = requests.patch(f"{API}/hr/pay-catalog/{cid}", headers=sh,
        json={"default_amount": 20000, "label": "Indemnité Carburant +"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["default_amount"] == 20000
    # Delete
    r = requests.delete(f"{API}/hr/pay-catalog/{cid}", headers=sh, timeout=10)
    assert r.status_code == 200
    r = requests.get(f"{API}/hr/pay-catalog?kind=allowance", headers=sh, timeout=10)
    assert r.json() == []


def test_apply_catalog_template_creates_allowance(tenant_two_emps):
    sh = tenant_two_emps["sh"]
    eid = tenant_two_emps["e2"]["id"]
    # Create allowance template
    r = requests.post(f"{API}/hr/pay-catalog", headers=sh, json={
        "kind": "allowance", "label": "Indemnité Repas",
        "default_amount": 12000, "currency": "XOF"}, timeout=10)
    cid = r.json()["id"]
    # Apply with default amount
    r = requests.post(f"{API}/hr/employees/{eid}/apply-catalog/{cid}", headers=sh, timeout=10)
    assert r.status_code == 200, r.text
    al = r.json()
    assert al["amount"] == 12000
    assert al["catalog_id"] == cid
    assert al["code"].startswith("IND-")
    # Apply with overridden amount
    r = requests.post(
        f"{API}/hr/employees/{eid}/apply-catalog/{cid}", headers=sh,
        data={"amount": "5000"}, timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["amount"] == 5000


def test_apply_catalog_bonus_requires_month(tenant_two_emps):
    sh = tenant_two_emps["sh"]
    eid = tenant_two_emps["e2"]["id"]
    r = requests.post(f"{API}/hr/pay-catalog", headers=sh, json={
        "kind": "bonus", "label": "Prime Q1", "default_amount": 30000}, timeout=10)
    cid = r.json()["id"]
    # Without month → 400
    r = requests.post(f"{API}/hr/employees/{eid}/apply-catalog/{cid}", headers=sh, timeout=10)
    assert r.status_code == 400
    # With month → 200
    r = requests.post(
        f"{API}/hr/employees/{eid}/apply-catalog/{cid}", headers=sh,
        data={"bonus_month": "2026-04"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json()["month"] == "2026-04"


# =====================================================================
# Copy primes/indemnités between employees
# =====================================================================
def test_copy_allowances_from_one_employee_to_another(tenant_two_emps):
    sh = tenant_two_emps["sh"]
    e1, e2 = tenant_two_emps["e1"]["id"], tenant_two_emps["e2"]["id"]
    # Seed 3 allowances on e1 (2 active, 1 inactive)
    for label, amt, active in [
        ("Transport", 20000, True),
        ("Logement", 50000, True),
        ("Désactivée", 99999, False),
    ]:
        requests.post(f"{API}/hr/employees/{e1}/allowances", headers=sh,
            json={"label": label, "amount": amt, "active": active}, timeout=10)
    # Copy
    r = requests.post(f"{API}/hr/employees/{e1}/copy-pay-items", headers=sh,
        json={"target_employee_id": e2, "include_allowances": True, "include_bonuses": False}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["copied_allowances"] == 2  # inactive excluded
    assert d["copied_bonuses"] == 0
    # Verify target has 2 allowances
    r = requests.get(f"{API}/hr/employees/{e2}/allowances", headers=sh, timeout=10)
    items = r.json()
    assert len(items) == 2
    labels = sorted(it["label"] for it in items)
    assert labels == ["Logement", "Transport"]
    # Verify copied_from_employee_id is set on each
    for it in items:
        assert it.get("copied_from_employee_id") == e1


def test_copy_bonuses_for_specific_month(tenant_two_emps):
    sh = tenant_two_emps["sh"]
    e1, e2 = tenant_two_emps["e1"]["id"], tenant_two_emps["e2"]["id"]
    # Seed 2 bonuses on e1 for 2026-05 + 1 for 2026-06
    for month, label, amt in [
        ("2026-05", "Rendement", 40000),
        ("2026-05", "Performance", 10000),
        ("2026-06", "Ne pas copier", 99999),
    ]:
        requests.post(f"{API}/hr/employees/{e1}/bonuses", headers=sh,
            json={"month": month, "label": label, "amount": amt}, timeout=10)
    # Copy bonuses for 2026-05
    r = requests.post(f"{API}/hr/employees/{e1}/copy-pay-items", headers=sh,
        json={"target_employee_id": e2, "include_allowances": False,
              "include_bonuses": True, "bonus_month": "2026-05"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["copied_bonuses"] == 2
    r = requests.get(f"{API}/hr/employees/{e2}/bonuses?month=2026-05", headers=sh, timeout=10)
    assert len(r.json()) == 2


def test_copy_rejects_same_employee(tenant_two_emps):
    sh = tenant_two_emps["sh"]
    e1 = tenant_two_emps["e1"]["id"]
    r = requests.post(f"{API}/hr/employees/{e1}/copy-pay-items", headers=sh,
        json={"target_employee_id": e1}, timeout=10)
    assert r.status_code == 400


def test_copy_404_when_target_unknown(tenant_two_emps):
    sh = tenant_two_emps["sh"]
    e1 = tenant_two_emps["e1"]["id"]
    r = requests.post(f"{API}/hr/employees/{e1}/copy-pay-items", headers=sh,
        json={"target_employee_id": "DOES_NOT_EXIST"}, timeout=10)
    assert r.status_code == 404
