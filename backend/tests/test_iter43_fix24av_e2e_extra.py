"""Iter43-fix24av — Extra E2E tests over the public URL.

Validates:
  - GET /api/admin/linkedin/oauth/preview-redirect-uri returns expected fields
  - POST /api/admin/linkedin/autopost/generate-draft (LIVE LLM call) returns
    a valid draft (100<length<3000, contains '#') AND persists pending_draft.
  - Then DELETE /pending clears it.
  - POST /publish-pending without pending_draft returns 400.
  - POST /tick-now when enabled=False returns 400 mentioning 'désactivé'.
"""
from __future__ import annotations

import os
import requests
import pytest

BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BACKEND_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    session, otp = body["session_token"], body["dev_otp"]
    v = requests.post(
        f"{BACKEND_URL}/api/auth/verify-otp",
        json={"session_token": session, "code": otp},
        timeout=15,
    )
    assert v.status_code == 200, v.text
    return v.json()["access_token"]


def _h(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_redirect_uri_preview_endpoint(admin_token):
    r = requests.get(
        f"{BACKEND_URL}/api/admin/linkedin/oauth/preview-redirect-uri",
        headers=_h(admin_token),
        timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "redirect_uri" in data
    assert "explicit_override" in data
    assert "computed_from_host" in data
    assert "computed_proto" in data
    # Must end with the canonical path
    assert data["redirect_uri"].endswith("/api/linkedin/oauth/callback"), data


def test_tick_now_disabled_returns_400(admin_token):
    # Make sure enabled=False
    p = requests.put(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_h(admin_token),
        json={"enabled": False},
        timeout=15,
    )
    assert p.status_code == 200, p.text
    r = requests.post(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/tick-now",
        headers=_h(admin_token),
        timeout=15,
    )
    assert r.status_code == 400, r.text
    detail = (r.json().get("detail") or "").lower()
    assert "désactiv" in detail or "desactiv" in detail, detail


def test_publish_pending_without_draft_returns_400(admin_token):
    # First clear any existing pending_draft
    requests.delete(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/pending",
        headers=_h(admin_token),
        timeout=15,
    )
    r = requests.post(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/publish-pending",
        headers=_h(admin_token),
        timeout=15,
    )
    assert r.status_code == 400, r.text


def test_generate_draft_live_llm(admin_token):
    """Live call to Claude Sonnet 4.5 via Emergent LLM. ~10-30s."""
    r = requests.post(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/generate-draft",
        headers=_h(admin_token),
        timeout=120,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, body
    draft = body.get("draft", "")
    length = body.get("length", len(draft))
    assert 100 < length < 3000, f"draft length {length} out of bounds"
    assert "#" in draft, "expected at least one hashtag in the draft"

    # Verify persisted in pending_draft
    cfg = requests.get(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/config",
        headers=_h(admin_token),
        timeout=15,
    )
    assert cfg.status_code == 200
    pending = cfg.json().get("pending_draft")
    assert pending and pending.get("text"), "pending_draft not persisted"
    assert pending["text"] == draft

    # Cleanup: delete pending
    d = requests.delete(
        f"{BACKEND_URL}/api/admin/linkedin/autopost/pending",
        headers=_h(admin_token),
        timeout=15,
    )
    assert d.status_code == 200, d.text
