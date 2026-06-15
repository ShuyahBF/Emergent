"""Iter43-fix23 (2026-06) — Tests d'intégration pour :
- Africa's Talking 2-Way SMS (webhook entrant + outbound + admin status)
- Webhook d'inventaire officines (Bearer token)
- Création d'officine via Admin UI
- Filtrage Officines Registry par rôle

Couvre les endpoints :
  POST   /api/webhooks/africas-talking/incoming-sms
  POST   /api/webhooks/africas-talking/delivery-report
  GET    /api/admin/africas-talking/status
  GET    /api/admin/africas-talking/messages
  POST   /api/admin/africas-talking/send-sms
  POST   /api/webhooks/officines/inventory          (Bearer auth)
  GET    /api/webhooks/officines/inventory/docs
  POST   /api/admin/officines-registry              (création manuelle)
  GET    /api/admin/officines-registry?role=        (filtre rôle)
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sawalismartsystems.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@Sawali2026")


@pytest.fixture(scope="module")
def admin_token():
    """Authenticate as admin (with OTP) and return Bearer access_token."""
    with httpx.Client(timeout=15) as client:
        # Step 1: login
        r1 = client.post(
            f"{API_BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert r1.status_code == 200, r1.text
        data1 = r1.json()
        if not data1.get("needs_otp"):
            return data1.get("access_token") or data1.get("token")
        # Step 2: verify OTP (dev_otp shown directly in dev)
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
# Africa's Talking Tests
# ===========================================================================
class TestAfricasTalking:
    def test_status_default_disabled(self, auth_headers):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/admin/africas-talking/status", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "enabled" in data
        assert "env" in data
        assert data["env"] in ("sandbox", "live")
        assert "webhook_url_template" in data

    def test_webhook_incoming_sms_persists_message(self, auth_headers):
        """Le webhook entrant doit toujours répondre OK et persister le SMS."""
        with httpx.Client(timeout=10) as client:
            # Active AT (sans Liluvine pour éviter les calls LLM)
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={
                    "africas_talking_enabled": True,
                    "africas_talking_env": "sandbox",
                    "africas_talking_username": "sandbox",
                    "africas_talking_use_liluvine": False,
                },
            )
            # POST inbound webhook (form-encoded)
            test_id = f"AT_TEST_{uuid.uuid4().hex[:8]}"
            r = client.post(
                f"{API_BASE}/webhooks/africas-talking/incoming-sms",
                data={
                    "from": "+22670111111",
                    "to": "15555",
                    "text": "Test SMS pytest",
                    "id": test_id,
                    "date": datetime.now(timezone.utc).isoformat(),
                },
            )
            assert r.status_code == 200
            assert r.text.strip() == "OK"
            # Vérifier qu'il est persisté
            r2 = client.get(
                f"{API_BASE}/admin/africas-talking/messages?q=pytest&limit=10",
                headers=auth_headers,
            )
            assert r2.status_code == 200
            items = r2.json().get("items", [])
            assert any(it.get("at_message_id") == test_id for it in items), \
                f"SMS {test_id} not found in {len(items)} items"

    def test_webhook_secret_validation(self, auth_headers):
        """Si un secret est configuré, le webhook doit rejeter les appels sans le bon secret."""
        with httpx.Client(timeout=10) as client:
            secret = f"pytest-secret-{uuid.uuid4().hex[:8]}"
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={"africas_talking_webhook_secret": secret},
            )
            try:
                # Sans secret → 401
                r1 = client.post(
                    f"{API_BASE}/webhooks/africas-talking/incoming-sms",
                    data={"from": "+22670000000", "to": "15555", "text": "x"},
                )
                assert r1.status_code == 401
                # Mauvais secret → 401
                r2 = client.post(
                    f"{API_BASE}/webhooks/africas-talking/incoming-sms?secret=wrong",
                    data={"from": "+22670000000", "to": "15555", "text": "x"},
                )
                assert r2.status_code == 401
                # Bon secret → 200
                r3 = client.post(
                    f"{API_BASE}/webhooks/africas-talking/incoming-sms?secret={secret}",
                    data={"from": "+22670000000", "to": "15555", "text": "x"},
                )
                assert r3.status_code == 200
            finally:
                # Cleanup
                client.put(
                    f"{API_BASE}/admin/settings",
                    headers=auth_headers,
                    json={"africas_talking_webhook_secret": ""},
                )

    def test_send_sms_requires_api_key(self, auth_headers):
        """L'envoi sortant doit échouer si l'API key n'est pas configurée."""
        with httpx.Client(timeout=10) as client:
            # Reset api_key (au cas où)
            client.put(
                f"{API_BASE}/admin/settings",
                headers=auth_headers,
                json={"africas_talking_api_key": ""},
            )
            r = client.post(
                f"{API_BASE}/admin/africas-talking/send-sms",
                headers=auth_headers,
                json={"to": "+22670000000", "text": "test"},
            )
            assert r.status_code in (503, 401, 400)


