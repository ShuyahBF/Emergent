"""Iter38r-fix8 — Emergent Object Storage helper for SAWALI SMART SYSTEMS.

Persistent storage for files that must survive deployments:
  - AI-generated images (Gemini Nano Banana)
  - AI-generated videos (Sora 2)
  - Media library uploads
  - WhatsApp attachments (inbound + outbound)
  - User avatars + profile photos

Pattern :
  put_object(path, bytes, content_type) → {"path": "...", "size": ..., "etag": "..."}
  get_object(path)                       → (bytes, content_type)

Paths are prefixed with `sawali/` so we never collide with other apps in the
shared bucket. We also include a tenant prefix (`sawali/{client_id}/...`) so
admins of a tenant can never accidentally read files from another tenant.

DB pattern : every uploaded object is logged in `stored_objects` so we can
soft-delete and list (the storage API has no delete/list endpoints).
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger("sawali.object_storage")

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_PREFIX = "sawali"

_storage_key: Optional[str] = None
_storage_init_failed_at: Optional[float] = None
_INIT_LOCK = asyncio.Lock()


# ============================================================
# Init (idempotent, retried lazily)
# ============================================================
def _init_storage_sync() -> Optional[str]:
    """Returns a session-scoped storage_key, or None when storage is not
    reachable (e.g., the EMERGENT_LLM_KEY is missing). Callers handle None
    by falling back to local-disk persistence."""
    global _storage_key, _storage_init_failed_at
    if _storage_key:
        return _storage_key
    api_key = (os.environ.get("EMERGENT_LLM_KEY") or "").strip()
    if not api_key:
        logger.warning("[object_storage] EMERGENT_LLM_KEY missing — storage disabled")
        return None
    try:
        resp = requests.post(
            f"{STORAGE_URL}/init",
            json={"emergent_key": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        _storage_key = resp.json().get("storage_key")
        if _storage_key:
            logger.info("[object_storage] initialized successfully")
        return _storage_key
    except Exception as exc:
        logger.warning("[object_storage] init failed (%s) — fallback to local disk", exc)
        _storage_init_failed_at = datetime.now(timezone.utc).timestamp()
        return None


async def init_storage() -> Optional[str]:
    """Async wrapper around the sync init (network call)."""
    if _storage_key:
        return _storage_key
    async with _INIT_LOCK:
        return await asyncio.to_thread(_init_storage_sync)


def is_enabled() -> bool:
    """Quick check that doesn't trigger a network call."""
    return _storage_key is not None


# ============================================================
# Put / Get
# ============================================================
def _put_sync(path: str, data: bytes, content_type: str) -> Dict[str, Any]:
    key = _init_storage_sync()
    if not key:
        raise RuntimeError("Object Storage non initialisé (EMERGENT_LLM_KEY manquant ?).")
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data,
        timeout=120,
    )
    # 409 = path already exists; treat as success and just return the path
    if resp.status_code == 409:
        return {"path": path, "size": len(data), "etag": "exists"}
    resp.raise_for_status()
    out = resp.json()
    out.setdefault("path", path)
    out.setdefault("size", len(data))
    return out


def _get_sync(path: str) -> Tuple[bytes, str]:
    key = _init_storage_sync()
    if not key:
        raise RuntimeError("Object Storage non initialisé.")
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


async def put_object(path: str, data: bytes, content_type: str) -> Dict[str, Any]:
    """Upload bytes to a remote path. Path MUST NOT start with '/'.
    Returns a dict with `path` / `size` / `etag` keys.
    """
    return await asyncio.to_thread(_put_sync, path, data, content_type)


async def get_object(path: str) -> Tuple[bytes, str]:
    """Download bytes from a remote path. Returns (bytes, content_type)."""
    return await asyncio.to_thread(_get_sync, path)


# ============================================================
# Path helpers
# ============================================================
MIME_FROM_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
    "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
    "pdf": "application/pdf", "json": "application/json",
    "csv": "text/csv", "txt": "text/plain",
}


def guess_content_type(filename_or_ext: str, fallback: str = "application/octet-stream") -> str:
    s = (filename_or_ext or "").strip().lower()
    if "." in s:
        s = s.rsplit(".", 1)[-1]
    return MIME_FROM_EXT.get(s, fallback)


def build_path(kind: str, tenant_id: str, ext: str = "bin", filename_hint: Optional[str] = None) -> str:
    """Builds a collision-proof path :
        sawali/{tenant_id}/{kind}/{YYYY-MM}/{uuid}.{ext}
    `kind` is the bucket : ai_media | media_library | wa_attachments | avatars | misc.
    """
    safe_tenant = (tenant_id or "_global").replace("/", "_")
    safe_kind = (kind or "misc").replace("/", "_")
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    ext = (ext or "bin").lstrip(".").lower() or "bin"
    uid = uuid.uuid4().hex[:16]
    return f"{APP_PREFIX}/{safe_tenant}/{safe_kind}/{ym}/{uid}.{ext}"


# ============================================================
# DB-backed save (logs the object so we can list/soft-delete)
# ============================================================
async def save_and_log(
    db,
    *,
    data: bytes,
    kind: str,
    tenant_id: str,
    ext: str,
    content_type: Optional[str] = None,
    original_filename: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Uploads `data` and logs the reference in `stored_objects`.

    Renvoie :
      {
        "path": <remote path>,
        "url":  <proxy URL the frontend can use: /api/files/{path}>,
        "size": int,
        "content_type": str,
        "id":   <stored_objects id>,
      }
    """
    ct = content_type or guess_content_type(original_filename or ext)
    path = build_path(kind, tenant_id, ext, original_filename)
    result = await put_object(path, data, ct)
    rec_id = secrets.token_urlsafe(12)
    doc = {
        "id": rec_id,
        "storage_path": result["path"],
        "kind": kind,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "original_filename": original_filename,
        "content_type": ct,
        "size": result.get("size") or len(data),
        "etag": result.get("etag"),
        "metadata": metadata or {},
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.stored_objects.insert_one(doc.copy())
    except Exception:
        logger.exception("[object_storage] DB log failed (object uploaded anyway)")
    return {
        "id": rec_id,
        "path": result["path"],
        "url": f"/api/files/{result['path']}",
        "size": doc["size"],
        "content_type": ct,
    }


async def soft_delete(db, storage_path: str) -> bool:
    """Mark the file as deleted in DB (storage has no delete API)."""
    res = await db.stored_objects.update_one(
        {"storage_path": storage_path},
        {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat()}},
    )
    return bool(res.modified_count)
