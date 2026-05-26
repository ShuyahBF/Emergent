"""Iter38b — GRH Phases 4+5+6 + Tenant country meta tests."""
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
    sup_id = f"hr2sup_{uuid.uuid4().hex[:6]}"
    cli_id = f"hr2cli_{uuid.uuid4().hex[:6]}"
    company = f"GRH2-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
         "full_name": "Boss", "company": company, "role": "superviseur",
         "account_status": "active", "created_at": now},
        {"id": cli_id, "email": f"{cli_id}@t.l", "password_hash": "x",
         "full_name": "Alice", "company": company, "parent_client_id": sup_id,
         "role": "client", "account_status": "active", "created_at": now},
    ])
    sh = {"Authorization": f"Bearer {_forge(sup_id)}"}
    # Create employee
    emp = requests.post(
        f"{API}/hr/employees", headers=sh,
        json={"user_id": cli_id, "base_salary": 160000, "pay_type": "monthly",
              "monthly_hours_baseline": 160, "currency": "XOF"},
        timeout=15,
    ).json()
    yield {"sup_id": sup_id, "cli_id": cli_id, "sh": sh, "emp": emp, "company": company}
    db.users.delete_many({"id": {"$in": [sup_id, cli_id]}})
    db.hr_employees.delete_many({"tenant_id": sup_id})
    db.hr_absences.delete_many({"tenant_id": sup_id})
    db.hr_advances.delete_many({"tenant_id": sup_id})
    db.hr_taxes.delete_many({"tenant_id": sup_id})
    db.hr_settings.delete_many({"tenant_id": sup_id})
    db.tenant_country.delete_many({"tenant_id": sup_id})
    db.access_logs.delete_many({"user_id": cli_id})


