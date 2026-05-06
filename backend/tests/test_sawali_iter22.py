"""Iter22 SAWALI backend tests — Lot A+B-partial.

Coverage:
 (A) /admin/usage/summary — totals/per_client/daily_series shape, days clamp
 (B) Auth login OTP per-domain — internal vs external
 (C) Settings.internal_domains — runtime override of internal/external domains
 (D) /auth/resend-otp — same internal-domain rule
 (E) /me/appointments — shared client_id scope (admin sees all, tracked user sees parent)
 (F) /me/appointments POST/PUT/DELETE — _fire_agenda_n8n best-effort (no error)
 (G) Inbound webhook /webhooks/agenda/{secret} — disabled/wrong/right secret + CRUD
 (H) Settings — agenda_n8n_outbound/inbound fields persist + 3 secrets are masked
"""
from __future__ import annotations

import os
import time
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient


def _bhash(pwd: str) -> str:
    return bcrypt.hashpw(pwd.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _next_business_slot(days_ahead: int = 1, hour: int = 10) -> str:
    """Returns ISO datetime for the next weekday at `hour:00` UTC."""
    dt = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    while dt.weekday() >= 5:  # skip sat/sun
        dt += timedelta(days=1)
    dt = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    return dt.isoformat()

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")


# ---------- helpers ----------
def _login_with_otp(email: str, password: str) -> dict:
    """Returns dict with login_response + access_token."""
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    data = r.json()
    code = data.get("dev_otp")
    assert code, f"dev_otp missing for {email}: {data}"
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
        timeout=15,
    )
    v.raise_for_status()
    token = v.json()["access_token"]
    return {"login": data, "access_token": token, "user": v.json().get("user")}


