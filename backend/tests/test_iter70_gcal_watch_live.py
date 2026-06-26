"""Iter70 live smoke test against public preview URL for GCal Watch admin endpoints."""
import os
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASS = "Admin@Sawali2026"


def _login_admin():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    otp = j.get("dev_otp")
    st = j.get("session_token")
    assert otp and st, f"Login missing: {j}"
    r2 = s.post(f"{BASE}/api/auth/verify-otp", json={"session_token": st, "code": otp}, timeout=20)
    assert r2.status_code == 200, r2.text
    token = r2.json().get("access_token") or r2.json().get("token")
    assert token, r2.json()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def test_watch_status_unauth():
    r = requests.get(f"{BASE}/api/admin/google/calendar/watch", timeout=15)
    assert r.status_code in (401, 403), r.status_code


def test_watch_status_as_admin():
    s = _login_admin()
    r = s.get(f"{BASE}/api/admin/google/calendar/watch", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    expected_keys = {"active", "channel_id", "resource_id", "webhook_url",
                     "calendar_id", "expiration", "renewed_at",
                     "last_notification_at", "last_sync_at", "sync_token_set"}
    missing = expected_keys - set(data.keys())
    assert not missing, f"missing keys: {missing}; got: {data}"
    assert data["active"] is False  # Not connected in preview


def test_start_watch_fails_when_not_connected():
    s = _login_admin()
    r = s.post(f"{BASE}/api/admin/google/calendar/watch", json={}, timeout=20)
    assert r.status_code in (400, 502), r.status_code
    body = r.json()
    detail = (body.get("detail") or body.get("message") or "").lower()
    assert "google" in detail or "calendar" in detail or "configur" in detail, body


def test_sync_now_fails_when_not_connected():
    s = _login_admin()
    r = s.post(f"{BASE}/api/admin/google/calendar/sync-now", json={}, timeout=20)
    assert r.status_code == 400, r.text


def test_stop_watch_when_inactive_does_not_raise():
    s = _login_admin()
    r = s.delete(f"{BASE}/api/admin/google/calendar/watch", timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ok" in body
    assert body["ok"] in (True, False)


def test_webhook_rejects_missing_headers():
    r = requests.post(f"{BASE}/api/google/calendar/webhook", timeout=15)
    assert r.status_code == 403, r.status_code


def test_webhook_rejects_invalid_channel():
    headers = {
        "x-goog-channel-id": "fake-channel",
        "x-goog-channel-token": "fake-token",
        "x-goog-resource-id": "fake-resource",
        "x-goog-resource-state": "exists",
    }
    r = requests.post(f"{BASE}/api/google/calendar/webhook", headers=headers, timeout=15)
    assert r.status_code == 403, r.status_code
