"""Iter72 — HTTP tests for Garde rotation toggle (Feature 1a/1b/1c/1d)

Live tests against the preview API:
- GET /api/public/officines/garde/current returns rotation_mode + next_rotation_at
- PUT /api/admin/settings can toggle to monday_midnight and back to saturday_noon
- Invalid garde_rotation_mode is rejected with HTTP 400 (French message)
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PWD = "Admin@Sawali2026"


@pytest.fixture(scope="module")
def admin_token():
    s = requests.Session()
    # Step 1: login (dev_otp returned)
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    j = r.json()
    session_token = j.get("session_token")
    otp = j.get("dev_otp") or j.get("otp")
    assert session_token and otp, f"missing session_token/dev_otp: {j}"
    r2 = s.post(f"{BASE_URL}/api/auth/verify-otp", json={"session_token": session_token, "code": str(otp)}, timeout=20)
    assert r2.status_code == 200, f"verify-otp failed: {r2.status_code} {r2.text[:300]}"
    tok = r2.json().get("access_token")
    assert tok, f"no access_token in response: {r2.json()}"
    return tok


def _auth_headers(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _next_weekday_at(weekday_iso: int, hour: int) -> datetime:
    """Compute next datetime that is weekday_iso (1=Mon..7=Sun) at hour UTC, relative to now."""
    now = datetime.now(timezone.utc)
    # current iso weekday: Mon=1..Sun=7
    cur = now.isoweekday()
    days_ahead = (weekday_iso - cur) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=7)
    return candidate


# === Test 1a: default mode is saturday_noon ===
def test_1a_garde_current_default_saturday_noon(admin_token):
    # Ensure we're in default mode (saturday_noon)
    r = requests.put(
        f"{BASE_URL}/api/admin/settings",
        json={"garde_rotation_mode": "saturday_noon"},
        headers=_auth_headers(admin_token),
        timeout=20,
    )
    assert r.status_code == 200, f"PUT settings failed: {r.status_code} {r.text[:300]}"

    r = requests.get(f"{BASE_URL}/api/public/officines/garde/current", timeout=20)
    assert r.status_code == 200, f"GET garde/current failed: {r.status_code} {r.text[:300]}"
    j = r.json()
    assert j.get("rotation_mode") == "saturday_noon", f"unexpected rotation_mode: {j}"
    nr = j.get("next_rotation_at")
    assert nr, f"missing next_rotation_at: {j}"
    # Parse and verify it's a Saturday at 12:00 UTC
    nrdt = datetime.fromisoformat(nr.replace("Z", "+00:00"))
    assert nrdt.isoweekday() == 6, f"next_rotation_at must be Saturday, got {nrdt} (weekday={nrdt.isoweekday()})"
    assert nrdt.hour == 12 and nrdt.minute == 0, f"must be 12:00, got {nrdt}"
    # Must be in the future and within 7 days
    delta = nrdt - datetime.now(timezone.utc)
    assert timedelta(seconds=-60) <= delta <= timedelta(days=7, minutes=1), f"next_rotation_at not within next 7 days: {nrdt}"


# === Test 1b: toggle to monday_midnight ===
def test_1b_toggle_legacy_monday_midnight(admin_token):
    r = requests.put(
        f"{BASE_URL}/api/admin/settings",
        json={"garde_rotation_mode": "monday_midnight"},
        headers=_auth_headers(admin_token),
        timeout=20,
    )
    assert r.status_code == 200, f"PUT legacy failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    assert body.get("ok") is True, f"expected ok=true: {body}"

    r = requests.get(f"{BASE_URL}/api/public/officines/garde/current", timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("rotation_mode") == "monday_midnight", f"rotation_mode mismatch after toggle: {j}"
    nr = j.get("next_rotation_at")
    nrdt = datetime.fromisoformat(nr.replace("Z", "+00:00"))
    assert nrdt.isoweekday() == 1, f"expected Monday, got {nrdt}"
    assert nrdt.hour == 0 and nrdt.minute == 0, f"expected 00:00, got {nrdt}"


# === Test 1c: invalid mode returns HTTP 400 with French message ===
def test_1c_invalid_mode_rejected(admin_token):
    r = requests.put(
        f"{BASE_URL}/api/admin/settings",
        json={"garde_rotation_mode": "sunday_noon"},
        headers=_auth_headers(admin_token),
        timeout=20,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code} body={r.text[:300]}"
    body = {}
    try:
        body = r.json()
    except Exception:
        pass
    msg = (body.get("detail") or body.get("message") or r.text or "").lower()
    # FR explicit message: should mention the mode/invalide/valeur
    assert any(k in msg for k in ["invalid", "invalide", "saturday_noon", "monday_midnight"]), (
        f"expected FR validation message, got: {msg[:200]}"
    )


# === Test 1d: restoring default updates next_rotation_at immediately ===
def test_1d_restore_default_changes_next_rotation(admin_token):
    # First ensure we're on monday_midnight from previous test (idempotent set)
    requests.put(
        f"{BASE_URL}/api/admin/settings",
        json={"garde_rotation_mode": "monday_midnight"},
        headers=_auth_headers(admin_token),
        timeout=20,
    )
    r1 = requests.get(f"{BASE_URL}/api/public/officines/garde/current", timeout=20)
    nr_legacy = r1.json().get("next_rotation_at")

    # Now switch back to saturday_noon
    r = requests.put(
        f"{BASE_URL}/api/admin/settings",
        json={"garde_rotation_mode": "saturday_noon"},
        headers=_auth_headers(admin_token),
        timeout=20,
    )
    assert r.status_code == 200, r.text

    r2 = requests.get(f"{BASE_URL}/api/public/officines/garde/current", timeout=20)
    j2 = r2.json()
    nr_sat = j2.get("next_rotation_at")
    assert j2.get("rotation_mode") == "saturday_noon"
    assert nr_sat != nr_legacy, f"next_rotation_at did not change: legacy={nr_legacy} sat={nr_sat}"
    nrdt = datetime.fromisoformat(nr_sat.replace("Z", "+00:00"))
    assert nrdt.isoweekday() == 6 and nrdt.hour == 12


# === Test 2a smoke: /me/contact-groups returns a list ===
def test_2a_contact_groups_list(admin_token):
    r = requests.get(f"{BASE_URL}/api/me/contact-groups", headers=_auth_headers(admin_token), timeout=20)
    assert r.status_code == 200, f"GET /me/contact-groups failed: {r.status_code} {r.text[:300]}"
    j = r.json()
    assert isinstance(j, list), f"expected list, got: {type(j)} body={str(j)[:200]}"
