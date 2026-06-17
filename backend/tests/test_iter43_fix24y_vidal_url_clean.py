"""Iter43-fix24y (2026-06-16) — Tests for VIDAL base_url cleaning.

Re-introducing automatic URL cleanup after confirming with user that:
  - `https://api.vidal.fr/rest/api` is the correct API root
  - `http://api.vidal.fr/#!/rest/api` is the Angular API explorer URL (frontend only)
  - VIDAL refuses plain HTTP (force HTTPS)

The function `_clean_vidal_base_url` unfolds the hashbang and forces https.
"""
from __future__ import annotations

import pytest

from routes.vidal import _clean_vidal_base_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        # User's case: Angular hashbang URL → unfolded REST root
        ("http://api.vidal.fr/#!/rest/api", "https://api.vidal.fr/rest/api"),
        ("http://api.vidal.fr/#!/rest/api/", "https://api.vidal.fr/rest/api"),
        # Hashbang at root only → strip the fragment entirely
        ("http://api.vidal.fr/#!/", "https://api.vidal.fr"),
        ("http://api.vidal.fr/#!", "https://api.vidal.fr"),
        # Hash without `!`
        ("http://api.vidal.fr/#rest/api", "https://api.vidal.fr/rest/api"),
        # Already correct → unchanged (but http→https forced)
        ("https://api.vidal.fr/rest/api", "https://api.vidal.fr/rest/api"),
        ("https://api.vidal.fr/rest/api/", "https://api.vidal.fr/rest/api"),
        ("http://api.vidal.fr/rest/api", "https://api.vidal.fr/rest/api"),
        # api-test endpoint
        ("https://api-test.vidal.net/rest/api", "https://api-test.vidal.net/rest/api"),
        # Edge cases
        ("", ""),
        ("   ", ""),
        ("https://api.vidal.net/", "https://api.vidal.net"),
    ],
)
def test_clean_vidal_base_url(raw, expected):
    assert _clean_vidal_base_url(raw) == expected


def test_clean_handles_none():
    assert _clean_vidal_base_url(None) == ""


def test_https_is_forced():
    """VIDAL refuse les requêtes HTTP."""
    assert _clean_vidal_base_url("http://api.vidal.fr/rest/api").startswith("https://")
    assert _clean_vidal_base_url("http://api.vidal.fr/#!/rest/api").startswith("https://")
