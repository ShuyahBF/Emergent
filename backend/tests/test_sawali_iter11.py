"""SAWALI — Iteration 11 backend tests: Admin WhatsApp Messaging module.

Coverage:
- GET /api/admin/messaging/audience requires admin (401 unauth, 403 non-admin)
  and returns {clients, tracked_users} with row fields + has_phone flag.
- POST /api/admin/messaging/bulk-send validations:
  * 400 empty recipients
  * 400 empty template_name
  * 401 unauth, 403 non-admin
- bulk-send happy path (Meta NOT configured): per-recipient ok=false with
  error 'WhatsApp non configuré ...' and the wrapper returns
  {requested, sent_ok, sent_ko, skipped, results[]} with bulk=true logged.
- bulk-send: client recipient WITHOUT phone -> ends up in skipped[] (not results).
- bulk-send: tracked-user resolution from tracked_users collection — a tracked
  user with a phone gets attempted (recipient_kind='tracked', tracked_user_id set
  in whatsapp_messages collection).
- GET /api/admin/messaging/history returns desc-sorted whatsapp_messages
  (admin-only, 403 non-admin).
- Regression: /api/me/whatsapp/send (validation 400 on missing fields) and
  /api/me/whatsapp/history (200 list) still respond for admin.
"""
import os
import uuid
import datetime as dt
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
        assert d.get("dev_otp"), f"dev_otp expected, got {d}"
        r2 = sess.post(f"{BASE}/api/auth/verify-otp",
                       json={"session_token": d["session_token"], "code": d["dev_otp"]})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        return body["access_token"], body["user"]
    return d["access_token"], d["user"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ----- shared fixtures -----------------------------------------------------
@pytest.fixture(scope="session")
def admin():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert u["role"] == "admin"
    return tok, u


@pytest.fixture(scope="session")
def admin_h(admin):
    return _h(admin[0])


@pytest.fixture(scope="session")
def secondary_client(admin_h):
    """Create non-admin client used for 403 tests; teardown deletes it."""
    email = f"test_iter11_cli_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "IterEleven!2026"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Iter11 Client", "password": pwd, "role": "client",
        "client_code": f"IT11{uuid.uuid4().hex[:3].upper()}",
    })
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    tok, _ = _login(email, pwd)
    yield {"id": uid, "email": email, "token": tok}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


@pytest.fixture(scope="session")
def phoneless_client(admin_h):
    """A client without a phone — used to assert it lands in skipped[]."""
    email = f"test_iter11_nophone_{uuid.uuid4().hex[:6]}@example.org"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Iter11 NoPhone", "password": "Whatever!2026", "role": "client",
        "client_code": f"IT11N{uuid.uuid4().hex[:2].upper()}",
        # explicit empty phone
        "phone": "",
    })
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    yield {"id": uid, "email": email}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


@pytest.fixture(scope="session")
def tracked_with_phone(admin_h):
    """Create a tracked-user with an E.164 phone via the contacts->save-as-tracked path."""
    # Need a client first
    parent_email = f"test_iter11_par_{uuid.uuid4().hex[:6]}@example.org"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": parent_email, "full_name": "Iter11 Parent", "password": "Whatever!2026",
        "role": "client", "client_code": f"IT11P{uuid.uuid4().hex[:2].upper()}",
    })
    assert r.status_code in (200, 201), r.text
    parent_id = r.json()["id"]
    # 1) public contact submission carrying a phone
    contact_email = f"test_iter11_tr_{uuid.uuid4().hex[:6]}@example.org"
    rc = requests.post(f"{BASE}/api/contact", json={
        "name": "Iter11 Tracked",
        "email": contact_email,
        "phone": "+22500000123",
        "company": "ITC",
        "subject": "Iter11 fixture",
        "message": "fixture",
    })
    assert rc.status_code in (200, 201), rc.text
    contact_id = rc.json()["id"]
    # 2) admin saves contact as tracked user (this path persists phone)
    rs = requests.post(
        f"{BASE}/api/admin/contacts/{contact_id}/save-as-tracked-user",
        headers=admin_h,
        json={"client_id": parent_id, "role": "Consultation"},
    )
    assert rs.status_code in (200, 201), rs.text
    tu = rs.json()
    yield {"id": tu["id"], "phone": "+22500000123", "client_id": parent_id, "email": contact_email}
    # Teardown
    try:
        requests.delete(f"{BASE}/api/admin/tracked-users/{tu['id']}", headers=admin_h)
    except Exception:
        pass
    try:
        requests.delete(f"{BASE}/api/admin/contacts/{contact_id}", headers=admin_h)
    except Exception:
        pass
    requests.delete(f"{BASE}/api/admin/clients/{parent_id}", headers=admin_h)


