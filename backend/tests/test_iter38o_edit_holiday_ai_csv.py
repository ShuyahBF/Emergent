"""Iter38o — Edit non-clôturée expense + Holidays exclude unjustified absences
+ AI feature gating + Catalog CSV export + pending_quotes_alerts."""
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
    admin_id = f"o_adm_{uuid.uuid4().hex[:6]}"
    cashier_id = f"o_csh_{uuid.uuid4().hex[:6]}"
    emp_user_id = f"o_emp_{uuid.uuid4().hex[:6]}"
    other_id = f"o_oth_{uuid.uuid4().hex[:6]}"
    company = f"O-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin O", "company": company, "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": cashier_id, "email": f"{cashier_id}@t.l", "password_hash": "x",
         "full_name": "Cashier O", "company": company, "role": "client",
         "can_cash": True, "tracked_user_id": admin_id, "parent_client_id": admin_id,
         "account_status": "active", "created_at": now},
        {"id": emp_user_id, "email": f"{emp_user_id}@t.l", "password_hash": "x",
         "full_name": "Employee O", "company": company, "role": "client",
         "tracked_user_id": admin_id, "parent_client_id": admin_id,
         "account_status": "active", "created_at": now},
        {"id": other_id, "email": f"{other_id}@t.l", "password_hash": "x",
         "full_name": "Outsider O", "company": f"OOTH-{uuid.uuid4().hex[:4]}",
         "role": "client", "account_status": "active", "created_at": now},
    ])
    yield {
        "admin_id": admin_id, "admin_token": _forge(admin_id, "admin"),
        "cashier_id": cashier_id, "cashier_token": _forge(cashier_id, "client"),
        "emp_id": emp_user_id, "emp_token": _forge(emp_user_id, "client"),
        "other_token": _forge(other_id, "client"),
        "company": company,
    }
    db.users.delete_many({"id": {"$in": [admin_id, cashier_id, emp_user_id, other_id]}})
    db.hr_employees.delete_many({"tenant_id": admin_id})
    db.hr_holidays.delete_many({"tenant_id": admin_id})
    db.hr_absences.delete_many({"tenant_id": admin_id})
    db.cashier_expenses.delete_many({"tenant_id": admin_id})
    db.catalog_events.delete_many({"tenant_id": admin_id})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ========================================================================
# A) Edit non-clôturée expense (creator can, locked when justified)
# ========================================================================
def test_creator_can_edit_unjustified(tenant):
    r = requests.post(f"{API}/cashier/expenses", headers=_h(tenant["cashier_token"]),
        json={"amount": 1000, "method": "cash", "motif": "Petit achat"})
    eid = r.json()["id"]
    # Cashier (= creator) edits motif AND amount
    r = requests.patch(f"{API}/cashier/expenses/{eid}", headers=_h(tenant["cashier_token"]),
        json={"motif": "Achat corrigé", "amount": 1200})
    assert r.status_code == 200, r.text
    assert r.json()["motif"] == "Achat corrigé"
    assert r.json()["amount"] == 1200


def test_non_creator_cannot_edit(tenant):
    r = requests.post(f"{API}/cashier/expenses", headers=_h(tenant["cashier_token"]),
        json={"amount": 1000, "method": "cash", "motif": "Achat"})
    eid = r.json()["id"]
    # Employee (not creator) tries to edit
    r = requests.patch(f"{API}/cashier/expenses/{eid}", headers=_h(tenant["emp_token"]),
        json={"amount": 2000})
    assert r.status_code == 403


