"""SAWALI SMART SYSTEMS - Main FastAPI server.

All API routes are prefixed with /api and registered here in a single file
for easy navigation. They are organized in sections:
  - Health
  - Auth & OTP
  - Public (catalog, RDV, contact, content)
  - Client portal (account, RDV, documents, interventions, users tracking)
  - Admin (clients, content, documents upload, settings, GCal OAuth, reports)
  - File serving
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import uuid
import asyncio
import ipaddress
import json
import logging
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Any, Dict

import httpx

from fastapi import (
    FastAPI,
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Query,
    Request,
)
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, Response, PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, EmailStr

from db import db, serialize, serialize_many
from models import (
    UserPublic,
    UserCreateAdmin,
    UserUpdateAdmin,
    LoginRequest,
    LoginResponse,
    OtpVerifyRequest,
    AuthTokenResponse,
    ChangePasswordRequest,
    PublicAppointmentRequest,
    ClientAppointmentRequest,
    AppointmentUpdate,
    InterventionCreate,
    InterventionUpdate,
    DocumentCreate,
    DocumentUpdate,
    ContentUpsert,
    ContactCreate,
    TrackedUserCreate,
    TrackedUserUpdate,
    SettingsUpdate,
    SaveContactAsTrackedUser,
    DocumentCategoryCreate,
    DocumentCategoryUpdate,
    ClientCategoryCreate,
    ClientCategoryUpdate,
    DeploymentCreate,
    DeploymentUpdate,
    BlacklistedIPCreate,
    UserNoteCreate,
    UserNoteUpdate,
    TrackedUserSetPassword,
    RatingCreate,
    AccessLogCreate,
    ApiTraceCreate,
    FormationCreate,
    FormationUpdate,
    FormationModuleCreate,
    FormationModuleUpdate,
    FormationCreditsUpdate,
    FormationStateUpdate,
    FormationModuleQuestion,
    TRACKED_USER_ROLES,
    USER_ROLES,
    _uuid,
    _now,
)
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    generate_otp,
    generate_session_token,
    get_current_user,
    get_current_admin,
)
from email_service import send_otp_email
from recaptcha import verify_recaptcha
import google_calendar as gcal


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
POLICIES_DIR = UPLOAD_DIR / "policies"
POLICIES_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")


def _public_base_url(request: Optional["Request"] = None) -> str:
    """Resolve the public base URL for absolute links (OAuth redirects, file URLs).

    Strategy:
      1. Use the browser-supplied Origin header first — when an admin clicks a button
         from sawalismartsystems.com, Origin is the source of truth even when the
         ingress rewrites X-Forwarded-Host to its internal hostname.
      2. Fall back to X-Forwarded-Host / Host (set by ingress).
      3. Fall back to the static PUBLIC_BASE_URL env var.
    """
    if request is not None:
        try:
            origin = request.headers.get("origin")
            if origin and origin.startswith(("http://", "https://")):
                return origin.rstrip("/")
            xfh = request.headers.get("x-forwarded-host") or request.headers.get("host")
            xfp = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
            if xfh:
                return f"{xfp}://{xfh.split(',')[0].strip()}".rstrip("/")
        except Exception:
            pass
    return (PUBLIC_BASE_URL or "").rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sawali")

app = FastAPI(
    title="SAWALI SMART SYSTEMS API",
    version="1.0.0",
    description=(
        "API officielle pour le site web de SAWALI SMART SYSTEMS. "
        "Tous les endpoints sont préfixés par /api. "
        "Documentation interactive : /docs (Swagger) et /redoc."
    ),
)
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# Cached compiled blacklist networks; refreshed on every settings/blacklist change.
_BLACKLIST_CACHE: dict = {"nets": [], "loaded": False}


async def _reload_blacklist() -> None:
    items = await db.blacklisted_ips.find({}, {"_id": 0}).to_list(5000)
    nets = []
    for it in items:
        cidr = (it.get("cidr") or "").strip()
        if not cidr:
            continue
        try:
            if "/" in cidr:
                nets.append(ipaddress.ip_network(cidr, strict=False))
            else:
                nets.append(ipaddress.ip_network(f"{cidr}/32" if "." in cidr else f"{cidr}/128", strict=False))
        except ValueError:
            continue
    _BLACKLIST_CACHE["nets"] = nets
    _BLACKLIST_CACHE["loaded"] = True


def _client_ip_from_request(request) -> str:
    # Trust X-Forwarded-For first hop (set by Kubernetes ingress)
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


@app.middleware("http")
async def ip_blacklist_middleware(request, call_next):
    # Apply only to /api/* (the public site files & assets are served separately)
    path = request.url.path or ""
    if path.startswith("/api/") and not path.startswith("/api/admin/blacklisted-ips"):
        if not _BLACKLIST_CACHE["loaded"]:
            try:
                await _reload_blacklist()
            except Exception:  # noqa: BLE001
                _BLACKLIST_CACHE["loaded"] = True  # don't block forever on first error
        try:
            client_ip = _client_ip_from_request(request)
            if client_ip and _BLACKLIST_CACHE["nets"]:
                ip_obj = ipaddress.ip_address(client_ip)
                for net in _BLACKLIST_CACHE["nets"]:
                    if ip_obj in net:
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "Adresse IP bloquée par l'administrateur."},
                        )
        except (ValueError, TypeError):
            pass
    return await call_next(request)


# ====================================================================
# Helpers
# ====================================================================
def _to_user_public(u: dict) -> dict:
    return {
        "id": u["id"],
        "email": u["email"],
        "full_name": u["full_name"],
        "role": u["role"],
        "phone": u.get("phone"),
        "company": u.get("company"),
        "account_status": u.get("account_status", "active"),
        "created_at": u["created_at"],
        "is_primary_client": bool(u.get("is_primary_client", False)),
        "logo_url": u.get("logo_url"),
        "tracked_role": u.get("tracked_role"),
        "tracked_user_id": u.get("tracked_user_id"),
        "parent_client_id": u.get("parent_client_id"),
    }


async def _get_settings_doc() -> dict:
    s = await db.settings.find_one({"_id": "global"})
    if s is None:
        s = {
            "_id": "global",
            "recaptcha_enabled": False,
            "smtp_use_tls": True,
            "business_open_time": "09:00",
            "business_close_time": "18:00",
            "business_days": [0, 1, 2, 3, 4],
            "slot_duration_min": 30,
        }
        await db.settings.insert_one(s)
    s.pop("_id", None)
    # mask sensitive values
    return s


# ---- Email syntax validation (RFC 5322 simplified) ----
_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_email_syntax(email: str) -> bool:
    return bool(email and _EMAIL_REGEX.match(email.strip()))


# ---- Intervention number generator (per client / year) ----
def _slugify_code(value: str) -> str:
    """Best-effort short uppercase slug for client code (max 8 chars)."""
    if not value:
        return "X"
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
    return (cleaned or "X")[:8]


async def _next_intervention_number(client_doc: dict) -> str:
    """Generate INT-YYYY-CODE-NNNN, sequential per client/year."""
    year = datetime.now(timezone.utc).year
    code = (client_doc.get("client_code") or "").strip()
    if not code:
        code = _slugify_code(client_doc.get("company") or client_doc.get("full_name") or "X")
    counter_id = f"intervention:{client_doc['id']}:{year}"
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,  # pymongo: ReturnDocument.AFTER (constant value 1)
    )
    # motor's find_one_and_update may return doc directly; fall back to manual fetch
    if res is None:
        res = await db.counters.find_one({"_id": counter_id})
    seq = (res or {}).get("seq", 1)
    return f"INT-{year}-{code}-{seq:04d}"


# ---- Intervention webhook ----
async def _fire_intervention_webhook(action: str, intervention_doc: dict) -> dict:
    """POST to {base_url}/{action}/{client_code}/{number}.
    Returns a result dict {enabled, fired, ok, status, url, body, error} — never raises.
    Synchronous: awaits the response so the caller can surface the real status.
    """
    result: dict = {"enabled": False, "fired": False, "ok": None, "status": None, "url": None, "body": None, "error": None}
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("webhook_enabled") or not s.get("webhook_base_url"):
            return result
        result["enabled"] = True
        client = await db.users.find_one({"id": intervention_doc.get("client_id")}, {"_id": 0})
        if not client:
            result["error"] = "Client introuvable"
            return result
        code = (client.get("client_code") or _slugify_code(client.get("company") or client.get("full_name") or "X"))
        number = intervention_doc.get("intervention_number") or "unknown"
        base = (s.get("webhook_base_url") or "").rstrip("/")
        url = f"{base}/{action}/{code}/{number}"
        result["url"] = url
        headers = {"Content-Type": "application/json", "User-Agent": "SawaliWebhook/1.0"}
        auth = None
        atype = (s.get("webhook_auth_type") or "none").lower()
        if atype == "bearer" and s.get("webhook_token"):
            headers["Authorization"] = f"Bearer {s['webhook_token']}"
        elif atype == "basic" and s.get("webhook_basic_user"):
            auth = (s.get("webhook_basic_user") or "", s.get("webhook_basic_pass") or "")
        async with httpx.AsyncClient(timeout=8.0) as http:
            r = await http.post(url, json=intervention_doc, headers=headers, auth=auth)
            result["fired"] = True
            result["status"] = r.status_code
            # Best-effort body extraction
            try:
                result["body"] = r.json()
            except Exception:
                result["body"] = (r.text or "")[:2000]
            result["ok"] = 200 <= r.status_code < 300
            logger.info("Intervention webhook %s %s -> %s", action, url, r.status_code)
    except httpx.TimeoutException:
        result["error"] = "Délai dépassé (timeout 8s)"
        logger.warning("Intervention webhook timeout")
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[:500]
        logger.warning("Intervention webhook failed: %s", exc)
    return result


async def _fire_notes_webhook(action: str, kind: str, note_doc: dict, user: dict) -> dict:
    """POST when a Rapport/Suivi is created/updated/deleted.

    URL pattern: {notes_webhook_url}/{action}/{kind_fr}/{note_id}
    where kind_fr is 'rapport' (singular French) for reports and 'suivi' for suivis.
    Returns a result dict {enabled, fired, ok, status, url, body, error}.
    """
    result: dict = {"enabled": False, "fired": False, "ok": None, "status": None, "url": None, "body": None, "error": None}
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("notes_webhook_enabled") or not s.get("notes_webhook_url"):
            return result
        result["enabled"] = True
        # Map internal plural English kind → French singular as expected by
        # downstream REST consumers: "reports" → "rapport", "suivis" → "suivi"
        kind_fr = "rapport" if kind == "reports" else ("suivi" if kind == "suivis" else kind)
        base = (s.get("notes_webhook_url") or "").rstrip("/")
        url = f"{base}/{action}/{kind_fr}/{note_doc.get('id', 'unknown')}"
        result["url"] = url
        headers = {"Content-Type": "application/json", "User-Agent": "SawaliNotesWebhook/1.0"}
        auth = None
        atype = (s.get("notes_webhook_auth_type") or "none").lower()
        if atype == "bearer" and s.get("notes_webhook_token"):
            headers["Authorization"] = f"Bearer {s['notes_webhook_token']}"
        elif atype == "basic" and s.get("notes_webhook_basic_user"):
            auth = (s.get("notes_webhook_basic_user") or "", s.get("notes_webhook_basic_pass") or "")
        body = {
            "action": action,
            "kind": kind_fr,
            "note": note_doc,
            "author": {"id": user.get("id"), "email": user.get("email"), "full_name": user.get("full_name"), "role": user.get("role")},
            "fired_at": _now(),
        }
        async with httpx.AsyncClient(timeout=8.0) as http:
            r = await http.post(url, json=body, headers=headers, auth=auth)
            result["fired"] = True
            result["status"] = r.status_code
            try:
                result["body"] = r.json()
            except Exception:
                result["body"] = (r.text or "")[:2000]
            result["ok"] = 200 <= r.status_code < 300
            logger.info("Notes webhook %s %s -> %s", action, url, r.status_code)
    except httpx.TimeoutException:
        result["error"] = "Délai dépassé (timeout 8s)"
        logger.warning("Notes webhook timeout")
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[:500]
        logger.warning("Notes webhook failed: %s", exc)
    return result


def _fire_webhook_bg(action: str, intervention_doc: dict) -> None:
    """Kept for backwards compatibility — triggers fire-and-forget without result."""
    try:
        asyncio.create_task(_fire_intervention_webhook(action, intervention_doc))
    except RuntimeError:
        pass


def _fire_notes_webhook_bg(action: str, kind: str, note_doc: dict, user: dict) -> None:
    try:
        asyncio.create_task(_fire_notes_webhook(action, kind, note_doc, user))
    except RuntimeError:
        pass


# ====================================================================
# Role-based access helpers
# ====================================================================
ELEVATED_TRACKED_ROLES = {"Moderation", "Administrateur", "Superviseur"}
ADMIN_LEVEL_TRACKED_ROLES = {"Administrateur", "Superviseur"}


def _user_tracked_role(user: dict) -> str:
    return user.get("tracked_role") or ""


def _is_admin_or_superviseur(user: dict) -> bool:
    """Hard admin (users.role admin/superviseur) — bypasses everything."""
    return user.get("role") in ("admin", "superviseur")


def _is_elevated_creator(user: dict) -> bool:
    """Can create rapports / suivis / interventions and access cross-client data."""
    if _is_admin_or_superviseur(user):
        return True
    return _user_tracked_role(user) in ELEVATED_TRACKED_ROLES


def _can_delete_records(user: dict) -> bool:
    """Can delete reports / suivis / interventions: only role admin/superviseur or tracked Admin/Superviseur."""
    if _is_admin_or_superviseur(user):
        return True
    return _user_tracked_role(user) in ADMIN_LEVEL_TRACKED_ROLES


def _can_rate(user: dict) -> bool:
    """Can post 5-star ratings on records."""
    return _can_delete_records(user)


def _can_consult_all_docs(user: dict) -> bool:
    """Moderation+ can read/upload documents of all clients (but only Admin/Superviseur can delete)."""
    return _is_elevated_creator(user)


async def _check_descent_window(action_label: str = "enregistrement") -> None:
    """Raise HTTP 403 if current time is past `descent_time + 1h`.
    `descent_time` is a HH:MM stored in settings (today's reference). If unset, no check.
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    descent = (s.get("descent_time") or "").strip()
    if not descent or ":" not in descent:
        return  # No descent set → no enforcement
    try:
        hh, mm = descent.split(":", 1)
        hh_i, mm_i = int(hh), int(mm)
    except ValueError:
        return
    now = datetime.now(timezone.utc)
    today_descent = now.replace(hour=hh_i, minute=mm_i, second=0, microsecond=0)
    cutoff = today_descent + timedelta(hours=1)
    if now > cutoff:
        raise HTTPException(
            status_code=403,
            detail=f"L'{action_label} est verrouillé : la fenêtre d'1h après l'heure de descente ({descent}) est dépassée.",
        )


async def _next_simple_number(prefix: str) -> str:
    """Generate {PREFIX}-YYYY-NNNN, sequential per kind/year."""
    year = datetime.now(timezone.utc).year
    counter_id = f"{prefix.lower()}:{year}"
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    if res is None:
        res = await db.counters.find_one({"_id": counter_id})
    seq = (res or {}).get("seq", 1)
    return f"{prefix}-{year}-{seq:04d}"


def _validate_images(images, max_count: int = 10) -> list:
    """Normalize and cap an attachment list. Each item should be {file_id, url, filename}."""
    if not images:
        return []
    if not isinstance(images, list):
        raise HTTPException(status_code=400, detail="Format des images invalide")
    if len(images) > max_count:
        raise HTTPException(status_code=400, detail=f"Maximum {max_count} images autorisées")
    cleaned = []
    for i, im in enumerate(images):
        if not isinstance(im, dict):
            raise HTTPException(status_code=400, detail=f"Image #{i + 1} mal formée")
        cleaned.append({
            "file_id": im.get("file_id"),
            "url": im.get("url"),
            "filename": im.get("filename"),
        })
    return cleaned


async def _attach_my_rating(items: list, kind: str, user_id: str) -> list:
    """Decorate each item with `my_rating` (the rating placed by the requesting user)."""
    if not items:
        return items
    ids = [it.get("id") for it in items if it.get("id")]
    cursor = db.ratings.find(
        {"kind": kind, "target_id": {"$in": ids}, "rated_by_user_id": user_id},
        {"_id": 0},
    )
    by_target = {r["target_id"]: r for r in await cursor.to_list(2000)}
    for it in items:
        rating = by_target.get(it.get("id"))
        it["my_rating"] = {"stars": rating["stars"], "comment": rating.get("comment")} if rating else None
    return items


# ---- Document category slugify ----
def _category_slug(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return s or "categorie"


# ---- Supervisor dependency (Primary client = role superviseur) ----
async def get_current_supervisor(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "superviseur":
        raise HTTPException(status_code=403, detail="Accès réservé au Superviseur")
    return user


async def get_admin_or_supervisor(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return user


# ====================================================================
# Health
# ====================================================================
@api.get("/", tags=["Santé"])
async def root():
    return {"service": "SAWALI SMART SYSTEMS API", "status": "ok", "time": _now()}


@api.get("/health", tags=["Santé"])
async def health():
    return {"status": "ok"}


# ====================================================================
# AUTH
# ====================================================================
@api.post("/auth/login", response_model=LoginResponse, tags=["Authentification"])
async def auth_login(payload: LoginRequest):
    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    if user.get("account_status") != "active":
        raise HTTPException(status_code=403, detail="Compte désactivé")

    captcha = await verify_recaptcha(payload.captcha_token)
    if not captcha["success"]:
        raise HTTPException(status_code=400, detail=f"Captcha invalide ({captcha['reason']})")

    code = generate_otp()
    session = generate_session_token()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await db.otps.insert_one(
        {
            "id": _uuid(),
            "user_id": user["id"],
            "session_token": session,
            "code": code,
            "expires_at": expires_at,
            "used": False,
            "created_at": _now(),
        }
    )
    sent = await send_otp_email(user["email"], user["full_name"], code)
    dev_otp = None if sent else code  # show only when SMTP not configured
    msg = (
        "Un code de vérification a été envoyé à votre adresse email."
        if sent
        else "SMTP non configuré : code OTP affiché en mode développement."
    )
    return LoginResponse(needs_otp=True, session_token=session, message=msg, dev_otp=dev_otp)


@api.post("/auth/verify-otp", response_model=AuthTokenResponse, tags=["Authentification"])
async def auth_verify_otp(payload: OtpVerifyRequest):
    otp = await db.otps.find_one({"session_token": payload.session_token, "used": False})
    if not otp:
        raise HTTPException(status_code=400, detail="Session invalide ou expirée")
    if datetime.fromisoformat(otp["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Code expiré")
    if otp["code"] != payload.code.strip():
        raise HTTPException(status_code=400, detail="Code incorrect")

    await db.otps.update_one({"id": otp["id"]}, {"$set": {"used": True, "used_at": _now()}})
    user = await db.users.find_one({"id": otp["user_id"]}, {"_id": 0, "password_hash": 0})
    if user is None:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    await db.users.update_one({"id": user["id"]}, {"$set": {"last_login": _now()}})
    token = create_access_token(user["id"], user["role"])
    return AuthTokenResponse(access_token=token, user=_to_user_public(user))


@api.post("/auth/resend-otp", tags=["Authentification"])
async def auth_resend_otp(session_token: str):
    otp = await db.otps.find_one({"session_token": session_token, "used": False})
    if not otp:
        raise HTTPException(status_code=400, detail="Session invalide")
    user = await db.users.find_one({"id": otp["user_id"]})
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    new_code = generate_otp()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await db.otps.update_one({"id": otp["id"]}, {"$set": {"code": new_code, "expires_at": expires}})
    sent = await send_otp_email(user["email"], user["full_name"], new_code)
    return {"sent": sent, "dev_otp": None if sent else new_code}


@api.get("/auth/me", response_model=UserPublic, tags=["Authentification"])
async def auth_me(user: dict = Depends(get_current_user)):
    return _to_user_public(user)


@api.post("/auth/change-password", tags=["Authentification"])
async def auth_change_password(
    payload: ChangePasswordRequest, user: dict = Depends(get_current_user)
):
    db_user = await db.users.find_one({"id": user["id"]})
    if not verify_password(payload.current_password, db_user["password_hash"]):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_password(payload.new_password), "updated_at": _now()}},
    )
    return {"ok": True}


@api.get("/auth/captcha-config", tags=["Authentification"])
async def auth_captcha_config():
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "enabled": bool(s.get("recaptcha_enabled") and s.get("recaptcha_site_key")),
        "site_key": s.get("recaptcha_site_key") or None,
    }


# ====================================================================
# PUBLIC - Content / Catalog / Contact / RDV
# ====================================================================
@api.get("/content", tags=["Public"])
async def list_content():
    items = await db.contents.find({}, {"_id": 0}).to_list(500)
    return items


@api.get("/content/{slug}", tags=["Public"])
async def get_content(slug: str):
    item = await db.contents.find_one({"slug": slug}, {"_id": 0})
    if item is None:
        raise HTTPException(status_code=404, detail="Contenu introuvable")
    return item


@api.get("/catalog", tags=["Public"])
async def public_catalog():
    items = await db.documents.find(
        {"category": "catalog", "is_public": True}, {"_id": 0}
    ).to_list(200)
    return items


@api.get("/public/documents", tags=["Public"])
async def public_documents():
    items = await db.documents.find({"is_public": True}, {"_id": 0}).to_list(500)
    return items


@api.get("/company-info", tags=["Public"])
async def company_info():
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "name": "SAWALI SMART SYSTEMS",
        "tagline": "Software Engineering",
        "email": s.get("company_email") or "contact@sawalismartsystems.com",
        "phone": s.get("company_phone") or "+228 00 00 00 00",
        "whatsapp": s.get("company_whatsapp") or "",
        "address": s.get("company_address") or "",
        "city": s.get("company_city") or "",
        "country": s.get("company_country") or "",
        "business_open_time": s.get("business_open_time", "09:00"),
        "business_close_time": s.get("business_close_time", "18:00"),
        "business_days": s.get("business_days", [0, 1, 2, 3, 4]),
        "slot_duration_min": s.get("slot_duration_min", 30),
        "hero_video": {
            "enabled": bool(s.get("hero_video_enabled", False)),
            "url": s.get("hero_video_url"),
            "title": s.get("hero_video_title"),
            "description": s.get("hero_video_description"),
            "autoplay": bool(s.get("hero_video_autoplay", True)),
            "loop": bool(s.get("hero_video_loop", True)),
            "muted": bool(s.get("hero_video_muted", True)),
            "poster_url": s.get("hero_video_poster_url"),
        },
        "assistant": {
            "enabled": bool(s.get("assistant_enabled", False)),
            "url": s.get("assistant_url"),
            "label": s.get("assistant_label") or "Assistant Support",
            "color": s.get("assistant_color") or "#0075E3",
        },
        "portal_features": {
            "show_reports_button": bool(s.get("show_reports_button", True)),
            "show_suivis_button": bool(s.get("show_suivis_button", True)),
        },
        "incident_banner": {
            "enabled": bool(s.get("incident_banner_enabled", False)),
            "severity": s.get("incident_banner_severity") or "warning",
            "message": s.get("incident_banner_message") or "",
            "link_url": s.get("incident_banner_link_url") or "",
            "link_label": s.get("incident_banner_link_label") or "",
            "updated_at": s.get("incident_banner_updated_at"),
        },
    }


@api.post("/contact", tags=["Public"])
async def submit_contact(payload: ContactCreate):
    doc = {
        "id": _uuid(),
        **payload.model_dump(),
        "status": "new",
        "created_at": _now(),
    }
    await db.contacts.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "id": doc["id"]}


# ----- RDV availability + booking ------
async def _check_slot_available(scheduled_at: str, duration_min: int, exclude_id: Optional[str] = None) -> tuple[bool, str]:
    """Verify the requested slot is within business hours and not taken.
    If exclude_id is provided, that appointment is excluded from the overlap check
    (used when rescheduling an existing appointment)."""
    try:
        start_dt = datetime.fromisoformat(scheduled_at)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False, "Format de date/heure invalide"

    if start_dt < datetime.now(timezone.utc):
        return False, "Le créneau est dans le passé"

    s = await db.settings.find_one({"_id": "global"}) or {}
    open_t = s.get("business_open_time", "09:00")
    close_t = s.get("business_close_time", "18:00")
    days = s.get("business_days", [0, 1, 2, 3, 4])

    if start_dt.weekday() not in days:
        return False, "Jour non ouvré"
    open_h, open_m = (int(x) for x in open_t.split(":"))
    close_h, close_m = (int(x) for x in close_t.split(":"))
    local = start_dt
    minutes_in_day = local.hour * 60 + local.minute
    open_min = open_h * 60 + open_m
    close_min = close_h * 60 + close_m
    if minutes_in_day < open_min or (minutes_in_day + duration_min) > close_min:
        return False, "Hors des heures ouvrables"

    end_dt = start_dt + timedelta(minutes=duration_min)
    # Look for overlapping non-cancelled appointments within a 24h window
    window_start = (start_dt - timedelta(days=1)).isoformat()
    window_end = (end_dt + timedelta(days=1)).isoformat()
    existing = await db.appointments.find(
        {
            "status": {"$in": ["pending", "confirmed"]},
            "scheduled_at": {"$gte": window_start, "$lte": window_end},
            **({"id": {"$ne": exclude_id}} if exclude_id else {}),
        },
        {"_id": 0, "scheduled_at": 1, "duration_min": 1},
    ).to_list(500)
    for a in existing:
        a_start = datetime.fromisoformat(a["scheduled_at"])
        if a_start.tzinfo is None:
            a_start = a_start.replace(tzinfo=timezone.utc)
        a_end = a_start + timedelta(minutes=int(a.get("duration_min", 30)))
        if a_start < end_dt and a_end > start_dt:
            return False, "Créneau déjà réservé"

    # Optional GCal busy check
    try:
        busy = await gcal.freebusy(start_dt.isoformat(), end_dt.isoformat())
        for b in busy:
            b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
            if b_start < end_dt and b_end > start_dt:
                return False, "Créneau occupé sur le calendrier Google"
    except Exception:
        pass

    return True, "ok"


@api.get("/availability", tags=["Public"])
async def availability(date: str = Query(..., description="YYYY-MM-DD")):
    """Return list of free/busy slots for a given date."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    open_t = s.get("business_open_time", "09:00")
    close_t = s.get("business_close_time", "18:00")
    days = s.get("business_days", [0, 1, 2, 3, 4])
    slot_min = int(s.get("slot_duration_min", 30))

    try:
        day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Format date invalide")
    if day.weekday() not in days:
        return {"date": date, "slots": [], "is_business_day": False}

    oh, om = (int(x) for x in open_t.split(":"))
    ch, cm = (int(x) for x in close_t.split(":"))
    start = day.replace(hour=oh, minute=om, second=0, microsecond=0)
    end = day.replace(hour=ch, minute=cm, second=0, microsecond=0)

    # Pre-load taken intervals for the requested day only
    appts = await db.appointments.find(
        {
            "status": {"$in": ["pending", "confirmed"]},
            "scheduled_at": {"$gte": start.isoformat(), "$lte": end.isoformat()},
        },
        {"_id": 0, "scheduled_at": 1, "duration_min": 1},
    ).to_list(500)
    intervals: list[tuple[datetime, datetime]] = []
    for a in appts:
        a_start = datetime.fromisoformat(a["scheduled_at"])
        if a_start.tzinfo is None:
            a_start = a_start.replace(tzinfo=timezone.utc)
        a_end = a_start + timedelta(minutes=int(a.get("duration_min", 30)))
        intervals.append((a_start, a_end))

    try:
        busy = await gcal.freebusy(start.isoformat(), end.isoformat())
        for b in busy:
            b_s = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            b_e = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
            intervals.append((b_s, b_e))
    except Exception:
        pass

    slots = []
    cur = start
    now = datetime.now(timezone.utc)
    while cur + timedelta(minutes=slot_min) <= end:
        slot_end = cur + timedelta(minutes=slot_min)
        taken = cur < now or any(s_ < slot_end and e_ > cur for s_, e_ in intervals)
        slots.append(
            {
                "start": cur.isoformat(),
                "end": slot_end.isoformat(),
                "available": not taken,
            }
        )
        cur = slot_end
    return {"date": date, "slots": slots, "is_business_day": True, "slot_duration_min": slot_min}


@api.post("/appointments/public", tags=["Public"])
async def create_public_appointment(payload: PublicAppointmentRequest):
    ok, reason = await _check_slot_available(payload.scheduled_at, payload.duration_min)
    if not ok:
        raise HTTPException(status_code=409, detail=reason)
    doc = {
        "id": _uuid(),
        "client_id": None,
        **payload.model_dump(),
        "status": "pending",
        "notes": None,
        "gcal_event_id": None,
        "created_at": _now(),
    }
    # GCal sync
    end_iso = (
        datetime.fromisoformat(payload.scheduled_at).replace(tzinfo=timezone.utc)
        + timedelta(minutes=payload.duration_min)
    ).isoformat()
    event_id = await gcal.create_event(
        summary=f"RDV (public) : {payload.subject}",
        description=f"Demandé par {payload.name} <{payload.email}>\n{payload.message or ''}",
        start_iso=payload.scheduled_at,
        end_iso=end_iso,
        attendee_email=payload.email,
    )
    doc["gcal_event_id"] = event_id
    await db.appointments.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "appointment": doc}


# ====================================================================
# CLIENT PORTAL
# ====================================================================
@api.get("/me/account", tags=["Portail Client"])
async def me_account(user: dict = Depends(get_current_user)):
    appts = await db.appointments.find({"client_id": user["id"]}, {"_id": 0}).to_list(500)
    interventions = await db.interventions.find({"client_id": user["id"]}, {"_id": 0}).to_list(500)
    docs = await db.documents.find(
        {"$or": [{"client_id": user["id"]}, {"is_public": True}]}, {"_id": 0}
    ).to_list(500)
    return {
        "user": _to_user_public(user),
        "stats": {
            "appointments": len(appts),
            "appointments_pending": sum(1 for a in appts if a["status"] == "pending"),
            "interventions": len(interventions),
            "documents": len(docs),
        },
        "recent_appointments": sorted(appts, key=lambda x: x["scheduled_at"], reverse=True)[:5],
        "recent_interventions": sorted(
            interventions, key=lambda x: x.get("intervention_date", ""), reverse=True
        )[:5],
    }


@api.get("/me/appointments", tags=["Portail Client"])
async def me_appointments(user: dict = Depends(get_current_user)):
    items = await db.appointments.find({"client_id": user["id"]}, {"_id": 0}).to_list(1000)
    return sorted(items, key=lambda x: x["scheduled_at"], reverse=True)


@api.put("/me/appointments/{appt_id}", tags=["Portail Client"])
async def me_update_appointment(
    appt_id: str, payload: AppointmentUpdate, user: dict = Depends(get_current_user),
):
    """Client may edit their own upcoming appointments (pending/confirmed)."""
    existing = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    # Access control: owner (client_id) or elevated tracked users
    owner_scope = existing.get("client_id")
    if owner_scope != (user.get("client_id") or user.get("id")) and not _is_elevated_creator(user) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès refusé")
    if (existing.get("status") or "") == "completed":
        raise HTTPException(status_code=400, detail="Un rendez-vous terminé ne peut être modifié")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Re-check slot availability if rescheduling
    if "scheduled_at" in update or "duration_min" in update:
        new_sched = update.get("scheduled_at") or existing.get("scheduled_at")
        new_dur = update.get("duration_min") or existing.get("duration_min") or 30
        ok, reason = await _check_slot_available(new_sched, new_dur, exclude_id=appt_id)
        if not ok:
            raise HTTPException(status_code=409, detail=reason)
    update["updated_at"] = _now()
    await db.appointments.update_one({"id": appt_id}, {"$set": update})
    # Sync Google Calendar if linked
    if existing.get("gcal_event_id") and ("scheduled_at" in update or "duration_min" in update or "subject" in update or "message" in update):
        try:
            new_sched = update.get("scheduled_at") or existing.get("scheduled_at")
            new_dur = update.get("duration_min") or existing.get("duration_min") or 30
            new_end = (datetime.fromisoformat(new_sched).replace(tzinfo=timezone.utc) + timedelta(minutes=new_dur)).isoformat()
            await gcal.update_event(
                event_id=existing["gcal_event_id"],
                summary=f"RDV client : {update.get('subject') or existing.get('subject')}",
                description=f"Client : {existing.get('name')} <{existing.get('email')}>\n{update.get('message') or existing.get('message') or ''}",
                start_iso=new_sched,
                end_iso=new_end,
            )
        except Exception as exc:
            logger.warning("GCal update failed: %s", exc)
    return {"ok": True}


@api.delete("/me/appointments/{appt_id}", tags=["Portail Client"])
async def me_delete_appointment(appt_id: str, user: dict = Depends(get_current_user)):
    existing = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    owner_scope = existing.get("client_id")
    if owner_scope != (user.get("client_id") or user.get("id")) and not _is_elevated_creator(user) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès refusé")
    await db.appointments.delete_one({"id": appt_id})
    if existing.get("gcal_event_id"):
        try:
            await gcal.delete_event(existing["gcal_event_id"])
        except Exception as exc:
            logger.warning("GCal delete failed: %s", exc)
    return {"ok": True}


@api.post("/me/appointments", tags=["Portail Client"])
async def me_create_appointment(
    payload: ClientAppointmentRequest, user: dict = Depends(get_current_user)
):
    ok, reason = await _check_slot_available(payload.scheduled_at, payload.duration_min)
    if not ok:
        raise HTTPException(status_code=409, detail=reason)
    doc = {
        "id": _uuid(),
        "client_id": user["id"],
        "name": user["full_name"],
        "email": user["email"],
        "phone": user.get("phone"),
        "company": user.get("company"),
        "subject": payload.subject,
        "message": payload.message,
        "scheduled_at": payload.scheduled_at,
        "duration_min": payload.duration_min,
        "status": "pending",
        "notes": None,
        "gcal_event_id": None,
        "created_at": _now(),
    }
    end_iso = (
        datetime.fromisoformat(payload.scheduled_at).replace(tzinfo=timezone.utc)
        + timedelta(minutes=payload.duration_min)
    ).isoformat()
    event_id = await gcal.create_event(
        summary=f"RDV client : {payload.subject}",
        description=f"Client : {user['full_name']} <{user['email']}>\n{payload.message or ''}",
        start_iso=payload.scheduled_at,
        end_iso=end_iso,
        attendee_email=user["email"],
    )
    doc["gcal_event_id"] = event_id
    await db.appointments.insert_one(doc.copy())
    doc.pop("_id", None)
    # Fire automation: appointment.created
    try:
        sched_human = doc["scheduled_at"]
        try:
            sched_human = datetime.fromisoformat(doc["scheduled_at"].replace("Z", "+00:00")).strftime("%d/%m/%Y à %Hh%M")
        except Exception:
            pass
        asyncio.create_task(_emit_event("appointment.created", {
            "client_id": user["id"],
            "phone": user.get("phone"),
            "extra_ctx": {
                "appointment_date": sched_human,
                "appointment_subject": doc.get("subject") or "",
            },
        }))
    except Exception:
        pass
    return doc


@api.get("/me/documents", tags=["Portail Client"])
async def me_documents(user: dict = Depends(get_current_user)):
    if _can_consult_all_docs(user):
        # Moderation/Admin/Superviseur see ALL documents
        items = await db.documents.find({}, {"_id": 0}).to_list(5000)
    else:
        # Resolve effective client id (tracked users → parent client)
        effective_client_id = user.get("parent_client_id") or user["id"]
        items = await db.documents.find(
            {"$or": [{"client_id": effective_client_id}, {"is_public": True}]}, {"_id": 0}
        ).to_list(500)
    return items


@api.get("/me/interventions", tags=["Portail Client"])
async def me_interventions(user: dict = Depends(get_current_user)):
    if _is_elevated_creator(user):
        items = await db.interventions.find({}, {"_id": 0}).to_list(2000)
    else:
        effective_client_id = user.get("parent_client_id") or user["id"]
        items = await db.interventions.find({"client_id": effective_client_id}, {"_id": 0}).to_list(1000)
    items = sorted(items, key=lambda x: x.get("intervention_date", ""), reverse=True)
    return await _attach_my_rating(items, "interventions", user["id"])


@api.get("/me/users", tags=["Portail Client"])
async def me_users(user: dict = Depends(get_current_user)):
    items = await db.tracked_users.find({"client_id": user["id"]}, {"_id": 0}).to_list(2000)
    return items


@api.get("/me/clients", tags=["Portail Client"])
async def me_clients_light(user: dict = Depends(get_current_user)):
    """Minimal client list for elevated users (used in suivis/intervention forms).
    Non-elevated users only see their own client record."""
    if _is_elevated_creator(user):
        cursor = db.users.find({"role": {"$in": ["client", "superviseur"]}}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "client_code": 1})
        items = await cursor.to_list(5000)
    else:
        effective_id = user.get("parent_client_id") or user["id"]
        u = await db.users.find_one({"id": effective_id}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "client_code": 1})
        items = [u] if u else []
    return items


# ====================================================================
# PORTAIL SUPERVISEUR (Client Primaire) — gère les comptes "Admin client"
# ====================================================================
@api.get("/me/admin-clients", tags=["Portail Client"])
async def supervisor_list_admin_clients(user: dict = Depends(get_current_supervisor)):
    """Le client Primaire (Superviseur) voit tous les autres clients ayant le rôle 'admin'.
    Note : les comptes 'admin' ici désignent des clients promus admin, pas l'admin SAWALI."""
    # Match all users with role=admin OR role=client (so superviseur can manage every account
    # except SAWALI's own super-admin marked specifically). For now we expose all role==admin
    # client-promoted accounts.
    users = await db.users.find(
        {"role": "admin", "id": {"$ne": user["id"]}},
        {"_id": 0, "password_hash": 0},
    ).to_list(2000)
    return users


