"""Iter36e — Admin history of Note de Service broadcasts.

Validates /admin/note-service/history aggregates broadcasts by source note
with sent/failed counts and recipient details, no values leaked.
"""
import asyncio
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestNoteServiceHistory:
    def _admin(self):
        return {"role": "admin", "email": "admin@test", "id": "admin-test"}

    def test_history_groups_by_source_note(self):
        from server import admin_note_service_history, db

        async def go():
            # Seed two broadcasts (one with 2 OK + 1 KO, another with 1 OK)
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36e-"}})
            await db.user_notes_personal.delete_many({"id": {"$regex": "^test-iter36e-note-"}})
            now = datetime.now(timezone.utc)
            await db.user_notes_personal.insert_many([
                {"id": "test-iter36e-note-A", "kind": "notes", "numero": "NTE-T-A",
                 "title": "Note A", "is_private": False, "owner_id": "admin-test"},
                {"id": "test-iter36e-note-B", "kind": "notes", "numero": "NTE-T-B",
                 "title": "Note B", "is_private": False, "owner_id": "admin-test"},
            ])
            rows = [
                {"id": "test-iter36e-A-1", "source": "note_de_service",
                 "source_note_id": "test-iter36e-note-A", "source_note_numero": "NTE-T-A",
                 "template_name": "notedeservice_fr", "status": "sent",
                 "tracked_user_name": "Alice", "to": "+22670111",
                 "owner_id": "admin-test", "client_id": "c1",
                 "created_at": (now - timedelta(minutes=5)).isoformat()},
                {"id": "test-iter36e-A-2", "source": "note_de_service",
                 "source_note_id": "test-iter36e-note-A", "source_note_numero": "NTE-T-A",
                 "template_name": "notedeservice_fr", "status": "sent",
                 "tracked_user_name": "Bob", "to": "+22670222",
                 "owner_id": "admin-test", "client_id": "c1",
                 "created_at": (now - timedelta(minutes=4)).isoformat()},
                {"id": "test-iter36e-A-3", "source": "note_de_service",
                 "source_note_id": "test-iter36e-note-A", "source_note_numero": "NTE-T-A",
                 "template_name": "notedeservice_fr", "status": "failed",
                 "api_message": "Numéro invalide",
                 "tracked_user_name": "Carlos", "to": "+22670333",
                 "owner_id": "admin-test", "client_id": "c1",
                 "created_at": (now - timedelta(minutes=3)).isoformat()},
                {"id": "test-iter36e-B-1", "source": "note_de_service",
                 "source_note_id": "test-iter36e-note-B", "source_note_numero": "NTE-T-B",
                 "template_name": "notedeservice_fr", "status": "sent",
                 "tracked_user_name": "Diane", "to": "+22670444",
                 "owner_id": "admin-test", "client_id": "c1",
                 "created_at": (now - timedelta(minutes=1)).isoformat()},
            ]
            await db.whatsapp_messages.insert_many([r.copy() for r in rows])
            res = await admin_note_service_history(limit=20, _=self._admin())
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36e-"}})
            await db.user_notes_personal.delete_many({"id": {"$regex": "^test-iter36e-note-"}})
            return res

        res = _run(go())
        notes = {r["note_id"]: r for r in res["items"]
                 if r["note_id"] in ("test-iter36e-note-A", "test-iter36e-note-B")}
        assert "test-iter36e-note-A" in notes, notes
        assert "test-iter36e-note-B" in notes, notes
        a = notes["test-iter36e-note-A"]
        b = notes["test-iter36e-note-B"]
        assert a["sent_count"] == 2 and a["failed_count"] == 1, a
        assert b["sent_count"] == 1 and b["failed_count"] == 0, b
        assert a["recipient_count"] == 3
        assert a["note_title"] == "Note A"
        assert a["note_numero"] == "NTE-T-A"
        # Recipients exposed with status + error
        names = {r["tracked_user_name"] for r in a["recipients"]}
        assert names == {"Alice", "Bob", "Carlos"}, names
        err = [r for r in a["recipients"] if r["status"] == "failed"][0]
        assert err["error"] == "Numéro invalide"
        # B sorted before A (more recent)? No, A's last is most recent (minute -3 vs -1)
        # Actually B is created -1, A's last is -3 → B should be first
        idx_a = next(i for i, x in enumerate(res["items"]) if x["note_id"] == "test-iter36e-note-A")
        idx_b = next(i for i, x in enumerate(res["items"]) if x["note_id"] == "test-iter36e-note-B")
        assert idx_b < idx_a, "B should be first (more recent last_sent_at)"
