"""Iter38q — Corbeille (archive) — irréversible, admin/sup only."""
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
    admin_id = f"q_adm_{uuid.uuid4().hex[:6]}"
    sup_id = f"q_sup_{uuid.uuid4().hex[:6]}"
    client_id = f"q_cli_{uuid.uuid4().hex[:6]}"
    company = f"Q-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin Q", "company": company, "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
         "full_name": "Sup Q", "company": company, "role": "superviseur",
         "account_status": "active", "created_at": now},
        {"id": client_id, "email": f"{client_id}@t.l", "password_hash": "x",
         "full_name": "Regular Q", "company": company, "role": "client",
         "tracked_user_id": admin_id,
         "account_status": "active", "created_at": now},
    ])
    cid = f"ct_{uuid.uuid4().hex[:8]}"
    db.directory_contacts.insert_one({
        "id": cid, "name": "Contact Q", "client_id": admin_id,
        "owner_id": admin_id, "phone": "+22675555555", "whatsapp": "+22675555555",
        "created_at": now,
    })
    yield {
        "admin_id": admin_id, "admin_token": _forge(admin_id, "admin"),
        "sup_token": _forge(sup_id, "superviseur"),
        "client_token": _forge(client_id, "client"),
        "cid": cid,
    }
    db.users.delete_many({"id": {"$in": [admin_id, sup_id, client_id]}})
    db.directory_contacts.delete_many({"client_id": admin_id})
    db.support_tickets.delete_many({"client_id": admin_id})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _make_open_ticket(db, admin_id, cid, number):
    tid = f"tk_{uuid.uuid4().hex[:8]}"
    db.support_tickets.insert_one({
        "id": tid, "number": number, "client_id": admin_id,
        "contact_id": cid, "contact_name": "Contact Q",
        "motif": "test", "status": "open",
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "opened_by_id": admin_id,
        "archived_at": None,
    })
    return tid


# ====================================================================
# Archive endpoint
# ====================================================================
def test_admin_can_archive_ticket(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0010")
    r = requests.post(f"{API}/me/tickets/{tid}/archive",
                      headers=_h(env["admin_token"]))
    assert r.status_code == 200, r.text
    t = db.support_tickets.find_one({"id": tid}, {"_id": 0})
    assert t["archived_at"] is not None
    assert t["archived_by_id"] == env["admin_id"]
    assert t["status"] == "closed"
    assert t["outcome"] == "archived_to_trash"


def test_sup_can_archive(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0011")
    r = requests.post(f"{API}/me/tickets/{tid}/archive",
                      headers=_h(env["sup_token"]))
    assert r.status_code == 200


def test_regular_client_cannot_archive(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0012")
    r = requests.post(f"{API}/me/tickets/{tid}/archive",
                      headers=_h(env["client_token"]))
    assert r.status_code == 403


def test_archived_excluded_from_list(env, db):
    tid_open = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0020")
    tid_arch = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0021")
    requests.post(f"{API}/me/tickets/{tid_arch}/archive", headers=_h(env["admin_token"]))
    # Normal listing should only return the live one
    r = requests.get(f"{API}/me/tickets", headers=_h(env["admin_token"]))
    assert r.status_code == 200
    numbers = [t["number"] for t in r.json()]
    assert "TKT-2026-0020" in numbers
    assert "TKT-2026-0021" not in numbers


def test_archived_excluded_from_active_ticket(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0030")
    requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]))
    r = requests.get(f"{API}/me/contacts/{env['cid']}/active-ticket",
                     headers=_h(env["admin_token"]))
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_archived_does_not_block_new_ticket(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0040")
    requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]))
    # Create new ticket succeeds
    r = requests.post(f"{API}/me/contacts/{env['cid']}/ticket",
        headers=_h(env["admin_token"]),
        json={"motif": "Nouveau", "client_id": env["admin_id"]})
    assert r.status_code == 200, r.text


def test_archived_ticket_cannot_be_reopened(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0050")
    requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]))
    # Try reopen — must fail with 409
    r = requests.post(f"{API}/me/tickets/{tid}/reopen",
        headers=_h(env["admin_token"]), json={"motif": "retry"})
    assert r.status_code == 409
    assert "corbeille" in r.json()["detail"].lower()


def test_archive_twice_idempotent_via_409(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0060")
    r1 = requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]))
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]))
    assert r2.status_code == 409
    assert "déjà" in r2.json()["detail"].lower() or "corbeille" in r2.json()["detail"].lower()


# ====================================================================
# Trash list endpoint
# ====================================================================
def test_trash_endpoint_returns_archived(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0070")
    requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]))
    r = requests.get(f"{API}/me/tickets/trash", headers=_h(env["admin_token"]))
    assert r.status_code == 200, r.text
    numbers = [t["number"] for t in r.json()]
    assert "TKT-2026-0070" in numbers


def test_trash_forbidden_for_regular_client(env, db):
    r = requests.get(f"{API}/me/tickets/trash", headers=_h(env["client_token"]))
    assert r.status_code == 403
