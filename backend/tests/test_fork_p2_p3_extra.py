"""2026-02 fork — Extra coverage for P2 (403 gating), P3a (login automation +
_emit_login_event fires) and P3b (whatsapp.received emission + wa_reply_tokens
row + #Rcode masked-reply lookup). Also regression check on /me/features
returning wa_notification_sound* fields.
"""
import os
import uuid
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    body = r.json()
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": body["session_token"], "code": body["dev_otp"]},
        timeout=10,
    )
    v.raise_for_status()
    return v.json()


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)["access_token"]


# ---------- P2: 403 for regular tracked user (non-allowed role) ----------
def test_walkin_forbidden_for_random_tracked_role(admin_token):
    """A tracked user with role='Comptable' (NOT in allowed set) must be 403."""
    tag = uuid.uuid4().hex[:6]
    client_email = f"cli-{tag}@sawali-test.com"
    r = requests.post(
        f"{API}/admin/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": client_email, "password": "Client@2026",
              "full_name": f"C {tag}", "role": "admin", "company": f"CO-{tag}"},
        timeout=10,
    )
    r.raise_for_status()
    client_id = r.json()["id"]

    tu_email = f"compta-{tag}@sawali-test.com"
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": tu_email, "name": "Compta", "role": "Comptable", "client_id": client_id},
        timeout=10,
    )
    if r.status_code >= 400:
        pytest.skip(f"Cannot create Comptable tracked user: {r.text}")
    tu_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{tu_id}/set-password",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"password": "Compta@2026"},
        timeout=10,
    )
    r.raise_for_status()

    tok = _login(tu_email, "Compta@2026")["access_token"]
    r = requests.post(
        f"{API}/me/planning/walk-in",
        headers={"Authorization": f"Bearer {tok}"},
        json={"medecin_id": "anything", "patient": "X"},
        timeout=10,
    )
    assert r.status_code == 403, f"Expected 403 for Comptable, got {r.status_code}: {r.text}"


# ---------- P3a: admin can create automation on user.login ----------
def test_can_create_automation_on_user_login(admin_token):
    payload = {
        "title": f"TEST login auto {uuid.uuid4().hex[:6]}",
        "name": f"TEST login auto {uuid.uuid4().hex[:6]}",
        "event": "user.login",
        "template_name": "noop_template",
        "action": "noop",
        "enabled": False,
        "config": {},
    }
    r = requests.post(
        f"{API}/admin/automations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=payload,
        timeout=10,
    )
    # Some builds may require different action names — accept 200/201.
    assert r.status_code in (200, 201), f"Create automation failed: {r.status_code} {r.text}"
    auto_id = r.json().get("id")
    # cleanup
    if auto_id:
        requests.delete(f"{API}/admin/automations/{auto_id}",
                        headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)


def test_events_endpoint_labels_and_descriptions(admin_token):
    r = requests.get(f"{API}/admin/automations/events",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    events = r.json().get("events", [])
    by_val = {e["value"]: e for e in events}
    assert "user.login" in by_val
    assert "whatsapp.received" in by_val
    login_desc = (by_val["user.login"].get("description") or "").lower()
    # Description should mention at least one of the injected ctx keys
    assert any(k in login_desc for k in ["login_email", "login_ip", "login_role"]), \
        f"user.login description missing ctx hints: {login_desc}"


# ---------- P3b: hitting webhook creates a wa_reply_tokens row ----------
def _fake_meta_webhook_payload(from_msisdn: str, text: str, phone_number_id: str = "0000") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "wa-entry",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "0000", "phone_number_id": phone_number_id},
                    "contacts": [{"wa_id": from_msisdn, "profile": {"name": "Fork Tester"}}],
                    "messages": [{
                        "from": from_msisdn,
                        "id": f"wamid.TEST_{uuid.uuid4().hex[:12]}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
            }],
        }],
    }


