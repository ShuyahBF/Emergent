"""SAWALI SMART SYSTEMS - Backend API end-to-end pytest suite.

Covers: Health, Public content, Availability, Contact, Auth (login+OTP),
Admin Clients CRUD, Public/Client appointments + conflict, Admin Upload + serve,
Admin Content upsert, Admin Settings (masked), API routes meta, GCal not configured.
"""
import os
import io
import time
import uuid
import pytest
import requests
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


# ----------------------------- Fixtures -----------------------------
@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login_and_get_token(sess, email, password):
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("needs_otp") is True
    assert data.get("session_token")
    assert data.get("dev_otp"), "dev_otp expected when SMTP not configured"
    r2 = sess.post(
        f"{BASE}/api/auth/verify-otp",
        json={"session_token": data["session_token"], "code": data["dev_otp"]},
    )
    assert r2.status_code == 200, f"verify-otp failed: {r2.status_code} {r2.text}"
    body = r2.json()
    assert body.get("access_token")
    return body["access_token"], body["user"]


@pytest.fixture(scope="session")
def admin_token(s):
    token, user = _login_and_get_token(s, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert user["role"] == "admin"
    return token


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ----------------------------- Health -----------------------------
class TestHealth:
    def test_root(self, s):
        r = s.get(f"{BASE}/api/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_health(self, s):
        r = s.get(f"{BASE}/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ----------------------------- Public content -----------------------------
class TestPublicContent:
    def test_company_info(self, s):
        r = s.get(f"{BASE}/api/company-info")
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "SAWALI SMART SYSTEMS"
        assert "business_open_time" in d and "business_close_time" in d
        assert isinstance(d.get("business_days"), list)

    def test_content_seeded(self, s):
        r = s.get(f"{BASE}/api/content")
        assert r.status_code == 200
        items = r.json()
        slugs = {i["slug"] for i in items}
        for required in ("home_hero", "mission", "experience", "specialisations", "about"):
            assert required in slugs, f"missing seeded content {required}"

    def test_content_get_by_slug(self, s):
        r = s.get(f"{BASE}/api/content/mission")
        assert r.status_code == 200
        assert r.json()["slug"] == "mission"

    def test_captcha_config(self, s):
        r = s.get(f"{BASE}/api/auth/captcha-config")
        assert r.status_code == 200
        assert "enabled" in r.json()


# ----------------------------- Availability -----------------------------
class TestAvailability:
    def test_business_day_returns_slots(self, s):
        # find a business day (Mon-Fri) at least 3 days ahead to avoid past-time
        d = datetime.now(timezone.utc) + timedelta(days=3)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        r = s.get(f"{BASE}/api/availability", params={"date": d.strftime("%Y-%m-%d")})
        assert r.status_code == 200
        body = r.json()
        assert body.get("is_business_day") is True
        assert isinstance(body.get("slots"), list) and len(body["slots"]) > 0

    def test_non_business_day(self, s):
        # find a Sunday
        d = datetime.now(timezone.utc) + timedelta(days=1)
        while d.weekday() != 6:
            d += timedelta(days=1)
        r = s.get(f"{BASE}/api/availability", params={"date": d.strftime("%Y-%m-%d")})
        assert r.status_code == 200
        body = r.json()
        assert body.get("is_business_day") is False
        assert body.get("slots") == []


# ----------------------------- Contact -----------------------------
class TestContact:
    def test_create_contact(self, s):
        payload = {
            "name": "TEST_Contact",
            "email": "test_contact@example.com",
            "phone": "+228 90 00 00 00",
            "subject": "Test",
            "message": "Hello from pytest",
        }
        r = s.post(f"{BASE}/api/contact", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True and d.get("id")


# ----------------------------- Auth -----------------------------
class TestAuth:
    def test_login_wrong_password(self, s):
        r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-pass"})
        assert r.status_code == 401

    def test_admin_me(self, s, admin_headers):
        r = s.get(f"{BASE}/api/auth/me", headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN_EMAIL
        assert d["role"] == "admin"

    def test_protected_without_token(self, s):
        r = s.get(f"{BASE}/api/me/account")
        assert r.status_code in (401, 403)


# ----------------------------- Admin Clients CRUD -----------------------------
@pytest.fixture(scope="class")
def created_client(admin_headers):
    sess = requests.Session()
    payload = {
        "email": f"test_client_{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "TEST Client",
        "password": "Test@Client2026",
        "role": "client",
        "phone": "+228 11 11 11 11",
        "company": "TEST Co",
    }
    r = sess.post(f"{BASE}/api/admin/clients", json=payload, headers=admin_headers)
    assert r.status_code == 200, r.text
    yield r.json(), payload
    # cleanup
    sess.delete(f"{BASE}/api/admin/clients/{r.json()['id']}", headers=admin_headers)


class TestAdminClientsCRUD:
    def test_create_and_list(self, s, admin_headers, created_client):
        client, payload = created_client
        assert client["email"] == payload["email"]
        assert client["role"] == "client"
        # GET via admin/clients/{id}
        r = s.get(f"{BASE}/api/admin/clients/{client['id']}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["email"] == payload["email"]
        # list
        r2 = s.get(f"{BASE}/api/admin/clients", headers=admin_headers)
        assert r2.status_code == 200
        assert any(u["id"] == client["id"] for u in r2.json())

    def test_update_and_persist(self, s, admin_headers, created_client):
        client, _ = created_client
        r = s.put(
            f"{BASE}/api/admin/clients/{client['id']}",
            json={"full_name": "TEST Client Updated", "company": "TEST Co Updated"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        r2 = s.get(f"{BASE}/api/admin/clients/{client['id']}", headers=admin_headers)
        assert r2.status_code == 200
        assert r2.json()["full_name"] == "TEST Client Updated"

    def test_client_login_and_me_endpoints(self, s, created_client):
        _, payload = created_client
        sess = requests.Session()
        sess.headers.update({"Content-Type": "application/json"})
        token, user = _login_and_get_token(sess, payload["email"], payload["password"])
        h = {"Authorization": f"Bearer {token}"}
        # me/account
        r = requests.get(f"{BASE}/api/me/account", headers=h)
        assert r.status_code == 200
        assert r.json()["user"]["email"] == payload["email"]
        # me/appointments
        r2 = requests.get(f"{BASE}/api/me/appointments", headers=h)
        assert r2.status_code == 200
        # me/documents
        r3 = requests.get(f"{BASE}/api/me/documents", headers=h)
        assert r3.status_code == 200


# ----------------------------- Appointments + Conflict -----------------------------
class TestAppointments:
    def test_public_book_and_conflict(self, s):
        # find next business day at 10:00 UTC
        d = datetime.now(timezone.utc) + timedelta(days=4)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        slot = d.replace(hour=10, minute=0, second=0, microsecond=0)
        # nudge to be unique
        slot = slot + timedelta(minutes=(int(time.time()) % 7) * 30)
        # ensure within business hours (max 17:30)
        if slot.hour >= 17:
            slot = slot.replace(hour=14, minute=0)
        scheduled_iso = slot.isoformat()
        payload = {
            "name": "TEST RDV",
            "email": "test_rdv@example.com",
            "phone": "+22890000000",
            "subject": "Test booking",
            "message": "pytest",
            "scheduled_at": scheduled_iso,
            "duration_min": 30,
        }
        r = s.post(f"{BASE}/api/appointments/public", json=payload)
        assert r.status_code == 200, r.text
        d1 = r.json()
        assert d1["ok"] is True
        assert d1["appointment"]["status"] == "pending"
        # conflict
        r2 = s.post(f"{BASE}/api/appointments/public", json=payload)
        assert r2.status_code == 409


# ----------------------------- Admin Upload + Serve File -----------------------------
class TestAdminUpload:
    def test_upload_and_serve(self, admin_token):
        files = {"file": ("hello.txt", b"hello sawali", "text/plain")}
        h = {"Authorization": f"Bearer {admin_token}"}
        r = requests.post(f"{BASE}/api/admin/upload", files=files, headers=h)
        assert r.status_code == 200, r.text
        meta = r.json()
        assert meta.get("id") and meta.get("url", "").startswith("/api/files/")
        # serve
        r2 = requests.get(f"{BASE}{meta['url']}")
        assert r2.status_code == 200
        assert r2.content == b"hello sawali"


# ----------------------------- Admin Content upsert -----------------------------
class TestAdminContent:
    def test_upsert_and_get(self, s, admin_headers):
        slug = "sawali-portal"
        payload = {
            "slug": slug,
            "title": "Portail SAWALI",
            "body_html": "<p>Bienvenue</p>",
            "images": [],
            "metadata": {"version": "1.0"},
        }
        r = s.put(f"{BASE}/api/admin/content/{slug}", json=payload, headers=admin_headers)
        assert r.status_code == 200
        # GET public
        r2 = s.get(f"{BASE}/api/content/{slug}")
        assert r2.status_code == 200
        d = r2.json()
        assert d["title"] == "Portail SAWALI"
        assert d["metadata"].get("version") == "1.0"


# ----------------------------- Admin Settings -----------------------------
class TestAdminSettings:
    def test_get_settings_masked(self, s, admin_headers):
        r = s.get(f"{BASE}/api/admin/settings", headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert "business_open_time" in d
        assert "google_calendar_connected" in d

    def test_update_settings(self, s, admin_headers):
        r = s.put(
            f"{BASE}/api/admin/settings",
            json={"company_phone": "+228 99 99 99 99"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        r2 = s.get(f"{BASE}/api/admin/settings", headers=admin_headers)
        assert r2.json().get("company_phone") == "+228 99 99 99 99"


# ----------------------------- API routes meta -----------------------------
class TestApiRoutesMeta:
    def test_list_routes(self, s):
        r = s.get(f"{BASE}/api/api-routes")
        assert r.status_code == 200
        routes = r.json()
        assert isinstance(routes, list) and len(routes) > 20
        assert any(rt["path"] == "/api/auth/login" for rt in routes)
        assert any(rt["path"] == "/api/admin/clients" for rt in routes)


# ----------------------------- GCal not configured -----------------------------
class TestGoogleAuthUrl:
    def test_returns_400_when_not_configured(self, s, admin_headers):
        # ensure unconfigured
        s.put(
            f"{BASE}/api/admin/settings",
            json={"google_client_id": "", "google_client_secret": ""},
            headers=admin_headers,
        )
        r = s.get(f"{BASE}/api/admin/google/auth-url", headers=admin_headers)
        assert r.status_code == 400
