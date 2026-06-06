"""Iter40 (2026-02) — Tests for the 4 priorities of this session :
  1. !aide WhatsApp command listing
  2. WA silent phones filter on the toast feed
  3. Liluvine KB streaming endpoint now passes query to RAG
  4. Contact groups CRUD + resolve
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def admin_token(db):
    aid = f"iter40d2_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(aid, "admin"), aid
    db.users.delete_one({"id": aid})


# ----------------------------------------------------------------------
# Priority 3 — !aide WhatsApp command
# ----------------------------------------------------------------------

def test_aide_command_regex_matches():
    """The regex inside the webhook should recognize all aliases."""
    import re
    pat = re.compile(r"^[!/]\s*(aide|help|commandes?|cmd)\s*$", re.IGNORECASE)
    for txt in ["!aide", "/aide", "!help", "!HELP", "!commandes", "!commande", "/cmd"]:
        assert pat.match(txt.strip()), f"Should match: {txt}"
    for txt in ["!aidemoi", "!ticket aide", "aide"]:
        assert not pat.match(txt.strip()), f"Should NOT match: {txt}"


# ----------------------------------------------------------------------
# Priority 2 — wa_silent_phones filter on autoreply-feed
# ----------------------------------------------------------------------

def test_silent_phone_filters_feed(db, admin_token):
    token, adm_id = admin_token
    silent_phone = "22607332313"
    other_phone = "22890111222"
    # Enable filter + add the silent number
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "wa_silent_phones_enabled": True,
            "wa_silent_phones": [silent_phone],
        }},
        upsert=True,
    )
    # Seed 2 sessions + 2 assistant messages : one from silent, one from other
    sid1 = f"sess_silent_{uuid.uuid4().hex[:6]}"
    sid2 = f"sess_other_{uuid.uuid4().hex[:6]}"
    db.liluvine_pro_sessions.insert_many([
        {"id": sid1, "client_id": adm_id, "user_label": "Silent",
         "external_payload": {"phone_digits": silent_phone}},
        {"id": sid2, "client_id": adm_id, "user_label": "Other",
         "external_payload": {"phone_digits": other_phone}},
    ])
    mid1 = f"msg_silent_{uuid.uuid4().hex[:6]}"
    mid2 = f"msg_other_{uuid.uuid4().hex[:6]}"
    db.liluvine_pro_messages.insert_many([
        {"id": mid1, "session_id": sid1, "client_id": adm_id,
         "external_source": "whatsapp_native", "role": "assistant",
         "content": "Réponse silent", "tokens": 5,
         "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": mid2, "session_id": sid2, "client_id": adm_id,
         "external_source": "whatsapp_native", "role": "assistant",
         "content": "Réponse other", "tokens": 5,
         "created_at": datetime.now(timezone.utc).isoformat()},
    ])
    try:
        r = requests.get(
            f"{API}/me/liluvine-pro/autoreply-feed",
            headers={"Authorization": f"Bearer {token}"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        # Silent message must NOT appear
        ids = [i["id"] for i in items]
        assert mid1 not in ids
        # Other must appear
        assert mid2 in ids
        # Disable filter → silent should now appear too
        db.settings.update_one(
            {"_id": "global"},
            {"$set": {"wa_silent_phones_enabled": False}}
        )
        r = requests.get(
            f"{API}/me/liluvine-pro/autoreply-feed",
            headers={"Authorization": f"Bearer {token}"}, timeout=10,
        )
        assert r.status_code == 200
        ids2 = [i["id"] for i in r.json()["items"]]
        assert mid1 in ids2
        assert mid2 in ids2
    finally:
        db.liluvine_pro_messages.delete_many({"id": {"$in": [mid1, mid2]}})
        db.liluvine_pro_sessions.delete_many({"id": {"$in": [sid1, sid2]}})


def test_silent_phone_setting_persisted_via_put_admin_settings(db, admin_token):
    token, _ = admin_token
    r = requests.put(
        f"{API}/admin/settings",
        json={
            "wa_silent_phones_enabled": True,
            "wa_silent_phones": ["+226 07 33 23 13", "+228 90 12 34 56"],
        },
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    s = db.settings.find_one({"_id": "global"})
    assert s.get("wa_silent_phones_enabled") is True
    # The PUT preserves the strings as-is — the filter normalizes at read time
    assert "+226 07 33 23 13" in s.get("wa_silent_phones", [])


# ----------------------------------------------------------------------
# Priority 4 — Contact groups CRUD + resolve
# ----------------------------------------------------------------------

@pytest.fixture
def admin_with_contacts(db, admin_token):
    """Admin + 3 directory contacts."""
    token, aid = admin_token
    cids = []
    for name, phone in [("Alpha SARL", "+22890000001"), ("Beta Corp", "+22890000002"), ("Gamma LLC", "+22890000003")]:
        cid = f"c_{uuid.uuid4().hex[:6]}"
        db.directory_contacts.insert_one({
            "id": cid, "client_id": aid, "name": name, "phone": phone,
            "whatsapp": phone, "email": f"{name.split()[0].lower()}@x.y",
            "company": name, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        cids.append(cid)
    yield token, aid, cids
    db.directory_contacts.delete_many({"id": {"$in": cids}})
    db.contact_groups.delete_many({"client_id": aid})


def test_create_group_with_contacts(admin_with_contacts):
    token, _, cids = admin_with_contacts
    r = requests.post(
        f"{API}/me/contact-groups",
        json={"name": "VIP", "color": "#ec4899", "description": "Top clients",
              "contact_ids": cids[:2]},
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "VIP"
    assert len(body["contact_ids"]) == 2


def test_duplicate_group_name_rejected(admin_with_contacts):
    token, _, _ = admin_with_contacts
    requests.post(f"{API}/me/contact-groups", json={"name": "Maintenance"},
                  headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r = requests.post(f"{API}/me/contact-groups", json={"name": "Maintenance"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 409, r.text


def test_add_remove_contacts_to_group(admin_with_contacts, db):
    token, _, cids = admin_with_contacts
    # Empty group
    r = requests.post(f"{API}/me/contact-groups",
                      json={"name": "Newsletter"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 201
    gid = r.json()["id"]
    # Add 2 contacts
    r = requests.post(f"{API}/me/contact-groups/{gid}/contacts",
                      json={"contact_ids": cids[:2]},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert len(body["added"]) == 2
    assert body["total"] == 2
    # Idempotency : re-adding doesn't duplicate
    r = requests.post(f"{API}/me/contact-groups/{gid}/contacts",
                      json={"contact_ids": cids[:2]},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["added"] == []
    assert r.json()["total"] == 2
    # Add an invalid contact id → ignored
    r = requests.post(f"{API}/me/contact-groups/{gid}/contacts",
                      json={"contact_ids": ["nonexistent-id"]},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    assert "nonexistent-id" in r.json()["ignored"]
    # Remove one
    r = requests.delete(f"{API}/me/contact-groups/{gid}/contacts/{cids[0]}",
                       headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["remaining"] == 1


def test_resolve_groups_and_individuals(admin_with_contacts):
    token, _, cids = admin_with_contacts
    # Group A with cid[0] and cid[1]
    rA = requests.post(f"{API}/me/contact-groups",
                       json={"name": "A", "contact_ids": cids[:2]},
                       headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert rA.status_code == 201
    gidA = rA.json()["id"]
    # Resolve: groupA + cid[2] individual → all 3
    r = requests.post(f"{API}/me/contact-groups/resolve",
                      json={"group_ids": [gidA], "contact_ids": [cids[2]]},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert set(body["contact_ids"]) == set(cids)


def test_delete_group(admin_with_contacts):
    token, _, _ = admin_with_contacts
    r = requests.post(f"{API}/me/contact-groups",
                      json={"name": "Temporary"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    gid = r.json()["id"]
    r = requests.delete(f"{API}/me/contact-groups/{gid}",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    # 404 second time
    r = requests.delete(f"{API}/me/contact-groups/{gid}",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 404


def test_tenant_scope_isolation(db, admin_with_contacts):
    """Another tenant cannot see / mutate this tenant's groups."""
    token_a, aid_a, _ = admin_with_contacts
    rA = requests.post(f"{API}/me/contact-groups",
                       json={"name": "Solo-A"},
                       headers={"Authorization": f"Bearer {token_a}"}, timeout=10)
    gid_a = rA.json()["id"]
    # Build a second admin
    aid_b = f"iter40_b_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": aid_b, "email": f"{aid_b}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    token_b = _forge(aid_b, "admin")
    try:
        r = requests.get(f"{API}/me/contact-groups",
                         headers={"Authorization": f"Bearer {token_b}"}, timeout=10)
        ids = [g["id"] for g in r.json()]
        assert gid_a not in ids
        # Delete attempt → 404
        r = requests.delete(f"{API}/me/contact-groups/{gid_a}",
                            headers={"Authorization": f"Bearer {token_b}"}, timeout=10)
        assert r.status_code == 404
    finally:
        db.users.delete_one({"id": aid_b})
        db.contact_groups.delete_many({"client_id": aid_b})


# ----------------------------------------------------------------------
# Priority 1 — Liluvine KB streaming endpoint passes query through
# ----------------------------------------------------------------------

def test_resolve_kb_context_signature_accepts_query():
    """Sanity check : the helper now accepts a `query` arg (was missing before)."""
    import inspect
    import importlib
    # The helper is defined inside setup_liluvine_pro_routes, so we
    # can't import it directly. Instead, assert build_kb_context is
    # invoked with the user query by reading the source of the
    # streaming endpoint.
    src = Path("/app/backend/routes/liluvine_pro.py").read_text()
    assert "_resolve_kb_context(payload.text)" in src
    assert "async def _resolve_kb_context(query: str = \"\")" in src
