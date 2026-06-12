"""Iter43-fix5 — Validate that GET /me/contacts enrichit chaque contact
d'un champ `last_interaction_at` (ISO string ou None) calculé via
wa_messages + sms_messages (match digits-10 sur whatsapp/phone).
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestLastInteractionAtEnrichment:
    def test_field_present_for_all_contacts(self):
        from server import me_list_contacts, db

        async def go():
            u = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            assert u is not None, "Admin user not seeded"
            items = await me_list_contacts(user=u)
            return items

        items = _run(go())
        assert isinstance(items, list)
        # Le champ doit exister sur chaque contact (peut être None)
        for c in items[:50]:  # sanity sample to keep output small
            assert "last_interaction_at" in c, f"Missing last_interaction_at on contact {c.get('id')}"
            v = c["last_interaction_at"]
            assert v is None or isinstance(v, str), f"Expected str or None, got {type(v)}"

    def test_contact_without_messages_returns_null(self):
        """Create a fresh contact with a clearly unused phone number, then
        verify last_interaction_at is None."""
        from server import me_list_contacts, db

        async def go():
            u = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            assert u is not None
            from server import _resolve_visible_client_ids
            cids = await _resolve_visible_client_ids(u)
            assert cids, "Admin user has no visible client_ids"
            cli = cids[0]
            # Unique phone unlikely to exist in any WA/SMS history
            unique_phone = f"+22699{uuid.uuid4().int % 10**8:08d}"
            cid = str(uuid.uuid4())
            doc = {
                "id": cid,
                "client_id": cli,
                "owner_user_id": u["id"],
                "name": f"TEST_lia_{cid[:8]}",
                "phone": unique_phone,
                "whatsapp": unique_phone,
                "shared": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.directory_contacts.insert_one(doc)
            try:
                items = await me_list_contacts(user=u)
                target = next((x for x in items if x.get("id") == cid), None)
                assert target is not None, "Newly created contact not returned"
                assert "last_interaction_at" in target
                assert target["last_interaction_at"] is None, (
                    f"Expected None for contact with no messages, got {target['last_interaction_at']!r}"
                )
            finally:
                await db.directory_contacts.delete_one({"id": cid})

        _run(go())

    def test_contact_with_wa_message_gets_timestamp(self):
        """Insert a fake WA message for a fresh contact and confirm
        last_interaction_at reflects it."""
        from server import me_list_contacts, db

        async def go():
            u = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            cli = u.get("client_id") or u.get("parent_client_id") or "sawali_smart_systems"
            from server import _resolve_visible_client_ids as _rvc
            cids2 = await _rvc(u)
            if cids2:
                cli = cids2[0]
            unique_digits = f"77{uuid.uuid4().int % 10**8:08d}"  # 10 digits
            phone = f"+226{unique_digits}"
            cid = str(uuid.uuid4())
            ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            await db.directory_contacts.insert_one({
                "id": cid,
                "client_id": cli,
                "owner_user_id": u["id"],
                "name": f"TEST_lia_wa_{cid[:8]}",
                "phone": phone,
                "whatsapp": phone,
                "shared": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            wa_msg_id = str(uuid.uuid4())
            await db.whatsapp_messages.insert_one({
                "id": wa_msg_id,
                "from": phone,
                "to": "+22670000000",
                "timestamp": ts,
                "created_at": ts,
                "direction": "inbound",
                "text": "TEST_lia_wa",
            })
            try:
                items = await me_list_contacts(user=u)
                target = next((x for x in items if x.get("id") == cid), None)
                assert target is not None
                assert target.get("last_interaction_at") is not None, (
                    "Expected last_interaction_at to be populated after WA message insert"
                )
                # Should match (string compare since stored as str)
                assert ts in str(target["last_interaction_at"]) or str(target["last_interaction_at"]) == ts, (
                    f"Got {target['last_interaction_at']!r}, expected near {ts!r}"
                )
            finally:
                await db.directory_contacts.delete_one({"id": cid})
                await db.whatsapp_messages.delete_one({"id": wa_msg_id})

        _run(go())
