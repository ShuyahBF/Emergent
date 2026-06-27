"""Iter43-fix24au (2026-02-26) — LinkedIn integration for SAWALI.

Provides OAuth2 Authorization Code Flow + Post creation (text + optional image)
+ Post listing for both **member profile** and **organization page**.

Routes mounted under :
  - GET    /api/admin/linkedin/config            — current config (masked secrets)
  - PUT    /api/admin/linkedin/config            — set/update client_id, client_secret
  - GET    /api/admin/linkedin/oauth/authorize   — returns LinkedIn authorization URL
  - GET    /api/linkedin/oauth/callback          — handles LinkedIn redirect (state validation + token exchange)
  - GET    /api/linkedin/status                  — current connection status (any user)
  - DELETE /api/admin/linkedin/connection        — disconnect (clears tokens + org list)
  - POST   /api/linkedin/posts                   — create a post (text + optional image_url)
  - GET    /api/linkedin/posts                   — list latest posts (where allowed)

Storage : everything lives under `db.settings._id="global"` so the LinkedIn
connection is **shared** across the CRM (SAWALI's official LinkedIn). One
admin connects once, all marketing operators reuse the same token.

Secrets masked through `GET_MASK_FIELDS` in `routes/admin_settings.py` :
  - `linkedin_client_secret`
  - `linkedin_access_token`
  - `linkedin_refresh_token`
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

logger = logging.getLogger("sawali.linkedin")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_API_BASE = "https://api.linkedin.com"
LINKEDIN_API_VERSION = "202507"
DEFAULT_TIMEOUT = 30

# Recommended scope set when both member + organization posting are needed.
# `r_member_social` is a closed permission per LinkedIn docs — we still request
# it (LinkedIn will ignore if not granted).
DEFAULT_SCOPES = [
    "openid",
    "profile",
    "email",
    "w_member_social",
    "r_member_social",
    "w_organization_social",
    "r_organization_social",
]


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


# --------------------------------------------------------------------------- #
# Payloads
# --------------------------------------------------------------------------- #
class LinkedInConfigPayload(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    # Allows overriding the redirect URI per environment (preview vs prod).
    # If left empty, the backend computes it from REACT_APP_BACKEND_URL or
    # the X-Forwarded-Host header.
    redirect_uri: Optional[str] = None
    # Allows admins to opt in/out of organization scopes.
    enable_member: Optional[bool] = None
    enable_organization: Optional[bool] = None


class CreatePostPayload(BaseModel):
    text: str
    image_url: Optional[str] = None
    author_type: str = "member"  # "member" | "organization"
    organization_urn: Optional[str] = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _load_settings(db) -> Dict[str, Any]:
    return await db.settings.find_one({"_id": "global"}) or {}


def _compute_redirect_uri(request: Request, settings: Dict[str, Any]) -> str:
    """Pick a redirect URI in this priority order :
    1. `settings.linkedin_redirect_uri` if explicitly set by admin.
    2. `https://{X-Forwarded-Host}/api/linkedin/oauth/callback` (preview/prod).
    3. Fallback to the request's own origin.
    """
    explicit = (settings.get("linkedin_redirect_uri") or "").strip()
    if explicit:
        return explicit
    # X-Forwarded-Host is set by the K8s ingress.
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    fwd_proto = request.headers.get("x-forwarded-proto") or "https"
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}/api/linkedin/oauth/callback"
    return str(request.url_for("linkedin_oauth_callback"))


async def _exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange the authorization code for tokens."""
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
        r = await cli.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Échange de code LinkedIn échoué ({r.status_code}) : {r.text[:300]}",
        )
    return r.json()


async def _refresh_token(client_id: str, client_secret: str, refresh_token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
        r = await cli.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Refresh LinkedIn échoué ({r.status_code}) : {r.text[:300]}",
        )
    return r.json()


async def _userinfo(access_token: str) -> Dict[str, Any]:
    """OpenID Connect /v2/userinfo — returns sub (member ID), name, email, picture."""
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
        r = await cli.get(
            f"{LINKEDIN_API_BASE}/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"LinkedIn /v2/userinfo a échoué ({r.status_code}) : {r.text[:300]}",
        )
    return r.json()


