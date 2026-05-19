"""Iter36h — Top expéditeurs uniqueness fix.

The "Importer" button must only appear when no directory contact already
matches the phone number on EITHER `phone` OR `whatsapp` fields.
"""
import asyncio
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


SAMPLE_DIGITS = "22678998877"  # Unique digits not used elsewhere in test DB


async def _setup(extra_dir_contact=None):
    from server import db
    await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36h-"}})
    await db.directory_contacts.delete_many({"id": {"$regex": "^test-iter36h-"}})
    user = await db.users.find_one(
        {"email": "admin@sawalismartsystems.com"},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
    )
    now = datetime.now(timezone.utc)
    for i in range(3):
        await db.whatsapp_messages.insert_one({
            "id": f"test-iter36h-wa-{i}", "client_id": user["id"],
            "direction": "inbound", "phone_digits": SAMPLE_DIGITS,
            "from": f"+{SAMPLE_DIGITS}",
            "media_url": "https://example.com/x.jpg", "media_kind": "image",
            "received_at": (now - timedelta(hours=i)).isoformat(),
            "created_at": (now - timedelta(hours=i)).isoformat(),
            "body": "Test message",
        })
    if extra_dir_contact:
        await db.directory_contacts.insert_one({
            "id": "test-iter36h-c1", "client_id": user["id"], "owner_id": user["id"],
            "name": "Existing", **extra_dir_contact,
        })
    return user


async def _cleanup():
    from server import db
    await db.whatsapp_messages.delete_many({"id": {"$regex": "^test-iter36h-"}})
    await db.directory_contacts.delete_many({"id": {"$regex": "^test-iter36h-"}})


def _call_summary_with(extra_dir_contact):
    """Returns the matching top_contact entry (or None)."""
    from server import me_wa_media_summary

    async def go():
        user = await _setup(extra_dir_contact)
        res = await me_wa_media_summary(days=7, user=user)
        await _cleanup()
        return next(
            (t for t in res["top_contacts"] if t["phone_digits"] == SAMPLE_DIGITS),
            None,
        )

    return _run(go())


class TestTopSendersUniqueness:
    def test_match_via_legacy_phone_digits(self):
        m = _call_summary_with({"phone_digits": SAMPLE_DIGITS})
        assert m is not None and m["in_directory"] is True, m

    def test_match_via_formatted_phone_spaced(self):
        m = _call_summary_with({"phone": "+226 78 99 88 77"})
        assert m is not None and m["in_directory"] is True, m

    def test_match_via_phone_with_00_prefix(self):
        m = _call_summary_with({"phone": "0022678998877"})
        assert m is not None and m["in_directory"] is True, m

    def test_match_via_whatsapp_field(self):
        m = _call_summary_with({"phone": "", "whatsapp": "+226 78 99 88 77"})
        assert m is not None and m["in_directory"] is True, m

    def test_no_match_when_not_in_directory(self):
        m = _call_summary_with(None)
        assert m is not None and m["in_directory"] is False, m

    def test_import_endpoint_idempotent_on_formatted_phone(self):
        """A formatted phone in DB must short-circuit the import (no duplicate)."""
        from server import me_wa_import_by_phone, WaImportByPhoneRequest, db

        async def go():
            user = await _setup({"phone": "+226 78 99 88 77"})
            r = await me_wa_import_by_phone(
                payload=WaImportByPhoneRequest(phone_digits=SAMPLE_DIGITS),
                user=user,
            )
            cnt = await db.directory_contacts.count_documents({"client_id": user["id"], "id": "test-iter36h-c1"})
            await _cleanup()
            return r, cnt

        r, cnt = _run(go())
        assert r["already_present"] is True, r
        assert cnt == 1, f"expected single contact, got {cnt}"
