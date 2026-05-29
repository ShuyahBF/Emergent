"""Iter38r-fix9f — Tests for shared notes/tasks visibility:

1. Tracked user (non-elevated) can NOW create notes/tasks (was 403 before).
2. Tracked user CANNOT create reports/suivis (still elevated-only).
3. Public notes from same tenant are visible to non-elevated tracked users.
4. Private+targeted notes are visible to the target user (existing behaviour
   confirmed by regression).
5. The `scope=mine` filter returns only owned items.
6. The `scope=shared` filter returns only items NOT owned by me.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"), override=False)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30).json()
    if r.get("needs_otp"):
        r = requests.post(f"{API}/auth/verify-otp", json={
            "session_token": r["session_token"], "code": r["dev_otp"],
        }, timeout=30).json()
    return r["access_token"]


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def admin_id(db_sync):
    return db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})["id"]


@pytest.fixture(scope="module")
def tracked_h(admin_h, db_sync, admin_id):
    """Provision a non-elevated tracked user (Consultation) directly in Mongo
    and return its Authorization header."""
    import uuid as _uuid
    import bcrypt
    email = f"fix9f-tracked-{_uuid.uuid4().hex[:6]}@sawalismartsystems.com"
    password = "Test@Sawali2026"
    uid = _uuid.uuid4().hex
    tu_id = _uuid.uuid4().hex
    pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    import datetime as _dt
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    # Insert tracked user record
    db_sync.tracked_users.insert_one({
        "id": tu_id, "client_id": admin_id, "email": email,
        "name": "Fix9f Tracked", "role": "Consultation", "phone": "",
        "created_at": now_iso, "updated_at": now_iso,
    })
    db_sync.users.insert_one({
        "id": uid, "email": email, "full_name": "Fix9f Tracked",
        "role": "tracked", "tracked_role": "Consultation",
        "tracked_user_id": tu_id,
        "parent_client_id": admin_id, "client_id": admin_id,
        "password_hash": pwd_hash, "is_active": True,
        "account_status": "active",
        "created_at": now_iso,
    })
    try:
        token = _login(email, password)
    except Exception as exc:
        # Cleanup before failing
        db_sync.users.delete_one({"id": uid})
        db_sync.tracked_users.delete_one({"id": tu_id})
        pytest.skip(f"Could not log in tracked user: {exc!r}")
    yield {"Authorization": f"Bearer {token}", "_email": email, "_user_id": uid}
    # Cleanup
    db_sync.users.delete_one({"id": uid})
    db_sync.tracked_users.delete_one({"id": tu_id})


@pytest.fixture(scope="module")
def tracked_id(tracked_h):
    return tracked_h["_user_id"]


def _h(tracked_h):
    """Strip the internal _email/_user_id keys from the tracked_h dict."""
    return {"Authorization": tracked_h["Authorization"]}


def test_tracked_user_can_create_notes_and_tasks(tracked_h):
    """Non-elevated tracked users must be allowed to create notes & tasks."""
    h = _h(tracked_h)
    for kind in ("notes", "tasks"):
        r = requests.post(
            f"{API}/me/notes/{kind}",
            headers=h,
            json={"title": f"fix9f {kind} {uuid.uuid4().hex[:6]}", "content_html": "Hello", "is_private": False},
            timeout=30,
        )
        assert r.status_code == 200, f"{kind}: {r.text}"
        # Cleanup
        requests.delete(f"{API}/me/notes/{kind}/{r.json()['id']}", headers=h, timeout=10)


def test_tracked_user_cannot_create_reports_or_suivis(tracked_h):
    """Reports & suivis remain elevated-only (formal documents)."""
    h = _h(tracked_h)
    for kind in ("reports", "suivis"):
        r = requests.post(
            f"{API}/me/notes/{kind}",
            headers=h,
            json={"title": f"fix9f {kind}", "content_html": "x"},
            timeout=30,
        )
        assert r.status_code == 403, f"{kind} should require elevation"


def test_public_note_visible_to_tracked_user(admin_h, tracked_h, db_sync):
    """A non-private note created by admin is visible to any tracked user
    of the same tenant."""
    h = _h(tracked_h)
    title = f"public-note-fix9f-{uuid.uuid4().hex[:6]}"
    r = requests.post(
        f"{API}/me/notes/notes",
        headers=admin_h,
        json={"title": title, "content_html": "Public content", "is_private": False},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    nid = r.json()["id"]
    try:
        r2 = requests.get(f"{API}/me/notes/notes", headers=h, timeout=30)
        assert r2.status_code == 200
        ids = [n["id"] for n in r2.json()]
        assert nid in ids, "public note must be visible to tracked user"
    finally:
        requests.delete(f"{API}/me/notes/notes/{nid}", headers=admin_h, timeout=10)


def test_private_note_hidden_unless_targeted(admin_h, tracked_h, tracked_id, db_sync):
    """A private note from admin is hidden — unless the tracked user is in
    target_user_ids."""
    h = _h(tracked_h)
    title_hidden = f"private-fix9f-{uuid.uuid4().hex[:6]}"
    title_targeted = f"targeted-fix9f-{uuid.uuid4().hex[:6]}"

    r1 = requests.post(f"{API}/me/notes/notes", headers=admin_h, json={
        "title": title_hidden, "content_html": "secret", "is_private": True,
    }, timeout=30)
    r2 = requests.post(f"{API}/me/notes/notes", headers=admin_h, json={
        "title": title_targeted, "content_html": "for you", "is_private": True,
        "target_user_ids": [tracked_id],
    }, timeout=30)
    assert r1.status_code == 200 and r2.status_code == 200
    hid_id = r1.json()["id"]
    tgt_id = r2.json()["id"]
    try:
        r = requests.get(f"{API}/me/notes/notes", headers=h, timeout=30)
        ids = [n["id"] for n in r.json()]
        assert hid_id not in ids, "private note must remain hidden"
        assert tgt_id in ids, "targeted private note must be visible to the target"
    finally:
        requests.delete(f"{API}/me/notes/notes/{hid_id}", headers=admin_h, timeout=10)
        requests.delete(f"{API}/me/notes/notes/{tgt_id}", headers=admin_h, timeout=10)


def test_scope_mine_and_scope_shared(admin_h, tracked_h, db_sync):
    """scope=mine returns only owned items; scope=shared excludes them."""
    h = _h(tracked_h)
    own_title = f"own-fix9f-{uuid.uuid4().hex[:6]}"
    other_title = f"other-fix9f-{uuid.uuid4().hex[:6]}"

    r1 = requests.post(f"{API}/me/notes/notes", headers=h, json={
        "title": own_title, "content_html": "mine", "is_private": False,
    }, timeout=30)
    r2 = requests.post(f"{API}/me/notes/notes", headers=admin_h, json={
        "title": other_title, "content_html": "by admin", "is_private": False,
    }, timeout=30)
    assert r1.status_code == 200 and r2.status_code == 200
    own_id = r1.json()["id"]
    other_id = r2.json()["id"]
    try:
        # scope=mine
        r = requests.get(f"{API}/me/notes/notes?scope=mine", headers=h, timeout=30)
        ids = [n["id"] for n in r.json()]
        assert own_id in ids
        assert other_id not in ids

        # scope=shared
        r = requests.get(f"{API}/me/notes/notes?scope=shared", headers=h, timeout=30)
        ids = [n["id"] for n in r.json()]
        assert own_id not in ids
        assert other_id in ids
    finally:
        requests.delete(f"{API}/me/notes/notes/{own_id}", headers=h, timeout=10)
        requests.delete(f"{API}/me/notes/notes/{other_id}", headers=admin_h, timeout=10)


def test_tenant_id_stamped_on_create(tracked_h, db_sync, admin_id):
    """The `tenant_id` field must be set at creation for new notes."""
    h = _h(tracked_h)
    r = requests.post(f"{API}/me/notes/notes", headers=h, json={
        "title": f"tenant-fix9f-{uuid.uuid4().hex[:6]}", "content_html": "x",
        "is_private": False,
    }, timeout=30)
    assert r.status_code == 200
    nid = r.json()["id"]
    try:
        doc = db_sync.user_notes_personal.find_one({"id": nid}, {"_id": 0, "tenant_id": 1})
        assert doc.get("tenant_id") == admin_id, f"expected tenant_id={admin_id}, got {doc.get('tenant_id')}"
    finally:
        requests.delete(f"{API}/me/notes/notes/{nid}", headers=h, timeout=10)