@api.put("/me/admin-clients/{target_id}", tags=["Portail Client"])
async def supervisor_update_admin_client(
    target_id: str,
    payload: UserUpdateAdmin,
    user: dict = Depends(get_current_supervisor),
):
    target = await db.users.find_one({"id": target_id}, {"_id": 0})
    if not target or target.get("role") != "admin":
        raise HTTPException(status_code=404, detail="Compte admin introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None and k != "password"}
    if "client_code" in update:
        update["client_code"] = (update["client_code"] or "").strip().upper() or None
    # Superviseur cannot self-promote/demote: ignore is_primary_client/role tampering
    update.pop("is_primary_client", None)
    update.pop("role", None)
    if payload.password:
        update["password_hash"] = hash_password(payload.password)
    update["updated_at"] = _now()
    await db.users.update_one({"id": target_id}, {"$set": update})
    return {"ok": True}


# ====================================================================
# ADMIN - Clients
# ====================================================================
@api.get("/admin/clients", tags=["Admin"])
async def admin_list_clients(_: dict = Depends(get_current_admin)):
    users = await db.users.find(
        {"role": {"$in": ["client", "superviseur"]}},
        {"_id": 0, "password_hash": 0},
    ).to_list(2000)
    return users


@api.post("/admin/clients", tags=["Admin"])
async def admin_create_client(payload: UserCreateAdmin, _: dict = Depends(get_current_admin)):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Cet email est déjà utilisé")
    doc = {
        "id": _uuid(),
        "email": payload.email.lower(),
        "full_name": payload.full_name,
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "phone": payload.phone,
        "company": payload.company,
        "client_code": (payload.client_code or "").strip().upper() or None,
        "category_slug": payload.category_slug,
        "country": payload.country,
        "city": payload.city,
        "logo_url": payload.logo_url,
        "account_status": payload.account_status,
        "is_primary_client": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.users.insert_one(doc.copy())
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    # Fire automation: client.created
    try:
        asyncio.create_task(_emit_event("client.created", {
            "client_id": doc["id"],
            "phone": doc.get("phone"),
            "extra_ctx": {},
        }))
    except Exception:
        pass
    return doc


@api.get("/admin/clients/{client_id}", tags=["Admin"])
async def admin_get_client(client_id: str, _: dict = Depends(get_current_admin)):
    u = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return u


@api.get("/admin/clients/{client_id}/whatsapp-stats", tags=["Admin"])
async def admin_client_whatsapp_stats(client_id: str, _: dict = Depends(get_current_admin)):
    """WhatsApp consumption summary for a client: messages sent OK/KO,
    inbound, last activity, configured unit cost & total cost."""
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "wa_unit_cost": 1, "wa_currency": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    unit_cost = float(client.get("wa_unit_cost") or 0)
    currency = client.get("wa_currency") or "XOF"
    cur = db.whatsapp_messages.find({"client_id": client_id}, {"_id": 0})
    sent_ok = sent_ko = inbound = 0
    last_at: Optional[str] = None
    last_outbound_at: Optional[str] = None
    last_inbound_at: Optional[str] = None
    async for m in cur:
        if (m.get("direction") or "outbound") == "inbound":
            inbound += 1
            ts = m.get("received_at") or m.get("created_at")
            if ts and (not last_inbound_at or ts > last_inbound_at):
                last_inbound_at = ts
        else:
            ok = m.get("ok")
            if ok is None:
                # Legacy logs may not have ok; infer from wa_status
                ok = (m.get("wa_status") or "").lower() not in ("failed",)
            if ok:
                sent_ok += 1
            else:
                sent_ko += 1
            ts = m.get("sent_at") or m.get("created_at")
            if ts and (not last_outbound_at or ts > last_outbound_at):
                last_outbound_at = ts
        ts_any = m.get("sent_at") or m.get("received_at") or m.get("created_at")
        if ts_any and (not last_at or ts_any > last_at):
            last_at = ts_any
    billable = sent_ok  # only successful sends are billed
    total_cost = round(billable * unit_cost, 4)
    return {
        "client_id": client_id,
        "client_name": client.get("full_name"),
        "client_company": client.get("company"),
        "sent_ok": sent_ok,
        "sent_ko": sent_ko,
        "inbound": inbound,
        "billable_messages": billable,
        "unit_cost": unit_cost,
        "currency": currency,
        "total_cost": total_cost,
        "last_outbound_at": last_outbound_at,
        "last_inbound_at": last_inbound_at,
        "last_activity_at": last_at,
    }


@api.put("/admin/clients/{client_id}/whatsapp-cost", tags=["Admin"])
async def admin_set_client_wa_cost(
    client_id: str,
    payload: Dict[str, Any],
    _: dict = Depends(get_current_admin),
):
    """Update the WhatsApp unit cost (per outbound message) for a client.
    Accepts {wa_unit_cost: number, wa_currency: str}."""
    update: Dict[str, Any] = {}
    if "wa_unit_cost" in payload:
        try:
            v = float(payload.get("wa_unit_cost") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Coût invalide")
        if v < 0:
            raise HTTPException(status_code=400, detail="Le coût ne peut être négatif")
        update["wa_unit_cost"] = v
    if "wa_currency" in payload:
        cur = (payload.get("wa_currency") or "").strip().upper()[:6]
        update["wa_currency"] = cur or "XOF"
    if not update:
        return {"ok": True}
    res = await db.users.update_one({"id": client_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return {"ok": True, **update}


@api.get("/admin/clients/{client_id}/timeline", tags=["Admin"])
async def admin_client_timeline(
    client_id: str,
    limit: int = 200,
    types: Optional[str] = None,  # CSV of: appointment,intervention,whatsapp,form,document,note,task
    _: dict = Depends(get_current_admin),
):
    """Unified CRM timeline for a client — aggregates events from 7 collections.

    Each event has shape: {id, type, ts, title, summary, status?, link?, payload}
    Sorted by ts DESC. Optional `types` filter (CSV)."""
    user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Client introuvable")

    wanted = {t.strip() for t in (types or "appointment,intervention,whatsapp,form,document,note,task").split(",") if t.strip()}
    events: List[Dict[str, Any]] = []

    # 1) Appointments
    if "appointment" in wanted:
        appts = await db.appointments.find(
            {"client_id": client_id},
            {"_id": 0, "id": 1, "scheduled_at": 1, "subject": 1, "status": 1, "duration_minutes": 1, "created_at": 1},
        ).sort("scheduled_at", -1).limit(limit).to_list(limit)
        for ap in appts:
            events.append({
                "id": ap["id"],
                "type": "appointment",
                "ts": ap.get("scheduled_at") or ap.get("created_at"),
                "title": ap.get("subject") or "Rendez-vous",
                "summary": f"Statut: {ap.get('status') or 'planifié'} · Durée: {ap.get('duration_minutes') or 30} min",
                "status": ap.get("status"),
                "payload": ap,
            })

    # 2) Interventions
    if "intervention" in wanted:
        ints = await db.interventions.find(
            {"client_id": client_id},
            {"_id": 0, "id": 1, "intervention_date": 1, "intervention_number": 1, "title": 1,
             "subject": 1, "type": 1, "status": 1, "created_at": 1},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        for it in ints:
            events.append({
                "id": it["id"],
                "type": "intervention",
                "ts": it.get("intervention_date") or it.get("created_at"),
                "title": f"{it.get('intervention_number') or ''} — {it.get('subject') or it.get('title') or 'Intervention'}".strip(" —"),
                "summary": f"Type: {it.get('type') or '—'} · Statut: {it.get('status') or '—'}",
                "status": it.get("status"),
                "payload": it,
            })

    # 3) WhatsApp messages (sent + received logs already use client_id)
    if "whatsapp" in wanted:
        msgs = await db.whatsapp_messages.find(
            {"client_id": client_id},
            {"_id": 0, "id": 1, "to": 1, "template_name": 1, "ok": 1, "status": 1,
             "error": 1, "recipient_label": 1, "automation_event": 1, "bulk": 1, "created_at": 1},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        for m in msgs:
            kind_label = "Auto" if m.get("automation_event") else ("Groupé" if m.get("bulk") else "Manuel")
            events.append({
                "id": m["id"],
                "type": "whatsapp",
                "ts": m.get("created_at"),
                "title": f"WhatsApp · {m.get('template_name') or '—'}",
                "summary": f"{kind_label} · {('OK' if m.get('ok') else (m.get('error') or 'KO'))[:80]}",
                "status": "ok" if m.get("ok") else "ko",
                "payload": m,
            })

    # 4) Form submissions
    if "form" in wanted:
        subs = await db.form_submissions.find(
            {"client_id": client_id},
            {"_id": 0, "id": 1, "form_id": 1, "user_label": 1, "anonymous": 1, "respondent_email": 1, "created_at": 1},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        # Resolve form titles in batch
        form_ids = list({s.get("form_id") for s in subs if s.get("form_id")})
        forms_by_id: Dict[str, str] = {}
        if form_ids:
            f_docs = await db.forms.find(
                {"id": {"$in": form_ids}}, {"_id": 0, "id": 1, "title": 1, "number": 1}
            ).to_list(len(form_ids))
            forms_by_id = {f["id"]: f"{f.get('number') or ''} — {f.get('title') or '—'}".strip(" —") for f in f_docs}
        for s in subs:
            events.append({
                "id": s["id"],
                "type": "form",
                "ts": s.get("created_at"),
                "title": forms_by_id.get(s.get("form_id") or "") or "Soumission formulaire",
                "summary": f"Auteur: {s.get('user_label') or '—'}{' · anonyme' if s.get('anonymous') else ''}",
                "status": "submitted",
                "payload": s,
            })

    # 5) Documents (uploaded by client or shared with client)
    if "document" in wanted:
        try:
            docs = await db.documents.find(
                {"$or": [{"client_id": client_id}, {"owner_id": client_id}, {"uploaded_by": client_id}]},
                {"_id": 0, "id": 1, "name": 1, "category": 1, "size": 1, "created_at": 1, "uploaded_by_label": 1},
            ).sort("created_at", -1).limit(limit).to_list(limit)
            for d in docs:
                size_kb = round((d.get("size") or 0) / 1024)
                events.append({
                    "id": d["id"],
                    "type": "document",
                    "ts": d.get("created_at"),
                    "title": d.get("name") or "Document",
                    "summary": f"{d.get('category') or 'Document'} · {size_kb} Ko · par {d.get('uploaded_by_label') or '—'}",
                    "status": "uploaded",
                    "payload": d,
                })
        except Exception:
            pass

    # 6) Notes (free-text by admin/commercial)
    if "note" in wanted:
        notes = await db.client_notes.find(
            {"client_id": client_id},
            {"_id": 0},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        for n in notes:
            preview = (n.get("text") or "").strip()
            events.append({
                "id": n["id"],
                "type": "note",
                "ts": n.get("created_at"),
                "title": f"Note de {n.get('author_label') or 'Admin'}",
                "summary": preview[:160] + ("…" if len(preview) > 160 else ""),
                "status": "note",
                "payload": n,
            })

    # 7) Tasks (todos with optional due date + WhatsApp reminder)
    if "task" in wanted:
        tasks = await db.client_tasks.find(
            {"client_id": client_id},
            {"_id": 0},
        ).sort("due_at", -1).limit(limit).to_list(limit)
        for t in tasks:
            due = t.get("due_at")
            events.append({
                "id": t["id"],
                "type": "task",
                "ts": due or t.get("created_at"),
                "title": t.get("title") or "Tâche",
                "summary": (
                    f"Échéance: {due or 'aucune'} · "
                    f"{'Terminée' if t.get('status') == 'done' else 'À faire'}"
                    + (" · 🔔 rappel WhatsApp" if t.get("remind_via_whatsapp") else "")
                ),
                "status": "completed" if t.get("status") == "done" else "open",
                "payload": t,
            })

    # Sort DESC by ts (string ISO sorts naturally)
    events.sort(key=lambda x: (x.get("ts") or ""), reverse=True)
    events = events[:limit]

    counts = {"appointment": 0, "intervention": 0, "whatsapp": 0, "form": 0, "document": 0, "note": 0, "task": 0}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1

    return {
        "client": {
            "id": user["id"],
            "full_name": user.get("full_name"),
            "company": user.get("company"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "client_code": user.get("client_code"),
            "country": user.get("country"),
            "city": user.get("city"),
            "account_status": user.get("account_status"),
            "created_at": user.get("created_at"),
        },
        "events": events,
        "counts": counts,
        "total": len(events),
    }


# ====================================================================
# CRM — Notes & Tasks per client
# ====================================================================
class ClientNoteCreate(BaseModel):
    text: str


class ClientTaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_at: Optional[str] = None  # ISO-8601 (date or datetime)
    remind_via_whatsapp: bool = False


class ClientTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[str] = None
    status: Optional[str] = None  # 'open' | 'done'
    remind_via_whatsapp: Optional[bool] = None


async def _ensure_client_exists(client_id: str) -> dict:
    user = await db.users.find_one({"id": client_id}, {"_id": 0, "full_name": 1, "company": 1, "phone": 1, "email": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return user


# ----- Notes -----
@api.get("/admin/clients/{client_id}/notes", tags=["Admin"])
async def admin_list_notes(client_id: str, _: dict = Depends(get_current_admin)):
    await _ensure_client_exists(client_id)
    return await db.client_notes.find({"client_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.post("/admin/clients/{client_id}/notes", tags=["Admin"])
async def admin_create_note(
    client_id: str, payload: ClientNoteCreate, admin_user: dict = Depends(get_current_admin)
):
    await _ensure_client_exists(client_id)
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Le texte de la note est requis")
    if len(text) > 5000:
        raise HTTPException(status_code=400, detail="Note trop longue (5000 caractères max)")
    doc = {
        "id": _uuid(),
        "client_id": client_id,
        "text": text,
        "author_id": admin_user["id"],
        "author_label": admin_user.get("full_name") or admin_user.get("email"),
        "created_at": _now(),
    }
    await db.client_notes.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.delete("/admin/clients/{client_id}/notes/{nid}", tags=["Admin"])
async def admin_delete_note(client_id: str, nid: str, _: dict = Depends(get_current_admin)):
    res = await db.client_notes.delete_one({"id": nid, "client_id": client_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Note introuvable")
    return {"ok": True}


# ----- Tasks -----
@api.get("/admin/clients/{client_id}/tasks", tags=["Admin"])
async def admin_list_tasks(client_id: str, _: dict = Depends(get_current_admin)):
    await _ensure_client_exists(client_id)
    return await db.client_tasks.find({"client_id": client_id}, {"_id": 0}).sort("due_at", 1).to_list(500)


@api.post("/admin/clients/{client_id}/tasks", tags=["Admin"])
async def admin_create_task(
    client_id: str, payload: ClientTaskCreate, admin_user: dict = Depends(get_current_admin)
):
    await _ensure_client_exists(client_id)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre de la tâche requis")
    due_iso: Optional[str] = None
    if payload.due_at:
        try:
            d = datetime.fromisoformat(payload.due_at.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            due_iso = d.isoformat()
        except Exception:
            raise HTTPException(status_code=400, detail="Date d'échéance invalide")
    doc = {
        "id": _uuid(),
        "client_id": client_id,
        "title": title,
        "description": (payload.description or "").strip() or None,
        "due_at": due_iso,
        "status": "open",
        "remind_via_whatsapp": bool(payload.remind_via_whatsapp),
        "reminder_sent_at": None,
        "author_id": admin_user["id"],
        "author_label": admin_user.get("full_name") or admin_user.get("email"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.client_tasks.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/clients/{client_id}/tasks/{tid}", tags=["Admin"])
async def admin_update_task(
    client_id: str, tid: str, payload: ClientTaskUpdate, _: dict = Depends(get_current_admin)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "status" in update and update["status"] not in ("open", "done"):
        raise HTTPException(status_code=400, detail="Statut invalide (open|done)")
    if "due_at" in update and update["due_at"]:
        try:
            d = datetime.fromisoformat(update["due_at"].replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            update["due_at"] = d.isoformat()
        except Exception:
            raise HTTPException(status_code=400, detail="Date d'échéance invalide")
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    res = await db.client_tasks.update_one({"id": tid, "client_id": client_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    refreshed = await db.client_tasks.find_one({"id": tid, "client_id": client_id}, {"_id": 0})
    return refreshed


@api.delete("/admin/clients/{client_id}/tasks/{tid}", tags=["Admin"])
async def admin_delete_task(client_id: str, tid: str, _: dict = Depends(get_current_admin)):
    res = await db.client_tasks.delete_one({"id": tid, "client_id": client_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return {"ok": True}


async def _task_reminder_cron():
    """Hourly cron: tasks with remind_via_whatsapp=true + due in [now, now+1h] + not yet reminded.
    Emits a 'task.reminder' event so admins can hook a WhatsApp template via /admin/automations."""
    now_utc = datetime.now(timezone.utc)
    win_end = (now_utc + timedelta(hours=1)).isoformat()
    tasks = await db.client_tasks.find(
        {
            "remind_via_whatsapp": True,
            "status": "open",
            "due_at": {"$gte": now_utc.isoformat(), "$lte": win_end},
            "reminder_sent_at": None,
        },
        {"_id": 0},
    ).to_list(200)
    for t in tasks:
        try:
            await _emit_event("task.reminder", {
                "client_id": t.get("client_id"),
                "extra_ctx": {
                    "task_title": t.get("title") or "",
                    "task_due": t.get("due_at") or "",
                },
            })
        except Exception:
            pass
        try:
            await db.client_tasks.update_one(
                {"id": t["id"]},
                {"$set": {"reminder_sent_at": _now()}},
            )
        except Exception:
            pass


@api.put("/admin/clients/{client_id}", tags=["Admin"])
async def admin_update_client(
    client_id: str, payload: UserUpdateAdmin, _: dict = Depends(get_current_admin)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None and k != "password"}
    if "client_code" in update:
        update["client_code"] = (update["client_code"] or "").strip().upper() or None
    if payload.password:
        update["password_hash"] = hash_password(payload.password)
    update["updated_at"] = _now()
    await db.users.update_one({"id": client_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/clients/{client_id}", tags=["Admin"])
async def admin_delete_client(client_id: str, _: dict = Depends(get_current_admin)):
    await db.users.delete_one({"id": client_id, "role": {"$in": ["client", "superviseur"]}})
    return {"ok": True}


@api.post("/admin/clients/{client_id}/set-primary", tags=["Admin"])
async def admin_set_primary_client(client_id: str, _: dict = Depends(get_current_admin)):
    """Designate ONE client as the primary site owner.
    The primary client is automatically promoted to role=superviseur.
    Any previous primary is unmarked and demoted back to role=client (unless admin).
    """
    target = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    if target.get("role") == "admin":
        raise HTTPException(status_code=400, detail="Un compte admin SAWALI ne peut pas être désigné comme client primaire")

    # Demote previous primary(ies)
    previous_primaries = await db.users.find({"is_primary_client": True}, {"_id": 0}).to_list(50)
    for prev in previous_primaries:
        if prev["id"] == client_id:
            continue
        # Restore previous role if known, default to "client"
        new_role = "client" if prev.get("role") == "superviseur" else prev.get("role", "client")
        await db.users.update_one(
            {"id": prev["id"]},
            {"$set": {"is_primary_client": False, "role": new_role, "updated_at": _now()}},
        )

    await db.users.update_one(
        {"id": client_id},
        {"$set": {"is_primary_client": True, "role": "superviseur", "updated_at": _now()}},
    )
    return {"ok": True, "id": client_id, "role": "superviseur", "is_primary_client": True}


@api.post("/admin/clients/{client_id}/unset-primary", tags=["Admin"])
async def admin_unset_primary_client(client_id: str, _: dict = Depends(get_current_admin)):
    target = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    await db.users.update_one(
        {"id": client_id},
        {"$set": {"is_primary_client": False, "role": "client", "updated_at": _now()}},
    )
    return {"ok": True, "id": client_id}


# ====================================================================
# ADMIN - Appointments
# ====================================================================
@api.get("/admin/appointments", tags=["Admin"])
async def admin_appointments(_: dict = Depends(get_current_admin)):
    items = await db.appointments.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x["scheduled_at"], reverse=True)


@api.put("/admin/appointments/{appt_id}", tags=["Admin"])
async def admin_update_appt(
    appt_id: str, payload: AppointmentUpdate, _: dict = Depends(get_current_admin)
):
    existing = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    # Auto-generate feedback token when status becomes "completed"
    if update.get("status") == "completed":
        if not existing.get("feedback_token"):
            update["feedback_token"] = generate_session_token()
            update["feedback_status"] = "pending"
    await db.appointments.update_one({"id": appt_id}, {"$set": update})
    # Sync GCal if the slot changed
    if existing.get("gcal_event_id") and ("scheduled_at" in update or "duration_min" in update or "subject" in update or "message" in update):
        try:
            new_sched = update.get("scheduled_at") or existing.get("scheduled_at")
            new_dur = update.get("duration_min") or existing.get("duration_min") or 30
            new_end = (datetime.fromisoformat(new_sched).replace(tzinfo=timezone.utc) + timedelta(minutes=new_dur)).isoformat()
            await gcal.update_event(
                event_id=existing["gcal_event_id"],
                summary=f"RDV client : {update.get('subject') or existing.get('subject')}",
                description=f"Client : {existing.get('name')} <{existing.get('email')}>\n{update.get('message') or existing.get('message') or ''}",
                start_iso=new_sched,
                end_iso=new_end,
            )
        except Exception as exc:
            logger.warning("GCal update failed: %s", exc)
    return {"ok": True}


@api.delete("/admin/appointments/{appt_id}", tags=["Admin"])
async def admin_delete_appt(appt_id: str, _: dict = Depends(get_current_admin)):
    await db.appointments.delete_one({"id": appt_id})
    return {"ok": True}


# ====================================================================
# ADMIN - Interventions
# ====================================================================
@api.get("/admin/interventions", tags=["Admin"])
async def admin_interventions(_: dict = Depends(get_current_admin)):
    items = await db.interventions.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x.get("intervention_date", ""), reverse=True)


@api.post("/admin/interventions", tags=["Admin"])
async def admin_create_intervention(
    request: Request,
    payload: InterventionCreate,
    user: dict = Depends(get_current_admin),
):
    await _check_descent_window(action_label="enregistrement")
    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    intervention_number = await _next_intervention_number(client)
    images = _validate_images(payload.images, max_count=10)
    doc = {
        "id": _uuid(),
        **payload.model_dump(),
        "images": images,
        "intervention_number": intervention_number,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "owner_role": user.get("role"),
        "ip": _client_ip_from_request(request),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.interventions.insert_one(doc.copy())
    doc.pop("_id", None)
    webhook_result = await _fire_intervention_webhook("created", doc)
    doc["webhook_result"] = webhook_result
    # Fire automation: intervention.created (admin)
    try:
        asyncio.create_task(_emit_event("intervention.created", {
            "client_id": payload.client_id,
            "extra_ctx": {
                "intervention_number": doc.get("intervention_number") or "",
                "intervention_subject": doc.get("subject") or doc.get("title") or "",
            },
        }))
    except Exception:
        pass
    return doc


@api.put("/admin/interventions/{int_id}", tags=["Admin"])
async def admin_update_intervention(
    int_id: str, payload: InterventionUpdate, _: dict = Depends(get_current_admin)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await db.interventions.update_one({"id": int_id}, {"$set": update})
    doc = await db.interventions.find_one({"id": int_id}, {"_id": 0})
    webhook_result = None
    if doc:
        webhook_result = await _fire_intervention_webhook("updated", doc)
    return {"ok": True, "webhook_result": webhook_result}


@api.delete("/admin/interventions/{int_id}", tags=["Admin"])
async def admin_delete_intervention(int_id: str, _: dict = Depends(get_current_admin)):
    await db.interventions.delete_one({"id": int_id})
    return {"ok": True}


# ====================================================================
# ADMIN - Documents (catalog, software docs, announcements)
# ====================================================================
@api.get("/admin/documents", tags=["Admin"])
async def admin_documents(_: dict = Depends(get_current_admin)):
    items = await db.documents.find({}, {"_id": 0}).to_list(5000)
    return items


@api.post("/admin/documents", tags=["Admin"])
async def admin_create_document(payload: DocumentCreate, _: dict = Depends(get_current_admin)):
    doc = {"id": _uuid(), **payload.model_dump(), "created_at": _now()}
    await db.documents.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/documents/{doc_id}", tags=["Admin"])
async def admin_update_document(
    doc_id: str, payload: DocumentUpdate, _: dict = Depends(get_current_admin)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await db.documents.update_one({"id": doc_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/documents/{doc_id}", tags=["Admin"])
async def admin_delete_document(doc_id: str, _: dict = Depends(get_current_admin)):
    await db.documents.delete_one({"id": doc_id})
    return {"ok": True}


# ---- Document categories CRUD ----
DEFAULT_DOC_CATEGORIES = [
    {"label": "Catalogue", "slug": "catalog", "is_default": True, "icon": "BookOpen", "color": "#1E90FF"},
    {"label": "Documentation", "slug": "documentation", "is_default": True, "icon": "FileText", "color": "#0EA5E9"},
    {"label": "Annonce", "slug": "announcement", "is_default": True, "icon": "Megaphone", "color": "#F59E0B"},
]


async def _ensure_default_categories():
    for c in DEFAULT_DOC_CATEGORIES:
        existing = await db.document_categories.find_one({"slug": c["slug"]})
        if not existing:
            await db.document_categories.insert_one({
                "id": _uuid(),
                "label": c["label"],
                "slug": c["slug"],
                "description": None,
                "icon": c.get("icon"),
                "color": c.get("color"),
                "is_default": True,
                "created_at": _now(),
                "updated_at": _now(),
            })
        elif not existing.get("icon"):
            await db.document_categories.update_one(
                {"slug": c["slug"]},
                {"$set": {"icon": c.get("icon"), "color": c.get("color"), "updated_at": _now()}},
            )


@api.get("/admin/document-categories", tags=["Admin"])
async def admin_list_doc_categories(_: dict = Depends(get_current_admin)):
    await _ensure_default_categories()
    items = await db.document_categories.find({}, {"_id": 0}).sort("label", 1).to_list(500)
    return items


@api.post("/admin/document-categories", tags=["Admin"])
async def admin_create_doc_category(payload: DocumentCategoryCreate, _: dict = Depends(get_current_admin)):
    label = (payload.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Libellé requis")
    slug = (payload.slug or _category_slug(label)).strip().lower()
    if await db.document_categories.find_one({"slug": slug}):
        raise HTTPException(status_code=409, detail="Slug déjà utilisé")
    doc = {
        "id": _uuid(),
        "label": label,
        "slug": slug,
        "description": payload.description,
        "icon": payload.icon,
        "color": payload.color,
        "is_default": bool(payload.is_default),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.document_categories.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/document-categories/{cat_id}", tags=["Admin"])
async def admin_update_doc_category(cat_id: str, payload: DocumentCategoryUpdate, _: dict = Depends(get_current_admin)):
    existing = await db.document_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "slug" in update:
        update["slug"] = update["slug"].strip().lower()
        if update["slug"] != existing["slug"]:
            dup = await db.document_categories.find_one({"slug": update["slug"]})
            if dup:
                raise HTTPException(status_code=409, detail="Slug déjà utilisé")
            # propagate slug renaming on existing documents
            await db.documents.update_many(
                {"category": existing["slug"]},
                {"$set": {"category": update["slug"], "updated_at": _now()}},
            )
    update["updated_at"] = _now()
    await db.document_categories.update_one({"id": cat_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/document-categories/{cat_id}", tags=["Admin"])
async def admin_delete_doc_category(cat_id: str, _: dict = Depends(get_current_admin)):
    existing = await db.document_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        return {"ok": True}
    if existing.get("is_default"):
        raise HTTPException(status_code=400, detail="Impossible de supprimer une catégorie par défaut")
    used = await db.documents.count_documents({"category": existing["slug"]})
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"Catégorie utilisée par {used} document(s). Réaffectez-les avant suppression.",
        )
    await db.document_categories.delete_one({"id": cat_id})
    return {"ok": True}


# ---- Public list of categories (for client portal & public site) ----
@api.get("/document-categories", tags=["Public"])
async def public_doc_categories():
    await _ensure_default_categories()
    items = await db.document_categories.find({}, {"_id": 0}).sort("label", 1).to_list(500)
    return items


# ====================================================================
# CLIENT CATEGORIES (clinique, pharmacie, commerce, etc.)
# ====================================================================
DEFAULT_CLIENT_CATEGORIES = [
    {"label": "Clinique", "slug": "clinique", "icon": "Cross", "color": "#EF4444"},
    {"label": "Pharmacie", "slug": "pharmacie", "icon": "Pill", "color": "#10B981"},
    {"label": "Commerce", "slug": "commerce", "icon": "Store", "color": "#3B82F6"},
    {"label": "Alimentation", "slug": "alimentation", "icon": "UtensilsCrossed", "color": "#F59E0B"},
    {"label": "Industrie", "slug": "industrie", "icon": "Factory", "color": "#6B7280"},
    {"label": "Éducation", "slug": "education", "icon": "GraduationCap", "color": "#8B5CF6"},
    {"label": "Bureautique", "slug": "bureautique", "icon": "Briefcase", "color": "#0EA5E9"},
    {"label": "Autre", "slug": "autre", "icon": "Building2", "color": "#94A3B8"},
]


async def _ensure_default_client_categories():
    for c in DEFAULT_CLIENT_CATEGORIES:
        existing = await db.client_categories.find_one({"slug": c["slug"]})
        if not existing:
            await db.client_categories.insert_one({
                "id": _uuid(),
                "label": c["label"],
                "slug": c["slug"],
                "icon": c["icon"],
                "color": c["color"],
                "is_default": True,
                "created_at": _now(),
                "updated_at": _now(),
            })


@api.get("/admin/client-categories", tags=["Admin"])
async def admin_list_client_categories(_: dict = Depends(get_current_admin)):
    await _ensure_default_client_categories()
    items = await db.client_categories.find({}, {"_id": 0}).sort("label", 1).to_list(500)
    return items


@api.post("/admin/client-categories", tags=["Admin"])
async def admin_create_client_category(payload: ClientCategoryCreate, _: dict = Depends(get_current_admin)):
    label = (payload.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Libellé requis")
    slug = (payload.slug or _category_slug(label)).strip().lower()
    if await db.client_categories.find_one({"slug": slug}):
        raise HTTPException(status_code=409, detail="Slug déjà utilisé")
    doc = {
        "id": _uuid(),
        "label": label,
        "slug": slug,
        "icon": payload.icon,
        "color": payload.color,
        "is_default": bool(payload.is_default),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.client_categories.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/client-categories/{cat_id}", tags=["Admin"])
async def admin_update_client_category(cat_id: str, payload: ClientCategoryUpdate, _: dict = Depends(get_current_admin)):
    existing = await db.client_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "slug" in update:
        update["slug"] = update["slug"].strip().lower()
        if update["slug"] != existing["slug"]:
            dup = await db.client_categories.find_one({"slug": update["slug"]})
            if dup:
                raise HTTPException(status_code=409, detail="Slug déjà utilisé")
            await db.users.update_many(
                {"category_slug": existing["slug"]},
                {"$set": {"category_slug": update["slug"], "updated_at": _now()}},
            )
    update["updated_at"] = _now()
    await db.client_categories.update_one({"id": cat_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/client-categories/{cat_id}", tags=["Admin"])
async def admin_delete_client_category(cat_id: str, _: dict = Depends(get_current_admin)):
    existing = await db.client_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        return {"ok": True}
    if existing.get("is_default"):
        raise HTTPException(status_code=400, detail="Impossible de supprimer une catégorie par défaut")
    used = await db.users.count_documents({"category_slug": existing["slug"]})
    if used:
        raise HTTPException(status_code=400, detail=f"Catégorie utilisée par {used} client(s).")
    await db.client_categories.delete_one({"id": cat_id})
    return {"ok": True}


@api.get("/client-categories", tags=["Public"])
async def public_client_categories():
    await _ensure_default_client_categories()
    items = await db.client_categories.find({}, {"_id": 0}).sort("label", 1).to_list(500)
    return items


# ====================================================================
# DEPLOYMENTS — software installations by country/city
# Composite key: (solution_name lower, country lower)
# ====================================================================
def _deployment_key(solution: str, country: str) -> str:
    return f"{(solution or '').strip().lower()}|{(country or '').strip().lower()}"


@api.get("/admin/deployments", tags=["Admin"])
async def admin_list_deployments(_: dict = Depends(get_current_admin)):
    items = await db.deployments.find({}, {"_id": 0}).sort([("country", 1), ("solution_name", 1)]).to_list(2000)
    return items


@api.post("/admin/deployments", tags=["Admin"])
async def admin_create_deployment(payload: DeploymentCreate, _: dict = Depends(get_current_admin)):
    if not payload.solution_name.strip() or not payload.country.strip():
        raise HTTPException(status_code=400, detail="Solution et pays requis")
    key = _deployment_key(payload.solution_name, payload.country)
    if await db.deployments.find_one({"key": key}):
        raise HTTPException(status_code=409, detail="Cette solution existe déjà pour ce pays — modifiez l'entrée existante")
    doc = {
        "id": _uuid(),
        "key": key,
        "solution_name": payload.solution_name.strip(),
        "country": payload.country.strip(),
        "city": (payload.city or "").strip() or None,
        "installations": max(0, int(payload.installations or 0)),
        "notes": payload.notes,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.deployments.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/deployments/{dep_id}", tags=["Admin"])
async def admin_update_deployment(dep_id: str, payload: DeploymentUpdate, _: dict = Depends(get_current_admin)):
    existing = await db.deployments.find_one({"id": dep_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Déploiement introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "solution_name" in update or "country" in update:
        new_solution = update.get("solution_name", existing["solution_name"])
        new_country = update.get("country", existing["country"])
        new_key = _deployment_key(new_solution, new_country)
        if new_key != existing.get("key"):
            dup = await db.deployments.find_one({"key": new_key})
            if dup and dup.get("id") != dep_id:
                raise HTTPException(status_code=409, detail="Couple (solution, pays) déjà existant")
            update["key"] = new_key
    if "installations" in update:
        update["installations"] = max(0, int(update["installations"]))
    update["updated_at"] = _now()
    await db.deployments.update_one({"id": dep_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/deployments/{dep_id}", tags=["Admin"])
async def admin_delete_deployment(dep_id: str, _: dict = Depends(get_current_admin)):
    await db.deployments.delete_one({"id": dep_id})
    return {"ok": True}


@api.get("/deployments", tags=["Public"])
async def public_deployments():
    """Public list, grouped by country, with all solutions and total installations.
    Returns: [{country, total_installations, solutions: [{name, installations, city, created_at, updated_at}]}]
    """
    items = await db.deployments.find({}, {"_id": 0}).to_list(2000)
    grouped: dict = {}
    for d in items:
        c = (d.get("country") or "").strip()
        if not c:
            continue
        if c not in grouped:
            grouped[c] = {"country": c, "total_installations": 0, "solutions": []}
        grouped[c]["solutions"].append({
            "name": d.get("solution_name"),
            "installations": int(d.get("installations") or 0),
            "city": d.get("city"),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
        })
        grouped[c]["total_installations"] += int(d.get("installations") or 0)
    out = list(grouped.values())
    out.sort(key=lambda x: x["total_installations"], reverse=True)
    return out


# ====================================================================
# ADMIN - File upload
# ====================================================================
@api.post("/admin/upload", tags=["Admin"])
async def admin_upload(request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_admin)):
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    target = UPLOAD_DIR / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    size = target.stat().st_size
    file_doc = {
        "id": file_id,
        "filename": file.filename,
        "stored_name": safe_name,
        "extension": suffix.lstrip(".") if suffix else None,
        "content_type": file.content_type or mimetypes.guess_type(file.filename or "")[0],
        "size": size,
        "url": f"/api/files/{file_id}",
        "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"),
        "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
    }
    await db.files.insert_one(file_doc.copy())
    # Mirror into document_logs for centralized auditing
    await db.document_logs.insert_one({
        "id": _uuid(),
        "event_type": "upload",
        "file_id": file_id,
        "filename": file.filename,
        "extension": file_doc.get("extension"),
        "size": size,
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "ip": file_doc["uploaded_from_ip"],
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
    })
    file_doc.pop("_id", None)
    return file_doc


# ====================================================================
# POLICIES — public legal documents (RGPD, services, suppression)
# Stored as files in POLICIES_DIR with a fixed slot name + metadata in DB.
# Public URL: /api/public/policies/{slot} (PDF inline) — shareable to Google,
# Facebook, partners, etc., without authentication.
# ====================================================================
POLICY_SLOTS = {
    "privacy": "Politique de confidentialité (RGPD)",
    "services": "Politique de services",
    "deletion": "Politique de suppression",
}
POLICY_MAX_SIZE = 15 * 1024 * 1024  # 15 MB


def _policy_public_url(request: Request, slot: str) -> str:
    base = _public_base_url(request) or (PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        scheme = request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        base = f"{scheme}://{host}"
    return f"{base}/api/public/policies/{slot}"


def _policy_path(slot: str) -> Path:
    return POLICIES_DIR / f"{slot}.pdf"


@api.get("/admin/policies", tags=["Admin"])
async def admin_list_policies(request: Request, _: dict = Depends(get_current_admin)):
    """Return the 3 fixed policy slots with metadata + public share URL."""
    items = []
    for slot, label in POLICY_SLOTS.items():
        meta = await db.policies.find_one({"slot": slot}, {"_id": 0})
        present = _policy_path(slot).exists()
        items.append({
            "slot": slot,
            "label": label,
            "present": present and bool(meta),
            "filename": (meta or {}).get("filename") if present else None,
            "size": (meta or {}).get("size") if present else None,
            "uploaded_at": (meta or {}).get("uploaded_at") if present else None,
            "uploaded_by_label": (meta or {}).get("uploaded_by_label") if present else None,
            "public_url": _policy_public_url(request, slot),
        })
    return {"items": items}


@api.post("/admin/policies/{slot}/upload", tags=["Admin"])
async def admin_upload_policy(
    slot: str,
    request: Request,
    file: UploadFile = File(...),
    admin_user: dict = Depends(get_current_admin),
):
    if slot not in POLICY_SLOTS:
        raise HTTPException(status_code=400, detail=f"Slot invalide. Valeurs : {sorted(POLICY_SLOTS)}")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pdf" and (file.content_type or "") != "application/pdf":
        raise HTTPException(status_code=400, detail="Format invalide : PDF requis")
    target = _policy_path(slot)
    tmp = target.with_suffix(".pdf.tmp")
    size = 0
    with tmp.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 64)
            if not chunk:
                break
            size += len(chunk)
            if size > POLICY_MAX_SIZE:
                tmp.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {POLICY_MAX_SIZE // (1024*1024)} Mo)")
            f.write(chunk)
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Fichier vide")
    tmp.replace(target)
    doc = {
        "slot": slot,
        "label": POLICY_SLOTS[slot],
        "filename": file.filename or f"{slot}.pdf",
        "size": size,
        "uploaded_at": _now(),
        "uploaded_by_id": admin_user["id"],
        "uploaded_by_label": admin_user.get("full_name") or admin_user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
    }
    await db.policies.update_one({"slot": slot}, {"$set": doc}, upsert=True)
    return {
        "ok": True,
        **doc,
        "present": True,
        "public_url": _policy_public_url(request, slot),
    }


@api.delete("/admin/policies/{slot}", tags=["Admin"])
async def admin_delete_policy(slot: str, _: dict = Depends(get_current_admin)):
    if slot not in POLICY_SLOTS:
        raise HTTPException(status_code=400, detail=f"Slot invalide. Valeurs : {sorted(POLICY_SLOTS)}")
    p = _policy_path(slot)
    if p.exists():
        p.unlink()
    await db.policies.delete_one({"slot": slot})
    return {"ok": True, "slot": slot}


@api.get("/public/policies/{slot}", tags=["Public"])
async def public_policy(slot: str):
    """Serve a policy PDF inline so 3rd parties (Google, Facebook…) can verify it."""
    if slot not in POLICY_SLOTS:
        raise HTTPException(status_code=404, detail="Politique introuvable")
    p = _policy_path(slot)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Politique non publiée")
    meta = await db.policies.find_one({"slot": slot}, {"_id": 0})
    download_name = (meta or {}).get("filename") or f"{slot}.pdf"
    return FileResponse(
        path=str(p),
        media_type="application/pdf",
        filename=download_name,
        headers={
            "Content-Disposition": f'inline; filename="{download_name}"',
            "Cache-Control": "public, max-age=3600",
            "X-Robots-Tag": "all",
        },
    )


@api.api_route("/files/{file_id}", methods=["GET", "HEAD"], tags=["Public"])
async def serve_file(request: Request, file_id: str):
    # Allow the URL to embed an extension hint (e.g. /api/files/abc-123.pdf) so external
    # consumers like Meta's WhatsApp Cloud API accept the link as a "valid document URL".
    # Also support HEAD requests because Meta probes the URL with HEAD before fetching.
    raw_id = file_id
    bare_id = file_id.split(".", 1)[0] if "." in file_id else file_id
    meta = await db.files.find_one({"id": bare_id}, {"_id": 0}) or await db.files.find_one({"id": raw_id}, {"_id": 0})
    if not meta:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    path = UPLOAD_DIR / meta["stored_name"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    # Try to identify the downloader via Authorization header (silent, optional)
    user_id = None
    user_email = None
    auth_header = request.headers.get("authorization") or ""
    if auth_header.startswith("Bearer "):
        try:
            from auth import decode_token  # local import to avoid cycle if any
            token_data = decode_token(auth_header.split(" ", 1)[1])
            if token_data and token_data.get("sub"):
                u = await db.users.find_one({"id": token_data["sub"]}, {"_id": 0, "password_hash": 0})
                if u:
                    user_id = u["id"]
                    user_email = u["email"]
        except Exception:  # noqa: BLE001
            pass
    started = datetime.now(timezone.utc)
    started_ts = started.timestamp()
    # HEAD probes (e.g. Meta validating the URL): return headers without body / log
    if request.method == "HEAD":
        return Response(
            status_code=200,
            headers={
                "Content-Type": meta.get("content_type") or "application/octet-stream",
                "Content-Length": str(meta.get("size") or path.stat().st_size),
                "Accept-Ranges": "bytes",
            },
        )
    response = FileResponse(
        path,
        media_type=meta.get("content_type") or "application/octet-stream",
        filename=meta.get("filename"),
    )
    # Fire-and-forget log of the download (duration is approximate as we log before streaming)
    async def _log_download():
        try:
            await db.document_logs.insert_one({
                "id": _uuid(),
                "event_type": "download",
                "file_id": file_id,
                "filename": meta.get("filename"),
                "extension": meta.get("extension"),
                "size": meta.get("size"),
                "user_id": user_id,
                "user_email": user_email,
                "ip": _client_ip_from_request(request),
                "user_agent": request.headers.get("user-agent"),
                "duration_ms": int((datetime.now(timezone.utc).timestamp() - started_ts) * 1000),
                "created_at": _now(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("download log failed: %s", exc)
    asyncio.create_task(_log_download())
    return response


@api.get("/admin/document-logs", tags=["Admin"])
async def admin_document_logs(file_id: Optional[str] = None, _: dict = Depends(get_current_admin)):
    """Returns combined upload + download history. Admin only."""
    query = {}
    if file_id:
        query["file_id"] = file_id
    items = await db.document_logs.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return items


# ============================================================
# Media library (shared per-client bank for WhatsApp templates)
# ============================================================
@api.get("/me/media-library", tags=["Portail Client"])
async def me_media_library(user: dict = Depends(get_current_user)):
    """All media items uploaded by users of the same client. Shared bank."""
    client_scope = user.get("client_id") or user.get("id")
    items = await db.media_library.find({"client_id": client_scope}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


@api.post("/me/media-library", tags=["Portail Client"])
async def me_media_library_create(
    request: Request,
    file: UploadFile = File(...),
    label: str = Form(""),
    user: dict = Depends(get_current_user),
):
    """Upload + register a media in the shared client library, returns a stable public URL
    (with the file extension, accepted by Meta WhatsApp Cloud API as a header media)."""
    if not (_is_tracked_user(user) or _is_elevated_creator(user) or user.get("role") in ("client", "admin")):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    target = UPLOAD_DIR / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    size = target.stat().st_size
    ext = (suffix.lstrip(".") or "").lower()
    public_path = f"/api/files/{file_id}{('.' + ext) if ext else ''}"
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    kind = "image" if content_type.startswith("image") else ("video" if content_type.startswith("video") else "document")
    public_url = f"{(_public_base_url(request) or str(request.base_url).rstrip('/'))}{public_path}"
    # Register in the regular files collection (so /api/files/{id} can serve it)
    file_doc = {
        "id": file_id, "filename": file.filename, "stored_name": safe_name,
        "extension": ext, "content_type": content_type, "size": size,
        "url": public_path, "public_url": public_url, "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"), "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
    }
    await db.files.insert_one(file_doc)
    # Register in the shared client library
    media = {
        "id": _uuid(),
        "file_id": file_id,
        "client_id": user.get("client_id") or user.get("id"),
        "uploaded_by_id": user.get("id"),
        "uploaded_by_label": user.get("full_name") or user.get("email"),
        "label": (label or file.filename or "")[:200],
        "filename": file.filename,
        "kind": kind,
        "content_type": content_type,
        "extension": ext,
        "size": size,
        "public_url": public_url,
        "created_at": _now(),
    }
    await db.media_library.insert_one(media.copy())
    media.pop("_id", None)
    return media


@api.delete("/me/media-library/{media_id}", tags=["Portail Client"])
async def me_media_library_delete(media_id: str, user: dict = Depends(get_current_user)):
    client_scope = user.get("client_id") or user.get("id")
    media = await db.media_library.find_one({"id": media_id, "client_id": client_scope}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Média introuvable")
    await db.media_library.delete_one({"id": media_id})
    # Best-effort: keep the underlying file in case other places reference it
    return {"ok": True}


@api.get("/me/clients-roster", tags=["Portail Client"])
async def me_clients_roster(user: dict = Depends(get_current_user)):
    """Returns a public-safe roster of clients used to populate the company dropdown
    when editing a contact. Includes id, full_name, company, and client_code (ACME)."""
    items = await db.users.find(
        {"role": {"$in": ["client", "superviseur", "admin"]}},
        {"_id": 0, "id": 1, "full_name": 1, "company": 1, "client_code": 1, "is_primary_client": 1},
    ).to_list(500)
    return [i for i in items if i.get("client_code") or i.get("company")]


# ============================================================
# Platform version / build info
# ============================================================
_BUILD_TIME_ISO = datetime.now(timezone.utc).isoformat()
_BUILD_VERSION = os.environ.get("APP_VERSION") or "1.0"


@api.get("/version", tags=["Public"])
async def get_version():
    """Returns the running build's version + last-restart time."""
    return {"version": _BUILD_VERSION, "started_at": _BUILD_TIME_ISO}


# ====================================================================
# ADMIN - Content (CMS)
# ====================================================================
@api.put("/admin/content/{slug}", tags=["Admin"])
async def admin_upsert_content(slug: str, payload: ContentUpsert, _: dict = Depends(get_current_admin)):
    doc = {**payload.model_dump(), "slug": slug, "updated_at": _now()}
    existing = await db.contents.find_one({"slug": slug})
    if existing:
        await db.contents.update_one({"slug": slug}, {"$set": doc})
    else:
        doc["id"] = _uuid()
        doc["created_at"] = _now()
        await db.contents.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.delete("/admin/content/{slug}", tags=["Admin"])
async def admin_delete_content(slug: str, _: dict = Depends(get_current_admin)):
    await db.contents.delete_one({"slug": slug})
    return {"ok": True}


# ====================================================================
# ADMIN - Tracked users (sub-users of clients)
# ====================================================================
@api.get("/admin/tracked-users", tags=["Admin"])
async def admin_tracked(client_id: Optional[str] = None, _: dict = Depends(get_current_admin)):
    q = {"client_id": client_id} if client_id else {}
    items = await db.tracked_users.find(q, {"_id": 0}).to_list(5000)
    return items


@api.post("/admin/tracked-users", tags=["Admin"])
async def admin_create_tracked(payload: TrackedUserCreate, _: dict = Depends(get_current_admin)):
    if payload.role and payload.role not in TRACKED_USER_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {', '.join(TRACKED_USER_ROLES)}")
    if payload.email and not is_valid_email_syntax(str(payload.email)):
        raise HTTPException(status_code=400, detail="Email invalide (syntaxe)")
    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    doc = {"id": _uuid(), **payload.model_dump(), "created_at": _now(), "updated_at": _now()}
    await db.tracked_users.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/tracked-users/{tu_id}", tags=["Admin"])
async def admin_update_tracked(tu_id: str, payload: TrackedUserUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "role" in update and update["role"] not in TRACKED_USER_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {', '.join(TRACKED_USER_ROLES)}")
    if "email" in update and update["email"] and not is_valid_email_syntax(str(update["email"])):
        raise HTTPException(status_code=400, detail="Email invalide (syntaxe)")
    update["updated_at"] = _now()
    await db.tracked_users.update_one({"id": tu_id}, {"$set": update})
    # Propagate role/name/email/status changes to the bridged users row, if any
    tu_doc = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    if tu_doc and tu_doc.get("user_account_id"):
        bridge_update = {"updated_at": _now()}
        if "role" in update:
            bridge_update["tracked_role"] = update["role"]
        if "name" in update and update["name"]:
            bridge_update["full_name"] = update["name"]
        if "email" in update and update["email"]:
            bridge_update["email"] = str(update["email"]).lower()
        if "status" in update and update["status"]:
            bridge_update["account_status"] = "active" if update["status"] == "active" else "inactive"
        await db.users.update_one({"id": tu_doc["user_account_id"]}, {"$set": bridge_update})
    return {"ok": True}


@api.delete("/admin/tracked-users/{tu_id}", tags=["Admin"])
async def admin_delete_tracked(tu_id: str, _: dict = Depends(get_current_admin)):
    tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    await db.tracked_users.delete_one({"id": tu_id})
    # Also remove the bridged users row (if any) so the email can no longer log in
    if tu and tu.get("user_account_id"):
        await db.users.delete_one({"id": tu["user_account_id"]})
    return {"ok": True}


@api.post("/admin/tracked-users/{tu_id}/set-password", tags=["Admin"])
async def admin_set_tracked_password(
    tu_id: str,
    payload: TrackedUserSetPassword,
    _: dict = Depends(get_current_admin),
):
    """Provision (or reset) a login for a tracked user.

    Creates/updates a row in `users` (role=client, account_status=active) bridged via
    `tracked_user_id`. The tracked user can then log in with their email + this password
    through the standard /auth/login → OTP flow.
    """
    if not payload.password or len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 8 caractères)")
    tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    if not tu:
        raise HTTPException(status_code=404, detail="Utilisateur suivi introuvable")
    email = (tu.get("email") or "").strip().lower()
    if not email or not is_valid_email_syntax(email):
        raise HTTPException(status_code=400, detail="L'utilisateur suivi doit avoir un email valide pour se connecter")

    # Make sure email is not already used by another (non-bridged) account
    other = await db.users.find_one({"email": email}, {"_id": 0})
    if other and other.get("tracked_user_id") and other.get("tracked_user_id") != tu_id:
        raise HTTPException(status_code=409, detail="Email déjà associé à un autre utilisateur suivi")
    if other and not other.get("tracked_user_id"):
        raise HTTPException(status_code=409, detail="Email déjà utilisé par un compte client/admin existant")

    # Resolve parent client to inherit company/logo
    parent = await db.users.find_one({"id": tu.get("client_id")}, {"_id": 0}) or {}
    pwd_hash = hash_password(payload.password)

    if other:
        # Update existing bridged users row
        await db.users.update_one(
            {"id": other["id"]},
            {"$set": {
                "password_hash": pwd_hash,
                "full_name": tu.get("name") or other.get("full_name"),
                "phone": tu.get("phone") or other.get("phone"),
                "company": parent.get("company") or other.get("company"),
                "logo_url": parent.get("logo_url"),
                "tracked_user_id": tu_id,
                "tracked_role": tu.get("role"),
                "parent_client_id": tu.get("client_id"),
                "account_status": "active",
                "updated_at": _now(),
            }},
        )
        user_id = other["id"]
    else:
        user_id = _uuid()
        await db.users.insert_one({
            "id": user_id,
            "email": email,
            "password_hash": pwd_hash,
            "full_name": tu.get("name") or email.split("@")[0],
            "role": "client",
            "phone": tu.get("phone"),
            "company": parent.get("company"),
            "logo_url": parent.get("logo_url"),
            "account_status": "active",
            "tracked_user_id": tu_id,
            "tracked_role": tu.get("role"),
            "parent_client_id": tu.get("client_id"),
            "created_at": _now(),
            "updated_at": _now(),
        })

    await db.tracked_users.update_one(
        {"id": tu_id},
        {"$set": {
            "user_account_id": user_id,
            "has_password": True,
            "updated_at": _now(),
        }},
    )
    return {"ok": True, "user_id": user_id, "email": email}


@api.post("/admin/tracked-users/{tu_id}/revoke-password", tags=["Admin"])
async def admin_revoke_tracked_password(tu_id: str, _: dict = Depends(get_current_admin)):
    tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    if not tu:
        raise HTTPException(status_code=404, detail="Utilisateur suivi introuvable")
    if tu.get("user_account_id"):
        await db.users.delete_one({"id": tu["user_account_id"]})
    await db.tracked_users.update_one(
        {"id": tu_id},
        {"$set": {"user_account_id": None, "has_password": False, "updated_at": _now()}},
    )
    return {"ok": True}


# ====================================================================
# ADMIN - Contacts inbox
# ====================================================================
@api.get("/admin/contacts", tags=["Admin"])
async def admin_contacts(_: dict = Depends(get_current_admin)):
    items = await db.contacts.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


@api.post("/admin/contacts/{contact_id}/save-as-tracked-user", tags=["Admin"])
async def admin_save_contact_as_tracked(
    contact_id: str,
    payload: SaveContactAsTrackedUser,
    _: dict = Depends(get_current_admin),
):
    contact = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Message introuvable")

    email = (contact.get("email") or "").strip()
    if not is_valid_email_syntax(email):
        raise HTTPException(status_code=400, detail="Email du message invalide (syntaxe)")

    if payload.role not in TRACKED_USER_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {', '.join(TRACKED_USER_ROLES)}")

    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    # Avoid duplicate (same email + same client)
    existing = await db.tracked_users.find_one(
        {"email": email, "client_id": payload.client_id}, {"_id": 0}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Cet utilisateur est déjà enregistré pour ce client")

    doc = {
        "id": _uuid(),
        "client_id": payload.client_id,
        "name": contact.get("name") or email,
        "email": email,
        "role": payload.role,
        "department": payload.department,
        "phone": contact.get("phone"),
        "company": contact.get("company"),
        "status": "active",
        "source_contact_id": contact_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.tracked_users.insert_one(doc.copy())
    await db.contacts.update_one(
        {"id": contact_id},
        {"$set": {"saved_as_tracked_user_id": doc["id"], "updated_at": _now()}},
    )
    doc.pop("_id", None)
    return doc


@api.get("/admin/meta/tracked-roles", tags=["Admin"])
async def admin_tracked_roles(_: dict = Depends(get_current_admin)):
    return {"roles": TRACKED_USER_ROLES}


# ====================================================================
# IP BLACKLIST (admin)
# ====================================================================
@api.get("/admin/blacklisted-ips", tags=["Admin"])
async def admin_list_blacklist(_: dict = Depends(get_current_admin)):
    items = await db.blacklisted_ips.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)


@api.post("/admin/blacklisted-ips", tags=["Admin"])
async def admin_add_blacklist(payload: BlacklistedIPCreate, _: dict = Depends(get_current_admin)):
    cidr = (payload.cidr or "").strip()
    if not cidr:
        raise HTTPException(status_code=400, detail="IP/CIDR requis")
    try:
        ipaddress.ip_network(cidr if "/" in cidr else (f"{cidr}/32" if "." in cidr else f"{cidr}/128"), strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"IP/CIDR invalide : {exc}") from exc
    existing = await db.blacklisted_ips.find_one({"cidr": cidr})
    if existing:
        raise HTTPException(status_code=409, detail="Cette entrée existe déjà")
    doc = {
        "id": _uuid(),
        "cidr": cidr,
        "reason": payload.reason,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.blacklisted_ips.insert_one(doc.copy())
    await _reload_blacklist()
    doc.pop("_id", None)
    return doc


@api.delete("/admin/blacklisted-ips/{ip_id}", tags=["Admin"])
async def admin_delete_blacklist(ip_id: str, _: dict = Depends(get_current_admin)):
    await db.blacklisted_ips.delete_one({"id": ip_id})
    await _reload_blacklist()
    return {"ok": True}


# ====================================================================
# PORTAL BRANDING — logo per client (used in sidebar)
# ====================================================================
@api.get("/me/branding", tags=["Portail Client"])
async def me_branding(user: dict = Depends(get_current_user)):
    """Return branding to display in the connected portal sidebar.
    Tracked-users inherit from their client_id; clients/superviseurs use their own logo."""
    logo_url = None
    company = user.get("company")
    if user.get("logo_url"):
        logo_url = user["logo_url"]
    else:
        # Tracked users have no logo; look up parent client by tracked_users.client_id
        tu = await db.tracked_users.find_one({"email": user.get("email")}, {"_id": 0})
        if tu and tu.get("client_id"):
            parent = await db.users.find_one({"id": tu["client_id"]}, {"_id": 0})
            if parent:
                logo_url = parent.get("logo_url")
                company = parent.get("company") or company
    return {"logo_url": logo_url, "company": company}


# ====================================================================
# USER NOTES — Rapports & Suivis
# ====================================================================
def _user_notes_collection(kind: str):
    if kind not in ("reports", "suivis"):
        raise HTTPException(status_code=404, detail="Type inconnu")
    return db.user_reports if kind == "reports" else db.user_suivis


@api.get("/me/notes/{kind}", tags=["Portail Client"])
async def me_list_notes(
    kind: str,
    author: Optional[str] = None,
    q: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    base = {} if _is_elevated_creator(user) else {"owner_id": user["id"]}
    query = dict(base)
    if author:
        query["owner_email"] = {"$regex": re.escape(author), "$options": "i"}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [
            {"title": rx},
            {"content_html": rx},
            {"numero": rx},
            {"tags": rx},
        ]
    items = await coll.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return await _attach_my_rating(items, kind, user["id"])


@api.get("/me/notes/{kind}/authors", tags=["Portail Client"])
async def me_list_note_authors(kind: str, user: dict = Depends(get_current_user)):
    """Distinct authors for the kind — used to populate the filter dropdown."""
    coll = _user_notes_collection(kind)
    base = {} if _is_elevated_creator(user) else {"owner_id": user["id"]}
    pipeline = [
        {"$match": base},
        {"$group": {"_id": "$owner_email", "name": {"$last": "$owner_name"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    items = await coll.aggregate(pipeline).to_list(500)
    return [{"email": a["_id"], "name": a.get("name"), "count": a["count"]} for a in items if a.get("_id")]


@api.post("/me/notes/{kind}", tags=["Portail Client"])
async def me_create_note(
    request: Request,
    kind: str,
    payload: UserNoteCreate,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Rôle insuffisant pour créer un enregistrement")
    await _check_descent_window(action_label="enregistrement")

    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre requis")

    # Suivis must specify the date and the client concerned
    if kind == "suivis":
        if not (payload.event_date and payload.event_date.strip()):
            raise HTTPException(status_code=400, detail="Date de l'événement requise pour un suivi")
        if not (payload.client_id and payload.client_id.strip()):
            raise HTTPException(status_code=400, detail="Client concerné requis pour un suivi")

    images = _validate_images(payload.images, max_count=10)
    prefix = "RPT" if kind == "reports" else "SUI"
    numero = await _next_simple_number(prefix)

    doc = {
        "id": _uuid(),
        "kind": kind,
        "numero": numero,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "owner_name": user.get("full_name"),
        "owner_role": user.get("tracked_role") or user.get("role"),
        "title": title,
        "content_html": payload.content_html or "",
        "tags": payload.tags or [],
        "client_id": (payload.client_id or None) if kind == "suivis" else None,
        "event_date": (payload.event_date or None) if kind == "suivis" else None,
        "images": images,
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await coll.insert_one(doc.copy())
    doc.pop("_id", None)
    # Await the webhook synchronously so the real upstream status can be
    # returned to the caller (and displayed via popup on the frontend).
    webhook_result = await _fire_notes_webhook("created", kind, doc, user)
    doc["webhook_result"] = webhook_result
    return doc


@api.put("/me/notes/{kind}/{note_id}", tags=["Portail Client"])
async def me_update_note(
    kind: str,
    note_id: str,
    payload: UserNoteUpdate,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    existing = await coll.find_one({"id": note_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Note introuvable")
    # Owner OR elevated user can edit
    if existing.get("owner_id") != user["id"] and not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Modification non autorisée")
    # 1h lock from creation (unless admin/superviseur which can always fix)
    if not _is_admin_or_superviseur(user):
        try:
            created = datetime.fromisoformat(existing["created_at"])
        except Exception:
            created = datetime.now(timezone.utc)
        if datetime.now(timezone.utc) > created + timedelta(hours=1):
            raise HTTPException(status_code=403, detail="Modification verrouillée : la fenêtre d'1h après la création est dépassée")

    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "images" in update:
        update["images"] = _validate_images(update["images"], max_count=10)
    update["updated_at"] = _now()
    await coll.update_one({"id": note_id}, {"$set": update})
    refreshed = await coll.find_one({"id": note_id}, {"_id": 0}) or {**existing, **update}
    webhook_result = await _fire_notes_webhook("updated", kind, refreshed, user)
    return {"ok": True, "webhook_result": webhook_result}


@api.delete("/me/notes/{kind}/{note_id}", tags=["Portail Client"])
async def me_delete_note(
    kind: str,
    note_id: str,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Suppression réservée aux rôles Administrateur / Superviseur")
    existing = await coll.find_one({"id": note_id}, {"_id": 0})
    res = await coll.delete_one({"id": note_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Note introuvable")
    if existing:
        webhook_result = await _fire_notes_webhook("deleted", kind, existing, user)
        return {"ok": True, "webhook_result": webhook_result}
    return {"ok": True}


@api.get("/me/notes-summary", tags=["Portail Client"])
async def me_notes_summary(user: dict = Depends(get_current_user)):
    """Returns counts and last update timestamps to display dashboard buttons.
    Elevated users see global counts (all notes); others see only their own.
    """
    base = {} if _is_elevated_creator(user) else {"owner_id": user["id"]}
    rep_count = await db.user_reports.count_documents(base)
    sui_count = await db.user_suivis.count_documents(base)
    rep_last = await db.user_reports.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    sui_last = await db.user_suivis.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    return {
        "reports": {"count": rep_count, "last_updated": (rep_last or {}).get("updated_at")},
        "suivis": {"count": sui_count, "last_updated": (sui_last or {}).get("updated_at")},
    }


# ====================================================================
# PORTAL — Interventions (elevated users)
# ====================================================================
@api.post("/me/interventions", tags=["Portail Client"])
async def me_create_intervention(
    request: Request,
    payload: InterventionCreate,
    user: dict = Depends(get_current_user),
):
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Rôle insuffisant pour créer une intervention")
    await _check_descent_window(action_label="enregistrement")
    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    intervention_number = await _next_intervention_number(client)
    images = _validate_images(payload.images, max_count=10)
    doc = {
        "id": _uuid(),
        **payload.model_dump(),
        "images": images,
        "intervention_number": intervention_number,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "owner_name": user.get("full_name"),
        "owner_role": user.get("tracked_role") or user.get("role"),
        "ip": _client_ip_from_request(request),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.interventions.insert_one(doc.copy())
    doc.pop("_id", None)
    webhook_result = await _fire_intervention_webhook("created", doc)
    doc["webhook_result"] = webhook_result
    # Fire automation: intervention.created (portal client)
    try:
        asyncio.create_task(_emit_event("intervention.created", {
            "client_id": payload.client_id,
            "extra_ctx": {
                "intervention_number": doc.get("intervention_number") or "",
                "intervention_subject": doc.get("subject") or doc.get("title") or "",
            },
        }))
    except Exception:
        pass
    return doc


@api.delete("/me/interventions/{int_id}", tags=["Portail Client"])
async def me_delete_intervention(int_id: str, user: dict = Depends(get_current_user)):
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Suppression réservée aux rôles Administrateur / Superviseur")
    res = await db.interventions.delete_one({"id": int_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    return {"ok": True}


# ====================================================================
# PORTAL — Documents (Moderation+ can read all & upload, only Admin/Sup delete)
# ====================================================================
@api.post("/me/documents", tags=["Portail Client"])
async def me_create_document(payload: DocumentCreate, user: dict = Depends(get_current_user)):
    if not _can_consult_all_docs(user):
        raise HTTPException(status_code=403, detail="Téléversement de document réservé aux rôles Modération / Administrateur / Superviseur")
    doc = {"id": _uuid(), **payload.model_dump(), "uploaded_by_user_id": user["id"], "uploaded_by_email": user["email"], "created_at": _now()}
    await db.documents.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.delete("/me/documents/{doc_id}", tags=["Portail Client"])
async def me_delete_document(doc_id: str, user: dict = Depends(get_current_user)):
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Suppression réservée aux rôles Administrateur / Superviseur")
    res = await db.documents.delete_one({"id": doc_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return {"ok": True}


# Portal-side file upload — same behaviour as /admin/upload but allowed for Moderation+
@api.post("/me/upload", tags=["Portail Client"])
async def me_upload(request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not _can_consult_all_docs(user):
        raise HTTPException(status_code=403, detail="Téléversement réservé aux rôles Modération / Administrateur / Superviseur")
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    target = UPLOAD_DIR / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    size = target.stat().st_size
    ext_suffix = (suffix.lstrip(".") or "").lower()
    public_path = f"/api/files/{file_id}{('.' + ext_suffix) if ext_suffix else ''}"
    file_doc = {
        "id": file_id,
        "filename": file.filename,
        "stored_name": safe_name,
        "extension": suffix.lstrip(".") if suffix else None,
        "content_type": file.content_type or mimetypes.guess_type(file.filename or "")[0],
        "size": size,
        "url": public_path,
        # Absolute public URL (used by Meta to fetch headers/media on outbound templates)
        # Include the extension so Meta accepts it as a "valid document/image link".
        "public_url": f"{(_public_base_url(request) or str(request.base_url).rstrip('/'))}{public_path}",
        "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"),
        "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
    }
    await db.files.insert_one(file_doc.copy())
    await db.document_logs.insert_one({
        "id": _uuid(),
        "event_type": "upload",
        "file_id": file_id,
        "filename": file.filename,
        "extension": file_doc.get("extension"),
        "size": size,
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "ip": file_doc["uploaded_from_ip"],
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
    })
    file_doc.pop("_id", None)
    return file_doc


# ====================================================================
# PORTAL — Contacts inbox (elevated users)
# ====================================================================
@api.get("/me/contact-inbox", tags=["Portail Client"])
async def me_contact_inbox(user: dict = Depends(get_current_user)):
    """Inbox of messages submitted via the public contact form.
    NOTE: renamed from /me/contacts to avoid collision with the contacts directory.
    """
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Accès aux messages réservé aux rôles Modération / Administrateur / Superviseur")
    items = await db.contacts.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


@api.post("/me/contacts/{contact_id}/save-as-tracked-user", tags=["Portail Client"])
async def me_save_contact_as_tracked(
    contact_id: str,
    payload: SaveContactAsTrackedUser,
    user: dict = Depends(get_current_user),
):
    """Same as /admin/contacts/{id}/save-as-tracked-user but also auto-generates a password,
    creates a bridged users row, optionally emails the credentials, and returns the password.
    """
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Accès réservé aux rôles Modération / Administrateur / Superviseur")
    contact = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Message introuvable")
    email = (contact.get("email") or "").strip().lower()
    if not is_valid_email_syntax(email):
        raise HTTPException(status_code=400, detail="Email du message invalide (syntaxe)")
    if payload.role not in TRACKED_USER_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {', '.join(TRACKED_USER_ROLES)}")
    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    existing = await db.tracked_users.find_one({"email": email, "client_id": payload.client_id}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="Cet utilisateur est déjà enregistré pour ce client")

    # Create tracked user
    tu_id = _uuid()
    tu_doc = {
        "id": tu_id,
        "client_id": payload.client_id,
        "name": contact.get("name") or email,
        "email": email,
        "role": payload.role,
        "department": payload.department,
        "phone": contact.get("phone"),
        "company": contact.get("company"),
        "status": "active",
        "source_contact_id": contact_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.tracked_users.insert_one(tu_doc.copy())

    # Auto-generate a strong password & bridge user
    raw_pwd = secrets.token_urlsafe(9)
    user_id = _uuid()
    await db.users.insert_one({
        "id": user_id,
        "email": email,
        "password_hash": hash_password(raw_pwd),
        "full_name": tu_doc["name"],
        "role": "client",
        "phone": tu_doc.get("phone"),
        "company": client.get("company"),
        "logo_url": client.get("logo_url"),
        "account_status": "active",
        "tracked_user_id": tu_id,
        "tracked_role": payload.role,
        "parent_client_id": payload.client_id,
        "created_at": _now(),
        "updated_at": _now(),
    })
    await db.tracked_users.update_one(
        {"id": tu_id},
        {"$set": {"user_account_id": user_id, "has_password": True, "updated_at": _now()}},
    )
    await db.contacts.update_one(
        {"id": contact_id},
        {"$set": {"saved_as_tracked_user_id": tu_id, "updated_at": _now()}},
    )

    # Try to email the credentials (non-blocking, best-effort)
    email_sent = False
    try:
        from email_service import send_email
        s = await db.settings.find_one({"_id": "global"}) or {}
        site = s.get("company_email") or "support@sawalismartsystems.com"
        text_body = (
            f"Bonjour {tu_doc['name']},\n\n"
            f"Un accès au portail SAWALI vient de vous être créé.\n\n"
            f"Identifiant : {email}\n"
            f"Mot de passe initial : {raw_pwd}\n\n"
            f"Connectez-vous via /login. Vous pourrez le modifier depuis votre espace.\n\n"
            f"— L'équipe {site}"
        )
        html_body = text_body.replace("\n", "<br>")
        email_sent = await send_email(email, "Vos identifiants SAWALI", html_body, text_body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email tracked-user credentials failed: %s", exc)

    tu_doc.pop("_id", None)
    return {**tu_doc, "generated_password": raw_pwd, "email_sent": email_sent}


# ====================================================================
# RATINGS — 5-star rating on report / suivi / intervention (Admin/Sup only)
# ====================================================================
RATEABLE_KINDS = ("reports", "suivis", "interventions", "formations")


@api.post("/me/ratings/{kind}/{target_id}", tags=["Portail Client"])
async def me_rate(
    kind: str,
    target_id: str,
    payload: RatingCreate,
    user: dict = Depends(get_current_user),
):
    if kind not in RATEABLE_KINDS:
        raise HTTPException(status_code=404, detail="Type non noté")
    if not _can_rate(user) and not (kind == "formations" and _is_tracked_user(user)):
        raise HTTPException(status_code=403, detail="Notation non autorisée")
    if not 1 <= payload.stars <= 5:
        raise HTTPException(status_code=400, detail="Note invalide (1 à 5)")
    coll_map = {
        "reports": db.user_reports,
        "suivis": db.user_suivis,
        "interventions": db.interventions,
        "formations": db.formations,
    }
    coll = coll_map[kind]
    target = await coll.find_one({"id": target_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    rating_doc = {
        "id": _uuid(),
        "kind": kind,
        "target_id": target_id,
        "rated_by_user_id": user["id"],
        "rated_by_email": user["email"],
        "stars": int(payload.stars),
        "comment": (payload.comment or "").strip() or None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    # Upsert: one rating per (rater, target)
    await db.ratings.update_one(
        {"kind": kind, "target_id": target_id, "rated_by_user_id": user["id"]},
        {"$set": rating_doc},
        upsert=True,
    )
    return {"ok": True, "stars": rating_doc["stars"]}


@api.delete("/me/ratings/{kind}/{target_id}", tags=["Portail Client"])
async def me_unrate(kind: str, target_id: str, user: dict = Depends(get_current_user)):
    if not _can_rate(user):
        raise HTTPException(status_code=403, detail="Notation réservée aux rôles Administrateur / Superviseur")
    await db.ratings.delete_one(
        {"kind": kind, "target_id": target_id, "rated_by_user_id": user["id"]}
    )
    return {"ok": True}


# ====================================================================
# ACCESS LOGS — every page access in client portal (admin/sup only to view)
# ====================================================================
@api.post("/me/access-log", tags=["Portail Client"])
async def me_log_access(
    request: Request,
    payload: AccessLogCreate,
    user: dict = Depends(get_current_user),
):
    """Records a portal page access. Called by the SPA on each route change."""
    await db.access_logs.insert_one({
        "id": _uuid(),
        "user_id": user["id"],
        "user_email": user["email"],
        "user_name": user.get("full_name"),
        "role": user.get("role"),
        "tracked_role": user.get("tracked_role"),
        "module": (payload.module or "").strip()[:120],
        "page": (payload.page or "").strip()[:255],
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent", "")[:500],
        "created_at": _now(),
    })
    return {"ok": True}


@api.get("/admin/access-logs", tags=["Admin"])
async def admin_access_logs(
    user_email: Optional[str] = None,
    module: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 1000,
    user: dict = Depends(get_current_user),
):
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Accès réservé aux rôles Administrateur / Superviseur")
    query = {}
    if user_email:
        query["user_email"] = {"$regex": re.escape(user_email), "$options": "i"}
    if module:
        query["module"] = {"$regex": re.escape(module), "$options": "i"}
    if q:
        query["$or"] = [
            {"user_email": {"$regex": re.escape(q), "$options": "i"}},
            {"user_name": {"$regex": re.escape(q), "$options": "i"}},
            {"module": {"$regex": re.escape(q), "$options": "i"}},
            {"page": {"$regex": re.escape(q), "$options": "i"}},
        ]
    items = await db.access_logs.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 10), 5000))
    return items


@api.get("/admin/access-logs/export.csv", tags=["Admin"])
async def admin_access_logs_csv(
    user_email: Optional[str] = None,
    module: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Accès réservé aux rôles Administrateur / Superviseur")
    items = await admin_access_logs(user_email=user_email, module=module, q=None, limit=5000, user=user)
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "user_email", "user_name", "role", "tracked_role", "module", "page", "ip"])
    for it in items:
        writer.writerow([
            it.get("created_at", ""),
            it.get("user_email", ""),
            it.get("user_name", ""),
            it.get("role", ""),
            it.get("tracked_role", ""),
            it.get("module", ""),
            it.get("page", ""),
            it.get("ip", ""),
        ])
    return JSONResponse(
        content={"csv": buf.getvalue()},
        headers={"Cache-Control": "no-store"},
    )


# ====================================================================
# API TRACE — frontend axios interceptor logs every mutating call here.
# Only the seeded super-admin (admin@sawalismartsystems.com) can read.
# ====================================================================
SUPER_ADMIN_EMAIL = (os.environ.get("SUPER_ADMIN_EMAIL") or "admin@sawalismartsystems.com").lower()
TRACE_MAX_BODY_CHARS = 8000

_scheduler = None  # APScheduler instance (set up in on_startup)
_health_webhook_semaphore = asyncio.Semaphore(5)  # cap concurrent realtime webhooks during error bursts
TRACE_SENSITIVE_KEYS_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|recaptcha|otp|code|session_token|"
    r"smtp_password|smtp_user|api_basic_pass|webhook_token|webhook_basic_pass|"
    r"notes_webhook_token|notes_webhook_basic_pass)",
    re.IGNORECASE,
)


def _redact_sensitive(value):
    """Server-side redaction guard (in case the FE didn't redact)."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        return json.dumps(_redact_sensitive(parsed), ensure_ascii=False, default=str)
    if isinstance(value, list):
        return [_redact_sensitive(v) for v in value]
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if TRACE_SENSITIVE_KEYS_RE.search(k) else _redact_sensitive(v))
            for k, v in value.items()
        }
    return value


def _truncate_for_trace(value):
    if value is None:
        return None
    try:
        if isinstance(value, (dict, list)):
            s = json.dumps(value, ensure_ascii=False, default=str)
        else:
            s = str(value)
    except Exception:
        s = repr(value)
    if len(s) > TRACE_MAX_BODY_CHARS:
        return s[:TRACE_MAX_BODY_CHARS] + f"... (truncated, {len(s)} chars)"
    return s


@api.post("/me/api-trace", tags=["Portail Client"])
async def me_api_trace(
    request: Request,
    payload: ApiTraceCreate,
    user: dict = Depends(get_current_user),
):
    """Records one API call from the frontend (mutations only, set up by the axios interceptor)."""
    safe_req = _redact_sensitive(payload.request_body)
    safe_resp = _redact_sensitive(payload.response_body)
    doc = {
        "id": _uuid(),
        "user_id": user["id"],
        "user_email": user["email"],
        "user_name": user.get("full_name"),
        "role": user.get("role"),
        "tracked_role": user.get("tracked_role"),
        "method": (payload.method or "").upper()[:10],
        "url": (payload.url or "")[:512],
        "status": int(payload.status or 0),
        "request_body": _truncate_for_trace(safe_req),
        "response_body": _truncate_for_trace(safe_resp),
        "duration_ms": int(payload.duration_ms or 0),
        "module": (payload.module or "")[:120],
        "error": (payload.error or "")[:500] if payload.error else None,
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent", "")[:500],
        "created_at": _now(),
    }
    await db.api_traces.insert_one(doc.copy())
    # Fire real-time alert (only on error rows, never block the request)
    try:
        if doc["status"] >= 400:
            asyncio.create_task(_fire_health_realtime(doc))
    except RuntimeError:
        pass
    return {"ok": True}


def _ensure_super_admin(user: dict) -> None:
    if (user.get("email") or "").lower() != SUPER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Accès réservé au superviseur principal")


@api.get("/admin/api-traces", tags=["Admin"])
async def admin_api_traces(
    user_email: Optional[str] = None,
    method: Optional[str] = None,
    status: Optional[int] = None,
    q: Optional[str] = None,
    only_errors: bool = False,
    limit: int = 1000,
    user: dict = Depends(get_current_user),
):
    _ensure_super_admin(user)
    query = {}
    if user_email:
        query["user_email"] = {"$regex": re.escape(user_email), "$options": "i"}
    if method:
        query["method"] = method.upper()
    if status:
        query["status"] = int(status)
    if only_errors:
        query["status"] = {"$gte": 400}
    if q:
        query["$or"] = [
            {"user_email": {"$regex": re.escape(q), "$options": "i"}},
            {"url": {"$regex": re.escape(q), "$options": "i"}},
            {"module": {"$regex": re.escape(q), "$options": "i"}},
            {"request_body": {"$regex": re.escape(q), "$options": "i"}},
            {"response_body": {"$regex": re.escape(q), "$options": "i"}},
        ]
    items = await db.api_traces.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 10), 5000))
    return items


@api.delete("/admin/api-traces", tags=["Admin"])
async def admin_clear_api_traces(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    res = await db.api_traces.delete_many({})
    return {"ok": True, "deleted": res.deleted_count}


@api.get("/admin/api-traces/export.csv", tags=["Admin"])
async def admin_api_traces_csv(
    user_email: Optional[str] = None,
    method: Optional[str] = None,
    only_errors: bool = False,
    user: dict = Depends(get_current_user),
):
    _ensure_super_admin(user)
    items = await admin_api_traces(
        user_email=user_email, method=method, status=None, q=None,
        only_errors=only_errors, limit=5000, user=user,
    )
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "user_email", "method", "url", "status", "duration_ms", "module", "ip", "request_body", "response_body", "error"])
    for it in items:
        writer.writerow([
            it.get("created_at", ""), it.get("user_email", ""), it.get("method", ""),
            it.get("url", ""), it.get("status", ""), it.get("duration_ms", ""),
            it.get("module", ""), it.get("ip", ""),
            (it.get("request_body") or "")[:1000],
            (it.get("response_body") or "")[:1000],
            it.get("error") or "",
        ])
    return JSONResponse(content={"csv": buf.getvalue()}, headers={"Cache-Control": "no-store"})


# ====================================================================
# HEALTH MONITORING — real-time alerts + weekly digest + generic DB query
# ====================================================================
async def _fire_health_webhook(payload: dict) -> bool:
    s = await db.settings.find_one({"_id": "global"}) or {}
    url = (s.get("health_webhook_url") or "").strip()
    if not url:
        return False
    headers = {"Content-Type": "application/json", "User-Agent": "SawaliHealth/1.0"}
    auth = None
    atype = (s.get("health_webhook_auth_type") or "none").lower()
    if atype == "bearer" and s.get("health_webhook_token"):
        headers["Authorization"] = f"Bearer {s['health_webhook_token']}"
    elif atype == "basic":
        auth = (s.get("health_webhook_basic_user") or "", s.get("health_webhook_basic_pass") or "")
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            r = await http.post(url, json=payload, headers=headers, auth=auth)
            logger.info("Health webhook %s -> %s", url, r.status_code)
            return 200 <= r.status_code < 300
    except Exception as exc:  # noqa: BLE001
        logger.warning("Health webhook failed: %s", exc)
        return False


async def _fire_health_realtime(trace_doc: dict) -> None:
    async with _health_webhook_semaphore:
        try:
            s = await db.settings.find_one({"_id": "global"}) or {}
            if not s.get("health_realtime_enabled"):
                return
            recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
            body = {
                "type": "api_trace_error",
                "fired_at": _now(),
                "trace": {k: trace_doc.get(k) for k in (
                    "id", "method", "url", "status", "user_email", "module",
                    "duration_ms", "error", "request_body", "response_body", "ip", "created_at",
                )},
            }
            await _fire_health_webhook(body)
            try:
                from email_service import send_email
                subject = f"[SAWALI ALERT] {trace_doc.get('method')} {trace_doc.get('url')} -> HTTP {trace_doc.get('status')}"
                html = (
                    f"<div style='font-family:Arial,sans-serif;'>"
                    f"<h3 style='color:#EF4444'>Erreur API détectée</h3>"
                    f"<p style='color:#475569;font-size:13px;'>{trace_doc.get('user_email')} · {trace_doc.get('created_at')}</p>"
                    f"<p><code>{trace_doc.get('method')} {trace_doc.get('url')}</code> → "
                    f"<strong style='color:#EF4444'>HTTP {trace_doc.get('status')}</strong> ({trace_doc.get('duration_ms')} ms)</p>"
                    f"<pre style='background:#0F172A;color:#7DD3FC;padding:10px;border-radius:6px;font-size:11px;'>{(trace_doc.get('request_body') or '')[:1500]}</pre>"
                    f"<pre style='background:#0F172A;color:#FCA5A5;padding:10px;border-radius:6px;font-size:11px;'>{(trace_doc.get('response_body') or '')[:1500]}</pre>"
                    f"</div>"
                )
                text = f"Erreur API: {trace_doc.get('method')} {trace_doc.get('url')} HTTP {trace_doc.get('status')} par {trace_doc.get('user_email')}"
                await send_email(recipient, subject, html, text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Health realtime email failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Health realtime alert failed: %s", exc)


async def _build_health_stats(window_hours: int = 24) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    base = {"created_at": {"$gte": cutoff}}
    total = await db.api_traces.count_documents(base)
    errors = await db.api_traces.count_documents({**base, "status": {"$gte": 400}})
    rate = (errors / total * 100) if total else 0.0
    top_errors = await db.api_traces.aggregate([
        {"$match": {**base, "status": {"$gte": 400}}},
        {"$group": {"_id": {"method": "$method", "url": "$url"}, "count": {"$sum": 1}, "last_status": {"$last": "$status"}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ]).to_list(50)
    top_users = await db.api_traces.aggregate([
        {"$match": base},
        {"$group": {"_id": "$user_email", "count": {"$sum": 1}, "errors": {"$sum": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ]).to_list(50)
    hourly = await db.api_traces.aggregate([
        {"$match": base},
        {"$project": {"hour": {"$substr": ["$created_at", 0, 13]}, "is_err": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}}},
        {"$group": {"_id": "$hour", "total": {"$sum": 1}, "errors": {"$sum": "$is_err"}}},
        {"$sort": {"_id": 1}},
    ]).to_list(96)
    avg_duration = 0
    if total:
        agg = await db.api_traces.aggregate([
            {"$match": base}, {"$group": {"_id": None, "avg": {"$avg": "$duration_ms"}}},
        ]).to_list(1)
        avg_duration = int((agg[0]["avg"] if agg else 0) or 0)
    return {
        "window_hours": window_hours,
        "total": total,
        "errors": errors,
        "error_rate": round(rate, 2),
        "avg_duration_ms": avg_duration,
        "top_errors": [{"method": e["_id"]["method"], "url": e["_id"]["url"], "count": e["count"], "last_status": e.get("last_status")} for e in top_errors],
        "top_users": [{"email": u["_id"], "total": u["count"], "errors": u.get("errors", 0)} for u in top_users],
        "hourly": [{"hour": h["_id"], "total": h["total"], "errors": h["errors"]} for h in hourly],
    }


@api.get("/admin/health-stats", tags=["Admin"])
async def admin_health_stats(window_hours: int = 24, user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    window_hours = max(1, min(int(window_hours or 24), 24 * 14))
    return await _build_health_stats(window_hours)


@api.post("/admin/health/test-email", tags=["Admin"])
async def admin_health_test_email(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    s = await db.settings.find_one({"_id": "global"}) or {}
    recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
    fake_trace = {
        "id": _uuid(), "method": "POST", "url": "/api/test", "status": 500,
        "user_email": user["email"], "module": "test",
        "duration_ms": 42, "error": "Test alert (manual trigger)",
        "request_body": "{}", "response_body": "{}", "ip": "127.0.0.1",
        "created_at": _now(),
    }
    asyncio.create_task(_fire_health_realtime(fake_trace))
    return {"ok": True, "recipient": recipient}


async def _send_weekly_digest():
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("health_weekly_enabled"):
            return
        stats = await _build_health_stats(window_hours=24 * 7)
        recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
        await _fire_health_webhook({"type": "weekly_digest", "fired_at": _now(), "stats": stats})
        try:
            from email_service import send_email
            subject = f"[SAWALI] Rapport hebdo santé — {datetime.now(timezone.utc).date().isoformat()}"
            top_err_html = "".join(
                f"<tr><td style='padding:4px 8px;font-family:monospace;'>{e['method']} {e['url']}</td><td style='padding:4px 8px;text-align:right;'>{e['count']}</td></tr>"
                for e in stats["top_errors"][:5]
            ) or "<tr><td colspan='2' style='padding:6px 8px;color:#64748B;'>Aucune erreur — bravo !</td></tr>"
            top_user_html = "".join(
                f"<tr><td style='padding:4px 8px;'>{u['email']}</td><td style='padding:4px 8px;text-align:right;'>{u['total']}</td><td style='padding:4px 8px;text-align:right;color:{'#EF4444' if u['errors'] else '#94A3B8'}'>{u['errors']}</td></tr>"
                for u in stats["top_users"][:5]
            )
            html = (
                f"<div style='font-family:Arial,sans-serif;max-width:640px;'>"
                f"<h2 style='color:#1E90FF;'>Rapport hebdo santé applicative — SAWALI</h2>"
                f"<p style='color:#475569;font-size:13px;'>Synthèse des 7 derniers jours.</p>"
                f"<p>Total: <strong>{stats['total']}</strong> · Erreurs: "
                f"<strong style='color:{'#EF4444' if stats['errors'] else '#10B981'}'>{stats['errors']}</strong> · "
                f"Taux: <strong>{stats['error_rate']}%</strong> · Durée moy.: {stats['avg_duration_ms']} ms</p>"
                f"<h3 style='font-size:14px;'>Top endpoints en erreur</h3>"
                f"<table style='border-collapse:collapse;width:100%;border:1px solid #E2E8F0;'>{top_err_html}</table>"
                f"<h3 style='font-size:14px;margin-top:18px;'>Top utilisateurs</h3>"
                f"<table style='border-collapse:collapse;width:100%;border:1px solid #E2E8F0;'>"
                f"<tr style='background:#F8FAFC;'><th style='padding:4px 8px;text-align:left;'>Email</th>"
                f"<th style='padding:4px 8px;text-align:right;'>Actions</th>"
                f"<th style='padding:4px 8px;text-align:right;'>Erreurs</th></tr>"
                f"{top_user_html}</table>"
                f"<p style='color:#94A3B8;font-size:11px;margin-top:24px;'>Généré automatiquement chaque vendredi à 05:00 (Africa/Abidjan).</p>"
                f"</div>"
            )
            text = f"Hebdo SAWALI — {stats['total']} actions, {stats['errors']} erreurs ({stats['error_rate']}%)."
            await send_email(recipient, subject, html, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weekly digest email failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Weekly digest failed: %s", exc)


@api.post("/admin/health/run-weekly-now", tags=["Admin"])
async def admin_health_run_weekly_now(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    await _send_weekly_digest()
    return {"ok": True}


# ====================================================================
# AUTH CHECKER — periodic end-to-end probe of the login flow.
# Catches regressions like JWT secret rotation, deleted admin user,
# corrupted password hash, broken /auth/me handler, etc.
# ====================================================================
async def _run_auth_check(triggered_by: str = "manual") -> dict:
    """Run a 4-step probe of the auth pipeline. Never raises — always returns a dict."""
    started = datetime.now(timezone.utc)
    steps: list[dict] = []
    overall_ok = True

    async def _step(name: str, coro):
        nonlocal overall_ok
        t0 = datetime.now(timezone.utc)
        try:
            result = await coro
            duration = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            steps.append({"name": name, "ok": True, "duration_ms": duration, "error": None, "info": result})
            return result
        except Exception as exc:  # noqa: BLE001
            duration = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            steps.append({"name": name, "ok": False, "duration_ms": duration, "error": str(exc)[:300], "info": None})
            overall_ok = False
            return None

    # Step 1 — admin user exists in DB
    async def _check_admin_exists():
        admin = await db.users.find_one({"email": SUPER_ADMIN_EMAIL}, {"_id": 0, "id": 1, "role": 1, "password_hash": 1})
        if not admin:
            raise RuntimeError(f"Super-admin '{SUPER_ADMIN_EMAIL}' introuvable en base")
        if admin.get("role") != "admin":
            raise RuntimeError(f"Super-admin a le mauvais role: {admin.get('role')}")
        if not admin.get("password_hash"):
            raise RuntimeError("Hash mot de passe vide")
        return {"id": admin["id"], "role": admin["role"]}

    admin_info = await _step("admin_user_exists", _check_admin_exists())

    # Step 2 — JWT mint + decode roundtrip
    async def _check_jwt_roundtrip():
        if not admin_info:
            raise RuntimeError("Étape précédente échouée")
        from auth import decode_token
        token = create_access_token(admin_info["id"], admin_info["role"])
        if not token or len(token) < 20:
            raise RuntimeError("Token vide ou trop court")
        payload = decode_token(token)
        if payload.get("sub") != admin_info["id"] or payload.get("role") != "admin":
            raise RuntimeError(f"Payload incorrect: {payload}")
        return {"token_len": len(token), "exp": payload.get("exp")}

    jwt_info = await _step("jwt_mint_decode", _check_jwt_roundtrip())

    # Step 3 — HTTP call to /api/auth/me (full middleware stack)
    async def _check_auth_me_http():
        if not admin_info:
            raise RuntimeError("Étape précédente échouée")
        token = create_access_token(admin_info["id"], admin_info["role"])
        async with httpx.AsyncClient(timeout=5.0, base_url="http://127.0.0.1:8001") as http:
            r = await http.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            if r.status_code != 200:
                raise RuntimeError(f"/auth/me HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            if (data.get("email") or "").lower() != SUPER_ADMIN_EMAIL:
                raise RuntimeError(f"/auth/me retourne le mauvais user: {data.get('email')}")
            return {"http": r.status_code, "email": data.get("email")}

    await _step("auth_me_http", _check_auth_me_http())

    # Step 4 — POST /api/auth/login with empty payload should return 4xx (proves wiring)
    async def _check_login_endpoint_responsive():
        async with httpx.AsyncClient(timeout=5.0, base_url="http://127.0.0.1:8001") as http:
            r = await http.post("/api/auth/login", json={})
            if r.status_code >= 500:
                raise RuntimeError(f"/auth/login HTTP {r.status_code}: {r.text[:200]}")
            return {"http": r.status_code}

    await _step("login_endpoint_responsive", _check_login_endpoint_responsive())

    finished = datetime.now(timezone.utc)
    total_duration = int((finished - started).total_seconds() * 1000)
    result = {
        "id": _uuid(),
        "ok": overall_ok,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "total_duration_ms": total_duration,
        "steps": steps,
        "triggered_by": triggered_by,
        "created_at": _now(),
    }
    # Persist (capped to last 200 results)
    try:
        await db.auth_checks.insert_one(result.copy())
        # Trim collection to keep it small
        count = await db.auth_checks.count_documents({})
        if count > 200:
            old = await db.auth_checks.find({}, {"_id": 0, "id": 1}).sort("created_at", 1).limit(count - 200).to_list(50)
            if old:
                await db.auth_checks.delete_many({"id": {"$in": [o["id"] for o in old]}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("auth_check persist failed: %s", exc)

    # Fire alert if failed and toggle is on
    if not overall_ok:
        try:
            s = await db.settings.find_one({"_id": "global"}) or {}
            if s.get("health_auth_check_enabled"):
                await _fire_health_webhook({"type": "auth_check_failed", "fired_at": _now(), "result": result})
                try:
                    from email_service import send_email
                    recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
                    failed_steps = [s for s in steps if not s["ok"]]
                    rows = "".join(
                        f"<tr><td style='padding:4px 8px;font-family:monospace;'>{s['name']}</td>"
                        f"<td style='padding:4px 8px;color:#EF4444'>{s['error'] or '—'}</td></tr>"
                        for s in failed_steps
                    )
                    html = (
                        f"<div style='font-family:Arial,sans-serif;'>"
                        f"<h3 style='color:#EF4444'>🚨 Auth Checker — échec détecté</h3>"
                        f"<p style='color:#475569;font-size:13px;'>Déclenché : <strong>{triggered_by}</strong> · {finished.isoformat()}</p>"
                        f"<p>Durée totale : {total_duration} ms · {len(failed_steps)} étape(s) en erreur sur {len(steps)}.</p>"
                        f"<table style='border-collapse:collapse;width:100%;border:1px solid #E2E8F0;'>"
                        f"<tr style='background:#F8FAFC;'><th style='padding:4px 8px;text-align:left;'>Étape</th>"
                        f"<th style='padding:4px 8px;text-align:left;'>Erreur</th></tr>{rows}</table>"
                        f"<p style='color:#94A3B8;font-size:11px;margin-top:24px;'>Le flux de connexion est cassé. Vérifiez immédiatement /admin/health.</p>"
                        f"</div>"
                    )
                    text = f"AUTH FAIL — {len(failed_steps)} step(s): " + ", ".join(s["name"] for s in failed_steps)
                    await send_email(recipient, "[SAWALI ALERT] Auth Checker — échec détecté", html, text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Auth check email failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auth check alert pipeline failed: %s", exc)

    return result


@api.post("/admin/health/auth-check", tags=["Admin"])
async def admin_health_auth_check_now(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    return await _run_auth_check(triggered_by=f"manual:{user['email']}")


@api.get("/admin/health/auth-check/history", tags=["Admin"])
async def admin_health_auth_check_history(limit: int = 24, user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    items = await db.auth_checks.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 200))
    return items


@api.get("/admin/health/auth-check/latest", tags=["Admin"])
async def admin_health_auth_check_latest(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    item = await db.auth_checks.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
    return item or {"ok": None, "never_run": True}


# ====================================================================
# UPTIME MONITOR — multi-endpoint availability probes (hourly cron)
# Powers both the admin dashboard and the public /status page.
# ====================================================================
UPTIME_PROBES = [
    {"key": "db_ping", "label": "Base de données", "kind": "db", "public": True},
    {"key": "api_health", "label": "API publique", "kind": "http", "method": "GET", "path": "/api/health", "expect": 200, "public": True},
    {"key": "api_company_info", "label": "Contenu CMS", "kind": "http", "method": "GET", "path": "/api/company-info", "expect": 200, "public": True},
    {"key": "api_visits_count", "label": "Compteur de visites", "kind": "http", "method": "GET", "path": "/api/visits/count", "expect": 200, "public": True},
    {"key": "auth_login_endpoint", "label": "Endpoint /auth/login", "kind": "http", "method": "POST", "path": "/api/auth/login", "expect_max": 499, "public": False},
]


async def _probe_one(probe: dict) -> dict:
    """Execute a single probe. Returns {key, label, ok, duration_ms, error, status}."""
    started = datetime.now(timezone.utc)
    try:
        if probe["kind"] == "db":
            await asyncio.wait_for(db.users.find_one({}, {"_id": 1}), timeout=5.0)
            duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return {"key": probe["key"], "label": probe["label"], "ok": True, "duration_ms": duration, "error": None, "status": "OK"}
        elif probe["kind"] == "http":
            async with httpx.AsyncClient(timeout=5.0, base_url="http://127.0.0.1:8001") as http:
                if probe["method"] == "GET":
                    r = await http.get(probe["path"])
                else:
                    r = await http.post(probe["path"], json={})
                duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                expect = probe.get("expect")
                expect_max = probe.get("expect_max")
                ok = (r.status_code == expect) if expect else (r.status_code <= expect_max)
                return {
                    "key": probe["key"], "label": probe["label"], "ok": ok,
                    "duration_ms": duration, "error": None if ok else f"HTTP {r.status_code}",
                    "status": str(r.status_code),
                }
    except Exception as exc:  # noqa: BLE001
        duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        return {"key": probe["key"], "label": probe["label"], "ok": False, "duration_ms": duration, "error": str(exc)[:200], "status": "ERR"}


async def _run_uptime_probes(triggered_by: str = "manual") -> dict:
    """Run all configured probes, persist a single document, fire alert if any failed."""
    started = datetime.now(timezone.utc)
    probes = await asyncio.gather(*[_probe_one(p) for p in UPTIME_PROBES])
    finished = datetime.now(timezone.utc)
    overall_ok = all(p["ok"] for p in probes)
    doc = {
        "id": _uuid(),
        "ok": overall_ok,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "total_duration_ms": int((finished - started).total_seconds() * 1000),
        "probes": list(probes),
        "triggered_by": triggered_by,
        "created_at": _now(),
    }
    try:
        await db.uptime_checks.insert_one(doc.copy())
        # Trim — keep last 30 days × 24 = 720 max
        count = await db.uptime_checks.count_documents({})
        if count > 800:
            old = await db.uptime_checks.find({}, {"_id": 0, "id": 1}).sort("created_at", 1).limit(count - 720).to_list(200)
            if old:
                await db.uptime_checks.delete_many({"id": {"$in": [o["id"] for o in old]}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("uptime_check persist failed: %s", exc)

    # Fire alert if any probe failed and feature is enabled
    if not overall_ok:
        try:
            s = await db.settings.find_one({"_id": "global"}) or {}
            if s.get("health_uptime_alerts_enabled"):
                failed = [p for p in probes if not p["ok"]]
                payload = {"type": "uptime_failed", "fired_at": _now(), "result": doc}
                await _fire_health_webhook(payload)
                try:
                    from email_service import send_email
                    recipient = (s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
                    rows = "".join(
                        f"<tr><td style='padding:4px 8px;font-family:monospace;'>{p['label']}</td>"
                        f"<td style='padding:4px 8px;color:#EF4444'>{p['error'] or p['status']}</td>"
                        f"<td style='padding:4px 8px;text-align:right;'>{p['duration_ms']} ms</td></tr>"
                        for p in failed
                    )
                    html = (
                        f"<div style='font-family:Arial,sans-serif;'>"
                        f"<h3 style='color:#EF4444'>🚨 Uptime Monitor — services indisponibles</h3>"
                        f"<p>{len(failed)} sonde(s) en échec sur {len(probes)} à {finished.isoformat()}.</p>"
                        f"<table style='border-collapse:collapse;width:100%;border:1px solid #E2E8F0;'>"
                        f"<tr style='background:#F8FAFC;'><th style='padding:4px 8px;text-align:left;'>Service</th>"
                        f"<th style='padding:4px 8px;text-align:left;'>Erreur</th>"
                        f"<th style='padding:4px 8px;text-align:right;'>Latence</th></tr>{rows}</table>"
                        f"</div>"
                    )
                    text = f"UPTIME FAIL — {len(failed)} probe(s): " + ", ".join(p["key"] for p in failed)
                    await send_email(recipient, "[SAWALI ALERT] Uptime — services indisponibles", html, text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Uptime alert email failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Uptime alert pipeline failed: %s", exc)
    return doc


async def _build_uptime_stats(window_hours: int = 24 * 7, public_only: bool = False) -> dict:
    """Aggregate uptime per probe over the last `window_hours`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    docs = await db.uptime_checks.find({"created_at": {"$gte": cutoff}}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    visible_keys = {p["key"] for p in UPTIME_PROBES if (not public_only or p.get("public"))}
    per_probe: dict[str, dict] = {}
    for p in UPTIME_PROBES:
        if p["key"] not in visible_keys:
            continue
        per_probe[p["key"]] = {
            "key": p["key"], "label": p["label"], "total": 0, "ok": 0, "fail": 0,
            "avg_duration_ms": 0, "last_status": None, "last_error": None, "last_at": None,
            "timeline": [],  # [{ts, ok, duration_ms}]
        }
    durations: dict[str, list[int]] = {k: [] for k in per_probe}
    for d in docs:
        for p in d.get("probes", []):
            k = p.get("key")
            if k not in per_probe:
                continue
            per_probe[k]["total"] += 1
            if p.get("ok"):
                per_probe[k]["ok"] += 1
            else:
                per_probe[k]["fail"] += 1
            durations[k].append(p.get("duration_ms") or 0)
            per_probe[k]["last_status"] = p.get("status")
            per_probe[k]["last_error"] = p.get("error")
            per_probe[k]["last_at"] = d.get("created_at")
            per_probe[k]["timeline"].append({
                "ts": d.get("created_at"),
                "ok": bool(p.get("ok")),
                "duration_ms": p.get("duration_ms"),
            })
    for k, v in per_probe.items():
        v["avg_duration_ms"] = int(sum(durations[k]) / len(durations[k])) if durations[k] else 0
        v["uptime_pct"] = round((v["ok"] / v["total"] * 100) if v["total"] else 100.0, 2)
        # cap timeline to last 168 points (7d hourly) for payload size
        v["timeline"] = v["timeline"][-168:]
    overall_total = sum(v["total"] for v in per_probe.values())
    overall_ok = sum(v["ok"] for v in per_probe.values())
    overall_pct = round((overall_ok / overall_total * 100) if overall_total else 100.0, 2)
    return {
        "window_hours": window_hours,
        "overall_uptime_pct": overall_pct,
        "samples": len(docs),
        "probes": list(per_probe.values()),
        "generated_at": _now(),
    }


@api.post("/admin/health/uptime/run-now", tags=["Admin"])
async def admin_health_uptime_run_now(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    return await _run_uptime_probes(triggered_by=f"manual:{user['email']}")


@api.get("/admin/health/uptime/stats", tags=["Admin"])
async def admin_health_uptime_stats(window_hours: int = 168, user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    window_hours = max(1, min(int(window_hours or 168), 24 * 30))
    return await _build_uptime_stats(window_hours, public_only=False)


@api.get("/public/status", tags=["Public"])
async def public_status(window_hours: int = 168):
    """Public status page data (anyone can fetch). Only public-flagged probes."""
    window_hours = max(1, min(int(window_hours or 168), 24 * 30))
    stats = await _build_uptime_stats(window_hours, public_only=True)
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "company": s.get("company_name") or "SAWALI SMART SYSTEMS",
        "logo_url": s.get("company_logo_url"),
        "stats": stats,
    }


# Generic DB query
ALLOWED_COLLECTIONS = {
    "users", "tracked_users", "appointments", "documents", "interventions",
    "contacts", "deployments", "blacklist", "client_categories", "document_categories",
    "case_studies", "blog_posts", "newsletter_subscribers", "testimonials",
    "settings", "user_reports", "user_suivis", "ratings",
    "access_logs", "api_traces", "visits", "document_logs", "files",
    "formations", "formation_modules", "formation_enrollments", "formation_visits", "formation_qa",
    "otps", "counters", "auth_checks", "uptime_checks", "incidents", "incident_subscribers",
    "user_module_visits", "forms", "form_submissions", "directory_contacts", "whatsapp_messages", "whatsapp_schedules", "automations", "client_notes", "client_tasks", "policies",
}


@api.get("/admin/db", tags=["Admin"])
async def admin_list_collections(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    out = []
    for c in sorted(ALLOWED_COLLECTIONS):
        try:
            count = await getattr(db, c).estimated_document_count()
        except Exception:
            count = None
        out.append({"name": c, "count": count})
    return out


@api.get("/admin/db/{collection}", tags=["Admin"])
async def admin_query_collection(
    collection: str,
    request: Request,
    limit: int = 200,
    sort_by: Optional[str] = None,
    sort_dir: int = -1,
    user: dict = Depends(get_current_user),
):
    """Generic JSON query over any whitelisted collection.

    Supports special suffixes on filter keys:
      - `key__regex=pattern` (case-insensitive)
      - `key__gte=...` `key__lte=...` `key__gt=...` `key__lt=...` `key__ne=...`
      - `key=value` (exact match; booleans and integers auto-coerced)
    Reserved query params: `limit`, `sort_by`, `sort_dir`.
    """
    _ensure_super_admin(user)
    if collection not in ALLOWED_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Collection non autorisée. Valeurs : {', '.join(sorted(ALLOWED_COLLECTIONS))}",
        )
    OP_MAP = {"gte": "$gte", "lte": "$lte", "gt": "$gt", "lt": "$lt", "ne": "$ne"}

    def _coerce(v: str):
        if v.lower() in ("true", "false"):
            return v.lower() == "true"
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v

    query: dict = {}
    for key, value in request.query_params.items():
        if key in ("limit", "sort_by", "sort_dir"):
            continue
        if "__" in key:
            field, op = key.split("__", 1)
            if op == "regex":
                query.setdefault(field, {})["$regex"] = re.escape(value)
                query[field]["$options"] = "i"
            elif op in OP_MAP:
                query.setdefault(field, {})[OP_MAP[op]] = _coerce(value)
            else:
                query[field] = value
        else:
            query[key] = _coerce(value)
    coll = getattr(db, collection)
    cursor = coll.find(query, {"_id": 0})
    if sort_by:
        cursor = cursor.sort(sort_by, int(sort_dir))
    items = await cursor.to_list(min(max(int(limit), 1), 5000))
    items = [_redact_sensitive(it) for it in items]
    total = await coll.count_documents(query)
    return {
        "collection": collection,
        "total_matched": total,
        "returned": len(items),
        "limit": limit,
        "items": items,
    }



# ====================================================================
# ADMIN - Settings
# ====================================================================
@api.get("/admin/settings", tags=["Admin"])
async def admin_get_settings(_: dict = Depends(get_current_admin)):
    s = await _get_settings_doc()
    # mask sensitive
    masked = dict(s)
    for k in ("smtp_password", "google_client_secret", "recaptcha_secret_key", "google_calendar_password_hint", "tracking_auth_header", "webhook_token", "webhook_basic_pass", "notes_webhook_token", "notes_webhook_basic_pass", "health_webhook_token", "health_webhook_basic_pass", "wa_access_token", "wa_verify_token"):
        if masked.get(k):
            masked[k] = "********"
    masked["google_calendar_connected"] = bool((await db.settings.find_one({"_id": "global"}) or {}).get("google_refresh_token"))
    return masked


@api.put("/admin/settings", tags=["Admin"])
async def admin_update_settings(payload: SettingsUpdate, user: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Treat the masking placeholder as "no change" for sensitive fields
    SECRET_FIELDS = (
        "smtp_password", "google_client_secret", "recaptcha_secret_key",
        "tracking_auth_header", "webhook_token", "webhook_basic_pass",
        "notes_webhook_token", "notes_webhook_basic_pass",
        "health_webhook_token", "health_webhook_basic_pass",
        "wa_access_token", "wa_verify_token",
    )
    for k in SECRET_FIELDS:
        if update.get(k) == "********":
            update.pop(k, None)
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    # Stamp incident_banner_updated_at whenever any banner field changes
    BANNER_FIELDS = ("incident_banner_enabled", "incident_banner_severity", "incident_banner_message", "incident_banner_link_url", "incident_banner_link_label")
    banner_touched = any(f in update for f in BANNER_FIELDS)
    if banner_touched:
        update["incident_banner_updated_at"] = _now()
        # Snapshot previous state to detect transitions
        prev = await db.settings.find_one({"_id": "global"}) or {}
        prev_enabled = bool(prev.get("incident_banner_enabled", False))
        next_enabled = bool(update.get("incident_banner_enabled", prev_enabled))
        editor = (user.get("email") or "").lower() or None
        # off → on : open a new incident
        if not prev_enabled and next_enabled:
            new_incident = {
                "id": _uuid(),
                "severity": update.get("incident_banner_severity") or prev.get("incident_banner_severity") or "warning",
                "message": update.get("incident_banner_message") or prev.get("incident_banner_message") or "",
                "link_url": update.get("incident_banner_link_url") or prev.get("incident_banner_link_url") or "",
                "link_label": update.get("incident_banner_link_label") or prev.get("incident_banner_link_label") or "",
                "status": "ongoing",
                "started_at": _now(),
                "resolved_at": None,
                "duration_minutes": None,
                "updates": [],
                "created_by": editor,
                "resolved_by": None,
            }
            await db.incidents.insert_one(new_incident.copy())
            asyncio.create_task(_broadcast_incident_to_subscribers("opened", new_incident))
        # on → off : resolve the latest open incident
        elif prev_enabled and not next_enabled:
            ongoing = await db.incidents.find_one({"status": "ongoing"}, sort=[("started_at", -1)])
            if ongoing:
                started = datetime.fromisoformat(ongoing["started_at"]) if isinstance(ongoing["started_at"], str) else ongoing["started_at"]
                resolved_at = datetime.now(timezone.utc)
                duration = int((resolved_at - started).total_seconds() / 60)
                resolved_doc = {**ongoing, "status": "resolved", "resolved_at": resolved_at.isoformat(), "duration_minutes": duration, "resolved_by": editor}
                await db.incidents.update_one(
                    {"id": ongoing["id"]},
                    {"$set": {"status": "resolved", "resolved_at": resolved_at.isoformat(), "duration_minutes": duration, "resolved_by": editor}},
                )
                resolved_doc.pop("_id", None)
                asyncio.create_task(_broadcast_incident_to_subscribers("resolved", resolved_doc))
        # ongoing edit : append an update entry to the latest open incident
        elif prev_enabled and next_enabled:
            content_changed = any(f in update for f in ("incident_banner_severity", "incident_banner_message", "incident_banner_link_url", "incident_banner_link_label"))
            if content_changed:
                ongoing = await db.incidents.find_one({"status": "ongoing"}, sort=[("started_at", -1)])
                if ongoing:
                    await db.incidents.update_one(
                        {"id": ongoing["id"]},
                        {"$push": {"updates": {
                            "ts": _now(),
                            "severity": update.get("incident_banner_severity") or ongoing.get("severity"),
                            "message": update.get("incident_banner_message") or ongoing.get("message"),
                            "by": editor,
                        }}},
                    )
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    return {"ok": True}


# ----- Incident history -----
@api.get("/admin/incidents", tags=["Admin"])
async def admin_list_incidents(limit: int = 200, _: dict = Depends(get_current_admin)):
    items = await db.incidents.find({}, {"_id": 0}).sort("started_at", -1).to_list(min(max(limit, 1), 1000))
    return items


@api.delete("/admin/incidents/{incident_id}", tags=["Admin"])
async def admin_delete_incident(incident_id: str, _: dict = Depends(get_current_admin)):
    res = await db.incidents.delete_one({"id": incident_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Incident introuvable")
    return {"ok": True}


@api.get("/admin/incidents/export.csv", tags=["Admin"])
async def admin_export_incidents_csv(_: dict = Depends(get_current_admin)):
    items = await db.incidents.find({}, {"_id": 0}).sort("started_at", -1).to_list(2000)
    import csv, io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["started_at", "resolved_at", "duration_minutes", "severity", "status", "message", "link_url", "created_by", "resolved_by", "updates_count"])
    for it in items:
        writer.writerow([
            it.get("started_at", ""), it.get("resolved_at") or "",
            it.get("duration_minutes") if it.get("duration_minutes") is not None else "",
            it.get("severity", ""), it.get("status", ""),
            (it.get("message") or "")[:500], it.get("link_url") or "",
            it.get("created_by") or "", it.get("resolved_by") or "",
            len(it.get("updates") or []),
        ])
    return JSONResponse(content={"csv": buf.getvalue()}, headers={"Cache-Control": "no-store"})


@api.get("/public/incidents", tags=["Public"])
async def public_list_incidents(limit: int = 30):
    """Public timeline of incidents (resolved + ongoing). Used by /uptime page."""
    items = await db.incidents.find(
        {},
        {"_id": 0, "id": 1, "severity": 1, "message": 1, "link_url": 1, "link_label": 1,
         "status": 1, "started_at": 1, "resolved_at": 1, "duration_minutes": 1, "updates": 1},
    ).sort("started_at", -1).to_list(min(max(limit, 1), 100))
    return items


# ====================================================================
# INCIDENT SUBSCRIBERS — public can subscribe to email notifications.
# Double opt-in: subscription is only active after email confirmation.
# ====================================================================
class IncidentSubscribeRequest(BaseModel):
    email: EmailStr


def _public_url() -> str:
    """Best-effort base URL for confirmation/unsubscribe links in emails."""
    return (PUBLIC_BASE_URL or "").rstrip("/")


async def _send_subscriber_confirmation(email: str, confirm_token: str) -> None:
    try:
        from email_service import send_email
        link = f"{_public_url()}/api/public/incidents/confirm?token={confirm_token}"
        html = (
            f"<div style='font-family:Arial,sans-serif;max-width:480px;'>"
            f"<h2 style='color:#1E90FF;'>SAWALI — Confirmation d'abonnement</h2>"
            f"<p>Bonjour,</p>"
            f"<p>Vous recevrez les notifications d'incidents de SAWALI SMART SYSTEMS sur cet email "
            f"après avoir cliqué sur le lien ci-dessous :</p>"
            f"<p><a href='{link}' style='display:inline-block;background:#1E90FF;color:white;"
            f"padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:bold;'>"
            f"Confirmer mon abonnement</a></p>"
            f"<p style='color:#94A3B8;font-size:11px;margin-top:24px;'>"
            f"Si vous n'avez pas demandé cet abonnement, vous pouvez ignorer cet email.</p>"
            f"</div>"
        )
        text = f"Confirmez votre abonnement aux notifications SAWALI : {link}"
        await send_email(email, "[SAWALI] Confirmez votre abonnement aux notifications", html, text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Subscriber confirmation email failed: %s", exc)


async def _broadcast_incident_to_subscribers(action: str, incident: dict) -> None:
    """Send email to all confirmed subscribers when an incident is opened or resolved."""
    try:
        subs = await db.incident_subscribers.find({"confirmed": True}, {"_id": 0, "email": 1, "unsubscribe_token": 1}).to_list(2000)
        if not subs:
            return
        from email_service import send_email
        sev = (incident.get("severity") or "warning").lower()
        sev_label = {"info": "Info", "warning": "Avertissement", "critical": "Critique"}.get(sev, sev)
        sev_color = {"info": "#0EA5E9", "warning": "#F59E0B", "critical": "#EF4444"}.get(sev, "#F59E0B")
        if action == "opened":
            subject = f"[SAWALI] Incident en cours — {sev_label}"
            headline = "Un incident est en cours"
            timeline_html = f"<p><strong>Démarré :</strong> {incident.get('started_at')}</p>"
        else:  # resolved
            subject = f"[SAWALI] Incident résolu — {sev_label}"
            headline = "Incident résolu"
            duration = incident.get("duration_minutes")
            if duration is None:
                dur_str = "—"
            elif duration < 1:
                dur_str = "moins d'une minute"
            elif duration < 60:
                dur_str = f"{duration} min"
            else:
                dur_str = f"{duration // 60} h {duration % 60} min"
            timeline_html = (
                f"<p><strong>Durée totale :</strong> {dur_str}</p>"
                f"<p><strong>Résolu :</strong> {incident.get('resolved_at')}</p>"
            )
        # Send one personalized email per subscriber (so unsubscribe link is unique)
        sem = asyncio.Semaphore(10)
        async def _send_one(sub):
            async with sem:
                unsub = f"{_public_url()}/api/public/incidents/unsubscribe?token={sub.get('unsubscribe_token','')}"
                html = (
                    f"<div style='font-family:Arial,sans-serif;max-width:560px;'>"
                    f"<div style='background:{sev_color};color:white;padding:12px 16px;border-radius:6px 6px 0 0;'>"
                    f"<strong style='text-transform:uppercase;letter-spacing:.1em;font-size:11px;'>{sev_label}</strong>"
                    f"<h2 style='margin:6px 0 0 0;font-size:18px;'>{headline}</h2></div>"
                    f"<div style='border:1px solid #E2E8F0;border-top:0;padding:18px;border-radius:0 0 6px 6px;'>"
                    f"<p style='font-size:15px;color:#0F172A;'>{(incident.get('message') or '')[:1000]}</p>"
                    f"{timeline_html}"
                    f"<p style='margin-top:18px;'><a href='{_public_url()}/uptime' style='color:#1E90FF;'>Voir le détail sur la page de statut →</a></p>"
                    f"<p style='color:#94A3B8;font-size:11px;margin-top:32px;border-top:1px solid #E2E8F0;padding-top:12px;'>"
                    f"Vous recevez cet email car vous êtes abonné aux notifications d'incidents SAWALI."
                    f" <a href='{unsub}' style='color:#94A3B8;'>Se désabonner</a></p>"
                    f"</div></div>"
                )
                text = f"{headline} ({sev_label}): {(incident.get('message') or '')[:300]} — {_public_url()}/uptime"
                try:
                    await send_email(sub["email"], subject, html, text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Subscriber broadcast to %s failed: %s", sub.get("email"), exc)
        await asyncio.gather(*[_send_one(s) for s in subs])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Incident broadcast pipeline failed: %s", exc)


@api.post("/public/incidents/subscribe", tags=["Public"])
async def public_subscribe_to_incidents(payload: IncidentSubscribeRequest):
    email = payload.email.strip().lower()
    if not is_valid_email_syntax(email):
        raise HTTPException(status_code=400, detail="Email invalide")
    existing = await db.incident_subscribers.find_one({"email": email})
    if existing:
        if existing.get("confirmed"):
            return {"ok": True, "already_subscribed": True}
        # Resend confirmation
        token = existing.get("confirmation_token") or secrets.token_urlsafe(24)
        await db.incident_subscribers.update_one({"email": email}, {"$set": {"confirmation_token": token}})
        asyncio.create_task(_send_subscriber_confirmation(email, token))
        return {"ok": True, "confirmation_resent": True}
    confirm_token = secrets.token_urlsafe(24)
    unsubscribe_token = secrets.token_urlsafe(24)
    await db.incident_subscribers.insert_one({
        "id": _uuid(),
        "email": email,
        "confirmed": False,
        "confirmation_token": confirm_token,
        "unsubscribe_token": unsubscribe_token,
        "subscribed_at": _now(),
        "confirmed_at": None,
    })
    asyncio.create_task(_send_subscriber_confirmation(email, confirm_token))
    return {"ok": True}


@api.get("/public/incidents/confirm", tags=["Public"])
async def public_confirm_subscription(token: str):
    sub = await db.incident_subscribers.find_one({"confirmation_token": token})
    if not sub:
        return RedirectResponse(url=f"{_public_url()}/uptime?subscribe=invalid")
    if not sub.get("confirmed"):
        await db.incident_subscribers.update_one(
            {"id": sub["id"]},
            {"$set": {"confirmed": True, "confirmed_at": _now()}, "$unset": {"confirmation_token": ""}},
        )
    return RedirectResponse(url=f"{_public_url()}/uptime?subscribe=confirmed")


@api.get("/public/incidents/unsubscribe", tags=["Public"])
async def public_unsubscribe(token: str):
    res = await db.incident_subscribers.delete_one({"unsubscribe_token": token})
    suffix = "ok" if res.deleted_count else "invalid"
    return RedirectResponse(url=f"{_public_url()}/uptime?subscribe={suffix}")


@api.get("/admin/incident-subscribers", tags=["Admin"])
async def admin_list_subscribers(_: dict = Depends(get_current_admin)):
    items = await db.incident_subscribers.find(
        {},
        {"_id": 0, "id": 1, "email": 1, "confirmed": 1, "subscribed_at": 1, "confirmed_at": 1},
    ).sort("subscribed_at", -1).to_list(2000)
    confirmed = sum(1 for s in items if s.get("confirmed"))
    return {"total": len(items), "confirmed": confirmed, "items": items}


@api.delete("/admin/incident-subscribers/{sub_id}", tags=["Admin"])
async def admin_delete_subscriber(sub_id: str, _: dict = Depends(get_current_admin)):
    res = await db.incident_subscribers.delete_one({"id": sub_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Abonné introuvable")
    return {"ok": True}


# ----- Google Calendar OAuth admin endpoints -----
@api.get("/admin/google/auth-url", tags=["Admin"])
async def admin_google_auth_url(request: Request, _: dict = Depends(get_current_admin)):
    base = _public_base_url(request) or PUBLIC_BASE_URL
    redirect_uri = f"{base}/api/admin/google/callback"
    url = await gcal.get_auth_url(redirect_uri)
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Veuillez configurer google_client_id et google_client_secret dans les paramètres",
        )
    return {"auth_url": url, "redirect_uri": redirect_uri}


@api.get("/admin/google/callback", tags=["Admin"])
async def admin_google_callback(request: Request, code: str):
    base = _public_base_url(request) or PUBLIC_BASE_URL
    redirect_uri = f"{base}/api/admin/google/callback"
    try:
        await gcal.exchange_code(code, redirect_uri)
        return RedirectResponse(url=f"{base}/admin/settings?gcal=ok")
    except Exception as e:
        return RedirectResponse(url=f"{base}/admin/settings?gcal=error&msg={e}")


@api.post("/admin/google/disconnect", tags=["Admin"])
async def admin_google_disconnect(_: dict = Depends(get_current_admin)):
    await db.settings.update_one(
        {"_id": "global"},
        {"$unset": {"google_refresh_token": "", "google_access_token": ""}},
    )
    return {"ok": True}


# ====================================================================
# API DOCS METADATA (custom listing)
# ====================================================================
@api.get("/api-routes", tags=["Documentation"])
async def list_api_routes():
    """Liste tous les endpoints disponibles (pour la page /api-docs)."""
    routes = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api"):
            continue
        methods = sorted(list(getattr(r, "methods", []) - {"HEAD", "OPTIONS"}))
        if not methods:
            continue
        tags = list(getattr(r, "tags", []) or [])
        routes.append(
            {
                "path": path,
                "methods": methods,
                "name": getattr(r, "name", ""),
                "tags": tags,
                "summary": getattr(r, "summary", "") or (r.endpoint.__doc__ or "").strip().split("\n")[0],
            }
        )
    routes.sort(key=lambda r: (r["tags"][0] if r["tags"] else "", r["path"]))
    return routes


# ====================================================================
# TESTIMONIALS / NPS Feedback
# ====================================================================
@api.get("/testimonials", tags=["Public"])
async def list_published_testimonials():
    """Liste les témoignages clients publiés (pour le site public)."""
    items = await db.testimonials.find(
        {"status": "published"}, {"_id": 0}
    ).to_list(200)
    return sorted(items, key=lambda x: x.get("published_at", x.get("created_at", "")), reverse=True)


@api.get("/testimonials/stats", tags=["Public"])
async def testimonials_stats():
    """Statistiques NPS publiques (basées uniquement sur les témoignages publiés)."""
    items = await db.testimonials.find({"status": "published"}, {"_id": 0}).to_list(500)
    if not items:
        return {"count": 0, "nps": None, "average_score": None, "promoters": 0, "passives": 0, "detractors": 0}
    promoters = sum(1 for x in items if x["score"] >= 9)
    passives = sum(1 for x in items if 7 <= x["score"] <= 8)
    detractors = sum(1 for x in items if x["score"] <= 6)
    total = len(items)
    nps = round(((promoters - detractors) / total) * 100)
    return {
        "count": total,
        "nps": nps,
        "average_score": round(sum(x["score"] for x in items) / total, 1),
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
    }


@api.get("/feedback/{token}", tags=["Public"])
async def get_feedback_form(token: str):
    """Récupère les infos d'un RDV via son feedback_token (formulaire NPS public)."""
    appt = await db.appointments.find_one({"feedback_token": token}, {"_id": 0})
    if not appt:
        raise HTTPException(status_code=404, detail="Lien invalide")
    if appt.get("feedback_status") == "submitted":
        raise HTTPException(status_code=400, detail="Avis déjà soumis pour ce rendez-vous")
    return {
        "appointment_id": appt["id"],
        "client_name": appt["name"],
        "company": appt.get("company"),
        "subject": appt["subject"],
        "scheduled_at": appt["scheduled_at"],
    }


@api.post("/feedback/{token}", tags=["Public"])
async def submit_feedback(token: str, payload: dict):
    """Soumet un témoignage NPS via le feedback_token. payload: {score:int, comment:str, allow_publish:bool}"""
    appt = await db.appointments.find_one({"feedback_token": token}, {"_id": 0})
    if not appt:
        raise HTTPException(status_code=404, detail="Lien invalide")
    if appt.get("feedback_status") == "submitted":
        raise HTTPException(status_code=400, detail="Avis déjà soumis")
    score = int(payload.get("score", -1))
    if not 0 <= score <= 10:
        raise HTTPException(status_code=400, detail="Score invalide (0-10)")
    rating_5 = payload.get("rating_5")
    if rating_5 is not None and rating_5 != "":
        rating_5 = float(rating_5)
        if not 0 <= rating_5 <= 5:
            raise HTTPException(status_code=400, detail="Note /5 doit être entre 0 et 5")
    else:
        rating_5 = None
    comment = (payload.get("comment") or "").strip()
    allow_publish = bool(payload.get("allow_publish", True))

    doc = {
        "id": _uuid(),
        "appointment_id": appt["id"],
        "client_id": appt.get("client_id"),
        "client_name": appt["name"],
        "client_company": appt.get("company"),
        "city": payload.get("city") or "",
        "country": payload.get("country") or "",
        "photo_url": payload.get("photo_url") or "",
        "subject": appt["subject"],
        "score": score,
        "rating_5": rating_5,
        "comment": comment,
        "allow_publish": allow_publish,
        "status": "pending",  # admin must moderate before publishing
        "source": "feedback",
        "created_at": _now(),
        "published_at": None,
    }
    await db.testimonials.insert_one(doc.copy())
    await db.appointments.update_one(
        {"id": appt["id"]}, {"$set": {"feedback_status": "submitted", "feedback_score": score}}
    )
    doc.pop("_id", None)
    return {"ok": True, "id": doc["id"]}


@api.get("/admin/testimonials", tags=["Admin"])
async def admin_list_testimonials(_: dict = Depends(get_current_admin)):
    items = await db.testimonials.find({}, {"_id": 0}).to_list(2000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


@api.post("/admin/testimonials", tags=["Admin"])
async def admin_create_testimonial(payload: dict, _: dict = Depends(get_current_admin)):
    """Création manuelle d'un témoignage par l'admin.

    Champs : client_name (req), comment, score (0-10), rating_5 (1-5),
    client_company, city, country, photo_url, subject, status (default published),
    allow_publish (default True).
    """
    name = (payload.get("client_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Identité requise")
    score = int(payload.get("score", 10))
    if not 0 <= score <= 10:
        raise HTTPException(status_code=400, detail="Score doit être entre 0 et 10")
    rating_5 = payload.get("rating_5")
    if rating_5 is not None:
        rating_5 = float(rating_5)
        if not 0 <= rating_5 <= 5:
            raise HTTPException(status_code=400, detail="Note /5 doit être entre 0 et 5")
    status = payload.get("status", "published")
    if status not in ("pending", "published", "hidden"):
        status = "published"
    doc = {
        "id": _uuid(),
        "appointment_id": None,
        "client_id": payload.get("client_id"),
        "client_name": name,
        "client_company": payload.get("client_company") or "",
        "city": payload.get("city") or "",
        "country": payload.get("country") or "",
        "photo_url": payload.get("photo_url") or "",
        "subject": payload.get("subject") or "",
        "score": score,
        "rating_5": rating_5,
        "comment": (payload.get("comment") or "").strip(),
        "allow_publish": bool(payload.get("allow_publish", True)),
        "status": status,
        "source": "manual",
        "created_at": _now(),
        "published_at": _now() if status == "published" else None,
    }
    await db.testimonials.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/testimonials/{tid}", tags=["Admin"])
async def admin_update_testimonial(tid: str, payload: dict, _: dict = Depends(get_current_admin)):
    """Modère ou modifie un témoignage. Champs supportés : status, comment, client_name,
    client_company, city, country, photo_url, score, rating_5, subject, allow_publish."""
    update = {}
    for k in ("client_name", "client_company", "city", "country", "photo_url",
              "comment", "subject", "allow_publish"):
        if k in payload:
            update[k] = payload[k]
    if "score" in payload:
        score = int(payload["score"])
        if not 0 <= score <= 10:
            raise HTTPException(status_code=400, detail="Score 0-10")
        update["score"] = score
    if "rating_5" in payload:
        r = payload["rating_5"]
        if r is None or r == "":
            update["rating_5"] = None
        else:
            r = float(r)
            if not 0 <= r <= 5:
                raise HTTPException(status_code=400, detail="Note /5 doit être 0-5")
            update["rating_5"] = r
    if "status" in payload and payload["status"] in ("pending", "published", "hidden"):
        update["status"] = payload["status"]
        if payload["status"] == "published":
            update["published_at"] = _now()
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    await db.testimonials.update_one({"id": tid}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/testimonials/{tid}", tags=["Admin"])
async def admin_delete_testimonial(tid: str, _: dict = Depends(get_current_admin)):
    await db.testimonials.delete_one({"id": tid})
    return {"ok": True}


@api.post("/admin/testimonials/request/{appt_id}", tags=["Admin"])
async def admin_request_feedback(appt_id: str, _: dict = Depends(get_current_admin)):
    """Génère/regénère un feedback_token pour un RDV (le admin peut ensuite copier le lien et l'envoyer)."""
    appt = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    if not appt:
        raise HTTPException(status_code=404, detail="RDV introuvable")
    token = appt.get("feedback_token") or generate_session_token()
    await db.appointments.update_one(
        {"id": appt_id},
        {"$set": {"feedback_token": token, "feedback_status": "pending", "updated_at": _now()}},
    )
    return {"ok": True, "feedback_token": token, "feedback_url": f"/feedback/{token}"}


# ====================================================================
# CASE STUDIES (Études de cas)
# ====================================================================
@api.get("/case-studies", tags=["Public"])
async def list_case_studies():
    items = await db.case_studies.find({"is_published": True}, {"_id": 0}).to_list(500)
    return sorted(items, key=lambda x: (not x.get("featured"), x.get("created_at", "")), reverse=False)


@api.get("/case-studies/{slug}", tags=["Public"])
async def get_case_study(slug: str):
    item = await db.case_studies.find_one({"slug": slug, "is_published": True}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Étude de cas introuvable")
    return item


@api.get("/admin/case-studies", tags=["Admin"])
async def admin_list_case_studies(_: dict = Depends(get_current_admin)):
    items = await db.case_studies.find({}, {"_id": 0}).to_list(2000)
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)


def _slugify(s: str) -> str:
    import re
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s)
    return s[:80] or _uuid()[:8]


@api.post("/admin/case-studies", tags=["Admin"])
async def admin_create_case_study(payload: dict, _: dict = Depends(get_current_admin)):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre requis")
    slug = (payload.get("slug") or _slugify(title)).strip()
    # Ensure unique slug
    if await db.case_studies.find_one({"slug": slug}):
        slug = f"{slug}-{_uuid()[:6]}"
    doc = {
        "id": _uuid(),
        "slug": slug,
        "title": title,
        "client_name": payload.get("client_name") or "",
        "sector": payload.get("sector") or "",
        "summary": payload.get("summary") or "",
        "challenge": payload.get("challenge") or "",
        "solution": payload.get("solution") or "",
        "results": payload.get("results") or "",
        "cover_image_url": payload.get("cover_image_url") or "",
        "before_image_url": payload.get("before_image_url") or "",
        "after_image_url": payload.get("after_image_url") or "",
        "gallery": payload.get("gallery") or [],
        "kpis": payload.get("kpis") or [],
        "tags": payload.get("tags") or [],
        "duration": payload.get("duration") or "",
        "year": payload.get("year") or "",
        "is_published": bool(payload.get("is_published", True)),
        "featured": bool(payload.get("featured", False)),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.case_studies.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/case-studies/{cs_id}", tags=["Admin"])
async def admin_update_case_study(cs_id: str, payload: dict, _: dict = Depends(get_current_admin)):
    allowed = {"title", "slug", "client_name", "sector", "summary", "challenge", "solution",
               "results", "cover_image_url", "before_image_url", "after_image_url",
               "gallery", "kpis", "tags", "duration", "year", "is_published", "featured"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    await db.case_studies.update_one({"id": cs_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/case-studies/{cs_id}", tags=["Admin"])
async def admin_delete_case_study(cs_id: str, _: dict = Depends(get_current_admin)):
    await db.case_studies.delete_one({"id": cs_id})
    return {"ok": True}


# ====================================================================
# BLOG (Articles techniques)
# ====================================================================
@api.get("/blog", tags=["Public"])
async def list_blog_posts(tag: Optional[str] = None):
    q = {"is_published": True}
    if tag:
        q["tags"] = tag
    items = await db.blog_posts.find(q, {"_id": 0, "body_html": 0}).to_list(500)
    return sorted(items, key=lambda x: x.get("published_at") or x.get("created_at", ""), reverse=True)


@api.get("/blog/tags", tags=["Public"])
async def list_blog_tags():
    items = await db.blog_posts.find({"is_published": True}, {"_id": 0, "tags": 1}).to_list(2000)
    counts: dict[str, int] = {}
    for it in items:
        for t in it.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)]


@api.get("/blog/{slug}", tags=["Public"])
async def get_blog_post(slug: str):
    item = await db.blog_posts.find_one({"slug": slug, "is_published": True}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Article introuvable")
    await db.blog_posts.update_one({"slug": slug}, {"$inc": {"views": 1}})
    item["views"] = (item.get("views") or 0) + 1
    return item


@api.get("/admin/blog", tags=["Admin"])
async def admin_list_blog(_: dict = Depends(get_current_admin)):
    items = await db.blog_posts.find({}, {"_id": 0, "body_html": 0}).to_list(2000)
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)


@api.get("/admin/blog/{post_id}", tags=["Admin"])
async def admin_get_blog(post_id: str, _: dict = Depends(get_current_admin)):
    item = await db.blog_posts.find_one({"id": post_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return item


@api.post("/admin/blog", tags=["Admin"])
async def admin_create_blog(payload: dict, _: dict = Depends(get_current_admin)):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre requis")
    slug = (payload.get("slug") or _slugify(title)).strip()
    if await db.blog_posts.find_one({"slug": slug}):
        slug = f"{slug}-{_uuid()[:6]}"
    is_pub = bool(payload.get("is_published", True))
    doc = {
        "id": _uuid(),
        "slug": slug,
        "title": title,
        "excerpt": payload.get("excerpt") or "",
        "body_html": payload.get("body_html") or "",
        "cover_image_url": payload.get("cover_image_url") or "",
        "author_name": payload.get("author_name") or "Équipe SAWALI",
        "author_role": payload.get("author_role") or "",
        "author_photo_url": payload.get("author_photo_url") or "",
        "tags": payload.get("tags") or [],
        "reading_time_min": int(payload.get("reading_time_min") or 0),
        "is_published": is_pub,
        "featured": bool(payload.get("featured", False)),
        "views": 0,
        "created_at": _now(),
        "updated_at": _now(),
        "published_at": _now() if is_pub else None,
    }
    await db.blog_posts.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/blog/{post_id}", tags=["Admin"])
async def admin_update_blog(post_id: str, payload: dict, _: dict = Depends(get_current_admin)):
    allowed = {"title", "slug", "excerpt", "body_html", "cover_image_url",
               "author_name", "author_role", "author_photo_url",
               "tags", "reading_time_min", "is_published", "featured"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if "reading_time_min" in update:
        try:
            update["reading_time_min"] = int(update["reading_time_min"] or 0)
        except Exception:
            update.pop("reading_time_min")
    if update.get("is_published"):
        existing = await db.blog_posts.find_one({"id": post_id}, {"_id": 0})
        if existing and not existing.get("published_at"):
            update["published_at"] = _now()
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    await db.blog_posts.update_one({"id": post_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/blog/{post_id}", tags=["Admin"])
async def admin_delete_blog(post_id: str, _: dict = Depends(get_current_admin)):
    await db.blog_posts.delete_one({"id": post_id})
    return {"ok": True}


# ====================================================================
# NEWSLETTER
# ====================================================================
@api.post("/newsletter/subscribe", tags=["Public"])
async def newsletter_subscribe(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalide")
    existing = await db.newsletter.find_one({"email": email})
    if existing:
        if existing.get("status") == "unsubscribed":
            await db.newsletter.update_one({"email": email}, {"$set": {"status": "active", "resubscribed_at": _now()}})
            return {"ok": True, "message": "Inscription réactivée"}
        return {"ok": True, "message": "Déjà abonné"}
    doc = {
        "id": _uuid(),
        "email": email,
        "name": (payload.get("name") or "").strip(),
        "source": payload.get("source") or "footer",
        "status": "active",
        "created_at": _now(),
    }
    await db.newsletter.insert_one(doc.copy())
    return {"ok": True, "message": "Merci pour votre inscription !"}


@api.post("/newsletter/unsubscribe", tags=["Public"])
async def newsletter_unsubscribe(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    await db.newsletter.update_one({"email": email}, {"$set": {"status": "unsubscribed", "unsubscribed_at": _now()}})
    return {"ok": True}


@api.get("/admin/newsletter", tags=["Admin"])
async def admin_list_newsletter(_: dict = Depends(get_current_admin)):
    items = await db.newsletter.find({}, {"_id": 0}).to_list(10000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


@api.delete("/admin/newsletter/{sub_id}", tags=["Admin"])
async def admin_delete_newsletter(sub_id: str, _: dict = Depends(get_current_admin)):
    await db.newsletter.delete_one({"id": sub_id})
    return {"ok": True}


@api.get("/admin/newsletter/export", tags=["Admin"])
async def admin_export_newsletter(_: dict = Depends(get_current_admin)):
    """Export CSV de tous les abonnés (séparateur virgule)."""
    items = await db.newsletter.find({}, {"_id": 0}).to_list(50000)
    import io
    import csv
    from fastapi.responses import StreamingResponse
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["email", "name", "status", "source", "created_at"])
    for it in sorted(items, key=lambda x: x["created_at"], reverse=True):
        writer.writerow([it.get("email", ""), it.get("name", ""), it.get("status", ""), it.get("source", ""), it.get("created_at", "")])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=newsletter_subscribers.csv"},
    )


# ====================================================================
# PHASE 5 — Notification badges on menu links
# For each module, count items created/updated since the user last visited
# that module's page. Uses collection `user_module_visits` ({user_id, module, last_visited_at}).
# ====================================================================
MODULE_COUNT_QUERIES = {
    # (module_key, collection, date_field, user_scope_field)
    # user_scope_field == "owner_id" means filter where field == user['id']
    # user_scope_field == "client_id" means use user's client_id (or self if client)
    "appointments": ("appointments", "created_at", "client_id"),
    "documents": ("documents", "created_at", "client_id"),
    "interventions": ("interventions", "created_at", "client_id"),
    "reports": ("user_notes_reports", "created_at", "owner_id"),
    "suivis": ("user_notes_suivis", "created_at", "owner_id"),
    "formations": ("formation_enrollments", "created_at", "user_id"),
    # Admin-only
    "admin_clients": ("users", "created_at", "_ADMIN_"),
    "admin_appointments": ("appointments", "created_at", "_ADMIN_"),
    "admin_interventions": ("interventions", "created_at", "_ADMIN_"),
    "admin_contacts": ("contacts", "created_at", "_ADMIN_"),
    "admin_testimonials": ("testimonials", "created_at", "_ADMIN_"),
    "admin_visits": ("visits", "datetime", "_ADMIN_"),
    "admin_access_logs": ("access_logs", "created_at", "_ADMIN_"),
    "admin_api_traces": ("api_traces", "created_at", "_ADMIN_"),
}


async def _resolve_client_id(user: dict) -> Optional[str]:
    """Return the client_id scope for a user: themselves if role=client, or parent_client_id if tracked."""
    if user.get("role") == "client":
        return user.get("id")
    if user.get("role") == "admin":
        return None  # admin has no client scope
    # tracked user — find the parent client
    return user.get("parent_client_id") or user.get("client_id")


@api.get("/me/notifications/counts", tags=["Portail Client"])
async def me_notifications_counts(user: dict = Depends(get_current_user)):
    """Return the count of new items per module since the user last visited that module."""
    now = datetime.now(timezone.utc)
    # Default lookback window: 30 days for modules the user has never visited
    default_since = (now - timedelta(days=30)).isoformat()

    visits_cursor = db.user_module_visits.find({"user_id": user["id"]}, {"_id": 0, "module": 1, "last_visited_at": 1})
    visits = {v["module"]: v["last_visited_at"] async for v in visits_cursor}

    is_admin = user.get("role") == "admin"
    client_scope = await _resolve_client_id(user)
    counts: dict[str, int] = {}

    async def _count(module_key: str, spec: tuple) -> int:
        coll_name, date_field, scope = spec
        since = visits.get(module_key, default_since)
        query: dict = {date_field: {"$gt": since}}
        if scope == "_ADMIN_":
            if not is_admin:
                return 0
        elif scope == "owner_id":
            query["owner_id"] = user["id"]
        elif scope == "user_id":
            query["user_id"] = user["id"]
        elif scope == "client_id":
            if client_scope is None and not is_admin:
                return 0
            if client_scope:
                query["client_id"] = client_scope
        try:
            return await db[coll_name].count_documents(query)
        except Exception:
            return 0

    for key, spec in MODULE_COUNT_QUERIES.items():
        counts[key] = await _count(key, spec)
    return {"counts": counts, "generated_at": _now()}


class MarkSeenRequest(BaseModel):
    module: str


# ====================================================================
# PHASE 3 — WhatsApp Business API (Meta / Facebook Business Portfolio)
# Sends approved TEMPLATE messages via Meta Graph API /v{version}/{phone-number-id}/messages
# Credentials configured globally by super-admin in /admin/settings.
# ====================================================================
WA_GRAPH_VERSION = "v21.0"  # Meta Graph API version (update as Meta ships new)


async def _wa_send_template(to_e164: str, template_name: str, language_code: str = "fr", components: Optional[list] = None) -> dict:
    """Send a WhatsApp template message. Returns {ok, status, message_id, error, raw}."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    phone_number_id = s.get("wa_phone_number_id")
    if not access_token or not phone_number_id:
        return {"ok": False, "error": "WhatsApp non configuré (token ou phone_number_id manquant)", "status": None, "message_id": None, "raw": None}
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{phone_number_id}/messages"
    body = {
        "messaging_product": "whatsapp",
        "to": to_e164.lstrip("+").replace(" ", "").replace("-", ""),
        "type": "template",
        "template": {"name": template_name, "language": {"code": language_code}},
    }
    if components:
        body["template"]["components"] = components
    try:
        async with httpx.AsyncClient(timeout=12) as http:
            r = await http.post(url, json=body, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:2000]}
            if r.status_code >= 300:
                # Log payload + Meta response for ops debugging — masking the token
                logger.warning(
                    "[wa-send] FAIL template=%s lang=%s status=%s body=%s meta_response=%s",
                    template_name, language_code, r.status_code,
                    json.dumps(body)[:1500], json.dumps(raw)[:1500],
                )
            if r.status_code < 300:
                mid = None
                if isinstance(raw, dict) and raw.get("messages"):
                    mid = raw["messages"][0].get("id")
                return {"ok": True, "status": r.status_code, "message_id": mid, "error": None, "raw": raw}
            err_msg = None
            err_details = None
            err_code = None
            if isinstance(raw, dict):
                err_obj = raw.get("error") or {}
                err_msg = err_obj.get("message") or str(raw)[:500]
                err_code = err_obj.get("code")
                err_details = (err_obj.get("error_data") or {}).get("details")
                # Meta nests the most actionable explanation in error_data.details
                if err_details:
                    err_msg = f"{err_msg} — {err_details}"
            return {"ok": False, "status": r.status_code, "message_id": None, "error": err_msg or f"HTTP {r.status_code}", "error_code": err_code, "error_details": err_details, "raw": raw}
    except httpx.TimeoutException:
        return {"ok": False, "status": None, "message_id": None, "error": "Timeout", "raw": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "message_id": None, "error": str(exc)[:500], "raw": None}


# ---------- Dynamic-variable templating for WhatsApp templates ----------
# Each entry in `variables` is a free-text string that may contain tokens
# like {{full_name}}, {{company}}, {{phone}}, {{email}}, {{client_code}},
# {{today}}, {{tomorrow}}. At send time they are resolved against the
# recipient's profile. Positional → mapped to body parameters {{1}} {{2}}…
SUPPORTED_VAR_TOKENS = {"full_name", "company", "phone", "email", "client_code", "today", "tomorrow"}

_VAR_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _render_variable(value: str, ctx: Dict[str, str]) -> str:
    """Replace {{token}} occurrences in `value` using ctx. Unknown tokens are left blank."""
    if not value:
        return ""

    def _repl(m):
        key = m.group(1).lower()
        if key in ctx:
            return ctx[key] or ""
        return ""  # unknown token → blank to avoid sending literal "{{x}}"

    return _VAR_TOKEN_RE.sub(_repl, value)


def _build_recipient_ctx(kind: str, user_doc: Optional[dict], phone: str, label: Optional[str]) -> Dict[str, str]:
    """Build a substitution context dict from a resolved user/tracked-user doc."""
    u = user_doc or {}
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)
    return {
        "full_name": (u.get("full_name") or u.get("name") or label or "").strip(),
        "company": (u.get("company") or "").strip(),
        "phone": phone or (u.get("phone") or "").strip(),
        "email": (u.get("email") or "").strip(),
        "client_code": (u.get("client_code") or "").strip(),
        "today": today.strftime("%d/%m/%Y"),
        "tomorrow": tomorrow.strftime("%d/%m/%Y"),
    }


def _build_components(
    variables: Optional[List[str]],
    ctx: Dict[str, str],
    *,
    header_text: Optional[str] = None,
    header_media: Optional[Dict[str, Any]] = None,
    button_vars: Optional[List[List[str]]] = None,
) -> Optional[list]:
    """Build Meta template `components` array from positional variables and optional
    HEADER (text or media link) + URL-button parameters.
    Returns None when nothing to send."""
    components: list = []
    # HEADER
    if header_text:
        components.append({
            "type": "header",
            "parameters": [{"type": "text", "text": _render_variable(header_text, ctx)}],
        })
    elif header_media and header_media.get("link"):
        kind = (header_media.get("kind") or "document").lower()
        link = header_media["link"]
        if kind == "image":
            components.append({"type": "header", "parameters": [{"type": "image", "image": {"link": link}}]})
        elif kind == "video":
            components.append({"type": "header", "parameters": [{"type": "video", "video": {"link": link}}]})
        else:
            components.append({"type": "header", "parameters": [{"type": "document", "document": {"link": link, "filename": header_media.get("filename") or "document.pdf"}}]})
    # BODY
    if variables:
        params = [{"type": "text", "text": _render_variable(v, ctx)} for v in variables]
        components.append({"type": "body", "parameters": params})
    # BUTTONS (URL with {{N}})
    if button_vars:
        for index, params in enumerate(button_vars):
            if not params:
                continue
            components.append({
                "type": "button",
                "sub_type": "url",
                "index": str(index),
                "parameters": [{"type": "text", "text": _render_variable(p, ctx)} for p in params],
            })
    return components or None


# ----- Directory of contacts (per client) -----
class ContactCreate(BaseModel):
    name: str
    phone: Optional[str] = ""
    whatsapp: Optional[str] = ""
    email: Optional[str] = ""
    company: Optional[str] = ""
    notes: Optional[str] = ""
    tags: Optional[List[str]] = []
    shared: bool = False


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    shared: Optional[bool] = None


@api.get("/me/contacts", tags=["Portail Client"])
async def me_list_contacts(user: dict = Depends(get_current_user)):
    """List contacts: owned by me + shared within my client scope."""
    client_scope = (user.get("client_id") or user.get("id"))
    query = {"$or": [
        {"client_id": client_scope, "owner_id": user["id"]},
        {"client_id": client_scope, "shared": True},
    ]}
    items = await db.directory_contacts.find(query, {"_id": 0}).sort("name", 1).to_list(2000)
    return items


@api.post("/me/contacts", tags=["Portail Client"])
async def me_create_contact(payload: ContactCreate, user: dict = Depends(get_current_user)):
    client_scope = (user.get("client_id") or user.get("id"))
    doc = {
        "id": _uuid(),
        "client_id": client_scope,
        "owner_id": user["id"],
        "owner_label": user.get("full_name") or user.get("email"),
        **payload.model_dump(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.directory_contacts.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/me/contacts/{cid}", tags=["Portail Client"])
async def me_update_contact(cid: str, payload: ContactUpdate, user: dict = Depends(get_current_user)):
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    if existing.get("owner_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Modification non autorisée")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await db.directory_contacts.update_one({"id": cid}, {"$set": update})
    return {"ok": True}


@api.delete("/me/contacts/{cid}", tags=["Portail Client"])
async def me_delete_contact(cid: str, user: dict = Depends(get_current_user)):
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if existing and existing.get("owner_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Suppression non autorisée")
    await db.directory_contacts.delete_one({"id": cid})
    return {"ok": True}


# ----- Send WhatsApp from portal -----
class WhatsAppSendRequest(BaseModel):
    to: str  # E.164 phone number (contact's whatsapp field, or tracked-user's phone)
    template_name: str
    language_code: Optional[str] = "fr"
    components: Optional[list] = None  # Template variables (body, header, button params)
    contact_id: Optional[str] = None
    tracked_user_id: Optional[str] = None


@api.post("/me/whatsapp/send", tags=["Portail Client"])
async def me_whatsapp_send(payload: WhatsAppSendRequest, user: dict = Depends(get_current_user)):
    # RBAC: elevated roles (Moderator/Admin/Superviseur) + the main client account + tracked users (any role)
    allowed = (
        user.get("role") in ("client", "admin")
        or _is_elevated_creator(user)
        or _is_tracked_user(user)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des messages WhatsApp")
    to = (payload.to or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Numéro destinataire requis")
    result = await _wa_send_template(to, payload.template_name, payload.language_code or "fr", payload.components)
    # Log the attempt
    client_scope = (user.get("client_id") or user.get("id"))
    digits_only = "".join(ch for ch in to if ch.isdigit())
    log = {
        "id": _uuid(),
        "client_id": client_scope,
        "direction": "outbound",
        "sender_id": user["id"],
        "sender_label": user.get("full_name") or user.get("email"),
        "to": to,
        "phone_digits": digits_only,
        "template_name": payload.template_name,
        "language_code": payload.language_code,
        "contact_id": payload.contact_id,
        "tracked_user_id": payload.tracked_user_id,
        "ok": result["ok"],
        "status": result["status"],
        "message_id": result["message_id"],
        "error": result.get("error"),
        "wa_status": "sent" if result["ok"] else "failed",
        "sent_at": _now() if result["ok"] else None,
        "failed_at": None if result["ok"] else _now(),
        "created_at": _now(),
    }
    try: await db.whatsapp_messages.insert_one(log.copy())
    except Exception: pass
    log.pop("_id", None)
    return {"ok": result["ok"], "message_id": result["message_id"], "error": result.get("error"), "http_status": result["status"]}


@api.get("/me/whatsapp/history", tags=["Portail Client"])
async def me_whatsapp_history(limit: int = 100, user: dict = Depends(get_current_user)):
    client_scope = (user.get("client_id") or user.get("id"))
    query = {"client_id": client_scope} if user.get("role") != "admin" else {}
    items = await db.whatsapp_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    return items


@api.get("/me/whatsapp/templates", tags=["Portail Client"])
async def me_list_wa_templates(user: dict = Depends(get_current_user)):
    """Portal users: list APPROVED templates + only those marked as available.
    Attaches the admin-maintained description note."""
    if user.get("role") not in ("client", "admin") and not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    waba_id = s.get("wa_business_account_id")
    if not access_token or not waba_id:
        return {"configured": False, "items": []}
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates?limit=100"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(url, headers={"Authorization": f"Bearer {access_token}"})
            if r.status_code >= 300:
                return {"configured": True, "items": [], "error": f"HTTP {r.status_code}"}
            d = r.json()
            notes_map = await _load_template_notes_map()
            approved = []
            for t in (d.get("data") or []):
                if (t.get("status") or "").upper() != "APPROVED":
                    continue
                note = notes_map.get(t["name"]) or {}
                # Hide if explicitly marked unavailable to users (default = available)
                if note.get("is_available_for_users") is False:
                    continue
                t["note_description"] = note.get("description") or ""
                approved.append(t)
            return {"configured": True, "items": approved}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "items": [], "error": str(exc)[:200]}


@api.get("/me/contacts/{cid}/messages", tags=["Portail Client"])
async def me_contact_messages(cid: str, user: dict = Depends(get_current_user)):
    """Return the full WhatsApp conversation for a contact of the directory.
    Includes outbound messages (sent via /me/whatsapp/send), inbound messages
    captured by the Meta webhook, and the status-update timeline
    (sent/delivered/read/failed) with timestamps."""
    client_scope = (user.get("client_id") or user.get("id"))
    contact = await db.directory_contacts.find_one({"id": cid, "client_id": client_scope}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    # Match by contact_id OR by exact phone number (covers inbound messages from unknown senders)
    norm_phones = []
    for raw in (contact.get("whatsapp") or "", contact.get("phone") or ""):
        clean = "".join(ch for ch in (raw or "") if ch.isdigit())
        if clean:
            norm_phones.append(clean)
    or_clauses = [{"contact_id": cid}]
    if norm_phones:
        or_clauses.append({"phone_digits": {"$in": norm_phones}})
    items = await db.whatsapp_messages.find(
        {"client_id": client_scope, "$or": or_clauses},
        {"_id": 0},
    ).sort("created_at", 1).to_list(1000)
    return {"contact": contact, "messages": items}


# ---------- Meta Cloud API webhook ----------
@api.get("/whatsapp/webhook", tags=["Webhook"])
async def whatsapp_webhook_verify(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Meta verifies the webhook via GET with hub.mode=subscribe, hub.verify_token, hub.challenge.
    We must echo hub.challenge as plain text when the verify token matches."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    expected = s.get("wa_verify_token") or ""
    if not expected:
        raise HTTPException(status_code=400, detail="Verify token non configuré")
    if hub_mode == "subscribe" and hub_verify_token == expected and hub_challenge:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Invalid verify token")


@api.post("/whatsapp/webhook", tags=["Webhook"])
async def whatsapp_webhook_incoming(request: Request):
    """Receive Meta Cloud API events: new inbound messages + outbound status updates.
    Shape: {object:'whatsapp_business_account', entry:[{changes:[{value:{...}}]}]}"""
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}  # malformed → don't let Meta retry

    client_scope = None  # our app uses per-install WABA, so scope = primary client/superviseur
    try:
        primary = await db.users.find_one({"role": "superviseur"}, {"_id": 0, "id": 1})
        client_scope = (primary or {}).get("id")
    except Exception:
        pass

    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            val = change.get("value") or {}
            # --- Inbound messages ---
            for msg in val.get("messages") or []:
                try:
                    from_num = msg.get("from") or ""
                    digits_only = "".join(ch for ch in from_num if ch.isdigit())
                    mtype = msg.get("type") or "text"
                    text_body = None
                    if mtype == "text":
                        text_body = (msg.get("text") or {}).get("body")
                    elif mtype in ("image", "document", "audio", "video", "sticker"):
                        text_body = f"[{mtype} reçu]"
                    elif mtype == "button":
                        text_body = (msg.get("button") or {}).get("text")
                    elif mtype == "interactive":
                        interactive = msg.get("interactive") or {}
                        text_body = (interactive.get("button_reply") or interactive.get("list_reply") or {}).get("title")
                    ts_raw = int(msg.get("timestamp") or 0)
                    ts_iso = datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat() if ts_raw else _now()
                    # Find contact by phone within the scope
                    contact = await db.directory_contacts.find_one(
                        {"$or": [{"whatsapp": {"$regex": digits_only}}, {"phone": {"$regex": digits_only}}]},
                        {"_id": 0, "id": 1, "client_id": 1, "name": 1},
                    ) if digits_only else None
                    scope_for_msg = (contact or {}).get("client_id") or client_scope
                    doc = {
                        "id": _uuid(),
                        "client_id": scope_for_msg,
                        "direction": "inbound",
                        "contact_id": (contact or {}).get("id"),
                        "contact_name": (contact or {}).get("name"),
                        "from": from_num,
                        "phone_digits": digits_only,
                        "body": text_body,
                        "message_type": mtype,
                        "wa_message_id": msg.get("id"),
                        "received_at": ts_iso,
                        "created_at": _now(),
                        "read_by_us_at": None,
                    }
                    await db.whatsapp_messages.insert_one(doc)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("WA inbound parse failed: %s", exc)
            # --- Status updates for outbound ---
            for st in val.get("statuses") or []:
                try:
                    mid = st.get("id")
                    status_val = st.get("status") or ""  # sent | delivered | read | failed
                    ts_raw = int(st.get("timestamp") or 0)
                    ts_iso = datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat() if ts_raw else _now()
                    if not mid:
                        continue
                    stamp_field = {
                        "sent": "sent_at",
                        "delivered": "delivered_at",
                        "read": "read_at",
                        "failed": "failed_at",
                    }.get(status_val)
                    update: Dict[str, Any] = {
                        "wa_status": status_val,
                        "wa_status_updated_at": _now(),
                    }
                    if stamp_field:
                        update[stamp_field] = ts_iso
                    if status_val == "failed":
                        errs = st.get("errors") or []
                        if errs:
                            update["wa_error_code"] = errs[0].get("code")
                            update["wa_error_message"] = errs[0].get("message") or errs[0].get("title")
                    await db.whatsapp_messages.update_one({"message_id": mid}, {"$set": update})
                except Exception as exc:  # noqa: BLE001
                    logger.warning("WA status parse failed: %s", exc)
    return {"ok": True}


@api.get("/admin/whatsapp/templates", tags=["Admin"])
async def admin_list_wa_templates(_: dict = Depends(get_current_admin)):
    """List all templates from the configured WABA + merge admin notes (description + availability)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    waba_id = s.get("wa_business_account_id")
    if not access_token or not waba_id:
        return {"configured": False, "items": []}
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates?limit=100"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(url, headers={"Authorization": f"Bearer {access_token}"})
            if r.status_code >= 300:
                return {"configured": True, "items": [], "error": f"HTTP {r.status_code}"}
            d = r.json()
            notes_map = await _load_template_notes_map()
            items = []
            for t in (d.get("data") or []):
                note = notes_map.get(t["name"]) or {}
                t["note_description"] = note.get("description") or ""
                # Default TRUE when not explicitly set
                t["is_available_for_users"] = note.get("is_available_for_users", True)
                items.append(t)
            return {"configured": True, "items": items}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "items": [], "error": str(exc)[:200]}


# ---------- Admin-managed template notes (index by name) ----------
async def _load_template_notes_map() -> Dict[str, Dict[str, Any]]:
    docs = await db.wa_template_notes.find({}, {"_id": 0}).to_list(1000)
    return {d["name"]: d for d in docs if d.get("name")}


@api.get("/admin/whatsapp/template-notes", tags=["Admin"])
async def admin_list_template_notes(_: dict = Depends(get_current_admin)):
    docs = await db.wa_template_notes.find({}, {"_id": 0}).sort("name", 1).to_list(1000)
    return docs


class WaTemplateNoteUpsert(BaseModel):
    description: Optional[str] = None
    is_available_for_users: Optional[bool] = None


@api.put("/admin/whatsapp/template-notes/{name}", tags=["Admin"])
async def admin_upsert_template_note(
    name: str, payload: WaTemplateNoteUpsert, _: dict = Depends(get_current_admin),
):
    name = (name or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Nom de template manquant")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    update["name"] = name
    await db.wa_template_notes.update_one({"name": name}, {"$set": update}, upsert=True)
    doc = await db.wa_template_notes.find_one({"name": name}, {"_id": 0})
    return doc


@api.delete("/admin/whatsapp/template-notes/{name}", tags=["Admin"])
async def admin_delete_template_note(name: str, _: dict = Depends(get_current_admin)):
    await db.wa_template_notes.delete_one({"name": (name or "").strip().lower()})
    return {"ok": True}


# ---------- Templates: create / delete (Meta submission flow) ----------
WA_TEMPLATE_CATEGORIES = {"UTILITY", "MARKETING", "AUTHENTICATION"}
_TEMPLATE_NAME_RE = re.compile(r"^[a-z0-9_]{2,512}$")


class WaTemplateCreate(BaseModel):
    name: str
    language: str = "fr"
    category: str = "UTILITY"
    body_text: str  # Required by Meta. May contain {{1}}, {{2}}…
    body_examples: Optional[List[str]] = None  # Required when body has variables, len must match max({{N}})
    header_text: Optional[str] = None  # Optional plain-text header
    footer_text: Optional[str] = None  # Optional footer (max 60 chars per Meta)


def _count_body_vars(body: str) -> int:
    matches = [int(m.group(1)) for m in re.finditer(r"\{\{\s*(\d+)\s*\}\}", body or "")]
    return max(matches) if matches else 0


@api.post("/admin/whatsapp/templates", tags=["Admin"])
async def admin_create_wa_template(payload: WaTemplateCreate, _: dict = Depends(get_current_admin)):
    """Submit a new template to Meta for approval.
    Per Meta: name must be lowercase letters/digits/underscores, body is mandatory,
    {{1}}…{{N}} placeholders need example values."""
    name = (payload.name or "").strip().lower()
    if not _TEMPLATE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Nom invalide : minuscules, chiffres et _ uniquement (2-512 caractères)")
    category = (payload.category or "UTILITY").upper()
    if category not in WA_TEMPLATE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Catégorie invalide. Valeurs : {sorted(WA_TEMPLATE_CATEGORIES)}")
    body = (payload.body_text or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Le corps du template est requis")
    if len(body) > 1024:
        raise HTTPException(status_code=400, detail="Corps trop long (1024 caractères max)")
    n_vars = _count_body_vars(body)
    examples = payload.body_examples or []
    if n_vars > 0 and len(examples) < n_vars:
        raise HTTPException(status_code=400, detail=f"Exemples manquants : {n_vars} variable(s) détectée(s), {len(examples)} fournie(s)")
    if payload.header_text and len(payload.header_text.strip()) > 60:
        raise HTTPException(status_code=400, detail="Header trop long (60 caractères max)")
    if payload.footer_text and len(payload.footer_text.strip()) > 60:
        raise HTTPException(status_code=400, detail="Footer trop long (60 caractères max)")

    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    waba_id = s.get("wa_business_account_id")
    if not access_token or not waba_id:
        raise HTTPException(status_code=400, detail="WhatsApp non configuré (renseignez WABA ID et Access Token dans Paramètres)")

    components: List[Dict[str, Any]] = []
    if payload.header_text:
        components.append({"type": "HEADER", "format": "TEXT", "text": payload.header_text.strip()})
    body_comp: Dict[str, Any] = {"type": "BODY", "text": body}
    if n_vars > 0:
        body_comp["example"] = {"body_text": [examples[:n_vars]]}
    components.append(body_comp)
    if payload.footer_text:
        components.append({"type": "FOOTER", "text": payload.footer_text.strip()})

    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates"
    body_payload = {
        "name": name,
        "language": payload.language or "fr",
        "category": category,
        "components": components,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                url,
                json=body_payload,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            )
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:2000]}
            if r.status_code >= 300:
                err = (raw.get("error") or {}).get("message") if isinstance(raw, dict) else None
                # Never forward Meta 401/403 verbatim — the client axios interceptor
                # would log the admin out. Return 502 (Bad Gateway) so we surface
                # the Meta error without affecting our own auth session.
                raise HTTPException(status_code=502, detail=f"Meta API {r.status_code}: {err or f'Échec HTTP {r.status_code}'}")
            return {
                "ok": True,
                "name": name,
                "language": body_payload["language"],
                "category": category,
                "id": raw.get("id"),
                "status": raw.get("status") or "PENDING",
                "raw": raw,
            }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout Meta")


@api.delete("/admin/whatsapp/templates/{name}", tags=["Admin"])
async def admin_delete_wa_template(name: str, _: dict = Depends(get_current_admin)):
    """Delete a template by name (deletes ALL languages of this name on the WABA)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    waba_id = s.get("wa_business_account_id")
    if not access_token or not waba_id:
        raise HTTPException(status_code=400, detail="WhatsApp non configuré")
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.delete(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"name": name},
            )
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:1000]}
            if r.status_code >= 300:
                err = (raw.get("error") or {}).get("message") if isinstance(raw, dict) else None
                raise HTTPException(status_code=502, detail=f"Meta API {r.status_code}: {err or f'Échec HTTP {r.status_code}'}")
            return {"ok": True, "name": name, "raw": raw}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout Meta")


# ---------- Config validator ----------
@api.post("/admin/whatsapp/test-config", tags=["Admin"])
async def admin_test_wa_config(_: dict = Depends(get_current_admin)):
    """Validate Meta credentials by probing Graph API for WABA + phone number.
    Returns {ok, checks:[{key,label,ok,detail}], summary}."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token") or ""
    waba_id = s.get("wa_business_account_id") or ""
    phone_id = s.get("wa_phone_number_id") or ""
    app_id = s.get("wa_app_id") or ""

    checks: List[Dict[str, Any]] = []
    def add(key, label, ok, detail):
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": detail})

    # 1) Required fields
    add("access_token", "Access Token renseigné", bool(access_token), "Token présent" if access_token else "Manquant")
    add("waba_id", "WABA ID renseigné", bool(waba_id), waba_id or "Manquant")
    add("phone_id", "Phone Number ID renseigné", bool(phone_id), phone_id or "Manquant")
    add("app_id", "App ID renseigné (optionnel)", bool(app_id), app_id or "Non fourni (facultatif)")

    if not access_token or not waba_id or not phone_id:
        return {"ok": False, "checks": checks, "summary": "Informations requises manquantes — impossible de contacter Meta."}

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            # 2) WABA lookup
            r1 = await http.get(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}",
                params={"fields": "id,name,message_template_namespace"},
                headers=headers,
            )
            try:
                d1 = r1.json()
            except Exception:
                d1 = {"text": r1.text[:500]}
            if r1.status_code < 300:
                name = d1.get("name") or "(sans nom)"
                add("waba_check", "WABA accessible", True, f"{name} (id={d1.get('id')})")
            else:
                err = (d1.get("error") or {}).get("message") if isinstance(d1, dict) else None
                add("waba_check", "WABA accessible", False, f"HTTP {r1.status_code} — {err or 'erreur Meta'}")

            # 3) Phone Number lookup
            r2 = await http.get(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{phone_id}",
                params={"fields": "display_phone_number,verified_name,quality_rating,code_verification_status"},
                headers=headers,
            )
            try:
                d2 = r2.json()
            except Exception:
                d2 = {"text": r2.text[:500]}
            if r2.status_code < 300:
                display = d2.get("display_phone_number") or "?"
                verified = d2.get("verified_name") or "?"
                quality = d2.get("quality_rating") or "?"
                add("phone_check", "Numéro WhatsApp Business validé", True, f"{display} — {verified} — Qualité {quality}")
            else:
                err = (d2.get("error") or {}).get("message") if isinstance(d2, dict) else None
                add("phone_check", "Numéro WhatsApp Business validé", False, f"HTTP {r2.status_code} — {err or 'erreur Meta'}")

            # 4) Templates fetch probe
            r3 = await http.get(
                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba_id}/message_templates",
                params={"limit": 1},
                headers=headers,
            )
            if r3.status_code < 300:
                try:
                    total = len((r3.json() or {}).get("data") or [])
                except Exception:
                    total = 0
                add("templates_check", "Lecture des templates", True, f"Réponse Meta OK ({total} template(s) trouvé(s) dans la 1ère page)")
            else:
                try:
                    d3 = r3.json()
                    err = (d3.get("error") or {}).get("message") if isinstance(d3, dict) else None
                except Exception:
                    err = None
                add("templates_check", "Lecture des templates", False, f"HTTP {r3.status_code} — {err or 'erreur Meta'}")
    except httpx.TimeoutException:
        add("network", "Connexion Meta Graph API", False, "Timeout 10s — vérifiez la connectivité sortante du serveur")
    except Exception as exc:  # noqa: BLE001
        add("network", "Connexion Meta Graph API", False, f"Erreur : {str(exc)[:200]}")

    ok = all(c["ok"] for c in checks if c["key"] not in ("app_id",))  # app_id is optional
    summary = "Tous les paramètres sont valides — prêt à envoyer." if ok else "Un ou plusieurs paramètres sont invalides. Voir détail."
    return {"ok": ok, "checks": checks, "summary": summary}


# ====================================================================
# ADMIN — Messagerie WhatsApp groupée (clients + tracked users)
# ====================================================================
@api.get("/admin/messaging/audience", tags=["Admin"])
async def admin_messaging_audience(_: dict = Depends(get_current_admin)):
    """Return all contactable recipients (clients with phone/whatsapp + tracked users with phone)."""
    users = await db.users.find(
        {"role": {"$in": ["client", "superviseur"]}},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1, "company": 1,
         "phone": 1, "account_status": 1, "client_code": 1, "country": 1, "city": 1},
    ).to_list(3000)
    tracked = await db.tracked_users.find(
        {}, {"_id": 0, "id": 1, "name": 1, "full_name": 1, "email": 1, "phone": 1,
             "client_id": 1, "role": 1, "status": 1},
    ).to_list(5000)
    # Build client lookup for tracked-users labels
    client_map = {u["id"]: (u.get("company") or u.get("full_name") or u.get("email")) for u in users}

    clients_rows = []
    for u in users:
        phone = (u.get("phone") or "").strip()
        clients_rows.append({
            "kind": "client",
            "id": u["id"],
            "full_name": u.get("full_name") or "—",
            "email": u.get("email"),
            "company": u.get("company") or "",
            "phone": phone,
            "client_code": u.get("client_code"),
            "country": u.get("country"),
            "city": u.get("city"),
            "account_status": u.get("account_status"),
            "has_phone": bool(phone),
        })

    tracked_rows = []
    for t in tracked:
        phone = (t.get("phone") or "").strip()
        tracked_rows.append({
            "kind": "tracked",
            "id": t["id"],
            "full_name": t.get("full_name") or t.get("name") or "—",
            "email": t.get("email"),
            "client_id": t.get("client_id"),
            "client_label": client_map.get(t.get("client_id") or "") or "—",
            "phone": phone,
            "role": t.get("role"),
            "status": t.get("status"),
            "has_phone": bool(phone),
        })
    return {"clients": clients_rows, "tracked_users": tracked_rows}


class AdminBulkSendRequest(BaseModel):
    recipients: List[Dict[str, Any]]  # [{kind:'client'|'tracked'|'raw', id?, phone?}]
    template_name: str
    language_code: Optional[str] = "fr"
    components: Optional[list] = None
    variables: Optional[List[str]] = None  # Positional body-variable recipes with {{token}} tokens
    header_text: Optional[str] = None  # Optional header TEXT variable (with token substitution)
    header_media: Optional[Dict[str, Any]] = None  # {link, kind, filename?} for header IMAGE/DOC/VIDEO
    button_vars: Optional[List[List[str]]] = None  # [[urlVar1,...], ...] indexed by button position


@api.post("/admin/messaging/bulk-send", tags=["Admin"])
async def admin_messaging_bulk_send(
    payload: AdminBulkSendRequest,
    admin_user: dict = Depends(get_current_admin),
):
    """Send the same WhatsApp template to a list of recipients. Returns a per-recipient result."""
    if not payload.recipients:
        raise HTTPException(status_code=400, detail="Aucun destinataire")
    if not payload.template_name:
        raise HTTPException(status_code=400, detail="Template requis")

    # Resolve each recipient into an E.164 phone + user doc for variable context
    resolved = []
    for r in payload.recipients:
        kind = (r.get("kind") or "").lower()
        rid = r.get("id")
        phone = (r.get("phone") or "").strip()
        label = r.get("label")
        user_doc: Optional[dict] = None
        if kind == "client" and rid:
            u = await db.users.find_one({"id": rid}, {"_id": 0, "phone": 1, "full_name": 1, "email": 1, "company": 1, "client_code": 1})
            if u:
                user_doc = u
                if not phone:
                    phone = (u.get("phone") or "").strip()
                label = label or u.get("company") or u.get("full_name") or u.get("email")
        elif kind == "tracked" and rid:
            t = await db.tracked_users.find_one({"id": rid}, {"_id": 0, "phone": 1, "name": 1, "full_name": 1, "email": 1, "client_id": 1})
            if t:
                user_doc = t
                if not phone:
                    phone = (t.get("phone") or "").strip()
                label = label or t.get("full_name") or t.get("name") or t.get("email")
        resolved.append({"kind": kind or "raw", "id": rid, "phone": phone, "label": label or phone or "—", "user_doc": user_doc})

    # Validate phones (basic)
    to_send = [x for x in resolved if x["phone"]]
    skipped = [x for x in resolved if not x["phone"]]

    # Send sequentially to avoid burst rate-limits (Meta Cloud ~80 msg/s max)
    results = []
    for x in to_send:
        # Build per-recipient components from either the static `components` or dynamic `variables`/header/buttons
        if payload.variables or payload.header_text or payload.header_media or payload.button_vars:
            ctx = _build_recipient_ctx(x["kind"], x["user_doc"], x["phone"], x["label"])
            components = _build_components(
                payload.variables, ctx,
                header_text=payload.header_text,
                header_media=payload.header_media,
                button_vars=payload.button_vars,
            )
        else:
            components = payload.components
        try:
            r = await _wa_send_template(x["phone"], payload.template_name, payload.language_code or "fr", components)
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "status": 0, "message_id": None, "error": str(exc)[:200]}
        log = {
            "id": _uuid(),
            "client_id": x.get("id") if x.get("kind") == "client" else None,
            "sender_id": admin_user["id"],
            "sender_label": admin_user.get("full_name") or admin_user.get("email"),
            "to": x["phone"],
            "template_name": payload.template_name,
            "language_code": payload.language_code,
            "contact_id": None,
            "tracked_user_id": x.get("id") if x.get("kind") == "tracked" else None,
            "recipient_kind": x.get("kind"),
            "recipient_label": x.get("label"),
            "bulk": True,
            "ok": r["ok"],
            "status": r["status"],
            "message_id": r["message_id"],
            "error": r.get("error"),
            "created_at": _now(),
        }
        try:
            await db.whatsapp_messages.insert_one(log.copy())
        except Exception:
            pass
        results.append({
            "label": x["label"],
            "phone": x["phone"],
            "kind": x["kind"],
            "ok": r["ok"],
            "status": r["status"],
            "message_id": r["message_id"],
            "error": r.get("error"),
        })

    sent_ok = sum(1 for r in results if r["ok"])
    return {
        "requested": len(payload.recipients),
        "sent_ok": sent_ok,
        "sent_ko": len(results) - sent_ok,
        "skipped": [{"label": s["label"], "reason": "Pas de numéro de téléphone"} for s in skipped],
        "results": results,
    }


@api.get("/admin/messaging/history", tags=["Admin"])
async def admin_messaging_history(
    limit: int = 200,
    _: dict = Depends(get_current_admin),
):
    items = await db.whatsapp_messages.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 1000))
    return items


@api.get("/admin/messaging/variable-tokens", tags=["Admin"])
async def admin_messaging_variable_tokens(_: dict = Depends(get_current_admin)):
    """List of substitution tokens the admin can insert into template variables.
    Resolved per-recipient at send time from the client or tracked-user profile."""
    return _wa_variable_tokens()


@api.get("/me/messaging/variable-tokens", tags=["Portail Client"])
async def me_messaging_variable_tokens(user: dict = Depends(get_current_user)):
    """Portal mirror of variable tokens. Same resolution at send time."""
    if user.get("role") not in ("client", "admin") and not _is_elevated_creator(user) and not _is_tracked_user(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    return _wa_variable_tokens()


def _wa_variable_tokens() -> dict:
    return {
        "tokens": [
            {"token": "{{full_name}}", "label": "Nom complet", "example": "Jean Dupont"},
            {"token": "{{company}}", "label": "Société", "example": "Acme Corp"},
            {"token": "{{phone}}", "label": "Téléphone", "example": "+225 01 23 45 67"},
            {"token": "{{email}}", "label": "Email", "example": "client@example.com"},
            {"token": "{{client_code}}", "label": "Code client", "example": "ACME"},
            {"token": "{{today}}", "label": "Date du jour", "example": datetime.now(timezone.utc).strftime("%d/%m/%Y")},
            {"token": "{{tomorrow}}", "label": "Date de demain", "example": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d/%m/%Y")},
        ]
    }


# ====================================================================
# AUTOMATIONS — Triggered WhatsApp messages on system events
# Supported events: appointment.created, appointment.reminder,
#                   intervention.created, client.created
# Recipient strategy: 'event_target' → resolve phone from event payload
#                     (typically client_id → users.phone OR tracked_user)
# ====================================================================
SUPPORTED_AUTOMATION_EVENTS = {
    "appointment.created",
    "appointment.reminder",
    "intervention.created",
    "client.created",
    "task.reminder",
}


class AutomationCreate(BaseModel):
    title: str
    event: str
    template_name: str
    language_code: Optional[str] = "fr"
    variables: Optional[List[str]] = None
    delay_minutes: int = 0      # 0 = immédiat ; >0 = planifié
    target: str = "event_target"  # placeholder for future targets (e.g. fixed phone)
    target_phone: Optional[str] = None  # used when target='fixed'
    enabled: bool = True


class AutomationUpdate(BaseModel):
    title: Optional[str] = None
    template_name: Optional[str] = None
    language_code: Optional[str] = None
    variables: Optional[List[str]] = None
    delay_minutes: Optional[int] = None
    target: Optional[str] = None
    target_phone: Optional[str] = None
    enabled: Optional[bool] = None


@api.get("/admin/automations", tags=["Admin"])
async def admin_list_automations(_: dict = Depends(get_current_admin)):
    items = await db.automations.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


@api.get("/admin/automations/events", tags=["Admin"])
async def admin_automation_events(_: dict = Depends(get_current_admin)):
    return {
        "events": [
            {"value": "appointment.created", "label": "RDV créé",
             "description": "Confirmation immédiate envoyée au client après création d'un RDV."},
            {"value": "appointment.reminder", "label": "Rappel RDV (J-1)",
             "description": "Rappel automatique envoyé 24h avant l'heure du RDV (cron horaire)."},
            {"value": "intervention.created", "label": "Intervention créée",
             "description": "Notification au client lorsqu'une intervention est enregistrée."},
            {"value": "client.created", "label": "Nouveau client",
             "description": "Message de bienvenue à un client fraîchement créé."},
            {"value": "task.reminder", "label": "Rappel de tâche",
             "description": "Rappel WhatsApp envoyé 1h avant l'échéance d'une tâche client (cron horaire)."},
        ]
    }


@api.post("/admin/automations", tags=["Admin"])
async def admin_create_automation(payload: AutomationCreate, admin_user: dict = Depends(get_current_admin)):
    if payload.event not in SUPPORTED_AUTOMATION_EVENTS:
        raise HTTPException(status_code=400, detail=f"Événement non supporté. Valeurs : {sorted(SUPPORTED_AUTOMATION_EVENTS)}")
    if not payload.template_name.strip():
        raise HTTPException(status_code=400, detail="Template requis")
    if (payload.delay_minutes or 0) < 0:
        raise HTTPException(status_code=400, detail="delay_minutes doit être ≥ 0")
    if payload.target == "fixed" and not (payload.target_phone or "").strip():
        raise HTTPException(status_code=400, detail="target_phone requis quand target='fixed'")
    doc = {
        "id": _uuid(),
        **payload.model_dump(),
        "created_by_id": admin_user["id"],
        "created_by_label": admin_user.get("full_name") or admin_user.get("email"),
        "created_at": _now(),
        "updated_at": _now(),
        "trigger_count": 0,
    }
    await db.automations.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/automations/{aid}", tags=["Admin"])
async def admin_update_automation(aid: str, payload: AutomationUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    res = await db.automations.update_one({"id": aid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Automation introuvable")
    refreshed = await db.automations.find_one({"id": aid}, {"_id": 0})
    return refreshed


@api.delete("/admin/automations/{aid}", tags=["Admin"])
async def admin_delete_automation(aid: str, _: dict = Depends(get_current_admin)):
    res = await db.automations.delete_one({"id": aid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Automation introuvable")
    return {"ok": True}


async def _emit_event(event: str, target: dict) -> None:
    """Fire-and-forget : exécute toutes les automations actives pour cet event.

    target dict supports the following keys (best-effort; missing → blank in templates):
      - client_id: str  → resolves via db.users (provides full_name, company, phone, email, client_code)
      - tracked_user_id: str → resolves via db.tracked_users (provides full_name, phone, email)
      - phone: str (fallback if no id given)
      - extra_ctx: dict (additional substitution tokens, e.g. {"appointment_date": "..."})
    """
    if event not in SUPPORTED_AUTOMATION_EVENTS:
        return
    automations = await db.automations.find(
        {"event": event, "enabled": True}, {"_id": 0}
    ).to_list(50)
    if not automations:
        return

    # Resolve user_doc + phone once for the whole event
    user_doc: Optional[dict] = None
    phone = (target.get("phone") or "").strip()
    label: Optional[str] = None
    kind = "raw"
    rid: Optional[str] = None
    if target.get("client_id"):
        rid = target["client_id"]
        kind = "client"
        u = await db.users.find_one({"id": rid}, {"_id": 0, "phone": 1, "full_name": 1, "email": 1, "company": 1, "client_code": 1})
        if u:
            user_doc = u
            phone = phone or (u.get("phone") or "").strip()
            label = u.get("company") or u.get("full_name") or u.get("email")
    elif target.get("tracked_user_id"):
        rid = target["tracked_user_id"]
        kind = "tracked"
        t = await db.tracked_users.find_one({"id": rid}, {"_id": 0, "phone": 1, "name": 1, "full_name": 1, "email": 1})
        if t:
            user_doc = t
            phone = phone or (t.get("phone") or "").strip()
            label = t.get("full_name") or t.get("name") or t.get("email")
    label = label or phone or "—"

    for au in automations:
        # Choose recipient
        if (au.get("target") or "event_target") == "fixed":
            to_phone = (au.get("target_phone") or "").strip()
            ctx_phone = to_phone
            ctx_label = to_phone or "Fixed"
            ctx_user_doc = None
            ctx_kind = "raw"
            ctx_rid = None
        else:
            to_phone = phone
            ctx_phone = phone
            ctx_label = label
            ctx_user_doc = user_doc
            ctx_kind = kind
            ctx_rid = rid

        if not to_phone:
            # Skipped silently (cannot send) but still log a tracking row
            try:
                await db.whatsapp_messages.insert_one({
                    "id": _uuid(),
                    "client_id": ctx_rid if ctx_kind == "client" else None,
                    "tracked_user_id": ctx_rid if ctx_kind == "tracked" else None,
                    "to": "",
                    "template_name": au["template_name"],
                    "language_code": au.get("language_code"),
                    "recipient_kind": ctx_kind,
                    "recipient_label": ctx_label,
                    "automation_id": au["id"],
                    "automation_event": event,
                    "ok": False,
                    "status": None,
                    "message_id": None,
                    "error": "Pas de numéro de téléphone",
                    "created_at": _now(),
                })
            except Exception:
                pass
            continue

        # Build per-recipient ctx + components
        base_ctx = _build_recipient_ctx(ctx_kind, ctx_user_doc, ctx_phone, ctx_label)
        for k, v in (target.get("extra_ctx") or {}).items():
            base_ctx[k] = str(v) if v is not None else ""
        components = _build_components(au.get("variables"), base_ctx)
        delay = int(au.get("delay_minutes") or 0)

        if delay > 0:
            # Schedule for later — leverage the existing whatsapp_schedules pipeline
            sched_at = (datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat()
            await db.whatsapp_schedules.insert_one({
                "id": _uuid(),
                "title": f"Auto: {au.get('title') or au['template_name']}",
                "recipients": [{"kind": ctx_kind, "id": ctx_rid, "phone": to_phone, "label": ctx_label}],
                "template_name": au["template_name"],
                "language_code": au.get("language_code") or "fr",
                "components": None,
                "variables": au.get("variables"),
                "scheduled_at": sched_at,
                "status": "pending",
                "result_summary": None,
                "automation_id": au["id"],
                "automation_event": event,
                "extra_ctx": target.get("extra_ctx") or {},
                "created_by_id": "automation",
                "created_by_label": f"Automation: {au.get('title') or au['template_name']}",
                "created_at": _now(),
                "updated_at": _now(),
            })
        else:
            try:
                wr = await _wa_send_template(to_phone, au["template_name"], au.get("language_code") or "fr", components)
            except Exception as exc:  # noqa: BLE001
                wr = {"ok": False, "status": 0, "message_id": None, "error": str(exc)[:200]}
            try:
                await db.whatsapp_messages.insert_one({
                    "id": _uuid(),
                    "client_id": ctx_rid if ctx_kind == "client" else None,
                    "tracked_user_id": ctx_rid if ctx_kind == "tracked" else None,
                    "to": to_phone,
                    "template_name": au["template_name"],
                    "language_code": au.get("language_code"),
                    "recipient_kind": ctx_kind,
                    "recipient_label": ctx_label,
                    "automation_id": au["id"],
                    "automation_event": event,
                    "ok": wr["ok"],
                    "status": wr["status"],
                    "message_id": wr["message_id"],
                    "error": wr.get("error"),
                    "created_at": _now(),
                })
            except Exception:
                pass

        # Counter (fire-and-forget)
        try:
            await db.automations.update_one({"id": au["id"]}, {"$inc": {"trigger_count": 1}})
        except Exception:
            pass


async def _appointment_reminder_cron():
    """Hourly cron: find appointments scheduled in (now+23h, now+25h) window and emit reminders."""
    now_utc = datetime.now(timezone.utc)
    win_start = (now_utc + timedelta(hours=23)).isoformat()
    win_end = (now_utc + timedelta(hours=25)).isoformat()
    appts = await db.appointments.find(
        {"scheduled_at": {"$gte": win_start, "$lte": win_end},
         "status": {"$nin": ["cancelled", "rejected"]},
         "reminder_sent_at": {"$exists": False}},
        {"_id": 0, "id": 1, "client_id": 1, "scheduled_at": 1, "subject": 1, "phone": 1},
    ).to_list(200)
    for ap in appts:
        try:
            sched_dt = datetime.fromisoformat(ap["scheduled_at"].replace("Z", "+00:00"))
            sched_human = sched_dt.strftime("%d/%m/%Y à %Hh%M")
        except Exception:
            sched_human = ap.get("scheduled_at") or ""
        await _emit_event("appointment.reminder", {
            "client_id": ap.get("client_id"),
            "phone": ap.get("phone"),
            "extra_ctx": {
                "appointment_date": sched_human,
                "appointment_subject": ap.get("subject") or "",
            },
        })
        try:
            await db.appointments.update_one(
                {"id": ap["id"]},
                {"$set": {"reminder_sent_at": _now()}},
            )
        except Exception:
            pass


# ====================================================================
# ADMIN — Envois WhatsApp planifiés (scheduler minute-based)
# ====================================================================
class AdminScheduleCreate(BaseModel):
    title: Optional[str] = None
    recipients: List[Dict[str, Any]]
    template_name: str
    language_code: Optional[str] = "fr"
    components: Optional[list] = None
    variables: Optional[List[str]] = None  # Positional body-variable recipes
    header_text: Optional[str] = None
    header_media: Optional[Dict[str, Any]] = None
    button_vars: Optional[List[List[str]]] = None
    scheduled_at: str  # ISO-8601 UTC, e.g. "2026-05-10T14:30:00+00:00"


@api.get("/admin/messaging/schedules", tags=["Admin"])
async def admin_list_schedules(_: dict = Depends(get_current_admin)):
    items = await db.whatsapp_schedules.find({}, {"_id": 0}).sort("scheduled_at", -1).to_list(1000)
    return items


@api.post("/admin/messaging/schedules", tags=["Admin"])
async def admin_create_schedule(
    payload: AdminScheduleCreate,
    admin_user: dict = Depends(get_current_admin),
):
    if not payload.recipients:
        raise HTTPException(status_code=400, detail="Aucun destinataire")
    if not payload.template_name:
        raise HTTPException(status_code=400, detail="Template requis")
    # Parse + validate datetime
    try:
        sched = datetime.fromisoformat(payload.scheduled_at.replace("Z", "+00:00"))
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Date invalide (ISO-8601 attendu)")
    now_utc = datetime.now(timezone.utc)
    if sched <= now_utc - timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="La date planifiée doit être dans le futur")

    doc = {
        "id": _uuid(),
        "title": (payload.title or "").strip() or f"Envoi {payload.template_name}",
        "recipients": payload.recipients,
        "template_name": payload.template_name,
        "language_code": payload.language_code or "fr",
        "components": payload.components,
        "variables": payload.variables,
        "header_text": payload.header_text,
        "header_media": payload.header_media,
        "button_vars": payload.button_vars,
        "scheduled_at": sched.isoformat(),
        "status": "pending",
        "result_summary": None,
        "created_by_id": admin_user["id"],
        "created_by_label": admin_user.get("full_name") or admin_user.get("email"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.whatsapp_schedules.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.delete("/admin/messaging/schedules/{sid}", tags=["Admin"])
async def admin_delete_schedule(sid: str, _: dict = Depends(get_current_admin)):
    existing = await db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Planification introuvable")
    if existing.get("status") in ("running", "done"):
        # Don't hard-delete an active one — mark cancelled for audit
        await db.whatsapp_schedules.update_one(
            {"id": sid},
            {"$set": {"status": "cancelled", "updated_at": _now()}},
        )
        return {"ok": True, "status": "cancelled"}
    await db.whatsapp_schedules.delete_one({"id": sid})
    return {"ok": True, "status": "deleted"}


async def _run_scheduled_whatsapp():
    """Cron job (runs every minute) — execute any pending schedule whose scheduled_at <= now."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        due = await db.whatsapp_schedules.find(
            {"status": "pending", "scheduled_at": {"$lte": now_iso}},
            {"_id": 0},
        ).to_list(50)
        for sc in due:
            # Claim it (atomic update to running)
            claimed = await db.whatsapp_schedules.update_one(
                {"id": sc["id"], "status": "pending"},
                {"$set": {"status": "running", "started_at": _now(), "updated_at": _now()}},
            )
            if claimed.modified_count == 0:
                continue  # Someone else got it (defensive)

            # Resolve + send (same logic as bulk-send, simplified)
            results = []
            skipped = []
            variables = sc.get("variables") or []
            static_components = sc.get("components")
            for r in (sc.get("recipients") or []):
                kind = (r.get("kind") or "").lower()
                rid = r.get("id")
                phone = (r.get("phone") or "").strip()
                label = r.get("label")
                user_doc: Optional[dict] = None
                if kind == "client" and rid:
                    u = await db.users.find_one({"id": rid}, {"_id": 0, "phone": 1, "full_name": 1, "company": 1, "email": 1, "client_code": 1})
                    if u:
                        user_doc = u
                        if not phone:
                            phone = (u.get("phone") or "").strip()
                        label = label or u.get("company") or u.get("full_name") or u.get("email")
                elif kind == "tracked" and rid:
                    t = await db.tracked_users.find_one({"id": rid}, {"_id": 0, "phone": 1, "name": 1, "full_name": 1, "email": 1})
                    if t:
                        user_doc = t
                        if not phone:
                            phone = (t.get("phone") or "").strip()
                        label = label or t.get("full_name") or t.get("name") or t.get("email")
                label = label or phone or "—"
                if not phone:
                    skipped.append({"label": label, "reason": "Pas de numéro de téléphone"})
                    continue
                # Per-recipient dynamic components
                if variables or sc.get("header_text") or sc.get("header_media") or sc.get("button_vars"):
                    ctx = _build_recipient_ctx(kind, user_doc, phone, label)
                    components = _build_components(
                        variables, ctx,
                        header_text=sc.get("header_text"),
                        header_media=sc.get("header_media"),
                        button_vars=sc.get("button_vars"),
                    )
                else:
                    components = static_components
                try:
                    wr = await _wa_send_template(
                        phone, sc["template_name"], sc.get("language_code") or "fr", components,
                    )
                except Exception as exc:  # noqa: BLE001
                    wr = {"ok": False, "status": 0, "message_id": None, "error": str(exc)[:200]}
                log = {
                    "id": _uuid(),
                    "client_id": rid if kind == "client" else None,
                    "sender_id": sc.get("created_by_id"),
                    "sender_label": sc.get("created_by_label"),
                    "to": phone,
                    "template_name": sc["template_name"],
                    "language_code": sc.get("language_code"),
                    "tracked_user_id": rid if kind == "tracked" else None,
                    "recipient_kind": kind,
                    "recipient_label": label,
                    "bulk": True,
                    "scheduled": True,
                    "schedule_id": sc["id"],
                    "ok": wr["ok"],
                    "status": wr["status"],
                    "message_id": wr["message_id"],
                    "error": wr.get("error"),
                    "created_at": _now(),
                }
                try:
                    await db.whatsapp_messages.insert_one(log.copy())
                except Exception:
                    pass
                results.append({
                    "label": label, "phone": phone, "kind": kind,
                    "ok": wr["ok"], "status": wr["status"],
                    "message_id": wr["message_id"], "error": wr.get("error"),
                })
            sent_ok = sum(1 for x in results if x["ok"])
            final_status = "done" if sent_ok > 0 or not results else "failed"
            await db.whatsapp_schedules.update_one(
                {"id": sc["id"]},
                {"$set": {
                    "status": final_status,
                    "result_summary": {
                        "requested": len(sc.get("recipients") or []),
                        "sent_ok": sent_ok,
                        "sent_ko": len(results) - sent_ok,
                        "skipped_count": len(skipped),
                        "skipped": skipped,
                        "results": results,
                    },
                    "finished_at": _now(),
                    "updated_at": _now(),
                }},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduled_whatsapp runner failed: %s", exc)


# ====================================================================
# PHASE 4 — Dynamic Forms (Google Forms-like)
# Structure :
#   forms : {id, client_id, number, title, description, is_public, pages, created_by_id, created_by_label, created_at, updated_at, uses_count, revisions_count}
#     pages : [{id, title, fields:[{id, type, label, required, options?, placeholder?, col_start, col_span, row}]}]
#   form_submissions : {id, form_id, client_id, user_id, user_label, data, geo, created_at, updated_at, revisions_count}
# ====================================================================
FIELD_TYPES = {"text", "textarea", "number", "boolean", "select", "multiselect", "date", "datetime", "email", "tel", "url", "location"}


class FormField(BaseModel):
    id: str
    type: str
    label: str
    required: bool = False
    options: Optional[List[str]] = None
    placeholder: Optional[str] = None
    default_value: Optional[Any] = None
    # Position inside a 12-column responsive grid
    col_start: int = 1      # 1..12
    col_span: int = 12      # 1..12 (col_start + col_span <= 13)
    row: int = 0


class FormPage(BaseModel):
    id: str
    title: str = "Page"
    fields: List[FormField] = []


class FormCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    is_public: bool = False
    pages: Optional[List[FormPage]] = None


class FormUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    pages: Optional[List[FormPage]] = None


async def _next_form_number(client_code: str) -> int:
    res = await db.counters.find_one_and_update(
        {"_id": f"form_{client_code}"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=True,
    )
    return (res or {}).get("value", 1)


def _form_serialize(doc: dict) -> dict:
    if not doc:
        return doc
    doc.pop("_id", None)
    return doc


async def _require_owner_or_admin(form: dict, user: dict) -> None:
    if user.get("role") == "admin":
        return
    if form.get("client_id") != (user.get("client_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Formulaire non accessible")


@api.get("/me/forms", tags=["Formulaires"])
async def me_list_forms(user: dict = Depends(get_current_user)):
    """List forms: all of the user's client + all public forms from other clients."""
    client_scope = (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else None
    if user.get("role") == "admin":
        query = {}
    else:
        query = {"$or": [{"client_id": client_scope}, {"is_public": True}]}
    items = await db.forms.find(query, {"_id": 0, "pages": 0}).sort("created_at", -1).to_list(500)
    # Tag each form so the UI can distinguish mine vs public-imported
    for it in items:
        if user.get("role") == "admin":
            # Admin sees everything as "mine" (full edit/stats/share/delete rights)
            it["is_mine"] = True
        else:
            it["is_mine"] = it.get("client_id") == client_scope
    return items


@api.post("/me/forms", tags=["Formulaires"])
async def me_create_form(payload: FormCreate, user: dict = Depends(get_current_user)):
    client_scope = (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else user["id"]
    client = await db.users.find_one({"id": client_scope}, {"_id": 0, "client_code": 1, "company": 1, "full_name": 1})
    code = (client or {}).get("client_code") or _slugify_code((client or {}).get("company") or (client or {}).get("full_name") or "X")
    number = await _next_form_number(code)
    doc = {
        "id": _uuid(),
        "client_id": client_scope,
        "client_code": code,
        "number": f"FORM-{code}-{number:04d}",
        "title": payload.title,
        "description": payload.description or "",
        "is_public": payload.is_public,
        "pages": [p.model_dump() for p in (payload.pages or [FormPage(id=_uuid(), title="Page 1", fields=[])])],
        "created_by_id": user["id"],
        "created_by_label": user.get("full_name") or user.get("email"),
        "created_at": _now(),
        "updated_at": _now(),
        "uses_count": 0,
    }
    await db.forms.insert_one(doc.copy())
    return _form_serialize(doc)


@api.get("/me/forms/{form_id}", tags=["Formulaires"])
async def me_get_form(form_id: str, user: dict = Depends(get_current_user)):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    client_scope = (user.get("client_id") or user.get("id"))
    is_public = form.get("is_public")
    is_mine = form.get("client_id") == client_scope
    if user.get("role") != "admin" and not is_public and not is_mine:
        raise HTTPException(status_code=403, detail="Formulaire non accessible")
    form["is_mine"] = is_mine
    return form


@api.put("/me/forms/{form_id}", tags=["Formulaires"])
async def me_update_form(form_id: str, payload: FormUpdate, user: dict = Depends(get_current_user)):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "pages" in update:
        update["pages"] = [p if isinstance(p, dict) else p.model_dump() for p in update["pages"]]
    update["updated_at"] = _now()
    await db.forms.update_one({"id": form_id}, {"$set": update})
    refreshed = await db.forms.find_one({"id": form_id}, {"_id": 0})
    return _form_serialize(refreshed)


@api.delete("/me/forms/{form_id}", tags=["Formulaires"])
async def me_delete_form(form_id: str, user: dict = Depends(get_current_user)):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        return {"ok": True}
    await _require_owner_or_admin(form, user)
    await db.forms.delete_one({"id": form_id})
    await db.form_submissions.delete_many({"form_id": form_id})
    return {"ok": True}


@api.post("/me/forms/{form_id}/import", tags=["Formulaires"])
async def me_import_form(form_id: str, user: dict = Depends(get_current_user)):
    """Duplicate a public form into the current client's scope (numbered & owned by them)."""
    src = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not src:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    if not src.get("is_public") and src.get("client_id") != (user.get("client_id") or user.get("id")) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Ce formulaire n'est pas public")
    client_scope = (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else user["id"]
    client = await db.users.find_one({"id": client_scope}, {"_id": 0, "client_code": 1, "company": 1, "full_name": 1})
    code = (client or {}).get("client_code") or _slugify_code((client or {}).get("company") or (client or {}).get("full_name") or "X")
    number = await _next_form_number(code)
    dup = {
        "id": _uuid(),
        "client_id": client_scope,
        "client_code": code,
        "number": f"FORM-{code}-{number:04d}",
        "title": f"{src['title']} (importé)",
        "description": src.get("description") or "",
        "is_public": False,
        "pages": src.get("pages") or [],
        "created_by_id": user["id"],
        "created_by_label": user.get("full_name") or user.get("email"),
        "imported_from": src["id"],
        "created_at": _now(),
        "updated_at": _now(),
        "uses_count": 0,
    }
    await db.forms.insert_one(dup.copy())
    return _form_serialize(dup)


# ----- Form submissions (one per user per form — auto-alimentation on reopen) -----
class SubmissionSave(BaseModel):
    data: Dict[str, Any]
    geo: Optional[Dict[str, Any]] = None


@api.get("/me/forms/{form_id}/submission", tags=["Formulaires"])
async def me_get_my_submission(form_id: str, user: dict = Depends(get_current_user)):
    """Return the current user's submission for the form (or an empty stub)."""
    sub = await db.form_submissions.find_one(
        {"form_id": form_id, "user_id": user["id"]}, {"_id": 0}
    )
    return sub or {"form_id": form_id, "user_id": user["id"], "data": {}, "revisions_count": 0}


@api.post("/me/forms/{form_id}/submission", tags=["Formulaires"])
async def me_save_submission(form_id: str, payload: SubmissionSave, user: dict = Depends(get_current_user)):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0, "client_id": 1, "uses_count": 1})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    existing = await db.form_submissions.find_one({"form_id": form_id, "user_id": user["id"]}, {"_id": 0})
    if existing:
        update = {
            "data": payload.data,
            "geo": payload.geo,
            "updated_at": _now(),
            "revisions_count": (existing.get("revisions_count") or 0) + 1,
            "user_label": user.get("full_name") or user.get("email"),
        }
        await db.form_submissions.update_one({"id": existing["id"]}, {"$set": update})
        refreshed = await db.form_submissions.find_one({"id": existing["id"]}, {"_id": 0})
        return refreshed
    doc = {
        "id": _uuid(),
        "form_id": form_id,
        "client_id": form.get("client_id"),
        "user_id": user["id"],
        "user_label": user.get("full_name") or user.get("email"),
        "data": payload.data,
        "geo": payload.geo,
        "created_at": _now(),
        "updated_at": _now(),
        "revisions_count": 1,
    }
    await db.form_submissions.insert_one(doc.copy())
    await db.forms.update_one({"id": form_id}, {"$inc": {"uses_count": 1}})
    doc.pop("_id", None)
    return doc


@api.get("/me/forms/{form_id}/submissions", tags=["Formulaires"])
async def me_list_form_submissions(form_id: str, user: dict = Depends(get_current_user)):
    """List all submissions for a form — owner/admin only."""
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)
    items = await db.form_submissions.find({"form_id": form_id}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return {"form": {"id": form["id"], "title": form.get("title"), "pages": form.get("pages") or []}, "items": items}


# ----- Public (anonymous) form fill — only for is_public forms -----
class PublicSubmissionRequest(BaseModel):
    data: Dict[str, Any]
    geo: Optional[Dict[str, Any]] = None
    respondent_name: Optional[str] = None
    respondent_email: Optional[str] = None


@api.get("/public/forms/{form_id}", tags=["Public"])
async def public_get_form(form_id: str):
    """Fetch a public form anonymously — only works when `is_public=True`."""
    form = await db.forms.find_one(
        {"id": form_id, "is_public": True},
        {"_id": 0, "id": 1, "number": 1, "title": 1, "description": 1, "pages": 1, "client_code": 1},
    )
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable ou non public")
    return form


@api.post("/public/forms/{form_id}/submission", tags=["Public"])
async def public_submit_form(form_id: str, payload: PublicSubmissionRequest, request: Request):
    form = await db.forms.find_one({"id": form_id, "is_public": True}, {"_id": 0, "client_id": 1})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable ou non public")
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "")
    doc = {
        "id": _uuid(),
        "form_id": form_id,
        "client_id": form.get("client_id"),
        "user_id": f"anon-{_uuid()[:8]}",  # unique per submission so we bypass the (form_id,user_id) unique index
        "user_label": (payload.respondent_name or payload.respondent_email or f"Anonyme · {ip}")[:120],
        "data": payload.data,
        "geo": payload.geo,
        "respondent_email": payload.respondent_email,
        "anonymous": True,
        "source_ip": ip,
        "created_at": _now(),
        "updated_at": _now(),
        "revisions_count": 1,
    }
    await db.form_submissions.insert_one(doc.copy())
    await db.forms.update_one({"id": form_id}, {"$inc": {"uses_count": 1}})
    return {"ok": True, "id": doc["id"]}


# ====================================================================
# PHASE 4b — Form Analytics Dashboard (global + per-form)
# ====================================================================
def _parse_date(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        # Accept YYYY-MM-DD or full ISO
        if len(v) == 10:
            return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None


def _analytics_scope_query(user: dict, admin_all: bool = True) -> dict:
    """Scope forms/submissions to current client unless admin asks for global."""
    if user.get("role") == "admin" and admin_all:
        return {}
    cid = user.get("client_id") or user.get("id")
    return {"client_id": cid}


async def _submissions_analytics(match: dict, date_from: Optional[datetime], date_to: Optional[datetime]) -> dict:
    """Common aggregation pipeline used by global + per-form analytics."""
    range_q = {}
    if date_from:
        range_q["$gte"] = date_from.isoformat()
    if date_to:
        range_q["$lte"] = date_to.isoformat()
    if range_q:
        match = {**match, "created_at": range_q}

    subs = await db.form_submissions.find(
        match,
        {"_id": 0, "id": 1, "form_id": 1, "user_id": 1, "user_label": 1,
         "anonymous": 1, "created_at": 1, "geo": 1, "source_ip": 1, "respondent_email": 1},
    ).to_list(10000)

    # Time-series: group per day (UTC)
    by_day: Dict[str, int] = {}
    auth_count = 0
    anon_count = 0
    by_country: Dict[str, int] = {}
    by_author: Dict[str, Dict[str, Any]] = {}

    for s in subs:
        ts = s.get("created_at")
        if isinstance(ts, datetime):
            day_key = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        else:
            day_key = (str(ts) or "")[:10] or "unknown"
        by_day[day_key] = by_day.get(day_key, 0) + 1

        if s.get("anonymous"):
            anon_count += 1
        else:
            auth_count += 1
            label = s.get("user_label") or s.get("user_id") or "—"
            node = by_author.setdefault(label, {"label": label, "count": 0})
            node["count"] += 1

        geo = s.get("geo") or {}
        country = (geo.get("country") or geo.get("country_name") or "").strip() or "Inconnu"
        by_country[country] = by_country.get(country, 0) + 1

    # Sort series by date ascending
    series = [{"date": d, "count": by_day[d]} for d in sorted(by_day.keys())]
    top_authors = sorted(by_author.values(), key=lambda x: x["count"], reverse=True)[:10]
    country_list = sorted(
        [{"country": k, "count": v} for k, v in by_country.items()],
        key=lambda x: x["count"], reverse=True,
    )

    return {
        "total_submissions": len(subs),
        "auth_count": auth_count,
        "anon_count": anon_count,
        "series": series,
        "top_authors": top_authors,
        "by_country": country_list,
    }


@api.get("/me/forms-analytics", tags=["Formulaires"])
async def me_forms_analytics_global(
    user: dict = Depends(get_current_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Global analytics across all forms the user can see.
    - Admin : tous les formulaires.
    - Client : tous ses formulaires.
    """
    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    forms_scope = _analytics_scope_query(user)
    forms = await db.forms.find(
        forms_scope,
        {"_id": 0, "id": 1, "number": 1, "title": 1, "is_public": 1, "uses_count": 1, "created_at": 1, "client_code": 1},
    ).to_list(5000)
    form_ids = [f["id"] for f in forms]

    if not form_ids:
        return {
            "scope": "global",
            "total_forms": 0,
            "total_views": 0,
            "public_count": 0,
            "private_count": 0,
            "submissions": await _submissions_analytics({"form_id": {"$in": []}}, df, dt),
            "top_forms": [],
        }

    agg = await _submissions_analytics({"form_id": {"$in": form_ids}}, df, dt)

    # Top forms by submissions
    sub_counts: Dict[str, int] = {}
    per_form_match: Dict[str, Any] = {"form_id": {"$in": form_ids}}
    if df or dt:
        rng: Dict[str, Any] = {}
        if df: rng["$gte"] = df.isoformat()
        if dt: rng["$lte"] = dt.isoformat()
        per_form_match["created_at"] = rng
    cursor = db.form_submissions.aggregate([
        {"$match": per_form_match},
        {"$group": {"_id": "$form_id", "count": {"$sum": 1}}},
    ])
    async for r in cursor:
        sub_counts[r["_id"]] = r["count"]

    top_forms = sorted(
        [{
            "id": f["id"],
            "number": f.get("number"),
            "title": f.get("title"),
            "is_public": bool(f.get("is_public")),
            "views": int(f.get("uses_count") or 0),
            "submissions": int(sub_counts.get(f["id"], 0)),
        } for f in forms],
        key=lambda x: x["submissions"], reverse=True,
    )[:10]

    return {
        "scope": "global",
        "total_forms": len(forms),
        "total_views": sum(int(f.get("uses_count") or 0) for f in forms),
        "public_count": sum(1 for f in forms if f.get("is_public")),
        "private_count": sum(1 for f in forms if not f.get("is_public")),
        "submissions": agg,
        "top_forms": top_forms,
    }


@api.get("/me/forms/{form_id}/analytics", tags=["Formulaires"])
async def me_form_analytics_detail(
    form_id: str,
    user: dict = Depends(get_current_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    agg = await _submissions_analytics({"form_id": form_id}, df, dt)
    views = int(form.get("uses_count") or 0)
    submissions = agg["total_submissions"]
    completion_rate = round((submissions / views) * 100, 1) if views > 0 else (100.0 if submissions > 0 else 0.0)

    # Most recent 10 submissions (trimmed)
    recent = await db.form_submissions.find(
        {"form_id": form_id},
        {"_id": 0, "id": 1, "user_label": 1, "anonymous": 1, "created_at": 1, "geo": 1, "respondent_email": 1},
    ).sort("created_at", -1).limit(10).to_list(10)

    return {
        "scope": "form",
        "form": {
            "id": form["id"],
            "number": form.get("number"),
            "title": form.get("title"),
            "is_public": bool(form.get("is_public")),
            "created_at": form.get("created_at"),
        },
        "views": views,
        "submissions": submissions,
        "completion_rate": completion_rate,
        "auth_count": agg["auth_count"],
        "anon_count": agg["anon_count"],
        "series": agg["series"],
        "by_country": agg["by_country"],
        "top_authors": agg["top_authors"],
        "recent": recent,
    }


@api.get("/me/forms/{form_id}/analytics/export.csv", tags=["Formulaires"])
async def me_form_analytics_csv(
    form_id: str,
    user: dict = Depends(get_current_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """CSV export of all submissions for a form (flat answers + metadata)."""
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)

    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    match: Dict[str, Any] = {"form_id": form_id}
    rng: Dict[str, Any] = {}
    if df: rng["$gte"] = df.isoformat()
    if dt: rng["$lte"] = dt.isoformat()
    if rng:
        match["created_at"] = rng

    # Collect all field labels from pages
    labels: List[tuple] = []  # (field_id, label)
    seen = set()
    for page in (form.get("pages") or []):
        for field in (page.get("fields") or []):
            fid = field.get("id")
            if fid and fid not in seen:
                seen.add(fid)
                labels.append((fid, field.get("label") or fid))

    subs = await db.form_submissions.find(match, {"_id": 0}).sort("created_at", 1).to_list(10000)

    import csv, io
    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["id", "date", "auteur", "type", "email", "pays", "ville", "ip"] + [lab for _, lab in labels]
    writer.writerow(header)
    for s in subs:
        data = s.get("data") or {}
        geo = s.get("geo") or {}
        ts = s.get("created_at")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts or "")
        row = [
            s.get("id", ""),
            ts_str,
            s.get("user_label", ""),
            "Anonyme" if s.get("anonymous") else "Authentifié",
            s.get("respondent_email") or "",
            geo.get("country") or geo.get("country_name") or "",
            geo.get("city") or "",
            s.get("source_ip") or "",
        ]
        for fid, _ in labels:
            v = data.get(fid, "")
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            row.append(v)
        writer.writerow(row)

    csv_bytes = buf.getvalue().encode("utf-8-sig")  # BOM for Excel
    filename = f"{(form.get('number') or form_id)}-submissions.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ====================================================================
# PHASE 5 — Notification badges on menu links


@api.post("/me/notifications/mark-seen", tags=["Portail Client"])
async def me_notifications_mark_seen(payload: MarkSeenRequest, user: dict = Depends(get_current_user)):
    """Mark a module as visited (resets its badge counter to 0)."""
    if payload.module not in MODULE_COUNT_QUERIES:
        raise HTTPException(status_code=400, detail=f"Module inconnu : {payload.module}")
    await db.user_module_visits.update_one(
        {"user_id": user["id"], "module": payload.module},
        {"$set": {"last_visited_at": _now()}},
        upsert=True,
    )
    return {"ok": True}


# ====================================================================
# PHASE 2 — Deep-links cryptés pour intégrations externes (Windows apps)
# URL pattern : {PUBLIC_BASE_URL}/launch?t=<jwt>
# Token claims : {action, client_code, username, target_id?, iat, exp}
# Signed with LINK_JWT_SECRET (separate from auth JWT to avoid token confusion).
# ====================================================================
import jwt as _pyjwt_links

LINK_JWT_SECRET = os.environ.get("LINK_JWT_SECRET") or (os.environ.get("JWT_SECRET", "fallback-insecure") + "-link")
LINK_JWT_ALGO = "HS256"
LINK_DEFAULT_TTL_SECONDS = 15 * 60  # 15 minutes
LINK_ACTIONS = {
    "login": "Connexion au portail",
    "rdv": "Demande / prise de RDV",
    "appointments": "Liste des RDV",
    "document": "Espace documents",
    "intervention": "Espace interventions",
    "contact": "Formulaire de contact",
    "dashboard": "Tableau de bord portail",
    "formations": "Formations spécialisées",
    "note": "Rapports et suivis",
    "status": "Page d'état /uptime",
}


class BuildLinkRequest(BaseModel):
    action: str
    client_code: Optional[str] = None
    username: Optional[str] = None
    target_id: Optional[str] = None
    ttl_seconds: Optional[int] = None


@api.get("/integrations/link-actions", tags=["Admin"])
async def integrations_link_actions(_: dict = Depends(get_current_admin)):
    """List the supported deep-link actions for the admin UI dropdown."""
    return [{"value": k, "label": v} for k, v in LINK_ACTIONS.items()]


@api.post("/integrations/build-link", tags=["Admin"])
async def integrations_build_link(request: Request, payload: BuildLinkRequest, _: dict = Depends(get_current_admin)):
    action = (payload.action or "").strip().lower()
    if action not in LINK_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Action inconnue. Options : {', '.join(LINK_ACTIONS.keys())}")
    ttl = payload.ttl_seconds if payload.ttl_seconds and payload.ttl_seconds > 0 else LINK_DEFAULT_TTL_SECONDS
    ttl = min(ttl, 24 * 3600)  # hard cap 24h to prevent abuse
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "action": action,
        "client_code": (payload.client_code or "").strip() or None,
        "username": (payload.username or "").strip() or None,
        "target_id": (payload.target_id or "").strip() or None,
        "iat": now,
        "exp": now + ttl,
    }
    token = _pyjwt_links.encode(claims, LINK_JWT_SECRET, algorithm=LINK_JWT_ALGO)
    # Use the host the admin is actually browsing from (production vs preview)
    # rather than the static PUBLIC_BASE_URL env value.
    base = _public_base_url(request) or (PUBLIC_BASE_URL or "").rstrip("/")
    url = f"{base}/launch?t={token}" if base else f"/launch?t={token}"
    return {
        "token": token,
        "url": url,
        "expires_at": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat(),
        "ttl_seconds": ttl,
        "action": action,
        "action_label": LINK_ACTIONS[action],
    }


@api.get("/integrations/resolve-link", tags=["Public"])
async def integrations_resolve_link(t: str):
    """Public endpoint — decode a link token, return its claims so the SPA
    can redirect the user to the right route. Never raises on bad tokens;
    returns {valid: false, reason}."""
    try:
        claims = _pyjwt_links.decode(t, LINK_JWT_SECRET, algorithms=[LINK_JWT_ALGO])
    except _pyjwt_links.ExpiredSignatureError:
        return {"valid": False, "reason": "expired"}
    except Exception:
        return {"valid": False, "reason": "invalid"}
    action = claims.get("action")
    if action not in LINK_ACTIONS:
        return {"valid": False, "reason": "invalid_action"}
    return {
        "valid": True,
        "action": action,
        "action_label": LINK_ACTIONS[action],
        "client_code": claims.get("client_code"),
        "username": claims.get("username"),
        "target_id": claims.get("target_id"),
        "expires_at": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat() if claims.get("exp") else None,
    }


# ====================================================================
# VISITOR TRACKING (with optional forward to external REST endpoint)
# ====================================================================
# In-memory cache for geo lookups — avoids hitting ip-api.com on every
# request and surviving short outages.
_GEO_CACHE: dict[str, dict] = {}
_GEO_CACHE_MAX = 5000


async def _resolve_geo(ip: str) -> dict:
    """Resolve country/city from IP via free ip-api.com (rate-limited but no key)."""
    if not ip or ip.startswith(("127.", "10.", "192.168.", "172.")) or ip == "::1":
        return {"country": "", "city": "", "region": ""}
    if ip in _GEO_CACHE:
        return _GEO_CACHE[ip]
    try:
        import httpx
        # Aggressive 1.5 s timeout — ip-api.com is best-effort, we never want it
        # to block the request pipeline.
        async with httpx.AsyncClient(timeout=1.5) as cli:
            r = await cli.get(f"http://ip-api.com/json/{ip}?fields=country,regionName,city,status")
            d = r.json()
            if d.get("status") == "success":
                geo = {"country": d.get("country", ""), "city": d.get("city", ""), "region": d.get("regionName", "")}
                # Trivial LRU-ish: drop a random entry if cache is full
                if len(_GEO_CACHE) >= _GEO_CACHE_MAX:
                    try:
                        _GEO_CACHE.pop(next(iter(_GEO_CACHE)))
                    except StopIteration:
                        pass
                _GEO_CACHE[ip] = geo
                return geo
    except Exception as e:
        logger.warning("GeoIP lookup failed for %s: %s", ip, e)
    fallback = {"country": "", "city": "", "region": ""}
    _GEO_CACHE[ip] = fallback  # cache miss too — avoid retrying broken IPs
    return fallback


async def _enrich_visit_geo(visit_id: str, ip: str) -> None:
    """Resolve geo info AFTER the response has been sent and patch the visit document."""
    geo = await _resolve_geo(ip)
    if geo.get("country") or geo.get("city"):
        try:
            await db.visits.update_one({"id": visit_id}, {"$set": geo})
        except Exception as e:
            logger.warning("Geo enrichment write failed for %s: %s", visit_id, e)


@api.post("/track", tags=["Public"])
async def track_visit(request: Request, payload: dict):
    """Enregistre une visite et la transmet (si configuré) à l'API REST externe.
    Geo enrichment is performed in the background so /track always returns instantly.
    """
    # Resolve client IP
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not ip:
        ip = request.headers.get("x-real-ip", "")
    if not ip and request.client:
        ip = request.client.host or ""

    # Use cached geo if known, otherwise blank — we'll fill in async.
    geo = _GEO_CACHE.get(ip) or {"country": "", "city": "", "region": ""}
    event = {
        "id": _uuid(),
        "datetime": _now(),
        "ip": ip,
        "country": geo["country"],
        "city": geo["city"],
        "region": geo["region"],
        "page": payload.get("page") or "/",
        "referrer": payload.get("referrer") or "",
        "user_agent": request.headers.get("user-agent", ""),
        "session_id": payload.get("session_id") or "",
    }
    # Store locally (capped)
    await db.visits.insert_one(event.copy())
    event.pop("_id", None)

    # Schedule geo enrichment in background only when needed (fire-and-forget)
    if ip and not (geo.get("country") or geo.get("city")):
        asyncio.create_task(_enrich_visit_geo(event["id"], ip))

    # Optional forward to external REST endpoint — fire-and-forget so a slow
    # third-party never blocks /track from returning.
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("tracking_enabled") and s.get("tracking_base_url"):
        forward_url = s["tracking_base_url"].rstrip("/") + "/" + (s.get("tracking_endpoint") or "").lstrip("/")
        async def _fwd():
            try:
                import httpx
                headers = {"Content-Type": "application/json"}
                if s.get("tracking_auth_header"):
                    headers["Authorization"] = s["tracking_auth_header"]
                async with httpx.AsyncClient(timeout=3) as cli:
                    await cli.post(forward_url, json=event, headers=headers)
            except Exception as e:
                logger.warning("Tracking forward failed: %s", e)
        asyncio.create_task(_fwd())
    return {"ok": True, "id": event["id"], "geo": geo}


@api.get("/admin/visits", tags=["Admin"])
async def admin_list_visits(limit: int = 200, _: dict = Depends(get_current_admin)):
    items = await db.visits.find({}, {"_id": 0}).to_list(limit)
    return sorted(items, key=lambda x: x["datetime"], reverse=True)


@api.get("/admin/visits/stats", tags=["Admin"])
async def admin_visits_stats(_: dict = Depends(get_current_admin)):
    # Use Mongo aggregation instead of loading 50k docs into Python.
    pipeline_country = [
        {"$group": {"_id": {"$ifNull": ["$country", "Inconnu"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    pipeline_pages = [
        {"$group": {"_id": {"$ifNull": ["$page", "/"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    total_doc = await db.visits.estimated_document_count()
    countries = await db.visits.aggregate(pipeline_country).to_list(20)
    pages = await db.visits.aggregate(pipeline_pages).to_list(20)
    unique_countries = await db.visits.distinct("country", {"country": {"$nin": [None, ""]}})
    return {
        "total": total_doc,
        "unique_countries": len([c for c in unique_countries if c]),
        "top_countries": [{"country": c["_id"] or "Inconnu", "count": c["count"]} for c in countries],
        "top_pages": [{"page": p["_id"] or "/", "count": p["count"]} for p in pages],
    }


@api.get("/visits/count", tags=["Public"])
async def public_visit_count():
    """Total visit counter for the public homepage. Includes admin-tunable offset."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("visits_counter_enabled") is False:
        return {"enabled": False, "count": 0}
    real = await db.visits.count_documents({})
    offset = int(s.get("visits_counter_offset") or 0)
    return {"enabled": True, "count": max(0, real + offset)}


@api.get("/visits/trend", tags=["Public"])
async def public_visit_trend(days: int = 7):
    """Daily visit counts for the last N days (default 7), oldest first.
    Used by the homepage ticker sparkline.
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("visits_counter_enabled") is False:
        return {"enabled": False, "days": []}
    days = max(2, min(days, 30))
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    cursor = db.visits.find(
        {"datetime": {"$gte": start.isoformat()}},
        {"_id": 0, "datetime": 1},
    )
    items = await cursor.to_list(50000)
    buckets = {(start + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for v in items:
        dt = (v.get("datetime") or "")[:10]
        if dt in buckets:
            buckets[dt] += 1
    series = [{"date": k, "count": v} for k, v in sorted(buckets.items())]
    return {"enabled": True, "days": series, "total": sum(b["count"] for b in series)}


@api.post("/admin/visits/reset", tags=["Admin"])
async def admin_reset_visit_counter(_: dict = Depends(get_current_admin)):
    """Resets the publicly displayed counter to zero (real visits remain in DB)."""
    real = await db.visits.count_documents({})
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"visits_counter_offset": -real, "updated_at": _now()}},
        upsert=True,
    )
    return {"ok": True, "displayed_count": 0, "real_count": real}


# ====================================================================
# FORMATIONS — admin CRUD + tracked-user portal access
# ====================================================================
def _is_tracked_user(user: dict) -> bool:
    return bool(user.get("tracked_user_id"))


def _formation_state_from_progress(modules_total: int, modules_seen: int, last_access_iso: Optional[str], current_state: Optional[str]) -> str:
    """Compute the formation state from the user's progress.

    Rules :
    - "annulée" set by admin → never auto-changed back.
    - 0 module seen → "inscription".
    - 1 ≤ seen < total/2 → "commencée".
    - total/2 ≤ seen < total → "en_cours".
    - seen >= total → "terminée".
    - 7+ days since last_access → "suspendue" (unless terminée or annulée).
    """
    if current_state == "annulée":
        return "annulée"
    if modules_total <= 0:
        return current_state or "inscription"
    if modules_seen <= 0:
        new = "inscription"
    elif modules_seen >= modules_total:
        new = "terminée"
    elif modules_seen < max(1, modules_total // 2):
        new = "commencée"
    else:
        new = "en_cours"
    if new not in ("terminée", "annulée") and last_access_iso:
        try:
            last = datetime.fromisoformat(last_access_iso)
            if (datetime.now(timezone.utc) - last).total_seconds() > 7 * 24 * 3600:
                new = "suspendue"
        except Exception:
            pass
    return new


async def _refresh_enrollment_state(enr: dict) -> dict:
    """Recompute state + counts; returns enrollment with refreshed values (without DB write)."""
    modules_total = await db.formation_modules.count_documents({"formation_id": enr["formation_id"]})
    seen = set(enr.get("modules_seen") or [])
    modules_seen = len(seen)
    new_state = _formation_state_from_progress(modules_total, modules_seen, enr.get("last_access"), enr.get("state"))
    enr["modules_total"] = modules_total
    enr["modules_seen_count"] = modules_seen
    enr["state"] = new_state
    return enr


@api.get("/admin/formations", tags=["Admin"])
async def admin_list_formations(_: dict = Depends(get_current_admin)):
    items = await db.formations.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    for it in items:
        it["modules_count"] = await db.formation_modules.count_documents({"formation_id": it["id"]})
        it["enrolled_count"] = await db.formation_enrollments.count_documents({"formation_id": it["id"]})
    return items


@api.post("/admin/formations", tags=["Admin"])
async def admin_create_formation(payload: FormationCreate, user: dict = Depends(get_current_admin)):
    doc = {"id": _uuid(), **payload.model_dump(), "created_by_id": user["id"], "created_at": _now(), "updated_at": _now()}
    await db.formations.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/formations/{fid}", tags=["Admin"])
async def admin_update_formation(fid: str, payload: FormationUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    res = await db.formations.update_one({"id": fid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Formation introuvable")
    return {"ok": True}


@api.delete("/admin/formations/{fid}", tags=["Admin"])
async def admin_delete_formation(fid: str, _: dict = Depends(get_current_admin)):
    await db.formations.delete_one({"id": fid})
    await db.formation_modules.delete_many({"formation_id": fid})
    await db.formation_enrollments.delete_many({"formation_id": fid})
    await db.formation_visits.delete_many({"formation_id": fid})
    return {"ok": True}


# Modules
@api.get("/admin/formations/{fid}/modules", tags=["Admin"])
async def admin_list_modules(fid: str, _: dict = Depends(get_current_admin)):
    items = await db.formation_modules.find({"formation_id": fid}, {"_id": 0}).sort("order", 1).to_list(500)
    return items


@api.post("/admin/formations/{fid}/modules", tags=["Admin"])
async def admin_create_module(fid: str, payload: FormationModuleCreate, _: dict = Depends(get_current_admin)):
    formation = await db.formations.find_one({"id": fid}, {"_id": 0})
    if not formation:
        raise HTTPException(status_code=404, detail="Formation introuvable")
    doc = {"id": _uuid(), "formation_id": fid, **payload.model_dump(), "created_at": _now(), "updated_at": _now()}
    await db.formation_modules.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/formations/{fid}/modules/{mid}", tags=["Admin"])
async def admin_update_module(fid: str, mid: str, payload: FormationModuleUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    res = await db.formation_modules.update_one({"id": mid, "formation_id": fid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Module introuvable")
    return {"ok": True}


@api.delete("/admin/formations/{fid}/modules/{mid}", tags=["Admin"])
async def admin_delete_module(fid: str, mid: str, _: dict = Depends(get_current_admin)):
    await db.formation_modules.delete_one({"id": mid, "formation_id": fid})
    return {"ok": True}


@api.get("/admin/formations/{fid}/enrollments", tags=["Admin"])
async def admin_list_enrollments(fid: str, _: dict = Depends(get_current_admin)):
    items = await db.formation_enrollments.find({"formation_id": fid}, {"_id": 0}).to_list(5000)
    for it in items:
        await _refresh_enrollment_state(it)
    return items


@api.post("/admin/formations/{fid}/enrollments/{user_id}/credits", tags=["Admin"])
async def admin_adjust_credits(fid: str, user_id: str, payload: FormationCreditsUpdate, _: dict = Depends(get_current_admin)):
    enr = await db.formation_enrollments.find_one({"formation_id": fid, "user_id": user_id}, {"_id": 0})
    if not enr:
        raise HTTPException(status_code=404, detail="Inscription introuvable")
    delta = int(payload.credits_delta)
    new_purchased = max(0, int(enr.get("credits_purchased") or 0) + max(delta, 0))
    new_consumed = int(enr.get("credits_consumed") or 0)
    if delta < 0:
        new_consumed = max(0, new_consumed + abs(delta))  # interpret negative as "consume"
    await db.formation_enrollments.update_one(
        {"id": enr["id"]},
        {"$set": {
            "credits_purchased": new_purchased,
            "credits_consumed": new_consumed,
            "credits_available": max(0, new_purchased - new_consumed),
            "updated_at": _now(),
        }},
    )
    return {"ok": True}


@api.post("/admin/formations/{fid}/enrollments/{user_id}/state", tags=["Admin"])
async def admin_set_enrollment_state(fid: str, user_id: str, payload: FormationStateUpdate, _: dict = Depends(get_current_admin)):
    if payload.state not in ("annulée", "en_cours", "suspendue"):
        raise HTTPException(status_code=400, detail="État manuel autorisé : annulée, en_cours, suspendue")
    res = await db.formation_enrollments.update_one(
        {"formation_id": fid, "user_id": user_id},
        {"$set": {"state": payload.state, "updated_at": _now()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Inscription introuvable")
    return {"ok": True}


# ====================================================================
# PORTAL — Formations (tracked users, plus elevated cross-view)
# ====================================================================
@api.get("/me/formations", tags=["Portail Client"])
async def me_list_formations(user: dict = Depends(get_current_user)):
    if not (_is_tracked_user(user) or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Accès réservé aux utilisateurs suivis")
    formations = await db.formations.find({}, {"_id": 0}).sort("name", 1).to_list(500)
    out = []
    for f in formations:
        if not f.get("available") and not _is_elevated_creator(user):
            continue
        modules_total = await db.formation_modules.count_documents({"formation_id": f["id"]})
        enr = await db.formation_enrollments.find_one({"formation_id": f["id"], "user_id": user["id"]}, {"_id": 0})
        if enr:
            enr = await _refresh_enrollment_state(enr)
        rating = await db.ratings.find_one(
            {"kind": "formations", "target_id": f["id"], "rated_by_user_id": user["id"]}, {"_id": 0}
        )
        out.append({
            **f,
            "modules_total": modules_total,
            "enrollment": enr,
            "my_rating": ({"stars": rating["stars"], "comment": rating.get("comment")} if rating else None),
        })
    return out


@api.post("/me/formations/{fid}/enroll", tags=["Portail Client"])
async def me_enroll_formation(fid: str, user: dict = Depends(get_current_user)):
    if not _is_tracked_user(user):
        raise HTTPException(status_code=403, detail="Inscription réservée aux utilisateurs suivis")
    formation = await db.formations.find_one({"id": fid}, {"_id": 0})
    if not formation or not formation.get("available", True):
        raise HTTPException(status_code=404, detail="Formation indisponible")
    existing = await db.formation_enrollments.find_one({"formation_id": fid, "user_id": user["id"]}, {"_id": 0})
    if existing:
        return existing
    doc = {
        "id": _uuid(),
        "formation_id": fid,
        "user_id": user["id"],
        "user_email": user["email"],
        "user_name": user.get("full_name"),
        "state": "inscription",
        "credits_purchased": int(formation.get("default_credits") or 0),
        "credits_consumed": 0,
        "credits_available": int(formation.get("default_credits") or 0),
        "modules_seen": [],
        "total_time_ms": 0,
        "last_access": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.formation_enrollments.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.get("/me/formations/{fid}", tags=["Portail Client"])
async def me_get_formation(fid: str, user: dict = Depends(get_current_user)):
    formation = await db.formations.find_one({"id": fid}, {"_id": 0})
    if not formation:
        raise HTTPException(status_code=404, detail="Formation introuvable")
    if not (_is_tracked_user(user) or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Accès réservé")
    modules = await db.formation_modules.find({"formation_id": fid}, {"_id": 0}).sort("order", 1).to_list(500)
    enr = await db.formation_enrollments.find_one({"formation_id": fid, "user_id": user["id"]}, {"_id": 0})
    if enr:
        enr = await _refresh_enrollment_state(enr)
    return {"formation": formation, "modules": modules, "enrollment": enr}


@api.post("/me/formations/{fid}/modules/{mid}/visit", tags=["Portail Client"])
async def me_visit_module(fid: str, mid: str, request: Request, user: dict = Depends(get_current_user)):
    """Mark a module as visited (call when the page is OPENED)."""
    if not _is_tracked_user(user):
        raise HTTPException(status_code=403, detail="Réservé aux utilisateurs suivis")
    enr = await db.formation_enrollments.find_one({"formation_id": fid, "user_id": user["id"]}, {"_id": 0})
    if not enr:
        raise HTTPException(status_code=404, detail="Inscription requise")
    visit_id = _uuid()
    await db.formation_visits.insert_one({
        "id": visit_id,
        "enrollment_id": enr["id"],
        "user_id": user["id"],
        "formation_id": fid,
        "module_id": mid,
        "opened_at": _now(),
        "closed_at": None,
        "duration_ms": 0,
        "ip": _client_ip_from_request(request),
    })
    seen = set(enr.get("modules_seen") or [])
    seen.add(mid)
    await db.formation_enrollments.update_one(
        {"id": enr["id"]},
        {"$set": {
            "modules_seen": list(seen),
            "last_access": _now(),
            "updated_at": _now(),
        }},
    )
    return {"visit_id": visit_id}


@api.post("/me/formations/{fid}/modules/{mid}/visit/{visit_id}/close", tags=["Portail Client"])
async def me_close_visit(fid: str, mid: str, visit_id: str, user: dict = Depends(get_current_user)):
    """Records the duration once the user leaves the module."""
    visit = await db.formation_visits.find_one({"id": visit_id, "user_id": user["id"]}, {"_id": 0})
    if not visit:
        return {"ok": True}  # silently ignore
    if visit.get("closed_at"):
        return {"ok": True}
    try:
        opened = datetime.fromisoformat(visit["opened_at"])
        duration_ms = int((datetime.now(timezone.utc) - opened).total_seconds() * 1000)
    except Exception:
        duration_ms = 0
    duration_ms = max(0, min(duration_ms, 4 * 3600 * 1000))  # cap at 4h to avoid runaway tabs
    await db.formation_visits.update_one(
        {"id": visit_id},
        {"$set": {"closed_at": _now(), "duration_ms": duration_ms}},
    )
    await db.formation_enrollments.update_one(
        {"formation_id": fid, "user_id": user["id"]},
        {"$inc": {"total_time_ms": duration_ms}, "$set": {"updated_at": _now()}},
    )
    return {"ok": True, "duration_ms": duration_ms}


@api.post("/me/formations/{fid}/modules/{mid}/ask", tags=["Portail Client"])
async def me_module_ask(fid: str, mid: str, payload: FormationModuleQuestion, user: dict = Depends(get_current_user)):
    """Forwards the user's question to the module's external REST API as configured by the admin."""
    if not _is_tracked_user(user):
        raise HTTPException(status_code=403, detail="Réservé aux utilisateurs suivis")
    module = await db.formation_modules.find_one({"id": mid, "formation_id": fid}, {"_id": 0})
    if not module:
        raise HTTPException(status_code=404, detail="Module introuvable")
    api_url = (module.get("api_url") or "").strip()
    if not api_url:
        raise HTTPException(status_code=400, detail="Aucune API configurée pour ce module")

    headers = {"Content-Type": "application/json", "User-Agent": "SawaliFormationsClient/1.0"}
    auth = None
    atype = (module.get("api_auth_type") or "none").lower()
    if atype == "bearer" and module.get("api_token"):
        headers["Authorization"] = f"Bearer {module['api_token']}"
    elif atype == "basic":
        auth = (module.get("api_basic_user") or "", module.get("api_basic_pass") or "")

    body = {
        "question": (payload.question or "").strip(),
        "user_id": user["id"],
        "user_email": user["email"],
        "formation_id": fid,
        "module_id": mid,
        **(payload.payload or {}),
    }
    response_text = None
    status = 0
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.post(api_url, json=body, headers=headers, auth=auth)
            status = r.status_code
            response_text = r.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("Formation module ask failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Appel API distant échoué : {exc}") from exc

    qa_doc = {
        "id": _uuid(),
        "formation_id": fid,
        "module_id": mid,
        "user_id": user["id"],
        "user_email": user["email"],
        "question": body["question"],
        "response_text": response_text,
        "response_status": status,
        "created_at": _now(),
    }
    await db.formation_qa.insert_one(qa_doc.copy())
    qa_doc.pop("_id", None)

    # Try to interpret JSON
    try:
        return {"status": status, "response": json.loads(response_text), "id": qa_doc["id"]}
    except Exception:
        return {"status": status, "response": response_text, "id": qa_doc["id"]}


# ====================================================================
# REGISTER & STARTUP
# ====================================================================
app.include_router(api)


@app.on_event("startup")
async def on_startup():
    # Indexes — critical for performance as collections grow.
    # New indexes are added on every startup (idempotent).
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id")
    await db.otps.create_index("session_token")
    await db.otps.create_index("expires_at")
    await db.appointments.create_index("scheduled_at")
    await db.appointments.create_index("client_id")
    await db.documents.create_index("category")
    await db.documents.create_index("client_id")
    await db.contents.create_index("slug", unique=True)
    await db.api_traces.create_index("created_at")
    await db.api_traces.create_index("status")
    # Visit tracking — hot path, queried by date + page
    await db.visits.create_index("datetime")
    await db.visits.create_index("session_id")
    # Health & uptime monitor — queried by created_at sort
    await db.auth_checks.create_index("created_at")
    await db.uptime_checks.create_index("created_at")
    # Incidents
    await db.incidents.create_index("started_at")
    await db.incidents.create_index("status")
    await db.incident_subscribers.create_index("email", unique=True)
    await db.incident_subscribers.create_index("confirmation_token")
    await db.incident_subscribers.create_index("unsubscribe_token")
    # User notes (rapports/suivis) — queried by user_id + kind + event_date
    await db.user_notes.create_index([("user_id", 1), ("kind", 1)])
    await db.user_notes.create_index("event_date")
    # Interventions
    await db.interventions.create_index("client_id")
    await db.interventions.create_index("created_at")
    # Access logs
    await db.access_logs.create_index("created_at")
    await db.access_logs.create_index("user_email")
    # Document logs
    await db.document_logs.create_index([("document_id", 1), ("created_at", -1)])
    # Notification badges — lookup by (user_id, module)
    await db.user_module_visits.create_index([("user_id", 1), ("module", 1)], unique=True)
    # Dynamic forms (Phase 4)
    await db.forms.create_index("client_id")
    await db.forms.create_index("is_public")
    await db.forms.create_index("created_at")
    await db.form_submissions.create_index([("form_id", 1), ("user_id", 1)], unique=True)
    await db.form_submissions.create_index("client_id")
    # Directory & WhatsApp (Phase 3)
    await db.directory_contacts.create_index("client_id")
    await db.directory_contacts.create_index([("client_id", 1), ("owner_id", 1)])
    await db.whatsapp_messages.create_index("client_id")
    await db.whatsapp_messages.create_index("created_at")
    await db.whatsapp_schedules.create_index("status")
    await db.whatsapp_schedules.create_index("scheduled_at")
    await db.automations.create_index("event")
    await db.automations.create_index("enabled")
    await db.client_notes.create_index("client_id")
    await db.client_tasks.create_index("client_id")
    await db.client_tasks.create_index("status")
    await db.client_tasks.create_index("due_at")
    await db.policies.create_index("slot", unique=True)

    # Seed initial admin
    init_email = os.environ.get("ADMIN_INIT_EMAIL")
    init_password = os.environ.get("ADMIN_INIT_PASSWORD")
    init_name = os.environ.get("ADMIN_INIT_NAME", "Administrateur")
    if init_email and init_password:
        existing = await db.users.find_one({"email": init_email.lower()})
        if not existing:
            await db.users.insert_one(
                {
                    "id": _uuid(),
                    "email": init_email.lower(),
                    "full_name": init_name,
                    "password_hash": hash_password(init_password),
                    "role": "admin",
                    "phone": None,
                    "company": "SAWALI SMART SYSTEMS",
                    "account_status": "active",
                    "created_at": _now(),
                }
            )
            logger.info("Initial admin seeded: %s", init_email)

    # Seed default settings
    existing_settings = await db.settings.find_one({"_id": "global"})
    if not existing_settings:
        await db.settings.insert_one(
            {
                "_id": "global",
                "recaptcha_enabled": False,
                "smtp_use_tls": True,
                "business_open_time": "09:00",
                "business_close_time": "18:00",
                "business_days": [0, 1, 2, 3, 4],
                "slot_duration_min": 30,
                "company_email": "contact@sawalismartsystems.com",
                "company_phone": "+228 00 00 00 00",
                "company_address": "Lomé, Togo",
                "google_calendar_email": "sup.alphasofti@gmail.com",
                "assistant_enabled": True,
                "assistant_url": "https://agent.jotform.com/0199e26b35a87a6ea156d196e3e180731e7d?embedMode=popup",
                "assistant_label": "Liluvine — Support Technique",
                "assistant_color": "#0075E3",
            }
        )
    else:
        # Backfill assistant defaults if not present (existing installs)
        update_fields = {}
        if "assistant_url" not in existing_settings:
            update_fields.update({
                "assistant_enabled": True,
                "assistant_url": "https://agent.jotform.com/0199e26b35a87a6ea156d196e3e180731e7d?embedMode=popup",
                "assistant_label": "Liluvine — Support Technique",
                "assistant_color": "#0075E3",
            })
        if update_fields:
            await db.settings.update_one({"_id": "global"}, {"$set": update_fields})

    # Seed default contents (only if not present)
    defaults = [
        {
            "slug": "home_hero",
            "title": "L'ingénierie logicielle au service de votre transformation",
            "body_html": "<p>SAWALI SMART SYSTEMS conçoit, déploie et maintient des solutions logicielles métiers pour les entreprises africaines exigeantes.</p>",
            "images": [],
            "metadata": {
                "kicker": "SAWALI SMART SYSTEMS · SOFTWARE ENGINEERING",
            },
        },
        {
            "slug": "mission",
            "title": "Notre Mission",
            "body_html": (
                "<p>Accompagner les entreprises et institutions dans leur transformation digitale "
                "à travers des logiciels sur-mesure, robustes et évolutifs.</p>"
                "<p>Nous combinons rigueur d'ingénierie et proximité humaine pour livrer des "
                "produits qui durent.</p>"
            ),
            "images": [],
            "metadata": {},
        },
        {
            "slug": "experience",
            "title": "Notre Expérience",
            "body_html": (
                "<p>Plus de 10 ans d'expérience cumulée en conception de systèmes critiques, "
                "des bases de données aux applications web et mobiles.</p>"
            ),
            "images": [],
            "metadata": {
                "metrics": [
                    {"label": "Années d'expérience", "value": "10+"},
                    {"label": "Projets livrés", "value": "50+"},
                    {"label": "Clients satisfaits", "value": "30+"},
                    {"label": "Disponibilité", "value": "24/7"},
                ]
            },
        },
        {
            "slug": "specialisations",
            "title": "Nos Spécialisations",
            "body_html": "",
            "images": [],
            "metadata": {
                "items": [
                    {
                        "title": "Développement Web",
                        "icon": "Globe",
                        "desc": "Plateformes web performantes : portails clients, ERP, CRM sur mesure.",
                    },
                    {
                        "title": "Applications Mobiles",
                        "icon": "Smartphone",
                        "desc": "Apps Android & iOS natives ou hybrides, optimisées pour vos usages métier.",
                    },
                    {
                        "title": "Systèmes Métiers",
                        "icon": "Database",
                        "desc": "Conception de bases de données et systèmes back-office hautement disponibles.",
                    },
                    {
                        "title": "Ingénierie & Conseil",
                        "icon": "Cpu",
                        "desc": "Audit, architecture, automatisation et accompagnement DevOps.",
                    },
                ]
            },
        },
        {
            "slug": "about",
            "title": "À propos",
            "body_html": (
                "<p>SAWALI SMART SYSTEMS est une société d'ingénierie logicielle basée en Afrique "
                "de l'Ouest. Nous mettons l'expertise technique au service d'une vision claire : "
                "rendre vos opérations plus simples, plus rapides, plus fiables.</p>"
            ),
            "images": [],
            "metadata": {},
        },
    ]
    for d in defaults:
        if not await db.contents.find_one({"slug": d["slug"]}):
            d_doc = {
                **d,
                "id": _uuid(),
                "created_at": _now(),
                "updated_at": _now(),
            }
            await db.contents.insert_one(d_doc.copy())

    # ---------- Scheduler ----------
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        global _scheduler
        if _scheduler is None:
            _scheduler = AsyncIOScheduler(timezone="Africa/Abidjan")
            _scheduler.add_job(
                _send_weekly_digest,
                CronTrigger(day_of_week="fri", hour=5, minute=0, timezone="Africa/Abidjan"),
                id="health_weekly_digest",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            # Hourly auth checker — only fires alert if health_auth_check_enabled is on,
            # but always persists the result to db.auth_checks for the dashboard banner.
            async def _scheduled_auth_check():
                await _run_auth_check(triggered_by="cron:hourly")
            _scheduler.add_job(
                _scheduled_auth_check,
                CronTrigger(minute=0, timezone="Africa/Abidjan"),
                id="auth_checker_hourly",
                replace_existing=True,
                misfire_grace_time=600,
            )
            # Hourly uptime monitor — multi-endpoint probes (db + public APIs).
            async def _scheduled_uptime():
                await _run_uptime_probes(triggered_by="cron:hourly")
            _scheduler.add_job(
                _scheduled_uptime,
                CronTrigger(minute=5, timezone="Africa/Abidjan"),  # offset 5min from auth check
                id="uptime_monitor_hourly",
                replace_existing=True,
                misfire_grace_time=600,
            )
            # Minute-level WhatsApp scheduler — drains pending schedules due for send.
            _scheduler.add_job(
                _run_scheduled_whatsapp,
                CronTrigger(minute="*", timezone="Africa/Abidjan"),
                id="whatsapp_scheduler_minutely",
                replace_existing=True,
                misfire_grace_time=120,
            )
            # Hourly appointment reminders (J-1 window).
            _scheduler.add_job(
                _appointment_reminder_cron,
                CronTrigger(minute=15, timezone="Africa/Abidjan"),
                id="appointment_reminder_hourly",
                replace_existing=True,
                misfire_grace_time=600,
            )
            # Hourly task reminders (1h window before due_at).
            _scheduler.add_job(
                _task_reminder_cron,
                CronTrigger(minute=20, timezone="Africa/Abidjan"),
                id="task_reminder_hourly",
                replace_existing=True,
                misfire_grace_time=600,
            )
            _scheduler.start()
            logger.info("Scheduler started — weekly digest Fri 05:00 + auth check H:00 + uptime H:05 (Africa/Abidjan)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scheduler init failed: %s", exc)


@app.on_event("shutdown")
async def on_shutdown():
    try:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        pass
