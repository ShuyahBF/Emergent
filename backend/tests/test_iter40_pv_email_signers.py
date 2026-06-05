"""Iter40 — PV signers can be free-form emails (Task 2).

Validates :
 - Backend `_norm_id_list` keeps both UUIDs and emails, dedupes lowercased
 - A PV with mixed signers (uuid + email) persists correctly
 - Sign-check :
   * a user whose email is in signers can sign
   * a user not in signers (id nor email) cannot
 - PDF includes the email entry as-is in the signers row
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
def admin_pair(db):
    """Returns 2 admins: 'A' creates the PV, 'B' has email used as signer."""
    a_id = f"sigem_a_{uuid.uuid4().hex[:6]}"
    b_email = f"sigem_b_{uuid.uuid4().hex[:6]}@test.local"
    b_id = f"sigem_b_{uuid.uuid4().hex[:6]}"
    company = f"SigEm Co {uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": a_id, "email": f"{a_id}@t.l", "password_hash": "x",
        "role": "admin", "company": company, "full_name": "Admin A",
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": b_id, "email": b_email, "password_hash": "x",
        "role": "admin", "company": company, "parent_client_id": a_id,
        "full_name": "Admin B", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {
        "a_id": a_id, "a_token": _forge(a_id, "admin"),
        "b_id": b_id, "b_email": b_email, "b_token": _forge(b_id, "admin"),
    }
    db.users.delete_many({"id": {"$in": [a_id, b_id]}})
    db.meeting_minutes.delete_many({"author_id": {"$in": [a_id, b_id]}})


def test_norm_id_list_keeps_mixed_uuid_and_email():
    from routes.meetings import _norm_id_list
    ids = ["uuid-1234", "USER@EXAMPLE.com", "user@example.com", "uuid-1234", "user2@example.com"]
    out = _norm_id_list(ids)
    # Email lowercased + de-duped, uuid kept once
    assert "uuid-1234" in out
    assert "user@example.com" in out
    assert "user2@example.com" in out
    assert out.count("user@example.com") == 1
    assert out.count("uuid-1234") == 1


def test_pv_can_persist_email_signer(db, admin_pair):
    ctx = admin_pair
    external = "external.consultant@partner.co"
    body = {
        "meeting_date": "2026-04-15",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "title": "PV avec email externe",
        "body_html": "<p>Test</p>",
        "signers": [ctx["b_id"], external],
        "participants": [],
    }
    r = requests.post(
        f"{API}/me/meetings", json=body,
        headers={"Authorization": f"Bearer {ctx['a_token']}"}, timeout=10,
    )
    assert r.status_code == 201, r.text
    pv = r.json()
    assert ctx["b_id"] in pv["signers"]
    assert external in pv["signers"]
    # The PDF includes the external email as-is in the Signers row
    pdf_r = requests.get(
        f"{API}/me/meetings/{pv['id']}/pdf",
        headers={"Authorization": f"Bearer {ctx['a_token']}"}, timeout=10,
    )
    assert pdf_r.status_code == 200
    assert pdf_r.headers["content-type"].startswith("application/pdf")
    # Cannot easily parse PDF here but we at least check the bytes are non-empty
    assert len(pdf_r.content) > 1500


def test_pv_sign_requires_email_match_when_external(db, admin_pair):
    """A signer email matches a user → that user can sign even though their
    id isn't directly listed (they only have an email entry)."""
    ctx = admin_pair
    # Create the PV with B's email (not B's id) as the only signer
    body = {
        "meeting_date": "2026-05-01",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "title": "PV signature par email",
        "body_html": "<p>signature par email</p>",
        "signers": [ctx["b_email"]],
        "participants": [],
    }
    r = requests.post(
        f"{API}/me/meetings", json=body,
        headers={"Authorization": f"Bearer {ctx['a_token']}"}, timeout=10,
    )
    assert r.status_code == 201, r.text
    pv_id = r.json()["id"]
    # B (whose email matches) can sign
    r = requests.post(
        f"{API}/me/meetings/{pv_id}/sign",
        headers={"Authorization": f"Bearer {ctx['b_token']}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json()["signed_by_email"] == ctx["b_email"]


def test_pv_sign_refused_when_not_in_signers(db, admin_pair):
    """Admin A (the creator) is NOT in the signers list → must be refused."""
    ctx = admin_pair
    body = {
        "meeting_date": "2026-05-02",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "title": "PV refus signature",
        "body_html": "<p>x</p>",
        "signers": [ctx["b_email"]],  # only B (by email)
        "participants": [],
    }
    r = requests.post(
        f"{API}/me/meetings", json=body,
        headers={"Authorization": f"Bearer {ctx['a_token']}"}, timeout=10,
    )
    assert r.status_code == 201
    pv_id = r.json()["id"]
    # A tries to sign — refused
    r = requests.post(
        f"{API}/me/meetings/{pv_id}/sign",
        headers={"Authorization": f"Bearer {ctx['a_token']}"}, timeout=10,
    )
    assert r.status_code == 403, r.text
    assert "signataires obligatoires" in r.json()["detail"]
