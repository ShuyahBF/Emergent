"""Iter35z — Tableau de bord SMS (consommation/coût/échecs par opérateur).

Real-time dashboard surfacing:
  • Volume by provider (Orange / Moov / Telecel / OVH)
  • Success vs failure ratios
  • Estimated cost vs monthly budget (jauge dépassement)
  • Top error messages (so the admin knows WHY sends fail)
  • Daily series for the last N days (zero-filled)

Cost estimation is admin-configurable per provider via the settings
keys `sms_<provider>_unit_cost_xof` (defaults to a sensible value for
Burkina Faso operators). The monthly budget cap is `sms_monthly_budget_xof`.

Endpoint: GET /api/admin/sms/dashboard?days=30
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends


# Sensible defaults (XOF) when the admin hasn't configured per-provider costs.
DEFAULT_UNIT_COSTS: dict[str, float] = {
    "orange": 25.0,
    "moov": 22.0,
    "telecel": 24.0,
    "ovh": 35.0,  # International routing → more expensive
    "unknown": 20.0,
}


def make_router(*, db, get_current_admin):
    """Build the APIRouter with the project-level dependencies injected.

    `db` and `get_current_admin` are taken from server.py to keep the
    extraction zero-impact on existing routing.
    """
    router = APIRouter(prefix="/admin/sms", tags=["Admin"])

    @router.get("/dashboard")
    async def admin_sms_dashboard(days: int = 30, _: dict = Depends(get_current_admin)):
        days = max(1, min(int(days or 30), 365))
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        since_iso = since.isoformat()

        s = await db.settings.find_one({"_id": "global"}) or {}
        budget = float(s.get("sms_monthly_budget_xof") or 0)
        unit_costs = {
            p: float(s.get(f"sms_{p}_unit_cost_xof") or DEFAULT_UNIT_COSTS.get(p, 20.0))
            for p in ("orange", "moov", "telecel", "ovh")
        }

        # ---------- 1. Per-provider aggregate ----------
        by_provider: dict[str, dict] = {}
        cursor = db.sms_messages.aggregate([
            {"$match": {"created_at": {"$gte": since_iso}}},
            {"$group": {
                "_id": {"provider": {"$ifNull": ["$provider", "unknown"]},
                        "status": {"$ifNull": ["$status", "unknown"]}},
                "count": {"$sum": 1},
            }},
        ])
        async for row in cursor:
            prov = (row["_id"]["provider"] or "unknown").lower()
            status = (row["_id"]["status"] or "unknown").lower()
            slot = by_provider.setdefault(prov, {"sent_ok": 0, "sent_ko": 0, "total": 0})
            slot["total"] += int(row["count"])
            if status == "sent":
                slot["sent_ok"] += int(row["count"])
            else:
                slot["sent_ko"] += int(row["count"])

        # Compute cost per provider + totals
        total_cost = 0.0
        total_ok = 0
        total_ko = 0
        for prov, slot in by_provider.items():
            unit = unit_costs.get(prov, DEFAULT_UNIT_COSTS.get(prov, 20.0))
            slot["unit_cost_xof"] = unit
            # Only OK sends are billable
            slot["cost_xof"] = round(slot["sent_ok"] * unit, 2)
            slot["success_rate_pct"] = (
                round(100 * slot["sent_ok"] / slot["total"], 1) if slot["total"] else 0.0
            )
            total_cost += slot["cost_xof"]
            total_ok += slot["sent_ok"]
            total_ko += slot["sent_ko"]

        # ---------- 2. Cost vs budget (current calendar month) ----------
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        month_pipeline = [
            {"$match": {"created_at": {"$gte": month_start}, "status": "sent"}},
            {"$group": {"_id": {"$ifNull": ["$provider", "unknown"]}, "count": {"$sum": 1}}},
        ]
        cost_month = 0.0
        async for row in db.sms_messages.aggregate(month_pipeline):
            prov = (row["_id"] or "unknown").lower()
            unit = unit_costs.get(prov, DEFAULT_UNIT_COSTS.get(prov, 20.0))
            cost_month += float(row["count"]) * unit
        budget_used_pct = (round(100 * cost_month / budget, 1) if budget > 0 else None)
        budget_status = (
            "ok" if budget == 0 or (cost_month / budget) < 0.8
            else "warning" if (cost_month / budget) < 1.0
            else "over"
        ) if budget else "no_budget"

        # ---------- 3. Top error messages ----------
        top_errors: list[dict] = []
        err_pipeline = [
            {"$match": {"created_at": {"$gte": since_iso}, "status": {"$ne": "sent"}}},
            {"$group": {
                "_id": {"$ifNull": ["$api_message", "(sans message)"]},
                "count": {"$sum": 1},
                "providers": {"$addToSet": "$provider"},
            }},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        async for row in db.sms_messages.aggregate(err_pipeline):
            top_errors.append({
                "message": (row["_id"] or "(sans message)")[:200],
                "count": int(row["count"]),
                "providers": [p for p in (row.get("providers") or []) if p],
            })

        # ---------- 4. Daily series (zero-filled) ----------
        daily = []
        daily_map: dict[str, dict] = {}
        day_pipeline = [
            {"$match": {"created_at": {"$gte": since_iso}}},
            {"$group": {
                "_id": {
                    "day": {"$substr": ["$created_at", 0, 10]},
                    "status": {"$ifNull": ["$status", "unknown"]},
                },
                "count": {"$sum": 1},
            }},
        ]
        async for row in db.sms_messages.aggregate(day_pipeline):
            day = row["_id"]["day"]
            status = (row["_id"]["status"] or "unknown").lower()
            slot = daily_map.setdefault(day, {"day": day, "sent_ok": 0, "sent_ko": 0})
            if status == "sent":
                slot["sent_ok"] += int(row["count"])
            else:
                slot["sent_ko"] += int(row["count"])
        # Zero-fill
        for i in range(days):
            d = (since + timedelta(days=i)).strftime("%Y-%m-%d")
            daily.append(daily_map.get(d, {"day": d, "sent_ok": 0, "sent_ko": 0}))

        return {
            "period_days": days,
            "since": since_iso,
            "totals": {
                "sent_ok": total_ok,
                "sent_ko": total_ko,
                "total": total_ok + total_ko,
                "success_rate_pct": round(100 * total_ok / (total_ok + total_ko), 1) if (total_ok + total_ko) else 0.0,
                "cost_xof": round(total_cost, 2),
            },
            "by_provider": by_provider,
            "unit_costs_xof": unit_costs,
            "budget": {
                "monthly_xof": budget,
                "spent_this_month_xof": round(cost_month, 2),
                "used_pct": budget_used_pct,
                "status": budget_status,  # ok | warning | over | no_budget
            },
            "top_errors": top_errors,
            "daily_series": daily,
        }

    return router
