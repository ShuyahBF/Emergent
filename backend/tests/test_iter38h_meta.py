"""Iter38h — Meta integration tests (hits the live preview backend via /api/...)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    if not d.get("needs_otp"):
        return d["access_token"]
    r2 = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": d["session_token"], "code": d["dev_otp"]},
        timeout=30,
    )
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


def test_admin_get_meta_config(admin_token):
    r = requests.get(f"{API}/admin/meta/config", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("meta_app_id", "meta_app_secret_preview", "meta_webhook_verify_token_preview",
              "meta_graph_version", "meta_redirect_uri", "default_redirect_uri", "webhook_callback_url"):
        assert k in data
    assert data["webhook_callback_url"].endswith("/api/meta/webhook")


def test_admin_put_meta_config_then_preview(admin_token):
    r = requests.put(f"{API}/admin/meta/config",
                     headers={"Authorization": f"Bearer {admin_token}"},
                     json={"meta_app_id": "TEST-APP-1234",
                           "meta_app_secret": "test-secret-iter38h-XYZW",
                           "meta_webhook_verify_token": "verify-iter38h-ABCD"},
                     timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "meta_app_id" in body["updated_keys"]

    r2 = requests.get(f"{API}/admin/meta/config", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    d = r2.json()
    assert d["meta_app_id"] == "TEST-APP-1234"
    assert d["meta_app_secret_preview"].endswith("XYZW")
    assert d["meta_webhook_verify_token_preview"].endswith("ABCD")


def test_admin_put_empty_secret_does_not_wipe(admin_token):
    # Just update app_id; do not send secret/token. The previous values must remain.
    r = requests.put(f"{API}/admin/meta/config",
                     headers={"Authorization": f"Bearer {admin_token}"},
                     json={"meta_app_id": "TEST-APP-5678"}, timeout=10)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/admin/meta/config", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    d = r2.json()
    assert d["meta_app_id"] == "TEST-APP-5678"
    assert d["meta_app_secret_preview"].endswith("XYZW")  # unchanged


def test_me_meta_status_disabled_by_default(admin_token):
    r = requests.get(f"{API}/me/meta/status", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["connected"] is False
    assert d["features"] == {"meta_pages": False, "meta_messenger": False, "meta_ads": False}


def test_me_meta_oauth_url_403_when_no_features(admin_token):
    r = requests.get(f"{API}/me/meta/oauth/url", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 403


def test_me_meta_pages_403_when_feature_off(admin_token):
    r = requests.get(f"{API}/me/meta/pages", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 403


def test_meta_webhook_get_verify_correct(admin_token):
    # Make sure verify token is what we expect
    requests.put(f"{API}/admin/meta/config",
                 headers={"Authorization": f"Bearer {admin_token}"},
                 json={"meta_webhook_verify_token": "verify-iter38h-ABCD"}, timeout=10)
    r = requests.get(f"{API}/meta/webhook",
                     params={"hub.mode": "subscribe", "hub.verify_token": "verify-iter38h-ABCD", "hub.challenge": "PING_42"},
                     timeout=10)
    assert r.status_code == 200
    assert r.text == "PING_42"


def test_meta_webhook_get_verify_wrong():
    r = requests.get(f"{API}/meta/webhook",
                     params={"hub.mode": "subscribe", "hub.verify_token": "WRONG_xxx", "hub.challenge": "X"},
                     timeout=10)
    assert r.status_code == 403


def test_meta_webhook_post_bad_signature():
    payload = {"object": "page", "entry": []}
    body = json.dumps(payload).encode()
    r = requests.post(f"{API}/meta/webhook", data=body,
                      headers={"X-Hub-Signature-256": "sha256=deadbeef",
                               "Content-Type": "application/json"}, timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["received"] is False
    assert j["reason"] == "bad_signature"


def test_meta_webhook_post_valid_signature(admin_token):
    # We know the app secret because we set it in test_admin_put_meta_config_then_preview
    requests.put(f"{API}/admin/meta/config",
                 headers={"Authorization": f"Bearer {admin_token}"},
                 json={"meta_app_secret": "test-secret-iter38h-XYZW"}, timeout=10)
    payload = {"object": "page", "entry": []}
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"test-secret-iter38h-XYZW", body, hashlib.sha256).hexdigest()
    r = requests.post(f"{API}/meta/webhook", data=body,
                      headers={"X-Hub-Signature-256": sig,
                               "Content-Type": "application/json"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["received"] is True


def test_me_meta_disconnect_idempotent(admin_token):
    r = requests.post(f"{API}/me/meta/disconnect", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Second call should also succeed (no integration left to delete)
    r2 = requests.post(f"{API}/me/meta/disconnect", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r2.status_code == 200
