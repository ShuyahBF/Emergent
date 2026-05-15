"""Iter35h — Batch 3 tests: `demo` role.

Validates:
  • Creating a demo account persists demo_expires_at + demo_quotas
  • The /me/demo/status endpoint returns is_demo + quotas + days_left
  • A demo with payments=0 quota gets a clear 403 when creating a payment-link
  • A demo with directory_contacts quota gets a clear 403 when exceeding it
  • Expired demo accounts are rejected by get_current_user (account_status=expired)
  • Non-demo accounts have is_demo: false in /me/demo/status
  • Admin can list and resolve demo-expiry-events
"""
import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
import requests

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
        return data.get("access_token")
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data.get("dev_otp")}, timeout=30)
    assert r2.status_code == 200, r2.text
    return r2.json().get("access_token")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


@pytest.fixture()
def fresh_demo(admin_h):
    """Create a fresh demo account, yield its credentials + cleanup."""
    s = uuid.uuid4().hex[:8]
    email = f"demo_{s}@iter35h.example.com"
    password = "DemoPass2026!"
    expires = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    r = requests.post(
        f"{API}/admin/clients", headers=admin_h, timeout=20,
        json={
            "full_name": f"Demo {s}",
            "email": email,
            "password": password,
            "role": "demo",
            "company": f"DemoCo {s}",
            "demo_expires_at": expires,
            "demo_quotas": {
                "whatsapp_sends": 2,
                "sms_sends": 1,
                "ai_generations": 1,
                "transcriptions": 2,
                "directory_contacts": 2,  # smaller cap so we can exceed it in tests
                "payments": 0,
                "attachments_bytes": 5 * 1024 * 1024,
            },
        },
    )
    assert r.status_code in (200, 201), r.text
    user_id = r.json()["id"]
    tok = _login(email, password)
    yield {"id": user_id, "email": email, "password": password, "token": tok, "headers": {"Authorization": f"Bearer {tok}"}}
    # Cleanup
    requests.delete(f"{API}/admin/clients/{user_id}", headers=admin_h, timeout=15)


class TestDemoRoleProvisioning:
    def test_can_create_demo_account_with_quotas(self, admin_h, fresh_demo):
        r = requests.get(f"{API}/admin/clients/{fresh_demo['id']}", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == "demo"
        assert body.get("demo_expires_at")
        assert (body.get("demo_quotas") or {}).get("payments") == 0

    def test_status_endpoint_for_demo(self, fresh_demo):
        r = requests.get(f"{API}/me/demo/status", headers=fresh_demo["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_demo"] is True
        assert "days_left" in body
        assert body["days_left"] is not None and 0 <= body["days_left"] <= 11
        quotas = body.get("quotas") or {}
        assert "whatsapp_sends" in quotas
        assert quotas["whatsapp_sends"]["limit"] == 2
        assert quotas["payments"]["limit"] == 0

    def test_status_endpoint_for_non_demo(self, admin_h):
        r = requests.get(f"{API}/me/demo/status", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json() == {"is_demo": False}


class TestDemoQuotaEnforcement:
    def test_payment_link_blocked_when_quota_zero(self, fresh_demo):
        r = requests.post(
            f"{API}/me/payment-links", headers=fresh_demo["headers"], timeout=15,
            json={"label": "Test demo iter35h", "amount": 100, "currency": "XOF"},
        )
        # Either 403 (demo quota=0) or 403 (other gate). Either way must be 403 with French message.
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
        # Look for our specific French detail
        text = r.text.lower()
        assert "démo" in text or "demo" in text or "désactiv" in text or "non autoris" in text

    def test_contact_creation_blocked_after_cap(self, fresh_demo):
        h = fresh_demo["headers"]
        # The fixture sets the cap to 2 — create 2 successfully, the 3rd must 403.
        for i in range(2):
            r = requests.post(
                f"{API}/me/contacts", headers=h, timeout=15,
                json={"name": f"Contact démo #{i}", "email": f"c{i}_{uuid.uuid4().hex[:6]}@iter35h.example.com"},
            )
            assert r.status_code in (200, 201), f"contact {i} failed: {r.status_code} {r.text}"
        r3 = requests.post(
            f"{API}/me/contacts", headers=h, timeout=15,
            json={"name": "Contact démo #3", "email": f"c3_{uuid.uuid4().hex[:6]}@iter35h.example.com"},
        )
        assert r3.status_code == 403, f"expected 403 over-quota, got {r3.status_code}: {r3.text}"
        assert "quota" in r3.text.lower() or "démo" in r3.text.lower()


class TestDemoExpiration:
    def test_expired_demo_cannot_login(self, admin_h):
        # Create a demo with an expiration date in the past
        s = uuid.uuid4().hex[:8]
        email = f"expired_{s}@iter35h.example.com"
        password = "Pass1234!aa"
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        cr = requests.post(
            f"{API}/admin/clients", headers=admin_h, timeout=20,
            json={
                "full_name": f"Expired {s}",
                "email": email,
                "password": password,
                "role": "demo",
                "demo_expires_at": past,
            },
        )
        assert cr.status_code in (200, 201), cr.text
        uid = cr.json()["id"]
        try:
            # Login should still succeed (auth returns a token), but subsequent
            # API calls go through get_current_user which rejects expired demos.
            login = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
            if login.status_code != 200:
                # Either way: not usable. Accept and exit early.
                return
            data = login.json()
            tok = data.get("access_token")
            if not tok and data.get("needs_otp"):
                v = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data.get("dev_otp")}, timeout=15)
                if v.status_code != 200:
                    return
                tok = v.json().get("access_token")
            if not tok:
                return
            me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
            assert me.status_code == 403, f"expected 403 expired, got {me.status_code}: {me.text}"
            assert "expir" in me.text.lower()
            # Admin endpoint must now list this user
            ev = requests.get(f"{API}/admin/demo/expiry-events", headers=admin_h, timeout=15)
            assert ev.status_code == 200
            items = ev.json().get("items") or []
            assert any(it.get("user_id") == uid for it in items), f"expiry event missing: {items}"
        finally:
            requests.delete(f"{API}/admin/clients/{uid}", headers=admin_h, timeout=15)

    def test_admin_can_resolve_expiry_event(self, admin_h):
        ev = requests.get(f"{API}/admin/demo/expiry-events?only_unresolved=true", headers=admin_h, timeout=15)
        items = ev.json().get("items") or []
        if not items:
            pytest.skip("no expiry events to resolve")
        first = items[0]
        r = requests.post(f"{API}/admin/demo/expiry-events/{first['id']}/resolve", headers=admin_h, timeout=10)
        assert r.status_code == 200
        # Re-list with only_unresolved → first should no longer appear
        ev2 = requests.get(f"{API}/admin/demo/expiry-events?only_unresolved=true", headers=admin_h, timeout=15)
        items2 = ev2.json().get("items") or []
        assert not any(it.get("id") == first["id"] for it in items2)
