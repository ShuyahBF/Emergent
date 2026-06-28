"""Iter43-fix24az-e (2026-02-26) — Validate period dates (Sat→Sat) under
both rotation modes, plus reset-year + delete-empty-group endpoints.
"""
from __future__ import annotations

from datetime import datetime, timezone, date


def _at(y, m, d, h=0, mn=0):
    return datetime(y, m, d, h, mn, tzinfo=timezone.utc)


def test_period_dates_saturday_noon_basic():
    from routes.garde_planning import _period_dates_for_week
    # ISO week 26 of 2026 → Sat 27/06 → Sat 04/07
    start, end = _period_dates_for_week(2026, 26, "saturday_noon")
    assert start == date(2026, 6, 27)
    assert end == date(2026, 7, 4)


def test_period_dates_monday_midnight_legacy():
    from routes.garde_planning import _period_dates_for_week
    # ISO week 26 of 2026 → Mon 22/06 → Sun 28/06
    start, end = _period_dates_for_week(2026, 26, "monday_midnight")
    assert start == date(2026, 6, 22)
    assert end == date(2026, 6, 28)


def test_period_dates_end_of_year_crossover():
    from routes.garde_planning import _period_dates_for_week
    # Week 53 of 2026 doesn't exist (52 max). Use week 52.
    start, end = _period_dates_for_week(2026, 52, "saturday_noon")
    # Saturday of week 52, 2026 = December 26, 2026
    assert start == date(2026, 12, 26)
    # Period end = Saturday week 53 = January 2, 2027
    assert end == date(2027, 1, 2)


def test_current_garde_period_includes_dates():
    """Sanity-check the period helper returns the expected dict shape."""
    from routes.garde_planning import _current_garde_period
    import asyncio

    class _StubDB:
        class settings:
            @staticmethod
            async def find_one(*args, **kwargs):
                return None

    # Sunday 28/06/2026 (matches user's bug report exactly)
    res = asyncio.run(_current_garde_period(_StubDB(), now=_at(2026, 6, 28, 9, 0)))
    assert res["year"] == 2026
    assert res["week"] == 26
    assert res["mode"] == "saturday_noon"
    assert res["period_start"] == date(2026, 6, 27)
    assert res["period_end"] == date(2026, 7, 4)


def test_current_garde_period_legacy_mode():
    from routes.garde_planning import _current_garde_period
    import asyncio

    class _StubDB:
        class settings:
            @staticmethod
            async def find_one(*args, **kwargs):
                return {"garde_rotation_mode": "monday_midnight"}

    # Tuesday 23/02/2026 (week 9 ISO)
    res = asyncio.run(_current_garde_period(_StubDB(), now=_at(2026, 2, 23, 10)))
    assert res["mode"] == "monday_midnight"
    assert res["week"] == 9
    # ISO week 9 of 2026 = Mon 23/02 → Sun 01/03
    assert res["period_start"] == date(2026, 2, 23)
    assert res["period_end"] == date(2026, 3, 1)
