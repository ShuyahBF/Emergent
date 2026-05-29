"""Iter38r-fix8c — Regression test: every flag in DEFAULT_CLIENT_FEATURES
must be accepted by the PUT /admin/clients/{id}/features endpoint AND
actually persisted to MongoDB.

Root cause: Pydantic `ClientFeaturesUpdate` was missing `ai_liluvine_pro`
so the toggle silently disappeared on save. This test guards against any
future feature being added to DEFAULT_CLIENT_FEATURES but forgotten in
ClientFeaturesUpdate.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"), override=False)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": data["dev_otp"]},
        timeout=30,
    )
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_id(db):
    u = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    return u["id"]


def test_ai_liluvine_pro_toggle_persists(admin_h, db, admin_id):
    """PUT /admin/clients/{admin_id}/features with ai_liluvine_pro=true must
    survive a round-trip in the DB."""
    # Capture the original value to restore later
    orig = (db.users.find_one({"id": admin_id}, {"_id": 0, "features": 1}) or {}).get("features") or {}
    original_value = bool(orig.get("ai_liluvine_pro", False))
    try:
        # Toggle ON
        r = requests.put(
            f"{API}/admin/clients/{admin_id}/features",
            headers=admin_h,
            json={"ai_liluvine_pro": True},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("features", {}).get("ai_liluvine_pro") is True, (
            f"Server response did not persist the flag: {body}"
        )

        # Verify in MongoDB directly
        u = db.users.find_one({"id": admin_id}, {"_id": 0, "features": 1})
        assert (u or {}).get("features", {}).get("ai_liluvine_pro") is True, (
            "Flag was NOT actually written to MongoDB — Pydantic may be silently stripping it"
        )

        # Verify the GET reads it back
        r2 = requests.get(f"{API}/admin/clients/{admin_id}/features", headers=admin_h, timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("features", {}).get("ai_liluvine_pro") is True

        # Verify /me/features reflects it for the admin user
        r3 = requests.get(f"{API}/me/features", headers=admin_h, timeout=30)
        # admin/superviseur get everything True by default, so this is a weak
        # check but at minimum we ensure the value is True (not False).
        assert r3.json().get("features", {}).get("ai_liluvine_pro") is True
    finally:
        # Restore
        requests.put(
            f"{API}/admin/clients/{admin_id}/features",
            headers=admin_h,
            json={"ai_liluvine_pro": original_value},
            timeout=30,
        )


def test_default_client_features_are_all_in_pydantic_model():
    """Static check: every key in DEFAULT_CLIENT_FEATURES must exist as a
    field on ClientFeaturesUpdate, otherwise toggles silently get dropped."""
    import sys
    sys.path.insert(0, "/app/backend")
    from server import DEFAULT_CLIENT_FEATURES, ClientFeaturesUpdate
    missing = [
        k for k in DEFAULT_CLIENT_FEATURES
        if k not in ClientFeaturesUpdate.model_fields
    ]
    assert not missing, (
        f"ClientFeaturesUpdate is missing the following fields, "
        f"the toggle won't persist: {missing}"
    )
