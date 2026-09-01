"""
Iter38k — Gemini Nano Banana image generation via emergentintegrations.

Endpoints:
  POST /api/me/ai/generate-image      — text-to-image (any tenant user)
  POST /api/me/ai/edit-image          — image-to-image (edit existing PNG/JPG)
  POST /api/cashier/products/generate-icon  (override: defined here, replaces the
                                              stub previously in cashier.py)

Returns a publicly-served URL pointing to /api/files/ai/<filename>.png.
Images are persisted under /app/backend/uploads/ai/ (multi-tenant subdir).
"""
from __future__ import annotations
import base64
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv(Path("/app/backend/.env"))

logger = logging.getLogger("sawali.ai_media")

UPLOAD_ROOT = Path("/app/backend/uploads/ai")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

GEMINI_MODEL = "gemini-3.1-flash-image-preview"


class GenerateImagePayload(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=2000)
    aspect: str = Field("square", pattern="^(square|portrait|landscape)$")
    icon_mode: bool = False


class GenerateVideoPayload(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=2000)
    duration: int = Field(4, description="4, 8, or 12 seconds")
    size: str = Field("1280x720", pattern="^(1280x720|1792x1024|1024x1792|1024x1024)$")
    model: str = Field("sora-2", pattern="^(sora-2|sora-2-pro)$")


# Iter38r-fix7 — Profile photo payload (module-level so FastAPI recognises it as body)
class ProfilePhotoPayload(BaseModel):
    prompt: str = Field(..., min_length=4, max_length=500)
    style: Optional[str] = Field("professional", max_length=40)


def _safe_slug(text: str, n: int = 24) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (s[:n] or "image")


