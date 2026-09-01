"""2026-02 fork (P0) — Tenant KYC + per-tenant Smart Communications.

Endpoints mounted under /api :

  GET  /me/kyc                          — read the caller tenant's KYC record
  PUT  /me/kyc                          — update text fields (IFU, RCCM, address…)
  POST /me/kyc/upload/{doc_type}        — upload id_photo | id_card | letterhead
                                          (PDF/JPG/PNG, max 3 MB)
  GET  /admin/kyc/{tenant_id}           — super-admin read of any tenant's KYC

  GET  /me/smart-communications         — read the caller tenant's WA/Meta/Insta/X/
                                          TikTok/LinkedIn config
  PUT  /me/smart-communications         — update it

Design:
  - The tenant_id used is `user.parent_client_id or user.client_id or user.id`
    (matches the resolution used by walk-ins, wa_reply_tokens, etc.).
  - KYC & Smart-Comm docs live in dedicated collections keyed by `tenant_id`.
  - Only the caller tenant can read/write their own; super-admin can read any.
  - Uploads are mirrored best-effort to Emergent Object Storage (playbook
    verified) and always saved locally so `/api/files/{file_id}` serves them.
"""
from __future__ import annotations

import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.tenant_kyc")

MAX_UPLOAD_BYTES = 3 * 1024 * 1024  # 3 MB
ALLOWED_EXTS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")
DOC_TYPES = ("id_photo", "id_card", "letterhead")


class KycUpdatePayload(BaseModel):
    business_name: Optional[str] = Field(None, max_length=200)
    ifu: Optional[str] = Field(None, max_length=40)
    rccm: Optional[str] = Field(None, max_length=60)
    address: Optional[str] = Field(None, max_length=400)
    phone: Optional[str] = Field(None, max_length=32)
    bank_details: Optional[str] = Field(None, max_length=600)


class SmartCommUpdatePayload(BaseModel):
    """All fields optional — tenant can partially fill.
    Q3=b : this configuration is a strict OVERRIDE. If empty, the tenant has NO
    outbound communications (no fallback on the global admin settings)."""
    wa_waba_id: Optional[str] = None
    wa_phone_number_id: Optional[str] = None
    wa_access_token: Optional[str] = None
    wa_verify_token: Optional[str] = None
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None
    meta_page_id: Optional[str] = None
    meta_page_access_token: Optional[str] = None
    instagram_business_id: Optional[str] = None
    instagram_access_token: Optional[str] = None
    x_api_key: Optional[str] = None
    x_api_secret: Optional[str] = None
    x_access_token: Optional[str] = None
    x_access_secret: Optional[str] = None
    tiktok_client_id: Optional[str] = None
    tiktok_client_secret: Optional[str] = None
    tiktok_access_token: Optional[str] = None
    linkedin_client_id: Optional[str] = None
    linkedin_client_secret: Optional[str] = None
    linkedin_access_token: Optional[str] = None
    linkedin_organization_id: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tenant_id_for_user(u: dict) -> str:
    return u.get("parent_client_id") or u.get("client_id") or u["id"]


# List of Smart-Comm secret fields (never returned in cleartext to non-admin readers)
SMART_COMM_SECRET_FIELDS = {
    "wa_access_token", "wa_verify_token",
    "meta_app_secret", "meta_page_access_token",
    "instagram_access_token",
    "x_api_secret", "x_access_secret",
    "tiktok_client_secret", "tiktok_access_token",
    "linkedin_client_secret", "linkedin_access_token",
}


