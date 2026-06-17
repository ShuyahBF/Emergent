"""Iter43-fix24aa (2026-06-16) — Tests for non-raising error responses.

When VIDAL returns 4xx/5xx, `_vidal_call` must NOT raise HTTPException.
Instead it returns the same `{raw, _request, _error}` structure so the UI
can display both the request meta and the response body (essential for
diagnostic, demanded by user).
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest


class _FakeResp:
    def __init__(self, status: int, html: str, ctype: str = "text/html"):
        self.status_code = status
        self.text = html
        self.headers = {"content-type": ctype}
        self.elapsed = type("E", (), {"total_seconds": lambda s: 0.05})()
    def json(self):
        import json as _j
        return _j.loads(self.text)


class _FakeClient:
    def __init__(self, resp): self._r = resp
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
    async def get(self, *a, **kw): return self._r
    async def post(self, *a, **kw): return self._r
    async def request(self, *a, **kw): return self._r


@pytest.mark.asyncio
async def test_404_returns_structured_data_no_raise():
    """Iter43-fix24aa : un 404 VIDAL ne doit PAS lever d'HTTPException ;
    il doit renvoyer `{raw, _request, _error}` pour l'UI."""
    from routes.vidal import _vidal_call
    html = "<!DOCTYPE html><html><head></head><body><h1>404 Not Found</h1></body></html>"
    cfg = {"base_url": "https://api.vidal.fr/rest/api", "app_id": "x", "app_key": "y",
           "http_timeout": 5, "mode": "production"}
    fake = _FakeClient(_FakeResp(404, html))
    with patch.object(httpx, "AsyncClient", lambda *a, **kw: fake):
        # Should NOT raise
        result = await _vidal_call(cfg, "GET", "/wrong-endpoint", params={"q": "doliprane"})
    assert "raw" in result
    assert "_request" in result
    assert "_error" in result
    assert result["_error"]["status"] == 404
    assert "404" in result["_error"]["message"]
    # The body is preserved so the user sees the error page
    assert "404 Not Found" in result["raw"]


@pytest.mark.asyncio
async def test_500_returns_structured_data_no_raise():
    from routes.vidal import _vidal_call
    html = "<html><head></head><body><h1>500 Internal Server Error</h1></body></html>"
    cfg = {"base_url": "https://api.vidal.fr/rest/api", "app_id": "x", "app_key": "y",
           "http_timeout": 5, "mode": "production"}
    fake = _FakeClient(_FakeResp(500, html))
    with patch.object(httpx, "AsyncClient", lambda *a, **kw: fake):
        result = await _vidal_call(cfg, "GET", "/products")
    assert result["_error"]["status"] == 500
    assert "raw" in result
    assert "_request" in result


@pytest.mark.asyncio
async def test_200_no_error_field():
    """Réponse 200 → pas de `_error`."""
    from routes.vidal import _vidal_call
    xml = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Doliprane</title></entry></feed>'
    cfg = {"base_url": "https://api.vidal.fr/rest/api", "app_id": "x", "app_key": "y",
           "http_timeout": 5, "mode": "production"}
    fake = _FakeClient(_FakeResp(200, xml, ctype="application/atom+xml"))
    with patch.object(httpx, "AsyncClient", lambda *a, **kw: fake):
        result = await _vidal_call(cfg, "GET", "/products/search", params={"q": "doliprane"})
    assert "_error" not in result
    assert "raw" in result  # XML returned as raw
    assert "Doliprane" in result["raw"]


@pytest.mark.asyncio
async def test_request_meta_includes_masked_app_key():
    """`_request.params.app_key` doit être masqué (jamais en clair vers l'UI)."""
    from routes.vidal import _vidal_call
    cfg = {"base_url": "https://api.vidal.fr/rest/api", "app_id": "MY_APP_ID", "app_key": "MY_SECRET_KEY",
           "http_timeout": 5, "mode": "production"}
    fake = _FakeClient(_FakeResp(404, "<html></html>"))
    with patch.object(httpx, "AsyncClient", lambda *a, **kw: fake):
        result = await _vidal_call(cfg, "GET", "/x")
    params = result["_request"]["params"]
    assert params.get("app_key") == "***", f"app_key must be masked, got: {params}"
    assert params.get("app_id") == "MY_APP_ID", f"app_id should be exposed for debug: {params}"