@pytest.fixture(scope="session")
def admin_token() -> str:
    return _login_with_otp(ADMIN_EMAIL, ADMIN_PASSWORD)["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def db():
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Snapshot-restore the global settings doc per-test
@pytest.fixture
def settings_snapshot(db, event_loop):
    async def _grab():
        return await db.settings.find_one({"_id": "global"}) or {}
    snap = event_loop.run_until_complete(_grab())
    yield snap

    async def _restore(prev):
        SECRET_AND_CONFIG = [
            "internal_domains",
            "agenda_n8n_outbound_enabled", "agenda_n8n_outbound_url",
            "agenda_n8n_outbound_auth_type", "agenda_n8n_outbound_token",
            "agenda_n8n_outbound_basic_user", "agenda_n8n_outbound_basic_pass",
            "agenda_n8n_inbound_enabled", "agenda_n8n_inbound_secret",
        ]
        unset = {k: "" for k in SECRET_AND_CONFIG if k not in prev}
        set_back = {k: prev[k] for k in SECRET_AND_CONFIG if k in prev}
        ops = {}
        if unset:
            ops["$unset"] = unset
        if set_back:
            ops["$set"] = set_back
        if ops:
            await db.settings.update_one({"_id": "global"}, ops, upsert=True)
    event_loop.run_until_complete(_restore(snap))


# ============================================================
# (A) /admin/usage/summary
# ============================================================
class TestAdminUsageSummary:
    def test_default_days_30(self, admin_headers):
        r = requests.get(f"{API}/admin/usage/summary", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["period_days"] == 30
        assert isinstance(d["totals"], dict)
        for k in ("wa_sent_ok", "wa_sent_ko", "wa_inbound", "wa_total", "wa_cost", "ai_count"):
            assert k in d["totals"], f"missing total: {k}"
        assert isinstance(d["per_client"], list)
        assert isinstance(d["daily_series"], list)
        assert len(d["daily_series"]) == 30

    def test_days_7(self, admin_headers):
        r = requests.get(f"{API}/admin/usage/summary?days=7", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["period_days"] == 7
        assert len(d["daily_series"]) == 7
        # daily series rows shape
        for row in d["daily_series"]:
            assert "day" in row and "wa" in row and "ai" in row

    def test_days_clamp(self, admin_headers):
        # below 1 → 1
        r = requests.get(f"{API}/admin/usage/summary?days=0", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["period_days"] == 1
        # above 365 → 365
        r2 = requests.get(f"{API}/admin/usage/summary?days=999", headers=admin_headers, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["period_days"] == 365

    def test_per_client_shape_and_sort(self, admin_headers):
        r = requests.get(f"{API}/admin/usage/summary?days=30", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        rows = r.json()["per_client"]
        # rows may be empty in a fresh env, but shape must be correct when present
        for row in rows:
            for k in ("client_id", "features", "wa_sent_ok", "wa_sent_ko", "wa_inbound",
                      "wa_total", "wa_cost", "ai_summaries"):
                assert k in row, f"missing {k}"
            assert isinstance(row["features"], dict)
            for f in ("whatsapp", "sms", "ai", "payments"):
                assert f in row["features"]
        # sort: wa_cost+ai_summaries DESC
        scores = [r["wa_cost"] + r["ai_summaries"] for r in rows]
        assert scores == sorted(scores, reverse=True)

    def test_requires_admin(self):
        r = requests.get(f"{API}/admin/usage/summary", timeout=10)
        assert r.status_code in (401, 403)


# ============================================================
# (B) (C) (D) Auth — internal vs external + resend-otp
# ============================================================
class TestAuthOtpPerDomain:
    def test_admin_internal_message(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("dev_otp"), "admin should always get dev_otp (internal domain)"
        assert "interne" in (d.get("message") or "").lower(), d.get("message")

    def test_external_user_smtp_unconfigured_fallback(self, admin_headers, db, event_loop, settings_snapshot):
        # Create a TEST external user
        email = f"test_iter22_ext_{uuid.uuid4().hex[:8]}@example.com"
        # bcrypt hash of "Pass@1234567"
        async def _seed():
            
            
            await db.users.insert_one({
                "id": str(uuid.uuid4()),
                "email": email,
                "full_name": "Ext User",
                "password_hash": _bhash("Pass@1234567"),
                "role": "client",
                "account_status": "active",
                "must_change_password": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        event_loop.run_until_complete(_seed())

        try:
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": "Pass@1234567"}, timeout=15)
            assert r.status_code == 200, r.text
            d = r.json()
            # SMTP not configured → fallback dev_otp returned with French message
            if d.get("dev_otp"):
                assert "indisponible" in (d.get("message") or "").lower() or "interne" not in (d.get("message") or "").lower()
            # If SMTP IS configured at this preview env, sent=true is acceptable too
        finally:
            event_loop.run_until_complete(db.users.delete_one({"email": email}))

    def test_internal_domains_override(self, admin_headers, db, event_loop, settings_snapshot):
        """PUT internal_domains='foo.com' → @foo.com login becomes internal."""
        # Set internal_domains to include foo.com
        r = requests.put(
            f"{API}/admin/settings",
            json={"internal_domains": "sawalismartsystems.com, foo.com"},
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text

        # Seed external user @foo.com
        email = f"test_iter22_foo_{uuid.uuid4().hex[:8]}@foo.com"

        async def _seed():
            
            
            await db.users.insert_one({
                "id": str(uuid.uuid4()),
                "email": email,
                "full_name": "Foo User",
                "password_hash": _bhash("Pass@1234567"),
                "role": "client",
                "account_status": "active",
                "must_change_password": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        event_loop.run_until_complete(_seed())

        try:
            login = requests.post(f"{API}/auth/login",
                                  json={"email": email, "password": "Pass@1234567"}, timeout=15)
            assert login.status_code == 200
            d = login.json()
            # foo.com is now internal → message must mention 'interne'
            assert "interne" in (d.get("message") or "").lower(), d.get("message")
            assert d.get("dev_otp"), "Internal user should always get dev_otp"

            # /auth/resend-otp must respect internal_domains too
            rs = requests.post(
                f"{API}/auth/resend-otp",
                params={"session_token": d["session_token"]},
                timeout=15,
            )
            assert rs.status_code == 200, rs.text
            rd = rs.json()
            assert rd.get("dev_otp"), "Internal resend should return dev_otp"
            assert rd.get("sent") is False
        finally:
            event_loop.run_until_complete(db.users.delete_one({"email": email}))


# ============================================================
# (E) (F) /me/appointments shared scope + outbound webhook fire
# ============================================================
class TestAppointmentsSharedScope:
    def test_admin_create_and_outbound_safe(self, admin_headers, db, event_loop):
        """POST + PUT + DELETE — _fire_agenda_n8n must not raise even when disabled (default)."""
        sched = _next_business_slot(days_ahead=2, hour=10)
        # Create
        r = requests.post(
            f"{API}/me/appointments",
            json={"subject": "TEST_iter22 Agenda", "message": "auto-test", "scheduled_at": sched, "duration_min": 30},
            headers=admin_headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        appt = r.json()
        assert appt.get("id")
        appt_id = appt["id"]

        try:
            # GET — admin must see it (and at least 1 item)
            g = requests.get(f"{API}/me/appointments", headers=admin_headers, timeout=15)
            assert g.status_code == 200
            ids = [x["id"] for x in g.json()]
            assert appt_id in ids

            # Update
            new_sched = _next_business_slot(days_ahead=3, hour=14)
            u = requests.put(
                f"{API}/me/appointments/{appt_id}",
                json={"scheduled_at": new_sched, "subject": "TEST_iter22 Agenda updated"},
                headers=admin_headers, timeout=15,
            )
            assert u.status_code == 200, u.text

            # Delete
            d = requests.delete(f"{API}/me/appointments/{appt_id}", headers=admin_headers, timeout=15)
            assert d.status_code == 200
        finally:
            event_loop.run_until_complete(db.appointments.delete_many({"id": appt_id}))

    def test_tracked_user_shares_parent_scope(self, admin_headers, db, event_loop):
        """Tracked user (client_id=parent.id) sees the parent's RDV."""
        # Seed a parent client + a tracked user pointing to it
        parent_id = str(uuid.uuid4())
        parent_email = f"test_iter22_parent_{uuid.uuid4().hex[:6]}@example.com"
        tracked_email = f"test_iter22_tracked_{uuid.uuid4().hex[:6]}@example.com"
        appt_id = str(uuid.uuid4())

        async def _seed():
            
            
            now = datetime.now(timezone.utc).isoformat()
            await db.users.insert_one({
                "id": parent_id, "email": parent_email, "full_name": "Parent Co",
                "password_hash": _bhash("Pass@1234567"),
                "role": "client", "account_status": "active", "must_change_password": False,
                "created_at": now,
            })
            await db.users.insert_one({
                "id": str(uuid.uuid4()), "email": tracked_email, "full_name": "Tracked User",
                "password_hash": _bhash("Pass@1234567"),
                "role": "client", "client_id": parent_id, "parent_client_id": parent_id,
                "account_status": "active", "must_change_password": False, "created_at": now,
            })
            await db.appointments.insert_one({
                "id": appt_id, "client_id": parent_id,
                "name": "Parent Co", "email": parent_email, "phone": None, "company": None,
                "subject": "TEST_iter22 Parent RDV", "message": None,
                "scheduled_at": _next_business_slot(days_ahead=5, hour=15),
                "duration_min": 30, "status": "pending",
                "notes": None, "gcal_event_id": None, "created_at": now,
            })
        event_loop.run_until_complete(_seed())

        try:
            # Login as tracked user
            tk = _login_with_otp(tracked_email, "Pass@1234567")["access_token"]
            r = requests.get(f"{API}/me/appointments", headers={"Authorization": f"Bearer {tk}"}, timeout=15)
            assert r.status_code == 200, r.text
            ids = [x["id"] for x in r.json()]
            assert appt_id in ids, f"Tracked user should see parent RDV, got {ids}"
        finally:
            event_loop.run_until_complete(db.users.delete_many(
                {"email": {"$in": [parent_email, tracked_email]}}
            ))
            event_loop.run_until_complete(db.appointments.delete_many({"id": appt_id}))


# ============================================================
# (G) Inbound webhook /webhooks/agenda/{secret}
# ============================================================
class TestInboundAgendaWebhook:
    def test_disabled_returns_503(self, admin_headers, settings_snapshot):
        # Ensure disabled
        r = requests.put(f"{API}/admin/settings",
                         json={"agenda_n8n_inbound_enabled": False}, headers=admin_headers, timeout=15)
        assert r.status_code == 200
        # Any path/secret → 503 because disabled
        rr = requests.post(f"{API}/webhooks/agenda/anything",
                           json={"action": "list"}, timeout=15)
        assert rr.status_code == 503

    def test_wrong_secret_403(self, admin_headers, settings_snapshot):
        secret = f"sec_{uuid.uuid4().hex[:12]}"
        r = requests.put(f"{API}/admin/settings",
                         json={"agenda_n8n_inbound_enabled": True,
                               "agenda_n8n_inbound_secret": secret},
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200
        rr = requests.post(f"{API}/webhooks/agenda/wrongsecret",
                           json={"action": "list"}, timeout=15)
        assert rr.status_code == 403

    def test_full_crud_via_webhook(self, admin_headers, db, event_loop, settings_snapshot):
        secret = f"sec_{uuid.uuid4().hex[:12]}"
        r = requests.put(f"{API}/admin/settings",
                         json={"agenda_n8n_inbound_enabled": True,
                               "agenda_n8n_inbound_secret": secret},
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200

        # Seed a client to scope by email
        client_email = f"test_iter22_n8n_{uuid.uuid4().hex[:6]}@example.com"
        cid = str(uuid.uuid4())

        async def _seed():
            
            
            await db.users.insert_one({
                "id": cid, "email": client_email, "full_name": "N8N Client",
                "password_hash": _bhash("X"),
                "role": "client", "account_status": "active", "must_change_password": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        event_loop.run_until_complete(_seed())

        created_id = None
        try:
            # action=list → ok
            lr = requests.post(f"{API}/webhooks/agenda/{secret}",
                               json={"action": "list", "client_email": client_email}, timeout=15)
            assert lr.status_code == 200, lr.text
            assert lr.json().get("ok") is True
            assert isinstance(lr.json().get("items"), list)

            # action=create
            sched = _next_business_slot(days_ahead=4, hour=11)
            cr = requests.post(f"{API}/webhooks/agenda/{secret}",
                               json={"action": "create", "client_email": client_email,
                                     "subject": "TEST_iter22 from n8n", "scheduled_at": sched,
                                     "duration_min": 45},
                               timeout=15)
            assert cr.status_code == 200, cr.text
            cd = cr.json()
            assert cd["ok"] is True
            assert cd["appointment"]["source"] == "n8n"
            assert cd["appointment"]["client_id"] == cid
            created_id = cd["appointment"]["id"]

            # action=update
            ur = requests.post(f"{API}/webhooks/agenda/{secret}",
                               json={"action": "update", "appointment_id": created_id,
                                     "subject": "TEST_iter22 from n8n UPDATED",
                                     "status": "confirmed"},
                               timeout=15)
            assert ur.status_code == 200, ur.text
            assert ur.json()["appointment"]["subject"] == "TEST_iter22 from n8n UPDATED"
            assert ur.json()["appointment"]["status"] == "confirmed"

            # action=delete
            dr = requests.post(f"{API}/webhooks/agenda/{secret}",
                               json={"action": "delete", "appointment_id": created_id}, timeout=15)
            assert dr.status_code == 200, dr.text

            # action=invalid
            ir = requests.post(f"{API}/webhooks/agenda/{secret}",
                               json={"action": "frobnicate"}, timeout=15)
            assert ir.status_code == 400

            # update without appointment_id → 400
            br = requests.post(f"{API}/webhooks/agenda/{secret}",
                               json={"action": "update", "subject": "x"}, timeout=15)
            assert br.status_code == 400

        finally:
            event_loop.run_until_complete(db.users.delete_one({"email": client_email}))
            if created_id:
                event_loop.run_until_complete(db.appointments.delete_many({"id": created_id}))


# ============================================================
# (H) Settings — agenda_n8n_* round-trip + masking of 3 secrets
# ============================================================
class TestAgendaSettingsMasking:
    def test_settings_persist_and_mask(self, admin_headers, db, event_loop, settings_snapshot):
        payload = {
            "agenda_n8n_outbound_enabled": True,
            "agenda_n8n_outbound_url": "https://example.com/n8n/agenda",
            "agenda_n8n_outbound_auth_type": "bearer",
            "agenda_n8n_outbound_token": "TEST_token_12345",
            "agenda_n8n_outbound_basic_user": "u1",
            "agenda_n8n_outbound_basic_pass": "TEST_pass_67890",
            "agenda_n8n_inbound_enabled": True,
            "agenda_n8n_inbound_secret": "TEST_secret_abcde",
        }
        r = requests.put(f"{API}/admin/settings", json=payload, headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text

        # GET masked
        g = requests.get(f"{API}/admin/settings", headers=admin_headers, timeout=15)
        assert g.status_code == 200
        gd = g.json()
        assert gd["agenda_n8n_outbound_enabled"] is True
        assert gd["agenda_n8n_outbound_url"] == "https://example.com/n8n/agenda"
        assert gd["agenda_n8n_outbound_auth_type"] == "bearer"
        assert gd["agenda_n8n_outbound_basic_user"] == "u1"
        assert gd["agenda_n8n_inbound_enabled"] is True
        # Three secrets must be masked
        assert gd["agenda_n8n_outbound_token"] == "********"
        assert gd["agenda_n8n_outbound_basic_pass"] == "********"
        assert gd["agenda_n8n_inbound_secret"] == "********"

        # Raw db has unmasked
        async def _read():
            return await db.settings.find_one({"_id": "global"})
        raw = event_loop.run_until_complete(_read())
        assert raw["agenda_n8n_outbound_token"] == "TEST_token_12345"
        assert raw["agenda_n8n_inbound_secret"] == "TEST_secret_abcde"

        # Sending '********' must NOT overwrite
        r2 = requests.put(f"{API}/admin/settings",
                          json={"agenda_n8n_inbound_secret": "********"},
                          headers=admin_headers, timeout=15)
        assert r2.status_code == 200
        raw2 = event_loop.run_until_complete(_read())
        assert raw2["agenda_n8n_inbound_secret"] == "TEST_secret_abcde"
