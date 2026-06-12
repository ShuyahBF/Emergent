"""Iter43-fix6 (Jan 2026) — Tests for Invoice Payment Tracking feature.

Coverage:
- PUT /api/admin/invoices/from-interventions/{inv_id}
  - 404 if not found
  - 400 if no field provided
  - 400 if deposited_at malformed
  - 400 if due_days out of range
  - accept combo deposited_at + due_days persisted
  - clear_deposited_at -> None
  - clear_paid_at -> None
  - returns enriched invoice with payment_status & days_overdue
- GET /api/me/invoices/from-interventions
  - each item has payment_status & days_overdue
  - fresh invoice (no deposited_at) -> days_overdue=None, payment_status='unpaid'
  - deposited 35 days ago + due_days=30 -> days_overdue=5
  - paid_at set -> payment_status='paid', days_overdue=None
- GET /api/me/invoices/from-interventions/{inv_id}/pdf
  - PDF rendered OK with various states
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
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


@pytest.fixture()
def setup_env(db):
    suffix = uuid.uuid4().hex[:8]
    admin_id = f"iter43f6_adm_{suffix}"
    tA_id = f"iter43f6_tA_{suffix}"
    cli_id = f"iter43f6_cli_{suffix}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@s.com", "password_hash": "x",
         "role": "admin", "full_name": "Admin Iter43f6", "account_status": "active", "created_at": now},
        {"id": tA_id, "email": f"{tA_id}@s.com", "password_hash": "x", "role": "client",
         "company": "Tenant Iter43f6", "hourly_rate": 20000, "account_status": "active", "created_at": now},
        {"id": cli_id, "email": f"{cli_id}@s.com", "password_hash": "x", "role": "client",
         "parent_client_id": tA_id, "account_status": "active", "created_at": now},
    ])
    db.settings.update_one({"_id": "global"}, {"$set": {"default_intervention_hourly_rate_xof": 15000}}, upsert=True)
    yield {"admin": admin_id, "tA": tA_id, "cli": cli_id}
    db.users.delete_many({"id": {"$in": [admin_id, tA_id, cli_id]}})


def _mk_invoice(db, tenant_id: str) -> str:
    """Create one intervention and invoice via API, return inv_id."""
    iv = f"iter43f6_iv_{uuid.uuid4().hex[:10]}"
    db.interventions.insert_one({
        "id": iv, "client_id": tenant_id,
        "intervention_number": f"IV-{iv[-4:]}",
        "intervention_date": "2026-01-10T09:00:00+00:00",
        "title": "Iter43-fix6 test", "technician": "Tech",
        "duration_hours": 2.0, "status": "termine",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return iv


@pytest.fixture()
def cleanup(db):
    yield
    db.interventions.delete_many({"id": {"$regex": "^iter43f6_iv_"}})
    db.interventions_invoices.delete_many({"id": {"$regex": "^iter43f6_inv_"}})
    db.interventions_invoices.delete_many({"intervention_ids": {"$elemMatch": {"$regex": "^iter43f6_iv_"}}})


# ---------- PUT /admin/invoices/from-interventions/{id} ----------

def test_put_404_when_unknown(setup_env, cleanup):
    tok = _forge(setup_env["admin"], role="admin")
    r = requests.put(f"{API}/admin/invoices/from-interventions/does-not-exist",
                     headers={"Authorization": f"Bearer {tok}"},
                     json={"due_days": 30})
    assert r.status_code == 404, r.text


def test_put_400_when_no_change(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    r = requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                     headers={"Authorization": f"Bearer {tok}"}, json={})
    assert r.status_code == 400, r.text


def test_put_400_invalid_deposited_at(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    r = requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                     headers={"Authorization": f"Bearer {tok}"},
                     json={"deposited_at": "not-a-date"})
    assert r.status_code == 400, r.text


def test_put_400_due_days_out_of_range(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    r_neg = requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                        headers={"Authorization": f"Bearer {tok}"},
                        json={"due_days": -1})
    assert r_neg.status_code == 400, r_neg.text

    r_huge = requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"due_days": 1000})
    assert r_huge.status_code == 400, r_huge.text


def test_put_accepts_deposited_and_due_days_and_persists(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    dep_iso = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    r = requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                     headers={"Authorization": f"Bearer {tok}"},
                     json={"deposited_at": dep_iso, "due_days": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    inv = body["invoice"]
    assert inv["deposited_at"] == dep_iso
    assert inv["due_days"] == 30
    assert inv["payment_status"] == "unpaid"
    # 35 days ago - 30 due_days => 5 days overdue (allow tolerance 4-6)
    assert inv["days_overdue"] is not None
    assert 4 <= inv["days_overdue"] <= 6, f"days_overdue={inv['days_overdue']}"

    # Persisted
    doc = db.interventions_invoices.find_one({"id": inv_id})
    assert doc["deposited_at"] == dep_iso
    assert doc["due_days"] == 30


def test_put_clear_deposited(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    dep_iso = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                 headers={"Authorization": f"Bearer {tok}"},
                 json={"deposited_at": dep_iso})

    r = requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                     headers={"Authorization": f"Bearer {tok}"},
                     json={"clear_deposited_at": True})
    assert r.status_code == 200, r.text
    inv = r.json()["invoice"]
    assert inv.get("deposited_at") in (None, "")
    assert inv["payment_status"] == "unpaid"
    assert inv["days_overdue"] is None


def test_put_clear_paid(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    paid_iso = datetime.now(timezone.utc).isoformat()
    requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                 headers={"Authorization": f"Bearer {tok}"},
                 json={"paid_at": paid_iso})

    r = requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                     headers={"Authorization": f"Bearer {tok}"},
                     json={"clear_paid_at": True})
    assert r.status_code == 200, r.text
    inv = r.json()["invoice"]
    assert inv.get("paid_at") in (None, "")
    assert inv["payment_status"] == "unpaid"


def test_put_paid_sets_payment_status_paid(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    dep_iso = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    paid_iso = datetime.now(timezone.utc).isoformat()
    r = requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                     headers={"Authorization": f"Bearer {tok}"},
                     json={"deposited_at": dep_iso, "paid_at": paid_iso, "due_days": 30})
    assert r.status_code == 200
    inv = r.json()["invoice"]
    assert inv["payment_status"] == "paid"
    assert inv["days_overdue"] is None


# ---------- GET /me/invoices/from-interventions ----------

def test_get_list_includes_payment_fields_fresh_invoice(db, setup_env, cleanup):
    """Regression: freshly created invoice has payment_status='unpaid' and days_overdue=None."""
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    r = requests.get(f"{API}/me/invoices/from-interventions",
                     headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    items = [i for i in r.json() if i["id"] == inv_id]
    assert len(items) == 1
    item = items[0]
    assert "payment_status" in item
    assert "days_overdue" in item
    assert item["payment_status"] == "unpaid"
    assert item["days_overdue"] is None


def test_get_list_overdue_calculated(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    dep_iso = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                 headers={"Authorization": f"Bearer {tok}"},
                 json={"deposited_at": dep_iso, "due_days": 30})

    r = requests.get(f"{API}/me/invoices/from-interventions",
                     headers={"Authorization": f"Bearer {tok}"})
    item = next(i for i in r.json() if i["id"] == inv_id)
    assert item["payment_status"] == "unpaid"
    assert 4 <= item["days_overdue"] <= 6


# ---------- PDF ----------

def test_pdf_renders_with_deposited_and_paid(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    dep_iso = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    paid_iso = datetime.now(timezone.utc).isoformat()
    requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                 headers={"Authorization": f"Bearer {tok}"},
                 json={"deposited_at": dep_iso, "paid_at": paid_iso, "due_days": 30})

    r = requests.get(f"{API}/me/invoices/from-interventions/{inv_id}/pdf",
                     headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF"


def test_pdf_renders_overdue_state(db, setup_env, cleanup):
    iv = _mk_invoice(db, setup_env["tA"])
    tok = _forge(setup_env["admin"], role="admin")
    rc = requests.post(f"{API}/me/invoices/from-interventions",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"intervention_ids": [iv]})
    inv_id = rc.json()["invoices"][0]["id"]

    dep_iso = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    requests.put(f"{API}/admin/invoices/from-interventions/{inv_id}",
                 headers={"Authorization": f"Bearer {tok}"},
                 json={"deposited_at": dep_iso, "due_days": 30})

    r = requests.get(f"{API}/me/invoices/from-interventions/{inv_id}/pdf",
                     headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
