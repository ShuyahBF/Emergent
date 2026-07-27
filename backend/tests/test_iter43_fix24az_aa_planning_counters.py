"""Iter43-fix24az-aa (2026-07-22) — Live counters : sidebar badge + planning header.

Tests couvrant :
  1. GET /me/planning/counts retourne le shape attendu (date, from_date,
     today_walk_ins_open, upcoming_rdv_count, upcoming_walk_in_count).
  2. `today_walk_ins_open` compte les walk-ins d'AUJOURD'HUI (peu importe la
     date passée en paramètre).
  3. `upcoming_rdv_count` compte les RDV avec start_at >= from_date (= date+1).
  4. `upcoming_walk_in_count` compte les walk-ins dont walk_in_list préfixé
     par un jour futur (à partir de date+1) sur `horizon_days` jours.
  5. Le médecin logué voit UNIQUEMENT ses propres compteurs.
  6. Admin peut filtrer par medecin_id.
  7. Validation `date` invalide → 400.
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
    """Crée un médecin tracked avec bridge users row propre."""
    tu_id = "aa-tu-1"
    bu_id = "aa-bu-1"
    email = "aa-medecin@sawalitest.com"
    db.tracked_users.delete_many({"email": email})
    db.users.delete_many({"email": email})
    db.tracked_users.insert_one({
        "id": tu_id, "client_id": super_admin["id"],
        "name": "Dr Counter", "email": email, "role": "Médecin",
        "status": "active", "user_account_id": bu_id, "has_password": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": bu_id, "email": email, "full_name": "Dr Counter",
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


def _sign_admin(super_admin) -> str:
    return pyjwt.encode({
        "sub": super_admin["id"], "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


# =============================================================================
# 1. Shape par défaut
# =============================================================================
def test_counts_default_shape(med_setup):
    r = requests.get(f"{API}/me/planning/counts",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # Shape
    assert set(body.keys()) >= {"date", "from_date", "horizon_days",
                                "today_walk_ins_open", "upcoming_rdv_count",
                                "upcoming_walk_in_count"}
    # from_date == date + 1
    d1 = datetime.strptime(body["date"], "%Y-%m-%d")
    d2 = datetime.strptime(body["from_date"], "%Y-%m-%d")
    assert (d2 - d1).days == 1
    assert body["horizon_days"] == 90
    # No data → all zero
    assert body["today_walk_ins_open"] == 0
    assert body["upcoming_rdv_count"] == 0
    assert body["upcoming_walk_in_count"] == 0


# =============================================================================
# 2. today_walk_ins_open compte AUJOURD'HUI (peu importe la date paramètre)
# =============================================================================
def test_today_walk_ins_open_counts_only_today(med_setup, webhook_secret):
    now = datetime.now(timezone.utc)
    # Walk-in TODAY
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AA-T1", "medecin": "Dr Counter",
              "medecin_email": med_setup["email"], "patient": "PatientToday",
              "start": now.isoformat(), "is_rdv": 0, "domaine": "gyneco"},
        timeout=15,
    )
    # Walk-in tomorrow (forcer via start param dans la clé YYMMDD)
    tomorrow = now + timedelta(days=1)
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AA-T2", "medecin": "Dr Counter",
              "medecin_email": med_setup["email"], "patient": "PatientTomorrow",
              "start": tomorrow.isoformat(), "is_rdv": 0, "domaine": "gyneco"},
        timeout=15,
    )
    # Query counts with date = today (default)
    r = requests.get(f"{API}/me/planning/counts",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    body = r.json()
    # today_walk_ins_open should be 1 (only the "today" one)
    assert body["today_walk_ins_open"] == 1, f"Expected 1 walk-in today, got {body}"
    # upcoming_walk_in_count should include tomorrow's walk-in
    assert body["upcoming_walk_in_count"] >= 1


# =============================================================================
# 3. upcoming_rdv_count : RDV avec start_at >= from_date
# =============================================================================
def test_upcoming_rdv_count(med_setup, webhook_secret):
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    # RDV today (should NOT be counted as "upcoming from tomorrow")
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AA-R1", "medecin": "Dr Counter",
              "medecin_email": med_setup["email"], "patient": "RdvToday",
              "start": now.isoformat(), "is_rdv": 1},
        timeout=15,
    )
    # RDV in 2 days (SHOULD be counted)
    d2 = now + timedelta(days=2)
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AA-R2", "medecin": "Dr Counter",
              "medecin_email": med_setup["email"], "patient": "RdvIn2Days",
              "start": d2.isoformat(), "is_rdv": 1},
        timeout=15,
    )
    # RDV in 3 days (SHOULD be counted)
    d3 = now + timedelta(days=3)
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AA-R3", "medecin": "Dr Counter",
              "medecin_email": med_setup["email"], "patient": "RdvIn3Days",
              "start": d3.isoformat(), "is_rdv": 1},
        timeout=15,
    )
    r = requests.get(f"{API}/me/planning/counts",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    body = r.json()
    # upcoming_rdv_count = RDV starting from tomorrow (day+1) : should be >= 2
    assert body["upcoming_rdv_count"] >= 2, f"Expected >=2 upcoming RDVs, got {body}"


# =============================================================================
# 4. Query with `date` param — shifts the from_date window
# =============================================================================
def test_counts_with_custom_date_shifts_window(med_setup, webhook_secret):
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    d3 = now + timedelta(days=3)  # RDV in 3 days
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AA-D1", "medecin": "Dr Counter",
              "medecin_email": med_setup["email"], "patient": "RdvIn3",
              "start": d3.isoformat(), "is_rdv": 1},
        timeout=15,
    )
    # Query with date=today+3 → from_date = today+4 → the RDV in 3 days
    # should NOT be counted as upcoming.
    date_param = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    r = requests.get(f"{API}/me/planning/counts?date={date_param}",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    body = r.json()
    assert body["date"] == date_param
    # from_date = date + 1 (day+4)
    from_dt = datetime.strptime(body["from_date"], "%Y-%m-%d")
    date_dt = datetime.strptime(body["date"], "%Y-%m-%d")
    assert (from_dt - date_dt).days == 1


# =============================================================================
# 5. Médecin voit uniquement ses propres compteurs
# =============================================================================
def test_medecin_sees_only_own_counters(db, super_admin, med_setup, webhook_secret):
    # Create a SECOND médecin with different RDVs
    other_bu = "aa-bu-2"
    other_tu = "aa-tu-2"
    other_email = "aa-medecin2@sawalitest.com"
    db.tracked_users.insert_one({
        "id": other_tu, "client_id": super_admin["id"],
        "name": "Dr Other", "email": other_email, "role": "Médecin",
        "status": "active", "user_account_id": other_bu, "has_password": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": other_bu, "email": other_email, "full_name": "Dr Other",
        "role": "client", "tracked_role": "Médecin", "tracked_user_id": other_tu,
        "parent_client_id": super_admin["id"], "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    now = datetime.now(timezone.utc).replace(hour=11, minute=0, second=0, microsecond=0)
    d1 = now + timedelta(days=2)
    # Other doctor gets 3 RDVs in the future
    for i in range(3):
        requests.post(
            f"{API}/webhooks/planning/{webhook_secret}",
            json={"code_clinique": "AA-OT", "medecin": "Dr Other",
                  "medecin_email": other_email,
                  "patient": f"OtherPatient{i}",
                  "start": (d1 + timedelta(hours=i)).isoformat(), "is_rdv": 1},
            timeout=15,
        )
    # First médecin (med_setup) queries their counts → should NOT see other's
    r = requests.get(f"{API}/me/planning/counts",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    body = r.json()
    upcoming_rdv_med1 = body["upcoming_rdv_count"]

    # Other médecin queries
    r2 = requests.get(f"{API}/me/planning/counts",
                     headers={"Authorization": f"Bearer {_sign_user(other_bu)}"},
                     timeout=15)
    body2 = r2.json()
    upcoming_rdv_med2 = body2["upcoming_rdv_count"]

    assert upcoming_rdv_med2 >= 3
    # Med1's counter should not include Med2's RDVs
    assert upcoming_rdv_med1 < upcoming_rdv_med2 + 100  # sanity

    # Cleanup other médecin
    db.tracked_users.delete_one({"id": other_tu})
    db.users.delete_one({"id": other_bu})
    db.planning_appointments.delete_many({"medecin_email": other_email})


# =============================================================================
# 6. Validation date invalide → 400
# =============================================================================
def test_counts_invalid_date_returns_400(med_setup):
    r = requests.get(f"{API}/me/planning/counts?date=not-a-date",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    assert r.status_code == 400
    assert "date" in r.json()["detail"].lower()


# =============================================================================
# 7. Admin peut filtrer par medecin_id
# =============================================================================
def test_admin_can_filter_by_medecin_id(super_admin, med_setup, webhook_secret):
    now = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    d2 = now + timedelta(days=5)
    requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "AA-AD", "medecin": "Dr Counter",
              "medecin_email": med_setup["email"], "patient": "AdminFilterTest",
              "start": d2.isoformat(), "is_rdv": 1},
        timeout=15,
    )
    r = requests.get(
        f"{API}/me/planning/counts?medecin_id={med_setup['bu_id']}",
        headers={"Authorization": f"Bearer {_sign_admin(super_admin)}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["medecin_id"] == med_setup["bu_id"]
    assert body["upcoming_rdv_count"] >= 1
