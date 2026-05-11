"""Iter34o — Recovery from the over-broad retag bug.

Validates:
  • Owner-scoped retag: contacts owned by OTHER users of the same source
    client are NOT moved when one user is realigned (this is the production
    bug rabo.f exposed).
  • POST /admin/contacts/revert-retag dry-run returns accurate counts.
  • POST /admin/contacts/revert-retag (live) restores client_id_legacy
    back into client_id and removes the legacy field.
  • Endpoint is idempotent (second call: 0 rows touched).
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
        return data["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data["dev_otp"]}, timeout=30)
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
def cmco_with_neighbour(mongo):
    """Set up:
      - rabo.f-like user with stale parent → CMCO_id
      - CMCO_id holds 2 contacts: one owned by rabo, one owned by another
        CMCO user (mimicking real Clinique CMCO data).
    """
    sawali = mongo.users.find_one({"email": ADMIN_EMAIL})
    sawali_id = sawali["id"]

    cmco_id = str(uuid.uuid4())
    mongo.users.insert_one({
        "id": cmco_id, "email": f"cmco.o+{uuid.uuid4().hex[:6]}@sawalitest.local",
        "password_hash": "x", "role": "client", "full_name": "CMCO Owner",
        "company": "Clinique CMCO TEST O", "is_primary_client": True,
        "client_id": cmco_id, "parent_client_id": None,
    })
    rabo_id = str(uuid.uuid4())
    rabo_email = f"rabo.o+{uuid.uuid4().hex[:6]}@sawalitest.local"
    mongo.users.insert_one({
        "id": rabo_id, "email": rabo_email,
        "password_hash": "x", "role": "client", "full_name": "Rabo O",
        "company": "SAWALI SMART SYSTEMS",  # typed SAWALI
        "client_id": cmco_id, "parent_client_id": cmco_id,  # stale → CMCO
    })

    rabo_contact_id = str(uuid.uuid4())
    cmco_contact_id = str(uuid.uuid4())
    mongo.directory_contacts.insert_many([
        {"id": rabo_contact_id, "client_id": cmco_id, "owner_id": rabo_id,
         "full_name": "Rabo's contact", "created_at": "2026-05-11T00:00:00+00:00"},
        {"id": cmco_contact_id, "client_id": cmco_id, "owner_id": cmco_id,
         "full_name": "Real CMCO contact", "created_at": "2026-05-11T00:00:00+00:00"},
    ])

    yield {
        "sawali_id": sawali_id,
        "cmco_id": cmco_id,
        "rabo_id": rabo_id,
        "rabo_email": rabo_email,
        "rabo_contact_id": rabo_contact_id,
        "cmco_contact_id": cmco_contact_id,
    }
    mongo.users.delete_one({"id": rabo_id})
    mongo.users.delete_one({"id": cmco_id})
    mongo.directory_contacts.delete_one({"id": rabo_contact_id})
    mongo.directory_contacts.delete_one({"id": cmco_contact_id})


def test_owner_scoped_retag_leaves_other_users_data_intact(admin_h, cmco_with_neighbour, mongo):
    """The exact production bug: when rabo.f is realigned, the CMCO contact
    owned by another CMCO user MUST stay tagged with the CMCO client_id."""
    r = requests.post(
        f"{API}/admin/realign-user-to-client",
        json={"email": cmco_with_neighbour["rabo_email"], "dry_run": False},
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True

    rabo_contact = mongo.directory_contacts.find_one({"id": cmco_with_neighbour["rabo_contact_id"]})
    cmco_contact = mongo.directory_contacts.find_one({"id": cmco_with_neighbour["cmco_contact_id"]})

    # Rabo's contact moved to SAWALI
    assert rabo_contact["client_id"] == cmco_with_neighbour["sawali_id"]
    assert rabo_contact.get("client_id_legacy") == cmco_with_neighbour["cmco_id"]
    # CMCO's other contact stays put
    assert cmco_contact["client_id"] == cmco_with_neighbour["cmco_id"]
    assert "client_id_legacy" not in cmco_contact


def test_revert_retag_dry_run_counts(admin_h, cmco_with_neighbour, mongo):
    # First, perform the realign so there's something to revert
    requests.post(
        f"{API}/admin/realign-user-to-client",
        json={"email": cmco_with_neighbour["rabo_email"], "dry_run": False},
        headers=admin_h, timeout=30,
    )
    r = requests.post(
        f"{API}/admin/contacts/revert-retag",
        json={"dry_run": True},
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["total_rows"] >= 1  # at least the contact we moved
    # Ensure DB unchanged
    rabo_contact = mongo.directory_contacts.find_one({"id": cmco_with_neighbour["rabo_contact_id"]})
    assert rabo_contact["client_id"] == cmco_with_neighbour["sawali_id"]
    assert rabo_contact.get("client_id_legacy") == cmco_with_neighbour["cmco_id"]


def test_revert_retag_apply_restores_everything(admin_h, cmco_with_neighbour, mongo):
    requests.post(
        f"{API}/admin/realign-user-to-client",
        json={"email": cmco_with_neighbour["rabo_email"], "dry_run": False},
        headers=admin_h, timeout=30,
    )
    r = requests.post(
        f"{API}/admin/contacts/revert-retag",
        json={"dry_run": False, "collections": ["directory_contacts"]},
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    # Contact should be restored
    rabo_contact = mongo.directory_contacts.find_one({"id": cmco_with_neighbour["rabo_contact_id"]})
    assert rabo_contact["client_id"] == cmco_with_neighbour["cmco_id"]
    assert "client_id_legacy" not in rabo_contact

    # Second run = idempotent (0 changes for directory_contacts).
    r2 = requests.post(
        f"{API}/admin/contacts/revert-retag",
        json={"dry_run": False, "collections": ["directory_contacts"]},
        headers=admin_h, timeout=30,
    )
    assert r2.status_code == 200
    dc_result = next(x for x in r2.json()["results"] if x["collection"] == "directory_contacts")
    assert dc_result["count"] == 0


def test_revert_retag_with_from_filter(admin_h, cmco_with_neighbour, mongo):
    """`from_client_id` parameter restricts the revert to a specific source."""
    requests.post(
        f"{API}/admin/realign-user-to-client",
        json={"email": cmco_with_neighbour["rabo_email"], "dry_run": False},
        headers=admin_h, timeout=30,
    )
    r = requests.post(
        f"{API}/admin/contacts/revert-retag",
        json={"dry_run": True, "from_client_id": "id-that-does-not-exist", "collections": ["directory_contacts"]},
        headers=admin_h, timeout=30,
    )
    body = r.json()
    # The `users` revert always runs, but directory_contacts must be 0
    # because no row has client_id_legacy == "id-that-does-not-exist".
    dc = next(x for x in body["results"] if x["collection"] == "directory_contacts")
    assert dc["count"] == 0
