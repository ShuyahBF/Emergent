"""Iter43-fix24aw (2026-02-26) — Twitter/X and Facebook integration endpoint contracts.

Validates the new endpoints without performing real OAuth handshakes:
  - Twitter: /api/twitter/status, /api/admin/twitter/config (GET/PUT),
    /api/admin/twitter/oauth/preview-redirect-uri, /api/admin/twitter/oauth/authorize
  - Facebook: /api/facebook/status, /api/admin/facebook/config (GET/PUT),
    /api/admin/facebook/oauth/preview-redirect-uri, /api/admin/facebook/oauth/authorize,
    /api/admin/facebook/pages
  - Auth required on all admin endpoints
  - LinkedIn autopost config now contains also_post_twitter / also_post_facebook
"""
from __future__ import annotations

import os
import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login_admin() -> str:
    r = requests.post(
        f"{BACKEND_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=8,
    )
    body = r.json()
    v = requests.post(
        f"{BACKEND_URL}/api/auth/verify-otp",
        json={"session_token": body["session_token"], "code": body["dev_otp"]},
        timeout=8,
    )
    return v.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# TWITTER
# ============================================================
def test_twitter_status_public_returns_disconnected():
    r = requests.get(f"{BACKEND_URL}/api/twitter/status", timeout=8)
    assert r.status_code in (200, 401, 403), r.text
    if r.status_code == 200:
        body = r.json()
        assert body.get("connected") is False


def test_twitter_admin_endpoints_require_auth():
    for url in [
        f"{BACKEND_URL}/api/admin/twitter/config",
        f"{BACKEND_URL}/api/admin/twitter/oauth/preview-redirect-uri",
        f"{BACKEND_URL}/api/admin/twitter/oauth/authorize",
    ]:
        r = requests.get(url, timeout=8)
        assert r.status_code in (401, 403), f"{url}: {r.status_code}"


def test_twitter_config_get_masks_secret():
    token = _login_admin()
    r = requests.get(f"{BACKEND_URL}/api/admin/twitter/config", headers=_auth(token), timeout=8)
    assert r.status_code == 200, r.text
    body = r.json()
    # Secret must be masked (or empty)
    secret = body.get("client_secret", "")
    if secret:
        assert secret == "********", f"client_secret not masked: {secret!r}"


