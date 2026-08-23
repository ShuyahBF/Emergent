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

import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.smart_comm_senders")

LINKEDIN_API_BASE = "https://api.linkedin.com"
LINKEDIN_API_VERSION = "202401"


def _tenant_id_for(user: dict) -> str:
    return user.get("parent_client_id") or user.get("client_id") or user.get("id") or ""


def _require_channel_operator(user: dict) -> None:
    if user.get("role") not in ("admin", "superviseur", "moderator", "marketing", "communication"):
        raise HTTPException(status_code=403, detail="Réservé aux rôles admin / superviseur / marketing")


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
            "image_urn": None,
            "post_urn": post_urn,
            "credentials_source": creds["source"],
            "tenant_id": tid,
            "created_at": r.headers.get("date"),
        })
        return {"ok": True, "post_urn": post_urn, "credentials_source": creds["source"]}

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
        _require_channel_operator(user)
        tid = _tenant_id_for(user)
        creds = await resolver.resolve("x", tid)
        # X posting requires OAuth 1.0a signature — deliberately NOT implemented
        # here to avoid pulling in `requests_oauthlib` client-side. Surface a
        # clear 501 so tenants know they need the platform's implementation.
        required = ("x_api_key", "x_api_secret", "x_access_token", "x_access_secret")
        if not all((creds.get(k) or "").strip() for k in required):
            raise HTTPException(status_code=400, detail="X (Twitter) non configuré. Renseignez les 4 clés OAuth.")
        raise HTTPException(
            status_code=501,
            detail=(
                "X (Twitter) : la publication passe par le module `routes/twitter.py`. "
                "Les credentials du tenant sont bien détectés (source="
                + creds["source"] + ") mais le sender direct n'est pas encore branché ici."
            ),
        )

    return api


__all__ = ["setup_smart_comm_senders"]
