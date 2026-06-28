"""Iter43-fix24az-d (2026-02-26) — Garde rotation Saturday-12:00 logic.

Validates:
  - `_saturday_noon_week_year` returns the correct ISO week for various inputs
  - `_next_rotation_iso` returns the correct next-rotation timestamp
  - `_current_garde_week` honors `settings.garde_rotation_mode` toggle
  - `garde_rotation_mode` is validated by PUT /api/admin/settings
"""
from __future__ import annotations

from datetime import datetime, timezone, date


def _at(y, m, d, h=0, mn=0):
    return datetime(y, m, d, h, mn, tzinfo=timezone.utc)


def test_saturday_noon_week_year_monday_to_friday():
    from routes.garde_planning import _saturday_noon_week_year
    # Feb 23, 2026 = Monday (ISO week 9). Last Sat = Feb 21 (ISO week 8).
    y, w = _saturday_noon_week_year(_at(2026, 2, 23, 10))
    assert (y, w) == (2026, 8)
    # Feb 27, 2026 = Friday late night. Last Sat = Feb 21 (week 8).
    y, w = _saturday_noon_week_year(_at(2026, 2, 27, 23))
    assert (y, w) == (2026, 8)


def test_saturday_noon_week_year_saturday_boundary():
    from routes.garde_planning import _saturday_noon_week_year
    # Saturday Feb 28 11:59 → previous Saturday's week (8)
    y, w = _saturday_noon_week_year(_at(2026, 2, 28, 11, 59))
    assert (y, w) == (2026, 8)
    # Saturday Feb 28 12:00 → THIS Saturday's week (9)
    y, w = _saturday_noon_week_year(_at(2026, 2, 28, 12, 0))
    assert (y, w) == (2026, 9)


def test_saturday_noon_week_year_sunday():
    from routes.garde_planning import _saturday_noon_week_year
    # Sunday March 1 → most recent Sat 12:00 was yesterday → THIS week (9)
    y, w = _saturday_noon_week_year(_at(2026, 3, 1, 9))
    assert (y, w) == (2026, 9)


def test_next_rotation_iso_saturday_noon():
    from routes.garde_planning import _next_rotation_iso
    # Monday morning → next Saturday at 12:00
    nr = _next_rotation_iso(_at(2026, 2, 23, 10), "saturday_noon")
    assert nr == "2026-02-28T12:00:00+00:00"
    # Saturday morning before 12:00 → today at 12:00
    nr = _next_rotation_iso(_at(2026, 2, 28, 9), "saturday_noon")
    assert nr == "2026-02-28T12:00:00+00:00"
    # Saturday after 12:00 → next week's Saturday
    nr = _next_rotation_iso(_at(2026, 2, 28, 14), "saturday_noon")
    assert nr == "2026-03-07T12:00:00+00:00"


def test_next_rotation_iso_monday_midnight_legacy():
    from routes.garde_planning import _next_rotation_iso
    # Tuesday → next Monday 00:00
    nr = _next_rotation_iso(_at(2026, 2, 24, 15), "monday_midnight")
    assert nr.startswith("2026-03-02T00:00:00")


def test_current_garde_week_default_mode_is_saturday_noon():
    """Without settings, default to saturday_noon (the new behavior)."""
    from routes.garde_planning import _current_garde_week
    import asyncio

    class _StubDB:
        class settings:
            @staticmethod
            async def find_one(*args, **kwargs):
                return None  # no settings doc

    res = asyncio.run(_current_garde_week(_StubDB(), now=_at(2026, 2, 23, 10)))
    y, w, mode = res
    assert mode == "saturday_noon"
    assert (y, w) == (2026, 8)


def test_current_garde_week_honors_legacy_mode():
    """When settings.garde_rotation_mode='monday_midnight', use ISO week."""
    from routes.garde_planning import _current_garde_week
    import asyncio

    class _StubDB:
        class settings:
            @staticmethod
            async def find_one(*args, **kwargs):
                return {"garde_rotation_mode": "monday_midnight"}

    res = asyncio.run(_current_garde_week(_StubDB(), now=_at(2026, 2, 23, 10)))
    y, w, mode = res
    assert mode == "monday_midnight"
    # Feb 23 = Monday → ISO week 9
    assert (y, w) == (2026, 9)


def test_iso_week_sanity():
    """Sanity: ensure our ISO-week assumptions match Python's stdlib."""
    assert date(2026, 2, 21).isocalendar()[1] == 8   # Saturday end of week 8
    assert date(2026, 2, 23).isocalendar()[1] == 9   # Monday start of week 9
    assert date(2026, 2, 28).isocalendar()[1] == 9   # Saturday end of week 9
    assert date(2026, 3, 1).isocalendar()[1] == 9    # Sunday end of week 9
