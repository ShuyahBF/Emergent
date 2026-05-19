"""Iter35w — Test endpoint for critical URLs (Coffre-fort).

Validates the /admin/settings/test-url endpoint:
  • Rejects non-testable keys (e.g. tracking_endpoint, smtp_host, …)
  • Rejects when the setting is not configured
  • Successfully pings a real URL (httpbin.org) and surfaces status/timing
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeAdmin(dict):
    pass


_ADMIN = FakeAdmin({"id": "admin-test", "email": "admin@sawalismartsystems.com", "role": "admin"})


class TestCriticalUrlTester:
    def test_rejects_unknown_key(self):
        from fastapi import HTTPException
        from server import admin_test_critical_url, CriticalUrlTestRequest

        async def go():
            try:
                await admin_test_critical_url(CriticalUrlTestRequest(key="smtp_host"), _=_ADMIN)
                return None
            except HTTPException as exc:
                return exc

        exc = _run(go())
        assert exc is not None and exc.status_code == 400
        assert "non testable" in exc.detail.lower()

    def test_rejects_unconfigured_key(self):
        """When the setting is empty, the endpoint must return 400."""
        from fastapi import HTTPException
        from server import admin_test_critical_url, CriticalUrlTestRequest, db

        async def go():
            # Wipe health_webhook_url to ensure it's empty
            await db.settings.update_one({"_id": "global"}, {"$set": {"health_webhook_url": ""}}, upsert=True)
            try:
                await admin_test_critical_url(CriticalUrlTestRequest(key="health_webhook_url"), _=_ADMIN)
                return None
            except HTTPException as exc:
                return exc

        exc = _run(go())
        assert exc is not None and exc.status_code == 400
        assert "configur" in exc.detail.lower()

    def test_successful_ping_to_httpbin(self):
        """Set webhook_base_url to httpbin's POST echo and verify the test works."""
        from server import admin_test_critical_url, CriticalUrlTestRequest, db

        async def go():
            # Temporarily set webhook_base_url
            previous = await db.settings.find_one({"_id": "global"}, {"_id": 0, "webhook_base_url": 1}) or {}
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"webhook_base_url": "https://httpbin.org/post"}},
                upsert=True,
            )
            try:
                result = await admin_test_critical_url(
                    CriticalUrlTestRequest(key="webhook_base_url"), _=_ADMIN
                )
                return result
            finally:
                # Restore
                await db.settings.update_one(
                    {"_id": "global"},
                    {"$set": {"webhook_base_url": previous.get("webhook_base_url") or ""}},
                )

        result = _run(go())
        assert result["ok"] is True, result
        assert result["http_status"] == 200, result
        assert result["method"] == "POST"
        assert result["final_url"] == "https://httpbin.org/post"
        # httpbin echoes the body — confirm our dry_run payload made it through
        resp = result.get("response")
        if isinstance(resp, dict):
            json_payload = resp.get("json") or {}
            assert json_payload.get("dry_run") is True, json_payload
            assert json_payload.get("source") == "sawali-coffre-fort-test"
