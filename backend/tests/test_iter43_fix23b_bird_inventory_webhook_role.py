"""Iter43-fix23b (2026-06) — Tests d'intégration pour Bird.com 2-Way SMS
(remplace l'intégration Africa's Talking).

Couvre les endpoints :
  POST   /api/webhooks/bird/inbound-sms             (HMAC SHA-256 sig)
  POST   /api/webhooks/bird/delivery-report
  GET    /api/admin/bird/status
  GET    /api/admin/bird/messages
  POST   /api/admin/bird/send-sms

Couvre aussi (depuis fix23 original) :
  POST   /api/webhooks/officines/inventory          (Bearer auth)
  GET    /api/webhooks/officines/inventory/docs
  POST   /api/admin/officines-registry              (création manuelle)
  GET    /api/admin/officines-registry?role=        (filtre rôle)
"""
import hashlib
import hmac
import json
import os
import uuid

import httpx
import pytest

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sawalismartsystems.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@Sawali2026")


@pytest.fixture(scope="module")
def admin_token():
    """Authenticate as admin (with OTP) and return Bearer access_token."""
    with httpx.Client(timeout=15) as client:
        r1 = client.post(
            f"{API_BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert r1.status_code == 200, r1.text
        data1 = r1.json()
        if not data1.get("needs_otp"):
            return data1.get("access_token") or data1.get("token")
        sess = data1["session_token"]
        otp = data1.get("dev_otp")
        assert otp, "dev_otp missing in dev environment"
        r2 = client.post(
            f"{API_BASE}/auth/verify-otp",
            json={"session_token": sess, "code": otp},
        )
        assert r2.status_code == 200, r2.text
        return r2.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ===========================================================================
# Bird SMS Tests
# ===========================================================================
class TestBirdSms:
    def test_status_default(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/admin/bird/status", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "enabled" in data
        assert "api_base_url" in data
        assert data["api_base_url"].startswith("https://")
        assert "webhook_url_template" in data
        assert "/webhooks/bird/inbound-sms" in data["webhook_url_template"]

    def test_webhook_inbound_sms_persists(self, auth_headers):
        """Le webhook entrant doit retourner OK et persister le SMS."""
        with httpx.Client(timeout=10) as client:
            # Reset secret to disable signature check
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={
                    "bird_enabled": True,
                    "bird_use_liluvine": False,
                    "bird_webhook_secret": "",
                },
            )
            test_id = f"BIRD_TEST_{uuid.uuid4().hex[:8]}"
            payload = {
                "id": test_id,
                "direction": "inbound",
                "sender": {"phoneNumber": "+22670111111"},
                "receiver": {"phoneNumber": "+22655000000"},
                "body": {"type": "text", "text": {"text": "Bonjour Liluvine pytest"}},
            }
            r = client.post(
                f"{API_BASE}/webhooks/bird/inbound-sms",
                json=payload,
            )
            assert r.status_code == 200, r.text
            assert r.json().get("status") == "ok"
            # Verify persisted
            r2 = client.get(
                f"{API_BASE}/admin/bird/messages?q=pytest&limit=10",
                headers=auth_headers,
            )
            assert r2.status_code == 200
            items = r2.json().get("items", [])
            assert any(it.get("provider_message_id") == test_id for it in items), \
                f"SMS {test_id} not found"

    def test_webhook_signature_verification(self, auth_headers):
        """Si bird_webhook_secret configuré, le webhook vérifie HMAC SHA-256."""
        secret = f"pytest-bird-secret-{uuid.uuid4().hex[:8]}"
        with httpx.Client(timeout=10) as client:
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={"bird_webhook_secret": secret, "bird_enabled": True, "bird_use_liluvine": False},
            )
            try:
                test_id = f"BIRD_SIG_{uuid.uuid4().hex[:6]}"
                payload = {
                    "id": test_id,
                    "sender": {"phoneNumber": "+22670222222"},
                    "receiver": {"phoneNumber": "+22655000000"},
                    "body": {"type": "text", "text": {"text": "sig test"}},
                }
                body_bytes = json.dumps(payload).encode("utf-8")
                good_sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
                # 1. Sans signature → 401
                r_no = client.post(
                    f"{API_BASE}/webhooks/bird/inbound-sms",
                    content=body_bytes,
                    headers={"Content-Type": "application/json"},
                )
                assert r_no.status_code == 401
                # 2. Mauvaise signature → 401
                r_bad = client.post(
                    f"{API_BASE}/webhooks/bird/inbound-sms",
                    content=body_bytes,
                    headers={"Content-Type": "application/json", "Bird-Signature": "wrong"},
                )
                assert r_bad.status_code == 401
                # 3. Bonne signature → 200
                r_ok = client.post(
                    f"{API_BASE}/webhooks/bird/inbound-sms",
                    content=body_bytes,
                    headers={"Content-Type": "application/json", "Bird-Signature": good_sig},
                )
                assert r_ok.status_code == 200, r_ok.text
            finally:
                client.put(
                    f"{API_BASE}/admin/settings",
                    headers=auth_headers,
                    json={"bird_webhook_secret": ""},
                )

    def test_send_sms_requires_config(self, auth_headers):
        """L'envoi sortant échoue si access_key non configurée."""
        with httpx.Client(timeout=10) as client:
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={"bird_access_key": "", "bird_workspace_id": "", "bird_channel_id": ""},
            )
            r = client.post(
                f"{API_BASE}/admin/bird/send-sms",
                headers=auth_headers,
                json={"to": "+22670000000", "text": "test"},
            )
            assert r.status_code == 503

    def test_idempotent_duplicate_webhook(self, auth_headers):
        """Un même provider_message_id ne doit pas être persisté 2 fois."""
        with httpx.Client(timeout=10) as client:
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={"bird_enabled": True, "bird_use_liluvine": False, "bird_webhook_secret": ""},
            )
            dup_id = f"BIRD_DUP_{uuid.uuid4().hex[:8]}"
            payload = {
                "id": dup_id,
                "sender": {"phoneNumber": "+22670333333"},
                "receiver": {"phoneNumber": "+22655000000"},
                "body": {"type": "text", "text": {"text": "dedup"}},
            }
            r1 = client.post(f"{API_BASE}/webhooks/bird/inbound-sms", json=payload)
            assert r1.status_code == 200
            assert not r1.json().get("duplicate")
            r2 = client.post(f"{API_BASE}/webhooks/bird/inbound-sms", json=payload)
            assert r2.status_code == 200
            assert r2.json().get("duplicate") is True


