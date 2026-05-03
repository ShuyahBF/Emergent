"""SAWALI — Iteration 12 backend tests: Admin WhatsApp Schedule planner.

Coverage:
- GET /api/admin/messaging/schedules (401 unauth, 403 non-admin, 200 admin list with shape).
- POST /api/admin/messaging/schedules
  * 400 empty recipients
  * 400 missing template_name
  * 400 scheduled_at in the past (more than 1 minute ago)
  * 200 happy path with a future ISO datetime → status='pending'.
- DELETE /api/admin/messaging/schedules/{id}
  * 200 hard-delete on pending → {ok:true, status:'deleted'}
  * 200 soft-cancel when status='running' or 'done' → status:'cancelled'
  * 404 on unknown id.
- _run_scheduled_whatsapp() runner (in-process):
  * Direct DB insert of past-dated 'pending' schedule with one tracked recipient.
  * await _run_scheduled_whatsapp() once (no 60s wait).
  * Verifies pending → running → failed/done transition with result_summary
    {requested, sent_ok, sent_ko, skipped_count, skipped, results}.
  * Verifies whatsapp_messages log written with schedule_id, scheduled=true,
    bulk=true, recipient_kind, recipient_label.
  * Verifies a recipient with empty phone goes to result_summary.skipped with
    reason 'Pas de numéro de téléphone'.
- Iter11 carry-over: POST /api/admin/tracked-users with phone='+xxx' persists
  phone (TrackedUserCreate now exposes phone Optional[str]).
"""
import os
import sys
import uuid
import asyncio
import datetime as dt
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path
from pymongo import MongoClient

# Load backend .env for direct DB access in tests
load_dotenv(Path("/app/backend/.env"))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

# Sync mongo client used to seed/inspect docs for the cron-runner test
_sync_mongo = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_mongo[os.environ["DB_NAME"]]


# ---------- helpers --------------------------------------------------------
def _login(email, password):
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    if d.get("needs_otp"):
        assert d.get("dev_otp"), f"dev_otp expected, got {d}"
        r2 = sess.post(f"{BASE}/api/auth/verify-otp",
                       json={"session_token": d["session_token"], "code": d["dev_otp"]})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        return body["access_token"], body["user"]
    return d["access_token"], d["user"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _future_iso(seconds_ahead=300):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds_ahead)).isoformat()


def _past_iso(seconds_back=300):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_back)).isoformat()


# ---------- session-scoped fixtures ----------------------------------------
@pytest.fixture(scope="session")
def admin():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok, u


@pytest.fixture(scope="session")
def admin_h(admin):
    return _h(admin[0])


@pytest.fixture(scope="session")
def secondary_client(admin_h):
    email = f"test_iter12_cli_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "IterTwelve!2026"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Iter12 Client", "password": pwd, "role": "client",
        "client_code": f"IT12{uuid.uuid4().hex[:3].upper()}",
    })
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    tok, _ = _login(email, pwd)
    yield {"id": uid, "email": email, "token": tok}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


