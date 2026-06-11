"""Iter42d (2026-02) — Tests pour :
  - Webhook entrant /api/public/incidents (mot de passe simple)
  - Lookup AMM /api/officines-portal/inventory/lookup-amm
  - country_code sur les AMM (auto depuis settings.amm_default_country)
"""
from __future__ import annotations

import os
import secrets
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


def _forge_admin(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def _forge_officine(oid: str) -> str:
    return pyjwt.encode({
        "sub": f"officine:{oid}", "officine_id": oid,
        "aud": "officine-portal",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    aid = f"iter42d_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@admintest.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge_admin(aid), aid
    db.users.delete_one({"id": aid})


@pytest.fixture()
def active_officine(db):
    oid = f"off42d-{uuid.uuid4().hex[:8]}"
    db.officines.insert_one({
        "id": oid, "name": "Test Pharma 42d",
        "email": f"{oid}@officinetest.com", "phone": f"+22507{uuid.uuid4().int % 10000000:07d}",
        "phone_digits": "22507" + f"{uuid.uuid4().int % 10000000:07d}",
        "status": "active",
        "created_at": datetime.now(timezone.utc),
    })
    yield oid
    db.officines.delete_one({"id": oid})


# =========================================================== #
# 1) Webhook incidents
# =========================================================== #
def test_incidents_webhook_unconfigured_returns_503(db, admin_token):
    # Désactive d'abord
    db.settings.update_one({"_id": "global"}, {"$unset": {"incidents_webhook_password": ""}})
    r = requests.post(f"{API}/public/incidents", json={"title": "Test", "password": "x"})
    assert r.status_code == 503


def test_incidents_webhook_regenerate_and_post(db, admin_token):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    # Régénération password (one-shot display)
    r = requests.post(f"{API}/admin/incidents-webhook/regenerate-password", headers=H)
    assert r.status_code == 200
    password = r.json()["password"]
    assert len(password) > 20

    # GET admin info → configured=True
    info = requests.get(f"{API}/admin/incidents-webhook", headers=H).json()
    assert info["configured"] is True
    assert info["url"] == "/api/public/incidents"

    # POST sans password → 401
    r = requests.post(f"{API}/public/incidents", json={"title": "Outage prod"})
    assert r.status_code == 401

    # POST avec mauvais password → 401
    r = requests.post(f"{API}/public/incidents", json={"title": "Outage prod", "password": "wrong"})
    assert r.status_code == 401

    # POST avec bon password dans body → 200
    r = requests.post(f"{API}/public/incidents", json={
        "title": "Outage prod DB", "description": "Mongo unreachable",
        "severity": "critical", "source": "watchdog-prod",
        "password": password,
        "metadata": {"region": "eu-west-1", "duration_s": 120},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["severity"] == "critical"
    ticket_id = body["ticket_id"]
    ticket_no = body["ticket_number"]
    try:
        # Vérifie dans support_tickets
        t = db.support_tickets.find_one({"id": ticket_id})
        assert t is not None
        assert t["severity"] == "critical"
        assert t["channel"] == "webhook"
        assert t["source"] == "watchdog-prod"
        assert "Outage prod DB" in t["motif"]
        assert "eu-west-1" in t.get("description", "")
    finally:
        db.support_tickets.delete_one({"id": ticket_id})

    # POST avec password dans header → 200
    r = requests.post(f"{API}/public/incidents",
                      headers={"X-Webhook-Password": password, "Content-Type": "application/json"},
                      json={"title": "Header auth test", "severity": "low"})
    assert r.status_code == 200
    db.support_tickets.delete_one({"id": r.json()["ticket_id"]})


def test_incidents_webhook_disable(db, admin_token):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    # Régénère pour activer
    r = requests.post(f"{API}/admin/incidents-webhook/regenerate-password", headers=H)
    assert r.status_code == 200
    # Désactive
    r = requests.delete(f"{API}/admin/incidents-webhook/password", headers=H)
    assert r.status_code == 200
    # POST → 503
    r = requests.post(f"{API}/public/incidents", json={"title": "test disable", "password": "x"})
    assert r.status_code == 503


def test_incidents_webhook_aizenta_format(db, admin_token):
    """Iter43 (2026-03) — Le webhook doit accepter le format Aizenta
    `{TicketDemnde: {...}}` et le mapper automatiquement vers le format interne."""
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}/admin/incidents-webhook/regenerate-password", headers=H)
    assert r.status_code == 200
    password = r.json()["password"]

    aizenta_payload = {
        "TicketDemnde": {
            "IDTicketDemnde": "44ce72d0-40d2-45b6-bd15-907d73c0bfef",
            "TypeTicket": "Erreur [Aizenta",
            "CompteClient": "PHCIE AMITIE MIYOUGOU",
            "Motif": "AMY:Erreur d'écriture sur le port n°1\r\nCode erreur : 1",
            "Code_Client": "AMY",
            "CodeApplicatif": "WAB",
            "Numéro_Généré": "2026-ASI31103",
            "NuméroDemandeur": "22625385236",
            "StatutEnCours": "EN ATTENTE",
        },
    }
    r = requests.post(
        f"{API}/public/incidents",
        headers={"X-Webhook-Password": password, "Content-Type": "application/json"},
        json=aizenta_payload,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # Sévérité "high" déduite du mot "Erreur" dans TypeTicket/Motif
    assert body["severity"] == "high"
    ticket_id = body["ticket_id"]
    try:
        t = db.support_tickets.find_one({"id": ticket_id})
        assert t is not None
        assert t["channel"] == "webhook"
        # Source = "AMY/WAB"
        assert t["source"] == "AMY/WAB"
        # Titre contient le numéro Aizenta + Type + Compte
        assert "2026-ASI31103" in t["motif"]
        assert "PHCIE AMITIE MIYOUGOU" in t["motif"]
        # Le Motif Aizenta entier est dans la description
        assert "Erreur d'écriture sur le port" in t["description"]
        # Le bloc TicketDemnde brut est dans metadata pour traçabilité
        assert t["metadata"]["IDTicketDemnde"] == "44ce72d0-40d2-45b6-bd15-907d73c0bfef"
        assert t["metadata"]["NuméroDemandeur"] == "22625385236"
    finally:
        db.support_tickets.delete_one({"id": ticket_id})


def test_incidents_webhook_aizenta_password_in_body(db, admin_token):
    """Le password peut aussi être passé dans le body racine pour Aizenta."""
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}/admin/incidents-webhook/regenerate-password", headers=H)
    password = r.json()["password"]

    payload = {
        "password": password,
        "TicketDemnde": {
            "TypeTicket": "Info",
            "CompteClient": "Test Client",
            "Motif": "Petit log",
            "Code_Client": "TST",
        },
    }
    r = requests.post(f"{API}/public/incidents", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    # Pas de mot "erreur" → severity medium
    assert body["severity"] == "medium"
    db.support_tickets.delete_one({"id": body["ticket_id"]})




# =========================================================== #
# 2) Lookup AMM
# =========================================================== #
def test_lookup_amm_found_with_country(db, active_officine):
    oid = active_officine
    tok = _forge_officine(oid)
    H = {"Authorization": f"Bearer {tok}"}
    # Configure default country
    db.settings.update_one({"_id": "global"}, {"$set": {"amm_default_country": "BF"}}, upsert=True)
    # Insère un AMM dans le bon pays
    amm_id = f"amm42d-{uuid.uuid4().hex[:6]}"
    db.amm_numbers.insert_one({
        "id": amm_id, "internal_no": f"INT-{uuid.uuid4().hex[:8].upper()}",
        "product_name": "Doliprane Test",
        "amm_number": f"BF-{uuid.uuid4().hex[:6]}",
        "country_code": "BF", "cip1": "3400930999111",
        "laboratory": "Sanofi BF", "status": "active",
        "expires_at": "2030-12-31",
        "source": "manual", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(f"{API}/officines-portal/inventory/lookup-amm",
                          headers=H, json={"cip": "3400930999111"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["found"] is True
        assert body["country"] == "BF"
        assert body["product_name"] == "Doliprane Test"
        assert body["status"] == "active"
        assert body["expired"] is False
    finally:
        db.amm_numbers.delete_one({"id": amm_id})


def test_lookup_amm_not_found_returns_friendly_message(db, active_officine):
    oid = active_officine
    tok = _forge_officine(oid)
    H = {"Authorization": f"Bearer {tok}"}
    db.settings.update_one({"_id": "global"}, {"$set": {"amm_default_country": "BF"}}, upsert=True)
    r = requests.post(f"{API}/officines-portal/inventory/lookup-amm",
                      headers=H, json={"cip": "9999999999999"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert "Aucun AMM trouvé" in body["message"]


def test_lookup_amm_detects_expired(db, active_officine):
    oid = active_officine
    tok = _forge_officine(oid)
    H = {"Authorization": f"Bearer {tok}"}
    db.settings.update_one({"_id": "global"}, {"$set": {"amm_default_country": "BF"}}, upsert=True)
    amm_id = f"amm42d-exp-{uuid.uuid4().hex[:6]}"
    db.amm_numbers.insert_one({
        "id": amm_id, "internal_no": f"INT-{uuid.uuid4().hex[:8].upper()}",
        "product_name": "Expired Drug",
        "amm_number": f"BF-EXP-{uuid.uuid4().hex[:6]}",
        "country_code": "BF", "cip1": "3400930888222",
        "status": "active",
        "expires_at": "2020-01-01",  # passé
        "source": "manual", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(f"{API}/officines-portal/inventory/lookup-amm",
                          headers=H, json={"cip": "3400930888222"})
        assert r.status_code == 200
        body = r.json()
        assert body["found"] is True
        assert body["expired"] is True
    finally:
        db.amm_numbers.delete_one({"id": amm_id})


# =========================================================== #
# 3) country_code sur AMM (auto depuis settings)
# =========================================================== #
def test_create_amm_uses_default_country(db, admin_token):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    db.settings.update_one({"_id": "global"}, {"$set": {"amm_default_country": "ci"}}, upsert=True)
    suffix = uuid.uuid4().hex[:6]
    r = requests.post(f"{API}/amm", headers=H, json={
        "product_name": f"CountryTest-{suffix}",
    })
    assert r.status_code == 200, r.text
    amm = r.json()["amm"]
    try:
        assert amm["country_code"] == "CI"  # normalisé en MAJ
    finally:
        db.amm_numbers.delete_one({"id": amm["id"]})


def test_create_amm_explicit_country_overrides_default(db, admin_token):
    token, _ = admin_token
    H = {"Authorization": f"Bearer {token}"}
    db.settings.update_one({"_id": "global"}, {"$set": {"amm_default_country": "BF"}}, upsert=True)
    suffix = uuid.uuid4().hex[:6]
    r = requests.post(f"{API}/amm", headers=H, json={
        "product_name": f"FrTest-{suffix}",
        "country_code": "fr",
    })
    assert r.status_code == 200
    amm = r.json()["amm"]
    try:
        assert amm["country_code"] == "FR"
    finally:
        db.amm_numbers.delete_one({"id": amm["id"]})