def test_attributed_employee_can_edit(tenant, db):
    """Employee on whom the expense is attributed can edit while not justified."""
    eid_emp = f"emp_{uuid.uuid4().hex[:8]}"
    db.hr_employees.insert_one({
        "id": eid_emp, "tenant_id": tenant["admin_id"],
        "user_id": tenant["emp_id"], "name_snapshot": "Employee O",
        "email_snapshot": f"{tenant['emp_id']}@t.l",
        "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Admin attributes an expense to employee
    r = requests.post(f"{API}/cashier/expenses", headers=_h(tenant["admin_token"]),
        json={"amount": 5000, "method": "cash", "motif": "Mission",
              "attribution_type": "employee", "employee_id": eid_emp})
    exid = r.json()["id"]
    # The attributed employee adjusts the amount (still unjustified)
    r = requests.patch(f"{API}/cashier/expenses/{exid}", headers=_h(tenant["emp_token"]),
        json={"amount": 5500})
    assert r.status_code == 200, r.text


def test_justified_expense_locked_for_non_admin(tenant):
    r = requests.post(f"{API}/cashier/expenses", headers=_h(tenant["cashier_token"]),
        json={"amount": 1000, "method": "cash", "motif": "Achat"})
    eid = r.json()["id"]
    # Justify
    requests.post(f"{API}/cashier/expenses/{eid}/justify",
        headers=_h(tenant["cashier_token"]),
        json={"justification_text": "Reçu joint"})
    # Cashier (creator) can no longer edit
    r = requests.patch(f"{API}/cashier/expenses/{eid}", headers=_h(tenant["cashier_token"]),
        json={"amount": 9999})
    assert r.status_code == 403
    # Admin still can (force)
    r = requests.patch(f"{API}/cashier/expenses/{eid}", headers=_h(tenant["admin_token"]),
        json={"amount": 9999})
    assert r.status_code == 200


# ========================================================================
# B) Holidays exclude unjustified absences from deduction
# ========================================================================
def test_holiday_absence_not_deducted(tenant, db):
    """Setup an employee + a holiday + an absence on that holiday →
    payslip endpoint should report holiday hours separately and NOT deduct."""
    eid_emp = f"emp_{uuid.uuid4().hex[:8]}"
    db.hr_employees.insert_one({
        "id": eid_emp, "tenant_id": tenant["admin_id"],
        "user_id": tenant["emp_id"], "name_snapshot": "Employee O",
        "email_snapshot": f"{tenant['emp_id']}@t.l",
        "pay_type": "monthly", "base_salary": 200000, "currency": "XOF",
        "monthly_hours_baseline": 160,
        "absence_threshold_hours_override": 0,
        "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Insert a paid holiday on 2026-05-01
    db.hr_holidays.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tenant["admin_id"],
        "date": "2026-05-01", "label": "Fête du Travail",
        "holiday_type": "national", "is_paid": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Insert a 8h unjustified absence on the holiday date
    db.hr_absences.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tenant["admin_id"],
        "employee_id": eid_emp,
        "start_date": "2026-05-01", "end_date": "2026-05-01",
        "hours_count": 8.0, "is_justified": False,
        "reason": "Test",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Insert a second 4h unjustified absence on a normal day
    db.hr_absences.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tenant["admin_id"],
        "employee_id": eid_emp,
        "start_date": "2026-05-15", "end_date": "2026-05-15",
        "hours_count": 4.0, "is_justified": False,
        "reason": "Test",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Fetch payslip
    r = requests.get(
        f"{API}/hr/employees/{eid_emp}/payslip?month=2026-05",
        headers=_h(tenant["admin_token"]),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    abs_h = data["absence_hours"]
    # The 8h holiday absence is in the `holiday` bucket, not `unjustified`
    assert abs_h["holiday"] == 8.0
    assert abs_h["unjustified"] == 4.0
    assert abs_h["total"] == 12.0


# ========================================================================
# C) AI feature gating
# ========================================================================
def test_ai_image_gen_blocked_when_feature_off(tenant, db):
    # Ensure feature is OFF on the parent (admin) doc
    db.users.update_one(
        {"id": tenant["admin_id"]},
        {"$set": {"features.ai_image_gen": False, "features.ai_video_gen": False}},
    )
    r = requests.post(f"{API}/me/ai/generate-image",
        headers=_h(tenant["emp_token"]),
        json={"prompt": "A flower", "icon_mode": False, "aspect": "square"})
    assert r.status_code == 403, r.text
    assert "désactivée" in r.json()["detail"].lower() or "disabled" in r.json()["detail"].lower()


def test_ai_video_gen_blocked_when_feature_off(tenant, db):
    db.users.update_one(
        {"id": tenant["admin_id"]},
        {"$set": {"features.ai_video_gen": False}},
    )
    r = requests.post(f"{API}/me/ai/generate-video",
        headers=_h(tenant["emp_token"]),
        json={"prompt": "Sunset over Ouaga", "duration": 4})
    assert r.status_code == 403


def test_ai_admin_bypasses_feature_check(tenant, db):
    """Admin can call AI generation even when the feature is OFF."""
    db.users.update_one(
        {"id": tenant["admin_id"]},
        {"$set": {"features.ai_image_gen": False}},
    )
    # Admin call passes the gate (will fail at LLM step if no key, but we just
    # check the 403 isn't raised — anything else means the gate let it through).
    r = requests.post(f"{API}/me/ai/generate-image",
        headers=_h(tenant["admin_token"]),
        json={"prompt": "test", "icon_mode": False, "aspect": "square"})
    assert r.status_code != 403


# ========================================================================
# D) Catalog CSV export + pending_quotes_alerts
# ========================================================================
def test_catalog_csv_export(tenant):
    requests.post(f"{API}/public/catalog/track",
        json={"event_type": "catalog_view"})
    r = requests.get(f"{API}/me/catalog/export.csv?days=7",
        headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    body = r.text
    assert "date;event_type" in body.split("\n", 1)[0]


def test_pending_quotes_alert_above_threshold(tenant, db):
    pid = f"prod_{uuid.uuid4().hex[:8]}"
    db.products.insert_one({
        "id": pid, "tenant_id": tenant["admin_id"], "client_id": tenant["admin_id"],
        "name": "Laptop Demo", "sku": "DEMO-001",
        "is_public": True, "active": True, "deleted_at": None,
    })
    # 11 untreated quote clicks → above threshold
    for _ in range(11):
        requests.post(f"{API}/public/catalog/track",
            json={"event_type": "product_quote_click", "product_id": pid,
                  "product_name": "Laptop Demo"})
    r = requests.get(f"{API}/me/catalog/stats?days=7",
        headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    alerts = r.json()["pending_quotes_alerts"]
    pids = [a["product_id"] for a in alerts]
    assert pid in pids
    # Mark treated → alert disappears
    r = requests.post(f"{API}/me/catalog/quotes/mark-treated",
        headers=_h(tenant["admin_token"]),
        json={"product_id": pid})
    assert r.status_code == 200
    assert r.json()["marked"] >= 11
    r = requests.get(f"{API}/me/catalog/stats?days=7",
        headers=_h(tenant["admin_token"]))
    alerts = r.json()["pending_quotes_alerts"]
    pids2 = [a["product_id"] for a in alerts]
    assert pid not in pids2
    db.products.delete_one({"id": pid})
