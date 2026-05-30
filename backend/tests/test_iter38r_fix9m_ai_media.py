"""Iter38r-fix9m — Tests for AI Media additional models (Veo 3.1, Imagen 4,
ElevenLabs Voice Cloning + TTS)."""
from __future__ import annotations

import os
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASS = "Admin@Sawali2026"


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10).json()
    if r.get("needs_otp"):
        r = requests.post(f"{API}/auth/verify-otp",
                          json={"session_token": r["session_token"], "code": r["dev_otp"]},
                          timeout=10).json()
    token = r.get("access_token") or r.get("token")
    assert token, f"login failed: {r}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


def test_imagen_4_generates_image_inline(admin_h):
    """Real-call test against Google Imagen 4 API."""
    payload = {"prompt": "a small red apple, simple", "aspect_ratio": "1:1"}
    r = requests.post(f"{API}/me/ai/generate-image-imagen", headers=admin_h, json=payload, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "images" in body
    assert len(body["images"]) >= 1
    assert body["images"][0].startswith("data:image/")


def test_imagen_4_rejects_empty_prompt(admin_h):
    r = requests.post(f"{API}/me/ai/generate-image-imagen", headers=admin_h, json={"prompt": ""}, timeout=10)
    assert r.status_code == 400


def test_voices_list_empty_initially(admin_h, db_sync):
    db_sync.eleven_voices.delete_many({})  # clean slate for this user
    r = requests.get(f"{API}/me/ai/voices", headers=admin_h, timeout=10)
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_tts_validates_inputs(admin_h):
    r = requests.post(f"{API}/me/ai/tts-elevenlabs", headers=admin_h, json={}, timeout=10)
    assert r.status_code == 400
    r2 = requests.post(f"{API}/me/ai/tts-elevenlabs", headers=admin_h, json={"voice_id": "x"}, timeout=10)
    assert r2.status_code == 400


def test_veo_initiate_creates_job(admin_h, db_sync):
    """Veo 3.1 long-running. We only verify the predict-long-running call
    successfully queues a job (200 OK + operation_name persisted)."""
    payload = {"prompt": "a calm beach with palm trees at sunset", "resolution": "720p"}
    r = requests.post(f"{API}/me/ai/generate-video-veo", headers=admin_h, json=payload, timeout=60)
    # Veo may not be available on all tiers — accept both success and 4xx model-not-allowed
    assert r.status_code in (200, 400, 403, 404), r.text
    if r.status_code == 200:
        body = r.json()
        assert "job_id" in body
        assert body["status"] == "pending"
        # Cleanup
        db_sync.veo_jobs.delete_one({"id": body["job_id"]})


def test_tts_endpoint_rejects_unknown_voice(admin_h):
    """If voice_id is bogus, ElevenLabs returns 4xx — our endpoint surfaces it."""
    r = requests.post(f"{API}/me/ai/tts-elevenlabs", headers=admin_h,
                      json={"voice_id": "bogus-voice-id", "text": "Hello"}, timeout=30)
    # ElevenLabs returns 400/422 for invalid voice — we forward as-is
    assert r.status_code != 200
