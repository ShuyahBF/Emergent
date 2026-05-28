"""Iter38r-fix3 — Tests for:
  1. /me/tickets/{tid}/archive with also_unlink=true (Bug Corbeille orphans)
  2. /api/meta/webhook routes WhatsApp Cloud payloads via object detection
     (Bug WhatsApp messages stop arriving after Meta install)
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
def env(db):
    admin_id = f"fix3_adm_{uuid.uuid4().hex[:6]}"
    company = f"FX3-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "full_name": "Admin FX3", "company": company, "role": "admin",
        "account_status": "active", "created_at": now,
    })
    cid = f"ct_{uuid.uuid4().hex[:8]}"
    db.directory_contacts.insert_one({
        "id": cid, "name": "Contact FX3", "client_id": admin_id,
        "owner_id": admin_id, "phone": "+22675001234", "whatsapp": "+22675001234",
        "created_at": now,
    })
    yield {
        "admin_id": admin_id,
        "admin_token": _forge(admin_id, "admin"),
        "cid": cid,
    }
    db.users.delete_many({"id": admin_id})
    db.directory_contacts.delete_many({"client_id": admin_id})
    db.support_tickets.delete_many({"client_id": admin_id})


def _h(tok): return {"Authorization": f"Bearer {tok}"}


def _make_open_ticket(db, admin_id, cid, number):
    tid = f"tk_{uuid.uuid4().hex[:8]}"
    db.support_tickets.insert_one({
        "id": tid, "number": number, "client_id": admin_id,
        "contact_id": cid, "contact_name": "Contact FX3",
        "motif": "test", "status": "open",
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "opened_by_id": admin_id,
        "archived_at": None,
    })
    return tid


# ====================================================================
# 1) Archive with also_unlink=true
# ====================================================================
def test_archive_without_unlink_keeps_contact_id(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0100")
    r = requests.post(
        f"{API}/me/tickets/{tid}/archive",
        headers=_h(env["admin_token"]),
        json={"also_unlink": False},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("unlinked") is False
    doc = db.support_tickets.find_one({"id": tid}, {"_id": 0})
    assert doc["contact_id"] == env["cid"]  # contact_id intact
    assert doc["archived_at"]


def test_archive_with_unlink_clears_contact_id(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0101")
    r = requests.post(
        f"{API}/me/tickets/{tid}/archive",
        headers=_h(env["admin_token"]),
        json={"also_unlink": True},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("unlinked") is True
    doc = db.support_tickets.find_one({"id": tid}, {"_id": 0})
    assert doc["contact_id"] is None  # cleared
    assert doc["archived_contact_id"] == env["cid"]  # audit preserved
    assert doc["unlinked_at"]
    assert doc["unlinked_by_id"] == env["admin_id"]


def test_archive_already_archived_with_unlink_releases_contact(env, db):
    """If a ticket is already archived but still has its contact_id set
    (legacy bug), passing also_unlink=true should release the contact
    instead of returning 409."""
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0102")
    # First archive WITHOUT unlink
    requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]), json={"also_unlink": False})
    # Now try to unlink retroactively
    r = requests.post(
        f"{API}/me/tickets/{tid}/archive",
        headers=_h(env["admin_token"]),
        json={"also_unlink": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("already_archived") is True
    assert body.get("unlinked") is True
    doc = db.support_tickets.find_one({"id": tid}, {"_id": 0})
    assert doc["contact_id"] is None
    assert doc["archived_contact_id"] == env["cid"]


def test_archive_already_archived_without_unlink_returns_409(env, db):
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0103")
    requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]), json={})
    r = requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]), json={})
    assert r.status_code == 409


def test_archive_without_body_still_works(env, db):
    """Backwards compatibility — clients pre-Iter38r-fix3 sending no body."""
    tid = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0104")
    r = requests.post(f"{API}/me/tickets/{tid}/archive", headers=_h(env["admin_token"]))
    assert r.status_code == 200, r.text
    doc = db.support_tickets.find_one({"id": tid}, {"_id": 0})
    assert doc["archived_at"]
    assert doc["contact_id"] == env["cid"]  # unchanged when no body


def test_archive_unlink_releases_contact_for_new_ticket(env, db):
    """The whole point of also_unlink: after the archive, the contact
    must be free to receive a fresh new ticket without any blocker."""
    tid_old = _make_open_ticket(db, env["admin_id"], env["cid"], "TKT-2026-0105")
    requests.post(
        f"{API}/me/tickets/{tid_old}/archive",
        headers=_h(env["admin_token"]),
        json={"also_unlink": True},
    )
    # Active-ticket lookup for this contact must return active=False
    r = requests.get(
        f"{API}/me/contacts/{env['cid']}/active-ticket",
        headers=_h(env["admin_token"]),
    )
    assert r.status_code == 200
    assert r.json()["active"] is False
    # Create a fresh ticket — must succeed
    r2 = requests.post(
        f"{API}/me/contacts/{env['cid']}/ticket",
        headers=_h(env["admin_token"]),
        json={"motif": "Nouveau", "client_id": env["admin_id"]},
    )
    assert r2.status_code == 200, r2.text


# ====================================================================
# 2) /api/meta/webhook routes WhatsApp payloads
# ====================================================================
def test_meta_webhook_routes_whatsapp_payload(env, db):
    """When Meta delivers a WhatsApp Cloud payload (object='whatsapp_business_account')
    to /api/meta/webhook, the handler should detect it and forward to the
    WhatsApp Cloud logic, persisting the inbound message into
    `db.whatsapp_messages`."""
    # Need at least one superviseur so the WA handler can attribute client_scope.
    sup_id = env["admin_id"]  # our admin has role='admin', not 'superviseur'.
    # Create a superviseur user temporarily
    sup_real = f"fix3_sup_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": sup_real, "email": f"{sup_real}@t.l", "password_hash": "x",
        "full_name": "Sup FX3", "role": "superviseur",
        "account_status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        unique_msg_id = f"wamid.FIX3-{uuid.uuid4().hex[:12]}"
        unique_phone = "22675" + str(uuid.uuid4().int)[:6]
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "fake_waba_id",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "fake_phone_id"},
                        "contacts": [{"profile": {"name": "Test FX3"}, "wa_id": unique_phone}],
                        "messages": [{
                            "from": unique_phone,
                            "id": unique_msg_id,
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "type": "text",
                            "text": {"body": "Hello from fix3 routing test"},
                        }],
                    },
                    "field": "messages",
                }],
            }],
        }
        r = requests.post(f"{API}/meta/webhook", json=payload, timeout=15)
        # Should NOT be 403 (the WA branch bypasses the Meta HMAC check)
        assert r.status_code != 403, r.text
        # Verify the message was actually persisted
        doc = db.whatsapp_messages.find_one({"wa_message_id": unique_msg_id}, {"_id": 0})
        assert doc is not None, "WhatsApp message must be persisted via /meta/webhook routing"
        assert doc["direction"] == "inbound"
        assert doc["body"] == "Hello from fix3 routing test"
    finally:
        db.users.delete_one({"id": sup_real})
        db.whatsapp_messages.delete_many({"wa_message_id": {"$regex": "^wamid.FIX3-"}})


def test_meta_webhook_verify_accepts_wa_verify_token(env, db):
    """GET /api/meta/webhook must accept the wa_verify_token as a fallback
    so the same URL can be used for both Messenger and WhatsApp Cloud
    subscriptions when the user enters wa_verify_token in Meta App config."""
    original = db.settings.find_one({"_id": "global"}) or {}
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "wa_verify_token": "wa-token-fix3",
            "meta_webhook_verify_token": "meta-token-fix3",
        }},
        upsert=True,
    )
    try:
        # WA token must succeed
        r1 = requests.get(
            f"{API}/meta/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "wa-token-fix3",
                    "hub.challenge": "challenge-wa-fix3"},
        )
        assert r1.status_code == 200, r1.text
        assert r1.text == "challenge-wa-fix3"
        # Meta token must also succeed
        r2 = requests.get(
            f"{API}/meta/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "meta-token-fix3",
                    "hub.challenge": "challenge-meta-fix3"},
        )
        assert r2.status_code == 200
        # Wrong token must 403
        r3 = requests.get(
            f"{API}/meta/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong",
                    "hub.challenge": "x"},
        )
        assert r3.status_code == 403
    finally:
        if original:
            db.settings.replace_one({"_id": "global"}, original, upsert=True)
