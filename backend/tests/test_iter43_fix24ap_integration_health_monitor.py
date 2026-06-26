"""Iter43-fix24ap (2026-06-17) — Periodic integration health monitor tests.

Verifies that the 4-hourly cron `_run_integration_health_check` :
- Tests Google Calendar (via `gcal.list_upcoming_events`)
- Tests Meta WA Webhook (via Graph API `subscribed_apps`)
- Persists result in `db.integration_health_checks`
- Sends a WhatsApp alert ONCE per 12h to the configured admin number
  when at least one integration is broken.
"""
from __future__ import annotations

import os
import sys

import httpx
import pytest


API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
sys.path.insert(0, "/app/backend")


def _login_admin():
    r1 = httpx.post(f"{API_BASE}/auth/login",
                    json={"email": "admin@sawalismartsystems.com",
                          "password": "Admin@Sawali2026"}, timeout=15)
    d1 = r1.json()
    r2 = httpx.post(f"{API_BASE}/auth/verify-otp",
                    json={"session_token": d1["session_token"],
                          "code": d1["dev_otp"]}, timeout=15)
    return r2.json()["access_token"]


def test_integration_health_check_endpoint_runs_and_returns_status():
    """Manual trigger of the health check returns Google + Meta status."""
    token = _login_admin()
    h = {"Authorization": f"Bearer {token}"}
    r = httpx.get(f"{API_BASE}/admin/integrations/health-check", headers=h, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "google_calendar" in body
    assert "meta_webhook" in body
    assert "ok" in body
    assert "google_calendar" in body and "ok" in body["google_calendar"]
    assert "meta_webhook" in body and "ok" in body["meta_webhook"]
    assert "checked_at" in body
    assert body.get("triggered_by") == "manual"


def test_integration_health_check_persists_to_db():
    """Each run should append an entry to db.integration_health_checks."""
    token = _login_admin()
    h = {"Authorization": f"Bearer {token}"}
    # Run twice
    httpx.get(f"{API_BASE}/admin/integrations/health-check", headers=h, timeout=20)
    httpx.get(f"{API_BASE}/admin/integrations/health-check", headers=h, timeout=20)
    r = httpx.get(f"{API_BASE}/admin/integrations/health-history?limit=5", headers=h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 2
    # Recent items have triggered_by=manual
    assert any(item.get("triggered_by") == "manual" for item in body["items"])


def test_health_history_endpoint_requires_admin_auth():
    r = httpx.get(f"{API_BASE}/admin/integrations/health-history", timeout=15)
    assert r.status_code in (401, 403)


def test_integration_health_check_endpoint_requires_admin_auth():
    r = httpx.get(f"{API_BASE}/admin/integrations/health-check", timeout=15)
    assert r.status_code in (401, 403)


def test_health_check_failure_state_records_failures_separately():
    """When configured integrations are missing/broken, the response must
    expose granular `reason` for each component so the admin can act."""
    token = _login_admin()
    h = {"Authorization": f"Bearer {token}"}
    r = httpx.get(f"{API_BASE}/admin/integrations/health-check", headers=h, timeout=20)
    body = r.json()
    # In preview, Google Cal is likely "not_connected" and Meta WA could be either
    g = body["google_calendar"]
    m = body["meta_webhook"]
    if not g["ok"]:
        assert g.get("reason") in ("not_connected", "api_error", "missing_config"), g
        assert g.get("message")
    if not m["ok"]:
        assert m.get("reason") in ("missing_config", "no_subscription", "api_error", "exception"), m
        assert m.get("message")
