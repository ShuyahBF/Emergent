"""Iter43-fix24an (2026-06-17) — Google Calendar OAuth PKCE fix.

Bug: After Google validated the consent screen, clicking "Connecter Google
Calendar" then validating consent → backend returned:
   "Missing code verifier"

Root cause: `google_auth_oauthlib.Flow.authorization_url()` auto-enables
PKCE (generates `code_verifier` + `code_challenge` S256). The
`code_challenge` was sent in the auth URL, but the subsequent `exchange_code`
POST to `/token` did NOT include the matching `code_verifier`, so Google
rejected the exchange.

Fix: Persist `flow.code_verifier` in `settings` during `get_auth_url`, then
load + include it in the `/token` POST body during `exchange_code`, then
clear it (one-shot).
"""
from __future__ import annotations

import os

import httpx
import pytest


API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")


@pytest.mark.asyncio
async def test_get_auth_url_persists_code_verifier():
    """Calling get_auth_url() must store the PKCE code_verifier in settings
    so exchange_code() can include it in the /token POST."""
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # Save snapshot
    s_before = await db.settings.find_one({"_id": "global"}) or {}
    cid_b = s_before.get("google_client_id")
    csec_b = s_before.get("google_client_secret")
    cv_b = s_before.get("google_oauth_code_verifier")
    try:
        # Seed bogus but valid-looking creds (so the flow builds)
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "google_client_id": "test-client.apps.googleusercontent.com",
                "google_client_secret": "GOCSPX-TEST",
            }},
            upsert=True,
        )
        # Import after the env is loaded so `db` module picks the right URL
        import importlib
        if "google_calendar" in sys.modules:
            importlib.reload(sys.modules["google_calendar"])
        import google_calendar as gcal_mod
        gcal_mod.db = db  # bind to OUR test client (avoid event-loop issues)
        url = await gcal_mod.get_auth_url("https://example.com/callback")
        assert url is not None
        assert "accounts.google.com" in url
        # `code_challenge` must appear in the URL (PKCE active)
        assert "code_challenge=" in url
        # And the matching verifier must now be in settings
        s = await db.settings.find_one({"_id": "global"})
        cv = s.get("google_oauth_code_verifier")
        assert cv and len(cv) >= 43  # PKCE verifier ≥ 43 chars
    finally:
        # Restore
        restore = {}
        if cid_b is not None:
            restore["google_client_id"] = cid_b
        if csec_b is not None:
            restore["google_client_secret"] = csec_b
        unset = {}
        if cv_b is None:
            unset["google_oauth_code_verifier"] = ""
        elif cv_b is not None:
            restore["google_oauth_code_verifier"] = cv_b
        ops = {}
        if restore:
            ops["$set"] = restore
        if unset:
            ops["$unset"] = unset
        if ops:
            await db.settings.update_one({"_id": "global"}, ops)
        client.close()


@pytest.mark.asyncio
async def test_exchange_code_sends_code_verifier_in_token_post():
    """exchange_code() must include the persisted code_verifier in the
    /token POST body when one exists."""
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    s_before = await db.settings.find_one({"_id": "global"}) or {}

    try:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "google_client_id": "test-client.apps.googleusercontent.com",
                "google_client_secret": "GOCSPX-TEST",
                "google_oauth_code_verifier": "TEST_VERIFIER_FOR_PKCE_ABC123_AT_LEAST_43_CHARS_LONG",
            }},
            upsert=True,
        )
        import importlib
        if "google_calendar" in sys.modules:
            importlib.reload(sys.modules["google_calendar"])
        import google_calendar as gcal_mod
        # Iter43-fix24an — Bind google_calendar.db to OUR test client to
        # avoid the "Event loop is closed" issue (the module-level `db.py`
        # client was bound to a different/closed event loop).
        gcal_mod.db = db
        # Monkey-patch httpx.AsyncClient to capture the POST data
        captured = {}
        original_async_client = httpx.AsyncClient

        class _MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def post(self, url, data=None, **kw):
                captured["url"] = url
                captured["data"] = data or {}
                class _R:
                    def json(self_):
                        # Return a refresh_token so exchange_code doesn't raise
                        return {"access_token": "AT", "refresh_token": "RT"}
                return _R()

        httpx.AsyncClient = _MockClient
        try:
            out = await gcal_mod.exchange_code("AUTHCODE", "https://example.com/callback")
            assert out == {"ok": True}
            assert captured["url"] == "https://oauth2.googleapis.com/token"
            assert captured["data"].get("code") == "AUTHCODE"
            # KEY ASSERTION: code_verifier must be in the body
            assert captured["data"].get("code_verifier") == "TEST_VERIFIER_FOR_PKCE_ABC123_AT_LEAST_43_CHARS_LONG"
            # And after success, the verifier is cleared (one-shot)
            s_after = await db.settings.find_one({"_id": "global"})
            assert s_after.get("google_oauth_code_verifier") is None
            assert s_after.get("google_refresh_token") == "RT"
        finally:
            httpx.AsyncClient = original_async_client
    finally:
        # Restore all touched fields
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "google_client_id": s_before.get("google_client_id") or "",
                "google_client_secret": s_before.get("google_client_secret") or "",
                "google_refresh_token": s_before.get("google_refresh_token") or "",
                "google_access_token": s_before.get("google_access_token") or "",
            }},
        )
        if "google_oauth_code_verifier" in s_before:
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"google_oauth_code_verifier": s_before["google_oauth_code_verifier"]}},
            )
        client.close()


@pytest.mark.asyncio
async def test_exchange_code_surfaces_google_error_explicitly():
    """When Google returns an error (no refresh_token), the exception
    message must include the Google `error_description`."""
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "google_client_id": "test-client.apps.googleusercontent.com",
            "google_client_secret": "GOCSPX-TEST",
        }},
        upsert=True,
    )
    import importlib
    if "google_calendar" in sys.modules:
        importlib.reload(sys.modules["google_calendar"])
    import google_calendar as gcal_mod
    gcal_mod.db = db
    original = httpx.AsyncClient

    class _MockClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, data=None, **kw):
            class _R:
                def json(self_):
                    return {"error": "invalid_grant",
                            "error_description": "Missing code verifier"}
            return _R()

    httpx.AsyncClient = _MockClient
    try:
        with pytest.raises(RuntimeError) as exc:
            await gcal_mod.exchange_code("AUTHCODE", "https://example.com/callback")
        # Error message must include Google's explicit description
        assert "Missing code verifier" in str(exc.value)
    finally:
        httpx.AsyncClient = original
        client.close()
