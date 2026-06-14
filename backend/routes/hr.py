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
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from pydantic import BaseModel, Field

log = logging.getLogger("sawali.hr")


# =====================================================================
# Pydantic models
# =====================================================================
class EmployeePayload(BaseModel):
    user_id: str = Field(..., min_length=1)
    base_salary: float = Field(0.0, ge=0)
    # Iter40-hr-fixed — pay_type accepts 3 values:
    #   "monthly"  : base_salary prorated by hours_worked / monthly_hours_baseline
    #   "hourly"   : hourly_rate × hours_worked
    #   "fixed"    : base_salary paid in full each month, regardless of hours
    #                (useful for late-month hires, contractors with flat fees,
    #                 trial periods, or any agent whose payment is not time-based)
    pay_type: str = Field("monthly", pattern=r"^(monthly|hourly|fixed)$")
    currency: str = Field("XOF", max_length=8)
    hourly_rate: Optional[float] = Field(None, ge=0)  # used when pay_type == hourly
    monthly_hours_baseline: float = Field(160.0, ge=0)  # contractual monthly hours (default 160)
    department: Optional[str] = Field(None, max_length=80)
    job_title: Optional[str] = Field(None, max_length=120)
    notes: Optional[str] = Field(None, max_length=1000)
    # Iter38b — Phase 4 override for absence tolerance threshold (hours/month).
    # None means: use tenant global threshold.
    absence_threshold_hours_override: Optional[float] = Field(None, ge=0)
    # Iter38b — Phase 5 per-employee tax overrides {tax_id: value}
    tax_overrides: Optional[Dict[str, float]] = None


class EmployeeUpdate(BaseModel):
    base_salary: Optional[float] = Field(None, ge=0)
    pay_type: Optional[str] = Field(None, pattern=r"^(monthly|hourly|fixed)$")
    currency: Optional[str] = Field(None, max_length=8)
    hourly_rate: Optional[float] = Field(None, ge=0)
    monthly_hours_baseline: Optional[float] = Field(None, ge=0)
    department: Optional[str] = Field(None, max_length=80)
    job_title: Optional[str] = Field(None, max_length=120)
    notes: Optional[str] = Field(None, max_length=1000)
    absence_threshold_hours_override: Optional[float] = Field(None, ge=0)
    tax_overrides: Optional[Dict[str, float]] = None


# ---------------------------------------------------------------------
# Iter38b — Phase 4 Absences
# ---------------------------------------------------------------------
class AbsencePayload(BaseModel):
    employee_id: str = Field(..., min_length=1)
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    hours_count: float = Field(8.0, ge=0)
    abs_type: str = Field("non_justifiee")  # maladie | conge | non_justifiee | personnelle | autre
    is_justified: bool = False
    justification: Optional[str] = Field(None, max_length=1000)


class AbsenceUpdate(BaseModel):
    start_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    hours_count: Optional[float] = Field(None, ge=0)
    abs_type: Optional[str] = None
    is_justified: Optional[bool] = None
    justification: Optional[str] = Field(None, max_length=1000)


# ---------------------------------------------------------------------
# Iter38b — Phase 5 Taxes (up to 5 per tenant, configurable)
# ---------------------------------------------------------------------
class TaxDefinitionPayload(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    calc_type: str = Field("percentage", pattern=r"^(percentage|fixed)$")
    value: float = Field(0.0, ge=0)
    applies_to: str = Field("gross", pattern=r"^(gross|net)$")
    active: bool = True
    sort_order: int = 0


class TaxesReplacePayload(BaseModel):
    """Replace all tenant taxes at once (max 5)."""
    taxes: List[TaxDefinitionPayload] = Field(default_factory=list)


# ---------------------------------------------------------------------
# Iter38b — Phase 5 Advances
# ---------------------------------------------------------------------
class AdvancePayload(BaseModel):
    employee_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    currency: str = Field("XOF", max_length=8)
    motive: Optional[str] = Field(None, max_length=500)
    granted_at: Optional[str] = None  # ISO date string YYYY-MM-DD; defaults to today
    auto_deduct: bool = True


class AdvanceRepayPayload(BaseModel):
    repaid_amount: float = Field(..., gt=0)
    note: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------
# S-iter39s (2026-02) — Allowances (indemnités fixes) & Bonuses (primes variables)
# ---------------------------------------------------------------------
class AllowancePayload(BaseModel):
    """Indemnité fixe — récurrente chaque mois (transport, logement, panier…).
    Reste active jusqu'à modification/désactivation/suppression manuelle."""
    label: str = Field(..., min_length=1, max_length=120)
    amount: float = Field(..., ge=0)
    currency: str = Field("XOF", max_length=8)
    active: bool = True
    sort_order: int = 0
    notes: Optional[str] = Field(None, max_length=500)
    catalog_id: Optional[str] = None  # 0-3 — link to catalog template


class AllowanceUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    amount: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=8)
    active: Optional[bool] = None
    sort_order: Optional[int] = None
    notes: Optional[str] = Field(None, max_length=500)


class BonusPayload(BaseModel):
    """Prime variable — rattachée à un mois précis (YYYY-MM). Peut être
    absente ou présente d'un mois à l'autre."""
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    label: str = Field(..., min_length=1, max_length=120)
    amount: float = Field(..., ge=0)
    currency: str = Field("XOF", max_length=8)
    notes: Optional[str] = Field(None, max_length=500)
    catalog_id: Optional[str] = None  # 0-3 — link to catalog template


class BonusUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    amount: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=8)
    notes: Optional[str] = Field(None, max_length=500)


# 0-3 (2026-02) — Catalog of standalone pay items (allowance/bonus templates)
class PayCatalogItemPayload(BaseModel):
    kind: str = Field(..., pattern=r"^(allowance|bonus)$")
    label: str = Field(..., min_length=1, max_length=120)
    default_amount: float = Field(0, ge=0)
    currency: str = Field("XOF", max_length=8)
    description: Optional[str] = Field(None, max_length=500)


class PayCatalogItemUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    default_amount: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=8)
    description: Optional[str] = Field(None, max_length=500)


class CopyPayItemsPayload(BaseModel):
    """Copy primes/indemnités from src employee to target employee."""
    target_employee_id: str = Field(..., min_length=1)
    include_allowances: bool = True
    include_bonuses: bool = False
    bonus_month: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}$")


# ---------------------------------------------------------------------
# Iter38b — Tenant HR settings (thresholds + payslip template)
# ---------------------------------------------------------------------
class HrSettingsPayload(BaseModel):
    absence_threshold_hours: Optional[float] = Field(None, ge=0)  # global default
    payslip_company_name: Optional[str] = Field(None, max_length=200)
    payslip_employer_id: Optional[str] = Field(None, max_length=80)
    payslip_address: Optional[str] = Field(None, max_length=400)
    payslip_legal_mentions: Optional[str] = Field(None, max_length=1000)
    payslip_footer: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------
