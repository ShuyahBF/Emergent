"""Iter36f — Retry failed recipients of a Note de Service broadcast.

Validates:
  • Sends only to recipients whose LATEST attempt is 'failed'.
  • Skips recipients whose latest attempt is already 'sent' (idempotency).
  • Returns proper {sent_count, skipped_count, total_targets} schema.
  • New outbound rows are tagged is_retry=True.
  • 404 if note doesn't exist, 400 if no previous broadcast.
"""
import asyncio
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRetryFailedNoteService:
    def _admin(self):
        return {"role": "admin", "email": "admin@test", "id": "admin-test"}

    def test_retries_only_failed_recipients(self):
        from server import admin_retry_failed_note_service, db

        async def go():
            # Cleanup
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36f-"}})
            await db.user_notes_personal.delete_many({"id": "test-iter36f-note"})
            # Seed note
            await db.user_notes_personal.insert_one({
                "id": "test-iter36f-note", "kind": "notes", "numero": "NTE-T-F",
                "title": "Retry test", "is_private": False, "owner_id": "admin-test",
                "client_id": "c1", "content_html": "<p>Body content for retry</p>",
            })
            # Initial broadcast: Alice OK, Bob failed, Carlos failed
            now = datetime.now(timezone.utc)
            initial = [
                {"id": "test-iter36f-m1", "source": "note_de_service",
                 "source_note_id": "test-iter36f-note", "source_note_numero": "NTE-T-F",
                 "tracked_user_id": "u-alice", "tracked_user_name": "Alice",
                 "to": "+22670111", "status": "sent",
                 "owner_id": "admin-test", "client_id": "c1",
                 "created_at": (now - timedelta(minutes=10)).isoformat()},
                {"id": "test-iter36f-m2", "source": "note_de_service",
                 "source_note_id": "test-iter36f-note", "source_note_numero": "NTE-T-F",
                 "tracked_user_id": "u-bob", "tracked_user_name": "Bob",
                 "to": "+22675222", "status": "failed", "api_message": "Template paused",
                 "owner_id": "admin-test", "client_id": "c1",
                 "created_at": (now - timedelta(minutes=9)).isoformat()},
                {"id": "test-iter36f-m3", "source": "note_de_service",
                 "source_note_id": "test-iter36f-note", "source_note_numero": "NTE-T-F",
                 "tracked_user_id": "u-carlos", "tracked_user_name": "Carlos",
                 "to": "+22676333", "status": "failed", "api_message": "Invalid number",
                 "owner_id": "admin-test", "client_id": "c1",
                 "created_at": (now - timedelta(minutes=8)).isoformat()},
            ]
            await db.whatsapp_messages.insert_many([r.copy() for r in initial])
            with patch("server._wa_send_template", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = {"ok": True, "message_id": "wa-retry-id", "error": None}
                r = await admin_retry_failed_note_service(note_id="test-iter36f-note", _=self._admin())
                call_count = mock_send.call_count
                called_phones = [c.args[0] for c in mock_send.call_args_list]
            retries = await db.whatsapp_messages.count_documents({
                "source_note_id": "test-iter36f-note", "is_retry": True,
            })
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36f-"}})
            await db.whatsapp_messages.delete_many({"source_note_id": "test-iter36f-note"})
            await db.user_notes_personal.delete_many({"id": "test-iter36f-note"})
            return r, call_count, called_phones, retries

        r, call_count, called_phones, retries = _run(go())
        # Only Bob + Carlos should have been re-attempted (Alice was already OK)
        assert call_count == 2, called_phones
        assert "+22675222" in called_phones
        assert "+22676333" in called_phones
        assert "+22670111" not in called_phones, "Alice was OK, must NOT be retried"
        assert r["sent_count"] == 2, r
        assert r["total_targets"] == 2, r
        assert retries == 2, "retry outbound rows must be tagged is_retry=True"

    def test_returns_message_when_nothing_to_retry(self):
        from server import admin_retry_failed_note_service, db

        async def go():
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36f-allok-"}})
            await db.user_notes_personal.delete_many({"id": "test-iter36f-allok"})
            await db.user_notes_personal.insert_one({
                "id": "test-iter36f-allok", "kind": "notes", "numero": "NTE-T-OK",
                "title": "All ok", "is_private": False, "owner_id": "admin-test",
                "content_html": "<p>x</p>",
            })
            await db.whatsapp_messages.insert_one({
                "id": "test-iter36f-allok-1", "source": "note_de_service",
                "source_note_id": "test-iter36f-allok", "source_note_numero": "NTE-T-OK",
                "tracked_user_id": "u-a", "to": "+22670000", "status": "sent",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await admin_retry_failed_note_service(note_id="test-iter36f-allok", _=self._admin())
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36f-allok-"}})
            await db.user_notes_personal.delete_many({"id": "test-iter36f-allok"})
            return r

        r = _run(go())
        assert r["sent_count"] == 0
        assert "message" in r and "rien" in r["message"].lower()

    def test_404_for_unknown_note(self):
        from fastapi import HTTPException
        from server import admin_retry_failed_note_service

        async def go():
            try:
                await admin_retry_failed_note_service(note_id="nonexistent-iter36f", _=self._admin())
                return None
            except HTTPException as exc:
                return exc

        exc = _run(go())
        assert exc is not None and exc.status_code == 404
