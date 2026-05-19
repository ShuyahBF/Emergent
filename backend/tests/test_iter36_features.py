"""Iter36 — Tests for the 4 new features:
  • Feature 1 : Top expéditeurs (in_directory + last_message_preview + import)
  • Feature 3 : Ticket close → auto-intervention with traceability
  • Feature 4 : Note de Service broadcast
"""
import asyncio
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================
# Feature 1 — Top expéditeurs (Iter36a)
# =============================================================
class TestTopSendersEnrichment:
    def test_top_contacts_have_in_directory_and_last_message(self):
        from server import me_wa_media_summary, db

        async def go():
            # Cleanup
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36a-"}})
            await db.directory_contacts.delete_many({"id": {"$regex": "^test-iter36a-"}})
            # Find an admin user
            user = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            cid = user["id"]
            # Seed 1 known + 1 unknown contact
            await db.directory_contacts.insert_one({
                "id": "test-iter36a-dir-1", "client_id": cid, "owner_id": cid,
                "name": "Alice Connue", "phone": "+22678991122", "phone_digits": "22678991122",
                "tags": [],
            })
            for i, digits in enumerate(["22678991122", "22679881133"]):
                for j in range(3):
                    await db.whatsapp_messages.insert_one({
                        "id": f"test-iter36a-{digits}-{j}", "client_id": cid,
                        "direction": "inbound", "phone_digits": digits, "from": digits,
                        "from_profile_name": f"Profile {i}",
                        "media_url": "https://example.com/x.jpg", "media_kind": "image",
                        "received_at": (datetime.now(timezone.utc) - timedelta(hours=j)).isoformat(),
                        "created_at": (datetime.now(timezone.utc) - timedelta(hours=j)).isoformat(),
                        "body": f"Coucou ceci est le message {j}",
                    })
            res = await me_wa_media_summary(days=7, user=user)
            # cleanup
            await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36a-"}})
            await db.directory_contacts.delete_many({"id": {"$regex": "^test-iter36a-"}})
            return res

        res = _run(go())
        top = res["top_contacts"]
        assert len(top) >= 2, top
        by_phone = {t["phone_digits"]: t for t in top}
        assert "22678991122" in by_phone
        assert "22679881133" in by_phone
        # Known one
        known = by_phone["22678991122"]
        assert known["in_directory"] is True, known
        assert known["contact_id"] == "test-iter36a-dir-1", known
        assert "message" in (known.get("last_message_preview") or "").lower(), known
        # Unknown one
        unknown = by_phone["22679881133"]
        assert unknown["in_directory"] is False, unknown


# =============================================================
# Feature 3 — Ticket close → auto-intervention (Iter36c)
# =============================================================
class TestTicketCloseAutoIntervention:
    def test_closing_ticket_creates_intervention(self):
        from server import me_close_ticket, db
        from models import TicketClosePayload

        async def go():
            await db.support_tickets.delete_many({"id": "test-iter36c-tk"})
            await db.interventions.delete_many({"source_ticket_id": "test-iter36c-tk"})
            user = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "full_name": 1, "client_id": 1, "parent_client_id": 1},
            )
            opened = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            ticket = {
                "id": "test-iter36c-tk", "number": "TKT-T-IT36C-1",
                "client_id": user["id"], "motif": "Test feature 36c",
                "status": "open", "opened_at": opened,
                "contact_name": "Bob", "contact_phone": "+22670000000",
                "notes": "Notes initiales",
            }
            await db.support_tickets.insert_one(ticket.copy())
            payload = TicketClosePayload(outcome="done", resolution_note="Réparé", notify_contact=False)
            r = await me_close_ticket(tid="test-iter36c-tk", payload=payload, user=user)
            # Fetch the created intervention
            inter = await db.interventions.find_one({"source_ticket_id": "test-iter36c-tk"}, {"_id": 0})
            # cleanup
            await db.support_tickets.delete_many({"id": "test-iter36c-tk"})
            await db.interventions.delete_many({"source_ticket_id": "test-iter36c-tk"})
            return r, inter

        r, inter = _run(go())
        # Response contains intervention info
        assert r["ok"] is True
        assert r["intervention"] is not None, r
        assert r["intervention"]["intervention_number"], r
        # Intervention has expected payload
        assert inter is not None, "Intervention not created in DB"
        assert inter["source_ticket_id"] == "test-iter36c-tk"
        assert inter["source_ticket_number"] == "TKT-T-IT36C-1"
        assert inter["status"] == "completed"
        assert "Test feature 36c" in inter["title"]
        assert "Réparé" in inter["description"]
        assert "Bob" in inter["description"]
        assert inter["technician"]  # populated
        # duration_hours roughly = 2 (we set opened 2h ago)
        assert inter["duration_hours"] is not None
        assert 1.5 <= float(inter["duration_hours"]) <= 2.5


