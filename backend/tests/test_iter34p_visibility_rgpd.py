"""Iter34p — Tests for cross-scope contact access + RGPD inheritance + admin/clients role inclusion.

Validates:
  • GET /me/contacts/{cid}/messages now uses _resolve_visible_client_ids so a
    contact tagged with a peer client_id (same company) stays accessible
    (the post-migration "Contact introuvable" bug).
  • RGPD anon_* flags are inherited via parent_client_id (priority over
    client_id), so child users get their parent's RGPD configuration even
    when their own client_id is null/self.
  • GET /admin/clients returns users of role admin + moderateur now (was
    only client + superviseur). The SAWALI seed admin is excluded.
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


def _login(email, password):
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


def test_admin_clients_includes_admins_and_moderateurs(admin_h, mongo):
    """GET /admin/clients returns admin + moderateur roles now."""
    # Seed: create one admin client + one moderateur for this test
    extra_admin_id = str(uuid.uuid4())
    extra_mod_id = str(uuid.uuid4())
    extra_admin_email = f"test.admin.34p+{uuid.uuid4().hex[:6]}@sawalitest.local"
    extra_mod_email = f"test.mod.34p+{uuid.uuid4().hex[:6]}@sawalitest.local"
    mongo.users.insert_many([
        {"id": extra_admin_id, "email": extra_admin_email, "password_hash": "x",
         "role": "admin", "full_name": "Test Admin Client 34p",
         "company": "Test Co 34p", "client_id": extra_admin_id},
        {"id": extra_mod_id, "email": extra_mod_email, "password_hash": "x",
         "role": "moderateur", "full_name": "Test Moderateur 34p",
         "company": "Test Co 34p", "client_id": extra_mod_id},
    ])
    try:
        r = requests.get(f"{API}/admin/clients", headers=admin_h, timeout=30)
        assert r.status_code == 200
        emails = {(u.get("email") or "").lower() for u in r.json()}
        assert extra_admin_email.lower() in emails, "admin role should now be visible"
        assert extra_mod_email.lower() in emails, "moderateur role should be visible"
        # SAWALI seeded admin must NEVER appear
        assert ADMIN_EMAIL.lower() not in emails
    finally:
        mongo.users.delete_one({"id": extra_admin_id})
        mongo.users.delete_one({"id": extra_mod_id})


def test_messages_endpoint_uses_visible_scope_after_migration(admin_h, mongo):
    """Iter34p — Even if a contact's client_id matches a peer (company match)
    rather than the viewer's own client_id, the messages endpoint must find it.
    This is the exact failure mode reported after the rabo.f migration.
    """
    sawali_admin = mongo.users.find_one({"email": ADMIN_EMAIL})
    sawali_id = sawali_admin["id"]
    # Create a peer SAWALI user that has a contact under a *different* client_id
    peer_id = str(uuid.uuid4())
    peer_email = f"peer.34p+{uuid.uuid4().hex[:6]}@sawalitest.local"
    mongo.users.insert_one({
        "id": peer_id, "email": peer_email, "password_hash": "x",
        "role": "client", "full_name": "Peer 34p",
        "company": "SAWALI SMART SYSTEMS",  # company-match bridges scope
        "client_id": peer_id, "parent_client_id": peer_id,
    })
    contact_id = str(uuid.uuid4())
    mongo.directory_contacts.insert_one({
        "id": contact_id, "client_id": peer_id, "owner_id": peer_id,
        "name": "Peer's contact", "whatsapp": "+22612345678",
        "created_at": "2026-05-11T00:00:00+00:00",
    })
    try:
        # Logged in as SAWALI admin (client_id=sawali_id, NOT peer_id), the
        # visible-scope bridge via company match must let us find the contact.
        r = requests.get(f"{API}/me/contacts/{contact_id}/messages", headers=admin_h, timeout=30)
        assert r.status_code == 200, f"expected 200 (cross-scope visible), got {r.status_code}: {r.text}"
        body = r.json()
        assert body["contact"]["id"] == contact_id
    finally:
        mongo.directory_contacts.delete_one({"id": contact_id})
        mongo.users.delete_one({"id": peer_id})


def test_rgpd_flags_inherited_via_parent_client_id(admin_h, mongo):
    """When a child user has `parent_client_id` set, /me/features must
    pull anon_* flags from the parent — even if the user's own `client_id`
    points elsewhere or is null. This is the inheritance bug reported."""
    parent_id = str(uuid.uuid4())
    parent_email = f"parent.rgpd+{uuid.uuid4().hex[:6]}@example.com"
    child_id = str(uuid.uuid4())
    child_email = f"child.rgpd+{uuid.uuid4().hex[:6]}@example.com"

    mongo.users.insert_one({
        "id": parent_id, "email": parent_email, "password_hash": "x",
        "role": "client", "full_name": "RGPD Parent",
        "company": "RGPD Co", "client_id": parent_id, "parent_client_id": None,
        "account_status": "active",
        "features": {"anon_phone": True, "anon_email": True},
    })
    mongo.users.insert_one({
        "id": child_id, "email": child_email, "password_hash": "x",
        "role": "client", "full_name": "RGPD Child",
        "company": "RGPD Co",
        "account_status": "active",
        # Critically: child's `client_id` is null so iter34p priority
        # order must reach parent_client_id to find the features.
        "client_id": None, "parent_client_id": parent_id,
    })
    # Forge a JWT for the child using the same secret/algo as the server.
    import sys
    sys.path.insert(0, "/app/backend")
    from auth import create_access_token  # noqa: E402

    try:
        child_token = create_access_token(child_id, "client")
        h = {"Authorization": f"Bearer {child_token}"}
        r = requests.get(f"{API}/me/features", headers=h, timeout=30)
        assert r.status_code == 200, r.text
        feats = r.json().get("features") or {}
        assert feats.get("anon_phone") is True, f"anon_phone should be inherited from parent: {feats}"
        assert feats.get("anon_email") is True, f"anon_email should be inherited from parent: {feats}"
    finally:
        mongo.users.delete_one({"id": parent_id})
        mongo.users.delete_one({"id": child_id})