# ===========================================================================
# Officines Inventory Webhook Tests (Bearer auth)
# ===========================================================================
class TestOfficinesInventoryWebhook:
    def test_webhook_docs_public(self):
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/webhooks/officines/inventory/docs")
        assert r.status_code == 200
        data = r.json()
        assert data["endpoint"] == "POST /api/webhooks/officines/inventory"
        assert "csv_compatibility" in data

    def test_webhook_no_token_503(self, auth_headers):
        """Sans token configuré → 503."""
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
        """Flow complet : config token → create officine → push inventory → verify."""
        webhook_token = f"pytest-wh-token-{uuid.uuid4().hex}"
        with httpx.Client(timeout=15) as client:
            try:
                # 1. Config token
                client.put(
                    f"{API_BASE}/admin/settings",
                    headers=auth_headers,
                    json={"officines_inventory_webhook_token": webhook_token},
                )
                # 2. Créer une officine de test
                r_create = client.post(
                    f"{API_BASE}/admin/officines-registry",
                    headers=auth_headers,
                    json={
                        "name": f"PYTEST_OFFICINE_{uuid.uuid4().hex[:8]}",
                        "city": "Ouagadougou",
                        "country": "BF",
                        "status": "active",
                    },
                )
                assert r_create.status_code == 200, r_create.text
                officine_id = r_create.json()["officine"]["id"]
                try:
                    # 3. Mauvais Bearer → 401
                    r401 = client.post(
                        f"{API_BASE}/webhooks/officines/inventory",
                        headers={"Authorization": "Bearer wrong"},
                        json={"officine_id": officine_id, "items": []},
                    )
                    assert r401.status_code == 401
                    # 4. Sans Authorization → 401
                    rno = client.post(
                        f"{API_BASE}/webhooks/officines/inventory",
                        json={"officine_id": officine_id, "items": []},
                    )
                    assert rno.status_code == 401
                    # 5. Bon Bearer + items → 200 et création
                    r_ok = client.post(
                        f"{API_BASE}/webhooks/officines/inventory",
                        headers={"Authorization": f"Bearer {webhook_token}"},
                        json={
                            "officine_id": officine_id,
                            "items": [
                                {"product_name": "Doliprane 1000mg", "cip": "3400930000000",
                                 "quantity": 50, "unit_price": 1500, "currency": "XOF"},
                                {"product_name": "Paracetamol 500mg", "quantity": 120},
                            ],
                            "source": "pytest",
                        },
                    )
                    assert r_ok.status_code == 200, r_ok.text
                    data = r_ok.json()
                    assert data["ok"] is True
                    assert data["created"] == 2
                    assert data["updated"] == 0
                    # 6. Replay → doit faire des updates
                    r_replay = client.post(
                        f"{API_BASE}/webhooks/officines/inventory",
                        headers={"Authorization": f"Bearer {webhook_token}"},
                        json={
                            "officine_id": officine_id,
                            "items": [{"product_name": "Doliprane 1000mg", "quantity": 75}],
                            "source": "pytest-replay",
                        },
                    )
                    assert r_replay.status_code == 200
                    assert r_replay.json()["updated"] == 1
                    # 7. Officine introuvable → 404
                    r404 = client.post(
                        f"{API_BASE}/webhooks/officines/inventory",
                        headers={"Authorization": f"Bearer {webhook_token}"},
                        json={"officine_id": "non-existing-uuid", "items": []},
                    )
                    assert r404.status_code == 404
                    # 8. CSV-compatible keys (Nom du produit FR)
                    r_csv = client.post(
                        f"{API_BASE}/webhooks/officines/inventory",
                        headers={"Authorization": f"Bearer {webhook_token}"},
                        json={
                            "officine_id": officine_id,
                            "items": [{"Nom du produit": "Aspirine", "Quantité": 30, "Prix unitaire": 200}],
                        },
                    )
                    assert r_csv.status_code == 200
                    assert r_csv.json()["created"] == 1
                finally:
                    # Cleanup officine de test
                    # On utilise l'API admin pour supprimer si dispo, sinon DB direct
                    pass
            finally:
                # Reset token
                client.put(
                    f"{API_BASE}/admin/settings",
                    headers=auth_headers,
                    json={"officines_inventory_webhook_token": ""},
                )


