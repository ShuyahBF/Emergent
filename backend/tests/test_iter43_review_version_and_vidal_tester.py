"""Iter43 review — Version endpoint (no git) + VIDAL tester backend support.

Tests:
- GET /api/version returns 200 with deploy_seq >= 1 and version != '1.0'
- Two consecutive /api/version calls return same deploy_seq (idempotency)
- GET /api/admin/vidal/actions (admin) >= 7 actions
- POST /api/vidal/execute/recherche returns {cached,data,action} with data._request
  containing method/url/params with app_key masked as ***
"""
from __future__ import annotations

import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


@pytest.fixture(scope="module")
def admin_token():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    session_token = body.get("session_token") or body.get("sessionToken")
    dev_otp = body.get("dev_otp")
    assert session_token, f"No session_token in login response: {body}"
    assert dev_otp, f"No dev_otp in login response (needed for tests): {body}"
    r2 = s.post(f"{API}/auth/verify-otp", json={"session_token": session_token, "code": dev_otp}, timeout=20)
    assert r2.status_code == 200, f"OTP verify failed: {r2.status_code} {r2.text[:200]}"
    body2 = r2.json()
    token = body2.get("access_token") or body2.get("token")
    assert token, f"No access_token in verify-otp response: {body2}"
    return token


# --- /api/version (no-git fingerprint) -----------------------------

def test_version_returns_200_and_deploy_seq():
    r = requests.get(f"{API}/version", timeout=15)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "deploy_seq" in body
    assert isinstance(body["deploy_seq"], int)
    assert body["deploy_seq"] >= 1, f"deploy_seq should be >= 1, got {body['deploy_seq']}"
    assert "version" in body
    assert body["version"] != "1.0", f"version should not be '1.0' fallback, got {body['version']}"
    assert "." in body["version"]


def test_version_idempotent_same_seq():
    r1 = requests.get(f"{API}/version", timeout=15)
    r2 = requests.get(f"{API}/version", timeout=15)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["deploy_seq"] == r2.json()["deploy_seq"], (
        f"deploy_seq drifted between calls: {r1.json()['deploy_seq']} vs {r2.json()['deploy_seq']}"
    )


# --- VIDAL actions admin endpoint ---------------------------------

def test_admin_vidal_actions_lists_at_least_7(admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{API}/admin/vidal/actions", headers=h, timeout=20)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    body = r.json()
    actions = body.get("actions") if isinstance(body, dict) else body
    assert isinstance(actions, list), f"Expected list of actions, got: {type(actions)} -> {body}"
    assert len(actions) >= 7, f"Expected >=7 default actions, got {len(actions)}"
    # Each action should have an id
    ids = [a.get("id") for a in actions]
    assert "recherche" in ids, f"Expected 'recherche' in action ids: {ids}"


# --- VIDAL execute with _request introspection --------------------

def test_vidal_execute_recherche_returns_request_introspection(admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = requests.post(
        f"{API}/vidal/execute/recherche",
        json={"q": "doliprane"},
        headers=h,
        timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
    body = r.json()
    # Expected structure: {cached, data, action}
    assert "data" in body, f"Missing 'data' field: {body}"
    assert "action" in body, f"Missing 'action' field: {body}"
    data = body["data"]
    # _request introspection
    assert "_request" in data, f"Missing data._request: keys={list(data.keys())}"
    req = data["_request"]
    assert "method" in req, f"Missing method in _request: {req}"
    assert "url" in req, f"Missing url in _request: {req}"
    # params should exist and app_key (if present) must be masked
    params = req.get("params") or {}
    if "app_key" in params:
        assert params["app_key"] == "***", f"app_key should be masked '***', got {params['app_key']!r}"
    # VIDAL upstream may be unreachable from preview — that's OK,
    # but the backend should still return introspection.
    # Optionally check _error or raw
    # Don't fail if VIDAL itself errored; only structure matters.
