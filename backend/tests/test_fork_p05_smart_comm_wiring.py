"""2026-02 fork (P0.5 sender wiring) — Per-tenant Smart Comm WA credentials.

Vérifie via HTTP + un endpoint de diagnostic que le resolver retourne bien les
credentials du tenant lorsqu'ils sont configurés, sinon retombe sur les
credentials globaux.
"""
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

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


def test_diag_resolver_global_when_no_tenant(admin_token):
    """No tenant → global source."""
    r = requests.get(
        f"{API}/admin/wa-credentials-resolver-diag",
        headers=_auth(admin_token),
        params={},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "global"
    assert body["tenant_id"] is None


def test_diag_resolver_tenant_configured(admin_token):
    """Configure a tenant Smart Comm → resolver picks tenant credentials."""
    tag = uuid.uuid4().hex[:6]
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={
            "email": f"p05-{tag}@sawali-test.com",
            "password": "P05@2026",
            "full_name": f"P05 tenant {tag}",
            "role": "admin",
            "company": f"P05-CO-{tag}",
        },
        timeout=10,
    )
    r.raise_for_status()
    tenant_id = r.json()["id"]
    tenant_tok = _login(f"p05-{tag}@sawali-test.com", "P05@2026")

    # Empty smart-comm → resolver still returns global
    r = requests.get(
        f"{API}/admin/wa-credentials-resolver-diag",
        headers=_auth(admin_token),
        params={"tenant_id": tenant_id},
        timeout=10,
    )
    assert r.status_code == 200 and r.json()["source"] == "global"

    # Configure tenant Smart Comm WA credentials
    r = requests.put(
        f"{API}/me/smart-communications",
        headers=_auth(tenant_tok),
        json={
            "wa_access_token": f"TOK_{tag}_ABC",
            "wa_phone_number_id": f"PHONE_{tag}_123",
        },
        timeout=10,
    )
    assert r.status_code == 200

    r = requests.get(
        f"{API}/admin/wa-credentials-resolver-diag",
        headers=_auth(admin_token),
        params={"tenant_id": tenant_id},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "tenant"
    assert body["tenant_id"] == tenant_id
    # Secrets not returned verbatim (only prefix/length)
    assert body["access_token_len"] == len(f"TOK_{tag}_ABC")
    assert body["phone_number_id"] == f"PHONE_{tag}_123"


def test_diag_denied_for_non_admin(admin_token):
    """Non-admin cannot use the resolver diag endpoint."""
    tag = uuid.uuid4().hex[:6]
    # Seed a plain user
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={
            "email": f"p05-nonadm-{tag}@sawali-test.com",
            "password": "NonAdm@2026",
            "full_name": f"NonAdmin {tag}",
            "role": "client",
        },
        timeout=10,
    )
    r.raise_for_status()
    tok = _login(f"p05-nonadm-{tag}@sawali-test.com", "NonAdm@2026")
    r = requests.get(
        f"{API}/admin/wa-credentials-resolver-diag",
        headers=_auth(tok),
        timeout=10,
    )
    assert r.status_code == 403
