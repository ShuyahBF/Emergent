"""Iter35p — Ticket enhancements (assign, reopen, motif templates, resolution stats)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": data["dev_otp"]},
        timeout=30,
    )
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_user(db):
    return db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})


@pytest.fixture
def test_contact(db, admin_user):
    scope = admin_user.get("client_id") or admin_user["id"]
    cid = f"TEST_ct_{uuid.uuid4().hex[:8]}"
    contact = {
        "id": cid, "client_id": scope, "name": "Iter35p Contact",
        "whatsapp": "+22899880099", "phone": "+22899880099",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.contacts.insert_one(contact.copy())
    yield contact
    db.contacts.delete_one({"id": cid})
    db.support_tickets.delete_many({"contact_id": cid})


# ============================================================
# 1. Assignment
# ============================================================
class TestTicketAssignment:
    def test_assign_to_self_and_unassign(self, admin_h, admin_user, test_contact):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"motif": "assign"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        # Assign to admin himself
        r2 = requests.post(f"{API}/me/tickets/{tid}/assign", headers=admin_h, json={"user_id": admin_user["id"]}, timeout=15)
        assert r2.status_code == 200, r2.text
        t = r2.json()["ticket"]
        assert t["assigned_to_id"] == admin_user["id"]
        assert t["assigned_to_label"]
        assert t["assigned_at"]
        # Unassign
        r3 = requests.post(f"{API}/me/tickets/{tid}/assign", headers=admin_h, json={"user_id": ""}, timeout=15)
        assert r3.status_code == 200
        assert r3.json()["ticket"]["assigned_to_id"] is None

    def test_assign_rejects_out_of_scope(self, admin_h, test_contact):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"motif": "x"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        r2 = requests.post(f"{API}/me/tickets/{tid}/assign", headers=admin_h, json={"user_id": "__nonexistent__"}, timeout=15)
        assert r2.status_code == 400

    def test_assign_rejects_when_closed(self, admin_h, admin_user, test_contact):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"motif": "x"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        requests.post(f"{API}/me/tickets/{tid}/close", headers=admin_h, json={"outcome": "done"}, timeout=15)
        r2 = requests.post(f"{API}/me/tickets/{tid}/assign", headers=admin_h, json={"user_id": admin_user["id"]}, timeout=15)
        assert r2.status_code == 409


# ============================================================
# 2. Reopen (TKT-...-R1 chain)
# ============================================================
class TestTicketReopen:
    def test_reopen_creates_R1_linked(self, admin_h, db, test_contact):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"motif": "Origin"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        original_number = r.json()["ticket"]["number"]
        requests.post(f"{API}/me/tickets/{tid}/close", headers=admin_h, json={"outcome": "done"}, timeout=15)
        # Reopen
        r2 = requests.post(f"{API}/me/tickets/{tid}/reopen", headers=admin_h, json={"motif": "Re-prob"}, timeout=15)
        assert r2.status_code == 200, r2.text
        new_t = r2.json()["ticket"]
        assert new_t["number"] == f"{original_number}-R1"
        assert new_t["parent_ticket_id"] == tid
        assert new_t["root_number"] == original_number
        assert new_t["status"] == "open"
        # Second reopen → R2
        nt_id = new_t["id"]
        requests.post(f"{API}/me/tickets/{nt_id}/close", headers=admin_h, json={"outcome": "cancelled"}, timeout=15)
        r3 = requests.post(f"{API}/me/tickets/{nt_id}/reopen", headers=admin_h, json={}, timeout=15)
        assert r3.status_code == 200
        assert r3.json()["ticket"]["number"] == f"{original_number}-R2"
        assert r3.json()["ticket"]["root_number"] == original_number

    def test_reopen_rejects_if_open_exists(self, admin_h, test_contact):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"motif": "x"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        # Don't close — try to reopen
        r2 = requests.post(f"{API}/me/tickets/{tid}/reopen", headers=admin_h, json={}, timeout=15)
        assert r2.status_code == 409

    def test_reopen_reuses_motif_when_empty(self, admin_h, test_contact):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"motif": "ParentMotif"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        requests.post(f"{API}/me/tickets/{tid}/close", headers=admin_h, json={"outcome": "done"}, timeout=15)
        r2 = requests.post(f"{API}/me/tickets/{tid}/reopen", headers=admin_h, json={}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["ticket"]["motif"] == "ParentMotif"


# ============================================================
# 3. Motif templates
# ============================================================
class TestMotifTemplates:
    def test_crud_full_cycle(self, admin_h, db, admin_user):
        # Create
        r = requests.post(
            f"{API}/me/ticket-motif-templates", headers=admin_h,
            json={"label": "Panne onduleur", "motif": "Onduleur en alarme — site coupé"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        tpl_id = r.json()["template"]["id"]
        try:
            # List
            r2 = requests.get(f"{API}/me/ticket-motif-templates", headers=admin_h, timeout=15)
            assert r2.status_code == 200
            assert any(t["id"] == tpl_id and t["label"] == "Panne onduleur" for t in r2.json())
            # Delete
            r3 = requests.delete(f"{API}/me/ticket-motif-templates/{tpl_id}", headers=admin_h, timeout=15)
            assert r3.status_code == 200
            # Confirm gone
            r4 = requests.get(f"{API}/me/ticket-motif-templates", headers=admin_h, timeout=15)
            assert not any(t["id"] == tpl_id for t in r4.json())
        finally:
            db.ticket_motif_templates.delete_one({"id": tpl_id})

    def test_rejects_empty_or_too_long(self, admin_h):
        r = requests.post(f"{API}/me/ticket-motif-templates", headers=admin_h, json={"label": "", "motif": ""}, timeout=15)
        assert r.status_code == 400
        r2 = requests.post(f"{API}/me/ticket-motif-templates", headers=admin_h, json={"label": "x" * 61, "motif": "x"}, timeout=15)
        assert r2.status_code == 400


# ============================================================
# 4. Resolution-time stats
# ============================================================
class TestTicketStats:
    def test_resolution_stats_with_seeded_done(self, admin_h, db, admin_user):
        scope = admin_user.get("client_id") or admin_user["id"]
        now = datetime.now(timezone.utc)
        ids = []
        try:
            for hours_ago_open, hours_ago_close in [(5, 4), (3, 2), (8, 1)]:
                tid = f"TEST_stat_{uuid.uuid4().hex[:8]}"
                db.support_tickets.insert_one({
                    "id": tid,
                    "number": f"TKT-{now.year}-9{ids.__len__()}",
                    "client_id": scope,
                    "contact_id": f"TEST_ct_{uuid.uuid4().hex[:6]}",
                    "status": "done",
                    "outcome": "done",
                    "opened_at": (now - timedelta(hours=hours_ago_open)).isoformat(),
                    "closed_at": (now - timedelta(hours=hours_ago_close)).isoformat(),
                    "closed_by_id": admin_user["id"],
                    "closed_by_label": "Admin SAWALI",
                })
                ids.append(tid)

            r = requests.get(f"{API}/me/dashboard/ticket-stats?days=7", headers=admin_h, timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["days"] == 7
            me = body["me"]
            assert me["closed_count"] >= 3
            assert me["avg_seconds"] and me["avg_seconds"] > 0
            assert me["fastest_seconds"] and me["fastest_seconds"] > 0
            # Team leaderboard included for admin
            assert isinstance(body["team"], list)
        finally:
            for tid in ids:
                db.support_tickets.delete_one({"id": tid})

    def test_invalid_days(self, admin_h):
        r = requests.get(f"{API}/me/dashboard/ticket-stats?days=0", headers=admin_h, timeout=10)
        assert r.status_code == 422
