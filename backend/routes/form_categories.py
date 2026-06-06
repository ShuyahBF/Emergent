"""Iter40 (2026-02) — Form categories (max 6 per tenant) with a default tab.

Allows organizing forms by category (Client, Suivi Logiciel, Maintenances,
Questionnaires, etc.) with up to 6 tabs. When a tenant opens the forms
page, the tab marked `is_default = True` is selected by default.

Model :
  form_categories : {
    id, client_id, name, color?, is_default,
    sort_order, created_at, updated_at, created_by,
  }

The `forms` collection gains an optional `category_id` field. Forms with
no category appear under a virtual « Sans catégorie » tab on the UI side
(no special handling needed in the API).

Endpoints :
  GET    /me/form-categories
  POST   /me/form-categories
  PUT    /me/form-categories/{cid}
  DELETE /me/form-categories/{cid}
  POST   /me/form-categories/{cid}/set-default     — exclusive default flag
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.form_categories")

MAX_CATEGORIES = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_scope(user: dict) -> str:
    return user.get("parent_client_id") or user.get("client_id") or user["id"]


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    color: Optional[str] = Field(default=None, max_length=24)
    is_default: bool = False
    sort_order: Optional[int] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    color: Optional[str] = Field(default=None, max_length=24)
    sort_order: Optional[int] = None


def attach_form_categories_routes(*, api, db, get_current_user):
    @api.get("/me/form-categories", tags=["Formulaires"])
    async def list_categories(user: dict = Depends(get_current_user)):
        cid = _client_scope(user)
        items = await db.form_categories.find(
            {"client_id": cid},
            {"_id": 0},
        ).sort([("sort_order", 1), ("created_at", 1)]).to_list(MAX_CATEGORIES * 2)
        return items

    @api.post("/me/form-categories", status_code=201, tags=["Formulaires"])
    async def create_category(payload: CategoryCreate = Body(...), user: dict = Depends(get_current_user)):
        scope = _client_scope(user)
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Nom requis")
        # Limit to MAX_CATEGORIES per tenant
        count = await db.form_categories.count_documents({"client_id": scope})
        if count >= MAX_CATEGORIES:
            raise HTTPException(
                status_code=409,
                detail=f"Limite atteinte : maximum {MAX_CATEGORIES} catégories par espace.",
            )
        # Uniqueness on name (case-insensitive)
        existing = await db.form_categories.find_one(
            {"client_id": scope, "name": {"$regex": f"^\\s*{name}\\s*$", "$options": "i"}},
            {"_id": 0, "id": 1},
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"La catégorie « {name} » existe déjà.")
        # If is_default → reset others first
        if payload.is_default:
            await db.form_categories.update_many(
                {"client_id": scope, "is_default": True},
                {"$set": {"is_default": False, "updated_at": _now()}},
            )
        # Auto-assign sort_order if not provided
        sort_order = payload.sort_order if payload.sort_order is not None else count
        # First category created is automatically default
        is_default = bool(payload.is_default) or count == 0
        doc = {
            "id": str(uuid.uuid4()),
            "client_id": scope,
            "name": name,
            "color": (payload.color or "").strip() or "#6366f1",
            "is_default": is_default,
            "sort_order": sort_order,
            "created_at": _now(),
            "updated_at": _now(),
            "created_by": user.get("id"),
        }
        await db.form_categories.insert_one(doc.copy())
        return doc

    @api.put("/me/form-categories/{cid}", tags=["Formulaires"])
    async def update_category(cid: str, payload: CategoryUpdate = Body(...), user: dict = Depends(get_current_user)):
        scope = _client_scope(user)
        upd: Dict[str, Any] = {"updated_at": _now()}
        if payload.name is not None:
            n = payload.name.strip()
            if not n:
                raise HTTPException(status_code=400, detail="Nom requis")
            clash = await db.form_categories.find_one(
                {"client_id": scope, "name": {"$regex": f"^\\s*{n}\\s*$", "$options": "i"}, "id": {"$ne": cid}},
                {"_id": 0, "id": 1},
            )
            if clash:
                raise HTTPException(status_code=409, detail=f"Une autre catégorie « {n} » existe déjà.")
            upd["name"] = n
        if payload.color is not None:
            upd["color"] = (payload.color or "").strip() or "#6366f1"
        if payload.sort_order is not None:
            upd["sort_order"] = int(payload.sort_order)
        res = await db.form_categories.update_one({"id": cid, "client_id": scope}, {"$set": upd})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Catégorie introuvable")
        return await db.form_categories.find_one({"id": cid}, {"_id": 0})

    @api.delete("/me/form-categories/{cid}", tags=["Formulaires"])
    async def delete_category(cid: str, user: dict = Depends(get_current_user)):
        scope = _client_scope(user)
        cat = await db.form_categories.find_one({"id": cid, "client_id": scope}, {"_id": 0})
        if not cat:
            raise HTTPException(status_code=404, detail="Catégorie introuvable")
        # Detach forms that referenced this category
        await db.forms.update_many(
            {"client_id": scope, "category_id": cid},
            {"$set": {"category_id": None, "updated_at": _now()}},
        )
        await db.form_categories.delete_one({"id": cid})
        # If this was the default, promote the next one (lowest sort_order)
        if cat.get("is_default"):
            next_cat = await db.form_categories.find_one(
                {"client_id": scope},
                sort=[("sort_order", 1), ("created_at", 1)],
            )
            if next_cat:
                await db.form_categories.update_one(
                    {"id": next_cat["id"]},
                    {"$set": {"is_default": True, "updated_at": _now()}},
                )
        return {"ok": True}

    @api.post("/me/form-categories/{cid}/set-default", tags=["Formulaires"])
    async def set_default_category(cid: str, user: dict = Depends(get_current_user)):
        scope = _client_scope(user)
        cat = await db.form_categories.find_one({"id": cid, "client_id": scope})
        if not cat:
            raise HTTPException(status_code=404, detail="Catégorie introuvable")
        await db.form_categories.update_many(
            {"client_id": scope, "is_default": True},
            {"$set": {"is_default": False, "updated_at": _now()}},
        )
        await db.form_categories.update_one(
            {"id": cid},
            {"$set": {"is_default": True, "updated_at": _now()}},
        )
        return {"ok": True}


__all__ = ["attach_form_categories_routes", "MAX_CATEGORIES"]
