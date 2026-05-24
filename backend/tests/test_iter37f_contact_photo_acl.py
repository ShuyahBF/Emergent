"""Iter37f — Contact photo / wa-sync endpoints accept admin AND superviseur.

Bug reported by user: even as Admin or Superviseur, "Modification non autorisée"
when uploading a contact photo. Root cause: the 3 photo/wa-sync endpoints
only checked `user.role == 'admin'` while the rest of the contact CRUD
correctly accepts admin + superviseur + visible-scope. This test pins
down the fix.
"""
from __future__ import annotations

import io
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
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
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


@pytest.fixture
def supervisor_with_contact(db):
    """Seed a supervisor + a contact owned by ANOTHER user but in their visible scope."""
    sup_id = f"sup_{uuid.uuid4().hex[:6]}"
    other_id = f"other_{uuid.uuid4().hex[:6]}"
    contact_id = f"c_{uuid.uuid4().hex[:6]}"
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@test.local", "password_hash": "x",
         "full_name": "Sup Test", "role": "superviseur", "account_status": "active"},
        {"id": other_id, "email": f"{other_id}@test.local", "password_hash": "x",
         "full_name": "Other Owner", "role": "client", "account_status": "active",
         "parent_client_id": sup_id},
    ])
    db.directory_contacts.insert_one({
        "id": contact_id,
        "name": "Bug Photo Test",
        "phone": "+22600000000",
        "client_id": sup_id,
        "owner_id": other_id,  # NOT the supervisor — must still be editable
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"sup_id": sup_id, "other_id": other_id, "contact_id": contact_id}
    db.users.delete_many({"id": {"$in": [sup_id, other_id]}})
    db.directory_contacts.delete_many({"id": contact_id})


# 1x1 transparent PNG
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\x86s\x18\xc7\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestPhotoEndpointsAclFix:
    def test_supervisor_can_upload_contact_photo(self, supervisor_with_contact):
        ctx = supervisor_with_contact
        h = {"Authorization": f"Bearer {_forge(ctx['sup_id'], role='superviseur')}"}
        files = {"file": ("avatar.png", io.BytesIO(TINY_PNG), "image/png")}
        r = requests.post(f"{API}/me/contacts/{ctx['contact_id']}/photo",
                          headers=h, files=files, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["photo_url"].startswith("/api/files/")

    def test_supervisor_can_delete_contact_photo(self, supervisor_with_contact):
        ctx = supervisor_with_contact
        h = {"Authorization": f"Bearer {_forge(ctx['sup_id'], role='superviseur')}"}
        # First upload one, then delete
        files = {"file": ("avatar.png", io.BytesIO(TINY_PNG), "image/png")}
        up = requests.post(f"{API}/me/contacts/{ctx['contact_id']}/photo",
                           headers=h, files=files, timeout=15)
        assert up.status_code == 200
        dl = requests.delete(f"{API}/me/contacts/{ctx['contact_id']}/photo",
                             headers=h, timeout=15)
        assert dl.status_code == 200, dl.text
        assert dl.json()["ok"] is True

    def test_supervisor_can_wa_sync_contact(self, supervisor_with_contact):
        ctx = supervisor_with_contact
        h = {"Authorization": f"Bearer {_forge(ctx['sup_id'], role='superviseur')}"}
        r = requests.post(f"{API}/me/contacts/{ctx['contact_id']}/wa-sync",
                          headers=h, timeout=15)
        # Must NOT be 403 — may be 200 with empty result or specific message
        # depending on whether the contact has prior inbound messages.
        assert r.status_code != 403, f"Supervisor must be allowed, got {r.status_code}: {r.text}"

    def test_outsider_still_forbidden(self, supervisor_with_contact, db):
        """Regression: a non-owner client outside the visible scope must still get 403."""
        ctx = supervisor_with_contact
        outsider_id = f"outsider_{uuid.uuid4().hex[:6]}"
        # Outsider has NO parent_client_id linking to sup_id, no shared company
        db.users.insert_one({
            "id": outsider_id, "email": f"{outsider_id}@test.local", "password_hash": "x",
            "full_name": "Outsider", "role": "client", "account_status": "active",
        })
        try:
            h = {"Authorization": f"Bearer {_forge(outsider_id)}"}
            files = {"file": ("avatar.png", io.BytesIO(TINY_PNG), "image/png")}
            r = requests.post(f"{API}/me/contacts/{ctx['contact_id']}/photo",
                              headers=h, files=files, timeout=15)
            assert r.status_code == 403, f"Outsider should be 403, got {r.status_code}"
        finally:
            db.users.delete_one({"id": outsider_id})