# =============================================================
# Feature 4 — Note de Service broadcast (Iter36d)
# =============================================================
class TestNoteDeService:
    def test_rejects_private_note(self):
        from fastapi import HTTPException
        from server import me_send_note_de_service, db

        async def go():
            await db.user_notes_personal.delete_many({"id": "test-iter36d-private"})
            user = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            await db.user_notes_personal.insert_one({
                "id": "test-iter36d-private", "kind": "notes", "numero": "NTE-T-1",
                "owner_id": user["id"], "is_private": True,
                "content_html": "<p>secret</p>", "title": "secret",
            })
            try:
                await me_send_note_de_service(kind="notes", note_id="test-iter36d-private", user=user)
                return None
            except HTTPException as exc:
                await db.user_notes_personal.delete_many({"id": "test-iter36d-private"})
                return exc

        exc = _run(go())
        assert exc is not None and exc.status_code == 400
        assert "publique" in exc.detail.lower()

    def test_rejects_unnumbered_note(self):
        from fastapi import HTTPException
        from server import me_send_note_de_service, db

        async def go():
            await db.user_notes_personal.delete_many({"id": "test-iter36d-nonum"})
            user = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            await db.user_notes_personal.insert_one({
                "id": "test-iter36d-nonum", "kind": "notes", "numero": "",
                "owner_id": user["id"], "is_private": False,
                "content_html": "<p>txt</p>", "title": "no number",
            })
            try:
                await me_send_note_de_service(kind="notes", note_id="test-iter36d-nonum", user=user)
                return None
            except HTTPException as exc:
                await db.user_notes_personal.delete_many({"id": "test-iter36d-nonum"})
                return exc

        exc = _run(go())
        assert exc is not None and exc.status_code == 400
        assert "numéro" in exc.detail.lower()

    def test_broadcast_sends_to_each_suivi(self):
        """When WA is configured (or stubbed), broadcasting to N suivis yields
        N outbound rows in db.whatsapp_messages with source=note_de_service."""
        from server import me_send_note_de_service, db
        from unittest.mock import patch, AsyncMock

        async def go():
            await db.user_notes_personal.delete_many({"id": "test-iter36d-broadcast"})
            await db.tracked_users.delete_many({"id": {"$regex": "^test-iter36d-suivi-"}})
            await db.whatsapp_messages.delete_many({"source_note_id": "test-iter36d-broadcast"})
            user = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            cid = user["id"]
            await db.user_notes_personal.insert_one({
                "id": "test-iter36d-broadcast", "kind": "notes", "numero": "NTE-T-99",
                "owner_id": user["id"], "is_private": False, "client_id": cid,
                "content_html": "<p>Service test 36d</p>", "title": "broadcast",
            })
            await db.tracked_users.insert_many([
                {"id": "test-iter36d-suivi-1", "client_id": cid, "name": "Carla", "phone": "+22670111", "status": "active"},
                {"id": "test-iter36d-suivi-2", "client_id": cid, "name": "Diego", "whatsapp_number": "+22675222", "status": "active"},
            ])
            with patch("server._wa_send_template", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = {"ok": True, "message_id": "wa-test-id", "error": None}
                r = await me_send_note_de_service(kind="notes", note_id="test-iter36d-broadcast", user=user)
                call_count = mock_send.call_count
            outbound = await db.whatsapp_messages.count_documents({"source_note_id": "test-iter36d-broadcast"})
            await db.user_notes_personal.delete_many({"id": "test-iter36d-broadcast"})
            await db.tracked_users.delete_many({"id": {"$regex": "^test-iter36d-suivi-"}})
            await db.whatsapp_messages.delete_many({"source_note_id": "test-iter36d-broadcast"})
            return r, call_count, outbound

        r, call_count, outbound = _run(go())
        assert r["ok"] is True, r
        assert r["sent_count"] == 2, r
        assert r["total_targets"] == 2, r
        assert call_count == 2
        assert outbound == 2
