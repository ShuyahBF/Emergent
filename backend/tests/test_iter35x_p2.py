"""Iter35x — P2 features tests:
  • Secret change audit (db.secret_change_audit) + email notify (best-effort)
  • Alexa Voice Monkey notify helper
"""
import asyncio
import sys
from unittest.mock import patch, AsyncMock

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================
# P2-1 : Secret change audit
# =============================================================
class TestSecretChangeAudit:
    def test_audit_tracks_vault_key_change(self):
        from server import _audit_secret_changes, db, VAULT_KEYS, _uuid

        async def go():
            # Cleanup before
            await db.secret_change_audit.delete_many({"actor_email": "test-audit-x@test"})
            # Simulate a vault key update — pick any key actually in VAULT_KEYS
            assert "public_base_url" in VAULT_KEYS
            await _audit_secret_changes(
                update={"public_base_url": "https://test-iter35x.com"},
                actor={"email": "test-audit-x@test", "id": "actor-1"},
                prev_full={"public_base_url": ""},
            )
            audit = await db.secret_change_audit.find(
                {"actor_email": "test-audit-x@test"}, {"_id": 0}
            ).to_list(10)
            await db.secret_change_audit.delete_many({"actor_email": "test-audit-x@test"})
            return audit

        audit = _run(go())
        assert len(audit) == 1, audit
        assert audit[0]["key"] == "public_base_url"
        assert audit[0]["action"] == "created"  # prev empty, new set → created
        assert audit[0]["fingerprint"]  # SHA256 prefix
        # Audit must NEVER contain the value
        for k, v in audit[0].items():
            assert "test-iter35x.com" not in str(v), f"Value leaked in audit field {k}: {v}"

    def test_no_audit_when_value_unchanged(self):
        from server import _audit_secret_changes, db

        async def go():
            await db.secret_change_audit.delete_many({"actor_email": "test-noop-x@test"})
            await _audit_secret_changes(
                update={"public_base_url": "same"},
                actor={"email": "test-noop-x@test", "id": "a2"},
                prev_full={"public_base_url": "same"},
            )
            n = await db.secret_change_audit.count_documents({"actor_email": "test-noop-x@test"})
            await db.secret_change_audit.delete_many({"actor_email": "test-noop-x@test"})
            return n

        n = _run(go())
        assert n == 0, "no-op updates must not produce audit rows"

    def test_endpoint_returns_audit_rows(self):
        from server import _audit_secret_changes, admin_secret_change_audit, db

        async def go():
            await db.secret_change_audit.delete_many({"actor_email": "endpoint-x@test"})
            await _audit_secret_changes(
                update={"public_base_url": "https://endpoint-test.com"},
                actor={"email": "endpoint-x@test", "id": "a3"},
                prev_full={"public_base_url": "https://before.com"},
            )
            res = await admin_secret_change_audit(key=None, limit=50, _={"email": "admin@test"})
            await db.secret_change_audit.delete_many({"actor_email": "endpoint-x@test"})
            return res

        res = _run(go())
        assert "items" in res
        keys_in_audit = {it["key"] for it in res["items"]}
        assert "public_base_url" in keys_in_audit


# =============================================================
# P2-2 : Alexa Voice Monkey
# =============================================================
class TestAlexaVoiceMonkey:
    def test_skips_when_disabled(self):
        from server import _alexa_notify, db

        async def go():
            previous = await db.settings.find_one({"_id": "global"}, {"_id": 0, "alexa_enabled": 1, "alexa_webhook_url": 1, "alexa_events": 1}) or {}
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"alexa_enabled": False, "alexa_webhook_url": "https://example.com", "alexa_events": ["wa_inbound"]}},
                upsert=True,
            )
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                await _alexa_notify("wa_inbound", "test")
            await db.settings.update_one({"_id": "global"}, {"$set": previous})
            return mock_post.call_count

        n = _run(go())
        assert n == 0, "must not POST when alexa_enabled is false"

    def test_skips_when_event_not_subscribed(self):
        from server import _alexa_notify, db

        async def go():
            previous = await db.settings.find_one({"_id": "global"}, {"_id": 0, "alexa_enabled": 1, "alexa_webhook_url": 1, "alexa_events": 1}) or {}
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"alexa_enabled": True, "alexa_webhook_url": "https://example.com", "alexa_events": ["wa_inbound"]}},
                upsert=True,
            )
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                await _alexa_notify("sms_inbound", "test")  # not subscribed
            await db.settings.update_one({"_id": "global"}, {"$set": previous})
            return mock_post.call_count

        n = _run(go())
        assert n == 0, "must not POST when event not in alexa_events"

    def test_posts_when_enabled_and_event_subscribed(self):
        from server import _alexa_notify, db

        async def go():
            previous = await db.settings.find_one({"_id": "global"}, {"_id": 0, "alexa_enabled": 1, "alexa_webhook_url": 1, "alexa_events": 1}) or {}
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"alexa_enabled": True, "alexa_webhook_url": "https://example.com/voice", "alexa_events": ["wa_inbound", "support_load_critical"]}},
                upsert=True,
            )
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                await _alexa_notify("wa_inbound", "Nouveau message")
            await db.settings.update_one({"_id": "global"}, {"$set": previous})
            return mock_post

        mock_post = _run(go())
        assert mock_post.call_count == 1, "should POST exactly once"
        _, kwargs = mock_post.call_args
        body = kwargs.get("json") or {}
        assert body.get("event") == "wa_inbound"
        assert body.get("event_label") == "WhatsApp reçu"
        assert "Nouveau message" in body.get("announcement", "")
