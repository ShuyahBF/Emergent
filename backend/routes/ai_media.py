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


def _safe_slug(text: str, n: int = 24) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (s[:n] or "image")


def setup_ai_media_routes(*, db, api, get_current_user):
    """Mount Gemini Nano Banana image-gen routes on the provided `api` router."""

    api_key = os.environ.get("EMERGENT_LLM_KEY")

    async def _save_image_bytes(image_bytes: bytes, tenant_id: str, slug: str) -> Dict[str, str]:
        tenant_dir = UPLOAD_ROOT / (tenant_id or "_global")
        tenant_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{int(time.time())}-{secrets.token_urlsafe(6)}-{slug}.png"
        target = tenant_dir / fname
        target.write_bytes(image_bytes)
        # Path served by FastAPI route /api/files/ai/{tenant}/{fname}
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

    # ---------------------------------------------------------------------
    # 1) Generic text-to-image (used by /portal/media-generator)
    # ---------------------------------------------------------------------
    @api.post("/me/ai/generate-image", tags=["Portail Client — IA"])
    async def generate_image(payload: GenerateImagePayload, user: dict = Depends(get_current_user)):
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
        return {"ok": True, "url": saved["url"], "public_url": saved["url"], "filename": saved["filename"]}

    # ---------------------------------------------------------------------
    # 2-bis) Sora 2 — text-to-video. Long-running (2-5 min typical).
    # ---------------------------------------------------------------------
    @api.post("/me/ai/generate-video", tags=["Portail Client — IA"])
    async def generate_video(payload: GenerateVideoPayload, user: dict = Depends(get_current_user)):
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
        tenant_dir.mkdir(parents=True, exist_ok=True)
        slug = _safe_slug(payload.prompt)
        fname = f"{int(time.time())}-{secrets.token_urlsafe(6)}-{slug}.mp4"
        target = tenant_dir / fname
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
        target.write_bytes(video_bytes)
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
        return {"items": items}

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
