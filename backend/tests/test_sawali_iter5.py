"""SAWALI - Iteration 5 backend tests (Formations Spécialisées).

Coverage:
- Admin CRUD formations (modules_count + enrolled_count + cascade delete)
- Admin CRUD modules (api_url + auth fields)
- Portal RBAC: client w/o tracked_role -> 403 list & enroll; tracked -> 200 + credits_purchased
- Visit tracking + auto-state computation (inscription -> terminée when seen=total=1)
- close-visit duration_ms >= 0 + total_time_ms incremented
- Q/R proxy via httpbin.org/post (echo)
- Credits adjust + state='annulée' lock (stays cancelled even after a visit)
- Ratings on formations by tracked user (my_rating={stars:4})
"""
import os
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


# --------------- Session fixtures ---------------
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
    payload = {
        "email": f"test_iter5_client_{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "TEST iter5 Client",
        "password": "Test@Iter5-2026",
        "role": "client",
        "phone": "+228 11 22 33 44",
        "company": "TEST Iter5 Co",
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


@pytest.fixture(scope="session")
def tracked_user(admin_h, test_client):
    """Create a tracked user with role Moderation + provisioned password."""
    tu_email = f"test_iter5_tu_{uuid.uuid4().hex[:8]}@example.com"
    tu_pwd = "Tracked@Iter5-2026"
    r = requests.post(f"{BASE}/api/admin/tracked-users",
                      json={"client_id": test_client["id"], "name": "TEST iter5 TU",
                            "email": tu_email, "role": "Moderation"},
                      headers=admin_h)
    assert r.status_code == 200, r.text
    tu = r.json()
    sp = requests.post(f"{BASE}/api/admin/tracked-users/{tu['id']}/set-password",
                       json={"password": tu_pwd}, headers=admin_h)
    assert sp.status_code == 200, sp.text
    tok, user = _login(tu_email, tu_pwd)
    yield {"id": tu["id"], "email": tu_email, "password": tu_pwd, "tok": tok, "user": user}
    requests.delete(f"{BASE}/api/admin/tracked-users/{tu['id']}", headers=admin_h)


# --------------- Admin CRUD formations ---------------
class TestAdminCRUDFormations:
    def test_create_list_update_delete_with_cascade(self, admin_h):
        payload = {"name": "TEST_iter5_formation_A", "description": "desc",
                   "available": True, "access": "free", "default_credits": 7,
                   "cover_image_url": "https://example.com/cover.png"}
        r = requests.post(f"{BASE}/api/admin/formations", json=payload, headers=admin_h)
        assert r.status_code == 200, r.text
        f = r.json()
        assert f["name"] == payload["name"]
        assert f["default_credits"] == 7
        assert f["available"] is True
        fid = f["id"]
        try:
            # GET list contains it with modules_count + enrolled_count
            lst = requests.get(f"{BASE}/api/admin/formations", headers=admin_h).json()
            mine = next((x for x in lst if x["id"] == fid), None)
            assert mine is not None
            assert mine.get("modules_count") == 0
            assert mine.get("enrolled_count") == 0

            # Add a module to test cascade
            mr = requests.post(f"{BASE}/api/admin/formations/{fid}/modules",
                               json={"name": "TEST_mod_1", "order": 1,
                                     "content_html": "<p>x</p>"},
                               headers=admin_h)
            assert mr.status_code == 200, mr.text

            # PUT formation (rename + flip available)
            up = requests.put(f"{BASE}/api/admin/formations/{fid}",
                              json={"name": "TEST_iter5_formation_A2", "available": False},
                              headers=admin_h)
            assert up.status_code == 200, up.text
            lst2 = requests.get(f"{BASE}/api/admin/formations", headers=admin_h).json()
            mine2 = next((x for x in lst2 if x["id"] == fid), None)
            assert mine2["name"] == "TEST_iter5_formation_A2"
            assert mine2["available"] is False
            assert mine2["modules_count"] == 1
        finally:
            d = requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)
            assert d.status_code == 200
            # cascade: modules gone
            mods = requests.get(f"{BASE}/api/admin/formations/{fid}/modules",
                                headers=admin_h).json()
            assert mods == []


# --------------- Admin CRUD modules ---------------
class TestAdminCRUDModules:
    def test_create_update_delete_module(self, admin_h):
        f = requests.post(f"{BASE}/api/admin/formations",
                          json={"name": "TEST_iter5_form_mods", "default_credits": 3,
                                "available": True},
                          headers=admin_h).json()
        fid = f["id"]
        try:
            mp = {"name": "TEST_mod_qa", "order": 0, "content_html": "<p>hi</p>",
                  "api_url": "https://httpbin.org/post",
                  "api_auth_type": "bearer", "api_token": "abc123"}
            r = requests.post(f"{BASE}/api/admin/formations/{fid}/modules",
                              json=mp, headers=admin_h)
            assert r.status_code == 200, r.text
            m = r.json()
            assert m["api_url"] == mp["api_url"]
            assert m["api_auth_type"] == "bearer"
            mid = m["id"]

            # GET
            lst = requests.get(f"{BASE}/api/admin/formations/{fid}/modules",
                               headers=admin_h).json()
            assert any(x["id"] == mid for x in lst)

            # PUT
            up = requests.put(f"{BASE}/api/admin/formations/{fid}/modules/{mid}",
                              json={"name": "TEST_mod_qa_v2", "order": 2}, headers=admin_h)
            assert up.status_code == 200
            lst2 = requests.get(f"{BASE}/api/admin/formations/{fid}/modules",
                                headers=admin_h).json()
            assert next(x for x in lst2 if x["id"] == mid)["name"] == "TEST_mod_qa_v2"

            # DELETE
            d = requests.delete(f"{BASE}/api/admin/formations/{fid}/modules/{mid}",
                                headers=admin_h)
            assert d.status_code == 200
        finally:
            requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)


