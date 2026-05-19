"""Iter35t — /me/welcome-briefing must include a `daily_health` block
with the motivational mini-dashboard stats:
  • tickets_resolved_yesterday
  • tickets_opened_today
  • wa_response_rate_24h   (None if no inbound)
  • wa_inbound_24h / wa_outbound_24h
  • messages_sent_today
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestWelcomeBriefingDailyHealth:
    def test_daily_health_block_present(self):
        """Call the endpoint function directly with an admin user dict."""
        from server import me_welcome_briefing, db

        async def go():
            u = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            assert u is not None, "Admin user not seeded"
            res = await me_welcome_briefing(user=u)
            return res

        data = _run(go())
        assert isinstance(data, dict)
        assert "daily_health" in data, list(data.keys())
        h = data["daily_health"]
        for k in [
            "tickets_resolved_yesterday",
            "tickets_opened_today",
            "wa_response_rate_24h",
            "wa_inbound_24h",
            "wa_outbound_24h",
            "messages_sent_today",
        ]:
            assert k in h, f"missing key {k} in daily_health: {h}"
        for k in [
            "tickets_resolved_yesterday",
            "tickets_opened_today",
            "wa_inbound_24h",
            "wa_outbound_24h",
            "messages_sent_today",
        ]:
            assert isinstance(h[k], int) and h[k] >= 0, h
        rr = h["wa_response_rate_24h"]
        assert rr is None or (isinstance(rr, (int, float)) and 0 <= rr <= 100), h

    def test_response_rate_none_when_no_inbound(self):
        """When wa_inbound_24h == 0, wa_response_rate_24h must be None."""
        from server import me_welcome_briefing, db

        async def go():
            u = await db.users.find_one(
                {"email": "admin@sawalismartsystems.com"},
                {"_id": 0, "id": 1, "email": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
            )
            return await me_welcome_briefing(user=u)

        data = _run(go())
        h = data["daily_health"]
        if h["wa_inbound_24h"] == 0:
            assert h["wa_response_rate_24h"] is None, h
