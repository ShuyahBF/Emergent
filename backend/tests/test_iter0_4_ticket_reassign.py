"""0-4 (2026-02) — PATCH /me/tickets/{tid} accepts client_id to reassign
the ticket to a different tenant. Restricted to admin/sup/moderateur.
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


def _forge(uid: str, role: str = "superviseur") -> str:
    return pyjwt.encode(
        {"sub": uid, "role": role,
         "iat": int(datetime.now(timezone.utc).timestamp()),
         "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())},
        JWT_SECRET, algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def reassign_setup(db):
    """Create a superviseur + 2 client tenants + a ticket on cli1."""
    sup_id = f"trsup_{uuid.uuid4().hex[:6]}"
    cli1_id = f"trc1_{uuid.uuid4().hex[:6]}"
    cli2_id = f"trc2_{uuid.uuid4().hex[:6]}"
    contact_id = f"trct_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
         "full_name": "Sup", "company": "ReassignCo", "role": "superviseur",
         "account_status": "active", "created_at": now},
        {"id": cli1_id, "email": f"{cli1_id}@t.l", "password_hash": "x",
         "full_name": "Client 1", "company": "Tenant Alpha",
         "parent_client_id": sup_id, "role": "client",
         "account_status": "active", "created_at": now},
        {"id": cli2_id, "email": f"{cli2_id}@t.l", "password_hash": "x",
         "full_name": "Client 2", "company": "Tenant Beta",
         "parent_client_id": sup_id, "role": "client",
         "account_status": "active", "created_at": now},
    ])
    db.contacts.insert_one({
        "id": contact_id, "client_id": cli1_id,
        "first_name": "John", "last_name": "Doe",
        "phone": "+22500000000", "created_at": now,
    })
    sh = {"Authorization": f"Bearer {_forge(sup_id)}"}
    # Create a ticket on cli1
    r = requests.post(f"{API}/me/contacts/{contact_id}/ticket", headers=sh,
        json={"motif": "Test 0-4 reassign", "client_id": cli1_id}, timeout=15)
    assert r.status_code == 200, r.text
    tid = r.json()["ticket"]["id"]
    yield {"sup_id": sup_id, "cli1_id": cli1_id, "cli2_id": cli2_id,
           "tid": tid, "sh": sh, "contact_id": contact_id}
    db.users.delete_many({"id": {"$in": [sup_id, cli1_id, cli2_id]}})
    db.contacts.delete_many({"id": contact_id})
    db.support_tickets.delete_many({"id": tid})


def test_reassign_ticket_to_other_tenant(reassign_setup):
    sh = reassign_setup["sh"]
    tid = reassign_setup["tid"]
    cli2 = reassign_setup["cli2_id"]
    # PATCH with client_id → reassign
    r = requests.patch(f"{API}/me/tickets/{tid}", headers=sh,
        json={"client_id": cli2}, timeout=15)
    assert r.status_code == 200, r.text
    t = r.json()["ticket"]
    assert t["client_id"] == cli2
    assert t.get("reassigned_from") == reassign_setup["cli1_id"]
    assert t.get("reassigned_at")
    assert t.get("reassigned_by") == reassign_setup["sup_id"]


def test_reassign_same_client_id_is_noop(reassign_setup):
    sh = reassign_setup["sh"]
    tid = reassign_setup["tid"]
    cli1 = reassign_setup["cli1_id"]
    r = requests.patch(f"{API}/me/tickets/{tid}", headers=sh,
        json={"client_id": cli1}, timeout=15)
    assert r.status_code == 200
    # Ticket should still belong to cli1, no reassigned_from
    t = r.json()["ticket"]
    assert t["client_id"] == cli1
    assert t.get("reassigned_from") is None  # nothing changed


def test_reassign_404_when_target_unknown(reassign_setup):
    sh = reassign_setup["sh"]
    tid = reassign_setup["tid"]
    r = requests.patch(f"{API}/me/tickets/{tid}", headers=sh,
        json={"client_id": "NON_EXISTENT"}, timeout=15)
    assert r.status_code == 404


def test_reassign_403_for_regular_client(reassign_setup, db):
    """A 'client' role cannot reassign tickets."""
    cli_id = reassign_setup["cli1_id"]
    headers = {"Authorization": f"Bearer {_forge(cli_id, role='client')}"}
    r = requests.patch(f"{API}/me/tickets/{reassign_setup['tid']}", headers=headers,
        json={"client_id": reassign_setup["cli2_id"]}, timeout=15)
    # Either 403 (forbidden) or 404 (scope filter hides it) is acceptable
    assert r.status_code in (403, 404)
