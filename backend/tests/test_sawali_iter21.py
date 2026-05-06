"""SAWALI — Iteration 21 backend tests.

Coverage:
 - GET /api/me/features (admin)            -> all features True, inherited_from=None.
 - GET /api/admin/clients/{id}/features    -> default flags = all False (DEFAULT_CLIENT_FEATURES).
 - PUT /api/admin/clients/{id}/features    -> partial update via exclude_none merges,
                                              GET back confirms persistence.
 - POST/GET/PUT /api/me/notes/reports      -> is_private flag round-trips & flips on PUT.
 - POST /api/me/ai/summaries/{id}/to-report -> 404 (FR detail) / OK with seeded summary,
                                              content_html starts with <p> & ends with footer.
 - PUT /api/admin/settings  -> 28 new SMS/OVH/PawaPay fields persist;
                              GET masks every secret as '********'.
 - AI Summary system prompt — verified via the n8n echo-webhook path: the body sent to
                              n8n contains the `system_prompt` field with the new
                              "analyse précisément le CONTENU" text + the 5 bullet marks.
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


# -------- helpers ----------
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


@pytest.fixture(scope="module")
def admin_user(admin):
    return admin[1]


@pytest.fixture(scope="module")
def fresh_client(admin_h):
    """Create a TEST_ client, yield, delete it after the module."""
    email = f"test-iter21-{uuid.uuid4().hex[:6]}@example.com"
    payload = {
        "email": email,
        "full_name": "Test Client iter21",
        "password": "Sawali#Iter21!",
        "role": "client",
        "phone": "+22670000000",
        "company": "TEST Co",
        "country": "BFA",
        "city": "Ouagadougou",
        "account_status": "active",
    }
    r = requests.post(f"{BASE}/api/admin/clients", headers=admin_h, json=payload)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    yield cid
    # teardown
    _sync_db.users.delete_one({"id": cid})


# ============================================================
# A) /me/features  +  /admin/clients/{id}/features
# ============================================================
class TestFeatures:
    def test_me_features_admin_all_true(self, admin_h):
        r = requests.get(f"{BASE}/api/me/features", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        feats = d["features"]
        assert feats == {"whatsapp": True, "sms": True, "ai": True, "payments": True}, feats
        assert d.get("inherited_from") is None

    def test_admin_get_client_features_defaults(self, admin_h, fresh_client):
        r = requests.get(f"{BASE}/api/admin/clients/{fresh_client}/features", headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["client"]["id"] == fresh_client
        assert d["features"] == {"whatsapp": False, "sms": False, "ai": False, "payments": False}

    def test_admin_partial_update_preserves_other_flags(self, admin_h, fresh_client):
        # Step 1: turn on whatsapp + ai (sms/payments stay False).
        r1 = requests.put(
            f"{BASE}/api/admin/clients/{fresh_client}/features",
            headers=admin_h,
            json={"whatsapp": True, "ai": True},
        )
        assert r1.status_code == 200, r1.text
        feats = r1.json()["features"]
        assert feats == {"whatsapp": True, "sms": False, "ai": True, "payments": False}, feats

        # Persistence: GET must return same shape
        r2 = requests.get(f"{BASE}/api/admin/clients/{fresh_client}/features", headers=admin_h)
        assert r2.status_code == 200
        assert r2.json()["features"] == feats

        # Step 2: partial (only sms=True). Should preserve whatsapp/ai already True.
        r3 = requests.put(
            f"{BASE}/api/admin/clients/{fresh_client}/features",
            headers=admin_h,
            json={"sms": True},
        )
        assert r3.status_code == 200
        feats3 = r3.json()["features"]
        assert feats3 == {"whatsapp": True, "sms": True, "ai": True, "payments": False}, feats3

    def test_features_404_for_unknown_client(self, admin_h):
        bogus = f"nope-{uuid.uuid4().hex[:8]}"
        r = requests.get(f"{BASE}/api/admin/clients/{bogus}/features", headers=admin_h)
        assert r.status_code == 404


# ============================================================
# B) Notes — is_private round-trip on /me/notes/reports
# ============================================================
class TestNotesPrivacy:
    def test_create_private_then_flip(self, admin_h):
        created_ids = []
        try:
            # Create with is_private=True
            r = requests.post(
                f"{BASE}/api/me/notes/reports",
                headers=admin_h,
                json={"title": "TEST_iter21 priv", "content_html": "<p>secret</p>", "is_private": True},
            )
            assert r.status_code == 200, r.text
            note = r.json()
            assert note["is_private"] is True
            created_ids.append(note["id"])

            # GET list — find ours
            r2 = requests.get(f"{BASE}/api/me/notes/reports", headers=admin_h)
            assert r2.status_code == 200
            mine = next((n for n in r2.json() if n["id"] == note["id"]), None)
            assert mine is not None
            assert mine["is_private"] is True

            # Flip via PUT
            r3 = requests.put(
                f"{BASE}/api/me/notes/reports/{note['id']}",
                headers=admin_h,
                json={"is_private": False},
            )
            assert r3.status_code == 200, r3.text

            r4 = requests.get(f"{BASE}/api/me/notes/reports", headers=admin_h)
            mine2 = next((n for n in r4.json() if n["id"] == note["id"]), None)
            assert mine2 is not None
            assert mine2["is_private"] is False
        finally:
            for nid in created_ids:
                _sync_db.user_reports.delete_one({"id": nid})


# ============================================================
# C) AI summary -> Report conversion
# ============================================================
class TestSummaryToReport:
    def test_to_report_404_for_unknown(self, admin_h):
        bogus = f"nope-{uuid.uuid4().hex[:8]}"
        r = requests.post(
            f"{BASE}/api/me/ai/summaries/{bogus}/to-report",
            headers=admin_h,
            json={"title": "x", "is_private": True},
        )
        assert r.status_code == 404, r.text
        # French detail
        detail = r.json()["detail"]
        assert "introuvable" in detail.lower() or "non" in detail.lower(), detail

    def test_to_report_ok_with_seeded_summary(self, admin_h, admin_user):
        from datetime import datetime, timezone
        sid = f"TEST_sum_{uuid.uuid4().hex[:10]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        seed = {
            "id": sid,
            "user_id": admin_user["id"],
            "user_email": admin_user.get("email"),
            "provider": "openai",
            "model": "gpt-4o-mini",
            "target": "ACME",
            "context": "iter21 seed",
            "summary": "Ligne 1 sur le contenu.\nLigne 2 décisions prises.\nLigne 3 prochaines étapes.",
            "created_at": now_iso,
        }
        _sync_db.ai_summaries.insert_one(seed.copy())
        created_report_ids = []
        try:
            r = requests.post(
                f"{BASE}/api/me/ai/summaries/{sid}/to-report",
                headers=admin_h,
                json={"title": "TEST_iter21 rapport IA", "is_private": True},
            )
            assert r.status_code == 200, r.text
            d = r.json()
            assert d.get("ok") is True
            assert d.get("kind") == "reports"
            rep = d["report"]
            assert rep["is_private"] is True
            assert rep["title"] == "TEST_iter21 rapport IA"
            html = rep["content_html"]
            assert html.startswith("<p>"), f"content_html should start with <p>: {html[:80]}"
            assert "Généré automatiquement" in html, "footer attribution missing"
            assert "openai" in html  # provider in footer
            created_report_ids.append(rep["id"])

            # source_summary_id traceability
            assert rep.get("source_summary_id") == sid
        finally:
            _sync_db.ai_summaries.delete_one({"id": sid})
            for rid in created_report_ids:
                _sync_db.user_reports.delete_one({"id": rid})


# ============================================================
# D) AI summary system_prompt — verified via n8n echo
# ============================================================
class TestAiSummarySystemPrompt:
    def test_system_prompt_mentions_content_and_5_bullets(self, admin_h):
        webhook_url = "https://httpbin.org/anything"
        prev = _sync_db.settings.find_one({"_id": "global"}) or {}
        snap = {k: prev.get(k) for k in (
            "ai_summary_provider", "n8n_webhook_url", "n8n_webhook_auth_type", "n8n_webhook_token",
        )}
        _sync_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "ai_summary_provider": "n8n",
                "n8n_webhook_url": webhook_url,
                "n8n_webhook_auth_type": "none",
            }},
            upsert=True,
        )
        try:
            r = requests.post(
                f"{BASE}/api/me/ai/summarize",
                headers=admin_h,
                json={"messages": [{"body": "Bonjour, comment allez-vous ?", "direction": "inbound"}],
                      "context": "test prompt iter21"},
                timeout=90,
            )
            if r.status_code in (502, 504):
                pytest.skip(f"httpbin.org unreachable ({r.status_code}) — can't verify system_prompt echo")
            assert r.status_code == 200, r.text
            summary = r.json().get("summary", "")
            assert "Analyse pr" in summary and "CONTENU des messages WhatsApp" in summary, \
                f"system_prompt not echoed: {summary[:400]}"
            # 5 bullet markers (1)..(5)
            for marker in ("(1)", "(2)", "(3)", "(4)", "(5)"):
                assert marker in summary, f"bullet {marker} missing in echoed system_prompt"
        finally:
            set_ = {k: v for k, v in snap.items() if v is not None}
            unset_ = {k: "" for k, v in snap.items() if v is None}
            op = {}
            if set_:
                op["$set"] = set_
            if unset_:
                op["$unset"] = unset_
            if op:
                _sync_db.settings.update_one({"_id": "global"}, op)
            # Best-effort cleanup of any persisted summary the call wrote
            _sync_db.ai_summaries.delete_many({"context": "test prompt iter21"})


# ============================================================
# E) Admin settings — SMS / OVH / PawaPay fields + masking
# ============================================================
class TestAdminSettingsSmsOvhPawapay:
    def test_put_get_mask(self, admin_h):
        # Capture full DB state before for safe restore
        prev_doc = _sync_db.settings.find_one({"_id": "global"}) or {}

        new_fields = {
            # Orange Burkina
            "sms_orange_enabled": True,
            "sms_orange_url": "https://orange.example/sms",
            "sms_orange_method": "POST",
            "sms_orange_auth_type": "bearer",
            "sms_orange_token": f"orgT_{uuid.uuid4().hex[:6]}",
            "sms_orange_basic_user": "u",
            "sms_orange_basic_pass": f"orgP_{uuid.uuid4().hex[:6]}",
            "sms_orange_header_name": "X-Hdr",
            "sms_orange_header_value": f"orgH_{uuid.uuid4().hex[:6]}",
            "sms_orange_sender": "ORANGE-BF",
            # Moov Burkina
            "sms_moov_enabled": True,
            "sms_moov_url": "https://moov.example/sms",
            "sms_moov_method": "POST",
            "sms_moov_auth_type": "basic",
            "sms_moov_token": f"movT_{uuid.uuid4().hex[:6]}",
            "sms_moov_basic_user": "u",
            "sms_moov_basic_pass": f"movP_{uuid.uuid4().hex[:6]}",
            "sms_moov_header_name": "X-Hdr",
            "sms_moov_header_value": f"movH_{uuid.uuid4().hex[:6]}",
            "sms_moov_sender": "MOOV-BF",
            # Telecel Burkina
            "sms_telecel_enabled": True,
            "sms_telecel_url": "https://telecel.example/sms",
            "sms_telecel_method": "POST",
            "sms_telecel_auth_type": "header",
            "sms_telecel_token": f"telT_{uuid.uuid4().hex[:6]}",
            "sms_telecel_basic_user": "u",
            "sms_telecel_basic_pass": f"telP_{uuid.uuid4().hex[:6]}",
            "sms_telecel_header_name": "X-Auth",
            "sms_telecel_header_value": f"telH_{uuid.uuid4().hex[:6]}",
            "sms_telecel_sender": "TELECEL",
            # OVH SMS
            "sms_ovh_enabled": True,
            "sms_ovh_endpoint": "ovh-eu",
            "sms_ovh_application_key": "ovhAK",
            "sms_ovh_application_secret": f"ovhAS_{uuid.uuid4().hex[:6]}",
            "sms_ovh_consumer_key": f"ovhCK_{uuid.uuid4().hex[:6]}",
            "sms_ovh_service_name": "sms-XXXX-1",
            "sms_ovh_sender": "SAWALI",
            # PawaPay
            "pawapay_enabled": True,
            "pawapay_api_token": f"ppT_{uuid.uuid4().hex[:8]}",
            "pawapay_environment": "sandbox",
            "pawapay_country": "BFA",
        }

        secrets = {
            "sms_orange_token", "sms_orange_basic_pass", "sms_orange_header_value",
            "sms_moov_token", "sms_moov_basic_pass", "sms_moov_header_value",
            "sms_telecel_token", "sms_telecel_basic_pass", "sms_telecel_header_value",
            "sms_ovh_application_secret", "sms_ovh_consumer_key",
            "pawapay_api_token",
        }

        try:
            r = requests.put(f"{BASE}/api/admin/settings", headers=admin_h, json=new_fields)
            assert r.status_code == 200, r.text

            r2 = requests.get(f"{BASE}/api/admin/settings", headers=admin_h)
            assert r2.status_code == 200
            got = r2.json()

            # Plain (non-secret) fields round-trip
            for k, v in new_fields.items():
                if k in secrets:
                    continue
                assert got.get(k) == v, f"field {k} did not round-trip: got={got.get(k)!r} expected={v!r}"

            # Secret fields are masked
            for k in secrets:
                assert got.get(k) == "********", f"secret {k} not masked: got={got.get(k)!r}"

            # Raw DB still holds true values
            raw = _sync_db.settings.find_one({"_id": "global"}) or {}
            for k in secrets:
                assert raw.get(k) == new_fields[k], f"raw DB lost true value for {k}"

            # Mask placeholder must NOT overwrite real secret
            r3 = requests.put(
                f"{BASE}/api/admin/settings",
                headers=admin_h,
                json={"pawapay_api_token": "********"},
            )
            assert r3.status_code == 200
            raw2 = _sync_db.settings.find_one({"_id": "global"}) or {}
            assert raw2.get("pawapay_api_token") == new_fields["pawapay_api_token"], \
                "mask placeholder should not overwrite pawapay_api_token"
        finally:
            # Unset everything we touched, then restore previous values that existed
            unset_keys = list(new_fields.keys())
            _sync_db.settings.update_one({"_id": "global"}, {"$unset": {k: "" for k in unset_keys}})
            restore = {k: prev_doc[k] for k in unset_keys if k in prev_doc}
            if restore:
                _sync_db.settings.update_one({"_id": "global"}, {"$set": restore})
