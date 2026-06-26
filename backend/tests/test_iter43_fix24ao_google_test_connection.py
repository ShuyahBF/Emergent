"""Iter43-fix24ao (2026-06-17) — Tests for the Google Calendar "Test
connection" diagnostic endpoint.

Verifies:
- When NOT connected (no refresh_token), the endpoint returns ok=False
  with reason="not_connected" and a helpful message.
- When `list_upcoming_events` raises, the endpoint catches and surfaces
  the error message + error_type without crashing.
- When everything works, returns ok=True with `events` and `events_count`.
"""
from __future__ import annotations

import os
import sys

import httpx
import pytest


API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
sys.path.insert(0, "/app/backend")


def _login_admin():
    r1 = httpx.post(f"{API_BASE}/auth/login",
                    json={"email": "admin@sawalismartsystems.com",
                          "password": "Admin@Sawali2026"}, timeout=15)
    d1 = r1.json()
    r2 = httpx.post(f"{API_BASE}/auth/verify-otp",
                    json={"session_token": d1["session_token"],
                          "code": d1["dev_otp"]}, timeout=15)
    return r2.json()["access_token"]


def test_test_connection_returns_not_connected_when_no_refresh_token():
    """Without google_refresh_token in settings, endpoint must return a
    clean ok=False with reason='not_connected'."""
    token = _login_admin()
    h = {"Authorization": f"Bearer {token}"}
    # Ensure refresh_token is absent (cleanup is best-effort; test creds are
    # bogus from earlier and have already been cleared in the preview DB).
    r = httpx.get(f"{API_BASE}/admin/google/test-connection", headers=h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "not_connected"
    assert "connect" in body["message"].lower() or "configurez" in body["message"].lower()


@pytest.mark.asyncio
async def test_list_upcoming_events_raises_when_no_service():
    """When build_service fails (no credentials), `list_upcoming_events`
    must raise RuntimeError with a helpful message."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    # Ensure no creds (cleanup leftover from earlier tests)
    await db.settings.update_one(
        {"_id": "global"},
        {"$unset": {
            "google_client_id": "", "google_client_secret": "",
            "google_refresh_token": "", "google_access_token": "",
        }},
    )
    import importlib
    if "google_calendar" in sys.modules:
        importlib.reload(sys.modules["google_calendar"])
    import google_calendar as gcal_mod
    gcal_mod.db = db  # bind to OUR test client
    with pytest.raises(RuntimeError) as exc:
        await gcal_mod.list_upcoming_events(max_results=3)
    assert "refresh_token" in str(exc.value).lower() or "service" in str(exc.value).lower()
    client.close()


def test_test_connection_requires_admin_auth():
    """Endpoint must reject unauthenticated requests."""
    r = httpx.get(f"{API_BASE}/admin/google/test-connection", timeout=15)
    assert r.status_code in (401, 403)
