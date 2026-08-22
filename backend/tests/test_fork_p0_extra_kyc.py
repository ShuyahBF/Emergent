"""2026-02 fork (P0) — EXTRA coverage (testing agent, iter95).

Covers what test_fork_p0_tenant_kyc.py does not:
  • PDF upload accepted + /api/files/{id} actually serves the bytes
  • bad extension -> 400 ; bad MIME (text/plain w/ .pdf name) -> 400
  • letterhead / id_card doc types fill their own *_url field
  • GET /admin/kyc/{unknown} -> 404 ; non-admin caller -> 401/403
  • GET /me/smart-communications never leaks ANY secret in cleartext
  • tracked (regular) user access surface on /me/kyc + /me/smart-communications
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

SECRET_FIELDS = [
    "wa_access_token", "wa_verify_token",
    "meta_app_secret", "meta_page_access_token",
    "instagram_access_token",
    "x_api_secret", "x_access_secret",
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


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def tenant(admin_token):
    tag = uuid.uuid4().hex[:8]
    email = f"kycx-{tag}@sawali-test.com"
    password = "Kyc@2026"
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={"email": email, "password": password, "full_name": f"KYCX {tag}",
              "role": "admin", "company": f"KYCX-CO-{tag}"},
        timeout=15,
    )
    r.raise_for_status()
    return {"id": r.json()["id"], "token": _login(email, password), "tag": tag, "email": email}


@pytest.fixture(scope="module")
def tracked_user(admin_token, tenant):
    """Regular tracked user attached to the fresh tenant."""
    tag = uuid.uuid4().hex[:6]
    email = f"kycx-tr-{tag}@sawali-test.com"
    password = "Tracked@2026"
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=_auth(tenant["token"]),
        json={"client_id": tenant["id"], "name": f"Tracked {tag}", "email": email,
              "role": "Médecin"},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        pytest.skip(f"tracked-user creation unavailable: {r.status_code} {r.text[:200]}")
    uid = r.json().get("id") or r.json().get("user", {}).get("id")
    sp = requests.post(
        f"{API}/admin/tracked-users/{uid}/set-password",
        headers=_auth(tenant["token"]),
        json={"password": password},
        timeout=15,
    )
    if sp.status_code not in (200, 204):
        pytest.skip(f"set-password unavailable: {sp.status_code} {sp.text[:200]}")
    return {"id": uid, "email": email, "token": _login(email, password)}


# ---------------- uploads ----------------

def test_upload_pdf_letterhead_and_serve(tenant):
    pdf = b"%PDF-1.4\n%fake\n" + b"0" * 1024 + b"\n%%EOF"
    r = requests.post(
        f"{API}/me/kyc/upload/letterhead",
        headers=_auth(tenant["token"]),
        files={"file": ("entete.pdf", io.BytesIO(pdf), "application/pdf")},
        timeout=25,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_type"] == "letterhead"
    assert body["size"] == len(pdf)

    # /api/files/{id} must serve the file
    served = requests.get(f"{BASE_URL.rstrip('/')}{body['url']}", timeout=25)
    assert served.status_code == 200, f"{served.status_code} {served.text[:200]}"
    assert served.content.startswith(b"%PDF"), served.headers.get("content-type")

    # KYC record reflects letterhead_url
    kyc = requests.get(f"{API}/me/kyc", headers=_auth(tenant["token"]), timeout=15).json()
    assert kyc.get("letterhead_url") == body["url"]


def test_upload_id_card_png(tenant):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 512
    r = requests.post(
        f"{API}/me/kyc/upload/id_card",
        headers=_auth(tenant["token"]),
        files={"file": ("cni.png", io.BytesIO(png), "image/png")},
        timeout=25,
    )
    assert r.status_code == 200, r.text
    kyc = requests.get(f"{API}/me/kyc", headers=_auth(tenant["token"]), timeout=15).json()
    assert kyc.get("id_card_url") == r.json()["url"]


def test_upload_bad_extension_rejected(tenant):
    r = requests.post(
        f"{API}/me/kyc/upload/id_card",
        headers=_auth(tenant["token"]),
        files={"file": ("virus.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        timeout=15,
    )
    assert r.status_code == 400, r.text


def test_upload_bad_mime_rejected(tenant):
    r = requests.post(
        f"{API}/me/kyc/upload/letterhead",
        headers=_auth(tenant["token"]),
        files={"file": ("doc.pdf", io.BytesIO(b"plain text"), "text/plain")},
        timeout=15,
    )
    assert r.status_code == 400, r.text


def test_upload_requires_auth(tenant):
    r = requests.post(
        f"{API}/me/kyc/upload/id_photo",
        files={"file": ("p.jpg", io.BytesIO(b"\xff\xd8\xff"), "image/jpeg")},
        timeout=15,
    )
    assert r.status_code in (401, 403), r.status_code


# ---------------- admin read ----------------

def test_admin_kyc_unknown_tenant_404(admin_token):
    r = requests.get(f"{API}/admin/kyc/does-not-exist-{uuid.uuid4().hex}",
                     headers=_auth(admin_token), timeout=15)
    assert r.status_code == 404, r.text


def test_tenant_admin_cannot_read_other_tenant_kyc(tenant, admin_token):
    """A tenant-level admin must NOT be able to read another tenant's KYC.
    /admin/kyc/{tenant_id} only uses get_current_admin (role=admin passes)."""
    # super-admin tenant id
    me = requests.get(f"{API}/auth/me", headers=_auth(admin_token), timeout=15).json()
    super_tid = me.get("parent_client_id") or me.get("client_id") or me.get("id")
    # seed a KYC for the super-admin tenant so the record exists
    requests.put(f"{API}/me/kyc", headers=_auth(admin_token),
                 json={"ifu": "SUPER-ADMIN-IFU-DONOTLEAK"}, timeout=15)
    r = requests.get(f"{API}/admin/kyc/{super_tid}", headers=_auth(tenant["token"]), timeout=15)
    assert r.status_code in (401, 403), (
        f"CROSS-TENANT LEAK: tenant admin read another tenant's KYC "
        f"({r.status_code}) {r.text[:200]}"
    )


def test_admin_kyc_requires_auth():
    r = requests.get(f"{API}/admin/kyc/whatever", timeout=15)
    assert r.status_code in (401, 403), r.status_code


# ---------------- smart communications ----------------

def test_smart_comm_all_secrets_masked(tenant):
    payload = {f: f"SECRET-{f}-{uuid.uuid4().hex[:8]}" for f in SECRET_FIELDS}
    payload.update({"x_api_key": "XKEY123", "linkedin_organization_id": "ORG999"})
    r = requests.put(f"{API}/me/smart-communications", headers=_auth(tenant["token"]),
                     json=payload, timeout=20)
    assert r.status_code == 200, r.text

    g = requests.get(f"{API}/me/smart-communications", headers=_auth(tenant["token"]), timeout=20)
    assert g.status_code == 200
    body = g.json()
    raw = g.text
    for f in SECRET_FIELDS:
        assert body.get(f) == "", f"{f} not blanked: {body.get(f)!r}"
        assert body.get(f"{f}_masked"), f"{f}_masked missing"
        assert payload[f] not in raw, f"CLEARTEXT LEAK of {f}"
    # non secrets still readable
    assert body["x_api_key"] == "XKEY123"
    assert body["linkedin_organization_id"] == "ORG999"


def test_smart_comm_partial_update_preserves_others(tenant):
    r = requests.put(f"{API}/me/smart-communications", headers=_auth(tenant["token"]),
                     json={"tiktok_client_id": "TT-999"}, timeout=20)
    assert r.status_code == 200
    assert r.json().get("updated") == ["tiktok_client_id"] or "tiktok_client_id" in r.json().get("updated", [])
    body = requests.get(f"{API}/me/smart-communications", headers=_auth(tenant["token"]), timeout=20).json()
    assert body["tiktok_client_id"] == "TT-999"
    assert body["x_api_key"] == "XKEY123"  # untouched


def test_smart_comm_requires_auth():
    assert requests.get(f"{API}/me/smart-communications", timeout=15).status_code in (401, 403)


# ---------------- tracked user surface ----------------

def test_tracked_user_cannot_write_smart_comm(tracked_user):
    r = requests.put(f"{API}/me/smart-communications", headers=_auth(tracked_user["token"]),
                     json={"wa_access_token": "HIJACKED-BY-TRACKED-USER"}, timeout=15)
    assert r.status_code == 403, (
        f"Tracked (regular) user overwrote the tenant WA credentials: "
        f"{r.status_code} {r.text[:200]}"
    )


def test_tracked_user_kyc_access_surface(tracked_user, tenant):
    """UI hides the sections for tracked users; document the API surface."""
    g = requests.get(f"{API}/me/kyc", headers=_auth(tracked_user["token"]), timeout=15)
    assert g.status_code in (200, 403), g.text
    if g.status_code == 200:
        # Tracked user resolves to the parent tenant -> can READ the tenant KYC
        assert g.json().get("tenant_id") == tenant["id"]

    p = requests.put(f"{API}/me/kyc", headers=_auth(tracked_user["token"]),
                     json={"ifu": "TRACKED-WRITE-TEST"}, timeout=15)
    # The UI hides the section for tracked users; the API should also refuse the write.
    assert p.status_code == 403, (
        f"Tracked (regular) user was able to WRITE the tenant KYC: "
        f"{p.status_code} {p.text[:200]}"
    )

    s = requests.get(f"{API}/me/smart-communications", headers=_auth(tracked_user["token"]), timeout=15)
    assert s.status_code in (200, 403)
    if s.status_code == 200:
        for f in SECRET_FIELDS:
            assert s.json().get(f, "") == "", f"tracked user sees cleartext {f}"
