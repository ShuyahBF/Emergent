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
import base64
import hashlib
import hmac
import json
import os
import uuid
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import jwt as _pyjwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Depends, Body, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Iter43-fix24k — Stockage objet persistant (survit aux redéploiements K8s).
# Si désactivé (clé manquante), retombe gracieusement sur le disque local.
import object_storage as _obj_storage

load_dotenv()

logger = logging.getLogger("sawali.story_studio")


# ----------------------------------------------------------------------------
# Iter43-fix11 (2026-03) — Phase 2 Meta OAuth helpers
# ----------------------------------------------------------------------------
# Constants
GRAPH_API_VERSION = "v23.0"  # latest stable as of Feb 2026
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
GRAPH_VIDEO_BASE = f"https://graph-video.facebook.com/{GRAPH_API_VERSION}"
RUPLOAD_IG_BASE = f"https://rupload.facebook.com/ig-api-upload/{GRAPH_API_VERSION}"

# Iter43-fix14 — TikTok Content Posting API (v2)
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
TIKTOK_USERINFO_URL = "https://open.tiktokapis.com/v2/user/info/"
TIKTOK_DIRECT_POST_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_STATUS_FETCH_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
TIKTOK_OAUTH_SCOPES = ["video.upload", "video.publish", "user.info.basic"]

# Default scopes requested when connecting a Meta Business account.
META_OAUTH_SCOPES = [
    "public_profile",
    "email",
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "pages_manage_engagement",
    "instagram_basic",
    "instagram_content_publish",
    "business_management",
]


def _get_fernet() -> Fernet:
    """Derive a stable Fernet key from JWT_SECRET (no extra env var to manage).

    Tokens stored in `social_accounts.*_token_encrypted` use Fernet for symmetric
    encryption at rest. Key material is derived deterministically so server
    restarts don't break previously stored tokens.
    """
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    # SHA-256 of secret -> 32 bytes -> base64-urlsafe -> 44-char Fernet key
    digest = hashlib.sha256(f"sawali-story-studio-meta::{secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _enc(plain: Optional[str]) -> Optional[str]:
    if not plain:
        return None
    return _get_fernet().encrypt(plain.encode()).decode()


def _dec(enc: Optional[str]) -> Optional[str]:
    if not enc:
        return None
    try:
        return _get_fernet().decrypt(enc.encode()).decode()
    except (InvalidToken, Exception):  # noqa: BLE001
        logger.warning("[story_studio] failed to decrypt token (possibly migrated/corrupted)")
        return None


def _oauth_state_encode(payload: Dict[str, Any]) -> str:
    """JWT-encoded state for CSRF protection. TTL ~10 min."""
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    claims = {
        **payload,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
        "nonce": uuid.uuid4().hex,
    }
    return _pyjwt.encode(claims, secret + "-story-meta-state", algorithm="HS256")


def _oauth_state_decode(state: str) -> Dict[str, Any]:
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    try:
        return _pyjwt.decode(state, secret + "-story-meta-state", algorithms=["HS256"])
    except _pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="OAuth state expiré (relancez la connexion Meta)")
    except _pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail=f"OAuth state invalide : {exc}")


def _signed_media_token(asset_id: str, ttl_minutes: int = 60) -> str:
    """Short-lived signed URL token for public media access (used by Meta Graph
    API when it has to fetch the video via `video_url`)."""
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    claims = {
        "asset_id": asset_id,
        "purpose": "meta-publish",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    return _pyjwt.encode(claims, secret + "-signed-media", algorithm="HS256")


def _verify_signed_media_token(token: str) -> str:
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    try:
        claims = _pyjwt.decode(token, secret + "-signed-media", algorithms=["HS256"])
        return claims["asset_id"]
    except _pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="Lien expiré")
    except _pyjwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Lien invalide")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _meta_get(client: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = await client.get(url, params=params)
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
            raise HTTPException(
                status_code=502,
                detail=f"Meta Graph API erreur {err.get('code')}: {err.get('message') or r.text}",
            )
        except (ValueError, KeyError):
            raise HTTPException(status_code=502, detail=f"Meta Graph API erreur HTTP {r.status_code}")
    return r.json()


