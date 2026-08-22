"""iter96 P0 RETEST — edge cases around the 3 security fixes (tenant KYC / Smart-Comm).

Covers:
  * tracked_role='Superviseur'  -> MUST be allowed (200) on /me/kyc + /me/smart-communications
  * tracked_role='Médecin'      -> 403 on every KYC/SmartComm endpoint (incl. GET smart-comm)
  * non-super-admin admin      -> 403 on /admin/kyc/{any tenant} (even its own id)
  * super-admin                -> 200/404 on /admin/kyc/{tenant}
  * secrets never returned in cleartext for a legit tenant manager
"""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL.rstrip('/')}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

SECRET_FIELDS = [
    "wa_access_token", "wa_verify_token", "meta_app_secret", "meta_page_access_token",
    "instagram_access_token", "x_api_secret", "x_access_secret",
    "tiktok_client_secret", "tiktok_access_token",
    "linkedin_client_secret", "linkedin_access_token",
]


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    b = r.json()
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": b["session_token"], "code": b["dev_otp"]},
        timeout=15,
    )
    v.raise_for_status()
    return v.json()["access_token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def super_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def env(super_token):
    tag = uuid.uuid4().hex[:8]
    hdr = _hdr(super_token)
    email = f"i96-adm-{tag}@sawali-test.com"
    r = requests.post(f"{API}/admin/clients", headers=hdr, json={
        "email": email, "password": "Sec@2026", "full_name": f"I96 {tag}",
        "role": "admin", "company": f"I96-{tag}",
    }, timeout=15)
    r.raise_for_status()
    tenant_id = r.json()["id"]

    def mk_tracked(role_label, slug):
        tu_email = f"i96-{slug}-{tag}@sawali-test.com"
        rr = requests.post(f"{API}/admin/tracked-users", headers=hdr, json={
            "email": tu_email, "name": f"{role_label} {tag}",
            "role": role_label, "client_id": tenant_id,
        }, timeout=15)
        rr.raise_for_status()
        tu_id = rr.json()["id"]
        requests.post(f"{API}/admin/tracked-users/{tu_id}/set-password", headers=hdr,
                      json={"password": "Tracked@2026"}, timeout=15).raise_for_status()
        return _login(tu_email, "Tracked@2026")

    return {
        "tenant_id": tenant_id,
        "admin_token": _login(email, "Sec@2026"),
        "sup_token": mk_tracked("Superviseur", "sup"),
        "med_token": mk_tracked("Médecin", "med"),
    }


# ---- tracked_role='Superviseur' is a tenant manager -> allowed
def test_tracked_superviseur_can_read_kyc(env):
    r = requests.get(f"{API}/me/kyc", headers=_hdr(env["sup_token"]), timeout=15)
    assert r.status_code == 200, r.text
    assert "tenant_id" in r.json()


def test_tracked_superviseur_can_write_kyc(env):
    r = requests.put(f"{API}/me/kyc", headers=_hdr(env["sup_token"]),
                     json={"ifu": "TEST_I96_SUP"}, timeout=15)
    assert r.status_code == 200, r.text
    g = requests.get(f"{API}/me/kyc", headers=_hdr(env["sup_token"]), timeout=15)
    assert g.json().get("ifu") == "TEST_I96_SUP"


def test_tracked_superviseur_can_read_smart_comm(env):
    r = requests.get(f"{API}/me/smart-communications", headers=_hdr(env["sup_token"]), timeout=15)
    assert r.status_code == 200, r.text


# ---- tracked regular (Médecin) is blocked everywhere
@pytest.mark.parametrize("method,path,kwargs", [
    ("get", "/me/kyc", {}),
    ("put", "/me/kyc", {"json": {"ifu": "HACK"}}),
    ("get", "/me/smart-communications", {}),
    ("put", "/me/smart-communications", {"json": {"wa_access_token": "HACK"}}),
    ("post", "/me/kyc/upload/id_card", {"files": {"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}}),
])
def test_tracked_medecin_forbidden(env, method, path, kwargs):
    r = getattr(requests, method)(f"{API}{path}", headers=_hdr(env["med_token"]), timeout=20, **kwargs)
    assert r.status_code == 403, f"{method.upper()} {path} -> {r.status_code} {r.text[:200]}"


def test_tracked_medecin_write_did_not_persist(env):
    """After the blocked PUT above, the tenant's KYC must still hold the Superviseur value."""
    g = requests.get(f"{API}/me/kyc", headers=_hdr(env["admin_token"]), timeout=15)
    assert g.status_code == 200
    assert g.json().get("ifu") != "HACK"


# ---- /admin/kyc is super-admin only
def test_tenant_admin_forbidden_on_admin_kyc_own_tenant(env):
    r = requests.get(f"{API}/admin/kyc/{env['tenant_id']}", headers=_hdr(env["admin_token"]), timeout=15)
    assert r.status_code == 403, r.text


def test_tracked_medecin_forbidden_on_admin_kyc(env):
    r = requests.get(f"{API}/admin/kyc/{env['tenant_id']}", headers=_hdr(env["med_token"]), timeout=15)
    assert r.status_code in (401, 403), r.text


def test_super_admin_reads_tenant_kyc(env, super_token):
    r = requests.get(f"{API}/admin/kyc/{env['tenant_id']}", headers=_hdr(super_token), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("ifu") == "TEST_I96_SUP"


def test_super_admin_unknown_tenant_404(super_token):
    r = requests.get(f"{API}/admin/kyc/does-not-exist-{uuid.uuid4().hex}",
                     headers=_hdr(super_token), timeout=15)
    assert r.status_code == 404


def test_unauthenticated_blocked(env):
    for m, p in [("get", "/me/kyc"), ("get", "/me/smart-communications"),
                 ("get", f"/admin/kyc/{env['tenant_id']}")]:
        r = getattr(requests, m)(f"{API}{p}", timeout=15)
        assert r.status_code in (401, 403), f"{p} -> {r.status_code}"


# ---- masking still holds for a legit tenant manager
def test_secrets_masked_for_tenant_manager(env):
    payload = {f: f"TEST_SECRET_{f}_1234" for f in SECRET_FIELDS}
    r = requests.put(f"{API}/me/smart-communications", headers=_hdr(env["admin_token"]),
                     json=payload, timeout=20)
    assert r.status_code == 200, r.text
    g = requests.get(f"{API}/me/smart-communications", headers=_hdr(env["admin_token"]), timeout=15)
    assert g.status_code == 200
    body = g.json()
    raw = g.text
    for f in SECRET_FIELDS:
        assert body.get(f) == "", f"{f} returned cleartext: {body.get(f)}"
        assert body.get(f"{f}_masked"), f"{f}_masked missing"
    assert "TEST_SECRET_wa_access_token_1234" not in raw
