"""Iter38 — GRH (Gestion des Ressources Humaines) module.

Phases delivered in this iteration:
  1. Base definitions: Track personnel derived from db.users of a tenant.
     New tracked role `Comptable` (HR write + Caisse read-only).
  2. Financials: base_salary, pay_type (hourly/monthly), currency.
  3. Time tracking: presence computed on-the-fly from db.access_logs.
     A worked day = plage min(login)→max(logout) of the day (user choice 3c).

Security:
  - HR full CRUD: admin / superviseur / tracked_role == "Comptable".
  - Tenant isolation: same logic as Caisse (parent_client_id → client_id →
    canonical-by-company → self). Super-admin (admin@sawalismartsystems.com)
    sees all tenants.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

log = logging.getLogger("sawali.hr")


# =====================================================================
# Pydantic models
# =====================================================================
class EmployeePayload(BaseModel):
    user_id: str = Field(..., min_length=1)
    base_salary: float = Field(0.0, ge=0)
    pay_type: str = Field("monthly", pattern=r"^(monthly|hourly)$")
    currency: str = Field("XOF", max_length=8)
    hourly_rate: Optional[float] = Field(None, ge=0)  # used when pay_type == hourly
    monthly_hours_baseline: float = Field(160.0, ge=0)  # contractual monthly hours (default 160)
    department: Optional[str] = Field(None, max_length=80)
    job_title: Optional[str] = Field(None, max_length=120)
    notes: Optional[str] = Field(None, max_length=1000)


class EmployeeUpdate(BaseModel):
    base_salary: Optional[float] = Field(None, ge=0)
    pay_type: Optional[str] = Field(None, pattern=r"^(monthly|hourly)$")
    currency: Optional[str] = Field(None, max_length=8)
    hourly_rate: Optional[float] = Field(None, ge=0)
    monthly_hours_baseline: Optional[float] = Field(None, ge=0)
    department: Optional[str] = Field(None, max_length=80)
    job_title: Optional[str] = Field(None, max_length=120)
    notes: Optional[str] = Field(None, max_length=1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_super_admin(user: dict) -> bool:
    return (user.get("email") or "").lower() == "admin@sawalismartsystems.com"


def _is_admin_or_sup(user: dict) -> bool:
    return (user.get("role") or "") in ("admin", "superviseur")


def _is_comptable(user: dict) -> bool:
    return (user.get("tracked_role") or "") == "Comptable"


def _can_access_hr(user: dict) -> bool:
    """Read+Write for admin/sup/Comptable."""
    return _is_admin_or_sup(user) or _is_comptable(user)


# =====================================================================
# Router factory
# =====================================================================
def make_router(*, db, get_current_user):
    router = APIRouter(prefix="/hr", tags=["GRH"])

    # ----------------------------------------------------------------
    # Tenant resolution (mirrors cashier logic)
    # ----------------------------------------------------------------
    async def _resolve_tenant_id(user: dict) -> str:
        # 1) parent_client_id / client_id pointing to another user
        for key in ("parent_client_id", "client_id"):
            ref_id = user.get(key)
            if ref_id and ref_id != user.get("id"):
                doc = await db.users.find_one({"id": ref_id}, {"_id": 0, "id": 1})
                if doc:
                    return doc["id"]
        # 2) Canonical by company
        company = (user.get("company") or "").strip()
        if company:
            for role_filter in (
                {"role": "admin"},
                {"role": "superviseur"},
                {"account_status": {"$ne": "deleted"}},
            ):
                canonical = await db.users.find_one(
                    {**role_filter, "company": company},
                    {"_id": 0, "id": 1},
                    sort=[("created_at", 1)],
                )
                if canonical:
                    return canonical["id"]
        # 3) self
        return user["id"]

    async def _scoped(user: dict) -> Dict[str, Any]:
        if _is_super_admin(user):
            return {}
        tid = await _resolve_tenant_id(user)
        return {"tenant_id": tid}

    async def _users_in_tenant(user: dict) -> List[dict]:
        """All users belonging to the same Client Lié (tenant)."""
        if _is_super_admin(user):
            cursor = db.users.find(
                {"account_status": {"$ne": "deleted"}},
                {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1,
                 "tracked_role": 1, "company": 1, "phone": 1, "created_at": 1},
            )
            return [u async for u in cursor]
        tid = await _resolve_tenant_id(user)
        # Find tenant company
        tenant_doc = await db.users.find_one({"id": tid}, {"_id": 0, "company": 1})
        company = (tenant_doc or {}).get("company") if tenant_doc else None
        # Build query: users with parent_client_id == tid OR client_id == tid OR id == tid
        # OR same company
        or_conds: List[Dict[str, Any]] = [
            {"parent_client_id": tid},
            {"client_id": tid},
            {"id": tid},
        ]
        if company:
            or_conds.append({"company": company})
        cursor = db.users.find(
            {"$or": or_conds, "account_status": {"$ne": "deleted"}},
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1,
             "tracked_role": 1, "company": 1, "phone": 1, "created_at": 1},
        )
        return [u async for u in cursor]

    # ----------------------------------------------------------------
    # Eligible candidates (users not yet enrolled as employees in this tenant)
    # ----------------------------------------------------------------
    @router.get("/eligible-users")
    async def list_eligible(user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        users = await _users_in_tenant(user)
        scope = await _scoped(user)
        existing_ids = set()
        async for emp in db.hr_employees.find(
            {**scope, "deleted_at": None}, {"_id": 0, "user_id": 1}
        ):
            existing_ids.add(emp.get("user_id"))
        return [u for u in users if u.get("id") not in existing_ids]

    # ----------------------------------------------------------------
    # Employees CRUD
    # ----------------------------------------------------------------
    @router.get("/employees")
    async def list_employees(
        include_deleted: bool = Query(False),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        q: Dict[str, Any] = {**scope}
        if not include_deleted:
            q["deleted_at"] = None
        cursor = db.hr_employees.find(q, {"_id": 0}).sort("created_at", -1)
        items = [e async for e in cursor]
        # Enrich with current user info
        for it in items:
            u = await db.users.find_one(
                {"id": it.get("user_id")},
                {"_id": 0, "email": 1, "full_name": 1, "role": 1,
                 "tracked_role": 1, "phone": 1, "company": 1},
            )
            it["user"] = u or {
                "email": it.get("email_snapshot"),
                "full_name": it.get("name_snapshot"),
            }
        return items

    @router.post("/employees")
    async def create_employee(
        payload: EmployeePayload, user: dict = Depends(get_current_user)
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        # Verify target user belongs to the same tenant
        users = await _users_in_tenant(user)
        target = next((u for u in users if u.get("id") == payload.user_id), None)
        if not target:
            raise HTTPException(
                status_code=404,
                detail="Utilisateur introuvable dans ce tenant",
            )
        tid = await _resolve_tenant_id(user)
        # Idempotence: prevent duplicates (active OR soft-deleted with same user_id)
        existing = await db.hr_employees.find_one(
            {"tenant_id": tid, "user_id": payload.user_id, "deleted_at": None},
            {"_id": 0, "id": 1},
        )
        if existing:
            raise HTTPException(
                status_code=409, detail="Cet utilisateur est déjà enrôlé"
            )
        doc = payload.model_dump()
        doc.update(
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tid,
                "email_snapshot": target.get("email"),
                "name_snapshot": target.get("full_name"),
                "created_at": _now_iso(),
                "created_by": user["id"],
                "updated_at": _now_iso(),
                "deleted_at": None,
            }
        )
        await db.hr_employees.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/employees/{eid}")
    async def update_employee(
        eid: str, payload: EmployeeUpdate, user: dict = Depends(get_current_user)
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one(
            {**scope, "id": eid, "deleted_at": None}, {"_id": 0}
        )
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not updates:
            return emp
        updates["updated_at"] = _now_iso()
        await db.hr_employees.update_one({"id": eid}, {"$set": updates})
        doc = await db.hr_employees.find_one({"id": eid}, {"_id": 0})
        return doc

    @router.delete("/employees/{eid}")
    async def delete_employee(eid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one(
            {**scope, "id": eid, "deleted_at": None}, {"_id": 0, "id": 1}
        )
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        await db.hr_employees.update_one(
            {"id": eid}, {"$set": {"deleted_at": _now_iso()}}
        )
        return {"ok": True}

    @router.post("/employees/{eid}/restore")
    async def restore_employee(eid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one(
            {**scope, "id": eid, "deleted_at": {"$ne": None}}, {"_id": 0, "id": 1}
        )
        if not emp:
            raise HTTPException(
                status_code=404, detail="Employé introuvable ou déjà actif"
            )
        await db.hr_employees.update_one(
            {"id": eid}, {"$set": {"deleted_at": None, "updated_at": _now_iso()}}
        )
        doc = await db.hr_employees.find_one({"id": eid}, {"_id": 0})
        return doc

    # ----------------------------------------------------------------
    # Timesheet (Phase 3) — computed from access_logs
    # Choice 3c: a worked day = plage min(login)→max(last seen) of the day
    # ----------------------------------------------------------------
    @router.get("/employees/{eid}/timesheet")
    async def employee_timesheet(
        eid: str,
        month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one(
            {**scope, "id": eid}, {"_id": 0}
        )
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        # Parse month
        try:
            year, mm = month.split("-")
            year_i, month_i = int(year), int(mm)
            start = datetime(year_i, month_i, 1, tzinfo=timezone.utc)
            if month_i == 12:
                end = datetime(year_i + 1, 1, 1, tzinfo=timezone.utc)
            else:
                end = datetime(year_i, month_i + 1, 1, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Format mois invalide (YYYY-MM)")

        # Identify the user by user_id OR by email (resilience for migrated users)
        uid = emp.get("user_id")
        snap_email = (emp.get("email_snapshot") or "").lower()
        # Build access_logs filter
        or_conds: List[Dict[str, Any]] = []
        if uid:
            or_conds.append({"user_id": uid})
        if snap_email:
            or_conds.append({"user_email": snap_email})
        if not or_conds:
            return {
                "employee_id": eid,
                "month": month,
                "days": [],
                "totals": {"days_worked": 0, "hours_worked": 0.0, "expected_hours": emp.get("monthly_hours_baseline", 0)},
            }
        # Aggregate min/max created_at per day
        pipeline = [
            {
                "$match": {
                    "$or": or_conds,
                    "created_at": {"$gte": start.isoformat(), "$lt": end.isoformat()},
                }
            },
            {
                "$group": {
                    "_id": {"$substr": ["$created_at", 0, 10]},
                    "first": {"$min": "$created_at"},
                    "last": {"$max": "$created_at"},
                    "hits": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        days = []
        total_seconds = 0.0
        days_worked = 0
        async for row in db.access_logs.aggregate(pipeline):
            first = row.get("first")
            last = row.get("last")
            secs = 0.0
            try:
                f_dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
                l_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                secs = max(0.0, (l_dt - f_dt).total_seconds())
            except Exception:
                secs = 0.0
            days_worked += 1
            total_seconds += secs
            days.append({
                "date": row.get("_id"),
                "first_seen": first,
                "last_seen": last,
                "presence_seconds": secs,
                "presence_hours": round(secs / 3600.0, 2),
                "hits": row.get("hits"),
            })
        expected_hours = float(emp.get("monthly_hours_baseline") or 0)
        hours_worked = round(total_seconds / 3600.0, 2)
        # Computed gross salary preview (Phase 2/3 join)
        pay_type = emp.get("pay_type") or "monthly"
        base = float(emp.get("base_salary") or 0)
        hourly = float(emp.get("hourly_rate") or 0)
        if pay_type == "hourly":
            computed = round(hours_worked * hourly, 2)
        else:
            # Monthly: prorate by hours_worked / expected_hours (clamped to 1.0)
            ratio = (hours_worked / expected_hours) if expected_hours > 0 else 1.0
            ratio = min(1.0, max(0.0, ratio))
            computed = round(base * ratio, 2)
        return {
            "employee_id": eid,
            "month": month,
            "days": days,
            "totals": {
                "days_worked": days_worked,
                "hours_worked": hours_worked,
                "expected_hours": expected_hours,
                "pay_type": pay_type,
                "base_salary": base,
                "hourly_rate": hourly,
                "computed_gross": computed,
                "currency": emp.get("currency") or "XOF",
            },
        }

    return router


__all__ = ["make_router"]
