"""Iter43-fix24af (2026-06-17) — vidal_mode must stay a string.

Bug: PUT /admin/clients/{id}/features failed with HTTP 422 because
`_normalize_features` coerced `vidal_mode` to `bool`, the GET handler then
returned `vidal_mode: True`, the form sent it back as bool, and Pydantic
rejected (model expects `Optional[str]`).
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest


sys.path.insert(0, "/app/backend")


def _server():
    if "server" not in sys.modules:
        importlib.import_module("server")
    return sys.modules["server"]


def test_normalize_features_preserves_vidal_mode_string():
    srv = _server()
    # User had `vidal_mode: "test"` → must stay "test", not become True
    out = srv._normalize_features({"vidal_mode": "test"})
    assert out["vidal_mode"] == "test"
    out = srv._normalize_features({"vidal_mode": "production"})
    assert out["vidal_mode"] == "production"
    out = srv._normalize_features({"vidal_mode": "inherit"})
    assert out["vidal_mode"] == "inherit"


def test_normalize_features_coerces_legacy_bool_to_default():
    """Old DB docs had `vidal_mode: True` (legacy bug). They must be
    normalized back to `"inherit"`, not crash and not stay as bool."""
    srv = _server()
    out = srv._normalize_features({"vidal_mode": True})
    assert out["vidal_mode"] == "inherit"
    assert isinstance(out["vidal_mode"], str)
    out = srv._normalize_features({"vidal_mode": False})
    assert out["vidal_mode"] == "inherit"


def test_normalize_features_default_vidal_mode_when_missing():
    srv = _server()
    out = srv._normalize_features({})
    assert out["vidal_mode"] == "inherit"


def test_client_features_update_accepts_bool_vidal_mode():
    """The Pydantic model coerces a stray bool → 'inherit' instead of 422."""
    srv = _server()
    payload = srv.ClientFeaturesUpdate(vidal_mode=True)
    assert payload.vidal_mode == "inherit"
    payload = srv.ClientFeaturesUpdate(vidal_mode=False)
    assert payload.vidal_mode == "inherit"
    payload = srv.ClientFeaturesUpdate(vidal_mode="test")
    assert payload.vidal_mode == "test"
    payload = srv.ClientFeaturesUpdate(vidal_mode="PRODUCTION")  # case-insensitive
    assert payload.vidal_mode == "production"
    payload = srv.ClientFeaturesUpdate(vidal_mode="garbage")
    assert payload.vidal_mode == "inherit"
    payload = srv.ClientFeaturesUpdate()
    assert payload.vidal_mode is None  # None preserved (no change in DB)
