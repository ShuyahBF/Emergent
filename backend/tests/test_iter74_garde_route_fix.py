"""Iter74 — Quick re-test after critical route-ordering fix.

Validates:
  1) DELETE /api/admin/officines-registry/garde-planning/year/2026 → 200 ok=true weeks_deleted (was 422)
  2) DELETE /api/admin/officines-registry/garde-planning/2026/30 single-week regression → 200 ok=true
  3) GET /api/public/officines/garde/current exposes period_start AND period_end
     explicitly (in addition to monday/sunday, with identical values)
"""
from __future__ import annotations

import os
from datetime import date

import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _admin_token() -> str:
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    session = data.get("session_token") or data.get("session_id") or data.get("session")
    otp = data.get("dev_otp") or data.get("otp")
    assert session and otp, f"missing session/otp: {data}"
    r2 = requests.post(
        f"{BASE}/api/auth/verify-otp",
        json={"session_token": session, "code": otp},
        timeout=20,
    )
    assert r2.status_code == 200, f"otp failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("access_token") or r2.json().get("token")
    assert tok, f"no access_token: {r2.json()}"
    return tok


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---- Fix #1: critical route-ordering for reset-year ----
def test_reset_year_returns_200_not_422():
    """The route shadow bug from iter73 should now be fixed."""
    tok = _admin_token()
    r = requests.delete(
        f"{BASE}/api/admin/officines-registry/garde-planning/year/2026",
        headers=_hdr(tok),
        timeout=20,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
    body = r.json()
    assert body.get("ok") is True, body
    assert body.get("year") == 2026, body
    assert "weeks_deleted" in body, body
    assert isinstance(body["weeks_deleted"], int)
    assert body["weeks_deleted"] >= 0


# ---- Regression: single-week delete still works ----
def test_delete_single_week_regression():
    tok = _admin_token()
    r = requests.delete(
        f"{BASE}/api/admin/officines-registry/garde-planning/2026/30",
        headers=_hdr(tok),
        timeout=20,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
    body = r.json()
    assert body.get("ok") is True, body
    assert body.get("year") == 2026
    assert body.get("week_number") == 30
    assert body.get("reset") is True


# ---- Feature: period_start / period_end explicitly exposed ----
def test_garde_current_exposes_period_start_end():
    r = requests.get(f"{BASE}/api/public/officines/garde/current", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    # period_start AND period_end MUST be present as separate keys
    assert "period_start" in data, f"period_start missing: keys={list(data.keys())}"
    assert "period_end" in data, f"period_end missing: keys={list(data.keys())}"
    ps = data["period_start"]
    pe = data["period_end"]
    assert ps and pe, f"empty values: ps={ps!r} pe={pe!r}"
    # Must be valid ISO dates
    d_start = date.fromisoformat(ps)
    d_end = date.fromisoformat(pe)
    # Under default saturday_noon mode: Sat→Sat, 7-day delta
    if (data.get("rotation_mode") or "").lower() == "saturday_noon":
        assert d_start.weekday() == 5, f"period_start should be Sat, got {d_start} (wd={d_start.weekday()})"
        assert d_end.weekday() == 5, f"period_end should be Sat, got {d_end} (wd={d_end.weekday()})"
        assert (d_end - d_start).days == 7
    # Same values as monday/sunday (backwards compat)
    assert data.get("monday") == ps, f"monday={data.get('monday')} vs period_start={ps}"
    assert data.get("sunday") == pe, f"sunday={data.get('sunday')} vs period_end={pe}"
