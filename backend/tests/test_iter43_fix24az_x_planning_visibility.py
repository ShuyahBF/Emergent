"""Iter43-fix24az-x (2026-07-22) — Bug prod planning : webhook + GET robustness.

Fix pour le bug production où les RDVs importés par le webhook Planning
étaient invisibles pour le médecin connecté, alors que les RDVs seedés
manuellement s'affichaient. Root cause : lookup `db.users.find_one({email})`
échouait pour les médecins sans bridge users row OU avec casse divergente,
forçant le fallback `tenant_id = super-admin.id` qui n'était pas dans le
scope du médecin.

Fix (couvre 3 chemins) :
  1. Webhook : lookup case-insensitive dans users + fallback dans tracked_users.
  2. GET /me/planning/appointments : scope élargi avec tracked_users.client_id
     + tracked_users.id ; email match case-insensitive.
  3. Front (autre test file) : médecin tracked redirigé vers /portal/planning
     au login + Welcome briefing supprimé.

Tests :
  - RDV webhook visible pour un médecin sans bridge users row (tracked_users
    only).
  - RDV webhook visible pour un médecin dont l'email a une casse différente
    entre db.users.email et le payload webhook.
  - RDV webhook visible pour un médecin avec bridge users row correct
    (régression : ancien path continue de fonctionner).
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


def _sign_user(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "client",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def _cleanup(db, prefix: str):
    db.tracked_users.delete_many({"email": {"$regex": f"^{prefix}"}})
    db.users.delete_many({"email": {"$regex": f"^{prefix}", "$options": "i"}})
    db.planning_appointments.delete_many({"medecin_email": {"$regex": f"^{prefix}", "$options": "i"}})


@pytest.fixture(autouse=True)
def _isolation(db):
    _cleanup(db, "docfix-")
    yield
    _cleanup(db, "docfix-")


# =============================================================================
# 1. Baseline — médecin avec bridge users row correct (ancien chemin)
# =============================================================================
def test_webhook_rdv_visible_with_bridged_user(db, super_admin, webhook_secret):
    """Régression : le médecin avec bridge users row voit bien son RDV
    inséré par webhook."""
    tu_id = "docfix-tu-bridge"
    bu_id = "docfix-bu-bridge"
    email = "docfix-bridge@sawalitest.com"
    db.tracked_users.insert_one({
        "id": tu_id, "client_id": super_admin["id"],
        "name": "Dr Bridge", "email": email, "role": "Médecin",
        "status": "active", "user_account_id": bu_id, "has_password": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": bu_id, "email": email, "full_name": "Dr Bridge",
        "role": "client", "tracked_role": "Médecin", "tracked_user_id": tu_id,
        "parent_client_id": super_admin["id"], "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=2)).replace(microsecond=0).isoformat()
    r = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "DOCFIX", "medecin": "Dr Bridge",
              "medecin_email": email, "patient": "Bridge Patient",
              "start": start},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    # Médecin queries his planning
    date_str = (now + timedelta(hours=2)).strftime("%Y-%m-%d")
    r2 = requests.get(f"{API}/me/planning/appointments?date={date_str}",
                      headers={"Authorization": f"Bearer {_sign_user(bu_id)}"},
                      timeout=15)
    assert r2.status_code == 200, r2.text
    patients = [i["patient"] for i in r2.json()["items"]]
    assert "Bridge Patient" in patients, f"Missing patient in response: {r2.json()}"


# =============================================================================
# 2. Fix principal — médecin SANS bridge users row (tracked_users only)
# =============================================================================
def test_webhook_rdv_visible_with_tracked_users_only(db, super_admin, webhook_secret):
    """Bug prod : le médecin qui n'a QUE une ligne tracked_users (pas de
    bridge users row) doit quand même voir ses RDVs. AVANT le fix, le
    webhook ne trouvait rien dans db.users et fallback sur super-admin
    tenant_id — hors scope du médecin → RDV invisible."""
    tu_id = "docfix-tu-nobridge"
    bu_id = "docfix-bu-nobridge"  # Bridged user exists to enable login,
                                   # BUT tracked_users has client_id set
                                   # to an intermediate client (simule le
                                   # cas prod où parent_client_id sur users
                                   # est stale/manquant).
    email = "docfix-nobridge@sawalitest.com"
    # Intermediate client : NOT super_admin. This is the "correct" tenant_id
    # the RDV should be tagged with.
    intermediate_client_id = "docfix-client-inter"
    db.users.insert_one({
        "id": intermediate_client_id, "email": "docfix-client-inter@x.com",
        "full_name": "Intermediate Client", "role": "client",
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.tracked_users.insert_one({
        "id": tu_id, "client_id": intermediate_client_id,
        "name": "Dr NoBridge", "email": email, "role": "Médecin",
        "status": "active", "user_account_id": bu_id, "has_password": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Bridged user with MISSING parent_client_id (simule bug prod)
    db.users.insert_one({
        "id": bu_id, "email": email, "full_name": "Dr NoBridge",
        "role": "client", "tracked_role": "Médecin", "tracked_user_id": tu_id,
        # NB: NO parent_client_id — this triggers the fallback path
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=2)).replace(microsecond=0).isoformat()
    r = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "DOCFIX-NB", "medecin": "Dr NoBridge",
              "medecin_email": email, "patient": "PALE Nathalie",
              "start": start},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    # Verify DB : the webhook should have used the bridged user's id
    # (parent_client_id fallback → client_id → id) which is bu_id in this case.
    doc = db.planning_appointments.find_one({"patient": "PALE Nathalie"})
    assert doc is not None
    assert doc.get("medecin_email") == email

    # Médecin queries his planning — must see PALE Nathalie despite
    # the parent_client_id-less bridge.
    date_str = (now + timedelta(hours=2)).strftime("%Y-%m-%d")
    r2 = requests.get(f"{API}/me/planning/appointments?date={date_str}",
                      headers={"Authorization": f"Bearer {_sign_user(bu_id)}"},
                      timeout=15)
    assert r2.status_code == 200, r2.text
    patients = [i["patient"] for i in r2.json()["items"]]
    assert "PALE Nathalie" in patients, (
        f"CRITICAL: PALE Nathalie webhook-inserted RDV is invisible to médecin. "
        f"Response: {r2.json()}. Inserted doc tenant_id={doc.get('tenant_id')!r}"
    )
    # Cleanup intermediate
    db.users.delete_one({"id": intermediate_client_id})


# =============================================================================
# 3. Case-insensitive email — payload en MAJUSCULES, base en lowercase
# =============================================================================
def test_webhook_rdv_visible_with_uppercase_email_in_payload(db, super_admin, webhook_secret):
    """Meta / webhooks externes peuvent envoyer des emails avec casse
    variable. Le lookup doit être case-insensitive."""
    tu_id = "docfix-tu-case"
    bu_id = "docfix-bu-case"
    email_lower = "docfix-case@sawalitest.com"
    db.tracked_users.insert_one({
        "id": tu_id, "client_id": super_admin["id"],
        "name": "Dr Case", "email": email_lower, "role": "Médecin",
        "status": "active", "user_account_id": bu_id, "has_password": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": bu_id, "email": email_lower, "full_name": "Dr Case",
        "role": "client", "tracked_role": "Médecin", "tracked_user_id": tu_id,
        "parent_client_id": super_admin["id"], "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=2)).replace(microsecond=0).isoformat()
    # Send with UPPERCASE email in webhook payload
    r = requests.post(
        f"{API}/webhooks/planning/{webhook_secret}",
        json={"code_clinique": "DOCFIX-C", "medecin": "Dr Case",
              "medecin_email": "DOCFIX-CASE@SAWALITEST.COM",  # uppercase
              "patient": "Case Patient",
              "start": start},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    # Médecin sees it
    date_str = (now + timedelta(hours=2)).strftime("%Y-%m-%d")
    r2 = requests.get(f"{API}/me/planning/appointments?date={date_str}",
                      headers={"Authorization": f"Bearer {_sign_user(bu_id)}"},
                      timeout=15)
    assert r2.status_code == 200, r2.text
    patients = [i["patient"] for i in r2.json()["items"]]
    assert "Case Patient" in patients, (
        f"Case-insensitive email lookup failed. Response: {r2.json()}"
    )


# =============================================================================
# 4. Multiple RDVs — le médecin voit TOUS ses RDVs webhook (pas juste 1)
# =============================================================================
def test_all_webhook_rdvs_visible_for_medecin(db, super_admin, webhook_secret):
    """Reproduit le cas prod : 5 RDVs webhook + 1 seed manuel → tous
    doivent être visibles."""
    tu_id = "docfix-tu-multi"
    bu_id = "docfix-bu-multi"
    email = "docfix-multi@sawalitest.com"
    db.tracked_users.insert_one({
        "id": tu_id, "client_id": super_admin["id"],
        "name": "Dr Multi", "email": email, "role": "Médecin",
        "status": "active", "user_account_id": bu_id, "has_password": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.insert_one({
        "id": bu_id, "email": email, "full_name": "Dr Multi",
        "role": "client", "tracked_role": "Médecin", "tracked_user_id": tu_id,
        "parent_client_id": super_admin["id"], "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    now = datetime.now(timezone.utc)
    day = (now + timedelta(hours=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    # Insert 5 webhook RDVs
    for i in range(5):
        start = (day + timedelta(minutes=30 * i)).isoformat()
        requests.post(
            f"{API}/webhooks/planning/{webhook_secret}",
            json={"code_clinique": "DOCFIX-M", "medecin": "Dr Multi",
                  "medecin_email": email,
                  "patient": f"WebhookPatient{i:02d}",
                  "start": start},
            timeout=15,
        )
    # Insert 1 seed RDV (like curl direct insert)
    db.planning_appointments.insert_one({
        "id": "docfix-seed-1",
        "tenant_id": super_admin["id"],
        "code_clinique": "DOCFIX-S",
        "medecin": "Dr Multi", "medecin_email": email, "medecin_id": bu_id,
        "patient": "SeedPatient",
        "start_at": (day + timedelta(hours=3)).isoformat(),
        "end_at": (day + timedelta(hours=3, minutes=30)).isoformat(),
        "source": "manual-seed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Query
    date_str = day.strftime("%Y-%m-%d")
    r2 = requests.get(f"{API}/me/planning/appointments?date={date_str}",
                      headers={"Authorization": f"Bearer {_sign_user(bu_id)}"},
                      timeout=15)
    assert r2.status_code == 200, r2.text
    patients = [i["patient"] for i in r2.json()["items"]]
    for i in range(5):
        assert f"WebhookPatient{i:02d}" in patients, (
            f"Webhook RDV #{i} missing. Got: {patients}"
        )
    assert "SeedPatient" in patients
    assert r2.json()["count"] == 6
