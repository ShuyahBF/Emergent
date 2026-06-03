"""Bug #3 — rabo.f case (2026-02).

When a moderator user (e.g. rabo.f@…) sends a WhatsApp message to the bot,
her name must appear in:
  - /portal/contacts (messaging center)
  - /portal/liluvine     (chat history)
  - /portal/liluvine-history (admin history)

Two repair surfaces are tested here:

  1) `GET /api/admin/liluvine-pro/diagnose?email=…` enriched with the new
     `contact_visibility` section that lists matching directory_contacts,
     wa_pending_imports and recent inbound whatsapp_messages.

  2) `POST /api/admin/contacts/repair-user-contact` that fixes any of the
     three root causes :
        a) no directory_contacts row at all → creates one
        b) row exists but `name` is blank/phone-only → fills with full_name
        c) row exists in another tenant scope → archives + creates canonical
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
    assert tok, "admin login failed"
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


@pytest.fixture()
def fixture_moderator(db_sync):
    """Spawn a fake moderator user 'rabo_test' with a phone number, no
    directory_contacts row, then clean up at the end."""
    suffix = uuid.uuid4().hex[:8]
    # Build a stable 11-digit phone (avoid hex letters in suffix).
    digits = "22890" + str(int(suffix, 16))[:6].rjust(6, "0")
    email = f"rabo_{suffix}@example.com"
    parent_admin = db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    assert parent_admin, "Seed admin missing"
    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "full_name": "Rabo Test Moderator",
        "role": "moderateur",
        "phone": f"+{digits}",
        "parent_client_id": parent_admin["id"],
        "client_id": parent_admin["id"],
        "company": "SAWALI",
        "account_status": "active",
    }
    db_sync.users.insert_one(user)
    yield {"user": user, "digits": digits, "email": email, "parent_id": parent_admin["id"]}
    # Cleanup
    db_sync.users.delete_one({"id": user["id"]})
    db_sync.directory_contacts.delete_many({"phone": f"+{digits}"})
    db_sync.directory_contacts.delete_many({"whatsapp": f"+{digits}"})
    db_sync.wa_pending_imports.delete_many({"phone_digits": digits})
    db_sync.whatsapp_messages.delete_many({"phone_digits": digits})
    db_sync.liluvine_pro_sessions.delete_many({"id": {"$regex": f":{digits}$"}})


def test_diagnose_returns_contact_visibility_section(admin_h, fixture_moderator):
    """The enriched diagnose endpoint must include the new
    `contact_visibility` key with directory_contacts + wa_pending_imports + recent_inbound_messages."""
    r = requests.get(
        f"{API}/admin/liluvine-pro/diagnose",
        params={"email": fixture_moderator["email"]},
        headers=admin_h,
        timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("user_found") is True
    cv = data.get("contact_visibility") or {}
    # All the expected diagnostic keys must be present.
    for key in (
        "phone",
        "phone_digits",
        "directory_contacts_count",
        "directory_contacts",
        "wa_pending_imports_count",
        "recent_inbound_messages",
        "user_visible_client_ids",
        "diagnosis",
    ):
        assert key in cv, f"missing diagnostic key: {key}"
    # No directory contact yet → expect the "no contact" diagnosis.
    assert cv["directory_contacts_count"] == 0
    assert any("Aucun contact" in line for line in cv["diagnosis"])


def test_repair_creates_canonical_contact_when_missing(admin_h, db_sync, fixture_moderator):
    """If no directory_contacts row exists for the moderator's phone, the
    repair endpoint must create one in the parent tenant scope with
    name = full_name."""
    digits = fixture_moderator["digits"]
    parent_id = fixture_moderator["parent_id"]
    # Pre-condition: no contact yet
    assert db_sync.directory_contacts.count_documents({
        "$or": [{"phone": {"$regex": digits}}, {"whatsapp": {"$regex": digits}}]
    }) == 0
    r = requests.post(
        f"{API}/admin/contacts/repair-user-contact",
        json={"email": fixture_moderator["email"]},
        headers=admin_h,
        timeout=15,
    )
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["canonical_scope"] == parent_id
    assert report["canonical_contact_name"] == "Rabo Test Moderator"
    actions = {a["type"] for a in report["actions"]}
    assert "created_canonical_contact" in actions
    # Verify the new contact actually lives in the parent scope with the right name
    row = db_sync.directory_contacts.find_one(
        {"id": report["canonical_contact_id"]},
        {"_id": 0, "client_id": 1, "name": 1, "phone": 1},
    )
    assert row is not None
    assert row["client_id"] == parent_id
    assert row["name"] == "Rabo Test Moderator"
    assert digits in (row.get("phone") or "")


def test_repair_fixes_blank_name(admin_h, db_sync, fixture_moderator):
    """If a contact exists but `name` is blank, repair must fill it from
    the user's full_name."""
    digits = fixture_moderator["digits"]
    parent_id = fixture_moderator["parent_id"]
    # Seed a directory_contacts row with EMPTY name (simulating production bug).
    contact = {
        "id": str(uuid.uuid4()),
        "client_id": parent_id,
        "owner_id": fixture_moderator["user"]["id"],
        "name": "",
        "phone": f"+{digits}",
        "whatsapp": f"+{digits}",
        "shared": True,
    }
    db_sync.directory_contacts.insert_one(contact)
    r = requests.post(
        f"{API}/admin/contacts/repair-user-contact",
        json={"email": fixture_moderator["email"]},
        headers=admin_h,
        timeout=15,
    )
    assert r.status_code == 200, r.text
    report = r.json()
    actions = {a["type"] for a in report["actions"]}
    assert "patched_canonical_contact" in actions
    # Verify the name is now filled
    row = db_sync.directory_contacts.find_one({"id": contact["id"]}, {"_id": 0, "name": 1})
    assert row["name"] == "Rabo Test Moderator"


