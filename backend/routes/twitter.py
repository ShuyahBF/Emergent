"""Iter43-fix24ax (2026-02-26) — Twitter (X) API v2 integration.

OAuth 2.0 Authorization Code Flow with PKCE + tweet creation (text + optional
image via v1.1 media/upload) + recent tweets listing.

Routes :
  - GET    /api/admin/twitter/config            — current config (masked)
  - PUT    /api/admin/twitter/config            — set Client ID, Secret, Redirect URI
  - GET    /api/admin/twitter/oauth/preview-redirect-uri  — compute the redirect_uri
  - GET    /api/admin/twitter/oauth/authorize   — returns auth URL with PKCE
  - GET    /api/twitter/oauth/callback          — handles redirect, exchange code+verifier
  - GET    /api/twitter/status                  — connection status (any user)
  - DELETE /api/admin/twitter/connection        — disconnect
  - POST   /api/twitter/tweets                  — post a tweet
  - GET    /api/twitter/tweets                  — list recent tweets

Storage : settings.global.twitter_*
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger("sawali.twitter")

TWITTER_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TWITTER_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
TWITTER_API_BASE = "https://api.twitter.com"
TWITTER_MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
DEFAULT_SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access"]
DEFAULT_TIMEOUT = 20


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge)."""
    verifier = _base64url(os.urandom(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _compute_redirect_uri(request: Request, settings: Dict[str, Any]) -> str:
    explicit = (settings.get("twitter_redirect_uri") or "").strip()
    if explicit:
        return explicit
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    fwd_proto = request.headers.get("x-forwarded-proto") or "https"
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}/api/twitter/oauth/callback"
    return str(request.url_for("twitter_oauth_callback"))


class TwitterConfigPayload(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: Optional[str] = None


class TweetPayload(BaseModel):
    text: str
    image_url: Optional[str] = None


async def _ensure_token_valid(db, settings: Dict[str, Any]) -> str:
    access = (settings.get("twitter_access_token") or "").strip()
    if not access:
        raise HTTPException(status_code=400, detail="Twitter non connecté. Admin → Settings → Twitter.")
    expires_at_iso = settings.get("twitter_token_expires_at")
    if not expires_at_iso:
        return access
    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except (TypeError, ValueError):
        return access
    if expires_at - _now_dt() > timedelta(minutes=2):
        return access
    refresh = (settings.get("twitter_refresh_token") or "").strip()
    if not refresh:
        raise HTTPException(status_code=401, detail="Token Twitter expiré. Reconnectez.")
    cid = (settings.get("twitter_client_id") or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="Client ID Twitter manquant.")
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
        r = await cli.post(
            TWITTER_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": cid},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail=f"Refresh Twitter échoué : {r.text[:200]}")
    tok = r.json()
    new_access = tok.get("access_token")
    new_refresh = tok.get("refresh_token") or refresh  # rotation : always store the latest
    expires_in = int(tok.get("expires_in") or 7200)
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "twitter_access_token": new_access,
            "twitter_refresh_token": new_refresh,
            "twitter_token_expires_at": (_now_dt() + timedelta(seconds=expires_in)).isoformat(),
            "twitter_refreshed_at": _now_iso(),
        }},
    )
    return new_access


async def _post_tweet(access_token: str, text: str, media_id: Optional[str]) -> Dict[str, Any]:
    body: Dict[str, Any] = {"text": text}
    if media_id:
        body["media"] = {"media_ids": [media_id]}
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.post(
            f"{TWITTER_API_BASE}/2/tweets",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=body,
        )
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"Tweet création échouée ({r.status_code}) : {r.text[:300]}")
    return r.json()


async def _upload_media_from_url(access_token: str, image_url: str) -> str:
    """Download the image then POST to v1.1 media/upload. Returns media_id."""
    async with httpx.AsyncClient(timeout=30) as cli:
        img = await cli.get(image_url)
    if img.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Image source inaccessible ({img.status_code})")
    files = {"media": img.content}
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            TWITTER_MEDIA_UPLOAD_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            files=files,
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Upload média Twitter échoué ({r.status_code}) : {r.text[:200]}. "
                   f"Note : votre App Twitter doit être dans un Project avec accès v1.1 media/upload.",
        )
    j = r.json()
    mid = j.get("media_id_string") or str(j.get("media_id") or "")
    if not mid:
        raise HTTPException(status_code=502, detail=f"media_id absent dans la réponse : {j}")
    return mid


