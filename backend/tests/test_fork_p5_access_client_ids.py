"""2026-02 fork (P5) — Listes d'accessibilité par tenant.

Couvre :
  • Formation : `access_client_ids=[tenant_A]` → tenant_A voit, tenant_B non
  • Document : idem
  • Formulaire (form) : idem
  • access_client_ids vide/manquant → visible par tous (comportement legacy)
  • Enroll refusé (403) pour tenant non autorisé
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


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def two_tenants(admin_token: str):
    """Deux tenants indépendants (A et B) + un utilisateur suivi par tenant."""
    tag = uuid.uuid4().hex[:8]

    def make_tenant(prefix: str):
        email = f"{prefix}-{tag}@sawali-test.com"
        pwd = "Tenant@2026"
        r = requests.post(
            f"{API}/admin/clients",
            headers=_auth(admin_token),
            json={
                "email": email,
                "password": pwd,
                "full_name": f"{prefix.upper()} Client {tag}",
                "role": "admin",
                "company": f"{prefix.upper()}-CO-{tag}",
            },
            timeout=10,
        )
        r.raise_for_status()
        tenant_id = r.json()["id"]
        # Create a tracked-user (suivi) directly bridged via set-password
        r2 = requests.post(
            f"{API}/admin/tracked-users",
            headers=_auth(admin_token),
            json={
                "client_id": tenant_id,
                "name": f"Suivi {prefix} {tag}",
                "email": f"suivi-{prefix}-{tag}@sawali-test.com",
                "role": "Consultation",
            },
            timeout=10,
        )
        r2.raise_for_status()
        tu_id = r2.json()["id"]
        r3 = requests.post(
            f"{API}/admin/tracked-users/{tu_id}/set-password",
            headers=_auth(admin_token),
            json={"password": "Suivi@2026"},
            timeout=10,
        )
        r3.raise_for_status()
        suivi_token = _login(f"suivi-{prefix}-{tag}@sawali-test.com", "Suivi@2026")
        return {"tenant_id": tenant_id, "tenant_token": _login(email, pwd), "suivi_token": suivi_token}

    return {"a": make_tenant("p5a"), "b": make_tenant("p5b"), "tag": tag}


def test_formation_access_gate_restricts_visibility(admin_token, two_tenants):
    """Formation avec access_client_ids=[A] → A voit, B ne voit pas."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    tag = two_tenants["tag"]

    # Create formation restricted to tenant A only
    r = requests.post(
        f"{API}/admin/formations",
        headers=_auth(admin_token),
        json={
            "name": f"Formation P5-restrict {tag}",
            "description": "Restreinte au tenant A",
            "available": True,
            "access": "free",
            "access_client_ids": [a["tenant_id"]],
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    fid = r.json()["id"]

    # Tenant A suivi → sees it
    la = requests.get(f"{API}/me/formations", headers=_auth(a["suivi_token"]), timeout=10)
    assert la.status_code == 200
    ids_a = [f["id"] for f in la.json()]
    assert fid in ids_a, "Tenant A doit voir sa formation autorisée"

    # Tenant B suivi → does NOT see it
    lb = requests.get(f"{API}/me/formations", headers=_auth(b["suivi_token"]), timeout=10)
    assert lb.status_code == 200
    ids_b = [f["id"] for f in lb.json()]
    assert fid not in ids_b, "Tenant B ne doit PAS voir la formation restreinte"

    # Tenant B suivi → GET single formation returns 403
    rb = requests.get(f"{API}/me/formations/{fid}", headers=_auth(b["suivi_token"]), timeout=10)
    assert rb.status_code == 403

    # Tenant B suivi → enroll fails 403
    eb = requests.post(f"{API}/me/formations/{fid}/enroll", headers=_auth(b["suivi_token"]), timeout=10)
    assert eb.status_code == 403


def test_formation_empty_list_visible_to_all(admin_token, two_tenants):
    """Formation sans access_client_ids → visible par les deux tenants."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    tag = two_tenants["tag"]

    r = requests.post(
        f"{API}/admin/formations",
        headers=_auth(admin_token),
        json={
            "name": f"Formation P5-open {tag}",
            "description": "Ouverte à tous",
            "available": True,
            "access": "free",
            "access_client_ids": [],
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    fid = r.json()["id"]

    la = requests.get(f"{API}/me/formations", headers=_auth(a["suivi_token"]), timeout=10)
    lb = requests.get(f"{API}/me/formations", headers=_auth(b["suivi_token"]), timeout=10)
    assert fid in [f["id"] for f in la.json()]
    assert fid in [f["id"] for f in lb.json()]


def test_document_access_gate_restricts_visibility(admin_token, two_tenants):
    """Document is_public=True MAIS access_client_ids=[A] → seul A le voit."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    tag = two_tenants["tag"]

    r = requests.post(
        f"{API}/admin/documents",
        headers=_auth(admin_token),
        json={
            "title": f"Doc P5-restrict {tag}",
            "category": "documentation",
            "is_public": True,  # normally visible everyone, but gated below
            "body_html": "<p>Content</p>",
            "access_client_ids": [a["tenant_id"]],
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    la = requests.get(f"{API}/me/documents", headers=_auth(a["suivi_token"]), timeout=10)
    lb = requests.get(f"{API}/me/documents", headers=_auth(b["suivi_token"]), timeout=10)
    assert la.status_code == 200 and lb.status_code == 200
    assert doc_id in [d["id"] for d in la.json()], "Tenant A doit voir le document restreint"
    assert doc_id not in [d["id"] for d in lb.json()], "Tenant B ne doit PAS voir le document restreint"


def test_form_access_gate_restricts_visibility(admin_token, two_tenants):
    """Formulaire is_public=True MAIS access_client_ids=[A] → seul A le voit
    dans la liste + 403 sur GET détail pour B."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    tag = two_tenants["tag"]

    # Admin creates a form scoped internally to admin, marked public + gated
    r = requests.post(
        f"{API}/me/forms",
        headers=_auth(admin_token),
        json={
            "title": f"Form P5-restrict {tag}",
            "description": "Restricted to A",
            "is_public": True,
            "access_client_ids": [a["tenant_id"]],
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    form_id = r.json()["id"]

    la = requests.get(f"{API}/me/forms", headers=_auth(a["suivi_token"]), timeout=10)
    lb = requests.get(f"{API}/me/forms", headers=_auth(b["suivi_token"]), timeout=10)
    assert la.status_code == 200 and lb.status_code == 200
    assert form_id in [f["id"] for f in la.json()], "Tenant A doit voir le formulaire restreint"
    assert form_id not in [f["id"] for f in lb.json()], "Tenant B ne doit PAS voir le formulaire restreint"

    # Direct GET on the form returns 403 for tenant B
    rb = requests.get(f"{API}/me/forms/{form_id}", headers=_auth(b["suivi_token"]), timeout=10)
    assert rb.status_code == 403


def test_admin_bypass_access_gate(admin_token, two_tenants):
    """Admin (super-admin) ne subit jamais le gate access_client_ids."""
    tag = two_tenants["tag"]
    a = two_tenants["a"]

    # Create a formation restricted to a fictional tenant that admin doesn't belong to
    fake_tenant = str(uuid.uuid4())
    r = requests.post(
        f"{API}/admin/formations",
        headers=_auth(admin_token),
        json={
            "name": f"Formation admin-bypass {tag}",
            "available": True,
            "access": "free",
            "access_client_ids": [fake_tenant],
        },
        timeout=10,
    )
    assert r.status_code == 200
    fid = r.json()["id"]

    # Admin lists all formations
    la = requests.get(f"{API}/admin/formations", headers=_auth(admin_token), timeout=10)
    assert la.status_code == 200
    ids = [f["id"] for f in la.json()]
    assert fid in ids, "Admin doit voir toutes les formations sans gate"

    # Suivi A does NOT see it
    lsa = requests.get(f"{API}/me/formations", headers=_auth(a["suivi_token"]), timeout=10)
    assert fid not in [f["id"] for f in lsa.json()], "Suivi A ne doit pas voir la formation restreinte à un autre tenant"
