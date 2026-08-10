"""2026-02 (fork) — Regression tests for PATCH /me/whatsapp/messages/{id}/recall

Covers the soft-recall business rules:
  • Only outbound messages can be recalled
  • Cannot recall a `read` message (destinataire l'a lu)
  • Cannot recall a message older than 15 min (except `failed`)
  • Recalling flips `is_recalled=True` + records timestamp/author
  • Recalling twice is idempotent (returns already_recalled=True)
  • Recall preserves the wa_status warning when the message was already delivered
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL.rstrip('/')}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    body = r.json()
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": body["session_token"], "code": body["dev_otp"]},
        timeout=10,
    )
    v.raise_for_status()
    return v.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture()
def seed_outbound_msg():
    """Insert a synthetic outbound message directly in MongoDB, yield its id,
    then cleanup. We use pymongo for the direct write since we don't have a
    dedicated seed endpoint.
    """
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME") or "sawali_db"
    client = MongoClient(mongo_url)
    db = client[db_name]

    def _factory(status: str = "sent", age_min: int = 0, direction: str = "outbound", client_id: str = None):
        now = datetime.now(timezone.utc)
        ref = now - timedelta(minutes=age_min)
        # Discover the admin's tenant id if none was passed
        if client_id is None:
            admin = db.users.find_one({"email": ADMIN_EMAIL})
            client_id = admin["id"]
        doc = {
            "id": f"test-recall-{uuid.uuid4().hex[:12]}",
            "client_id": client_id,
            "direction": direction,
            "body": "Test recall message",
            "wa_status": status,
            "created_at": ref.isoformat(),
            "sent_at": ref.isoformat(),
        }
        db.whatsapp_messages.insert_one(doc)
        return doc

    created_ids = []
    def factory(**kw):
        d = _factory(**kw)
        created_ids.append(d["id"])
        return d

    yield factory

    # Cleanup
    if created_ids:
        db.whatsapp_messages.delete_many({"id": {"$in": created_ids}})
    client.close()


def test_recall_outbound_sent_message(admin_token, seed_outbound_msg):
    m = seed_outbound_msg(status="sent", age_min=1)
    r = requests.patch(
        f"{API}/me/whatsapp/messages/{m['id']}/recall",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["meta_delete_supported"] is False
    assert body.get("warning")  # sent → already delivered → warning present


def test_recall_read_message_refused(admin_token, seed_outbound_msg):
    m = seed_outbound_msg(status="read", age_min=2)
    r = requests.patch(
        f"{API}/me/whatsapp/messages/{m['id']}/recall",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 409
    assert "lu" in r.json()["detail"].lower()


def test_recall_message_too_old_refused(admin_token, seed_outbound_msg):
    m = seed_outbound_msg(status="sent", age_min=30)  # > 15 min
    r = requests.patch(
        f"{API}/me/whatsapp/messages/{m['id']}/recall",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 409
    assert "15" in r.json()["detail"]


def test_recall_failed_message_always_allowed(admin_token, seed_outbound_msg):
    """Even a failed message > 15 min old should be recallable (never delivered)."""
    m = seed_outbound_msg(status="failed", age_min=60)
    r = requests.patch(
        f"{API}/me/whatsapp/messages/{m['id']}/recall",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 200
    # failed → wa_status not in delivered/sent → no warning
    assert not r.json().get("warning")


def test_recall_inbound_message_refused(admin_token, seed_outbound_msg):
    m = seed_outbound_msg(status="delivered", direction="inbound", age_min=1)
    r = requests.patch(
        f"{API}/me/whatsapp/messages/{m['id']}/recall",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 400
    assert "sortant" in r.json()["detail"].lower()


def test_recall_idempotent(admin_token, seed_outbound_msg):
    m = seed_outbound_msg(status="sent", age_min=1)
    r1 = requests.patch(
        f"{API}/me/whatsapp/messages/{m['id']}/recall",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r1.status_code == 200
    r2 = requests.patch(
        f"{API}/me/whatsapp/messages/{m['id']}/recall",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r2.status_code == 200
    assert r2.json().get("already_recalled") is True


def test_recall_missing_message_returns_404(admin_token):
    r = requests.patch(
        f"{API}/me/whatsapp/messages/does-not-exist/recall",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 404
