"""Iter43-fix24az-l retest (2026-02-26) — WhatsApp inbound deduplication.

Meta sometimes retries a webhook (network glitch or missing 200 ACK). Before
this fix, each retry created a NEW row in `db.whatsapp_messages` and
re-triggered Liluvine's AI auto-reply. The fix short-circuits the inbound
loop when a `wa_message_id` is already present in the collection.

Validates:
  1. First webhook call with a fresh `wa_message_id` → inserts a row.
  2. Same webhook call (same `wa_message_id`) → NO new row inserted.
  3. Different `wa_message_id` for the same phone → new row inserted.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
WEBHOOK_URL = f"{BASE_URL}/api/whatsapp/webhook"


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _make_meta_payload(wa_message_id: str, from_phone: str, body: str) -> dict:
    """Synthesize a valid Meta Cloud API inbound webhook payload."""
    ts = int(datetime.now(timezone.utc).timestamp())
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "_dedup_test_waba_",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "+22600000000",
                        "phone_number_id": "_dedup_test_pnid_",
                    },
                    "contacts": [{
                        "profile": {"name": "Dedup Fixture"},
                        "wa_id": from_phone,
                    }],
                    "messages": [{
                        "from": from_phone,
                        "id": wa_message_id,
                        "timestamp": str(ts),
                        "type": "text",
                        "text": {"body": body},
                    }],
                },
            }],
        }],
    }


def test_wa_inbound_dedup_single_write(db):
    """POSTing the SAME wa_message_id twice results in only ONE persisted row."""
    wa_msg_id = f"wamid.DEDUP_{uuid.uuid4().hex[:24]}"
    phone = "22690001122"
    payload = _make_meta_payload(wa_msg_id, phone, "Dedup regression #1")

    # First call — should insert
    r1 = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    assert r1.status_code == 200, r1.text

    # Second call — same id → should skip
    r2 = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    assert r2.status_code == 200, r2.text

    # DB should have exactly one row with this wa_message_id
    count = db.whatsapp_messages.count_documents({
        "wa_message_id": wa_msg_id,
        "direction": "inbound",
    })
    assert count == 1, f"Expected 1 inbound row for {wa_msg_id}, found {count}"

    # Cleanup
    db.whatsapp_messages.delete_many({"wa_message_id": wa_msg_id})


def test_wa_inbound_different_ids_both_written(db):
    """Two different wa_message_ids from the same phone → both persisted."""
    phone = "22690003344"
    id_a = f"wamid.DEDUP_A_{uuid.uuid4().hex[:24]}"
    id_b = f"wamid.DEDUP_B_{uuid.uuid4().hex[:24]}"

    r1 = requests.post(WEBHOOK_URL, json=_make_meta_payload(id_a, phone, "Msg A"), timeout=15)
    assert r1.status_code == 200, r1.text
    r2 = requests.post(WEBHOOK_URL, json=_make_meta_payload(id_b, phone, "Msg B"), timeout=15)
    assert r2.status_code == 200, r2.text

    assert db.whatsapp_messages.count_documents({"wa_message_id": id_a}) == 1
    assert db.whatsapp_messages.count_documents({"wa_message_id": id_b}) == 1

    # Cleanup
    db.whatsapp_messages.delete_many({"wa_message_id": {"$in": [id_a, id_b]}})


def test_wa_dedup_index_created(db):
    """Startup should have created the sparse index on wa_message_id."""
    idx_names = [ix["name"] for ix in db.whatsapp_messages.list_indexes()]
    assert "wa_message_id_sparse" in idx_names, (
        f"Missing sparse index on wa_message_id. Existing: {idx_names}"
    )
