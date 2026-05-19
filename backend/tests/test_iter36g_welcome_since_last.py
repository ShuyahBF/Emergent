"""Iter36g — Welcome briefing "since last visit" enrichment tests.

Validates that /me/welcome-briefing with last_seen_at returns a
`since_last_visit` block listing tickets / WA inbound / notes created
strictly after that timestamp.
"""
import asyncio
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestWelcomeSinceLastVisit:
    def test_since_last_visit_block_returns_diff(self):
        from server import me_welcome_briefing, db

        async def go():
            user = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            # Cleanup any test data
            await db.support_tickets.delete_many({"id": {"$regex": "^test-iter36g-"}})
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36g-"}})
            await db.user_notes_personal.delete_many({"id": {"$regex": "^test-iter36g-"}})
            # last_seen_at = 2h ago
            now = datetime.now(timezone.utc)
            last_seen = (now - timedelta(hours=2)).isoformat()
            # Seed: 2 new tickets (1h ago), 1 old ticket (3h ago = before)
            await db.support_tickets.insert_many([
                {"id": "test-iter36g-tk-new1", "number": "TKT-G-1", "client_id": user["id"],
                 "motif": "Nouveau souci 1", "status": "open",
                 "opened_at": (now - timedelta(hours=1)).isoformat(),
                 "created_at": (now - timedelta(hours=1)).isoformat()},
                {"id": "test-iter36g-tk-new2", "number": "TKT-G-2", "client_id": user["id"],
                 "motif": "Nouveau souci 2", "status": "open",
                 "opened_at": (now - timedelta(minutes=30)).isoformat(),
                 "created_at": (now - timedelta(minutes=30)).isoformat()},
                {"id": "test-iter36g-tk-old", "number": "TKT-G-OLD", "client_id": user["id"],
                 "motif": "Vieux ticket", "status": "open",
                 "opened_at": (now - timedelta(hours=3)).isoformat(),
                 "created_at": (now - timedelta(hours=3)).isoformat()},
            ])
            # Seed: 3 new WA inbound + 1 old
            await db.whatsapp_messages.insert_many([
                {"id": f"test-iter36g-wa-new-{i}", "client_id": user["id"],
                 "direction": "inbound", "phone_digits": "22670111",
                 "received_at": (now - timedelta(minutes=20 + i)).isoformat(),
                 "created_at": (now - timedelta(minutes=20 + i)).isoformat()}
                for i in range(3)
            ] + [
                {"id": "test-iter36g-wa-old", "client_id": user["id"],
                 "direction": "inbound", "phone_digits": "22670111",
                 "received_at": (now - timedelta(hours=4)).isoformat(),
                 "created_at": (now - timedelta(hours=4)).isoformat()},
            ])
            # Seed: 1 new note + 1 old
            await db.user_notes_personal.insert_many([
                {"id": "test-iter36g-note-new", "kind": "notes",
                 "owner_id": user["id"], "title": "Nouvelle note",
                 "created_at": (now - timedelta(minutes=5)).isoformat()},
                {"id": "test-iter36g-note-old", "kind": "notes",
                 "owner_id": user["id"], "title": "Vieille note",
                 "created_at": (now - timedelta(hours=6)).isoformat()},
            ])
            res = await me_welcome_briefing(last_seen_at=last_seen, user=user)
            # Cleanup
            await db.support_tickets.delete_many({"id": {"$regex": "^test-iter36g-"}})
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36g-"}})
            await db.user_notes_personal.delete_many({"id": {"$regex": "^test-iter36g-"}})
            return res

        res = _run(go())
        assert "since_last_visit" in res
        slv = res["since_last_visit"]
        assert slv is not None, "expected since_last_visit block when last_seen_at provided"
        # We seeded EXACTLY 2 new tickets, 3 new WA, 1 new note that should match
        # (other ambient data may exist for the admin user but we look for OURS)
        new_ids = {t["id"] for t in slv["new_tickets"]}
        assert "test-iter36g-tk-new1" in new_ids
        assert "test-iter36g-tk-new2" in new_ids
        assert "test-iter36g-tk-old" not in new_ids, "old ticket leaked into the diff"
        new_note_ids = {n["id"] for n in slv["new_notes"]}
        assert "test-iter36g-note-new" in new_note_ids
        assert "test-iter36g-note-old" not in new_note_ids
        # WA inbound counter is global to the scope — must be >= the 3 we seeded
        assert slv["new_whatsapp_count"] >= 3, slv
        assert slv["total_count"] >= 2 + 3 + 1
        # server_now is exposed for the frontend to refresh its localStorage stamp
        assert "server_now" in res and res["server_now"]

    def test_no_last_seen_returns_none(self):
        from server import me_welcome_briefing, db

        async def go():
            user = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            return await me_welcome_briefing(last_seen_at=None, user=user)

        res = _run(go())
        assert res["since_last_visit"] is None
