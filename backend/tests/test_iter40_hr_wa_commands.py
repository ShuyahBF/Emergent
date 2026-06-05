"""Iter40 — HR WhatsApp commands (Task 3).

Validates :
 - detect_hr_command() recognizes !absence YYYY-MM-DD and !avance MONTANT
 - try_handle_hr_wa_command() refused when user not registered
 - try_handle_hr_wa_command() creates absence + disables user account
 - try_handle_hr_wa_command() creates advance with pending_approval
 - approve_absence reactivates the user
 - reject_absence removes + reactivates the user
"""
from __future__ import annotations

import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient

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
def motor_db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def hr_context(db):
    """Tenant + admin + employee user + hr_employee row."""
    tid = f"hrwa_t_{uuid.uuid4().hex[:6]}"
    adm_id = f"hrwa_adm_{uuid.uuid4().hex[:6]}"
    emp_user_id = f"hrwa_u_{uuid.uuid4().hex[:6]}"
    emp_id = f"hrwa_emp_{uuid.uuid4().hex[:6]}"
    # All-digit phone (no hex letters) so the regex anchors match cleanly
    rand_digits = "".join(c for c in uuid.uuid4().hex if c.isdigit())
    while len(rand_digits) < 6:
        rand_digits += "".join(c for c in uuid.uuid4().hex if c.isdigit())
    test_phone = "22890" + rand_digits[:6]
    company = f"HRWA Co {uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": adm_id, "email": f"{adm_id}@t.l", "password_hash": "x",
        "role": "admin", "company": company, "account_status": "active",
        "phone": "+22899900000",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": emp_user_id, "email": f"{emp_user_id}@t.l", "password_hash": "x",
        "role": "client", "company": company, "parent_client_id": adm_id,
        "account_status": "active",
        "phone": "+" + test_phone,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.hr_employees.insert_one({
        "id": emp_id, "tenant_id": adm_id, "user_id": emp_user_id,
        "matricule": "EMP-001", "full_name": "Employé Test",
        "hourly_rate": 1500, "monthly_hours_baseline": 173.33,
        "pay_type": "hourly", "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {
        "tid": adm_id, "adm_id": adm_id, "adm_token": _forge(adm_id, "admin"),
        "emp_user_id": emp_user_id, "emp_id": emp_id, "phone": test_phone,
    }
    db.users.delete_one({"id": adm_id})
    db.users.delete_one({"id": emp_user_id})
    db.hr_employees.delete_one({"id": emp_id})
    db.hr_absences.delete_many({"employee_id": emp_id})
    db.hr_advances.delete_many({"employee_id": emp_id})


def test_detect_hr_command():
    from routes.liluvine_hr_wa import detect_hr_command
    assert detect_hr_command("!absence 2026-03-01 au 2026-03-03 maladie") == "absence"
    assert detect_hr_command("/absence 2026-04-15") == "absence"
    assert detect_hr_command("!avance 50000 mariage") == "advance"
    assert detect_hr_command("!avance 25000") == "advance"
    assert detect_hr_command("bonjour") is None
    assert detect_hr_command("!ticket truc") is None


def test_absence_unknown_phone(db, motor_db):
    from routes.liluvine_hr_wa import try_handle_hr_wa_command
    res = asyncio.run(try_handle_hr_wa_command(
        motor_db, from_phone="22899111222", message_text="!absence 2026-03-01",
    ))
    assert res is not None
    assert res["ok"] is False
    assert res["reason"] == "user_not_found"


def test_absence_creates_record_and_disables_user(db, motor_db, hr_context):
    from routes.liluvine_hr_wa import try_handle_hr_wa_command
    ctx = hr_context
    res = asyncio.run(try_handle_hr_wa_command(
        motor_db, from_phone=ctx["phone"],
        message_text="!absence 2026-04-10 au 2026-04-12 maladie palu",
    ))
    assert res["ok"] is True, res
    assert res["command"] == "absence"
    # Absence stored with pending_approval
    abs_doc = db.hr_absences.find_one({"id": res["id"]})
    assert abs_doc is not None
    assert abs_doc["status"] == "pending_approval"
    assert abs_doc["start_date"] == "2026-04-10"
    assert abs_doc["end_date"] == "2026-04-12"
    assert "palu" in abs_doc["justification"]
    # User account is disabled
    u = db.users.find_one({"id": ctx["emp_user_id"]})
    assert u["account_status"] == "inactive"
    assert u["wa_absence_request_id"] == res["id"]


def test_advance_creates_pending(db, motor_db, hr_context):
    from routes.liluvine_hr_wa import try_handle_hr_wa_command
    ctx = hr_context
    res = asyncio.run(try_handle_hr_wa_command(
        motor_db, from_phone=ctx["phone"],
        message_text="!avance 35000 dépenses imprévues",
    ))
    assert res["ok"] is True, res
    assert res["command"] == "advance"
    adv = db.hr_advances.find_one({"id": res["id"]})
    assert adv["status"] == "pending_approval"
    assert adv["amount"] == 35000.0
    assert "imprévues" in adv["motive"]


def test_advance_rejects_zero_amount(db, motor_db, hr_context):
    from routes.liluvine_hr_wa import try_handle_hr_wa_command
    ctx = hr_context
    res = asyncio.run(try_handle_hr_wa_command(
        motor_db, from_phone=ctx["phone"], message_text="!avance 0 test",
    ))
    assert res["ok"] is False
    assert "supérieur à 0" in res["user_reply"]


def test_approve_absence_reactivates_user(db, motor_db, hr_context):
    """Approve endpoint flips status + reactivates the user."""
    ctx = hr_context
    # Re-create one absence (the user is now inactive)
    from routes.liluvine_hr_wa import try_handle_hr_wa_command
    res = asyncio.run(try_handle_hr_wa_command(
        motor_db, from_phone=ctx["phone"],
        message_text="!absence 2026-05-01 au 2026-05-02 RDV médical",
    ))
    assert res["ok"]
    aid = res["id"]
    r = requests.post(
        f"{API}/hr/absences/{aid}/approve",
        headers={"Authorization": f"Bearer {ctx['adm_token']}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    # User is now active again
    u = db.users.find_one({"id": ctx["emp_user_id"]})
    assert u["account_status"] == "active"
    assert u.get("wa_absence_request_id") in (None, "")


def test_reject_absence_removes_and_reactivates(db, motor_db, hr_context):
    ctx = hr_context
    from routes.liluvine_hr_wa import try_handle_hr_wa_command
    res = asyncio.run(try_handle_hr_wa_command(
        motor_db, from_phone=ctx["phone"], message_text="!absence 2026-06-15",
    ))
    assert res["ok"]
    aid = res["id"]
    # User disabled
    assert db.users.find_one({"id": ctx["emp_user_id"]})["account_status"] == "inactive"
    r = requests.post(
        f"{API}/hr/absences/{aid}/reject",
        headers={"Authorization": f"Bearer {ctx['adm_token']}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("rejected") is True
    # Absence gone
    assert db.hr_absences.find_one({"id": aid}) is None
    # User active again
    assert db.users.find_one({"id": ctx["emp_user_id"]})["account_status"] == "active"
