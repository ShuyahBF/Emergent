"""Bug #3 — rabo.f webhook hardening.

When a registered system user (moderator, admin, etc.) sends a WhatsApp
message inbound, the webhook must auto-create a `directory_contacts` row
in HER tenant scope so she appears in /portal/contacts with her real name.

Without this, system users land in `wa_pending_imports` and never appear
by name in the messaging center.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


def test_wa_webhook_auto_creates_contact_for_system_user(db_sync):
    """Posting an inbound WA payload with a phone matching a system user
    must auto-create a directory_contacts row in HER parent tenant scope
    with `name = full_name`."""
    suffix = uuid.uuid4().hex[:8]
    digits = "22890" + str(int(suffix, 16))[:6].rjust(6, "0")
    email = f"mod_{suffix}@example.com"
    parent_admin = db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    assert parent_admin, "Seed admin missing"
    mod_user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "full_name": "Mod Webhook Test",
        "role": "moderateur",
        "phone": f"+{digits}",
        "parent_client_id": parent_admin["id"],
        "client_id": parent_admin["id"],
        "company": "SAWALI",
        "account_status": "active",
    }
    db_sync.users.insert_one(mod_user)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "test_entry",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "22500000000", "phone_number_id": "999"},
                    "contacts": [{"profile": {"name": "Mod Webhook Test"}, "wa_id": digits}],
                    "messages": [{
                        "from": digits,
                        "id": f"wamid.MOD_{uuid.uuid4().hex[:12]}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": "Bonjour bug3"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    try:
        r = requests.post(f"{API}/whatsapp/webhook", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        # Give the async insert a moment to settle.
        time.sleep(0.4)
        contact = db_sync.directory_contacts.find_one(
            {"$or": [{"phone": {"$regex": digits}}, {"whatsapp": {"$regex": digits}}]},
            {"_id": 0, "client_id": 1, "name": 1, "wa_user_link": 1},
        )
        assert contact is not None, "directory_contacts row should have been auto-created"
        assert contact["client_id"] == parent_admin["id"], (
            "auto-created contact must live in the user's parent tenant scope"
        )
        assert contact["name"] == "Mod Webhook Test", (
            "auto-created contact must inherit the user's full_name"
        )
        assert contact.get("wa_user_link") == mod_user["id"]

        # The inbound message must reference this contact (no orphan).
        msg = db_sync.whatsapp_messages.find_one(
            {"phone_digits": digits, "direction": "inbound"},
            {"_id": 0, "contact_id": 1, "contact_name": 1, "client_id": 1},
        )
        assert msg is not None
        assert msg["client_id"] == parent_admin["id"]
        assert msg["contact_name"] == "Mod Webhook Test"

        # The message must NOT also land in wa_pending_imports.
        pending = db_sync.wa_pending_imports.find_one({"phone_digits": digits})
        assert pending is None, "system user must not show up as a pending import"
    finally:
        db_sync.users.delete_one({"id": mod_user["id"]})
        db_sync.directory_contacts.delete_many({
            "$or": [{"phone": {"$regex": digits}}, {"whatsapp": {"$regex": digits}}]
        })
        db_sync.whatsapp_messages.delete_many({"phone_digits": digits})
        db_sync.wa_pending_imports.delete_many({"phone_digits": digits})
