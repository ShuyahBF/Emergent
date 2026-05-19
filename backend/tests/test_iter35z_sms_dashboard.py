"""Iter35z — SMS dashboard tests.

Validates the structure + cost arithmetic of the per-provider report and
the monthly budget gauge.
"""
import asyncio
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSmsDashboard:
    def _admin(self):
        return {"role": "admin", "email": "admin@test", "id": "admin-test"}

    def _seed_sms(self):
        """Insert 5 OK + 2 KO sends across orange/moov in last 30 days."""
        from server import db

        now = datetime.now(timezone.utc)
        rows = []
        for i in range(5):
            rows.append({
                "id": f"test-iter35z-ok-{i}",
                "client_id": "test-client",
                "provider": "orange",
                "status": "sent",
                "msisdn": "22670000000",
                "created_at": (now - timedelta(days=i, hours=2)).isoformat(),
            })
        for i in range(2):
            rows.append({
                "id": f"test-iter35z-ko-{i}",
                "client_id": "test-client",
                "provider": "moov",
                "status": "failed",
                "msisdn": "22675000000",
                "api_message": "Solde insuffisant",
                "created_at": (now - timedelta(days=i)).isoformat(),
            })
        return rows

    def test_dashboard_returns_full_schema(self):
        from server import db
        from routes.sms_dashboard import make_router  # noqa: F401

        async def go():
            await db.sms_messages.delete_many({"id": {"$regex": "^test-iter35z-"}})
            rows = self._seed_sms()
            await db.sms_messages.insert_many([r.copy() for r in rows])

            # Direct call to the endpoint via the router's registered route
            import server
            # Find the endpoint function
            target = None
            for r in server.app.routes:
                if getattr(r, "path", "") == "/api/admin/sms/dashboard":
                    target = r.endpoint
                    break
            assert target is not None, "endpoint not mounted"
            res = await target(days=30, _=self._admin())
            await db.sms_messages.delete_many({"id": {"$regex": "^test-iter35z-"}})
            return res

        res = _run(go())
        # Schema check
        for k in ["period_days", "since", "totals", "by_provider", "unit_costs_xof",
                  "budget", "top_errors", "daily_series"]:
            assert k in res, f"missing key {k}"
        # Totals
        assert res["totals"]["sent_ok"] >= 5, res["totals"]
        assert res["totals"]["sent_ko"] >= 2, res["totals"]
        # Per-provider
        assert "orange" in res["by_provider"], res["by_provider"]
        assert "moov" in res["by_provider"], res["by_provider"]
        orange = res["by_provider"]["orange"]
        assert orange["sent_ok"] >= 5
        assert orange["cost_xof"] >= 5 * 25.0  # default unit cost
        # Top errors
        msgs = [e["message"] for e in res["top_errors"]]
        assert any("solde" in m.lower() for m in msgs), msgs
        # Daily series has the right length
        assert len(res["daily_series"]) == 30

    def test_budget_status_warning_at_80pct(self):
        from server import db
        from routes.sms_dashboard import make_router  # noqa: F401

        async def go():
            await db.sms_messages.delete_many({"id": {"$regex": "^test-iter35z-budget-"}})
            # Set a small budget so 5 sends * 25 XOF = 125 XOF will exceed
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"sms_monthly_budget_xof": 100.0}},
                upsert=True,
            )
            now = datetime.now(timezone.utc)
            rows = [
                {"id": f"test-iter35z-budget-{i}", "provider": "orange", "status": "sent",
                 "msisdn": "22670000000", "created_at": now.isoformat()}
                for i in range(5)
            ]
            await db.sms_messages.insert_many([r.copy() for r in rows])
            import server
            target = None
            for r in server.app.routes:
                if getattr(r, "path", "") == "/api/admin/sms/dashboard":
                    target = r.endpoint
                    break
            res = await target(days=30, _=self._admin())
            await db.sms_messages.delete_many({"id": {"$regex": "^test-iter35z-budget-"}})
            await db.settings.update_one({"_id": "global"}, {"$set": {"sms_monthly_budget_xof": 0}})
            return res

        res = _run(go())
        b = res["budget"]
        assert b["monthly_xof"] == 100.0
        assert b["spent_this_month_xof"] >= 100.0
        assert b["status"] == "over", b
