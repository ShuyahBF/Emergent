"""Iter41 Phase 2 (2026-02) — Tests pour le module VIDAL Phase 2 :
 - Détection des commandes WhatsApp `!vidal*`
 - Helper AMM CRUD (lecture + écriture restreinte)
 - Tenant gate (`vidal_enabled`/`vidal_mode`)
 - Debug verbose du test-connection
 - Helper `_resolve_tenant_vidal`
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid, role="admin"):
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    aid = f"v2_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "admin"), aid
    db.users.delete_one({"id": aid})


@pytest.fixture(scope="module")
def regulateur_token(db):
    uid = f"v2_reg_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "regulateur", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(uid, "regulateur"), uid
    db.users.delete_one({"id": uid})


@pytest.fixture(scope="module")
def client_token(db):
    uid = f"v2_cli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(uid, "client"), uid
    db.users.delete_one({"id": uid})


# ---------------------------------------------------------------------------
# !vidal* command detection
# ---------------------------------------------------------------------------
def test_detect_vidal_help():
    from routes.liluvine_vidal_wa import detect_vidal_command
    assert detect_vidal_command("!vidal?")["cmd"] == "help"
    assert detect_vidal_command("!vidal ?")["cmd"] == "help"
    assert detect_vidal_command("!vidal")["cmd"] == "help"
    assert detect_vidal_command("!VIDAL HELP")["cmd"] == "help"


def test_detect_vidal_fiche():
    from routes.liluvine_vidal_wa import detect_vidal_command
    p = detect_vidal_command("!vidal fiche doliprane")
    assert p["cmd"] == "fiche"
    assert p["args"] == ["doliprane"]
    # missing arg
    assert detect_vidal_command("!vidal fiche")["cmd"] == "missing_arg"


def test_detect_vidal_amm():
    from routes.liluvine_vidal_wa import detect_vidal_command
    p = detect_vidal_command("!vidal amm efferalgan 1g")
    assert p["cmd"] == "amm"
    assert p["args"] == ["efferalgan 1g"]


def test_detect_vidal_interactions():
    from routes.liluvine_vidal_wa import detect_vidal_command
    p = detect_vidal_command("!vidal interactions 11064 12345 99")
    assert p["cmd"] == "interactions"
    assert p["args"] == ["11064", "12345", "99"]
    assert detect_vidal_command("!vidal interactions 11064")["cmd"] == "missing_arg"


def test_detect_vidal_allergie():
    from routes.liluvine_vidal_wa import detect_vidal_command
    p = detect_vidal_command("!vidal allergie pénicilline")
    assert p["cmd"] == "allergie"
    assert p["args"] == ["pénicilline"]


def test_detect_vidal_unknown():
    from routes.liluvine_vidal_wa import detect_vidal_command
    assert detect_vidal_command("!vidal foobar")["cmd"] == "unknown"
    assert detect_vidal_command("hello world") is None
    assert detect_vidal_command("!aide") is None


# ---------------------------------------------------------------------------
# AMM CRUD
# ---------------------------------------------------------------------------
def test_amm_create_by_regulateur(db, regulateur_token):
    token, _ = regulateur_token
    amm_num = f"AMM-TEST-{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/amm", json={
        "vidal_product_id": 11064,
        "product_name": "Doliprane 1000mg Test",
        "amm_number": amm_num,
        "laboratory": "Sanofi",
        "status": "active",
    }, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    amm = r.json()["amm"]
    assert amm["amm_number"] == amm_num
    assert amm["source"] == "manual"
    # cleanup
    db.amm_numbers.delete_many({"amm_number": amm_num})


def test_amm_create_blocked_for_client(client_token):
    token, _ = client_token
    r = requests.post(f"{API}/amm", json={
        "product_name": "x", "amm_number": f"AMM-{uuid.uuid4().hex[:6]}",
    }, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code in (401, 403)


def test_amm_lookup_by_product(db, admin_token):
    token, _ = admin_token
    amm_num = f"AMM-LOOKUP-{uuid.uuid4().hex[:6]}"
    db.amm_numbers.insert_one({
        "id": uuid.uuid4().hex, "vidal_product_id": 99999,
        "product_name": "Lookup Test", "amm_number": amm_num,
        "status": "active", "source": "manual",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.get(f"{API}/amm/by-product/99999",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["amm"]["amm_number"] == amm_num
    db.amm_numbers.delete_many({"vidal_product_id": 99999})


def test_amm_unique_constraint(db, admin_token):
    token, _ = admin_token
    amm_num = f"AMM-UNIQ-{uuid.uuid4().hex[:6]}"
    r1 = requests.post(f"{API}/amm", json={"product_name": "A", "amm_number": amm_num},
                       headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/amm", json={"product_name": "B", "amm_number": amm_num},
                       headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r2.status_code == 409
    db.amm_numbers.delete_many({"amm_number": amm_num})


# ---------------------------------------------------------------------------
# Tenant gate
# ---------------------------------------------------------------------------
def test_tenant_gate_blocks_when_disabled(db, admin_token, client_token):
    """A client whose parent tenant has vidal_enabled=False gets 403."""
    atoken, _ = admin_token
    ctoken, cid = client_token

    # Create a parent admin tenant for this client with vidal_enabled=False
    parent_id = f"v2_parent_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": parent_id, "email": f"{parent_id}@t.l", "role": "admin",
        "features": {"vidal_enabled": False, "vidal_mode": "inherit"},
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.update_one({"id": cid}, {"$set": {"parent_client_id": parent_id}})

    # Enable VIDAL globally + add creds so we test the tenant gate, not the global flag
    requests.put(f"{API}/admin/vidal/config", json={
        "enabled": True, "mode": "test",
        "test_app_id": "x", "test_app_key": "y",
    }, headers={"Authorization": f"Bearer {atoken}"}, timeout=10)

    r = requests.get(f"{API}/vidal/search?q=doliprane&filter=product",
                     headers={"Authorization": f"Bearer {ctoken}"}, timeout=10)
    assert r.status_code == 403
    assert "non activé pour votre établissement" in r.json()["detail"]

    # Now enable for the tenant
    db.users.update_one({"id": parent_id}, {"$set": {"features.vidal_enabled": True}})
    # Restore client parent removal for downstream tests
    db.users.update_one({"id": cid}, {"$unset": {"parent_client_id": ""}})
    db.users.delete_one({"id": parent_id})


def test_quota_me_returns_access_and_tenant_type(client_token):
    token, _ = client_token
    r = requests.get(f"{API}/vidal/quota/me",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "access" in body
    assert "tenant_type" in body
    assert "mode" in body


# ---------------------------------------------------------------------------
# Debug verbose
# ---------------------------------------------------------------------------
def test_test_connection_returns_debug_block(db, admin_token):
    """Disabled module → returns debug=None but ok=False with clear error."""
    atoken, _ = admin_token
    requests.put(f"{API}/admin/vidal/config", json={"enabled": False},
                 headers={"Authorization": f"Bearer {atoken}"}, timeout=10)
    r = requests.post(f"{API}/admin/vidal/test-connection",
                      headers={"Authorization": f"Bearer {atoken}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "désactivé" in body["error"]
    # Restore for cleanliness
    requests.put(f"{API}/admin/vidal/config", json={"enabled": True, "test_app_id": "x", "test_app_key": "y"},
                 headers={"Authorization": f"Bearer {atoken}"}, timeout=10)


def test_test_connection_debug_includes_url(admin_token):
    """With creds set but bogus → returns debug.request.url showing what was sent."""
    atoken, _ = admin_token
    requests.put(f"{API}/admin/vidal/config", json={
        "enabled": True, "mode": "test",
        "test_base_url": "https://api-test.vidal.example/rest/api",
        "test_app_id": "bogus_id",
        "test_app_key": "bogus_key",
    }, headers={"Authorization": f"Bearer {atoken}"}, timeout=10)
    r = requests.post(f"{API}/admin/vidal/test-connection",
                      headers={"Authorization": f"Bearer {atoken}"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    debug = body.get("debug") or {}
    req = debug.get("request") or {}
    assert "vidal.example" in req.get("url", "")
    # app_key MUST be masked
    params = req.get("params") or {}
    assert params.get("app_key") == "***"
    assert params.get("app_id") == "bogus_id"
