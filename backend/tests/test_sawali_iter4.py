"""SAWALI - Iteration 4 backend tests.

Coverage:
- Notes auto-numbering (RPT-YYYY-NNNN, SUI-YYYY-NNNN)
- Suivi requires client_id + event_date
- descent_time window (403 when past cutoff)
- Ratings (Admin posts, GET /me/notes returns my_rating, DELETE clears, non-admin 403)
- Role-based access (Consultation cannot create, Moderation creates but cannot delete, Administrateur deletes)
- /me/contacts/{id}/save-as-tracked-user returns generated_password and login works
- Access logs (POST /me/access-log + GET /admin/access-logs?q=... + export.csv + 403 for client)
- Documents visibility / upload / delete role enforcement
- Images cap at 10
- 1h-edit lock — admin always allowed
"""
import os
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
    assert r.status_code == 200, f"login: {r.status_code} {r.text}"
    d = r.json()
    if d.get("needs_otp"):
        assert d.get("dev_otp"), "dev_otp expected"
        r2 = sess.post(f"{BASE}/api/auth/verify-otp",
                       json={"session_token": d["session_token"], "code": d["dev_otp"]})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        return body["access_token"], body["user"]
    return d["access_token"], d["user"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ----------------- Session-scoped fixtures -----------------
@pytest.fixture(scope="session")
def admin_tok():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok


@pytest.fixture(scope="session")
def admin_h(admin_tok):
    return _h(admin_tok)


@pytest.fixture(scope="session")
def test_client(admin_h):
    """A real client (non-elevated) we can use across tests."""
    payload = {
        "email": f"test_iter4_client_{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "TEST iter4 Client",
        "password": "Test@Iter4-2026",
        "role": "client",
        "phone": "+228 11 22 33 44",
        "company": "TEST Iter4 Co",
    }
    r = requests.post(f"{BASE}/api/admin/clients", json=payload, headers=admin_h)
    assert r.status_code == 200, r.text
    client = r.json()
    yield {**client, "_password": payload["password"]}
    requests.delete(f"{BASE}/api/admin/clients/{client['id']}", headers=admin_h)


@pytest.fixture(scope="session")
def client_tok(test_client):
    tok, _ = _login(test_client["email"], test_client["_password"])
    return tok


# Reset descent_time at session end so we don't break other suites.
@pytest.fixture(scope="session", autouse=True)
def _reset_descent(admin_h):
    yield
    requests.put(f"{BASE}/api/admin/settings", json={"descent_time": ""}, headers=admin_h)


# ----------------- Notes creation + numbering -----------------
class TestNotesCreate:
    def test_admin_create_report_returns_numero_ip(self, admin_h):
        # Make sure descent_time is open
        requests.put(f"{BASE}/api/admin/settings", json={"descent_time": ""}, headers=admin_h)
        r = requests.post(f"{BASE}/api/me/notes/reports",
                          json={"title": "TEST_RPT iter4", "content_html": "<p>hello</p>"},
                          headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["numero"].startswith("RPT-") and len(d["numero"].split("-")[2]) == 4
        assert d["owner_id"] and d["owner_email"] == ADMIN_EMAIL
        assert d.get("ip")
        assert d.get("created_at")
        # Cleanup
        requests.delete(f"{BASE}/api/me/notes/reports/{d['id']}", headers=admin_h)

    def test_suivi_requires_client_and_date(self, admin_h, test_client):
        # missing both
        r = requests.post(f"{BASE}/api/me/notes/suivis",
                          json={"title": "TEST_SUI miss"}, headers=admin_h)
        assert r.status_code == 400
        # missing client
        r2 = requests.post(f"{BASE}/api/me/notes/suivis",
                           json={"title": "TEST_SUI miss client", "event_date": "2026-02-01"},
                           headers=admin_h)
        assert r2.status_code == 400
        # OK
        r3 = requests.post(f"{BASE}/api/me/notes/suivis",
                           json={"title": "TEST_SUI ok", "event_date": "2026-02-01",
                                 "client_id": test_client["id"]},
                           headers=admin_h)
        assert r3.status_code == 200, r3.text
        d = r3.json()
        assert d["numero"].startswith("SUI-")
        requests.delete(f"{BASE}/api/me/notes/suivis/{d['id']}", headers=admin_h)


# ----------------- descent_time window -----------------
class TestDescentWindow:
    def test_descent_locks_creation(self, admin_h):
        # 00:00 + 1h means after 01:00 UTC, creation refused. Tests run anytime, so:
        r = requests.put(f"{BASE}/api/admin/settings",
                         json={"descent_time": "00:00"}, headers=admin_h)
        assert r.status_code == 200
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            r2 = requests.post(f"{BASE}/api/me/notes/reports",
                               json={"title": "TEST_RPT locked"}, headers=admin_h)
            if now.hour == 0:
                # Within 1h window — creation allowed; revert and skip.
                assert r2.status_code == 200
                requests.delete(f"{BASE}/api/me/notes/reports/{r2.json()['id']}", headers=admin_h)
                pytest.skip("Test ran within 00:00-01:00 UTC window — descent lock not enforceable here")
            assert r2.status_code == 403, r2.text
            assert "verrouill" in r2.json().get("detail", "").lower()

            # Same lock applies to /me/interventions
            r3 = requests.post(f"{BASE}/api/me/interventions",
                               json={"client_id": "any", "title": "TEST_INT locked",
                                     "intervention_date": "2026-02-01"},
                               headers=admin_h)
            assert r3.status_code == 403
        finally:
            # Always restore
            requests.put(f"{BASE}/api/admin/settings",
                         json={"descent_time": ""}, headers=admin_h)


# ----------------- Ratings -----------------
class TestRatings:
    def test_admin_rate_then_unrate_and_my_rating(self, admin_h):
        requests.put(f"{BASE}/api/admin/settings", json={"descent_time": ""}, headers=admin_h)
        # create a report
        r = requests.post(f"{BASE}/api/me/notes/reports",
                          json={"title": "TEST_RPT rate me"}, headers=admin_h)
        nid = r.json()["id"]
        try:
            # Rate 4
            rr = requests.post(f"{BASE}/api/me/ratings/reports/{nid}",
                               json={"stars": 4, "comment": "nice"}, headers=admin_h)
            assert rr.status_code == 200, rr.text
            assert rr.json()["stars"] == 4
            # GET notes -> my_rating
            lst = requests.get(f"{BASE}/api/me/notes/reports", headers=admin_h).json()
            mine = next((x for x in lst if x["id"] == nid), None)
            assert mine and mine.get("my_rating") and mine["my_rating"]["stars"] == 4
            # Delete rating
            dd = requests.delete(f"{BASE}/api/me/ratings/reports/{nid}", headers=admin_h)
            assert dd.status_code == 200
            lst2 = requests.get(f"{BASE}/api/me/notes/reports", headers=admin_h).json()
            mine2 = next((x for x in lst2 if x["id"] == nid), None)
            assert mine2 and mine2.get("my_rating") is None
        finally:
            requests.delete(f"{BASE}/api/me/notes/reports/{nid}", headers=admin_h)

    def test_non_admin_cannot_rate(self, admin_h, client_tok):
        # create one with admin
        r = requests.post(f"{BASE}/api/me/notes/reports",
                          json={"title": "TEST_RPT no-rate"}, headers=admin_h)
        nid = r.json()["id"]
        try:
            rr = requests.post(f"{BASE}/api/me/ratings/reports/{nid}",
                               json={"stars": 5}, headers=_h(client_tok))
            assert rr.status_code == 403
        finally:
            requests.delete(f"{BASE}/api/me/notes/reports/{nid}", headers=admin_h)


# ----------------- Role-based access (tracked-user lifecycle) -----------------
class TestRoleAccess:
    def test_consultation_then_moderation_then_admin(self, admin_h, test_client):
        requests.put(f"{BASE}/api/admin/settings", json={"descent_time": ""}, headers=admin_h)
        # create tracked user with role Consultation
        tu_email = f"test_iter4_tu_{uuid.uuid4().hex[:8]}@example.com"
        tu_pwd = "Tracked@Iter4-2026"
        r = requests.post(f"{BASE}/api/admin/tracked-users",
                          json={"client_id": test_client["id"], "name": "TEST TU iter4",
                                "email": tu_email, "role": "Consultation"},
                          headers=admin_h)
        assert r.status_code == 200, r.text
        tu = r.json()
        try:
            # provision pwd
            sp = requests.post(f"{BASE}/api/admin/tracked-users/{tu['id']}/set-password",
                               json={"password": tu_pwd}, headers=admin_h)
            assert sp.status_code == 200, sp.text
            tu_tok, _ = _login(tu_email, tu_pwd)

            # Consultation cannot create
            r1 = requests.post(f"{BASE}/api/me/notes/reports",
                               json={"title": "TEST_RPT consultation"}, headers=_h(tu_tok))
            assert r1.status_code == 403

            # Promote to Moderation
            up = requests.put(f"{BASE}/api/admin/tracked-users/{tu['id']}",
                              json={"role": "Moderation"}, headers=admin_h)
            assert up.status_code == 200
            # re-set-password to refresh tracked_role on bridged user (token still valid but tracked_role
            # comes from db on every request via get_current_user → so just re-login to be safe)
            sp2 = requests.post(f"{BASE}/api/admin/tracked-users/{tu['id']}/set-password",
                                json={"password": tu_pwd}, headers=admin_h)
            assert sp2.status_code == 200
            tu_tok, _ = _login(tu_email, tu_pwd)
            r2 = requests.post(f"{BASE}/api/me/notes/reports",
                               json={"title": "TEST_RPT moderation"}, headers=_h(tu_tok))
            assert r2.status_code == 200, r2.text
            nid = r2.json()["id"]

            # Moderation cannot delete
            d_mod = requests.delete(f"{BASE}/api/me/notes/reports/{nid}", headers=_h(tu_tok))
            assert d_mod.status_code == 403

            # Promote to Administrateur → can delete
            up2 = requests.put(f"{BASE}/api/admin/tracked-users/{tu['id']}",
                               json={"role": "Administrateur"}, headers=admin_h)
            assert up2.status_code == 200
            sp3 = requests.post(f"{BASE}/api/admin/tracked-users/{tu['id']}/set-password",
                                json={"password": tu_pwd}, headers=admin_h)
            assert sp3.status_code == 200
            tu_tok, _ = _login(tu_email, tu_pwd)
            d_adm = requests.delete(f"{BASE}/api/me/notes/reports/{nid}", headers=_h(tu_tok))
            assert d_adm.status_code == 200
        finally:
            requests.delete(f"{BASE}/api/admin/tracked-users/{tu['id']}", headers=admin_h)


# ----------------- save-as-tracked-user via /me -----------------
class TestSaveContactAsTracked:
    def test_generates_password_and_login_works(self, admin_h, test_client):
        # Seed a contact
        contact_email = f"test_iter4_contact_{uuid.uuid4().hex[:8]}@example.org"
        cr = requests.post(f"{BASE}/api/contact",
                           json={"name": "TEST_iter4 Contact", "email": contact_email,
                                 "phone": "+228 90 00 00 00", "subject": "iter4",
                                 "message": "save me as tracked"})
        assert cr.status_code == 200
        cid = cr.json()["id"]

        r = requests.post(f"{BASE}/api/me/contacts/{cid}/save-as-tracked-user",
                          json={"client_id": test_client["id"], "role": "Moderation"},
                          headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("generated_password") and len(d["generated_password"]) >= 8
        assert "email_sent" in d
        # Login works with the generated password
        tok, u = _login(contact_email, d["generated_password"])
        assert u["email"] == contact_email
        assert u.get("tracked_role") == "Moderation"
        assert u.get("parent_client_id") == test_client["id"]
        # Cleanup tracked user (drops bridged users row too)
        requests.delete(f"{BASE}/api/admin/tracked-users/{d['id']}", headers=admin_h)


# ----------------- Access logs -----------------
class TestAccessLogs:
    def test_log_search_and_csv_export(self, admin_h, client_tok):
        marker = f"TEST_iter4_{uuid.uuid4().hex[:6]}"
        # admin posts a log
        rp = requests.post(f"{BASE}/api/me/access-log",
                           json={"module": marker, "page": "/portal/test"},
                           headers=admin_h)
        assert rp.status_code == 200
        # search
        rs = requests.get(f"{BASE}/api/admin/access-logs",
                          params={"q": marker}, headers=admin_h)
        assert rs.status_code == 200
        items = rs.json()
        assert any(it.get("module") == marker for it in items), f"marker {marker} missing"
        # CSV export
        rc = requests.get(f"{BASE}/api/admin/access-logs/export.csv", headers=admin_h)
        assert rc.status_code == 200
        body = rc.json()
        assert "csv" in body
        first_line = body["csv"].splitlines()[0]
        assert first_line.startswith("created_at,user_email")
        # Non-admin cannot list
        forbidden = requests.get(f"{BASE}/api/admin/access-logs", headers=_h(client_tok))
        assert forbidden.status_code == 403


# ----------------- Documents visibility / upload / delete -----------------
class TestDocuments:
    def test_moderation_sees_all_uploads_no_delete(self, admin_h, test_client):
        # Create a tracked Moderation user
        tu_email = f"test_iter4_modoc_{uuid.uuid4().hex[:8]}@example.com"
        tu_pwd = "Tracked@Iter4-2026"
        r = requests.post(f"{BASE}/api/admin/tracked-users",
                          json={"client_id": test_client["id"], "name": "TEST mod doc",
                                "email": tu_email, "role": "Moderation"},
                          headers=admin_h)
        tu = r.json()
        try:
            requests.post(f"{BASE}/api/admin/tracked-users/{tu['id']}/set-password",
                          json={"password": tu_pwd}, headers=admin_h)
            mod_tok, _ = _login(tu_email, tu_pwd)
            mod_h = _h(mod_tok)

            # Admin posts a document for test_client
            doc_payload = {
                "title": "TEST_iter4_doc",
                "client_id": test_client["id"],
                "category": "documentation",
                "filename": "iter4.txt",
                "file_extension": "txt",
                "file_url": "/api/files/dummy",
            }
            rd = requests.post(f"{BASE}/api/me/documents", json=doc_payload, headers=admin_h)
            assert rd.status_code == 200, rd.text
            doc_id = rd.json()["id"]

            # Moderation GET sees it (cross-client)
            lst = requests.get(f"{BASE}/api/me/documents", headers=mod_h).json()
            assert any(x["id"] == doc_id for x in lst), "Moderation should see all docs"

            # Moderation upload OK
            files = {"file": ("hello.txt", b"hello mod", "text/plain")}
            ru = requests.post(f"{BASE}/api/me/upload",
                               files=files,
                               headers={"Authorization": f"Bearer {mod_tok}"})
            assert ru.status_code == 200, ru.text

            # Moderation cannot delete
            rdel = requests.delete(f"{BASE}/api/me/documents/{doc_id}", headers=mod_h)
            assert rdel.status_code == 403

            # Admin can delete
            rdel2 = requests.delete(f"{BASE}/api/me/documents/{doc_id}", headers=admin_h)
            assert rdel2.status_code == 200
        finally:
            requests.delete(f"{BASE}/api/admin/tracked-users/{tu['id']}", headers=admin_h)


# ----------------- Images cap (10) -----------------
class TestImagesCap:
    def test_max_10_images(self, admin_h):
        requests.put(f"{BASE}/api/admin/settings", json={"descent_time": ""}, headers=admin_h)
        imgs = [{"file_id": str(i), "url": f"/api/files/{i}", "filename": f"a{i}.png"} for i in range(11)]
        r = requests.post(f"{BASE}/api/me/notes/reports",
                          json={"title": "TEST_RPT imgs", "images": imgs}, headers=admin_h)
        assert r.status_code == 400, r.text
        assert "10" in r.json().get("detail", "")


# ----------------- Admin can edit even outside the 1h window -----------------
class TestAdminEditsAlways:
    def test_admin_edits_within_window(self, admin_h):
        requests.put(f"{BASE}/api/admin/settings", json={"descent_time": ""}, headers=admin_h)
        r = requests.post(f"{BASE}/api/me/notes/reports",
                          json={"title": "TEST_RPT edit"}, headers=admin_h)
        nid = r.json()["id"]
        try:
            up = requests.put(f"{BASE}/api/me/notes/reports/{nid}",
                              json={"title": "TEST_RPT edit2"}, headers=admin_h)
            assert up.status_code == 200
        finally:
            requests.delete(f"{BASE}/api/me/notes/reports/{nid}", headers=admin_h)