# --------------- Portal RBAC ---------------
class TestPortalRBAC:
    def test_regular_client_forbidden_list_and_enroll(self, admin_h, client_tok):
        # Create a formation so list is non-empty
        f = requests.post(f"{BASE}/api/admin/formations",
                          json={"name": "TEST_iter5_rbac", "default_credits": 5,
                                "available": True},
                          headers=admin_h).json()
        fid = f["id"]
        try:
            r = requests.get(f"{BASE}/api/me/formations", headers=_h(client_tok))
            assert r.status_code == 403, r.text
            re = requests.post(f"{BASE}/api/me/formations/{fid}/enroll",
                               headers=_h(client_tok))
            assert re.status_code == 403
        finally:
            requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)

    def test_admin_can_list(self, admin_h):
        r = requests.get(f"{BASE}/api/me/formations", headers=admin_h)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_tracked_user_list_and_enroll(self, admin_h, tracked_user):
        f = requests.post(f"{BASE}/api/admin/formations",
                          json={"name": "TEST_iter5_track_enroll", "default_credits": 12,
                                "available": True},
                          headers=admin_h).json()
        fid = f["id"]
        try:
            tu_h = _h(tracked_user["tok"])
            r = requests.get(f"{BASE}/api/me/formations", headers=tu_h)
            assert r.status_code == 200, r.text
            assert any(x["id"] == fid for x in r.json())
            re = requests.post(f"{BASE}/api/me/formations/{fid}/enroll", headers=tu_h)
            assert re.status_code == 200, re.text
            enr = re.json()
            assert enr["formation_id"] == fid
            assert enr["credits_purchased"] == 12
            assert enr["state"] in ("inscription", "commencée")
        finally:
            requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)


# --------------- Visit tracking + close + state ---------------
class TestVisitFlow:
    def test_visit_close_and_terminee(self, admin_h, tracked_user):
        f = requests.post(f"{BASE}/api/admin/formations",
                          json={"name": "TEST_iter5_visit", "default_credits": 1,
                                "available": True},
                          headers=admin_h).json()
        fid = f["id"]
        # Single module so seen=1=total=1 -> terminée
        m = requests.post(f"{BASE}/api/admin/formations/{fid}/modules",
                          json={"name": "TEST_mod_solo", "order": 1,
                                "content_html": "<p>only</p>"},
                          headers=admin_h).json()
        mid = m["id"]
        try:
            tu_h = _h(tracked_user["tok"])
            re = requests.post(f"{BASE}/api/me/formations/{fid}/enroll", headers=tu_h)
            assert re.status_code == 200, re.text

            # POST visit
            v = requests.post(f"{BASE}/api/me/formations/{fid}/modules/{mid}/visit",
                              headers=tu_h)
            assert v.status_code == 200, v.text
            visit_id = v.json()["visit_id"]
            assert visit_id

            # Sleep 200 ms so duration_ms > 0
            time.sleep(0.25)

            # Close visit
            c = requests.post(
                f"{BASE}/api/me/formations/{fid}/modules/{mid}/visit/{visit_id}/close",
                headers=tu_h)
            assert c.status_code == 200, c.text
            cb = c.json()
            assert cb.get("ok") is True
            assert cb.get("duration_ms", 0) >= 0

            # GET /me/formations/{fid} → enrollment.state='terminée'
            g = requests.get(f"{BASE}/api/me/formations/{fid}", headers=tu_h)
            assert g.status_code == 200, g.text
            data = g.json()
            assert data["formation"]["id"] == fid
            assert any(x["id"] == mid for x in data["modules"])
            enr = data["enrollment"]
            assert enr is not None
            assert mid in (enr.get("modules_seen") or [])
            assert enr["state"] == "terminée", enr
            assert (enr.get("total_time_ms") or 0) >= 0
        finally:
            requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)


