"""Iter35o — Support tickets (intervention tickets opened from WA chat).

Validates:
  - POST /api/me/contacts/{cid}/ticket creates a TKT-YYYY-NNNN per client.
  - Cannot open a second ticket while the previous is still open.
  - GET /api/me/tickets returns the list and supports ?status filter.
  - GET /api/me/tickets/pending-count counts non-closed.
  - PATCH /api/me/tickets/{tid} updates status / motif within allowed values.
  - POST /api/me/tickets/{tid}/close closes the ticket (done | cancelled).
  - GET /api/me/contacts/{cid}/active-ticket returns the open one (if any).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
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
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data["access_token"]
    code = data.get("dev_otp")
    assert code
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": data["session_token"], "code": code},
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




@pytest.fixture(scope="module")
def target_client_id(admin_user):
    """Iter36k — client_id obligatoire dans le payload (dropdown frontend)."""
    return admin_user.get("client_id") or admin_user["id"]


def _ticket_payload(motif: str, client_id: str) -> dict:
    return {"motif": motif, "client_id": client_id}

@pytest.fixture
def test_contact(db, admin_user):
    """Create a fresh contact + clean up at teardown."""
    scope = admin_user.get("client_id") or admin_user["id"]
    cid = f"TEST_ct_{uuid.uuid4().hex[:8]}"
    contact = {
        "id": cid,
        "client_id": scope,
        "name": "Test Contact iter35o",
        "phone": "+22899887700",
        "whatsapp": "+22899887700",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.contacts.insert_one(contact.copy())
    yield contact
    db.contacts.delete_one({"id": cid})
    db.support_tickets.delete_many({"contact_id": cid})


class TestTicketCreation:
    def test_open_ticket_returns_TKT_format(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        r = requests.post(
            f"{API}/me/contacts/{cid}/ticket",
            headers=admin_h, json={"client_id": target_client_id, "motif": "Panne onduleur"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        t = body["ticket"]
        year = datetime.now(timezone.utc).year
        assert t["number"].startswith(f"TKT-{year}-")
        assert t["status"] == "open"
        assert t["motif"] == "Panne onduleur"
        assert t["contact_id"] == cid
        assert t["closed_at"] is None
        assert t["opened_by_id"]
        # Notification block always present (sent may be False if no template)
        assert "notification" in body
        assert "sent" in body["notification"]

    def test_motif_required(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        r = requests.post(
            f"{API}/me/contacts/{cid}/ticket",
            headers=admin_h, json={"client_id": target_client_id, "motif": ""},
            timeout=15,
        )
        assert r.status_code == 400
        assert "motif" in r.text.lower()

    def test_motif_max_length(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        r = requests.post(
            f"{API}/me/contacts/{cid}/ticket",
            headers=admin_h, json={"client_id": target_client_id, "motif": "x" * 201},
            timeout=15,
        )
        assert r.status_code == 400

    def test_blocks_when_open_ticket_exists(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        # 1st open
        r1 = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "Premier"}, timeout=15)
        assert r1.status_code == 200
        # 2nd should be blocked
        r2 = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "Second"}, timeout=15)
        assert r2.status_code == 409
        assert "encore ouvert" in r2.text

    def test_404_unknown_contact(self, admin_h, target_client_id):
        r = requests.post(f"{API}/me/contacts/__nope__/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "x"}, timeout=15)
        assert r.status_code == 404

    def test_sequence_increments(self, admin_h, db, admin_user, target_client_id):
        """Two contacts → two tickets, sequence increments monotonically."""
        scope = admin_user.get("client_id") or admin_user["id"]
        c_ids = []
        try:
            for i in range(2):
                cid = f"TEST_seq_{uuid.uuid4().hex[:8]}"
                db.contacts.insert_one({"id": cid, "client_id": scope, "name": f"Seq{i}", "whatsapp": "+22899880000", "created_at": datetime.now(timezone.utc).isoformat()})
                c_ids.append(cid)
            r1 = requests.post(f"{API}/me/contacts/{c_ids[0]}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "A"}, timeout=15)
            r2 = requests.post(f"{API}/me/contacts/{c_ids[1]}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "B"}, timeout=15)
            assert r1.status_code == 200 and r2.status_code == 200
            n1 = int(r1.json()["ticket"]["number"].rsplit("-", 1)[1])
            n2 = int(r2.json()["ticket"]["number"].rsplit("-", 1)[1])
            assert n2 == n1 + 1
        finally:
            for cid in c_ids:
                db.contacts.delete_one({"id": cid})
                db.support_tickets.delete_many({"contact_id": cid})


class TestTicketLifecycle:
    def test_patch_status_to_in_progress(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "Lifecycle"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        r2 = requests.patch(f"{API}/me/tickets/{tid}", headers=admin_h, json={"status": "in_progress"}, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["ticket"]["status"] == "in_progress"

    def test_patch_rejects_done_via_patch(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "x"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        r2 = requests.patch(f"{API}/me/tickets/{tid}", headers=admin_h, json={"status": "done"}, timeout=15)
        assert r2.status_code == 400

    def test_close_done_sets_closed_at_and_outcome(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "Close me"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        r2 = requests.post(f"{API}/me/tickets/{tid}/close", headers=admin_h, json={"outcome": "done", "resolution_note": "OK"}, timeout=15)
        assert r2.status_code == 200, r2.text
        t = r2.json()["ticket"]
        assert t["status"] == "done"
        assert t["outcome"] == "done"
        assert t["closed_at"]
        assert t["closed_by_id"]
        assert t["resolution_note"] == "OK"

    def test_can_reopen_via_new_ticket_after_closed(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        # Open + close
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "1st"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        requests.post(f"{API}/me/tickets/{tid}/close", headers=admin_h, json={"outcome": "cancelled"}, timeout=15)
        # New ticket allowed
        r3 = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "2nd"}, timeout=15)
        assert r3.status_code == 200
        # New number is sequential
        n1 = int(r.json()["ticket"]["number"].rsplit("-", 1)[1])
        n2 = int(r3.json()["ticket"]["number"].rsplit("-", 1)[1])
        assert n2 > n1

    def test_close_rejects_invalid_outcome(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "x"}, timeout=15)
        tid = r.json()["ticket"]["id"]
        r2 = requests.post(f"{API}/me/tickets/{tid}/close", headers=admin_h, json={"outcome": "lol"}, timeout=15)
        assert r2.status_code == 400


class TestTicketListing:
    def test_list_and_pending_count(self, admin_h, db, admin_user, target_client_id):
        scope = admin_user.get("client_id") or admin_user["id"]
        cid = f"TEST_list_{uuid.uuid4().hex[:8]}"
        db.contacts.insert_one({"id": cid, "client_id": scope, "name": "List", "whatsapp": "+22899887701", "created_at": datetime.now(timezone.utc).isoformat()})
        try:
            r = requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "ListMe"}, timeout=15)
            assert r.status_code == 200
            # List filtered by status=open
            r2 = requests.get(f"{API}/me/tickets?status=open", headers=admin_h, timeout=15)
            assert r2.status_code == 200
            assert any(t["contact_id"] == cid for t in r2.json())
            # pending-count returns >= 1
            r3 = requests.get(f"{API}/me/tickets/pending-count", headers=admin_h, timeout=15)
            assert r3.status_code == 200
            body = r3.json()
            assert body["count"] >= 1
            assert body["by_status"].get("open", 0) >= 1
        finally:
            db.contacts.delete_one({"id": cid})
            db.support_tickets.delete_many({"contact_id": cid})

    def test_active_ticket_endpoint(self, admin_h, test_contact, target_client_id):
        cid = test_contact["id"]
        # No ticket yet → active=False
        r0 = requests.get(f"{API}/me/contacts/{cid}/active-ticket", headers=admin_h, timeout=15)
        assert r0.status_code == 200
        assert r0.json()["active"] is False
        # Open one
        requests.post(f"{API}/me/contacts/{cid}/ticket", headers=admin_h, json={"client_id": target_client_id, "motif": "x"}, timeout=15)
        r1 = requests.get(f"{API}/me/contacts/{cid}/active-ticket", headers=admin_h, timeout=15)
        assert r1.status_code == 200
        body = r1.json()
        assert body["active"] is True
        assert body["ticket"]["status"] == "open"
