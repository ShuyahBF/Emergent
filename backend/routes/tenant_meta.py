"""Iter38b — Tenant country & phone-prefix metadata.

Lets the admin pick the tenant's default country (e.g. Burkina Faso → +226)
and curate the list of available countries. Every authenticated user can read
the current tenant prefix via GET /api/me/tenant-meta — used to drive dynamic
phone-number placeholders across the UI.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Default catalog (UEMOA + a few extras). Editable by admins via the API.
# country.code = ISO-2 (or 3 char ad-hoc). dial includes "+" prefix.
DEFAULT_COUNTRIES = [
    {"code": "BF", "name": "Burkina Faso", "dial": "+226", "example": "+22670000000"},
    {"code": "CI", "name": "Côte d'Ivoire", "dial": "+225", "example": "+22507000000"},
    {"code": "SN", "name": "Sénégal", "dial": "+221", "example": "+221770000000"},
    {"code": "ML", "name": "Mali", "dial": "+223", "example": "+22370000000"},
    {"code": "NE", "name": "Niger", "dial": "+227", "example": "+22790000000"},
    {"code": "TG", "name": "Togo", "dial": "+228", "example": "+22890000000"},
    {"code": "BJ", "name": "Bénin", "dial": "+229", "example": "+22990000000"},
    {"code": "GN", "name": "Guinée", "dial": "+224", "example": "+22462000000"},
    {"code": "FR", "name": "France", "dial": "+33", "example": "+33612345678"},
    {"code": "CM", "name": "Cameroun", "dial": "+237", "example": "+237670000000"},
]

DEFAULT_TENANT_COUNTRY_CODE = "BF"


class CountryPayload(BaseModel):
    code: str = Field(..., min_length=2, max_length=4)
    name: str = Field(..., min_length=1, max_length=80)
    dial: str = Field(..., pattern=r"^\+\d{1,4}$")
    example: Optional[str] = Field(None, max_length=40)


class TenantCountrySelect(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=4)


def make_router(*, db, get_current_user, get_current_admin):
    router = APIRouter(tags=["Tenant Meta"])

    async def _ensure_seeded() -> None:
        n = await db.country_catalog.count_documents({})
        if n > 0:
            return
        docs = []
        for c in DEFAULT_COUNTRIES:
            docs.append({
                "id": str(uuid.uuid4()),
                "code": c["code"].upper(),
                "name": c["name"],
                "dial": c["dial"],
                "example": c.get("example") or f"{c['dial']}00000000",
                "created_at": _now_iso(),
            })
        await db.country_catalog.insert_many(docs)

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

    async def _tenant_meta_doc(tenant_id: str) -> dict:
        await _ensure_seeded()
        doc = await db.tenant_country.find_one({"tenant_id": tenant_id}, {"_id": 0})
        return doc or {}

    async def _build_meta(user: dict) -> dict:
        tid = await _resolve_tenant_id(user)
        meta = await _tenant_meta_doc(tid)
        code = (meta.get("country_code") or DEFAULT_TENANT_COUNTRY_CODE).upper()
        country = await db.country_catalog.find_one({"code": code}, {"_id": 0})
        if not country:
            # Fallback if admin deleted the selected country
            country = await db.country_catalog.find_one(
                {"code": DEFAULT_TENANT_COUNTRY_CODE}, {"_id": 0}
            )
        return {
            "country_code": (country or {}).get("code") or DEFAULT_TENANT_COUNTRY_CODE,
            "country_name": (country or {}).get("name") or "Burkina Faso",
            "dial_prefix": (country or {}).get("dial") or "+226",
            "phone_example": (country or {}).get("example") or "+22670000000",
        }

    # ----------------------------------------------------------------
    # Public for any authenticated user (used by frontend placeholders)
    # ----------------------------------------------------------------
    @router.get("/me/tenant-meta")
    async def me_tenant_meta(user: dict = Depends(get_current_user)):
        return await _build_meta(user)

    # ----------------------------------------------------------------
    # Country catalog CRUD (admin)
    # ----------------------------------------------------------------
    @router.get("/admin/countries")
    async def list_countries(_: dict = Depends(get_current_admin)):
        await _ensure_seeded()
        cursor = db.country_catalog.find({}, {"_id": 0}).sort("name", 1)
        return [c async for c in cursor]

    @router.post("/admin/countries")
    async def add_country(payload: CountryPayload, _: dict = Depends(get_current_admin)):
        code = payload.code.upper()
        existing = await db.country_catalog.find_one({"code": code})
        if existing:
            raise HTTPException(status_code=409, detail="Code pays déjà présent")
        doc = {
            "id": str(uuid.uuid4()),
            "code": code,
            "name": payload.name,
            "dial": payload.dial,
            "example": payload.example or f"{payload.dial}00000000",
            "created_at": _now_iso(),
        }
        await db.country_catalog.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.patch("/admin/countries/{code}")
    async def update_country(
        code: str, payload: CountryPayload, _: dict = Depends(get_current_admin)
    ):
        code = code.upper()
        existing = await db.country_catalog.find_one({"code": code})
        if not existing:
            raise HTTPException(status_code=404, detail="Pays introuvable")
        await db.country_catalog.update_one(
            {"code": code},
            {"$set": {
                "name": payload.name,
                "dial": payload.dial,
                "example": payload.example or f"{payload.dial}00000000",
                "updated_at": _now_iso(),
            }},
        )
        return await db.country_catalog.find_one({"code": code}, {"_id": 0})

    @router.delete("/admin/countries/{code}")
    async def delete_country(code: str, _: dict = Depends(get_current_admin)):
        code = code.upper()
        if code == DEFAULT_TENANT_COUNTRY_CODE:
            # Keep default for safety
            raise HTTPException(status_code=400, detail="Le pays par défaut ne peut pas être supprimé")
        res = await db.country_catalog.delete_one({"code": code})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Pays introuvable")
        return {"ok": True}

    # ----------------------------------------------------------------
    # Tenant country selection (admin)
    # ----------------------------------------------------------------
    @router.get("/admin/tenant-country")
    async def get_tenant_country(user: dict = Depends(get_current_admin)):
        return await _build_meta(user)

    @router.patch("/admin/tenant-country")
    async def set_tenant_country(
        payload: TenantCountrySelect, user: dict = Depends(get_current_admin)
    ):
        code = payload.country_code.upper()
        country = await db.country_catalog.find_one({"code": code})
        if not country:
            raise HTTPException(status_code=404, detail="Code pays inconnu")
        tid = await _resolve_tenant_id(user)
        await db.tenant_country.update_one(
            {"tenant_id": tid},
            {"$set": {
                "tenant_id": tid,
                "country_code": code,
                "updated_at": _now_iso(),
                "updated_by": user.get("id"),
            }},
            upsert=True,
        )
        return await _build_meta(user)

    return router


__all__ = ["make_router", "DEFAULT_COUNTRIES", "DEFAULT_TENANT_COUNTRY_CODE"]
