"""2026-02 fork (P0) — KYC + Smart Communications par tenant.

Couvre :
  • GET/PUT /me/kyc round-trip
  • POST /me/kyc/upload/{doc_type} — valide type, taille (3 MB cap), remplit URL
  • GET /admin/kyc/{tenant_id} — super-admin uniquement
  • GET/PUT /me/smart-communications — secrets masqués en lecture
  • Empty PUT sur smart-comm = no-op idempotent
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
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def tenant_env(admin_token: str):
    """Create a fresh tenant admin so we don't mess with the SAWALI KYC."""
    tag = uuid.uuid4().hex[:8]
    email = f"kyctest-{tag}@sawali-test.com"
    password = "Kyc@2026"
    r = requests.post(
        f"{API}/admin/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": email,
            "password": password,
            "full_name": f"Tenant KYC {tag}",
            "role": "admin",
            "company": f"KYC-CO-{tag}",
        },
        timeout=10,
    )
    r.raise_for_status()
    tenant_id = r.json()["id"]
    token = _login(email, password)
    return {"tenant_id": tenant_id, "token": token, "tag": tag}


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_kyc_default_empty(tenant_env):
    r = requests.get(f"{API}/me/kyc", headers=_auth(tenant_env["token"]), timeout=10)
    assert r.status_code == 200
    b = r.json()
    assert b["tenant_id"] == tenant_env["tenant_id"]


def test_kyc_put_and_read(tenant_env):
    payload = {
        "business_name": f"SARL Test {tenant_env['tag']}",
        "ifu": "12345678901234",
        "rccm": f"BF-OUA-2026-{tenant_env['tag']}",
        "address": "Ouagadougou, Zone 1",
        "phone": "+22690000001",
        "bank_details": "IBAN BF00 0000 0000 0000",
    }
    r = requests.put(f"{API}/me/kyc", headers=_auth(tenant_env["token"]), json=payload, timeout=10)
    assert r.status_code == 200
    r = requests.get(f"{API}/me/kyc", headers=_auth(tenant_env["token"]), timeout=10)
    b = r.json()
    for k, v in payload.items():
        assert b[k] == v, f"KYC {k} not persisted: got {b.get(k)}"


def test_kyc_upload_id_photo(tenant_env):
    files = {"file": ("photo.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 2048), "image/jpeg")}
    r = requests.post(
        f"{API}/me/kyc/upload/id_photo",
        headers=_auth(tenant_env["token"]),
        files=files,
        timeout=15,
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["ok"] is True
    assert b["url"].startswith("/api/files/")
    # The KYC doc should now reflect id_photo_url
    r = requests.get(f"{API}/me/kyc", headers=_auth(tenant_env["token"]), timeout=10)
    assert r.json().get("id_photo_url") == b["url"]


def test_kyc_upload_invalid_doc_type(tenant_env):
    files = {"file": ("x.jpg", io.BytesIO(b"x"), "image/jpeg")}
    r = requests.post(
        f"{API}/me/kyc/upload/not_a_type",
        headers=_auth(tenant_env["token"]),
        files=files,
        timeout=10,
    )
    assert r.status_code == 400


def test_kyc_upload_oversized(tenant_env):
    big = b"\x00" * (4 * 1024 * 1024)  # 4 MB > 3 MB cap
    files = {"file": ("big.pdf", io.BytesIO(big), "application/pdf")}
    r = requests.post(
        f"{API}/me/kyc/upload/letterhead",
        headers=_auth(tenant_env["token"]),
        files=files,
        timeout=20,
    )
    assert r.status_code == 413


def test_admin_read_kyc_of_other_tenant(admin_token, tenant_env):
    r = requests.get(
        f"{API}/admin/kyc/{tenant_env['tenant_id']}",
        headers=_auth(admin_token),
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json().get("ifu") == "12345678901234"


def test_smart_comm_put_and_masked_read(tenant_env):
    payload = {
        "wa_waba_id": "555000111",
        "wa_phone_number_id": "999888777",
        "wa_access_token": "EAAsecrettoken12345",  # secret
        "meta_app_id": "12345",
    }
    r = requests.put(
        f"{API}/me/smart-communications",
        headers=_auth(tenant_env["token"]),
        json=payload,
        timeout=10,
    )
    assert r.status_code == 200
    r = requests.get(f"{API}/me/smart-communications", headers=_auth(tenant_env["token"]), timeout=10)
    b = r.json()
    # Non-secrets returned in cleartext
    assert b["wa_waba_id"] == "555000111"
    assert b["wa_phone_number_id"] == "999888777"
    assert b["meta_app_id"] == "12345"
    # Secret masked, cleartext blanked
    assert b["wa_access_token"] == ""
    assert b.get("wa_access_token_masked", "").endswith("2345")


def test_smart_comm_empty_put_is_noop(tenant_env):
    r = requests.put(
        f"{API}/me/smart-communications",
        headers=_auth(tenant_env["token"]),
        json={},
        timeout=10,
    )
    assert r.status_code == 200
    assert r.json().get("unchanged") is True
