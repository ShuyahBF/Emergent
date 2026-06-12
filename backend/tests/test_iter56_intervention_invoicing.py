"""Iter56 (Jan 2026) — Tests for Intervention Invoicing feature.

Coverage:
- POST /api/me/invoices/from-interventions
  - 403 for role=client
  - 400 for empty list
  - 409 for all-already-invoiced
  - groups by tenant => 1 invoice per tenant
  - invoice_number auto-incremented INV-YYYY-NNNNN
  - lines, total_xof, currency=XOF, status=draft
  - marks each intervention invoiced=True with invoice_id & invoice_number
  - hourly_rate = tenant.hourly_rate fallback global default
- GET /api/me/invoices/from-interventions
  - admin sees all
  - client sees only own tenant
- GET /api/me/invoices/from-interventions/{inv_id}/pdf
  - admin OK (application/pdf)
  - 404 if missing
  - 403 if other-tenant client
- PUT /api/admin/interventions/{int_id}
  - updates fields
  - returns 409 if intervention invoiced
- POST /api/admin/interventions/{int_id}/unlock-invoice
  - removes invoiced/invoice_id/invoice_number
  - 404 if not found
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
def tenants(db):
    """Create 2 tenant clients and an admin user."""
    suffix = uuid.uuid4().hex[:8]
    admin_id = f"iter56_adm_{suffix}"
    tA_id = f"iter56_tA_{suffix}"
    tB_id = f"iter56_tB_{suffix}"
    cli_id = f"iter56_cli_{suffix}"  # client member of tA
    now = datetime.now(timezone.utc).isoformat()

    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@s.com", "password_hash": "x",
         "role": "admin", "full_name": "Admin Iter56", "account_status": "active", "created_at": now},
        {"id": tA_id, "email": f"{tA_id}@s.com", "password_hash": "x", "role": "client",
         "company": "Tenant A", "hourly_rate": 25000, "account_status": "active", "created_at": now},
        {"id": tB_id, "email": f"{tB_id}@s.com", "password_hash": "x", "role": "client",
         "company": "Tenant B", "account_status": "active", "created_at": now},
        {"id": cli_id, "email": f"{cli_id}@s.com", "password_hash": "x", "role": "client",
         "parent_client_id": tA_id, "account_status": "active", "created_at": now},
    ])
    # Global fallback set to 15000
    db.settings.update_one({"_id": "global"},
                           {"$set": {"default_intervention_hourly_rate_xof": 15000}}, upsert=True)
    yield {"admin": admin_id, "tA": tA_id, "tB": tB_id, "cli": cli_id}
    db.users.delete_many({"id": {"$in": [admin_id, tA_id, tB_id, cli_id]}})


def _mk_intervention(db, client_id: str, duration_hours: float = 2.0, title: str = "Intervention test"):
    iid = f"iter56_iv_{uuid.uuid4().hex[:10]}"
    db.interventions.insert_one({
        "id": iid,
        "client_id": client_id,
        "intervention_number": f"IV-{iid[-4:]}",
        "intervention_date": "2026-01-10T09:00:00+00:00",
        "title": title,
        "technician": "Tech Iter56",
        "duration_hours": duration_hours,
        "status": "termine",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return iid


@pytest.fixture()
def cleanup(db):
    yield
    db.interventions.delete_many({"id": {"$regex": "^iter56_iv_"}})
    db.interventions_invoices.delete_many({"intervention_ids": {"$elemMatch": {"$regex": "^iter56_iv_"}}})


# ---------- POST /me/invoices/from-interventions ----------

def test_post_invoice_client_role_forbidden(tenants, cleanup):
    tok = _forge(tenants["cli"], role="client")
    r = requests.post(f"{API}/me/invoices/from-interventions",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"intervention_ids": ["x"]})
    assert r.status_code == 403, r.text


def test_post_invoice_empty_list_400(tenants, cleanup):
    tok = _forge(tenants["admin"], role="admin")
    r = requests.post(f"{API}/me/invoices/from-interventions",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"intervention_ids": []})
    assert r.status_code == 400, r.text


def test_post_invoice_all_already_invoiced_409(db, tenants, cleanup):
    iv = _mk_intervention(db, tenants["tA"])
    db.interventions.update_one({"id": iv}, {"$set": {"invoiced": True}})
    tok = _forge(tenants["admin"], role="admin")
    r = requests.post(f"{API}/me/invoices/from-interventions",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"intervention_ids": [iv]})
    assert r.status_code == 409, r.text


def test_post_invoice_groups_by_tenant_and_marks(db, tenants, cleanup):
    """2 interventions tA + 1 tB => 2 invoices, marks interventions, uses tenant rate."""
    iv1 = _mk_intervention(db, tenants["tA"], duration_hours=2.0)
    iv2 = _mk_intervention(db, tenants["tA"], duration_hours=1.5)
    iv3 = _mk_intervention(db, tenants["tB"], duration_hours=3.0)
    tok = _forge(tenants["admin"], role="admin")
    r = requests.post(f"{API}/me/invoices/from-interventions",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"intervention_ids": [iv1, iv2, iv3]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 2
    by_tenant = {inv["tenant_id"]: inv for inv in data["invoices"]}
    assert tenants["tA"] in by_tenant and tenants["tB"] in by_tenant

    invA = by_tenant[tenants["tA"]]
    # Tenant A rate is 25000 → (2.0+1.5)*25000 = 87500
    assert invA["currency"] == "XOF"
    assert invA["status"] == "draft"
    assert invA["total_xof"] == 87500
    assert invA["hourly_rate_xof"] == 25000
    assert len(invA["lines"]) == 2
    assert invA["invoice_number"].startswith("INV-")
    parts = invA["invoice_number"].split("-")
    assert len(parts) == 3 and len(parts[2]) == 5  # NNNNN

    invB = by_tenant[tenants["tB"]]
    # Tenant B no hourly_rate → global 15000 → 3.0*15000 = 45000
    assert invB["total_xof"] == 45000
    assert invB["hourly_rate_xof"] == 15000

    # Interventions marked
    for iv in [iv1, iv2, iv3]:
        d = db.interventions.find_one({"id": iv})
        assert d.get("invoiced") is True
        assert d.get("invoice_number", "").startswith("INV-")
        assert d.get("invoice_id")


# ---------- GET list ----------

def test_get_list_admin_sees_all_and_client_only_own(db, tenants, cleanup):
    iv1 = _mk_intervention(db, tenants["tA"])
    iv2 = _mk_intervention(db, tenants["tB"])
    tok_admin = _forge(tenants["admin"], role="admin")
    requests.post(f"{API}/me/invoices/from-interventions",
                  headers={"Authorization": f"Bearer {tok_admin}"},
                  json={"intervention_ids": [iv1, iv2]})
    # Admin sees both
    r = requests.get(f"{API}/me/invoices/from-interventions",
                     headers={"Authorization": f"Bearer {tok_admin}"})
    assert r.status_code == 200
    tenants_seen = {inv["tenant_id"] for inv in r.json()}
    assert tenants["tA"] in tenants_seen and tenants["tB"] in tenants_seen

    # Client of tA sees only tA
    tok_cli = _forge(tenants["cli"], role="client")
    r2 = requests.get(f"{API}/me/invoices/from-interventions",
                      headers={"Authorization": f"Bearer {tok_cli}"})
    assert r2.status_code == 200
    for inv in r2.json():
        assert inv["tenant_id"] == tenants["tA"]


# ---------- GET PDF ----------

def test_get_pdf_admin_and_404_and_403(db, tenants, cleanup):
    iv = _mk_intervention(db, tenants["tA"])
    tok_admin = _forge(tenants["admin"], role="admin")
    r = requests.post(f"{API}/me/invoices/from-interventions",
                      headers={"Authorization": f"Bearer {tok_admin}"},
                      json={"intervention_ids": [iv]})
    inv_id = r.json()["invoices"][0]["id"]

    # admin gets PDF
    r_pdf = requests.get(f"{API}/me/invoices/from-interventions/{inv_id}/pdf",
                         headers={"Authorization": f"Bearer {tok_admin}"})
    assert r_pdf.status_code == 200
    assert r_pdf.headers.get("content-type", "").startswith("application/pdf")
    assert r_pdf.content[:4] == b"%PDF"

    # 404 if missing
    r_404 = requests.get(f"{API}/me/invoices/from-interventions/nonexistent-id/pdf",
                        headers={"Authorization": f"Bearer {tok_admin}"})
    assert r_404.status_code == 404

    # 403 for other tenant client
    other_id = f"iter56_other_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({"id": other_id, "email": f"{other_id}@s.com", "password_hash": "x",
                         "role": "client", "parent_client_id": tenants["tB"],
                         "account_status": "active",
                         "created_at": datetime.now(timezone.utc).isoformat()})
    try:
        tok_other = _forge(other_id, role="client")
        r_403 = requests.get(f"{API}/me/invoices/from-interventions/{inv_id}/pdf",
                             headers={"Authorization": f"Bearer {tok_other}"})
        assert r_403.status_code == 403
    finally:
        db.users.delete_one({"id": other_id})


# ---------- PUT /admin/interventions/{id} ----------

def test_admin_update_intervention_ok(db, tenants, cleanup):
    iv = _mk_intervention(db, tenants["tA"], title="Original")
    tok = _forge(tenants["admin"], role="admin")
    r = requests.put(f"{API}/admin/interventions/{iv}",
                     headers={"Authorization": f"Bearer {tok}"},
                     json={"title": "Modifié", "duration_hours": 4.5})
    assert r.status_code == 200, r.text
    d = db.interventions.find_one({"id": iv})
    assert d["title"] == "Modifié"
    assert d["duration_hours"] == 4.5


def test_admin_update_intervention_invoiced_returns_409(db, tenants, cleanup):
    iv = _mk_intervention(db, tenants["tA"])
    db.interventions.update_one({"id": iv}, {"$set": {"invoiced": True, "invoice_number": "INV-2026-99999"}})
    tok = _forge(tenants["admin"], role="admin")
    r = requests.put(f"{API}/admin/interventions/{iv}",
                     headers={"Authorization": f"Bearer {tok}"},
                     json={"title": "should fail"})
    assert r.status_code == 409, r.text


# ---------- POST /admin/interventions/{id}/unlock-invoice ----------

def test_admin_unlock_intervention(db, tenants, cleanup):
    iv = _mk_intervention(db, tenants["tA"])
    db.interventions.update_one({"id": iv}, {"$set": {
        "invoiced": True, "invoice_id": "inv-xxx", "invoice_number": "INV-2026-12345"}})
    tok = _forge(tenants["admin"], role="admin")
    r = requests.post(f"{API}/admin/interventions/{iv}/unlock-invoice",
                      headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    d = db.interventions.find_one({"id": iv})
    assert "invoiced" not in d
    assert "invoice_id" not in d
    assert "invoice_number" not in d


def test_admin_unlock_intervention_404(tenants, cleanup):
    tok = _forge(tenants["admin"], role="admin")
    r = requests.post(f"{API}/admin/interventions/iter56_iv_doesnotexist/unlock-invoice",
                      headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 404
