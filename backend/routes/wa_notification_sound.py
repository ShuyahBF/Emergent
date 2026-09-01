"""WhatsApp inbound notification sound — admin config & MP3 upload.

Endpoints:
  GET  /api/notification-sounds/presets                 — public list of preset keys
  POST /api/admin/notification-sounds/upload            — admin uploads a custom MP3
  GET  /api/admin/notification-sounds/config            — admin reads current tenant config
  PUT  /api/admin/notification-sounds/config            — admin updates preset/volume/url

The tenant-wide config lives on the `settings` doc (`_id="global"`) with keys:
  - `wa_notification_sound`       : "bip"|"ding"|"chime"|"alert"|"subtle"|"custom"
  - `wa_notification_sound_url`   : URL to uploaded MP3 when preset == "custom"
  - `wa_notification_volume`      : float 0.0-1.0

User-level overrides are stored client-side (localStorage) — no backend state required.
"""
from __future__ import annotations

import logging
import mimetypes
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.notification_sound")

VALID_PRESETS = ("bip", "ding", "chime", "alert", "subtle", "custom")
ALLOWED_MIMES = ("audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "audio/webm")
ALLOWED_EXTS = (".mp3", ".wav", ".ogg", ".webm", ".m4a")
MAX_UPLOAD_BYTES = 500 * 1024  # 500 KB — notification sounds should be short


class NotificationSoundConfig(BaseModel):
    preset: Optional[str] = Field(default=None, description="Preset key or 'custom'")
    url: Optional[str] = None
    volume: Optional[float] = Field(default=None, ge=0.0, le=1.0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def attach_notification_sound_routes(*, api, db, get_current_admin, upload_dir: Path):
    """Mount the notification-sound routes onto the /api router."""

    @api.get("/notification-sounds/presets", tags=["Public"])
    async def list_presets():
        """Public list of available preset keys (labels/descriptions live in
        the frontend so we keep i18n on that side)."""
        return {
            "presets": [
                {"key": "bip"},
                {"key": "ding"},
                {"key": "chime"},
                {"key": "alert"},
                {"key": "subtle"},
            ],
            "custom_supported": True,
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "allowed_extensions": list(ALLOWED_EXTS),
        }

    @api.get("/admin/notification-sounds/config", tags=["Admin"])
    async def admin_get_config(_: dict = Depends(get_current_admin)):
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        return {
            "preset": s.get("wa_notification_sound") or "bip",
            "url": s.get("wa_notification_sound_url") or None,
            "volume": (
                float(s["wa_notification_volume"])
                if isinstance(s.get("wa_notification_volume"), (int, float))
                else 0.4
            ),
        }

    @api.put("/admin/notification-sounds/config", tags=["Admin"])
    async def admin_update_config(
        payload: NotificationSoundConfig = Body(...),
        _: dict = Depends(get_current_admin),
    ):
        update: dict = {}
        if payload.preset is not None:
            preset = (payload.preset or "").strip().lower()
            if preset not in VALID_PRESETS:
                raise HTTPException(
                    status_code=400,
                    detail=f"preset doit être l'un de {list(VALID_PRESETS)}",
                )
            update["wa_notification_sound"] = preset
        if payload.url is not None:
            update["wa_notification_sound_url"] = (payload.url or "").strip() or None
        if payload.volume is not None:
            update["wa_notification_volume"] = float(payload.volume)
        if not update:
            return {"ok": True, "unchanged": True}
        update["updated_at"] = _now()
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    @api.post("/admin/notification-sounds/upload", tags=["Admin"])
    async def admin_upload_sound(
        request: Request,
        file: UploadFile = File(...),
        user: dict = Depends(get_current_admin),
    ):
        # Validate extension + mime
        original_name = file.filename or "sound"
        ext = Path(original_name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"Extension non autorisée. Autorisées : {', '.join(ALLOWED_EXTS)}",
            )
        content_type = file.content_type or mimetypes.guess_type(original_name)[0] or ""
        if content_type and not content_type.startswith("audio/"):
            raise HTTPException(status_code=400, detail=f"Type MIME non audio : {content_type}")

        # 2026-02 fork iter108 — Deploy-safe : read then persist via helper (storage + local).
        file_id = uuid.uuid4().hex
        safe_name = f"wa-notif-{file_id}{ext}"
        raw = await file.read()
        size = len(raw)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Fichier trop volumineux (>{MAX_UPLOAD_BYTES // 1024} KB)",
            )
        from storage import save_upload_and_cache
        target, storage_path, storage_error = save_upload_and_cache(
            upload_dir=upload_dir, filename=safe_name, data=raw,
            content_type=content_type or "audio/mpeg",
        )
        if storage_error:
            logger.warning("[notif_sound_upload] storage mirror failed: %s", storage_error)

        # Register the file so it is served via /api/files/{file_id}
        file_doc = {
            "id": file_id,
            "filename": original_name,
            "stored_name": safe_name,
            "extension": ext.lstrip("."),
            "content_type": content_type or "audio/mpeg",
            "size": size,
            "url": f"/api/files/{file_id}",
            "uploaded_at": _now(),
            "uploaded_by_id": user.get("id"),
            "uploaded_by_email": user.get("email"),
            "storage_path": storage_path,
            "storage_error": storage_error,
            "purpose": "wa_notification_sound",
        }
        await db.files.insert_one(file_doc.copy())
        file_doc.pop("_id", None)

        # Auto-select "custom" preset + save the URL in the tenant settings
        public_url = f"/api/files/{file_id}"
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "wa_notification_sound": "custom",
                "wa_notification_sound_url": public_url,
                "updated_at": _now(),
            }},
            upsert=True,
        )
        return {"ok": True, "file_id": file_id, "url": public_url, "size": size}


__all__ = ["attach_notification_sound_routes"]
