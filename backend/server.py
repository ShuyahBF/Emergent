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
import shutil
import uuid
import logging
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List

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
    # Look for overlapping non-cancelled appointments
    existing = await db.appointments.find(
        {"status": {"$in": ["pending", "confirmed"]}}, {"_id": 0}
    ).to_list(2000)
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

    # Pre-load taken intervals
    appts = await db.appointments.find(
        {"status": {"$in": ["pending", "confirmed"]}}, {"_id": 0}
    ).to_list(2000)
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
# ADMIN - Clients
# ====================================================================
@api.get("/admin/clients", tags=["Admin"])
async def admin_list_clients(_: dict = Depends(get_current_admin)):
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(2000)
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
        "account_status": payload.account_status,
        "created_at": _now(),
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
    if payload.password:
        update["password_hash"] = hash_password(payload.password)
    update["updated_at"] = _now()
    await db.users.update_one({"id": client_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/clients/{client_id}", tags=["Admin"])
async def admin_delete_client(client_id: str, _: dict = Depends(get_current_admin)):
    await db.users.delete_one({"id": client_id, "role": "client"})
    return {"ok": True}


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
    doc = {"id": _uuid(), **payload.model_dump(), "created_at": _now()}
    await db.interventions.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/interventions/{int_id}", tags=["Admin"])
async def admin_update_intervention(
    int_id: str, payload: InterventionUpdate, _: dict = Depends(get_current_admin)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await db.interventions.update_one({"id": int_id}, {"$set": update})
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


# ====================================================================
# ADMIN - File upload
# ====================================================================
@api.post("/admin/upload", tags=["Admin"])
async def admin_upload(file: UploadFile = File(...), _: dict = Depends(get_current_admin)):
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
        "content_type": file.content_type or mimetypes.guess_type(file.filename or "")[0],
        "size": size,
        "url": f"/api/files/{file_id}",
        "uploaded_at": _now(),
    }
    await db.files.insert_one(file_doc.copy())
    file_doc.pop("_id", None)
    return file_doc


@api.get("/files/{file_id}", tags=["Public"])
async def serve_file(file_id: str):
    meta = await db.files.find_one({"id": file_id}, {"_id": 0})
    if not meta:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    path = UPLOAD_DIR / meta["stored_name"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(path, media_type=meta.get("content_type") or "application/octet-stream", filename=meta.get("filename"))


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
    doc = {"id": _uuid(), **payload.model_dump(), "created_at": _now()}
    await db.tracked_users.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/tracked-users/{tu_id}", tags=["Admin"])
async def admin_update_tracked(tu_id: str, payload: TrackedUserUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await db.tracked_users.update_one({"id": tu_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/tracked-users/{tu_id}", tags=["Admin"])
async def admin_delete_tracked(tu_id: str, _: dict = Depends(get_current_admin)):
    await db.tracked_users.delete_one({"id": tu_id})
    return {"ok": True}


# ====================================================================
# ADMIN - Contacts inbox
# ====================================================================
@api.get("/admin/contacts", tags=["Admin"])
async def admin_contacts(_: dict = Depends(get_current_admin)):
    items = await db.contacts.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


# ====================================================================
# ADMIN - Settings
# ====================================================================
@api.get("/admin/settings", tags=["Admin"])
async def admin_get_settings(_: dict = Depends(get_current_admin)):
    s = await _get_settings_doc()
    # mask sensitive
    masked = dict(s)
    for k in ("smtp_password", "google_client_secret", "recaptcha_secret_key", "google_calendar_password_hint"):
        if masked.get(k):
            masked[k] = "********"
    masked["google_calendar_connected"] = bool((await db.settings.find_one({"_id": "global"}) or {}).get("google_refresh_token"))
    return masked


@api.put("/admin/settings", tags=["Admin"])
async def admin_update_settings(payload: SettingsUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
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
    if not await db.settings.find_one({"_id": "global"}):
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
            }
        )

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