def _mask(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    if len(v) <= 6:
        return "•" * len(v)
    return v[:2] + "•" * (len(v) - 6) + v[-4:]


def attach_tenant_kyc_routes(*, api, db, get_current_user, get_current_admin, upload_dir: Path, is_super_admin=None, super_admin_email: Optional[str] = None):
    """Mount all /me/kyc, /admin/kyc, /me/smart-communications routes.

    Args:
      is_super_admin: optional callable(user) -> bool. Used to gate
        /admin/kyc/{tenant_id}. If None, we fall back to comparing user.email
        against `super_admin_email`.
    """

    def _is_tenant_manager(u: dict) -> bool:
        """Whoever is allowed to read/write the tenant's KYC + Smart-Comm.
        Q2 : le tenant lui-même (role admin/superviseur) — les tracked users
        regular ne peuvent PAS lire ni écrire cette fiche sensible.
        Les tracked users avec `tracked_role='Superviseur'` ou 'Administrateur'
        sont aussi considérés gestionnaires du tenant (héritage du rôle).
        Comparaison casse-insensible pour éviter les surprises stockage.
        """
        role = (u.get("role") or "").lower()
        if role in ("admin", "superviseur"):
            return True
        tr = (u.get("tracked_role") or "").strip().lower()
        return tr in {"superviseur", "administrateur"}

    def _is_super_admin_user(u: dict) -> bool:
        if is_super_admin is not None:
            try:
                return bool(is_super_admin(u))
            except Exception:  # noqa: BLE001
                return False
        if super_admin_email:
            return (u.get("email") or "").lower() == super_admin_email.lower()
        return False

    # ============================ KYC ============================

    @api.get("/me/kyc", tags=["Portail Client"])
    async def me_get_kyc(user: dict = Depends(get_current_user)):
        if not _is_tenant_manager(user):
            raise HTTPException(status_code=403, detail="Réservé au gestionnaire du tenant (admin/superviseur)")
        tid = _tenant_id_for_user(user)
        doc = await db.tenant_kyc.find_one({"tenant_id": tid}, {"_id": 0}) or {"tenant_id": tid}
        return doc

    @api.put("/me/kyc", tags=["Portail Client"])
    async def me_put_kyc(
        payload: KycUpdatePayload = Body(...),
        user: dict = Depends(get_current_user),
    ):
        if not _is_tenant_manager(user):
            raise HTTPException(status_code=403, detail="Réservé au gestionnaire du tenant (admin/superviseur)")
        tid = _tenant_id_for_user(user)
        update = {k: (v.strip() if isinstance(v, str) else v)
                  for k, v in payload.model_dump(exclude_none=True).items()}
        if not update:
            return {"ok": True, "unchanged": True}
        update["updated_at"] = _now()
        update["updated_by_id"] = user.get("id")
        await db.tenant_kyc.update_one(
            {"tenant_id": tid},
            {"$set": update, "$setOnInsert": {"tenant_id": tid, "created_at": _now()}},
            upsert=True,
        )
        return {"ok": True, "updated": list(update.keys())}

    @api.post("/me/kyc/upload/{doc_type}", tags=["Portail Client"])
    async def me_upload_kyc(
        doc_type: str,
        file: UploadFile = File(...),
        user: dict = Depends(get_current_user),
    ):
        if not _is_tenant_manager(user):
            raise HTTPException(status_code=403, detail="Réservé au gestionnaire du tenant (admin/superviseur)")
        if doc_type not in DOC_TYPES:
            raise HTTPException(status_code=400, detail=f"Type doc invalide (attendu : {DOC_TYPES})")
        original = file.filename or "kyc"
        ext = Path(original).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"Extension non autorisée. Autorisées : {', '.join(ALLOWED_EXTS)}",
            )
        content_type = file.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream"
        if not (content_type.startswith("image/") or content_type == "application/pdf"):
            raise HTTPException(status_code=400, detail=f"Type MIME non autorisé : {content_type}")

        # 2026-02 fork iter108 — Deploy-safe : read then persist via helper (storage + local).
        file_id = uuid.uuid4().hex
        safe_name = f"kyc-{doc_type}-{file_id}{ext}"
        raw = await file.read()
        size = len(raw)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Fichier trop volumineux (>{MAX_UPLOAD_BYTES // 1024 // 1024} MB)",
            )
        from storage import save_upload_and_cache
        target, storage_path, _err = save_upload_and_cache(
            upload_dir=upload_dir, filename=safe_name, data=raw, content_type=content_type,
        )
        if _err:
            logger.warning("[kyc_upload] storage mirror failed: %s", _err)

        file_doc = {
            "id": file_id,
            "filename": original,
            "stored_name": safe_name,
            "extension": ext.lstrip("."),
            "content_type": content_type,
            "size": size,
            "url": f"/api/files/{file_id}",
            "uploaded_at": _now(),
            "uploaded_by_id": user.get("id"),
            "uploaded_by_email": user.get("email"),
            "storage_path": storage_path,
            "purpose": f"kyc_{doc_type}",
        }
        await db.files.insert_one(file_doc.copy())
        file_doc.pop("_id", None)

        # Update the KYC record with the new URL for this doc_type
        tid = _tenant_id_for_user(user)
        field = f"{doc_type}_url"
        await db.tenant_kyc.update_one(
            {"tenant_id": tid},
            {"$set": {field: f"/api/files/{file_id}", "updated_at": _now()},
             "$setOnInsert": {"tenant_id": tid, "created_at": _now()}},
            upsert=True,
        )
        return {"ok": True, "file_id": file_id, "url": f"/api/files/{file_id}", "doc_type": doc_type, "size": size}

    @api.get("/admin/kyc/{tenant_id}", tags=["Admin"])
    async def admin_get_kyc(tenant_id: str, user: dict = Depends(get_current_admin)):
        # Q2 : seul le SUPER-ADMIN (SAWALI) peut lire la KYC d'un autre tenant.
        # get_current_admin accepte tous les admin (cross-tenant leak sinon).
        if not _is_super_admin_user(user):
            raise HTTPException(status_code=403, detail="Réservé au super-admin SAWALI")
        doc = await db.tenant_kyc.find_one({"tenant_id": tenant_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Aucune fiche KYC pour ce tenant")
        return doc

    # ================== SMART COMMUNICATIONS ==================

    @api.get("/me/smart-communications", tags=["Portail Client"])
    async def me_get_smart_comm(user: dict = Depends(get_current_user)):
        """Return the caller tenant's smart-communications config with SECRETS
        MASKED (last 4 chars). Use PUT to overwrite full secrets."""
        if not _is_tenant_manager(user):
            raise HTTPException(status_code=403, detail="Réservé au gestionnaire du tenant (admin/superviseur)")
        tid = _tenant_id_for_user(user)
        doc = await db.tenant_smart_comm.find_one({"tenant_id": tid}, {"_id": 0}) or {"tenant_id": tid}
        # Mask secret fields
        masked = dict(doc)
        for field in SMART_COMM_SECRET_FIELDS:
            if field in masked and masked[field]:
                masked[f"{field}_masked"] = _mask(masked[field])
                masked[field] = ""  # never return cleartext secret
        return masked

    @api.put("/me/smart-communications", tags=["Portail Client"])
    async def me_put_smart_comm(
        payload: SmartCommUpdatePayload = Body(...),
        user: dict = Depends(get_current_user),
    ):
        if not _is_tenant_manager(user):
            raise HTTPException(status_code=403, detail="Réservé au gestionnaire du tenant (admin/superviseur)")
        tid = _tenant_id_for_user(user)
        # Only apply non-None fields — empty string means "clear this field"
        update = {}
        for k, v in payload.model_dump(exclude_unset=True).items():
            if v is None:
                continue
            update[k] = v.strip() if isinstance(v, str) else v
        if not update:
            return {"ok": True, "unchanged": True}
        update["updated_at"] = _now()
        update["updated_by_id"] = user.get("id")
        await db.tenant_smart_comm.update_one(
            {"tenant_id": tid},
            {"$set": update, "$setOnInsert": {"tenant_id": tid, "created_at": _now()}},
            upsert=True,
        )
        return {"ok": True, "updated": list(update.keys())}


__all__ = ["attach_tenant_kyc_routes"]
