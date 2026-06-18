"""Iter43-fix24aj (2026-06-17) — `_build_components` + `button_specs` fix
for Meta WhatsApp template error #131009.

Before this fix, `_build_components` hardcoded `sub_type=url` for every
button when the caller passed `button_vars`. Templates with QUICK_REPLY
buttons rejected with HTTP 400 "Components sub_type invalid at index: N
and type: 0".
"""
from __future__ import annotations

import importlib
import sys

import pytest


sys.path.insert(0, "/app/backend")


def _srv():
    if "server" not in sys.modules:
        importlib.import_module("server")
    return sys.modules["server"]


def test_button_specs_url_emits_sub_type_url():
    srv = _srv()
    ctx = {"full_name": "Alice", "phone": "+22670"}
    specs = [{
        "sub_type": "url",
        "index": 0,
        "parameters": [{"type": "text", "text": "promo123"}],
    }]
    components = srv._build_components(None, ctx, button_specs=specs)
    assert components is not None
    btn = next(c for c in components if c["type"] == "button")
    assert btn["sub_type"] == "url"
    assert btn["index"] == "0"
    assert btn["parameters"][0] == {"type": "text", "text": "promo123"}


def test_button_specs_quick_reply_emits_payload_param_type():
    """A QUICK_REPLY button's parameter must be `{type: payload, payload: ...}`
    not `{type: text, text: ...}` — otherwise Meta returns #131009."""
    srv = _srv()
    ctx = {}
    specs = [{
        "sub_type": "quick_reply",
        "index": 1,
        "parameters": ["YES_RDV"],  # bare string → must default to payload type
    }]
    components = srv._build_components(None, ctx, button_specs=specs)
    btn = next(c for c in components if c["type"] == "button")
    assert btn["sub_type"] == "quick_reply"
    assert btn["index"] == "1"
    assert btn["parameters"][0] == {"type": "payload", "payload": "YES_RDV"}


def test_button_specs_token_substitution():
    srv = _srv()
    ctx = {"full_name": "Alice", "client_code": "CL-001"}
    specs = [{
        "sub_type": "url",
        "index": 0,
        "parameters": ["promo-{{client_code}}"],
    }]
    components = srv._build_components(None, ctx, button_specs=specs)
    btn = next(c for c in components if c["type"] == "button")
    assert btn["parameters"][0]["text"] == "promo-CL-001"


def test_button_specs_empty_parameters_skip_emission():
    srv = _srv()
    ctx = {}
    specs = [{"sub_type": "url", "index": 0, "parameters": []}]
    components = srv._build_components(None, ctx, button_specs=specs)
    # No body, no buttons → returns None entirely
    assert components is None


def test_button_specs_takes_precedence_over_button_vars():
    """If both are passed, `button_specs` wins (it's the typed form)."""
    srv = _srv()
    ctx = {}
    components = srv._build_components(
        None, ctx,
        button_specs=[{"sub_type": "quick_reply", "index": 0, "parameters": ["YES"]}],
        button_vars=[["should-be-ignored"]],  # legacy form
    )
    btn = next(c for c in components if c["type"] == "button")
    assert btn["sub_type"] == "quick_reply"
    # Specifically should NOT have emitted a second button from button_vars
    assert sum(1 for c in components if c["type"] == "button") == 1


def test_button_vars_legacy_still_works_for_url():
    """Old callers that only pass `button_vars` (no specs) still get a
    URL button — backwards compatible."""
    srv = _srv()
    ctx = {}
    components = srv._build_components(None, ctx, button_vars=[["promo123"]])
    btn = next(c for c in components if c["type"] == "button")
    assert btn["sub_type"] == "url"
    assert btn["parameters"][0]["text"] == "promo123"


def test_button_vars_legacy_skips_empty_strings():
    """Iter43-fix24aj — Old `button_vars` path now filters fully-empty params
    so it doesn't emit invalid components."""
    srv = _srv()
    ctx = {}
    components = srv._build_components(None, ctx, button_vars=[["", "  "]])
    # Should not emit a button at all
    assert components is None or all(c["type"] != "button" for c in components)


def test_full_components_with_body_and_button_specs():
    """End-to-end test: body params + correctly-typed button → 2 components."""
    srv = _srv()
    ctx = {"full_name": "Alice", "company": "ACME"}
    specs = [{
        "sub_type": "url",
        "index": 0,
        "parameters": [{"type": "text", "text": "promo123"}],
    }]
    components = srv._build_components(
        ["{{full_name}}", "{{company}}"], ctx, button_specs=specs,
    )
    assert len(components) == 2
    body = components[0]
    assert body["type"] == "body"
    assert body["parameters"][0]["text"] == "Alice"
    assert body["parameters"][1]["text"] == "ACME"
    btn = components[1]
    assert btn["type"] == "button"
    assert btn["sub_type"] == "url"
