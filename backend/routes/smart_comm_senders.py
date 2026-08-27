"""2026-02 fork (P0.5 extended) — Tenant-scoped social senders.

Adds a family of endpoints that let a tenant post on THEIR OWN Smart-Comm
credentials (LinkedIn / Meta / X / Instagram / TikTok) via a single, uniform
interface. Falls back to global settings when the tenant hasn't configured
Smart Comm for that channel yet.

Endpoints (all under /api):
  POST /me/social/linkedin/post   {text, image_url?, org_urn?}  → publishes on LinkedIn
  POST /me/social/meta/post       {message, page_id?, link?, image_url?} → Facebook page feed
  POST /me/social/x/post          {text}                        → X (Twitter) tweet
  GET  /me/social/status                                        → what channels this tenant can use
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets as pysecrets
import time
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.smart_comm_senders")

LINKEDIN_API_BASE = "https://api.linkedin.com"
LINKEDIN_API_VERSION = "202401"
X_API_V2_BASE = "https://api.twitter.com/2"
X_UPLOAD_V1_1 = "https://upload.twitter.com/1.1/media/upload.json"


def _tenant_id_for(user: dict) -> str:
    return user.get("parent_client_id") or user.get("client_id") or user.get("id") or ""


def _require_channel_operator(user: dict) -> None:
    if user.get("role") not in ("admin", "superviseur", "moderator", "marketing", "communication"):
        raise HTTPException(status_code=403, detail="Réservé aux rôles admin / superviseur / marketing")


# =============================================================================
# OAuth 1.0a signing (X / Twitter)
# =============================================================================
def _oauth1_percent_encode(value: str) -> str:
    """RFC 3986 percent encoding used by OAuth 1.0a (safe='')."""
    return quote(str(value), safe="")


def _oauth1_build_signature(
    *,
    method: str,
    url: str,
    oauth_params: Dict[str, str],
    consumer_secret: str,
    token_secret: str,
    body_params: Optional[Dict[str, str]] = None,
) -> str:
    """Compute HMAC-SHA1 signature for OAuth 1.0a.

    - `oauth_params` : dict of oauth_* params (all except oauth_signature).
    - `body_params`  : additional form-encoded body params (e.g. `status=…`).
      Ignored for JSON bodies (X v2 /tweets uses JSON, so pass None).
    """
    # Merge params for the signature base string (does NOT include JSON body).
    all_params = dict(oauth_params)
    if body_params:
        all_params.update(body_params)
    # Sort by key (then value) and percent-encode both key + value.
    sorted_pairs = sorted(all_params.items())
    encoded_pairs = "&".join(
        f"{_oauth1_percent_encode(k)}={_oauth1_percent_encode(v)}" for k, v in sorted_pairs
    )
    base_string = "&".join([
        method.upper(),
        _oauth1_percent_encode(url),
        _oauth1_percent_encode(encoded_pairs),
    ])
    signing_key = (
        f"{_oauth1_percent_encode(consumer_secret)}&{_oauth1_percent_encode(token_secret)}"
    )
    digest = hmac.new(
        signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _oauth1_auth_header(
    *,
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_secret: str,
    body_params: Optional[Dict[str, str]] = None,
) -> str:
    """Build the `Authorization: OAuth …` header value for X API v2 requests."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": pysecrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    signature = _oauth1_build_signature(
        method=method,
        url=url,
        oauth_params=oauth_params,
        consumer_secret=consumer_secret,
        token_secret=access_secret,
        body_params=body_params,
    )
    oauth_params["oauth_signature"] = signature
    parts = ", ".join(
        f'{_oauth1_percent_encode(k)}="{_oauth1_percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {parts}"


class LinkedInPostIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=3000)
    image_url: Optional[str] = None
    org_urn: Optional[str] = None  # e.g. urn:li:organization:12345


class MetaPostIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    page_id: Optional[str] = None  # overrides the tenant default
    link: Optional[str] = None
    image_url: Optional[str] = None


class XPostIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=280)


