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
import shutil
import uuid
import asyncio
import ipaddress
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
    items = await db.documents.find(
        {"$or": [{"client_id": user["id"]}, {"is_public": True}]}, {"_id": 0}
    ).to_list(500)
    return items


@api.get("/me/interventions", tags=["Portail Client"])
async def me_interventions(user: dict = Depends(get_current_user)):
    items = await db.interventions.find({"client_id": user["id"]}, {"_id": 0}).to_list(1000)
    return sorted(items, key=lambda x: x.get("intervention_date", ""), reverse=True)


@api.get("/me/users", tags=["Portail Client"])
async def me_users(user: dict = Depends(get_current_user)):
    items = await db.tracked_users.find({"client_id": user["id"]}, {"_id": 0}).to_list(2000)
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
    payload: InterventionCreate, _: dict = Depends(get_current_admin)
):
    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    intervention_number = await _next_intervention_number(client)
    doc = {
        "id": _uuid(),
        **payload.model_dump(),
        "intervention_number": intervention_number,
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
async def me_list_notes(kind: str, user: dict = Depends(get_current_user)):
    coll = _user_notes_collection(kind)
    items = await coll.find({"owner_id": user["id"]}, {"_id": 0}).sort("updated_at", -1).to_list(2000)
    return items


@api.post("/me/notes/{kind}", tags=["Portail Client"])
async def me_create_note(kind: str, payload: UserNoteCreate, user: dict = Depends(get_current_user)):
    coll = _user_notes_collection(kind)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre requis")
    doc = {
        "id": _uuid(),
        "kind": kind,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "title": title,
        "content_html": payload.content_html or "",
        "tags": payload.tags or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    await coll.insert_one(doc.copy())
    doc.pop("_id", None)
    _fire_notes_webhook_bg("created", kind, doc, user)
    return doc


@api.put("/me/notes/{kind}/{note_id}", tags=["Portail Client"])
async def me_update_note(kind: str, note_id: str, payload: UserNoteUpdate, user: dict = Depends(get_current_user)):
    coll = _user_notes_collection(kind)
    existing = await coll.find_one({"id": note_id, "owner_id": user["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Note introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await coll.update_one({"id": note_id}, {"$set": update})
    refreshed = await coll.find_one({"id": note_id}, {"_id": 0}) or {**existing, **update}
    _fire_notes_webhook_bg("updated", kind, refreshed, user)
    return {"ok": True}


@api.delete("/me/notes/{kind}/{note_id}", tags=["Portail Client"])
async def me_delete_note(kind: str, note_id: str, user: dict = Depends(get_current_user)):
    coll = _user_notes_collection(kind)
    existing = await coll.find_one({"id": note_id, "owner_id": user["id"]}, {"_id": 0})
    res = await coll.delete_one({"id": note_id, "owner_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Note introuvable")
    if existing:
        _fire_notes_webhook_bg("deleted", kind, existing, user)
    return {"ok": True}


@api.get("/me/notes-summary", tags=["Portail Client"])
async def me_notes_summary(user: dict = Depends(get_current_user)):
    """Returns counts and last update timestamps to display dashboard buttons."""
    rep_count = await db.user_reports.count_documents({"owner_id": user["id"]})
    sui_count = await db.user_suivis.count_documents({"owner_id": user["id"]})
    rep_last = await db.user_reports.find_one({"owner_id": user["id"]}, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    sui_last = await db.user_suivis.find_one({"owner_id": user["id"]}, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    return {
        "reports": {"count": rep_count, "last_updated": (rep_last or {}).get("updated_at")},
        "suivis": {"count": sui_count, "last_updated": (sui_last or {}).get("updated_at")},
    }


# ====================================================================
# ADMIN - Settings
# ====================================================================
@api.get("/admin/settings", tags=["Admin"])
async def admin_get_settings(_: dict = Depends(get_current_admin)):
    s = await _get_settings_doc()
    # mask sensitive
    masked = dict(s)
    for k in ("smtp_password", "google_client_secret", "recaptcha_secret_key", "google_calendar_password_hint", "tracking_auth_header", "webhook_token", "webhook_basic_pass", "notes_webhook_token", "notes_webhook_basic_pass"):
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


@app.on_event("shutdown")
async def on_shutdown():
    pass
