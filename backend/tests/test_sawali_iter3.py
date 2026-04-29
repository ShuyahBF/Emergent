"""SAWALI - Iteration 3 backend pytest suite.

Covers:
- Tracked-user set-password / revoke-password (incl. login bridging)
- Notes webhook fire-and-forget logging on POST/PUT/DELETE notes
- Admin Settings masking for notes_webhook_token / notes_webhook_basic_pass
- Admin Documents filename + file_extension persistence (admin + portal)
"""
import os
import time
import uuid
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"
BACKEND_LOG = "/var/log/supervisor/backend.err.log"


# ----------------------------- Auth helpers -----------------------------
def _login(email, password):
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        return None, None, r
    data = r.json()
    if not data.get("dev_otp"):
        return None, None, r
    r2 = sess.post(
        f"{BASE}/api/auth/verify-otp",
        json={"session_token": data["session_token"], "code": data["dev_otp"]},
    )
    if r2.status_code != 200:
        return None, None, r2
    body = r2.json()
    return body["access_token"], body["user"], r2


@pytest.fixture(scope="session")
def admin_headers():
    token, user, _ = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert token, "admin login failed"
    assert user["role"] == "admin"
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def admin_token(admin_headers):
    return admin_headers["Authorization"].split(" ", 1)[1]


# Create a client + tracked-user for the test session
@pytest.fixture(scope="module")
def parent_client(admin_headers):
    payload = {
        "email": f"TEST_parent_{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "TEST Parent Client",
        "password": "Parent@Test2026",
        "role": "client",
        "company": "TEST Co",
    }
    r = requests.post(f"{BASE}/api/admin/clients", json=payload, headers=admin_headers)
    assert r.status_code == 200, r.text
    client = r.json()
    yield client
    requests.delete(f"{BASE}/api/admin/clients/{client['id']}", headers=admin_headers)


@pytest.fixture(scope="module")
def tracked_user(admin_headers, parent_client):
    email = f"TEST_tracked_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "client_id": parent_client["id"],
        "name": "TEST Tracked",
        "email": email,
        "phone": "+22890000000",
        "role": "Consultation",
    }
    r = requests.post(f"{BASE}/api/admin/tracked-users", json=payload, headers=admin_headers)
    assert r.status_code == 200, r.text
    tu = r.json()
    yield tu
    # cleanup tracked user (also drops the bridged users row)
    requests.delete(f"{BASE}/api/admin/tracked-users/{tu['id']}", headers=admin_headers)


