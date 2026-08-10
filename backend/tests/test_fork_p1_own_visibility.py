"""2026-02 (fork) — Regression test for P1 bug:
`support@sawalismartsystems.com` created tickets/interventions were invisible
to them because the visibility filter matched on `client_id ∈ scope` only.
This test seeds a "support" tracked-user with `role=admin` and `company=SUPPORT-CO`
that opens a ticket + intervention against ANOTHER client tenant (different
company). The support user must now see them via the own-creation fallback.
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
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
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
def seeded_support(admin_token: str):
    """Create a fresh "support-like" admin user with a distinct `company` +
    a fresh "target client" tenant. Support opens a ticket + intervention
    referencing target-client. Returns dict with credentials + IDs.
    """
    tag = uuid.uuid4().hex[:8]
    support_email = f"support-{tag}@sawali-test.com"
    support_password = "Support@2026"
    client_email = f"client-target-{tag}@sawali-test.com"
    client_password = "Client@2026"

    # Create the "target client" tenant first (admin role, different company)
    r = requests.post(
        f"{API}/admin/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": client_email,
            "password": client_password,
            "full_name": f"Client Target {tag}",
            "role": "admin",
            "company": f"CLIENT-CO-{tag}",
        },
        timeout=10,
    )
    r.raise_for_status()
    client_id = r.json()["id"]

    # Create the "support" user with a totally different company
    r = requests.post(
        f"{API}/admin/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": support_email,
            "password": support_password,
            "full_name": f"Support Agent {tag}",
            "role": "admin",  # elevated so they can open tickets against other clients
            "company": f"SUPPORT-CO-{tag}",  # distinct company → not in target scope
        },
        timeout=10,
    )
    r.raise_for_status()
    support_id = r.json()["id"]

    support_token = _login(support_email, support_password)

    return {
        "support_id": support_id,
        "support_email": support_email,
        "support_token": support_token,
        "client_id": client_id,
        "tag": tag,
    }


def test_support_can_see_own_created_ticket(seeded_support):
    """Support opens a ticket against a different-company client. They must
    then see it in `/me/tickets` even though its client_id is out of scope.
    """
    tok = seeded_support["support_token"]
    # POST /me/tickets (quick-create)
    r = requests.post(
        f"{API}/me/tickets",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "client_id": seeded_support["client_id"],
            "reason": f"P1 own-visibility check {seeded_support['tag']}",
            "contact_name": "Test Contact",
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    ticket_id = r.json()["id"]

    # GET /me/tickets — the ticket must be in the list
    r = requests.get(
        f"{API}/me/tickets",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=10,
    )
    assert r.status_code == 200
    tickets = r.json()
    ids = [t["id"] for t in tickets]
    assert ticket_id in ids, f"Support cannot see own ticket! ids={ids}"


def test_support_can_see_own_created_intervention(seeded_support):
    """Support creates an intervention against a different-company client.
    They must then see it in `/me/interventions`.
    """
    tok = seeded_support["support_token"]
    r = requests.post(
        f"{API}/me/interventions",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "client_id": seeded_support["client_id"],
            "intervention_date": "2026-02-14",
            "title": f"P1 intervention check {seeded_support['tag']}",
            "description": "Support-created intervention should be visible to support",
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    int_id = r.json()["id"]

    r = requests.get(
        f"{API}/me/interventions",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=10,
    )
    assert r.status_code == 200
    ints = r.json()
    ids = [i["id"] for i in ints]
    assert int_id in ids, f"Support cannot see own intervention! ids={ids}"


def test_super_admin_still_sees_everything(admin_token, seeded_support):
    """Regression : the super-admin (SAWALI) must still see ALL tickets and
    interventions across every tenant, including the ones support just made.
    """
    r = requests.get(
        f"{API}/me/tickets",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 200
    tickets = r.json()
    # Must find at least one ticket authored by our support user
    support_tickets = [t for t in tickets if t.get("opened_by_id") == seeded_support["support_id"]]
    assert support_tickets, "Super-admin lost visibility on support-created tickets!"
