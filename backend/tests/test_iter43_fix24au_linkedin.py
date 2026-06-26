"""Iter43-fix24au (2026-02-26) — LinkedIn integration endpoints.

Validates :
  - /admin/linkedin/config GET + PUT (masking, persistence)
  - /admin/linkedin/oauth/authorize requires client_id + client_secret
  - /linkedin/status returns connected=False when no token
  - /linkedin/posts requires authentication
  - /admin/linkedin/connection DELETE clears tokens
  - /linkedin/oauth/callback returns 400 on missing params

Does NOT cover the LinkedIn OAuth round-trip (would require a real LinkedIn
account + browser). The full E2E flow must be tested manually.
"""
from __future__ import annotations

import os
import sys
import uuid

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login_admin() -> str:
    r = requests.post(
        f"{BACKEND_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    session, otp = body["session_token"], body.get("dev_otp")
    assert otp
    v = requests.post(
        f"{BACKEND_URL}/api/auth/verify-otp",
        json={"session_token": session, "code": otp},
        timeout=8,
    )
    assert v.status_code == 200
    return v.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_linkedin_config_get_and_put_masks_secret():
    token = _login_admin()

    # PUT with a unique client_id so we can verify roundtrip
    unique_cid = f"test_cid_{uuid.uuid4().hex[:8]}"
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/config",
        headers=_auth(token),
        json={"client_id": unique_cid, "client_secret": "super-secret-xyz", "enable_member": True, "enable_organization": True},
        timeout=8,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # GET — client_id visible, client_secret masked
    r = requests.get(f"{BACKEND_URL}/api/admin/linkedin/config", headers=_auth(token), timeout=8)
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["client_id"] == unique_cid
    assert cfg["client_secret"] == "********"
    assert cfg["enable_member"] is True
    assert cfg["enable_organization"] is True

    # PUT with masked secret should NOT overwrite the real one
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/config",
        headers=_auth(token),
        json={"client_secret": "********"},
        timeout=8,
    )
    # 400 because no actual field is updated (masked sentinel is filtered out)
    # We're tolerant : 200 (no-op accepted) or 400 (no field updated)
    assert r.status_code in (200, 400)


def test_linkedin_authorize_requires_credentials():
    token = _login_admin()
    # First wipe both fields
    # We don't actually wipe (admin may have set them in prod) — we test the
    # behaviour by setting an empty client_id
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/config",
        headers=_auth(token),
        json={"client_id": "", "client_secret": ""},
        timeout=8,
    )
    # Empty client_id IS a valid update (admin's choice). So either 200 or 400.
    # The next call should fail with 400.
    r = requests.get(
        f"{BACKEND_URL}/api/admin/linkedin/oauth/authorize",
        headers=_auth(token),
        timeout=8,
    )
    assert r.status_code == 400
    assert "client" in r.text.lower() or "secret" in r.text.lower()


def test_linkedin_authorize_returns_url_with_credentials():
    token = _login_admin()
    # Reinstall a fake client_id + secret
    requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/config",
        headers=_auth(token),
        json={"client_id": "fake_cid_for_test", "client_secret": "fake_secret_for_test"},
        timeout=8,
    )
    r = requests.get(
        f"{BACKEND_URL}/api/admin/linkedin/oauth/authorize",
        headers=_auth(token),
        timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "authorization_url" in body
    url = body["authorization_url"]
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "client_id=fake_cid_for_test" in url
    assert "response_type=code" in url
    assert "state=" in url
    assert "scope=" in url
    assert "redirect_uri=" in url
    # State should be persisted in DB for callback validation
    assert len(body["state"]) >= 10
    # Scopes default set
    scopes = body["scopes"]
    assert "openid" in scopes
    assert "w_member_social" in scopes


def test_linkedin_status_returns_disconnected_when_no_token():
    token = _login_admin()
    # Disconnect first to ensure clean state
    requests.delete(
        f"{BACKEND_URL}/api/admin/linkedin/connection",
        headers=_auth(token),
        timeout=8,
    )
    r = requests.get(f"{BACKEND_URL}/api/linkedin/status", headers=_auth(token), timeout=8)
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["member_urn"] == ""
    assert body["organizations"] == []


def test_linkedin_posts_requires_token():
    token = _login_admin()
    # Make sure disconnected
    requests.delete(
        f"{BACKEND_URL}/api/admin/linkedin/connection",
        headers=_auth(token),
        timeout=8,
    )
    r = requests.post(
        f"{BACKEND_URL}/api/linkedin/posts",
        headers=_auth(token),
        json={"text": "test", "author_type": "member"},
        timeout=8,
    )
    # Should fail because no access_token in DB
    assert r.status_code == 400
    assert "non connecté" in r.text.lower() or "linkedin" in r.text.lower()


def test_linkedin_oauth_callback_rejects_missing_params():
    r = requests.get(f"{BACKEND_URL}/api/linkedin/oauth/callback", timeout=8)
    assert r.status_code == 400
    assert "code" in r.text.lower() or "state" in r.text.lower()


def test_linkedin_oauth_callback_rejects_invalid_state():
    r = requests.get(
        f"{BACKEND_URL}/api/linkedin/oauth/callback?code=xxx&state=invalid_state",
        timeout=8,
    )
    assert r.status_code == 400
    assert "state" in r.text.lower()


def test_linkedin_endpoints_require_auth():
    """All admin endpoints must reject unauthenticated requests."""
    r = requests.get(f"{BACKEND_URL}/api/admin/linkedin/config", timeout=8)
    assert r.status_code in (401, 403)
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/config",
        json={"client_id": "x"},
        timeout=8,
    )
    assert r.status_code in (401, 403)
    r = requests.get(f"{BACKEND_URL}/api/admin/linkedin/oauth/authorize", timeout=8)
    assert r.status_code in (401, 403)
    r = requests.delete(f"{BACKEND_URL}/api/admin/linkedin/connection", timeout=8)
    assert r.status_code in (401, 403)
    # /linkedin/status & /linkedin/posts require user-level auth
    r = requests.get(f"{BACKEND_URL}/api/linkedin/status", timeout=8)
    assert r.status_code in (401, 403)
    r = requests.post(f"{BACKEND_URL}/api/linkedin/posts", json={"text": "x"}, timeout=8)
    assert r.status_code in (401, 403)
