"""2026-02 (fork P5) — Superviseur (tracked-role) must see all doctors of the
same client via /me/planning/doctors.

Seed scenario:
  1) client_id=CLI-A, role='admin', company='ISISPHARMA'
  2) Tracked user role='Superviseur' bridged under CLI-A
  3) Tracked user role='Médecin' bridged under CLI-A
  4) Another unrelated Médecin under a DIFFERENT client CLI-B (should NOT
     appear in superviseur's doctors list).
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
def superviseur_scenario(admin_token: str):
    tag = uuid.uuid4().hex[:8]
    hdr = {"Authorization": f"Bearer {admin_token}"}

    def _create_client(company_suffix: str):
        email = f"client-{company_suffix}-{tag}@sawali-test.com"
        r = requests.post(
            f"{API}/admin/clients",
            headers=hdr,
            json={
                "email": email,
                "password": "Client@2026",
                "full_name": f"Client {company_suffix}",
                "role": "admin",
                "company": f"{company_suffix}-{tag}",
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["id"]

    def _create_tracked(email: str, role: str, client_id: str, password: str):
        r = requests.post(
            f"{API}/admin/tracked-users",
            headers=hdr,
            json={"email": email, "name": email.split("@")[0], "role": role, "client_id": client_id},
            timeout=10,
        )
        r.raise_for_status()
        tu_id = r.json()["id"]
        r = requests.post(
            f"{API}/admin/tracked-users/{tu_id}/set-password",
            headers=hdr,
            json={"password": password},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["user_id"]

    cli_a = _create_client("ISISA")
    cli_b = _create_client("OTHERCO")

    medecin_a = _create_tracked(f"med-a-{tag}@sawali-test.com", "Médecin", cli_a, "Med@2026")
    medecin_b = _create_tracked(f"med-b-{tag}@sawali-test.com", "Médecin", cli_b, "Med@2026")

    sup_email = f"sup-{tag}@sawali-test.com"
    sup_password = "Sup@2026"
    _create_tracked(sup_email, "Superviseur", cli_a, sup_password)

    sup_token = _login(sup_email, sup_password)
    return {
        "sup_token": sup_token,
        "medecin_a": medecin_a,
        "medecin_b": medecin_b,
        "cli_a": cli_a,
        "cli_b": cli_b,
    }


def test_superviseur_sees_doctors_of_same_client(superviseur_scenario):
    r = requests.get(
        f"{API}/me/planning/doctors",
        headers={"Authorization": f"Bearer {superviseur_scenario['sup_token']}"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    ids = [d["id"] for d in r.json().get("doctors", [])]
    assert superviseur_scenario["medecin_a"] in ids, \
        f"Superviseur cannot see medecin_a of the same client! ids={ids}"


def test_superviseur_does_not_see_doctors_of_other_client(superviseur_scenario):
    r = requests.get(
        f"{API}/me/planning/doctors",
        headers={"Authorization": f"Bearer {superviseur_scenario['sup_token']}"},
        timeout=10,
    )
    assert r.status_code == 200
    ids = [d["id"] for d in r.json().get("doctors", [])]
    assert superviseur_scenario["medecin_b"] not in ids, \
        f"Superviseur leaks other-tenant medecin! ids={ids}"
