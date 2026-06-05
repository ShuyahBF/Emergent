"""S045 Phase 2 — Refactor admin_settings routes.

Validates the 6 endpoints extracted to `routes/admin_settings.py` :
  GET    /admin/settings
  POST   /admin/settings/test-url
  GET    /admin/secrets/change-audit
  GET    /admin/incidents
  DELETE /admin/incidents/{id}
  GET    /admin/incidents/export.csv

Behavior must be unchanged compared to the in-server implementation.
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
def admin_token(db):
    admin_id = f"s045p2_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin"), admin_id
    db.users.delete_one({"id": admin_id})


@pytest.fixture
def client_token(db):
    uid = f"s045p2c_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(uid, "client"), uid
    db.users.delete_one({"id": uid})


# ----------------------------------------------------------------------
# GET /admin/settings
# ----------------------------------------------------------------------

def test_get_settings_masks_sensitive(db, admin_token):
    token, _ = admin_token
    # Seed a secret to verify masking
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {"smtp_password": "supersecret-XYZ", "openai_api_key": "sk-test-leak"}},
        upsert=True,
    )
    r = requests.get(f"{API}/admin/settings", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    # Sensitive fields are masked to ********
    assert body.get("smtp_password") == "********"
    assert body.get("openai_api_key") == "********"
    # The google_calendar_connected synthetic flag is present
    assert "google_calendar_connected" in body


def test_get_settings_403_for_non_admin(client_token):
    token, _ = client_token
    r = requests.get(f"{API}/admin/settings", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403, r.text


# ----------------------------------------------------------------------
# POST /admin/settings/test-url
# ----------------------------------------------------------------------

def test_test_url_rejects_unlisted_key(admin_token):
    token, _ = admin_token
    r = requests.post(
        f"{API}/admin/settings/test-url",
        json={"key": "smtp_password"},  # not in TESTABLE_URL_KEYS
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 400, r.text
    assert "Clé non testable" in r.json()["detail"]


def test_test_url_rejects_when_unconfigured(db, admin_token):
    token, _ = admin_token
    # Make sure the key is empty
    db.settings.update_one({"_id": "global"}, {"$set": {"alexa_webhook_url": ""}}, upsert=True)
    r = requests.post(
        f"{API}/admin/settings/test-url",
        json={"key": "alexa_webhook_url"},
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 400, r.text
    assert "n'est pas configuré" in r.json()["detail"]


def test_test_url_ping_public_base_url(db, admin_token):
    """When public_base_url points to the backend itself, a GET should return 2xx."""
    token, _ = admin_token
    db.settings.update_one(
        {"_id": "global"}, {"$set": {"public_base_url": BASE_URL}}, upsert=True,
    )
    r = requests.post(
        f"{API}/admin/settings/test-url",
        json={"key": "public_base_url"},
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The endpoint returns a structured report whether the ping succeeded or not
    assert body.get("key") == "public_base_url"
    assert body.get("method") == "GET"
    assert "elapsed_ms" in body or "error" in body


# ----------------------------------------------------------------------
# GET /admin/secrets/change-audit
# ----------------------------------------------------------------------

def test_secrets_change_audit_returns_items_shape(db, admin_token):
    token, _ = admin_token
    # Seed an audit entry directly
    aid = f"audit_{uuid.uuid4().hex[:6]}"
    db.secret_change_audit.insert_one({
        "id": aid, "key": "smtp_password", "action": "updated",
        "actor_email": "test@x.y", "ts": datetime.now(timezone.utc).isoformat(),
        "fingerprint": "abc123", "is_secret": True,
    })
    try:
        r = requests.get(
            f"{API}/admin/secrets/change-audit?limit=50",
            headers={"Authorization": f"Bearer {token}"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "total" in body
        assert any(i.get("id") == aid for i in body["items"])
    finally:
        db.secret_change_audit.delete_one({"id": aid})


def test_secrets_change_audit_filter_by_key(db, admin_token):
    token, _ = admin_token
    a1 = f"audit_a_{uuid.uuid4().hex[:6]}"
    a2 = f"audit_b_{uuid.uuid4().hex[:6]}"
    db.secret_change_audit.insert_many([
        {"id": a1, "key": "smtp_password", "action": "updated", "actor_email": "x@y", "ts": datetime.now(timezone.utc).isoformat()},
        {"id": a2, "key": "openai_api_key", "action": "created", "actor_email": "x@y", "ts": datetime.now(timezone.utc).isoformat()},
    ])
    try:
        r = requests.get(
            f"{API}/admin/secrets/change-audit?key=smtp_password",
            headers={"Authorization": f"Bearer {token}"}, timeout=10,
        )
        assert r.status_code == 200
        items = r.json()["items"]
        keys_seen = {i.get("key") for i in items}
        assert "smtp_password" in keys_seen
        assert "openai_api_key" not in keys_seen
    finally:
        db.secret_change_audit.delete_many({"id": {"$in": [a1, a2]}})


# ----------------------------------------------------------------------
# /admin/incidents (list, delete, csv)
# ----------------------------------------------------------------------

def test_admin_incidents_list_and_delete(db, admin_token):
    token, _ = admin_token
    iid = f"inc_{uuid.uuid4().hex[:6]}"
    db.incidents.insert_one({
        "id": iid, "severity": "warning", "message": "Test inc S045P2",
        "status": "ongoing", "started_at": datetime.now(timezone.utc).isoformat(),
        "updates": [], "created_by": "test@x.y", "resolved_by": None,
    })
    try:
        # List
        r = requests.get(f"{API}/admin/incidents?limit=200",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200, r.text
        items = r.json()
        assert any(i.get("id") == iid for i in items)
        # Delete
        r = requests.delete(f"{API}/admin/incidents/{iid}",
                            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}
        # 404 on missing
        r = requests.delete(f"{API}/admin/incidents/inc-missing-{uuid.uuid4().hex[:6]}",
                            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 404
    finally:
        db.incidents.delete_one({"id": iid})


def test_admin_incidents_csv_export(db, admin_token):
    token, _ = admin_token
    iid = f"inc_{uuid.uuid4().hex[:6]}"
    db.incidents.insert_one({
        "id": iid, "severity": "critical", "message": "CSV Test Iter40",
        "status": "resolved", "started_at": datetime.now(timezone.utc).isoformat(),
        "resolved_at": datetime.now(timezone.utc).isoformat(), "duration_minutes": 5,
        "updates": [{"ts": datetime.now(timezone.utc).isoformat(), "message": "x"}],
        "created_by": "x@y", "resolved_by": "x@y", "link_url": "https://test/x",
    })
    try:
        r = requests.get(f"{API}/admin/incidents/export.csv",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "csv" in body
        csv_text = body["csv"]
        # Header present
        assert "started_at,resolved_at,duration_minutes,severity" in csv_text
        # Our row present
        assert "CSV Test Iter40" in csv_text
        assert "critical" in csv_text
    finally:
        db.incidents.delete_one({"id": iid})


def test_admin_incidents_403_for_client(client_token):
    token, _ = client_token
    r = requests.get(f"{API}/admin/incidents", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403
    r = requests.get(f"{API}/admin/secrets/change-audit", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403
    r = requests.post(f"{API}/admin/settings/test-url", json={"key": "public_base_url"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403
