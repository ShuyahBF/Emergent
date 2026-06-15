"""Iter43-fix24b (2026-06) — Tests d'intégration : SMS Bird dans /portal/inbox

Couvre :
  - L'agrégation des SMS Bird dans GET /api/me/inbox/unified
  - Le détail d'un thread Bird via GET /api/me/inbox/unified/sms_bird/{thread_id}
  - L'envoi sortant via POST /api/me/inbox/send (channel="sms_bird")
"""
import os
import uuid

import httpx
import pytest

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sawalismartsystems.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@Sawali2026")


@pytest.fixture(scope="module")
def admin_token():
    with httpx.Client(timeout=15) as client:
        r1 = client.post(
            f"{API_BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert r1.status_code == 200
        data1 = r1.json()
        if not data1.get("needs_otp"):
            return data1.get("access_token") or data1.get("token")
        sess = data1["session_token"]
        otp = data1.get("dev_otp")
        r2 = client.post(
            f"{API_BASE}/auth/verify-otp",
            json={"session_token": sess, "code": otp},
        )
        assert r2.status_code == 200
        return r2.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


class TestInboxBirdAggregation:
    def test_inbox_includes_sms_bird_channel(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            # Enable Bird
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={"bird_enabled": True, "bird_use_liluvine": False, "bird_webhook_secret": ""},
            )
            # Push an inbound Bird SMS
            test_id = f"INBOX_BIRD_{uuid.uuid4().hex[:8]}"
            sender = f"+22670{uuid.uuid4().int % 1000000:06d}"
            payload = {
                "id": test_id,
                "direction": "inbound",
                "sender": {"phoneNumber": sender},
                "receiver": {"phoneNumber": "+22655000000"},
                "body": {"type": "text", "text": {"text": "Inbox pytest test SMS"}},
            }
            r_in = client.post(f"{API_BASE}/webhooks/bird/inbound-sms", json=payload)
            assert r_in.status_code == 200
            # Fetch inbox
            r = client.get(f"{API_BASE}/me/inbox/unified?limit=100", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            assert data["channels_enabled"]["sms_bird"] is True
            assert "sms_bird" in data["totals"]
            bird_threads = [t for t in data["items"] if t.get("channel") == "sms_bird"]
            assert any(sender in (t.get("peer_id") or "") for t in bird_threads), \
                f"Sender {sender} not found in Bird threads"

    def test_inbox_sms_bird_thread_messages(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            sender = f"+22670{uuid.uuid4().int % 1000000:06d}"
            # Push 2 inbound + simulate response via webhook
            for i in range(2):
                client.post(
                    f"{API_BASE}/webhooks/bird/inbound-sms",
                    json={
                        "id": f"PYT_MSGS_{uuid.uuid4().hex[:6]}",
                        "direction": "inbound",
                        "sender": {"phoneNumber": sender},
                        "receiver": {"phoneNumber": "+22655000000"},
                        "body": {"type": "text", "text": {"text": f"Message {i+1}"}},
                    },
                )
            # Retrieve thread messages
            r = client.get(
                f"{API_BASE}/me/inbox/unified/sms_bird/{sender}",
                headers=auth_headers,
            )
            assert r.status_code == 200
            data = r.json()
            assert data["channel"] == "sms_bird"
            assert data["thread_id"] == sender
            msgs = data["messages"]
            assert len(msgs) >= 2
            assert all(m.get("provider") == "bird" for m in msgs)

    def test_inbox_send_via_bird_fails_when_no_workspace(self, auth_headers):
        """Sans workspace_id / channel_id configurés, l'envoi via Bird doit échouer (503)."""
        with httpx.Client(timeout=10) as client:
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={"bird_workspace_id": "", "bird_channel_id": ""},
            )
            r = client.post(
                f"{API_BASE}/me/inbox/send",
                headers=auth_headers,
                json={"channel": "sms_bird", "thread_id": "+22670000000", "text": "test"},
            )
            # 503 (workspace non configuré) ou 502 (Bird API error)
            assert r.status_code in (503, 502)
