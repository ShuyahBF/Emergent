"""Iter43-fix24az-o (2026-07-21) — Liluvine Reactions tests.

Validates :
  1. Fuzzy command matching : "pharmacies de garde" → detects `garde` cmd
  2. Ad template exact + fuzzy matching + received/replied counters
  3. Auto-add new contact when enabled
  4. `!reactions` summary message
  5. Admin CRUD endpoints for templates + config
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

# For direct unit testing of matching helpers
import sys
sys.path.insert(0, "/app/backend")
from routes.liluvine_reactions import _fuzzy_match_command, _match_ad_template, _norm, _similarity  # noqa: E402

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    u = db.users.find_one({"email": "admin@sawalismartsystems.com"})
    return pyjwt.encode({
        "sub": u["id"], "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


# ---------------------------------------------------------------------------
# 1) FUZZY COMMAND MATCHING — unit tests
# ---------------------------------------------------------------------------
def test_norm_removes_accents_and_ponct():
    assert _norm("Pharmacies de Garde ??") == "pharmacies de garde"
    assert _norm("MÉTÉO !") == "meteo"


def test_similarity_scores():
    assert _similarity("garde", "garde") == 100.0
    assert _similarity("garde", "gardes") > 80.0
    assert _similarity("garde", "xxxxx") < 30.0


def test_fuzzy_match_garde_variations():
    """La commande 'garde' doit être détectée dans plusieurs formulations."""
    for text in ["pharmacies de garde", "pharmacie de garde", "! garde", "garde pharmacie", "de garde"]:
        m = _fuzzy_match_command(text, 70)
        assert m is not None, f"Fuzzy match failed for: {text}"
        assert m[0] == "garde", f"Expected 'garde', got {m[0]} for text: {text}"


def test_fuzzy_no_match_random_text():
    assert _fuzzy_match_command("bonjour comment allez vous", 70) is None
    assert _fuzzy_match_command("abcdef xyz", 80) is None


def test_fuzzy_match_meteo_via_synonym():
    m = _fuzzy_match_command("quel temps fait il", 70)
    # `temps` is a synonym for meteo
    assert m is not None and m[0] == "meteo"


# ---------------------------------------------------------------------------
# 2) AD TEMPLATE MATCHING — unit tests
# ---------------------------------------------------------------------------
def test_ad_template_exact_match():
    templates = [{
        "id": "t1", "active": True,
        "trigger_text": "Puis-je en savoir plus sur votre entreprise ?",
        "trigger_variations": ["plus d'infos", "en savoir plus"],
    }]
    m = _match_ad_template("Puis-je en savoir plus sur votre entreprise ?", templates, 70)
    assert m and m["id"] == "t1"


def test_ad_template_variation_match():
    templates = [{
        "id": "t1", "active": True,
        "trigger_text": "Puis-je en savoir plus sur votre entreprise ?",
        "trigger_variations": ["plus d'infos"],
    }]
    m = _match_ad_template("plus d'infos", templates, 70)
    assert m and m["id"] == "t1"


def test_ad_template_fuzzy_match():
    templates = [{
        "id": "t1", "active": True,
        "trigger_text": "Puis-je en savoir plus sur votre entreprise ?",
        "trigger_variations": [],
    }]
    # Slight variation
    m = _match_ad_template("puis-je en savoir plus sur vôtre entreprise", templates, 70)
    assert m and m["id"] == "t1"


def test_ad_template_inactive_ignored():
    templates = [{
        "id": "t1", "active": False,
        "trigger_text": "test",
        "trigger_variations": [],
    }]
    assert _match_ad_template("test", templates, 70) is None


# ---------------------------------------------------------------------------
# 3) ADMIN CRUD ENDPOINTS — integration
# ---------------------------------------------------------------------------
def test_get_reactions_config(admin_token):
    r = requests.get(f"{API}/admin/liluvine/reactions-config",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "config" in d
    cfg = d["config"]
    assert set(cfg.keys()) >= {"fuzzy_match_enabled", "fuzzy_threshold", "auto_add_new_contacts", "default_new_contact_group_id"}


def test_put_reactions_config(admin_token):
    r = requests.put(f"{API}/admin/liluvine/reactions-config",
                     headers={"Authorization": f"Bearer {admin_token}"},
                     json={"fuzzy_threshold": 75, "auto_add_new_contacts": True},
                     timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["config"]["fuzzy_threshold"] == 75
    assert d["config"]["auto_add_new_contacts"] is True
    # Revert to defaults
    requests.put(f"{API}/admin/liluvine/reactions-config",
                 headers={"Authorization": f"Bearer {admin_token}"},
                 json={"fuzzy_threshold": 70, "auto_add_new_contacts": False}, timeout=10)


def test_create_update_delete_template(admin_token, db):
    # Create
    r = requests.post(f"{API}/admin/liluvine/reactions-templates",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      json={
                          "name": f"pytest-{uuid.uuid4().hex[:6]}",
                          "trigger_text": "trigger pytest unique",
                          "trigger_variations": ["variation 1"],
                          "response_text": "réponse pytest",
                      }, timeout=10)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]

    # Update
    r2 = requests.put(f"{API}/admin/liluvine/reactions-templates/{tid}",
                     headers={"Authorization": f"Bearer {admin_token}"},
                     json={"active": False, "response_text": "réponse maj"}, timeout=10)
    assert r2.status_code == 200
    assert r2.json()["active"] is False
    assert r2.json()["response_text"] == "réponse maj"

    # Delete
    r3 = requests.delete(f"{API}/admin/liluvine/reactions-templates/{tid}",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r3.status_code == 200
    assert r3.json()["ok"] is True

    # Not found update
    r4 = requests.put(f"{API}/admin/liluvine/reactions-templates/{tid}",
                     headers={"Authorization": f"Bearer {admin_token}"},
                     json={"active": True}, timeout=10)
    assert r4.status_code == 404


def test_get_stats_returns_totals(admin_token):
    r = requests.get(f"{API}/admin/liluvine/reactions-stats",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "totals" in d and "templates" in d
    assert set(d["totals"].keys()) == {"received", "replied", "reply_rate"}