def test_repair_archives_cross_tenant_duplicate(admin_h, db_sync, fixture_moderator):
    """If a duplicate contact lives in another tenant (cross-tenant
    pollution), repair must flag it without deleting it and still create
    a canonical contact in the user's parent scope."""
    digits = fixture_moderator["digits"]
    parent_id = fixture_moderator["parent_id"]
    # Seed a contact in ANOTHER tenant (random uuid as client_id)
    other_tenant = str(uuid.uuid4())
    cross_contact = {
        "id": str(uuid.uuid4()),
        "client_id": other_tenant,
        "owner_id": other_tenant,
        "name": "Stale Cross-Tenant Row",
        "phone": f"+{digits}",
        "whatsapp": f"+{digits}",
        "shared": True,
    }
    db_sync.directory_contacts.insert_one(cross_contact)

    r = requests.post(
        f"{API}/admin/contacts/repair-user-contact",
        json={"email": fixture_moderator["email"]},
        headers=admin_h,
        timeout=15,
    )
    assert r.status_code == 200, r.text
    report = r.json()
    actions = {a["type"] for a in report["actions"]}
    assert "created_canonical_contact" in actions
    assert "flagged_cross_tenant_duplicate" in actions
    # The cross-tenant duplicate must still exist but now flagged.
    stale = db_sync.directory_contacts.find_one({"id": cross_contact["id"]},
                                                {"_id": 0, "wa_user_link": 1, "wa_user_link_canonical": 1})
    assert stale is not None
    assert stale.get("wa_user_link") == fixture_moderator["user"]["id"]
    # The canonical contact must be in the parent scope
    canonical = db_sync.directory_contacts.find_one({"id": report["canonical_contact_id"]},
                                                    {"_id": 0, "client_id": 1, "name": 1})
    assert canonical["client_id"] == parent_id
    assert canonical["name"] == "Rabo Test Moderator"


def test_repair_requires_takeover_role(db_sync, fixture_moderator):
    """A non-privileged user must get a 403 from the repair endpoint."""
    # Spawn a basic 'client' user
    suffix = uuid.uuid4().hex[:6]
    plain_email = f"plain_{suffix}@example.com"
    # Use the existing seed mechanism: insert a user with role 'client' and a
    # known password hash. We rely on the public /auth/register flow instead
    # to keep the password hashing consistent with the rest of the codebase.
    r = requests.post(
        f"{API}/auth/register",
        json={"email": plain_email, "password": "Password123!", "full_name": "Plain User",
              "company": "X", "phone": "+22890000000"},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        pytest.skip(f"register endpoint refused: {r.status_code} {r.text[:120]}")
    tok = _login(plain_email, "Password123!")
    if not tok:
        pytest.skip("login flow blocked for the new user — skip RBAC check")
    h = {"Authorization": f"Bearer {tok}"}
    try:
        rr = requests.post(
            f"{API}/admin/contacts/repair-user-contact",
            json={"email": fixture_moderator["email"]},
            headers=h,
            timeout=15,
        )
        assert rr.status_code == 403, rr.text
    finally:
        db_sync.users.delete_one({"email": plain_email})
