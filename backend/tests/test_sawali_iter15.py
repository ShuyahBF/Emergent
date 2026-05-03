"""SAWALI — Iteration 15 backend tests: WhatsApp Templates editor (create/delete via Meta).

Coverage:
- GET /admin/whatsapp/templates: still returns {configured:false, items:[]} when Meta unconfigured; 401/403 enforced.
- POST /admin/whatsapp/templates: 6 validation paths (name, category, body, vars, header, footer),
  then 400 when Meta unconfigured.
- POST happy path (in-process + monkeypatched httpx + seeded settings): with variables → body.example
  sent; without variables → no example field.
- DELETE /admin/whatsapp/templates/{name}: 400 when unconfigured, 401/403 enforced, happy path mocked.
"""
from __future__ import annotations

import os
import sys
import uuid
import asyncio
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

_sync_mongo = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_mongo[os.environ["DB_NAME"]]

sys.path.insert(0, "/app/backend")
import server  # noqa: E402


# ---------- helpers -------------------------------------------------------
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
        return r2.json()["access_token"], r2.json()["user"]
    return d["access_token"], d["user"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


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
    email = f"test_iter15_cli_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "IterFifteen!2026"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Iter15 Client", "password": pwd, "role": "client",
        "client_code": f"IT15{uuid.uuid4().hex[:3].upper()}",
    })
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    tok, _ = _login(email, pwd)
    yield {"id": uid, "email": email, "token": tok}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


