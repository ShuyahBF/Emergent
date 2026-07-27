"""Iter43-fix24az-z (2026-07-22) — Planning : placement intelligent + walk-ins.

Tests couvrant :
  1. Nouveaux champs webhook : is_rdv, numero_liste, numero_ordre, domaine.
  2. Walk-ins (is_rdv=0) : pas de start_at requis ; numero_ordre auto-attribué
     chronologiquement dans la liste (walk_in_list = YYMMDD:email:domaine).
  3. RDV en conflit avec un autre RDV : placement au slot libre le plus proche
     (avant ou après) + correction_applied + correction_reason retournés.
  4. RDV sans conflit : placement conservé tel quel, correction_applied=False.
  5. Rétro-compat : is_rdv absent → traité comme is_rdv=1 (RDV).
  6. GET /me/planning/appointments retourne aussi les walk-ins du jour.
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
    assert r.status_code == 200, r.text
    return r.json().get("planning_webhook_secret")


@pytest.fixture
def med_setup(db, super_admin):
    """Crée un médecin tracked avec bridge users row propre."""
    tu_id = "zzz-tu-1"
    bu_id = "zzz-bu-1"
    email = "zzz-medecin@sawalitest.com"
    db.tracked_users.delete_many({"email": email})
    db.users.delete_many({"email": email})
    db.tracked_users.insert_one({
        "id": tu_id, "client_id": super_admin["id"],
        "name": "Dr Placement", "email": email, "role": "Médecin",
        "status": "active", "user_account_id": bu_id, "has_password": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": bu_id, "email": email, "full_name": "Dr Placement",
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
# 1. Nouveaux champs : is_rdv + numero_liste + numero_ordre + domaine
# =============================================================================
def test_webhook_accepts_new_fields_for_rdv(db, med_setup, webhook_secret):
    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=2)).replace(microsecond=0).isoformat()
    r = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "TZZ-1", "medecin": "Dr Placement",
              "medecin_email": med_setup["email"], "patient": "PatientA",
              "start": start,
              "is_rdv": 1, "numero_liste": "L01", "numero_ordre": 3,
              "domaine": "Gyneco"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_rdv"] == 1
    assert body["numero_liste"] == "L01"
    assert body["numero_ordre"] == 3
    assert body["domaine"] == "gyneco"  # normalized to lowercase
    assert body["correction_applied"] is False
    assert body["placed_at"] == start
    assert body["walk_in_list"] is None  # RDV → no walk-in list
    doc = db.planning_appointments.find_one({"patient": "PatientA",
                                              "medecin_email": med_setup["email"]})
    assert doc is not None
    assert doc["is_rdv"] == 1
    assert doc["domaine"] == "gyneco"


# =============================================================================
# 2. Walk-ins (is_rdv=0) — pas de start_at requis + numero_ordre auto
# =============================================================================
def test_walk_in_no_start_needed_auto_numero_ordre(db, med_setup, webhook_secret):
    """3 walk-ins arrivent sans start_at ni numero_ordre → numérotés 1, 2, 3
    dans leur liste (YYMMDD:email:gyneco)."""
    responses = []
    for name in ("PatientW1", "PatientW2", "PatientW3"):
        r = requests.post(
            f"{API}/webhooks/planning/{webhook_secret}",
            json={"code_clinique": "TZZ-W", "medecin": "Dr Placement",
                  "medecin_email": med_setup["email"], "patient": name,
                  "is_rdv": 0, "domaine": "gyneco"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        responses.append(r.json())
    assert [x["numero_ordre"] for x in responses] == [1, 2, 3]
    # walk_in_list is consistent
    lists = {x["walk_in_list"] for x in responses}
    assert len(lists) == 1
    # Format YYMMDD:email:gyneco
    wlist = next(iter(lists))
    parts = wlist.split(":")
    assert len(parts) == 3
    assert len(parts[0]) == 6 and parts[0].isdigit()
    assert parts[1] == med_setup["email"]
    assert parts[2] == "gyneco"


def test_walk_in_missing_start_but_is_rdv_1_returns_400(db, med_setup, webhook_secret):
    """is_rdv=1 (RDV) sans start → 400."""
    r = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "TZZ-X", "medecin": "Dr Placement",
              "medecin_email": med_setup["email"], "patient": "PatientX",
              "is_rdv": 1},  # no start!
        timeout=15,
    )
    assert r.status_code == 400
    assert "start" in r.json()["detail"].lower()


# =============================================================================
# 3. Placement intelligent — conflit RDV vs RDV
# =============================================================================
def test_conflict_rdv_vs_rdv_shifts_new_appointment(db, med_setup, webhook_secret):
    """Deux RDV se chevauchent : le 2e est déplacé au slot libre le plus proche."""
    day = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    slot_a_start = day.isoformat()
    slot_a_end = (day + timedelta(minutes=30)).isoformat()

    # RDV #1 : 10h00 → 10h30
    r1 = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "TZZ-C", "medecin": "Dr Placement",
              "medecin_email": med_setup["email"], "patient": "Patient1",
              "start": slot_a_start, "end": slot_a_end, "is_rdv": 1},
        timeout=15,
    )
    assert r1.status_code == 200
    assert r1.json()["correction_applied"] is False

    # RDV #2 : demande aussi 10h00 → 10h30 (même patient différent)
    r2 = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "TZZ-C", "medecin": "Dr Placement",
              "medecin_email": med_setup["email"], "patient": "Patient2",
              "start": slot_a_start, "end": slot_a_end, "is_rdv": 1},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["correction_applied"] is True, f"Expected correction: {body}"
    assert body["correction_reason"]
    assert "créneau" in body["correction_reason"].lower() or "occup" in body["correction_reason"].lower()
    # placed_at != original_start_at
    assert body["placed_at"] != body["original_start_at"]
    # Le nouveau slot ne chevauche pas le premier
    placed_start = datetime.fromisoformat(body["placed_at"].replace("Z", "+00:00"))
    placed_end = datetime.fromisoformat(body["placed_end_at"].replace("Z", "+00:00"))
    slot_a_end_dt = datetime.fromisoformat(slot_a_end.replace("Z", "+00:00"))
    slot_a_start_dt = datetime.fromisoformat(slot_a_start.replace("Z", "+00:00"))
    # Le nouveau slot doit être avant ou après (pas de chevauchement)
    assert placed_end <= slot_a_start_dt or placed_start >= slot_a_end_dt, (
        f"Slot overlaps: placed=[{placed_start}, {placed_end}], "
        f"existing=[{slot_a_start_dt}, {slot_a_end_dt}]"
    )


def test_rdv_no_conflict_no_correction(db, med_setup, webhook_secret):
    """Un RDV sans conflit : placement intact, correction_applied=False."""
    day = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=2)
    r = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "TZZ-N", "medecin": "Dr Placement",
              "medecin_email": med_setup["email"], "patient": "PatientN",
              "start": day.isoformat(), "is_rdv": 1},
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["correction_applied"] is False
    assert body["placed_at"] == day.isoformat()


# =============================================================================
# 4. Rétro-compat : is_rdv absent → traité comme is_rdv=1
# =============================================================================
def test_legacy_webhook_without_is_rdv_treated_as_rdv(db, med_setup, webhook_secret):
    day = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=3)
    r = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "TZZ-L", "medecin": "Dr Placement",
              "medecin_email": med_setup["email"], "patient": "LegacyPatient",
              "start": day.isoformat()},  # no is_rdv, no domaine
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_rdv"] == 1
    assert body["walk_in_list"] is None


# =============================================================================
# 5. GET /me/planning/appointments retourne aussi les walk-ins
# =============================================================================
def test_get_planning_returns_both_rdv_and_walk_ins(db, med_setup, webhook_secret):
    day = datetime.now(timezone.utc).replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=4)
    # 2 RDV
    for i, name in enumerate(["Rdv1", "Rdv2"]):
        requests.post(
            f"{API}/webhooks/planning/{webhook_secret}",
            json={"code_clinique": "TZZ-M", "medecin": "Dr Placement",
                  "medecin_email": med_setup["email"], "patient": name,
                  "start": (day + timedelta(hours=i)).isoformat(),
                  "is_rdv": 1},
            timeout=15,
        )
    # 3 walk-ins sur la même journée
    for name in ("Walk1", "Walk2", "Walk3"):
        requests.post(
            f"{API}/webhooks/planning/{webhook_secret}",
            json={"code_clinique": "TZZ-M", "medecin": "Dr Placement",
                  "medecin_email": med_setup["email"], "patient": name,
                  # walk-ins prennent leur "date" via received_at (today)
                  # mais pour cibler `day` dans la liste, on force start_at
                  # avec le champ start (utilisé uniquement pour la clé date).
                  "start": day.isoformat(),
                  "is_rdv": 0, "domaine": "gyneco"},
            timeout=15,
        )
    # Query the médecin's planning for `day`
    date_str = day.strftime("%Y-%m-%d")
    r = requests.get(f"{API}/me/planning/appointments?date={date_str}",
                     headers={"Authorization": f"Bearer {_sign_user(med_setup['bu_id'])}"},
                     timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    patients = [i["patient"] for i in body["items"]]
    for expected in ("Rdv1", "Rdv2", "Walk1", "Walk2", "Walk3"):
        assert expected in patients, f"Missing {expected} in {patients}"
    # Walk-ins have is_rdv=0
    walk_docs = [i for i in body["items"] if i.get("is_rdv") == 0]
    assert len(walk_docs) == 3
    # numero_ordre 1,2,3
    orders = sorted([d.get("numero_ordre") for d in walk_docs])
    assert orders == [1, 2, 3]
    # RDVs have is_rdv=1
    rdv_docs = [i for i in body["items"] if i.get("is_rdv") == 1]
    assert len(rdv_docs) == 2