async def _list_admin_organizations(access_token: str) -> List[Dict[str, Any]]:
    """Lookup the organizations where the connected member has ADMIN/CONTENT_ADMIN
    roles. Requires Community Management API access.

    Returns a list of `{urn, name, vanity_name}`. Empty list if LinkedIn refuses
    (insufficient scope) — that's expected for apps without Community Mgmt
    approval, and member posting still works.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-RestLi-Protocol-Version": "2.0.0",
    }
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as cli:
            # Step 1 : list ACLs (organizationAcls?q=roleAssignee&role=ADMINISTRATOR)
            r = await cli.get(
                f"{LINKEDIN_API_BASE}/rest/organizationAcls",
                headers=headers,
                params={
                    "q": "roleAssignee",
                    "role": "ADMINISTRATOR",
                    "state": "APPROVED",
                },
            )
            if r.status_code != 200:
                logger.info("[linkedin] organizationAcls returned %s : %s", r.status_code, r.text[:200])
                return []
            acls = r.json().get("elements", [])
            org_urns = [a.get("organization") for a in acls if a.get("organization")]
            if not org_urns:
                return []
            # Step 2 : resolve names via /rest/organizations/{id}
            orgs: List[Dict[str, Any]] = []
            for urn in org_urns[:20]:  # cap to avoid abuse
                org_id = urn.rsplit(":", 1)[-1]
                try:
                    rr = await cli.get(
                        f"{LINKEDIN_API_BASE}/rest/organizations/{org_id}",
                        headers=headers,
                    )
                    if rr.status_code == 200:
                        d = rr.json()
                        loc = (d.get("localizedName") or {})
                        name = d.get("localizedName") if isinstance(d.get("localizedName"), str) else (
                            (loc.get("value") if isinstance(loc, dict) else None) or d.get("vanityName") or urn
                        )
                        orgs.append({
                            "urn": urn,
                            "name": name,
                            "vanity_name": d.get("vanityName", ""),
                        })
                    else:
                        orgs.append({"urn": urn, "name": urn, "vanity_name": ""})
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[linkedin] org lookup %s failed: %s", urn, exc)
                    orgs.append({"urn": urn, "name": urn, "vanity_name": ""})
            return orgs
    except httpx.HTTPError as exc:
        logger.info("[linkedin] org list HTTP error: %s", exc)
        return []


async def _ensure_token_valid(db, settings: Dict[str, Any]) -> str:
    """Return a non-expired access_token, refreshing if needed."""
    access = (settings.get("linkedin_access_token") or "").strip()
    if not access:
        raise HTTPException(status_code=400, detail="LinkedIn non connecté. Allez dans Admin → Settings → LinkedIn.")
    expires_at_iso = settings.get("linkedin_token_expires_at")
    if not expires_at_iso:
        return access
    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except (TypeError, ValueError):
        return access
    if expires_at - _now_dt() > timedelta(minutes=5):
        return access  # still valid for at least 5 min
    refresh = (settings.get("linkedin_refresh_token") or "").strip()
    if not refresh:
        # Token expired and no refresh token → user must reconnect
        raise HTTPException(
            status_code=401,
            detail="Token LinkedIn expiré et pas de refresh_token. Reconnectez le compte (Admin → Settings).",
        )
    cid = (settings.get("linkedin_client_id") or "").strip()
    csec = (settings.get("linkedin_client_secret") or "").strip()
    if not cid or not csec:
        raise HTTPException(status_code=400, detail="Client ID / Secret LinkedIn manquant en base.")
    fresh = await _refresh_token(cid, csec, refresh)
    new_access = fresh.get("access_token")
    new_expires_in = int(fresh.get("expires_in") or 0)
    if not new_access:
        raise HTTPException(status_code=401, detail="Refresh LinkedIn a renvoyé un token vide. Reconnectez.")
    new_expires_at = _now_dt() + timedelta(seconds=new_expires_in)
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "linkedin_access_token": new_access,
            "linkedin_token_expires_at": new_expires_at.isoformat(),
            "linkedin_refreshed_at": _now_iso(),
        }},
    )
    return new_access


# --------------------------------------------------------------------------- #
# LinkedIn API calls — posts + images
# --------------------------------------------------------------------------- #
async def _initialize_image_upload(access_token: str, owner_urn: str) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-RestLi-Protocol-Version": "2.0.0",
    }
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            f"{LINKEDIN_API_BASE}/rest/images?action=initializeUpload",
            headers=headers,
            json={"initializeUploadRequest": {"owner": owner_urn}},
        )
    if r.status_code not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"LinkedIn image init failed ({r.status_code}) : {r.text[:300]}",
        )
    return r.json()


async def _upload_image_from_url(access_token: str, owner_urn: str, image_url: str) -> str:
    """Download `image_url` server-side and upload it to LinkedIn. Returns
    the `urn:li:image:...` URN that can be embedded in a post."""
    async with httpx.AsyncClient(timeout=60) as cli:
        img_r = await cli.get(image_url)
    if img_r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Image source inaccessible ({img_r.status_code}) : {image_url[:200]}",
        )
    img_bytes = img_r.content
    ctype = img_r.headers.get("content-type", "image/jpeg")

    init = await _initialize_image_upload(access_token, owner_urn)
    value = (init.get("value") or {})
    upload_url = value.get("uploadUrl")
    image_urn = value.get("image")
    if not upload_url or not image_urn:
        raise HTTPException(status_code=502, detail=f"LinkedIn init malformé : {init}")
    async with httpx.AsyncClient(timeout=120) as cli:
        u = await cli.put(
            upload_url,
            content=img_bytes,
            headers={"Content-Type": ctype, "Authorization": f"Bearer {access_token}"},
        )
    if u.status_code not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"Upload image LinkedIn échoué ({u.status_code}) : {u.text[:200]}",
        )
    return image_urn


async def _create_post(access_token: str, author_urn: str, text: str, image_urn: Optional[str]) -> str:
    """Returns the created post URN."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-RestLi-Protocol-Version": "2.0.0",
    }
    body: Dict[str, Any] = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
    }
    if image_urn:
        body["content"] = {"media": {"id": image_urn}}
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(f"{LINKEDIN_API_BASE}/rest/posts", headers=headers, json=body)
    if r.status_code not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"Création post LinkedIn échouée ({r.status_code}) : {r.text[:500]}",
        )
    post_urn = r.headers.get("x-restli-id") or r.headers.get("X-RestLi-Id")
    if not post_urn:
        # Try to find it in the body
        try:
            data = r.json()
            post_urn = data.get("id") or data.get("urn") or ""
        except Exception:  # noqa: BLE001
            post_urn = ""
    return post_urn or "(URN inconnu)"


