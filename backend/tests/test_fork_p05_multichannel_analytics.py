"""2026-02 fork (P0.5 extended + analytics) — Multi-channel Smart Comm
resolver diag + tenant social senders (LinkedIn/Meta/X status) + planning
digest analytics.
"""
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL.rstrip('/')}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    body = r.json()
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": body["session_token"], "code": body["dev_otp"]},
        timeout=10,
    )
    v.raise_for_status()
    return v.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def tenant_ctx(admin_token):
    tag = uuid.uuid4().hex[:6]
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={
            "email": f"sc-{tag}@sawali-test.com",
            "password": "SC@2026",
            "full_name": f"SC tenant {tag}",
            "role": "admin",
            "company": f"SC-CO-{tag}",
        },
        timeout=10,
    )
    r.raise_for_status()
    tenant_id = r.json()["id"]
    tok = _login(f"sc-{tag}@sawali-test.com", "SC@2026")
    return {"tenant_id": tenant_id, "token": tok, "tag": tag}


# ---------------------------------------------------------- Multi-channel diag
def test_smart_comm_diag_supports_all_channels(admin_token):
    for ch in ("wa", "meta", "instagram", "linkedin", "x", "tiktok"):
        r = requests.get(
            f"{API}/admin/smart-comm/resolver-diag",
            headers=_auth(admin_token),
            params={"channel": ch},
            timeout=10,
        )
        assert r.status_code == 200, f"{ch} → {r.status_code} {r.text}"
        body = r.json()
        assert body["channel"] == ch
        assert body["source"] in ("global", "tenant")


def test_smart_comm_diag_rejects_unknown_channel(admin_token):
    r = requests.get(
        f"{API}/admin/smart-comm/resolver-diag",
        headers=_auth(admin_token),
        params={"channel": "signal"},
        timeout=10,
    )
    assert r.status_code == 400


