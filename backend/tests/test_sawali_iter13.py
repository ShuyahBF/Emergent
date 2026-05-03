"""SAWALI — Iteration 13 backend tests: WhatsApp template DYNAMIC VARIABLES.

Coverage:
- Pure helper unit tests (direct import of server module):
  * _render_variable: known/unknown tokens, empty input, mixed text.
  * _build_recipient_ctx: returns dict with all 7 keys, dates DD/MM/YYYY format.
  * _build_components: positional body params shape; None when variables empty.
- HTTP: GET /api/admin/messaging/variable-tokens (401/403/200, shape).
- HTTP: POST /api/admin/messaging/bulk-send with `variables` field
  - monkeypatch server._wa_send_template to capture per-recipient `components`.
  - Verifies tokens are resolved against the recipient's user doc.
- HTTP: POST /api/admin/messaging/schedules persists `variables` on the doc.
- Runner: _run_scheduled_whatsapp resolves variables per-recipient at exec time
  (verified by capturing the components arg via monkeypatch).
- Regression: bulk-send & schedules without `variables` still work as before.
"""
import os
import sys
import uuid
import asyncio
import datetime as dt
import importlib
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

# Make backend importable for in-process helper / runner tests
sys.path.insert(0, "/app/backend")
import server  # noqa: E402


# ---------- helpers --------------------------------------------------------
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


def _future_iso(seconds_ahead=600):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds_ahead)).isoformat()


def _past_iso(seconds_back=120):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_back)).isoformat()


# ---------- session-scoped fixtures ----------------------------------------
# (event_loop fixture lives in /app/backend/tests/conftest.py — shared across modules)


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
    email = f"test_iter13_cli_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "IterThirteen!2026"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Iter13 Client", "password": pwd, "role": "client",
        "client_code": f"IT13{uuid.uuid4().hex[:3].upper()}",
    })
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    tok, _ = _login(email, pwd)
    yield {"id": uid, "email": email, "token": tok}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


@pytest.fixture(scope="session")
def variable_client(admin_h):
    """Client with full_name='Marie' and company='ACME' for substitution tests."""
    email = f"test_iter13_var_{uuid.uuid4().hex[:6]}@example.org"
    pwd = "VariableTest!2026"
    code = f"V13{uuid.uuid4().hex[:3].upper()}"
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json={
        "email": email, "full_name": "Marie", "password": pwd, "role": "client",
        "client_code": code, "company": "ACME", "phone": "+22500000777",
    })
    assert r.status_code in (200, 201), r.text
    body = r.json()
    uid = body["id"]
    yield {"id": uid, "email": email, "client_code": code, "full_name": "Marie", "company": "ACME"}
    requests.delete(f"{BASE}/api/admin/clients/{uid}", headers=admin_h)


# ====================================================================
# 1) PURE HELPER UNIT TESTS (in-process)
# ====================================================================
class TestRenderVariable:
    def test_empty_input_returns_empty(self):
        assert server._render_variable("", {"full_name": "X"}) == ""

    def test_known_tokens_resolved(self):
        ctx = {"full_name": "Marie", "company": "ACME"}
        out = server._render_variable("Bonjour {{full_name}} de {{company}}", ctx)
        assert out == "Bonjour Marie de ACME"

    def test_unknown_token_becomes_blank(self):
        ctx = {"full_name": "Marie", "company": "ACME"}
        out = server._render_variable(
            "Bonjour {{full_name}} de {{company}}, code: {{unknown}}", ctx
        )
        assert out == "Bonjour Marie de ACME, code: "

    def test_no_tokens_returns_static_text(self):
        assert server._render_variable("plain text", {}) == "plain text"

    def test_token_with_whitespace(self):
        ctx = {"full_name": "Marie"}
        # Regex tolerates whitespace inside braces
        assert server._render_variable("Hello {{ full_name }}", ctx) == "Hello Marie"


class TestBuildRecipientCtx:
    def test_returns_all_seven_keys(self):
        ctx = server._build_recipient_ctx("client", None, "+22500000000", "Anonymous")
        for k in ("full_name", "company", "phone", "email", "client_code", "today", "tomorrow"):
            assert k in ctx, f"missing {k}"

    def test_today_tomorrow_format_ddmmyyyy(self):
        ctx = server._build_recipient_ctx("client", None, "", None)
        # DD/MM/YYYY → exactly 10 chars with 2 slashes
        for k in ("today", "tomorrow"):
            assert len(ctx[k]) == 10
            assert ctx[k][2] == "/" and ctx[k][5] == "/"
        today = dt.datetime.now(dt.timezone.utc).date()
        tomorrow = today + dt.timedelta(days=1)
        assert ctx["today"] == today.strftime("%d/%m/%Y")
        assert ctx["tomorrow"] == tomorrow.strftime("%d/%m/%Y")

    def test_user_doc_overrides(self):
        u = {
            "full_name": "Marie", "company": "ACME", "email": "m@a.io",
            "phone": "+22500000111", "client_code": "ACME01",
        }
        ctx = server._build_recipient_ctx("client", u, "+22500000111", None)
        assert ctx["full_name"] == "Marie"
        assert ctx["company"] == "ACME"
        assert ctx["email"] == "m@a.io"
        assert ctx["client_code"] == "ACME01"
        assert ctx["phone"] == "+22500000111"

    def test_label_fallback_for_full_name(self):
        ctx = server._build_recipient_ctx("raw", None, "+225999", "Visitor")
        assert ctx["full_name"] == "Visitor"


