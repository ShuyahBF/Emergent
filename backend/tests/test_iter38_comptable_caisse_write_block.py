"""Iter38 — Additional regression: Comptable read-only on Caisse endpoints.

Validates that tracked_role='Comptable' can READ Caisse list endpoints
but CANNOT write (POST/PATCH/DELETE) on Caisse.
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


def _forge(uid: str, role: str = "client") -> str:
    return pyjwt.encode(
        {
            "sub": uid,
            "role": role,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int(
                (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
            ),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def comptable_ctx(db):
    """Setup a tenant (sup) + a Comptable user + a regular client."""
    sup_id = f"cpsup_{uuid.uuid4().hex[:6]}"
    company = f"CMP-{uuid.uuid4().hex[:4]}"
    cpt_id = f"cpcpt_{uuid.uuid4().hex[:6]}"
    reg_id = f"cpreg_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many(
        [
            {
                "id": sup_id,
                "email": f"{sup_id}@test.local",
                "password_hash": "x",
                "full_name": "Tenant Boss",
                "company": company,
                "role": "superviseur",
                "account_status": "active",
                "created_at": now,
            },
            {
                "id": cpt_id,
                "email": f"{cpt_id}@test.local",
                "password_hash": "x",
                "full_name": "Comptable User",
                "company": company,
                "parent_client_id": sup_id,
                "role": "client",
                "tracked_role": "Comptable",
                "tracked_user_id": f"tu_{uuid.uuid4().hex[:6]}",
                "account_status": "active",
                "created_at": now,
            },
            {
                "id": reg_id,
                "email": f"{reg_id}@test.local",
                "password_hash": "x",
                "full_name": "Regular Client",
                "company": company,
                "parent_client_id": sup_id,
                "role": "client",
                "account_status": "active",
                "created_at": now,
            },
        ]
    )
    yield {
        "sup_id": sup_id,
        "cpt_id": cpt_id,
        "reg_id": reg_id,
        "company": company,
        "sup_h": {"Authorization": f"Bearer {_forge(sup_id, role='superviseur')}"},
        "cpt_h": {"Authorization": f"Bearer {_forge(cpt_id, role='client')}"},
        "reg_h": {"Authorization": f"Bearer {_forge(reg_id, role='client')}"},
    }
    db.users.delete_many({"id": {"$in": [sup_id, cpt_id, reg_id]}})


# ---------- READ access (Comptable allowed) ----------
def test_comptable_can_read_business_clients(comptable_ctx):
    r = requests.get(
        f"{API}/admin/business-clients", headers=comptable_ctx["cpt_h"], timeout=15
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_comptable_can_read_products(comptable_ctx):
    r = requests.get(
        f"{API}/admin/products", headers=comptable_ctx["cpt_h"], timeout=15
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_comptable_can_read_receipts(comptable_ctx):
    # GET list of receipts is also a cashier read
    r = requests.get(
        f"{API}/cashier/receipts", headers=comptable_ctx["cpt_h"], timeout=15
    )
    # Should be allowed (200) OR allowed but empty list
    assert r.status_code in (200,), f"Status={r.status_code} body={r.text[:200]}"


def test_comptable_can_read_invoices(comptable_ctx):
    r = requests.get(
        f"{API}/cashier/invoices", headers=comptable_ctx["cpt_h"], timeout=15
    )
    assert r.status_code in (200,), f"Status={r.status_code} body={r.text[:200]}"


# ---------- WRITE access (Comptable forbidden, regular client too) ----------
def test_comptable_cannot_create_business_client(comptable_ctx):
    r = requests.post(
        f"{API}/admin/business-clients",
        headers=comptable_ctx["cpt_h"],
        json={"name": "Should be blocked"},
        timeout=15,
    )
    assert r.status_code in (401, 403), (
        f"Expected 401/403 got {r.status_code}: {r.text[:200]}"
    )


def test_comptable_cannot_create_product(comptable_ctx):
    r = requests.post(
        f"{API}/admin/products",
        headers=comptable_ctx["cpt_h"],
        json={"name": "Blocked product", "unit_price": 100},
        timeout=15,
    )
    assert r.status_code in (401, 403), (
        f"Expected 401/403 got {r.status_code}: {r.text[:200]}"
    )


def test_regular_client_cannot_read_business_clients(comptable_ctx):
    """Regression: non-Comptable, non-admin client must remain blocked."""
    r = requests.get(
        f"{API}/admin/business-clients", headers=comptable_ctx["reg_h"], timeout=15
    )
    assert r.status_code in (401, 403), (
        f"Regular client should not read cashier; got {r.status_code}"
    )


# ---------- Admin/Sup still has FULL access (no regression) ----------
def test_admin_sup_can_still_read_caisse(comptable_ctx):
    r = requests.get(
        f"{API}/admin/business-clients", headers=comptable_ctx["sup_h"], timeout=15
    )
    assert r.status_code == 200


def test_admin_sup_can_still_write_caisse(comptable_ctx):
    """Superviseur creates a business client — no regression on write path."""
    r = requests.post(
        f"{API}/admin/business-clients",
        headers=comptable_ctx["sup_h"],
        json={"name": f"BC-TEST-{uuid.uuid4().hex[:6]}"},
        timeout=15,
    )
    # Some envs use 200, some 201; accept both
    assert r.status_code in (200, 201), f"Got {r.status_code}: {r.text[:300]}"
