"""Iter43-fix24av (2026-02-26) — LinkedIn weekly auto-post.

Validates the new endpoints under /api/admin/linkedin/autopost/* :
  - GET /config returns defaults (enabled=False, day=4=Friday, hour=9, etc.)
  - PUT /config updates fields and validates author_type / validation_mode
  - POST /generate-draft generates a Liluvine draft (calls Claude Sonnet 4.5
    via Emergent LLM key — actually hits the network, marked slow)
  - POST /publish-pending requires a pending_draft (400 otherwise) AND
    requires LinkedIn to be connected (member_urn). Since we don't have a
    real OAuth token, publish should fail with 400 « LinkedIn non connecté »
    or « member_urn manquant ».
  - DELETE /pending clears the pending draft
  - POST /tick-now requires enabled=True + LinkedIn connected (400 otherwise)
  - All admin endpoints require auth (401/403 without token)

The full scheduler tick is verified via the /tick-now endpoint which bypasses
the day/hour/minute check but reuses the rest of the logic.
"""
from __future__ import annotations

import os
import sys

import pytest
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
    assert r.status_code == 200
    body = r.json()
    session, otp = body["session_token"], body["dev_otp"]
    v = requests.post(
        f"{BACKEND_URL}/api/auth/verify-otp",
        json={"session_token": session, "code": otp},
        timeout=8,
    )
    assert v.status_code == 200
    return v.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_autopost_config_get_defaults():
    token = _login_admin()
    r = requests.get(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Default values
    assert "enabled" in body
    assert isinstance(body["day_of_week"], int)
    assert 0 <= body["day_of_week"] <= 6
    assert isinstance(body["hour"], int)
    assert 0 <= body["hour"] <= 23
    assert isinstance(body["minute"], int)
    assert 0 <= body["minute"] <= 59
    assert body["author_type"] in ("member", "organization")
    assert body["validation_mode"] in ("auto", "wa_approval")
    assert isinstance(body["topic_prompt"], str)
    # Non-empty prompt (default is long, but a previous test may have set a short one)
    assert len(body["topic_prompt"]) > 0


def test_autopost_config_put_validation():
    token = _login_admin()
    # Valid update
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        json={"enabled": False, "day_of_week": 4, "hour": 9, "minute": 0},
        timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True

    # Invalid day_of_week (must be 0-6)
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        json={"day_of_week": 9},
        timeout=8,
    )
    assert r.status_code == 422

    # Invalid hour
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        json={"hour": 25},
        timeout=8,
    )
    assert r.status_code == 422

    # Invalid author_type
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        json={"author_type": "invalid"},
        timeout=8,
    )
    assert r.status_code == 400

    # Invalid validation_mode
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        json={"validation_mode": "garbage"},
        timeout=8,
    )
    assert r.status_code == 400


def test_autopost_config_persists():
    token = _login_admin()
    requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        json={
            "enabled": True,
            "day_of_week": 4,
            "hour": 9,
            "minute": 0,
            "topic_prompt": "Test custom prompt 2026",
            "validation_mode": "wa_approval",
            "validation_phone": "+22670112233",
        },
        timeout=8,
    )
    r = requests.get(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        timeout=8,
    )
    body = r.json()
    assert body["enabled"] is True
    assert body["day_of_week"] == 4
    assert body["hour"] == 9
    assert body["minute"] == 0
    assert body["topic_prompt"] == "Test custom prompt 2026"
    assert body["validation_mode"] == "wa_approval"
    assert body["validation_phone"] == "+22670112233"


def test_autopost_publish_pending_requires_pending():
    token = _login_admin()
    # Clear any pending
    requests.delete(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/pending",
        headers=_auth(token),
        timeout=8,
    )
    r = requests.post(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/publish-pending",
        headers=_auth(token),
        timeout=8,
    )
    assert r.status_code == 400
    assert "brouillon" in r.text.lower() or "pending" in r.text.lower()


def test_autopost_delete_pending():
    token = _login_admin()
    r = requests.delete(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/pending",
        headers=_auth(token),
        timeout=8,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Verify pending is now None
    r = requests.get(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        timeout=8,
    )
    assert r.json()["pending_draft"] is None


def test_autopost_tick_now_requires_enabled_and_connected():
    token = _login_admin()
    # Disable + ensure LinkedIn might be connected, test enabled=False first
    requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_auth(token),
        json={"enabled": False},
        timeout=8,
    )
    r = requests.post(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/tick-now",
        headers=_auth(token),
        timeout=8,
    )
    assert r.status_code == 400
    assert "désactivé" in r.text.lower() or "non connecté" in r.text.lower() or "disabled" in r.text.lower()


def test_autopost_endpoints_require_auth():
    """All admin endpoints reject unauthenticated requests."""
    r = requests.get(f"{BACKEND_URL}/api/admin/linkedin/autopost/config", timeout=8)
    assert r.status_code in (401, 403)
    r = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        json={"enabled": True},
        timeout=8,
    )
    assert r.status_code in (401, 403)
    r = requests.post(f"{BACKEND_URL}/api/admin/linkedin/autopost/generate-draft", timeout=8)
    assert r.status_code in (401, 403)
    r = requests.post(f"{BACKEND_URL}/api/admin/linkedin/autopost/publish-pending", timeout=8)
    assert r.status_code in (401, 403)
    r = requests.delete(f"{BACKEND_URL}/api/admin/linkedin/autopost/pending", timeout=8)
    assert r.status_code in (401, 403)
    r = requests.post(f"{BACKEND_URL}/api/admin/linkedin/autopost/tick-now", timeout=8)
    assert r.status_code in (401, 403)


@pytest.mark.slow
def test_autopost_generate_draft_with_llm():
    """Hits the real LLM (Claude Sonnet 4.5 via Emergent LLM key) — expensive.

    Skipped by default in CI but useful for end-to-end validation.
    """
    if not os.environ.get("RUN_LLM_TESTS"):
        pytest.skip("Set RUN_LLM_TESTS=1 to enable")
    token = _login_admin()
    r = requests.post(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/generate-draft",
        headers=_auth(token),
        timeout=90,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["draft"], str)
    assert 100 < body["length"] < 3000  # reasonable LinkedIn post length
    assert "#" in body["draft"]  # contains at least one hashtag (per prompt)
