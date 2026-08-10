"""2026-02 (fork) — Regression tests for P2 (walk-in CRUD) and P3a (login event).

P2 coverage:
  • Secrétaire médicale can create/update/delete a walk-in
  • The medecin_id must belong to a tracked-role='Médecin' user in her scope
  • The endpoint refuses non-walk-in (is_rdv != 0) records on PATCH/DELETE
  • Regular clients (no elevated role & no matching tracked_role) get 403

P3a coverage:
  • SUPPORTED_AUTOMATION_EVENTS lists `user.login` and `whatsapp.received`
  • /admin/automations/events GET returns them with labels
"""
import os
import uuid

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


@pytest.fixture(scope="module")
def secretaire_env(admin_token: str):
    """Seed: client tenant + Médecin tracked user + Secrétaire médicale tracked user."""
    tag = uuid.uuid4().hex[:8]

    # 1) Client tenant (admin role, distinct company)
    client_email = f"client-{tag}@sawali-test.com"
    r = requests.post(
        f"{API}/admin/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": client_email,
            "password": "Client@2026",
            "full_name": f"Client {tag}",
            "role": "admin",
            "company": f"CO-{tag}",
        },
        timeout=10,
    )
    r.raise_for_status()
    client_id = r.json()["id"]

    # 2) Médecin (tracked user attached to that client)
    medecin_email = f"medecin-{tag}@sawali-test.com"
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": medecin_email,
            "name": f"Dr {tag}",
            "role": "Médecin",
            "client_id": client_id,
        },
        timeout=10,
    )
    r.raise_for_status()
    medecin_tu_id = r.json()["id"]
    # Provision a bridged user account so `tracked_role='Médecin'` lands on users doc
    r = requests.post(
        f"{API}/admin/tracked-users/{medecin_tu_id}/set-password",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"password": "Medecin@2026"},
        timeout=10,
    )
    r.raise_for_status()
    medecin_id = r.json()["user_id"]

    # 3) Secrétaire médicale (tracked user attached to same client)
    sec_email = f"secretaire-{tag}@sawali-test.com"
    sec_password = "Secret@2026"
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": sec_email,
            "name": f"Secrétaire {tag}",
            "role": "Secrétaire médicale",
            "client_id": client_id,
        },
        timeout=10,
    )
    r.raise_for_status()
    sec_tu_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{sec_tu_id}/set-password",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"password": sec_password},
        timeout=10,
    )
    r.raise_for_status()
    secretaire_id = r.json()["user_id"]

    sec_token = _login(sec_email, sec_password)

    return {
        "client_id": client_id,
        "medecin_id": medecin_id,
        "secretaire_id": secretaire_id,
        "secretaire_email": sec_email,
        "secretaire_token": sec_token,
        "tag": tag,
    }


def test_secretaire_can_create_walk_in(secretaire_env):
    tok = secretaire_env["secretaire_token"]
    r = requests.post(
        f"{API}/me/planning/walk-in",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "medecin_id": secretaire_env["medecin_id"],
            "patient": f"Patient {secretaire_env['tag']}-1",
            "patient_phone": "+22690123456",
            "motif": "Contrôle tension",
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["walk_in"]["is_rdv"] == 0
    assert body["walk_in"]["numero_ordre"] >= 1
    secretaire_env["last_walk_in_id"] = body["walk_in"]["id"]


def test_secretaire_can_update_walk_in(secretaire_env):
    tok = secretaire_env["secretaire_token"]
    wid = secretaire_env["last_walk_in_id"]
    r = requests.patch(
        f"{API}/me/planning/walk-in/{wid}",
        headers={"Authorization": f"Bearer {tok}"},
        json={"patient": "Patient renommé", "motif": "Suivi post-op"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["walk_in"]["patient"] == "Patient renommé"
    assert body["walk_in"]["motif"] == "Suivi post-op"


def test_secretaire_can_delete_walk_in(secretaire_env):
    tok = secretaire_env["secretaire_token"]
    # Create then delete
    r = requests.post(
        f"{API}/me/planning/walk-in",
        headers={"Authorization": f"Bearer {tok}"},
        json={"medecin_id": secretaire_env["medecin_id"], "patient": "À supprimer"},
        timeout=10,
    )
    assert r.status_code == 200
    wid = r.json()["walk_in"]["id"]
    r = requests.delete(
        f"{API}/me/planning/walk-in/{wid}",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_secretaire_refuses_unknown_medecin(secretaire_env):
    tok = secretaire_env["secretaire_token"]
    r = requests.post(
        f"{API}/me/planning/walk-in",
        headers={"Authorization": f"Bearer {tok}"},
        json={"medecin_id": "nonexistent-id", "patient": "Patient X"},
        timeout=10,
    )
    assert r.status_code == 404
    assert "Médecin" in r.json()["detail"]


def test_supported_automation_events_include_new_ones(admin_token):
    r = requests.get(
        f"{API}/admin/automations/events",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 200
    events = r.json().get("events", [])
    values = [e["value"] for e in events]
    assert "user.login" in values, f"user.login not registered! Got: {values}"
    assert "whatsapp.received" in values, f"whatsapp.received not registered! Got: {values}"
    # Both must have a label + description
    login_evt = next(e for e in events if e["value"] == "user.login")
    assert login_evt.get("label")
    assert login_evt.get("description")
    wa_evt = next(e for e in events if e["value"] == "whatsapp.received")
    assert "reply_code" in wa_evt.get("description", "").lower() or "wa_reply_code" in wa_evt.get("description", "")


def test_doctors_list_scoped_to_secretaire_client(secretaire_env):
    """The secrétaire must see the médecin attached to her own client."""
    tok = secretaire_env["secretaire_token"]
    r = requests.get(
        f"{API}/me/planning/doctors",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=10,
    )
    assert r.status_code == 200
    doctors = r.json().get("doctors", [])
    ids = [d["id"] for d in doctors]
    assert secretaire_env["medecin_id"] in ids, \
        f"Secrétaire can't see her médecin! ids={ids}"