async def _list_posts(access_token: str, author_urn: str, count: int = 10) -> List[Dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-RestLi-Protocol-Version": "2.0.0",
    }
    params = {
        "q": "author",
        "author": author_urn,
        "count": count,
        "sortBy": "LAST_MODIFIED",
    }
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.get(f"{LINKEDIN_API_BASE}/rest/posts", headers=headers, params=params)
    if r.status_code != 200:
        # LinkedIn returns 403 if the read scope is not granted (very common).
        # Surface it gently so the UI can display a helpful message.
        return [{"_error": f"HTTP {r.status_code}", "_detail": r.text[:400]}]
    data = r.json()
    elements = data.get("elements", []) or []
    out: List[Dict[str, Any]] = []
    for el in elements:
        out.append({
            "urn": el.get("id") or el.get("urn") or "",
            "text": (el.get("commentary") or "") if isinstance(el.get("commentary"), str) else "",
            "lifecycle_state": el.get("lifecycleState"),
            "created_at": (el.get("createdAt") or el.get("publishedAt") or None),
        })
    return out


# --------------------------------------------------------------------------- #
# Route mounting
# --------------------------------------------------------------------------- #
def attach_linkedin_routes(*, api, db, get_current_user, get_current_admin):
    """Mount the LinkedIn endpoints."""

    @api.get("/admin/linkedin/config", tags=["Admin — LinkedIn"])
    async def admin_get_linkedin_config(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await _load_settings(db)
        return {
            "client_id": s.get("linkedin_client_id") or "",
            "client_secret": "********" if s.get("linkedin_client_secret") else "",
            "redirect_uri": s.get("linkedin_redirect_uri") or "",
            "enable_member": bool(s.get("linkedin_enable_member", True)),
            "enable_organization": bool(s.get("linkedin_enable_organization", True)),
            "connected": bool(s.get("linkedin_access_token")),
            "member_urn": s.get("linkedin_member_urn", ""),
            "member_name": s.get("linkedin_member_name", ""),
            "scopes": s.get("linkedin_scopes", []),
            "organizations": s.get("linkedin_organizations", []),
            "token_expires_at": s.get("linkedin_token_expires_at"),
            "refresh_expires_at": s.get("linkedin_refresh_expires_at"),
            "connected_at": s.get("linkedin_connected_at"),
            "connected_by": s.get("linkedin_connected_by"),
        }

    @api.put("/admin/linkedin/config", tags=["Admin — LinkedIn"])
    async def admin_put_linkedin_config(
        payload: LinkedInConfigPayload = Body(...),
        user: dict = Depends(get_current_admin),
    ) -> Dict[str, Any]:
        update: Dict[str, Any] = {}
        if payload.client_id is not None:
            update["linkedin_client_id"] = payload.client_id.strip()
        if payload.client_secret is not None and payload.client_secret != "********":
            update["linkedin_client_secret"] = payload.client_secret.strip()
        if payload.redirect_uri is not None:
            update["linkedin_redirect_uri"] = payload.redirect_uri.strip()
        if payload.enable_member is not None:
            update["linkedin_enable_member"] = bool(payload.enable_member)
        if payload.enable_organization is not None:
            update["linkedin_enable_organization"] = bool(payload.enable_organization)
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["linkedin_config_updated_at"] = _now_iso()
        update["linkedin_config_updated_by"] = user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    @api.get("/admin/linkedin/oauth/authorize", tags=["Admin — LinkedIn"])
    async def admin_linkedin_authorize(
        request: Request,
        user: dict = Depends(get_current_admin),
    ) -> Dict[str, Any]:
        s = await _load_settings(db)
        cid = (s.get("linkedin_client_id") or "").strip()
        csec = (s.get("linkedin_client_secret") or "").strip()
        if not cid or not csec:
            raise HTTPException(
                status_code=400,
                detail="Configurez Client ID + Client Secret avant de lancer l'autorisation.",
            )
        redirect_uri = _compute_redirect_uri(request, s)
        state = pysecrets.token_urlsafe(32)
        # Persist state in MongoDB (state must survive the redirect, OAuth is
        # cross-host: LinkedIn → our backend → no cookie attached in callback)
        await db.linkedin_oauth_states.insert_one({
            "state": state,
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "redirect_uri": redirect_uri,
            "created_at": _now_dt(),
        })
        # Build scope list based on admin toggles
        scopes: List[str] = ["openid", "profile", "email"]
        if s.get("linkedin_enable_member", True):
            scopes += ["w_member_social", "r_member_social"]
        if s.get("linkedin_enable_organization", True):
            scopes += ["w_organization_social", "r_organization_social"]
        params = {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
        url = f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"
        logger.info("[linkedin] authorize → redirect_uri=%s scopes=%s state=%s", redirect_uri, scopes, state[:8])
        return {
            "authorization_url": url,
            "redirect_uri": redirect_uri,
            "scopes": scopes,
            "state": state,
        }

    @api.get("/admin/linkedin/oauth/preview-redirect-uri", tags=["Admin — LinkedIn"])
    async def admin_linkedin_preview_redirect_uri(
        request: Request,
        _: dict = Depends(get_current_admin),
    ) -> Dict[str, Any]:
        """Iter43-fix24au-fix1 — Returns the EXACT redirect_uri the backend
        will send to LinkedIn for OAuth, so the admin can register it in their
        LinkedIn App before clicking « Connecter ».

        Lightweight (no DB write, no state generation) — safe to call on every
        section mount.
        """
        s = await _load_settings(db)
        redirect_uri = _compute_redirect_uri(request, s)
        # Also expose the explicit setting + computed fallback so the UI can
        # tell the user which one is in effect.
        return {
            "redirect_uri": redirect_uri,
            "explicit_override": s.get("linkedin_redirect_uri") or "",
            "computed_from_host": request.headers.get("x-forwarded-host") or request.headers.get("host") or "",
            "computed_proto": request.headers.get("x-forwarded-proto") or "https",
        }

    @api.get("/linkedin/oauth/callback", tags=["LinkedIn"], name="linkedin_oauth_callback")
    async def linkedin_oauth_callback(
        request: Request,
        code: Optional[str] = Query(None),
        state: Optional[str] = Query(None),
        error: Optional[str] = Query(None),
        error_description: Optional[str] = Query(None),
    ):
        """Handles LinkedIn's redirect. Public endpoint (LinkedIn does NOT send
        any auth header). State validation happens against our DB. On success
        we render a tiny HTML page that auto-closes the popup or redirects to
        Admin Settings.

        Iter43-fix24az (2026-02-26) — Wrap the whole body in a try/except so
        that any unexpected exception (network glitch, JSON parse, LinkedIn
        API quirk…) renders a friendly HTML page instead of FastAPI's bare
        "Internal Server Error". The previous version surfaced raw 500s when
        e.g. /v2/userinfo timed out, which the user encountered in production.
        """
        try:
            if error:
                return HTMLResponse(
                    _render_html(success=False, message=f"LinkedIn a refusé : {error} — {error_description or ''}"),
                    status_code=400,
                )
            if not code or not state:
                return HTMLResponse(
                    _render_html(success=False, message="Paramètres `code` et `state` requis."),
                    status_code=400,
                )
            st = await db.linkedin_oauth_states.find_one({"state": state})
            if not st:
                return HTMLResponse(
                    _render_html(success=False, message="State invalide ou déjà utilisé."),
                    status_code=400,
                )
            # One-shot state
            await db.linkedin_oauth_states.delete_one({"state": state})
            # Reject states older than 15 min — handle both tz-aware (Python
            # datetime stored by us) and tz-naive (BSON Date read back by
            # motor's default tz_aware=False) created_at values, otherwise
            # the subtraction raises "can't subtract offset-naive and
            # offset-aware datetimes".
            created_at = st.get("created_at")
            if isinstance(created_at, datetime):
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if (_now_dt() - created_at) > timedelta(minutes=15):
                    return HTMLResponse(
                        _render_html(success=False, message="State expiré (> 15 min). Relancez la connexion."),
                        status_code=400,
                    )

            s = await _load_settings(db)
            cid = (s.get("linkedin_client_id") or "").strip()
            csec = (s.get("linkedin_client_secret") or "").strip()
            if not cid or not csec:
                return HTMLResponse(
                    _render_html(success=False, message="Config LinkedIn perdue côté serveur."),
                    status_code=500,
                )

            try:
                tok = await _exchange_code(cid, csec, code, st.get("redirect_uri"))
            except HTTPException as exc:
                return HTMLResponse(
                    _render_html(success=False, message=str(exc.detail)),
                    status_code=exc.status_code,
                )

            access = tok.get("access_token")
            if not access:
                return HTMLResponse(
                    _render_html(success=False, message="LinkedIn n'a pas renvoyé d'access_token."),
                    status_code=400,
                )
            expires_in = int(tok.get("expires_in") or 0)
            refresh = tok.get("refresh_token")
            refresh_expires_in = int(tok.get("refresh_token_expires_in") or 0)
            scope_str = tok.get("scope") or ""
            scopes = scope_str.split() if scope_str else []
            token_expires_at = _now_dt() + timedelta(seconds=expires_in) if expires_in else None
            refresh_expires_at = _now_dt() + timedelta(seconds=refresh_expires_in) if refresh_expires_in else None

            # Fetch profile via /v2/userinfo (works with openid+profile+email).
            # Tolerate ANY failure here — the access token is already valid
            # and the connection should not be aborted just because the
            # profile endpoint hiccupped.
            ui: Dict[str, Any] = {}
            try:
                ui = await _userinfo(access)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[linkedin] /v2/userinfo failed (non-fatal): %s", exc)
            sub = ui.get("sub") or ""
            member_urn = f"urn:li:person:{sub}" if sub else ""
            raw_name = ui.get("name")
            given_family = (ui.get("given_name") or "") + " " + (ui.get("family_name") or "")
            member_name = (raw_name or given_family).strip()
            member_picture = ui.get("picture") or ""
            member_email = ui.get("email") or ""

            # Discover organizations the connected user can post for
            try:
                orgs = await _list_admin_organizations(access)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[linkedin] org listing failed (non-fatal): %s", exc)
                orgs = []

            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {
                    "linkedin_access_token": access,
                    "linkedin_token_expires_at": token_expires_at.isoformat() if token_expires_at else None,
                    "linkedin_refresh_token": refresh,
                    "linkedin_refresh_expires_at": refresh_expires_at.isoformat() if refresh_expires_at else None,
                    "linkedin_scopes": scopes,
                    "linkedin_member_urn": member_urn,
                    "linkedin_member_name": member_name,
                    "linkedin_member_picture": member_picture,
                    "linkedin_member_email": member_email,
                    "linkedin_organizations": orgs,
                    "linkedin_connected_at": _now_iso(),
                    "linkedin_connected_by": st.get("user_email") or "",
                }},
                upsert=True,
            )
            logger.info(
                "[linkedin] OAuth success — member=%s orgs=%d scopes=%s",
                member_urn or "(unknown)", len(orgs), scopes,
            )
            display_name = member_name or member_urn or "(profil indéterminé)"
            return HTMLResponse(
                _render_html(
                    success=True,
                    message=f"LinkedIn connecté avec succès en tant que « {display_name} »."
                            f" {len(orgs)} organisation(s) gérée(s) détectée(s).",
                )
            )
        except Exception as exc:  # noqa: BLE001 — final safety net
            logger.exception("[linkedin] callback unexpected error")
            return HTMLResponse(
                _render_html(
                    success=False,
                    message=f"Erreur inattendue durant la callback LinkedIn : {str(exc)[:300]}",
                ),
                status_code=500,
            )

    @api.get("/linkedin/status", tags=["LinkedIn"])
    async def linkedin_status(_: dict = Depends(get_current_user)) -> Dict[str, Any]:
        s = await _load_settings(db)
        connected = bool(s.get("linkedin_access_token"))
        return {
            "connected": connected,
            "member_urn": s.get("linkedin_member_urn", ""),
            "member_name": s.get("linkedin_member_name", ""),
            "member_picture": s.get("linkedin_member_picture", ""),
            "member_email": s.get("linkedin_member_email", ""),
            "scopes": s.get("linkedin_scopes", []),
            "organizations": s.get("linkedin_organizations", []),
            "token_expires_at": s.get("linkedin_token_expires_at"),
            "refresh_expires_at": s.get("linkedin_refresh_expires_at"),
            "connected_at": s.get("linkedin_connected_at"),
            "connected_by": s.get("linkedin_connected_by"),
        }

    @api.delete("/admin/linkedin/connection", tags=["Admin — LinkedIn"])
    async def admin_linkedin_disconnect(user: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        await db.settings.update_one(
            {"_id": "global"},
            {"$unset": {
                "linkedin_access_token": "",
                "linkedin_token_expires_at": "",
                "linkedin_refresh_token": "",
                "linkedin_refresh_expires_at": "",
                "linkedin_scopes": "",
                "linkedin_member_urn": "",
                "linkedin_member_name": "",
                "linkedin_member_picture": "",
                "linkedin_member_email": "",
                "linkedin_organizations": "",
                "linkedin_connected_at": "",
                "linkedin_connected_by": "",
            }},
        )
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"linkedin_disconnected_at": _now_iso(), "linkedin_disconnected_by": user.get("email")}},
        )
        return {"ok": True}

    @api.post("/linkedin/posts", tags=["LinkedIn"])
    async def create_linkedin_post(
        payload: CreatePostPayload = Body(...),
        user: dict = Depends(get_current_user),
    ) -> Dict[str, Any]:
        # Only admins + marketing roles can post (keep it simple : admin only for now)
        if user.get("role") not in ("admin", "marketing", "communication"):
            raise HTTPException(status_code=403, detail="Réservé aux rôles admin / marketing")
        s = await _load_settings(db)
        access = await _ensure_token_valid(db, s)
        # Resolve author URN
        if payload.author_type == "member":
            author_urn = s.get("linkedin_member_urn") or ""
            if not author_urn:
                raise HTTPException(status_code=400, detail="member_urn introuvable. Reconnectez LinkedIn.")
        elif payload.author_type == "organization":
            if not payload.organization_urn:
                raise HTTPException(status_code=400, detail="`organization_urn` requis pour author_type=organization")
            allowed = {o.get("urn") for o in (s.get("linkedin_organizations") or [])}
            if payload.organization_urn not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Vous n'êtes pas administrateur de {payload.organization_urn}. Orgs disponibles : {sorted(allowed)}",
                )
            author_urn = payload.organization_urn
        else:
            raise HTTPException(status_code=400, detail="author_type doit être 'member' ou 'organization'")
        # Optional image upload
        image_urn = None
        if payload.image_url:
            image_urn = await _upload_image_from_url(access, author_urn, payload.image_url)
        post_urn = await _create_post(access, author_urn, payload.text, image_urn)
        # Audit
        await db.linkedin_posts_audit.insert_one({
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "author_urn": author_urn,
            "author_type": payload.author_type,
            "text": payload.text[:2000],
            "image_url": payload.image_url,
            "image_urn": image_urn,
            "post_urn": post_urn,
            "created_at": _now_dt(),
        })
        return {"ok": True, "post_urn": post_urn, "author_urn": author_urn, "image_urn": image_urn}

    @api.get("/linkedin/posts", tags=["LinkedIn"])
    async def list_linkedin_posts(
        author_type: str = Query("member", regex="^(member|organization)$"),
        organization_urn: Optional[str] = Query(None),
        limit: int = Query(10, ge=1, le=50),
        user: dict = Depends(get_current_user),
    ) -> Dict[str, Any]:
        s = await _load_settings(db)
        access = await _ensure_token_valid(db, s)
        if author_type == "member":
            author_urn = s.get("linkedin_member_urn") or ""
            if not author_urn:
                raise HTTPException(status_code=400, detail="member_urn introuvable. Reconnectez LinkedIn.")
        else:
            if not organization_urn:
                raise HTTPException(status_code=400, detail="organization_urn requis")
            allowed = {o.get("urn") for o in (s.get("linkedin_organizations") or [])}
            if organization_urn not in allowed:
                raise HTTPException(status_code=403, detail=f"Org non autorisée : {organization_urn}")
            author_urn = organization_urn
        items = await _list_posts(access, author_urn, count=limit)
        return {"items": items, "author_urn": author_urn}

    # Best-effort cleanup of old states (>1h)
    async def _cleanup_old_states():
        try:
            cutoff = _now_dt() - timedelta(hours=1)
            await db.linkedin_oauth_states.delete_many({"created_at": {"$lt": cutoff}})
        except Exception as exc:  # noqa: BLE001
            logger.warning("[linkedin] state cleanup error: %s", exc)

    try:
        import asyncio
        asyncio.get_event_loop().create_task(_cleanup_old_states())
    except Exception:  # noqa: BLE001
        pass

    logger.info("[linkedin] routes mounted under /api/admin/linkedin/* + /api/linkedin/*")


