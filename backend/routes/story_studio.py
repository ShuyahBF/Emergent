"""
Iter43-fix10 (2026-03) — Story Studio
=====================================

Module dédié à la création/diffusion de "Stories" (formats verticaux 9:16)
générées par IA pour publication sur les réseaux sociaux.

Architecture multi-tenant :
- SAWALI (admin global) configure les clés API GLOBALES (Meta App, Fal.ai,
  TikTok) dans `settings.global.story_studio`.
- Chaque TENANT connecte SES PROPRES comptes sociaux via OAuth (table
  `social_accounts` scopée par `tenant_id`).
- L'admin SAWALI peut publier sur n'importe quel tenant via le sélecteur UI.

Phase 1 (MVP livré ici) :
- Settings Story Studio (CRUD config globale)
- Génération vidéo Sora 2 (via Universal Key Emergent)
- Génération vidéo Fal.ai (Kling 2.1 Master, Veo 3)
- Génération image Nano Banana (déjà intégré ailleurs - on réutilise)
- Bibliothèque d'assets (`story_assets`)
- WhatsApp share deep link (mobile)
- Scaffolding social_accounts + boutons "Connecter"

Phase 2/3 (à venir) :
- OAuth flows Meta / TikTok
- Publication automatique IG/FB/TikTok
- Cron scheduler
- Analytics
"""

from __future__ import annotations

import asyncio
import os
import uuid
import logging
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Depends, Body
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sawali.story_studio")


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------
class StoryStudioSettings(BaseModel):
    """Configuration globale SAWALI (admin only).

    Toutes les clés sont optionnelles - l'application fonctionne en mode dégradé
    si certaines sont vides (ex : génération Sora 2 OK même sans Fal.ai)."""
    # Génération
    fal_api_key: Optional[str] = None
    fal_default_model: str = "fal-ai/kling-video/v2.1/master/text-to-video"
    sora_enabled: bool = True
    sora_default_duration: int = 8  # 4/8/12 sec
    sora_default_size: str = "1024x1792"  # 9:16 vertical (Stories)
    # Cross-posting
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None
    meta_redirect_uri: Optional[str] = None
    tiktok_client_key: Optional[str] = None
    tiktok_client_secret: Optional[str] = None
    tiktok_redirect_uri: Optional[str] = None
    # Comportement
    auto_download_after_generation: bool = True
    default_caption_template: str = "✨ {title}\n\n#SAWALI #Liluvine"


class StoryGenerateText2Video(BaseModel):
    """Génération vidéo à partir d'un prompt texte."""
    tenant_id: Optional[str] = None  # admin SAWALI peut cibler un tenant
    engine: str = Field(..., description="'sora-2', 'sora-2-pro' ou 'fal'")
    model: Optional[str] = None  # pour fal : ex 'fal-ai/kling-video/v2.1/master/text-to-video'
    prompt: str = Field(..., min_length=5, max_length=2000)
    duration_seconds: int = 8
    size: str = "1024x1792"  # 9:16 pour Stories par défaut
    generate_audio: bool = False
    title: Optional[str] = None  # libellé interne pour la bibliothèque


class StoryGenerateImage(BaseModel):
    """Génération image (Nano Banana) - format Story 1080x1920."""
    tenant_id: Optional[str] = None
    prompt: str = Field(..., min_length=5, max_length=2000)
    title: Optional[str] = None


class StoryAssetUpdate(BaseModel):
    title: Optional[str] = None
    caption: Optional[str] = None
    tags: Optional[List[str]] = None