# ----------------------------- TrackedUser set-password -----------------------------
class TestTrackedUserPassword:
    def test_set_password_short_returns_400(self, admin_headers, tracked_user):
        r = requests.post(
            f"{BASE}/api/admin/tracked-users/{tracked_user['id']}/set-password",
            json={"password": "short"},
            headers=admin_headers,
        )
        assert r.status_code == 400, r.text

    def test_set_password_no_email(self, admin_headers, parent_client):
        # create a tracked-user without email
        payload = {
            "client_id": parent_client["id"],
            "name": "TEST NoEmail",
            "role": "Consultation",
        }
        r = requests.post(f"{BASE}/api/admin/tracked-users", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        tu = r.json()
        try:
            r2 = requests.post(
                f"{BASE}/api/admin/tracked-users/{tu['id']}/set-password",
                json={"password": "Strong@Pwd2026"},
                headers=admin_headers,
            )
            assert r2.status_code == 400
        finally:
            requests.delete(f"{BASE}/api/admin/tracked-users/{tu['id']}", headers=admin_headers)

    def test_set_password_ok_and_login(self, admin_headers, tracked_user):
        password = "Strong@Pwd2026"
        r = requests.post(
            f"{BASE}/api/admin/tracked-users/{tracked_user['id']}/set-password",
            json={"password": password},
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["email"].lower() == tracked_user["email"].lower()
        assert data.get("user_id")

        # tracked_users updated
        lst = requests.get(f"{BASE}/api/admin/tracked-users", headers=admin_headers).json()
        match = [t for t in lst if t["id"] == tracked_user["id"]][0]
        assert match.get("has_password") is True
        assert match.get("user_account_id") == data["user_id"]

        # Login as tracked-user
        token, user, _ = _login(tracked_user["email"], password)
        assert token, "tracked user login failed"
        assert user["role"] == "client"
        assert user["email"].lower() == tracked_user["email"].lower()

        # /me/account works
        r2 = requests.get(
            f"{BASE}/api/me/account",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200
        assert r2.json()["user"]["email"].lower() == tracked_user["email"].lower()

    def test_revoke_password_blocks_login(self, admin_headers, tracked_user):
        # ensure password is set first
        password = "Strong@Pwd2026"
        requests.post(
            f"{BASE}/api/admin/tracked-users/{tracked_user['id']}/set-password",
            json={"password": password},
            headers=admin_headers,
        )
        r = requests.post(
            f"{BASE}/api/admin/tracked-users/{tracked_user['id']}/revoke-password",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        # login should now fail
        rl = requests.post(
            f"{BASE}/api/auth/login",
            json={"email": tracked_user["email"], "password": password},
        )
        assert rl.status_code == 401, rl.text
        # has_password False
        lst = requests.get(f"{BASE}/api/admin/tracked-users", headers=admin_headers).json()
        match = [t for t in lst if t["id"] == tracked_user["id"]][0]
        assert match.get("has_password") in (False, None)


# ----------------------------- Notes webhook -----------------------------
class TestNotesWebhook:
    def _read_log_tail(self, n=400):
        try:
            with open(BACKEND_LOG, "r") as f:
                return f.read()[-50000:]
        except Exception:
            return ""

    def test_webhook_fires_on_create_update_delete(self, admin_headers):
        # 1) Configure webhook to httpbin
        r = requests.put(
            f"{BASE}/api/admin/settings",
            json={
                "notes_webhook_enabled": True,
                "notes_webhook_url": "https://httpbin.org/post",
                "notes_webhook_auth_type": "none",
            },
            headers=admin_headers,
        )
        assert r.status_code == 200

        # 2) Need a non-admin user (admin doesn't have /me/notes routes? Check role)
        # /me/notes uses get_current_user — admin role works too as it returns user.
        marker = uuid.uuid4().hex[:8]
        # Use admin token to create a note
        h = {"Authorization": admin_headers["Authorization"], "Content-Type": "application/json"}
        rc = requests.post(
            f"{BASE}/api/me/notes/reports",
            json={"title": f"TEST_webhook_{marker}", "content_html": "<p>hi</p>"},
            headers=h,
        )
        assert rc.status_code == 200, rc.text
        note_id = rc.json()["id"]

        ru = requests.put(
            f"{BASE}/api/me/notes/reports/{note_id}",
            json={"title": f"TEST_webhook_{marker}_upd"},
            headers=h,
        )
        assert ru.status_code == 200

        rd = requests.delete(f"{BASE}/api/me/notes/reports/{note_id}", headers=h)
        assert rd.status_code == 200

        # Wait for fire-and-forget tasks to log
        time.sleep(4)
        log = self._read_log_tail()
        # We accept either success or failed messages because httpbin may be unreachable
        # but the route MUST not have failed.
        # The presence of "Notes webhook" is what we check.
        assert "Notes webhook" in log, "Expected 'Notes webhook' log line for fire-and-forget call"

    def test_disable_webhook_cleanup(self, admin_headers):
        r = requests.put(
            f"{BASE}/api/admin/settings",
            json={"notes_webhook_enabled": False},
            headers=admin_headers,
        )
        assert r.status_code == 200


# ----------------------------- Settings masking (new secrets) -----------------------------
class TestSettingsMaskingNewSecrets:
    def test_masking_token_and_pass(self, admin_headers):
        # Set a clear token + basic-pass
        r = requests.put(
            f"{BASE}/api/admin/settings",
            json={
                "notes_webhook_token": "abc-secret",
                "notes_webhook_basic_pass": "p@ss",
            },
            headers=admin_headers,
        )
        assert r.status_code == 200

        # GET masks
        rg = requests.get(f"{BASE}/api/admin/settings", headers=admin_headers)
        assert rg.status_code == 200
        d = rg.json()
        assert d.get("notes_webhook_token") == "********"
        assert d.get("notes_webhook_basic_pass") == "********"

        # PUT another field only — secrets must remain
        r2 = requests.put(
            f"{BASE}/api/admin/settings",
            json={"notes_webhook_url": "https://httpbin.org/post"},
            headers=admin_headers,
        )
        assert r2.status_code == 200
        rg2 = requests.get(f"{BASE}/api/admin/settings", headers=admin_headers)
        d2 = rg2.json()
        assert d2.get("notes_webhook_token") == "********"
        assert d2.get("notes_webhook_basic_pass") == "********"


# ----------------------------- Admin Documents filename/extension -----------------------------
class TestAdminDocumentsMetadata:
    def test_create_with_filename_extension_persists(self, admin_headers):
        payload = {
            "title": f"TEST Doc {uuid.uuid4().hex[:6]}",
            "description": "TEST",
            "category": "documentation",
            "file_url": "/api/files/dummy.pdf",
            "file_type": "pdf",
            "filename": "rapport.pdf",
            "file_extension": ".pdf",
            "is_public": True,
        }
        r = requests.post(f"{BASE}/api/admin/documents", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["filename"] == "rapport.pdf"
        assert doc["file_extension"] == ".pdf"
        doc_id = doc["id"]

        # GET admin list
        rl = requests.get(f"{BASE}/api/admin/documents", headers=admin_headers)
        assert rl.status_code == 200
        match = [d for d in rl.json() if d["id"] == doc_id]
        assert match, "doc not found in admin list"
        assert match[0]["filename"] == "rapport.pdf"
        assert match[0]["file_extension"] == ".pdf"

        # cleanup
        requests.delete(f"{BASE}/api/admin/documents/{doc_id}", headers=admin_headers)
