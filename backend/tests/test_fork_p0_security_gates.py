"""2026-02 fork (iter95 SECURITY) — vérifie les gates de sécurité KYC/SmartComm.

  - Un tracked user regular (role=client) ne peut ni lire ni écrire /me/kyc
    ni /me/smart-communications (403).
  - Un tenant admin ordinaire NE PEUT PAS lire la KYC d'un autre tenant via
    /admin/kyc/{other} — seul le super-admin SAWALI peut.
"""
import io
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
    b = r.json()
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": b["session_token"], "code": b["dev_otp"]},
        timeout=10,
    )
    v.raise_for_status()
    return v.json()["access_token"]


@pytest.fixture(scope="module")
def sawali_admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def scenario(sawali_admin_token: str):
    """Two isolated tenants + one tracked user under tenant A."""
    tag = uuid.uuid4().hex[:8]
    hdr = {"Authorization": f"Bearer {sawali_admin_token}"}

    def create_client(suffix: str):
        email = f"sec-{suffix}-{tag}@sawali-test.com"
        r = requests.post(
            f"{API}/admin/clients",
            headers=hdr,
            json={
                "email": email,
                "password": "Sec@2026",
                "full_name": f"Sec {suffix}",
                "role": "admin",
                "company": f"SEC-{suffix}-{tag}",
            },
            timeout=10,
        )
        r.raise_for_status()
        return {"id": r.json()["id"], "email": email, "password": "Sec@2026"}

    tenant_a = create_client("A")
    tenant_b = create_client("B")

    # Create a tracked user under tenant A with tracked_role='Médecin'
    tu_email = f"tracked-{tag}@sawali-test.com"
    tu_password = "TrackedU@2026"
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=hdr,
        json={"email": tu_email, "name": f"TU {tag}", "role": "Médecin", "client_id": tenant_a["id"]},
        timeout=10,
    )
    r.raise_for_status()
    tu_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{tu_id}/set-password",
        headers=hdr,
        json={"password": tu_password},
        timeout=10,
    )
    r.raise_for_status()

    return {
        "tenant_a": {**tenant_a, "token": _login(tenant_a["email"], tenant_a["password"])},
        "tenant_b": {**tenant_b, "token": _login(tenant_b["email"], tenant_b["password"])},
        "tracked": {"email": tu_email, "password": tu_password, "token": _login(tu_email, tu_password)},
    }


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_tracked_user_cannot_read_kyc(scenario):
    r = requests.get(f"{API}/me/kyc", headers=_hdr(scenario["tracked"]["token"]), timeout=10)
    assert r.status_code == 403


def test_tracked_user_cannot_put_kyc(scenario):
    r = requests.put(
        f"{API}/me/kyc",
        headers=_hdr(scenario["tracked"]["token"]),
        json={"ifu": "1"},
        timeout=10,
    )
    assert r.status_code == 403


def test_tracked_user_cannot_upload_kyc(scenario):
    files = {"file": ("x.jpg", io.BytesIO(b"x"), "image/jpeg")}
    r = requests.post(
        f"{API}/me/kyc/upload/id_photo",
        headers=_hdr(scenario["tracked"]["token"]),
        files=files,
        timeout=10,
    )
    assert r.status_code == 403


def test_tracked_user_cannot_read_smart_comm(scenario):
    r = requests.get(
        f"{API}/me/smart-communications",
        headers=_hdr(scenario["tracked"]["token"]),
        timeout=10,
    )
    assert r.status_code == 403


def test_tracked_user_cannot_write_smart_comm(scenario):
    r = requests.put(
        f"{API}/me/smart-communications",
        headers=_hdr(scenario["tracked"]["token"]),
        json={"wa_waba_id": "leak"},
        timeout=10,
    )
    assert r.status_code == 403


def test_non_super_admin_cannot_read_other_tenant_kyc(scenario):
    """Tenant A admin should NOT be able to read Tenant B's KYC via /admin/kyc/{tenant_b_id}."""
    r = requests.get(
        f"{API}/admin/kyc/{scenario['tenant_b']['id']}",
        headers=_hdr(scenario["tenant_a"]["token"]),
        timeout=10,
    )
    assert r.status_code == 403


def test_super_admin_can_read_any_tenant_kyc(scenario, sawali_admin_token):
    """SAWALI super-admin can read any tenant's KYC (200 if exists, 404 if not)."""
    # Fabriquons d'abord une fiche KYC dans le tenant A pour avoir un 200
    requests.put(
        f"{API}/me/kyc",
        headers=_hdr(scenario["tenant_a"]["token"]),
        json={"ifu": "22334455"},
        timeout=10,
    )
    r = requests.get(
        f"{API}/admin/kyc/{scenario['tenant_a']['id']}",
        headers=_hdr(sawali_admin_token),
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json().get("ifu") == "22334455"