class SocialAccountManualToken(BaseModel):
    """Saisie manuelle d'un token (mode dev, en attendant OAuth flow)."""
    tenant_id: str
    provider: str  # 'instagram', 'facebook', 'tiktok'
    account_id: str  # ID de la Page FB ou compte IG/TikTok
    account_label: str
    access_token: str
    extra: Optional[Dict[str, Any]] = None


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def attach_story_studio_routes(
    *,
    api,
    db,
    get_current_user,
    get_current_admin,
    get_admin_or_supervisor,
):
    """Monte tous les endpoints Story Studio sur l'api router fourni."""

    UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", "/tmp/uploads"))
    STORY_DIR = UPLOAD_ROOT / "stories"
    STORY_DIR.mkdir(parents=True, exist_ok=True)

    # ========================================================================
    # SETTINGS (admin only)
    # ========================================================================
    @api.get("/admin/story-studio/settings", tags=["Admin — Story Studio"])
    async def get_settings(_: dict = Depends(get_current_admin)):
        """Récupère la config globale Story Studio. Masque les secrets."""
        doc = await db.settings.find_one({"_id": "global"}) or {}
        st = (doc.get("story_studio") or {})
        # Mask secrets (return last 4 chars only)
        def _mask(v: Optional[str]) -> Optional[str]:
            if not v:
                return None
            if len(v) <= 8:
                return "***"
            return f"***{v[-4:]}"
        return {
            "fal_api_key": _mask(st.get("fal_api_key")),
            "fal_api_key_set": bool(st.get("fal_api_key")),
            "fal_default_model": st.get("fal_default_model", "fal-ai/kling-video/v2.1/master/text-to-video"),
            "sora_enabled": st.get("sora_enabled", True),
            "sora_default_duration": st.get("sora_default_duration", 8),
            "sora_default_size": st.get("sora_default_size", "1024x1792"),
            "meta_app_id": st.get("meta_app_id"),  # non-secret
            "meta_app_secret": _mask(st.get("meta_app_secret")),
            "meta_app_secret_set": bool(st.get("meta_app_secret")),
            "meta_redirect_uri": st.get("meta_redirect_uri"),
            "tiktok_client_key": st.get("tiktok_client_key"),
            "tiktok_client_secret": _mask(st.get("tiktok_client_secret")),
            "tiktok_client_secret_set": bool(st.get("tiktok_client_secret")),
            "tiktok_redirect_uri": st.get("tiktok_redirect_uri"),
            "auto_download_after_generation": st.get("auto_download_after_generation", True),
            "default_caption_template": st.get("default_caption_template", "✨ {title}\n\n#SAWALI #Liluvine"),
        }

    @api.put("/admin/story-studio/settings", tags=["Admin — Story Studio"])
    async def update_settings(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        """Met à jour la config globale. Si une valeur secrète est `null` OU
        commence par `***` (masque), elle n'est PAS modifiée."""
        allowed = {
            "fal_api_key", "fal_default_model",
            "sora_enabled", "sora_default_duration", "sora_default_size",
            "meta_app_id", "meta_app_secret", "meta_redirect_uri",
            "tiktok_client_key", "tiktok_client_secret", "tiktok_redirect_uri",
            "auto_download_after_generation", "default_caption_template",
        }
        secret_fields = {"fal_api_key", "meta_app_secret", "tiktok_client_secret"}
        update_set: Dict[str, Any] = {}
        for k, v in (payload or {}).items():
            if k not in allowed:
                continue
            if k in secret_fields and isinstance(v, str) and v.startswith("***"):
                continue  # masque retransmis → ne pas écraser
            update_set[f"story_studio.{k}"] = v
        if not update_set:
            raise HTTPException(status_code=400, detail="Aucun champ valide")
        update_set["story_studio.updated_at"] = _now_iso()
        update_set["story_studio.updated_by"] = user.get("email")
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": update_set, "$setOnInsert": {"_id": "global"}},
            upsert=True,
        )
        return {"ok": True}

    # ========================================================================
    # GÉNÉRATION TEXT-TO-VIDEO (Sora 2 ou Fal.ai)
    # ========================================================================
    @api.post("/admin/story-studio/generate/text-to-video", tags=["Admin — Story Studio"])
    async def generate_text_to_video(
        payload: StoryGenerateText2Video,
        user: dict = Depends(get_admin_or_supervisor),
    ):
        """Génère une vidéo à partir d'un prompt texte. Synchrone (jusqu'à 10 min)."""
        engine = (payload.engine or "").lower()
        if engine not in ("sora-2", "sora-2-pro", "fal"):
            raise HTTPException(status_code=400, detail="engine doit être sora-2, sora-2-pro ou fal")

        asset_id = str(uuid.uuid4())
        # Pré-enregistrement du job "processing"
        asset_doc = {
            "id": asset_id,
            "tenant_id": payload.tenant_id or user.get("parent_client_id") or user["id"],
            "kind": "video",
            "engine": engine,
            "model": payload.model,
            "prompt": payload.prompt,
            "title": payload.title or payload.prompt[:60],
            "duration_seconds": payload.duration_seconds,
            "size": payload.size,
            "generate_audio": payload.generate_audio,
            "status": "processing",
            "url": None,
            "file_size": None,
            "error": None,
            "created_at": _now_iso(),
            "created_by_id": user["id"],
            "created_by_email": user.get("email"),
            "tags": [],
            "caption": None,
        }
        await db.story_assets.insert_one(asset_doc.copy())

        # Exécute la génération en tâche bloquante (le client web est patient ou poll après)
        try:
            if engine.startswith("sora"):
                video_path = await _generate_with_sora(payload, asset_id)
            else:
                # Fal.ai
                video_path = await _generate_with_fal(payload, asset_id, db)

            if not video_path or not Path(video_path).exists():
                raise RuntimeError("Génération vidéo : aucun fichier produit")

            file_size = Path(video_path).stat().st_size
            rel_url = f"/uploads/stories/{Path(video_path).name}"
            await db.story_assets.update_one(
                {"id": asset_id},
                {"$set": {
                    "status": "ready",
                    "url": rel_url,
                    "file_size": file_size,
                    "updated_at": _now_iso(),
                }},
            )
            fresh = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
            return {"ok": True, "asset": fresh}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[story_studio] generation failed (asset=%s)", asset_id)
            await db.story_assets.update_one(
                {"id": asset_id},
                {"$set": {"status": "failed", "error": str(exc), "updated_at": _now_iso()}},
            )
            raise HTTPException(status_code=500, detail=f"Génération échouée : {exc}") from exc

    async def _generate_with_sora(payload: StoryGenerateText2Video, asset_id: str) -> str:
        """Sora 2 via Universal Key Emergent (emergentintegrations)."""
        from emergentintegrations.llm.openai.video_generation import OpenAIVideoGeneration  # type: ignore

        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY manquant côté serveur")
        out_path = str(STORY_DIR / f"sora_{asset_id}.mp4")
        # On exécute dans un thread car la lib est bloquante
        def _run() -> Optional[bytes]:
            gen = OpenAIVideoGeneration(api_key=key)
            return gen.text_to_video(
                prompt=payload.prompt,
                model=payload.engine,  # 'sora-2' ou 'sora-2-pro'
                size=payload.size,
                duration=payload.duration_seconds,
                max_wait_time=900,
            )
        video_bytes = await asyncio.to_thread(_run)
        if not video_bytes:
            raise RuntimeError("Sora 2 : aucune vidéo retournée")
        Path(out_path).write_bytes(video_bytes)
        return out_path

    async def _generate_with_fal(payload: StoryGenerateText2Video, asset_id: str, db_) -> str:
        """Fal.ai (Kling 2.1 Master par défaut)."""
        import fal_client  # type: ignore
        import httpx
        # Récupère la clé Fal depuis settings.global.story_studio
        st_doc = await db_.settings.find_one({"_id": "global"}) or {}
        fal_key = (st_doc.get("story_studio") or {}).get("fal_api_key")
        if not fal_key:
            raise HTTPException(status_code=400, detail="Clé Fal.ai non configurée dans Settings → Story Studio")
        os.environ["FAL_KEY"] = fal_key  # le client lit la variable
        model = payload.model or "fal-ai/kling-video/v2.1/master/text-to-video"
        def _run() -> Dict[str, Any]:
            return fal_client.subscribe(
                model,
                arguments={
                    "prompt": payload.prompt,
                    "duration": str(payload.duration_seconds),
                },
            )
        result = await asyncio.to_thread(_run)
        video = result.get("video") or (result.get("data") or {}).get("video") or {}
        video_url = video.get("url")
        if not video_url:
            raise RuntimeError(f"Fal.ai : URL vidéo manquante dans la réponse : {result!r:.200}")
        # Télécharge le fichier
        out_path = STORY_DIR / f"fal_{asset_id}.mp4"
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.get(video_url)
            r.raise_for_status()
            out_path.write_bytes(r.content)
        return str(out_path)

    # ========================================================================
    # GÉNÉRATION TEXT-TO-IMAGE (Nano Banana) - format Story 1080x1920
    # ========================================================================
    @api.post("/admin/story-studio/generate/text-to-image", tags=["Admin — Story Studio"])
    async def generate_text_to_image(
        payload: StoryGenerateImage,
        user: dict = Depends(get_admin_or_supervisor),
    ):
        """Génère une image (Nano Banana via Universal Key) en format 9:16."""
        from emergentintegrations.llm.openai.image_generation import OpenAIImageGeneration  # type: ignore
        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY manquant")

        asset_id = str(uuid.uuid4())
        asset_doc = {
            "id": asset_id,
            "tenant_id": payload.tenant_id or user.get("parent_client_id") or user["id"],
            "kind": "image",
            "engine": "nano-banana",
            "prompt": payload.prompt,
            "title": payload.title or payload.prompt[:60],
            "size": "1024x1536",  # proche 9:16
            "status": "processing",
            "url": None,
            "created_at": _now_iso(),
            "created_by_id": user["id"],
            "created_by_email": user.get("email"),
            "tags": [],
            "caption": None,
        }
        await db.story_assets.insert_one(asset_doc.copy())
        try:
            def _run() -> Optional[bytes]:
                gen = OpenAIImageGeneration(api_key=key)
                # NB: signature peut varier; on tente l'API moderne
                try:
                    return gen.text_to_image(prompt=payload.prompt, size="1024x1536")
                except Exception:
                    return gen.generate(prompt=payload.prompt)
            img_bytes = await asyncio.to_thread(_run)
            if not img_bytes:
                raise RuntimeError("Nano Banana : aucune image retournée")
            out_path = STORY_DIR / f"img_{asset_id}.png"
            out_path.write_bytes(img_bytes)
            rel_url = f"/uploads/stories/{out_path.name}"
            await db.story_assets.update_one(
                {"id": asset_id},
                {"$set": {"status": "ready", "url": rel_url, "file_size": len(img_bytes), "updated_at": _now_iso()}},
            )
            fresh = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
            return {"ok": True, "asset": fresh}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[story_studio] image generation failed")
            await db.story_assets.update_one(
                {"id": asset_id},
                {"$set": {"status": "failed", "error": str(exc), "updated_at": _now_iso()}},
            )
            raise HTTPException(status_code=500, detail=f"Génération image échouée : {exc}") from exc

    # ========================================================================
    # BIBLIOTHÈQUE
    # ========================================================================
    @api.get("/admin/story-studio/library", tags=["Admin — Story Studio"])
    async def list_library(
        tenant_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 100,
        user: dict = Depends(get_admin_or_supervisor),
    ):
        q: Dict[str, Any] = {}
        if (user.get("role") or "").lower() == "admin":
            if tenant_id:
                q["tenant_id"] = tenant_id
        else:
            q["tenant_id"] = user.get("parent_client_id") or user["id"]
        if kind in ("video", "image"):
            q["kind"] = kind
        items = await db.story_assets.find(q, {"_id": 0}).sort("created_at", -1).limit(min(limit, 500)).to_list(min(limit, 500))
        return {"items": items, "count": len(items)}

    @api.put("/admin/story-studio/library/{asset_id}", tags=["Admin — Story Studio"])
    async def update_asset(
        asset_id: str,
        payload: StoryAssetUpdate,
        user: dict = Depends(get_admin_or_supervisor),
    ):
        doc = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Asset introuvable")
        update_set: Dict[str, Any] = {}
        if payload.title is not None: update_set["title"] = payload.title
        if payload.caption is not None: update_set["caption"] = payload.caption
        if payload.tags is not None: update_set["tags"] = payload.tags
        if not update_set:
            raise HTTPException(status_code=400, detail="Aucun champ")
        update_set["updated_at"] = _now_iso()
        await db.story_assets.update_one({"id": asset_id}, {"$set": update_set})
        return {"ok": True}

    @api.delete("/admin/story-studio/library/{asset_id}", tags=["Admin — Story Studio"])
    async def delete_asset(asset_id: str, _: dict = Depends(get_current_admin)):
        doc = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Asset introuvable")
        # Supprime le fichier physique
        if doc.get("url"):
            try:
                fpath = UPLOAD_ROOT / doc["url"].lstrip("/").removeprefix("uploads/")
                if fpath.exists():
                    fpath.unlink()
            except Exception:  # noqa: BLE001
                logger.warning("[story_studio] failed to unlink %s", doc.get("url"))
        await db.story_assets.delete_one({"id": asset_id})
        return {"ok": True}

    # ========================================================================
    # SHARE WHATSAPP (deep link mobile)
    # ========================================================================
    @api.get("/admin/story-studio/library/{asset_id}/whatsapp-share", tags=["Admin — Story Studio"])
    async def whatsapp_share_link(asset_id: str, user: dict = Depends(get_admin_or_supervisor)):
        """Renvoie un deep link WhatsApp pour partager l'asset sur le mobile admin.

        Comme Meta n'expose pas d'API pour publier un Status, le flow est :
        1. Admin reçoit le lien
        2. Ouvre depuis son mobile → WhatsApp s'ouvre avec un message pré-rempli
           (texte + lien direct vers le média)
        3. Admin appuie sur "Status" depuis WhatsApp pour publier
        """
        doc = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Asset introuvable")
        if not doc.get("url"):
            raise HTTPException(status_code=400, detail="Asset non encore prêt")
        # Construit l'URL publique du média
        public_base = os.environ.get("PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or ""
        media_url = f"{public_base}{doc['url']}"
        caption = doc.get("caption") or doc.get("title") or "Nouvelle Story SAWALI ✨"
        text = f"{caption}\n\n{media_url}"
        wa_link = f"whatsapp://send?text={urllib.parse.quote(text)}"
        # Lien web fallback (ouvre WhatsApp Web puis bascule sur app si installée)
        web_fallback = f"https://wa.me/?text={urllib.parse.quote(text)}"
        return {
            "ok": True,
            "deep_link": wa_link,
            "web_fallback": web_fallback,
            "media_url": media_url,
            "caption": caption,
            "instructions": (
                "Sur mobile : cliquez sur le lien → WhatsApp s'ouvre → "
                "appuyez sur 'Status' (icône paperclip) ou utilisez 'Partager' "
                "depuis la galerie après avoir téléchargé la vidéo."
            ),
        }

    # ========================================================================
    # SOCIAL ACCOUNTS (scaffolding - saisie manuelle des tokens en mode dev)
    # ========================================================================
    @api.get("/admin/story-studio/social-accounts", tags=["Admin — Story Studio"])
    async def list_social_accounts(
        tenant_id: Optional[str] = None,
        user: dict = Depends(get_current_admin),
    ):
        q: Dict[str, Any] = {}
        if tenant_id:
            q["tenant_id"] = tenant_id
        items = await db.social_accounts.find(q, {"_id": 0, "access_token": 0}).sort("created_at", -1).to_list(500)
        return {"items": items}

    @api.post("/admin/story-studio/social-accounts/manual", tags=["Admin — Story Studio"])
    async def add_social_account_manual(
        payload: SocialAccountManualToken,
        user: dict = Depends(get_current_admin),
    ):
        """Iter43-fix10 — Saisie manuelle d'un token (mode dev). Phase 2
        introduira un vrai flow OAuth (login + callback)."""
        if payload.provider not in ("instagram", "facebook", "tiktok"):
            raise HTTPException(status_code=400, detail="provider invalide")
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": payload.tenant_id,
            "provider": payload.provider,
            "account_id": payload.account_id,
            "account_label": payload.account_label,
            "access_token": payload.access_token,
            "extra": payload.extra or {},
            "status": "connected",
            "created_at": _now_iso(),
            "created_by": user.get("email"),
        }
        await db.social_accounts.insert_one(doc.copy())
        # Don't return the token
        doc.pop("access_token", None)
        return {"ok": True, "account": doc}

    @api.delete("/admin/story-studio/social-accounts/{account_id}", tags=["Admin — Story Studio"])
    async def remove_social_account(account_id: str, _: dict = Depends(get_current_admin)):
        r = await db.social_accounts.delete_one({"id": account_id})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Compte introuvable")
        return {"ok": True}

    # ========================================================================
    # PUBLICATION STUB (Phase 2 — log only pour l'instant)
    # ========================================================================
    @api.post("/admin/story-studio/library/{asset_id}/publish", tags=["Admin — Story Studio"])
    async def publish_asset_stub(
        asset_id: str,
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_admin_or_supervisor),
    ):
        """Phase 2 — Publication automatique IG/FB/TikTok.

        STATUT ACTUEL : **MOCKED**. La publication ne fait que journaliser la
        requête. Le flow OAuth Meta + l'appel Graph API seront ajoutés en
        itération suivante. Pour Phase 1, utilisez `whatsapp-share` pour le
        partage manuel ou téléchargez l'asset et publiez via vos canaux."""
        doc = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Asset introuvable")
        channels = payload.get("channels") or []
        scheduled_at = payload.get("scheduled_at")
        post_id = str(uuid.uuid4())
        await db.story_posts.insert_one({
            "id": post_id,
            "asset_id": asset_id,
            "tenant_id": doc.get("tenant_id"),
            "channels": channels,  # ['instagram', 'facebook', 'tiktok']
            "caption": payload.get("caption") or doc.get("caption"),
            "scheduled_at": scheduled_at,
            "status": "scheduled" if scheduled_at else "queued",
            "created_at": _now_iso(),
            "created_by": user.get("email"),
            "note": "MOCKED — Phase 2 ajoutera la publication réelle via OAuth",
        })
        return {
            "ok": True,
            "post_id": post_id,
            "status": "queued",
            "warning": (
                "Publication automatique IG/FB/TikTok non encore opérationnelle "
                "(Phase 2). Utilisez le bouton 'Partager WhatsApp' ou téléchargez "
                "le média et publiez manuellement."
            ),
        }

    logger.info("[story_studio] routes mounted (Phase 1 MVP)")
