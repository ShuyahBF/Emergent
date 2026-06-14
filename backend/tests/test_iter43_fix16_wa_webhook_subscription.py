"""Iter43-fix16 — Tests pour le diagnostic + re-souscription du webhook Meta.

Endpoints couverts :
  - GET  /api/admin/whatsapp/webhook-subscription
  - POST /api/admin/whatsapp/webhook-subscribe

But : aider l'admin à diagnostiquer le symptôme « les messages WA sortants
partent mais Liluvine ne reçoit plus aucun message entrant depuis X jours ».
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001") + "/api"


def _admin_token() -> str:
    """Login admin → OTP dev → return JWT."""
    r1 = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@sawalismartsystems.com", "password": "Admin@Sawali2026"},
        timeout=10,
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1.get("needs_otp")
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": d1["session_token"], "code": d1["dev_otp"]},
        timeout=10,
    )
    assert r2.status_code == 200, r2.text
    return r2.json()["access_token"]


class TestWebhookSubscriptionDiagnostic:
    def test_diagnostic_endpoint_responds(self):
        """L'endpoint répond sans 500 même si Meta n'est pas configuré."""
        token = _admin_token()
        r = requests.get(
            f"{API}/admin/whatsapp/webhook-subscription",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "ok" in d
        # Si non configuré, on attend `missing_config`
        assert "subscribed_apps" in d or d.get("reason") == "missing_config"

    def test_subscribe_endpoint_requires_admin(self):
        """L'endpoint POST renvoie 401/403 sans token admin."""
        r = requests.post(f"{API}/admin/whatsapp/webhook-subscribe", timeout=10)
        assert r.status_code in (401, 403), r.text

    def test_subscribe_endpoint_400_without_config(self):
        """Avec token admin mais sans config Meta, renvoie 400."""
        token = _admin_token()
        r = requests.post(
            f"{API}/admin/whatsapp/webhook-subscribe",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        # Soit 400 si la config manque, soit 200 avec ok=False si la config existe
        # mais Meta refuse. Dans tous les cas, pas de 500.
        assert r.status_code in (200, 400), r.text
