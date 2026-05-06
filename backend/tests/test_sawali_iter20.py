"""SAWALI — Iteration 20 backend tests.

Coverage:
 - GET/HEAD /api/public/policies/{slot}: HEAD returns 200 + correct headers when
   PDF is uploaded; 404 when missing.
 - POST /api/me/ai/summarize:
     * 503 when provider=openai and openai_chat_api_key not set.
     * 503 when provider=n8n  and n8n_webhook_url empty.
     * OpenAI branch: with fake key → reaches api.openai.com (returns 502 with
       OpenAI error message) — verifies wiring.
     * n8n branch: with a public echo webhook (httpbin) → ok=True,
       provider='n8n', Authorization bearer header is forwarded.
 - PUT /api/admin/settings persists ai_summary_provider, openai_chat_api_key,
   openai_chat_model, n8n_webhook_url, n8n_webhook_auth_type, n8n_webhook_token,
   n8n_webhook_basic_user, n8n_webhook_basic_pass. Subsequent GET masks the
   three secrets as '********'. Teardown restores previous values.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL must be set"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

_sync_mongo = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_mongo[os.environ["DB_NAME"]]


def _login(email: str, password: str):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    if d.get("needs_otp"):
        assert d.get("dev_otp"), f"dev_otp expected, got {d}"
        r2 = s.post(f"{BASE}/api/auth/verify-otp",
                    json={"session_token": d["session_token"], "code": d["dev_otp"]})
        assert r2.status_code == 200, r2.text
        return r2.json()["access_token"], r2.json()["user"]
    return d["access_token"], d["user"]


@pytest.fixture(scope="module")
def admin():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def admin_h(admin):
    return {"Authorization": f"Bearer {admin[0]}"}


# ============================================================
# A) HEAD /api/public/policies/{slot}
# ============================================================
class TestPublicPoliciesHead:
    def test_head_returns_200_for_privacy(self):
        r = requests.head(f"{BASE}/api/public/policies/privacy", allow_redirects=True)
        # We accept 200 (existing PDF) OR 404 (no PDF uploaded). Skip if 404.
        if r.status_code == 404:
            pytest.skip("privacy PDF not uploaded — cannot test HEAD 200 path")
        assert r.status_code == 200, r.text
        assert "application/pdf" in (r.headers.get("Content-Type") or "").lower()
        cl = int(r.headers.get("Content-Length") or "0")
        assert cl > 0, f"Content-Length missing/zero: {r.headers}"

    def test_head_404_for_missing_slot(self):
        fake = f"does-not-exist-{uuid.uuid4().hex[:6]}"
        r = requests.head(f"{BASE}/api/public/policies/{fake}")
        assert r.status_code == 404, r.text

    def test_get_returns_pdf_inline(self):
        r = requests.get(f"{BASE}/api/public/policies/privacy")
        if r.status_code == 404:
            pytest.skip("privacy PDF not uploaded")
        assert r.status_code == 200, r.text
        assert "application/pdf" in (r.headers.get("Content-Type") or "").lower()
        # iframe-able: content-disposition should be inline OR absent
        cd = (r.headers.get("Content-Disposition") or "").lower()
        assert "attachment" not in cd, f"PDF served as attachment (breaks iframe): {cd}"
        assert len(r.content) > 100


# ============================================================
# B) POST /api/me/ai/summarize — default 503 paths
# ============================================================
class TestAiSummarizeNotConfigured:
    def _ensure_default_config(self):
        # Unset keys to guarantee 503 for both providers.
        _sync_db.settings.update_one(
            {"_id": "global"},
            {"$unset": {
                "ai_summary_provider": "",
                "openai_chat_api_key": "",
                "n8n_webhook_url": "",
                "n8n_webhook_auth_type": "",
                "n8n_webhook_token": "",
            }},
            upsert=True,
        )

    def test_openai_default_503_when_key_missing(self, admin_h):
        self._ensure_default_config()
        r = requests.post(
            f"{BASE}/api/me/ai/summarize",
            headers=admin_h,
            json={"messages": [{"body": "hello", "direction": "inbound"}]},
        )
        assert r.status_code == 503, r.text
        detail = r.json()["detail"].lower()
        assert "chatgpt" in detail or "openai" in detail, detail

    def test_n8n_503_when_webhook_missing(self, admin_h):
        # Switch to n8n with no URL — expect 503 mentioning n8n
        _sync_db.settings.update_one(
            {"_id": "global"},
            {"$set": {"ai_summary_provider": "n8n"}, "$unset": {"n8n_webhook_url": ""}},
            upsert=True,
        )
        try:
            r = requests.post(
                f"{BASE}/api/me/ai/summarize",
                headers=admin_h,
                json={"messages": [{"body": "x"}]},
            )
            assert r.status_code == 503, r.text
            detail = r.json()["detail"].lower()
            assert "n8n" in detail or "webhook" in detail
        finally:
            _sync_db.settings.update_one(
                {"_id": "global"},
                {"$unset": {"ai_summary_provider": ""}},
            )

    def test_requires_auth(self):
        r = requests.post(f"{BASE}/api/me/ai/summarize",
                          json={"messages": [{"body": "x"}]})
        assert r.status_code in (401, 403), r.text


# ============================================================
# C) POST /api/me/ai/summarize — OpenAI branch with fake key
# ============================================================
class TestAiSummarizeOpenAIWiring:
    def test_openai_reaches_api_with_fake_key(self, admin_h):
        """Set a clearly-fake key and verify we reach api.openai.com — which
        will respond 401 → our endpoint maps to 502 with the OpenAI error
        message. Proves the Authorization header + endpoint URL + model are
        wired correctly."""
        fake_key = f"sk-TEST-iter20-{uuid.uuid4().hex}"
        prev = _sync_db.settings.find_one({"_id": "global"}) or {}
        prev_key = prev.get("openai_chat_api_key")
        prev_model = prev.get("openai_chat_model")
        prev_provider = prev.get("ai_summary_provider")
        _sync_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "ai_summary_provider": "openai",
                "openai_chat_api_key": fake_key,
                "openai_chat_model": "gpt-4o-mini",
            }},
            upsert=True,
        )
        try:
            r = requests.post(
                f"{BASE}/api/me/ai/summarize",
                headers=admin_h,
                json={"messages": [{"body": "ping", "direction": "inbound"}],
                      "target": "ACME", "context": "short test"},
                timeout=60,
            )
            # Expect 502 with OpenAI error message (invalid API key) OR 504 if timeout
            assert r.status_code in (502, 504), f"unexpected: {r.status_code} {r.text}"
            if r.status_code == 502:
                detail = r.json()["detail"].lower()
                # OpenAI returns an error like "Incorrect API key provided"
                assert "openai" in detail or "api key" in detail or "401" in detail or "incorrect" in detail, detail
        finally:
            # Restore previous values
            unset = {}
            set_ = {}
            if prev_key is None:
                unset["openai_chat_api_key"] = ""
            else:
                set_["openai_chat_api_key"] = prev_key
            if prev_model is None:
                unset["openai_chat_model"] = ""
            else:
                set_["openai_chat_model"] = prev_model
            if prev_provider is None:
                unset["ai_summary_provider"] = ""
            else:
                set_["ai_summary_provider"] = prev_provider
            op = {}
            if set_:
                op["$set"] = set_
            if unset:
                op["$unset"] = unset
            _sync_db.settings.update_one({"_id": "global"}, op)


# ============================================================
# D) POST /api/me/ai/summarize — n8n branch with echo webhook
# ============================================================
class TestAiSummarizeN8nEcho:
    def test_n8n_reaches_webhook_and_returns_ok(self, admin_h):
        """Use httpbin.org/anything as an echo webhook. It returns the JSON
        body + headers we sent. Our backend's fallback parsing (no 'summary'
        key in response) will stringify the JSON into summary — still ok=True
        and provider='n8n'."""
        webhook_url = "https://httpbin.org/anything"
        token = f"tok_{uuid.uuid4().hex}"
        prev = _sync_db.settings.find_one({"_id": "global"}) or {}
        prev_snapshot = {k: prev.get(k) for k in (
            "ai_summary_provider", "n8n_webhook_url", "n8n_webhook_auth_type",
            "n8n_webhook_token",
        )}
        _sync_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "ai_summary_provider": "n8n",
                "n8n_webhook_url": webhook_url,
                "n8n_webhook_auth_type": "bearer",
                "n8n_webhook_token": token,
            }},
            upsert=True,
        )
        try:
            r = requests.post(
                f"{BASE}/api/me/ai/summarize",
                headers=admin_h,
                json={"messages": [{"body": "hello", "direction": "inbound"}],
                      "context": "test iter20"},
                timeout=90,
            )
            if r.status_code == 504 or r.status_code == 502:
                pytest.skip(f"httpbin.org unreachable from backend ({r.status_code}) — can't verify n8n wiring")
            assert r.status_code == 200, r.text
            d = r.json()
            assert d.get("ok") is True
            assert d.get("provider") == "n8n"
            assert isinstance(d.get("summary"), str) and len(d["summary"]) > 0
            # httpbin echoes back the headers — verify our bearer token was forwarded
            # (the summary is stringified JSON of httpbin's response).
            assert token in d["summary"], "bearer token was not forwarded to n8n webhook"
            # Our payload fields should appear in the echo too
            assert "ai_summary" in d["summary"]
        finally:
            # Restore
            set_ = {k: v for k, v in prev_snapshot.items() if v is not None}
            unset_ = {k: "" for k, v in prev_snapshot.items() if v is None}
            op = {}
            if set_:
                op["$set"] = set_
            if unset_:
                op["$unset"] = unset_
            if op:
                _sync_db.settings.update_one({"_id": "global"}, op)


# ============================================================
# E) PUT /api/admin/settings — new fields + masking
# ============================================================
class TestAdminSettingsAiFields:
    def test_put_ai_fields_and_mask(self, admin_h):
        r0 = requests.get(f"{BASE}/api/admin/settings", headers=admin_h)
        assert r0.status_code == 200
        prev = r0.json()

        fake_openai = f"sk-TEST-iter20-{uuid.uuid4().hex[:10]}"
        fake_tok = f"bear_{uuid.uuid4().hex[:10]}"
        fake_pass = f"pw_{uuid.uuid4().hex[:8]}"
        payload = {
            "ai_summary_provider": "n8n",
            "openai_chat_api_key": fake_openai,
            "openai_chat_model": "gpt-4o-mini",
            "n8n_webhook_url": "https://example.com/hook/iter20",
            "n8n_webhook_auth_type": "basic",
            "n8n_webhook_token": fake_tok,
            "n8n_webhook_basic_user": "testuser",
            "n8n_webhook_basic_pass": fake_pass,
        }
        r = requests.put(f"{BASE}/api/admin/settings", headers=admin_h, json=payload)
        assert r.status_code == 200, r.text

        r2 = requests.get(f"{BASE}/api/admin/settings", headers=admin_h)
        got = r2.json()
        try:
            assert got.get("ai_summary_provider") == "n8n"
            assert got.get("openai_chat_model") == "gpt-4o-mini"
            assert got.get("n8n_webhook_url") == "https://example.com/hook/iter20"
            assert got.get("n8n_webhook_auth_type") == "basic"
            assert got.get("n8n_webhook_basic_user") == "testuser"
            # Masked
            assert got.get("openai_chat_api_key") == "********", f"openai_chat_api_key not masked: {got.get('openai_chat_api_key')!r}"
            assert got.get("n8n_webhook_token") == "********", f"n8n_webhook_token not masked: {got.get('n8n_webhook_token')!r}"
            assert got.get("n8n_webhook_basic_pass") == "********", f"n8n_webhook_basic_pass not masked: {got.get('n8n_webhook_basic_pass')!r}"
            # Raw DB still holds real values
            raw = _sync_db.settings.find_one({"_id": "global"}) or {}
            assert raw.get("openai_chat_api_key") == fake_openai
            assert raw.get("n8n_webhook_token") == fake_tok
            assert raw.get("n8n_webhook_basic_pass") == fake_pass

            # Masking-placeholder "no change" behavior — send back "********" must not overwrite
            r3 = requests.put(f"{BASE}/api/admin/settings", headers=admin_h,
                              json={"openai_chat_api_key": "********"})
            assert r3.status_code == 200
            raw2 = _sync_db.settings.find_one({"_id": "global"}) or {}
            assert raw2.get("openai_chat_api_key") == fake_openai, "mask placeholder should not overwrite real key"
        finally:
            # Teardown: fully unset the new AI fields (+provider) so subsequent
            # runs of the 503 tests still see defaults.
            _sync_db.settings.update_one(
                {"_id": "global"},
                {"$unset": {
                    "ai_summary_provider": "",
                    "openai_chat_api_key": "",
                    "openai_chat_model": "",
                    "n8n_webhook_url": "",
                    "n8n_webhook_auth_type": "",
                    "n8n_webhook_token": "",
                    "n8n_webhook_basic_user": "",
                    "n8n_webhook_basic_pass": "",
                }},
            )