def attach_twitter_routes(*, api, db, get_current_user, get_current_admin):

    @api.get("/admin/twitter/config", tags=["Admin — Twitter"])
    async def get_config(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "client_id": s.get("twitter_client_id") or "",
            "client_secret": "********" if s.get("twitter_client_secret") else "",
            "redirect_uri": s.get("twitter_redirect_uri") or "",
            "connected": bool(s.get("twitter_access_token")),
            "user_id": s.get("twitter_user_id", ""),
            "username": s.get("twitter_username", ""),
            "scopes": (s.get("twitter_scope", "") or "").split() if s.get("twitter_scope") else [],
            "token_expires_at": s.get("twitter_token_expires_at"),
            "connected_at": s.get("twitter_connected_at"),
            "connected_by": s.get("twitter_connected_by"),
        }

    @api.put("/admin/twitter/config", tags=["Admin — Twitter"])
    async def put_config(payload: TwitterConfigPayload = Body(...), user: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        update: Dict[str, Any] = {}
        if payload.client_id is not None:
            update["twitter_client_id"] = payload.client_id.strip()
        if payload.client_secret is not None and payload.client_secret != "********":
            update["twitter_client_secret"] = payload.client_secret.strip()
        if payload.redirect_uri is not None:
            update["twitter_redirect_uri"] = payload.redirect_uri.strip()
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["twitter_config_updated_at"] = _now_iso()
        update["twitter_config_updated_by"] = user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    @api.get("/admin/twitter/oauth/preview-redirect-uri", tags=["Admin — Twitter"])
    async def preview_redirect(request: Request, _: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "redirect_uri": _compute_redirect_uri(request, s),
            "explicit_override": s.get("twitter_redirect_uri") or "",
            "computed_from_host": request.headers.get("x-forwarded-host") or request.headers.get("host") or "",
        }

    @api.get("/admin/twitter/oauth/authorize", tags=["Admin — Twitter"])
    async def authorize(request: Request, user: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        cid = (s.get("twitter_client_id") or "").strip()
        if not cid:
            raise HTTPException(status_code=400, detail="Configurez Client ID Twitter d'abord.")
        verifier, challenge = _generate_pkce_pair()
        state = pysecrets.token_urlsafe(32)
        redirect_uri = _compute_redirect_uri(request, s)
        await db.twitter_oauth_states.insert_one({
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "created_at": _now_dt(),
        })
        params = {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "scope": " ".join(DEFAULT_SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return {
            "authorization_url": f"{TWITTER_AUTH_URL}?{urlencode(params)}",
            "redirect_uri": redirect_uri,
            "scopes": DEFAULT_SCOPES,
            "state": state,
        }

    @api.get("/twitter/oauth/callback", tags=["Twitter"], name="twitter_oauth_callback")
    async def callback(
        request: Request,
        code: Optional[str] = Query(None),
        state: Optional[str] = Query(None),
        error: Optional[str] = Query(None),
        error_description: Optional[str] = Query(None),
    ):
        if error:
            return HTMLResponse(_render_html(False, f"Twitter a refusé : {error} — {error_description or ''}"), 400)
        if not code or not state:
            return HTMLResponse(_render_html(False, "Paramètres code/state requis."), 400)
        st = await db.twitter_oauth_states.find_one({"state": state})
        if not st:
            return HTMLResponse(_render_html(False, "State invalide ou déjà utilisé."), 400)
        await db.twitter_oauth_states.delete_one({"state": state})
        created_at = st.get("created_at")
        if isinstance(created_at, datetime) and (_now_dt() - created_at) > timedelta(minutes=15):
            return HTMLResponse(_render_html(False, "State expiré (> 15 min)."), 400)
        s = await db.settings.find_one({"_id": "global"}) or {}
        cid = (s.get("twitter_client_id") or "").strip()
        csec = (s.get("twitter_client_secret") or "").strip()
        if not cid:
            return HTMLResponse(_render_html(False, "Client ID perdu."), 500)
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cid,
            "redirect_uri": st["redirect_uri"],
            "code_verifier": st["code_verifier"],
        }
        # Twitter requires basic auth for confidential clients (client_secret)
        auth = (cid, csec) if csec else None
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
            r = await cli.post(TWITTER_TOKEN_URL, data=data, auth=auth)
        if r.status_code != 200:
            return HTMLResponse(_render_html(False, f"Échange token échoué ({r.status_code}) : {r.text[:200]}"), 400)
        tok = r.json()
        access = tok.get("access_token")
        refresh = tok.get("refresh_token")
        expires_in = int(tok.get("expires_in") or 7200)
        scope = tok.get("scope", "")
        # Fetch user info
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
            uir = await cli.get(f"{TWITTER_API_BASE}/2/users/me", headers={"Authorization": f"Bearer {access}"})
        username = ""
        user_id = ""
        if uir.status_code == 200:
            ud = (uir.json().get("data") or {})
            username = ud.get("username", "")
            user_id = ud.get("id", "")
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "twitter_access_token": access,
                "twitter_refresh_token": refresh,
                "twitter_token_expires_at": (_now_dt() + timedelta(seconds=expires_in)).isoformat(),
                "twitter_scope": scope,
                "twitter_user_id": user_id,
                "twitter_username": username,
                "twitter_connected_at": _now_iso(),
                "twitter_connected_by": st.get("user_email", ""),
            }},
            upsert=True,
        )
        logger.info("[twitter] OAuth success — @%s (id=%s)", username, user_id)
        return HTMLResponse(_render_html(True, f"Twitter connecté en tant que @{username or user_id}"))

    @api.get("/twitter/status", tags=["Twitter"])
    async def status(_: dict = Depends(get_current_user)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "connected": bool(s.get("twitter_access_token")),
            "user_id": s.get("twitter_user_id", ""),
            "username": s.get("twitter_username", ""),
            "scopes": (s.get("twitter_scope", "") or "").split() if s.get("twitter_scope") else [],
            "token_expires_at": s.get("twitter_token_expires_at"),
            "connected_at": s.get("twitter_connected_at"),
            "connected_by": s.get("twitter_connected_by"),
        }

    @api.delete("/admin/twitter/connection", tags=["Admin — Twitter"])
    async def disconnect(user: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        await db.settings.update_one(
            {"_id": "global"},
            {"$unset": {
                "twitter_access_token": "", "twitter_refresh_token": "",
                "twitter_token_expires_at": "", "twitter_scope": "",
                "twitter_user_id": "", "twitter_username": "",
                "twitter_connected_at": "", "twitter_connected_by": "",
            }},
        )
        await db.settings.update_one({"_id": "global"}, {"$set": {"twitter_disconnected_at": _now_iso(), "twitter_disconnected_by": user.get("email")}})
        return {"ok": True}

    @api.post("/twitter/tweets", tags=["Twitter"])
    async def post_tweet(payload: TweetPayload = Body(...), user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        if user.get("role") not in ("admin", "marketing", "communication"):
            raise HTTPException(status_code=403, detail="Réservé aux rôles admin/marketing")
        if len(payload.text) > 280:
            raise HTTPException(status_code=400, detail=f"Tweet trop long ({len(payload.text)}/280)")
        s = await db.settings.find_one({"_id": "global"}) or {}
        access = await _ensure_token_valid(db, s)
        media_id = None
        if payload.image_url:
            media_id = await _upload_media_from_url(access, payload.image_url)
        result = await _post_tweet(access, payload.text, media_id)
        tweet_data = (result.get("data") or {})
        tweet_id = tweet_data.get("id", "")
        await db.twitter_posts_audit.insert_one({
            "user_id": user.get("id"), "user_email": user.get("email"),
            "tweet_id": tweet_id, "text": payload.text[:500], "image_url": payload.image_url,
            "media_id": media_id, "created_at": _now_dt(),
        })
        return {"ok": True, "tweet_id": tweet_id, "media_id": media_id, "raw": result}

    @api.get("/twitter/tweets", tags=["Twitter"])
    async def list_tweets(limit: int = Query(10, ge=5, le=100), user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        access = await _ensure_token_valid(db, s)
        uid = s.get("twitter_user_id")
        if not uid:
            raise HTTPException(status_code=400, detail="twitter_user_id manquant. Reconnectez.")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
            r = await cli.get(
                f"{TWITTER_API_BASE}/2/users/{uid}/tweets",
                headers={"Authorization": f"Bearer {access}"},
                params={"max_results": limit, "tweet.fields": "created_at,public_metrics"},
            )
        if r.status_code != 200:
            return {"items": [], "_error": f"HTTP {r.status_code}", "_detail": r.text[:300]}
        data = r.json()
        items = []
        for el in data.get("data") or []:
            items.append({
                "tweet_id": el.get("id", ""),
                "text": el.get("text", ""),
                "created_at": el.get("created_at"),
                "metrics": el.get("public_metrics"),
            })
        return {"items": items, "username": s.get("twitter_username", "")}

    logger.info("[twitter] routes mounted under /api/admin/twitter/* + /api/twitter/*")


def _render_html(success: bool, message: str) -> str:
    color = "#16a34a" if success else "#dc2626"
    icon = "✅" if success else "❌"
    safe = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>sawalismartsystems — Twitter OAuth</title>
<style>body{{font-family:system-ui;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#1e293b;padding:32px;border-radius:12px;max-width:480px;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.4)}}
h1{{color:{color};margin:0 0 12px;font-size:22px}}.icon{{font-size:48px;margin-bottom:16px}}
a{{display:inline-block;margin-top:18px;padding:10px 20px;background:#1d9bf0;color:#fff;border-radius:6px;text-decoration:none}}</style></head>
<body><div class="card"><div class="icon">{icon}</div><h1>Twitter OAuth — {"Succès" if success else "Échec"}</h1>
<p>{safe}</p><a href="/admin/settings">← Retour</a></div>
<script>if(window.opener){{try{{window.opener.postMessage({{type:'twitter-oauth-result',success:{str(success).lower()},message:{repr(safe)}}},'*');setTimeout(()=>window.close(),1500)}}catch(e){{}}}}</script>
</body></html>"""