def test_twitter_preview_redirect_uri():
    token = _login_admin()
    r = requests.get(
        f"{BACKEND_URL}/api/admin/twitter/oauth/preview-redirect-uri",
        headers=_auth(token), timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "redirect_uri" in body
    assert body["redirect_uri"].startswith("http")
    assert "/api/twitter/oauth/callback" in body["redirect_uri"]


def test_twitter_config_put_then_authorize_url():
    token = _login_admin()
    # Save fake creds
    r = requests.put(
        f"{BACKEND_URL}/api/admin/twitter/config",
        headers=_auth(token),
        json={
            "client_id": "FAKE_TWITTER_CID_iter69",
            "client_secret": "FAKE_TWITTER_SECRET_iter69",
        },
        timeout=8,
    )
    assert r.status_code == 200, r.text

    try:
        # Authorize URL must include PKCE + state + tweet scopes
        r = requests.get(
            f"{BACKEND_URL}/api/admin/twitter/oauth/authorize",
            headers=_auth(token), timeout=8,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        url = body.get("authorization_url", "")
        assert url.startswith("https://twitter.com/i/oauth2/authorize"), url
        assert "code_challenge=" in url
        assert "state=" in url
        # Scope should mention tweet.read/write/offline.access
        assert "tweet.read" in url
        assert "tweet.write" in url
        assert "offline.access" in url
    finally:
        # Reset to empty for cleanup (user has not connected Twitter yet)
        requests.put(
            f"{BACKEND_URL}/api/admin/twitter/config",
            headers=_auth(token),
            json={"client_id": "", "client_secret": ""},
            timeout=8,
        )


def test_twitter_authorize_requires_client_id():
    """When client_id is empty, /authorize must return an error (400/422)."""
    token = _login_admin()
    # Ensure empty
    requests.put(
        f"{BACKEND_URL}/api/admin/twitter/config",
        headers=_auth(token),
        json={"client_id": "", "client_secret": ""},
        timeout=8,
    )
    r = requests.get(
        f"{BACKEND_URL}/api/admin/twitter/oauth/authorize",
        headers=_auth(token), timeout=8,
    )
    assert r.status_code in (400, 422, 503), r.text


# ============================================================
# FACEBOOK
# ============================================================
def test_facebook_status_public_returns_disconnected():
    r = requests.get(f"{BACKEND_URL}/api/facebook/status", timeout=8)
    assert r.status_code in (200, 401, 403), r.text
    if r.status_code == 200:
        body = r.json()
        assert body.get("connected") is False


def test_facebook_admin_endpoints_require_auth():
    for url in [
        f"{BACKEND_URL}/api/admin/facebook/config",
        f"{BACKEND_URL}/api/admin/facebook/oauth/preview-redirect-uri",
        f"{BACKEND_URL}/api/admin/facebook/oauth/authorize",
        f"{BACKEND_URL}/api/admin/facebook/pages",
    ]:
        r = requests.get(url, timeout=8)
        assert r.status_code in (401, 403), f"{url}: {r.status_code}"


def test_facebook_config_get_masks_secret():
    token = _login_admin()
    r = requests.get(f"{BACKEND_URL}/api/admin/facebook/config", headers=_auth(token), timeout=8)
    assert r.status_code == 200, r.text
    body = r.json()
    secret = body.get("app_secret", "")
    if secret:
        assert secret == "********", f"app_secret not masked: {secret!r}"


def test_facebook_preview_redirect_uri():
    token = _login_admin()
    r = requests.get(
        f"{BACKEND_URL}/api/admin/facebook/oauth/preview-redirect-uri",
        headers=_auth(token), timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "redirect_uri" in body
    assert body["redirect_uri"].startswith("http")
    assert "/api/facebook/oauth/callback" in body["redirect_uri"]


def test_facebook_config_put_then_authorize_url():
    token = _login_admin()
    r = requests.put(
        f"{BACKEND_URL}/api/admin/facebook/config",
        headers=_auth(token),
        json={
            "app_id": "FAKE_FB_APPID_iter69",
            "app_secret": "FAKE_FB_SECRET_iter69",
        },
        timeout=8,
    )
    assert r.status_code == 200, r.text

    try:
        r = requests.get(
            f"{BACKEND_URL}/api/admin/facebook/oauth/authorize",
            headers=_auth(token), timeout=8,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        url = body.get("authorization_url", "")
        assert "facebook.com" in url
        assert "/dialog/oauth" in url
        assert "state=" in url
        assert "scope=" in url
    finally:
        requests.put(
            f"{BACKEND_URL}/api/admin/facebook/config",
            headers=_auth(token),
            json={"app_id": "", "app_secret": ""},
            timeout=8,
        )


def test_facebook_authorize_requires_app_id():
    token = _login_admin()
    requests.put(
        f"{BACKEND_URL}/api/admin/facebook/config",
        headers=_auth(token),
        json={"app_id": "", "app_secret": ""},
        timeout=8,
    )
    r = requests.get(
        f"{BACKEND_URL}/api/admin/facebook/oauth/authorize",
        headers=_auth(token), timeout=8,
    )
    assert r.status_code in (400, 422, 503), r.text


def test_facebook_pages_requires_connected_user():
    token = _login_admin()
    r = requests.get(
        f"{BACKEND_URL}/api/admin/facebook/pages",
        headers=_auth(token), timeout=8,
    )
    # Not connected → 400 expected
    assert r.status_code in (400, 401, 503), r.text


# ============================================================
# AUTOPOST MULTI-CHANNEL FIELDS
# ============================================================
def test_autopost_config_contains_also_post_flags():
    token = _login_admin()
    r = requests.get(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token), timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "also_post_twitter" in body, f"missing key in: {list(body.keys())}"
    assert "also_post_facebook" in body, f"missing key in: {list(body.keys())}"
    assert isinstance(body["also_post_twitter"], bool)
    assert isinstance(body["also_post_facebook"], bool)


def test_autopost_config_put_updates_also_post_flags():
    token = _login_admin()
    # Set true
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        json={"also_post_twitter": True, "also_post_facebook": True},
        timeout=8,
    )
    assert r.status_code == 200, r.text

    try:
        r = requests.get(
            f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
            headers=_auth(token), timeout=8,
        )
        body = r.json()
        assert body["also_post_twitter"] is True
        assert body["also_post_facebook"] is True
    finally:
        # Reset to defaults
        requests.put(
            f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
            headers=_auth(token),
            json={"also_post_twitter": False, "also_post_facebook": False},
            timeout=8,
        )