class TestBuildComponents:
    def test_none_when_variables_empty(self):
        assert server._build_components(None, {}) is None
        assert server._build_components([], {}) is None

    def test_builds_body_with_positional_text_params(self):
        ctx = {"full_name": "Marie", "tomorrow": "31/12/2026"}
        comps = server._build_components(
            ["Bonjour {{full_name}}", "RDV {{tomorrow}}"], ctx,
        )
        assert comps == [
            {"type": "body", "parameters": [
                {"type": "text", "text": "Bonjour Marie"},
                {"type": "text", "text": "RDV 31/12/2026"},
            ]}
        ]

    def test_unknown_tokens_resolve_to_empty(self):
        ctx = {"full_name": "Marie"}
        comps = server._build_components(["{{unknown}}"], ctx)
        assert comps == [{"type": "body", "parameters": [{"type": "text", "text": ""}]}]


# ====================================================================
# 2) GET /admin/messaging/variable-tokens
# ====================================================================
class TestVariableTokensEndpoint:
    def test_unauth_401(self):
        r = requests.get(f"{BASE}/api/admin/messaging/variable-tokens")
        assert r.status_code in (401, 403)

    def test_non_admin_forbidden(self, secondary_client):
        r = requests.get(f"{BASE}/api/admin/messaging/variable-tokens",
                         headers=_h(secondary_client["token"]))
        assert r.status_code == 403

    def test_admin_returns_seven_tokens(self, admin_h):
        r = requests.get(f"{BASE}/api/admin/messaging/variable-tokens", headers=admin_h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "tokens" in body and isinstance(body["tokens"], list)
        tokens = body["tokens"]
        assert len(tokens) == 7
        keys = [t.get("token") for t in tokens]
        for must in ("{{full_name}}", "{{company}}", "{{phone}}", "{{email}}",
                     "{{client_code}}", "{{today}}", "{{tomorrow}}"):
            assert must in keys, f"missing token {must}"
        # Each entry has token, label, example
        for t in tokens:
            assert "token" in t and "label" in t and "example" in t


# ====================================================================
# 3) bulk-send with variables — monkeypatch _wa_send_template
# ====================================================================
class TestBulkSendVariables:
    """Capture the components argument passed to _wa_send_template per recipient.

    We invoke the endpoint function directly via asyncio.run (bypassing FastAPI
    TestClient which closes its loop and breaks the motor client between tests).
    """

    def _admin_user_doc(self):
        return _sync_db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})

    def test_bulk_send_resolves_variables_per_recipient(self, admin_h, variable_client, monkeypatch, event_loop):
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append({
                "phone": phone, "template_name": template_name,
                "language_code": language_code, "components": components,
            })
            return {"ok": False, "status": 0, "message_id": None, "error": "MOCKED"}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        admin_doc = self._admin_user_doc()
        assert admin_doc is not None

        payload = server.AdminBulkSendRequest(
            recipients=[{"kind": "client", "id": variable_client["id"]}],
            template_name="hello_world",
            language_code="fr",
            variables=["Bonjour {{full_name}}", "{{today}}"],
        )
        body = event_loop.run_until_complete(server.admin_messaging_bulk_send(payload, admin_doc))
        assert body["requested"] == 1
        assert len(captured) == 1, f"expected 1 send, got {len(captured)}"
        cap = captured[0]
        assert cap["template_name"] == "hello_world"
        assert cap["language_code"] == "fr"
        assert cap["phone"] == "+22500000777"
        comps = cap["components"]
        assert isinstance(comps, list) and len(comps) == 1
        assert comps[0]["type"] == "body"
        params = comps[0]["parameters"]
        assert params[0] == {"type": "text", "text": "Bonjour Marie"}
        today = dt.datetime.now(dt.timezone.utc).date().strftime("%d/%m/%Y")
        assert params[1] == {"type": "text", "text": today}

    def test_bulk_send_without_variables_passes_static_components(self, admin_h, variable_client, monkeypatch, event_loop):
        """Regression: omitting variables → fallback to payload.components (None here)."""
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append({"components": components, "phone": phone})
            return {"ok": False, "status": 0, "message_id": None, "error": "MOCKED"}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        admin_doc = self._admin_user_doc()
        payload = server.AdminBulkSendRequest(
            recipients=[{"kind": "client", "id": variable_client["id"]}],
            template_name="hello_world",
            language_code="fr",
        )
        body = event_loop.run_until_complete(server.admin_messaging_bulk_send(payload, admin_doc))
        assert body["requested"] == 1
        assert len(captured) == 1
        assert captured[0]["components"] is None