# ===========================================================================
# Officines Inventory Webhook Tests (Bearer auth) — inchangé depuis fix23
# ===========================================================================
class TestOfficinesInventoryWebhook:
    def test_webhook_docs_public(self):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/webhooks/officines/inventory/docs")
        assert r.status_code == 200
        data = r.json()
        assert data["endpoint"] == "POST /api/webhooks/officines/inventory"

    def test_webhook_no_token_503(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={"officines_inventory_webhook_token": ""},
            )
            r = client.post(
                f"{API_BASE}/webhooks/officines/inventory",
                json={"officine_id": "fake", "items": []},
            )
            assert r.status_code == 503

    def test_webhook_full_flow(self, auth_headers):
        webhook_token = f"pytest-wh-token-{uuid.uuid4().hex}"
        with httpx.Client(timeout=15) as client:
            try:
                client.put(
                    f"{API_BASE}/admin/settings",
                    headers=auth_headers,
                    json={"officines_inventory_webhook_token": webhook_token},
                )
                r_create = client.post(
                    f"{API_BASE}/admin/officines-registry",
                    headers=auth_headers,
                    json={"name": f"PYTEST_INV_{uuid.uuid4().hex[:8]}", "status": "active"},
                )
                assert r_create.status_code == 200, r_create.text
                officine_id = r_create.json()["officine"]["id"]
                # Bad token → 401
                r401 = client.post(
                    f"{API_BASE}/webhooks/officines/inventory",
                    headers={"Authorization": "Bearer wrong"},
                    json={"officine_id": officine_id, "items": []},
                )
                assert r401.status_code == 401
                # Good token + items → 200, created=2
                r_ok = client.post(
                    f"{API_BASE}/webhooks/officines/inventory",
                    headers={"Authorization": f"Bearer {webhook_token}"},
                    json={
                        "officine_id": officine_id,
                        "items": [
                            {"product_name": "Doliprane 1000mg", "quantity": 50, "unit_price": 1500},
                            {"product_name": "Paracetamol 500mg", "quantity": 120},
                        ],
                    },
                )
                assert r_ok.status_code == 200, r_ok.text
                assert r_ok.json()["created"] == 2
                # Replay → updated=1
                r_replay = client.post(
                    f"{API_BASE}/webhooks/officines/inventory",
                    headers={"Authorization": f"Bearer {webhook_token}"},
                    json={
                        "officine_id": officine_id,
                        "items": [{"product_name": "Doliprane 1000mg", "quantity": 75}],
                    },
                )
                assert r_replay.json()["updated"] == 1
            finally:
                client.put(
                    f"{API_BASE}/admin/settings",
                    headers=auth_headers,
                    json={"officines_inventory_webhook_token": ""},
                )


# ===========================================================================
# Officines Registry — Création manuelle + filtre rôle (inchangé)
# ===========================================================================
class TestOfficinesRegistryCreateAndRoleFilter:
    def test_create_requires_name(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            r = client.post(
                f"{API_BASE}/admin/officines-registry",
                headers=auth_headers,
                json={"name": ""},
            )
            assert r.status_code == 400

    def test_create_with_role_and_filter(self, auth_headers):
        unique = uuid.uuid4().hex[:8]
        phone_suffix = unique[:6]
        phone_digits = "226" + str(int(phone_suffix, 16) % 100000000).zfill(8)
        with httpx.Client(timeout=10) as client:
            r = client.post(
                f"{API_BASE}/admin/officines-registry",
                headers=auth_headers,
                json={
                    "name": f"PYTEST_ROLE_{unique}",
                    "phone": f"+{phone_digits}",
                    "role": "Pharmacie",
                    "groupe_garde": 3,
                    "status": "active",
                },
            )
            assert r.status_code == 200, r.text
            assert r.json()["officine"]["role"] == "Pharmacie"
            # Filter
            rf = client.get(
                f"{API_BASE}/admin/officines-registry?role=Pharmacie&status=active",
                headers=auth_headers,
            )
            assert rf.status_code == 200
            items = rf.json().get("items", [])
            assert all(it.get("role") == "Pharmacie" for it in items)

    def test_create_duplicate_blocked(self, auth_headers):
        unique = uuid.uuid4().hex[:8]
        name = f"PYTEST_DUP_{unique}"
        with httpx.Client(timeout=10) as client:
            r1 = client.post(
                f"{API_BASE}/admin/officines-registry",
                headers=auth_headers,
                json={"name": name},
            )
            assert r1.status_code == 200
            r2 = client.post(
                f"{API_BASE}/admin/officines-registry",
                headers=auth_headers,
                json={"name": name},
            )
            assert r2.status_code == 409
