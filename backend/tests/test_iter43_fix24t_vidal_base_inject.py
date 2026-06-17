"""Iter43-fix24t (2026-06-16) — Test VIDAL HTML response gets <base> tag injected.

When VIDAL returns an HTML page (typically the Angular API explorer), the
backend must inject a `<base href="{origin}/">` tag right after `<head>` so
that relative paths (CSS, JS, images) resolve correctly when the HTML is
rendered inside a sandboxed `<iframe srcdoc>` in the admin UI.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest


VIDAL_ANGULAR_HTML = """<!DOCTYPE html>
<html data-ng-app="app">
<head>
    <meta charset="utf-8" />
    <link rel="stylesheet" type="text/css" href="css/bootstrap.min.css">
</head>
<body>
    <div data-ng-controller="MainCtrl"><img src="img/logo.png" /></div>
    <script src="lib/angular.min.js"></script>
</body>
</html>"""


VIDAL_ERROR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Error</title>
</head>
<body>
    <div class="container">
        <img src="/img/logo.png" alt="VIDAL logo" />
        <h1>Oops! Something went wrong.</h1>
    </div>
</body>
</html>"""


class _FakeAsyncClient:
    """Async context-manager stub that returns a configurable HTML response."""

    def __init__(self, html: str, ctype: str = "text/html", status: int = 200):
        self._html = html
        self._ctype = ctype
        self._status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url, **_):
        return self._make_resp()

    async def request(self, method, url, **_):
        return self._make_resp()

    def _make_resp(self):
        html = self._html
        ctype = self._ctype
        status = self._status

        class _R:
            status_code = status
            text = html
            headers = {"content-type": ctype}
            elapsed = type("E", (), {"total_seconds": lambda self_: 0.05})()

            def json(self_):
                import json as _json
                return _json.loads(html)
        return _R()


@pytest.mark.asyncio
async def test_html_response_injects_base_tag():
    """The Angular API explorer page gets <base> injected after <head>.

    Iter43-fix24u — `<base href>` points to the backend proxy (`/api/vidal/proxy/`),
    not the VIDAL origin. This makes all relative resources transit through
    our backend, avoiding CORS issues in sandboxed iframes.
    """
    from routes.vidal import _vidal_call
    cfg = {
        "base_url": "http://api.vidal.fr/#!/rest/api",
        "app_id": "x", "app_key": "y",
        "http_timeout": 5, "mode": "production",
    }
    fake = _FakeAsyncClient(VIDAL_ANGULAR_HTML)
    with patch.object(httpx, "AsyncClient", lambda *a, **kw: fake):
        result = await _vidal_call(cfg, "GET", "/products/search", params={"q": "x"})
    raw = result.get("raw") or ""
    assert '<base href="/api/vidal/proxy/">' in raw, raw[:500]
    # <base> must come right after <head> opening tag
    head_idx = raw.lower().find("<head>")
    base_idx = raw.find('<base href="/api/vidal/proxy/">')
    assert base_idx > head_idx, "base tag must come AFTER <head>"
    assert base_idx - head_idx < 10, "base tag must be IMMEDIATELY after <head>"


@pytest.mark.asyncio
async def test_html_error_page_also_gets_base_tag():
    """The generic 'Oops! Something went wrong' page also gets <base> injected."""
    from routes.vidal import _vidal_call
    cfg = {
        "base_url": "https://api.vidal.net/rest/api",
        "app_id": "x", "app_key": "y",
        "http_timeout": 5, "mode": "production",
    }
    fake = _FakeAsyncClient(VIDAL_ERROR_HTML)
    with patch.object(httpx, "AsyncClient", lambda *a, **kw: fake):
        result = await _vidal_call(cfg, "GET", "/authentication")
    raw = result.get("raw") or ""
    assert '<base href="/api/vidal/proxy/">' in raw, raw[:500]


@pytest.mark.asyncio
async def test_json_response_unaffected():
    """JSON responses must NOT be touched — only HTML gets the <base> injection."""
    from routes.vidal import _vidal_call
    cfg = {
        "base_url": "https://api.vidal.net/rest/api",
        "app_id": "x", "app_key": "y",
        "http_timeout": 5, "mode": "production",
    }
    fake = _FakeAsyncClient('{"entries": [{"id": 1, "title": "Doliprane"}]}', ctype="application/json")
    with patch.object(httpx, "AsyncClient", lambda *a, **kw: fake):
        result = await _vidal_call(cfg, "GET", "/products/search")
    # JSON parsed normally — no `raw` field, no `<base>` injection
    assert "entries" in result
    assert isinstance(result["entries"], list)
    assert result["entries"][0]["title"] == "Doliprane"


@pytest.mark.asyncio
async def test_plain_text_response_no_injection():
    """Non-HTML plain text responses are NOT touched."""
    from routes.vidal import _vidal_call
    cfg = {
        "base_url": "https://api.vidal.net/rest/api",
        "app_id": "x", "app_key": "y",
        "http_timeout": 5, "mode": "production",
    }
    fake = _FakeAsyncClient("just some plain text without html", ctype="text/plain")
    with patch.object(httpx, "AsyncClient", lambda *a, **kw: fake):
        result = await _vidal_call(cfg, "GET", "/x")
    raw = result.get("raw") or ""
    assert "<base href=" not in raw
    assert raw == "just some plain text without html"
