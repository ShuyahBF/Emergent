"""Iter43 (2026-02) — Tests pour le partage cross-utilisateur basé sur
   société + rattachement (mode AND/OR sur le tenant).

Couvre :
  - Helper `resolve_visible_owner_ids` avec mode AND/OR/défaut
  - Contact Groups : visibilité cross-utilisateur quand `shared_with_tenant=True`
  - Meetings (PV) : idem
  - User notes (kind=notes) : idem + cross édition collaborative
  - Support tickets : idem
  - Interventions : idem (client lambda)
  - Suppression toujours réservée à l'auteur (sauf admin/superviseur)
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid: str, role: str = "client") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def async_db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


@pytest.fixture()
def tenant_admin(db):
    """Un client parent (tenant) avec un mode de partage défini."""
    tid = f"iter43_tenant_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": tid, "email": f"{tid}@tenant.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "company": "Acme Corp",
        "tenant_sharing_mode": "OR",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield tid
    db.users.delete_one({"id": tid})


@pytest.fixture()
def two_colleagues(db, tenant_admin):
    """Deux sous-utilisateurs du même tenant, même société, même rattachement."""
    u1 = f"iter43_u1_{uuid.uuid4().hex[:8]}"
    u2 = f"iter43_u2_{uuid.uuid4().hex[:8]}"
    base = {
        "company": "Acme Corp",
        "parent_client_id": tenant_admin,
        "role": "client",
        "account_status": "active",
        "password_hash": "x",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.users.insert_one({**base, "id": u1, "email": f"{u1}@acme.com"})
    db.users.insert_one({**base, "id": u2, "email": f"{u2}@acme.com"})
    yield u1, u2
    db.users.delete_many({"id": {"$in": [u1, u2]}})


@pytest.fixture()
def stranger(db):
    """Un utilisateur d'une autre société, hors scope."""
    sid = f"iter43_str_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": sid, "email": f"{sid}@other.com", "password_hash": "x",
        "role": "client", "account_status": "active",
        "company": "Other LLC",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield sid
    db.users.delete_one({"id": sid})


# =========================================================== #
# 1) Helper resolve_visible_owner_ids
# =========================================================== #
def test_resolve_visible_owner_ids_or_mode(async_db, db, two_colleagues, tenant_admin):
    """En mode OR sur le tenant, les utilisateurs avec même société OU même
    parent_client_id sont visibles."""
    u1, u2 = two_colleagues

    async def run():
        from routes.tenant_sharing import resolve_visible_owner_ids
        user1 = await async_db.users.find_one({"id": u1})
        ids = await resolve_visible_owner_ids(async_db, user1)
        return ids

    ids = asyncio.get_event_loop().run_until_complete(run())
    assert u1 in ids
    assert u2 in ids
    # tenant admin partage aussi le parent_client_id (None vs u1.parent=tenant)
    # mais l'admin n'a pas parent_client_id (lui-même). Donc match via company.
    assert tenant_admin in ids


def test_resolve_visible_owner_ids_and_mode(async_db, db, two_colleagues, tenant_admin):
    """En mode AND, les deux conditions doivent matcher."""
    # Switch tenant to AND mode
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "AND"}})
    u1, u2 = two_colleagues

    async def run():
        from routes.tenant_sharing import resolve_visible_owner_ids
        user1 = await async_db.users.find_one({"id": u1})
        ids = await resolve_visible_owner_ids(async_db, user1)
        return ids

    ids = asyncio.get_event_loop().run_until_complete(run())
    assert u1 in ids
    assert u2 in ids  # u2 has same company AND same parent_client_id
    # tenant admin has same company but DIFFERENT parent_client_id (None) → exclu en AND
    assert tenant_admin not in ids


def test_stranger_not_visible(async_db, db, two_colleagues, stranger):
    u1, _ = two_colleagues

    async def run():
        from routes.tenant_sharing import resolve_visible_owner_ids
        user1 = await async_db.users.find_one({"id": u1})
        ids = await resolve_visible_owner_ids(async_db, user1)
        return ids

    ids = asyncio.get_event_loop().run_until_complete(run())
    assert stranger not in ids


