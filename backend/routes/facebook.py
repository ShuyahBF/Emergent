"""Iter43-fix24ax (2026-02-26) — Facebook Page integration.

OAuth 2.0 standard flow + Page Access Token retrieval via /me/accounts +
Page posting (text + optional image via /{page-id}/photos).

Routes :
  - GET    /api/admin/facebook/config           — current config (masked)
  - PUT    /api/admin/facebook/config           — set App ID, App Secret, Redirect URI
  - GET    /api/admin/facebook/oauth/preview-redirect-uri
  - GET    /api/admin/facebook/oauth/authorize
  - GET    /api/facebook/oauth/callback         — exchanges code + obtains long-lived token
  - GET    /api/admin/facebook/pages            — lists user's Pages
  - PUT    /api/admin/facebook/active-page      — pick the active Page
  - GET    /api/facebook/status
  - DELETE /api/admin/facebook/connection
  - POST   /api/facebook/posts                  — post text or photo
  - GET    /api/facebook/posts                  — list page feed

Storage : settings.global.facebook_*
"""
from __future__ import annotations

import logging
import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger("sawali.facebook")

GRAPH_VERSION = "v20.0"
FB_AUTH_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
FB_TOKEN_URL = f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token"
FB_API_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
DEFAULT_SCOPES = ["pages_show_list", "pages_manage_posts", "pages_read_engagement", "public_profile", "email"]
DEFAULT_TIMEOUT = 20


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


def _compute_redirect_uri(request: Request, settings: Dict[str, Any]) -> str:
    explicit = (settings.get("facebook_redirect_uri") or "").strip()
    if explicit:
        return explicit
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    fwd_proto = request.headers.get("x-forwarded-proto") or "https"
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}/api/facebook/oauth/callback"
    return str(request.url_for("facebook_oauth_callback"))


class FacebookConfigPayload(BaseModel):
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    redirect_uri: Optional[str] = None


class ActivePagePayload(BaseModel):
    page_id: str
    page_access_token: str
    page_name: Optional[str] = None


class FacebookPostPayload(BaseModel):
    text: str
    image_url: Optional[str] = None


