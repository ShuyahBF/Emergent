"""Iter43-fix24az-ab (2026-07-22) — Next busy day (chip cliquable).

Tests couvrant :
  1. GET /me/planning/next-busy-day retourne le shape attendu.
  2. Retour next_busy_date = date du 1er RDV >= after.
  3. Retour next_busy_date = date du 1er walk-in >= after quand pas de RDV.
  4. Prend la PLUS PROCHE des deux (RDV vs walk-in).
  5. Aucun RDV/walk-in dans l'horizon → next_busy_date = null.
  6. Validation `after` invalide → 400.
"""
from __future__ import annotations

import os
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
def super_admin(db):
    return db.users.find_one({"email": "admin@sawalismartsystems.com"})


@pytest.fixture(scope="module")
def webhook_secret(db, super_admin):
    tok = pyjwt.encode({
        "sub": super_admin["id"], "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")
    r = requests.get(f"{API}/admin/planning/config",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200
    return r.json().get("planning_webhook_secret")


@pytest.fixture
def med_setup(db, super_admin):
    tu_id = "ab-tu-1"
    bu_id = "ab-bu-1"
    email = "ab-medecin@sawalitest.com"
    db.tracked_users.delete_many({"email": email})
    db.users.delete_many({"email": email})
    db.tracked_users.insert_one({
        "id": tu_id, "client_id": super_admin["id"],
        "name": "Dr Next", "email": email, "role": "Médecin",
        "status": "active", "user_account_id": bu_id, "has_password": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": bu_id, "email": email, "full_name": "Dr Next",
        "role": "client", "tracked_role": "Médecin", "tracked_user_id": tu_id,
        "parent_client_id": super_admin["id"], "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"tu_id": tu_id, "bu_id": bu_id, "email": email}
    db.tracked_users.delete_one({"id": tu_id})
    db.users.delete_one({"id": bu_id})
    db.planning_appointments.delete_many({
        "$or": [{"medecin_email": email},
                {"walk_in_list": {"$regex": f".*:{email}:.*"}}]
    })


def _sign_user(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "client",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


# =============================================================================
# 1. Shape par défaut (no data → next_busy_date=null)
# =============================================================================
def test_next_busy_day_default_shape(med_setup):
    r = requests.get(f"{API}/me/planning/next-busy-day",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"after", "next_busy_date", "has_rdv", "has_walk_in", "horizon_days"}
    assert body["horizon_days"] == 90
    assert body["next_busy_date"] is None
    assert body["has_rdv"] is False
    assert body["has_walk_in"] is False


# =============================================================================
# 2. Prochain RDV
# =============================================================================
def test_next_busy_day_finds_first_rdv(med_setup, webhook_secret):
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    d3 = now + timedelta(days=3)
    d5 = now + timedelta(days=5)
    d10 = now + timedelta(days=10)
    # Insert RDVs sur J+3, J+5, J+10
    for delta, name in ((3, "P1"), (5, "P2"), (10, "P3")):
        requests.post(
            f"{API}/webhooks/planning/{webhook_secret}",
            json={"code_clinique": "AB-R", "medecin": "Dr Next",
                  "medecin_email": med_setup["email"], "patient": name,
                  "start": (now + timedelta(days=delta)).isoformat(),
                  "is_rdv": 1},
            timeout=15,
        )
    # Query with after = tomorrow → next should be J+3
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    r = requests.get(f"{API}/me/planning/next-busy-day?after={tomorrow}",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    body = r.json()
    assert body["next_busy_date"] == d3.strftime("%Y-%m-%d"), body
    assert body["has_rdv"] is True

    # Query with after = J+4 → next should be J+5
    d4 = (now + timedelta(days=4)).strftime("%Y-%m-%d")
    r2 = requests.get(f"{API}/me/planning/next-busy-day?after={d4}",
                      headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                      timeout=15)
    body2 = r2.json()
    assert body2["next_busy_date"] == d5.strftime("%Y-%m-%d"), body2

    # Query with after = J+11 → no more RDVs
    d11 = (now + timedelta(days=11)).strftime("%Y-%m-%d")
    r3 = requests.get(f"{API}/me/planning/next-busy-day?after={d11}",
                      headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                      timeout=15)
    assert r3.json()["next_busy_date"] is None


# =============================================================================
# 3. Prochain walk-in
# =============================================================================
def test_next_busy_day_finds_first_walk_in(med_setup, webhook_secret):
    now = datetime.now(timezone.utc)
    d4 = now + timedelta(days=4)
    # Walk-in sur J+4
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AB-W", "medecin": "Dr Next",
              "medecin_email": med_setup["email"], "patient": "WalkPatient",
              "start": d4.isoformat(), "is_rdv": 0, "domaine": "gyneco"},
        timeout=15,
    )
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    r = requests.get(f"{API}/me/planning/next-busy-day?after={tomorrow}",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    body = r.json()
    assert body["next_busy_date"] == d4.strftime("%Y-%m-%d"), body
    assert body["has_walk_in"] is True


# =============================================================================
# 4. RDV et walk-in coexistent — prend le plus proche
# =============================================================================
def test_next_busy_day_prefers_closest(med_setup, webhook_secret):
    now = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    d2 = now + timedelta(days=2)  # walk-in J+2
    d5 = now + timedelta(days=5)  # RDV J+5
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AB-M", "medecin": "Dr Next",
              "medecin_email": med_setup["email"], "patient": "Walk2",
              "start": d2.isoformat(), "is_rdv": 0, "domaine": "gyneco"},
        timeout=15,
    )
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AB-M", "medecin": "Dr Next",
              "medecin_email": med_setup["email"], "patient": "RdvIn5",
              "start": d5.isoformat(), "is_rdv": 1},
        timeout=15,
    )
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    r = requests.get(f"{API}/me/planning/next-busy-day?after={tomorrow}",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    body = r.json()
    # Walk-in J+2 est plus proche que RDV J+5
    assert body["next_busy_date"] == d2.strftime("%Y-%m-%d"), body
    assert body["has_rdv"] is True
    assert body["has_walk_in"] is True


# =============================================================================
# 5. Validation date invalide
# =============================================================================
def test_next_busy_day_invalid_date(med_setup):
    r = requests.get(f"{API}/me/planning/next-busy-day?after=not-a-date",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    assert r.status_code == 400


# =============================================================================
# 6. Horizon respecté (RDV hors horizon → non trouvé)
# =============================================================================
def test_next_busy_day_respects_horizon(med_setup, webhook_secret):
    now = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    # RDV loin dans le futur (J+100)
    d100 = now + timedelta(days=100)
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AB-F", "medecin": "Dr Next",
              "medecin_email": med_setup["email"], "patient": "FarPatient",
              "start": d100.isoformat(), "is_rdv": 1},
        timeout=15,
    )
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    # Horizon 30 jours → J+100 hors fenêtre
    r = requests.get(f"{API}/me/planning/next-busy-day?after={tomorrow}&horizon_days=30",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    assert r.json()["next_busy_date"] is None
    # Horizon 180 jours → J+100 dans la fenêtre
    r2 = requests.get(f"{API}/me/planning/next-busy-day?after={tomorrow}&horizon_days=180",
                      headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                      timeout=15)
    assert r2.json()["next_busy_date"] == d100.strftime("%Y-%m-%d")
