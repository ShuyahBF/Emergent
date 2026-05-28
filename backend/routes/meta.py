"""
Iter38h — Meta Graph API integration (Pages + Messenger + Ads).

Endpoints:
  - Admin config:
      GET/PUT /api/admin/meta/config
  - Tenant OAuth:
      GET     /api/me/meta/oauth/url
      GET     /api/me/meta/oauth/callback      (browser redirect, no auth)
  - Tenant integration status:
      GET     /api/me/meta/status
      POST    /api/me/meta/disconnect
  - Pages (feature-gated: meta_pages):
      GET     /api/me/meta/pages
      GET     /api/me/meta/pages/{page_id}/posts
      POST    /api/me/meta/pages/{page_id}/posts
      POST    /api/me/meta/pages/{page_id}/photos
      GET     /api/me/meta/pages/{page_id}/posts/{post_id}/comments
      POST    /api/me/meta/pages/{page_id}/comments/{comment_id}/reply
  - Messenger (feature-gated: meta_messenger):
      GET     /api/me/meta/messenger/conversations
      POST    /api/me/meta/messenger/send
  - Ads (feature-gated: meta_ads):
      GET     /api/me/meta/ads/accounts
      GET     /api/me/meta/ads/accounts/{ad_account_id}/insights
      POST    /api/me/meta/ads/campaigns
      POST    /api/me/meta/ads/campaigns/{campaign_id}/status
  - Webhook (public, HMAC-validated):
      GET     /api/meta/webhook
      POST    /api/meta/webhook

Tenant integration documents live in `db.meta_integrations` keyed by `tenant_id`.

References: integration_playbook_expert_v2 (cached in CHANGELOG iter38g).
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.meta")

router = APIRouter()

DEFAULT_GRAPH_VERSION = "v20.0"
GRAPH_BASE = "https://graph.facebook.com"


# ---- Pydantic payload models (must be module-level so FastAPI introspection works) ----

class MetaConfigUpdate(BaseModel):
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None
    meta_webhook_verify_token: Optional[str] = None
    meta_graph_version: Optional[str] = None
    meta_redirect_uri: Optional[str] = None


class CreatePostPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=63000)
    link: Optional[str] = None
    published: bool = True


class UploadPhotoPayload(BaseModel):
    image_url: str
    caption: Optional[str] = None
    published: bool = True


class CommentReplyPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)


class MessengerSendPayload(BaseModel):
    page_id: str
    recipient_id: str
    text: str = Field(..., min_length=1, max_length=2000)
    quick_replies: Optional[List[Dict[str, Any]]] = None


class CampaignCreatePayload(BaseModel):
    ad_account_id: str
    name: str = Field(..., min_length=1, max_length=200)
    objective: str = Field(..., description="ex: OUTCOME_TRAFFIC, OUTCOME_LEADS")
    status: str = Field("PAUSED", pattern="^(ACTIVE|PAUSED)$")
    special_ad_categories: List[str] = Field(default_factory=list)


class CampaignStatusPayload(BaseModel):
    status: str = Field(..., pattern="^(ACTIVE|PAUSED|ARCHIVED|DELETED)$")


def setup_meta_routes(
    *,
    db,
    api,
    get_current_user,
    get_current_admin,
    get_settings_doc,
    save_settings,
    public_base_url_fn,
    _normalize_features,
    _tenant_id_of=None,
):
    """Attach all Meta integration routes to the provided FastAPI router/app."""

    # ----- helpers ------------------------------------------------------------

    async def _get_meta_settings() -> Dict[str, Any]:
        s = await get_settings_doc()
        return {
            "meta_app_id": (s.get("meta_app_id") or "").strip(),
            "meta_app_secret": (s.get("meta_app_secret") or "").strip(),
            "meta_webhook_verify_token": (s.get("meta_webhook_verify_token") or "").strip(),
            "meta_graph_version": (s.get("meta_graph_version") or DEFAULT_GRAPH_VERSION).strip(),
            "meta_redirect_uri": (s.get("meta_redirect_uri") or "").strip(),
        }

    async def _tenant_id(user: dict) -> str:
        if _tenant_id_of is not None:
            try:
                return await _tenant_id_of(user)
            except Exception:
                pass
        # Fallback: client_id or self
        return user.get("client_id") or user.get("id")

    async def _tenant_features(tid: str) -> Dict[str, bool]:
        u = await db.users.find_one({"id": tid}, {"_id": 0, "features": 1})
        feats = (u or {}).get("features") or {}
        return _normalize_features(feats)

    def _require_feature(feats: Dict[str, bool], key: str):
        if not feats.get(key):
            raise HTTPException(status_code=403, detail=f"Module Meta '{key}' désactivé pour ce tenant.")

    async def _get_integration(tid: str) -> Optional[Dict[str, Any]]:
        return await db.meta_integrations.find_one({"tenant_id": tid}, {"_id": 0})

    async def _save_integration(tid: str, patch: Dict[str, Any]) -> None:
        patch.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        await db.meta_integrations.update_one(
            {"tenant_id": tid}, {"$set": patch, "$setOnInsert": {"tenant_id": tid}}, upsert=True
        )

    async def _get_page_token(tid: str, page_id: str) -> str:
        doc = await _get_integration(tid)
        if not doc:
            raise HTTPException(status_code=404, detail="Aucune connexion Meta pour ce tenant.")
        for p in doc.get("pages") or []:
            if p.get("page_id") == page_id:
                token = p.get("page_access_token")
                if not token:
                    raise HTTPException(status_code=400, detail="Token de Page manquant.")
                return token
        raise HTTPException(status_code=404, detail="Page non connectée.")

    async def _get_user_token(tid: str) -> str:
        doc = await _get_integration(tid)
        if not doc or not (doc.get("meta_user") or {}).get("long_lived_user_access_token"):
            raise HTTPException(status_code=400, detail="Aucun token utilisateur Meta enregistré.")
        return doc["meta_user"]["long_lived_user_access_token"]

    def _build_scopes(features: Dict[str, bool]) -> List[str]:
        scopes: List[str] = []
        if features.get("meta_pages") or features.get("meta_messenger"):
            scopes += [
                "pages_show_list", "pages_read_engagement",
                "pages_manage_posts", "pages_manage_engagement",
                "pages_read_user_content",
            ]
        if features.get("meta_messenger"):
            scopes += ["pages_messaging", "pages_manage_metadata"]
        if features.get("meta_ads"):
            scopes += ["ads_read", "ads_management"]
        return sorted(set(scopes))

    async def _graph_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ms = await _get_meta_settings()
        url = f"{GRAPH_BASE}/{ms['meta_graph_version']}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(url, params=params)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Meta Graph error {r.status_code}: {r.text[:300]}")
        return r.json()

    async def _graph_post(path: str, params: Dict[str, Any], data: Dict[str, Any] = None, json_body: Dict[str, Any] = None) -> Dict[str, Any]:
        ms = await _get_meta_settings()
        url = f"{GRAPH_BASE}/{ms['meta_graph_version']}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=30.0) as c:
            kwargs = {"params": params}
            if json_body is not None:
                kwargs["json"] = json_body
            elif data is not None:
                kwargs["data"] = data
            r = await c.post(url, **kwargs)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Meta Graph error {r.status_code}: {r.text[:300]}")
        return r.json()

    # =========================================================================
    # Admin config: App ID / Secret / Verify Token / Redirect URI / Graph version
    # =========================================================================

    @api.get("/admin/meta/config", tags=["Admin"])
    async def admin_get_meta_config(request: Request, _: dict = Depends(get_current_admin)):
        ms = await _get_meta_settings()
        # Mask secrets — only show last 4 chars
        return {
            "meta_app_id": ms["meta_app_id"],
            "meta_app_secret_preview": ("…" + ms["meta_app_secret"][-4:]) if ms["meta_app_secret"] else "",
            "meta_webhook_verify_token_preview": ("…" + ms["meta_webhook_verify_token"][-4:]) if ms["meta_webhook_verify_token"] else "",
            "meta_graph_version": ms["meta_graph_version"],
            "meta_redirect_uri": ms["meta_redirect_uri"] or f"{public_base_url_fn(request) or ''}/api/me/meta/oauth/callback",
            "default_redirect_uri": f"{public_base_url_fn(request) or ''}/api/me/meta/oauth/callback",
            "webhook_callback_url": f"{public_base_url_fn(request) or ''}/api/meta/webhook",
        }

    @api.put("/admin/meta/config", tags=["Admin"])
    async def admin_set_meta_config(payload: MetaConfigUpdate, _: dict = Depends(get_current_admin)):
        update: Dict[str, Any] = {}
        for k in ("meta_app_id", "meta_app_secret", "meta_webhook_verify_token", "meta_graph_version", "meta_redirect_uri"):
            v = getattr(payload, k, None)
            if v is not None:
                update[k] = v.strip()
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour.")
        await save_settings(update)
        return {"ok": True, "updated_keys": list(update.keys())}

    # =========================================================================
    # Tenant OAuth (browser flow)
    # =========================================================================

    @api.get("/me/meta/oauth/url", tags=["Portail Client — Meta"])
    async def meta_oauth_url(request: Request, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        if not any(feats.get(k) for k in ("meta_pages", "meta_messenger", "meta_ads")):
            raise HTTPException(status_code=403, detail="Aucune feature Meta activée pour ce tenant.")
        ms = await _get_meta_settings()
        if not ms["meta_app_id"]:
            raise HTTPException(status_code=400, detail="App Meta non configurée (Admin → Paramètres → Meta).")
        scopes = _build_scopes(feats)
        redirect_uri = ms["meta_redirect_uri"] or f"{public_base_url_fn(request) or ''}/api/me/meta/oauth/callback"
        state_payload = {"tid": tid, "uid": user["id"], "nonce": secrets.token_urlsafe(16), "ts": int(time.time())}
        state = json.dumps(state_payload, separators=(",", ":"))
        # Sign the state with the app secret to detect tampering
        sig = hmac.new(ms["meta_app_secret"].encode(), state.encode(), hashlib.sha256).hexdigest() if ms["meta_app_secret"] else ""
        params = {
            "client_id": ms["meta_app_id"],
            "redirect_uri": redirect_uri,
            "state": f"{state}.{sig}",
            "scope": ",".join(scopes),
            "response_type": "code",
        }
        return {
            "auth_url": f"https://www.facebook.com/{ms['meta_graph_version']}/dialog/oauth?{urlencode(params)}",
            "scopes": scopes,
            "redirect_uri": redirect_uri,
        }

    @api.get("/me/meta/oauth/callback", tags=["Portail Client — Meta"])
    async def meta_oauth_callback(
        request: Request,
        code: Optional[str] = Query(None),
        state: Optional[str] = Query(None),
        error: Optional[str] = Query(None),
        error_description: Optional[str] = Query(None),
    ):
        # Front-end redirect target
        base = public_base_url_fn(request) or ""
        portal = f"{base}/portal/meta?cb=1"
        if error or not code or not state:
            return RedirectResponse(url=f"{portal}&status=error&reason={error or 'missing_code'}")
        try:
            raw_state, raw_sig = state.rsplit(".", 1)
            payload = json.loads(raw_state)
        except Exception:
            return RedirectResponse(url=f"{portal}&status=error&reason=bad_state")
        ms = await _get_meta_settings()
        if ms["meta_app_secret"]:
            expected = hmac.new(ms["meta_app_secret"].encode(), raw_state.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, raw_sig):
                return RedirectResponse(url=f"{portal}&status=error&reason=bad_signature")
        if int(time.time()) - int(payload.get("ts", 0)) > 600:
            return RedirectResponse(url=f"{portal}&status=error&reason=state_expired")
        tid = payload.get("tid")
        if not tid:
            return RedirectResponse(url=f"{portal}&status=error&reason=missing_tid")

        redirect_uri = ms["meta_redirect_uri"] or f"{base}/api/me/meta/oauth/callback"
        try:
            # Exchange code → short-lived token
            short_data = await _graph_get("oauth/access_token", {
                "client_id": ms["meta_app_id"], "client_secret": ms["meta_app_secret"],
                "redirect_uri": redirect_uri, "code": code,
            })
            short_token = short_data["access_token"]
            # Exchange → long-lived user token
            long_data = await _graph_get("oauth/access_token", {
                "grant_type": "fb_exchange_token",
                "client_id": ms["meta_app_id"], "client_secret": ms["meta_app_secret"],
                "fb_exchange_token": short_token,
            })
            long_token = long_data["access_token"]
            expires_in = int(long_data.get("expires_in") or 0)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat() if expires_in else None
            # Fetch user + pages + ad accounts
            me = await _graph_get("me", {"access_token": long_token, "fields": "id,name"})
            pages_resp = await _graph_get("me/accounts", {"access_token": long_token, "fields": "id,name,access_token,category"})
            ads_resp = await _graph_get("me/adaccounts", {"access_token": long_token, "fields": "id,name,account_status,currency"})
        except HTTPException as exc:
            logger.warning("[meta-oauth] exchange failed: %s", exc.detail)
            return RedirectResponse(url=f"{portal}&status=error&reason=token_exchange&detail={exc.detail[:80]}")
        except Exception:
            logger.exception("[meta-oauth] unexpected error")
            return RedirectResponse(url=f"{portal}&status=error&reason=unexpected")

        pages_docs = [{
            "page_id": p["id"], "name": p.get("name"),
            "page_access_token": p.get("access_token"),
            "category": p.get("category"),
            "subscribed_messenger": False,
        } for p in (pages_resp.get("data") or []) if p.get("access_token")]

        # Iter38k — Auto-subscribe each Page to Messenger + feed webhooks.
        # Best-effort: errors are logged but never break the OAuth flow.
        async with httpx.AsyncClient(timeout=20.0) as c:
            ms = await _get_meta_settings()
            for page in pages_docs:
                try:
                    sub = await c.post(
                        f"{GRAPH_BASE}/{ms['meta_graph_version']}/{page['page_id']}/subscribed_apps",
                        params={
                            "access_token": page["page_access_token"],
                            "subscribed_fields": "messages,messaging_postbacks,feed",
                        },
                    )
                    if sub.status_code < 400:
                        page["subscribed_messenger"] = True
                    else:
                        logger.warning("[meta-oauth] subscribe failed for %s: %s", page["page_id"], sub.text[:200])
                except Exception as exc:
                    logger.warning("[meta-oauth] subscribe error for %s: %s", page["page_id"], exc)

        ads_docs = [{
            "id": a["id"], "name": a.get("name"),
            "status": a.get("account_status"), "currency": a.get("currency"),
        } for a in (ads_resp.get("data") or [])]

        await _save_integration(tid, {
            "meta_user": {
                "facebook_user_id": me["id"], "name": me.get("name"),
                "long_lived_user_access_token": long_token, "expires_at": expires_at,
            },
            "pages": pages_docs,
            "ads_accounts": ads_docs,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        })
        return RedirectResponse(url=f"{portal}&status=success&pages={len(pages_docs)}&ads={len(ads_docs)}")

    # =========================================================================
    # Tenant status + disconnect
    # =========================================================================

    @api.get("/me/meta/status", tags=["Portail Client — Meta"])
    async def meta_status(user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        doc = await _get_integration(tid)
        connected = bool(doc and (doc.get("meta_user") or {}).get("long_lived_user_access_token"))
        return {
            "features": {
                "meta_pages": bool(feats.get("meta_pages")),
                "meta_messenger": bool(feats.get("meta_messenger")),
                "meta_ads": bool(feats.get("meta_ads")),
            },
            "connected": connected,
            "user_name": (doc or {}).get("meta_user", {}).get("name") if connected else None,
            "expires_at": (doc or {}).get("meta_user", {}).get("expires_at") if connected else None,
            "pages": [{"page_id": p["page_id"], "name": p.get("name"), "category": p.get("category"), "subscribed_messenger": p.get("subscribed_messenger", False)} for p in (doc or {}).get("pages") or []],
            "ads_accounts": (doc or {}).get("ads_accounts") or [],
            "connected_at": (doc or {}).get("connected_at"),
        }

    @api.post("/me/meta/disconnect", tags=["Portail Client — Meta"])
    async def meta_disconnect(user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        await db.meta_integrations.delete_one({"tenant_id": tid})
        return {"ok": True}

    # =========================================================================
    # Pages module
    # =========================================================================

    @api.get("/me/meta/pages", tags=["Portail Client — Meta"])
    async def list_pages(user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_pages")
        doc = await _get_integration(tid)
        return {"pages": (doc or {}).get("pages") or []}

    @api.get("/me/meta/pages/{page_id}/posts", tags=["Portail Client — Meta"])
    async def page_posts(page_id: str, limit: int = 10, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_pages")
        token = await _get_page_token(tid, page_id)
        return await _graph_get(f"{page_id}/feed", {
            "access_token": token, "limit": limit,
            "fields": "id,message,created_time,permalink_url,is_published,reactions.summary(true),comments.summary(true)",
        })

    @api.post("/me/meta/pages/{page_id}/posts", tags=["Portail Client — Meta"])
    async def create_post(page_id: str, payload: CreatePostPayload, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_pages")
        token = await _get_page_token(tid, page_id)
        data = {"message": payload.message, "published": "true" if payload.published else "false"}
        if payload.link:
            data["link"] = payload.link
        return await _graph_post(f"{page_id}/feed", {"access_token": token}, data=data)

    @api.post("/me/meta/pages/{page_id}/photos", tags=["Portail Client — Meta"])
    async def upload_photo(page_id: str, payload: UploadPhotoPayload, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_pages")
        token = await _get_page_token(tid, page_id)
        data = {"url": payload.image_url, "published": "true" if payload.published else "false"}
        if payload.caption:
            data["caption"] = payload.caption
        return await _graph_post(f"{page_id}/photos", {"access_token": token}, data=data)

    @api.get("/me/meta/pages/{page_id}/posts/{post_id}/comments", tags=["Portail Client — Meta"])
    async def post_comments(page_id: str, post_id: str, limit: int = 25, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_pages")
        token = await _get_page_token(tid, page_id)
        return await _graph_get(f"{post_id}/comments", {
            "access_token": token, "limit": limit,
            "fields": "id,message,from,created_time,like_count,comment_count",
        })

    @api.post("/me/meta/pages/{page_id}/comments/{comment_id}/reply", tags=["Portail Client — Meta"])
    async def reply_comment(page_id: str, comment_id: str, payload: CommentReplyPayload, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_pages")
        token = await _get_page_token(tid, page_id)
        return await _graph_post(f"{comment_id}/comments", {"access_token": token}, data={"message": payload.message})

    # =========================================================================
    # Messenger module
    # =========================================================================

    @api.get("/me/meta/messenger/conversations", tags=["Portail Client — Meta"])
    async def messenger_conversations(page_id: str, limit: int = 20, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_messenger")
        token = await _get_page_token(tid, page_id)
        return await _graph_get(f"{page_id}/conversations", {
            "access_token": token, "limit": limit,
            "fields": "id,updated_time,message_count,participants,messages.limit(5){id,from,to,message,created_time}",
        })

    @api.post("/me/meta/messenger/send", tags=["Portail Client — Meta"])
    async def messenger_send(payload: MessengerSendPayload, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_messenger")
        token = await _get_page_token(tid, payload.page_id)
        body: Dict[str, Any] = {
            "recipient": {"id": payload.recipient_id},
            "message": {"text": payload.text},
            "messaging_type": "RESPONSE",
        }
        if payload.quick_replies:
            body["message"]["quick_replies"] = payload.quick_replies
        return await _graph_post(f"{payload.page_id}/messages", {"access_token": token}, json_body=body)

    # =========================================================================
    # Ads module
    # =========================================================================

    @api.get("/me/meta/ads/accounts", tags=["Portail Client — Meta"])
    async def ads_accounts(user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_ads")
        doc = await _get_integration(tid)
        return {"accounts": (doc or {}).get("ads_accounts") or []}

    @api.get("/me/meta/ads/accounts/{ad_account_id}/insights", tags=["Portail Client — Meta"])
    async def ads_insights(ad_account_id: str, date_preset: str = "last_7d", user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_ads")
        token = await _get_user_token(tid)
        return await _graph_get(f"{ad_account_id}/insights", {
            "access_token": token, "fields": "impressions,clicks,spend,reach,ctr,cpc",
            "date_preset": date_preset,
        })

    @api.post("/me/meta/ads/campaigns", tags=["Portail Client — Meta"])
    async def ads_create_campaign(payload: CampaignCreatePayload, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_ads")
        token = await _get_user_token(tid)
        return await _graph_post(payload.ad_account_id + "/campaigns", {"access_token": token}, data={
            "name": payload.name, "objective": payload.objective, "status": payload.status,
            "special_ad_categories": json.dumps(payload.special_ad_categories),
        })

    @api.post("/me/meta/ads/campaigns/{campaign_id}/status", tags=["Portail Client — Meta"])
    async def ads_set_status(campaign_id: str, payload: CampaignStatusPayload, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        _require_feature(feats, "meta_ads")
        token = await _get_user_token(tid)
        return await _graph_post(campaign_id, {"access_token": token}, data={"status": payload.status})

    # =========================================================================
    # Webhook (public, verified via HMAC)
    # =========================================================================

    @api.get("/meta/webhook", tags=["Meta Webhook"])
    async def meta_webhook_verify(
        hub_mode: str = Query(None, alias="hub.mode"),
        hub_challenge: str = Query(None, alias="hub.challenge"),
        hub_verify_token: str = Query(None, alias="hub.verify_token"),
    ):
        """Iter38r-fix3 — Accepts either `meta_webhook_verify_token`
        (Messenger/Pages/Ads) OR `wa_verify_token` (WhatsApp Cloud) so the
        same URL can be used for both subscriptions in a single Meta App."""
        ms = await _get_meta_settings()
        s_global = await db.settings.find_one({"_id": "global"}) or {}
        wa_token = (s_global.get("wa_verify_token") or "").strip()
        meta_token = (ms.get("meta_webhook_verify_token") or "").strip()
        if hub_mode == "subscribe" and hub_verify_token and (
            (meta_token and hub_verify_token == meta_token)
            or (wa_token and hub_verify_token == wa_token)
        ):
            return PlainTextResponse(content=hub_challenge or "")
        raise HTTPException(status_code=403, detail="Verification failed")

    @api.post("/meta/webhook", tags=["Meta Webhook"])
    async def meta_webhook_receive(request: Request):
        """Iter38r-fix3 — Detects WhatsApp Cloud payloads
        (`object='whatsapp_business_account'`) and forwards them to the
        existing WhatsApp webhook handler. Pure Messenger/Pages payloads
        keep the HMAC-verified flow."""
        ms = await _get_meta_settings()
        body_bytes = await request.body()
        # Pre-parse to detect object type before deciding signature policy
        try:
            payload = json.loads(body_bytes)
        except Exception:
            payload = {}
        if (payload.get("object") or "").lower() == "whatsapp_business_account":
            # Delegate to the WhatsApp Cloud handler. We import lazily to avoid
            # a circular dependency between server.py and routes/meta.py.
            try:
                from server import whatsapp_webhook_incoming  # type: ignore
            except Exception:
                whatsapp_webhook_incoming = None  # noqa: N816
            if whatsapp_webhook_incoming is not None:
                # The handler reads request.body() — body is already consumed,
                # so we need to inject the bytes back. Wrap the request in a
                # minimal proxy that returns our cached bytes.
                async def _body():
                    return body_bytes
                request._body = body_bytes  # Starlette caches body internally
                return await whatsapp_webhook_incoming(request)
            return JSONResponse({"received": False, "reason": "wa_handler_missing"}, status_code=200)
        # Non-WhatsApp (Messenger / Pages / Ads / Instagram) — keep HMAC check
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not ms["meta_app_secret"]:
            return JSONResponse({"received": False, "reason": "no_secret_configured"}, status_code=200)
        expected = "sha256=" + hmac.new(ms["meta_app_secret"].encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return JSONResponse({"received": False, "reason": "bad_signature"}, status_code=200)
        # Iterate entries, route to tenant by page_id, persist message
        for entry in payload.get("entry", []):
            page_id = entry.get("id")
            tenant = await db.meta_integrations.find_one({"pages.page_id": page_id}, {"_id": 0, "tenant_id": 1})
            if not tenant:
                continue
            tid = tenant["tenant_id"]
            for event in entry.get("messaging", []) or []:
                sender = (event.get("sender") or {}).get("id")
                recipient = (event.get("recipient") or {}).get("id")
                msg = event.get("message") or {}
                text = msg.get("text") or ""
                doc = {
                    "id": secrets.token_urlsafe(12), "tenant_id": tid, "page_id": page_id,
                    "sender_id": sender, "recipient_id": recipient,
                    "text": text, "timestamp_ms": event.get("timestamp"),
                    "raw": event,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.meta_messenger_messages.insert_one(doc)
            for event in entry.get("changes", []) or []:
                doc = {
                    "id": secrets.token_urlsafe(12), "tenant_id": tid, "page_id": page_id,
                    "field": event.get("field"), "value": event.get("value"),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.meta_webhook_events.insert_one(doc)
        return JSONResponse({"received": True}, status_code=200)
