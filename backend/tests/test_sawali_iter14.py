"""SAWALI — Iteration 14 backend tests: AUTOMATIONS CRM module.

Coverage:
- HTTP CRUD: GET /admin/automations/events (4 events, label+description, 401/403 enforced).
- HTTP CRUD: GET/POST/PUT/DELETE /admin/automations (validation 400s, 404 unknown).
- Emitter (_emit_event):
  * Immediate happy path with variables substitution (monkeypatch _wa_send_template).
  * Delayed path → inserts whatsapp_schedules row (no immediate send).
  * No phone → logs row with ok=false, no send.
  * Disabled automation → no-op.
  * Unsupported event → no-op.
- Integration: POST /admin/clients triggers 'client.created' (asyncio.create_task).
- Integration: POST /admin/interventions triggers 'intervention.created'.
- Cron: _appointment_reminder_cron emits 'appointment.reminder' and stamps reminder_sent_at.
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

load_dotenv(Path("/app/backend/.env"))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

_sync_mongo = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_mongo[os.environ["DB_NAME"]]

sys.path.insert(0, "/app/backend")
import server  # noqa: E402


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
        return r2.json()["access_token"], r2.json()["user"]
    return d["access_token"], d["user"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


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
    email = f"test_iter14_cli_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "IterFourteen!2026"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Iter14 Client", "password": pwd, "role": "client",
        "client_code": f"IT14{uuid.uuid4().hex[:3].upper()}",
    })
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    tok, _ = _login(email, pwd)
    yield {"id": uid, "email": email, "token": tok}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


@pytest.fixture(scope="session")
def variable_client(admin_h):
    email = f"test_iter14_var_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "VarIter14!"
    code = f"V14{uuid.uuid4().hex[:3].upper()}"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Marie", "password": pwd, "role": "client",
        "client_code": code, "company": "Acme", "phone": "+22500000888",
    })
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    yield {"id": uid, "email": email, "client_code": code}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


def _cleanup_automation(aid):
    try:
        _sync_db.automations.delete_one({"id": aid})
    except Exception:
        pass


# ====================================================================
# 1) GET /admin/automations/events
# ====================================================================
class TestEventsEndpoint:
    def test_unauth_401(self):
        r = requests.get(f"{BASE}/api/admin/automations/events")
        assert r.status_code in (401, 403)

    def test_non_admin_forbidden(self, secondary_client):
        r = requests.get(f"{BASE}/api/admin/automations/events",
                         headers=_h(secondary_client["token"]))
        assert r.status_code == 403

    def test_admin_returns_four_events(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/automations/events", headers=admin_h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "events" in body and isinstance(body["events"], list)
        values = {e["value"] for e in body["events"]}
        # iter14 baseline: these 4 events must always be present
        # (iter17 added 'task.reminder' → allow superset)
        required = {"appointment.created", "appointment.reminder",
                    "intervention.created", "client.created"}
        assert required.issubset(values), f"missing required events: {required - values}"
        for e in body["events"]:
            assert "label" in e and "description" in e
            assert e["label"] and e["description"]


# ====================================================================
# 2) POST /admin/automations validation
# ====================================================================
class TestAutomationCreateValidation:
    def test_unsupported_event_400(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/automations", headers=admin_h, json={
            "title": "Bad", "event": "foo.bar", "template_name": "hello_world",
        })
        assert r.status_code == 400
        assert "non support" in r.text.lower() or "supporté" in r.text.lower() or "supporte" in r.text.lower()

    def test_empty_template_400(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/automations", headers=admin_h, json={
            "title": "Bad", "event": "client.created", "template_name": "   ",
        })
        assert r.status_code == 400

    def test_negative_delay_400(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/automations", headers=admin_h, json={
            "title": "Bad", "event": "client.created", "template_name": "hello_world",
            "delay_minutes": -1,
        })
        assert r.status_code == 400

    def test_fixed_target_requires_phone_400(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/automations", headers=admin_h, json={
            "title": "Bad", "event": "client.created", "template_name": "hello_world",
            "target": "fixed",
        })
        assert r.status_code == 400

    def test_happy_path_returns_doc(self, admin_h, admin):
        r = requests.post(f"{BASE}/api/admin/automations", headers=admin_h, json={
            "title": f"AutoTest {uuid.uuid4().hex[:5]}",
            "event": "client.created", "template_name": "hello_world",
            "language_code": "fr", "delay_minutes": 0, "enabled": True,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        try:
            assert "id" in d
            assert d["trigger_count"] == 0
            assert d["created_by_id"] == admin[1]["id"]
            assert "created_at" in d
            assert d["event"] == "client.created"
            assert "_id" not in d
        finally:
            requests.delete(f"{BASE}/api/admin/automations/{d['id']}", headers=admin_h)


# ====================================================================
# 3) GET / PUT / DELETE
# ====================================================================
class TestAutomationCrud:
    def test_list_returns_array(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/automations", headers=admin_h)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_unauth_401(self):
        r = requests.get(f"{BASE}/api/admin/automations")
        assert r.status_code in (401, 403)

    def test_update_partial_and_404(self, admin_h):
        # 404
        r = requests.put(f"{BASE}/api/admin/automations/nonexistent-id",
                         headers=admin_h, json={"enabled": False})
        assert r.status_code == 404

        # create then PUT enabled=false
        c = requests.post(f"{BASE}/api/admin/automations", headers=admin_h, json={
            "title": "Patch me", "event": "client.created", "template_name": "hello_world",
        })
        assert c.status_code == 200
        aid = c.json()["id"]
        try:
            assert c.json()["enabled"] is True
            u = requests.put(f"{BASE}/api/admin/automations/{aid}",
                             headers=admin_h, json={"enabled": False})
            assert u.status_code == 200, u.text
            d = u.json()
            assert d["enabled"] is False
            # template_name must be unchanged (only enabled was sent)
            assert d["template_name"] == "hello_world"
        finally:
            requests.delete(f"{BASE}/api/admin/automations/{aid}", headers=admin_h)

    def test_delete_404_then_200(self, admin_h):
        r = requests.delete(f"{BASE}/api/admin/automations/does-not-exist", headers=admin_h)
        assert r.status_code == 404

        c = requests.post(f"{BASE}/api/admin/automations", headers=admin_h, json={
            "title": "Delete me", "event": "client.created", "template_name": "hello_world",
        })
        aid = c.json()["id"]
        d = requests.delete(f"{BASE}/api/admin/automations/{aid}", headers=admin_h)
        assert d.status_code == 200
        # Verify gone
        listing = requests.get(f"{BASE}/api/admin/automations", headers=admin_h).json()
        assert all(it["id"] != aid for it in listing)


# ====================================================================
# 4) Emitter — _emit_event direct in-process tests
# ====================================================================
class TestEmitter:
    def _seed_automation(self, **overrides):
        doc = {
            "id": uuid.uuid4().hex,
            "title": "Test auto",
            "event": "client.created",
            "template_name": "hello_world",
            "language_code": "fr",
            "variables": ["Bonjour {{full_name}} de {{company}}"],
            "delay_minutes": 0,
            "target": "event_target",
            "target_phone": None,
            "enabled": True,
            "trigger_count": 0,
            "created_by_id": "iter14-test",
            "created_by_label": "iter14",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        doc.update(overrides)
        _sync_db.automations.insert_one(doc.copy())
        return doc

    def test_immediate_happy_path_substitutes_variables(self, variable_client, monkeypatch, event_loop):
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append({"phone": phone, "template_name": template_name,
                             "language_code": language_code, "components": components})
            return {"ok": True, "status": 200, "message_id": "wamid.TEST", "error": None}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        au = self._seed_automation()
        try:
            event_loop.run_until_complete(server._emit_event("client.created", {
                "client_id": variable_client["id"],
                "phone": "+22500000888",
            }))
            assert len(captured) == 1, f"expected 1 send, got {len(captured)}"
            cap = captured[0]
            assert cap["phone"] == "+22500000888"
            assert cap["template_name"] == "hello_world"
            comps = cap["components"]
            assert isinstance(comps, list) and len(comps) == 1
            assert comps[0]["parameters"][0] == {"type": "text", "text": "Bonjour Marie de Acme"}

            # whatsapp_messages row inserted
            log = _sync_db.whatsapp_messages.find_one({"automation_id": au["id"]}, {"_id": 0})
            assert log is not None
            assert log["automation_event"] == "client.created"
            assert log["recipient_kind"] == "client"
            assert log["ok"] is True

            # trigger_count incremented
            after = _sync_db.automations.find_one({"id": au["id"]}, {"_id": 0})
            assert after["trigger_count"] == 1
        finally:
            _cleanup_automation(au["id"])
            _sync_db.whatsapp_messages.delete_many({"automation_id": au["id"]})

    def test_delayed_creates_schedule_no_immediate_send(self, variable_client, monkeypatch, event_loop):
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append(phone)
            return {"ok": True, "status": 200, "message_id": "X", "error": None}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        au = self._seed_automation(delay_minutes=30)
        try:
            event_loop.run_until_complete(server._emit_event("client.created", {
                "client_id": variable_client["id"],
                "phone": "+22500000888",
            }))
            assert captured == [], "no immediate send expected for delayed automation"

            sched = _sync_db.whatsapp_schedules.find_one({"automation_id": au["id"]}, {"_id": 0})
            assert sched is not None
            assert sched["status"] == "pending"
            assert sched["template_name"] == "hello_world"
            assert sched["variables"] == ["Bonjour {{full_name}} de {{company}}"]
            # scheduled_at ~ now + 30min (allow ±5min)
            sa = dt.datetime.fromisoformat(sched["scheduled_at"])
            now = dt.datetime.now(dt.timezone.utc)
            delta = (sa - now).total_seconds()
            assert 25 * 60 <= delta <= 35 * 60, f"delta out of bounds: {delta}s"
            # recipient carried over
            assert sched["recipients"][0]["phone"] == "+22500000888"
            # trigger_count still incremented
            after = _sync_db.automations.find_one({"id": au["id"]}, {"_id": 0})
            assert after["trigger_count"] == 1
        finally:
            _cleanup_automation(au["id"])
            _sync_db.whatsapp_schedules.delete_many({"automation_id": au["id"]})

    def test_no_phone_logs_row_no_send(self, admin_h, monkeypatch, event_loop):
        # Create user without phone
        email = f"test_iter14_nop_{uuid.uuid4().hex[:5]}@example.org"
        r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
            "email": email, "full_name": "NoPhone", "password": "Pwd!2026", "role": "client",
            "client_code": f"NP{uuid.uuid4().hex[:3].upper()}",
        })
        uid = r.json()["id"]

        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append(phone)
            return {"ok": True, "status": 200, "message_id": "X", "error": None}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        au = self._seed_automation()
        try:
            event_loop.run_until_complete(server._emit_event("client.created", {
                "client_id": uid,
            }))
            assert captured == [], "should not call _wa_send_template when no phone"
            log = _sync_db.whatsapp_messages.find_one({"automation_id": au["id"]}, {"_id": 0})
            assert log is not None
            assert log["ok"] is False
            assert log["error"] == "Pas de numéro de téléphone"
        finally:
            _cleanup_automation(au["id"])
            _sync_db.whatsapp_messages.delete_many({"automation_id": au["id"]})
            requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)

    def test_disabled_automation_is_ignored(self, variable_client, monkeypatch, event_loop):
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append(phone)
            return {"ok": True, "status": 200, "message_id": "X", "error": None}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        au = self._seed_automation(enabled=False)
        try:
            event_loop.run_until_complete(server._emit_event("client.created", {
                "client_id": variable_client["id"],
                "phone": "+22500000888",
            }))
            assert captured == []
            sched = _sync_db.whatsapp_schedules.find_one({"automation_id": au["id"]})
            assert sched is None
            after = _sync_db.automations.find_one({"id": au["id"]}, {"_id": 0})
            assert after["trigger_count"] == 0
        finally:
            _cleanup_automation(au["id"])

    def test_unsupported_event_is_noop(self, monkeypatch, event_loop):
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append(phone)
            return {"ok": True, "status": 200, "message_id": "X", "error": None}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)
        # Should not raise, no captures
        event_loop.run_until_complete(server._emit_event("foo.bar", {"phone": "+22500000123"}))
        assert captured == []


# ====================================================================
# 5) Integration — POST /admin/clients triggers 'client.created'
# ====================================================================
class TestIntegrationClientCreated:
    def test_post_admin_clients_emits_event(self, admin_h, monkeypatch, event_loop):
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append({"phone": phone, "components": components})
            return {"ok": True, "status": 200, "message_id": "wamid.X", "error": None}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        # Seed automation
        aid = uuid.uuid4().hex
        _sync_db.automations.insert_one({
            "id": aid,
            "title": "OnClientCreated",
            "event": "client.created",
            "template_name": "welcome",
            "language_code": "fr",
            "variables": ["Bienvenue {{full_name}}"],
            "delay_minutes": 0,
            "target": "event_target",
            "target_phone": None,
            "enabled": True,
            "trigger_count": 0,
            "created_by_id": "iter14-test",
            "created_by_label": "iter14",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })

        email = f"test_iter14_int_{uuid.uuid4().hex[:5]}@example.org"
        body = {
            "email": email, "full_name": "Pierre", "password": "Pwd!2026", "role": "client",
            "client_code": f"INT{uuid.uuid4().hex[:3].upper()}",
            "company": "Acme", "phone": "+22500000999",
        }
        r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json=body)
        assert r.status_code in (200, 201), r.text
        uid = r.json()["id"]

        try:
            # Wait for fire-and-forget asyncio.create_task (lives in backend's loop)
            for _ in range(40):
                if captured:
                    break
                event_loop.run_until_complete(asyncio.sleep(0.1))
            # NOTE: Because monkeypatch is in THIS process and the API runs in the
            # backend uvicorn process, we cannot directly capture sends made by the
            # live server. Instead, verify side effects via DB: a whatsapp_messages
            # row with automation_id=aid must exist.
            for _ in range(20):
                log = _sync_db.whatsapp_messages.find_one({"automation_id": aid}, {"_id": 0})
                if log:
                    break
                import time as _t
                _t.sleep(0.25)
            log = _sync_db.whatsapp_messages.find_one({"automation_id": aid}, {"_id": 0})
            assert log is not None, "Expected whatsapp_messages row from client.created automation"
            assert log["automation_event"] == "client.created"
            after = _sync_db.automations.find_one({"id": aid}, {"_id": 0})
            assert after["trigger_count"] >= 1
        finally:
            _sync_db.automations.delete_one({"id": aid})
            _sync_db.whatsapp_messages.delete_many({"automation_id": aid})
            requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


# ====================================================================
# 6) Integration — POST /admin/interventions triggers 'intervention.created'
# ====================================================================
class TestIntegrationInterventionCreated:
    def test_post_admin_interventions_emits_event(self, admin_h, variable_client):
        aid = uuid.uuid4().hex
        _sync_db.automations.insert_one({
            "id": aid,
            "title": "OnInterventionCreated",
            "event": "intervention.created",
            "template_name": "intervention_tpl",
            "language_code": "fr",
            "variables": None,
            "delay_minutes": 0,
            "target": "event_target",
            "target_phone": None,
            "enabled": True,
            "trigger_count": 0,
            "created_by_id": "iter14-test",
            "created_by_label": "iter14",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })

        body = {
            "client_id": variable_client["id"],
            "title": "Iter14 intervention",
            "subject": "Iter14 intervention",
            "type": "support",
            "description": "Test",
            "intervention_date": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        r = requests.post(f"{BASE}/api/admin/interventions", headers=admin_h, json=body)
        assert r.status_code in (200, 201), r.text
        iid = r.json().get("id")

        try:
            import time as _t
            log = None
            for _ in range(20):
                log = _sync_db.whatsapp_messages.find_one({"automation_id": aid}, {"_id": 0})
                if log:
                    break
                _t.sleep(0.25)
            assert log is not None, "Expected whatsapp_messages row from intervention.created automation"
            assert log["automation_event"] == "intervention.created"
        finally:
            _sync_db.automations.delete_one({"id": aid})
            _sync_db.whatsapp_messages.delete_many({"automation_id": aid})
            if iid:
                requests.delete(f"{BASE}/api/admin/interventions/{iid}", headers=admin_h)


# ====================================================================
# 7) Cron — _appointment_reminder_cron emits and stamps
# ====================================================================
class TestAppointmentReminderCron:
    def test_cron_emits_reminder_and_stamps(self, variable_client, monkeypatch, event_loop):
        captured_events = []

        # Monkey-patch _emit_event itself (this process) to capture invocation.
        original_emit = server._emit_event

        async def fake_emit(event, target):
            captured_events.append({"event": event, "target": target})
            # Don't call through (avoid double-effects)
            return None

        monkeypatch.setattr(server, "_emit_event", fake_emit)

        appt_id = uuid.uuid4().hex
        sched_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)).isoformat()
        _sync_db.appointments.insert_one({
            "id": appt_id,
            "client_id": variable_client["id"],
            "subject": "Iter14 reminder",
            "scheduled_at": sched_at,
            "status": "confirmed",
            "phone": "+22500000888",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })

        try:
            event_loop.run_until_complete(server._appointment_reminder_cron())
            # Should emit appointment.reminder
            reminder_events = [e for e in captured_events if e["event"] == "appointment.reminder"]
            assert len(reminder_events) >= 1, f"Expected at least 1 appointment.reminder, captured: {captured_events}"
            # Find the one matching our client
            ours = [e for e in reminder_events if e["target"].get("client_id") == variable_client["id"]]
            assert len(ours) == 1
            assert "extra_ctx" in ours[0]["target"]
            assert "appointment_date" in ours[0]["target"]["extra_ctx"]

            # Stamped reminder_sent_at
            updated = _sync_db.appointments.find_one({"id": appt_id}, {"_id": 0})
            assert updated.get("reminder_sent_at"), "reminder_sent_at not stamped"
        finally:
            server._emit_event = original_emit
            _sync_db.appointments.delete_one({"id": appt_id})
