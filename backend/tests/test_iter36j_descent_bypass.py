"""Iter36j — Verrouillage 1h après descente : doit être levé pour
admin / superviseur / Moderation / Administrateur / Superviseur (tracked).

Reproduit le scénario : descent_time = 00:00, l'heure courante est >> 01:00,
donc la fenêtre est dépassée. Sans le fix, _check_descent_window lèverait
HTTP 403. Avec le fix, les utilisateurs élevés passent.
"""
import asyncio
import sys
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _force_lock_window():
    """Set descent_time to a value guaranteed to be > 1h ago (00:00 UTC).

    Restored after each test.
    """
    from server import db

    async def setup():
        prev = await db.settings.find_one({"_id": "global"}, {"_id": 0, "descent_time": 1}) or {}
        await db.settings.update_one(
            {"_id": "global"}, {"$set": {"descent_time": "00:00"}}, upsert=True
        )
        return prev

    async def teardown(prev):
        await db.settings.update_one(
            {"_id": "global"}, {"$set": {"descent_time": prev.get("descent_time") or ""}}
        )

    prev = _run(setup())
    yield
    _run(teardown(prev))


class TestDescentWindowBypass:
    def test_admin_bypasses_lock(self):
        from server import _check_descent_window

        async def go():
            # No exception expected
            await _check_descent_window(action_label="enregistrement", user={"role": "admin"})

        _run(go())  # would raise if not bypassed

    def test_superviseur_bypasses_lock(self):
        from server import _check_descent_window

        async def go():
            await _check_descent_window(action_label="enregistrement", user={"role": "superviseur"})

        _run(go())

    def test_tracked_moderation_bypasses_lock(self):
        from server import _check_descent_window

        async def go():
            await _check_descent_window(
                action_label="enregistrement",
                user={"role": "tracked", "tracked_role": "Moderation"},
            )

        _run(go())

    def test_tracked_administrateur_bypasses_lock(self):
        from server import _check_descent_window

        async def go():
            await _check_descent_window(
                action_label="enregistrement",
                user={"role": "tracked", "tracked_role": "Administrateur"},
            )

        _run(go())

    def test_regular_agent_still_locked(self):
        """A normal tracked user (no elevated role) must STILL get HTTP 403."""
        from server import _check_descent_window

        async def go():
            try:
                await _check_descent_window(
                    action_label="enregistrement",
                    user={"role": "tracked", "tracked_role": "Agent"},
                )
                return None
            except HTTPException as exc:
                return exc

        exc = _run(go())
        assert exc is not None, "regular agent should be locked after the 1h window"
        assert exc.status_code == 403, exc
        assert "verrouill" in exc.detail.lower(), exc.detail

    def test_no_descent_time_means_no_lock(self):
        """If descent_time is empty, neither admin nor agent is locked."""
        from server import _check_descent_window, db

        async def go():
            prev = await db.settings.find_one({"_id": "global"}, {"_id": 0, "descent_time": 1}) or {}
            await db.settings.update_one(
                {"_id": "global"}, {"$set": {"descent_time": ""}}, upsert=True
            )
            try:
                await _check_descent_window(
                    action_label="enregistrement",
                    user={"role": "tracked", "tracked_role": "Agent"},
                )
                ok = True
            except HTTPException:
                ok = False
            await db.settings.update_one(
                {"_id": "global"}, {"$set": {"descent_time": prev.get("descent_time") or ""}}
            )
            return ok

        ok = _run(go())
        assert ok is True, "descent_time empty → no lock for anyone"