class InstagramPostIn(BaseModel):
    caption: str = Field("", max_length=2200)
    image_url: Optional[str] = None
    image_urls: Optional[list] = None  # If provided (2-10 URLs), post as carousel
    video_url: Optional[str] = None  # If provided, post as Reels (single item)
    # 2026-02 fork iter104 — When True, publish as a 24h ephemeral Story
    # (mutually exclusive with carousel). Uses `image_url` OR `video_url`.
    as_story: Optional[bool] = False


class TikTokPostIn(BaseModel):
    video_url: str = Field(..., min_length=8)  # publicly-fetchable URL
    caption: Optional[str] = Field(default="", max_length=2200)
    privacy: Optional[str] = None  # SELF_ONLY | MUTUAL_FOLLOW_FRIENDS | FOLLOWER_OF_CREATOR | PUBLIC_TO_EVERYONE


def setup_smart_comm_senders(
    *,
    app,
    db,
    resolver,
    get_current_user,
):
    """Mount /me/social/* endpoints. `resolver` is the SmartCommResolver."""
    api = app

    # ------------------------------------------------------------------ status
    @api.get("/me/social/status", tags=["Portail Client — Social"])
    async def me_social_status(user: dict = Depends(get_current_user)):
        _require_channel_operator(user)
        tid = _tenant_id_for(user)
        out: Dict[str, Any] = {"tenant_id": tid, "channels": {}}
        for channel in resolver.channels():
            creds = await resolver.resolve(channel, tid)
            # A channel is "ready" if source is tenant OR global provides a
            # non-empty required field. We derive that by checking the first
            # required field pattern (matches our schema).
            required = {
                "wa": ["wa_access_token", "wa_phone_number_id"],
                "meta": ["meta_page_id", "meta_page_access_token"],
                "instagram": ["instagram_business_id", "instagram_access_token"],
                "linkedin": ["linkedin_access_token"],
                "x": ["x_api_key", "x_api_secret", "x_access_token", "x_access_secret"],
                "tiktok": ["tiktok_access_token"],
            }[channel]
            ready = all(bool((creds.get(f) or "")) for f in required)
            out["channels"][channel] = {"source": creds["source"], "ready": ready}
        return out

    # ---------------------------------------------------------------- LinkedIn
    async def _linkedin_upload_image(
        *, access_token: str, org_urn: str, image_bytes: bytes
    ) -> Optional[str]:
        """Upload an image on the org's LinkedIn assets and return its image URN.

        3-step flow (Marketing / Community APIs v202401+):
          1. POST /rest/images?action=initializeUpload → returns uploadUrl + image URN
          2. PUT the raw bytes to `uploadUrl`
          3. Reference the image URN in the post body (media block)
        Returns None on any failure (post continues text-only).
        """
        init_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "LinkedIn-Version": LINKEDIN_API_VERSION,
            "X-RestLi-Protocol-Version": "2.0.0",
        }
        init_body = {"initializeUploadRequest": {"owner": org_urn}}
        try:
            async with httpx.AsyncClient(timeout=30) as cli:
                init_r = await cli.post(
                    f"{LINKEDIN_API_BASE}/rest/images?action=initializeUpload",
                    headers=init_headers,
                    json=init_body,
                )
                if init_r.status_code not in (200, 201):
                    logger.warning("[linkedin/upload/init] %s : %s", init_r.status_code, init_r.text[:200])
                    return None
                init_js = init_r.json() or {}
                value = (init_js.get("value") or {})
                upload_url = value.get("uploadUrl")
                image_urn = value.get("image")
                if not upload_url or not image_urn:
                    logger.warning("[linkedin/upload/init] missing upload URL / image URN : %s", init_js)
                    return None
                # Step 2 — PUT binary
                put_r = await cli.put(
                    upload_url,
                    content=image_bytes,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if put_r.status_code not in (200, 201):
                    logger.warning("[linkedin/upload/put] %s : %s", put_r.status_code, put_r.text[:200])
                    return None
                return image_urn
        except httpx.HTTPError as exc:
            logger.warning("[linkedin/upload] HTTP error : %s", exc)
            return None

    @api.post("/me/social/linkedin/post", tags=["Portail Client — Social"])
    async def me_social_linkedin_post(
        payload: LinkedInPostIn = Body(...),
        user: dict = Depends(get_current_user),
    ):
        _require_channel_operator(user)
        tid = _tenant_id_for(user)
        creds = await resolver.resolve("linkedin", tid)
        access = (creds.get("linkedin_access_token") or "").strip()
        if not access:
            raise HTTPException(status_code=400, detail="LinkedIn non configuré. Renseignez `linkedin_access_token` dans Smart Communications.")
        org_urn = (payload.org_urn or "").strip() or ((creds.get("linkedin_organization_id") or "").strip())
        if org_urn and not org_urn.startswith("urn:li:"):
            org_urn = f"urn:li:organization:{org_urn}"
        if not org_urn:
            raise HTTPException(status_code=400, detail="`org_urn` requis ou `linkedin_organization_id` doit être défini dans Smart Communications")

        # 2026-02 fork iter102 — Upload image en amont si `image_url` fourni.
        # Best-effort : si le download OU l'upload LinkedIn échoue, on continue
        # en publiant du texte seul (jamais bloquant).
        image_urn: Optional[str] = None
        image_error: Optional[str] = None
        if (payload.image_url or "").strip():
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as cli:
                    img_r = await cli.get(payload.image_url.strip())
                if img_r.status_code == 200 and img_r.content:
                    # 20 MB safety cap (LinkedIn limite à ~10 MB pour images).
                    if len(img_r.content) > 20 * 1024 * 1024:
                        image_error = "Image > 20 Mo — publication en texte seul"
                    else:
                        image_urn = await _linkedin_upload_image(
                            access_token=access, org_urn=org_urn, image_bytes=img_r.content
                        )
                        if not image_urn:
                            image_error = "Upload LinkedIn échoué — publication en texte seul"
                else:
                    image_error = f"Téléchargement image {img_r.status_code}"
            except httpx.HTTPError as exc:
                image_error = f"Téléchargement image : {exc}"

        headers = {
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json",
            "LinkedIn-Version": LINKEDIN_API_VERSION,
            "X-RestLi-Protocol-Version": "2.0.0",
        }
        body: Dict[str, Any] = {
            "author": org_urn,
            "lifecycleState": "PUBLISHED",
            "commentary": payload.text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
        }
        if image_urn:
            body["content"] = {"media": {"id": image_urn}}
        try:
            async with httpx.AsyncClient(timeout=30) as cli:
                r = await cli.post(f"{LINKEDIN_API_BASE}/rest/posts", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"LinkedIn indisponible : {exc}")
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"LinkedIn refuse le post ({r.status_code}) : {r.text[:400]}")
        post_urn = r.headers.get("x-restli-id") or r.headers.get("X-RestLi-Id") or ""
        # Audit — same shape as `db.linkedin_posts_audit` used elsewhere.
        await db.linkedin_posts_audit.insert_one({
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "author_urn": org_urn,
            "author_type": "organization",
            "text": payload.text[:2000],
            "image_url": payload.image_url,
            "image_urn": image_urn,
            "image_error": image_error,
            "post_urn": post_urn,
            "credentials_source": creds["source"],
            "tenant_id": tid,
            "created_at": r.headers.get("date"),
        })
        return {
            "ok": True,
            "post_urn": post_urn,
            "credentials_source": creds["source"],
            "image_urn": image_urn,
            "image_error": image_error,
        }

    # -------------------------------------------------------------------- Meta
    @api.post("/me/social/meta/post", tags=["Portail Client — Social"])
    async def me_social_meta_post(
        payload: MetaPostIn = Body(...),
        user: dict = Depends(get_current_user),
    ):
        _require_channel_operator(user)
        tid = _tenant_id_for(user)
        creds = await resolver.resolve("meta", tid)
        page_id = (payload.page_id or creds.get("meta_page_id") or "").strip()
        token = (creds.get("meta_page_access_token") or "").strip()
        if not page_id or not token:
            raise HTTPException(status_code=400, detail="Meta non configuré. Renseignez `meta_page_id` et `meta_page_access_token`.")
        data: Dict[str, Any] = {"message": payload.message}
        if payload.link:
            data["link"] = payload.link
        endpoint = f"https://graph.facebook.com/v22.0/{page_id}/feed"
        params = {"access_token": token}
        try:
            async with httpx.AsyncClient(timeout=30) as cli:
                r = await cli.post(endpoint, params=params, data=data)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Meta indisponible : {exc}")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail=f"Meta refuse le post ({r.status_code}) : {r.text[:400]}")
        try:
            js = r.json()
        except Exception:  # noqa: BLE001
            js = {"raw": r.text[:2000]}
        return {"ok": True, "post_id": js.get("id"), "credentials_source": creds["source"]}

    # ----------------------------------------------------------------------- X
    @api.post("/me/social/x/post", tags=["Portail Client — Social"])
    async def me_social_x_post(
        payload: XPostIn = Body(...),
        user: dict = Depends(get_current_user),
    ):
        """2026-02 fork iter102 — Publie un tweet via OAuth 1.0a signé.

        Utilise l'endpoint v2 `POST /2/tweets` (JSON body). Les credentials
        sont résolues via SmartCommResolver (`source=tenant` si les 4 clés
        OAuth du tenant sont présentes, sinon `source=global`).
        """
        _require_channel_operator(user)
        tid = _tenant_id_for(user)
        creds = await resolver.resolve("x", tid)
        required = ("x_api_key", "x_api_secret", "x_access_token", "x_access_secret")
        if not all((creds.get(k) or "").strip() for k in required):
            raise HTTPException(status_code=400, detail="X (Twitter) non configuré. Renseignez les 4 clés OAuth 1.0a.")
        url = f"{X_API_V2_BASE}/tweets"
        # v2 /tweets accepte un JSON body — NE PAS l'inclure dans la base string.
        auth_header = _oauth1_auth_header(
            method="POST",
            url=url,
            consumer_key=creds["x_api_key"].strip(),
            consumer_secret=creds["x_api_secret"].strip(),
            access_token=creds["x_access_token"].strip(),
            access_secret=creds["x_access_secret"].strip(),
            body_params=None,
        )
        try:
            async with httpx.AsyncClient(timeout=30) as cli:
                r = await cli.post(
                    url,
                    headers={"Authorization": auth_header, "Content-Type": "application/json"},
                    json={"text": payload.text},
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"X indisponible : {exc}")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail=f"X refuse le tweet ({r.status_code}) : {r.text[:400]}")
        try:
            js = r.json()
        except Exception:  # noqa: BLE001
            js = {"raw": r.text[:2000]}
        tweet = (js.get("data") or {}) if isinstance(js, dict) else {}
        tweet_id = tweet.get("id") or ""
        # Audit léger dans la même collection que le module principal Twitter.
        try:
            await db.twitter_posts_audit.insert_one({
                "user_id": user.get("id"),
                "user_email": user.get("email"),
                "text": payload.text[:1000],
                "tweet_id": tweet_id,
                "credentials_source": creds["source"],
                "tenant_id": tid,
                "created_at": r.headers.get("date"),
            })
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "tweet_id": tweet_id, "credentials_source": creds["source"]}

    # --------------------------------------------------------------- Instagram
    async def _instagram_wait_container_ready(
        *, cli: httpx.AsyncClient, container_id: str, access_token: str,
        max_attempts: int = 20, delay_s: float = 1.5,
    ) -> str:
        """Poll status_code of a media container until FINISHED or ERROR/EXPIRED."""
        import asyncio
        for _ in range(max_attempts):
            sr = await cli.get(
                f"https://graph.facebook.com/v22.0/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
            )
            if sr.status_code >= 300:
                return f"HTTP_{sr.status_code}"
            code = ((sr.json() or {}).get("status_code") or "").upper()
            if code == "FINISHED":
                return "FINISHED"
            if code in ("ERROR", "EXPIRED"):
                return code
            await asyncio.sleep(delay_s)
        return "TIMEOUT"

    @api.post("/me/social/instagram/post", tags=["Portail Client — Social"])
    async def me_social_instagram_post(
        payload: InstagramPostIn = Body(...),
        user: dict = Depends(get_current_user),
    ):
        """2026-02 fork iter103 — Publie une image / carrousel / Reels sur
        Instagram Business via Graph API v22.

        3 modes :
          - `image_url` seul → single image
          - `image_urls` (2-10) → carousel (POST /media?is_carousel_item…)
          - `video_url` seul → Reels
        """
        _require_channel_operator(user)
        tid = _tenant_id_for(user)
        creds = await resolver.resolve("instagram", tid)
        ig_id = (creds.get("instagram_business_id") or "").strip()
        token = (creds.get("instagram_access_token") or "").strip()
        if not ig_id or not token:
            raise HTTPException(status_code=400, detail="Instagram non configuré. Renseignez `instagram_business_id` et `instagram_access_token`.")
        image_urls = [u for u in (payload.image_urls or []) if (u or "").strip()]
        if not payload.image_url and not payload.video_url and not image_urls:
            raise HTTPException(status_code=400, detail="Fournir `image_url`, `image_urls` (2-10) ou `video_url`.")
        base_url = f"https://graph.facebook.com/v22.0/{ig_id}"
        caption = (payload.caption or "").strip()
        creation_id: Optional[str] = None
        mode = "single_image"
        try:
            async with httpx.AsyncClient(timeout=45) as cli:
                # ------- Story (24h ephemeral) --------------------------------
                # 2026-02 fork iter104 — mutually exclusive with carousel.
                if payload.as_story:
                    mode = "story"
                    if not payload.image_url and not payload.video_url:
                        raise HTTPException(status_code=400, detail="Story Instagram : `image_url` ou `video_url` requis.")
                    if image_urls and len(image_urls) >= 2:
                        raise HTTPException(status_code=400, detail="Story Instagram : le carrousel n'est pas supporté (1 image OU 1 vidéo).")
                    story_data = {"media_type": "STORIES"}
                    if payload.video_url:
                        story_data["video_url"] = payload.video_url.strip()
                    else:
                        story_data["image_url"] = payload.image_url.strip()
                    r = await cli.post(
                        f"{base_url}/media",
                        params={"access_token": token},
                        data=story_data,
                    )
                # ------- Carousel ---------------------------------------------
                elif len(image_urls) >= 2:
                    mode = "carousel"
                    if len(image_urls) > 10:
                        raise HTTPException(status_code=400, detail="Carrousel Instagram : maximum 10 items.")
                    children: list = []
                    for u_ in image_urls:
                        cr = await cli.post(
                            f"{base_url}/media",
                            params={"access_token": token},
                            data={"image_url": u_, "is_carousel_item": "true"},
                        )
                        if cr.status_code >= 300:
                            raise HTTPException(status_code=502, detail=f"Instagram refuse un item ({cr.status_code}) : {cr.text[:300]}")
                        cid = (cr.json() or {}).get("id")
                        if not cid:
                            raise HTTPException(status_code=502, detail=f"Instagram : id manquant dans un item ({cr.text[:200]})")
                        children.append(cid)
                    r = await cli.post(
                        f"{base_url}/media",
                        params={"access_token": token},
                        data={"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption},
                    )
                # ------- Reels ------------------------------------------------
                elif payload.video_url:
                    mode = "reels"
                    r = await cli.post(
                        f"{base_url}/media",
                        params={"access_token": token},
                        data={"media_type": "REELS", "video_url": payload.video_url.strip(), "caption": caption},
                    )
                # ------- Single image ----------------------------------------
                else:
                    mode = "single_image"
                    single = (payload.image_url or image_urls[0]).strip()
                    r = await cli.post(
                        f"{base_url}/media",
                        params={"access_token": token},
                        data={"image_url": single, "caption": caption},
                    )
                if r.status_code >= 300:
                    raise HTTPException(status_code=502, detail=f"Instagram refuse la création ({r.status_code}) : {r.text[:300]}")
                creation_id = (r.json() or {}).get("id")
                if not creation_id:
                    raise HTTPException(status_code=502, detail=f"Instagram : creation_id manquant ({r.text[:200]})")
                # Reels & carousels need to wait for FINISHED before publish.
                # Stories with video need it too.
                needs_wait = mode in ("reels", "carousel") or (mode == "story" and payload.video_url)
                if needs_wait:
                    status_final = await _instagram_wait_container_ready(
                        cli=cli, container_id=creation_id, access_token=token
                    )
                    if status_final != "FINISHED":
                        raise HTTPException(status_code=502, detail=f"Instagram : container non prêt ({status_final})")
                pub = await cli.post(
                    f"{base_url}/media_publish",
                    params={"access_token": token},
                    data={"creation_id": creation_id},
                )
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Instagram indisponible : {exc}")
        if pub.status_code >= 300:
            raise HTTPException(status_code=502, detail=f"Instagram refuse la publication ({pub.status_code}) : {pub.text[:300]}")
        try:
            js = pub.json()
        except Exception:  # noqa: BLE001
            js = {"raw": pub.text[:2000]}
        media_id = js.get("id") if isinstance(js, dict) else None
        # Audit
        try:
            await db.instagram_posts_audit.insert_one({
                "user_id": user.get("id"),
                "user_email": user.get("email"),
                "ig_business_id": ig_id,
                "mode": mode,
                "caption": caption[:1000],
                "media_id": media_id,
                "creation_id": creation_id,
                "credentials_source": creds["source"],
                "tenant_id": tid,
                "created_at": pub.headers.get("date"),
            })
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "media_id": media_id, "mode": mode, "credentials_source": creds["source"]}

    # ------------------------------------------------------------------ TikTok
    @api.post("/me/social/tiktok/post", tags=["Portail Client — Social"])
    async def me_social_tiktok_post(
        payload: TikTokPostIn = Body(...),
        user: dict = Depends(get_current_user),
    ):
        """2026-02 fork iter103 — Publie une vidéo TikTok via l'API Direct-Post.

        Utilise `PULL_FROM_URL` (l'URL doit être publiquement téléchargeable
        depuis les serveurs TikTok). Le `privacy_level` par défaut est lu
        depuis `settings.global.tiktok_privacy_level` (fallback SELF_ONLY).
        """
        _require_channel_operator(user)
        tid = _tenant_id_for(user)
        creds = await resolver.resolve("tiktok", tid)
        access = (creds.get("tiktok_access_token") or "").strip()
        if not access:
            raise HTTPException(status_code=400, detail="TikTok non configuré. Renseignez `tiktok_access_token`.")
        # Privacy resolution : payload > tenant settings > SELF_ONLY.
        privacy = (payload.privacy or "").strip().upper()
        if not privacy:
            try:
                s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "tiktok_privacy_level": 1}) or {}
            except Exception:  # noqa: BLE001
                s = {}
            privacy = (s.get("tiktok_privacy_level") or "SELF_ONLY").upper()
        allowed_privacy = {"SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"}
        if privacy not in allowed_privacy:
            raise HTTPException(status_code=400, detail=f"privacy invalide, attendu l'un de {sorted(allowed_privacy)}")
        body = {
            "post_info": {
                "title": (payload.caption or "").strip()[:2200],
                "privacy_level": privacy,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": payload.video_url.strip(),
            },
        }
        try:
            async with httpx.AsyncClient(timeout=45) as cli:
                r = await cli.post(
                    "https://open.tiktokapis.com/v2/post/publish/video/init/",
                    headers={
                        "Authorization": f"Bearer {access}",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"TikTok indisponible : {exc}")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail=f"TikTok refuse le post ({r.status_code}) : {r.text[:400]}")
        try:
            js = r.json()
        except Exception:  # noqa: BLE001
            js = {"raw": r.text[:2000]}
        data = (js.get("data") or {}) if isinstance(js, dict) else {}
        publish_id = data.get("publish_id") or data.get("publish_id_v2") or ""
        # Audit
        try:
            await db.tiktok_posts_audit.insert_one({
                "user_id": user.get("id"),
                "user_email": user.get("email"),
                "video_url": payload.video_url,
                "caption": (payload.caption or "")[:1000],
                "privacy": privacy,
                "publish_id": publish_id,
                "credentials_source": creds["source"],
                "tenant_id": tid,
                "created_at": r.headers.get("date"),
            })
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "publish_id": publish_id, "privacy": privacy, "credentials_source": creds["source"]}

    return api


__all__ = ["setup_smart_comm_senders"]
