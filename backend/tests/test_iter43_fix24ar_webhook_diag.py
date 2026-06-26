"""
Iter43-fix24ar (2026-02) — Test du diagnostic webhook Meta amélioré.

Régression couverte :
  L'admin reçoit « subscribed_apps exception: » sans détail au lieu d'un
  message actionnable. On vérifie maintenant que :
  1. Quand le token est expiré/invalide, on retourne un message clair
     (« 🔑 Token Meta expiré ») AVANT l'appel subscribed_apps.
  2. Quand l'appel subscribed_apps réussit avec 0 apps, on retourne un
     message actionnable invitant à cliquer sur « Re-souscrire ».
  3. Quand l'appel échoue avec une exception réseau (timeout, DNS),
     on retourne le `type(exc).__name__` + le str(exc) en clair (jamais
     un message vide).
  4. Le diagnostic expose `token_probe.ok`, `http_status` et
     `raw_response_preview` pour permettre à l'admin de diagnostiquer
     SANS accès aux logs serveur.
"""
from __future__ import annotations

import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON body")
        return self._payload


def _build_fake_client(responses_iter):
    """Build a FakeClient class that returns successive responses from `responses_iter`.
    If a response is an Exception, it is raised instead."""
    responses = list(responses_iter)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            if not responses:
                raise RuntimeError("FakeClient: no more responses queued")
            resp = responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp

    return FakeClient


async def _ensure_wa_config(access_token="VALID_TOKEN_ABC", waba_id="1277222612345678",
                            phone_number_id="987654321"):
    """Restore the WA config to a known state and return previous values to restore later."""
    prev = await server.db.settings.find_one(
        {"_id": "global"},
        {"_id": 0, "wa_access_token": 1, "wa_business_account_id": 1, "wa_phone_number_id": 1},
    ) or {}
    await server.db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "wa_access_token": access_token,
            "wa_business_account_id": waba_id,
            "wa_phone_number_id": phone_number_id,
        }},
        upsert=True,
    )
    return prev


async def _restore_wa_config(prev):
    await server.db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "wa_access_token": prev.get("wa_access_token", ""),
            "wa_business_account_id": prev.get("wa_business_account_id", ""),
            "wa_phone_number_id": prev.get("wa_phone_number_id", ""),
        }},
        upsert=True,
    )


# --------------------------------------------------------------------------
# Helper: run an async coroutine on the session-shared event loop.
# --------------------------------------------------------------------------
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_diag_token_expired_short_circuits_with_clear_message(monkeypatch):
    """Iter43-fix24ar — Token expiré (code 190) → message clair avant /subscribed_apps."""
    prev = _run(_ensure_wa_config(access_token="EXPIRED_TOKEN_XYZ"))
    try:
        fake_responses = [
            _FakeResponse(401, {"error": {
                "message": "Invalid OAuth access token - Cannot parse access token",
                "code": 190,
                "type": "OAuthException",
            }}),
        ]
        monkeypatch.setattr(server.httpx, "AsyncClient", _build_fake_client(fake_responses))
        result = _run(server.admin_wa_webhook_subscription({}))
        assert result["ok"] is False, result
        assert result["error_code"] == 190, result
        assert "expir" in (result["message"] or "").lower() or "🔑" in (result["message"] or "")
        assert result["token_probe"]["ok"] is False
        assert result["token_probe"]["status"] == 401
        assert "subscribed_apps exception" not in (result["message"] or "")
    finally:
        _run(_restore_wa_config(prev))


def test_diag_network_exception_returns_typed_message(monkeypatch):
    """Iter43-fix24ar — Exception réseau → type(exc).__name__ + str(exc), JAMAIS vide."""
    prev = _run(_ensure_wa_config())
    try:
        fake_responses = [
            _FakeResponse(200, {"id": "12345", "name": "Test App"}),
            httpx.ConnectTimeout("Connection timed out after 10s"),
        ]
        monkeypatch.setattr(server.httpx, "AsyncClient", _build_fake_client(fake_responses))
        result = _run(server.admin_wa_webhook_subscription({}))
        assert result["ok"] is False, result
        assert result["error_type"] == "ConnectTimeout", result
        assert "ConnectTimeout" in result["message"]
        assert "Connection timed out" in result["message"]
        assert result["token_probe"]["ok"] is True
    finally:
        _run(_restore_wa_config(prev))


def test_diag_zero_apps_returns_actionable_message(monkeypatch):
    """Iter43-fix24ar — 0 apps abonnées → message invitant à re-souscrire."""
    prev = _run(_ensure_wa_config())
    try:
        fake_responses = [
            _FakeResponse(200, {"id": "12345", "name": "Test App"}),
            _FakeResponse(200, {"data": []}),
        ]
        monkeypatch.setattr(server.httpx, "AsyncClient", _build_fake_client(fake_responses))
        result = _run(server.admin_wa_webhook_subscription({}))
        assert result["ok"] is False, result
        assert result["http_status"] == 200, result
        assert result["subscribed_apps"] == []
        assert "re-souscrire" in (result["message"] or "").lower() or \
               "Re-souscrire" in (result["message"] or "")
        assert result["token_probe"]["ok"] is True
    finally:
        _run(_restore_wa_config(prev))


def test_diag_missing_config_no_meta_call(monkeypatch):
    """Iter43-fix24ar — Config vide → retour immédiat sans appel Meta."""
    prev = _run(_ensure_wa_config(access_token="", waba_id="", phone_number_id=""))
    try:
        def _factory(*args, **kwargs):
            raise AssertionError("httpx should NOT be called when config is missing")

        monkeypatch.setattr(server.httpx, "AsyncClient", _factory)
        result = _run(server.admin_wa_webhook_subscription({}))
        assert result["ok"] is False, result
        assert result["reason"] == "missing_config", result
        assert "wa_access_token" in (result["message"] or "") or \
               "wa_business_account_id" in (result["message"] or "")
    finally:
        _run(_restore_wa_config(prev))


def test_diag_non_json_response_captured(monkeypatch):
    """Iter43-fix24ar — Réponse non-JSON → on remonte le preview + un message clair."""
    prev = _run(_ensure_wa_config())
    try:
        fake_responses = [
            _FakeResponse(200, {"id": "12345", "name": "Test App"}),
            _FakeResponse(502, payload=None, text="<html><body>Bad Gateway</body></html>"),
        ]
        monkeypatch.setattr(server.httpx, "AsyncClient", _build_fake_client(fake_responses))
        result = _run(server.admin_wa_webhook_subscription({}))
        assert result["ok"] is False, result
        assert "raw_response_preview" in result, result
        assert "Bad Gateway" in (result.get("raw_response_preview") or "")
        assert result.get("http_status") == 502
        assert result["token_probe"]["ok"] is True
    finally:
        _run(_restore_wa_config(prev))
