"""Iter41 Phase 5 (2026-02) — Officines : secrets par officine + page admin
des inventaires + doc API publique.

Architecture :
  - Nouvelle collection `officines_secrets` : un secret HMAC distinct par
    officine, créé via `POST /api/admin/officines/secrets`. Le secret n'est
    montré qu'UNE seule fois à la création (toast côté UI).
  - `/api/public/officines/register` accepte maintenant 2 modes :
       a. Secret global (`settings.global.officines_register_hmac_secret`)
          — fallback rétrocompatibilité
       b. Secret per-officine — résolu via `officines_secrets.officine_id`
  - Nouvelle route admin `GET /api/admin/officines/inventory` pour lister
    les inventaires reçus, avec export CSV via `?format=csv`.
"""
from __future__ import annotations

import csv
import io
import logging
import secrets as pysecrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("sawali.officines_admin")


class OfficineSecretCreate(BaseModel):
    officine_id: str
    label: Optional[str] = None
    contact_email: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def resolve_officine_secret(db, officine_id: str) -> Optional[str]:
    """Look up the per-officine HMAC secret first; fall back to the global
    secret if no per-officine record exists. Returns None if neither found."""
    if officine_id:
        doc = await db.officines_secrets.find_one(
            {"officine_id": officine_id, "revoked_at": None},
            {"_id": 0, "secret": 1},
        )
        if doc and doc.get("secret"):
            return doc["secret"]
    # Fallback to global
    s = await db.settings.find_one(
        {"_id": "global"},
        {"_id": 0, "officines_register_hmac_secret": 1},
    ) or {}
    return s.get("officines_register_hmac_secret") or None


def attach_officines_admin_routes(*, api, db, get_current_admin):

    # -------- Per-officine HMAC secrets --------
    @api.post("/admin/officines/secrets", tags=["Admin — Officines"])
    async def create_secret(payload: OfficineSecretCreate = Body(...), user: dict = Depends(get_current_admin)):
        """Generate a fresh HMAC secret for a specific officine. The secret
        is returned in the response body and NEVER displayed again."""
        if not payload.officine_id.strip():
            raise HTTPException(status_code=400, detail="officine_id requis")
        existing = await db.officines_secrets.find_one({"officine_id": payload.officine_id, "revoked_at": None})
        if existing:
            raise HTTPException(status_code=409, detail="Cette officine a déjà un secret actif. Révoquez-le avant d'en créer un nouveau.")
        secret = pysecrets.token_urlsafe(48)
        doc = {
            "id": pysecrets.token_urlsafe(12),
            "officine_id": payload.officine_id.strip(),
            "label": (payload.label or "").strip() or None,
            "contact_email": (payload.contact_email or "").strip() or None,
            "secret": secret,
            "created_by": user.get("id"),
            "created_at": _now(),
            "revoked_at": None,
            "revoked_by": None,
            "last_used_at": None,
        }
        await db.officines_secrets.insert_one(doc)
        doc.pop("_id", None)
        return {
            "ok": True,
            "secret": secret,
            "warning": "Ce secret ne sera plus jamais affiché — communiquez-le immédiatement à l'officine et ne le stockez pas en clair.",
            "officine_id": payload.officine_id,
        }

    @api.get("/admin/officines/secrets", tags=["Admin — Officines"])
    async def list_secrets(user: dict = Depends(get_current_admin)):
        cursor = db.officines_secrets.find(
            {},
            {"_id": 0, "secret": 0},  # NEVER return the raw secret
        ).sort("created_at", -1).limit(500)
        items = await cursor.to_list(500)
        return {"items": items, "count": len(items)}

    @api.post("/admin/officines/secrets/{secret_id}/revoke", tags=["Admin — Officines"])
    async def revoke_secret(secret_id: str, user: dict = Depends(get_current_admin)):
        r = await db.officines_secrets.update_one(
            {"id": secret_id, "revoked_at": None},
            {"$set": {"revoked_at": _now(), "revoked_by": user.get("id")}},
        )
        if r.modified_count == 0:
            raise HTTPException(status_code=404, detail="Secret introuvable ou déjà révoqué")
        return {"ok": True}

    # -------- Inventories admin list + CSV --------
    @api.get("/admin/officines/inventory", tags=["Admin — Officines"])
    async def list_inventory(
        q: Optional[str] = Query(None),
        format: str = Query("json", regex="^(json|csv)$"),
        limit: int = Query(200, ge=1, le=2000),
        user: dict = Depends(get_current_admin),
    ):
        query: Dict[str, Any] = {}
        if q:
            query["$or"] = [
                {"officine_name": {"$regex": q, "$options": "i"}},
                {"city": {"$regex": q, "$options": "i"}},
                {"officine_id": {"$regex": q, "$options": "i"}},
            ]
        cursor = db.officines_inventory.find(query, {"_id": 0}).sort("registered_at", -1).limit(limit)
        items = await cursor.to_list(limit)
        if format == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "officine_id", "officine_name", "city", "country", "phone",
                "contact_email", "inventory_count", "updates_count", "registered_at",
            ])
            for it in items:
                writer.writerow([
                    it.get("officine_id", ""),
                    it.get("officine_name", ""),
                    it.get("city", "") or "",
                    it.get("country", "") or "",
                    it.get("phone", "") or "",
                    it.get("contact_email", "") or "",
                    it.get("inventory_count", 0),
                    it.get("updates_count", 0),
                    str(it.get("registered_at", "")),
                ])
            buf.seek(0)
            return StreamingResponse(
                iter([buf.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=officines_inventory_{_now().date()}.csv"},
            )
        return {"items": items, "count": len(items)}

    @api.get("/admin/officines/inventory/{officine_id}", tags=["Admin — Officines"])
    async def inventory_detail(officine_id: str, user: dict = Depends(get_current_admin)):
        doc = await db.officines_inventory.find_one({"officine_id": officine_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Inventaire introuvable")
        return doc

    logger.info("[officines_admin] secrets + inventory routes mounted")
