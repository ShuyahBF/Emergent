"""Iter38r-fix4 — Smoke tests for the 3 tasks of the day.

1. Compta strict role restriction is a frontend-only concern (PortalLayout
   filter), so we don't have a backend test for it here.
2. WhatsApp share-from-library uses existing GET endpoints; we sanity-check
   that they're still up.
3. Forms uses_count matches the actual count of submissions in the DB.
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
def env(db):
    admin_id = f"fix4_adm_{uuid.uuid4().hex[:6]}"
    company = f"FX4-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "full_name": "Admin FX4", "company": company, "role": "admin",
        "client_code": "FX4",
        "account_status": "active", "created_at": now,
    })
    yield {"admin_id": admin_id, "admin_token": _forge(admin_id, "admin")}
    db.users.delete_many({"id": admin_id})
    db.forms.delete_many({"client_id": admin_id})
    db.form_submissions.delete_many({"client_id": admin_id})


def _h(tok): return {"Authorization": f"Bearer {tok}"}


# ====================================================================
# Task 3 — uses_count must equal the actual count of form_submissions
# ====================================================================
def test_uses_count_matches_real_submissions(env, db):
    # Create a public form
    r = requests.post(
        f"{API}/me/forms",
        headers=_h(env["admin_token"]),
        json={
            "title": f"Test fix4 {uuid.uuid4().hex[:4]}",
            "is_public": True,
            "pages": [{"id": str(uuid.uuid4()), "title": "P1", "fields": [
                {"id": "f1", "label": "Nom", "type": "text"},
            ]}],
        },
    )
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    # Submit 3 times anonymously via the public endpoint
    for i in range(3):
        rs = requests.post(
            f"{API}/public/forms/{fid}/submission",
            json={"data": {"f1": f"Anon {i}"}, "respondent_name": f"User{i}"},
        )
        assert rs.status_code == 200, rs.text
    # List /me/forms — uses_count must now be 3
    rl = requests.get(f"{API}/me/forms", headers=_h(env["admin_token"]))
    assert rl.status_code == 200
    me_form = next((f for f in rl.json() if f["id"] == fid), None)
    assert me_form is not None
    assert me_form["uses_count"] == 3, f"Expected 3 submissions, got {me_form['uses_count']}"
    # Confirm via the submissions endpoint
    rs = requests.get(f"{API}/me/forms/{fid}/submissions-table", headers=_h(env["admin_token"]))
    assert rs.status_code == 200
    assert rs.json()["total"] == 3
    # And via the raw submissions endpoint
    rl2 = requests.get(f"{API}/me/forms/{fid}/submissions", headers=_h(env["admin_token"]))
    assert rl2.status_code == 200
    assert len(rl2.json()["items"]) == 3


# ====================================================================
# Task 2 — WhatsApp share modal endpoints are reachable
# ====================================================================
def test_media_library_endpoint_reachable(env):
    r = requests.get(f"{API}/me/media-library", headers=_h(env["admin_token"]))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_me_forms_endpoint_reachable(env):
    r = requests.get(f"{API}/me/forms", headers=_h(env["admin_token"]))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_public_products_endpoint_reachable():
    """Used by the catalog tab of the share-from-library modal.
    Anonymous endpoint — no auth needed."""
    r = requests.get(f"{API}/public/products")
    assert r.status_code == 200
    body = r.json()
    assert "categories" in body or "count" in body
