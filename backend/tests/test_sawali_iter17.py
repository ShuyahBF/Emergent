"""SAWALI — Iteration 17 backend tests: Notes & Tasks per client + task.reminder cron.

Coverage:
 - Notes CRUD (GET/POST/DELETE) with auth, validation (empty, >5000), 404 on unknown.
 - Tasks CRUD (GET/POST/PUT/DELETE) with auth, validation (empty title, bad ISO, bad status), 404.
 - Timeline now includes 'note' and 'task' types; counts has 'note' and 'task' keys;
   ?types=note → only notes, ?types=task → only tasks.
 - Automation events endpoint returns 5 events incl. task.reminder; creating an
   automation with event='task.reminder' succeeds.
 - _task_reminder_cron:
      (a) stamps reminder_sent_at on matching task,
      (b) invokes _wa_send_template (monkeypatched) when an enabled automation
          with event='task.reminder' exists,
      (c) 2nd invocation does NOT re-send (reminder_sent_at already set).
"""
from __future__ import annotations

import os
import sys
import uuid
import datetime as dt
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

# Ensure backend on path for direct module import (cron test)
sys.path.insert(0, str(Path("/app/backend")))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

_sync_mongo = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_mongo[os.environ["DB_NAME"]]


# ---------- helpers -------------------------------------------------------
def _login(email: str, password: str):
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    if d.get("needs_otp"):
        assert d.get("dev_otp"), f"dev_otp expected, got {d}"
        r2 = sess.post(
            f"{BASE}/api/auth/verify-otp",
            json={"session_token": d["session_token"], "code": d["dev_otp"]},
        )
        assert r2.status_code == 200, r2.text
        return r2.json()["access_token"], r2.json()["user"]
    return d["access_token"], d["user"]


def _h(tok: str):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- fixtures ------------------------------------------------------
@pytest.fixture(scope="module")
def admin():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok, u


@pytest.fixture(scope="module")
def admin_h(admin):
    return _h(admin[0])


@pytest.fixture(scope="module")
def test_client(admin_h):
    email = f"test_iter17_nt_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "IterSeventeen!2026"
    r = requests.post(
        f"{BASE}/api/admin/clients",
        headers=admin_h,
        json={
            "email": email,
            "full_name": "Iter17 Notes/Tasks Client",
            "company": "Iter17 Co",
            "password": pwd,
            "role": "client",
            "client_code": f"IT17{uuid.uuid4().hex[:3].upper()}",
        },
    )
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    tok, _ = _login(email, pwd)
    yield {"id": uid, "email": email, "token": tok}
    # cleanup
    _sync_db.client_notes.delete_many({"client_id": uid})
    _sync_db.client_tasks.delete_many({"client_id": uid})
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


