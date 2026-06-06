"""Iter41 hot-fix (2026-02) — Bug ContactGroups : add-to-group ignored
peer-shared contacts (different client_id but same company).
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


def _forge(uid, role="client"):
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def peer_setup(db):
    """Create 2 users with the SAME `company` but DIFFERENT client_ids,
    and a contact owned by user A. User B should be able to add A's contact
    to their group (peer-sharing).
    """
    company = f"AcmeCorp_{uuid.uuid4().hex[:6]}"
    uid_a = f"cg_a_{uuid.uuid4().hex[:6]}"
    uid_b = f"cg_b_{uuid.uuid4().hex[:6]}"
    cid_a = f"client_{uuid.uuid4().hex[:6]}"
    cid_b = f"client_{uuid.uuid4().hex[:6]}"
    contact_id = f"contact_{uuid.uuid4().hex[:6]}"
    db.users.insert_many([
        {"id": uid_a, "email": f"{uid_a}@t.l", "role": "client", "client_id": cid_a, "company": company,
         "account_status": "active", "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": uid_b, "email": f"{uid_b}@t.l", "role": "client", "client_id": cid_b, "company": company,
         "account_status": "active", "created_at": datetime.now(timezone.utc).isoformat()},
    ])
    db.directory_contacts.insert_one({
        "id": contact_id, "client_id": cid_a,  # owned by A
        "name": "Jean Dupont", "phone": "+33611111111", "company": company,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"uid_a": uid_a, "uid_b": uid_b, "cid_a": cid_a, "cid_b": cid_b,
           "contact_id": contact_id, "company": company,
           "token_a": _forge(uid_a, "client"), "token_b": _forge(uid_b, "client")}
    db.users.delete_many({"id": {"$in": [uid_a, uid_b]}})
    db.directory_contacts.delete_many({"id": contact_id})
    db.contact_groups.delete_many({"client_id": {"$in": [cid_a, cid_b]}})


def test_user_b_can_add_user_a_contact_to_group(db, peer_setup):
    """Reproducer for the user-reported bug : adding a peer-shared contact
    to a group returned ok=true but `added=[]` and total=0."""
    s = peer_setup
    # User B creates a group
    r1 = requests.post(f"{API}/me/contact-groups", json={"name": "Mon groupe peer"},
                       headers={"Authorization": f"Bearer {s['token_b']}"}, timeout=10)
    assert r1.status_code == 201, r1.text
    gid = r1.json()["id"]

    # User B sees A's contact via /me/contacts (peer-sharing)
    r_list = requests.get(f"{API}/me/contacts",
                         headers={"Authorization": f"Bearer {s['token_b']}"}, timeout=10)
    assert r_list.status_code == 200
    contact_ids = [c["id"] for c in r_list.json()]
    assert s["contact_id"] in contact_ids, "Peer-sharing not visible — test setup broken"

    # User B adds A's contact to the group — THIS used to return added=[]
    r2 = requests.post(f"{API}/me/contact-groups/{gid}/contacts",
                       json={"contact_ids": [s["contact_id"]]},
                       headers={"Authorization": f"Bearer {s['token_b']}"}, timeout=10)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["added"] == [s["contact_id"]]
    assert body["ignored"] == []
    assert body["total"] == 1


def test_group_creation_with_peer_contact(db, peer_setup):
    """Bonus : creating a group with initial peer-shared contact_ids should
    preserve them, not silently drop them."""
    s = peer_setup
    r = requests.post(f"{API}/me/contact-groups",
                     json={"name": f"Groupe init {uuid.uuid4().hex[:4]}", "contact_ids": [s["contact_id"]]},
                     headers={"Authorization": f"Bearer {s['token_b']}"}, timeout=10)
    assert r.status_code == 201, r.text
    assert r.json()["contact_ids"] == [s["contact_id"]]


def test_resolve_includes_peer_contacts(db, peer_setup):
    """`POST /me/contact-groups/resolve` should expand a peer-shared contact_id
    to a full contact row (was dropped by the previous client_id filter)."""
    s = peer_setup
    r = requests.post(f"{API}/me/contact-groups/resolve",
                     json={"contact_ids": [s["contact_id"]]},
                     headers={"Authorization": f"Bearer {s['token_b']}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["contact_ids"] == [s["contact_id"]]
    assert body["contacts"][0]["name"] == "Jean Dupont"
