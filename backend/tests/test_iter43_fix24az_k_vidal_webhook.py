"""Iter43-fix24az-k (2026-02-26) — VIDAL Webhook proxy tests.

Validates the outbound → inbound bridge :
  1. Admin can enable webhook config via /admin/vidal/config
  2. GET /admin/vidal/config exposes webhook_enabled + webhook_outbound_url +
     webhook_callback_url
  3. When webhook_enabled=False, direct VIDAL call is used (existing behavior)
  4. When webhook_enabled=True, `_dispatch_via_webhook` POSTs to the configured
     URL and waits for the callback
  5. POST /vidal/webhook/callback with a valid correlation_id delivers the
     response back to the waiter
  6. POST /vidal/webhook/callback with an unknown correlation_id → 404
  7. Timeout when no callback arrives
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge_admin() -> str:
    """Forge a JWT for an existing admin user (uses SAWALI seeded admin)."""
    return pyjwt.encode({
        "sub": "admin-fixture-vidal-webhook",
        "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    admin = db.users.find_one({"email": "admin@sawalismartsystems.com"}) or db.users.find_one({"role": "admin"})
    assert admin, "No admin user found for tests"
    return pyjwt.encode({
        "sub": admin["id"],
        "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def _H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_config_has_webhook_fields(admin_token):
    r = requests.get(f"{API}/admin/vidal/config", headers=_H(admin_token), timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("webhook_enabled", "webhook_outbound_url", "webhook_timeout_seconds", "webhook_callback_url"):
        assert k in data, f"missing field {k} in config response : {data}"
    # callback_url must end with the canonical endpoint path
    assert data["webhook_callback_url"].endswith("/api/vidal/webhook/callback"), data["webhook_callback_url"]


def test_config_persists_webhook_update(admin_token):
    r = requests.put(f"{API}/admin/vidal/config", headers=_H(admin_token),
                     json={"webhook_enabled": True,
                           "webhook_outbound_url": "https://n8n.example.com/webhook/vidal",
                           "webhook_timeout_seconds": 10}, timeout=10)
    assert r.status_code == 200, r.text
    r2 = requests.get(f"{API}/admin/vidal/config", headers=_H(admin_token), timeout=10)
    d = r2.json()
    assert d["webhook_enabled"] is True
    assert d["webhook_outbound_url"] == "https://n8n.example.com/webhook/vidal"
    assert d["webhook_timeout_seconds"] == 10
    # Cleanup — turn off to avoid interfering with other test suites
    requests.put(f"{API}/admin/vidal/config", headers=_H(admin_token),
                 json={"webhook_enabled": False, "webhook_outbound_url": ""}, timeout=10)


def test_callback_endpoint_rejects_unknown_correlation():
    # No auth required (feature-first per spec).
    r = requests.post(f"{API}/vidal/webhook/callback",
                      json={"correlation_id": "unknown-" + str(uuid.uuid4()),
                            "status_code": 200, "body": {"hello": "world"}}, timeout=5)
    assert r.status_code == 404, r.text
    detail = r.json().get("detail", "")
    assert "inconnu" in detail.lower() or "expiré" in detail.lower()


def test_callback_endpoint_rejects_missing_correlation():
    r = requests.post(f"{API}/vidal/webhook/callback",
                      json={"body": {"hello": "world"}}, timeout=5)
    # 422 = missing required field
    assert r.status_code == 422, r.text


def test_dispatch_and_callback_end_to_end(admin_token):
    """Full happy path : simulate an external system that echoes what it
    received back to /vidal/webhook/callback."""
    import threading, time
    # Config : point outbound URL at a Python echo server we start locally.
    import http.server, socketserver, json as pyjson
    captured = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs):  # silence
            return
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            env = pyjson.loads(raw.decode())
            captured["envelope"] = env
            # Immediately fire the callback with a canned response.
            def _cb():
                time.sleep(0.3)  # tiny delay to simulate external processing
                try:
                    requests.post(f"{API}/vidal/webhook/callback", json={
                        "correlation_id": env["correlation_id"],
                        "status_code": 200,
                        "content_type": "application/json",
                        "body": {"_data": {"products": [{"id": "TEST-42", "name": "TEST PRODUCT"}]}},
                    }, timeout=5)
                except Exception as e:
                    print("callback error:", e)
            threading.Thread(target=_cb, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"received":true}')

    # Bind on any free port
    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        # Configure the webhook to point at our local echo server.
        outbound = f"http://127.0.0.1:{port}/webhook"
        # Also enable VIDAL & set app_id/app_key so `_ensure_active` passes.
        r = requests.put(f"{API}/admin/vidal/config", headers=_H(admin_token), json={
            "enabled": True,
            "mode": "test",
            "test_app_id": "fake-app-id",
            "test_app_key": "fake-app-key",
            "webhook_enabled": True,
            "webhook_outbound_url": outbound,
            "webhook_timeout_seconds": 10,
        }, timeout=10)
        assert r.status_code == 200, r.text

        # Trigger a VIDAL call — /admin/vidal/test-connection uses _vidal_call
        # under the hood which is now webhook-aware.
        r = requests.post(f"{API}/admin/vidal/test-connection", headers=_H(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        # Must succeed (via webhook proxy)
        assert body.get("ok") is True, body
        debug = body.get("debug") or {}
        assert debug.get("request", {}).get("transport") == "webhook", debug
        # Verify the outbound envelope was captured correctly
        env = captured.get("envelope") or {}
        assert env.get("correlation_id"), env
        assert env.get("method") == "GET"
        assert "/products" in env.get("url", "")
        assert env.get("params", {}).get("q") == "doliprane"
        assert env.get("callback_url", "").endswith("/api/vidal/webhook/callback")
    finally:
        server.shutdown()
        server.server_close()
        # Restore config
        requests.put(f"{API}/admin/vidal/config", headers=_H(admin_token), json={
            "webhook_enabled": False, "webhook_outbound_url": "",
        }, timeout=10)


def test_dispatch_timeout_when_no_callback(admin_token):
    """Point webhook at a black-hole endpoint that never calls back → we must
    return an error after webhook_timeout_seconds (short = 3 s)."""
    import threading, socketserver, http.server

    class Silent(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs): return
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"received":true}')
            # Do NOT fire the callback → force the timeout branch.

    server = socketserver.TCPServer(("127.0.0.1", 0), Silent)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        r = requests.put(f"{API}/admin/vidal/config", headers=_H(admin_token), json={
            "enabled": True, "mode": "test",
            "test_app_id": "fake", "test_app_key": "fake",
            "webhook_enabled": True,
            "webhook_outbound_url": f"http://127.0.0.1:{port}/wh",
            "webhook_timeout_seconds": 5,
        }, timeout=10)
        assert r.status_code == 200
        # Trigger — must return ok=False with a timeout message.
        r = requests.post(f"{API}/admin/vidal/test-connection", headers=_H(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is False, body
        err = (body.get("error") or "").lower()
        assert "timeout" in err or "callback" in err, body
    finally:
        server.shutdown()
        server.server_close()
        requests.put(f"{API}/admin/vidal/config", headers=_H(admin_token), json={
            "webhook_enabled": False, "webhook_outbound_url": "",
        }, timeout=10)
