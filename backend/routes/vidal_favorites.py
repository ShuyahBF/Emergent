"""Iter43-fix24at (2026-02-26) — VIDAL Favorites per user.

Allows each authenticated user to bookmark VIDAL products from the search /
catalog / Atom feed viewers, and to consult them again in a dedicated
"Favoris" tab on `/portal/vidal`.

Stored in Mongo collection `vidal_favorites` :
  - `user_id`     (str)   — owner
  - `vidal_id`    (str)   — VIDAL numeric code (e.g. "5485")
  - `title`       (str)   — drug name (e.g. "DOLIPRANE 500 mg, comprimé")
  - `type`        (str)   — VIDAL resource type (e.g. "product")
  - `summary`     (str)   — short description (truncated to 400 chars)
  - `created_at`  (datetime UTC)

Unique compound index `(user_id, vidal_id)` to dedupe quietly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Path
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.vidal.favorites")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FavoritePayload(BaseModel):
    vidal_id: str = Field(..., description="VIDAL numeric code (digits)", min_length=1, max_length=32)
    title: str = Field("", max_length=400)
    type: str = Field("", max_length=64)
    summary: str = Field("", max_length=800)


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Mongo doc → JSON-safe payload (no ObjectId, ISO timestamps)."""
    if not doc:
        return {}
    out = {
        "vidal_id": doc.get("vidal_id", ""),
        "title": doc.get("title", ""),
        "type": doc.get("type", ""),
        "summary": doc.get("summary", ""),
    }
    created = doc.get("created_at")
    if isinstance(created, datetime):
        out["created_at"] = created.astimezone(timezone.utc).isoformat()
    else:
        out["created_at"] = str(created) if created else _now_iso()
    return out


def attach_vidal_favorites_routes(*, api, db, get_current_user):
    """Mount the favorites endpoints under `/api/vidal/favorites*`."""

    @api.get("/vidal/favorites", tags=["VIDAL"])
    async def list_favorites(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        """List the current user's favorite VIDAL products (most recent first)."""
        cursor = db.vidal_favorites.find({"user_id": user["id"]}).sort("created_at", -1).limit(500)
        items: List[Dict[str, Any]] = []
        async for doc in cursor:
            items.append(_serialize(doc))
        return {"items": items, "count": len(items)}

    @api.post("/vidal/favorites", tags=["VIDAL"])
    async def add_favorite(
        payload: FavoritePayload = Body(...),
        user: dict = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Add (or refresh) a favorite. Idempotent on `(user_id, vidal_id)`."""
        vidal_id = (payload.vidal_id or "").strip()
        if not vidal_id:
            raise HTTPException(status_code=400, detail="vidal_id requis")
        # We accept any alphanumeric code, not only digits, to stay forward-compatible
        # with non-numeric VIDAL identifiers if VIDAL ever introduces them.
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user["id"],
            "vidal_id": vidal_id,
            "title": (payload.title or "").strip()[:400],
            "type": (payload.type or "").strip()[:64],
            "summary": (payload.summary or "").strip()[:800],
            "created_at": now,
        }
        await db.vidal_favorites.update_one(
            {"user_id": user["id"], "vidal_id": vidal_id},
            {"$set": doc},
            upsert=True,
        )
        return {"ok": True, "favorite": _serialize(doc)}

    @api.delete("/vidal/favorites/{vidal_id}", tags=["VIDAL"])
    async def delete_favorite(
        vidal_id: str = Path(..., min_length=1, max_length=32),
        user: dict = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Remove a favorite. Returns `{ok, deleted}`."""
        r = await db.vidal_favorites.delete_one({"user_id": user["id"], "vidal_id": vidal_id})
        return {"ok": True, "deleted": int(r.deleted_count or 0)}

    # Best-effort index — keeps lookups fast and prevents duplicates.
    async def _ensure_index() -> None:
        try:
            await db.vidal_favorites.create_index(
                [("user_id", 1), ("vidal_id", 1)],
                unique=True,
                name="vidal_favorites_user_id_unique",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[vidal.favorites] index create skipped: %s", exc)

    try:
        import asyncio
        asyncio.get_event_loop().create_task(_ensure_index())
    except Exception:  # noqa: BLE001
        pass

    logger.info("[vidal.favorites] routes mounted under /api/vidal/favorites*")
