"""Iter43-fix24r (2026-06) — Tests for VIDAL base_url auto-cleaning.

When admins paste the Angular frontend URL (`http://api.vidal.fr/#!/rest/api`)
into the AdminSettings VIDAL config, the hashbang fragment must be "unfolded"
so the resulting URL is a valid REST root (`http://api.vidal.fr/rest/api`).
"""
from __future__ import annotations

import pytest

from routes.vidal import _clean_vidal_base_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        # User's reported case: Angular hashbang frontend URL
        ("http://api.vidal.fr/#!/rest/api", "http://api.vidal.fr/rest/api"),
        # Same case with trailing slash
        ("http://api.vidal.fr/#!/rest/api/", "http://api.vidal.fr/rest/api"),
        # Hashbang at the root only (no extra path) — strip it entirely
        ("http://api.vidal.fr/#!/", "http://api.vidal.fr"),
        ("http://api.vidal.fr/#!", "http://api.vidal.fr"),
        # Plain # hash without `!`
        ("http://api.vidal.fr/#rest/api", "http://api.vidal.fr/rest/api"),
        # Already clean URL — unchanged
        ("https://api.vidal.net/rest/api", "https://api.vidal.net/rest/api"),
        ("https://api.vidal.net/rest/api/", "https://api.vidal.net/rest/api"),
        # Empty / None-ish
        ("", ""),
        ("   ", ""),
        # Just trailing slash
        ("https://api.vidal.net/", "https://api.vidal.net"),
    ],
)
def test_clean_vidal_base_url(raw, expected):
    assert _clean_vidal_base_url(raw) == expected


def test_clean_handles_none():
    assert _clean_vidal_base_url(None) == ""
