"""Iter34l — Backend tests for the Admin Profile Update Requests workflow.

Covers:
  • POST /me/profile-update-request (user submits a change request)
  • GET  /admin/profile-requests?status=… (admin lists w/ filter)
  • PATCH /admin/profile-requests/{id} (mark processed, note, reopen)
  • Bad inputs return 400, missing id returns 404
  • The notification count `admin_profile_requests` reflects pending count
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    data = r.json()
    if not data.get("needs_otp"):
        return data.get("access_token")
    session_token = data["session_token"]
    code = data.get("dev_otp")
    assert code, f"no dev_otp in response: {data}"
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": session_token, "code": code}, timeout=30)
    assert r2.status_code == 200, f"verify-otp failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def admin_h() -> dict:
    tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def fresh_request(admin_h) -> str:
    """Submit a brand-new profile-update-request as the admin (acts as a user)
    and return its id. Each test gets its own row."""
    r = requests.post(
        f"{API}/me/profile-update-request",
        headers=admin_h,
        json={"message": "Test iter34l — please correct my surname", "fields": ["full_name", "phone"]},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_list_all_includes_fresh(admin_h, fresh_request):
    r = requests.get(f"{API}/admin/profile-requests?status=all", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "items" in data and "pending_count" in data
    ids = [it["id"] for it in data["items"]]
    assert fresh_request in ids


def test_filter_pending_shows_new_row(admin_h, fresh_request):
    r = requests.get(f"{API}/admin/profile-requests?status=pending", headers=admin_h, timeout=30)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["id"] == fresh_request and it["status"] == "pending" for it in items)


def test_notification_count_reflects_pending(admin_h, fresh_request):
    r = requests.get(f"{API}/me/notifications/counts", headers=admin_h, timeout=30)
    assert r.status_code == 200
    counts = r.json().get("counts", {})
    assert counts.get("admin_profile_requests", 0) >= 1


def test_mark_processed_with_note_and_reopen(admin_h, fresh_request):
    # 1. mark processed
    r = requests.patch(
        f"{API}/admin/profile-requests/{fresh_request}",
        headers=admin_h,
        json={"status": "processed", "admin_note": "Corrigé en BDD le 11/05"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "processed"
    assert body["admin_note"] == "Corrigé en BDD le 11/05"
    assert body["resolved_at"] is not None
    assert body.get("resolved_by_email") == ADMIN_EMAIL

    # 2. it should now appear in processed filter
    r2 = requests.get(f"{API}/admin/profile-requests?status=processed", headers=admin_h, timeout=30)
    assert r2.status_code == 200
    ids = [it["id"] for it in r2.json()["items"]]
    assert fresh_request in ids

    # 3. reopen
    r3 = requests.patch(
        f"{API}/admin/profile-requests/{fresh_request}",
        headers=admin_h,
        json={"status": "pending"},
        timeout=30,
    )
    assert r3.status_code == 200
    body3 = r3.json()
    assert body3["status"] == "pending"
    assert body3.get("resolved_at") in (None, "")


def test_invalid_status_returns_400(admin_h, fresh_request):
    r = requests.patch(
        f"{API}/admin/profile-requests/{fresh_request}",
        headers=admin_h,
        json={"status": "garbage"},
        timeout=30,
    )
    assert r.status_code == 400


def test_missing_id_returns_404(admin_h):
    r = requests.patch(
        f"{API}/admin/profile-requests/does-not-exist-xxx",
        headers=admin_h,
        json={"status": "processed"},
        timeout=30,
    )
    assert r.status_code == 404


def test_long_admin_note_rejected(admin_h, fresh_request):
    r = requests.patch(
        f"{API}/admin/profile-requests/{fresh_request}",
        headers=admin_h,
        json={"admin_note": "x" * 2001},
        timeout=30,
    )
    assert r.status_code == 400
