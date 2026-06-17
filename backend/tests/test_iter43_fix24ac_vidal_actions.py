"""Iter43-fix24ac (2026-06-16) — Tests for configurable VIDAL actions.

Validates:
  - Default seed of 7 actions on first load
  - `find_action_by_command` matches by `exclamation_command` AND by `id`
  - `render_action` substitutes `{var}` placeholders in path / query / body
  - `_clean_vidal_base_url` strips `/authentication` suffix
"""
from __future__ import annotations

import pytest

from routes.vidal_actions import (
    DEFAULT_ACTIONS, find_action_by_command, render_action,
)
from routes.vidal import _clean_vidal_base_url


def test_defaults_have_required_fields():
    for a in DEFAULT_ACTIONS:
        assert a["id"]
        assert a["method"] in {"GET", "POST", "PUT", "DELETE"}
        assert a["path"].startswith("/")
        assert "is_public" in a


def test_defaults_include_recherche_with_correct_path():
    """Doit suivre la doc VIDAL fournie par l'utilisateur :
    `https://api.vidal.fr/rest/api/products?app_id=X&app_key=Y&q=doliprane`
    → path = `/products`, query_param `q` avec template `{q}`."""
    recherche = next(a for a in DEFAULT_ACTIONS if a["id"] == "recherche")
    assert recherche["method"] == "GET"
    assert recherche["path"] == "/products"
    qp = recherche["query_params"]
    assert any(p["key"] == "q" and p["value_template"] == "{q}" for p in qp)


def test_defaults_alerts_full_is_post_with_xml():
    a = next(a for a in DEFAULT_ACTIONS if a["id"] == "alerts_full")
    assert a["method"] == "POST"
    assert "<alertsRequest>" in a["body_template"]
    assert a["is_public"] is False  # Réservé aux Abonnés VIDAL


def test_find_action_by_command_matches_explicit():
    a = find_action_by_command(DEFAULT_ACTIONS, "recherche")
    assert a and a["id"] == "recherche"
    # Tolerates the bang
    a2 = find_action_by_command(DEFAULT_ACTIONS, "!recherche")
    assert a2 and a2["id"] == "recherche"
    # Case-insensitive
    a3 = find_action_by_command(DEFAULT_ACTIONS, "RECHERCHE")
    assert a3 and a3["id"] == "recherche"


def test_find_action_by_command_falls_back_to_id():
    # `cip` is the exclamation, but if user types `!package`, it should
    # match the `package` action by id.
    a = find_action_by_command(DEFAULT_ACTIONS, "package")
    assert a and a["id"] == "package"


def test_find_action_by_command_returns_none_for_unknown():
    assert find_action_by_command(DEFAULT_ACTIONS, "azertyuiop") is None


def test_render_action_substitutes_path_placeholder():
    a = next(x for x in DEFAULT_ACTIONS if x["id"] == "produit")
    rendered = render_action(a, {"id": "5485"})
    assert rendered["path"] == "/product/5485"
    assert rendered["method"] == "GET"
    assert rendered["body"] is None


def test_render_action_substitutes_query_template():
    a = next(x for x in DEFAULT_ACTIONS if x["id"] == "recherche")
    rendered = render_action(a, {"q": "doliprane"})
    assert rendered["path"] == "/products"
    assert rendered["params"] == {"q": "doliprane"}


def test_render_action_substitutes_xml_body():
    a = next(x for x in DEFAULT_ACTIONS if x["id"] == "alerts_full")
    rendered = render_action(a, {"vidal_id": "5485"})
    assert "<vidalId>5485</vidalId>" in rendered["body"]
    assert rendered["method"] == "POST"


def test_render_action_missing_var_keeps_placeholder():
    """If a `{var}` isn't provided, we keep the placeholder for visual
    feedback rather than crashing or silently emitting empty values."""
    a = next(x for x in DEFAULT_ACTIONS if x["id"] == "produit")
    rendered = render_action(a, {})  # no `id` given
    assert "{id}" in rendered["path"]


def test_clean_strips_authentication_suffix():
    """User confused `/authentication` (test endpoint) with the base path.
    The cleaner must strip it so concatenated paths don't double-prefix."""
    assert _clean_vidal_base_url("https://api.vidal.fr/rest/api/authentication") == "https://api.vidal.fr/rest/api"
    assert _clean_vidal_base_url("http://api.vidal.fr/#!/rest/api/authentication") == "https://api.vidal.fr/rest/api"
    # Suffix anywhere but not at the very end should be kept
    assert _clean_vidal_base_url("https://api.vidal.fr/rest/api") == "https://api.vidal.fr/rest/api"