# ====================================================================
# 4) POST /admin/messaging/schedules persists `variables`
# ====================================================================
class TestScheduleVariables:
    def test_schedule_persists_variables_field(self, admin_h, variable_client):
        title = f"Iter13 Var Sched {uuid.uuid4().hex[:5]}"
        r = requests.post(f"{BASE}/api/admin/messaging/schedules", headers=admin_h, json={
            "title": title,
            "recipients": [{"kind": "client", "id": variable_client["id"]}],
            "template_name": "hello_world",
            "language_code": "fr",
            "variables": ["Bonjour {{full_name}}", "{{today}}"],
            "scheduled_at": _future_iso(900),
        })
        assert r.status_code == 200, r.text
        d = r.json()
        sid = d["id"]
        try:
            # Read back from DB to confirm `variables` is persisted (it's not echoed in
            # the API list shape — but it lives in the doc and is consumed by the runner)
            doc = _sync_db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
            assert doc is not None
            assert doc.get("variables") == ["Bonjour {{full_name}}", "{{today}}"]
            assert doc["status"] == "pending"
        finally:
            requests.delete(f"{BASE}/api/admin/messaging/schedules/{sid}", headers=admin_h)

    def test_schedule_without_variables_persists_none(self, admin_h):
        r = requests.post(f"{BASE}/api/admin/messaging/schedules", headers=admin_h, json={
            "recipients": [{"kind": "raw", "phone": "+22500000999"}],
            "template_name": "hello_world",
            "scheduled_at": _future_iso(900),
        })
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        try:
            doc = _sync_db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
            # variables should be None or absent
            assert doc.get("variables") in (None, [], )
        finally:
            requests.delete(f"{BASE}/api/admin/messaging/schedules/{sid}", headers=admin_h)


# ====================================================================
# 5) Runner resolves variables per-recipient at execution time
# ====================================================================
class TestRunnerResolvesVariables:
    def test_runner_uses_resolved_components(self, admin_h, variable_client, monkeypatch, event_loop):
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append({"phone": phone, "components": components})
            return {"ok": False, "status": 0, "message_id": None, "error": "MOCKED"}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        sid = uuid.uuid4().hex
        doc = {
            "id": sid,
            "title": "Iter13 var runner",
            "recipients": [
                {"kind": "client", "id": variable_client["id"], "label": "Marie/ACME"},
            ],
            "template_name": "hello_world",
            "language_code": "fr",
            "components": None,
            "variables": ["Hello {{full_name}}", "{{client_code}}"],
            "scheduled_at": _past_iso(60),
            "status": "pending",
            "result_summary": None,
            "created_by_id": "iter13-test",
            "created_by_label": "iter13-runner",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        _sync_db.whatsapp_schedules.insert_one(doc.copy())
        try:
            event_loop.run_until_complete(server._run_scheduled_whatsapp())

            after = _sync_db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
            assert after is not None
            assert after["status"] in ("failed", "done")

            assert len(captured) == 1, f"expected 1 fake send, got {len(captured)}"
            cap = captured[0]
            assert cap["phone"] == "+22500000777"
            comps = cap["components"]
            assert comps is not None
            params = comps[0]["parameters"]
            assert params[0] == {"type": "text", "text": "Hello Marie"}
            assert params[1] == {"type": "text",
                                 "text": variable_client["client_code"]}
        finally:
            _sync_db.whatsapp_schedules.delete_one({"id": sid})
            _sync_db.whatsapp_messages.delete_many({"schedule_id": sid})

    def test_runner_without_variables_unchanged(self, admin_h, monkeypatch, event_loop):
        """Regression: scheduler with no variables passes static components (None) through."""
        captured = []

        async def fake_send(phone, template_name, language_code, components):
            captured.append({"phone": phone, "components": components})
            return {"ok": False, "status": 0, "message_id": None, "error": "MOCKED"}

        monkeypatch.setattr(server, "_wa_send_template", fake_send)

        sid = uuid.uuid4().hex
        phone = "+22500000" + uuid.uuid4().hex[:3]
        doc = {
            "id": sid,
            "title": "Iter13 no-var runner",
            "recipients": [{"kind": "raw", "phone": phone, "label": "RawIter13"}],
            "template_name": "hello_world",
            "language_code": "fr",
            "components": None,
            "variables": None,
            "scheduled_at": _past_iso(60),
            "status": "pending",
            "result_summary": None,
            "created_by_id": "iter13-test",
            "created_by_label": "iter13-runner-novar",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        _sync_db.whatsapp_schedules.insert_one(doc.copy())
        try:
            event_loop.run_until_complete(server._run_scheduled_whatsapp())
            assert len(captured) == 1
            assert captured[0]["phone"] == phone
            assert captured[0]["components"] is None
        finally:
            _sync_db.whatsapp_schedules.delete_one({"id": sid})
            _sync_db.whatsapp_messages.delete_many({"schedule_id": sid})
