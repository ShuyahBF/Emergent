"""Iter43-fix24az-e (HTTP) — Validate garde period endpoints over real HTTP:
  1) GET /api/public/officines/garde/current — defaults to saturday_noon and
     includes monday/sunday/period_start/period_end aligned to Sat→Sat.
  2) PUT /api/admin/settings garde_rotation_mode=monday_midnight then GET
     garde/current → ISO Mon→Sun, then restore default.
  3) DELETE /api/admin/officines-registry/garde-planning/year/{year} → 200.
  4) DELETE single-week endpoint regression.
  5) DELETE empty garde group → 200; non-empty → 409.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone

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


# ---------- BUG #1 — public garde/current dates ----------

def test_garde_current_default_includes_period_dates():
    r = requests.get(f"{BASE}/api/public/officines/garde/current", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "year" in data and ("week_number" in data or "week" in data), data
    # rotation_mode defaults to saturday_noon
    mode = (data.get("rotation_mode") or "").lower()
    assert mode == "saturday_noon", f"mode={mode!r} data={data}"
    ps = data.get("monday")
    pe = data.get("sunday")
    assert ps and pe, f"missing monday/sunday: {data}"
    d_start = date.fromisoformat(ps)
    d_end = date.fromisoformat(pe)
    # Saturday weekday = 5 (Sat→Sat period under saturday_noon mode)
    assert d_start.weekday() == 5, f"monday field weekday={d_start.weekday()} ({d_start})"
    assert d_end.weekday() == 5, f"sunday field weekday={d_end.weekday()} ({d_end})"
    assert (d_end - d_start).days == 7, f"delta={(d_end - d_start).days}"


def test_garde_current_legacy_mode_then_restore():
    tok = _admin_token()
    # Switch to legacy
    r = requests.put(
        f"{BASE}/api/admin/settings",
        headers=_hdr(tok),
        json={"garde_rotation_mode": "monday_midnight"},
        timeout=20,
    )
    assert r.status_code in (200, 204), f"PUT settings: {r.status_code} {r.text}"
    try:
        time.sleep(0.5)
        r2 = requests.get(f"{BASE}/api/public/officines/garde/current", timeout=20)
        assert r2.status_code == 200, r2.text
        d = r2.json()
        assert (d.get("rotation_mode") or "").lower() == "monday_midnight", d
        ps = date.fromisoformat(d.get("period_start") or d.get("monday"))
        pe = date.fromisoformat(d.get("period_end") or d.get("sunday"))
        # Mon = 0, Sun = 6
        assert ps.weekday() == 0, f"legacy start {ps} weekday={ps.weekday()}"
        assert pe.weekday() == 6, f"legacy end {pe} weekday={pe.weekday()}"
        assert (pe - ps).days == 6
    finally:
        # Restore default
        r3 = requests.put(
            f"{BASE}/api/admin/settings",
            headers=_hdr(tok),
            json={"garde_rotation_mode": "saturday_noon"},
            timeout=20,
        )
        assert r3.status_code in (200, 204), f"restore failed: {r3.status_code} {r3.text}"


# ---------- Feature #2 — reset year & single-week delete ----------

def test_reset_year_endpoint():
    tok = _admin_token()
    r = requests.delete(
        f"{BASE}/api/admin/officines-registry/garde-planning/year/2026",
        headers=_hdr(tok),
        timeout=20,
    )
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    body = r.json()
    assert body.get("ok") is True, body
    assert "weeks_deleted" in body, body
    assert isinstance(body["weeks_deleted"], int)
    assert body["weeks_deleted"] >= 0


def test_reset_year_endpoint_requires_admin():
    r = requests.delete(
        f"{BASE}/api/admin/officines-registry/garde-planning/year/2026",
        timeout=20,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_delete_single_week_still_works():
    tok = _admin_token()
    # Use week 30 (arbitrary) — should be idempotent (returns 200 even if absent or 404)
    r = requests.delete(
        f"{BASE}/api/admin/officines-registry/garde-planning/2026/30",
        headers=_hdr(tok),
        timeout=20,
    )
    # Endpoint exists; accept 200 (deleted/not present) or 404 (absent)
    assert r.status_code in (200, 204, 404), f"{r.status_code} {r.text}"


# ---------- Feature #3 — delete empty/non-empty garde group ----------

def test_delete_empty_garde_group():
    tok = _admin_token()
    # Choose group 100 (max valid value, unlikely to be assigned)
    r = requests.delete(
        f"{BASE}/api/admin/officines-registry/garde-groups/100",
        headers=_hdr(tok),
        timeout=20,
    )
    # Either 200 (deleted/no-op) or 404 (not found) acceptable for empty groups.
    assert r.status_code in (200, 404), f"{r.status_code} {r.text}"
    if r.status_code == 200:
        body = r.json()
        assert body.get("ok") is True, body


def test_delete_nonempty_garde_group_returns_409():
    tok = _admin_function = None
    tok = _admin_token()
    # Find an existing group with officines. Query the registry to find one.
    r = requests.get(
        f"{BASE}/api/admin/officines-registry",
        headers=_hdr(tok),
        timeout=20,
    )
    if r.status_code != 200:
        # Endpoint shape may differ; skip if registry not accessible
        import pytest
        pytest.skip(f"officines-registry not accessible: {r.status_code}")
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    if not items:
        import pytest
        pytest.skip("no officines in registry → cannot test 409 path")
    # Pick first non-null garde_group
    target_group = None
    for it in items:
        g = it.get("garde_group") or it.get("garde_group_number")
        if g is not None:
            target_group = int(g)
            break
    if target_group is None:
        import pytest
        pytest.skip("no officine has garde_group set")
    r2 = requests.delete(
        f"{BASE}/api/admin/officines-registry/garde-groups/{target_group}",
        headers=_hdr(tok),
        timeout=20,
    )
    assert r2.status_code == 409, f"expected 409, got {r2.status_code} {r2.text}"
    msg = r2.text.lower()
    assert any(kw in msg for kw in ("officine", "vide", "non")), f"missing FR error msg: {r2.text}"


def test_delete_nonempty_group_requires_admin():
    r = requests.delete(
        f"{BASE}/api/admin/officines-registry/garde-groups/1",
        timeout=20,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"
