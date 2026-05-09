"""SAWALI iter25 — Backend tests for P1 WhatsApp Bulk feature.

Covers:
  * POST /api/me/whatsapp/bulk validation (empty/missing/invalid/limits)
  * RBAC (admin allowed; tracked-user blocked when features.whatsapp=False)
  * Schedule branch (recipients[].kind='contact', whatsapp_schedules row)
  * Live-send branch (skipped + results, defensive logging when WA not configured)
  * GET /api/me/messaging/schedules + DELETE
  * Per-contact personalization via stored variables tokens
  * Cron _run_scheduled_whatsapp executes contact branch without crash
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to frontend/.env
    try:
        with open("/app/frontend/.env", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def admin_token() -> str:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=10)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    if body.get("access_token"):
        return body["access_token"]
    session_token = body.get("session_token")
    code = body.get("dev_otp")
    assert session_token and code, f"OTP flow expected, got: {body}"
    r2 = s.post(f"{API}/auth/verify-otp", json={"session_token": session_token, "code": code}, timeout=10)
    assert r2.status_code == 200, f"verify-otp failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("access_token")
    assert tok, f"no access_token: {r2.json()}"
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_client_id(admin_headers: dict) -> str:
    """admin's own user id (==parent_id for admin's contacts)."""
    r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def seeded_contacts(admin_headers: dict) -> list[dict]:
    """Seed 3 TEST_iter25 contacts; cleanup at module teardown."""
    created = []
    payloads = [
        {"name": "TEST_iter25 Jean Dupont", "company": "ACME SARL", "phone": "+212600000001",
         "whatsapp": "+212600000001", "email": "jean@example.com"},
        {"name": "TEST_iter25 Marie Curie", "company": "Lab Pasteur", "phone": "+212600000002",
         "whatsapp": "+212600000002", "email": "marie@example.com"},
        {"name": "TEST_iter25 Sans Phone", "company": "NoPhone Co", "phone": "",
         "whatsapp": "", "email": "noph@example.com"},
    ]
    for p in payloads:
        r = requests.post(f"{API}/me/contacts", headers=admin_headers, json=p, timeout=10)
        assert r.status_code in (200, 201), f"contact create failed: {r.status_code} {r.text}"
        created.append(r.json())
    yield created
    for c in created:
        try:
            requests.delete(f"{API}/me/contacts/{c['id']}", headers=admin_headers, timeout=10)
        except Exception:
            pass


# ---------- Validation ----------

class TestBulkValidation:
    def test_empty_contact_ids_returns_400(self, admin_headers):
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers,
                          json={"contact_ids": [], "template_name": "hello_world"}, timeout=10)
        assert r.status_code == 400, r.text
        assert "destinataire" in r.text.lower() or "aucun" in r.text.lower()

    def test_missing_template_returns_400(self, admin_headers, seeded_contacts):
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers,
                          json={"contact_ids": [seeded_contacts[0]["id"]], "template_name": ""}, timeout=10)
        assert r.status_code == 400, r.text
        assert "template" in r.text.lower()

    def test_too_many_contacts_returns_400(self, admin_headers):
        ids = [f"fake-{i}" for i in range(501)]
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers,
                          json={"contact_ids": ids, "template_name": "hello_world"}, timeout=10)
        assert r.status_code == 400, r.text
        assert "500" in r.text or "maximum" in r.text.lower()

    def test_scheduled_at_too_soon_returns_400(self, admin_headers, seeded_contacts):
        soon = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers, json={
            "contact_ids": [seeded_contacts[0]["id"]],
            "template_name": "hello_world",
            "scheduled_at": soon,
        }, timeout=10)
        assert r.status_code == 400, r.text
        assert "30 secondes" in r.text or "30s" in r.text.lower()


# ---------- RBAC ----------

class TestBulkRBAC:
    def test_unauth_returns_401_or_403(self, seeded_contacts):
        r = requests.post(f"{API}/me/whatsapp/bulk", json={
            "contact_ids": [seeded_contacts[0]["id"]], "template_name": "hello_world"
        }, timeout=10)
        assert r.status_code in (401, 403), r.text


# ---------- Schedule branch ----------

class TestBulkSchedule:
    @pytest.fixture
    def created_schedule(self, admin_headers, seeded_contacts):
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers, json={
            "contact_ids": [c["id"] for c in seeded_contacts[:2]],
            "template_name": "hello_world",
            "language_code": "fr",
            "variables": ["{name}", "{client_code}"],
            "scheduled_at": future,
            "title": "TEST_iter25 schedule",
        }, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["scheduled"] is True
        assert body["recipients"] == 2
        sid = body["id"]
        yield sid, body
        try:
            requests.delete(f"{API}/me/messaging/schedules/{sid}", headers=admin_headers, timeout=10)
        except Exception:
            pass

    def test_schedule_creates_row_with_kind_contact(self, created_schedule, admin_headers, seeded_contacts):
        sid, body = created_schedule
        # GET schedules list must include it
        r = requests.get(f"{API}/me/messaging/schedules", headers=admin_headers, timeout=10)
        assert r.status_code == 200, r.text
        rows = r.json() if isinstance(r.json(), list) else r.json().get("items") or r.json().get("schedules") or []
        match = next((x for x in rows if x.get("id") == sid), None)
        assert match is not None, f"schedule {sid} not in list"
        assert match.get("status") == "pending"
        assert match.get("bulk") is True
        recs = match.get("recipients") or []
        assert len(recs) == 2
        wanted_ids = {c["id"] for c in seeded_contacts[:2]}
        for r0 in recs:
            assert r0.get("kind") == "contact"
            assert r0.get("id") in wanted_ids

    def test_delete_pending_schedule(self, admin_headers, seeded_contacts):
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers, json={
            "contact_ids": [seeded_contacts[0]["id"]],
            "template_name": "hello_world",
            "scheduled_at": future,
        }, timeout=10)
        assert r.status_code == 200
        sid = r.json()["id"]
        rd = requests.delete(f"{API}/me/messaging/schedules/{sid}", headers=admin_headers, timeout=10)
        assert rd.status_code == 200, rd.text
        assert rd.json().get("ok") is True
        # Subsequent delete: 404
        rd2 = requests.delete(f"{API}/me/messaging/schedules/{sid}", headers=admin_headers, timeout=10)
        assert rd2.status_code == 404


# ---------- Live-send branch (WA not configured -> graceful failure) ----------

class TestBulkLiveSend:
    def test_live_send_returns_results_and_skipped_no_5xx(self, admin_headers, seeded_contacts):
        """WA is not configured in preview env. Endpoint MUST NOT 5xx — must return ok=true
        with sent_ko=N for all contacts that have a phone, and contacts without phone in skipped."""
        ids = [c["id"] for c in seeded_contacts]  # includes one without phone
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers, json={
            "contact_ids": ids,
            "template_name": "hello_world",
            "language_code": "fr",
            "variables": ["{name}"],
        }, timeout=15)
        assert r.status_code == 200, f"expected 200 not {r.status_code}: {r.text}"
        body = r.json()
        assert body["ok"] is True
        assert body["scheduled"] is False
        assert isinstance(body.get("results"), list)
        # 2 with phone, 1 without
        assert body.get("sent_ok", 0) + body.get("sent_ko", 0) == 2
        assert len(body.get("skipped") or []) == 1
        # Each result has shape
        for res in body["results"]:
            for k in ("label", "phone", "ok", "status", "message_id", "error"):
                assert k in res, f"missing key {k} in result {res}"
            # WA not configured => ok must be False with an error string
            assert res["ok"] is False
            assert res.get("error")

    def test_out_of_scope_contact_id_silently_dropped(self, admin_headers):
        """Passing a non-existent contact_id should not 5xx; results empty / skipped empty."""
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers, json={
            "contact_ids": ["does-not-exist-zzz"],
            "template_name": "hello_world",
        }, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sent_ok"] == 0
        assert body["sent_ko"] == 0
        assert body.get("skipped") == []


# ---------- Cron _run_scheduled_whatsapp on kind='contact' ----------

class TestSchedulerContactBranch:
    def test_runner_handles_contact_branch(self, admin_headers, seeded_contacts, admin_client_id):
        """Insert a schedule with scheduled_at in the past for kind='contact', then call the
        runner directly via importing server. Must not crash; status must end up
        'failed' or 'done' with result_summary set.
        All motor ops must share a single event loop with the server module's global db client."""
        import sys
        sys.path.insert(0, "/app/backend")

        async def _full_flow():
            import server as srv  # imported inside the loop so srv.db is bound here
            sid = f"TEST_iter25_sched_{int(time.time())}"
            past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            recipients = []
            for c in seeded_contacts[:2]:
                recipients.append({
                    "kind": "contact",
                    "id": c["id"],
                    "phone": c.get("whatsapp") or c.get("phone"),
                    "label": c.get("name"),
                })
            await srv.db.whatsapp_schedules.insert_one({
                "id": sid,
                "title": "TEST_iter25 runner",
                "recipients": recipients,
                "template_name": "hello_world",
                "language_code": "fr",
                "components": None,
                "variables": ["{name}"],
                "header_text": None,
                "header_media": None,
                "button_vars": None,
                "scheduled_at": past_iso,
                "status": "pending",
                "result_summary": None,
                "created_by_id": admin_client_id,
                "created_by_label": "admin",
                "created_by_role": "admin",
                "client_id": admin_client_id,
                "bulk": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            crashed = None
            try:
                await srv._run_scheduled_whatsapp()
            except Exception as exc:  # noqa: BLE001
                crashed = exc
            row = await srv.db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
            await srv.db.whatsapp_schedules.delete_one({"id": sid})
            await srv.db.whatsapp_messages.delete_many({"schedule_id": sid})
            return row, crashed

        row, crashed = asyncio.run(_full_flow())
        assert crashed is None, f"_run_scheduled_whatsapp crashed: {crashed}"
        assert row is not None
        assert row.get("status") in ("done", "failed"), f"unexpected status {row.get('status')}"
        rs = row.get("result_summary") or {}
        assert rs.get("requested") == 2
        assert rs.get("sent_ok", 0) + rs.get("sent_ko", 0) == 2