# Iter38m — Holidays (jours fériés) per tenant
# ---------------------------------------------------------------------
class HolidayPayload(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    label: str = Field(..., min_length=1, max_length=160)
    holiday_type: str = Field("national", pattern=r"^(national|religious|local|other)$")
    is_paid: bool = True


class HolidayUpdate(BaseModel):
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    label: Optional[str] = Field(None, min_length=1, max_length=160)
    holiday_type: Optional[str] = Field(None, pattern=r"^(national|religious|local|other)$")
    is_paid: Optional[bool] = None


# Catalogue of well-known fixed-date holidays by country.
# Mobile religious holidays (Aïd el-Fitr, Aïd el-Kébir, Mawlid) are excluded
# from automatic import (dates change every year) — admin sets them manually.
_HOLIDAYS_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "BF": [  # Burkina Faso
        {"md": "01-01", "label": "Jour de l'An", "holiday_type": "national"},
        {"md": "01-03", "label": "Soulèvement populaire (1966)", "holiday_type": "national"},
        {"md": "03-08", "label": "Journée internationale des droits des femmes", "holiday_type": "national"},
        {"md": "05-01", "label": "Fête du Travail", "holiday_type": "national"},
        {"md": "08-04", "label": "Journée nationale du 4 août", "holiday_type": "national"},
        {"md": "08-05", "label": "Fête de l'Indépendance", "holiday_type": "national"},
        {"md": "08-15", "label": "Assomption", "holiday_type": "religious"},
        {"md": "11-01", "label": "Toussaint", "holiday_type": "religious"},
        {"md": "12-11", "label": "Proclamation de la République", "holiday_type": "national"},
        {"md": "12-25", "label": "Noël", "holiday_type": "religious"},
    ],
    "CI": [  # Côte d'Ivoire
        {"md": "01-01", "label": "Jour de l'An", "holiday_type": "national"},
        {"md": "05-01", "label": "Fête du Travail", "holiday_type": "national"},
        {"md": "08-07", "label": "Fête de l'Indépendance", "holiday_type": "national"},
        {"md": "08-15", "label": "Assomption", "holiday_type": "religious"},
        {"md": "11-01", "label": "Toussaint", "holiday_type": "religious"},
        {"md": "11-15", "label": "Journée nationale de la paix", "holiday_type": "national"},
        {"md": "12-25", "label": "Noël", "holiday_type": "religious"},
    ],
    "SN": [  # Sénégal
        {"md": "01-01", "label": "Jour de l'An", "holiday_type": "national"},
        {"md": "04-04", "label": "Fête de l'Indépendance", "holiday_type": "national"},
        {"md": "05-01", "label": "Fête du Travail", "holiday_type": "national"},
        {"md": "08-15", "label": "Assomption", "holiday_type": "religious"},
        {"md": "11-01", "label": "Toussaint", "holiday_type": "religious"},
        {"md": "12-25", "label": "Noël", "holiday_type": "religious"},
    ],
    "FR": [  # France
        {"md": "01-01", "label": "Jour de l'An", "holiday_type": "national"},
        {"md": "05-01", "label": "Fête du Travail", "holiday_type": "national"},
        {"md": "05-08", "label": "Victoire 1945", "holiday_type": "national"},
        {"md": "07-14", "label": "Fête nationale", "holiday_type": "national"},
        {"md": "08-15", "label": "Assomption", "holiday_type": "religious"},
        {"md": "11-01", "label": "Toussaint", "holiday_type": "religious"},
        {"md": "11-11", "label": "Armistice 1918", "holiday_type": "national"},
        {"md": "12-25", "label": "Noël", "holiday_type": "religious"},
    ],
}


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

    # Iter38d — Exposed so payroll_webhooks can re-use payslip computation
    _exposed = {}

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
        # Iter38c — Generate matricule automatically per tenant.
        # Format: MAT-{tenant_prefix}-{sequence:05d}
        # tenant_prefix = first 4 alphanumeric chars of tenant company (uppercase).
        tenant_company = ""
        tenant_doc = await db.users.find_one({"id": tid}, {"_id": 0, "company": 1, "full_name": 1})
        if tenant_doc:
            tenant_company = (tenant_doc.get("company") or tenant_doc.get("full_name") or "").upper()
        import re as _re
        prefix = _re.sub(r"[^A-Z0-9]", "", tenant_company)[:4] or "TEAM"
        counter = await db.employee_matricule_counters.find_one_and_update(
            {"tenant_id": tid},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        seq = int((counter or {}).get("seq", 1))
        matricule = f"MAT-{prefix}-{seq:05d}"
        doc = payload.model_dump()
        doc.update(
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tid,
                "matricule": matricule,
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
        elif pay_type == "fixed":
            # Iter40-hr-fixed — Flat amount, ignores hours worked completely.
            # Useful for late-month hires, trial periods, or contractors.
            computed = round(base, 2)
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

    @router.post("/employees/backfill-matricules")
    async def backfill_matricules(user: dict = Depends(get_current_user)):
        """Iter38c — Assign auto-generated matricule to employees missing one (tenant-scoped)."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        # Need per-tenant matricule sequence. Walk by tenant if super-admin.
        affected: List[Dict[str, Any]] = []
        if not scope:
            # super-admin: process across all tenants
            tenant_ids = await db.hr_employees.distinct("tenant_id", {"matricule": {"$in": [None, ""]}})
        else:
            tenant_ids = [scope.get("tenant_id")]
        import re as _re
        for tid in tenant_ids:
            if not tid:
                continue
            tenant_doc = await db.users.find_one({"id": tid}, {"_id": 0, "company": 1, "full_name": 1})
            tenant_company = ((tenant_doc or {}).get("company") or (tenant_doc or {}).get("full_name") or "").upper()
            prefix = _re.sub(r"[^A-Z0-9]", "", tenant_company)[:4] or "TEAM"
            # Find candidates missing a matricule
            cursor = db.hr_employees.find(
                {"tenant_id": tid, "matricule": {"$in": [None, ""]}},
                {"_id": 0, "id": 1, "name_snapshot": 1},
            ).sort("created_at", 1)
            async for emp in cursor:
                counter = await db.employee_matricule_counters.find_one_and_update(
                    {"tenant_id": tid},
                    {"$inc": {"seq": 1}},
                    upsert=True,
                    return_document=True,
                )
                seq = int((counter or {}).get("seq", 1))
                matricule = f"MAT-{prefix}-{seq:05d}"
                await db.hr_employees.update_one(
                    {"id": emp["id"]},
                    {"$set": {"matricule": matricule, "updated_at": _now_iso()}},
                )
                affected.append({"id": emp["id"], "name": emp.get("name_snapshot"), "matricule": matricule})
        return {"ok": True, "count": len(affected), "items": affected}

    # ================================================================
    # Iter38b — HR Settings (tenant scope, stored in db.hr_settings)
    # ================================================================
    async def _hr_settings(user: dict) -> dict:
        if _is_super_admin(user):
            return await db.hr_settings.find_one({"_id": "default"}, {"_id": 0}) or {}
        tid = await _resolve_tenant_id(user)
        return await db.hr_settings.find_one({"tenant_id": tid}, {"_id": 0}) or {}

    @router.get("/settings")
    async def get_hr_settings(user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        s = await _hr_settings(user)
        # Defaults
        return {
            "absence_threshold_hours": float(s.get("absence_threshold_hours", 0)),
            "payslip_company_name": s.get("payslip_company_name") or "",
            "payslip_employer_id": s.get("payslip_employer_id") or "",
            "payslip_address": s.get("payslip_address") or "",
            "payslip_legal_mentions": s.get("payslip_legal_mentions") or "",
            "payslip_footer": s.get("payslip_footer") or "",
        }

    @router.patch("/settings")
    async def update_hr_settings(payload: HrSettingsPayload, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        tid = await _resolve_tenant_id(user)
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        updates["tenant_id"] = tid
        updates["updated_at"] = _now_iso()
        await db.hr_settings.update_one(
            {"tenant_id": tid}, {"$set": updates}, upsert=True
        )
        return await get_hr_settings(user)

    # ================================================================
    # Iter38b — Phase 4: Absences
    # ================================================================
    def _days_inclusive(start: str, end: str) -> List[str]:
        try:
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            return []
        from datetime import timedelta as _td
        out = []
        cur = s
        while cur <= e:
            out.append(cur.isoformat())
            cur = cur + _td(days=1)
        return out

    async def _employee_in_tenant(user: dict, employee_id: str) -> Optional[dict]:
        scope = await _scoped(user)
        return await db.hr_employees.find_one(
            {**scope, "id": employee_id, "deleted_at": None}, {"_id": 0}
        )

    @router.get("/absences")
    async def list_absences(
        employee_id: Optional[str] = None,
        month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        q: Dict[str, Any] = {**scope}
        if employee_id:
            q["employee_id"] = employee_id
        if month:
            q["start_date"] = {"$gte": f"{month}-01", "$lt": f"{month}-32"}
        cursor = db.hr_absences.find(q, {"_id": 0}).sort("start_date", -1)
        return [a async for a in cursor]

    @router.post("/absences")
    async def create_absence(payload: AbsencePayload, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        emp = await _employee_in_tenant(user, payload.employee_id)
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        if payload.end_date < payload.start_date:
            raise HTTPException(status_code=400, detail="end_date doit être ≥ start_date")
        tid = await _resolve_tenant_id(user)
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "tenant_id": tid,
            "auto_detected": False,
            "created_at": _now_iso(),
            "created_by": user["id"],
        })
        await db.hr_absences.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/absences/{aid}")
    async def update_absence(aid: str, payload: AbsenceUpdate, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_absences.find_one({**scope, "id": aid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Absence introuvable")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not updates:
            return existing
        updates["updated_at"] = _now_iso()
        await db.hr_absences.update_one({"id": aid}, {"$set": updates})
        return await db.hr_absences.find_one({"id": aid}, {"_id": 0})

    @router.delete("/absences/{aid}")
    async def delete_absence(aid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_absences.find_one({**scope, "id": aid}, {"_id": 0, "wa_user_id": 1})
        res = await db.hr_absences.delete_one({**scope, "id": aid})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Absence introuvable")
        # Iter40 (2026-02) — Si la demande venait d'un !absence WA, on
        # ré-active l'utilisateur dont l'accès a été désactivé.
        if existing and existing.get("wa_user_id"):
            await db.users.update_one(
                {"id": existing["wa_user_id"], "wa_absence_request_id": aid},
                {"$set": {
                    "account_status": "active",
                    "wa_absence_disabled_at": None,
                    "wa_absence_request_id": None,
                }},
            )
        return {"ok": True}

    @router.post("/absences/{aid}/approve")
    async def approve_absence(aid: str, user: dict = Depends(get_current_user)):
        """Iter40 — Approuve une absence (typiquement une requête !absence WA).
        Sets status='approved' and re-activates the requesting user."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_absences.find_one({**scope, "id": aid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Absence introuvable")
        await db.hr_absences.update_one(
            {"id": aid},
            {"$set": {
                "status": "approved",
                "approved_at": _now_iso(),
                "approved_by": user["id"],
                "approved_by_name": user.get("full_name") or user.get("email"),
                "updated_at": _now_iso(),
            }},
        )
        # Re-activate the user
        if existing.get("wa_user_id"):
            await db.users.update_one(
                {"id": existing["wa_user_id"]},
                {"$set": {
                    "account_status": "active",
                    "wa_absence_disabled_at": None,
                    "wa_absence_request_id": None,
                }},
            )
        return await db.hr_absences.find_one({"id": aid}, {"_id": 0})

    @router.post("/absences/{aid}/reject")
    async def reject_absence(aid: str, user: dict = Depends(get_current_user)):
        """Iter40 — Refuse une absence en attente : suppression + réactivation de l'utilisateur."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_absences.find_one({**scope, "id": aid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Absence introuvable")
        await db.hr_absences.delete_one({"id": aid})
        if existing.get("wa_user_id"):
            await db.users.update_one(
                {"id": existing["wa_user_id"]},
                {"$set": {
                    "account_status": "active",
                    "wa_absence_disabled_at": None,
                    "wa_absence_request_id": None,
                }},
            )
        return {"ok": True, "rejected": True}

    @router.post("/advances/{aid}/approve")
    async def approve_advance(aid: str, user: dict = Depends(get_current_user)):
        """Iter40 — Approve a pending advance (typically WA-issued)."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_advances.find_one({**scope, "id": aid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Avance introuvable")
        await db.hr_advances.update_one(
            {"id": aid},
            {"$set": {
                "status": "pending",  # back to default workflow (pending repayment)
                "approved_at": _now_iso(),
                "approved_by": user["id"],
                "approved_by_name": user.get("full_name") or user.get("email"),
                "updated_at": _now_iso(),
            }},
        )
        return await db.hr_advances.find_one({"id": aid}, {"_id": 0})

    @router.post("/advances/{aid}/reject")
    async def reject_advance(aid: str, user: dict = Depends(get_current_user)):
        """Iter40 — Reject (delete) a pending advance."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        res = await db.hr_advances.delete_one({**scope, "id": aid})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Avance introuvable")
        return {"ok": True, "rejected": True}

    @router.post("/absences/scan")
    async def scan_auto_absences(
        employee_id: str = Query(...),
        month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
        user: dict = Depends(get_current_user),
    ):
        """Auto-detect business days in month with no access_logs entry.
        Returns suggested absences (not persisted). Caller can POST them with
        is_justified=false to persist.
        """
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        emp = await _employee_in_tenant(user, employee_id)
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        year_i, month_i = int(month[:4]), int(month[5:7])
        from calendar import monthrange
        last_day = monthrange(year_i, month_i)[1]
        # Compute set of days with logs
        uid = emp.get("user_id")
        snap_email = (emp.get("email_snapshot") or "").lower()
        or_conds: List[Dict[str, Any]] = []
        if uid:
            or_conds.append({"user_id": uid})
        if snap_email:
            or_conds.append({"user_email": snap_email})
        days_seen: set = set()
        if or_conds:
            pipeline = [
                {"$match": {
                    "$or": or_conds,
                    "created_at": {"$gte": f"{month}-01", "$lt": f"{month}-32"},
                }},
                {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}}},
            ]
            async for r in db.access_logs.aggregate(pipeline):
                days_seen.add(r.get("_id"))
        # Filter business days (Mon-Fri)
        suggestions = []
        for d in range(1, last_day + 1):
            date_iso = f"{year_i:04d}-{month_i:02d}-{d:02d}"
            try:
                dt = datetime.strptime(date_iso, "%Y-%m-%d")
            except ValueError:
                continue
            # weekday 0=Mon..6=Sun → business if <5
            if dt.weekday() >= 5:
                continue
            if date_iso not in days_seen:
                suggestions.append({
                    "date": date_iso,
                    "weekday": dt.strftime("%A"),
                    "suggested_hours": 8.0,
                    "abs_type": "non_justifiee",
                })
        return {"employee_id": employee_id, "month": month, "suggestions": suggestions}

    async def _absence_hours_for_month(user: dict, employee_id: str, month: str) -> Dict[str, float]:
        """Aggregate absences for a given employee+month.
        Returns {justified: float, unjustified: float, total: float, holiday: float}.

        Iter38o — Absences whose date falls on a configured public holiday
        (jour férié payé) are NOT counted as unjustified — they are reclassified
        to a separate 'holiday' bucket so HR / payroll never deducts pay for them.
        """
        scope = await _scoped(user)
        # Preload holiday dates for this month (set lookup, O(1))
        tid = await _resolve_tenant_id(user)
        holiday_dates = set()
        async for h in db.hr_holidays.find({
            "tenant_id": tid,
            "date": {"$gte": f"{month}-01", "$lte": f"{month}-31"},
            "is_paid": True,
        }, {"_id": 0, "date": 1}):
            holiday_dates.add(h["date"])
        cursor = db.hr_absences.find({
            **scope,
            "employee_id": employee_id,
            "start_date": {"$gte": f"{month}-01", "$lt": f"{month}-32"},
        }, {"_id": 0})
        j = 0.0
        u = 0.0
        holiday_hours = 0.0
        async for a in cursor:
            h = float(a.get("hours_count") or 0)
            on_holiday = (a.get("start_date") or "")[:10] in holiday_dates
            if on_holiday:
                holiday_hours += h
            elif a.get("is_justified"):
                j += h
            else:
                u += h
        return {"justified": j, "unjustified": u, "holiday": holiday_hours, "total": j + u + holiday_hours}

    # ================================================================
    # Iter38b — Phase 5: Taxes (definitions)
    # ================================================================
    @router.get("/taxes")
    async def list_taxes(user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        cursor = db.hr_taxes.find(scope, {"_id": 0}).sort("sort_order", 1)
        return [t async for t in cursor]

    @router.put("/taxes")
    async def replace_taxes(payload: TaxesReplacePayload, user: dict = Depends(get_current_user)):
        """Replace the tenant's taxes (max 5)."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        if len(payload.taxes) > 5:
            raise HTTPException(status_code=400, detail="Maximum 5 taxes par tenant")
        tid = await _resolve_tenant_id(user)
        await db.hr_taxes.delete_many({"tenant_id": tid})
        docs = []
        for idx, t in enumerate(payload.taxes):
            d = t.model_dump()
            d.update({
                "id": str(uuid.uuid4()),
                "tenant_id": tid,
                "sort_order": d.get("sort_order") or idx,
                "created_at": _now_iso(),
            })
            docs.append(d)
        if docs:
            await db.hr_taxes.insert_many([d.copy() for d in docs])
        for d in docs:
            d.pop("_id", None)
        return docs

    # ================================================================
    # Iter38b — Phase 5: Advances
    # ================================================================
    @router.get("/advances")
    async def list_advances(
        employee_id: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        q: Dict[str, Any] = {**scope}
        if employee_id:
            q["employee_id"] = employee_id
        cursor = db.hr_advances.find(q, {"_id": 0}).sort("granted_at", -1)
        return [a async for a in cursor]

    @router.post("/advances")
    async def create_advance(payload: AdvancePayload, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        emp = await _employee_in_tenant(user, payload.employee_id)
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        tid = await _resolve_tenant_id(user)
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "tenant_id": tid,
            "granted_at": doc.get("granted_at") or datetime.now(timezone.utc).date().isoformat(),
            "repaid_amount": 0.0,
            "status": "pending",
            "created_at": _now_iso(),
            "created_by": user["id"],
        })
        await db.hr_advances.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.post("/advances/{aid}/repay")
    async def repay_advance(aid: str, payload: AdvanceRepayPayload, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        adv = await db.hr_advances.find_one({**scope, "id": aid}, {"_id": 0})
        if not adv:
            raise HTTPException(status_code=404, detail="Avance introuvable")
        new_repaid = float(adv.get("repaid_amount", 0)) + payload.repaid_amount
        amount = float(adv.get("amount") or 0)
        status_val = "repaid" if new_repaid >= amount else ("partial" if new_repaid > 0 else "pending")
        await db.hr_advances.update_one(
            {"id": aid},
            {"$set": {
                "repaid_amount": round(new_repaid, 2),
                "status": status_val,
                "last_repay_note": payload.note,
                "last_repay_at": _now_iso(),
            }},
        )
        return await db.hr_advances.find_one({"id": aid}, {"_id": 0})

    @router.delete("/advances/{aid}")
    async def delete_advance(aid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        res = await db.hr_advances.delete_one({**scope, "id": aid})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Avance introuvable")
        return {"ok": True}

    # ================================================================
    # Iter38b — Phase 6: Payslip synthesis (preview + PDF)
    # ================================================================
    async def _compute_payslip(user: dict, eid: str, month: str) -> Dict[str, Any]:
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one({**scope, "id": eid}, {"_id": 0})
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        # Reuse timesheet computation
        ts = await employee_timesheet(eid=eid, month=month, user=user)  # type: ignore[name-defined]
        totals = ts["totals"]
        gross = float(totals.get("computed_gross") or 0)
        hr_set = await _hr_settings(user)
        global_threshold = float(hr_set.get("absence_threshold_hours", 0))
        threshold = float(emp.get("absence_threshold_hours_override") or 0) or global_threshold
        abs_h = await _absence_hours_for_month(user, eid, month)
        # Deduction: per-hour rate
        # Iter40-hr-fixed — pay_type=fixed: NO absence deduction (flat amount).
        baseline_hours = float(emp.get("monthly_hours_baseline") or 1) or 1
        if emp.get("pay_type") == "fixed":
            hourly_for_deduction = 0.0
        elif emp.get("pay_type") == "hourly":
            hourly_for_deduction = float(emp.get("hourly_rate") or 0)
        else:
            hourly_for_deduction = float(emp.get("base_salary") or 0) / baseline_hours
        billable_unjustified = max(0.0, abs_h["unjustified"] - threshold)
        absence_deduction = round(billable_unjustified * hourly_for_deduction, 2)
        # S-iter39s — Allowances (indemnités fixes récurrentes) + bonuses (primes du mois)
        allowance_cursor = db.hr_allowances.find({
            **scope, "employee_id": eid, "active": True,
        }, {"_id": 0}).sort("sort_order", 1)
        allowance_lines = []
        total_allowances = 0.0
        async for al in allowance_cursor:
            amt = float(al.get("amount", 0))
            total_allowances += amt
            allowance_lines.append({
                "id": al["id"], "label": al.get("label"),
                "amount": round(amt, 2),
                "notes": al.get("notes") or "",
            })
        total_allowances = round(total_allowances, 2)
        bonus_cursor = db.hr_bonuses.find({
            **scope, "employee_id": eid, "month": month,
        }, {"_id": 0}).sort("created_at", 1)
        bonus_lines = []
        total_bonuses = 0.0
        async for b in bonus_cursor:
            amt = float(b.get("amount", 0))
            total_bonuses += amt
            bonus_lines.append({
                "id": b["id"], "label": b.get("label"),
                "amount": round(amt, 2),
                "notes": b.get("notes") or "",
            })
        total_bonuses = round(total_bonuses, 2)
        gross_with_gains = round(gross + total_allowances + total_bonuses, 2)
        # Apply tax overrides
        emp_overrides = emp.get("tax_overrides") or {}
        taxes_cursor = db.hr_taxes.find({**scope}, {"_id": 0}).sort("sort_order", 1)
        taxes = [t async for t in taxes_cursor]
        tax_lines = []
        total_taxes = 0.0
        gross_after_abs = max(0.0, gross_with_gains - absence_deduction)
        for t in taxes:
            if not t.get("active"):
                continue
            override_val = emp_overrides.get(t["id"])
            v = float(override_val if override_val is not None else t.get("value", 0))
            if t.get("calc_type") == "fixed":
                amt = v
            else:
                base = gross_after_abs  # for simplicity, both gross/net use post-absence gross
                amt = round(base * v / 100.0, 2)
            total_taxes += amt
            tax_lines.append({
                "id": t["id"], "label": t.get("label"),
                "calc_type": t.get("calc_type"), "value": v,
                "amount": round(amt, 2),
                "overridden": override_val is not None,
            })
        total_taxes = round(total_taxes, 2)
        # Advances pending auto-deduct
        adv_cursor = db.hr_advances.find({
            **scope, "employee_id": eid,
            "auto_deduct": True, "status": {"$ne": "repaid"},
        }, {"_id": 0})
        adv_total = 0.0
        adv_lines = []
        async for a in adv_cursor:
            remaining = float(a.get("amount", 0)) - float(a.get("repaid_amount", 0))
            if remaining <= 0:
                continue
            adv_total += remaining
            adv_lines.append({
                "id": a["id"], "motive": a.get("motive"),
                "amount": float(a.get("amount", 0)),
                "remaining": round(remaining, 2),
            })
        adv_total = round(adv_total, 2)
        # Iter38c — Late-unjustified cashier expenses (rolled into payslip)
        from routes.cashier_expenses import late_unjustified_for_employee  # local import
        tid = await _resolve_tenant_id(user)
        late_expenses_amount = await late_unjustified_for_employee(
            db, tenant_id=tid, user_id=emp.get("user_id"), month=month
        )
        net = round(gross_after_abs - total_taxes - adv_total - late_expenses_amount, 2)
        return {
            "employee": {
                "id": emp["id"], "user_id": emp.get("user_id"),
                "matricule": emp.get("matricule"),
                "full_name": emp.get("name_snapshot"),
                "email": emp.get("email_snapshot"),
                "job_title": emp.get("job_title"),
                "department": emp.get("department"),
                "currency": emp.get("currency") or "XOF",
                "pay_type": emp.get("pay_type"),
            },
            "month": month,
            "hours_worked": totals.get("hours_worked"),
            "expected_hours": totals.get("expected_hours"),
            "absence_hours": abs_h,
            "absence_threshold_hours": threshold,
            "billable_unjustified_hours": round(billable_unjustified, 2),
            "absence_deduction": absence_deduction,
            "gross": gross,
            "allowances": allowance_lines,
            "total_allowances": total_allowances,
            "bonuses": bonus_lines,
            "total_bonuses": total_bonuses,
            "gross_with_gains": gross_with_gains,
            "gross_after_absence": round(gross_after_abs, 2),
            "taxes": tax_lines,
            "total_taxes": total_taxes,
            "advances": adv_lines,
            "advances_deduction": adv_total,
            "late_expenses_deduction": late_expenses_amount,
            "net": net,
            "hr_settings": hr_set,
        }

    @router.get("/employees/{eid}/payslip")
    async def employee_payslip(
        eid: str,
        month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        return await _compute_payslip(user, eid, month)

    @router.get("/employees/{eid}/payslip.pdf")
    async def employee_payslip_pdf(
        eid: str,
        month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
        user: dict = Depends(get_current_user),
    ):
        from fastapi import Response  # local import
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        data = await _compute_payslip(user, eid, month)
        pdf_bytes = _render_payslip_pdf(data)
        fname = f"paie_{eid}_{month}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # ================================================================
    # Iter38b — Dashboard mini-graph: weekly presence
    # ================================================================
    @router.get("/dashboard/weekly-presence")
    async def weekly_presence(user: dict = Depends(get_current_user)):
        """Top 5 active employees this calendar week (Mon-Sun, UTC)."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        now = datetime.now(timezone.utc)
        from datetime import timedelta as _td
        week_start = (now - _td(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + _td(days=7)
        cursor = db.hr_employees.find({**scope, "deleted_at": None}, {"_id": 0})
        emps = [e async for e in cursor]
        results = []
        for e in emps:
            uid = e.get("user_id")
            email = (e.get("email_snapshot") or "").lower()
            or_conds: List[Dict[str, Any]] = []
            if uid:
                or_conds.append({"user_id": uid})
            if email:
                or_conds.append({"user_email": email})
            if not or_conds:
                results.append({"employee_id": e["id"], "name": e.get("name_snapshot"), "hours": 0.0, "days": 0})
                continue
            pipeline = [
                {"$match": {
                    "$or": or_conds,
                    "created_at": {"$gte": week_start.isoformat(), "$lt": week_end.isoformat()},
                }},
                {"$group": {
                    "_id": {"$substr": ["$created_at", 0, 10]},
                    "first": {"$min": "$created_at"},
                    "last": {"$max": "$created_at"},
                }},
            ]
            secs = 0.0
            days = 0
            async for row in db.access_logs.aggregate(pipeline):
                try:
                    f_dt = datetime.fromisoformat(row["first"].replace("Z", "+00:00"))
                    l_dt = datetime.fromisoformat(row["last"].replace("Z", "+00:00"))
                    secs += max(0.0, (l_dt - f_dt).total_seconds())
                    days += 1
                except Exception:
                    pass
            results.append({
                "employee_id": e["id"],
                "name": e.get("name_snapshot") or e.get("email_snapshot"),
                "hours": round(secs / 3600.0, 2),
                "days": days,
            })
        results.sort(key=lambda x: x["hours"], reverse=True)
        return {
            "week_start": week_start.date().isoformat(),
            "week_end": (week_end - _td(days=1)).date().isoformat(),
            "top": results[:5],
            "total_employees": len(results),
        }

    # 2026-02 — Same metric, but aggregated over an arbitrary calendar month.
    # Used by the admin /portal/users dashboard card so admins can pick any
    # past month and see the top performers.
    @router.get("/dashboard/monthly-presence")
    async def monthly_presence(
        month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
        user: dict = Depends(get_current_user),
    ):
        """Top 10 employees by accumulated hours for the given month.
        `month` format = YYYY-MM. If absent, defaults to the current month."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        now = datetime.now(timezone.utc)
        from datetime import timedelta as _td
        month_str = month or f"{now.year}-{str(now.month).zfill(2)}"
        year, mon = int(month_str[:4]), int(month_str[5:7])
        month_start = datetime(year, mon, 1, tzinfo=timezone.utc)
        if mon == 12:
            month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            month_end = datetime(year, mon + 1, 1, tzinfo=timezone.utc)

        cursor = db.hr_employees.find({**scope, "deleted_at": None}, {"_id": 0})
        emps = [e async for e in cursor]
        results = []
        for e in emps:
            uid = e.get("user_id")
            email = (e.get("email_snapshot") or "").lower()
            or_conds: List[Dict[str, Any]] = []
            if uid:
                or_conds.append({"user_id": uid})
            if email:
                or_conds.append({"user_email": email})
            if not or_conds:
                results.append({"employee_id": e["id"], "name": e.get("name_snapshot"), "hours": 0.0, "days": 0})
                continue
            pipeline = [
                {"$match": {
                    "$or": or_conds,
                    "created_at": {"$gte": month_start.isoformat(), "$lt": month_end.isoformat()},
                }},
                {"$group": {
                    "_id": {"$substr": ["$created_at", 0, 10]},
                    "first": {"$min": "$created_at"},
                    "last": {"$max": "$created_at"},
                }},
            ]
            secs = 0.0
            days = 0
            async for row in db.access_logs.aggregate(pipeline):
                try:
                    f_dt = datetime.fromisoformat(row["first"].replace("Z", "+00:00"))
                    l_dt = datetime.fromisoformat(row["last"].replace("Z", "+00:00"))
                    secs += max(0.0, (l_dt - f_dt).total_seconds())
                    days += 1
                except Exception:
                    pass
            results.append({
                "employee_id": e["id"],
                "name": e.get("name_snapshot") or e.get("email_snapshot"),
                "hours": round(secs / 3600.0, 2),
                "days": days,
            })
        results.sort(key=lambda x: x["hours"], reverse=True)
        return {
            "month": month_str,
            "month_start": month_start.date().isoformat(),
            "month_end": (month_end - _td(days=1)).date().isoformat(),
            "top": results[:10],
            "total_employees": len(results),
        }

    # ================================================================
    # Iter38m — Holidays (Jours fériés) — per tenant
    # ================================================================
    @router.get("/holidays")
    async def list_holidays(
        year: Optional[int] = Query(None, ge=1970, le=3000),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        q: Dict[str, Any] = {**scope}
        if year is not None:
            q["date"] = {"$gte": f"{year:04d}-01-01", "$lte": f"{year:04d}-12-31"}
        cursor = db.hr_holidays.find(q, {"_id": 0}).sort("date", 1)
        return [h async for h in cursor]

    @router.post("/holidays")
    async def create_holiday(
        payload: HolidayPayload, user: dict = Depends(get_current_user)
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        tid = await _resolve_tenant_id(user)
        # Idempotence: prevent two holidays with same (tenant, date, label)
        existing = await db.hr_holidays.find_one(
            {"tenant_id": tid, "date": payload.date, "label": payload.label},
            {"_id": 0, "id": 1},
        )
        if existing:
            raise HTTPException(
                status_code=409, detail="Jour férié déjà enregistré à cette date avec ce libellé"
            )
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "tenant_id": tid,
            "created_at": _now_iso(),
            "created_by": user["id"],
            "updated_at": _now_iso(),
        })
        await db.hr_holidays.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/holidays/{hid}")
    async def update_holiday(
        hid: str, payload: HolidayUpdate, user: dict = Depends(get_current_user)
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_holidays.find_one({**scope, "id": hid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Jour férié introuvable")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not updates:
            return existing
        updates["updated_at"] = _now_iso()
        await db.hr_holidays.update_one({"id": hid}, {"$set": updates})
        return await db.hr_holidays.find_one({"id": hid}, {"_id": 0})

    @router.delete("/holidays/{hid}")
    async def delete_holiday(hid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        res = await db.hr_holidays.delete_one({**scope, "id": hid})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Jour férié introuvable")
        return {"ok": True}

    @router.post("/holidays/import")
    async def import_holidays(
        year: int = Query(..., ge=1970, le=3000),
        country: Optional[str] = Query(None, min_length=2, max_length=4),
        user: dict = Depends(get_current_user),
    ):
        """Importe les jours fériés à date fixe connus pour l'année/pays donnés.
        Country code defaults to the tenant's configured default (BF if none).
        Returns {created, skipped, items: [...]}.
        Mobile religious holidays (Aïd, Mawlid) must be added manually."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        tid = await _resolve_tenant_id(user)
        # Resolve country from tenant_meta if not provided
        country_code = (country or "").strip().upper()
        if not country_code:
            tm = await db.tenant_meta.find_one(
                {"tenant_id": tid}, {"_id": 0, "country_code": 1}
            ) or {}
            country_code = (tm.get("country_code") or "BF").upper()
        catalog = _HOLIDAYS_CATALOG.get(country_code) or _HOLIDAYS_CATALOG["BF"]
        created: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for entry in catalog:
            date_iso = f"{year:04d}-{entry['md']}"
            existing = await db.hr_holidays.find_one(
                {"tenant_id": tid, "date": date_iso, "label": entry["label"]},
                {"_id": 0, "id": 1},
            )
            if existing:
                skipped.append({"date": date_iso, "label": entry["label"]})
                continue
            doc = {
                "id": str(uuid.uuid4()),
                "tenant_id": tid,
                "date": date_iso,
                "label": entry["label"],
                "holiday_type": entry["holiday_type"],
                "is_paid": True,
                "created_at": _now_iso(),
                "created_by": user["id"],
                "updated_at": _now_iso(),
            }
            await db.hr_holidays.insert_one(doc.copy())
            doc.pop("_id", None)
            created.append(doc)
        return {
            "country": country_code,
            "year": year,
            "created": created,
            "skipped": skipped,
            "created_count": len(created),
            "skipped_count": len(skipped),
        }

    # Iter38d — Expose _compute_payslip to payroll_webhooks module
    async def compute_payslip_public(user: dict, eid: str, month: str):
        return await _compute_payslip(user, eid, month)
    router.compute_payslip = compute_payslip_public  # type: ignore[attr-defined]

    # 0-3 (2026-02) — Auto-generated codes for pay-table indexes.
    # Format : `IND-NNNN` for indemnités, `PRM-NNNN` for primes, `CAT-NNNN`
    # for the standalone catalog. Tenant-scoped counter stored in hr_counters.
    async def _next_pay_code(tid: str, prefix: str) -> str:
        counter_id = f"hr_{prefix.lower()}_{tid}"
        r = await db.hr_counters.find_one_and_update(
            {"_id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,  # type: ignore[arg-type]
        )
        # find_one_and_update returns the updated doc when return_document=AFTER;
        # motor's default differs — fallback to fetching the doc explicitly.
        seq = (r or {}).get("seq")
        if not seq:
            doc = await db.hr_counters.find_one({"_id": counter_id})
            seq = (doc or {}).get("seq", 1)
        return f"{prefix}-{int(seq):04d}"

    # =====================================================================
    # S-iter39s (2026-02) — Allowances (indemnités fixes) CRUD
    # =====================================================================
    @router.get("/employees/{eid}/allowances")
    async def list_allowances(eid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one({**scope, "id": eid, "deleted_at": None}, {"_id": 0, "id": 1})
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        cursor = db.hr_allowances.find(
            {**scope, "employee_id": eid}, {"_id": 0}
        ).sort([("active", -1), ("sort_order", 1), ("created_at", 1)])
        return [a async for a in cursor]

    @router.post("/employees/{eid}/allowances")
    async def create_allowance(
        eid: str, payload: AllowancePayload, user: dict = Depends(get_current_user)
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one({**scope, "id": eid, "deleted_at": None}, {"_id": 0, "id": 1})
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        tid = await _resolve_tenant_id(user)
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "code": await _next_pay_code(tid, "IND"),  # 0-3 — auto code IND-NNNN
            "tenant_id": tid,
            "employee_id": eid,
            "created_at": _now_iso(),
            "created_by": user["id"],
            "updated_at": _now_iso(),
        })
        await db.hr_allowances.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/allowances/{aid}")
    async def update_allowance(
        aid: str, payload: AllowanceUpdate, user: dict = Depends(get_current_user)
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_allowances.find_one({**scope, "id": aid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Indemnité introuvable")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not updates:
            return existing
        updates["updated_at"] = _now_iso()
        await db.hr_allowances.update_one({"id": aid}, {"$set": updates})
        return await db.hr_allowances.find_one({"id": aid}, {"_id": 0})

    @router.delete("/allowances/{aid}")
    async def delete_allowance(aid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        r = await db.hr_allowances.delete_one({**scope, "id": aid})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Indemnité introuvable")
        return {"ok": True, "id": aid}

    # =====================================================================
    # S-iter39s (2026-02) — Bonuses (primes variables par mois) CRUD
    # =====================================================================
    @router.get("/employees/{eid}/bonuses")
    async def list_bonuses(
        eid: str,
        month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one({**scope, "id": eid, "deleted_at": None}, {"_id": 0, "id": 1})
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        q: Dict[str, Any] = {**scope, "employee_id": eid}
        if month:
            q["month"] = month
        cursor = db.hr_bonuses.find(q, {"_id": 0}).sort([("month", -1), ("created_at", 1)])
        return [b async for b in cursor]

    @router.post("/employees/{eid}/bonuses")
    async def create_bonus(
        eid: str, payload: BonusPayload, user: dict = Depends(get_current_user)
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one({**scope, "id": eid, "deleted_at": None}, {"_id": 0, "id": 1})
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        tid = await _resolve_tenant_id(user)
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "code": await _next_pay_code(tid, "PRM"),  # 0-3 — auto code PRM-NNNN
            "tenant_id": tid,
            "employee_id": eid,
            "created_at": _now_iso(),
            "created_by": user["id"],
        })
        await db.hr_bonuses.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/bonuses/{bid}")
    async def update_bonus(
        bid: str, payload: BonusUpdate, user: dict = Depends(get_current_user)
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_bonuses.find_one({**scope, "id": bid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Prime introuvable")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not updates:
            return existing
        updates["updated_at"] = _now_iso()
        await db.hr_bonuses.update_one({"id": bid}, {"$set": updates})
        return await db.hr_bonuses.find_one({"id": bid}, {"_id": 0})

    @router.delete("/bonuses/{bid}")
    async def delete_bonus(bid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        r = await db.hr_bonuses.delete_one({**scope, "id": bid})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Prime introuvable")
        return {"ok": True, "id": bid}

    # =====================================================================
    # 0-3 (2026-02) — Pay Catalog (standalone allowance/bonus templates)
    # =====================================================================
    @router.get("/pay-catalog")
    async def list_catalog(
        kind: Optional[str] = Query(None, pattern=r"^(allowance|bonus)$"),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        q: Dict[str, Any] = {**scope}
        if kind:
            q["kind"] = kind
        cursor = db.hr_pay_catalog.find(q, {"_id": 0}).sort([("kind", 1), ("label", 1)])
        return [c async for c in cursor]

    @router.post("/pay-catalog")
    async def create_catalog_item(
        payload: PayCatalogItemPayload, user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        tid = await _resolve_tenant_id(user)
        prefix = "CAT" if payload.kind == "allowance" else "PRMC"
        doc = payload.model_dump()
        doc.update({
            "id": str(uuid.uuid4()),
            "code": await _next_pay_code(tid, prefix),
            "tenant_id": tid,
            "created_at": _now_iso(),
            "created_by": user["id"],
            "updated_at": _now_iso(),
        })
        await db.hr_pay_catalog.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/pay-catalog/{cid}")
    async def update_catalog_item(
        cid: str, payload: PayCatalogItemUpdate, user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        existing = await db.hr_pay_catalog.find_one({**scope, "id": cid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Élément introuvable")
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not updates:
            return existing
        updates["updated_at"] = _now_iso()
        await db.hr_pay_catalog.update_one({"id": cid}, {"$set": updates})
        return await db.hr_pay_catalog.find_one({"id": cid}, {"_id": 0})

    @router.delete("/pay-catalog/{cid}")
    async def delete_catalog_item(cid: str, user: dict = Depends(get_current_user)):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        r = await db.hr_pay_catalog.delete_one({**scope, "id": cid})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Élément introuvable")
        return {"ok": True, "id": cid}

    @router.post("/employees/{eid}/apply-catalog/{cid}")
    async def apply_catalog_to_employee(
        eid: str, cid: str,
        amount: Optional[float] = Form(None),
        bonus_month: Optional[str] = Form(None),
        user: dict = Depends(get_current_user),
    ):
        """0-3 — Applique un modèle de catalogue à un employé. Pour les indemnités,
        creates a hr_allowances row; for bonuses, creates a hr_bonuses row
        (bonus_month required). The amount can be overridden via the
        `amount` form field, otherwise uses default_amount from catalog."""
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        emp = await db.hr_employees.find_one({**scope, "id": eid, "deleted_at": None}, {"_id": 0, "id": 1})
        if not emp:
            raise HTTPException(status_code=404, detail="Employé introuvable")
        cat = await db.hr_pay_catalog.find_one({**scope, "id": cid}, {"_id": 0})
        if not cat:
            raise HTTPException(status_code=404, detail="Élément catalogue introuvable")
        tid = await _resolve_tenant_id(user)
        final_amount = float(amount) if amount is not None else float(cat.get("default_amount") or 0)
        now = _now_iso()
        if cat["kind"] == "allowance":
            doc = {
                "id": str(uuid.uuid4()),
                "code": await _next_pay_code(tid, "IND"),
                "tenant_id": tid,
                "employee_id": eid,
                "label": cat["label"],
                "amount": final_amount,
                "currency": cat.get("currency", "XOF"),
                "active": True,
                "sort_order": 0,
                "notes": cat.get("description") or "",
                "catalog_id": cid,
                "created_at": now,
                "created_by": user["id"],
                "updated_at": now,
            }
            await db.hr_allowances.insert_one(doc.copy())
        else:  # bonus
            if not bonus_month:
                raise HTTPException(status_code=400, detail="bonus_month requis pour une prime.")
            if not re.match(r"^\d{4}-\d{2}$", bonus_month):
                raise HTTPException(status_code=400, detail="bonus_month doit être au format YYYY-MM.")
            doc = {
                "id": str(uuid.uuid4()),
                "code": await _next_pay_code(tid, "PRM"),
                "tenant_id": tid,
                "employee_id": eid,
                "month": bonus_month,
                "label": cat["label"],
                "amount": final_amount,
                "currency": cat.get("currency", "XOF"),
                "notes": cat.get("description") or "",
                "catalog_id": cid,
                "created_at": now,
                "created_by": user["id"],
            }
            await db.hr_bonuses.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    # =====================================================================
    # 0-3 (2026-02) — Copy primes/indemnités from one employee to another
    # =====================================================================
    @router.post("/employees/{src_eid}/copy-pay-items")
    async def copy_pay_items(
        src_eid: str, payload: CopyPayItemsPayload, user: dict = Depends(get_current_user),
    ):
        if not _can_access_hr(user):
            raise HTTPException(status_code=403, detail="Accès réservé au module GRH")
        scope = await _scoped(user)
        src = await db.hr_employees.find_one({**scope, "id": src_eid, "deleted_at": None}, {"_id": 0, "id": 1})
        if not src:
            raise HTTPException(status_code=404, detail="Employé source introuvable")
        tgt = await db.hr_employees.find_one({**scope, "id": payload.target_employee_id, "deleted_at": None}, {"_id": 0, "id": 1})
        if not tgt:
            raise HTTPException(status_code=404, detail="Employé cible introuvable")
        if src_eid == payload.target_employee_id:
            raise HTTPException(status_code=400, detail="Source et cible doivent différer.")
        tid = await _resolve_tenant_id(user)
        now = _now_iso()
        copied_allowances = 0
        copied_bonuses = 0
        if payload.include_allowances:
            cursor = db.hr_allowances.find(
                {**scope, "employee_id": src_eid, "active": True}, {"_id": 0},
            )
            async for src_al in cursor:
                doc = {
                    "id": str(uuid.uuid4()),
                    "code": await _next_pay_code(tid, "IND"),
                    "tenant_id": tid,
                    "employee_id": payload.target_employee_id,
                    "label": src_al["label"],
                    "amount": src_al["amount"],
                    "currency": src_al.get("currency", "XOF"),
                    "active": True,
                    "sort_order": src_al.get("sort_order", 0),
                    "notes": src_al.get("notes") or "",
                    "catalog_id": src_al.get("catalog_id"),
                    "copied_from_employee_id": src_eid,
                    "created_at": now,
                    "created_by": user["id"],
                    "updated_at": now,
                }
                await db.hr_allowances.insert_one(doc.copy())
                copied_allowances += 1
        if payload.include_bonuses:
            if not payload.bonus_month:
                raise HTTPException(status_code=400, detail="bonus_month requis quand include_bonuses=true.")
            cursor = db.hr_bonuses.find(
                {**scope, "employee_id": src_eid, "month": payload.bonus_month}, {"_id": 0},
            )
            async for src_b in cursor:
                doc = {
                    "id": str(uuid.uuid4()),
                    "code": await _next_pay_code(tid, "PRM"),
                    "tenant_id": tid,
                    "employee_id": payload.target_employee_id,
                    "month": src_b["month"],
                    "label": src_b["label"],
                    "amount": src_b["amount"],
                    "currency": src_b.get("currency", "XOF"),
                    "notes": src_b.get("notes") or "",
                    "catalog_id": src_b.get("catalog_id"),
                    "copied_from_employee_id": src_eid,
                    "created_at": now,
                    "created_by": user["id"],
                }
                await db.hr_bonuses.insert_one(doc.copy())
                copied_bonuses += 1
        return {
            "ok": True,
            "source_employee_id": src_eid,
            "target_employee_id": payload.target_employee_id,
            "copied_allowances": copied_allowances,
            "copied_bonuses": copied_bonuses,
        }

    return router


# =====================================================================
# Payslip PDF rendering (Iter38b — Phase 6)
# =====================================================================
def _fmt_amount(v: float, currency: str = "XOF") -> str:
    try:
        return f"{float(v):,.0f} {currency}".replace(",", " ")
    except Exception:
        return f"{v} {currency}"


def _render_payslip_pdf(data: Dict[str, Any]) -> bytes:
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    hr_set = data.get("hr_settings") or {}
    emp = data["employee"]
    currency = emp.get("currency", "XOF")
    company_name = hr_set.get("payslip_company_name") or "—"
    employer_id = hr_set.get("payslip_employer_id") or ""
    addr = hr_set.get("payslip_address") or ""
    legal = hr_set.get("payslip_legal_mentions") or ""
    footer = hr_set.get("payslip_footer") or ""

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=24, bottomMargin=24, leftMargin=28, rightMargin=28,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontSize=15, textColor=colors.HexColor("#0E1F3D"))
    h = ParagraphStyle("h", parent=styles["Heading4"], fontSize=10, textColor=colors.HexColor("#0E1F3D"))
    muted = ParagraphStyle("m", parent=styles["BodyText"], fontSize=8, textColor=colors.HexColor("#64748b"))

    story = []
    # Header
    story.append(Paragraph(f"<b>{company_name}</b>", title))
    if employer_id:
        story.append(Paragraph(f"N° employeur : {employer_id}", muted))
    if addr:
        story.append(Paragraph(addr.replace("\n", "<br/>"), muted))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>BULLETIN DE PAIE — {data['month']}</b>", h))
    story.append(Spacer(1, 6))

    # Identity
    id_data = [
        ["Matricule", emp.get("matricule") or "—", "Période", data["month"]],
        ["Employé", emp.get("full_name") or "—", "Poste", emp.get("job_title") or "—"],
        ["Email", emp.get("email") or "—", "Département", emp.get("department") or "—"],
        ["Type paie", "Horaire" if emp.get("pay_type") == "hourly" else "Mensuel", "", ""],
    ]
    t = Table(id_data, colWidths=[70, 180, 70, 180])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#64748b")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#64748b")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    # Gains
    story.append(Paragraph("<b>GAINS</b>", h))
    gains_data = [
        ["Salaire brut estimé", _fmt_amount(data["gross"], currency)],
        ["Heures travaillées (mois)", f"{data['hours_worked']} h / {data['expected_hours']} h"],
    ]
    # S-iter39s — Allowances (indemnités fixes) + bonuses (primes variables)
    for al in (data.get("allowances") or []):
        gains_data.append([f"Indemnité — {al['label']}", _fmt_amount(al['amount'], currency)])
    for b in (data.get("bonuses") or []):
        gains_data.append([f"Prime — {b['label']}", _fmt_amount(b['amount'], currency)])
    total_allowances = float(data.get("total_allowances") or 0)
    total_bonuses = float(data.get("total_bonuses") or 0)
    if total_allowances or total_bonuses:
        gains_data.append([
            "Total brut avec indemnités & primes",
            _fmt_amount(data.get("gross_with_gains") or data["gross"], currency),
        ])
    tg = Table(gains_data, colWidths=[350, 150])
    tg.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold") if (total_allowances or total_bonuses) else ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(tg)
    story.append(Spacer(1, 8))

    # Absences
    story.append(Paragraph("<b>ABSENCES</b>", h))
    abs_data = [
        ["Absences justifiées", f"{data['absence_hours']['justified']:.1f} h"],
        ["Absences non justifiées", f"{data['absence_hours']['unjustified']:.1f} h"],
        ["Seuil de tolérance", f"{data['absence_threshold_hours']:.1f} h"],
        ["Heures à déduire", f"{data['billable_unjustified_hours']:.1f} h"],
        ["Déduction sur salaire", _fmt_amount(data['absence_deduction'], currency)],
    ]
    ta = Table(abs_data, colWidths=[350, 150])
    ta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(ta)
    story.append(Spacer(1, 8))

    # Taxes
    story.append(Paragraph("<b>RETENUES & TAXES</b>", h))
    if data["taxes"]:
        tx_rows = [["Libellé", "Valeur", "Montant"]]
        for tx in data["taxes"]:
            v = f"{tx['value']}%" if tx["calc_type"] == "percentage" else _fmt_amount(tx["value"], currency)
            tx_rows.append([tx["label"], v, _fmt_amount(tx["amount"], currency)])
        tx_rows.append(["", "Total taxes", _fmt_amount(data["total_taxes"], currency)])
        ttx = Table(tx_rows, colWidths=[260, 90, 150])
        ttx.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("FONTNAME", (-1, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (-2, -1), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(ttx)
    else:
        story.append(Paragraph("Aucune taxe configurée pour ce tenant.", muted))
    story.append(Spacer(1, 8))

    # Advances
    if data["advances"]:
        story.append(Paragraph("<b>AVANCES SUR SALAIRE</b>", h))
        adv_rows = [["Motif", "Montant initial", "Restant à déduire"]]
        for a in data["advances"]:
            adv_rows.append([a.get("motive") or "—",
                             _fmt_amount(a["amount"], currency),
                             _fmt_amount(a["remaining"], currency)])
        adv_rows.append(["", "Total avances", _fmt_amount(data["advances_deduction"], currency)])
        tadv = Table(adv_rows, colWidths=[260, 130, 110])
        tadv.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("FONTNAME", (-1, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (-2, -1), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(tadv)
        story.append(Spacer(1, 8))

    # Iter38c — Late-unjustified expenses deduction
    late_exp = float(data.get("late_expenses_deduction") or 0)
    if late_exp > 0:
        story.append(Paragraph("<b>DÉPENSES CAISSE NON JUSTIFIÉES (EN RETARD)</b>", h))
        le_rows = [
            ["Somme des dépenses non justifiées au-delà du délai",
             _fmt_amount(late_exp, currency)],
        ]
        tle = Table(le_rows, colWidths=[350, 150])
        tle.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef2f2")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#991b1b")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(tle)
        story.append(Spacer(1, 8))

    # Net
    net_data = [["NET À PAYER", _fmt_amount(data["net"], currency)]]
    tn = Table(net_data, colWidths=[350, 150])
    tn.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0E1F3D")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(tn)
    story.append(Spacer(1, 10))

    if legal:
        story.append(Paragraph(legal.replace("\n", "<br/>"), muted))
    if footer:
        story.append(Spacer(1, 6))
        story.append(Paragraph(footer.replace("\n", "<br/>"), muted))

    doc.build(story)
    return buf.getvalue()



__all__ = ["make_router"]