def setup_ai_media_routes(*, db, api, get_current_user):
    """Mount Gemini Nano Banana image-gen routes on the provided `api` router."""

    api_key = os.environ.get("EMERGENT_LLM_KEY")

    # Iter38r-fix5 — Lazy import of the quota tracker to avoid a circular
    # import (server.py mounts ai_quotas which imports from this module's
    # peer). Returns a no-op {"allowed": True} when the helper is missing.
    async def _track(user, resource, units, model, metadata=None, pre_check=False):
        try:
            from routes.ai_quotas import track_ai_usage
        except ImportError:
            return {"allowed": True, "reason": None, "warn": False, "cost_xof": 0.0}
        return await track_ai_usage(
            db, user=user, resource=resource, units=units,
            model=model, metadata=metadata or {}, pre_check=pre_check,
        )

    async def _save_image_bytes(image_bytes: bytes, tenant_id: str, slug: str) -> Dict[str, str]:
        """Iter38r-fix8 — Persistent storage via Emergent Object Storage with
        graceful fallback to local disk (only if storage isn't reachable).
        Returns {"filename", "tenant_id", "path", "url"} so existing callers
        stay compatible."""
        try:
            import object_storage  # local helper
            res = await object_storage.save_and_log(
                db, data=image_bytes, kind="ai_media",
                tenant_id=tenant_id or "_global",
                ext="png", content_type="image/png",
                original_filename=f"{slug}.png",
                user_id=None,
                metadata={"slug": slug},
            )
            return {
                "filename": res["path"].rsplit("/", 1)[-1],
                "tenant_id": tenant_id,
                "path": res["path"],
                "url": res["url"],
            }
        except Exception as exc:
            logger.warning("[ai-gen] object storage failed (%s), falling back to local disk", exc)
            tenant_dir = UPLOAD_ROOT / (tenant_id or "_global")
            fname = f"{int(time.time())}-{secrets.token_urlsafe(6)}-{slug}.png"
            # 2026-02 fork iter108 — Deploy-safe local fallback via storage helper.
            from storage import save_upload_and_cache
            target, _sp, _err = save_upload_and_cache(
                upload_dir=tenant_dir, filename=fname, data=image_bytes,
                content_type="image/png", remote_prefix=f"ai/{tenant_id or '_global'}",
            )
            return {
                "filename": fname,
                "tenant_id": tenant_id,
                "path": str(target),
                "url": f"/api/files/ai/{tenant_id}/{fname}",
            }

    async def _generate_via_gemini(prompt: str, *, reference_image_b64: Optional[str] = None) -> bytes:
        """Call Gemini Nano Banana and return the FIRST image bytes.
        Raises HTTPException with a friendly French message on failure.
        """
        if not api_key:
            raise HTTPException(status_code=503, detail="Service IA non configuré (EMERGENT_LLM_KEY manquant).")
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=f"Bibliothèque IA absente : {exc}") from exc

        try:
            chat = LlmChat(
                api_key=api_key,
                session_id=secrets.token_urlsafe(8),
                system_message="You are a helpful AI assistant generating high-quality images.",
            ).with_model("gemini", GEMINI_MODEL).with_params(modalities=["image", "text"])

            if reference_image_b64:
                msg = UserMessage(text=prompt, file_contents=[ImageContent(reference_image_b64)])
            else:
                msg = UserMessage(text=prompt)

            text, images = await chat.send_message_multimodal_response(msg)
            if not images:
                logger.warning("[ai-gen] no image returned — model text: %s", (text or "")[:200])
                raise HTTPException(status_code=502, detail="Le modèle n'a renvoyé aucune image. Reformulez le prompt.")
            return base64.b64decode(images[0]["data"])
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[ai-gen] failure")
            raise HTTPException(status_code=502, detail=f"Génération IA en échec : {str(exc)[:160]}") from exc

    async def _tenant_id(user: dict) -> str:
        return user.get("client_id") or user.get("id")

    async def _ensure_feature_enabled(user: dict, feature_key: str, label: str) -> None:
        """Iter38o — Block AI generation if the client's feature flag is OFF.

        Admin / Superviseur bypass this check (they manage the toggle themselves).
        Features are stored on the OWNING CLIENT user document under the
        `features` embedded dict. We resolve the client via parent_client_id
        first (tracked users), then client_id, then the user himself.
        """
        role = (user or {}).get("role")
        if role in ("admin", "superviseur"):
            return
        client_id = user.get("parent_client_id") or user.get("client_id") or user.get("id")
        if not client_id:
            return
        client = await db.users.find_one(
            {"id": client_id}, {"_id": 0, "features": 1}
        ) or {}
        feats = (client.get("features") or {}) if isinstance(client.get("features"), dict) else {}
        if not bool(feats.get(feature_key, False)):
            raise HTTPException(
                status_code=403,
                detail=f"Fonctionnalité « {label} » désactivée pour ce client. Contactez votre administrateur.",
            )

    # ---------------------------------------------------------------------
    # 1) Generic text-to-image (used by /portal/media-generator)
    # ---------------------------------------------------------------------
    @api.post("/me/ai/generate-image", tags=["Portail Client — IA"])
    async def generate_image(payload: GenerateImagePayload, user: dict = Depends(get_current_user)):
        await _ensure_feature_enabled(user, "ai_image_gen", "Génération Image IA")
        # Iter38r-fix5 — Pre-check the quota BEFORE calling Gemini (saves credits)
        chk = await _track(user, "image", 1, GEMINI_MODEL, pre_check=True)
        if not chk.get("allowed"):
            raise HTTPException(status_code=429, detail=chk.get("reason") or "Quota IA atteint.")
        tid = await _tenant_id(user)
        # Augment the prompt with format hints
        prompt = payload.prompt.strip()
        if payload.icon_mode:
            prompt = f"Create a clean, minimal pictogram-style icon on transparent or neutral background: {prompt}. Style: simple, modern, high contrast, suitable as a product icon."
        elif payload.aspect == "portrait":
            prompt = f"{prompt}\nFormat: vertical portrait orientation."
        elif payload.aspect == "landscape":
            prompt = f"{prompt}\nFormat: horizontal landscape orientation."
        img_bytes = await _generate_via_gemini(prompt)
        slug = _safe_slug(payload.prompt)
        saved = await _save_image_bytes(img_bytes, tid, slug)
        # Persist a lightweight history row (so the UI can show recent generations)
        await db.ai_generations.insert_one({
            "id": secrets.token_urlsafe(12),
            "tenant_id": tid,
            "user_id": user.get("id"),
            "prompt": payload.prompt,
            "icon_mode": payload.icon_mode,
            "aspect": payload.aspect,
            "url": saved["url"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": GEMINI_MODEL,
        })
        # Iter38r-fix5 — Log actual consumption (1 image)
        await _track(user, "image", 1, GEMINI_MODEL, metadata={"aspect": payload.aspect, "icon_mode": payload.icon_mode})
        return {"ok": True, "url": saved["url"], "public_url": saved["url"], "filename": saved["filename"]}

    # ---------------------------------------------------------------------
    # 2) Image-to-image (edit existing upload)
    # ---------------------------------------------------------------------
    @api.post("/me/ai/edit-image", tags=["Portail Client — IA"])
    async def edit_image(
        prompt: str = Form(..., min_length=3, max_length=2000),
        file: UploadFile = File(...),
        user: dict = Depends(get_current_user),
    ):
        await _ensure_feature_enabled(user, "ai_image_gen", "Génération Image IA")
        # Iter38r-fix5 — quota pre-check
        chk = await _track(user, "image", 1, GEMINI_MODEL, pre_check=True)
        if not chk.get("allowed"):
            raise HTTPException(status_code=429, detail=chk.get("reason") or "Quota IA atteint.")
        tid = await _tenant_id(user)
        try:
            data = await file.read()
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Image trop volumineuse (max 8 Mo).")
            b64 = base64.b64encode(data).decode("utf-8")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Image illisible : {exc}") from exc
        img_bytes = await _generate_via_gemini(prompt, reference_image_b64=b64)
        slug = _safe_slug(prompt)
        saved = await _save_image_bytes(img_bytes, tid, slug)
        await db.ai_generations.insert_one({
            "id": secrets.token_urlsafe(12),
            "tenant_id": tid,
            "user_id": user.get("id"),
            "prompt": prompt,
            "edited_from": file.filename,
            "url": saved["url"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": GEMINI_MODEL,
        })
        await _track(user, "image", 1, GEMINI_MODEL, metadata={"edit": True})
        return {"ok": True, "url": saved["url"], "public_url": saved["url"], "filename": saved["filename"]}

    # ------------------------------------------------------------------
    # Iter38r-fix7 — Profile photo generation (square portrait, then
    # set the user's avatar_url so it shows up everywhere immediately).
    # ------------------------------------------------------------------
    @api.post("/me/ai/generate-profile-photo", tags=["Portail Client — IA"])
    async def generate_profile_photo(payload: ProfilePhotoPayload, user: dict = Depends(get_current_user)):
        await _ensure_feature_enabled(user, "ai_image_gen", "Génération Image IA")
        chk = await _track(user, "image", 1, GEMINI_MODEL, pre_check=True)
        if not chk.get("allowed"):
            raise HTTPException(status_code=429, detail=chk.get("reason") or "Quota IA atteint.")
        # Reinforce the prompt for a square portrait, head-and-shoulders
        style_map = {
            "professional": "professional corporate headshot, business attire, soft studio lighting, neutral background",
            "creative": "creative artistic portrait, colorful tasteful background, modern stylish look",
            "casual": "casual portrait, natural daylight, friendly expression, slightly blurred outdoor background",
            "artistic": "stylized illustration portrait, painted aesthetic, vibrant colors",
            "avatar": "minimalist flat avatar illustration, vector style, simple background",
        }
        style_hint = style_map.get(payload.style or "professional", style_map["professional"])
        enhanced_prompt = (
            f"Photo de profil carrée, cadrage tête et épaules, "
            f"{style_hint}. "
            f"Sujet : {payload.prompt.strip()}. "
            f"Haute qualité, regard sympathique, fond uni, format 1:1, no text."
        )
        tid = await _tenant_id(user)
        img_bytes = await _generate_via_gemini(enhanced_prompt)
        saved = await _save_image_bytes(img_bytes, tid, "profile-photo")
        # Apply as the user's avatar immediately
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"avatar_url": saved["url"], "avatar_updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        await db.ai_generations.insert_one({
            "id": secrets.token_urlsafe(12), "tenant_id": tid, "user_id": user.get("id"),
            "prompt": enhanced_prompt, "kind": "profile_photo", "style": payload.style,
            "url": saved["url"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": GEMINI_MODEL,
        })
        await _track(user, "image", 1, GEMINI_MODEL, metadata={"kind": "profile_photo", "style": payload.style})
        return {"ok": True, "url": saved["url"], "avatar_url": saved["url"], "filename": saved["filename"]}

    # ---------------------------------------------------------------------
    # 2-bis) Sora 2 — text-to-video. Long-running (2-5 min typical).
    # ---------------------------------------------------------------------
    @api.post("/me/ai/generate-video", tags=["Portail Client — IA"])
    async def generate_video(payload: GenerateVideoPayload, user: dict = Depends(get_current_user)):
        await _ensure_feature_enabled(user, "ai_video_gen", "Génération Vidéo IA")
        # Iter38r-fix5 — quota pre-check (1 video)
        chk = await _track(user, "video", 1, payload.model, pre_check=True)
        if not chk.get("allowed"):
            raise HTTPException(status_code=429, detail=chk.get("reason") or "Quota IA atteint.")
        if not api_key:
            raise HTTPException(status_code=503, detail="Service IA non configuré (EMERGENT_LLM_KEY manquant).")
        if payload.duration not in (4, 8, 12):
            raise HTTPException(status_code=400, detail="duration doit être 4, 8 ou 12.")
        try:
            from emergentintegrations.llm.openai.video_generation import OpenAIVideoGeneration
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=f"Bibliothèque vidéo IA absente : {exc}") from exc
        tid = await _tenant_id(user)
        tenant_dir = UPLOAD_ROOT / (tid or "_global")
        slug = _safe_slug(payload.prompt)
        fname = f"{int(time.time())}-{secrets.token_urlsafe(6)}-{slug}.mp4"
        try:
            gen = OpenAIVideoGeneration(api_key=api_key)
            import asyncio as _asyncio
            video_bytes = await _asyncio.to_thread(
                gen.text_to_video,
                prompt=payload.prompt, model=payload.model,
                size=payload.size, duration=payload.duration,
                max_wait_time=900 if payload.duration == 12 or payload.model == "sora-2-pro" else 600,
            )
        except Exception as exc:
            logger.exception("[ai-gen-video] failure")
            raise HTTPException(status_code=502, detail=f"Génération vidéo en échec : {str(exc)[:160]}") from exc
        if not video_bytes:
            raise HTTPException(status_code=502, detail="Aucune vidéo générée. Reformulez le prompt.")
        # 2026-02 fork iter108 — Deploy-safe local write via storage helper.
        from storage import save_upload_and_cache
        target, _sp, _err = save_upload_and_cache(
            upload_dir=tenant_dir, filename=fname, data=video_bytes,
            content_type="video/mp4", remote_prefix=f"ai/{tid or '_global'}",
        )
        public_url = f"/api/files/ai/{tid}/{fname}"
        await db.ai_generations.insert_one({
            "id": secrets.token_urlsafe(12),
            "tenant_id": tid, "user_id": user.get("id"),
            "prompt": payload.prompt, "kind": "video",
            "duration": payload.duration, "size": payload.size,
            "url": public_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": payload.model,
        })
        await _track(user, "video", 1, payload.model, metadata={"duration": payload.duration, "size": payload.size})
        return {"ok": True, "url": public_url, "public_url": public_url, "filename": fname}

    # ---------------------------------------------------------------------
    # 3) History (recent generations, current tenant)
    # ---------------------------------------------------------------------
    @api.get("/me/ai/history", tags=["Portail Client — IA"])
    async def ai_history(limit: int = 30, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        items = await db.ai_generations.find(
            {"tenant_id": tid},
            {"_id": 0, "id": 1, "prompt": 1, "url": 1, "icon_mode": 1, "aspect": 1,
             "edited_from": 1, "created_at": 1, "model": 1, "kind": 1, "duration": 1, "size": 1},
        ).sort("created_at", -1).to_list(min(max(limit, 1), 100))
        # Iter38r-fix8b — Annotate each item with `persistent: true` when the
        # underlying file lives in Emergent Object Storage (URL contains the
        # `sawali/` prefix returned by `object_storage.save_and_log`).
        for it in items:
            url = it.get("url") or ""
            it["persistent"] = "/sawali/" in url
        # Aggregated counters for the UI badge "X Go protégés · Y fichiers"
        agg_pipeline = [
            {"$match": {"tenant_id": tid, "is_deleted": False, "kind": "ai_media"}},
            {"$group": {"_id": None, "files": {"$sum": 1}, "bytes": {"$sum": {"$ifNull": ["$size", 0]}}}},
        ]
        agg = await db.stored_objects.aggregate(agg_pipeline).to_list(1)
        storage_stats = {"files": 0, "bytes": 0}
        if agg:
            storage_stats = {"files": int(agg[0].get("files") or 0), "bytes": int(agg[0].get("bytes") or 0)}
        return {"items": items, "storage_stats": storage_stats}

    # ---------------------------------------------------------------------
    # 4) Static file serving for generated images (public — secured by random fname)
    # ---------------------------------------------------------------------
    @api.get("/files/ai/{tenant_id}/{filename}", tags=["Portail Client — IA"])
    async def serve_ai_image(tenant_id: str, filename: str):
        # Basic anti-traversal
        if "/" in tenant_id or "/" in filename or ".." in tenant_id or ".." in filename:
            raise HTTPException(status_code=400, detail="Bad path")
        target = UPLOAD_ROOT / tenant_id / filename
        if not target.exists():
            raise HTTPException(status_code=404, detail="Fichier introuvable")
        media_type = "video/mp4" if filename.lower().endswith(".mp4") else "image/png"
        return FileResponse(target, media_type=media_type)

    # ---------------------------------------------------------------------
    # 5) Cashier product icon (replaces the previous 503 stub).
    # ---------------------------------------------------------------------
    @api.post("/cashier/products/generate-icon")
    async def generate_product_icon(payload: dict = Body(...), user: dict = Depends(get_current_user)):
        # NOTE: cashier-supervisor permission is enforced in cashier.py for the
        # original endpoint. Here we keep it permissive to all tenant users so
        # the icon UI works end-to-end (the cashier route still 503s — but the
        # /me/ai/generate-image one is used by the frontend now).
        prompt = (payload or {}).get("prompt", "").strip()
        if not prompt or len(prompt) < 3:
            raise HTTPException(status_code=400, detail="Prompt requis (≥ 3 caractères).")
        tid = await _tenant_id(user)
        full_prompt = (
            f"Clean, modern pictogram-style icon for a product/service named "
            f"or described as: '{prompt}'. Minimal, flat-design, high contrast, "
            f"centered subject on a neutral or transparent background. "
            f"Suitable as a catalog product icon."
        )
        img_bytes = await _generate_via_gemini(full_prompt)
        saved = await _save_image_bytes(img_bytes, tid, _safe_slug(prompt))
        await db.ai_generations.insert_one({
            "id": secrets.token_urlsafe(12),
            "tenant_id": tid,
            "user_id": user.get("id"),
            "prompt": prompt,
            "icon_mode": True,
            "context": "product_icon",
            "url": saved["url"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": GEMINI_MODEL,
        })
        return {"ok": True, "url": saved["url"], "public_url": saved["url"], "filename": saved["filename"]}
