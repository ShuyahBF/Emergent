"""Iter38r-fix9s — PDF regeneration endpoint authorization tests.

Validates that POST /api/admin/docs/regenerate/{slug} is:
  - 403 for client/tracked-only users
  - 404 for unknown slug (admin)
  - 200 for admin on a valid slug (skipped if generator missing reportlab deps)
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


@pytest.fixture
def users():
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    admin_id = f"ds_adm_{uuid.uuid4().hex[:6]}"
    client_id = f"ds_cli_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin DS", "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": client_id, "email": f"{client_id}@t.l", "password_hash": "x",
         "full_name": "Client DS", "role": "client",
         "account_status": "active", "created_at": now},
    ])
    yield {
        "admin_token": _forge(admin_id, "admin"),
        "client_token": _forge(client_id, "client"),
    }
    db.users.delete_many({"id": {"$in": [admin_id, client_id]}})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_regen_forbidden_for_client(users):
    r = requests.post(
        f"{API}/admin/docs/regenerate/guide-utilisateur",
        headers=_h(users["client_token"]),
    )
    assert r.status_code == 403


def test_regen_404_for_unknown_slug(users):
    r = requests.post(
        f"{API}/admin/docs/regenerate/does-not-exist",
        headers=_h(users["admin_token"]),
    )
    assert r.status_code == 404


def test_regen_200_for_admin_on_valid_slug(users):
    # Use the smallest/fastest of the 3 to avoid timeouts on slow CI
    r = requests.post(
        f"{API}/admin/docs/regenerate/brochure-fonctionnalites",
        headers=_h(users["admin_token"]),
        timeout=120,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["slug"] == "brochure-fonctionnalites"
    assert data["size_kb"] > 0
