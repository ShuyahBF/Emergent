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
from typing import Optional, List

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
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

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
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

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
async def _fire_intervention_webhook(action: str, intervention_doc: dict) -> None:
    """Fire-and-forget POST to {base_url}/{action}/{client_code}/{number}.
    Authentication options: none | bearer | basic.
    Failures are logged but never raised.
    """
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("webhook_enabled") or not s.get("webhook_base_url"):
            return
        client = await db.users.find_one({"id": intervention_doc.get("client_id")}, {"_id": 0})
        if not client:
            return
        code = (client.get("client_code") or _slugify_code(client.get("company") or client.get("full_name") or "X"))
        number = intervention_doc.get("intervention_number") or "unknown"
        base = (s.get("webhook_base_url") or "").rstrip("/")
        url = f"{base}/{action}/{code}/{number}"
        headers = {"Content-Type": "application/json", "User-Agent": "SawaliWebhook/1.0"}
        auth = None
        atype = (s.get("webhook_auth_type") or "none").lower()
        if atype == "bearer" and s.get("webhook_token"):
            headers["Authorization"] = f"Bearer {s['webhook_token']}"
        elif atype == "basic" and s.get("webhook_basic_user"):
            auth = (s.get("webhook_basic_user") or "", s.get("webhook_basic_pass") or "")
        async with httpx.AsyncClient(timeout=8.0) as http:
            r = await http.post(url, json=intervention_doc, headers=headers, auth=auth)
            logger.info("Intervention webhook %s %s -> %s", action, url, r.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Intervention webhook failed: %s", exc)


def _fire_webhook_bg(action: str, intervention_doc: dict) -> None:
    """Schedule webhook without awaiting it (fire and forget)."""
    try:
        asyncio.create_task(_fire_intervention_webhook(action, intervention_doc))
    except RuntimeError:
        # No running loop (shouldn't happen in FastAPI), ignore.
        pass


async def _fire_notes_webhook(action: str, kind: str, note_doc: dict, user: dict) -> None:
    """Fire-and-forget POST when a Rapport/Suivi is created/updated/deleted.

    URL pattern: {notes_webhook_url}/{action}/{kind}/{note_id}
    Body: full note doc + author block.
    """
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("notes_webhook_enabled") or not s.get("notes_webhook_url"):
            return
        base = (s.get("notes_webhook_url") or "").rstrip("/")
        url = f"{base}/{action}/{kind}/{note_doc.get('id', 'unknown')}"
        headers = {"Content-Type": "application/json", "User-Agent": "SawaliNotesWebhook/1.0"}
        auth = None
        atype = (s.get("notes_webhook_auth_type") or "none").lower()
        if atype == "bearer" and s.get("notes_webhook_token"):
            headers["Authorization"] = f"Bearer {s['notes_webhook_token']}"
        elif atype == "basic" and s.get("notes_webhook_basic_user"):
            auth = (s.get("notes_webhook_basic_user") or "", s.get("notes_webhook_basic_pass") or "")
        body = {
            "action": action,
            "kind": kind,
            "note": note_doc,
            "author": {"id": user.get("id"), "email": user.get("email"), "full_name": user.get("full_name"), "role": user.get("role")},
            "fired_at": _now(),
        }
        async with httpx.AsyncClient(timeout=8.0) as http:
            r = await http.post(url, json=body, headers=headers, auth=auth)
            logger.info("Notes webhook %s %s -> %s", action, url, r.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notes webhook failed: %s", exc)


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
async def _check_slot_available(scheduled_at: str, duration_min: int) -> tuple[bool, str]:
    """Verify the requested slot is within business hours and not taken."""
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
    return doc


@api.get("/admin/clients/{client_id}", tags=["Admin"])
async def admin_get_client(client_id: str, _: dict = Depends(get_current_admin)):
    u = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return u


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
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    # Auto-generate feedback token when status becomes "completed"
    if update.get("status") == "completed":
        existing = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
        if existing and not existing.get("feedback_token"):
            update["feedback_token"] = generate_session_token()
            update["feedback_status"] = "pending"
    await db.appointments.update_one({"id": appt_id}, {"$set": update})
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
    _fire_webhook_bg("created", doc)
    return doc


@api.put("/admin/interventions/{int_id}", tags=["Admin"])
async def admin_update_intervention(
    int_id: str, payload: InterventionUpdate, _: dict = Depends(get_current_admin)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await db.interventions.update_one({"id": int_id}, {"$set": update})
    doc = await db.interventions.find_one({"id": int_id}, {"_id": 0})
    if doc:
        _fire_webhook_bg("updated", doc)
    return {"ok": True}


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


@api.get("/files/{file_id}", tags=["Public"])
async def serve_file(request: Request, file_id: str):
    meta = await db.files.find_one({"id": file_id}, {"_id": 0})
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
    _fire_notes_webhook_bg("created", kind, doc, user)
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
    _fire_notes_webhook_bg("updated", kind, refreshed, user)
    return {"ok": True}


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
        _fire_notes_webhook_bg("deleted", kind, existing, user)
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
    _fire_webhook_bg("created", doc)
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
@api.get("/me/contacts", tags=["Portail Client"])
async def me_contacts(user: dict = Depends(get_current_user)):
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


# Generic DB query
ALLOWED_COLLECTIONS = {
    "users", "tracked_users", "appointments", "documents", "interventions",
    "contacts", "deployments", "blacklist", "client_categories", "document_categories",
    "case_studies", "blog_posts", "newsletter_subscribers", "testimonials",
    "settings", "user_reports", "user_suivis", "ratings",
    "access_logs", "api_traces", "visits", "document_logs", "files",
    "formations", "formation_modules", "formation_enrollments", "formation_visits", "formation_qa",
    "otps", "counters",
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
    for k in ("smtp_password", "google_client_secret", "recaptcha_secret_key", "google_calendar_password_hint", "tracking_auth_header", "webhook_token", "webhook_basic_pass", "notes_webhook_token", "notes_webhook_basic_pass", "health_webhook_token", "health_webhook_basic_pass"):
        if masked.get(k):
            masked[k] = "********"
    masked["google_calendar_connected"] = bool((await db.settings.find_one({"_id": "global"}) or {}).get("google_refresh_token"))
    return masked


@api.put("/admin/settings", tags=["Admin"])
async def admin_update_settings(payload: SettingsUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Treat the masking placeholder as "no change" for sensitive fields
    SECRET_FIELDS = (
        "smtp_password", "google_client_secret", "recaptcha_secret_key",
        "tracking_auth_header", "webhook_token", "webhook_basic_pass",
        "notes_webhook_token", "notes_webhook_basic_pass",
        "health_webhook_token", "health_webhook_basic_pass",
    )
    for k in SECRET_FIELDS:
        if update.get(k) == "********":
            update.pop(k, None)
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    return {"ok": True}


# ----- Google Calendar OAuth admin endpoints -----
@api.get("/admin/google/auth-url", tags=["Admin"])
async def admin_google_auth_url(request: Request, _: dict = Depends(get_current_admin)):
    redirect_uri = f"{PUBLIC_BASE_URL}/api/admin/google/callback"
    url = await gcal.get_auth_url(redirect_uri)
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Veuillez configurer google_client_id et google_client_secret dans les paramètres",
        )
    return {"auth_url": url, "redirect_uri": redirect_uri}


@api.get("/admin/google/callback", tags=["Admin"])
async def admin_google_callback(code: str):
    redirect_uri = f"{PUBLIC_BASE_URL}/api/admin/google/callback"
    try:
        await gcal.exchange_code(code, redirect_uri)
        return RedirectResponse(url=f"{PUBLIC_BASE_URL}/admin/settings?gcal=ok")
    except Exception as e:
        return RedirectResponse(url=f"{PUBLIC_BASE_URL}/admin/settings?gcal=error&msg={e}")


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
# VISITOR TRACKING (with optional forward to external REST endpoint)
# ====================================================================
async def _resolve_geo(ip: str) -> dict:
    """Resolve country/city from IP via free ip-api.com (rate-limited but no key)."""
    if not ip or ip.startswith(("127.", "10.", "192.168.", "172.")) or ip == "::1":
        return {"country": "", "city": "", "region": ""}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as cli:
            r = await cli.get(f"http://ip-api.com/json/{ip}?fields=country,regionName,city,status")
            d = r.json()
            if d.get("status") == "success":
                return {"country": d.get("country", ""), "city": d.get("city", ""), "region": d.get("regionName", "")}
    except Exception as e:
        logger.warning("GeoIP lookup failed: %s", e)
    return {"country": "", "city": "", "region": ""}


@api.post("/track", tags=["Public"])
async def track_visit(request: Request, payload: dict):
    """Enregistre une visite et la transmet (si configuré) à l'API REST externe."""
    # Resolve client IP
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not ip:
        ip = request.headers.get("x-real-ip", "")
    if not ip and request.client:
        ip = request.client.host or ""

    geo = await _resolve_geo(ip)
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

    # Optional forward to external REST endpoint
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("tracking_enabled") and s.get("tracking_base_url"):
        forward_url = s["tracking_base_url"].rstrip("/") + "/" + (s.get("tracking_endpoint") or "").lstrip("/")
        try:
            import httpx
            headers = {"Content-Type": "application/json"}
            if s.get("tracking_auth_header"):
                headers["Authorization"] = s["tracking_auth_header"]
            async with httpx.AsyncClient(timeout=5) as cli:
                await cli.post(forward_url, json=event, headers=headers)
            event["forwarded"] = True
        except Exception as e:
            logger.warning("Tracking forward failed: %s", e)
            event["forwarded"] = False
    return {"ok": True, "id": event["id"], "geo": geo}


@api.get("/admin/visits", tags=["Admin"])
async def admin_list_visits(limit: int = 200, _: dict = Depends(get_current_admin)):
    items = await db.visits.find({}, {"_id": 0}).to_list(limit)
    return sorted(items, key=lambda x: x["datetime"], reverse=True)


@api.get("/admin/visits/stats", tags=["Admin"])
async def admin_visits_stats(_: dict = Depends(get_current_admin)):
    items = await db.visits.find({}, {"_id": 0}).to_list(50000)
    total = len(items)
    countries: dict[str, int] = {}
    pages: dict[str, int] = {}
    for v in items:
        c = v.get("country") or "Inconnu"
        countries[c] = countries.get(c, 0) + 1
        p = v.get("page") or "/"
        pages[p] = pages.get(p, 0) + 1
    top_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)[:10]
    top_pages = sorted(pages.items(), key=lambda x: x[1], reverse=True)[:10]
    return {
        "total": total,
        "unique_countries": len([c for c in countries if c != "Inconnu"]),
        "top_countries": [{"country": k, "count": v} for k, v in top_countries],
        "top_pages": [{"page": k, "count": v} for k, v in top_pages],
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
    # Indexes
    await db.users.create_index("email", unique=True)
    await db.otps.create_index("session_token")
    await db.appointments.create_index("scheduled_at")
    await db.documents.create_index("category")
    await db.contents.create_index("slug", unique=True)
    await db.api_traces.create_index("created_at")
    await db.api_traces.create_index("status")

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
            _scheduler.start()
            logger.info("Scheduler started — weekly digest scheduled for Fri 05:00 Africa/Abidjan")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scheduler init failed: %s", exc)


@app.on_event("shutdown")
async def on_shutdown():
    try:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        pass
