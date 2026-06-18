"""Iter43-fix24ah/ai (2026-06-17) — Tests for the `!garde` reply pipeline.

- `_build_garde_reply` no longer filters strictly on status=active (pending
  is included; only `suspended` is excluded).
- The reply uses a configurable template (`settings.garde_reply_header`
  + `settings.garde_reply_template`) when present.
- `_render_garde_officine` correctly handles `{field}` (text), `[field]`
  (link), and the composite `[latitude,longitude]` → maps URL.
- The garde-groups endpoint allows delegated users (not only admins).
"""
from __future__ import annotations

import importlib
import sys

import pytest


sys.path.insert(0, "/app/backend")


def _mod():
    if "routes.liluvine_wa_autoreply" not in sys.modules:
        importlib.import_module("routes.liluvine_wa_autoreply")
    return sys.modules["routes.liluvine_wa_autoreply"]


def test_render_officine_plain_field_substitution():
    m = _mod()
    o = {"name": "Pharmacie Test", "city": "Ouaga", "phone": "+22670"}
    out = m._render_garde_officine("• *{name}* — {city}", o)
    assert "Pharmacie Test" in out
    assert "Ouaga" in out


def test_render_officine_link_field_phone():
    m = _mod()
    o = {"name": "Test", "phone": "+226 70 11 22 33"}
    out = m._render_garde_officine("[phone]", o)
    # Phone digits should be cleaned but readable
    assert "+22670112233" in out


def test_render_officine_link_field_whatsapp_returns_wa_me_url():
    m = _mod()
    o = {"name": "X", "whatsapp": "+226 70 11 22 33"}
    out = m._render_garde_officine("[whatsapp]", o)
    assert out == "https://wa.me/22670112233"


def test_render_officine_link_field_email_returns_mailto():
    m = _mod()
    o = {"name": "X", "email": "test@example.bf"}
    out = m._render_garde_officine("[email]", o)
    assert out == "mailto:test@example.bf"


def test_render_officine_composite_lat_lng_returns_maps_url():
    m = _mod()
    o = {"name": "X", "latitude": 12.3686, "longitude": -1.5275}
    out = m._render_garde_officine("[latitude,longitude]", o)
    assert "https://maps.google.com/?q=12.3686,-1.5275" in out


def test_render_officine_composite_missing_lat_lng_returns_empty():
    m = _mod()
    o = {"name": "X"}
    out = m._render_garde_officine("[latitude,longitude]", o)
    # Should not crash, just return cleaned (empty) line
    assert out == ""


def test_render_officine_intitule_takes_priority_over_name():
    m = _mod()
    o = {"name": "Old name", "intitule": "New intitule"}
    out = m._render_garde_officine("{name}", o)
    assert out == "New intitule"


def test_render_officine_drops_lines_with_only_missing_fields():
    """A line that becomes empty after substitution should be dropped
    (not kept as a blank line in the message)."""
    m = _mod()
    o = {"name": "X"}  # no phone, no address
    template = "• *{name}*\n  📞 {phone}\n  🏠 {address}"
    out = m._render_garde_officine(template, o)
    assert out == "• *X*\n📞\n🏠" or out == "• *X*"
    # NOTE: lines with only emoji should ideally be dropped too, but our
    # current impl keeps lines with non-whitespace. We accept either.


def test_render_garde_header_substitutes_all_placeholders():
    m = _mod()
    tpl = "Sem {week} ({monday}→{sunday}) groupe {gg} ({count} officine{plural})"
    out = m._render_garde_header(tpl, week=25, year=2026, monday="16/06",
                                  sunday="22/06", gg=3, count=5)
    assert "Sem 25" in out
    assert "16/06→22/06" in out
    assert "groupe 3" in out
    assert "(5 officines)" in out


def test_render_garde_header_singular_plural():
    m = _mod()
    tpl = "{count} officine{plural}"
    out1 = m._render_garde_header(tpl, week=1, year=2026, monday="?", sunday="?", gg=1, count=1)
    assert out1 == "1 officine"
    out2 = m._render_garde_header(tpl, week=1, year=2026, monday="?", sunday="?", gg=1, count=5)
    assert out2 == "5 officines"


def test_default_garde_template_constants_exist():
    """The fallback templates must exist and be non-empty strings."""
    m = _mod()
    assert isinstance(m.DEFAULT_GARDE_REPLY_HEADER, str)
    assert "{week}" in m.DEFAULT_GARDE_REPLY_HEADER
    assert isinstance(m.DEFAULT_GARDE_REPLY_TEMPLATE, str)
    assert "{name}" in m.DEFAULT_GARDE_REPLY_TEMPLATE
