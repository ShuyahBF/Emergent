"""2026-02 fork (P4) — Overrides per-tracked-user pour la visibilité :
  - Tableau de bord (show_dashboard)
  - Modale de bienvenue (show_welcome_modal)
  - Notifications du Centre de Messagerie (show_messaging_notifs)

Ces flags sont settables via PUT /admin/tracked-users/{tu_id}. Ils sont
propagés au compte bridged (users) lors du set-password + à chaque update.
Le endpoint /auth/me les remonte via UserPublic.
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
def tenant_and_tracked(admin_token):
    tag = uuid.uuid4().hex[:8]
    # Create parent client
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={
            "email": f"p4parent-{tag}@sawali-test.com",
            "password": "Parent@2026",
            "full_name": f"P4 Parent {tag}",
            "role": "admin",
            "company": f"P4-CO-{tag}",
        },
        timeout=10,
    )
    r.raise_for_status()
    parent_id = r.json()["id"]

    # Create tracked user
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=_auth(admin_token),
        json={
            "client_id": parent_id,
            "name": f"P4 Consultation {tag}",
            "email": f"p4consult-{tag}@sawali-test.com",
            "role": "Consultation",
        },
        timeout=10,
    )
    r.raise_for_status()
    tu_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{tu_id}/set-password",
        headers=_auth(admin_token),
        json={"password": "Consult@2026"},
        timeout=10,
    )
    r.raise_for_status()
    return {"parent_id": parent_id, "tu_id": tu_id, "email": f"p4consult-{tag}@sawali-test.com", "password": "Consult@2026"}


def test_default_overrides_are_null(tenant_and_tracked):
    tok = _login(tenant_and_tracked["email"], tenant_and_tracked["password"])
    r = requests.get(f"{API}/auth/me", headers=_auth(tok), timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["show_dashboard"] is None
    assert body["show_welcome_modal"] is None
    assert body["show_messaging_notifs"] is None


def test_admin_can_set_and_reset_p4_toggles(admin_token, tenant_and_tracked):
    tu_id = tenant_and_tracked["tu_id"]

    # 1) Force show_dashboard=False, show_welcome_modal=True
    r = requests.put(
        f"{API}/admin/tracked-users/{tu_id}",
        headers=_auth(admin_token),
        json={"show_dashboard": False, "show_welcome_modal": True, "show_messaging_notifs": False},
        timeout=10,
    )
    assert r.status_code == 200

    # Login again to refresh JWT payload
    tok = _login(tenant_and_tracked["email"], tenant_and_tracked["password"])
    me = requests.get(f"{API}/auth/me", headers=_auth(tok), timeout=10).json()
    assert me["show_dashboard"] is False
    assert me["show_welcome_modal"] is True
    assert me["show_messaging_notifs"] is False

    # 2) Reset via null (frontend "Défaut du rôle" behaviour)
    r = requests.put(
        f"{API}/admin/tracked-users/{tu_id}",
        headers=_auth(admin_token),
        json={"show_dashboard": None, "show_welcome_modal": None, "show_messaging_notifs": None},
        timeout=10,
    )
    assert r.status_code == 200

    tok = _login(tenant_and_tracked["email"], tenant_and_tracked["password"])
    me = requests.get(f"{API}/auth/me", headers=_auth(tok), timeout=10).json()
    assert me["show_dashboard"] is None
    assert me["show_welcome_modal"] is None
    assert me["show_messaging_notifs"] is None


def test_admin_bypass_no_p4_impact(admin_token):
    """Le super-admin n'a pas de tracked_user_id : ses flags restent null."""
    r = requests.get(f"{API}/auth/me", headers=_auth(admin_token), timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["show_dashboard"] is None
    assert body["show_welcome_modal"] is None
    assert body["show_messaging_notifs"] is None