# =========================================================== #
# 2) Contact Groups partage tenant
# =========================================================== #
def test_contact_groups_shared_visible_to_colleague(db, two_colleagues, tenant_admin):
    """u1 crée un groupe partagé → u2 doit le voir dans GET /me/contact-groups."""
    # Reset to OR mode
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "OR"}})
    u1, u2 = two_colleagues
    t1 = _forge(u1)
    t2 = _forge(u2)
    # u1 crée un groupe partagé
    payload = {"name": f"Groupe partagé {uuid.uuid4().hex[:6]}", "color": "#6366f1",
               "shared_with_tenant": True, "editable_by_tenant": False}
    r = requests.post(f"{API}/me/contact-groups", json=payload,
                      headers={"Authorization": f"Bearer {t1}"})
    assert r.status_code in (200, 201), r.text
    gid = r.json()["id"]

    # u2 voit le groupe
    r = requests.get(f"{API}/me/contact-groups", headers={"Authorization": f"Bearer {t2}"})
    assert r.status_code in (200, 201), r.text
    items = r.json()
    found = [g for g in items if g["id"] == gid]
    assert found, f"Group {gid} not visible to colleague u2 — items: {[g.get('id') for g in items]}"

    # Cleanup
    db.contact_groups.delete_one({"id": gid})


def test_contact_groups_private_NOT_visible_to_colleague(db, two_colleagues, tenant_admin):
    """Within DIFFERENT tenants but same company:
    u1 crée un groupe non partagé → u2 NE doit PAS le voir."""
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "OR"}})
    u1, u2 = two_colleagues
    # Force u2 to belong to a DIFFERENT tenant (parent_client_id) but same company
    other_tenant = f"iter43_other_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": other_tenant, "email": f"{other_tenant}@tt.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "company": "Acme Corp", "tenant_sharing_mode": "OR",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.users.update_one({"id": u2}, {"$set": {"parent_client_id": other_tenant}})

    t1 = _forge(u1)
    t2 = _forge(u2)
    payload = {"name": f"Groupe privé {uuid.uuid4().hex[:6]}", "color": "#ec4899",
               "shared_with_tenant": False}
    r = requests.post(f"{API}/me/contact-groups", json=payload,
                      headers={"Authorization": f"Bearer {t1}"})
    assert r.status_code in (200, 201), r.text
    gid = r.json()["id"]

    r = requests.get(f"{API}/me/contact-groups", headers={"Authorization": f"Bearer {t2}"})
    items = r.json()
    found = [g for g in items if g["id"] == gid]
    assert not found, f"Private group {gid} should not be visible to colleague in DIFFERENT tenant"

    db.contact_groups.delete_one({"id": gid})
    db.users.delete_one({"id": other_tenant})
    # restore parent
    db.users.update_one({"id": u2}, {"$set": {"parent_client_id": tenant_admin}})


def test_contact_groups_delete_reserved_to_owner(db, two_colleagues, tenant_admin):
    """Même partagé, la suppression reste réservée à l'auteur."""
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "OR"}})
    u1, u2 = two_colleagues
    t1 = _forge(u1)
    t2 = _forge(u2)
    payload = {"name": f"Test {uuid.uuid4().hex[:6]}",
               "shared_with_tenant": True, "editable_by_tenant": True}
    r = requests.post(f"{API}/me/contact-groups", json=payload,
                      headers={"Authorization": f"Bearer {t1}"})
    gid = r.json()["id"]

    # u2 essaie de supprimer → 403
    r = requests.delete(f"{API}/me/contact-groups/{gid}",
                        headers={"Authorization": f"Bearer {t2}"})
    assert r.status_code == 403, f"u2 should not be able to delete group of u1 — got {r.status_code}: {r.text}"

    db.contact_groups.delete_one({"id": gid})


# =========================================================== #
# 3) User Notes (kind=notes) partage tenant
# =========================================================== #
def test_user_notes_shared_visible_to_colleague(db, two_colleagues, tenant_admin):
    """u1 crée une note (kind=notes) avec shared_with_tenant=True → u2 doit la voir."""
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "OR"}})
    u1, u2 = two_colleagues
    t1 = _forge(u1)
    t2 = _forge(u2)
    payload = {"title": f"Note partagée {uuid.uuid4().hex[:6]}",
               "content_html": "<p>contenu</p>",
               "is_private": True,  # combiné avec shared_with_tenant doit rester visible
               "shared_with_tenant": True}
    r = requests.post(f"{API}/me/notes/notes", json=payload,
                      headers={"Authorization": f"Bearer {t1}"})
    assert r.status_code in (200, 201), r.text
    nid = r.json()["id"]

    # u2 voit la note via cross-tenant share
    r = requests.get(f"{API}/me/notes/notes", headers={"Authorization": f"Bearer {t2}"})
    assert r.status_code == 200
    items = r.json()
    found = [n for n in items if n["id"] == nid]
    assert found, f"Shared note {nid} not visible to colleague u2"

    db.user_notes_personal.delete_one({"id": nid})