async def _post_to_page(page_id: str, page_token: str, text: str, image_url: Optional[str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as cli:
        if image_url:
            data = {"url": image_url, "caption": text, "published": "true", "access_token": page_token}
            r = await cli.post(f"{FB_API_BASE}/{page_id}/photos", data=data)
        else:
            data = {"message": text, "access_token": page_token}
            r = await cli.post(f"{FB_API_BASE}/{page_id}/feed", data=data)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Post Facebook échoué ({r.status_code}) : {r.text[:300]}")
    return r.json()


def attach_facebook_routes(*, api, db, get_current_user, get_current_admin):

    @api.get("/admin/facebook/config", tags=["Admin — Facebook"])
    async def get_config(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "app_id": s.get("facebook_app_id") or "",
            "app_secret": "********" if s.get("facebook_app_secret") else "",
            "redirect_uri": s.get("facebook_redirect_uri") or "",
            "connected": bool(s.get("facebook_user_access_token")),
            "user_id": s.get("facebook_user_id", ""),
            "user_name": s.get("facebook_user_name", ""),
            "user_email": s.get("facebook_user_email", ""),
            "user_token_expires_at": s.get("facebook_user_token_expires_at"),
            "active_page_id": s.get("facebook_page_id", ""),
            "active_page_name": s.get("facebook_page_name", ""),
            "has_active_page_token": bool(s.get("facebook_page_access_token")),
            "connected_at": s.get("facebook_connected_at"),
            "connected_by": s.get("facebook_connected_by"),
        }

    @api.put("/admin/facebook/config", tags=["Admin — Facebook"])
    async def put_config(payload: FacebookConfigPayload = Body(...), user: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        update: Dict[str, Any] = {}
        if payload.app_id is not None:
            update["facebook_app_id"] = payload.app_id.strip()
        if payload.app_secret is not None and payload.app_secret != "********":
            update["facebook_app_secret"] = payload.app_secret.strip()
        if payload.redirect_uri is not None:
            update["facebook_redirect_uri"] = payload.redirect_uri.strip()
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["facebook_config_updated_at"] = _now_iso()
        update["facebook_config_updated_by"] = user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    @api.get("/admin/facebook/oauth/preview-redirect-uri", tags=["Admin — Facebook"])
    async def preview_redirect(request: Request, _: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "redirect_uri": _compute_redirect_uri(request, s),
            "explicit_override": s.get("facebook_redirect_uri") or "",
            "computed_from_host": request.headers.get("x-forwarded-host") or request.headers.get("host") or "",
        }

    @api.get("/admin/facebook/oauth/authorize", tags=["Admin — Facebook"])
    async def authorize(request: Request, user: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        app_id = (s.get("facebook_app_id") or "").strip()
        if not app_id:
            raise HTTPException(status_code=400, detail="Configurez App ID Facebook d'abord.")
        state = pysecrets.token_urlsafe(32)
        redirect_uri = _compute_redirect_uri(request, s)
        await db.facebook_oauth_states.insert_one({
            "state": state, "redirect_uri": redirect_uri,
            "user_id": user.get("id"), "user_email": user.get("email"),
            "created_at": _now_dt(),
        })
        params = {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": ",".join(DEFAULT_SCOPES),
        }
        return {
            "authorization_url": f"{FB_AUTH_URL}?{urlencode(params)}",
            "redirect_uri": redirect_uri,
            "scopes": DEFAULT_SCOPES,
            "state": state,
        }

    @api.post("/admin/facebook/test-config", tags=["Admin — Facebook"])
    async def test_config(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        """Iter43-fix24az-c — Validate App ID + App Secret WITHOUT going through
        the OAuth dance. Calls Facebook's `client_credentials` grant which
        returns an App Access Token if both are valid, else returns the exact
        FB error (e.g. "Error validating client secret").

        Saves the user from doing a full OAuth round-trip just to discover
        their secret was typed wrong.
        """
        s = await db.settings.find_one({"_id": "global"}) or {}
        app_id = (s.get("facebook_app_id") or "").strip()
        app_secret = (s.get("facebook_app_secret") or "").strip()
        if not app_id:
            raise HTTPException(status_code=400, detail="App ID manquant. Saisissez puis Enregistrer.")
        if not app_secret:
            raise HTTPException(status_code=400, detail="App Secret manquant. Saisissez puis Enregistrer.")
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
                r = await cli.get(FB_TOKEN_URL, params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "grant_type": "client_credentials",
                })
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "status_code": 0,
                "message": f"Erreur réseau : {str(exc)[:200]}",
                "app_id_masked": (app_id[:6] + "…" + app_id[-3:]) if len(app_id) > 10 else app_id,
            }
        if r.status_code != 200:
            # Try to extract the FB error structure
            err: Dict[str, Any] = {}
            try:
                err = r.json().get("error", {})
            except Exception:  # noqa: BLE001
                err = {}
            return {
                "ok": False,
                "status_code": r.status_code,
                "fb_error_code": err.get("code"),
                "fb_error_type": err.get("type"),
                "fb_error_message": err.get("message") or r.text[:200],
                "fb_trace_id": err.get("fbtrace_id"),
                "raw_body": r.text[:500],
                "app_id_masked": (app_id[:6] + "…" + app_id[-3:]) if len(app_id) > 10 else app_id,
            }
        # 200 — App Access Token returned. Keep it ephemeral (don't persist).
        try:
            tok_body = r.json()
        except Exception:  # noqa: BLE001
            tok_body = {}
        return {
            "ok": True,
            "status_code": 200,
            "message": "App ID + App Secret VALIDES (Facebook a renvoyé un App Access Token).",
            "token_type": tok_body.get("token_type"),
            "app_id_masked": (app_id[:6] + "…" + app_id[-3:]) if len(app_id) > 10 else app_id,
        }

    @api.get("/facebook/oauth/callback", tags=["Facebook"], name="facebook_oauth_callback")
    async def callback(
        request: Request,
        code: Optional[str] = Query(None),
        state: Optional[str] = Query(None),
        error: Optional[str] = Query(None),
        error_description: Optional[str] = Query(None),
    ):
        # Iter43-fix24az — defensive wrapper so unexpected errors render a
        # friendly HTML page instead of FastAPI's bare 500.
        try:
            if error:
                return HTMLResponse(_render_html(False, f"Facebook a refusé : {error} — {error_description or ''}"), 400)
            if not code or not state:
                return HTMLResponse(_render_html(False, "code/state requis."), 400)
            st = await db.facebook_oauth_states.find_one({"state": state})
            if not st:
                return HTMLResponse(_render_html(False, "State invalide."), 400)
            await db.facebook_oauth_states.delete_one({"state": state})
            s = await db.settings.find_one({"_id": "global"}) or {}
            app_id = (s.get("facebook_app_id") or "").strip()
            app_secret = (s.get("facebook_app_secret") or "").strip()
            if not app_id or not app_secret:
                return HTMLResponse(_render_html(False, "App ID/Secret perdus."), 500)
            # Step 1: exchange code for short-lived user token
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
                r = await cli.get(FB_TOKEN_URL, params={
                    "client_id": app_id, "redirect_uri": st["redirect_uri"],
                    "client_secret": app_secret, "code": code,
                })
            if r.status_code != 200:
                return HTMLResponse(_render_html(False, f"Échange code échoué : {r.text[:200]}"), 400)
            short = r.json()
            short_token = short.get("access_token")
            if not short_token:
                return HTMLResponse(_render_html(False, "Facebook n'a pas renvoyé d'access_token."), 400)
            # Step 2: exchange for long-lived (60 days)
            long_token = short_token
            expires_in = 0
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
                    r2 = await cli.get(FB_TOKEN_URL, params={
                        "grant_type": "fb_exchange_token",
                        "client_id": app_id, "client_secret": app_secret,
                        "fb_exchange_token": short_token,
                    })
                if r2.status_code == 200:
                    lj = r2.json()
                    long_token = lj.get("access_token") or short_token
                    expires_in = int(lj.get("expires_in") or 0)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[facebook] long-lived token exchange failed (non-fatal): %s", exc)
            # Step 3: fetch user info (tolerate failure)
            u: Dict[str, Any] = {}
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
                    ur = await cli.get(f"{FB_API_BASE}/me", params={"access_token": long_token, "fields": "id,name,email"})
                if ur.status_code == 200:
                    u = ur.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[facebook] /me failed (non-fatal): %s", exc)
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {
                    "facebook_user_access_token": long_token,
                    "facebook_user_token_expires_at": (_now_dt() + timedelta(seconds=expires_in)).isoformat() if expires_in else None,
                    "facebook_user_id": u.get("id", ""),
                    "facebook_user_name": u.get("name", ""),
                    "facebook_user_email": u.get("email", ""),
                    "facebook_connected_at": _now_iso(),
                    "facebook_connected_by": st.get("user_email", ""),
                }},
                upsert=True,
            )
            return HTMLResponse(_render_html(True, f"Facebook connecté en tant que {u.get('name', 'utilisateur')}. Sélectionnez une Page maintenant."))
        except Exception as exc:  # noqa: BLE001
            logger.exception("[facebook] callback unexpected error")
            return HTMLResponse(_render_html(False, f"Erreur inattendue : {str(exc)[:300]}"), 500)

    @api.get("/admin/facebook/pages", tags=["Admin — Facebook"])
    async def list_pages(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        ut = (s.get("facebook_user_access_token") or "").strip()
        if not ut:
            raise HTTPException(status_code=400, detail="Connectez d'abord votre compte Facebook utilisateur.")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
            r = await cli.get(f"{FB_API_BASE}/me/accounts", params={"access_token": ut, "fields": "id,name,access_token,category,tasks"})
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Échec lecture pages : {r.text[:300]}")
        pages = r.json().get("data", [])
        # Trim sensitive tokens from response for safety — but admin needs the token to select
        return {"pages": [{"id": p.get("id"), "name": p.get("name"), "category": p.get("category"),
                            "tasks": p.get("tasks", []), "access_token": p.get("access_token", "")} for p in pages]}

    @api.put("/admin/facebook/active-page", tags=["Admin — Facebook"])
    async def set_active_page(payload: ActivePagePayload = Body(...), user: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "facebook_page_id": payload.page_id,
                "facebook_page_name": payload.page_name or "",
                "facebook_page_access_token": payload.page_access_token,
                "facebook_active_page_set_at": _now_iso(),
                "facebook_active_page_set_by": user.get("email"),
            }},
        )
        return {"ok": True, "page_id": payload.page_id}

    @api.get("/facebook/status", tags=["Facebook"])
    async def status(_: dict = Depends(get_current_user)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "connected": bool(s.get("facebook_user_access_token")),
            "user_name": s.get("facebook_user_name", ""),
            "active_page_id": s.get("facebook_page_id", ""),
            "active_page_name": s.get("facebook_page_name", ""),
            "has_page_token": bool(s.get("facebook_page_access_token")),
            "user_token_expires_at": s.get("facebook_user_token_expires_at"),
            "connected_at": s.get("facebook_connected_at"),
        }

    @api.delete("/admin/facebook/connection", tags=["Admin — Facebook"])
    async def disconnect(user: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        await db.settings.update_one(
            {"_id": "global"},
            {"$unset": {
                "facebook_user_access_token": "", "facebook_user_token_expires_at": "",
                "facebook_user_id": "", "facebook_user_name": "", "facebook_user_email": "",
                "facebook_page_id": "", "facebook_page_name": "", "facebook_page_access_token": "",
                "facebook_connected_at": "", "facebook_connected_by": "",
            }},
        )
        await db.settings.update_one({"_id": "global"}, {"$set": {"facebook_disconnected_at": _now_iso(), "facebook_disconnected_by": user.get("email")}})
        return {"ok": True}

    @api.post("/facebook/posts", tags=["Facebook"])
    async def post(payload: FacebookPostPayload = Body(...), user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        if user.get("role") not in ("admin", "marketing", "communication"):
            raise HTTPException(status_code=403, detail="Réservé aux rôles admin/marketing")
        s = await db.settings.find_one({"_id": "global"}) or {}
        pid = (s.get("facebook_page_id") or "").strip()
        pt = (s.get("facebook_page_access_token") or "").strip()
        if not pid or not pt:
            raise HTTPException(status_code=400, detail="Aucune Page Facebook active. Connectez + sélectionnez une Page.")
        result = await _post_to_page(pid, pt, payload.text, payload.image_url)
        post_id = result.get("id") or result.get("post_id") or ""
        await db.facebook_posts_audit.insert_one({
            "user_id": user.get("id"), "user_email": user.get("email"),
            "post_id": post_id, "text": payload.text[:500],
            "image_url": payload.image_url, "page_id": pid, "created_at": _now_dt(),
        })
        return {"ok": True, "post_id": post_id, "raw": result}

    @api.get("/facebook/posts", tags=["Facebook"])
    async def list_page_posts(limit: int = Query(10, ge=1, le=50), _: dict = Depends(get_current_user)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        pid = (s.get("facebook_page_id") or "").strip()
        pt = (s.get("facebook_page_access_token") or "").strip()
        if not pid or not pt:
            raise HTTPException(status_code=400, detail="Aucune Page active.")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
            r = await cli.get(f"{FB_API_BASE}/{pid}/feed", params={"access_token": pt, "limit": limit, "fields": "id,message,created_time,permalink_url"})
        if r.status_code != 200:
            return {"items": [], "_error": f"HTTP {r.status_code}", "_detail": r.text[:300]}
        items = []
        for p in r.json().get("data", []):
            items.append({
                "post_id": p.get("id", ""), "text": p.get("message", ""),
                "created_at": p.get("created_time"), "permalink": p.get("permalink_url"),
            })
        return {"items": items, "page_id": pid, "page_name": s.get("facebook_page_name", "")}

    logger.info("[facebook] routes mounted under /api/admin/facebook/* + /api/facebook/*")


def _render_html(success: bool, message: str) -> str:
    color = "#16a34a" if success else "#dc2626"
    icon = "✅" if success else "❌"
    safe = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>sawalismartsystems — Facebook OAuth</title>
<style>body{{font-family:system-ui;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#1e293b;padding:32px;border-radius:12px;max-width:480px;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.4)}}
h1{{color:{color};margin:0 0 12px;font-size:22px}}.icon{{font-size:48px;margin-bottom:16px}}
a{{display:inline-block;margin-top:18px;padding:10px 20px;background:#1877f2;color:#fff;border-radius:6px;text-decoration:none}}</style></head>
<body><div class="card"><div class="icon">{icon}</div><h1>Facebook OAuth — {"Succès" if success else "Échec"}</h1>
<p>{safe}</p><a href="/admin/settings">← Retour</a></div>
<script>if(window.opener){{try{{window.opener.postMessage({{type:'facebook-oauth-result',success:{str(success).lower()},message:{repr(safe)}}},'*');setTimeout(()=>window.close(),1500)}}catch(e){{}}}}</script>
</body></html>"""
