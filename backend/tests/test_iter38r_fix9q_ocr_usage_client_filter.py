"""Iter38r-fix9q — OCR usage endpoint accepts `client_id` filter.

Verifies that GET /api/admin/liluvine-pro/kb/ocr-usage?client_id=X
returns only the usage matching that tenant_id, and that per-tenant
pricing/cap override the global settings.
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
def setup(db):
    """Create 2 tenants with distinct OCR usage rows for the current month."""
    tenant_a = f"qa_a_{uuid.uuid4().hex[:6]}"
    tenant_b = f"qa_b_{uuid.uuid4().hex[:6]}"
    admin = f"qa_adm_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    db.users.insert_many([
        {"id": admin, "email": f"{admin}@t.l", "password_hash": "x",
         "full_name": "Admin Q", "company": "QQ", "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": tenant_a, "email": f"{tenant_a}@t.l", "password_hash": "x",
         "full_name": "Tenant A", "company": "TA", "role": "admin",
         "account_status": "active", "created_at": now,
         "features": {"kb_ocr_xof_per_page": 100, "kb_ocr_xof_monthly_cap": 5000}},
        {"id": tenant_b, "email": f"{tenant_b}@t.l", "password_hash": "x",
         "full_name": "Tenant B", "company": "TB", "role": "admin",
         "account_status": "active", "created_at": now},
    ])
    # 7 OCR pages for A (cost 700 XOF @ 100/page)
    db.ai_usage.insert_one({
        "id": f"u_a_{uuid.uuid4().hex[:6]}",
        "tenant_id": tenant_a, "resource": "kb_ocr",
        "ym": ym, "units": 7, "cost_xof": 700,
        "created_at": now,
    })
    # 3 OCR pages for B
    db.ai_usage.insert_one({
        "id": f"u_b_{uuid.uuid4().hex[:6]}",
        "tenant_id": tenant_b, "resource": "kb_ocr",
        "ym": ym, "units": 3, "cost_xof": 150,
        "created_at": now,
    })
    yield {"admin_token": _forge(admin, "admin"), "tenant_a": tenant_a, "tenant_b": tenant_b, "ym": ym}
    db.users.delete_many({"id": {"$in": [admin, tenant_a, tenant_b]}})
    db.ai_usage.delete_many({"tenant_id": {"$in": [tenant_a, tenant_b]}})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_ocr_usage_filters_by_client_id(setup):
    r = requests.get(
        f"{API}/admin/liluvine-pro/kb/ocr-usage",
        headers=_h(setup["admin_token"]),
        params={"client_id": setup["tenant_a"]},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["client_id"] == setup["tenant_a"]
    assert data["pages"] == 7
    assert data["cost_xof"] == 700
    # Per-tenant override on cap & per_page
    assert data["monthly_cap_xof"] == 5000
    assert data["xof_per_page"] == 100
    assert data["remaining_xof"] == 4300


def test_ocr_usage_without_client_id_aggregates_all(setup):
    """No client_id → total across all tenants for that month."""
    r = requests.get(
        f"{API}/admin/liluvine-pro/kb/ocr-usage",
        headers=_h(setup["admin_token"]),
        params={"month": setup["ym"]},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["client_id"] is None
    # At least the 10 pages we inserted (other tenants may also have usage)
    assert data["pages"] >= 10
