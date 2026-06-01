"""S-iter39d — Tests for items 1, 2, 4, 5:
  - /api/me/tenant-users dropdown source
  - PV signers/participants persistence + sign validation
  - /admin/suggestions-registry markdown reader
  - /admin/messaging/audience now returns last_message_at
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30).json()
    if not r.get("needs_otp"):
        return r["access_token"]
    return requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": r["session_token"], "code": r["dev_otp"]},
        timeout=30,
    ).json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_tenant_users_endpoint(admin_h):
    r = requests.get(f"{API}/me/tenant-users", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert isinstance(items, list)
    # Each row has value + label
    for it in items:
        assert "value" in it
        assert "label" in it


def test_pv_signers_persistence_and_sign_check(admin_h, db_sync):
    """Create a PV with signers list, ensure persistence; verify sign
    refuses a user not in the signers list (we simulate by inserting a
    PV whose signers list excludes the admin)."""
    pv_ids = []
    try:
        # 1) Create a PV with empty signers — admin should still be able to sign
        r = requests.post(f"{API}/me/meetings", headers=admin_h, json={
            "meeting_date": "2026-02-26",
            "started_at": "2026-02-26T09:00:00Z",
            "title": "PV with empty signers",
            "body_html": "<p>Test</p>",
            "signers": [],
            "participants": [],
        }, timeout=30)
        assert r.status_code == 201, r.text
        pv1 = r.json()
        pv_ids.append(pv1["id"])
        assert pv1.get("signers") == []
        r = requests.post(f"{API}/me/meetings/{pv1['id']}/sign", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text  # empty signers list → no restriction

        # 2) Create a PV with a non-admin user as the only signer; admin can't sign
        fake_id = str(uuid.uuid4())
        r = requests.post(f"{API}/me/meetings", headers=admin_h, json={
            "meeting_date": "2026-02-26",
            "started_at": "2026-02-26T09:00:00Z",
            "title": "PV with non-admin signer",
            "body_html": "<p>Test</p>",
            "signers": [fake_id],
            "participants": [],
        }, timeout=30)
        assert r.status_code == 201
        pv2 = r.json()
        pv_ids.append(pv2["id"])
        assert pv2["signers"] == [fake_id]

        r = requests.post(f"{API}/me/meetings/{pv2['id']}/sign", headers=admin_h, timeout=30)
        assert r.status_code == 403, r.text
        assert "signataires" in (r.json().get("detail") or "").lower()

        # 3) Update signers to include admin → admin can sign
        admin_id = requests.get(f"{API}/auth/me", headers=admin_h, timeout=30).json()["id"]
        r = requests.put(f"{API}/me/meetings/{pv2['id']}", headers=admin_h, json={"signers": [admin_id]}, timeout=30)
        assert r.status_code == 200, r.text
        r = requests.post(f"{API}/me/meetings/{pv2['id']}/sign", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text

        # 4) Disjoint participants: passing the same id in signers and participants
        # should keep it ONLY in signers.
        admin_id2 = admin_id
        r = requests.post(f"{API}/me/meetings", headers=admin_h, json={
            "meeting_date": "2026-02-26",
            "started_at": "2026-02-26T09:00:00Z",
            "title": "Disjoint test",
            "body_html": "",
            "signers": [admin_id2],
            "participants": [admin_id2, fake_id],
        }, timeout=30)
        assert r.status_code == 201
        pv3 = r.json()
        pv_ids.append(pv3["id"])
        assert admin_id2 in pv3["signers"]
        assert admin_id2 not in pv3["participants"]
        assert fake_id in pv3["participants"]
    finally:
        if pv_ids:
            db_sync.meeting_minutes.delete_many({"id": {"$in": pv_ids}})


def test_suggestions_registry(admin_h):
    r = requests.get(f"{API}/admin/suggestions-registry", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "markdown" in body
    assert body["size_bytes"] > 0
    # Should contain at least one S### entry
    assert "S0" in body["markdown"] or "S1" in body["markdown"]


def test_messaging_audience_has_last_message_at(admin_h):
    r = requests.get(f"{API}/admin/messaging/audience", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    payload = r.json()
    # All client rows must expose last_message_at (None is fine when never contacted)
    for row in (payload.get("clients") or []):
        assert "last_message_at" in row
    for row in (payload.get("tracked_users") or []):
        assert "last_message_at" in row
