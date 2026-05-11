"""Iter34n — Guard rail: when admin edits a user's `company` text via
PUT /admin/clients/{id}, the backend auto-detects+auto-fixes a stale
parent_client_id (the rabo.f bug class)."""
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
    assert r.status_code == 200
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data["dev_otp"]}, timeout=30)
    assert r2.status_code == 200
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
def world(mongo):
    """Set up CMCO + a user currently anchored to CMCO."""
    sawali = mongo.users.find_one({"email": ADMIN_EMAIL})
    assert sawali
    sawali_id = sawali["id"]

    cmco_id = str(uuid.uuid4())
    mongo.users.insert_one({
        "id": cmco_id, "email": f"cmco.guard+{uuid.uuid4().hex[:6]}@sawalitest.local",
        "password_hash": "x", "role": "client", "full_name": "CMCO Guard",
        "company": "Clinique CMCO Guard", "is_primary_client": True,
        "client_id": cmco_id, "parent_client_id": None,
    })
    rabo_id = str(uuid.uuid4())
    rabo_email = f"rabo.guard+{uuid.uuid4().hex[:6]}@sawalitest.local"
    mongo.users.insert_one({
        "id": rabo_id, "email": rabo_email,
        "password_hash": "x", "role": "client", "full_name": "Rabo Guard",
        "company": "Clinique CMCO Guard",  # initially aligned
        "client_id": cmco_id, "parent_client_id": cmco_id,
    })
    yield {"sawali_id": sawali_id, "cmco_id": cmco_id, "rabo_id": rabo_id, "rabo_email": rabo_email}
    mongo.users.delete_one({"id": rabo_id})
    mongo.users.delete_one({"id": cmco_id})


def test_company_change_triggers_auto_realign(admin_h, world, mongo):
    """When admin changes company, the guard rail auto-fixes parent_client_id."""
    r = requests.put(
        f"{API}/admin/clients/{world['rabo_id']}",
        json={"company": "SAWALI SMART SYSTEMS"},
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    ar = body.get("auto_realign")
    assert ar is not None, f"auto_realign missing: {body}"
    assert ar["applied"] is True
    assert ar["to_canonical_id"] == world["sawali_id"]
    assert ar["actions_count"] >= 1
    # Verify DB state
    u = mongo.users.find_one({"id": world["rabo_id"]})
    assert u["parent_client_id"] == world["sawali_id"]
    assert u["client_id"] == world["sawali_id"]
    assert u["company"] == "SAWALI SMART SYSTEMS"
    assert u.get("parent_client_id_legacy") == world["cmco_id"]


def test_company_typo_returns_unresolvable_reason(admin_h, world, mongo):
    """When the new company doesn't match any admin/primary, the response
    surfaces the unresolvable state instead of silently leaving stale data."""
    r = requests.put(
        f"{API}/admin/clients/{world['rabo_id']}",
        json={"company": "Société Inexistante XYZ"},
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    ar = r.json().get("auto_realign")
    assert ar is not None
    assert ar["applied"] is False
    assert ar["reason"] == "no_canonical_for_company"
    assert ar["typed_company"] == "Société Inexistante XYZ"


def test_no_company_change_no_auto_realign(admin_h, world, mongo):
    """Editing other fields should not trigger the guard rail."""
    r = requests.put(
        f"{API}/admin/clients/{world['rabo_id']}",
        json={"full_name": "Rabo Renommé"},
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200
    assert r.json().get("auto_realign") is None