async def _meta_post(client: httpx.AsyncClient, url: str, params: Optional[Dict[str, Any]] = None,
                     data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = await client.post(url, params=params or {}, data=data or {})
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
            raise HTTPException(
                status_code=502,
                detail=f"Meta Graph API erreur {err.get('code')}: {err.get('message') or r.text}",
            )
        except (ValueError, KeyError):
            raise HTTPException(status_code=502, detail=f"Meta Graph API erreur HTTP {r.status_code}")
    return r.json()


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
# Iter43-fix11 (2026-03) — Phase 2 publish models
# ----------------------------------------------------------------------------
class PublishTarget(BaseModel):
    social_account_id: str
    page_id: str  # FB page id (also used to derive IG account via stored mapping)
    target: str  # 'fb_feed' | 'ig_story' | 'ig_reel'


class PublishRequest(BaseModel):
    targets: List[PublishTarget] = Field(default_factory=list)
    caption: Optional[str] = None
    mode: str = "immediate"  # 'immediate' | 'draft'
    scheduled_at: Optional[str] = None  # ISO datetime (future use)


class PageActivationUpdate(BaseModel):
    page_id: str
    is_active: bool


# ----------------------------------------------------------------------------
# Iter43-fix13 (2026-03) — Phase 3 multi-tenant monétisation
# Tarif par tenant + crédits prépayés + facture mensuelle
# ----------------------------------------------------------------------------
class TenantPublishPricing(BaseModel):
    fb_feed: int = Field(200, ge=0, description="XOF par publication Facebook Feed")
    ig_story: int = Field(300, ge=0, description="XOF par publication Instagram Story")
    ig_reel: int = Field(500, ge=0, description="XOF par publication Instagram Reel")
    tiktok: int = Field(500, ge=0, description="XOF par publication TikTok (Phase 4)")


class TenantPublishConfigUpsert(BaseModel):
    pricing: TenantPublishPricing = Field(default_factory=TenantPublishPricing)
    currency: str = Field("XOF", min_length=3, max_length=8)
    billing_mode: str = Field("credits_first",
                              pattern="^(credits_first|invoice_only|credits_only)$")
    monthly_invoice_day: int = Field(1, ge=1, le=28,
                                      description="Jour du mois pour clôturer la facture (1-28)")
    notes: Optional[str] = None


class CreditTopupRequest(BaseModel):
    amount_xof: int = Field(..., ge=100, description="Montant à créditer en XOF")
    reason: str = Field("admin_topup", max_length=100)
    note: Optional[str] = None


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _now_iso_dup() -> str:
    """Kept for backward-compat — use module-level `_now_iso` introduced above."""
    return _now_iso()


def _period_yyyymm(dt: Optional[datetime] = None) -> str:
    """'202603' format pour facturation mensuelle."""
    d = dt or datetime.now(timezone.utc)
    return f"{d.year:04d}{d.month:02d}"


def attach_story_studio_routes(
    *,
    api,
    db,
    get_current_user,
    get_current_admin,
    get_admin_or_supervisor,
):
    """Monte tous les endpoints Story Studio sur l'api router fourni."""

    # Iter43-fix10a — Utiliser STRICTEMENT le même UPLOAD_DIR que server.py
    # (par défaut /app/backend/uploads, override possible via UPLOAD_DIR env).
    UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
    STORY_DIR = UPLOAD_ROOT / "stories"
    STORY_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"[story_studio] media dir = {STORY_DIR}")

    # ========================================================================
    # Iter43-fix24k (2026-06) — Résilience disque éphémère
    # ========================================================================
    async def _ensure_local_file(asset_doc: Dict[str, Any]) -> Optional[str]:
        """Garantit qu'un fichier vidéo/image local existe pour cet asset.

        Logique en cascade (Iter43-fix24k) :
          1. Si `file_path` existe sur disque → retourne le chemin.
          2. Sinon, si `storage_path` (Emergent Object Storage) → download depuis là
             (PERSISTANT, survit aux redéploiements K8s — option PRÉFÉRÉE).
          3. Sinon, si `source_url` (URL CDN Fal.ai) → tente la re-download
             (peut expirer après 24-72h selon le provider).
          4. Si tout échoue → marque l'asset `status="expired"` et retourne None.
        """
        import httpx
        asset_id = asset_doc.get("id") or ""
        fpath = asset_doc.get("file_path")
        # Cas 1 : le fichier existe localement
        if fpath and Path(fpath).exists():
            return fpath
        # Cas 2 : reconstruire le path attendu (pour les anciens assets sans file_path)
        if not fpath:
            kind = asset_doc.get("kind") or "video"
            engine = asset_doc.get("engine") or ""
            if kind == "video":
                prefix = "fal_" if engine == "fal" else "sora_"
                guess = STORY_DIR / f"{prefix}{asset_id}.mp4"
            else:
                guess = STORY_DIR / f"img_{asset_id}.png"
            if guess.exists():
                await db.story_assets.update_one(
                    {"id": asset_id}, {"$set": {"file_path": str(guess)}},
                )
                return str(guess)
            fpath = str(guess)
        target_path = Path(fpath)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Cas 3 : tente la restauration depuis Object Storage (préféré, persistant)
        storage_path = asset_doc.get("storage_path")
        if storage_path and (_obj_storage.is_enabled() or await _obj_storage.init_storage()):
            try:
                logger.info(
                    "[story_studio] restoring asset %s from object_storage %s",
                    asset_id, storage_path,
                )
                data, _ct = await _obj_storage.get_object(storage_path)
                target_path.write_bytes(data)
                await db.story_assets.update_one(
                    {"id": asset_id},
                    {"$set": {
                        "file_path": str(target_path),
                        "file_size": target_path.stat().st_size,
                        "status": "ready",
                        "restored_at": _now_iso(),
                        "restored_from": "object_storage",
                    }},
                )
                return str(target_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[story_studio] object_storage restore failed for asset %s: %s",
                    asset_id, exc,
                )

        # Cas 4 : fallback re-download depuis source_url (Fal.ai CDN — peut expirer)
        source_url = asset_doc.get("source_url")
        if source_url:
            try:
                logger.info(
                    "[story_studio] re-downloading asset %s from source_url (file missing)",
                    asset_id,
                )
                async with httpx.AsyncClient(timeout=180.0) as client:
                    r = await client.get(source_url)
                    r.raise_for_status()
                    target_path.write_bytes(r.content)
                await db.story_assets.update_one(
                    {"id": asset_id},
                    {"$set": {
                        "file_path": str(target_path),
                        "file_size": target_path.stat().st_size,
                        "status": "ready",
                        "restored_at": _now_iso(),
                        "restored_from": "source_url",
                    }},
                )
                return str(target_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[story_studio] source_url re-download failed for %s: %s",
                    asset_id, exc,
                )

        # Cas 5 : impossible de restaurer → marque comme expired
        await db.story_assets.update_one(
            {"id": asset_id},
            {"$set": {
                "status": "expired",
                "expired_at": _now_iso(),
                "expired_reason": (
                    "Fichier local manquant ET object storage indisponible "
                    "ET URL source expirée. Régénérez l'asset pour le récupérer."
                ),
                "updated_at": _now_iso(),
            }},
        )
        return None

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
            # Iter43-fix24az-l — TikTok privacy toggle (audit compliance).
            # SELF_ONLY is required until the TikTok app audit passes ; after
            # audit, admin can flip to PUBLIC_TO_EVERYONE / MUTUAL_FOLLOW_FRIENDS /
            # FOLLOWER_OF_CREATOR.
            "tiktok_privacy_level": st.get("tiktok_privacy_level", "SELF_ONLY"),
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
            "tiktok_privacy_level",
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
    # Iter43-fix24az-l retest (2026-02-26) — Upload local d'assets Story Studio.
    # Permet à l'admin d'importer une image ou une vidéo depuis son ordinateur
    # sans passer par la génération IA (utile pour recycler du contenu existant,
    # ou pour compléter une story IA avec un visuel externe).
    # ========================================================================
    @api.post("/admin/story-studio/library/upload", tags=["Admin — Story Studio"])
    async def story_studio_upload_local(
        request: Request,
        user: dict = Depends(get_admin_or_supervisor),
    ):
        """Upload d'un asset local (image ou vidéo) directement dans la
        bibliothèque Story Studio. Multipart form-data :
          - file (required) : le fichier binaire
          - title (optional) : titre lisible
          - tenant_id (optional) : tenant cible (super-admin peut cibler un autre tenant)
        Retourne le doc `story_assets` créé (`status="ready"`).
        """
        try:
            form = await request.form()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Form invalide : {exc}") from exc
        file = form.get("file")
        if not file or not hasattr(file, "filename"):
            raise HTTPException(status_code=400, detail="Champ 'file' requis (multipart)")
        title = (form.get("title") or "").strip() or None
        tenant_id = (form.get("tenant_id") or "").strip() or None

        content_type = (getattr(file, "content_type", None) or "").lower()
        filename = getattr(file, "filename", "") or "upload"
        ext = Path(filename).suffix.lower().lstrip(".") or "bin"
        # Décide kind à partir du content_type OU de l'extension (fallback)
        if content_type.startswith("video") or ext in ("mp4", "mov", "webm", "mkv", "avi"):
            kind = "video"
            default_ext = "mp4"
        elif content_type.startswith("image") or ext in ("png", "jpg", "jpeg", "webp", "gif"):
            kind = "image"
            default_ext = "png"
        else:
            raise HTTPException(status_code=400, detail=f"Type non supporté : {content_type or ext}")

        raw_bytes = await file.read()
        max_bytes = 200 * 1024 * 1024  # 200 Mo
        if len(raw_bytes) > max_bytes:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (> {max_bytes // (1024 * 1024)} Mo)")
        if len(raw_bytes) == 0:
            raise HTTPException(status_code=400, detail="Fichier vide")

        asset_id = str(uuid.uuid4())
        safe_ext = ext if ext in ("mp4", "mov", "webm", "mkv", "avi", "png", "jpg", "jpeg", "webp", "gif") else default_ext
        target_path = STORY_DIR / f"{asset_id}.{safe_ext}"
        # 2026-02 fork iter108 — Deploy-safe local write via storage helper.
        try:
            from storage import save_upload_and_cache
            save_upload_and_cache(
                upload_dir=STORY_DIR, filename=target_path.name, data=raw_bytes,
                content_type=content_type or f"{kind}/{safe_ext}", remote_prefix="stories",
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Écriture disque échouée : {exc}") from exc

        rel_url = f"/admin/story-studio/library/{asset_id}/media"
        asset_doc: Dict[str, Any] = {
            "id": asset_id,
            "tenant_id": tenant_id or user.get("parent_client_id") or user["id"],
            "kind": kind,
            "engine": "import",  # marqueur : asset importé, pas généré IA
            "model": "local-upload",
            "prompt": None,
            "title": title or (filename[:60] if filename else f"Import {kind}"),
            "duration_seconds": None,
            "size": None,
            "generate_audio": False,
            "status": "ready",
            "url": rel_url,
            "file_path": str(target_path),
            "file_size": len(raw_bytes),
            "content_type": content_type or f"{kind}/{safe_ext}",
            "original_filename": filename,
            "error": None,
            "created_at": _now_iso(),
            "created_by_id": user["id"],
            "created_by_email": user.get("email"),
            "tags": ["imported"],
            "caption": None,
            "usage_estimate": {"tokens": 0, "usd_cost": 0, "xof_cost": 0},
        }

        # Mirror to Emergent Object Storage (survive redéploiements K8s).
        try:
            if _obj_storage.is_enabled() or await _obj_storage.init_storage():
                obj_meta = await _obj_storage.save_and_log(
                    db,
                    data=raw_bytes,
                    kind="ai_media",
                    tenant_id=asset_doc["tenant_id"],
                    ext=safe_ext,
                    content_type=asset_doc["content_type"],
                    original_filename=filename,
                    user_id=user["id"],
                    metadata={"asset_id": asset_id, "engine": "import", "source": "local_upload"},
                )
                asset_doc["storage_path"] = obj_meta["path"]
                asset_doc["storage_id"] = obj_meta["id"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[story_studio] local upload storage mirror failed: %s", exc)

        await db.story_assets.insert_one(asset_doc.copy())
        asset_doc.pop("_id", None)
        return asset_doc

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
            source_url: Optional[str] = None  # URL Fal/Sora CDN pour re-download si fichier perdu
            if engine.startswith("sora"):
                # Sora renvoie des bytes (pas d'URL CDN persistante exposée par emergentintegrations)
                video_path = await _generate_with_sora(payload, asset_id)
            else:
                # Fal.ai : on récupère ET le path local ET l'URL CDN d'origine
                video_path, source_url = await _generate_with_fal(payload, asset_id, db)

            if not video_path or not Path(video_path).exists():
                raise RuntimeError("Génération vidéo : aucun fichier produit")

            file_size = Path(video_path).stat().st_size
            # Iter43-fix15 — Estimation de la consommation (tokens/USD/XOF)
            usage_estimate = _compute_usage_estimate(
                engine=engine,
                duration_seconds=payload.duration_seconds,
                size=payload.size,
                kind="video",
            )
            # Iter43-fix10a — URL via endpoint streaming dédié (les fichiers ne sont PAS
            # exposés via static mount sur ce déploiement Kubernetes).
            rel_url = f"/admin/story-studio/library/{asset_id}/media"
            update_doc = {
                "status": "ready",
                "url": rel_url,
                "file_path": video_path,  # chemin disque pour le streamer
                "file_size": file_size,
                "usage_estimate": usage_estimate,
                "updated_at": _now_iso(),
            }
            # Iter43-fix24k — Persiste l'URL CDN d'origine (Fal.ai) pour permettre
            # la re-download à la demande si le fichier local disparaît (redéploiement
            # Kubernetes qui efface le filesystem du container).
            if source_url:
                update_doc["source_url"] = source_url
            # Iter43-fix24k — Upload vers Emergent Object Storage (PERSISTANT entre
            # redéploiements). Le `storage_path` permet la restauration garantie même
            # si l'URL Fal expire (≥72h après génération).
            try:
                if _obj_storage.is_enabled() or await _obj_storage.init_storage():
                    with open(video_path, "rb") as fh:
                        video_bytes = fh.read()
                    obj_meta = await _obj_storage.save_and_log(
                        db,
                        data=video_bytes,
                        kind="ai_media",
                        tenant_id=asset_doc.get("tenant_id") or "_global",
                        ext="mp4",
                        content_type="video/mp4",
                        original_filename=f"story_{asset_id}.mp4",
                        user_id=user["id"],
                        metadata={"asset_id": asset_id, "engine": engine, "model": payload.model},
                    )
                    update_doc["storage_path"] = obj_meta["path"]
                    update_doc["storage_id"] = obj_meta["id"]
                    logger.info(
                        "[story_studio] asset %s uploaded to object storage at %s",
                        asset_id, obj_meta["path"],
                    )
            except Exception as exc:  # noqa: BLE001
                # Non-fatal — l'asset reste utilisable via le disque local + source_url.
                # Mais alerter dans les logs pour qu'on remarque si le storage est down.
                logger.warning(
                    "[story_studio] object storage upload failed for asset %s: %s",
                    asset_id, exc,
                )
            await db.story_assets.update_one(
                {"id": asset_id},
                {"$set": update_doc},
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

    # ========================================================================
    # Iter43-fix15 (2026-03) — Estimation de consommation tokens / coût générateur
    # ========================================================================
    # Tarifs publics indicatifs (USD) au moment du livrable. Sont stockés tels
    # quels au moment de la génération pour rester historiquement justes même
    # si les prix changent. Source : documentation OpenAI/Gemini publique.
    USAGE_PRICING_USD = {
        # Video — Sora 2
        "sora-2": {"unit": "second", "price_per_unit_usd": 0.10,
                   "label": "Sora 2 (720p)"},
        "sora-2-pro": {"unit": "second", "price_per_unit_usd": 0.30,
                       "label": "Sora 2 Pro (1080p)"},
        # Video — Fal.ai (Kling Master)
        "kling-master": {"unit": "second", "price_per_unit_usd": 0.28,
                          "label": "Fal.ai Kling 2.1 Master"},
        # Image — Nano Banana (Gemini)
        "nano-banana": {"unit": "image", "price_per_unit_usd": 0.0395,
                        "label": "Nano Banana (Gemini 3)"},
    }
    USD_TO_XOF = 620  # taux d'approximation CFA

    def _compute_usage_estimate(
        *, engine: str, duration_seconds: Optional[int] = None,
        size: Optional[str] = None, kind: str = "video",
    ) -> Dict[str, Any]:
        """Calcule une estimation de la consommation pour un asset.

        Renvoie un dict structuré inséré dans l'asset MongoDB pour affichage UI."""
        # Normalisation du moteur
        key = (engine or "").lower()
        if key.startswith("fal-ai/kling"):
            key = "kling-master"
        pricing = USAGE_PRICING_USD.get(key)
        if not pricing:
            return {
                "engine": engine, "estimated": False,
                "note": "Tarif non répertorié pour ce moteur",
            }
        if kind == "image":
            qty = 1
        else:
            qty = int(duration_seconds or 0) or 0
        unit_cost = float(pricing["price_per_unit_usd"])
        total_usd = round(unit_cost * qty, 4)
        total_xof = int(round(total_usd * USD_TO_XOF))
        return {
            "engine": engine,
            "engine_label": pricing["label"],
            "unit": pricing["unit"],
            "quantity": qty,
            "unit_cost_usd": unit_cost,
            "estimated_cost_usd": total_usd,
            "estimated_cost_xof": total_xof,
            "estimated": True,
            "size": size,
            "estimated_at": _now_iso(),
        }

    async def _generate_with_sora(payload: StoryGenerateText2Video, asset_id: str) -> str:
        """Sora 2 via Universal Key Emergent (emergentintegrations)."""
        from emergentintegrations.llm.openai.video_generation import OpenAIVideoGeneration  # type: ignore

        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY manquant côté serveur")
        # Iter43-fix10a — Sora 2 contraintes : tailles supportées limitées.
        # Modèle 'sora-2' supporte : 1280x720, 720x1280
        # Modèle 'sora-2-pro' supporte : 1280x720, 720x1280, 1024x1792, 1792x1024
        # Mapping intelligent vers la taille la plus proche acceptée.
        engine = payload.engine
        size = payload.size
        if engine == "sora-2":
            # Seul 720p autorisé pour sora-2
            if "x" in size:
                w, h = [int(x) for x in size.split("x")]
                size = "720x1280" if h > w else "1280x720"  # portrait si vertical sinon paysage
            else:
                size = "720x1280"
        elif engine == "sora-2-pro":
            allowed = {"1280x720", "720x1280", "1024x1792", "1792x1024"}
            if size not in allowed:
                # Sélectionne la résolution acceptée la plus proche selon orientation
                try:
                    w, h = [int(x) for x in size.split("x")]
                    size = "1024x1792" if h > w else "1792x1024"
                except Exception:  # noqa: BLE001
                    size = "720x1280"
        logger.info(f"[story_studio] sora generation : engine={engine} size={size} duration={payload.duration_seconds}s")
        out_path = str(STORY_DIR / f"sora_{asset_id}.mp4")
        # On exécute dans un thread car la lib est bloquante
        def _run() -> Optional[bytes]:
            gen = OpenAIVideoGeneration(api_key=key)
            return gen.text_to_video(
                prompt=payload.prompt,
                model=engine,  # 'sora-2' ou 'sora-2-pro'
                size=size,
                duration=payload.duration_seconds,
                max_wait_time=900,
            )
        video_bytes = await asyncio.to_thread(_run)
        if not video_bytes:
            raise RuntimeError(
                f"Sora 2 ({engine}) : aucune vidéo retournée (size={size}, duration={payload.duration_seconds}s). "
                f"Vérifiez le solde Universal Key sur le profil. "
                f"Prompt rejeté possible si contenu non conforme aux règles OpenAI."
            )
        Path(out_path).write_bytes(video_bytes)
        return out_path

    async def _generate_with_fal(payload: StoryGenerateText2Video, asset_id: str, db_) -> tuple[str, Optional[str]]:
        """Fal.ai (Kling 2.1 Master par défaut).

        Returns: (local_path, source_url) — Iter43-fix24k stocke source_url pour
        permettre la re-download à la demande si le fichier disque disparaît
        (redéploiement K8s qui remet le filesystem à zéro).
        """
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
        return str(out_path), str(video_url)

    # ========================================================================
    # Iter43-fix11 — Meta credentials & publishing helpers (closure over `db`)
    # ========================================================================
    async def _get_meta_app_credentials(db_) -> tuple[Optional[str], Optional[str]]:
        doc = await db_.settings.find_one({"_id": "global"}) or {}
        st = doc.get("story_studio") or {}
        return st.get("meta_app_id"), st.get("meta_app_secret")

    async def _resolve_meta_redirect_uri(db_) -> str:
        """Return the redirect URI to use in the OAuth flow.

        Priority: setting `meta_redirect_uri` > derived from PUBLIC_BASE_URL.
        Whatever value is returned MUST be registered in the Meta Developer App
        valid OAuth redirect URIs."""
        doc = await db_.settings.find_one({"_id": "global"}) or {}
        st = doc.get("story_studio") or {}
        configured = st.get("meta_redirect_uri")
        if configured:
            return configured
        base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
        if not base:
            raise HTTPException(
                status_code=500,
                detail="PUBLIC_BASE_URL non défini et meta_redirect_uri non configuré",
            )
        return f"{base}/api/admin/story-studio/oauth/meta/callback"

    async def _publish_single_target(
        *, db_, asset_doc: Dict[str, Any], target: PublishTarget,
        caption: str, asset_id: str,
    ) -> Dict[str, Any]:
        """Publie l'asset vers UNE cible. Renvoie {ok, channel_id?, error?}."""
        try:
            acc = await db_.social_accounts.find_one({"id": target.social_account_id})
            if not acc:
                return {"ok": False, "error": "Compte social introuvable"}

            # Iter43-fix24k — Garantit que le fichier local existe (re-download
            # depuis source_url si nécessaire). Évite les "Fichier vidéo introuvable"
            # après un redéploiement K8s qui efface le filesystem du container.
            file_path = await _ensure_local_file(asset_doc)
            if not file_path:
                return {
                    "ok": False,
                    "error": (
                        "Fichier vidéo perdu (redéploiement serveur) "
                        "et URL source expirée. Régénérez la vidéo via « Recréer »."
                    ),
                }

            # TikTok : pas de notion de Page, on appelle directement
            if target.target == "tiktok":
                if acc.get("provider") != "tiktok":
                    return {"ok": False, "error": "Le compte social n'est pas un compte TikTok"}
                return await _publish_tiktok_video(
                    account_id=target.social_account_id,
                    file_path=file_path, caption=caption,
                )

            # Meta : nécessite Page + token
            if acc.get("provider") != "meta":
                return {"ok": False, "error": "Cible non Meta non supportée"}
            page = next((p for p in (acc.get("pages") or []) if p.get("page_id") == target.page_id), None)
            if not page:
                return {"ok": False, "error": "Page non trouvée dans ce compte"}
            page_token = _dec(page.get("page_access_token_encrypted"))
            user_token = _dec(acc.get("long_lived_user_token_encrypted"))
            if not page_token:
                return {"ok": False, "error": "Token de Page indisponible — relancez Rafraîchir"}

            if target.target == "fb_feed":
                return await _publish_facebook_video(
                    page_id=target.page_id, page_token=page_token,
                    file_path=file_path, caption=caption,
                )
            elif target.target in ("ig_story", "ig_reel"):
                ig_id = page.get("ig_business_account_id")
                if not ig_id:
                    return {"ok": False, "error": "Aucun compte Instagram Business lié à cette Page"}
                if not user_token:
                    return {"ok": False, "error": "Token utilisateur indisponible — reconnectez Meta"}
                return await _publish_instagram_video(
                    ig_user_id=ig_id, user_token=user_token,
                    asset_id=asset_id, caption=caption,
                    media_type=("STORIES" if target.target == "ig_story" else "REELS"),
                )
            else:
                return {"ok": False, "error": f"Cible inconnue: {target.target}"}
        except HTTPException as exc:
            return {"ok": False, "error": str(exc.detail)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[story_studio] publish target failed")
            return {"ok": False, "error": str(exc)}

    async def _publish_facebook_video(
        *, page_id: str, page_token: str, file_path: str, caption: str,
    ) -> Dict[str, Any]:
        """Upload + publication d'une vidéo dans le feed d'une Page FB.

        Utilise l'endpoint historique non-resumable (POST multipart) qui reste
        supporté pour les vidéos < 1 Go — suffisant pour des vidéos Sora 2 de
        4 à 12 sec (typiquement < 50 Mo)."""
        url = f"{GRAPH_VIDEO_BASE}/{page_id}/videos"
        async with httpx.AsyncClient(timeout=600.0) as client:
            with open(file_path, "rb") as fh:
                files = {"source": (Path(file_path).name, fh, "video/mp4")}
                data = {
                    "access_token": page_token,
                    "description": caption,
                    "published": "true",
                }
                r = await client.post(url, data=data, files=files)
            if r.status_code >= 400:
                try:
                    err = r.json().get("error", {})
                    return {"ok": False, "error": f"FB error {err.get('code')}: {err.get('message') or r.text[:200]}"}
                except (ValueError, KeyError):
                    return {"ok": False, "error": f"FB HTTP {r.status_code}: {r.text[:200]}"}
            video_id = r.json().get("id")
            return {"ok": True, "channel_id": video_id, "platform": "facebook"}

    async def _publish_instagram_video(
        *, ig_user_id: str, user_token: str, asset_id: str, caption: str, media_type: str,
    ) -> Dict[str, Any]:
        """Publie une vidéo en STORIES ou REELS sur Instagram.

        Stratégie: on génère une URL publique signée court terme pour notre
        vidéo locale, et on passe `video_url=` à Meta. Meta télécharge et
        traite. On poll le statut du container puis on publie."""
        base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
        if not base:
            return {"ok": False, "error": "PUBLIC_BASE_URL non défini, IG publication impossible"}
        token = _signed_media_token(asset_id, ttl_minutes=60)
        video_url = f"{base}/api/admin/story-studio/library/{asset_id}/signed-media?token={token}"

        params: Dict[str, Any] = {
            "media_type": media_type,
            "video_url": video_url,
            "access_token": user_token,
        }
        if media_type == "REELS":
            params["caption"] = caption
        # NB: For STORIES, Meta ignores caption (no captions on Stories video).

        async with httpx.AsyncClient(timeout=60.0) as client:
            # 1) Create container
            create = await _meta_post(client, f"{GRAPH_BASE}/{ig_user_id}/media", params=params)
            container_id = create.get("id")
            if not container_id:
                return {"ok": False, "error": f"Pas de container_id : {create!r:.200}"}

            # 2) Poll container status until FINISHED
            status_url = f"{GRAPH_BASE}/{container_id}"
            for _ in range(60):  # max 5 min (60 * 5s)
                st = await _meta_get(client, status_url, {
                    "fields": "status_code,status",
                    "access_token": user_token,
                })
                code_ = st.get("status_code")
                if code_ == "FINISHED":
                    break
                if code_ == "ERROR":
                    return {"ok": False, "error": f"IG processing error: {st.get('status') or st!r:.200}"}
                await asyncio.sleep(5)
            else:
                return {"ok": False, "error": "Timeout traitement IG (>5 min)"}

            # 3) Publish
            pub = await _meta_post(client, f"{GRAPH_BASE}/{ig_user_id}/media_publish", params={
                "creation_id": container_id,
                "access_token": user_token,
            })
            media_id = pub.get("id")
            if not media_id:
                return {"ok": False, "error": f"Pas de media_id à la publication : {pub!r:.200}"}
            return {"ok": True, "channel_id": media_id, "platform": "instagram",
                    "ig_target": media_type.lower()}

    # ========================================================================
    # Iter43-fix13 — Phase 3 multi-tenant billing helpers (closure over db)
    # ========================================================================
    DEFAULT_PRICING = {"fb_feed": 200, "ig_story": 300, "ig_reel": 500, "tiktok": 500}

    async def _get_tenant_billing_config(tenant_id: str) -> Dict[str, Any]:
        if not tenant_id:
            return {
                "tenant_id": "", "pricing": DEFAULT_PRICING.copy(),
                "currency": "XOF", "billing_mode": "credits_first",
                "credits_balance": 0, "monthly_invoice_day": 1,
            }
        doc = await db.tenant_publish_config.find_one({"tenant_id": tenant_id}, {"_id": 0})
        if not doc:
            return {
                "tenant_id": tenant_id, "pricing": DEFAULT_PRICING.copy(),
                "currency": "XOF", "billing_mode": "credits_first",
                "credits_balance": 0, "monthly_invoke_day": 1, "monthly_invoice_day": 1,
            }
        merged = DEFAULT_PRICING.copy()
        merged.update(doc.get("pricing") or {})
        doc["pricing"] = merged
        return doc

    async def _resolve_billing_tenant(post_doc: Dict[str, Any], targets: List[PublishTarget]) -> Optional[str]:
        """Le tenant facturé = celui qui possède le 1er social_account ciblé."""
        if not targets:
            return post_doc.get("tenant_id")
        first = targets[0]
        acc = await db.social_accounts.find_one(
            {"id": first.social_account_id}, {"_id": 0, "tenant_id": 1},
        )
        return (acc or {}).get("tenant_id") or post_doc.get("tenant_id")

    async def _charge_publication(
        *, tenant_id: str, post_id: str, target: PublishTarget,
        success: bool, asset_id: str, channel_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Facture (succès uniquement) : débit crédits OU provision facture mensuelle."""
        if not tenant_id or not success:
            return {"cost": 0, "currency": "XOF", "mode": "free", "billed": False}
        cfg = await _get_tenant_billing_config(tenant_id)
        cost = int(cfg["pricing"].get(target.target, 0))
        currency = cfg["currency"]
        billing_mode = cfg["billing_mode"]
        balance = int(cfg.get("credits_balance") or 0)

        debit_credits = 0
        invoice_debit = 0
        if cost == 0:
            settlement = "free"
        elif billing_mode == "credits_only":
            if balance < cost:
                settlement = "unbilled_no_credits"
                invoice_debit = cost
            else:
                debit_credits = cost
                settlement = "credits"
        elif billing_mode == "invoice_only":
            invoice_debit = cost
            settlement = "invoice"
        else:  # credits_first
            if balance >= cost:
                debit_credits = cost
                settlement = "credits"
            else:
                debit_credits = balance
                invoice_debit = cost - balance
                settlement = "mixed" if debit_credits else "invoice"

        new_balance = balance - debit_credits
        if debit_credits > 0:
            await db.tenant_publish_config.update_one(
                {"tenant_id": tenant_id},
                {"$inc": {"credits_balance": -debit_credits},
                 "$set": {"updated_at": _now_iso()}},
                upsert=True,
            )

        await db.tenant_publish_ledger.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tenant_id,
            "type": "publish_charge", "post_id": post_id, "asset_id": asset_id,
            "target": target.target, "social_account_id": target.social_account_id,
            "channel_id": channel_id, "cost": cost, "currency": currency,
            "debit_credits": debit_credits, "invoice_debit": invoice_debit,
            "balance_after": new_balance, "settlement": settlement,
            "period": _period_yyyymm(), "created_at": _now_iso(),
        })

        if invoice_debit > 0:
            period = _period_yyyymm()
            await db.tenant_publish_invoices.update_one(
                {"tenant_id": tenant_id, "period": period},
                {"$setOnInsert": {
                    "id": str(uuid.uuid4()), "tenant_id": tenant_id,
                    "period": period, "currency": currency,
                    "status": "open", "created_at": _now_iso(),
                },
                 "$inc": {"amount_due": invoice_debit, "publications_count": 1},
                 "$set": {"updated_at": _now_iso()}},
                upsert=True,
            )

        return {
            "cost": cost, "currency": currency, "mode": settlement, "billed": True,
            "debit_credits": debit_credits, "invoice_debit": invoice_debit,
            "balance_after": new_balance,
        }

    async def _check_credits_before_publish(
        tenant_id: str, targets: List[PublishTarget],
    ) -> Optional[str]:
        """Pre-flight (mode credits_only uniquement)."""
        if not tenant_id or not targets:
            return None
        cfg = await _get_tenant_billing_config(tenant_id)
        if cfg["billing_mode"] != "credits_only":
            return None
        total = sum(int(cfg["pricing"].get(t.target, 0)) for t in targets)
        balance = int(cfg.get("credits_balance") or 0)
        if balance < total:
            return (
                f"Crédits insuffisants : {balance} {cfg['currency']} disponibles, "
                f"{total} {cfg['currency']} requis."
            )
        return None

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
            rel_url = f"/admin/story-studio/library/{asset_id}/media"
            # Iter43-fix15 — Estimation de la consommation (1 image Nano Banana)
            usage_estimate = _compute_usage_estimate(
                engine="nano-banana", size="1024x1536", kind="image",
            )
            await db.story_assets.update_one(
                {"id": asset_id},
                {"$set": {"status": "ready", "url": rel_url, "file_path": str(out_path),
                          "file_size": len(img_bytes),
                          "usage_estimate": usage_estimate,
                          "updated_at": _now_iso()}},
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
        # Iter43-fix10a — Migration douce : si l'URL est l'ancienne forme
        # `/uploads/stories/...`, on la remplace par l'endpoint streaming.
        for it in items:
            url = it.get("url") or ""
            if url.startswith("/uploads/"):
                it["url"] = f"/admin/story-studio/library/{it['id']}/media"
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
        if payload.title is not None:
            update_set["title"] = payload.title
        if payload.caption is not None:
            update_set["caption"] = payload.caption
        if payload.tags is not None:
            update_set["tags"] = payload.tags
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
        fpath = doc.get("file_path")
        if fpath:
            try:
                p = Path(fpath)
                if p.exists():
                    p.unlink()
            except Exception:  # noqa: BLE001
                logger.warning("[story_studio] failed to unlink %s", fpath)
        await db.story_assets.delete_one({"id": asset_id})
        return {"ok": True}

    # ========================================================================
    # MEDIA STREAMING — Iter43-fix10a
    # Sert le fichier vidéo/image généré (auth requise = admin OR sup).
    # ========================================================================
    @api.get("/admin/story-studio/library/{asset_id}/media", tags=["Admin — Story Studio"])
    async def stream_asset_media(
        asset_id: str,
        user: dict = Depends(get_admin_or_supervisor),
    ):
        from fastapi.responses import FileResponse
        doc = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Asset introuvable")
        if doc.get("status") not in ("ready", "expired"):
            raise HTTPException(status_code=400, detail=f"Asset non prêt (statut: {doc.get('status')})")
        # Iter43-fix24k — Helper résilient : vérifie le fichier local, sinon
        # tente la re-download depuis source_url (Fal.ai CDN), sinon marque expired.
        fpath = await _ensure_local_file(doc)
        if not fpath:
            logger.error("[story_studio] file unrecoverable for asset=%s", asset_id)
            raise HTTPException(
                status_code=410,
                detail=(
                    "Vidéo expirée — le fichier local a été perdu (redéploiement) "
                    "et l'URL source n'est plus accessible. Régénérez l'asset."
                ),
            )
        media_type = "video/mp4" if doc.get("kind") == "video" else "image/png"
        return FileResponse(
            fpath,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )

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
        # Construit l'URL publique du média. Le doc.url commence par /admin/...
        # (sans /api/) car les clients utilisent apiClient avec baseURL=BACKEND/api.
        # Pour un partage externe (WhatsApp), il faut une URL complète absolue.
        public_base = (
            os.environ.get("PUBLIC_BACKEND_URL")
            or os.environ.get("REACT_APP_BACKEND_URL")
            or ""
        )
        rel = doc["url"]
        if not rel.startswith("/api/"):
            rel = "/api" + rel if rel.startswith("/") else "/api/" + rel
        media_url = f"{public_base}{rel}"
        caption = doc.get("caption") or doc.get("title") or "Nouvelle Story SAWALI ✨"
        # Iter43-fix10a — Le deep link contient SEULEMENT la légende (pas le
        # media_url qui requiert une auth Bearer). L'admin télécharge la
        # vidéo séparément puis l'attache dans WhatsApp.
        wa_link = f"whatsapp://send?text={urllib.parse.quote(caption)}"
        web_fallback = f"https://wa.me/?text={urllib.parse.quote(caption)}"
        return {
            "ok": True,
            "deep_link": wa_link,
            "web_fallback": web_fallback,
            "media_url": media_url,  # informatif uniquement (auth requise)
            "caption": caption,
            "instructions": (
                "1) Téléchargez la vidéo via le bouton « Télécharger » de la "
                "bibliothèque. 2) Ouvrez WhatsApp sur votre mobile → onglet "
                "« Status » → caméra → sélectionnez la vidéo téléchargée → "
                "collez la légende → Publier."
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
        # NB: exclude raw tokens but keep encrypted page tokens (still encrypted)
        items = await db.social_accounts.find(
            q,
            {"_id": 0, "access_token": 0,
             "long_lived_user_token_encrypted": 0},
        ).sort("created_at", -1).to_list(500)
        # Strip page-level encrypted tokens (frontend never needs them)
        for it in items:
            for p in (it.get("pages") or []):
                p.pop("page_access_token_encrypted", None)
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
    # PUBLICATION RÉELLE (Iter43-fix11 — Phase 2)
    # Publie un asset vidéo vers IG Story / IG Reel / FB Page Feed.
    # ========================================================================
    @api.post("/admin/story-studio/library/{asset_id}/publish", tags=["Admin — Story Studio"])
    async def publish_asset(
        asset_id: str,
        payload: PublishRequest,
        user: dict = Depends(get_admin_or_supervisor),
    ):
        """Publie une vidéo générée vers les réseaux sociaux sélectionnés.

        - `mode=draft` enregistre l'intent sans appel Meta (utile pour planifier).
        - `mode=immediate` appelle l'API Graph pour chaque target.
        Chaque target reçoit son propre statut dans la réponse — un échec
        partiel n'empêche pas les autres canaux d'aboutir.
        """
        doc = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Asset introuvable")
        if doc.get("kind") != "video":
            raise HTTPException(status_code=400, detail="Seules les vidéos sont publiables actuellement")
        if doc.get("status") != "ready":
            raise HTTPException(status_code=400, detail="Asset non prêt (génération en cours ou échouée)")
        if not payload.targets:
            raise HTTPException(status_code=400, detail="Aucune cible sélectionnée")

        post_id = str(uuid.uuid4())
        post_doc: Dict[str, Any] = {
            "id": post_id,
            "asset_id": asset_id,
            "tenant_id": doc.get("tenant_id"),
            "caption": payload.caption or doc.get("caption") or doc.get("title") or "",
            "mode": payload.mode,
            "scheduled_at": payload.scheduled_at,
            "status": "draft" if payload.mode == "draft" else "publishing",
            "targets": [t.model_dump() for t in payload.targets],
            "results": [],
            "created_at": _now_iso(),
            "created_by": user.get("email"),
        }

        # Iter43-fix13 — Phase 3 : déterminer le tenant facturé
        billing_tenant_id = await _resolve_billing_tenant(post_doc, payload.targets)
        post_doc["billing_tenant_id"] = billing_tenant_id

        # Mode brouillon : aucune action Meta, juste persiste.
        if payload.mode == "draft":
            await db.story_posts.insert_one(post_doc.copy())
            return {"ok": True, "post_id": post_id, "status": "draft",
                    "message": "Brouillon enregistré. Publiez-le plus tard depuis la bibliothèque."}

        # Iter43-fix13 — pré-flight check credits si billing_mode=credits_only
        credit_err = await _check_credits_before_publish(billing_tenant_id, payload.targets)
        if credit_err:
            post_doc["status"] = "blocked_credits"
            post_doc["completed_at"] = _now_iso()
            post_doc["billing_error"] = credit_err
            await db.story_posts.insert_one(post_doc.copy())
            raise HTTPException(status_code=402, detail=credit_err)

        # Mode immédiat : appel Meta Graph API pour chaque cible.
        results: List[Dict[str, Any]] = []
        billing_summary: List[Dict[str, Any]] = []
        for tgt in payload.targets:
            res = await _publish_single_target(
                db_=db, asset_doc=doc, target=tgt,
                caption=post_doc["caption"], asset_id=asset_id,
            )
            # Iter43-fix13 — Facturation succès uniquement
            charge = await _charge_publication(
                tenant_id=billing_tenant_id or "", post_id=post_id, target=tgt,
                success=bool(res.get("ok")), asset_id=asset_id,
                channel_id=res.get("channel_id"),
            )
            billing_summary.append({**tgt.model_dump(), **charge})
            results.append({**tgt.model_dump(), **res, "billing": charge})

        any_failed = any(not r.get("ok") for r in results)
        any_success = any(r.get("ok") for r in results)
        post_doc["results"] = results
        post_doc["billing_summary"] = billing_summary
        post_doc["total_cost"] = sum(int(b.get("cost") or 0) for b in billing_summary if b.get("billed"))
        post_doc["status"] = (
            "failed" if not any_success else ("partial" if any_failed else "published")
        )
        post_doc["completed_at"] = _now_iso()
        await db.story_posts.insert_one(post_doc.copy())

        return {
            "ok": any_success,
            "post_id": post_id,
            "status": post_doc["status"],
            "results": results,
            "total_cost": post_doc["total_cost"],
            "currency": "XOF",
        }

    # Publish a draft (mode=immediate) later
    @api.post("/admin/story-studio/posts/{post_id}/publish-now", tags=["Admin — Story Studio"])
    async def publish_draft_now(post_id: str, user: dict = Depends(get_admin_or_supervisor)):
        post = await db.story_posts.find_one({"id": post_id}, {"_id": 0})
        if not post:
            raise HTTPException(status_code=404, detail="Post introuvable")
        if post.get("status") not in ("draft", "failed", "blocked_credits"):
            raise HTTPException(status_code=400, detail=f"Post déjà en état '{post.get('status')}'")
        asset = await db.story_assets.find_one({"id": post["asset_id"]}, {"_id": 0})
        if not asset:
            raise HTTPException(status_code=404, detail="Asset associé introuvable")
        targets = [PublishTarget(**t) for t in post.get("targets", [])]

        # Iter43-fix13 — re-check billing
        billing_tenant_id = post.get("billing_tenant_id") or await _resolve_billing_tenant(post, targets)
        credit_err = await _check_credits_before_publish(billing_tenant_id, targets)
        if credit_err:
            await db.story_posts.update_one(
                {"id": post_id},
                {"$set": {"status": "blocked_credits", "billing_error": credit_err,
                          "completed_at": _now_iso()}},
            )
            raise HTTPException(status_code=402, detail=credit_err)

        results: List[Dict[str, Any]] = []
        billing_summary: List[Dict[str, Any]] = []
        for tgt in targets:
            res = await _publish_single_target(
                db_=db, asset_doc=asset, target=tgt,
                caption=post.get("caption") or "", asset_id=asset["id"],
            )
            charge = await _charge_publication(
                tenant_id=billing_tenant_id or "", post_id=post_id, target=tgt,
                success=bool(res.get("ok")), asset_id=asset["id"],
                channel_id=res.get("channel_id"),
            )
            billing_summary.append({**tgt.model_dump(), **charge})
            results.append({**tgt.model_dump(), **res, "billing": charge})
        any_failed = any(not r.get("ok") for r in results)
        any_success = any(r.get("ok") for r in results)
        new_status = "failed" if not any_success else ("partial" if any_failed else "published")
        total_cost = sum(int(b.get("cost") or 0) for b in billing_summary if b.get("billed"))
        await db.story_posts.update_one(
            {"id": post_id},
            {"$set": {
                "status": new_status, "results": results,
                "billing_summary": billing_summary, "total_cost": total_cost,
                "billing_tenant_id": billing_tenant_id,
                "completed_at": _now_iso(),
            }},
        )
        return {"ok": any_success, "status": new_status, "results": results,
                "total_cost": total_cost, "currency": "XOF"}

    # ========================================================================
    # Iter43-fix13 — Phase 3 multi-tenant monétisation (endpoints)
    # ========================================================================
    @api.get("/admin/story-studio/billing/tenants/{tenant_id}/config",
             tags=["Admin — Story Studio Billing"])
    async def get_tenant_billing_config(tenant_id: str, _: dict = Depends(get_current_admin)):
        return await _get_tenant_billing_config(tenant_id)

    @api.put("/admin/story-studio/billing/tenants/{tenant_id}/config",
             tags=["Admin — Story Studio Billing"])
    async def update_tenant_billing_config(
        tenant_id: str,
        payload: TenantPublishConfigUpsert,
        user: dict = Depends(get_current_admin),
    ):
        existing = await db.tenant_publish_config.find_one({"tenant_id": tenant_id}) or {}
        update_doc = {
            "tenant_id": tenant_id,
            "pricing": payload.pricing.model_dump(),
            "currency": payload.currency,
            "billing_mode": payload.billing_mode,
            "monthly_invoice_day": payload.monthly_invoice_day,
            "notes": payload.notes,
            "updated_at": _now_iso(),
            "updated_by": user.get("email"),
        }
        if not existing:
            update_doc["id"] = str(uuid.uuid4())
            update_doc["credits_balance"] = 0
            update_doc["created_at"] = _now_iso()
        await db.tenant_publish_config.update_one(
            {"tenant_id": tenant_id}, {"$set": update_doc}, upsert=True,
        )
        return await _get_tenant_billing_config(tenant_id)

    @api.post("/admin/story-studio/billing/tenants/{tenant_id}/credits/topup",
              tags=["Admin — Story Studio Billing"])
    async def topup_credits(
        tenant_id: str,
        payload: CreditTopupRequest,
        user: dict = Depends(get_current_admin),
    ):
        """Ajoute des crédits manuellement (admin only). Pour un topup via
        Stripe/PawaPay, créer d'abord la session de paiement côté CRM, puis
        appeler cet endpoint dans le webhook de confirmation."""
        cfg = await _get_tenant_billing_config(tenant_id)
        new_balance = int(cfg.get("credits_balance") or 0) + int(payload.amount_xof)
        await db.tenant_publish_config.update_one(
            {"tenant_id": tenant_id},
            {"$set": {"credits_balance": new_balance, "updated_at": _now_iso(),
                      "updated_by": user.get("email")},
             "$setOnInsert": {
                 "id": str(uuid.uuid4()), "tenant_id": tenant_id,
                 "pricing": DEFAULT_PRICING.copy(),
                 "currency": "XOF", "billing_mode": "credits_first",
                 "monthly_invoice_day": 1, "created_at": _now_iso(),
             }},
            upsert=True,
        )
        # Ledger entry
        await db.tenant_publish_ledger.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tenant_id, "type": "topup",
            "amount": int(payload.amount_xof), "currency": cfg["currency"],
            "balance_after": new_balance,
            "reason": payload.reason, "note": payload.note,
            "actor": user.get("email"),
            "period": _period_yyyymm(), "created_at": _now_iso(),
        })
        return {"ok": True, "tenant_id": tenant_id, "balance": new_balance,
                "currency": cfg["currency"]}

    @api.get("/admin/story-studio/billing/tenants/{tenant_id}/ledger",
             tags=["Admin — Story Studio Billing"])
    async def get_tenant_ledger(
        tenant_id: str,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        type_filter: Optional[str] = Query(None, alias="type"),
        _: dict = Depends(get_current_admin),
    ):
        q: Dict[str, Any] = {"tenant_id": tenant_id}
        if type_filter:
            q["type"] = type_filter
        total = await db.tenant_publish_ledger.count_documents(q)
        items = await (
            db.tenant_publish_ledger.find(q, {"_id": 0})
            .sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
        )
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    @api.get("/admin/story-studio/billing/tenants/{tenant_id}/invoices",
             tags=["Admin — Story Studio Billing"])
    async def list_tenant_invoices(tenant_id: str, _: dict = Depends(get_current_admin)):
        items = await db.tenant_publish_invoices.find(
            {"tenant_id": tenant_id}, {"_id": 0},
        ).sort("period", -1).to_list(200)
        return {"items": items}

    @api.put("/admin/story-studio/billing/invoices/{invoice_id}/status",
             tags=["Admin — Story Studio Billing"])
    async def update_invoice_status(
        invoice_id: str,
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        """Marque une facture comme payée / annulée / en attente."""
        new_status = (payload.get("status") or "").lower()
        if new_status not in {"open", "paid", "cancelled"}:
            raise HTTPException(status_code=400, detail="Statut invalide (open|paid|cancelled)")
        r = await db.tenant_publish_invoices.update_one(
            {"id": invoice_id},
            {"$set": {"status": new_status, "updated_at": _now_iso(),
                      "updated_by": user.get("email"),
                      **({"paid_at": _now_iso()} if new_status == "paid" else {})}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Facture introuvable")
        return {"ok": True, "status": new_status}

    @api.get("/admin/story-studio/billing/summary",
             tags=["Admin — Story Studio Billing"])
    async def billing_summary(_: dict = Depends(get_current_admin)):
        """Vue agrégée : total crédits en circulation, factures du mois, top consommateurs."""
        period = _period_yyyymm()
        total_credits_agg = await db.tenant_publish_config.aggregate([
            {"$group": {"_id": None, "total": {"$sum": "$credits_balance"}}}
        ]).to_list(1)
        total_credits = int(total_credits_agg[0]["total"]) if total_credits_agg else 0

        current_invoices = await db.tenant_publish_invoices.find(
            {"period": period}, {"_id": 0},
        ).to_list(500)
        current_total = sum(int(d.get("amount_due") or 0) for d in current_invoices)
        open_count = sum(1 for d in current_invoices if d.get("status") == "open")

        top_consumers = await db.tenant_publish_ledger.aggregate([
            {"$match": {"type": "publish_charge", "period": period}},
            {"$group": {
                "_id": "$tenant_id",
                "total_cost": {"$sum": "$cost"},
                "publications": {"$sum": 1},
            }},
            {"$sort": {"total_cost": -1}},
            {"$limit": 10},
        ]).to_list(10)

        return {
            "period": period,
            "currency": "XOF",
            "total_credits_in_circulation": total_credits,
            "current_period_invoices_total": current_total,
            "current_period_open_invoices": open_count,
            "top_consumers": [
                {"tenant_id": d["_id"], "total_cost": int(d.get("total_cost") or 0),
                 "publications": int(d.get("publications") or 0)}
                for d in top_consumers
            ],
        }

    @api.get("/admin/story-studio/billing/tenants",
             tags=["Admin — Story Studio Billing"])
    async def list_tenants_with_billing(_: dict = Depends(get_current_admin)):
        """Liste tous les tenants ayant déjà une config billing OU au moins un social_account."""
        # Tenants ayant un config
        cfg_tenants = await db.tenant_publish_config.find({}, {"_id": 0}).to_list(500)
        cfg_map = {c["tenant_id"]: c for c in cfg_tenants}

        # Tenants ayant des social_accounts
        sa_tenants_cur = db.social_accounts.distinct("tenant_id")
        sa_tenants = await sa_tenants_cur
        for tid in sa_tenants:
            if tid and tid not in cfg_map:
                cfg_map[tid] = {
                    "tenant_id": tid, "pricing": DEFAULT_PRICING.copy(),
                    "currency": "XOF", "billing_mode": "credits_first",
                    "credits_balance": 0, "monthly_invoice_day": 1,
                }
        # Enrichir avec stats du mois courant
        period = _period_yyyymm()
        items = list(cfg_map.values())
        for it in items:
            tid = it["tenant_id"]
            ledger_agg = await db.tenant_publish_ledger.aggregate([
                {"$match": {"tenant_id": tid, "type": "publish_charge", "period": period}},
                {"$group": {"_id": None, "total": {"$sum": "$cost"},
                            "count": {"$sum": 1}}},
            ]).to_list(1)
            it["current_period_total"] = int(ledger_agg[0]["total"]) if ledger_agg else 0
            it["current_period_publications"] = int(ledger_agg[0]["count"]) if ledger_agg else 0
            # User info enrich (si possible)
            user = await db.users.find_one({"id": tid}, {"_id": 0, "email": 1, "name": 1, "company": 1})
            if user:
                it["tenant_email"] = user.get("email")
                it["tenant_label"] = user.get("name") or user.get("company") or user.get("email")
        items.sort(key=lambda x: x.get("current_period_total", 0), reverse=True)
        return {"items": items, "period": period}


    # List posts history
    @api.get("/admin/story-studio/posts", tags=["Admin — Story Studio"])
    async def list_posts(
        tenant_id: Optional[str] = None,
        limit: int = 100,
        user: dict = Depends(get_admin_or_supervisor),
    ):
        q: Dict[str, Any] = {}
        if (user.get("role") or "").lower() != "admin":
            q["tenant_id"] = user.get("parent_client_id") or user["id"]
        elif tenant_id:
            q["tenant_id"] = tenant_id
        items = await db.story_posts.find(q, {"_id": 0}).sort("created_at", -1).limit(min(limit, 500)).to_list(min(limit, 500))
        return {"items": items, "count": len(items)}

    # ========================================================================
    # OAUTH META — Phase 2
    # ========================================================================
    @api.get("/admin/story-studio/oauth/meta/start", tags=["Admin — Story Studio"])
    async def meta_oauth_start(
        tenant_id: Optional[str] = Query(None),
        return_to: Optional[str] = Query(None),
        user: dict = Depends(get_current_admin),
    ):
        """Génère l'URL d'autorisation Meta. Le front l'utilise pour rediriger.

        Le `state` est un JWT signé qui transporte le tenant_id cible + l'admin
        appelant. Meta nous renverra sur le callback backend qui décodera ce
        state pour rattacher le compte au bon tenant."""
        app_id, app_secret = await _get_meta_app_credentials(db)
        if not app_id or not app_secret:
            raise HTTPException(
                status_code=400,
                detail="Meta App ID/Secret non configurés. Renseignez-les dans Paramètres → Meta.",
            )
        redirect_uri = await _resolve_meta_redirect_uri(db)
        tenant = tenant_id or user.get("parent_client_id") or user["id"]
        state = _oauth_state_encode({
            "tenant_id": tenant,
            "caller_id": user["id"],
            "caller_email": user.get("email"),
            "return_to": return_to or "/admin/story-studio",
        })
        scope = ",".join(META_OAUTH_SCOPES)
        auth_url = (
            "https://www.facebook.com/" + GRAPH_API_VERSION + "/dialog/oauth"
            f"?client_id={urllib.parse.quote(app_id)}"
            f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
            f"&state={urllib.parse.quote(state)}"
            f"&scope={urllib.parse.quote(scope)}"
            "&response_type=code"
        )
        logger.info(f"[story_studio] oauth meta start tenant={tenant} caller={user.get('email')}")
        return {"auth_url": auth_url, "redirect_uri": redirect_uri}

    @api.get("/admin/story-studio/oauth/meta/callback", tags=["Admin — Story Studio"])
    async def meta_oauth_callback(
        request: Request,
        code: Optional[str] = Query(None),
        state: Optional[str] = Query(None),
        error: Optional[str] = Query(None),
        error_description: Optional[str] = Query(None),
    ):
        """Endpoint PUBLIC appelé par Meta après authentification utilisateur.

        Décode le state, échange le code contre un token court → long-lived,
        récupère les Pages + IG accounts, persiste le tout en `social_accounts`
        (tokens encryptés), puis redirige vers le front."""
        # Resolve frontend redirect base for both success & error
        frontend_base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
        return_to = "/admin/story-studio"
        try:
            if state:
                try:
                    st = _oauth_state_decode(state)
                    return_to = st.get("return_to") or "/admin/story-studio"
                except HTTPException:
                    pass

            if error:
                msg = error_description or error
                logger.warning(f"[story_studio] meta oauth error from Meta: {msg}")
                return RedirectResponse(url=f"{frontend_base}{return_to}?meta_oauth=error&reason={urllib.parse.quote(msg)}")

            if not code or not state:
                raise HTTPException(status_code=400, detail="Paramètres OAuth manquants")

            st = _oauth_state_decode(state)
            tenant_id = st["tenant_id"]
            caller_email = st.get("caller_email")

            app_id, app_secret = await _get_meta_app_credentials(db)
            if not app_id or not app_secret:
                raise HTTPException(status_code=500, detail="Meta App credentials manquants côté serveur")
            redirect_uri = await _resolve_meta_redirect_uri(db)

            async with httpx.AsyncClient(timeout=30.0) as client:
                # 1) Exchange code -> short-lived user access token
                token_data = await _meta_get(client, f"{GRAPH_BASE}/oauth/access_token", {
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                })
                short_token = token_data.get("access_token")
                if not short_token:
                    raise HTTPException(status_code=502, detail=f"Pas de access_token dans la réponse Meta: {token_data!r:.300}")

                # 2) Exchange for long-lived user token (~60 days)
                long_data = await _meta_get(client, f"{GRAPH_BASE}/oauth/access_token", {
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": short_token,
                })
                long_token = long_data.get("access_token") or short_token
                expires_in = int(long_data.get("expires_in") or 60 * 24 * 3600)

                # 3) Fetch FB user info
                me = await _meta_get(client, f"{GRAPH_BASE}/me", {
                    "fields": "id,name,email",
                    "access_token": long_token,
                })

                # 4) List Pages
                pages_resp = await _meta_get(client, f"{GRAPH_BASE}/me/accounts", {
                    "fields": "id,name,access_token,category,instagram_business_account{id,username,name}",
                    "access_token": long_token,
                    "limit": 100,
                })
                pages = []
                for p in pages_resp.get("data", []):
                    ig = p.get("instagram_business_account") or {}
                    pages.append({
                        "page_id": p["id"],
                        "page_name": p.get("name"),
                        "category": p.get("category"),
                        "page_access_token_encrypted": _enc(p.get("access_token")),
                        "ig_business_account_id": ig.get("id"),
                        "ig_username": ig.get("username"),
                        "ig_name": ig.get("name"),
                        "is_active": True,  # active by default; admin can toggle
                    })

            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
            existing = await db.social_accounts.find_one({
                "tenant_id": tenant_id,
                "provider": "meta",
                "meta_user_id": me.get("id"),
            })

            doc = {
                "tenant_id": tenant_id,
                "provider": "meta",
                "status": "connected",
                "meta_user_id": me.get("id"),
                "meta_user_name": me.get("name"),
                "meta_user_email": me.get("email"),
                "long_lived_user_token_encrypted": _enc(long_token),
                "long_lived_user_token_expires_at": expires_at,
                "pages": pages,
                "updated_at": _now_iso(),
                "connected_by_email": caller_email,
            }
            if existing:
                await db.social_accounts.update_one({"id": existing["id"]}, {"$set": doc})
                account_id = existing["id"]
            else:
                doc["id"] = str(uuid.uuid4())
                doc["created_at"] = _now_iso()
                doc["account_label"] = f"Meta — {me.get('name') or me.get('id')}"
                doc["account_id"] = me.get("id")
                await db.social_accounts.insert_one(doc.copy())
                account_id = doc["id"]

            success_url = (
                f"{frontend_base}{return_to}"
                f"?meta_oauth=connected"
                f"&social_account_id={urllib.parse.quote(account_id)}"
                f"&pages={len(pages)}"
            )
            logger.info(f"[story_studio] meta oauth success tenant={tenant_id} pages={len(pages)} user={me.get('name')}")
            return RedirectResponse(url=success_url)

        except HTTPException as exc:
            logger.warning(f"[story_studio] meta oauth callback error: {exc.detail}")
            return RedirectResponse(
                url=f"{frontend_base}{return_to}?meta_oauth=error&reason={urllib.parse.quote(str(exc.detail))}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[story_studio] meta oauth callback unexpected error")
            return RedirectResponse(
                url=f"{frontend_base}{return_to}?meta_oauth=error&reason={urllib.parse.quote(str(exc))}"
            )

    @api.post("/admin/story-studio/social-accounts/{account_id}/refresh", tags=["Admin — Story Studio"])
    async def refresh_meta_account(account_id: str, _: dict = Depends(get_current_admin)):
        """Re-fetch les Pages et IG accounts d'un compte Meta connecté."""
        acc = await db.social_accounts.find_one({"id": account_id})
        if not acc:
            raise HTTPException(status_code=404, detail="Compte introuvable")
        if acc.get("provider") != "meta":
            raise HTTPException(status_code=400, detail="Pas un compte Meta")
        token = _dec(acc.get("long_lived_user_token_encrypted"))
        if not token:
            raise HTTPException(status_code=400, detail="Token utilisateur indisponible — reconnectez le compte")
        async with httpx.AsyncClient(timeout=30.0) as client:
            pages_resp = await _meta_get(client, f"{GRAPH_BASE}/me/accounts", {
                "fields": "id,name,access_token,category,instagram_business_account{id,username,name}",
                "access_token": token,
                "limit": 100,
            })
        # Preserve `is_active` flags from existing pages
        prev_active = {p["page_id"]: p.get("is_active", True) for p in (acc.get("pages") or [])}
        pages = []
        for p in pages_resp.get("data", []):
            ig = p.get("instagram_business_account") or {}
            pages.append({
                "page_id": p["id"],
                "page_name": p.get("name"),
                "category": p.get("category"),
                "page_access_token_encrypted": _enc(p.get("access_token")),
                "ig_business_account_id": ig.get("id"),
                "ig_username": ig.get("username"),
                "ig_name": ig.get("name"),
                "is_active": prev_active.get(p["id"], True),
            })
        await db.social_accounts.update_one(
            {"id": account_id},
            {"$set": {"pages": pages, "updated_at": _now_iso(), "status": "connected"}},
        )
        return {"ok": True, "pages_count": len(pages)}

    @api.put("/admin/story-studio/social-accounts/{account_id}/pages/{page_id}", tags=["Admin — Story Studio"])
    async def toggle_page_active(
        account_id: str, page_id: str,
        payload: Dict[str, Any] = Body(...),
        _: dict = Depends(get_current_admin),
    ):
        """Active/désactive une Page (page reste connue mais ignorée des publications)."""
        is_active = bool(payload.get("is_active", True))
        r = await db.social_accounts.update_one(
            {"id": account_id, "pages.page_id": page_id},
            {"$set": {"pages.$.is_active": is_active, "updated_at": _now_iso()}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Page non trouvée")
        return {"ok": True, "is_active": is_active}

    # ========================================================================
    # MEDIA SIGNED PUBLIC URL (pour les API Meta qui ont besoin d'un video_url)
    # ========================================================================
    @api.get("/admin/story-studio/library/{asset_id}/signed-media", tags=["Admin — Story Studio"])
    async def signed_public_media(asset_id: str, token: str):
        """Endpoint PUBLIC (signé par JWT court terme) — utilisé par Meta pour
        télécharger la vidéo lors d'un appel `video_url`."""
        verified_id = _verify_signed_media_token(token)
        if verified_id != asset_id:
            raise HTTPException(status_code=403, detail="Token / asset mismatch")
        from fastapi.responses import FileResponse
        doc = await db.story_assets.find_one({"id": asset_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Asset introuvable")
        # Iter43-fix24k — Résilience : re-download depuis source_url si fichier perdu
        fpath = await _ensure_local_file(doc)
        if not fpath:
            raise HTTPException(
                status_code=410,
                detail="Fichier perdu et URL source expirée (régénérez l'asset)",
            )
        media_type = "video/mp4" if doc.get("kind") == "video" else "image/png"
        return FileResponse(fpath, media_type=media_type)

    # ========================================================================
    # Iter43-fix14 — Phase 4 TikTok OAuth 2.0 + Direct Post API
    # ========================================================================
    async def _get_tiktok_credentials() -> tuple[Optional[str], Optional[str]]:
        doc = await db.settings.find_one({"_id": "global"}) or {}
        st = doc.get("story_studio") or {}
        return st.get("tiktok_client_key"), st.get("tiktok_client_secret")

    async def _resolve_tiktok_redirect_uri() -> str:
        doc = await db.settings.find_one({"_id": "global"}) or {}
        st = doc.get("story_studio") or {}
        configured = st.get("tiktok_redirect_uri")
        if configured:
            return configured
        base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
        if not base:
            raise HTTPException(status_code=500, detail="PUBLIC_BASE_URL non défini")
        return f"{base}/api/admin/story-studio/oauth/tiktok/callback"

    async def _get_valid_tiktok_token(account_id: str) -> str:
        """Retourne un access_token valide, en rafraîchissant si nécessaire."""
        acc = await db.social_accounts.find_one({"id": account_id})
        if not acc or acc.get("provider") != "tiktok":
            raise HTTPException(status_code=404, detail="Compte TikTok introuvable")
        now = datetime.now(timezone.utc)
        # Si l'access token est encore valide > 5min
        exp_str = acc.get("access_token_expires_at")
        if exp_str:
            exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            if (exp_dt - now).total_seconds() > 300:
                tok = _dec(acc.get("access_token_encrypted"))
                if tok:
                    return tok
        # Refresh
        refresh_tok = _dec(acc.get("refresh_token_encrypted"))
        if not refresh_tok:
            raise HTTPException(status_code=401, detail="Refresh token indisponible — reconnectez TikTok")
        client_key, client_secret = await _get_tiktok_credentials()
        if not client_key or not client_secret:
            raise HTTPException(status_code=500, detail="TikTok credentials manquants")
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(TIKTOK_TOKEN_URL, data={
                "client_key": client_key, "client_secret": client_secret,
                "grant_type": "refresh_token", "refresh_token": refresh_tok,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"TikTok refresh erreur : {r.text[:200]}")
        data = r.json().get("data") or r.json()
        new_access = data["access_token"]
        new_refresh = data.get("refresh_token", refresh_tok)
        expires_in = int(data.get("expires_in") or 86400)
        refresh_expires_in = int(data.get("refresh_expires_in") or 31536000)
        await db.social_accounts.update_one(
            {"id": account_id},
            {"$set": {
                "access_token_encrypted": _enc(new_access),
                "refresh_token_encrypted": _enc(new_refresh),
                "access_token_expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
                "refresh_token_expires_at": (now + timedelta(seconds=refresh_expires_in)).isoformat(),
                "updated_at": _now_iso(),
            }},
        )
        return new_access

    @api.get("/admin/story-studio/oauth/tiktok/start", tags=["Admin — Story Studio"])
    async def tiktok_oauth_start(
        tenant_id: Optional[str] = Query(None),
        return_to: Optional[str] = Query(None),
        user: dict = Depends(get_current_admin),
    ):
        ck, cs = await _get_tiktok_credentials()
        if not ck or not cs:
            raise HTTPException(
                status_code=400,
                detail="TikTok Client Key/Secret non configurés. Renseignez-les dans Paramètres → TikTok.",
            )
        redirect_uri = await _resolve_tiktok_redirect_uri()
        tenant = tenant_id or user.get("parent_client_id") or user["id"]
        state = _oauth_state_encode({
            "tenant_id": tenant, "caller_id": user["id"],
            "caller_email": user.get("email"),
            "return_to": return_to or "/admin/story-studio",
            "provider": "tiktok",
        })
        scope = ",".join(TIKTOK_OAUTH_SCOPES)
        params = {
            "client_key": ck, "response_type": "code", "scope": scope,
            "redirect_uri": redirect_uri, "state": state,
        }
        auth_url = f"{TIKTOK_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return {"auth_url": auth_url, "redirect_uri": redirect_uri}

    @api.get("/admin/story-studio/oauth/tiktok/callback", tags=["Admin — Story Studio"])
    async def tiktok_oauth_callback(
        request: Request,
        code: Optional[str] = Query(None),
        state: Optional[str] = Query(None),
        error: Optional[str] = Query(None),
        error_description: Optional[str] = Query(None),
    ):
        frontend_base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
        return_to = "/admin/story-studio"
        try:
            if state:
                try:
                    st = _oauth_state_decode(state)
                    return_to = st.get("return_to") or "/admin/story-studio"
                except HTTPException:
                    pass
            if error:
                msg = error_description or error
                return RedirectResponse(url=f"{frontend_base}{return_to}?tiktok_oauth=error&reason={urllib.parse.quote(msg)}")
            if not code or not state:
                raise HTTPException(status_code=400, detail="Paramètres manquants")
            st = _oauth_state_decode(state)
            tenant_id = st["tenant_id"]
            ck, cs = await _get_tiktok_credentials()
            if not ck or not cs:
                raise HTTPException(status_code=500, detail="TikTok credentials manquants")
            redirect_uri = await _resolve_tiktok_redirect_uri()

            async with httpx.AsyncClient(timeout=30.0) as client:
                tok_resp = await client.post(TIKTOK_TOKEN_URL, data={
                    "client_key": ck, "client_secret": cs, "code": code,
                    "grant_type": "authorization_code", "redirect_uri": redirect_uri,
                }, headers={"Content-Type": "application/x-www-form-urlencoded"})
                if tok_resp.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"TikTok token erreur : {tok_resp.text[:300]}")
                token_data = tok_resp.json().get("data") or tok_resp.json()
                access_token = token_data["access_token"]
                refresh_token = token_data["refresh_token"]
                expires_in = int(token_data.get("expires_in") or 86400)
                refresh_expires_in = int(token_data.get("refresh_expires_in") or 31536000)
                open_id = token_data.get("open_id")

                # Get user info
                ui_resp = await client.get(
                    TIKTOK_USERINFO_URL,
                    params={"fields": "open_id,union_id,avatar_url,display_name"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                user_info = (ui_resp.json().get("data") or {}).get("user") or {}

            now = datetime.now(timezone.utc)
            doc = {
                "tenant_id": tenant_id, "provider": "tiktok", "status": "connected",
                "tiktok_open_id": open_id or user_info.get("open_id"),
                "tiktok_display_name": user_info.get("display_name"),
                "tiktok_avatar_url": user_info.get("avatar_url"),
                "access_token_encrypted": _enc(access_token),
                "refresh_token_encrypted": _enc(refresh_token),
                "access_token_expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
                "refresh_token_expires_at": (now + timedelta(seconds=refresh_expires_in)).isoformat(),
                "scopes": TIKTOK_OAUTH_SCOPES,
                "updated_at": _now_iso(),
                "connected_by_email": st.get("caller_email"),
            }
            existing = await db.social_accounts.find_one({
                "tenant_id": tenant_id, "provider": "tiktok",
                "tiktok_open_id": doc["tiktok_open_id"],
            })
            if existing:
                await db.social_accounts.update_one({"id": existing["id"]}, {"$set": doc})
                account_id = existing["id"]
            else:
                doc["id"] = str(uuid.uuid4())
                doc["created_at"] = _now_iso()
                doc["account_label"] = f"TikTok — {user_info.get('display_name') or 'compte'}"
                doc["account_id"] = doc["tiktok_open_id"]
                await db.social_accounts.insert_one(doc.copy())
                account_id = doc["id"]
            return RedirectResponse(
                url=f"{frontend_base}{return_to}?tiktok_oauth=connected&social_account_id={account_id}",
            )
        except HTTPException as exc:
            return RedirectResponse(
                url=f"{frontend_base}{return_to}?tiktok_oauth=error&reason={urllib.parse.quote(str(exc.detail))}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[story_studio] tiktok oauth callback error")
            return RedirectResponse(
                url=f"{frontend_base}{return_to}?tiktok_oauth=error&reason={urllib.parse.quote(str(exc))}",
            )

    async def _publish_tiktok_video(*, account_id: str, file_path: str, caption: str) -> Dict[str, Any]:
        """Publie une vidéo via Direct Post (FILE_UPLOAD, single chunk).

        Iter43-fix24az-l (2026-02-26) — TikTok App Review compliance:
          * Unaudited apps can ONLY post to private accounts (SELF_ONLY).
          * `story_studio.tiktok_privacy_level` in `settings.global` allows the
            admin to force SELF_ONLY (default, until audit passes) or switch to
            PUBLIC_TO_EVERYONE / MUTUAL_FOLLOW_FRIENDS / FOLLOWER_OF_CREATOR
            after successful audit.
          * We call TikTok's `creator_info/query/` FIRST to validate the
            requested privacy_level is allowed for the connected account. If
            not, we return a friendly French error explaining the audit stage.
        """
        access_token = await _get_valid_tiktok_token(account_id)
        try:
            file_bytes = Path(file_path).read_bytes()
        except OSError as exc:
            return {"ok": False, "error": f"Fichier illisible : {exc}"}
        total_size = len(file_bytes)
        if total_size == 0:
            return {"ok": False, "error": "Fichier vide"}

        # Load admin config for the desired privacy level (default SELF_ONLY).
        settings_doc = await db.settings.find_one({"scope": "global"}) or {}
        story_cfg = (settings_doc.get("story_studio") or {}) if isinstance(settings_doc, dict) else {}
        # Also accept legacy top-level key for backward-compat
        desired_privacy = (
            story_cfg.get("tiktok_privacy_level")
            or settings_doc.get("tiktok_privacy_level")
            or "SELF_ONLY"
        )
        # Whitelist
        if desired_privacy not in ("SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"):
            desired_privacy = "SELF_ONLY"

        async with httpx.AsyncClient(timeout=120.0) as client:
            # 0) Pre-flight: creator_info/query/ to know allowed privacy levels
            try:
                cinfo_resp = await client.post(
                    "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
                    headers={"Authorization": f"Bearer {access_token}",
                             "Content-Type": "application/json; charset=utf-8"},
                    json={},
                )
                allowed_privacy: List[str] = []
                if cinfo_resp.status_code < 400:
                    cdata = cinfo_resp.json().get("data") or {}
                    allowed_privacy = cdata.get("privacy_level_options") or []
                # If the account restricts to SELF_ONLY (unaudited scenario), force it.
                if allowed_privacy and desired_privacy not in allowed_privacy:
                    if "SELF_ONLY" in allowed_privacy:
                        desired_privacy = "SELF_ONLY"
                    else:
                        desired_privacy = allowed_privacy[0]
            except httpx.HTTPError:
                # If creator_info fails, we still try with the configured default.
                pass
            # 1) Init Direct Post
            init_body = {
                "post_info": {
                    "title": caption[:150],
                    "privacy_level": desired_privacy,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": total_size,
                    "chunk_size": total_size,
                    "total_chunk_count": 1,
                },
            }
            init_resp = await client.post(
                TIKTOK_DIRECT_POST_INIT_URL,
                json=init_body,
                headers={"Authorization": f"Bearer {access_token}",
                         "Content-Type": "application/json; charset=utf-8"},
            )
            if init_resp.status_code >= 400:
                # Friendly message for the unaudited-app case.
                snippet = init_resp.text[:400]
                if "unaudited_client_can_only_post_to_private_accounts" in snippet:
                    return {"ok": False, "error": (
                        "TikTok — application non auditée : la publication n'est autorisée que "
                        "sur des comptes TikTok en mode PRIVÉ. Rendez votre compte TikTok privé "
                        "(profil → paramètres → confidentialité), ou attendez la validation de "
                        "l'audit TikTok avant d'activer les publications publiques."
                    )}
                return {"ok": False, "error": f"TikTok init {init_resp.status_code}: {snippet[:200]}"}
            init_data = init_resp.json().get("data") or init_resp.json()
            upload_url = init_data.get("upload_url")
            publish_id = init_data.get("publish_id")
            if not upload_url:
                return {"ok": False, "error": f"Pas d'upload_url : {init_data!r:.200}"}


            # 2) Binary upload (single chunk)
            upload_resp = await client.put(
                upload_url, content=file_bytes,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(total_size),
                    "Content-Range": f"bytes 0-{total_size - 1}/{total_size}",
                },
            )
            if upload_resp.status_code not in (200, 201, 204):
                return {"ok": False, "error": f"TikTok upload {upload_resp.status_code}: {upload_resp.text[:200]}"}

            return {"ok": True, "channel_id": publish_id, "platform": "tiktok"}

    # ========================================================================
    # Iter43-fix14 — Phase 2 Cron Scheduler (drafts scheduled_at → publish)
    # ========================================================================
    @api.post("/admin/story-studio/scheduler/tick", tags=["Admin — Story Studio"])
    async def scheduler_tick(
        max_posts: int = Query(20, ge=1, le=200),
        dry_run: bool = Query(False),
        _: dict = Depends(get_current_admin),
    ):
        """Endpoint à appeler par un cron externe (ex: every 5min) qui passe les
        posts `draft` avec `scheduled_at <= now` en `publishing` puis les exécute.

        Idempotent : ne traite que les posts pas encore exécutés."""
        now_iso = _now_iso()
        candidates = await db.story_posts.find({
            "mode": "draft",
            "status": "draft",
            "scheduled_at": {"$lte": now_iso, "$ne": None},
        }, {"_id": 0}).sort("scheduled_at", 1).limit(max_posts).to_list(max_posts)

        if dry_run:
            return {"would_process": len(candidates), "candidates": [
                {"id": p["id"], "scheduled_at": p.get("scheduled_at"),
                 "asset_id": p.get("asset_id")}
                for p in candidates
            ]}

        processed: List[Dict[str, Any]] = []
        for post in candidates:
            asset = await db.story_assets.find_one({"id": post["asset_id"]}, {"_id": 0})
            if not asset:
                await db.story_posts.update_one(
                    {"id": post["id"]},
                    {"$set": {"status": "failed", "billing_error": "Asset introuvable",
                              "completed_at": now_iso}},
                )
                processed.append({"id": post["id"], "status": "failed", "reason": "asset_missing"})
                continue
            targets = [PublishTarget(**t) for t in post.get("targets", [])]
            billing_tenant_id = post.get("billing_tenant_id") or await _resolve_billing_tenant(post, targets)
            credit_err = await _check_credits_before_publish(billing_tenant_id, targets)
            if credit_err:
                await db.story_posts.update_one(
                    {"id": post["id"]},
                    {"$set": {"status": "blocked_credits", "billing_error": credit_err,
                              "completed_at": now_iso}},
                )
                processed.append({"id": post["id"], "status": "blocked_credits"})
                continue
            results = []
            billing_summary = []
            for tgt in targets:
                res = await _publish_single_target(
                    db_=db, asset_doc=asset, target=tgt,
                    caption=post.get("caption") or "", asset_id=asset["id"],
                )
                charge = await _charge_publication(
                    tenant_id=billing_tenant_id or "", post_id=post["id"], target=tgt,
                    success=bool(res.get("ok")), asset_id=asset["id"],
                    channel_id=res.get("channel_id"),
                )
                billing_summary.append({**tgt.model_dump(), **charge})
                results.append({**tgt.model_dump(), **res, "billing": charge})
            any_failed = any(not r.get("ok") for r in results)
            any_success = any(r.get("ok") for r in results)
            new_status = "failed" if not any_success else ("partial" if any_failed else "published")
            await db.story_posts.update_one(
                {"id": post["id"]},
                {"$set": {"status": new_status, "results": results,
                          "billing_summary": billing_summary,
                          "total_cost": sum(int(b.get("cost") or 0) for b in billing_summary if b.get("billed")),
                          "completed_at": now_iso,
                          "executed_by_scheduler": True}},
            )
            processed.append({"id": post["id"], "status": new_status})

        return {"processed": len(processed), "results": processed}

    # ========================================================================
    # Iter43-fix14 — Phase 2 Analytics IG/FB Insights
    # ========================================================================
    @api.get("/admin/story-studio/posts/{post_id}/insights",
             tags=["Admin — Story Studio"])
    async def fetch_post_insights(post_id: str, _: dict = Depends(get_current_admin)):
        """Récupère likes/reach/impressions pour chaque cible d'un post publié.

        - IG : utilise /v23.0/{ig_media_id}/insights
        - FB : utilise /v23.0/{video_id}/video_insights (ou /insights selon disponibilité)
        - TikTok : non encore supporté (Phase 5)
        """
        post = await db.story_posts.find_one({"id": post_id}, {"_id": 0})
        if not post:
            raise HTTPException(status_code=404, detail="Post introuvable")
        if post.get("status") not in ("published", "partial"):
            raise HTTPException(status_code=400, detail=f"Post non publié (status={post.get('status')})")

        results: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for r in (post.get("results") or []):
                if not r.get("ok"):
                    continue
                target = r.get("target")
                channel_id = r.get("channel_id")
                if not channel_id:
                    continue

                # Trouve le compte social et son token
                acc = await db.social_accounts.find_one({"id": r.get("social_account_id")})
                if not acc:
                    results.append({"target": target, "channel_id": channel_id,
                                    "error": "Compte social introuvable"})
                    continue

                try:
                    if target in ("ig_story", "ig_reel"):
                        user_token = _dec(acc.get("long_lived_user_token_encrypted"))
                        if not user_token:
                            raise ValueError("Token IG indisponible")
                        # IG Insights métriques (varient selon le type)
                        metrics = (
                            "impressions,reach,replies"
                            if target == "ig_story"
                            else "comments,likes,plays,reach,total_interactions,shares,saved"
                        )
                        ins = await _meta_get(client, f"{GRAPH_BASE}/{channel_id}/insights", {
                            "metric": metrics, "access_token": user_token,
                        })
                        kv = {d["name"]: d.get("values", [{}])[0].get("value") for d in ins.get("data", [])}
                        results.append({"target": target, "channel_id": channel_id, "platform": "instagram",
                                        "metrics": kv})
                    elif target == "fb_feed":
                        # FB Page Video : besoin du page_token
                        page_id = r.get("page_id")
                        page = next((p for p in (acc.get("pages") or [])
                                     if p.get("page_id") == page_id), None)
                        page_token = _dec((page or {}).get("page_access_token_encrypted"))
                        if not page_token:
                            raise ValueError("Token de Page FB indisponible")
                        ins = await _meta_get(client, f"{GRAPH_BASE}/{channel_id}", {
                            "fields": "views,likes.summary(true),comments.summary(true),shares",
                            "access_token": page_token,
                        })
                        results.append({"target": target, "channel_id": channel_id, "platform": "facebook",
                                        "metrics": {
                                            "views": ins.get("views"),
                                            "likes": (ins.get("likes") or {}).get("summary", {}).get("total_count"),
                                            "comments": (ins.get("comments") or {}).get("summary", {}).get("total_count"),
                                            "shares": (ins.get("shares") or {}).get("count"),
                                        }})
                    elif target == "tiktok":
                        results.append({"target": target, "channel_id": channel_id,
                                        "error": "TikTok insights non encore supporté"})
                except HTTPException as exc:
                    results.append({"target": target, "channel_id": channel_id, "error": str(exc.detail)})
                except Exception as exc:  # noqa: BLE001
                    results.append({"target": target, "channel_id": channel_id, "error": str(exc)})

        # Cache dans le post pour évite re-fetch
        await db.story_posts.update_one(
            {"id": post_id},
            {"$set": {"insights": results, "insights_fetched_at": _now_iso()}},
        )
        return {"post_id": post_id, "insights": results}

    logger.info("[story_studio] routes mounted (Phase 1 MVP)")