def _render_html(success: bool, message: str) -> str:
    """Tiny HTML page rendered after LinkedIn callback. Self-closing window
    if opened in a popup, else redirects to Admin Settings."""
    color = "#16a34a" if success else "#dc2626"
    icon = "✅" if success else "❌"
    safe_msg = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>sawalismartsystems — LinkedIn OAuth</title>
  <style>
    body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
            background: #0f172a; color: #e2e8f0; display: flex; align-items: center;
            justify-content: center; min-height: 100vh; margin: 0; }}
    .card {{ background: #1e293b; padding: 32px; border-radius: 12px;
             max-width: 480px; text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }}
    h1 {{ color: {color}; margin: 0 0 12px; font-size: 22px; }}
    p {{ margin: 8px 0; line-height: 1.5; }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    a {{ display: inline-block; margin-top: 18px; padding: 10px 20px;
         background: #0a66c2; color: white; border-radius: 6px; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>LinkedIn OAuth — {"Succès" if success else "Échec"}</h1>
    <p>{safe_msg}</p>
    <a href="/admin/settings">← Retour à Admin Settings</a>
  </div>
  <script>
    // If opened in a popup, notify the parent window and close.
    if (window.opener) {{
      try {{
        window.opener.postMessage(
          {{ type: 'linkedin-oauth-result', success: {str(success).lower()}, message: {repr(safe_msg)} }},
          '*'
        );
        setTimeout(function() {{ window.close(); }}, 1500);
      }} catch (e) {{}}
    }}
  </script>
</body>
</html>"""
