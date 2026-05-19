"""Iter35r — Welcome briefing + ticket enrichment + notes rating fix."""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data["dev_otp"]}, timeout=30)
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_user(db):
    return db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})


# ============================================================
# #4 — Rating on notes/tasks no longer returns "Type non noté"
# ============================================================
class TestNotesRating:
    def test_rate_personal_note(self, admin_h, db, admin_user):
        # Create a personal note first
        r = requests.post(f"{API}/me/notes/notes", headers=admin_h, json={"title": "rate-test"}, timeout=15)
        assert r.status_code == 200, r.text
        note_id = r.json()["id"]
        try:
            # Rate it — previously this returned 404 "Type non noté"
            r2 = requests.post(f"{API}/me/ratings/notes/{note_id}", headers=admin_h, json={"stars": 4, "comment": "ok"}, timeout=15)
            assert r2.status_code == 200, r2.text
        finally:
            db.user_notes_personal.delete_one({"id": note_id})
            db.ratings.delete_many({"target_id": note_id})

    def test_rate_personal_task(self, admin_h, db):
        r = requests.post(f"{API}/me/notes/tasks", headers=admin_h, json={"title": "rate-task"}, timeout=15)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        try:
            r2 = requests.post(f"{API}/me/ratings/tasks/{tid}", headers=admin_h, json={"stars": 5}, timeout=15)
            assert r2.status_code == 200, r2.text
        finally:
            db.user_tasks_personal.delete_one({"id": tid})
            db.ratings.delete_many({"target_id": tid})

    def test_unknown_kind_still_rejected(self, admin_h):
        r = requests.post(f"{API}/me/ratings/wat/abc", headers=admin_h, json={"stars": 3}, timeout=15)
        assert r.status_code == 404


# ============================================================
# #1 — Tickets enrichment: client_label, company_label, age & pause
# ============================================================
class TestTicketsEnrichment:
    @pytest.fixture
    def fresh_ticket(self, admin_h, db, admin_user):
        scope = admin_user.get("client_id") or admin_user["id"]
        cid = f"TEST_dc_{uuid.uuid4().hex[:8]}"
        db.directory_contacts.insert_one({
            "id": cid, "client_id": scope, "name": "Iter35r ticket",
            "whatsapp": "+22899880022", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"motif": "Enrich"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        yield {"cid": cid, "tid": tid, "number": r.json()["ticket"]["number"]}
        db.directory_contacts.delete_one({"id": cid})
        db.support_tickets.delete_many({"contact_id": cid})

    def test_list_returns_client_company_and_durations(self, admin_h, fresh_ticket):
        r = requests.get(f"{API}/me/tickets?status=open", headers=admin_h, timeout=15)
        assert r.status_code == 200
        t = next((x for x in r.json() if x["id"] == fresh_ticket["tid"]), None)
        assert t is not None
        # Newly added fields must be present (values may be None for admin)
        assert "client_label" in t
        assert "company_label" in t
        assert "age_seconds" in t and t["age_seconds"] is not None and t["age_seconds"] >= 0
        assert "pause_seconds" in t and t["pause_seconds"] == 0  # not suspended yet

    def test_suspend_then_resume_accumulates_pause_time(self, admin_h, fresh_ticket):
        tid = fresh_ticket["tid"]
        # Suspend
        r1 = requests.patch(f"{API}/me/tickets/{tid}", headers=admin_h, json={"status": "suspended"}, timeout=15)
        assert r1.status_code == 200
        time.sleep(2)
        # Resume → in_progress
        r2 = requests.patch(f"{API}/me/tickets/{tid}", headers=admin_h, json={"status": "in_progress"}, timeout=15)
        assert r2.status_code == 200
        # List → pause_seconds must be ~2
        r3 = requests.get(f"{API}/me/tickets?status=in_progress", headers=admin_h, timeout=15)
        t = next((x for x in r3.json() if x["id"] == tid), None)
        assert t is not None
        assert t["pause_seconds"] >= 1, f"pause_seconds={t['pause_seconds']}"
        assert t["pause_seconds"] <= 30  # reasonable upper bound for test

    def test_suspended_ticket_includes_running_pause(self, admin_h, fresh_ticket):
        tid = fresh_ticket["tid"]
        requests.patch(f"{API}/me/tickets/{tid}", headers=admin_h, json={"status": "suspended"}, timeout=15)
        time.sleep(2)
        r = requests.get(f"{API}/me/tickets?status=suspended", headers=admin_h, timeout=15)
        t = next((x for x in r.json() if x["id"] == tid), None)
        assert t is not None
        # Still suspended → pause_seconds includes the live timer
        assert t["pause_seconds"] >= 1


# ============================================================
# #3 — Welcome briefing
# ============================================================
class TestWelcomeBriefing:
    def test_shape(self, admin_h):
        r = requests.get(f"{API}/me/welcome-briefing", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("tickets", "tickets_count", "unread_messages", "recent_notes", "recent_notes_count", "recent_notes_window_days"):
            assert k in body
        assert isinstance(body["tickets"], list)
        assert isinstance(body["recent_notes"], list)
        assert isinstance(body["tickets_count"], int)
        assert isinstance(body["unread_messages"], dict)
        for k in ("whatsapp", "sms", "total"):
            assert k in body["unread_messages"]
        assert body["recent_notes_window_days"] >= 1

    def test_recent_notes_respects_window(self, admin_h, db, admin_user):
        # Seed an old note (10 days ago) — must NOT appear
        old_id = f"TEST_old_{uuid.uuid4().hex[:6]}"
        old_iso = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        db.user_notes_personal.insert_one({
            "id": old_id, "owner_id": admin_user["id"], "title": "OLD note",
            "created_at": old_iso,
        })
        # Seed a fresh note (1 hour ago) — must appear
        new_id = f"TEST_new_{uuid.uuid4().hex[:6]}"
        new_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.user_notes_personal.insert_one({
            "id": new_id, "owner_id": admin_user["id"], "title": "FRESH note",
            "created_at": new_iso,
        })
        try:
            r = requests.get(f"{API}/me/welcome-briefing", headers=admin_h, timeout=15)
            assert r.status_code == 200
            ids = {n["id"] for n in r.json()["recent_notes"]}
            assert new_id in ids
            assert old_id not in ids
        finally:
            db.user_notes_personal.delete_one({"id": old_id})
            db.user_notes_personal.delete_one({"id": new_id})