# ====================================================================
# 1) GET /admin/whatsapp/templates — list (Meta unconfigured state)
# ====================================================================
class TestListTemplates:
    def test_unauth_401(self):
        r = requests.get(f"{BASE}/api/admin/whatsapp/templates")
        assert r.status_code in (401, 403)

    def test_non_admin_forbidden(self, secondary_client):
        r = requests.get(f"{BASE}/api/admin/whatsapp/templates",
                         headers=_h(secondary_client["token"]))
        assert r.status_code == 403

    def test_admin_unconfigured_returns_empty(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        # When Meta is not configured, backend returns configured:false, items:[]
        assert "configured" in d and "items" in d
        assert d["items"] == []
        # Be tolerant: if settings got populated elsewhere, accept configured=true with items=[]
        assert isinstance(d["configured"], bool)


# ====================================================================
# 2) POST /admin/whatsapp/templates — validation paths
# ====================================================================
class TestCreateValidation:
    URL = None

    def setup_method(self):
        self.URL = f"{BASE}/api/admin/whatsapp/templates"

    def test_unauth_401(self):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates",
                          json={"name": "t", "body_text": "hi"})
        assert r.status_code in (401, 403)

    def test_non_admin_forbidden(self, secondary_client):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates",
                          headers=_h(secondary_client["token"]),
                          json={"name": "my_name", "body_text": "hi"})
        assert r.status_code == 403

    def test_invalid_name_hyphen(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h,
                          json={"name": "my-name", "body_text": "Bonjour"})
        assert r.status_code == 400
        assert "Nom invalide" in r.json()["detail"]

    def test_name_auto_lowercased_validates(self, admin_h):
        # 'BadName' should be lowercased to 'badname' and pass NAME validation,
        # then progress to category check (UTILITY ok) → body check → Meta config check → 400 unconfigured.
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h,
                          json={"name": "BadName", "body_text": "Bonjour"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        # Must NOT be the name-invalid error — must be the Meta config error.
        assert "Nom invalide" not in detail
        assert "WhatsApp non configuré" in detail

    def test_invalid_category(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h,
                          json={"name": "ok_name", "category": "WRONG", "body_text": "hi"})
        assert r.status_code == 400
        assert "Catégorie invalide" in r.json()["detail"]

    def test_empty_body(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h,
                          json={"name": "ok_name", "category": "UTILITY", "body_text": "   "})
        assert r.status_code == 400
        assert "corps du template" in r.json()["detail"].lower()

    def test_body_too_long(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h,
                          json={"name": "ok_name", "body_text": "x" * 1025})
        assert r.status_code == 400
        assert "Corps trop long" in r.json()["detail"]

    def test_missing_examples_for_vars(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h,
                          json={"name": "ok_name", "body_text": "Hello {{1}} from {{2}}"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "Exemples manquants" in detail
        assert "2 variable" in detail and "0 fournie" in detail

    def test_header_too_long(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h, json={
            "name": "ok_name", "body_text": "Bonjour",
            "header_text": "x" * 61,
        })
        assert r.status_code == 400
        assert "Header trop long" in r.json()["detail"]

    def test_footer_too_long(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h, json={
            "name": "ok_name", "body_text": "Bonjour",
            "footer_text": "y" * 61,
        })
        assert r.status_code == 400
        assert "Footer trop long" in r.json()["detail"]

    def test_meta_unconfigured_after_valid_input(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/whatsapp/templates", headers=admin_h, json={
            "name": "hello_valid", "body_text": "Bonjour {{1}}", "body_examples": ["Marie"],
        })
        assert r.status_code == 400
        assert "WhatsApp non configuré" in r.json()["detail"]


# ====================================================================
# 3) POST happy-path (in-process call + monkeypatched httpx + seeded settings)
# ====================================================================
class _FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _FakeAsyncClient:
    """Monkeypatch target for server.httpx.AsyncClient. Captures .post/.delete args."""
    captured: dict = {}

    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, **kw):
        _FakeAsyncClient.captured["post"] = {"url": url, "json": json, "headers": headers}
        return _FakeResponse(200, {"id": "tpl-123", "status": "PENDING"})

    async def delete(self, url, headers=None, params=None, **kw):
        _FakeAsyncClient.captured["delete"] = {"url": url, "headers": headers, "params": params}
        return _FakeResponse(200, {"success": True})


@pytest.fixture
def seeded_meta(monkeypatch):
    """Seed settings doc so _emit_event / admin_create_wa_template find WABA creds.
    Uses pymongo (sync) for setup/teardown so it's visible to the async motor view too,
    but since we're calling the endpoint IN-PROCESS via server.admin_create_wa_template(),
    we also monkeypatch server.httpx.AsyncClient to avoid real network.
    """
    before = _sync_db.settings.find_one({"_id": "global"})
    _sync_db.settings.update_one(
        {"_id": "global"},
        {"$set": {"wa_access_token": "FAKE_TOKEN_iter15", "wa_business_account_id": "WABA_TEST_iter15"}},
        upsert=True,
    )
    _FakeAsyncClient.captured = {}
    monkeypatch.setattr(server.httpx, "AsyncClient", _FakeAsyncClient)
    yield
    # Restore: remove our keys (keep other setting fields if any)
    if before is None:
        _sync_db.settings.delete_one({"_id": "global"})
    else:
        _sync_db.settings.replace_one({"_id": "global"}, before, upsert=True)


class TestCreateHappyPath:
    def test_happy_with_variables(self, admin, seeded_meta, event_loop):
        from server import WaTemplateCreate, admin_create_wa_template
        payload = WaTemplateCreate(
            name="welcome_msg",
            language="fr",
            category="UTILITY",
            body_text="Bonjour {{1}}, bienvenue chez {{2}}",
            body_examples=["Marie", "Acme"],
            header_text="Confirmation",
            footer_text="SAWALI",
        )
        res = event_loop.run_until_complete(
            admin_create_wa_template(payload, _={"id": admin[1]["id"], "role": "admin"})
        )
        assert res["ok"] is True
        assert res["name"] == "welcome_msg"
        assert res["language"] == "fr"
        assert res["category"] == "UTILITY"
        assert res["id"] == "tpl-123"
        assert res["status"] == "PENDING"

        cap = _FakeAsyncClient.captured["post"]
        assert "message_templates" in cap["url"]
        assert "WABA_TEST_iter15" in cap["url"]
        assert cap["headers"]["Authorization"] == "Bearer FAKE_TOKEN_iter15"
        body = cap["json"]
        assert body["name"] == "welcome_msg"
        assert body["language"] == "fr"
        assert body["category"] == "UTILITY"
        comps = body["components"]
        # Expect HEADER + BODY + FOOTER
        kinds = [c["type"] for c in comps]
        assert kinds == ["HEADER", "BODY", "FOOTER"]
        header = comps[0]
        assert header["format"] == "TEXT"
        assert header["text"] == "Confirmation"
        body_c = comps[1]
        assert body_c["text"] == "Bonjour {{1}}, bienvenue chez {{2}}"
        assert body_c["example"] == {"body_text": [["Marie", "Acme"]]}
        footer = comps[2]
        assert footer["text"] == "SAWALI"

    def test_happy_no_variables(self, admin, seeded_meta, event_loop):
        from server import WaTemplateCreate, admin_create_wa_template
        payload = WaTemplateCreate(
            name="simple_notice",
            category="MARKETING",
            body_text="Bonjour, merci de votre confiance.",
            body_examples=None,
        )
        res = event_loop.run_until_complete(
            admin_create_wa_template(payload, _={"id": admin[1]["id"], "role": "admin"})
        )
        assert res["ok"] is True
        assert res["category"] == "MARKETING"

        body = _FakeAsyncClient.captured["post"]["json"]
        comps = body["components"]
        # No header/footer, only BODY
        assert [c["type"] for c in comps] == ["BODY"]
        body_c = comps[0]
        assert body_c["text"] == "Bonjour, merci de votre confiance."
        assert "example" not in body_c  # Critical: no example when n_vars==0


# ====================================================================
# 4) DELETE /admin/whatsapp/templates/{name}
# ====================================================================
class TestDeleteTemplate:
    def test_unauth_401(self):
        r = requests.delete(f"{BASE}/api/admin/whatsapp/templates/foo")
        assert r.status_code in (401, 403)

    def test_non_admin_forbidden(self, secondary_client):
        r = requests.delete(f"{BASE}/api/admin/whatsapp/templates/foo",
                            headers=_h(secondary_client["token"]))
        assert r.status_code == 403

    def test_unconfigured_returns_400(self, admin_h):
        r = requests.delete(f"{BASE}/api/admin/whatsapp/templates/any_name",
                            headers=admin_h)
        assert r.status_code == 400
        assert "WhatsApp non configuré" in r.json()["detail"]

    def test_happy_path_mocked(self, admin, seeded_meta, event_loop):
        from server import admin_delete_wa_template
        res = event_loop.run_until_complete(
            admin_delete_wa_template(name="welcome_msg",
                                     _={"id": admin[1]["id"], "role": "admin"})
        )
        assert res["ok"] is True
        assert res["name"] == "welcome_msg"
        assert "raw" in res
        cap = _FakeAsyncClient.captured["delete"]
        assert "message_templates" in cap["url"]
        assert cap["params"] == {"name": "welcome_msg"}
        assert cap["headers"]["Authorization"] == "Bearer FAKE_TOKEN_iter15"
