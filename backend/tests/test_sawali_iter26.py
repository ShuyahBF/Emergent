"""SAWALI iter26 — Backend tests for WhatsApp→SMS fallback feature.

Covers:
  * Live-send branch: WA unconfigured → fallback_used / fallback_results / fallback_ok
    populated; sms_messages rows inserted with wa_fallback=True, bulk=True.
    Skipped contacts (no whatsapp/phone) MUST NOT appear in fallback_results.
  * Schedule branch: persists sms_fallback / sms_fallback_message /
    sms_fallback_provider / sms_fallback_sender on whatsapp_schedules row.
  * Cron _run_scheduled_whatsapp: applies fallback for kind='contact' on WA
    failure; results[] includes a `fallback` field per recipient.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
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
# Pull DB_NAME from /app/backend/.env to ensure we hit the SAME db the FastAPI app is using.
DB_NAME = os.environ.get("DB_NAME") or ""
if not DB_NAME:
    try:
        with open("/app/backend/.env", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("DB_NAME="):
                    DB_NAME = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass
assert DB_NAME, "DB_NAME must be set"


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def admin_token() -> str:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=10)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    if body.get("access_token"):
        return body["access_token"]
    sess = body.get("session_token"); code = body.get("dev_otp")
    assert sess and code, body
    r2 = s.post(f"{API}/auth/verify-otp", json={"session_token": sess, "code": code}, timeout=10)
    assert r2.status_code == 200, r2.text
    tok = r2.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_client_id(admin_headers: dict) -> str:
    r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def seeded_contacts(admin_headers: dict) -> list[dict]:
    """3 contacts: 2 with phone+whatsapp, 1 without any number."""
    created = []
    payloads = [
        {"name": "TEST_iter26 Alice", "company": "ACME", "phone": "+212600000010",
         "whatsapp": "+212600000010", "email": "a@example.com"},
        {"name": "TEST_iter26 Bob",   "company": "Beta", "phone": "+212600000011",
         "whatsapp": "+212600000011", "email": "b@example.com"},
        {"name": "TEST_iter26 NoPhone","company": "Zilch","phone": "",
         "whatsapp": "", "email": "z@example.com"},
    ]
    for p in payloads:
        r = requests.post(f"{API}/me/contacts", headers=admin_headers, json=p, timeout=10)
        assert r.status_code in (200, 201), r.text
        created.append(r.json())
    yield created
    for c in created:
        try:
            requests.delete(f"{API}/me/contacts/{c['id']}", headers=admin_headers, timeout=10)
        except Exception:
            pass


# ---------- 1. Live-send branch SMS fallback ----------

class TestLiveSendFallback:
    def test_live_send_with_fallback_returns_fallback_block(self, admin_headers, seeded_contacts, admin_client_id):
        """WA + SMS both unconfigured → endpoint MUST return fallback_used=true,
        fallback_results=[2 entries], one sms_messages row per WA-failed contact."""
        ids = [c["id"] for c in seeded_contacts]  # 2 with phone, 1 without
        payload = {
            "contact_ids": ids,
            "template_name": "hello_world",
            "language_code": "fr",
            "variables": ["{name}"],
            "sms_fallback": True,
            "sms_fallback_message": "SMS retry pour {{name}}",
            "sms_fallback_provider": "auto",
            "sms_fallback_sender": "SAWALI",
        }
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["scheduled"] is False
        assert body.get("fallback_used") is True
        fb = body.get("fallback_results")
        assert isinstance(fb, list), body
        # Exactly 2 fallback entries (one per WA-failed contact w/ phone). NoPhone contact was
        # SKIPPED before WA-attempt, so it must NOT appear in fallback_results.
        assert len(fb) == 2, f"expected 2 fallback rows, got {len(fb)}: {fb}"
        # Each entry has shape
        for entry in fb:
            for k in ("label", "phone", "ok", "status", "error"):
                assert k in entry, f"missing key {k} in fallback entry {entry}"
            # SMS provider not configured → ok=False, error string present
            assert entry["ok"] is False
            assert entry.get("error")
        # fallback_ok counts ok=True entries
        assert body.get("fallback_ok") == 0
        # The skipped NoPhone contact must be reported in skipped[], not in fallback_results
        skipped_phones = {s.get("phone") for s in (body.get("skipped") or [])}
        # Ensure skipped is populated for the NoPhone contact (skipped is list of dicts)
        assert len(body.get("skipped") or []) == 1

        # ---- Verify sms_messages rows were inserted with wa_fallback:true and bulk:true ----
        async def _verify_sms_rows():
            cli = AsyncIOMotorClient(MONGO_URL)
            try:
                docs = await cli[DB_NAME].sms_messages.find(
                    {"wa_fallback": True, "bulk": True,
                     "contact_id": {"$in": [seeded_contacts[0]["id"], seeded_contacts[1]["id"]]},
                     "user_id": admin_client_id}
                ).to_list(length=10)
                # Cleanup these rows immediately
                if docs:
                    await cli[DB_NAME].sms_messages.delete_many(
                        {"id": {"$in": [d["id"] for d in docs]}})
                return docs
            finally:
                cli.close()

        rows = asyncio.run(_verify_sms_rows())
        assert len(rows) == 2, f"expected 2 sms_messages with wa_fallback=true, got {len(rows)}"
        for d in rows:
            assert d.get("wa_fallback") is True
            assert d.get("bulk") is True
            assert "SMS retry pour" in (d.get("message") or "")
            # Personalization happened: name token replaced
            assert "TEST_iter26" in (d.get("message") or "")

        # NoPhone contact must NOT have a sms_messages row
        async def _verify_no_phone_skipped():
            cli = AsyncIOMotorClient(MONGO_URL)
            try:
                cnt = await cli[DB_NAME].sms_messages.count_documents(
                    {"wa_fallback": True, "contact_id": seeded_contacts[2]["id"]})
                return cnt
            finally:
                cli.close()
        assert asyncio.run(_verify_no_phone_skipped()) == 0


# ---------- 2. Schedule branch persistence ----------

class TestScheduleFallbackPersist:
    def test_schedule_persists_fallback_fields(self, admin_headers, seeded_contacts):
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        payload = {
            "contact_ids": [seeded_contacts[0]["id"]],
            "template_name": "hello_world",
            "language_code": "fr",
            "variables": ["{name}"],
            "scheduled_at": future,
            "sms_fallback": True,
            "sms_fallback_message": "Retry SMS planifié pour {name}",
            "sms_fallback_provider": "orange",
            "sms_fallback_sender": "SAWALI",
        }
        r = requests.post(f"{API}/me/whatsapp/bulk", headers=admin_headers, json=payload, timeout=10)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]

        async def _read_doc():
            cli = AsyncIOMotorClient(MONGO_URL)
            try:
                row = await cli[DB_NAME].whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
                # Cleanup
                await cli[DB_NAME].whatsapp_schedules.delete_one({"id": sid})
                return row
            finally:
                cli.close()
        doc = asyncio.run(_read_doc())
        assert doc is not None
        assert doc.get("sms_fallback") is True
        assert doc.get("sms_fallback_message") == "Retry SMS planifié pour {name}"
        assert doc.get("sms_fallback_provider") == "orange"
        assert doc.get("sms_fallback_sender") == "SAWALI"


# ---------- 3. Cron runner applies fallback ----------

class TestCronRunnerFallback:
    def test_runner_applies_fallback_for_contact_branch(self, admin_headers, seeded_contacts, admin_client_id):
        """Past-date a schedule with sms_fallback=true & 2 contacts (one with phone,
        one without). Run the runner. Verify:
          * contact w/ phone gets sms_messages row (wa_fallback=True, schedule_id matches)
          * contact w/o phone has NO sms_messages row
          * schedule.results[] has `fallback` field per recipient
        """
        async def _flow():
            import sys
            sys.path.insert(0, "/app/backend")
            import server as srv
            sid = f"TEST_iter26_sched_{int(time.time())}"
            past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            with_phone = seeded_contacts[0]
            no_phone = seeded_contacts[2]
            recipients = [
                {"kind": "contact", "id": with_phone["id"],
                 "phone": with_phone.get("whatsapp") or with_phone.get("phone"),
                 "label": with_phone.get("name")},
                {"kind": "contact", "id": no_phone["id"],
                 "phone": "", "label": no_phone.get("name")},
            ]
            await srv.db.whatsapp_schedules.insert_one({
                "id": sid,
                "title": "TEST_iter26 fallback runner",
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
                "sms_fallback": True,
                "sms_fallback_message": "Cron retry SMS pour {{name}}",
                "sms_fallback_provider": "auto",
                "sms_fallback_sender": "SAWALI",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            crashed = None
            try:
                await srv._run_scheduled_whatsapp()
            except Exception as exc:
                crashed = exc
            row = await srv.db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
            sms_rows = await srv.db.sms_messages.find(
                {"schedule_id": sid}, {"_id": 0}
            ).to_list(length=10)
            # cleanup
            await srv.db.whatsapp_schedules.delete_one({"id": sid})
            await srv.db.sms_messages.delete_many({"schedule_id": sid})
            await srv.db.whatsapp_messages.delete_many({"schedule_id": sid})
            return row, sms_rows, crashed, with_phone["id"], no_phone["id"]

        row, sms_rows, crashed, with_phone_id, no_phone_id = asyncio.run(_flow())
        assert crashed is None, f"runner crashed: {crashed}"
        assert row is not None
        assert row.get("status") in ("done", "failed")
        # Exactly one SMS row for the with-phone contact, zero for no_phone
        assert len(sms_rows) == 1, f"expected 1 sms row, got {len(sms_rows)}: {sms_rows}"
        s = sms_rows[0]
        assert s.get("wa_fallback") is True
        assert s.get("schedule_id") == row["id"]
        assert s.get("contact_id") == with_phone_id
        assert "Cron retry SMS pour" in (s.get("message") or "")
        assert "TEST_iter26" in (s.get("message") or "")
        # results[] are stored under result_summary.results (per server.py line 10003).
        # Only recipients with a phone number reach the WA-attempt+fallback step;
        # no_phone recipients are pre-skipped (server.py L9892).
        rs = row.get("result_summary") or {}
        results = rs.get("results") or []
        skipped = rs.get("skipped") or []
        # 1 result row (Alice, with phone). NoPhone is in skipped[].
        assert len(results) == 1, results
        assert len(skipped) == 1, skipped
        wp_res = results[0]
        assert wp_res.get("label") == "TEST_iter26 Alice"
        assert "fallback" in wp_res, f"missing fallback field in {wp_res}"
        # SMS provider unconfigured → fallback string is "failed" or "err:..."
        assert wp_res.get("fallback") in ("ok", "failed") or (
            wp_res.get("fallback") and str(wp_res["fallback"]).startswith("err:")
        )
        # NoPhone recipient was pre-skipped (no SMS, no fallback row, no result row)
        np_skipped = skipped[0]
        assert np_skipped.get("label") == "TEST_iter26 NoPhone"
