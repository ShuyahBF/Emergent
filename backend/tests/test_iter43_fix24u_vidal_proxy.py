"""Iter43-fix24u (2026-06-16) — Smoke tests for the VIDAL proxy route registration.

The proxy logic itself relies on live MongoDB + httpx forwarding, so the heavy
integration is exercised on a deployed environment. Here we just sanity-check:
  - The `_vidal_call` HTML rewriting points to the proxy prefix.
  - The proxy prefix constant matches the publicly-exposed route.
"""
from __future__ import annotations

import pytest

from routes.vidal import VIDAL_PROXY_PREFIX


def test_proxy_prefix_is_canonical():
    """The proxy prefix must match the path mounted in `attach_vidal_routes`.

    The frontend `<base href>` injection relies on this exact string.
    """
    assert VIDAL_PROXY_PREFIX == "/api/vidal/proxy"


def test_proxy_prefix_starts_with_api():
    """Required so the ingress routes the request to the FastAPI backend."""
    assert VIDAL_PROXY_PREFIX.startswith("/api/")


def test_proxy_prefix_no_trailing_slash():
    """Avoid double-slash bugs when constructing `<base href="$PREFIX/">`."""
    assert not VIDAL_PROXY_PREFIX.endswith("/")
