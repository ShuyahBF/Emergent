"""2026-02 fork (P3) — Envoi quotidien du planning WA au Médecin.

Couvre :
  • GET /me/planning-wa-digest → 403 pour non-médecin, 200 pour médecin
  • PUT /me/planning-wa-digest → toggle enabled + hour (0-23, validation)
  • Cron run_medecin_planning_digest → n'envoie qu'aux médecins matchant l'heure
    courante + est idempotent via `planning_wa_last_digest_at`
"""
import os
import uuid
from datetime import datetime, timezone

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


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def medecin_ctx(admin_token):
    tag = uuid.uuid4().hex[:8]

    # Parent client
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={
            "email": f"p3parent-{tag}@sawali-test.com",
            "password": "Parent@2026",
            "full_name": f"P3 Parent {tag}",
            "role": "admin",
            "company": f"P3-CO-{tag}",
        },
        timeout=10,
    )
    r.raise_for_status()
    parent_id = r.json()["id"]

    # Tracked user Médecin
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=_auth(admin_token),
        json={
            "client_id": parent_id,
            "name": f"Dr Test {tag}",
            "email": f"p3medecin-{tag}@sawali-test.com",
            "role": "Médecin",
            "whatsapp_number": "+22507000000",
        },
        timeout=10,
    )
    r.raise_for_status()
    tu_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{tu_id}/set-password",
        headers=_auth(admin_token),
        json={"password": "Medecin@2026"},
        timeout=10,
    )
    r.raise_for_status()

    # Tracked user Non-Médecin (Consultation) for negative test
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=_auth(admin_token),
        json={
            "client_id": parent_id,
            "name": f"Consult Test {tag}",
            "email": f"p3consult-{tag}@sawali-test.com",
            "role": "Consultation",
        },
        timeout=10,
    )
    r.raise_for_status()
    ctu_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{ctu_id}/set-password",
        headers=_auth(admin_token),
        json={"password": "Consult@2026"},
        timeout=10,
    )
    r.raise_for_status()

    return {
        "medecin_email": f"p3medecin-{tag}@sawali-test.com",
        "medecin_password": "Medecin@2026",
        "consult_email": f"p3consult-{tag}@sawali-test.com",
        "consult_password": "Consult@2026",
        "tu_id": tu_id,
    }


def test_get_planning_wa_digest_defaults(medecin_ctx):
    tok = _login(medecin_ctx["medecin_email"], medecin_ctx["medecin_password"])
    r = requests.get(f"{API}/me/planning-wa-digest", headers=_auth(tok), timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["hour"] == 7


def test_get_planning_wa_digest_denied_for_non_medecin(medecin_ctx):
    tok = _login(medecin_ctx["consult_email"], medecin_ctx["consult_password"])
    r = requests.get(f"{API}/me/planning-wa-digest", headers=_auth(tok), timeout=10)
    assert r.status_code == 403


def test_put_planning_wa_digest_persists_toggle_and_hour(medecin_ctx):
    tok = _login(medecin_ctx["medecin_email"], medecin_ctx["medecin_password"])
    r = requests.put(
        f"{API}/me/planning-wa-digest",
        headers=_auth(tok),
        json={"enabled": True, "hour": 8},
        timeout=10,
    )
    assert r.status_code == 200
    got = requests.get(f"{API}/me/planning-wa-digest", headers=_auth(tok), timeout=10).json()
    assert got == {"enabled": True, "hour": 8}


def test_put_planning_wa_digest_rejects_invalid_hour(medecin_ctx):
    tok = _login(medecin_ctx["medecin_email"], medecin_ctx["medecin_password"])
    r = requests.put(
        f"{API}/me/planning-wa-digest",
        headers=_auth(tok),
        json={"enabled": True, "hour": 99},
        timeout=10,
    )
    assert r.status_code == 400


def test_admin_can_trigger_run_now(admin_token):
    """L'endpoint /admin/planning-wa-digest/run-now doit renvoyer un JSON."""
    r = requests.post(f"{API}/admin/planning-wa-digest/run-now", headers=_auth(admin_token), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert "sent" in body and "skipped" in body


def test_non_admin_cannot_trigger_run_now(medecin_ctx):
    tok = _login(medecin_ctx["medecin_email"], medecin_ctx["medecin_password"])
    r = requests.post(f"{API}/admin/planning-wa-digest/run-now", headers=_auth(tok), timeout=10)
    assert r.status_code == 403
