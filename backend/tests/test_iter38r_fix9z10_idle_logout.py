"""Iter38r-fix9z10 — Suggestion S009 — Auto-logout on inactivity.

Validates:
  • PUT /api/admin/settings accepts auto_logout_minutes (0–120)
  • Invalid values (negative, >120, non-int) rejected with 400
  • GET /api/me/idle-config returns the saved value + warning_seconds=30
  • Anonymous request → 401
  • auto_logout_minutes=0 means "disabled" (returned as 0, no special handling)
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
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
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
def admin(db):
    aid = f"fz10_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "token": _forge(aid, "admin"), "headers": {"Authorization": f"Bearer {_forge(aid, 'admin')}"}}
    db.users.delete_many({"id": aid})


@pytest.fixture
def regular_user(db):
    uid = f"u_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": uid, "token": _forge(uid, "client"), "headers": {"Authorization": f"Bearer {_forge(uid, 'client')}"}}
    db.users.delete_many({"id": uid})


# -------------------------- SETTINGS WRITE --------------------------

def test_admin_can_set_auto_logout_minutes(admin):
    r = requests.put(f"{API}/admin/settings", json={"auto_logout_minutes": 10}, headers=admin["headers"])
    assert r.status_code == 200, r.text

    r2 = requests.get(f"{API}/me/idle-config", headers=admin["headers"])
    assert r2.status_code == 200
    assert r2.json()["auto_logout_minutes"] == 10
    assert r2.json()["warning_seconds"] == 30


def test_zero_disables_auto_logout(admin):
    r = requests.put(f"{API}/admin/settings", json={"auto_logout_minutes": 0}, headers=admin["headers"])
    assert r.status_code == 200
    r2 = requests.get(f"{API}/me/idle-config", headers=admin["headers"])
    assert r2.json()["auto_logout_minutes"] == 0


def test_negative_value_rejected(admin):
    r = requests.put(f"{API}/admin/settings", json={"auto_logout_minutes": -5}, headers=admin["headers"])
    assert r.status_code == 400


def test_above_120_rejected(admin):
    r = requests.put(f"{API}/admin/settings", json={"auto_logout_minutes": 121}, headers=admin["headers"])
    assert r.status_code == 400


def test_non_integer_rejected(admin):
    r = requests.put(f"{API}/admin/settings", json={"auto_logout_minutes": "ten"}, headers=admin["headers"])
    assert r.status_code in (400, 422)


# -------------------------- IDLE CONFIG READ --------------------------

def test_idle_config_requires_authentication():
    r = requests.get(f"{API}/me/idle-config")
    assert r.status_code in (401, 403)


def test_regular_user_can_read_idle_config(admin, regular_user):
    requests.put(f"{API}/admin/settings", json={"auto_logout_minutes": 15}, headers=admin["headers"])
    r = requests.get(f"{API}/me/idle-config", headers=regular_user["headers"])
    assert r.status_code == 200
    assert r.json()["auto_logout_minutes"] == 15