# ============================================================
# Notes CRUD
# ============================================================
class TestNotes:
    def test_auth_no_token(self, test_client):
        r = requests.get(f"{BASE}/api/admin/clients/{test_client['id']}/notes")
        assert r.status_code in (401, 403), r.text

    def test_auth_non_admin_forbidden(self, test_client):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes",
            headers=_h(test_client["token"]),
        )
        assert r.status_code == 403, r.text

    def test_list_empty(self, test_client, admin_h):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes", headers=admin_h
        )
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_create_empty_text_400(self, test_client, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes",
            headers=admin_h,
            json={"text": "   "},
        )
        assert r.status_code == 400, r.text
        assert "Le texte de la note est requis" in r.json().get("detail", "")

    def test_create_too_long_400(self, test_client, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes",
            headers=admin_h,
            json={"text": "x" * 5001},
        )
        assert r.status_code == 400, r.text

    def test_create_ok_and_shape(self, test_client, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes",
            headers=admin_h,
            json={"text": "TEST_IT17 Note initial - appel client OK"},
        )
        assert r.status_code == 200, r.text
        doc = r.json()
        for k in ("id", "client_id", "text", "author_id", "author_label", "created_at"):
            assert k in doc, f"missing {k} in {doc}"
        assert doc["client_id"] == test_client["id"]
        assert doc["text"].startswith("TEST_IT17")
        # list should now contain 1 item
        r2 = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes", headers=admin_h
        )
        assert r2.status_code == 200
        assert any(n["id"] == doc["id"] for n in r2.json())

    def test_delete_unknown_404(self, test_client, admin_h):
        r = requests.delete(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes/not-exist-id",
            headers=admin_h,
        )
        assert r.status_code == 404, r.text

    def test_delete_ok(self, test_client, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes",
            headers=admin_h,
            json={"text": "to-be-deleted"},
        )
        nid = r.json()["id"]
        r2 = requests.delete(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes/{nid}",
            headers=admin_h,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json() == {"ok": True}


# ============================================================
# Tasks CRUD
# ============================================================
class TestTasks:
    def test_auth_no_token(self, test_client):
        r = requests.get(f"{BASE}/api/admin/clients/{test_client['id']}/tasks")
        assert r.status_code in (401, 403)

    def test_auth_non_admin_forbidden(self, test_client):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks",
            headers=_h(test_client["token"]),
        )
        assert r.status_code == 403

    def test_create_empty_title_400(self, test_client, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks",
            headers=admin_h,
            json={"title": "   "},
        )
        assert r.status_code == 400, r.text
        assert "Titre de la tâche requis" in r.json().get("detail", "")

    def test_create_bad_due_at_400(self, test_client, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks",
            headers=admin_h,
            json={"title": "T", "due_at": "not-an-iso-date"},
        )
        assert r.status_code == 400, r.text
        assert "Date d'échéance invalide" in r.json().get("detail", "")

    def test_create_ok_and_shape(self, test_client, admin_h):
        due = (dt.datetime.utcnow() + dt.timedelta(days=1)).replace(microsecond=0).isoformat()
        r = requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks",
            headers=admin_h,
            json={
                "title": "TEST_IT17 Rappel client",
                "due_at": due,
                "remind_via_whatsapp": True,
            },
        )
        assert r.status_code == 200, r.text
        doc = r.json()
        for k in ("id", "client_id", "title", "due_at", "status", "remind_via_whatsapp",
                   "reminder_sent_at", "created_at"):
            assert k in doc, f"missing {k}"
        assert doc["status"] == "open"
        assert doc["remind_via_whatsapp"] is True
        assert doc["reminder_sent_at"] is None
        # keep id on fixture for downstream tests
        pytest._IT17_task_id = doc["id"]

    def test_update_bad_status_400(self, test_client, admin_h):
        tid = pytest._IT17_task_id
        r = requests.put(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks/{tid}",
            headers=admin_h,
            json={"status": "wtf"},
        )
        assert r.status_code == 400, r.text

    def test_update_unknown_404(self, test_client, admin_h):
        r = requests.put(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks/ghost-id",
            headers=admin_h,
            json={"title": "nope"},
        )
        assert r.status_code == 404, r.text

    def test_update_ok_and_persist(self, test_client, admin_h):
        tid = pytest._IT17_task_id
        r = requests.put(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks/{tid}",
            headers=admin_h,
            json={"status": "done"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "done"
        # verify persisted
        r2 = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks", headers=admin_h
        )
        assert r2.status_code == 200
        match = [t for t in r2.json() if t["id"] == tid]
        assert match and match[0]["status"] == "done"

    def test_delete_unknown_404(self, test_client, admin_h):
        r = requests.delete(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks/nope",
            headers=admin_h,
        )
        assert r.status_code == 404, r.text

    def test_delete_ok(self, test_client, admin_h):
        tid = pytest._IT17_task_id
        r = requests.delete(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks/{tid}",
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}


# ============================================================
# Timeline integration
# ============================================================
class TestTimelineNotesTasks:
    @pytest.fixture(scope="class", autouse=True)
    def seed(self, test_client, admin_h):
        # 1 note + 1 task
        requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/notes",
            headers=admin_h,
            json={"text": "TEST_IT17_TL note"},
        )
        due = (dt.datetime.utcnow() + dt.timedelta(hours=5)).replace(microsecond=0).isoformat()
        requests.post(
            f"{BASE}/api/admin/clients/{test_client['id']}/tasks",
            headers=admin_h,
            json={"title": "TEST_IT17_TL task", "due_at": due},
        )
        yield
        _sync_db.client_notes.delete_many({"client_id": test_client["id"]})
        _sync_db.client_tasks.delete_many({"client_id": test_client["id"]})

    def test_counts_has_note_and_task_keys(self, test_client, admin_h):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline", headers=admin_h
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "note" in body["counts"]
        assert "task" in body["counts"]
        assert body["counts"]["note"] >= 1
        assert body["counts"]["task"] >= 1
        types = {e["type"] for e in body["events"]}
        assert "note" in types
        assert "task" in types

    def test_filter_types_note_only(self, test_client, admin_h):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline?types=note",
            headers=admin_h,
        )
        assert r.status_code == 200
        body = r.json()
        assert all(e["type"] == "note" for e in body["events"])
        assert body["counts"]["note"] == len(body["events"])
        assert body["counts"]["task"] == 0

    def test_filter_types_task_only(self, test_client, admin_h):
        r = requests.get(
            f"{BASE}/api/admin/clients/{test_client['id']}/timeline?types=task",
            headers=admin_h,
        )
        assert r.status_code == 200
        body = r.json()
        assert all(e["type"] == "task" for e in body["events"])
        assert body["counts"]["task"] == len(body["events"])
        assert body["counts"]["note"] == 0


