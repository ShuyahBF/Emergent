"""Iter41 Phase 3 (2026-02) — Synthèse + Officines + AMM CIP fields."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta, date
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
    aid = f"p3_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "admin"), aid
    db.users.delete_one({"id": aid})


@pytest.fixture(scope="module")
def regulateur_token(db):
    uid = f"p3_reg_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "regulateur", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(uid, "regulateur"), uid
    db.users.delete_one({"id": uid})


@pytest.fixture(scope="module")
def client_token(db):
    uid = f"p3_cli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(uid, "client"), uid
    db.users.delete_one({"id": uid})


# ----------------------------------------------------------------------
# AMM with CIP fields
# ----------------------------------------------------------------------
def test_amm_supports_cip_fields(db, regulateur_token):
    token, _ = regulateur_token
    num = f"AMM-CIP-{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/amm", json={
        "product_name": "Doliprane 1000mg",
        "amm_number": num,
        "cip1": "3400930471722", "cip2": "3400930471723",
        "cip3": "3400930471724", "cip4": "3400930471725",
        "cip5": "3400930471726",
    }, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    amm = r.json()["amm"]
    assert amm["cip1"] == "3400930471722"
    assert amm["cip5"] == "3400930471726"
    db.amm_numbers.delete_many({"amm_number": num})


# ----------------------------------------------------------------------
# Synthèse — date parsing
# ----------------------------------------------------------------------
def test_synthese_date_parsing_iso():
    from routes.synthese import parse_synthese_args
    s, e = parse_synthese_args("2026-02-01 2026-02-05")
    assert s == date(2026, 2, 1)
    assert e == date(2026, 2, 5)


def test_synthese_date_parsing_french():
    from routes.synthese import parse_synthese_args
    s, e = parse_synthese_args("01/02/2026 05/02/2026")
    assert s == date(2026, 2, 1)
    assert e == date(2026, 2, 5)


def test_synthese_date_parsing_keywords():
    from routes.synthese import parse_synthese_args
    s, e = parse_synthese_args("hier")
    assert s == e
    assert s == date.today() - timedelta(days=1)
    s2, e2 = parse_synthese_args("")
    assert s2 == e2 == date.today()


def test_synthese_date_parsing_mixed():
    """Mixed formats should still work — start ISO, end keyword."""
    from routes.synthese import parse_synthese_args
    s, e = parse_synthese_args("2026-01-01 aujourd'hui")
    assert s == date(2026, 1, 1)
    assert e == date.today()


def test_synthese_command_detection_case_insensitive():
    from routes.synthese import SYNTHESE_CMD_RE
    assert SYNTHESE_CMD_RE.match("!synthèse")
    assert SYNTHESE_CMD_RE.match("!SYNTHESE")
    assert SYNTHESE_CMD_RE.match("!Synthese 01/02/2026")
    assert SYNTHESE_CMD_RE.match("/synthese hier")
    assert not SYNTHESE_CMD_RE.match("synthese sans bang")


# ----------------------------------------------------------------------
# Officines — !aizenta detection
# ----------------------------------------------------------------------
def test_aizenta_command_detection():
    from routes.officines_wa import AIZENTA_RE
    m = AIZENTA_RE.match("!aizenta doliprane")
    assert m and m.group(2) == "doliprane"
    m2 = AIZENTA_RE.match("!AIZENTA doliprane 1000mg")
    assert m2 and m2.group(2) == "doliprane 1000mg"
    m3 = AIZENTA_RE.match("!officine efferalgan")
    assert m3 and m3.group(2) == "efferalgan"
    m4 = AIZENTA_RE.match("/officines paracétamol")
    assert m4 and m4.group(2) == "paracétamol"
    assert not AIZENTA_RE.match("hello world")


def test_aizenta_format_reply():
    from routes.officines import format_officines_wa_reply
    msg = format_officines_wa_reply("Doliprane", {"officines": [
        {"name": "Pharmacie Centrale", "address": "12 rue X", "phone": "+22670000000", "price_avg": "1500 XOF", "available": True},
        {"name": "Pharma Sud", "available": False},
    ]})
    assert "Pharmacie Centrale" in msg
    assert "1500 XOF" in msg
    assert "Disponible" in msg
    assert "Indispo" in msg


def test_aizenta_format_reply_empty():
    from routes.officines import format_officines_wa_reply
    msg = format_officines_wa_reply("Doliprane", {"officines": []})
    assert "Aucune officine" in msg


# ----------------------------------------------------------------------
# Officines — lookup RBAC
# ----------------------------------------------------------------------
def test_officines_lookup_blocked_for_client(client_token):
    token, _ = client_token
    r = requests.post(f"{API}/officines/lookup", json={"product_name": "doliprane"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    # Client doesn't have allowed role → 403
    assert r.status_code in (401, 403)


def test_officines_lookup_503_without_url(db, regulateur_token):
    """No officines_api_url configured → 503."""
    token, _ = regulateur_token
    # Wipe URL just in case
    db.settings.update_one({"_id": "global"}, {"$set": {"officines_api_url": ""}}, upsert=True)
    r = requests.post(f"{API}/officines/lookup", json={"product_name": "doliprane"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 503
    assert "URL" in r.json()["detail"]


# ----------------------------------------------------------------------
# Synthèse settings
# ----------------------------------------------------------------------
def test_synthese_settings_persistence(db, admin_token):
    token, _ = admin_token
    payload = {
        "synthese_enabled": True,
        "synthese_email_to": "boss@sawali.com",
        "synthese_wa_to": "22670000000",
        "synthese_hour": "08:30",
        "synthese_prompt": "Fais une synthèse de l'activité du jour.",
        "synthese_channels": "both",
    }
    r = requests.put(f"{API}/admin/settings", json=payload,
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code in (200, 204), r.text
    # Read back
    s = db.settings.find_one({"_id": "global"})
    assert s["synthese_enabled"] is True
    assert s["synthese_hour"] == "08:30"
    assert s["synthese_channels"] == "both"


def test_sidebar_image_url_persistence(db, admin_token):
    token, _ = admin_token
    r = requests.put(f"{API}/admin/settings", json={
        "sidebar_bg_image_url": "/api/files/abc-123-def",
        "sidebar_bg_image_opacity": 0.4,
    }, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code in (200, 204)
    s = db.settings.find_one({"_id": "global"})
    assert s["sidebar_bg_image_url"] == "/api/files/abc-123-def"
    assert abs(s["sidebar_bg_image_opacity"] - 0.4) < 1e-6


def test_officines_api_token_masked(db, admin_token):
    token, _ = admin_token
    db.settings.update_one({"_id": "global"}, {"$set": {"officines_api_token": "super_secret_token_xyz"}})
    r = requests.get(f"{API}/admin/settings",
                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    assert r.json().get("officines_api_token") == "********"