# ==================================================================
# Tenant Country Meta
# ==================================================================
def test_default_tenant_meta_is_burkina(tenant):
    r = requests.get(f"{API}/me/tenant-meta", headers=tenant["sh"], timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["country_code"] == "BF"
    assert data["dial_prefix"] == "+226"
    assert data["country_name"] == "Burkina Faso"
    assert data["phone_example"].startswith("+226")


def test_country_catalog_seeded_and_listable(tenant):
    r = requests.get(f"{API}/admin/countries", headers=tenant["sh"], timeout=10)
    assert r.status_code == 200
    items = r.json()
    codes = {c["code"] for c in items}
    assert "BF" in codes and "CI" in codes and "SN" in codes
    bf = next(c for c in items if c["code"] == "BF")
    assert bf["dial"] == "+226"


def test_admin_can_change_tenant_country_to_senegal(tenant):
    r = requests.patch(
        f"{API}/admin/tenant-country", headers=tenant["sh"],
        json={"country_code": "SN"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["country_code"] == "SN"
    assert data["dial_prefix"] == "+221"
    # Per-user view also reflects the change
    r2 = requests.get(f"{API}/me/tenant-meta", headers=tenant["sh"], timeout=10)
    assert r2.json()["dial_prefix"] == "+221"


def test_admin_can_add_and_delete_country(tenant):
    r = requests.post(
        f"{API}/admin/countries", headers=tenant["sh"],
        json={"code": "MA", "name": "Maroc", "dial": "+212", "example": "+212600000000"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    # Duplicate -> 409
    r2 = requests.post(
        f"{API}/admin/countries", headers=tenant["sh"],
        json={"code": "MA", "name": "Maroc", "dial": "+212"}, timeout=10,
    )
    assert r2.status_code == 409
    rd = requests.delete(f"{API}/admin/countries/MA", headers=tenant["sh"], timeout=10)
    assert rd.status_code == 200


def test_default_country_BF_cannot_be_deleted(tenant):
    rd = requests.delete(f"{API}/admin/countries/BF", headers=tenant["sh"], timeout=10)
    assert rd.status_code == 400


# ==================================================================
# Phase 4 — Absences
# ==================================================================
def test_create_list_update_delete_absence(tenant):
    payload = {
        "employee_id": tenant["emp"]["id"],
        "start_date": "2026-05-10",
        "end_date": "2026-05-10",
        "hours_count": 8,
        "abs_type": "maladie",
        "is_justified": True,
        "justification": "Certificat médical fourni",
    }
    c = requests.post(f"{API}/hr/absences", headers=tenant["sh"], json=payload, timeout=10)
    assert c.status_code == 200, c.text
    aid = c.json()["id"]
    assert c.json()["auto_detected"] is False
    # List
    lst = requests.get(f"{API}/hr/absences", headers=tenant["sh"], timeout=10).json()
    assert any(a["id"] == aid for a in lst)
    # By month filter
    lst2 = requests.get(f"{API}/hr/absences?month=2026-05", headers=tenant["sh"], timeout=10).json()
    assert any(a["id"] == aid for a in lst2)
    # Update
    u = requests.patch(
        f"{API}/hr/absences/{aid}", headers=tenant["sh"],
        json={"hours_count": 4, "is_justified": False}, timeout=10,
    )
    assert u.status_code == 200
    assert u.json()["hours_count"] == 4
    assert u.json()["is_justified"] is False
    # Delete
    d = requests.delete(f"{API}/hr/absences/{aid}", headers=tenant["sh"], timeout=10)
    assert d.status_code == 200


def test_absence_bad_dates_rejected(tenant):
    r = requests.post(
        f"{API}/hr/absences", headers=tenant["sh"],
        json={
            "employee_id": tenant["emp"]["id"],
            "start_date": "2026-05-15", "end_date": "2026-05-10",
            "hours_count": 8, "abs_type": "non_justifiee",
        },
        timeout=10,
    )
    assert r.status_code == 400


def test_absence_scan_proposes_business_days_missing_logs(tenant, db):
    # Insert one access_log entry on 2026-05-04 (Monday) only
    db.access_logs.insert_one({
        "id": f"al_{uuid.uuid4().hex[:6]}",
        "user_id": tenant["cli_id"],
        "user_email": f"{tenant['cli_id']}@t.l",
        "module": "x", "page": "/p",
        "created_at": "2026-05-04T09:00:00+00:00",
    })
    r = requests.post(
        f"{API}/hr/absences/scan?employee_id={tenant['emp']['id']}&month=2026-05",
        headers=tenant["sh"], timeout=15,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    sugg_dates = {s["date"] for s in out["suggestions"]}
    # 2026-05-04 is Monday — must NOT be in suggestions
    assert "2026-05-04" not in sugg_dates
    # 2026-05-05 (Tuesday) MUST be present
    assert "2026-05-05" in sugg_dates
    # 2026-05-09 (Saturday) — not business day, must NOT be present
    assert "2026-05-09" not in sugg_dates


# ==================================================================
# Phase 5 — Taxes
# ==================================================================
def test_replace_taxes_and_list(tenant):
    payload = {"taxes": [
        {"label": "IRPP", "calc_type": "percentage", "value": 10, "applies_to": "gross", "active": True, "sort_order": 0},
        {"label": "CNSS employé", "calc_type": "percentage", "value": 5.5, "applies_to": "gross", "active": True, "sort_order": 1},
        {"label": "Cotis. fixe", "calc_type": "fixed", "value": 1500, "applies_to": "gross", "active": True, "sort_order": 2},
    ]}
    r = requests.put(f"{API}/hr/taxes", headers=tenant["sh"], json=payload, timeout=10)
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out) == 3
    lst = requests.get(f"{API}/hr/taxes", headers=tenant["sh"], timeout=10).json()
    assert len(lst) == 3
    # Replace again with fewer
    r2 = requests.put(f"{API}/hr/taxes", headers=tenant["sh"],
                      json={"taxes": [payload["taxes"][0]]}, timeout=10)
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_more_than_5_taxes_rejected(tenant):
    payload = {"taxes": [
        {"label": f"T{i}", "calc_type": "percentage", "value": 1, "applies_to": "gross", "active": True, "sort_order": i}
        for i in range(6)
    ]}
    r = requests.put(f"{API}/hr/taxes", headers=tenant["sh"], json=payload, timeout=10)
    assert r.status_code == 400


# ==================================================================
# Phase 5 — Advances
# ==================================================================
def test_create_list_repay_advance(tenant):
    c = requests.post(
        f"{API}/hr/advances", headers=tenant["sh"],
        json={
            "employee_id": tenant["emp"]["id"],
            "amount": 30000, "currency": "XOF",
            "motive": "Besoin santé", "auto_deduct": True,
        },
        timeout=10,
    )
    assert c.status_code == 200, c.text
    aid = c.json()["id"]
    assert c.json()["status"] == "pending"
    # Partial repay
    r1 = requests.post(
        f"{API}/hr/advances/{aid}/repay", headers=tenant["sh"],
        json={"repaid_amount": 10000, "note": "Cycle 1"}, timeout=10,
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "partial"
    # Full repay
    r2 = requests.post(
        f"{API}/hr/advances/{aid}/repay", headers=tenant["sh"],
        json={"repaid_amount": 20000}, timeout=10,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "repaid"
    # Delete
    rd = requests.delete(f"{API}/hr/advances/{aid}", headers=tenant["sh"], timeout=10)
    assert rd.status_code == 200


# ==================================================================
# Phase 6 — Payslip
# ==================================================================
def test_payslip_with_full_pipeline(tenant, db):
    # Set HR settings: threshold = 4h
    requests.patch(
        f"{API}/hr/settings", headers=tenant["sh"],
        json={
            "absence_threshold_hours": 4,
            "payslip_company_name": "ACME Burkina",
            "payslip_employer_id": "BF-EMP-123",
            "payslip_address": "Ouagadougou\nBurkina Faso",
            "payslip_legal_mentions": "Ce bulletin doit être conservé sans limite de durée.",
            "payslip_footer": "Établi le " + datetime.now(timezone.utc).date().isoformat(),
        },
        timeout=10,
    )
    # 2 taxes: 10% IRPP + 5% CNSS
    requests.put(
        f"{API}/hr/taxes", headers=tenant["sh"],
        json={"taxes": [
            {"label": "IRPP", "calc_type": "percentage", "value": 10, "applies_to": "gross", "active": True, "sort_order": 0},
            {"label": "CNSS", "calc_type": "percentage", "value": 5, "applies_to": "gross", "active": True, "sort_order": 1},
        ]},
        timeout=10,
    )
    # Inject 2 days of access_logs in 2026-05: 8h + 8h = 16h total
    db.access_logs.insert_many([
        {"id": f"al_{uuid.uuid4().hex[:6]}", "user_id": tenant["cli_id"],
         "user_email": f"{tenant['cli_id']}@t.l", "module": "x", "page": "/p",
         "created_at": "2026-05-04T08:00:00+00:00"},
        {"id": f"al_{uuid.uuid4().hex[:6]}", "user_id": tenant["cli_id"],
         "user_email": f"{tenant['cli_id']}@t.l", "module": "x", "page": "/p",
         "created_at": "2026-05-04T16:00:00+00:00"},
        {"id": f"al_{uuid.uuid4().hex[:6]}", "user_id": tenant["cli_id"],
         "user_email": f"{tenant['cli_id']}@t.l", "module": "x", "page": "/p",
         "created_at": "2026-05-05T09:00:00+00:00"},
        {"id": f"al_{uuid.uuid4().hex[:6]}", "user_id": tenant["cli_id"],
         "user_email": f"{tenant['cli_id']}@t.l", "module": "x", "page": "/p",
         "created_at": "2026-05-05T17:00:00+00:00"},
    ])
    # Absence: 12h unjustified
    requests.post(
        f"{API}/hr/absences", headers=tenant["sh"],
        json={"employee_id": tenant["emp"]["id"], "start_date": "2026-05-06",
              "end_date": "2026-05-06", "hours_count": 12,
              "abs_type": "non_justifiee", "is_justified": False},
        timeout=10,
    )
    # Advance: 5000 XOF auto-deduct, unpaid
    requests.post(
        f"{API}/hr/advances", headers=tenant["sh"],
        json={"employee_id": tenant["emp"]["id"], "amount": 5000,
              "currency": "XOF", "motive": "Test"},
        timeout=10,
    )
    # Compute payslip
    r = requests.get(
        f"{API}/hr/employees/{tenant['emp']['id']}/payslip?month=2026-05",
        headers=tenant["sh"], timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # 16h / 160h = 10% of 160000 = 16000 gross
    assert abs(data["gross"] - 16000.0) < 1
    # 12h unjustified - 4h threshold = 8h billable; hourly = 160000/160 = 1000 → 8000
    assert abs(data["absence_deduction"] - 8000.0) < 1
    # gross_after_absence = 16000 - 8000 = 8000
    assert abs(data["gross_after_absence"] - 8000.0) < 1
    # Taxes: 10% + 5% of 8000 = 800 + 400 = 1200
    assert abs(data["total_taxes"] - 1200.0) < 1
    # Advances deduction = 5000
    assert abs(data["advances_deduction"] - 5000.0) < 1
    # Net = 8000 - 1200 - 5000 = 1800
    assert abs(data["net"] - 1800.0) < 1
    # PDF check
    pdf = requests.get(
        f"{API}/hr/employees/{tenant['emp']['id']}/payslip.pdf?month=2026-05",
        headers=tenant["sh"], timeout=15,
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 1000


# ==================================================================
# Weekly presence (mini-graph)
# ==================================================================
def test_weekly_presence_top(tenant, db):
    # Insert access_logs in current week for the cli employee
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(hour=8, minute=0, second=0, microsecond=0)
    db.access_logs.insert_many([
        {"id": f"al_{uuid.uuid4().hex[:6]}", "user_id": tenant["cli_id"],
         "user_email": f"{tenant['cli_id']}@t.l", "module": "x", "page": "/p",
         "created_at": monday.isoformat()},
        {"id": f"al_{uuid.uuid4().hex[:6]}", "user_id": tenant["cli_id"],
         "user_email": f"{tenant['cli_id']}@t.l", "module": "x", "page": "/p",
         "created_at": (monday + timedelta(hours=6)).isoformat()},
    ])
    r = requests.get(f"{API}/hr/dashboard/weekly-presence", headers=tenant["sh"], timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["total_employees"] >= 1
    top = data["top"]
    assert any(t["employee_id"] == tenant["emp"]["id"] for t in top)
    target = next(t for t in top if t["employee_id"] == tenant["emp"]["id"])
    assert target["hours"] >= 5.5  # ~6 hours in one day


# ==================================================================
# HR Settings (threshold + payslip)
# ==================================================================
def test_hr_settings_round_trip(tenant):
    r = requests.patch(
        f"{API}/hr/settings", headers=tenant["sh"],
        json={"absence_threshold_hours": 8.0, "payslip_company_name": "Test SAS"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["absence_threshold_hours"] == 8.0
    assert data["payslip_company_name"] == "Test SAS"
    g = requests.get(f"{API}/hr/settings", headers=tenant["sh"], timeout=10).json()
    assert g["absence_threshold_hours"] == 8.0
