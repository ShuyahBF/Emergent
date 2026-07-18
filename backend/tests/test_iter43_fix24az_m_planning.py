"""Iter43-fix24az-m (2026-07-18) — Planning médecins backend tests.

Validate the 4 endpoints of the Planning module :
  - POST /webhooks/planning/{secret}    (public, no auth)
  - GET  /admin/planning/config         (admin)
  - GET  /me/planning/doctors           (any user)
  - GET  /me/planning/appointments      (any user, medecin scoped)
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
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _forge_token(user_id: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": user_id,
        "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def admin_token(db):
    u = db.users.find_one({"email": "admin@sawalismartsystems.com"})
    return _forge_token(u["id"], "admin")


@pytest.fixture(scope="module")
def medecin_token(db):
    u = db.users.find_one({"email": "medecin-test@sawali-test.com"})
    assert u, "medecin-test@sawali-test.com not seeded"
    return _forge_token(u["id"], u.get("role", "client-tracked"))


@pytest.fixture(scope="module")
def webhook_secret(admin_token):
    r = requests.get(f"{API}/admin/planning/config", headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("planning_webhook_secret")
    return j["planning_webhook_secret"]


# ---------------------------------------------------------------------------
# ADMIN CONFIG
# ---------------------------------------------------------------------------
def test_admin_config_returns_webhook_url(admin_token):
    r = requests.get(f"{API}/admin/planning/config", headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j.get("planning_webhook_secret"), str) and len(j["planning_webhook_secret"]) >= 16
    assert j.get("webhook_url", "").endswith(f"/api/webhooks/planning/{j['planning_webhook_secret']}")
    assert "sample_payload" in j


def test_admin_config_regenerate(admin_token):
    r = requests.put(
        f"{API}/admin/planning/config",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"regenerate": True},
        timeout=15,
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    old = j["planning_webhook_secret"]
    r2 = requests.put(
        f"{API}/admin/planning/config",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"regenerate": True},
        timeout=15,
    )
    assert r2.json()["planning_webhook_secret"] != old, "Secret didn't rotate"


def test_admin_config_requires_auth():
    r = requests.get(f"{API}/admin/planning/config", timeout=15)
    assert r.status_code in (401, 403), r.text


# ---------------------------------------------------------------------------
# WEBHOOK PUBLIC
# ---------------------------------------------------------------------------
def test_webhook_wrong_secret_returns_404():
    r = requests.post(f"{API}/webhooks/planning/wrong-secret-xxx", json={}, timeout=15)
    assert r.status_code == 404


def test_webhook_missing_required_fields_400(webhook_secret):
    r = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "CLI-Z"},  # missing medecin, patient, start
        timeout=15,
    )
    assert r.status_code == 400
    detail = (r.json().get("detail") or "").lower()
    assert "medecin" in detail or "patient" in detail


def test_webhook_valid_payload_creates_appointment(webhook_secret, db):
    unique_patient = f"PYTEST-{uuid.uuid4().hex[:10]}"
    start = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "code_clinique": "PYTEST-CLI",
        "medecin": "Dr. Pytest",
        "medecin_email": "medecin-test@sawali-test.com",
        "patient": unique_patient,
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30)).isoformat(),
        "motif": "pytest webhook",
        "external_id": f"EXT-{uuid.uuid4().hex[:8]}",
    }
    r = requests.post(f"{API}/webhooks/planning/{webhook_secret}", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") is True
    assert j.get("created") is True
    # Check doc was inserted with medecin_id resolved via medecin_email
    assert j.get("medecin_id"), "medecin_id should be resolved from email"
    # Cleanup
    db.planning_appointments.delete_many({"patient": unique_patient})


def test_webhook_idempotent_upsert(webhook_secret, db):
    """Same payload twice should not create 2 rows (upsert)."""
    unique_patient = f"PYTEST-DUP-{uuid.uuid4().hex[:10]}"
    start = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "code_clinique": "PYTEST-CLI",
        "medecin": "Dr. Pytest",
        "patient": unique_patient,
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30)).isoformat(),
    }
    r1 = requests.post(f"{API}/webhooks/planning/{webhook_secret}", json=payload, timeout=15)
    r2 = requests.post(f"{API}/webhooks/planning/{webhook_secret}", json=payload, timeout=15)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json().get("created") is True
    assert r2.json().get("created") is False, "2nd call should update, not create"
    count = db.planning_appointments.count_documents({"patient": unique_patient})
    assert count == 1
    db.planning_appointments.delete_many({"patient": unique_patient})


# ---------------------------------------------------------------------------
# TENANT — /me/planning
# ---------------------------------------------------------------------------
def test_list_doctors_returns_medecin(admin_token):
    r = requests.get(f"{API}/me/planning/doctors", headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200
    docs = r.json().get("doctors") or []
    emails = [d.get("email") for d in docs]
    assert "medecin-test@sawali-test.com" in emails, f"Missing Médecin in doctors list. Got: {emails}"


def test_medecin_view_locks_to_self(medecin_token, db):
    medecin = db.users.find_one({"email": "medecin-test@sawali-test.com"})
    r = requests.get(
        f"{API}/me/planning/appointments",
        headers={"Authorization": f"Bearer {medecin_token}"},
        timeout=15,
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("is_medecin_view") is True
    assert j.get("medecin_id_locked") == medecin["id"]
    # Try to override with a different medecin_id — should be ignored (locked to self)
    r2 = requests.get(
        f"{API}/me/planning/appointments?medecin_id=other-fake-id",
        headers={"Authorization": f"Bearer {medecin_token}"},
        timeout=15,
    )
    j2 = r2.json()
    assert j2.get("medecin_id_locked") == medecin["id"], "Médecin should be locked to their own id"


def test_admin_can_filter_by_medecin(admin_token, db):
    medecin = db.users.find_one({"email": "medecin-test@sawali-test.com"})
    r = requests.get(
        f"{API}/me/planning/appointments?medecin_id={medecin['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("is_medecin_view") is False
    for a in j.get("items", []):
        # RDV must belong to that medecin (via id OR email match)
        assert a.get("medecin_id") == medecin["id"] or a.get("medecin_email") == medecin["email"]


def test_invalid_date_format_400(admin_token):
    r = requests.get(
        f"{API}/me/planning/appointments?date=not-a-date",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 400