# ---------- 1) GET /admin/messaging/schedules -----------------------------
class TestListSchedules:
    def test_unauth(self):
        r = requests.get(f"{BASE}/api/admin/messaging/schedules")
        assert r.status_code in (401, 403)

    def test_non_admin_forbidden(self, secondary_client):
        r = requests.get(f"{BASE}/api/admin/messaging/schedules",
                         headers=_h(secondary_client["token"]))
        assert r.status_code == 403

    def test_admin_returns_list(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/messaging/schedules", headers=admin_h)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)


# ---------- 2) POST /admin/messaging/schedules — validations + happy ------
class TestCreateSchedule:
    def test_400_empty_recipients(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/messaging/schedules", headers=admin_h, json={
            "recipients": [], "template_name": "hello_world", "scheduled_at": _future_iso(600),
        })
        assert r.status_code == 400, r.text

    def test_400_missing_template(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/messaging/schedules", headers=admin_h, json={
            "recipients": [{"kind": "raw", "phone": "+22500000000"}],
            "template_name": "",
            "scheduled_at": _future_iso(600),
        })
        assert r.status_code == 400, r.text

    def test_400_past_date(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/messaging/schedules", headers=admin_h, json={
            "recipients": [{"kind": "raw", "phone": "+22500000000"}],
            "template_name": "hello_world",
            "scheduled_at": _past_iso(600),  # 10 min ago
        })
        assert r.status_code == 400, r.text

    def test_happy_path_creates_pending(self, admin_h):
        title = f"Iter12 Sched {uuid.uuid4().hex[:5]}"
        r = requests.post(f"{BASE}/api/admin/messaging/schedules", headers=admin_h, json={
            "title": title,
            "recipients": [{"kind": "raw", "phone": "+22500000222", "label": "Iter12 raw"}],
            "template_name": "hello_world",
            "language_code": "fr",
            "scheduled_at": _future_iso(600),
        })
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("id", "title", "recipients", "template_name", "language_code",
                  "scheduled_at", "status", "result_summary", "created_by_id",
                  "created_by_label", "created_at"):
            assert k in d, f"missing key {k}"
        assert d["status"] == "pending"
        assert d["title"] == title
        assert d["template_name"] == "hello_world"
        # _id never leaks
        assert "_id" not in d

        # Cleanup
        requests.delete(f"{BASE}/api/admin/messaging/schedules/{d['id']}", headers=admin_h)