# ----- 1) Audience endpoint ------------------------------------------------
class TestAudience:
    def test_audience_requires_auth(self):
        r = requests.get(f"{BASE}/api/admin/messaging/audience")
        assert r.status_code in (401, 403), r.text

    def test_audience_forbidden_for_non_admin(self, secondary_client):
        r = requests.get(f"{BASE}/api/admin/messaging/audience",
                         headers=_h(secondary_client["token"]))
        assert r.status_code == 403, r.text

    def test_audience_admin_returns_payload(self, admin_h, secondary_client, tracked_with_phone):
        r = requests.get(f"{BASE}/api/admin/messaging/audience", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "clients" in d and isinstance(d["clients"], list)
        assert "tracked_users" in d and isinstance(d["tracked_users"], list)
        # Validate row shape on one client
        sample = next((c for c in d["clients"] if c["id"] == secondary_client["id"]), None)
        assert sample is not None, "secondary client missing from audience"
        for k in ("kind", "id", "full_name", "email", "phone", "has_phone"):
            assert k in sample, f"missing key {k} in client row"
        assert sample["kind"] == "client"
        assert isinstance(sample["has_phone"], bool)
        # Tracked rows must include client_label
        tr = next((t for t in d["tracked_users"] if t["id"] == tracked_with_phone["id"]), None)
        assert tr is not None, "tracked user missing from audience"
        assert tr["kind"] == "tracked"
        assert tr["has_phone"] is True
        assert tr["phone"] == tracked_with_phone["phone"]
        assert "client_label" in tr


# ----- 2) Bulk send validations & auth ------------------------------------
class TestBulkSendValidation:
    def test_unauth_blocked(self):
        r = requests.post(f"{BASE}/api/admin/messaging/bulk-send",
                          json={"recipients": [], "template_name": "hello_world"})
        assert r.status_code in (401, 403), r.text

    def test_non_admin_forbidden(self, secondary_client):
        r = requests.post(f"{BASE}/api/admin/messaging/bulk-send",
                          headers=_h(secondary_client["token"]),
                          json={"recipients": [{"kind": "raw", "phone": "+22500000000"}],
                                "template_name": "hello_world"})
        assert r.status_code == 403, r.text

    def test_400_empty_recipients(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/messaging/bulk-send", headers=admin_h,
                          json={"recipients": [], "template_name": "hello_world"})
        assert r.status_code == 400, r.text

    def test_400_empty_template(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/messaging/bulk-send", headers=admin_h,
                          json={"recipients": [{"kind": "raw", "phone": "+22500000000"}],
                                "template_name": ""})
        assert r.status_code == 400, r.text


# ----- 3) Bulk send happy path (Meta not configured) ----------------------
class TestBulkSendHappyPath:
    def test_send_with_explicit_phone_logs_failure_correctly(self, admin_h, secondary_client):
        payload = {
            "recipients": [
                {"kind": "client", "id": secondary_client["id"], "phone": "+22500000111"}
            ],
            "template_name": "hello_world",
            "language_code": "fr",
        }
        r = requests.post(f"{BASE}/api/admin/messaging/bulk-send",
                          headers=admin_h, json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        # wrapper contract
        for k in ("requested", "sent_ok", "sent_ko", "skipped", "results"):
            assert k in d, f"missing {k} in wrapper"
        assert d["requested"] == 1
        assert d["sent_ok"] == 0
        assert d["sent_ko"] == 1
        assert d["skipped"] == []
        res = d["results"][0]
        assert res["ok"] is False
        assert res["phone"] == "+22500000111"
        assert res["kind"] == "client"
        # Meta-not-configured wrapper error
        assert "configur" in (res.get("error") or "").lower(), f"unexpected error: {res.get('error')}"

    def test_skipped_when_no_phone(self, admin_h, phoneless_client):
        payload = {
            "recipients": [{"kind": "client", "id": phoneless_client["id"]}],
            "template_name": "hello_world",
            "language_code": "fr",
        }
        r = requests.post(f"{BASE}/api/admin/messaging/bulk-send",
                          headers=admin_h, json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["requested"] == 1
        assert d["sent_ok"] == 0
        assert d["sent_ko"] == 0
        assert d["results"] == []
        assert len(d["skipped"]) == 1
        assert "téléphone" in d["skipped"][0]["reason"].lower() or "telephone" in d["skipped"][0]["reason"].lower()

    def test_tracked_user_phone_is_resolved_and_logged(self, admin_h, tracked_with_phone):
        payload = {
            "recipients": [{"kind": "tracked", "id": tracked_with_phone["id"]}],
            "template_name": "hello_world",
            "language_code": "fr",
        }
        r = requests.post(f"{BASE}/api/admin/messaging/bulk-send",
                          headers=admin_h, json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["requested"] == 1
        assert d["skipped"] == []
        assert len(d["results"]) == 1
        res = d["results"][0]
        assert res["kind"] == "tracked"
        assert res["phone"] == tracked_with_phone["phone"]
        assert res["ok"] is False  # Meta not configured
        # History should now contain a bulk=true tracked entry for this phone
        h = requests.get(f"{BASE}/api/admin/messaging/history?limit=50", headers=admin_h)
        assert h.status_code == 200, h.text
        items = h.json()
        assert isinstance(items, list)
        match = next((m for m in items
                      if m.get("to") == tracked_with_phone["phone"]
                      and m.get("recipient_kind") == "tracked"
                      and m.get("tracked_user_id") == tracked_with_phone["id"]
                      and m.get("bulk") is True), None)
        assert match is not None, f"tracked bulk entry not found in history (first 5={items[:5]})"


# ----- 4) History endpoint -------------------------------------------------
class TestHistory:
    def test_history_requires_admin(self, secondary_client):
        r = requests.get(f"{BASE}/api/admin/messaging/history?limit=5",
                         headers=_h(secondary_client["token"]))
        assert r.status_code == 403, r.text

    def test_history_admin_desc_sorted(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/messaging/history?limit=20", headers=admin_h)
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        # Sorted desc by created_at when present
        ts = [i.get("created_at") for i in items if i.get("created_at")]
        assert ts == sorted(ts, reverse=True), "history not desc-sorted by created_at"


# ----- 5) Regression — existing /me/whatsapp endpoints still work ---------
class TestRegressionMeWhatsapp:
    def test_me_whatsapp_history_admin(self, admin_h):
        r = requests.get(f"{BASE}/api/me/whatsapp/history?limit=5", headers=admin_h)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_me_whatsapp_send_validates(self, admin_h):
        # missing 'to' → expect 4xx (Pydantic 422 or our 400)
        r = requests.post(f"{BASE}/api/me/whatsapp/send", headers=admin_h,
                          json={"template_name": "hello_world"})
        assert r.status_code in (400, 422), r.text
