"""Iter43-fix24az-r (2026-07-22) — Bug prod fix (tracked_user create with empty
optional fields) + Groupe d'assistance hebdomadaire pour garde planning."""
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


def h(token):
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# BUG FIX 1 — tracked user creation with empty email / optional fields
# =============================================================================
def test_create_tracked_user_with_empty_string_email_fails_gracefully(admin_token, db):
    """Repro : le frontend envoyait email="" (chaîne vide), Pydantic EmailStr
    renvoyait 422 + array `detail`. Post-fix : le frontend envoie null, backend
    accepte."""
    admin_id = db.users.find_one({"email": "admin@sawalismartsystems.com"})["id"]
    # Empty string on email still returns 422 (backend unchanged, only frontend fix)
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=h(admin_token),
        json={
            "client_id": admin_id,
            "name": "Test Empty Email User",
            "email": "",
            "phone": "",
            "whatsapp_number": "",
            "role": "Consultation",
            "department": "",
            "company": "",
            "status": "active",
        },
        timeout=15,
    )
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body.get("detail"), list)


def test_create_tracked_user_with_null_email_succeeds(admin_token, db):
    """Post-fix behaviour : frontend convertit "" → null, backend accepte."""
    admin_id = db.users.find_one({"email": "admin@sawalismartsystems.com"})["id"]
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=h(admin_token),
        json={
            "client_id": admin_id,
            "name": "Test Null Email User",
            "email": None,
            "phone": None,
            "whatsapp_number": None,
            "role": "Consultation",
            "department": None,
            "company": None,
            "status": "active",
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Test Null Email User"
    assert body.get("email") is None
    # Cleanup
    db.tracked_users.delete_one({"id": body["id"]})


def test_create_tracked_user_medecin_role_accepted(admin_token, db):
    """« Médecin » doit être un rôle valide (module Planning)."""
    admin_id = db.users.find_one({"email": "admin@sawalismartsystems.com"})["id"]
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=h(admin_token),
        json={
            "client_id": admin_id, "name": "Dr Test Iter43r",
            "role": "Médecin", "status": "active",
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "Médecin"
    db.tracked_users.delete_one({"id": body["id"]})


# =============================================================================
# FEATURE — Groupe d'assistance hebdo (assist_group)
# =============================================================================
def test_list_planning_includes_assist_group_field(admin_token, db):
    """GET planning must expose assist_group per week (None by default)."""
    year = 2026
    r = requests.get(f"{API}/admin/officines-registry/garde-planning?year={year}",
                     headers=h(admin_token), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "weeks" in body
    assert len(body["weeks"]) > 0
    for w in body["weeks"]:
        assert "assist_group" in w, f"week {w.get('week_number')} manque assist_group"


def test_set_assist_group_persists(admin_token, db):
    """PUT with assist_group persists + returns it correctly."""
    year, week = 2026, 45  # use a week that hasn't been touched
    # Cleanup first
    db.garde_planning.delete_one({"year": year, "week_number": week})
    # Get available groups
    groups = set()
    for o in db.officines.find({"groupe_garde": {"$nin": [None, ""]}}, {"groupe_garde": 1, "_id": 0}):
        try:
            groups.add(int(o["groupe_garde"]))
        except (TypeError, ValueError):
            continue
    groups = sorted(groups)
    if len(groups) < 2:
        pytest.skip("Besoin d'au moins 2 groupes standard pour tester l'assist")
    # Pick an assist different from what the auto-rotation would suggest
    auto_suggested = groups[(week - 1) % len(groups)]
    assist_choice = next(g for g in groups if g != auto_suggested)
    r = requests.put(
        f"{API}/admin/officines-registry/garde-planning/{year}/{week}",
        headers=h(admin_token),
        json={"assist_group": assist_choice},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assist_group"] == assist_choice
    # Le groupe standard doit être auto-préservé (auto rotation persistée)
    assert body["groupe_garde"] is not None
    # DB confirmed
    stored = db.garde_planning.find_one({"year": year, "week_number": week})
    assert stored["assist_group"] == assist_choice
    # Cleanup
    db.garde_planning.delete_one({"year": year, "week_number": week})


def test_reject_assist_equals_standard(admin_token, db):
    """assist_group ne peut pas être identique au groupe standard."""
    year, week = 2026, 46
    db.garde_planning.delete_one({"year": year, "week_number": week})
    r = requests.put(
        f"{API}/admin/officines-registry/garde-planning/{year}/{week}",
        headers=h(admin_token),
        json={"groupe_garde": 2, "assist_group": 2},
        timeout=15,
    )
    assert r.status_code == 400
    assert "assistance" in r.text.lower() or "identique" in r.text.lower()
    db.garde_planning.delete_one({"year": year, "week_number": week})


def test_clear_assist_group(admin_token, db):
    """PUT with assist_group=null clears it."""
    year, week = 2026, 47
    db.garde_planning.delete_one({"year": year, "week_number": week})
    # Set a value first
    r = requests.put(
        f"{API}/admin/officines-registry/garde-planning/{year}/{week}",
        headers=h(admin_token),
        json={"groupe_garde": 1, "assist_group": 2},
        timeout=15,
    )
    assert r.status_code == 200
    # Clear
    r = requests.put(
        f"{API}/admin/officines-registry/garde-planning/{year}/{week}",
        headers=h(admin_token),
        json={"assist_group": None},
        timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["assist_group"] is None
    db.garde_planning.delete_one({"year": year, "week_number": week})


def test_reject_missing_both_fields(admin_token, db):
    """Payload sans ni groupe_garde ni assist_group → 400."""
    year, week = 2026, 48
    r = requests.put(
        f"{API}/admin/officines-registry/garde-planning/{year}/{week}",
        headers=h(admin_token),
        json={},
        timeout=15,
    )
    assert r.status_code == 400


def test_public_current_exposes_assist_officines(db):
    """GET /api/public/officines/garde/current must include assist_group + assist_officines."""
    r = requests.get(f"{API}/public/officines/garde/current", timeout=15)
    assert r.status_code == 200
    body = r.json()
    # Fields must always exist even when None/empty
    assert "assist_group" in body
    assert "assist_officines" in body
    assert "assist_count" in body
    assert isinstance(body["assist_officines"], list)


def test_public_current_returns_assist_officines_when_configured(db):
    """When admin sets assist_group for the current week, public endpoint
    returns the assist officines list."""
    groups = set()
    for o in db.officines.find({"groupe_garde": {"$nin": [None, ""]}}, {"groupe_garde": 1, "_id": 0}):
        try:
            groups.add(int(o["groupe_garde"]))
        except (TypeError, ValueError):
            continue
    groups = sorted(groups)
    if len(groups) < 2:
        pytest.skip("Besoin d'au moins 2 groupes standard")
    # Trust the backend's own computation of (year, week)
    r = requests.get(f"{API}/public/officines/garde/current", timeout=15)
    initial = r.json()
    year = initial["year"]
    week = initial["week_number"]
    current_gg = initial.get("groupe_garde")
    assist_pick = next((g for g in groups if g != current_gg), None)
    assert assist_pick is not None, "Impossible de trouver un groupe distinct pour l'appui"
    # Save state
    existing = db.garde_planning.find_one({"year": year, "week_number": week}, {"_id": 0}) or {}
    db.garde_planning.update_one(
        {"year": year, "week_number": week},
        {"$set": {"year": year, "week_number": week, "assist_group": assist_pick,
                  "groupe_garde": current_gg}},
        upsert=True,
    )
    try:
        r = requests.get(f"{API}/public/officines/garde/current", timeout=15)
        body = r.json()
        assert body["assist_group"] == assist_pick
        expected = list(db.officines.find({"groupe_garde": assist_pick, "status": {"$ne": "suspended"}}))
        assert body["assist_count"] == len(expected)
    finally:
        if existing:
            db.garde_planning.replace_one({"year": year, "week_number": week}, existing)
        else:
            db.garde_planning.delete_one({"year": year, "week_number": week})