def test_smart_comm_diag_returns_tenant_when_configured(admin_token, tenant_ctx):
    tag = tenant_ctx["tag"]
    r = requests.put(
        f"{API}/me/smart-communications",
        headers=_auth(tenant_ctx["token"]),
        json={
            "linkedin_access_token": f"LI_TOK_{tag}",
            "linkedin_organization_id": f"999{tag}",
        },
        timeout=10,
    )
    assert r.status_code == 200
    r = requests.get(
        f"{API}/admin/smart-comm/resolver-diag",
        headers=_auth(admin_token),
        params={"channel": "linkedin", "tenant_id": tenant_ctx["tenant_id"]},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "tenant"
    assert body["tenant_id"] == tenant_ctx["tenant_id"]
    assert body["linkedin_organization_id"] == f"999{tag}"
    assert body["linkedin_access_token_present"] is True


# --------------------------------------------------------- Social senders API
def test_me_social_status_lists_channels(admin_token):
    r = requests.get(f"{API}/me/social/status", headers=_auth(admin_token), timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert set(body["channels"].keys()) == {"wa", "meta", "instagram", "linkedin", "x", "tiktok"}


def test_linkedin_post_requires_org_urn_when_unconfigured(admin_token):
    """POST /me/social/linkedin/post — 400 when no token AND no org_urn."""
    r = requests.post(
        f"{API}/me/social/linkedin/post",
        headers=_auth(admin_token),
        json={"text": "Hello LinkedIn"},
        timeout=10,
    )
    # Either 400 (no token in tenant + no global) OR 400 (no org_urn). We just
    # care that it doesn't 500 and rejects cleanly.
    assert r.status_code == 400


def test_meta_post_requires_config(admin_token):
    r = requests.post(
        f"{API}/me/social/meta/post",
        headers=_auth(admin_token),
        json={"message": "Test"},
        timeout=10,
    )
    # 400 when Meta credentials incomplete for this tenant
    assert r.status_code in (400, 502)  # 502 if credentials somehow set globally


def test_x_post_returns_501_not_wired(admin_token, tenant_ctx):
    tag = tenant_ctx["tag"]
    # Configure minimally so we get past the "credentials missing" check
    requests.put(
        f"{API}/me/smart-communications",
        headers=_auth(tenant_ctx["token"]),
        json={
            "x_api_key": f"K_{tag}", "x_api_secret": f"S_{tag}",
            "x_access_token": f"A_{tag}", "x_access_secret": f"AS_{tag}",
        },
        timeout=10,
    )
    # NB: /me/social/x/post requires admin/superviseur/moderator/marketing/communication.
    # tenant_ctx["token"] is a role=admin created via /admin/clients so it should pass.
    r = requests.post(
        f"{API}/me/social/x/post",
        headers=_auth(tenant_ctx["token"]),
        json={"text": "Hello X"},
        timeout=10,
    )
    assert r.status_code == 501
    assert "twitter" in r.json().get("detail", "").lower() or "x " in r.json().get("detail", "").lower() or "sender" in r.json().get("detail", "").lower()


# ------------------------------------------------------- Planning digest analytics
def test_digest_analytics_empty_by_default(admin_token):
    r = requests.get(
        f"{API}/admin/planning-digest/analytics",
        headers=_auth(admin_token),
        params={"days": 1},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 1
    assert body["totals"]["sent"] >= 0
    assert body["totals"]["opened"] >= 0
    assert isinstance(body["breakdown"], list)
    assert isinstance(body["recent"], list)


def test_digest_analytics_admin_only(admin_token):
    # Non-admin should be denied
    tag = uuid.uuid4().hex[:6]
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={
            "email": f"da-{tag}@sawali-test.com",
            "password": "DA@2026",
            "full_name": f"DA {tag}",
            "role": "client",
        },
        timeout=10,
    )
    r.raise_for_status()
    tok = _login(f"da-{tag}@sawali-test.com", "DA@2026")
    r = requests.get(f"{API}/admin/planning-digest/analytics", headers=_auth(tok), timeout=10)
    assert r.status_code == 403


def test_digest_analytics_rejects_absurd_days(admin_token):
    # `days` is clamped to [1, 365] server-side (silently). Should still succeed.
    r = requests.get(
        f"{API}/admin/planning-digest/analytics",
        headers=_auth(admin_token),
        params={"days": 999},
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["days"] == 365
    r = requests.get(
        f"{API}/admin/planning-digest/analytics",
        headers=_auth(admin_token),
        params={"days": 0},
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["days"] == 1


def test_recap_open_creates_event(admin_token):
    """Full round-trip: create médecin → issue token → exchange → analytics 'opened'."""
    import jwt as pyjwt
    from datetime import datetime, timezone as tz
    tag = uuid.uuid4().hex[:6]
    # Setup médecin
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={"email": f"da-med-parent-{tag}@sawali-test.com", "password": "P@2026",
              "full_name": f"P {tag}", "role": "admin", "company": f"C-{tag}"},
        timeout=10,
    )
    r.raise_for_status()
    parent_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=_auth(admin_token),
        json={"client_id": parent_id, "name": f"Dr {tag}",
              "email": f"da-med-{tag}@sawali-test.com", "role": "Médecin"},
        timeout=10,
    )
    r.raise_for_status()
    tu_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{tu_id}/set-password",
        headers=_auth(admin_token),
        json={"password": "Med@2026"},
        timeout=10,
    )
    r.raise_for_status()
    med_tok = _login(f"da-med-{tag}@sawali-test.com", "Med@2026")
    me = requests.get(f"{API}/auth/me", headers=_auth(med_tok), timeout=10).json()

    # Mint a valid recap token
    RECAP_SECRET = (
        os.environ.get("WA_PLANNING_RECAP_SECRET")
        or os.environ.get("LINK_JWT_SECRET")
        or (os.environ.get("JWT_SECRET", "fallback-insecure") + "-wa-recap")
    )
    now = int(datetime.now(tz.utc).timestamp())
    tok = pyjwt.encode(
        {"sub": me["id"], "scope": "wa_planning_recap", "iat": now, "exp": now + 300},
        RECAP_SECRET,
        algorithm="HS256",
    )

    # Baseline count
    before = requests.get(
        f"{API}/admin/planning-digest/analytics", headers=_auth(admin_token),
        params={"days": 1}, timeout=10,
    ).json()
    baseline_opened = before["totals"]["opened"]

    # Exchange
    r = requests.post(f"{API}/auth/wa-planning-exchange", json={"t": tok}, timeout=10)
    assert r.status_code == 200

    # After
    after = requests.get(
        f"{API}/admin/planning-digest/analytics", headers=_auth(admin_token),
        params={"days": 1}, timeout=10,
    ).json()
    assert after["totals"]["opened"] == baseline_opened + 1
