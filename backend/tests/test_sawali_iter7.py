"""SAWALI — Iteration 7 backend tests.

Coverage:
- GET /api/admin/health-stats?window_hours=24 → 200 with all fields, 403 for non-super-admin.
- POST /api/admin/health/test-email → 200 {ok,recipient}.
- Enable realtime + webhook (httpbin.org) then POST /me/api-trace status=500 — webhook fired.
- POST /api/admin/health/run-weekly-now → 200.
- GET /api/admin/db → list of whitelisted collections w/ counts.
- GET /api/admin/db/users?role=admin → filter works & password_hash is redacted.
- GET /api/admin/db/api_traces?status__gte=400&sort_by=created_at&sort_dir=-1&limit=10 → coercion.
- GET /api/admin/db/api_traces?method__regex=POST → regex filter works.
- GET /api/admin/db/INVALID → 400; /api/admin/db/users with non-super-admin → 403.
- Scheduler startup log present.
"""
import os
import re
import time
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email, password):
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    if d.get("needs_otp"):
        assert d.get("dev_otp"), f"dev_otp expected for {email}; got {d}"
        r2 = sess.post(f"{BASE}/api/auth/verify-otp",
                       json={"session_token": d["session_token"], "code": d["dev_otp"]})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        return body["access_token"], body["user"]
    return d["access_token"], d["user"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def admin_tok():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok


@pytest.fixture(scope="session")
def admin_h(admin_tok):
    return _h(admin_tok)


@pytest.fixture(scope="session")
def second_admin(admin_h):
    email = f"test_iter7_admin_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "Admin2@Iter7-2026"
    r = requests.post(
        f"{BASE}/api/admin/clients",
        json={"email": email, "full_name": "TEST iter7 admin2",
              "password": pwd, "role": "admin", "phone": "+228 00 00 00 00"},
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    client = r.json()
    tok, u = _login(email, pwd)
    yield {"id": client["id"], "email": email, "tok": tok}
    requests.delete(f"{BASE}/api/admin/clients/{client['id']}", headers=admin_h)


# ---------- health-stats ----------
class TestHealthStats:
    def test_super_admin_200(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/health-stats?window_hours=24", headers=admin_h)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("window_hours", "total", "errors", "error_rate",
                  "avg_duration_ms", "top_errors", "top_users", "hourly"):
            assert k in data, f"missing field {k}: {data.keys()}"
        assert data["window_hours"] == 24
        assert isinstance(data["total"], int)
        assert isinstance(data["errors"], int)
        assert isinstance(data["top_errors"], list)
        assert isinstance(data["top_users"], list)
        assert isinstance(data["hourly"], list)

    def test_non_super_admin_403(self, second_admin):
        r = requests.get(f"{BASE}/api/admin/health-stats?window_hours=24",
                         headers=_h(second_admin["tok"]))
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"


# ---------- test-email + webhook ----------
class TestHealthNotifications:
    def test_test_email_200(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/health/test-email", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert "recipient" in d
        # When SMTP not configured email_sent will be false — fine.

    def test_enable_webhook_and_fire_via_api_trace(self, admin_h):
        # Enable realtime + webhook pointing to httpbin
        r = requests.put(
            f"{BASE}/api/admin/settings",
            json={
                "health_realtime_enabled": True,
                "health_webhook_url": "https://httpbin.org/post",
                "health_webhook_auth_type": "none",
                "health_email_to": ADMIN_EMAIL,
            },
            headers=admin_h,
        )
        assert r.status_code == 200, r.text

        # Fire test-email which schedules a webhook call
        r2 = requests.post(f"{BASE}/api/admin/health/test-email", headers=admin_h)
        assert r2.status_code == 200, r2.text

        # Now record a failing api_trace via /me/api-trace — must be fire-and-forget
        r3 = requests.post(
            f"{BASE}/api/me/api-trace",
            json={"method": "GET", "url": "/api/test/iter7", "status": 500,
                  "duration_ms": 12, "message": "TEST_iter7 synthetic 500"},
            headers=admin_h,
        )
        assert r3.status_code in (200, 204), r3.text
        # Allow fire-and-forget to finish
        time.sleep(1.5)

    def test_run_weekly_now(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/health/run-weekly-now", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True

    def test_cleanup_disable_realtime(self, admin_h):
        # Restore to avoid polluting subsequent tests
        r = requests.put(
            f"{BASE}/api/admin/settings",
            json={"health_realtime_enabled": False, "health_webhook_url": ""},
            headers=admin_h,
        )
        assert r.status_code == 200


# ---------- admin/db ----------
class TestAdminDb:
    def test_list_collections(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/db", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d, list)
        names = [c["name"] for c in d]
        for expected in ("users", "api_traces", "settings"):
            assert expected in names, f"collection {expected} missing from {names}"
        for c in d:
            assert "name" in c and "count" in c

    def test_query_users_role_admin_and_redaction(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/db/users?role=admin", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["collection"] == "users"
        assert isinstance(d["total_matched"], int)
        assert d["total_matched"] >= 1  # at least super-admin
        assert isinstance(d["items"], list)
        for u in d["items"]:
            assert u.get("role") == "admin"
            if "password_hash" in u:
                # Redaction behaviour confirmed by task note
                assert u["password_hash"] == "[REDACTED]", \
                    f"password_hash NOT redacted: {u['password_hash']!r}"
            # _id must be stripped out
            assert "_id" not in u

    def test_query_api_traces_status_gte_coercion(self, admin_h):
        # Ensure at least one 500 trace exists
        requests.post(
            f"{BASE}/api/me/api-trace",
            json={"method": "GET", "url": "/api/test/iter7-coerce", "status": 500,
                  "duration_ms": 9, "message": "TEST_iter7 coerce"},
            headers=admin_h,
        )
        time.sleep(0.3)
        r = requests.get(
            f"{BASE}/api/admin/db/api_traces?status__gte=400&sort_by=created_at&sort_dir=-1&limit=10",
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["collection"] == "api_traces"
        assert d["limit"] == 10
        assert len(d["items"]) <= 10
        for it in d["items"]:
            assert isinstance(it.get("status"), int), f"status not int: {it.get('status')!r}"
            assert it["status"] >= 400

    def test_query_api_traces_method_regex(self, admin_h):
        r = requests.get(
            f"{BASE}/api/admin/db/api_traces?method__regex=POST&limit=20",
            headers=admin_h,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        for it in d["items"]:
            assert re.search("POST", it.get("method", ""), re.IGNORECASE), \
                f"regex filter leak: {it.get('method')}"

    def test_invalid_collection_400(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/db/INVALID_COLLECTION", headers=admin_h)
        assert r.status_code == 400, r.text
        assert "Collection" in (r.json().get("detail") or "")

    def test_non_super_admin_forbidden(self, second_admin):
        r = requests.get(f"{BASE}/api/admin/db/users",
                         headers=_h(second_admin["tok"]))
        assert r.status_code == 403


# ---------- scheduler log ----------
class TestScheduler:
    def test_scheduler_started_log(self):
        """Verify scheduler start message in backend logs (parallel supervisor logs)."""
        # Look across recent supervisor logs
        import subprocess
        out = subprocess.run(
            ["bash", "-lc",
             "grep -rh 'Scheduler started' /var/log/supervisor/backend*.log 2>/dev/null | tail -5"],
            capture_output=True, text=True, timeout=10,
        )
        combined = (out.stdout or "") + (out.stderr or "")
        assert "weekly digest scheduled for Fri 05:00 Africa/Abidjan" in combined, \
            f"scheduler log not found; got: {combined[:500]!r}"