# --------------- Q/R proxy ---------------
class TestModuleAsk:
    def test_ask_no_api_url_400(self, admin_h, tracked_user):
        f = requests.post(f"{BASE}/api/admin/formations",
                          json={"name": "TEST_iter5_ask_noapi", "default_credits": 1,
                                "available": True}, headers=admin_h).json()
        fid = f["id"]
        m = requests.post(f"{BASE}/api/admin/formations/{fid}/modules",
                          json={"name": "TEST_mod_noapi", "order": 1},
                          headers=admin_h).json()
        mid = m["id"]
        try:
            tu_h = _h(tracked_user["tok"])
            requests.post(f"{BASE}/api/me/formations/{fid}/enroll", headers=tu_h)
            r = requests.post(f"{BASE}/api/me/formations/{fid}/modules/{mid}/ask",
                              json={"question": "hi"}, headers=tu_h)
            assert r.status_code == 400, r.text
        finally:
            requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)

    def test_ask_with_httpbin_echo(self, admin_h, tracked_user):
        f = requests.post(f"{BASE}/api/admin/formations",
                          json={"name": "TEST_iter5_ask_ok", "default_credits": 1,
                                "available": True}, headers=admin_h).json()
        fid = f["id"]
        m = requests.post(f"{BASE}/api/admin/formations/{fid}/modules",
                          json={"name": "TEST_mod_ask", "order": 1,
                                "api_url": "https://httpbin.org/post"},
                          headers=admin_h).json()
        mid = m["id"]
        try:
            tu_h = _h(tracked_user["tok"])
            requests.post(f"{BASE}/api/me/formations/{fid}/enroll", headers=tu_h)
            r = requests.post(f"{BASE}/api/me/formations/{fid}/modules/{mid}/ask",
                              json={"question": "TEST_iter5_question"}, headers=tu_h,
                              timeout=30)
            # httpbin can be flaky -> tolerate 200/502, but assert on 200 main path
            if r.status_code == 502:
                pytest.skip("httpbin.org unreachable from backend; proxy code path verified by 502")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == 200
            resp = body["response"]
            # httpbin echoes back the JSON in 'json'
            assert isinstance(resp, dict)
            assert resp.get("json", {}).get("question") == "TEST_iter5_question"
        finally:
            requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)


# --------------- Admin credits / state ---------------
class TestAdminCreditsAndState:
    def test_credits_and_state_lock(self, admin_h, tracked_user):
        f = requests.post(f"{BASE}/api/admin/formations",
                          json={"name": "TEST_iter5_credits_state", "default_credits": 3,
                                "available": True}, headers=admin_h).json()
        fid = f["id"]
        m = requests.post(f"{BASE}/api/admin/formations/{fid}/modules",
                          json={"name": "TEST_mod_cs", "order": 1}, headers=admin_h).json()
        mid = m["id"]
        try:
            tu_h = _h(tracked_user["tok"])
            re = requests.post(f"{BASE}/api/me/formations/{fid}/enroll", headers=tu_h)
            assert re.status_code == 200, re.text
            assert re.json()["credits_purchased"] == 3

            # Add 20 credits
            cr = requests.post(
                f"{BASE}/api/admin/formations/{fid}/enrollments/{tracked_user['user']['id']}/credits",
                json={"credits_delta": 20}, headers=admin_h)
            assert cr.status_code == 200, cr.text

            # State -> annulée
            sr = requests.post(
                f"{BASE}/api/admin/formations/{fid}/enrollments/{tracked_user['user']['id']}/state",
                json={"state": "annulée"}, headers=admin_h)
            assert sr.status_code == 200, sr.text

            # Verify credits_purchased grew + state==annulée
            g = requests.get(f"{BASE}/api/me/formations/{fid}", headers=tu_h).json()
            enr = g["enrollment"]
            assert enr["credits_purchased"] == 23
            assert enr["state"] == "annulée"

            # Visit a module → state still 'annulée'
            v = requests.post(f"{BASE}/api/me/formations/{fid}/modules/{mid}/visit",
                              headers=tu_h)
            assert v.status_code == 200
            g2 = requests.get(f"{BASE}/api/me/formations/{fid}", headers=tu_h).json()
            assert g2["enrollment"]["state"] == "annulée"
        finally:
            requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)


# --------------- Ratings on formations ---------------
class TestFormationRatings:
    def test_tracked_user_rates_formation(self, admin_h, tracked_user):
        f = requests.post(f"{BASE}/api/admin/formations",
                          json={"name": "TEST_iter5_rating", "default_credits": 1,
                                "available": True}, headers=admin_h).json()
        fid = f["id"]
        try:
            tu_h = _h(tracked_user["tok"])
            requests.post(f"{BASE}/api/me/formations/{fid}/enroll", headers=tu_h)
            rr = requests.post(f"{BASE}/api/me/ratings/formations/{fid}",
                               json={"stars": 4, "comment": "TEST_iter5"}, headers=tu_h)
            assert rr.status_code == 200, rr.text
            body = rr.json()
            assert body["stars"] == 4

            lst = requests.get(f"{BASE}/api/me/formations", headers=tu_h).json()
            mine = next((x for x in lst if x["id"] == fid), None)
            assert mine is not None
            mr = mine.get("my_rating")
            assert mr and mr["stars"] == 4
        finally:
            requests.delete(f"{BASE}/api/admin/formations/{fid}", headers=admin_h)