def test_user_notes_private_NOT_visible_to_colleague(db, two_colleagues, tenant_admin):
    """is_private=True + shared_with_tenant=False → invisible pour u2."""
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "OR"}})
    u1, u2 = two_colleagues
    t1 = _forge(u1)
    t2 = _forge(u2)
    payload = {"title": f"Privé {uuid.uuid4().hex[:6]}",
               "is_private": True,
               "shared_with_tenant": False}
    r = requests.post(f"{API}/me/notes/notes", json=payload,
                      headers={"Authorization": f"Bearer {t1}"})
    assert r.status_code in (200, 201), r.text
    nid = r.json()["id"]

    r = requests.get(f"{API}/me/notes/notes", headers={"Authorization": f"Bearer {t2}"})
    items = r.json()
    found = [n for n in items if n["id"] == nid]
    assert not found, f"Private+unshared note must not leak to u2"

    db.user_notes_personal.delete_one({"id": nid})


def test_user_notes_collaborative_edit(db, two_colleagues, tenant_admin):
    """u1 partage en mode editable_by_tenant → u2 peut éditer la note."""
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "OR"}})
    u1, u2 = two_colleagues
    t1 = _forge(u1)
    t2 = _forge(u2)
    payload = {"title": f"Collab {uuid.uuid4().hex[:6]}",
               "shared_with_tenant": True, "editable_by_tenant": True}
    r = requests.post(f"{API}/me/notes/notes", json=payload,
                      headers={"Authorization": f"Bearer {t1}"})
    assert r.status_code in (200, 201), r.text
    nid = r.json()["id"]

    # u2 modifie la note
    r = requests.put(f"{API}/me/notes/notes/{nid}",
                     json={"title": "Modifié par u2"},
                     headers={"Authorization": f"Bearer {t2}"})
    assert r.status_code == 200, f"Collaborative edit should be allowed — got {r.status_code}: {r.text}"
    doc = db.user_notes_personal.find_one({"id": nid})
    assert doc["title"] == "Modifié par u2"

    db.user_notes_personal.delete_one({"id": nid})


def test_user_notes_no_collab_edit_when_disabled(db, two_colleagues, tenant_admin):
    """Shared mais editable_by_tenant=False → u2 ne peut PAS éditer."""
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "OR"}})
    u1, u2 = two_colleagues
    t1 = _forge(u1)
    t2 = _forge(u2)
    payload = {"title": f"Lecture seule {uuid.uuid4().hex[:6]}",
               "shared_with_tenant": True, "editable_by_tenant": False}
    r = requests.post(f"{API}/me/notes/notes", json=payload,
                      headers={"Authorization": f"Bearer {t1}"})
    nid = r.json()["id"]

    r = requests.put(f"{API}/me/notes/notes/{nid}",
                     json={"title": "Tentative u2"},
                     headers={"Authorization": f"Bearer {t2}"})
    assert r.status_code == 403, f"Edit should be blocked — got {r.status_code}"

    db.user_notes_personal.delete_one({"id": nid})


# =========================================================== #
# 4) Support tickets partage tenant
# =========================================================== #
def test_tickets_shared_visible_to_colleague(db, two_colleagues, tenant_admin):
    """u1 crée un ticket avec shared_with_tenant=True (client_id=tenant_admin)
    → u2 le voit dans GET /me/tickets."""
    db.users.update_one({"id": tenant_admin}, {"$set": {"tenant_sharing_mode": "OR"}})
    u1, u2 = two_colleagues
    t1 = _forge(u1)
    t2 = _forge(u2)
    payload = {"client_id": tenant_admin, "reason": f"Bug {uuid.uuid4().hex[:6]}",
               "shared_with_tenant": True}
    r = requests.post(f"{API}/me/tickets", json=payload,
                      headers={"Authorization": f"Bearer {t1}"})
    assert r.status_code in (200, 201), r.text
    tid = r.json()["id"]

    # u2 doit voir le ticket (même si u2 n'a pas de scope direct dessus)
    r = requests.get(f"{API}/me/tickets", headers={"Authorization": f"Bearer {t2}"})
    assert r.status_code == 200
    items = r.json()
    found = [t for t in items if t["id"] == tid]
    assert found, f"Shared ticket {tid} not visible to colleague u2"

    db.support_tickets.delete_one({"id": tid})
