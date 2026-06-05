"""Iter40 — Liluvine PRO Business RAG + ACL par module (Task 1).

Validates :
 - Admin can GET/PUT /api/admin/liluvine-pro/module-acl
 - Non-admin gets 403
 - ACL normalizes phones to digits
 - detect_intents() spots all 6 modules
 - build_business_rag_context() respects ACL whitelist
 - _phone_in_acl() matches last 9 digits with country code variants
 - detect_ticket_command() detects !ticket
 - handle_ticket_command() refused when phone not in tickets ACL
"""
from __future__ import annotations

import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient

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
def motor_db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def admin_token(db):
    admin_id = f"acl_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin"), admin_id
    db.users.delete_one({"id": admin_id})


@pytest.fixture
def client_token(db):
    cid = f"acl_cli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": cid, "email": f"{cid}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(cid, "client"), cid
    db.users.delete_one({"id": cid})


# ----------------------------------------------------------------------
# Admin ACL endpoints
# ----------------------------------------------------------------------

def test_admin_can_get_acl(admin_token):
    token, _ = admin_token
    r = requests.get(
        f"{API}/admin/liluvine-pro/module-acl",
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "modules" in body and "acl" in body
    assert set(body["modules"]) == {"rdv", "tickets", "hr", "caisse", "payments", "contacts"}


def test_client_forbidden_acl(client_token):
    token, _ = client_token
    r = requests.get(
        f"{API}/admin/liluvine-pro/module-acl",
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 403, r.text
    r2 = requests.put(
        f"{API}/admin/liluvine-pro/module-acl",
        json={"acl": {"rdv": ["+22890123456"]}},
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r2.status_code == 403, r2.text


def test_admin_put_acl_normalizes_digits(admin_token, db):
    token, _ = admin_token
    payload = {
        "acl": {
            "rdv": ["+228 90 12 34 56", "228 90 12 34 56"],  # duplicate after norm
            "hr": ["00 22890123456"],
            "tickets": [],
            "unknown_module": ["+22890123456"],  # should be dropped
        }
    }
    r = requests.put(
        f"{API}/admin/liluvine-pro/module-acl",
        json=payload,
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    acl = r.json()["acl"]
    # Both formats normalized to "22890123456" → de-duped to one entry
    assert acl["rdv"] == ["22890123456"], acl["rdv"]
    assert "00022890123456" in acl["hr"] or "0022890123456" in acl["hr"] or any("22890123456" in x for x in acl["hr"])
    assert acl["tickets"] == []
    assert "unknown_module" not in acl  # invalid module ignored


# ----------------------------------------------------------------------
# Detect intents
# ----------------------------------------------------------------------

def test_detect_intents_matches_modules():
    from routes.liluvine_business_rag import detect_intents
    assert "rdv" in detect_intents("Quels sont mes prochains rendez-vous ?")
    assert "tickets" in detect_intents("J'ai un incident à signaler")
    assert "hr" in detect_intents("Combien me reste-t-il de congés ?")
    assert "caisse" in detect_intents("Quel est le total caisse du jour ?")
    assert "payments" in detect_intents("Combien de paiements aujourd'hui ?")
    assert "contacts" in detect_intents("Je cherche un contact Martin")
    assert detect_intents("blabla random text") == []


# ----------------------------------------------------------------------
# ACL phone matching helper
# ----------------------------------------------------------------------

def test_phone_in_acl_matches_last_9_digits():
    from routes.liluvine_business_rag import _phone_in_acl
    assert _phone_in_acl("22890123456", ["22890123456"]) is True
    # With or without country code prefix → still matches last 9 digits
    assert _phone_in_acl("0022890123456", ["22890123456"]) is True
    assert _phone_in_acl("22890123456", ["+228 90 12 34 56".replace(" ", "").replace("+", "")]) is True
    # Different number → no match
    assert _phone_in_acl("22899999999", ["22890123456"]) is False
    # Empty inputs
    assert _phone_in_acl("", ["22890123456"]) is False
    assert _phone_in_acl("22890123456", []) is False


# ----------------------------------------------------------------------
# build_business_rag_context respects ACL
# ----------------------------------------------------------------------

def test_context_empty_when_phone_not_in_acl(db, motor_db, admin_token):
    """If no module has the caller's phone whitelisted, context = empty."""
    token, _ = admin_token
    # Reset ACL
    requests.put(
        f"{API}/admin/liluvine-pro/module-acl",
        json={"acl": {"rdv": ["12345678999"]}},  # not our test phone
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    from routes.liluvine_business_rag import build_business_rag_context
    ctx = asyncio.run(build_business_rag_context(
        motor_db, phone_digits="22890000111", query="Quels sont mes prochains RDV ?",
    ))
    assert ctx == ""


def test_context_returned_when_phone_in_acl(db, motor_db, admin_token):
    """When the caller's phone is in the rdv ACL, RDV section is injected."""
    token, _ = admin_token
    test_phone = "22890765432"
    # Seed: whitelist this phone for rdv
    requests.put(
        f"{API}/admin/liluvine-pro/module-acl",
        json={"acl": {"rdv": [test_phone]}},
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    # Seed: user matching phone + an appointment
    uid = f"rdv_u_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "admin", "phone": "+" + test_phone,
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    appt_id = f"rdv_appt_{uuid.uuid4().hex[:6]}"
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    db.appointments.insert_one({
        "id": appt_id, "client_id": uid, "title": "Demo Liluvine RAG",
        "scheduled_at": future, "duration_min": 30,
        "status": "confirmed", "contact_name": "Test Client",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        from routes.liluvine_business_rag import build_business_rag_context
        ctx = asyncio.run(build_business_rag_context(
            motor_db, phone_digits=test_phone, query="Mes prochains RDV ?",
        ))
        assert "CONTEXTE MÉTIER" in ctx, ctx
        assert "Demo Liluvine RAG" in ctx
    finally:
        db.appointments.delete_one({"id": appt_id})
        db.users.delete_one({"id": uid})


# ----------------------------------------------------------------------
# Ticket command
# ----------------------------------------------------------------------

def test_detect_ticket_command():
    from routes.liluvine_business_rag import detect_ticket_command
    assert detect_ticket_command("!ticket Imprimante en panne au bureau 3") is True
    assert detect_ticket_command("/ticket nouveau souci avec la base de données") is True
    assert detect_ticket_command("!ticket open Réinitialisation mot de passe Caisse") is True
    assert detect_ticket_command("Bonjour je voudrais ouvrir un ticket") is False
    assert detect_ticket_command("!absence 2026-03-01") is False


def test_handle_ticket_command_refused_when_phone_not_in_acl(db, motor_db, admin_token):
    token, _ = admin_token
    # Reset ACL — tickets empty
    requests.put(
        f"{API}/admin/liluvine-pro/module-acl",
        json={"acl": {"tickets": []}},
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    from routes.liluvine_business_rag import handle_ticket_command
    res = asyncio.run(handle_ticket_command(
        motor_db, phone_digits="22899999999",
        text="!ticket Demande non autorisée",
    ))
    assert res["ok"] is False
    assert res["reason"] == "acl_denied"


def test_handle_ticket_command_creates_when_allowed(db, motor_db, admin_token):
    token, adm_id = admin_token
    test_phone = "22890987654"
    requests.put(
        f"{API}/admin/liluvine-pro/module-acl",
        json={"acl": {"tickets": [test_phone]}},
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    # User with that phone exists for tenant resolution
    uid = f"tk_u_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "admin", "phone": "+" + test_phone, "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        from routes.liluvine_business_rag import handle_ticket_command
        res = asyncio.run(handle_ticket_command(
            motor_db, phone_digits=test_phone,
            text="!ticket Imprimante en panne bureau 3",
        ))
        assert res["ok"] is True
        assert res["number"].startswith("TKT-")
        assert "Imprimante" in res["user_reply"]
        # Cleanup
        db.support_tickets.delete_one({"id": res["id"]})
    finally:
        db.users.delete_one({"id": uid})
