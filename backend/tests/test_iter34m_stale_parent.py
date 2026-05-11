"""Iter34m — Reproduces the 'rabo.f' stale-parent_client_id bug and
verifies the new diagnostic detects it AND the realign endpoint fixes it.

Scenario:
  1. CMCO user (role=client, company='Clinique CMCO TEST', is_primary_client)
  2. SAWALI canonical = admin@sawalismartsystems.com (company='SAWALI SMART SYSTEMS')
  3. A child user rabo.f.test with:
       - company = "SAWALI SMART SYSTEMS"  (typed)
       - parent_client_id = CMCO_id        (stale pointer)
       - client_id = CMCO_id               (stale)
     plus one directory_contact tagged client_id=CMCO_id created on behalf
     of that user. After realignment:
       - rabo.f.test.parent_client_id should = SAWALI admin id
       - rabo.f.test.client_id should = SAWALI admin id
       - the contact row should be retagged to SAWALI admin id
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data.get("access_token")
    session_token = data["session_token"]
    code = data.get("dev_otp")
    assert code, f"no dev_otp: {data}"
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": session_token, "code": code}, timeout=30)
    assert r2.status_code == 200, r2.text
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def mongo():
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    cli = MongoClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    yield db
    cli.close()


@pytest.fixture()
def stale_parent_user(mongo, admin_h):
    """Provision a CMCO canonical user, ensure SAWALI admin exists with
    expected company, and create a child user with the stale-parent
    misconfiguration we want to detect."""
    # 1. SAWALI canonical (the seeded admin already has company = SAWALI SMART SYSTEMS)
    sawali = mongo.users.find_one({"email": ADMIN_EMAIL})
    assert sawali, "seeded admin missing"
    assert (sawali.get("company") or "").strip().lower() == "sawali smart systems"
    sawali_id = sawali["id"]

    # 2. CMCO canonical user (create if missing). Tag is_primary_client so the
    # fallback resolution works without an admin role.
    cmco_email = f"cmco.test+{uuid.uuid4().hex[:6]}@sawalitest.local"
    cmco_id = str(uuid.uuid4())
    mongo.users.insert_one({
        "id": cmco_id,
        "email": cmco_email,
        "password_hash": "x",
        "role": "client",
        "full_name": "Clinique CMCO Test",
        "company": "Clinique CMCO TEST",
        "is_primary_client": True,
        "client_id": cmco_id,
        "parent_client_id": None,
        "created_at": "2026-05-11T00:00:00+00:00",
    })

    # 3. The misconfigured child user — typed company is SAWALI but pointer
    # still points to CMCO.
    rabo_email = f"rabo.test+{uuid.uuid4().hex[:6]}@sawalitest.local"
    rabo_id = str(uuid.uuid4())
    mongo.users.insert_one({
        "id": rabo_id,
        "email": rabo_email,
        "password_hash": "x",
        "role": "client",
        "full_name": "Rabo Test",
        "company": "SAWALI SMART SYSTEMS",
        "client_id": cmco_id,
        "parent_client_id": cmco_id,
        "created_at": "2026-05-11T00:00:00+00:00",
    })

    # 4. A contact row currently scoped to CMCO that the user should keep
    # access to after realignment. Iter34o requires `owner_id` to scope
    # the retag — without it, the contact is considered "not owned by this
    # user" and stays at CMCO (the desired behaviour to avoid moving
    # contacts owned by other CMCO users).
    contact_id = str(uuid.uuid4())
    mongo.directory_contacts.insert_one({
        "id": contact_id,
        "client_id": cmco_id,
        "owner_id": rabo_id,
        "full_name": "Stale Contact",
        "phone": "+22612345678",
        "created_at": "2026-05-11T00:00:00+00:00",
    })

    yield {
        "rabo_email": rabo_email,
        "rabo_id": rabo_id,
        "cmco_id": cmco_id,
        "sawali_id": sawali_id,
        "contact_id": contact_id,
    }

    # Cleanup
    mongo.users.delete_one({"id": rabo_id})
    mongo.users.delete_one({"id": cmco_id})
    mongo.directory_contacts.delete_one({"id": contact_id})


def test_diagnostic_detects_stale_parent(admin_h, stale_parent_user):
    r = requests.get(
        f"{API}/admin/client-data-diagnostic",
        params={"email": stale_parent_user["rabo_email"]},
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    diag = r.json()
    # The bug used to report "Aucun désalignement détecté" here. Now we
    # detect the parent-company mismatch and re-route to SAWALI.
    assert diag["parent_company_mismatch"] is True
    assert diag["parent_company_observed"] == "Clinique CMCO TEST"
    assert diag["canonical"]["client_id"] == stale_parent_user["sawali_id"]
    assert "company match" in diag["canonical"]["source"]
    assert diag["realign_plan"]["needed"] is True
    types = [a["type"] for a in diag["realign_plan"]["actions"]]
    assert "relink_parent" in types
    assert "set_user_client_id" in types
    assert "retag_rows" in types  # the contact row needs retagging


def test_realign_actually_repairs_the_pointer(admin_h, stale_parent_user, mongo):
    r = requests.post(
        f"{API}/admin/realign-user-to-client",
        json={"email": stale_parent_user["rabo_email"], "dry_run": False},
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is True

    u = mongo.users.find_one({"id": stale_parent_user["rabo_id"]})
    assert u["parent_client_id"] == stale_parent_user["sawali_id"]
    assert u["client_id"] == stale_parent_user["sawali_id"]
    assert u.get("parent_client_id_legacy") == stale_parent_user["cmco_id"]

    contact = mongo.directory_contacts.find_one({"id": stale_parent_user["contact_id"]})
    assert contact["client_id"] == stale_parent_user["sawali_id"]
    assert contact.get("client_id_legacy") == stale_parent_user["cmco_id"]

    # Diagnostic should now be clean
    r2 = requests.get(
        f"{API}/admin/client-data-diagnostic",
        params={"email": stale_parent_user["rabo_email"]},
        headers=admin_h, timeout=30,
    )
    diag2 = r2.json()
    assert diag2["parent_company_mismatch"] is False
    assert diag2["realign_plan"]["needed"] is False
