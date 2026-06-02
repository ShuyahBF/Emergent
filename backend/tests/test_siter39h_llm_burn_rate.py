"""S032 — Universal Key burn-rate tracking & proactive warning alerts.

Validates:
  * `compute_metrics(db)` returns the expected metric shape with non-trivial
    burn rate and projection when usage rows are seeded.
  * `/admin/llm-health` exposes the S032 metrics block alongside the raw
    health state and the `status_level` field reflects the configured
    `llm_budget_warning_pct` and `llm_budget_critical_pct` thresholds.
  * Settings validation rejects out-of-range and inconsistent thresholds.
  * `record_llm_outcome` appends a row to the `llm_usage_log` collection for
    each LLM call.
  * `maybe_send_budget_warning_alerts` calls the email + WA callbacks when
    the level is warning/critical and skips silently when in OK zone.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30).json()
    if not r.get("needs_otp"):
        return r["access_token"]
    return requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": r["session_token"], "code": r["dev_otp"]},
        timeout=30,
    ).json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    try:
        return asyncio.get_event_loop().run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def test_record_outcome_appends_usage_log(db_sync):
    """Each successful LLM call must add a row to `llm_usage_log` with the
    correct context-based cost estimate and current month bucket."""
    from routes.llm_health import record_llm_outcome, LLM_COST_ESTIMATES

    async def go():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        tag = f"test_{uuid.uuid4().hex[:8]}"
        # Patch the cost map to inject an isolated context we can recognize
        LLM_COST_ESTIMATES[tag] = 0.0123
        try:
            await record_llm_outcome(async_db, ok=True, context=tag)
            row = await async_db.llm_usage_log.find_one({"context": tag})
            assert row is not None, "usage log row not persisted"
            assert row["estimated_cost_usd"] == pytest.approx(0.0123, rel=1e-6)
            assert row["ok"] is True
            assert row["month_bucket"] == datetime.now(timezone.utc).strftime("%Y-%m")
        finally:
            await async_db.llm_usage_log.delete_many({"context": tag})
            LLM_COST_ESTIMATES.pop(tag, None)

    _run(go())


def test_compute_metrics_burn_rate_and_projection(db_sync):
    """Seed deterministic usage rows and assert the burn rate aggregation +
    projected days left match the inputs."""
    from routes.llm_health import compute_metrics

    async def go():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        tag = f"burn_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        rows = [
            {"ts": now - timedelta(hours=h), "context": tag,
             "estimated_cost_usd": 0.10, "ok": True,
             "month_bucket": (now - timedelta(hours=h)).strftime("%Y-%m")}
            for h in (1, 5, 12, 20)
        ]
        # Pre-clean any leftover state from previous runs
        await async_db.llm_health_state.update_one(
            {"_id": "current"}, {"$set": {"status": "ok", "current_cost": None, "max_budget": None}}, upsert=True,
        )
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "llm_budget_warning_pct": 80, "llm_budget_critical_pct": 95,
                "llm_budget_max_usd": 1.0,
            }}, upsert=True,
        )
        try:
            await async_db.llm_usage_log.insert_many(rows)
            m = await compute_metrics(async_db)
            # 4 entries × $0.10 in the last 24h → $0.40 burn rate
            assert m["burn_rate_24h_usd"] >= 0.40 - 0.001
            assert m["calls_24h"] >= 4
            assert m["max_budget_usd"] == pytest.approx(1.0)
            # Cumulative month spend >= 0.40 → 40% used → "ok" status
            assert m["pct_used"] >= 40.0
            assert m["status_level"] in ("ok", "warning", "critical")
            # With remaining ~$0.60 and burn $0.40/24h → ~1.5 days projected
            assert m["projected_days_left"] is not None
            assert 0.5 <= m["projected_days_left"] <= 5.0
        finally:
            await async_db.llm_usage_log.delete_many({"context": tag})

    _run(go())


def test_status_level_warning_when_pct_used_crosses_threshold(db_sync):
    """When current_cost is 85% of max_budget AND warning_pct=80, the
    computed status_level must be `warning` (not `ok`)."""
    from routes.llm_health import compute_metrics

    async def go():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await async_db.llm_health_state.update_one(
            {"_id": "current"},
            {"$set": {"status": "ok", "current_cost": 0.85, "max_budget": 1.0}},
            upsert=True,
        )
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {"llm_budget_warning_pct": 80, "llm_budget_critical_pct": 95}},
            upsert=True,
        )
        m = await compute_metrics(async_db)
        assert m["pct_used"] == pytest.approx(85.0, abs=0.5)
        assert m["status_level"] == "warning"
        # Now bump to critical zone
        await async_db.llm_health_state.update_one(
            {"_id": "current"}, {"$set": {"current_cost": 0.97}},
        )
        m2 = await compute_metrics(async_db)
        assert m2["status_level"] == "critical"
        # Reset to ok
        await async_db.llm_health_state.update_one(
            {"_id": "current"}, {"$set": {"current_cost": 0.20}},
        )
        m3 = await compute_metrics(async_db)
        assert m3["status_level"] == "ok"

    _run(go())


def test_admin_health_endpoint_exposes_s032_metrics(admin_h):
    """GET /admin/llm-health must include the S032 fields."""
    r = requests.get(f"{API}/admin/llm-health", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("burn_rate_24h_usd", "burn_rate_1h_usd", "pct_used", "status_level",
              "warning_pct", "critical_pct", "cost_source"):
        assert k in body, f"missing S032 key: {k}"
    assert body["status_level"] in ("ok", "warning", "critical", "exhausted", "error")


def test_settings_validation_rejects_bad_thresholds(admin_h):
    """warning >= critical and out-of-range values must be 400."""
    # warning pct out of range
    r = requests.put(f"{API}/admin/settings", headers=admin_h,
                     json={"llm_budget_warning_pct": 30}, timeout=30)
    assert r.status_code == 400
    # critical pct out of range
    r = requests.put(f"{API}/admin/settings", headers=admin_h,
                     json={"llm_budget_critical_pct": 50}, timeout=30)
    assert r.status_code == 400
    # warning >= critical (inconsistent)
    r = requests.put(f"{API}/admin/settings", headers=admin_h,
                     json={"llm_budget_warning_pct": 90, "llm_budget_critical_pct": 85}, timeout=30)
    assert r.status_code == 400
    # negative max_usd
    r = requests.put(f"{API}/admin/settings", headers=admin_h,
                     json={"llm_budget_max_usd": -1.0}, timeout=30)
    assert r.status_code == 400
    # Valid update succeeds
    r = requests.put(f"{API}/admin/settings", headers=admin_h,
                     json={"llm_budget_warning_pct": 75, "llm_budget_critical_pct": 92,
                           "llm_budget_max_usd": 3.0,
                           "llm_budget_notify_email": True, "llm_budget_notify_wa": True,
                           "llm_budget_notify_wa_phone": "+22500000000"}, timeout=30)
    assert r.status_code == 200, r.text
    # Restore defaults
    requests.put(f"{API}/admin/settings", headers=admin_h,
                 json={"llm_budget_warning_pct": 80, "llm_budget_critical_pct": 95}, timeout=30)


def test_warning_alerts_invokes_email_and_wa_callables():
    """`maybe_send_budget_warning_alerts` must call both senders when
    warning level is reached and respect the 23h throttle."""
    from routes.llm_health import maybe_send_budget_warning_alerts

    async def go():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        # Force the state into warning zone with 85% usage
        await async_db.llm_health_state.update_one(
            {"_id": "current"},
            {"$set": {"status": "ok", "current_cost": 0.85, "max_budget": 1.0},
             "$unset": {"last_warning_alert_at_warning": "", "last_warning_alert_at_critical": ""}},
            upsert=True,
        )
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "llm_budget_warning_pct": 80, "llm_budget_critical_pct": 95,
                "llm_budget_notify_email": True, "llm_budget_notify_wa": True,
                "llm_budget_notify_wa_phone": "+22500000000",
            }}, upsert=True,
        )

        email_calls = []
        wa_calls = []

        async def fake_email(**kwargs):
            email_calls.append(kwargs)
            return True

        async def fake_wa(to_e164, text):
            wa_calls.append({"to": to_e164, "text": text})
            return {"ok": True}

        res = await maybe_send_budget_warning_alerts(async_db, fake_email, fake_wa)
        assert res["sent_email"] is True
        assert res["sent_wa"] is True
        assert res["level"] == "warning"
        # 23h throttle — calling again must be skipped
        res2 = await maybe_send_budget_warning_alerts(async_db, fake_email, fake_wa)
        assert res2["sent_email"] is False
        assert res2["sent_wa"] is False
        assert res2["skipped_reason"] == "throttled"
        # Reset state to OK → no alert
        await async_db.llm_health_state.update_one(
            {"_id": "current"}, {"$set": {"current_cost": 0.10}},
        )
        res3 = await maybe_send_budget_warning_alerts(async_db, fake_email, fake_wa)
        assert res3["sent_email"] is False
        assert res3["skipped_reason"] == "not_in_alert_zone"

    _run(go())