# ---------- 3) DELETE /admin/messaging/schedules/{id} ---------------------
class TestDeleteSchedule:
    def test_404_unknown(self, admin_h):
        r = requests.delete(f"{BASE}/api/admin/messaging/schedules/{uuid.uuid4().hex}",
                            headers=admin_h)
        assert r.status_code == 404, r.text

    def test_hard_delete_pending(self, admin_h):
        # Create
        c = requests.post(f"{BASE}/api/admin/messaging/schedules", headers=admin_h, json={
            "recipients": [{"kind": "raw", "phone": "+22500000999"}],
            "template_name": "hello_world",
            "scheduled_at": _future_iso(600),
        })
        assert c.status_code == 200, c.text
        sid = c.json()["id"]
        d = requests.delete(f"{BASE}/api/admin/messaging/schedules/{sid}", headers=admin_h)
        assert d.status_code == 200, d.text
        body = d.json()
        assert body == {"ok": True, "status": "deleted"}
        # Verify gone (404 on second delete)
        d2 = requests.delete(f"{BASE}/api/admin/messaging/schedules/{sid}", headers=admin_h)
        assert d2.status_code == 404

    def test_soft_cancel_running_or_done(self, admin_h):
        """Insert a doc directly with status='done' to simulate already-run schedule."""
        sid = uuid.uuid4().hex
        doc = {
            "id": sid,
            "title": "Iter12 done sched",
            "recipients": [{"kind": "raw", "phone": "+22500000333"}],
            "template_name": "hello_world",
            "language_code": "fr",
            "components": None,
            "scheduled_at": _past_iso(900),
            "status": "done",
            "result_summary": {"requested": 1, "sent_ok": 0, "sent_ko": 1, "skipped_count": 0, "skipped": [], "results": []},
            "created_by_id": "iter12-test",
            "created_by_label": "iter12",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        _sync_db.whatsapp_schedules.insert_one(doc.copy())
        try:
            r = requests.delete(f"{BASE}/api/admin/messaging/schedules/{sid}", headers=admin_h)
            assert r.status_code == 200, r.text
            assert r.json() == {"ok": True, "status": "cancelled"}
            after = _sync_db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
            assert after is not None
            assert after["status"] == "cancelled"
        finally:
            _sync_db.whatsapp_schedules.delete_one({"id": sid})


# ---------- 4) _run_scheduled_whatsapp runner (in-process) ----------------
class TestRunner:
    def test_runner_drains_past_pending(self, admin_h, event_loop):
        """Insert past-dated pending schedule with a phone recipient, run runner once,
        verify status=failed (Meta not configured) and result_summary populated."""
        sys.path.insert(0, "/app/backend")
        import server  # noqa: E402
        sid = uuid.uuid4().hex
        phone = "+225000004" + uuid.uuid4().hex[:2]
        doc = {
            "id": sid,
            "title": "Iter12 runner",
            "recipients": [
                {"kind": "raw", "phone": phone, "label": "Iter12 runner"},
                # phone-less recipient → should land in skipped[]
                {"kind": "client", "id": "no-such-user", "label": "Iter12 noPhone"},
            ],
            "template_name": "hello_world",
            "language_code": "fr",
            "components": None,
            "scheduled_at": _past_iso(120),
            "status": "pending",
            "result_summary": None,
            "created_by_id": "iter12-test",
            "created_by_label": "iter12-runner",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        _sync_db.whatsapp_schedules.insert_one(doc.copy())
        try:
            event_loop.run_until_complete(server._run_scheduled_whatsapp())

            after = _sync_db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
            assert after is not None, "schedule disappeared"
            assert after["status"] in ("failed", "done"), f"unexpected status={after['status']}"
            # Meta not configured → no successful send → status should be 'failed'
            assert after["status"] == "failed", f"expected 'failed' (Meta unconfigured), got {after['status']}"
            rs = after["result_summary"]
            assert rs is not None
            for k in ("requested", "sent_ok", "sent_ko", "skipped_count", "skipped", "results"):
                assert k in rs, f"missing {k} in result_summary"
            assert rs["requested"] == 2
            assert rs["sent_ok"] == 0
            assert rs["sent_ko"] == 1
            assert rs["skipped_count"] == 1
            assert any("téléphone" in (s.get("reason") or "").lower()
                       or "telephone" in (s.get("reason") or "").lower()
                       for s in rs["skipped"]), rs["skipped"]
            assert len(rs["results"]) == 1
            assert rs["results"][0]["phone"] == phone
            assert rs["results"][0]["ok"] is False

            msg = _sync_db.whatsapp_messages.find_one({"schedule_id": sid}, {"_id": 0})
            assert msg is not None, "no whatsapp_messages log written"
            assert msg.get("scheduled") is True
            assert msg.get("bulk") is True
            assert msg.get("to") == phone
            assert msg.get("recipient_kind") == "raw"
            # Re-running runner does NOT re-process (status no longer 'pending')
            event_loop.run_until_complete(server._run_scheduled_whatsapp())
            after2 = _sync_db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
            assert after2["status"] == after["status"]
        finally:
            _sync_db.whatsapp_schedules.delete_one({"id": sid})
            _sync_db.whatsapp_messages.delete_many({"schedule_id": sid})


# ---------- 5) Iter11 carry-over: TrackedUserCreate accepts phone ---------
class TestTrackedUserPhonePersistence:
    def test_create_tracked_with_phone(self, admin_h):
        # Need a parent client first
        parent_email = f"test_iter12_par_{uuid.uuid4().hex[:6]}@example.org"
        rc = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
            "email": parent_email, "full_name": "Iter12 Parent", "password": "Whatever!2026",
            "role": "client", "client_code": f"IT12P{uuid.uuid4().hex[:2].upper()}",
        })
        assert rc.status_code in (200, 201), rc.text
        parent_id = rc.json()["id"]
        try:
            phone = "+22500000456"
            email = f"test_iter12_tu_{uuid.uuid4().hex[:6]}@example.org"
            r = requests.post(f"{BASE}/api/admin/tracked-users", headers=admin_h, json={
                "client_id": parent_id,
                "name": "Iter12 Tracked",
                "email": email,
                "phone": phone,
                "role": "Consultation",
            })
            assert r.status_code in (200, 201), r.text
            tu = r.json()
            assert tu.get("phone") == phone, f"phone not persisted in create response: {tu}"
            tu_id = tu["id"]

            # Verify via audience endpoint that has_phone=true and phone matches
            aud = requests.get(f"{BASE}/api/admin/messaging/audience", headers=admin_h)
            assert aud.status_code == 200
            tracked_rows = aud.json().get("tracked_users", [])
            row = next((t for t in tracked_rows if t["id"] == tu_id), None)
            assert row is not None, "tracked user not visible in audience"
            assert row["phone"] == phone
            assert row["has_phone"] is True

            # Cleanup tracked user
            requests.delete(f"{BASE}/api/admin/tracked-users/{tu_id}", headers=admin_h)
        finally:
            requests.delete(f"{BASE}/api/admin/clients/{parent_id}", headers=admin_h)
