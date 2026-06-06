"""Iter41 Phase 2 (2026-02) — Table AMM (Autorisation de Mise sur le Marché)
éditable par les utilisateurs disposant du rôle `regulateur` (ou admin/superviseur).

Schéma (collection `amm_numbers`) :
  id, vidal_product_id, product_name, amm_number (unique), laboratory,
  galenic_form, atc_class, status (active|withdrawn|suspended),
  granted_at, expires_at, notes, source (vidal_auto | manual),
  created_by, created_at, updated_by, updated_at, tenant_type
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("sawali.amm")

AMM_ALLOWED_ROLES = ("admin", "superviseur", "regulateur")
AMM_STATUSES = ("active", "withdrawn", "suspended")


class AmmCreatePayload(BaseModel):
    vidal_product_id: Optional[int] = None
    product_name: str
    amm_number: str
    laboratory: Optional[str] = None
    galenic_form: Optional[str] = None
    atc_class: Optional[str] = None
    status: Optional[str] = "active"
    granted_at: Optional[str] = None  # ISO date
    expires_at: Optional[str] = None
    notes: Optional[str] = None


class AmmUpdatePayload(BaseModel):
    vidal_product_id: Optional[int] = None
    product_name: Optional[str] = None
    amm_number: Optional[str] = None
    laboratory: Optional[str] = None
    galenic_form: Optional[str] = None
    atc_class: Optional[str] = None
    status: Optional[str] = None
    granted_at: Optional[str] = None
    expires_at: Optional[str] = None
    notes: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _can_write(user: Dict[str, Any]) -> bool:
    return (user.get("role") or "") in AMM_ALLOWED_ROLES


def _can_read(user: Dict[str, Any]) -> bool:
    # Tous les utilisateurs authentifiés peuvent lire la table.
    return True


def attach_amm_routes(*, api, db, get_current_user):
    """Mount AMM CRUD endpoints under /api/amm/*."""

    @api.get("/amm", tags=["AMM"])
    async def list_amm(
        q: Optional[str] = Query(None, description="Recherche par nom ou numéro AMM"),
        status: Optional[str] = Query(None, regex="^(active|withdrawn|suspended)$"),
        limit: int = Query(100, ge=1, le=500),
        user: dict = Depends(get_current_user),
    ):
        if not _can_read(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        if q:
            query["$or"] = [
                {"product_name": {"$regex": q, "$options": "i"}},
                {"amm_number": {"$regex": q, "$options": "i"}},
                {"laboratory": {"$regex": q, "$options": "i"}},
            ]
        cursor = db.amm_numbers.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        items = await cursor.to_list(limit)
        return {"items": items, "count": len(items)}

    @api.get("/amm/by-product/{vidal_product_id}", tags=["AMM"])
    async def get_amm_by_product(vidal_product_id: int, user: dict = Depends(get_current_user)):
        if not _can_read(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        doc = await db.amm_numbers.find_one(
            {"vidal_product_id": vidal_product_id},
            {"_id": 0},
        )
        if not doc:
            return {"found": False}
        return {"found": True, "amm": doc}

    @api.post("/amm", tags=["AMM"])
    async def create_amm(payload: AmmCreatePayload = Body(...), user: dict = Depends(get_current_user)):
        if not _can_write(user):
            raise HTTPException(status_code=403, detail="Réservé aux admins, superviseurs et régulateurs")
        if not payload.amm_number.strip():
            raise HTTPException(status_code=400, detail="amm_number requis")
        existing = await db.amm_numbers.find_one({"amm_number": payload.amm_number.strip()})
        if existing:
            raise HTTPException(status_code=409, detail=f"Numéro AMM {payload.amm_number} déjà enregistré")
        status = (payload.status or "active").lower()
        if status not in AMM_STATUSES:
            status = "active"
        doc = {
            "id": secrets.token_urlsafe(12),
            "vidal_product_id": payload.vidal_product_id,
            "product_name": payload.product_name.strip(),
            "amm_number": payload.amm_number.strip(),
            "laboratory": (payload.laboratory or "").strip() or None,
            "galenic_form": (payload.galenic_form or "").strip() or None,
            "atc_class": (payload.atc_class or "").strip() or None,
            "status": status,
            "granted_at": payload.granted_at,
            "expires_at": payload.expires_at,
            "notes": (payload.notes or "").strip() or None,
            "source": "manual",
            "created_by": user.get("id"),
            "created_by_email": user.get("email"),
            "created_at": _now_iso(),
            "updated_by": None,
            "updated_at": None,
        }
        await db.amm_numbers.insert_one(doc)
        doc.pop("_id", None)
        return {"ok": True, "amm": doc}

    @api.put("/amm/{amm_id}", tags=["AMM"])
    async def update_amm(amm_id: str, payload: AmmUpdatePayload = Body(...), user: dict = Depends(get_current_user)):
        if not _can_write(user):
            raise HTTPException(status_code=403, detail="Réservé aux admins, superviseurs et régulateurs")
        existing = await db.amm_numbers.find_one({"id": amm_id})
        if not existing:
            raise HTTPException(status_code=404, detail="AMM introuvable")
        update = payload.model_dump(exclude_none=True)
        if "amm_number" in update:
            update["amm_number"] = update["amm_number"].strip()
            if update["amm_number"] != existing["amm_number"]:
                dup = await db.amm_numbers.find_one({"amm_number": update["amm_number"], "id": {"$ne": amm_id}})
                if dup:
                    raise HTTPException(status_code=409, detail="Ce numéro AMM existe déjà")
        if "status" in update:
            s = update["status"].lower()
            if s not in AMM_STATUSES:
                raise HTTPException(status_code=400, detail=f"status doit être un de {AMM_STATUSES}")
            update["status"] = s
        update["updated_by"] = user.get("id")
        update["updated_by_email"] = user.get("email")
        update["updated_at"] = _now_iso()
        await db.amm_numbers.update_one({"id": amm_id}, {"$set": update})
        merged = {**existing, **update}
        merged.pop("_id", None)
        return {"ok": True, "amm": merged}

    @api.delete("/amm/{amm_id}", tags=["AMM"])
    async def delete_amm(amm_id: str, user: dict = Depends(get_current_user)):
        if not _can_write(user):
            raise HTTPException(status_code=403, detail="Réservé aux admins, superviseurs et régulateurs")
        r = await db.amm_numbers.delete_one({"id": amm_id})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="AMM introuvable")
        return {"ok": True}

    logger.info("[amm] routes mounted under /api/amm/*")


async def lookup_amm_for_product(db, vidal_product_id: Optional[int], product_name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Helper used by the VIDAL fiche endpoint and WhatsApp `!vidal fiche/amm`
    commands to enrich the response with the locally-edited AMM record.
    """
    if vidal_product_id:
        doc = await db.amm_numbers.find_one({"vidal_product_id": vidal_product_id}, {"_id": 0})
        if doc:
            return doc
    if product_name:
        doc = await db.amm_numbers.find_one(
            {"product_name": {"$regex": f"^{product_name.strip()}$", "$options": "i"}},
            {"_id": 0},
        )
        if doc:
            return doc
    return None
