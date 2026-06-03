"""Bypass list & cross-tenant contact search & import (2026-02).

Three new features tested here :
  1) `settings.liluvine_pro_bypass_emails` lets specific user emails use
     Liluvine PRO even when their tenant's `ai_liluvine_pro` feature is OFF.
  2) `GET  /api/me/contacts/search-cross-tenant?phone=...` returns sanitized
     matches across ALL tenants.
  3) `POST /api/me/contacts/import-cross-tenant` re-creates the row in the
     caller's scope. Messages copy is reserved to admin/superviseur.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASS = "Admin@Sawali2026"


def _login(email: str, password: str) -> str | None:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15).json()
    if r.get("needs_otp"):
        r = requests.post(
            f"{API}/auth/verify-otp",
            json={"session_token": r["session_token"], "code": r.get("dev_otp")},
            timeout=15,
        ).json()
    return r.get("access_token") or r.get("token")


@pytest.fixture(scope="module")
def admin_h():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    assert tok
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


# ------------- Bypass list -------------


def test_get_bypass_emails_returns_list(admin_h):
    r = requests.get(f"{API}/admin/liluvine-pro/bypass-emails", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "emails" in data and isinstance(data["emails"], list)
    assert "count" in data


def test_patch_bypass_emails_normalizes_and_dedupes(admin_h, db_sync):
    payload = {"emails": ["A@Example.com", "a@example.com", " b@ex.com ", "", "c@ex.com"]}
    r = requests.patch(f"{API}/admin/liluvine-pro/bypass-emails", json=payload, headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["emails"] == ["a@example.com", "b@ex.com", "c@ex.com"]
    assert data["count"] == 3
    # Cleanup : reset to empty
    requests.patch(f"{API}/admin/liluvine-pro/bypass-emails", json={"emails": []}, headers=admin_h, timeout=15)


def test_patch_bypass_emails_rejects_invalid(admin_h):
    r = requests.patch(
        f"{API}/admin/liluvine-pro/bypass-emails",
        json={"emails": ["valid@ex.com", "not-an-email", "another@ex.com"]},
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 400, r.text
    assert "invalide" in r.text.lower()


def test_bypass_email_grants_liluvine_pro_access(admin_h, db_sync):
    """Create a user with no ai_liluvine_pro feature, put her in the bypass
    list, then verify she can call /api/me/liluvine-pro/chat (no 403)."""
    import sys
    sys.path.insert(0, "/app/backend")
    from auth import hash_password  # type: ignore

    suffix = uuid.uuid4().hex[:6]
    email = f"bypass_{suffix}@example.com"
    password = "Password123!"
    parent = db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": hash_password(password),
        "full_name": "Bypass Test",
        "company": "BypassCo",
        "phone": f"+228{suffix}99",
        "role": "moderateur",
        "parent_client_id": parent["id"],
        "client_id": parent["id"],
        "account_status": "active",
        "features": {"ai_liluvine_pro": False},
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    }
    db_sync.users.insert_one(user_doc)
    try:
        tok = _login(email, password)
        assert tok, "login failed"
        user_h = {"Authorization": f"Bearer {tok}"}

        # Ensure parent tenant has the feature OFF for this test, AND ensure
        # bypass list is empty so we start from a deterministic "denied" state.
        db_sync.users.update_one(
            {"id": parent["id"]},
            {"$set": {"features.ai_liluvine_pro": False}},
        )
        requests.patch(
            f"{API}/admin/liluvine-pro/bypass-emails",
            json={"emails": []}, headers=admin_h, timeout=15,
        )

        # Step 1: without bypass → 403
        r1 = requests.post(f"{API}/me/liluvine-pro/chat",
                           json={"text": "ping"}, headers=user_h, timeout=15)
        assert r1.status_code == 403, f"expected 403 before bypass, got {r1.status_code}: {r1.text}"

        # Step 2: add email to bypass list
        rp = requests.patch(
            f"{API}/admin/liluvine-pro/bypass-emails",
            json={"emails": [email]},
            headers=admin_h, timeout=15,
        )
        assert rp.status_code == 200, rp.text

        # Step 3: same call now succeeds (or fails for OTHER reasons but NOT 403)
        r2 = requests.post(f"{API}/me/liluvine-pro/chat",
                           json={"text": "ping"}, headers=user_h, timeout=30)
        assert r2.status_code != 403, (
            f"expected non-403 after bypass, got {r2.status_code}: {r2.text}"
        )
    finally:
        # Cleanup
        db_sync.users.delete_one({"email": email})
        # Re-enable parent feature (admin tenant normally has it ON)
        db_sync.users.update_one(
            {"email": ADMIN_EMAIL},
            {"$set": {"features.ai_liluvine_pro": True}},
        )
        requests.patch(
            f"{API}/admin/liluvine-pro/bypass-emails",
            json={"emails": []}, headers=admin_h, timeout=15,
        )


# ------------- Cross-tenant search & import -------------


@pytest.fixture()
def fixture_cross_tenant(db_sync):
    """Seed a directory_contacts row in a FAKE other tenant, then yield
    the phone digits + cleanup at the end."""
    suffix = uuid.uuid4().hex[:6]
    digits = "22899" + str(int(suffix, 16))[:6].rjust(6, "0")
    other_tenant_id = str(uuid.uuid4())
    src = {
        "id": str(uuid.uuid4()),
        "client_id": other_tenant_id,
        "owner_id": other_tenant_id,
        "name": "Crossy McTenant",
        "phone": f"+{digits}",
        "whatsapp": f"+{digits}",
        "email": f"crossy_{suffix}@example.com",
        "company": "OtherCo",
        "tags": ["legacy"],
        "shared": True,
    }
    db_sync.directory_contacts.insert_one(src)
    # Also seed a couple of whatsapp messages in that other tenant
    db_sync.whatsapp_messages.insert_many([
        {"id": str(uuid.uuid4()), "client_id": other_tenant_id, "phone_digits": digits,
         "direction": "inbound", "body": "hello A", "contact_id": src["id"]},
        {"id": str(uuid.uuid4()), "client_id": other_tenant_id, "phone_digits": digits,
         "direction": "inbound", "body": "hello B", "contact_id": src["id"]},
    ])
    yield {"digits": digits, "src_id": src["id"], "other_tenant_id": other_tenant_id}
    db_sync.directory_contacts.delete_many({
        "$or": [{"phone": {"$regex": digits}}, {"whatsapp": {"$regex": digits}}]
    })
    db_sync.whatsapp_messages.delete_many({"phone_digits": digits})


def test_search_cross_tenant_returns_sanitized_card(admin_h, fixture_cross_tenant):
    r = requests.get(
        f"{API}/me/contacts/search-cross-tenant",
        params={"phone": fixture_cross_tenant["digits"]},
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] >= 1
    item = next(i for i in data["items"] if i["id"] == fixture_cross_tenant["src_id"])
    assert item["name"] == "Crossy McTenant"
    assert "client_id" not in item, "client_id should NOT leak in cross-tenant search"
    assert "owner_id" not in item
    assert item["in_current_scope"] is False  # admin's scope != other_tenant_id


def test_search_cross_tenant_rejects_short_phone(admin_h):
    r = requests.get(
        f"{API}/me/contacts/search-cross-tenant",
        params={"phone": "12"}, headers=admin_h, timeout=15,
    )
    assert r.status_code == 400


def test_import_cross_tenant_creates_contact_in_caller_scope(admin_h, db_sync, fixture_cross_tenant):
    digits = fixture_cross_tenant["digits"]
    r = requests.post(
        f"{API}/me/contacts/import-cross-tenant",
        json={"phone": digits, "include_messages": False},
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["contact"]["name"] == "Crossy McTenant"
    assert data["messages_imported"] == 0
    # Verify a NEW row was inserted in the admin's scope (different from src tenant)
    admin = db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    new = db_sync.directory_contacts.find_one(
        {"id": data["contact"]["id"]},
        {"_id": 0, "client_id": 1, "imported_from_contact_id": 1, "name": 1},
    )
    assert new is not None
    assert new["client_id"] == admin["id"]
    assert new["imported_from_contact_id"] == fixture_cross_tenant["src_id"]


def test_import_cross_tenant_with_messages_admin_only(admin_h, db_sync, fixture_cross_tenant):
    digits = fixture_cross_tenant["digits"]
    r = requests.post(
        f"{API}/me/contacts/import-cross-tenant",
        json={"phone": digits, "include_messages": True},
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["include_messages_allowed"] is True
    assert data["messages_imported"] >= 2
    admin = db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    # The copied messages must be re-scoped to the admin tenant
    copied = list(db_sync.whatsapp_messages.find(
        {"phone_digits": digits, "client_id": admin["id"]},
        {"_id": 0, "imported_from_client_id": 1, "contact_name": 1},
    ))
    assert len(copied) >= 2
    assert all(m["imported_from_client_id"] == fixture_cross_tenant["other_tenant_id"] for m in copied)
    # Cleanup the imported copies (the fixture only cleans by digits which covers it)
