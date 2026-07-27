"""2026-02 (fork) — Regression tests for configurable WhatsApp notification sound.

Covers:
  • GET /notification-sounds/presets is public (no auth needed)
  • GET/PUT /admin/notification-sounds/config round-trips values
  • PUT rejects invalid preset keys and out-of-range volumes
  • /me/features exposes wa_notification_sound + url + volume so the frontend
    hook can resolve the effective config without an extra call
  • POST /admin/notification-sounds/upload validates extension + MIME + size
    (500 KB cap) and auto-flips preset → "custom" + stores the URL.
"""
import os
import io
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL.rstrip('/')}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login_admin() -> str:
    """Return a JWT for the admin (OTP resolved inline via dev_otp)."""
    r = requests.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()
    session = body.get("session_token")
    otp = body.get("dev_otp")
    assert session and otp, f"Missing OTP payload: {body}"
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": session, "code": otp},
        timeout=10,
    )
    v.raise_for_status()
    return v.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login_admin()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_presets_public():
    r = requests.get(f"{API}/notification-sounds/presets", timeout=10)
    assert r.status_code == 200
    body = r.json()
    keys = [p["key"] for p in body["presets"]]
    assert "bip" in keys
    assert "ding" in keys
    assert "chime" in keys
    assert "alert" in keys
    assert "subtle" in keys
    assert body["custom_supported"] is True
    assert body["max_upload_bytes"] == 500 * 1024


def test_get_config_default(admin_token: str):
    r = requests.get(
        f"{API}/admin/notification-sounds/config",
        headers=_auth(admin_token),
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert "preset" in body
    assert "url" in body
    assert "volume" in body
    assert 0.0 <= body["volume"] <= 1.0


def test_put_config_roundtrip(admin_token: str):
    # Set to ding + 0.75
    r = requests.put(
        f"{API}/admin/notification-sounds/config",
        headers=_auth(admin_token),
        json={"preset": "ding", "volume": 0.75},
        timeout=10,
    )
    assert r.status_code == 200
    r = requests.get(
        f"{API}/admin/notification-sounds/config",
        headers=_auth(admin_token),
        timeout=10,
    )
    body = r.json()
    assert body["preset"] == "ding"
    assert abs(body["volume"] - 0.75) < 1e-6

    # Reset back to bip + 0.4
    r = requests.put(
        f"{API}/admin/notification-sounds/config",
        headers=_auth(admin_token),
        json={"preset": "bip", "volume": 0.4},
        timeout=10,
    )
    assert r.status_code == 200


def test_put_config_rejects_invalid_preset(admin_token: str):
    r = requests.put(
        f"{API}/admin/notification-sounds/config",
        headers=_auth(admin_token),
        json={"preset": "not_a_valid_key"},
        timeout=10,
    )
    assert r.status_code == 400
    assert "preset" in r.json()["detail"].lower()


def test_put_config_rejects_volume_out_of_range(admin_token: str):
    # Pydantic ge/le → 422
    r = requests.put(
        f"{API}/admin/notification-sounds/config",
        headers=_auth(admin_token),
        json={"volume": 2.0},
        timeout=10,
    )
    assert r.status_code == 422


def test_me_features_exposes_sound_config(admin_token: str):
    r = requests.get(f"{API}/me/features", headers=_auth(admin_token), timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "wa_notification_sound" in body
    assert "wa_notification_sound_url" in body
    assert "wa_notification_volume" in body


def test_upload_rejects_wrong_extension(admin_token: str):
    files = {"file": ("bad.exe", io.BytesIO(b"notaudio"), "audio/mpeg")}
    r = requests.post(
        f"{API}/admin/notification-sounds/upload",
        headers=_auth(admin_token),
        files=files,
        timeout=10,
    )
    assert r.status_code == 400
    assert "Extension" in r.json()["detail"]


def test_upload_rejects_wrong_mime(admin_token: str):
    files = {"file": ("sound.mp3", io.BytesIO(b"payload"), "text/plain")}
    r = requests.post(
        f"{API}/admin/notification-sounds/upload",
        headers=_auth(admin_token),
        files=files,
        timeout=10,
    )
    assert r.status_code == 400
    assert "MIME" in r.json()["detail"] or "audio" in r.json()["detail"].lower()


def test_upload_rejects_oversized(admin_token: str):
    big = b"\x00" * (600 * 1024)  # 600 KB (cap is 500)
    files = {"file": (f"big-{uuid.uuid4().hex}.mp3", io.BytesIO(big), "audio/mpeg")}
    r = requests.post(
        f"{API}/admin/notification-sounds/upload",
        headers=_auth(admin_token),
        files=files,
        timeout=15,
    )
    assert r.status_code == 413
    assert "volumineux" in r.json()["detail"].lower() or "large" in r.json()["detail"].lower()


def test_upload_success_and_sets_custom_preset(admin_token: str):
    payload = b"ID3" + b"\x00" * (10 * 1024 - 3)  # 10 KB fake MP3
    files = {"file": (f"notif-{uuid.uuid4().hex}.mp3", io.BytesIO(payload), "audio/mpeg")}
    r = requests.post(
        f"{API}/admin/notification-sounds/upload",
        headers=_auth(admin_token),
        files=files,
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["url"].startswith("/api/files/")
    assert body["size"] == 10 * 1024

    # Config should now be "custom" with the freshly uploaded URL
    r2 = requests.get(
        f"{API}/admin/notification-sounds/config",
        headers=_auth(admin_token),
        timeout=10,
    )
    body2 = r2.json()
    assert body2["preset"] == "custom"
    assert body2["url"] == body["url"]

    # Reset to preset "bip" so we leave a clean state for other tests
    requests.put(
        f"{API}/admin/notification-sounds/config",
        headers=_auth(admin_token),
        json={"preset": "bip", "volume": 0.4},
        timeout=10,
    )
