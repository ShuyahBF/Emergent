"""SAWALI - Tests for new features: portal_features toggles, user notes (Rapports/Suivis),
and document logs (upload + download)."""
import os
import io
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


# ----------------------------- Helpers -----------------------------
def _login(email, password):
    sess = requests.Session()
    r = sess.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login: {r.status_code} {r.text}"
    d = r.json()
    assert d.get("dev_otp"), "dev_otp expected (SMTP not configured)"
    r2 = sess.post(
        f"{BASE}/api/auth/verify-otp",
        json={"session_token": d["session_token"], "code": d["dev_otp"]},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    return body["access_token"], body["user"]


@pytest.fixture(scope="module")
def admin_token():
    token, user = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert user["role"] == "admin"
    return token


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def client_account(admin_h):
    payload = {
        "email": f"test_notes_{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "TEST Notes Client",
        "password": "Test@Notes2026",
        "role": "client",
        "phone": "+228 22 22 22 22",
        "company": "TEST Notes Co",
    }
    r = requests.post(f"{BASE}/api/admin/clients", json=payload, headers=admin_h)
    assert r.status_code == 200, r.text
    info = r.json()
    yield info, payload
    requests.delete(f"{BASE}/api/admin/clients/{info['id']}", headers=admin_h)


@pytest.fixture(scope="module")
def client_token(client_account):
    _, payload = client_account
    token, user = _login(payload["email"], payload["password"])
    assert user["role"] == "client"
    return token


@pytest.fixture(scope="module")
def client_h(client_token):
    return {"Authorization": f"Bearer {client_token}"}


# ----------------------------- portal_features in /api/company-info -----------------------------
class TestPortalFeatures:
    def test_company_info_has_portal_features(self):
        r = requests.get(f"{BASE}/api/company-info")
        assert r.status_code == 200
        d = r.json()
        assert "portal_features" in d
        pf = d["portal_features"]
        assert isinstance(pf.get("show_reports_button"), bool)
        assert isinstance(pf.get("show_suivis_button"), bool)
        # default should be true
        assert pf["show_reports_button"] is True
        assert pf["show_suivis_button"] is True

    def test_admin_can_toggle_portal_features(self, admin_h):
        # turn off both
        r = requests.put(
            f"{BASE}/api/admin/settings",
            json={"show_reports_button": False, "show_suivis_button": False},
            headers={**admin_h, "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text

        info = requests.get(f"{BASE}/api/company-info").json()
        assert info["portal_features"]["show_reports_button"] is False
        assert info["portal_features"]["show_suivis_button"] is False

        # restore to true
        r2 = requests.put(
            f"{BASE}/api/admin/settings",
            json={"show_reports_button": True, "show_suivis_button": True},
            headers={**admin_h, "Content-Type": "application/json"},
        )
        assert r2.status_code == 200, r2.text
        info2 = requests.get(f"{BASE}/api/company-info").json()
        assert info2["portal_features"]["show_reports_button"] is True
        assert info2["portal_features"]["show_suivis_button"] is True


# ----------------------------- /api/me/notes-summary -----------------------------
class TestNotesSummary:
    def test_admin_summary_returns_valid_shape(self, admin_h):
        r = requests.get(f"{BASE}/api/me/notes-summary", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "reports" in d and "suivis" in d
        assert isinstance(d["reports"]["count"], int)
        assert isinstance(d["suivis"]["count"], int)
        assert "last_updated" in d["reports"] and "last_updated" in d["suivis"]

    def test_client_summary_returns_zero_initially(self, client_h):
        r = requests.get(f"{BASE}/api/me/notes-summary", headers=client_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["reports"]["count"] == 0
        assert d["suivis"]["count"] == 0


# ----------------------------- Notes CRUD -----------------------------
class TestNotesCRUD:
    def test_invalid_kind_returns_404(self, client_h):
        r = requests.post(
            f"{BASE}/api/me/notes/INVALID_KIND",
            json={"title": "x", "content_html": "<p>x</p>"},
            headers={**client_h, "Content-Type": "application/json"},
        )
        assert r.status_code == 404
        assert "Type inconnu" in r.text

    def test_empty_title_returns_400(self, client_h):
        r = requests.post(
            f"{BASE}/api/me/notes/reports",
            json={"title": "   ", "content_html": "<p>x</p>"},
            headers={**client_h, "Content-Type": "application/json"},
        )
        assert r.status_code == 400

    def test_create_list_update_delete_report(self, client_h):
        # Create
        r = requests.post(
            f"{BASE}/api/me/notes/reports",
            json={"title": "TEST_Rapport_1", "content_html": "<p>Contenu</p>"},
            headers={**client_h, "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        note = r.json()
        assert note["title"] == "TEST_Rapport_1"
        assert note["kind"] == "reports"
        assert note["content_html"] == "<p>Contenu</p>"
        nid = note["id"]

        # List
        r2 = requests.get(f"{BASE}/api/me/notes/reports", headers=client_h)
        assert r2.status_code == 200
        items = r2.json()
        assert any(it["id"] == nid for it in items)

        # Summary now reports count >=1
        s = requests.get(f"{BASE}/api/me/notes-summary", headers=client_h).json()
        assert s["reports"]["count"] >= 1

        # Update
        r3 = requests.put(
            f"{BASE}/api/me/notes/reports/{nid}",
            json={"title": "TEST_Rapport_1_Updated", "content_html": "<p>MAJ</p>"},
            headers={**client_h, "Content-Type": "application/json"},
        )
        assert r3.status_code == 200

        # Verify update persisted
        r4 = requests.get(f"{BASE}/api/me/notes/reports", headers=client_h)
        upd = next(it for it in r4.json() if it["id"] == nid)
        assert upd["title"] == "TEST_Rapport_1_Updated"
        assert upd["content_html"] == "<p>MAJ</p>"

        # Delete
        r5 = requests.delete(f"{BASE}/api/me/notes/reports/{nid}", headers=client_h)
        assert r5.status_code == 200

        # Verify deleted
        r6 = requests.get(f"{BASE}/api/me/notes/reports", headers=client_h)
        assert not any(it["id"] == nid for it in r6.json())

    def test_suivis_kind_works(self, client_h):
        r = requests.post(
            f"{BASE}/api/me/notes/suivis",
            json={"title": "TEST_Suivi_1", "content_html": "<p>Suivi</p>"},
            headers={**client_h, "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        nid = r.json()["id"]
        # cleanup
        requests.delete(f"{BASE}/api/me/notes/suivis/{nid}", headers=client_h)


# ----------------------------- Document logs (upload + download) -----------------------------
class TestDocumentLogs:
    def test_upload_creates_log_and_download_creates_log(self, admin_token, admin_h, client_h):
        # Upload file as admin
        files = {"file": ("test_logs.txt", b"sawali doc logs test", "text/plain")}
        r = requests.post(
            f"{BASE}/api/admin/upload",
            files=files,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200, r.text
        meta = r.json()
        file_id = meta["id"]
        assert meta["url"] == f"/api/files/{file_id}"

        # Download as authenticated client (auth header forces client log)
        rd = requests.get(f"{BASE}/api/files/{file_id}", headers=client_h)
        assert rd.status_code == 200
        assert rd.content == b"sawali doc logs test"

        # Give async log task time to flush
        import time
        time.sleep(1.5)

        # Admin retrieves logs
        rl = requests.get(
            f"{BASE}/api/admin/document-logs",
            params={"file_id": file_id},
            headers=admin_h,
        )
        assert rl.status_code == 200, rl.text
        logs = rl.json()
        assert isinstance(logs, list)
        events = [l.get("event_type") for l in logs]
        assert "upload" in events, f"missing upload log: {logs}"
        assert "download" in events, f"missing download log: {logs}"

        # Verify each log has the expected metadata fields
        upload_log = next(l for l in logs if l["event_type"] == "upload")
        assert upload_log["file_id"] == file_id
        download_log = next(l for l in logs if l["event_type"] == "download")
        assert download_log["file_id"] == file_id
        # IP and duration should be present on download
        assert download_log.get("ip") or download_log.get("user_id")
        assert "duration_ms" in download_log