# ============================================================
# Automation event task.reminder
# ============================================================
class TestAutomationEvent:
    def test_events_endpoint_has_task_reminder(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/automations/events", headers=admin_h)
        assert r.status_code == 200
        events = r.json()["events"]
        values = [e["value"] for e in events]
        assert "task.reminder" in values
        assert len(values) == 5
        tr = next(e for e in events if e["value"] == "task.reminder")
        assert tr["label"] == "Rappel de tâche"
        assert "1h" in tr["description"] or "horaire" in tr["description"]

    def test_create_automation_task_reminder_ok(self, admin_h):
        r = requests.post(
            f"{BASE}/api/admin/automations",
            headers=admin_h,
            json={
                "title": "TEST_IT17 Rappel tâche",
                "event": "task.reminder",
                "template_name": "task_reminder_iter17",
                "language_code": "fr",
                "variables": ["task_title", "task_due"],
                "delay_minutes": 0,
                "target": "event_target",
                "enabled": True,
            },
        )
        assert r.status_code in (200, 201), r.text
        aid = r.json().get("id")
        assert aid
        # cleanup
        requests.delete(f"{BASE}/api/admin/automations/{aid}", headers=admin_h)


# ============================================================
# _task_reminder_cron direct invocation
# ============================================================
class TestTaskReminderCron:
    def test_cron_stamps_and_fires_then_idempotent(self, event_loop, test_client, admin_h):
        import server  # type: ignore

        uid = test_client["id"]
        # Clean slate for this client
        _sync_db.client_tasks.delete_many({"client_id": uid})
        _sync_db.automations.delete_many({"title": "TEST_IT17_CRON auto"})

        # Seed task: due in 30min, open, remind=true, reminder_sent_at=None
        due = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)).replace(microsecond=0).isoformat()
        task_doc = {
            "id": f"task-it17-{uuid.uuid4().hex[:8]}",
            "client_id": uid,
            "title": "TEST_IT17_CRON task",
            "description": None,
            "due_at": due,
            "status": "open",
            "remind_via_whatsapp": True,
            "reminder_sent_at": None,
            "author_id": "admin",
            "author_label": "Admin",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        _sync_db.client_tasks.insert_one(task_doc.copy())

        # Seed an enabled automation on task.reminder so _emit_event has something to fire
        auto_doc = {
            "id": f"auto-it17-{uuid.uuid4().hex[:8]}",
            "title": "TEST_IT17_CRON auto",
            "event": "task.reminder",
            "template_name": "task_reminder_tpl",
            "language_code": "fr",
            "variables": ["task_title", "task_due"],
            "delay_minutes": 0,
            "target": "event_target",
            "target_phone": None,
            "enabled": True,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        _sync_db.automations.insert_one(auto_doc.copy())

        # Monkeypatch _wa_send_template to capture calls
        captured: list = []

        async def _fake_wa(to_e164, template_name, language_code="fr", components=None):
            captured.append({
                "to": to_e164,
                "template_name": template_name,
                "language_code": language_code,
                "components": components,
            })
            return {"ok": True, "status": "sent", "message_id": f"m-{uuid.uuid4().hex[:6]}"}

        original = server._wa_send_template
        server._wa_send_template = _fake_wa
        try:
            # Set a phone on the user to allow send
            _sync_db.users.update_one({"id": uid}, {"$set": {"phone": "+212600000017"}})

            # 1st run → should stamp + (if automation has phone) call _wa_send_template
            event_loop.run_until_complete(server._task_reminder_cron())

            stamped = _sync_db.client_tasks.find_one({"id": task_doc["id"]})
            assert stamped is not None
            assert stamped.get("reminder_sent_at") is not None, \
                f"reminder_sent_at should be stamped, got: {stamped.get('reminder_sent_at')}"

            first_count = len(captured)
            assert first_count == 1, f"expected 1 WA send on 1st cron run, got {first_count}: {captured}"

            # 2nd run → should NOT re-fire (reminder_sent_at already set)
            event_loop.run_until_complete(server._task_reminder_cron())
            assert len(captured) == first_count, \
                f"2nd cron run should not re-process, captured grew from {first_count} to {len(captured)}"
        finally:
            server._wa_send_template = original
            _sync_db.client_tasks.delete_many({"client_id": uid})
            _sync_db.automations.delete_many({"id": auto_doc["id"]})
