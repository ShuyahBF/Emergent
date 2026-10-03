"""Iter38r-fix8 — Stockage objet de SAWALI (lot 53 : Cloudflare R2, plus Emergent).

Persistent storage for files that must survive deployments:
  - AI-generated images / videos
  - Media library uploads
  - WhatsApp attachments (inbound + outbound)
  - User avatars + profile photos, pièces OCR

Pattern (inchangé) :
  put_object(path, bytes, content_type) → {"path": "...", "size": ..., "etag": "..."}
  get_object(path)                       → (bytes, content_type)

Lot 53 : les octets vont dans Cloudflare R2 via `storage.py` (même convention de
clés que l'outil « Migration vers Render » : « <R2_FICHIERS_PREFIXE>/objets/<path> »),
avec repli de lecture chez Emergent tant qu'EMERGENT_LLM_KEY est définie.

Paths are prefixed with `sawali/` so we never collide with other apps in the
shared bucket. We also include a tenant prefix (`sawali/{client_id}/...`).

DB pattern : every uploaded object is logged in `stored_objects` so we can
soft-delete and list.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import storage as _stockage

logger = logging.getLogger("sawali.object_storage")

APP_PREFIX = "sawali"


# ============================================================
# Init (aucun appel réseau)
# ============================================================
async def init_storage() -> Optional[str]:
    """Renvoie une valeur vraie si le stockage R2 est configuré, sinon None
    (les appelants se replient alors sur le disque local)."""
    return "r2" if _stockage.storage_available() else None


def is_enabled() -> bool:
    """Quick check that doesn't trigger a network call."""
    return _stockage.storage_available()


# ============================================================
# Put / Get
# ============================================================
def _put_sync(path: str, data: bytes, content_type: str) -> Dict[str, Any]:
    if not _stockage.storage_available():
        raise RuntimeError("Stockage R2 non configuré (R2_FICHIERS_BUCKET et identifiants R2).")
    # Chemin gardé tel quel (déjà « sawali/... ») : même clé que la migration
    chemin = _stockage.upload_bytes(path, data, content_type, normaliser=False)
    return {"path": chemin, "size": len(data), "etag": None}


def _get_sync(path: str) -> Tuple[bytes, str]:
    return _stockage.fetch_bytes(path)


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
    """Marque le fichier supprimé en base (l'objet reste dans R2, comme avant chez Emergent)."""
    res = await db.stored_objects.update_one(
        {"storage_path": storage_path},
        {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat()}},
    )
    return bool(res.modified_count)
