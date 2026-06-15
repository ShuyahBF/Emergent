"""Iter43-fix24g (2026-06) — Tests pour le dry-run sandbox des handler suggestions."""
import os
import uuid

import httpx
import pytest
from pymongo import MongoClient

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sawalismartsystems.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@Sawali2026")


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_token():
    with httpx.Client(timeout=15) as client:
        r1 = client.post(
            f"{API_BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        data1 = r1.json()
        if not data1.get("needs_otp"):
            return data1.get("access_token") or data1.get("token")
        sess = data1["session_token"]
        otp = data1.get("dev_otp")
        r2 = client.post(
            f"{API_BASE}/auth/verify-otp",
            json={"session_token": sess, "code": otp},
        )
        return r2.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _insert_sugg(db, *, command, code, applied=False):
    sid = uuid.uuid4().hex
    db.liluvine_handler_suggestions.insert_one({
        "id": sid,
        "command": command,
        "samples_count": 1,
        "generated_code": code,
        "model": "claude-sonnet-4-5-20250929",
        "generated_by": "pytest+dryrun@sawali.com",
        "generated_at": "2026-06-15T20:00:00+00:00",
        "applied": applied,
    })
    return sid


HAPPY_CODE = """## 1. Fonction principale
```python
async def _build_pingtest_reply(db, args: str) -> str:
    \"\"\"Renvoie un pong simple pour valider la chaîne dry-run.\"\"\"
    if args:
        return f"pong: {args[:40]}"
    return "pong"
```
## 2. Modifications
```python
# inutile pour le test
```
"""

SYNTAX_ERROR_CODE = """```python
async def _build_brokencmd_reply(db, args):
    return "oops"
    if  # missing condition
```
"""

TIMEOUT_CODE = """```python
async def _build_slowcmd_reply(db, args):
    import asyncio
    await asyncio.sleep(20)
    return "never"
```
"""

FORBIDDEN_IMPORT_CODE = """```python
async def _build_evilcmd_reply(db, args):
    import os
    return os.listdir(".")[0]
```
"""

NO_FUNCTION_CODE = """```python
async def _wrong_name(db, args):
    return "not the right function name"
```
"""


class TestHandlerDryRun:
    def test_happy_path_returns_reply(self, db, auth_headers):
        sid = _insert_sugg(db, command="pingtest", code=HAPPY_CODE)
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(
                    f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}/dry-run",
                    json={"args": "hello"},
                    headers=auth_headers,
                )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["ok"] is True, data
            assert data["reply"] == "pong: hello", data
            assert data["extracted_function"] == "_build_pingtest_reply"
            assert data["duration_ms"] >= 0
        finally:
            db.liluvine_handler_suggestions.delete_one({"id": sid})

    def test_happy_path_no_args(self, db, auth_headers):
        sid = _insert_sugg(db, command="pingtest", code=HAPPY_CODE)
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(
                    f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}/dry-run",
                    json={},
                    headers=auth_headers,
                )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["ok"] is True
            assert data["reply"] == "pong"
        finally:
            db.liluvine_handler_suggestions.delete_one({"id": sid})

    def test_syntax_error_returns_ok_false(self, db, auth_headers):
        sid = _insert_sugg(db, command="brokencmd", code=SYNTAX_ERROR_CODE)
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(
                    f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}/dry-run",
                    json={"args": ""},
                    headers=auth_headers,
                )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["ok"] is False, data
            assert "SyntaxError" in (data["error"] or ""), data
        finally:
            db.liluvine_handler_suggestions.delete_one({"id": sid})

    def test_timeout_returns_ok_false(self, db, auth_headers):
        sid = _insert_sugg(db, command="slowcmd", code=TIMEOUT_CODE)
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(
                    f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}/dry-run",
                    json={"args": "", "timeout_ms": 500},
                    headers=auth_headers,
                )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["ok"] is False, data
            assert "Timeout" in (data["error"] or ""), data
        finally:
            db.liluvine_handler_suggestions.delete_one({"id": sid})

    def test_forbidden_import_blocked(self, db, auth_headers):
        sid = _insert_sugg(db, command="evilcmd", code=FORBIDDEN_IMPORT_CODE)
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(
                    f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}/dry-run",
                    json={"args": ""},
                    headers=auth_headers,
                )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["ok"] is False, data
            assert "bloqué" in (data["error"] or "") or "ImportError" in (data["error"] or ""), data
        finally:
            db.liluvine_handler_suggestions.delete_one({"id": sid})

    def test_unknown_function_returns_422(self, db, auth_headers):
        sid = _insert_sugg(db, command="missingcmd", code=NO_FUNCTION_CODE)
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(
                    f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}/dry-run",
                    json={"args": ""},
                    headers=auth_headers,
                )
            # 422 si snippet introuvable (la fonction _build_missingcmd_reply n'existe pas)
            assert r.status_code == 422, r.text
        finally:
            db.liluvine_handler_suggestions.delete_one({"id": sid})

    def test_missing_suggestion_404(self, auth_headers):
        with httpx.Client(timeout=20) as client:
            r = client.post(
                f"{API_BASE}/admin/liluvine-pro/handler-suggestions/unknown-id/dry-run",
                json={"args": ""},
                headers=auth_headers,
            )
        assert r.status_code == 404, r.text

    def test_dry_run_logged_in_audit_collection(self, db, auth_headers):
        sid = _insert_sugg(db, command="pingtest", code=HAPPY_CODE)
        try:
            with httpx.Client(timeout=20) as client:
                client.post(
                    f"{API_BASE}/admin/liluvine-pro/handler-suggestions/{sid}/dry-run",
                    json={"args": "audit"},
                    headers=auth_headers,
                )
            log = db.liluvine_handler_dry_runs.find_one({"suggestion_id": sid})
            assert log is not None, "Pas de log d'audit dry-run"
            assert log["command"] == "pingtest"
            assert log["args"] == "audit"
            assert "audit" in (log.get("reply_preview") or "")
        finally:
            db.liluvine_handler_suggestions.delete_one({"id": sid})
            db.liluvine_handler_dry_runs.delete_many({"suggestion_id": sid})
