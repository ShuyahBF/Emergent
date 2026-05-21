"""Iter36n — Chat photo upload tests.

Validates:
  - POST /me/chat/{client_id}/messages/photo accepts JPEG/PNG, stores in
    object storage, creates a message with media_url + media_kind=image.
  - Empty / oversized / wrong-MIME uploads are rejected with proper codes.
  - DM recipient validation works (must be a member, not self).
  - GET /me/chat/media/{msg_id} re-validates membership and returns bytes.
  - Outsiders cannot fetch the media even if they know the msg_id.
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

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _token(uid: str, role: str = "client") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def _tiny_jpeg() -> bytes:
    """A minimal 1x1 JPEG. Enough to satisfy MIME sniffing."""
    # Real 1x1 black JPEG (124 bytes) — bare minimum valid file.
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
        "07090908"
        "0a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c283728"
        "2c30313434"
        "1f27393d38323c2e333432ffdb0043010909090c0b0c180d0d1832211c213232"
        "32323232323232323232323232323232323232323232323232323232323232"
        "323232323232323232323232323232323232ffc00011080001000103012200"
        "021101031101ffc4001f0000010501010101010100000000000000000102030405"
        "060708090a0bffc400b5100002010303020403050504040000017d010203000411"
        "05122131410613516107227114328191a1082342b1c11552d1f02433627282090a"
        "161718191a25262728292a3435363738393a434445464748494a5354555657"
        "58595a636465666768696a737475767778797a838485868788898a9293949596"
        "9798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2"
        "d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f"
        "0100030101010101010101010000000000000102030405060708090a0bffc4"
        "00b5110002010204040304070504040001027700010203110405213106124151"
        "0761711322328108144291a1b1c109233352f0156272d10a162434e125f11718"
        "191a262728292a35363738393a434445464748494a535455565758595a6364"
        "65666768696a737475767778797a82838485868788898a92939495969798"
        "999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3"
        "d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000c0301"
        "00021103110000003f00fbf8a28a2800a28a2800a28a2800a28a2800a28a"
        "2800a28a2800a28a2800a28a2800a28a2800ffd9"
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def setup(db):
    """Seed a chat-enabled client with 2 bridged members + 1 outsider."""
    cid = f"ph_client_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": cid, "email": f"{cid}@test.local", "password_hash": "x",
        "full_name": "Photo Client", "role": "client",
        "account_status": "active",
        "features": {"internal_chat": True},
    })
    members = []
    for i in range(2):
        uid = f"ph_user_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": uid, "email": f"{uid}@test.local", "password_hash": "x",
            "full_name": f"Photo User {i}", "role": "client",
            "account_status": "active",
        })
        db.tracked_users.insert_one({
            "id": f"tu_{uuid.uuid4().hex[:6]}", "client_id": cid,
            "name": f"Photo User {i}", "email": f"{uid}@test.local",
            "status": "active", "user_account_id": uid,
        })
        members.append(uid)
    outsider_id = f"ph_out_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": outsider_id, "email": f"{outsider_id}@test.local",
        "password_hash": "x", "full_name": "Outsider",
        "role": "client", "account_status": "active",
    })
    yield {"client_id": cid, "members": members, "outsider_id": outsider_id}
    db.users.delete_many({"id": {"$in": [cid, outsider_id, *members]}})
    db.tracked_users.delete_many({"client_id": cid})
    db.internal_chat_messages.delete_many({"client_id": cid})


class TestPhotoUpload:
    def test_send_jpeg_to_general_creates_message_with_media(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        files = {"photo": ("camera.jpg", _tiny_jpeg(), "image/jpeg")}
        r = requests.post(
            f"{API}/me/chat/{cid}/messages/photo",
            headers=h, files=files, data={"caption": "screenshot"}, timeout=30,
        )
        # 200 if storage is available, 503 otherwise — both are clean
        assert r.status_code in (200, 503), r.text
        if r.status_code == 503:
            pytest.skip("Object storage unavailable in this environment")
        body = r.json()
        assert body["media_kind"] == "image"
        assert body["media_mime"] == "image/jpeg"
        assert body["media_url"].startswith("/api/me/chat/media/")
        assert body["text"] == "screenshot"
        assert body["recipient_id"] is None  # general
        assert body["client_id"] == cid

    def test_send_jpeg_dm(self, setup):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        files = {"photo": ("photo.jpg", _tiny_jpeg(), "image/jpeg")}
        r = requests.post(
            f"{API}/me/chat/{cid}/messages/photo",
            headers=h, files=files, data={"recipient_id": uid_b}, timeout=30,
        )
        if r.status_code == 503:
            pytest.skip("Object storage unavailable")
        assert r.status_code == 200, r.text
        assert r.json()["recipient_id"] == uid_b

    def test_empty_file_400(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        files = {"photo": ("empty.jpg", b"", "image/jpeg")}
        r = requests.post(f"{API}/me/chat/{cid}/messages/photo", headers=h, files=files, timeout=15)
        assert r.status_code == 400

    def test_oversized_413(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        big = b"\xff\xd8" + b"\x00" * (11 * 1024 * 1024)  # 11 MB
        files = {"photo": ("big.jpg", big, "image/jpeg")}
        r = requests.post(f"{API}/me/chat/{cid}/messages/photo", headers=h, files=files, timeout=60)
        assert r.status_code == 413

    def test_wrong_mime_400(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        files = {"photo": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")}
        r = requests.post(f"{API}/me/chat/{cid}/messages/photo", headers=h, files=files, timeout=15)
        assert r.status_code == 400

    def test_cannot_dm_yourself(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        files = {"photo": ("p.jpg", _tiny_jpeg(), "image/jpeg")}
        r = requests.post(
            f"{API}/me/chat/{cid}/messages/photo",
            headers=h, files=files, data={"recipient_id": uid_a}, timeout=15,
        )
        assert r.status_code == 400

    def test_outsider_cannot_upload(self, setup):
        cid = setup["client_id"]
        h = {"Authorization": f"Bearer {_token(setup['outsider_id'])}"}
        files = {"photo": ("p.jpg", _tiny_jpeg(), "image/jpeg")}
        r = requests.post(f"{API}/me/chat/{cid}/messages/photo", headers=h, files=files, timeout=15)
        assert r.status_code == 403


class TestPhotoFetch:
    def test_fetch_media_returns_bytes_for_member(self, setup):
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        h_a = {"Authorization": f"Bearer {_token(uid_a)}"}
        files = {"photo": ("p.jpg", _tiny_jpeg(), "image/jpeg")}
        r = requests.post(
            f"{API}/me/chat/{cid}/messages/photo",
            headers=h_a, files=files, timeout=30,
        )
        if r.status_code == 503:
            pytest.skip("Object storage unavailable")
        assert r.status_code == 200
        msg_id = r.json()["id"]
        # Member B can fetch
        h_b = {"Authorization": f"Bearer {_token(uid_b)}"}
        r2 = requests.get(f"{API}/me/chat/media/{msg_id}", headers=h_b, timeout=20)
        assert r2.status_code == 200
        assert r2.headers.get("Content-Type", "").startswith("image/")
        assert len(r2.content) > 100  # Got real image bytes

    def test_outsider_cannot_fetch(self, setup):
        cid = setup["client_id"]
        uid_a = setup["members"][0]
        h_a = {"Authorization": f"Bearer {_token(uid_a)}"}
        files = {"photo": ("p.jpg", _tiny_jpeg(), "image/jpeg")}
        r = requests.post(f"{API}/me/chat/{cid}/messages/photo", headers=h_a, files=files, timeout=30)
        if r.status_code == 503:
            pytest.skip("Object storage unavailable")
        msg_id = r.json()["id"]
        h_out = {"Authorization": f"Bearer {_token(setup['outsider_id'])}"}
        r2 = requests.get(f"{API}/me/chat/media/{msg_id}", headers=h_out, timeout=15)
        assert r2.status_code == 403

    def test_dm_other_user_cannot_fetch(self, setup, db):
        """Even a same-client member who isn't sender/recipient of a DM
        cannot fetch the media (admins can; this user is role=client)."""
        cid = setup["client_id"]
        uid_a, uid_b = setup["members"]
        # Add a third member to the same client
        uid_c = f"ph_user_{uuid.uuid4().hex[:6]}"
        db.users.insert_one({
            "id": uid_c, "email": f"{uid_c}@test.local", "password_hash": "x",
            "full_name": "Photo User 3rd", "role": "client", "account_status": "active",
        })
        db.tracked_users.insert_one({
            "id": f"tu_{uuid.uuid4().hex[:6]}", "client_id": cid,
            "name": "Photo User 3rd", "email": f"{uid_c}@test.local",
            "status": "active", "user_account_id": uid_c,
        })
        try:
            h_a = {"Authorization": f"Bearer {_token(uid_a)}"}
            files = {"photo": ("p.jpg", _tiny_jpeg(), "image/jpeg")}
            r = requests.post(
                f"{API}/me/chat/{cid}/messages/photo",
                headers=h_a, files=files, data={"recipient_id": uid_b}, timeout=30,
            )
            if r.status_code == 503:
                pytest.skip("Object storage unavailable")
            msg_id = r.json()["id"]
            # User C (member but neither sender nor recipient) is denied
            h_c = {"Authorization": f"Bearer {_token(uid_c)}"}
            r2 = requests.get(f"{API}/me/chat/media/{msg_id}", headers=h_c, timeout=15)
            assert r2.status_code == 403
        finally:
            db.users.delete_one({"id": uid_c})
            db.tracked_users.delete_many({"user_account_id": uid_c})

    def test_unknown_msg_404(self, setup):
        uid_a = setup["members"][0]
        h = {"Authorization": f"Bearer {_token(uid_a)}"}
        r = requests.get(f"{API}/me/chat/media/__nope__", headers=h, timeout=15)
        assert r.status_code == 404
