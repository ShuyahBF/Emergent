"""Iter43-fix24aq (2026-06-17) — Tests pour :
 - L'extraction du `<vidal:id>` namespacé dans la réponse WA
   (`_format_vidal_data_for_wa`).
 - Le dispatcher d'images générique pour TOUTES les commandes
   (`!garde`, `!produits`, etc.) avec priorité per-command > legacy garde
   > default.
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


SAMPLE_VIDAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:vidal="http://api.vidal.fr/spec/vidal/1.0">
  <title>Recherche doliprane</title>
  <entry>
    <title>DOLIPRANE 100 mg pdre p sol buv en sachet-dose</title>
    <id>vidal://product/5485</id>
    <vidal:id>5485</vidal:id>
  </entry>
  <entry>
    <title>DOLIPRANE 1000 mg, comprimé</title>
    <id>vidal://product/5486</id>
    <vidal:id>5486</vidal:id>
  </entry>
  <entry>
    <title>DOLIPRANE LIBÉRATION PROLONGÉE</title>
    <id>vidal://product/5487</id>
    <vidal:id>5487</vidal:id>
  </entry>
</feed>"""


def test_wa_formatter_extracts_vidal_id_into_parens():
    """The WA reply text MUST include the product code in parens after each title."""
    m = _mod()
    action = {"id": "recherche", "label": "Recherche VIDAL"}
    data = {"raw": SAMPLE_VIDAL_XML}
    out = m._format_vidal_data_for_wa(action, data)
    # Titles must be present
    assert "DOLIPRANE 100 mg pdre p sol buv en sachet-dose" in out
    assert "DOLIPRANE 1000 mg, comprimé" in out
    # Codes must appear in *bold* parens (markdown for WhatsApp)
    assert "(*5485*)" in out
    assert "(*5486*)" in out
    assert "(*5487*)" in out
    # Each entry must be on its own numbered line
    assert "1. DOLIPRANE 100 mg pdre p sol buv en sachet-dose (*5485*)" in out


def test_wa_formatter_skips_feed_title():
    """The Atom <feed><title> must NOT appear as item #1 (only <entry><title>)."""
    m = _mod()
    out = m._format_vidal_data_for_wa({"id": "x", "label": "Test"}, {"raw": SAMPLE_VIDAL_XML})
    # "Recherche doliprane" is the feed title and must NOT appear as an entry
    assert "1. Recherche doliprane" not in out
    assert "Recherche doliprane (*" not in out


def test_wa_formatter_fallback_when_no_vidal_id_uses_urn_digits():
    """If `<vidal:id>` is absent, fall back to extracting digits from the
    atom `<id>vidal://product/NNNN</id>` URN."""
    m = _mod()
    xml = SAMPLE_VIDAL_XML.replace("<vidal:id>5485</vidal:id>", "")
    xml = xml.replace("<vidal:id>5486</vidal:id>", "")
    xml = xml.replace("<vidal:id>5487</vidal:id>", "")
    out = m._format_vidal_data_for_wa({"id": "x", "label": "T"}, {"raw": xml})
    # Codes still appear (extracted from URN)
    assert "(*5485*)" in out
    assert "(*5486*)" in out


def test_wa_formatter_handles_alt_namespace_prefix():
    """Some VIDAL API responses might use `<v:id>` instead of `<vidal:id>`.
    The formatter must still extract the numeric code."""
    m = _mod()
    xml = SAMPLE_VIDAL_XML.replace("vidal:id>", "v:id>")
    out = m._format_vidal_data_for_wa({"id": "x", "label": "T"}, {"raw": xml})
    assert "(*5485*)" in out


def test_wa_formatter_no_entries_returns_empty_message():
    """When `<entry>` tags exist but contain no extractable `<title>`,
    return the 'Aucun résultat trouvé' message."""
    m = _mod()
    out = m._format_vidal_data_for_wa(
        {"id": "x", "label": "Test"},
        {"raw": "<feed xmlns='http://www.w3.org/2005/Atom'><entry></entry></feed>"},
    )
    assert "Aucun résultat" in out


def test_wa_formatter_json_entries_path_includes_vidal_id():
    """JSON fallback path also surfaces vidal_id when present."""
    m = _mod()
    data = {"entries": [
        {"title": "DOLIPRANE", "vidal_id": "5485"},
        {"title": "PARACETAMOL", "id": "5486"},  # id field as fallback
    ]}
    out = m._format_vidal_data_for_wa({"id": "x", "label": "T"}, data)
    assert "(*5485*)" in out
    assert "(*5486*)" in out


def test_wa_formatter_truncates_long_lists():
    """Limit to 8 entries to fit WhatsApp message length."""
    m = _mod()
    entries = "".join(
        f"<entry><title>Item {i}</title><vidal:id>{1000+i}</vidal:id></entry>"
        for i in range(15)
    )
    xml = f"<feed xmlns:vidal='http://x'>{entries}</feed>"
    out = m._format_vidal_data_for_wa({"id": "x", "label": "T"}, {"raw": xml})
    assert "1. Item 0" in out
    assert "8. Item 7" in out
    assert "Item 8 " not in out  # 9th and beyond skipped
    assert "+7 résultats non affichés" in out
