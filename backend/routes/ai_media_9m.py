"""Iter38r-fix9m — AI Media Generator additional models.

Adds direct integration (NOT via Emergent Universal Key) for:
  - Google Veo 3.1 (video generation with native audio) via Gemini API
  - Google Imagen 4 (high-fidelity image gen) via Gemini API
  - ElevenLabs v3 Text-to-Speech + Instant Voice Cloning

Endpoints:
  POST /api/me/ai/generate-video-veo       (alternative to Sora 2)
  GET  /api/me/ai/generate-video-veo/{job} (status polling)
  POST /api/me/ai/generate-image-imagen    (alternative to Nano Banana)
  POST /api/me/ai/voices/clone             (multipart audio upload)
  GET  /api/me/ai/voices                   (list cloned voices)
  POST /api/me/ai/tts-elevenlabs           (uses cloned voice_id)
"""
from __future__ import annotations

import base64
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

logger = logging.getLogger("sawali.ai_media_9m")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
ELEVEN_BASE = "https://api.elevenlabs.io/v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_ai_media_routes(app, db, get_current_user):
    api: APIRouter = app

    def _gemini_key() -> str:
        k = os.environ.get("GOOGLE_GEMINI_API_KEY")
        if not k:
            raise HTTPException(status_code=503, detail="GOOGLE_GEMINI_API_KEY non configurée")
        return k

    def _elevenlabs_key() -> str:
        k = os.environ.get("ELEVENLABS_API_KEY")
        if not k:
            raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY non configurée")
        return k

    async def _ensure_feature_enabled(user: dict, feature_key: str, label: str) -> None:
        """Iter38r-fix9p — Block this AI endpoint when the tenant feature is OFF.

        Admins / superviseurs bypass the check. Features are stored on the
        owning client doc under the embedded `features` dict. We resolve the
        tenant via parent_client_id, then client_id, then the user himself.
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

    # ------------------------------------------------------------------
    # Veo 3.1 — Text-to-video with native audio
    # ------------------------------------------------------------------
    @api.post("/me/ai/generate-video-veo", tags=["Portail Client — AI Media (fix9m)"])
    async def generate_video_veo(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        await _ensure_feature_enabled(user, "ai_video_gen", "Génération Vidéo IA")
        prompt = (payload.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt requis")
        resolution = payload.get("resolution") or "1080p"
        model = payload.get("model") or "veo-3.1-generate-preview"
        key = _gemini_key()
        body = {
            "instances": [{"prompt": prompt}],
            "parameters": {"resolution": resolution},
        }
        url = f"{GEMINI_BASE}/models/{model}:predictLongRunning"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, headers={
                    "x-goog-api-key": key,
                    "Content-Type": "application/json",
                }, json=body)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Veo upstream error: {exc}")
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"Veo: {r.text[:300]}")
        data = r.json()
        operation_name = data.get("name")
        if not operation_name:
            raise HTTPException(status_code=502, detail="Veo: opération sans `name` retournée")
        job_id = str(uuid.uuid4())
        doc = {
            "id": job_id,
            "user_id": user["id"],
            "client_id": user.get("client_id") or user["id"],
            "provider": "google",
            "model": model,
            "prompt": prompt,
            "resolution": resolution,
            "operation_name": operation_name,
            "status": "pending",
            "video_uri": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.veo_jobs.insert_one(doc.copy())
        return {"ok": True, "job_id": job_id, "operation_name": operation_name, "status": "pending"}

    @api.get("/me/ai/generate-video-veo/{job_id}", tags=["Portail Client — AI Media (fix9m)"])
    async def poll_video_veo(job_id: str, user: dict = Depends(get_current_user)):
        job = await db.veo_jobs.find_one({"id": job_id, "user_id": user["id"]}, {"_id": 0})
        if not job:
            raise HTTPException(status_code=404, detail="Job introuvable")
        if job["status"] == "completed":
            return job
        key = _gemini_key()
        op = job["operation_name"]
        # Gemini operation names are full paths, e.g. "models/veo-3.1-generate-preview/operations/..."
        url = f"{GEMINI_BASE}/{op}" if op.startswith("models/") or op.startswith("operations/") else f"{GEMINI_BASE}/operations/{op}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(url, headers={"x-goog-api-key": key})
        except httpx.HTTPError:
            return job
        if r.status_code != 200:
            # Don't burn the job — leave pending and let user retry
            return job
        data = r.json()
        update: Dict[str, Any] = {"updated_at": _now_iso(), "last_poll": data}
        if data.get("done"):
            try:
                # Veo response shape: response.generateVideoResponse.generatedSamples[0].video.uri
                resp = data.get("response") or {}
                samples = (resp.get("generateVideoResponse") or {}).get("generatedSamples") or []
                if samples and samples[0].get("video", {}).get("uri"):
                    update["video_uri"] = samples[0]["video"]["uri"]
                    update["status"] = "completed"
                else:
                    update["status"] = "failed"
                    update["error"] = "Veo response sans URI"
            except Exception as exc:
                update["status"] = "failed"
                update["error"] = str(exc)[:200]
        await db.veo_jobs.update_one({"id": job_id}, {"$set": update})
        job.update(update)
        return job

    # ------------------------------------------------------------------
    # Imagen 4 — Text-to-image
    # ------------------------------------------------------------------
    @api.post("/me/ai/generate-image-imagen", tags=["Portail Client — AI Media (fix9m)"])
    async def generate_image_imagen(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        await _ensure_feature_enabled(user, "ai_image_gen", "Génération Image IA")
        prompt = (payload.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt requis")
        model = payload.get("model") or "imagen-4.0-generate-001"
        n = int(payload.get("number_of_images") or 1)
        if n < 1 or n > 4:
            n = 1
        aspect_ratio = payload.get("aspect_ratio") or "1:1"
        key = _gemini_key()
        body = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "sampleCount": n,
                "aspectRatio": aspect_ratio,
            },
        }
        url = f"{GEMINI_BASE}/models/{model}:predict"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, headers={
                    "x-goog-api-key": key,
                    "Content-Type": "application/json",
                }, json=body)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Imagen upstream error: {exc}")
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"Imagen: {r.text[:300]}")
        data = r.json()
        predictions = data.get("predictions") or []
        if not predictions:
            raise HTTPException(status_code=502, detail="Imagen: aucune image générée")
        # Each prediction has bytesBase64Encoded
        images_b64 = []
        for p in predictions:
            b64 = p.get("bytesBase64Encoded") or p.get("bytesBase64")
            if b64:
                images_b64.append(b64)
        job_id = str(uuid.uuid4())
        doc = {
            "id": job_id,
            "user_id": user["id"],
            "client_id": user.get("client_id") or user["id"],
            "provider": "google",
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "n_images": len(images_b64),
            "created_at": _now_iso(),
        }
        await db.imagen_jobs.insert_one(doc.copy())
        # Return data: URIs for direct rendering (no storage step yet)
        return {
            "ok": True,
            "job_id": job_id,
            "model": model,
            "images": [f"data:image/png;base64,{b64}" for b64 in images_b64],
        }

    # ------------------------------------------------------------------
    # ElevenLabs — Instant Voice Cloning + TTS v3
    # ------------------------------------------------------------------
    @api.post("/me/ai/voices/clone", tags=["Portail Client — AI Media (fix9m)"])
    async def clone_voice(
        name: str = Form(...),
        description: str = Form(""),
        audio_file: UploadFile = File(...),
        user: dict = Depends(get_current_user),
    ):
        await _ensure_feature_enabled(user, "ai_voice_gen", "Génération Vocale IA")
        key = _elevenlabs_key()
        raw = await audio_file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Fichier audio vide")
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Fichier audio trop volumineux (max 10 Mo)")
        files = [("files", (audio_file.filename or "voice.mp3", raw, audio_file.content_type or "audio/mpeg"))]
        data = {"name": name, "description": description}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    f"{ELEVEN_BASE}/voices/add",
                    headers={"xi-api-key": key},
                    files=files,
                    data=data,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"ElevenLabs error: {exc}")
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"ElevenLabs: {r.text[:300]}")
        body = r.json()
        voice_id = body.get("voice_id")
        if not voice_id:
            raise HTTPException(status_code=502, detail="ElevenLabs: voice_id manquant")
        doc = {
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "client_id": user.get("client_id") or user["id"],
            "name": name,
            "description": description,
            "voice_id": voice_id,
            "provider": "elevenlabs",
            "created_at": _now_iso(),
        }
        await db.eleven_voices.insert_one(doc.copy())
        return {"ok": True, "voice_id": voice_id, "name": name, "id": doc["id"]}

    @api.get("/me/ai/voices", tags=["Portail Client — AI Media (fix9m)"])
    async def list_voices(user: dict = Depends(get_current_user)):
        items = await db.eleven_voices.find(
            {"user_id": user["id"]},
            {"_id": 0},
        ).sort("created_at", -1).to_list(200)
        return {"items": items, "count": len(items)}

    @api.delete("/me/ai/voices/{voice_id}", tags=["Portail Client — AI Media (fix9m)"])
    async def delete_voice(voice_id: str, user: dict = Depends(get_current_user)):
        doc = await db.eleven_voices.find_one({"voice_id": voice_id, "user_id": user["id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Voix introuvable")
        # Remove from ElevenLabs as well (best effort)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.delete(
                    f"{ELEVEN_BASE}/voices/{voice_id}",
                    headers={"xi-api-key": _elevenlabs_key()},
                )
        except Exception:
            pass
        await db.eleven_voices.delete_one({"voice_id": voice_id, "user_id": user["id"]})
        return {"ok": True}

    @api.post("/me/ai/tts-elevenlabs", tags=["Portail Client — AI Media (fix9m)"])
    async def tts_elevenlabs(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        await _ensure_feature_enabled(user, "ai_voice_gen", "Génération Vocale IA")
        voice_id = (payload.get("voice_id") or "").strip()
        text = (payload.get("text") or "").strip()
        model_id = payload.get("model_id") or "eleven_multilingual_v2"
        if not voice_id or not text:
            raise HTTPException(status_code=400, detail="voice_id et text requis")
        # Verify the voice belongs to the user (or is a stock voice — skip check)
        owned = await db.eleven_voices.find_one({"voice_id": voice_id, "user_id": user["id"]}, {"_id": 0, "voice_id": 1})
        # (For stock voices, owned may be None — we still allow the call.)
        key = _elevenlabs_key()
        body = {"text": text[:5000], "model_id": model_id}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    f"{ELEVEN_BASE}/text-to-speech/{voice_id}",
                    headers={"xi-api-key": key, "Accept": "audio/mpeg", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"ElevenLabs TTS error: {exc}")
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"ElevenLabs TTS: {r.text[:300]}")
        audio_bytes = r.content
        await db.eleven_tts_jobs.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "voice_id": voice_id,
            "text_len": len(text),
            "model_id": model_id,
            "owned_voice": bool(owned),
            "created_at": _now_iso(),
        })
        # Return as base64 data URL — easier for the frontend to play inline
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        return {"ok": True, "audio_data_url": f"data:audio/mpeg;base64,{b64}", "size_bytes": len(audio_bytes)}

    return api
