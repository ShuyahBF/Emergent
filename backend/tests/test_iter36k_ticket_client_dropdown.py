"""Iter36k — Le client lié est désormais EXPLICITEMENT choisi via un
dropdown frontend. Le backend doit :
  - refuser (400) si client_id absent ou vide
  - refuser (403) si l'utilisateur n'a pas accès au client choisi
  - accepter (200) un client_id valide, même si != contact.client_id
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


@pytest.fixture
def fresh_contact(db, admin_user):
    """Crée un contact dans le scope admin avec un client_id différent
    pour démontrer que le ticket n'utilise PLUS le client_id du contact."""
    cid = f"TEST_iter36k_{uuid.uuid4().hex[:8]}"
    # Use admin's id so the contact is visible, but we'll force the ticket
    # to use admin_user["id"] explicitly via the payload (different from any
    # accidental fallback to contact.client_id).
    contact = {
        "id": cid,
        "client_id": admin_user.get("client_id") or admin_user["id"],
        "name": "Test Contact iter36k",
        "phone": "+22899771122",
        "whatsapp": "+22899771122",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.directory_contacts.insert_one(contact.copy())
    yield contact
    db.directory_contacts.delete_one({"id": cid})
    db.support_tickets.delete_many({"contact_id": cid})


class TestTicketClientDropdown:
    def test_client_id_required(self, admin_h, fresh_contact):
        """Sans client_id → 400."""
        r = requests.post(
            f"{API}/me/contacts/{fresh_contact['id']}/ticket",
            headers=admin_h,
            json={"motif": "Test sans client"},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "client lié" in r.text.lower() or "sélectionnez" in r.text.lower()

    def test_client_id_empty_rejected(self, admin_h, fresh_contact):
        r = requests.post(
            f"{API}/me/contacts/{fresh_contact['id']}/ticket",
            headers=admin_h,
            json={"motif": "Test client vide", "client_id": "   "},
            timeout=15,
        )
        assert r.status_code == 400

    def test_invalid_client_id_rejected(self, admin_h, fresh_contact):
        """client_id non existant en base → 403."""
        r = requests.post(
            f"{API}/me/contacts/{fresh_contact['id']}/ticket",
            headers=admin_h,
            json={"motif": "Test client bidon", "client_id": "nonexistent_xyz"},
            timeout=15,
        )
        assert r.status_code == 403, r.text

    def test_valid_client_id_creates_ticket(self, admin_h, fresh_contact, admin_user, db):
        """Admin peut choisir n'importe quel client portail valide. Le client_id
        finalement stocké dans le ticket est bien celui choisi via le dropdown,
        PAS un fallback automatique sur contact.client_id ou user.client_id."""
        # Find another distinct client in the DB (any role=client user)
        other = db.users.find_one(
            {"role": {"$in": ["client", "superviseur", "admin"]}, "id": {"$ne": admin_user["id"]}},
            {"_id": 0, "id": 1},
        )
        # Fallback to admin himself if no other client found
        valid_id = (other or admin_user)["id"]
        r = requests.post(
            f"{API}/me/contacts/{fresh_contact['id']}/ticket",
            headers=admin_h,
            json={"motif": "Avec dropdown", "client_id": valid_id},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        t = r.json()["ticket"]
        # Le ticket utilise le client_id CHOISI via le dropdown
        assert t["client_id"] == valid_id

    def test_motif_still_required(self, admin_h, fresh_contact, admin_user):
        r = requests.post(
            f"{API}/me/contacts/{fresh_contact['id']}/ticket",
            headers=admin_h,
            json={"motif": "", "client_id": admin_user["id"]},
            timeout=15,
        )
        assert r.status_code == 400
        assert "motif" in r.text.lower()
