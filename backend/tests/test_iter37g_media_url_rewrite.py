"""Iter37g — Media library URLs must be rewritten to the CURRENT request host.

Bug from prod: URLs uploaded via preview kept that host in the database and
returned "Fichier introuvable" when accessed from production. Fix:
`GET /me/media-library` rebuilds `public_url` from the current request host
by looking up the relative `url` in `db.files`.
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
def user_with_legacy_media(db):
    """Seed a user + a media item whose stored public_url is a STALE host."""
    uid = f"u_{uuid.uuid4().hex[:6]}"
    file_id = f"f_{uuid.uuid4().hex[:6]}"
    media_id = f"m_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
        "full_name": "Test", "role": "client", "account_status": "active",
        "client_id": uid, "created_at": now,
    })
    # Files row with a relative URL (this is the canonical storage path)
    db.files.insert_one({
        "id": file_id,
        "url": f"/api/files/{file_id}.pdf",
        "filename": "document.pdf",
        "uploaded_at": now,
    })
    # Media library entry with a STALE absolute URL (simulates pre-fix prod data)
    stale_url = f"https://OLD-HOSTNAME-DELETED.example.com/api/files/{file_id}.pdf"
    db.media_library.insert_one({
        "id": media_id,
        "client_id": uid,
        "file_id": file_id,
        "title": "Old upload",
        "public_url": stale_url,  # Buggy stored URL
        "created_at": now,
    })
    yield {"uid": uid, "file_id": file_id, "media_id": media_id, "stale_url": stale_url}
    db.users.delete_one({"id": uid})
    db.files.delete_one({"id": file_id})
    db.media_library.delete_one({"id": media_id})


class TestMediaLibraryUrlRewrite:
    def test_url_is_rewritten_to_current_host(self, user_with_legacy_media):
        """The returned `public_url` must point to the CURRENT host, not the stale one."""
        ctx = user_with_legacy_media
        h = {"Authorization": f"Bearer {_forge(ctx['uid'])}"}
        r = requests.get(f"{API}/me/media-library", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        items = r.json()
        target = next((it for it in items if it["id"] == ctx["media_id"]), None)
        assert target is not None, f"Seeded media not in response. Got {len(items)} items."
        # Must NOT contain the stale hostname
        assert "OLD-HOSTNAME-DELETED" not in target["public_url"], (
            f"Stale URL leaked: {target['public_url']}"
        )
        # Must contain the current API host AND the file path
        assert f"/api/files/{ctx['file_id']}.pdf" in target["public_url"]
        # Should start with http(s)://
        assert target["public_url"].startswith(("http://", "https://"))

    def test_url_filter_by_source_still_works(self, db):
        """Regression guard: `?source=…` filter still works after the rewrite."""
        uid = f"u_{uuid.uuid4().hex[:6]}"
        fid = f"f_{uuid.uuid4().hex[:6]}"
        mid = f"m_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc).isoformat()
        db.users.insert_one({
            "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
            "role": "client", "account_status": "active", "client_id": uid, "created_at": now,
        })
        db.files.insert_one({"id": fid, "url": f"/api/files/{fid}.jpg", "uploaded_at": now})
        db.media_library.insert_one({
            "id": mid, "client_id": uid, "file_id": fid, "source": "whatsapp_inbound",
            "public_url": f"https://stale.example.com/api/files/{fid}.jpg",
            "created_at": now,
        })
        try:
            h = {"Authorization": f"Bearer {_forge(uid)}"}
            r = requests.get(f"{API}/me/media-library",
                             params={"source": "whatsapp_inbound"}, headers=h, timeout=15)
            assert r.status_code == 200
            items = r.json()
            assert any(it["id"] == mid for it in items)
            # No source mismatch
            for it in items:
                assert it.get("source") == "whatsapp_inbound"
                assert "stale.example.com" not in (it.get("public_url") or "")
        finally:
            db.users.delete_one({"id": uid})
            db.files.delete_one({"id": fid})
            db.media_library.delete_one({"id": mid})