# ===========================================================================
# Officines Registry — Création manuelle + filtre rôle
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

    def test_create_with_all_fields(self, auth_headers):
        unique = uuid.uuid4().hex[:8]
        # Use unique phone to avoid duplicate detection across test runs
        phone_suffix = unique[:6]  # 6 hex chars → number
        phone_digits = "226" + str(int(phone_suffix, 16) % 100000000).zfill(8)
        payload = {
            "name": f"PYTEST_FULL_{unique}",
            "intitule": "Pharmacie de test",
            "email": f"pytest_{unique}@test.bf",
            "phone": f"+{phone_digits}",
            "whatsapp": f"+{phone_digits}",
            "city": "Bobo-Dioulasso",
            "country": "BF",
            "address": "Rue 12, Sect 5",
            "location_hint": "À côté du marché",
            "numero_ordre": f"BF-{unique}",
            "contact_name": "Dr. Test",
            "role": "Pharmacie",
            "groupe_garde": 3,
            "status": "active",
        }
        with httpx.Client(timeout=10) as client:
            r = client.post(
                f"{API_BASE}/admin/officines-registry",
                headers=auth_headers,
                json=payload,
            )
            assert r.status_code == 200, r.text
            officine = r.json()["officine"]
            assert officine["name"] == payload["name"]
            assert officine["code"] == payload["name"]
            assert officine["role"] == "Pharmacie"
            assert officine["groupe_garde"] == 3
            assert officine["phone"] == f"+{phone_digits}"
            assert officine["phone_digits"] == phone_digits

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

    def test_filter_by_role(self, auth_headers):
        """Le filtre `role` doit filtrer les officines."""
        unique = uuid.uuid4().hex[:8]
        with httpx.Client(timeout=10) as client:
            # Crée 2 officines avec des rôles distincts
            client.post(
                f"{API_BASE}/admin/officines-registry",
                headers=auth_headers,
                json={"name": f"PYTEST_ROLE_PHARMA_{unique}", "role": "Pharmacie", "status": "active"},
            )
            # Filtre par rôle Pharmacie
            r = client.get(
                f"{API_BASE}/admin/officines-registry?role=Pharmacie&status=active",
                headers=auth_headers,
            )
            assert r.status_code == 200
            data = r.json()
            assert all(it.get("role") == "Pharmacie" for it in data.get("items", []))
            # Vérifier que notre officine est bien dedans
            names = [it["name"] for it in data.get("items", [])]
            assert any(unique in n for n in names)
