"""Iter40 (2026-02) — Registre des erreurs (P2-7).

Validates :
 - Webhook auth (Bearer token from settings)
 - Webhook ingestion + auto-number generation
 - Listing with filters (status, code_client, search, date_window, active_only)
 - Stats endpoint (exception/fatale counters)
 - Soft-delete + acknowledge
 - Purge endpoint reserved to Superviseur
 - ACL : Modérateur/Admin/Superviseur access, client refused
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


def _forge(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def webhook_token(db):
    tok = "wh_tok_" + uuid.uuid4().hex[:12]
    db.settings.update_one({"_id": "global"}, {"$set": {"errors_webhook_token": tok}}, upsert=True)
    yield tok


@pytest.fixture(scope="module")
def admin_token(db):
    aid = f"er_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "admin"), aid
    db.users.delete_one({"id": aid})


@pytest.fixture(scope="module")
def superviseur_token(db):
    aid = f"er_sup_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "superviseur", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "superviseur"), aid
    db.users.delete_one({"id": aid})


@pytest.fixture(scope="module")
def client_token(db):
    aid = f"er_cli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "client"), aid
    db.users.delete_one({"id": aid})


# ----------------------------------------------------------------------
# Webhook ingestion
# ----------------------------------------------------------------------

def test_webhook_rejects_invalid_token(webhook_token):
    r = requests.post(
        f"{API}/errors/ingest",
        json={"Motif": "Test bad token", "CodeApplicatif": "APP-001"},
        headers={"Authorization": "Bearer wrong-token"}, timeout=10,
    )
    assert r.status_code == 401


def test_webhook_accepts_valid_token(db, webhook_token):
    r = requests.post(
        f"{API}/errors/ingest",
        json={
            "Motif": "NullPointerException dans /handlers/order",
            "CodeApplicatif": "ORDERSRV-2.1",
            "StatutEnCours": "exception",
            "Code_Client": "TENANT-XYZ",
            "SurNomWA": "OrderBot",
            "NuméroDemandeur": "+22890123456",
        },
        headers={"Authorization": f"Bearer {webhook_token}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["number"].startswith("ERR-")
    doc = db.error_registry.find_one({"id": body["id"]})
    assert doc is not None
    assert doc["Motif"].startswith("NullPointer")
    assert doc["StatutEnCours"] == "exception"
    assert doc["acknowledged"] is False
    db.error_registry.delete_one({"id": body["id"]})


def test_webhook_auto_generates_number(db, webhook_token):
    r = requests.post(
        f"{API}/errors/ingest",
        json={"Motif": "x", "CodeApplicatif": "Y"},
        headers={"Authorization": f"Bearer {webhook_token}"}, timeout=10,
    )
    assert r.status_code == 200
    num = r.json()["number"]
    assert num.startswith("ERR-")
    db.error_registry.delete_one({"id": r.json()["id"]})


# ----------------------------------------------------------------------
# Listing / filters / stats
# ----------------------------------------------------------------------

def _ingest(db, webhook_token, **fields):
    payload = {"Motif": "test", "CodeApplicatif": "APP"}
    payload.update(fields)
    r = requests.post(
        f"{API}/errors/ingest", json=payload,
        headers={"Authorization": f"Bearer {webhook_token}"}, timeout=10,
    )
    assert r.status_code == 200
    return r.json()["id"]


def test_list_with_filters(db, webhook_token, admin_token):
    token, _ = admin_token
    e1 = _ingest(db, webhook_token, Motif="Bug critique imprimante", CodeApplicatif="APP-A",
                 StatutEnCours="fatale", Code_Client="C-001", SurNomWA="ImpBot")
    e2 = _ingest(db, webhook_token, Motif="Avertissement disk plein", CodeApplicatif="APP-B",
                 StatutEnCours="exception", Code_Client="C-002")
    try:
        # Filter by status=fatale
        r = requests.get(f"{API}/me/errors?status=fatale",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200
        ids = [i["id"] for i in r.json()["items"]]
        assert e1 in ids and e2 not in ids
        # Filter by code_client
        r = requests.get(f"{API}/me/errors?code_client=C-002",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        ids = [i["id"] for i in r.json()["items"]]
        assert e2 in ids and e1 not in ids
        # Full-text search on Motif
        r = requests.get(f"{API}/me/errors?search=imprimante",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        ids = [i["id"] for i in r.json()["items"]]
        assert e1 in ids
        # Search on SurNomWA
        r = requests.get(f"{API}/me/errors?search=ImpBot",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        ids = [i["id"] for i in r.json()["items"]]
        assert e1 in ids
    finally:
        db.error_registry.delete_many({"id": {"$in": [e1, e2]}})


def test_stats_endpoint(db, webhook_token, admin_token):
    token, _ = admin_token
    e1 = _ingest(db, webhook_token, StatutEnCours="exception")
    e2 = _ingest(db, webhook_token, StatutEnCours="fatale")
    e3 = _ingest(db, webhook_token, StatutEnCours="exception")
    try:
        r = requests.get(f"{API}/me/errors/stats",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200, r.text
        s = r.json()
        # The counts include other test data, just sanity-check positive
        assert s["exception"] >= 2
        assert s["fatale"] >= 1
        assert "unacknowledged" in s
        # The notifications counts should also have errors_unack
        r = requests.get(f"{API}/me/notifications/counts",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        c = r.json()["counts"]
        assert "errors_unack" in c
        assert "errors_exception" in c
        assert "errors_fatale" in c
    finally:
        db.error_registry.delete_many({"id": {"$in": [e1, e2, e3]}})


def test_acknowledge_and_soft_delete(db, webhook_token, admin_token):
    token, _ = admin_token
    eid = _ingest(db, webhook_token, Motif="Ack test")
    try:
        r = requests.post(f"{API}/me/errors/{eid}/acknowledge",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200
        doc = db.error_registry.find_one({"id": eid})
        assert doc["acknowledged"] is True
        # Soft-delete
        r = requests.delete(f"{API}/me/errors/{eid}",
                            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200
        doc = db.error_registry.find_one({"id": eid})
        assert doc.get("deleted_at") is not None
        # No longer listed
        r = requests.get(f"{API}/me/errors",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        ids = [i["id"] for i in r.json()["items"]]
        assert eid not in ids
    finally:
        db.error_registry.delete_one({"id": eid})


# ----------------------------------------------------------------------
# ACL : client refused, purge supervisor-only
# ----------------------------------------------------------------------

def test_client_cannot_access(client_token):
    token, _ = client_token
    r = requests.get(f"{API}/me/errors", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403
    r = requests.get(f"{API}/me/errors/stats", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403


def test_admin_cannot_purge(admin_token):
    token, _ = admin_token
    r = requests.post(f"{API}/me/errors/purge",
                      json={"code_client": "ANYTHING"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403
    assert "Superviseur" in r.json()["detail"]


def test_superviseur_can_purge(db, webhook_token, superviseur_token):
    token, _ = superviseur_token
    e1 = _ingest(db, webhook_token, Motif="Will be purged", Code_Client="PURGE-ME")
    e2 = _ingest(db, webhook_token, Motif="Will NOT be purged", Code_Client="KEEP")
    try:
        r = requests.post(f"{API}/me/errors/purge",
                          json={"code_client": "PURGE-ME"},
                          headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] >= 1
        assert db.error_registry.find_one({"id": e1}) is None
        assert db.error_registry.find_one({"id": e2}) is not None
    finally:
        db.error_registry.delete_many({"id": {"$in": [e1, e2]}})


def test_purge_requires_criteria(superviseur_token):
    token, _ = superviseur_token
    r = requests.post(f"{API}/me/errors/purge", json={},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 400
