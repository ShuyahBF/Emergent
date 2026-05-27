"""Iter38c — Cashier Expenses (Dépenses) module.

Tracks cash/check expenses with a configurable justification deadline.
- Anyone with can_cash / admin / sup / Comptable can CREATE an expense.
- Only Admin can edit, delete or toggle the justified flag.
- The justification is REJECTED if the configured deadline (settings.expense_justification_deadline_hours)
  has elapsed since the expense was created. 0 = unlimited (always accept).
- Expenses unjustified after the deadline roll into the employee payslip as a
  deduction line ("Dépenses caisse non justifiées en retard").
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_super_admin(user: dict) -> bool:
    return (user.get("email") or "").lower() == "admin@sawalismartsystems.com"


def _is_admin(user: dict) -> bool:
    return (user.get("role") or "") == "admin"


def _is_admin_or_sup(user: dict) -> bool:
    return (user.get("role") or "") in ("admin", "superviseur")


def _is_comptable(user: dict) -> bool:
    return (user.get("tracked_role") or "") == "Comptable"


def _can_create_expense(user: dict) -> bool:
    return _is_admin_or_sup(user) or bool(user.get("can_cash")) or _is_comptable(user)


def _can_view_expenses(user: dict) -> bool:
    return _can_create_expense(user)


class ExpensePayload(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = Field("XOF", max_length=8)
    method: str = Field("cash", pattern=r"^(cash|check)$")
    payee: Optional[str] = Field(None, max_length=200)
    motif: str = Field(..., min_length=1, max_length=500)
    expense_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: Optional[str] = Field(None, max_length=500)
    # Iter38m — Attribution: "third_party" (default) or "employee"
    attribution_type: str = Field("third_party", pattern=r"^(third_party|employee)$")
    employee_id: Optional[str] = Field(None, max_length=80)


class ExpenseUpdatePayload(BaseModel):
    amount: Optional[float] = Field(None, gt=0)
    currency: Optional[str] = Field(None, max_length=8)
    method: Optional[str] = Field(None, pattern=r"^(cash|check)$")
    payee: Optional[str] = Field(None, max_length=200)
    motif: Optional[str] = Field(None, max_length=500)
    expense_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: Optional[str] = Field(None, max_length=500)
    attribution_type: Optional[str] = Field(None, pattern=r"^(third_party|employee)$")
    employee_id: Optional[str] = Field(None, max_length=80)


class ExpenseJustifyPayload(BaseModel):
    justification_text: Optional[str] = Field(None, max_length=1000)
    justification_proof_url: Optional[str] = Field(None, max_length=500)
    # Admin-only override flag (force justified regardless of deadline)
    force: bool = False


def make_router(*, db, get_current_user):
    router = APIRouter(prefix="/cashier/expenses", tags=["Caisse — Dépenses"])

    async def _resolve_tenant_id(user: dict) -> str:
        for key in ("parent_client_id", "client_id"):
            ref = user.get(key)
            if ref and ref != user.get("id"):
                doc = await db.users.find_one({"id": ref}, {"_id": 0, "id": 1})
                if doc:
                    return doc["id"]
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
        return user["id"]

    async def _scoped(user: dict) -> Dict[str, Any]:
        if _is_super_admin(user):
            return {}
        tid = await _resolve_tenant_id(user)
        return {"tenant_id": tid}

    async def _justification_deadline_hours() -> int:
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        v = s.get("expense_justification_deadline_hours", 72)
        try:
            return int(v)
        except (TypeError, ValueError):
            return 72

    # ----------------------------------------------------------------
    # CRUD
    # ----------------------------------------------------------------
    @router.get("")
    async def list_expenses(
        month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
        user_id: Optional[str] = None,
        status: Optional[str] = Query(None, pattern=r"^(justified|unjustified|late_unjustified|all)$"),
        user: dict = Depends(get_current_user),
    ):
        if not _can_view_expenses(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        scope = await _scoped(user)
        q: Dict[str, Any] = {**scope, "deleted_at": None}
        if month:
            q["expense_date"] = {"$gte": f"{month}-01", "$lt": f"{month}-32"}
        if user_id:
            q["created_by"] = user_id
        if status == "justified":
            q["is_justified"] = True
        elif status == "unjustified":
            q["is_justified"] = False
        cursor = db.cashier_expenses.find(q, {"_id": 0}).sort("expense_date", -1)
        items = [e async for e in cursor]
        # Compute late_unjustified status
        deadline_h = await _justification_deadline_hours()
        for it in items:
            it["is_late_unjustified"] = _is_late_unjustified(it, deadline_h)
            it["deadline_at"] = _deadline_at(it, deadline_h)
        if status == "late_unjustified":
            items = [it for it in items if it["is_late_unjustified"]]
        return items

    @router.get("/monthly-summary")
    async def monthly_summary(
        month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
        user: dict = Depends(get_current_user),
    ):
        if not _can_view_expenses(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        scope = await _scoped(user)
        deadline_h = await _justification_deadline_hours()
        cursor = db.cashier_expenses.find(
            {**scope, "deleted_at": None,
             "expense_date": {"$gte": f"{month}-01", "$lt": f"{month}-32"}},
            {"_id": 0},
        )
        items = [e async for e in cursor]
        total = sum(float(e.get("amount") or 0) for e in items)
        just = sum(float(e.get("amount") or 0) for e in items if e.get("is_justified"))
        unjust_total = total - just
        late_unjust_items = [e for e in items if _is_late_unjustified(e, deadline_h)]
        late_unjust_amount = sum(float(e.get("amount") or 0) for e in late_unjust_items)
        # By user
        per_user: Dict[str, Dict[str, Any]] = {}
        for e in items:
            uid = e.get("created_by") or "unknown"
            if uid not in per_user:
                per_user[uid] = {
                    "user_id": uid,
                    "user_name": e.get("created_by_name") or "—",
                    "total": 0.0, "justified": 0.0, "unjustified": 0.0,
                    "late_unjustified": 0.0, "count": 0,
                }
            amt = float(e.get("amount") or 0)
            per_user[uid]["total"] += amt
            per_user[uid]["count"] += 1
            if e.get("is_justified"):
                per_user[uid]["justified"] += amt
            else:
                per_user[uid]["unjustified"] += amt
                if _is_late_unjustified(e, deadline_h):
                    per_user[uid]["late_unjustified"] += amt
        return {
            "month": month,
            "deadline_hours": deadline_h,
            "total": round(total, 2),
            "justified": round(just, 2),
            "unjustified": round(unjust_total, 2),
            "late_unjustified": round(late_unjust_amount, 2),
            "by_user": list(per_user.values()),
            "count": len(items),
        }

    @router.post("")
    async def create_expense(payload: ExpensePayload, user: dict = Depends(get_current_user)):
        if not _can_create_expense(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        tid = await _resolve_tenant_id(user)
        # Iter38m — If attribution is "employee", resolve the employee
        # and capture a name snapshot for display
        employee_user_id: Optional[str] = None
        employee_name: Optional[str] = None
        if payload.attribution_type == "employee":
            if not payload.employee_id:
                raise HTTPException(
                    status_code=400,
                    detail="employee_id requis lorsque attribution_type=employee",
                )
            emp = await db.hr_employees.find_one(
                {"tenant_id": tid, "id": payload.employee_id, "deleted_at": None},
                {"_id": 0, "id": 1, "user_id": 1, "name_snapshot": 1,
                 "email_snapshot": 1, "matricule": 1},
            )
            if not emp:
                raise HTTPException(
                    status_code=404, detail="Employé introuvable dans ce tenant"
                )
            employee_user_id = emp.get("user_id")
            employee_name = emp.get("name_snapshot") or emp.get("email_snapshot")
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "tenant_id": tid,
            "created_at": _now_iso(),
            "created_by": user["id"],
            "created_by_name": user.get("full_name") or user.get("email"),
            "created_by_email": user.get("email"),
            "expense_date": doc.get("expense_date") or datetime.now(timezone.utc).date().isoformat(),
            "is_justified": False,
            "justified_at": None,
            "justified_by": None,
            "justification_text": None,
            "justification_proof_url": None,
            "deleted_at": None,
            # Iter38m — employee attribution snapshot
            "employee_user_id": employee_user_id,
            "employee_name_snapshot": employee_name,
        })
        await db.cashier_expenses.insert_one(doc.copy())
        doc.pop("_id", None)
        deadline_h = await _justification_deadline_hours()
        doc["is_late_unjustified"] = _is_late_unjustified(doc, deadline_h)
        doc["deadline_at"] = _deadline_at(doc, deadline_h)
        return doc

    @router.patch("/{eid}")
    async def update_expense(eid: str, payload: ExpenseUpdatePayload, user: dict = Depends(get_current_user)):
        """Iter38o — Edit allowed if NOT justified (clôturée):
        - admin/sup can always edit
        - creator (created_by == me) can edit while not justified
        - employee on whom the expense is attributed (employee_user_id == me)
          can edit while not justified
        Once justified ('clôturée'), only admin can edit (force).
        """
        scope = await _scoped(user)
        exp = await db.cashier_expenses.find_one({**scope, "id": eid, "deleted_at": None}, {"_id": 0})
        if not exp:
            raise HTTPException(status_code=404, detail="Dépense introuvable")
        is_admin = _is_admin_or_sup(user)
        is_creator = exp.get("created_by") == user["id"]
        is_attributed = exp.get("employee_user_id") == user["id"]
        if exp.get("is_justified"):
            if not is_admin:
                raise HTTPException(status_code=403, detail="Dépense clôturée — seul l'administrateur peut la modifier")
        else:
            if not (is_admin or is_creator or is_attributed):
                raise HTTPException(status_code=403, detail="Vous ne pouvez modifier que vos propres dépenses non clôturées")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        # If attribution_type changes to employee, ensure employee snapshot is refreshed
        if updates.get("attribution_type") == "employee":
            new_eid = updates.get("employee_id") or exp.get("employee_id")
            if not new_eid:
                raise HTTPException(status_code=400, detail="employee_id requis pour une attribution employé")
            tid = await _resolve_tenant_id(user)
            emp = await db.hr_employees.find_one(
                {"tenant_id": tid, "id": new_eid, "deleted_at": None},
                {"_id": 0, "id": 1, "user_id": 1, "name_snapshot": 1, "email_snapshot": 1},
            )
            if not emp:
                raise HTTPException(status_code=404, detail="Employé introuvable")
            updates["employee_user_id"] = emp.get("user_id")
            updates["employee_name_snapshot"] = emp.get("name_snapshot") or emp.get("email_snapshot")
        elif updates.get("attribution_type") == "third_party":
            updates["employee_id"] = None
            updates["employee_user_id"] = None
            updates["employee_name_snapshot"] = None
        if not updates:
            return exp
        updates["updated_at"] = _now_iso()
        updates["updated_by"] = user["id"]
        await db.cashier_expenses.update_one({"id": eid}, {"$set": updates})
        return await db.cashier_expenses.find_one({"id": eid}, {"_id": 0})

    @router.delete("/{eid}")
    async def delete_expense(eid: str, user: dict = Depends(get_current_user)):
        if not _is_admin(user):
            raise HTTPException(status_code=403, detail="Seul l'administrateur peut supprimer une dépense")
        scope = await _scoped(user)
        res = await db.cashier_expenses.update_one(
            {**scope, "id": eid, "deleted_at": None},
            {"$set": {"deleted_at": _now_iso(), "deleted_by": user["id"]}},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Dépense introuvable")
        return {"ok": True}

    @router.post("/{eid}/justify")
    async def justify_expense(eid: str, payload: ExpenseJustifyPayload, user: dict = Depends(get_current_user)):
        """Justifies an expense. Refused if past the deadline (unless admin uses force=true)."""
        if not _can_view_expenses(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        scope = await _scoped(user)
        exp = await db.cashier_expenses.find_one({**scope, "id": eid, "deleted_at": None}, {"_id": 0})
        if not exp:
            raise HTTPException(status_code=404, detail="Dépense introuvable")
        if exp.get("is_justified"):
            raise HTTPException(status_code=400, detail="Dépense déjà justifiée")
        deadline_h = await _justification_deadline_hours()
        if _is_late_unjustified(exp, deadline_h):
            if not (payload.force and _is_admin(user)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Délai de justification dépassé ({deadline_h}h depuis la création). Justification refusée.",
                )
        await db.cashier_expenses.update_one(
            {"id": eid},
            {"$set": {
                "is_justified": True,
                "justified_at": _now_iso(),
                "justified_by": user["id"],
                "justified_by_name": user.get("full_name") or user.get("email"),
                "justified_by_email": user.get("email"),
                "justification_text": payload.justification_text,
                "justification_proof_url": payload.justification_proof_url,
                "forced_justification": bool(payload.force and _is_admin(user)),
            }},
        )
        return await db.cashier_expenses.find_one({"id": eid}, {"_id": 0})

    @router.post("/{eid}/unjustify")
    async def unjustify_expense(eid: str, user: dict = Depends(get_current_user)):
        """Admin only — revert justification (e.g. mistake)."""
        if not _is_admin(user):
            raise HTTPException(status_code=403, detail="Seul l'administrateur peut décocher la justification")
        scope = await _scoped(user)
        exp = await db.cashier_expenses.find_one({**scope, "id": eid, "deleted_at": None}, {"_id": 0, "id": 1})
        if not exp:
            raise HTTPException(status_code=404, detail="Dépense introuvable")
        await db.cashier_expenses.update_one(
            {"id": eid},
            {"$set": {
                "is_justified": False,
                "justified_at": None,
                "justified_by": None,
                "justified_by_name": None,
                "justified_by_email": None,
                "justification_text": None,
                "forced_justification": False,
                "updated_at": _now_iso(),
                "updated_by": user["id"],
            }},
        )
        return await db.cashier_expenses.find_one({"id": eid}, {"_id": 0})

    @router.get("/employees-list")
    async def list_employees_for_expenses(user: dict = Depends(get_current_user)):
        """Iter38m — Lightweight list of employees of the current tenant for the
        expense attribution dropdown. Accessible to all roles that can create
        an expense (admin/sup/can_cash/Comptable) without requiring full HR access.
        Returns [{id, name, matricule, user_id}].
        """
        if not _can_create_expense(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        scope = await _scoped(user)
        cursor = db.hr_employees.find(
            {**scope, "deleted_at": None},
            {"_id": 0, "id": 1, "user_id": 1, "name_snapshot": 1,
             "email_snapshot": 1, "matricule": 1, "job_title": 1},
        ).sort("name_snapshot", 1)
        items = []
        async for e in cursor:
            items.append({
                "id": e.get("id"),
                "user_id": e.get("user_id"),
                "name": e.get("name_snapshot") or e.get("email_snapshot") or "—",
                "matricule": e.get("matricule"),
                "job_title": e.get("job_title"),
            })
        return items

    # ----------------------------------------------------------------
    # /me/dashboard/unjustified-expenses — for tracked-user dashboard card
    # ----------------------------------------------------------------
    @router.get("/me/dashboard-card")
    async def my_dashboard_card(user: dict = Depends(get_current_user)):
        """Sum of MY unjustified expenses + those late-unjustified.

        Iter38m — Includes:
          - expenses I created (created_by == me)
          - expenses attributed to me as employee (employee_user_id == me)
        """
        scope = await _scoped(user)
        deadline_h = await _justification_deadline_hours()
        # Match either created_by OR employee_user_id == me
        q: Dict[str, Any] = {
            **scope,
            "is_justified": False,
            "deleted_at": None,
            "$or": [
                {"created_by": user["id"]},
                {"employee_user_id": user["id"]},
            ],
        }
        cursor = db.cashier_expenses.find(q, {"_id": 0})
        items = [e async for e in cursor]
        total = sum(float(e.get("amount") or 0) for e in items)
        late_total = sum(float(e.get("amount") or 0) for e in items if _is_late_unjustified(e, deadline_h))
        currencies = {e.get("currency") or "XOF" for e in items}
        currency = next(iter(currencies)) if len(currencies) == 1 else "XOF"
        oldest = None
        if items:
            try:
                oldest = min(e.get("expense_date") or e.get("created_at") for e in items)
            except (ValueError, TypeError):
                oldest = None
        return {
            "count": len(items),
            "total_unjustified": round(total, 2),
            "late_unjustified": round(late_total, 2),
            "deadline_hours": deadline_h,
            "currency": currency,
            "oldest_date": oldest,
        }

    return router


def _deadline_at(exp: dict, deadline_h: int) -> Optional[str]:
    if deadline_h <= 0:
        return None
    try:
        c = datetime.fromisoformat((exp.get("created_at") or "").replace("Z", "+00:00"))
        return (c + timedelta(hours=deadline_h)).isoformat()
    except (ValueError, TypeError):
        return None


def _is_late_unjustified(exp: dict, deadline_h: int) -> bool:
    if exp.get("is_justified"):
        return False
    if deadline_h <= 0:
        return False
    try:
        c = datetime.fromisoformat((exp.get("created_at") or "").replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - c).total_seconds() > deadline_h * 3600
    except (ValueError, TypeError):
        return False


async def late_unjustified_for_employee(db, *, tenant_id: str, user_id: str, month: str) -> float:
    """Sum (XOF-equivalent) of late-unjustified expenses for a given user in a given month.
    Used by HR payslip computation to add the corresponding deduction line.

    Iter38m — Includes both:
      - expenses CREATED by the user (created_by == user_id)
      - expenses ATTRIBUTED to the user as employee (employee_user_id == user_id)
    """
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    try:
        deadline_h = int(s.get("expense_justification_deadline_hours", 72))
    except (TypeError, ValueError):
        deadline_h = 72
    if deadline_h <= 0:
        return 0.0
    cursor = db.cashier_expenses.find(
        {"tenant_id": tenant_id, "is_justified": False,
         "deleted_at": None,
         "expense_date": {"$gte": f"{month}-01", "$lt": f"{month}-32"},
         "$or": [
             {"created_by": user_id},
             {"employee_user_id": user_id},
         ]},
        {"_id": 0, "amount": 1, "created_at": 1},
    )
    total = 0.0
    async for e in cursor:
        if _is_late_unjustified(e, deadline_h):
            total += float(e.get("amount") or 0)
    return round(total, 2)


__all__ = ["make_router", "late_unjustified_for_employee"]
