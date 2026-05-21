"""Iter36l — Public team presence + Whisper transcription tests."""
from __future__ import annotations

import asyncio
import io
import json
import os
import struct
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
import websockets
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/ws/chat"
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    code = data.get("dev_otp")
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
        timeout=30,
    )
    return r2.json()["access_token"]


def _forge_token(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


# =====================================================================
# Public team presence
# =====================================================================
class TestTeamPresence:
    def test_endpoint_public_no_auth(self):
        r = requests.get(f"{API}/public/team-presence", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "online" in body and "total" in body and "ts" in body
        assert isinstance(body["online"], int)
        assert isinstance(body["total"], int)
        assert body["online"] >= 0
        # Should be >=1 (at least the seeded admin)
        assert body["total"] >= 1

    def test_no_pii_exposed(self):
        r = requests.get(f"{API}/public/team-presence", timeout=15)
        body = r.json()
        # No identifying fields
        for k in ("emails", "names", "users", "user_ids", "online_user_ids"):
            assert k not in body

    @pytest.mark.asyncio
    async def test_online_count_increments_when_admin_connects(self, db):
        admin = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
        token = _forge_token(admin["id"], "admin")
        # Read presence BEFORE
        r0 = requests.get(f"{API}/public/team-presence", timeout=15)
        before = r0.json()["online"]
        # Connect admin via WS
        async with websockets.connect(f"{WS_URL}?token={token}", open_timeout=10) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)  # hello
            # Give the server a moment to register
            await asyncio.sleep(0.3)
            r1 = requests.get(f"{API}/public/team-presence", timeout=15)
            after = r1.json()["online"]
            assert after >= before + 1, f"online expected to go up: before={before} after={after}"
        # After disconnect, the count should drop back (allow brief lag)
        await asyncio.sleep(0.5)
        r2 = requests.get(f"{API}/public/team-presence", timeout=15)
        after_disc = r2.json()["online"]
        assert after_disc <= after


# =====================================================================
# Whisper transcription endpoint — shape/validation only.
# We don't actually hit the OpenAI API in CI (would burn quota); we
# verify that:
#   - missing/empty audio → 400
#   - too-large audio → 413
#   - valid small audio → either 200 with text or 502 with explicit error
# =====================================================================
def _silent_wav(duration_seconds: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Build an in-memory mono PCM WAV file filled with silence."""
    num_samples = int(duration_seconds * sample_rate)
    pcm = b"\x00\x00" * num_samples  # 16-bit silence
    buf = io.BytesIO()
    # RIFF header
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + len(pcm)))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", len(pcm)))
    buf.write(pcm)
    return buf.getvalue()


class TestTranscribe:
    def test_empty_audio_400(self, admin_h):
        files = {"audio": ("empty.wav", b"", "audio/wav")}
        r = requests.post(f"{API}/me/chat/transcribe", headers=admin_h, files=files, timeout=15)
        assert r.status_code == 400

    def test_oversized_audio_413(self, admin_h):
        # 26 MB of zero bytes — over the 25 MB cap
        big = b"\x00" * (26 * 1024 * 1024)
        files = {"audio": ("big.wav", big, "audio/wav")}
        r = requests.post(f"{API}/me/chat/transcribe", headers=admin_h, files=files, timeout=60)
        assert r.status_code == 413

    def test_unauth_rejected(self):
        files = {"audio": ("x.wav", b"abc", "audio/wav")}
        r = requests.post(f"{API}/me/chat/transcribe", files=files, timeout=15)
        assert r.status_code == 401

    def test_valid_wav_returns_text_or_clean_error(self, admin_h):
        """A 0.5s silent WAV should either return empty text (200) or a
        clean 502 with detail — never crash with 500."""
        files = {"audio": ("silence.wav", _silent_wav(0.5), "audio/wav")}
        r = requests.post(f"{API}/me/chat/transcribe", headers=admin_h, files=files, timeout=60)
        assert r.status_code in (200, 502), r.text
        body = r.json()
        if r.status_code == 200:
            assert "text" in body
            assert isinstance(body["text"], str)
        else:
            assert "detail" in body
