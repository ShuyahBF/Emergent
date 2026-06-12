"""Iter43 (2026-03) — Tests pour :
  - /api/errors/ingest unwrap auto (Aizenta TicketDemnde, Biolog Erreur, flat)
  - /api/me/errors/bulk-delete + /me/errors/reset (admin/sup only)
  - /api/me/tickets/bulk-delete + /me/tickets/reset (admin/sup only)
  - /api/admin/error-registry/migrate-from-tickets (idempotent)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
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
def admin_user(db):
    aid = f"iter43_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@adm.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield aid
    db.users.delete_one({"id": aid})


@pytest.fixture(scope="module")
def superviseur_user(db):
    sid = f"iter43_sup_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": sid, "email": f"{sid}@sup.com", "password_hash": "x",
        "role": "superviseur", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield sid
    db.users.delete_one({"id": sid})


@pytest.fixture(scope="module")
def client_user(db):
    cid = f"iter43_cli_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": cid, "email": f"{cid}@cli.com", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield cid
    db.users.delete_one({"id": cid})


# =========================================================== #
# 1) /api/errors/ingest — unwrap auto
# =========================================================== #
def test_errors_ingest_flat_format(db):
    """Format historique plat — toujours accepté."""
    db.settings.update_one({"_id": "global"}, {"$unset": {"errors_webhook_token": ""}}, upsert=True)
    r = requests.post(f"{API}/errors/ingest", json={
        "Motif": "Erreur test plat",
        "CodeApplicatif": "TST",
        "Code_Client": "T01",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    eid = body["id"]
    try:
        doc = db.error_registry.find_one({"id": eid})
        assert doc is not None
        assert doc["Motif"] == "Erreur test plat"
        assert doc["CodeApplicatif"] == "TST"
    finally:
        db.error_registry.delete_one({"id": eid})


def test_errors_ingest_aizenta_wrapper(db):
    """Format Aizenta {TicketDemnde: {...}} doit être unwrap auto."""
    db.settings.update_one({"_id": "global"}, {"$unset": {"errors_webhook_token": ""}}, upsert=True)
    payload = {
        "TicketDemnde": {
            "IDTicketDemnde": "test-aizenta-uuid",
            "Motif": "Erreur d'écriture port n°1",
            "CodeApplicatif": "WAB",
            "Code_Client": "AMY",
            "TypeTicket": "Erreur [Aizenta",
            "CompteClient": "PHCIE AMITIE MIYOUGOU",
            "StatutEnCours": "EN ATTENTE",
        },
    }
    r = requests.post(f"{API}/errors/ingest", json=payload)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    try:
        doc = db.error_registry.find_one({"id": eid})
        assert doc["Motif"] == "Erreur d'écriture port n°1"
        assert doc["CodeApplicatif"] == "WAB"
        assert doc["Code_Client"] == "AMY"
        assert doc["CompteClient"] == "PHCIE AMITIE MIYOUGOU"
        assert doc["TypeTicket"] == "Erreur [Aizenta"
        assert doc["IDTicketDemnde"] == "test-aizenta-uuid"
    finally:
        db.error_registry.delete_one({"id": eid})


def test_errors_ingest_biolog_wrapper(db):
    """Format Biolog {Erreur: {...}} doit aussi être unwrap auto."""
    db.settings.update_one({"_id": "global"}, {"$unset": {"errors_webhook_token": ""}}, upsert=True)
    payload = {
        "Erreur": {
            "Motif": "Crash module bio",
            "CodeApplicatif": "BIOLOG",
            "Code_Client": "BIO",
            "StatutEnCours": "fatale",
        },
    }
    r = requests.post(f"{API}/errors/ingest", json=payload)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    try:
        doc = db.error_registry.find_one({"id": eid})
        assert doc["Motif"] == "Crash module bio"
        assert doc["CodeApplicatif"] == "BIOLOG"
    finally:
        db.error_registry.delete_one({"id": eid})


# =========================================================== #
# 2) Bulk delete — Errors
# =========================================================== #
def test_errors_bulk_delete_admin(db, admin_user):
    db.settings.update_one({"_id": "global"}, {"$unset": {"errors_webhook_token": ""}}, upsert=True)
    # Crée 3 erreurs
    ids = []
    for i in range(3):
        r = requests.post(f"{API}/errors/ingest", json={
            "Motif": f"Test bulk {i}", "CodeApplicatif": "T",
        })
        assert r.status_code == 200
        ids.append(r.json()["id"])
    tok = _forge(admin_user, "admin")
    r = requests.post(f"{API}/me/errors/bulk-delete",
                      json={"ids": ids[:2]},
                      headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 2
    # Le 3e reste
    assert db.error_registry.find_one({"id": ids[2]}) is not None
    db.error_registry.delete_one({"id": ids[2]})


def test_errors_bulk_delete_client_blocked(db, client_user):
    db.settings.update_one({"_id": "global"}, {"$unset": {"errors_webhook_token": ""}}, upsert=True)
    r = requests.post(f"{API}/errors/ingest", json={"Motif": "x", "CodeApplicatif": "x"})
    eid = r.json()["id"]
    tok = _forge(client_user, "client")
    r = requests.post(f"{API}/me/errors/bulk-delete",
                      json={"ids": [eid]},
                      headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    db.error_registry.delete_one({"id": eid})


def test_errors_reset_all(db, superviseur_user):
    db.settings.update_one({"_id": "global"}, {"$unset": {"errors_webhook_token": ""}}, upsert=True)
    # Crée quelques erreurs
    for i in range(2):
        requests.post(f"{API}/errors/ingest", json={"Motif": f"reset {i}", "CodeApplicatif": "X"})
    before = db.error_registry.count_documents({})
    assert before >= 2
    tok = _forge(superviseur_user, "superviseur")
    r = requests.post(f"{API}/me/errors/reset", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] >= 2
    assert db.error_registry.count_documents({}) == 0


# =========================================================== #
# 3) Bulk delete — Tickets
# =========================================================== #
def test_tickets_bulk_delete_admin(db, admin_user):
    # Insère 3 tickets directement
    ids = []
    for i in range(3):
        tid = str(uuid.uuid4())
        db.support_tickets.insert_one({
            "id": tid, "number": f"BULK-{i}",
            "client_id": admin_user, "motif": f"test {i}",
            "status": "open", "opened_at": datetime.now(timezone.utc).isoformat(),
        })
        ids.append(tid)
    tok = _forge(admin_user, "admin")
    r = requests.post(f"{API}/me/tickets/bulk-delete",
                      json={"ids": ids[:2]},
                      headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 2
    assert db.support_tickets.count_documents({"id": {"$in": ids}}) == 1
    db.support_tickets.delete_one({"id": ids[2]})


def test_tickets_bulk_delete_client_blocked(db, client_user):
    tid = str(uuid.uuid4())
    db.support_tickets.insert_one({
        "id": tid, "number": "NOPE", "client_id": client_user,
        "status": "open", "opened_at": datetime.now(timezone.utc).isoformat(),
    })
    tok = _forge(client_user, "client")
    r = requests.post(f"{API}/me/tickets/bulk-delete",
                      json={"ids": [tid]},
                      headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    db.support_tickets.delete_one({"id": tid})


# =========================================================== #
# 4) Migration tickets → error_registry
# =========================================================== #
def test_migrate_tickets_to_error_registry(db, admin_user):
    # Vide d'abord
    db.error_registry.delete_many({})
    db.support_tickets.delete_many({"channel": "webhook"})
    # Insère 2 tickets webhook avec metadata Aizenta
    for i in range(2):
        tid = str(uuid.uuid4())
        db.support_tickets.insert_one({
            "id": tid, "number": f"SUP-MIG-{i}",
            "channel": "webhook", "client_id": None,
            "motif": f"motif {i}", "description": f"desc {i}",
            "status": "open", "opened_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "IDTicketDemnde": f"aizenta-mig-{i}",
                "Motif": f"Erreur {i}",
                "CodeApplicatif": "WAB",
                "Code_Client": "AMY",
                "CompteClient": "Pharmacie test",
                "TypeTicket": "Erreur",
                "StatutEnCours": "EN ATTENTE",
            },
        })
    tok = _forge(admin_user, "admin")
    r = requests.post(f"{API}/admin/error-registry/migrate-from-tickets",
                      headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["migrated"] == 2
    assert body["skipped_already"] == 0
    # Re-run → idempotent (skipped)
    r2 = requests.post(f"{API}/admin/error-registry/migrate-from-tickets",
                       headers={"Authorization": f"Bearer {tok}"})
    assert r2.json()["migrated"] == 0
    assert r2.json()["skipped_already"] == 2
    # Vérifie le contenu
    docs = list(db.error_registry.find({}, {"_id": 0}))
    assert len(docs) == 2
    for d in docs:
        assert d["CodeApplicatif"] == "WAB"
        assert d["Code_Client"] == "AMY"
        assert d.get("migrated_from_ticket_id")
    # Cleanup
    db.error_registry.delete_many({})
    db.support_tickets.delete_many({"channel": "webhook"})