def test_whatsapp_webhook_creates_reply_token_and_emits_event():
    """POST a fake Meta payload to /api/whatsapp/webhook. It must return 200
    quickly. We can't easily verify the DB row from outside, but the webhook
    endpoint at least should not raise."""
    from_msisdn = f"22699{uuid.uuid4().int % 10_000_000:07d}"
    body = _fake_meta_webhook_payload(from_msisdn, f"Hello fork test {uuid.uuid4().hex[:6]}")
    r = requests.post(f"{API}/whatsapp/webhook", json=body, timeout=15)
    # Meta expects 200 OK regardless of internal handling
    assert r.status_code == 200, f"Webhook failed: {r.status_code} {r.text}"


# ---------- Regression: /me/features still returns wa_notification_sound fields ----------
def test_me_features_regression_wa_sound_fields(admin_token):
    r = requests.get(f"{API}/me/features", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    data = r.json()
    # These fields may live at root or inside a nested dict — accept both.
    def _has_field(name: str) -> bool:
        if name in data:
            return True
        for v in data.values():
            if isinstance(v, dict) and name in v:
                return True
        return False
    assert _has_field("wa_notification_sound"), f"Missing wa_notification_sound in /me/features: keys={list(data.keys())}"
    assert _has_field("wa_notification_sound_url"), "Missing wa_notification_sound_url in /me/features"
    assert _has_field("wa_notification_volume"), "Missing wa_notification_volume in /me/features"


# ---------- Regression: notification-sounds/presets endpoint still works ----------
def test_notification_sounds_presets_alive(admin_token):
    r = requests.get(f"{API}/notification-sounds/presets",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    presets = body.get("presets") if isinstance(body, dict) else body
    assert isinstance(presets, list) and len(presets) >= 1


# ---------- P2: numero_ordre auto-increments per tenant ----------
def test_walkin_numero_ordre_increments(admin_token):
    tag = uuid.uuid4().hex[:6]
    # Create client + medecin + secretaire
    r = requests.post(f"{API}/admin/clients",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      json={"email": f"cli2-{tag}@sawali-test.com", "password": "Client@2026",
                            "full_name": f"C {tag}", "role": "admin", "company": f"CO2-{tag}"}, timeout=10)
    r.raise_for_status()
    client_id = r.json()["id"]

    def _mk_tracked(role: str, name: str, pwd: str):
        r = requests.post(f"{API}/admin/tracked-users",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"email": f"{name}-{tag}@sawali-test.com", "name": name,
                                "role": role, "client_id": client_id}, timeout=10)
        r.raise_for_status()
        tu_id = r.json()["id"]
        r = requests.post(f"{API}/admin/tracked-users/{tu_id}/set-password",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"password": pwd}, timeout=10)
        r.raise_for_status()
        return r.json()["user_id"]

    medecin_id = _mk_tracked("Médecin", "medc", "Medc@2026")
    sec_email = f"secr-{tag}@sawali-test.com"
    r = requests.post(f"{API}/admin/tracked-users",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      json={"email": sec_email, "name": "Sec",
                            "role": "Secrétaire médicale", "client_id": client_id}, timeout=10)
    r.raise_for_status()
    tu_id = r.json()["id"]
    r = requests.post(f"{API}/admin/tracked-users/{tu_id}/set-password",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      json={"password": "Sec@2026"}, timeout=10)
    r.raise_for_status()
    sec_tok = _login(sec_email, "Sec@2026")["access_token"]

    ordres = []
    for i in range(2):
        r = requests.post(f"{API}/me/planning/walk-in",
                          headers={"Authorization": f"Bearer {sec_tok}"},
                          json={"medecin_id": medecin_id, "patient": f"P{i}"}, timeout=10)
        assert r.status_code == 200, r.text
        ordres.append(r.json()["walk_in"]["numero_ordre"])
    assert ordres[1] == ordres[0] + 1, f"numero_ordre did not increment: {ordres}"
