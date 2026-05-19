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
import gzip
import hashlib
import hmac
import base64
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
    Body,
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
    TicketOpenPayload,
    TicketUpdatePayload,
    TicketClosePayload,
    TicketAssignPayload,
    TicketReopenPayload,
    TicketMotifTemplatePayload,
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
from email_service import send_otp_email, send_email
from recaptcha import verify_recaptcha
import google_calendar as gcal


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
POLICIES_DIR = UPLOAD_DIR / "policies"
POLICIES_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
# Iter35u — DB-backed override for the public base URL. Refreshed on startup
# and after every PUT /admin/settings. Takes precedence over the env var,
# but request-supplied Origin/X-Forwarded-Host still wins (so per-host calls
# stay accurate even when an admin browses from the preview vs. production).
_PUBLIC_BASE_URL_DB: str = ""


# ---------- Iter35n — Version stamp ----------
# Surfaced via GET /api/version so the login page (and any UI) can display
# which build is currently deployed. We compute it once at import time:
#   - APP_VERSION    : human-readable tag (env var, falls back to "iter35n")
#   - APP_GIT_SHA    : short git SHA of /app (best-effort, "unknown" if not a repo)
#   - APP_BUILT_AT   : ISO timestamp of the latest commit (best-effort) or process start
#   - APP_STARTED_AT : ISO timestamp the FastAPI process booted (always set)
APP_VERSION = os.environ.get("APP_VERSION", "1.0")
APP_STARTED_AT = datetime.now(timezone.utc).isoformat()
try:
    import subprocess as _subproc
    _root = Path(__file__).resolve().parent.parent
    APP_GIT_SHA = _subproc.check_output(
        ["git", "-C", str(_root), "rev-parse", "--short", "HEAD"],
        stderr=_subproc.DEVNULL,
    ).decode("ascii", errors="ignore").strip() or "unknown"
    APP_BUILT_AT = _subproc.check_output(
        ["git", "-C", str(_root), "log", "-1", "--format=%cI"],
        stderr=_subproc.DEVNULL,
    ).decode("ascii", errors="ignore").strip() or None
except Exception:  # noqa: BLE001
    APP_GIT_SHA = "unknown"
    APP_BUILT_AT = None


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
    # Iter35u — DB override beats the static env var (admin-editable from
    # the Coffre-fort des secrets).
    if _PUBLIC_BASE_URL_DB:
        return _PUBLIC_BASE_URL_DB.rstrip("/")
    return (PUBLIC_BASE_URL or "").rstrip("/")


async def _refresh_public_base_url_cache() -> None:
    """Pull the DB-stored public_base_url into the in-memory cache so the
    sync `_public_base_url()` helper can use it without an await."""
    global _PUBLIC_BASE_URL_DB
    try:
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "public_base_url": 1}) or {}
        val = (s.get("public_base_url") or "").strip()
        _PUBLIC_BASE_URL_DB = val
    except Exception:  # noqa: BLE001
        # First startup may run before the DB is reachable — ignore.
        pass

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


async def _migrate_orphan_client_data(dry_run: bool = False) -> Dict[str, Any]:
    """Re-tag CRM data orphaned by the iter24 ``client_id`` mirror migration.

    Bridged tracked-user accounts had their ``users.client_id`` switched from
    empty to ``parent_client_id`` in iter24. Historical rows (contacts,
    messages, schedules, payment links) created BEFORE that mirror are still
    tagged with the user's OWN ``id`` (because the legacy creation path
    resolved scope as ``user.client_id || user.id`` and fell through to the
    user id). Those rows are now invisible to the user after the mirror.

    This function reassigns ``client_id`` to the parent_client_id on every
    affected document, and stores the previous value in ``client_id_legacy``
    for traceability and reversibility. The legacy field also acts as the
    idempotency guard so the migration is safe to re-run.

    When ``dry_run=True``, no writes happen — the function returns the counts
    of documents that **would** be migrated. Useful from the admin endpoint
    before applying.
    """
    collections = [
        "directory_contacts",
        "whatsapp_messages",
        "sms_messages",
        "whatsapp_schedules",
        "payment_links",
    ]
    per_user: List[Dict[str, Any]] = []
    totals = {c: 0 for c in collections}
    grand_total = 0
    bridged_cur = db.users.find(
        {
            "role": "client",
            "parent_client_id": {"$exists": True, "$nin": [None, ""]},
        },
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "parent_client_id": 1},
    )
    async for u in bridged_cur:
        uid = u.get("id")
        pid = u.get("parent_client_id")
        if not uid or not pid or uid == pid:
            # Skip rows where the user is its own parent or fields missing
            continue
        per_coll: Dict[str, int] = {}
        for coll_name in collections:
            q = {"client_id": uid, "client_id_legacy": {"$exists": False}}
            if dry_run:
                cnt = await db[coll_name].count_documents(q)
            else:
                res = await db[coll_name].update_many(
                    q,
                    {"$set": {"client_id": pid, "client_id_legacy": uid}},
                )
                cnt = int(getattr(res, "modified_count", 0) or 0)
            per_coll[coll_name] = cnt
            totals[coll_name] += cnt
            grand_total += cnt
        if any(v > 0 for v in per_coll.values()):
            per_user.append({
                "user_id": uid,
                "user_email": u.get("email"),
                "user_label": u.get("full_name") or u.get("email"),
                "parent_client_id": pid,
                "per_collection": per_coll,
            })
    return {
        "dry_run": dry_run,
        "per_collection_totals": totals,
        "total_migrated": grand_total,
        "affected_users": per_user,
    }


async def _next_contact_unique_code(client_doc: dict) -> str:
    """Generate a stable, never-reissued unique code for a CRM contact.
    Format: ``YYYY-CODE-NNNN`` where CODE is the parent client's slug (or
    ``client_code`` if defined) and NNNN is a sequential per-client/per-year
    counter. Once assigned to a contact, this code MUST NOT change — it is the
    inalterable business identifier displayed in the directory and on
    documents (invoices, quotes, etc.).
    """
    year = datetime.now(timezone.utc).year
    code = (client_doc.get("client_code") or "").strip()
    if not code:
        code = _slugify_code(client_doc.get("company") or client_doc.get("full_name") or "X")
    counter_id = f"contact:{client_doc['id']}:{year}"
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    if res is None:
        res = await db.counters.find_one({"_id": counter_id})
    seq = (res or {}).get("seq", 1)
    return f"{year}-{code}-{seq:04d}"


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


# ============================================================
# Iter35h — Demo role enforcement.
# A `demo` user has hard usage quotas (WA / SMS / IA / Whisper / contacts /
# payments / storage) and an expiration date. Each quota-bound endpoint
# calls `_enforce_demo_quota(user, key)` BEFORE the action; the helper
# raises 403 with a clear French message when the quota is reached.
# Counters live on the user doc itself (`demo_usage`).
# ============================================================
QUOTA_KEY_WA = "whatsapp_sends"
QUOTA_KEY_SMS = "sms_sends"
QUOTA_KEY_AI = "ai_generations"
QUOTA_KEY_TRANSCRIBE = "transcriptions"
QUOTA_KEY_CONTACTS = "directory_contacts"
QUOTA_KEY_PAYMENTS = "payments"
QUOTA_KEY_STORAGE = "attachments_bytes"


def _is_demo(user: dict) -> bool:
    return (user or {}).get("role") == "demo"


def _demo_quota_for(user: dict, key: str) -> int:
    """Resolve the configured limit for the user. Falls back to defaults
    from models.DEMO_DEFAULT_QUOTAS if no override is present on the doc."""
    from models import DEMO_DEFAULT_QUOTAS  # local import to avoid circular at module top
    overrides = (user or {}).get("demo_quotas") or {}
    if key in overrides:
        try:
            return int(overrides[key])
        except (TypeError, ValueError):
            pass
    return int(DEMO_DEFAULT_QUOTAS.get(key, 0))


async def _demo_usage(user_id: str) -> Dict[str, int]:
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "demo_usage": 1}) or {}
    return dict((u.get("demo_usage") or {}))


async def _enforce_demo_quota(user: dict, key: str, *, increment: int = 1) -> Dict[str, Any]:
    """Atomic check-and-increment of a demo quota counter.

    For numeric usage (`increment >= 1`): if usage + increment exceeds the
    quota, raises 403 with the current/limit values. Otherwise increments
    the counter and returns the new state.

    For storage (`key == QUOTA_KEY_STORAGE`): `increment` is the byte size
    to add — same check/inc semantics.

    For DB-row caps (e.g. `directory_contacts`): pass increment=0 and the
    helper re-counts the live row count instead of incrementing (so the
    check is always accurate even if rows were deleted).
    """
    if not _is_demo(user):
        return {"is_demo": False, "ok": True}
    limit = _demo_quota_for(user, key)
    # Quota = 0 means "feature disabled outright"
    if limit <= 0 and increment > 0:
        raise HTTPException(
            status_code=403,
            detail=f"Compte de démonstration — fonctionnalité « {key} » désactivée.",
        )
    usage = await _demo_usage(user["id"])
    if key == QUOTA_KEY_CONTACTS:
        # Live row count, ignore the stored counter
        current = await db.directory_contacts.count_documents({
            "client_id": user["id"],
        })
    else:
        current = int(usage.get(key, 0))
    new_total = current + max(0, int(increment))
    if new_total > limit:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Quota démo atteint pour « {key} » : {current}/{limit}. "
                "Contactez l'administrateur pour passer en compte standard."
            ),
        )
    if increment > 0 and key != QUOTA_KEY_CONTACTS:
        # Atomic $inc; we don't care about the prior value beyond the check above
        await db.users.update_one(
            {"id": user["id"]},
            {"$inc": {f"demo_usage.{key}": int(increment)}, "$set": {"updated_at": _now()}},
        )
    return {"is_demo": True, "ok": True, "key": key, "before": current, "after": new_total, "limit": limit}


def _demo_is_expired(user: dict) -> bool:
    if not _is_demo(user):
        return False
    exp = (user or {}).get("demo_expires_at")
    if not exp:
        return False
    try:
        dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > dt
    except Exception:
        return False




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


@api.get("/version", tags=["Santé"])
async def version():
    """Iter35n — Public version stamp. Surfaced on the login page so users
    can confirm which build they are about to authenticate against. Always
    returns 200 (never auth-protected); contains no secrets."""
    return {
        "version": APP_VERSION,
        "git_sha": APP_GIT_SHA,
        "built_at": APP_BUILT_AT,
        "started_at": APP_STARTED_AT,
    }


# ====================================================================
# AUTH
# ====================================================================
@api.post("/auth/login", response_model=LoginResponse, tags=["Authentification"])
async def auth_login(payload: LoginRequest, request: Request):
    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    if user.get("account_status") != "active":
        raise HTTPException(status_code=403, detail="Compte désactivé")

    captcha = await verify_recaptcha(payload.captcha_token, request=request)
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
    # Resolve OTP delivery mode: internal-domain users get the code shown on
    # the login page (no SMTP cost / round-trip) — everyone else gets an email.
    email_domain = (user["email"].split("@", 1)[-1] or "").lower().strip()
    settings_doc = await db.settings.find_one({"_id": "global"}) or {}
    internal_list = [
        d.strip().lower().lstrip("@")
        for d in (settings_doc.get("internal_domains") or "sawalismartsystems.com").split(",")
        if d.strip()
    ]
    is_internal_user = email_domain in internal_list
    if is_internal_user:
        dev_otp = code  # always revealed on the page
        sent = False
        msg = "Plateforme Interne : code OTP affiché directement sur la page."
    else:
        sent = await send_otp_email(user["email"], user["full_name"], code)
        dev_otp = None if sent else code
        msg = (
            "Un code de vérification a été envoyé à votre adresse email."
            if sent
            else "Service e-mail indisponible : code OTP affiché ci-dessous (à usage unique)."
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
    # Respect the same internal-domain rule as /auth/login
    email_domain = (user["email"].split("@", 1)[-1] or "").lower().strip()
    settings_doc = await db.settings.find_one({"_id": "global"}) or {}
    internal_list = [
        d.strip().lower().lstrip("@")
        for d in (settings_doc.get("internal_domains") or "sawalismartsystems.com").split(",")
        if d.strip()
    ]
    if email_domain in internal_list:
        return {"sent": False, "dev_otp": new_code}
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


# ============================================================
# Support Technique — Load Gauge (0..7) — public + admin + webhook
# Mirrors the "cellular signal bars" UX so users instantly grasp the
# current support team load. Set via Admin UI or POST webhook.
# ============================================================
def _clamp_load(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return max(0, min(7, n))


@api.get("/public/support-load", tags=["Public"])
async def public_support_load():
    s = await db.settings.find_one({"_id": "global"}) or {}
    level = _clamp_load(s.get("support_load_level"))
    threshold = _clamp_load(s.get("liluvine_alert_threshold") or 6)
    liluvine_alert_enabled = bool(s.get("liluvine_alert_enabled"))
    alert_active = liluvine_alert_enabled and bool(s.get("support_load_enabled")) and level >= threshold and threshold > 0
    return {
        "enabled": bool(s.get("support_load_enabled")),
        "level": level,
        "label": s.get("support_load_label") or "",
        "updated_at": s.get("support_load_updated_at"),
        "liluvine": {
            "alert_enabled": liluvine_alert_enabled,
            "threshold": threshold,
            "alert_active": alert_active,
            "label": (s.get("liluvine_alert_label") or "").strip() if alert_active else None,
            "message": (s.get("liluvine_alert_message") or "").strip() if alert_active else None,
        },
    }


class AdminSupportLoadUpdate(BaseModel):
    level: int
    label: Optional[str] = None
    enabled: Optional[bool] = None


@api.post("/admin/support-load", tags=["Admin"])
async def admin_set_support_load(payload: AdminSupportLoadUpdate, user: dict = Depends(get_current_admin)):
    update: Dict[str, Any] = {
        "support_load_level": _clamp_load(payload.level),
        "support_load_updated_at": _now(),
        "support_load_updated_by": user.get("email"),
    }
    if payload.label is not None:
        update["support_load_label"] = (payload.label or "")[:140]
    if payload.enabled is not None:
        update["support_load_enabled"] = bool(payload.enabled)
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    return {"ok": True, **update}


@api.api_route("/webhooks/support-load/{secret}", methods=["GET", "POST"], tags=["Webhooks"])
async def webhook_support_load(secret: str, request: Request):
    """External webhook to push the current support load (0..7).
    GET ?level=N[&label=...]  OR  POST JSON {level, label}.
    Useful from monitoring (Zabbix/Grafana/Freshdesk/Zendesk/n8n)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    expected = (s.get("support_load_webhook_secret") or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Secret invalide")
    level = None
    label = None
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        level = body.get("level") if isinstance(body, dict) else None
        label = body.get("label") if isinstance(body, dict) else None
    if level is None:
        level = request.query_params.get("level")
    if label is None:
        label = request.query_params.get("label")
    if level is None:
        raise HTTPException(status_code=400, detail="Paramètre 'level' requis (0..7)")
    update: Dict[str, Any] = {
        "support_load_level": _clamp_load(level),
        "support_load_updated_at": _now(),
        "support_load_updated_by": "webhook",
        "support_load_enabled": True,
    }
    if label is not None:
        update["support_load_label"] = (str(label) or "")[:140]
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    return {"ok": True, "level": update["support_load_level"], "label": update.get("support_load_label")}




# ============================================================
# Liluvine smart redirect — remote control via signed link or
# WhatsApp command. Generates short-lived HMAC tokens that can be
# bookmarked from the admin's mobile to flip the threshold/level
# without going through the login screen.
# ============================================================
def _liluvine_secret(s: Dict[str, Any]) -> str:
    """Return the per-install HMAC secret. Auto-generates one on first use."""
    sec = (s.get("liluvine_remote_secret") or "").strip()
    return sec


def _liluvine_sign(secret: str, payload: Dict[str, Any]) -> str:
    """Sign a JSON payload with HMAC-SHA256 → returns urlsafe base64 token."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}|{sig}".encode("utf-8")).decode("utf-8").rstrip("=")


def _liluvine_verify(secret: str, token: str) -> Optional[Dict[str, Any]]:
    if not token or not secret:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        body, sig = raw.rsplit("|", 1)
        expected = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        data = json.loads(body)
        # Expiry check
        exp = data.get("exp")
        if exp and datetime.now(timezone.utc) > datetime.fromisoformat(str(exp).replace("Z", "+00:00")):
            return None
        return data
    except Exception:  # noqa: BLE001
        return None


class AdminRemoteLinkRequest(BaseModel):
    ttl_hours: Optional[int] = 720  # default 30 days


@api.post("/admin/liluvine/remote-link", tags=["Admin"])
async def admin_liluvine_remote_link(payload: AdminRemoteLinkRequest, request: Request, user: dict = Depends(get_current_admin)):
    """Generate a long-lived signed link to control Liluvine threshold + level
    from a phone bookmark — without going through the login screen."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    secret = _liluvine_secret(s)
    if not secret:
        secret = secrets.token_urlsafe(32)
        await db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_remote_secret": secret}}, upsert=True)
    ttl = max(1, min(int(payload.ttl_hours or 720), 24 * 365))
    exp = (datetime.now(timezone.utc) + timedelta(hours=ttl)).isoformat()
    token = _liluvine_sign(secret, {
        "scope": "liluvine",
        "issued_at": _now(),
        "issued_by": user.get("email"),
        "exp": exp,
    })
    base_url = str(request.base_url).rstrip("/")
    # The remote console is a public React route → use frontend base
    public_origin = request.headers.get("origin") or request.headers.get("referer") or base_url
    if "://" in public_origin:
        public_origin = "://".join(public_origin.split("://")[:1] + [public_origin.split("://")[1].split("/")[0]])
    url = f"{public_origin}/remote/support/{token}"
    return {"ok": True, "url": url, "token": token, "expires_at": exp}


class RemoteSupportUpdate(BaseModel):
    level: Optional[int] = None  # 0..7
    threshold: Optional[int] = None  # 0..7
    label: Optional[str] = None  # support_load_label (the "main gauge" label)


@api.get("/public/remote/support/{token}", tags=["Public"])
async def public_remote_support_state(token: str):
    """Inspect the current support load + Liluvine config — gated by HMAC token."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    secret = _liluvine_secret(s)
    if not _liluvine_verify(secret, token):
        raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
    return {
        "support_load_enabled": bool(s.get("support_load_enabled")),
        "support_load_level": _clamp_load(s.get("support_load_level")),
        "support_load_label": s.get("support_load_label") or "",
        "liluvine_alert_threshold": _clamp_load(s.get("liluvine_alert_threshold") or 6),
        "liluvine_alert_enabled": bool(s.get("liluvine_alert_enabled")),
        "alert_active": (
            bool(s.get("liluvine_alert_enabled"))
            and bool(s.get("support_load_enabled"))
            and _clamp_load(s.get("support_load_level")) >= _clamp_load(s.get("liluvine_alert_threshold") or 6)
        ),
        "updated_at": s.get("support_load_updated_at"),
    }


@api.post("/public/remote/support/{token}", tags=["Public"])
async def public_remote_support_update(token: str, payload: RemoteSupportUpdate, request: Request):
    s = await db.settings.find_one({"_id": "global"}) or {}
    secret = _liluvine_secret(s)
    verified = _liluvine_verify(secret, token)
    if not verified:
        raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
    update: Dict[str, Any] = {"support_load_updated_at": _now(), "support_load_updated_by": f"remote-link({verified.get('issued_by') or 'admin'})"}
    if payload.level is not None:
        update["support_load_level"] = _clamp_load(payload.level)
        update["support_load_enabled"] = True
    if payload.threshold is not None:
        update["liluvine_alert_threshold"] = _clamp_load(payload.threshold)
    if payload.label is not None:
        update["support_load_label"] = (payload.label or "")[:140]
    if not any(k in update for k in ("support_load_level", "liluvine_alert_threshold", "support_load_label")):
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    # Audit trail
    await db.api_traces.insert_one({
        "id": _uuid(), "method": "REMOTE_LILUVINE", "url": "/public/remote/support",
        "module": "liluvine-remote", "status": 200, "ip": _client_ip_from_request(request),
        "request_body": {**payload.model_dump(), "issued_by": verified.get("issued_by")},
        "created_at": _now(),
    })
    return {"ok": True, **{k: v for k, v in update.items() if not k.startswith("support_load_updated")}}


async def _try_handle_liluvine_wa_command(from_phone: str, message_text: str) -> Optional[str]:
    """When a WhatsApp message comes from an allow-listed admin phone and
    starts with `!seuil` or `!niveau` (or `!load`), tweak the gauge live.
    Returns a status string for logging or None if no command was found."""
    if not message_text:
        return None
    text = message_text.strip()
    m = re.match(r"^[!/](?:seuil|niveau|level|threshold|load)\s+(-?\d+)\b\s*(.*)$", text, re.IGNORECASE)
    if not m:
        return None
    s = await db.settings.find_one({"_id": "global"}) or {}
    allowed = s.get("liluvine_remote_admin_phones") or []
    digits = "".join(ch for ch in (from_phone or "") if ch.isdigit())
    allowed_norm = {"".join(ch for ch in str(p) if ch.isdigit()) for p in allowed if p}
    if digits not in allowed_norm:
        return f"refused:{digits}"
    n = _clamp_load(m.group(1))
    extra = (m.group(2) or "").strip()
    cmd = re.match(r"^[!/](\w+)", text).group(1).lower()
    update: Dict[str, Any] = {"support_load_updated_at": _now(), "support_load_updated_by": f"wa({digits})"}
    if cmd in ("seuil", "threshold"):
        update["liluvine_alert_threshold"] = n
    else:
        update["support_load_level"] = n
        update["support_load_enabled"] = True
        if extra:
            update["support_load_label"] = extra[:140]
    await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    await db.api_traces.insert_one({
        "id": _uuid(), "method": "WA_LILUVINE", "url": "/whatsapp/webhook",
        "module": "liluvine-wa-cmd", "status": 200,
        "request_body": {"cmd": cmd, "value": n, "from": digits, "extra": extra},
        "created_at": _now(),
    })
    return f"ok:{cmd}={n}"





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
        "version_stamp": {
            "color": s.get("version_stamp_color") or "",
            "size": s.get("version_stamp_size") or "xs",
            "opacity": int(s.get("version_stamp_opacity") or 70),
            "style": s.get("version_stamp_style") or "normal",
        },
        "policy": {
            "contacts_require_tag": bool(s.get("contacts_require_tag", False)),
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


@api.get("/me/account-detail", tags=["Portail Client"])
async def me_account_detail(user: dict = Depends(get_current_user)):
    """Iter34k — Read-only account profile shown in the user-menu "Mon
    compte" page. Returns identity + company hierarchy + phone numbers +
    last-login (excluding the current session) + counters for Rapports,
    Suivis, Contacts (shared by the same company/client).
    """
    parent_id = user.get("parent_client_id") or user.get("client_id") or user.get("id")
    # Parent client information (employer/company owner)
    parent = await db.users.find_one(
        {"id": parent_id}, {"_id": 0, "full_name": 1, "company": 1, "email": 1}
    ) if parent_id and parent_id != user.get("id") else None
    # Previous login: ignore the very last access_log row (current session)
    prev_logins_cursor = db.access_logs.find(
        {"user_email": (user.get("email") or "").lower()},
        {"_id": 0, "created_at": 1},
    ).sort("created_at", -1).limit(2)
    prev_logins = [r async for r in prev_logins_cursor]
    last_seen = prev_logins[1]["created_at"] if len(prev_logins) >= 2 else None

    # Counters scoped to the user's effective client_id span
    client_ids = await _resolve_visible_client_ids(user)
    reports_count = await db.user_reports.count_documents({"user_id": user["id"]})
    suivis_count = await db.user_suivis.count_documents({"user_id": user["id"]})
    contacts_count = await db.directory_contacts.count_documents(
        {"client_id": {"$in": client_ids}}
    )

    return {
        "identity": {
            "full_name": user.get("full_name"),
            "email": user.get("email"),
            "role": user.get("role"),
            "phone": user.get("phone"),
            "whatsapp": user.get("whatsapp") or user.get("phone"),
            "avatar_url": user.get("avatar_url"),
            "company": user.get("company"),
            "birth_date": user.get("birth_date"),
        },
        "parent_client": {
            "id": parent_id if parent else None,
            "full_name": parent.get("full_name") if parent else None,
            "company": parent.get("company") if parent else None,
            "email": parent.get("email") if parent else None,
        } if parent else None,
        "last_seen_at": last_seen,
        "counters": {
            "reports": reports_count,
            "suivis": suivis_count,
            "contacts": contacts_count,
        },
    }


@api.post("/me/profile-update-request", tags=["Portail Client"])
async def me_request_profile_update(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    """Iter34k — Submit a free-form request to the admin to correct identity,
    surname spelling, birth date, phone numbers, etc. Stored in
    `db.profile_update_requests` for admin review; admin sees them in
    `/admin/settings` (separate section in a follow-up iter)."""
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Le message est obligatoire")
    if len(message) > 1500:
        raise HTTPException(status_code=400, detail="Message trop long (1500 caractères max)")
    fields = payload.get("fields") or []
    if not isinstance(fields, list):
        fields = []
    doc = {
        "id": _uuid(),
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_full_name": user.get("full_name"),
        "company": user.get("company"),
        "parent_client_id": user.get("parent_client_id") or user.get("client_id"),
        "fields": [str(f)[:60] for f in fields[:10]],
        "message": message,
        "status": "pending",
        "created_at": _now(),
        "resolved_at": None,
        "admin_note": "",
    }
    await db.profile_update_requests.insert_one(doc)
    out = dict(doc)
    out.pop("_id", None)
    return out


# ----- Admin side (Iter34l) ---------------------------------------------
@api.get("/admin/profile-requests", tags=["Admin"])
async def admin_profile_requests_list(
    status: str = "all",
    limit: int = 200,
    _: dict = Depends(get_current_admin),
):
    """Iter34l — List user-submitted requests to update their own profile.
    `status` = pending | processed | all. Newest first."""
    q: Dict[str, Any] = {}
    if status in ("pending", "processed"):
        q["status"] = status
    items = await db.profile_update_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(max(1, min(int(limit or 200), 1000)))
    pending_count = await db.profile_update_requests.count_documents({"status": "pending"})
    return {"items": items, "pending_count": pending_count}


@api.patch("/admin/profile-requests/{req_id}", tags=["Admin"])
async def admin_profile_requests_update(
    req_id: str,
    payload: Dict[str, Any] = Body(...),
    admin: dict = Depends(get_current_admin),
):
    """Iter34l — Mark a profile-update request as processed (or back to pending)
    and optionally attach an admin note."""
    existing = await db.profile_update_requests.find_one({"id": req_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    update: Dict[str, Any] = {}
    if "status" in payload:
        new_status = (payload.get("status") or "").strip().lower()
        if new_status not in ("pending", "processed"):
            raise HTTPException(status_code=400, detail="Statut invalide (pending | processed)")
        update["status"] = new_status
        update["resolved_at"] = _now() if new_status == "processed" else None
        update["resolved_by_email"] = admin.get("email") if new_status == "processed" else None
    if "admin_note" in payload:
        note = (payload.get("admin_note") or "").strip()
        if len(note) > 2000:
            raise HTTPException(status_code=400, detail="Note trop longue (2000 caractères max)")
        update["admin_note"] = note
    if not update:
        raise HTTPException(status_code=400, detail="Rien à mettre à jour")
    await db.profile_update_requests.update_one({"id": req_id}, {"$set": update})
    out = await db.profile_update_requests.find_one({"id": req_id}, {"_id": 0})
    return out


@api.get("/me/appointments", tags=["Portail Client"])
async def me_appointments(user: dict = Depends(get_current_user)):
    """All users belonging to the same client see the same set of RDV.
    Admin/superviseur see everything. RGPD: anonymizes customer fields per
    parent-client flags for non-privileged roles."""
    if user.get("role") in ("admin", "superviseur"):
        items = await db.appointments.find({}, {"_id": 0}).to_list(2000)
    else:
        scope = user.get("client_id") or user["id"]
        items = await db.appointments.find({"client_id": scope}, {"_id": 0}).to_list(2000)
    items = await _maybe_anon_list(user, items, _apply_anon_to_appointment)
    return sorted(items, key=lambda x: x["scheduled_at"], reverse=True)


# ============================================================
# n8n Agenda Agent — outbound webhook notifications
# Fired (best-effort, non-blocking) on every manual appointment CRUD so
# the n8n AI workflow can sync external systems / notify the user.
# Inbound endpoint: POST /webhooks/agenda/{secret}
# ============================================================
async def _fire_agenda_n8n(action: str, appointment: Dict[str, Any], user: Optional[Dict[str, Any]] = None) -> None:
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not s.get("agenda_n8n_outbound_enabled"):
        return
    url = (s.get("agenda_n8n_outbound_url") or "").strip()
    if not url:
        return
    headers = {"Content-Type": "application/json"}
    auth = None
    auth_type = (s.get("agenda_n8n_outbound_auth_type") or "none").lower()
    if auth_type == "bearer":
        tok = (s.get("agenda_n8n_outbound_token") or "").strip()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
    elif auth_type == "basic":
        bu = (s.get("agenda_n8n_outbound_basic_user") or "").strip()
        bp = (s.get("agenda_n8n_outbound_basic_pass") or "").strip()
        if bu and bp:
            auth = (bu, bp)
    safe_appt = {k: v for k, v in appointment.items() if k != "_id"}
    payload = {
        "type": "agenda",
        "action": action,  # created | updated | deleted | reactor
        "appointment": safe_appt,
        "user": (
            {
                "id": user.get("id"),
                "email": user.get("email"),
                "full_name": user.get("full_name"),
                "client_id": user.get("client_id") or user.get("id"),
                "role": user.get("role"),
            }
            if user
            else None
        ),
        "fired_at": _now(),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            await http.post(url, headers=headers, auth=auth, json=payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[agenda-n8n outbound] %s — %s", action, exc)


class AgendaWebhookCreate(BaseModel):
    action: str  # "create" | "update" | "delete" | "list"
    client_email: Optional[str] = None  # used to scope when the AI agent acts on behalf of a user
    appointment_id: Optional[str] = None  # required for update/delete
    subject: Optional[str] = None
    message: Optional[str] = None
    scheduled_at: Optional[str] = None  # ISO-8601
    duration_min: Optional[int] = None
    status: Optional[str] = None  # pending|confirmed|cancelled|completed


@api.post("/webhooks/agenda/{secret}", tags=["Webhooks"])
async def webhook_agenda_n8n(secret: str, payload: AgendaWebhookCreate, request: Request):
    """Inbound webhook from n8n AI Agent. Allows CRUD on appointments using a
    secret path token. The n8n workflow must scope by client_email when acting
    on behalf of a specific user — admin can act globally."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not s.get("agenda_n8n_inbound_enabled"):
        raise HTTPException(status_code=503, detail="Webhook entrant Agenda n8n désactivé")
    expected = (s.get("agenda_n8n_inbound_secret") or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Secret invalide")

    action = (payload.action or "").lower().strip()
    if action not in {"create", "update", "delete", "list"}:
        raise HTTPException(status_code=400, detail="Action inconnue")

    # Resolve scope: action targets a single client when client_email given
    scope_user = None
    if payload.client_email:
        scope_user = await db.users.find_one(
            {"email": payload.client_email.lower().strip()},
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "phone": 1, "company": 1, "client_id": 1, "role": 1},
        )
        if not scope_user:
            raise HTTPException(status_code=404, detail="Client introuvable")

    if action == "list":
        query = {"client_id": (scope_user.get("client_id") or scope_user["id"])} if scope_user else {}
        items = await db.appointments.find(query, {"_id": 0}).sort("scheduled_at", -1).to_list(500)
        return {"ok": True, "items": items}

    if action == "create":
        if not (payload.scheduled_at and payload.subject):
            raise HTTPException(status_code=400, detail="scheduled_at + subject requis")
        if not scope_user:
            raise HTTPException(status_code=400, detail="client_email requis pour create")
        ok, reason = await _check_slot_available(payload.scheduled_at, payload.duration_min or 30)
        if not ok:
            raise HTTPException(status_code=409, detail=reason)
        doc = {
            "id": _uuid(),
            "client_id": scope_user.get("client_id") or scope_user["id"],
            "name": scope_user["full_name"],
            "email": scope_user["email"],
            "phone": scope_user.get("phone"),
            "company": scope_user.get("company"),
            "subject": payload.subject,
            "message": payload.message,
            "scheduled_at": payload.scheduled_at,
            "duration_min": payload.duration_min or 30,
            "status": payload.status or "pending",
            "notes": None,
            "gcal_event_id": None,
            "source": "n8n",
            "created_at": _now(),
        }
        await db.appointments.insert_one(doc.copy())
        doc.pop("_id", None)
        return {"ok": True, "appointment": doc}

    if action == "update":
        if not payload.appointment_id:
            raise HTTPException(status_code=400, detail="appointment_id requis pour update")
        existing = await db.appointments.find_one({"id": payload.appointment_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
        update = {
            k: v
            for k, v in {
                "subject": payload.subject,
                "message": payload.message,
                "scheduled_at": payload.scheduled_at,
                "duration_min": payload.duration_min,
                "status": payload.status,
            }.items()
            if v is not None
        }
        update["updated_at"] = _now()
        await db.appointments.update_one({"id": payload.appointment_id}, {"$set": update})
        refreshed = await db.appointments.find_one({"id": payload.appointment_id}, {"_id": 0})
        return {"ok": True, "appointment": refreshed}

    # delete
    if not payload.appointment_id:
        raise HTTPException(status_code=400, detail="appointment_id requis pour delete")
    existing = await db.appointments.find_one({"id": payload.appointment_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    await db.appointments.delete_one({"id": payload.appointment_id})
    return {"ok": True, "deleted_id": payload.appointment_id}


# ============================================================
# PawaPay — mobile money "deposit" (encaissement) flow.
# Two API tokens stored: sandbox + production. The active token is
# selected via settings.pawapay_environment ("sandbox" | "production").
# Webhook callback : POST /api/webhooks/pawapay/{secret}
# Docs : https://docs.pawapay.io/v2/api-reference/deposits
# ============================================================
PAWAPAY_HOSTS = {
    "sandbox": "https://api.sandbox.pawapay.io",
    "production": "https://api.pawapay.io",
}


def _pawapay_str(field: Any) -> Optional[str]:
    """PawaPay v2 returns failureReason / rejectionReason as objects
    {failureCode, failureMessage} or {rejectionCode, rejectionMessage}.
    v1 sometimes returned strings. Coerce to a printable single string so
    React can render it without crashing."""
    if field is None:
        return None
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        msg = field.get("failureMessage") or field.get("rejectionMessage") or field.get("message")
        code = field.get("failureCode") or field.get("rejectionCode") or field.get("code")
        if msg and code:
            return f"{code} — {msg}"
        return msg or code or json.dumps(field)[:300]
    return str(field)[:300]


def _safe_text(field: Any, max_len: int = 300) -> Optional[str]:
    """Generic coercer for upstream API messages that may arrive as nested
    dicts or lists. Always returns a single short printable string (or None)
    so React JSX never receives a raw object → "Objects are not valid as a
    React child" crash. Use this for any value piped into the frontend that
    was originally produced by a third-party API response."""
    if field is None:
        return None
    if isinstance(field, str):
        return field[:max_len]
    if isinstance(field, dict):
        # Try common message keys first, then fall back to compact JSON
        for k in ("message", "description", "detail", "error", "errorMessage", "text"):
            v = field.get(k)
            if isinstance(v, str) and v:
                return v[:max_len]
        try:
            return json.dumps(field, default=str)[:max_len]
        except Exception:
            return str(field)[:max_len]
    if isinstance(field, list):
        try:
            return ", ".join(_safe_text(x, max_len) or "" for x in field if x is not None)[:max_len]
        except Exception:
            return str(field)[:max_len]
    return str(field)[:max_len]


def _pawapay_active_token(s: Dict[str, Any]) -> Optional[str]:
    env = (s.get("pawapay_environment") or "sandbox").lower()
    if env == "production":
        return s.get("pawapay_api_token_production") or s.get("pawapay_api_token")
    return s.get("pawapay_api_token_sandbox") or s.get("pawapay_api_token")


class PawaPayDepositCreate(BaseModel):
    amount: float
    msisdn: str  # E.164 (without leading +)
    mno: str  # ORANGE | MOOV | TELECEL
    description: Optional[str] = None


def _pawapay_correspondent(mno: str, country: str = "BFA") -> str:
    """Map MNO + country to the PawaPay "correspondent" code expected by the API.
    Fallback chain: MNO_<COUNTRY>_MTN. Burkina-specific mappings here are best-
    effort and can be overriden later via a settings field if PawaPay renames."""
    m = (mno or "").upper().strip()
    c = (country or "BFA").upper().strip()
    table = {
        "BFA": {"ORANGE": "ORANGE_BFA", "MOOV": "MOOV_BFA", "TELECEL": "TELECEL_BFA"},
    }
    return table.get(c, {}).get(m) or f"{m}_{c}"


@api.post("/me/payments/pawapay/deposit", tags=["Portail Client"])
async def me_pawapay_deposit(payload: PawaPayDepositCreate, request: Request, user: dict = Depends(get_current_user)):
    """Initiate a PawaPay deposit (collect) — the user pays. Stores a row in
    db.payments with status=pending then resolves via webhook callback."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not s.get("pawapay_enabled"):
        raise HTTPException(status_code=503, detail="PawaPay non activé")
    # Feature gating + per-client MNO whitelist
    parent_id = user.get("client_id") or user["id"]
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1, "pawapay_mnos": 1, "id": 1, "company": 1})
    if user.get("role") not in ("admin", "superviseur"):
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("payments"):
            raise HTTPException(status_code=403, detail="Paiements non autorisés pour votre client")
        allowed = _normalize_pawapay_mnos((parent or {}).get("pawapay_mnos"))
        if (payload.mno or "").upper() not in allowed:
            raise HTTPException(status_code=403, detail=f"Opérateur non autorisé. Disponibles : {', '.join(allowed)}")
    token = _pawapay_active_token(s)
    if not token:
        raise HTTPException(status_code=503, detail="Clé API PawaPay non configurée")
    env = (s.get("pawapay_environment") or "sandbox").lower()
    host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
    country = (s.get("pawapay_country") or "BFA").upper()
    deposit_id = _uuid()
    msisdn_clean = "".join(ch for ch in (payload.msisdn or "") if ch.isdigit())
    if len(msisdn_clean) < 8:
        raise HTTPException(status_code=400, detail="Numéro mobile invalide (format international attendu)")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Montant invalide")
    body = {
        "depositId": deposit_id,
        "amount": str(payload.amount),
        "currency": "XOF",
        "country": country,
        "correspondent": _pawapay_correspondent(payload.mno, country),
        "payer": {
            "type": "MSISDN",
            "address": {"value": msisdn_clean},
        },
        "customerTimestamp": _now(),
        "statementDescription": (payload.description or "SAWALI Smart Systems")[:22],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(
                f"{host}/deposits",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
            api_resp: Dict[str, Any] = {}
            try:
                api_resp = r.json()
            except Exception:
                api_resp = {"raw": r.text[:500]}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à PawaPay")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erreur PawaPay : {exc}"[:300])

    # Persist a row regardless of API outcome — the webhook (or polling) finalizes status
    api_status = (api_resp.get("status") or "").upper()
    initial_status = "pending" if api_status in ("ACCEPTED", "PENDING", "") else "failed"
    doc = {
        "id": _uuid(),
        "deposit_id": deposit_id,
        "client_id": (user.get("client_id") or user["id"]),
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_label": user.get("full_name") or user.get("email"),
        "amount": float(payload.amount),
        "currency": "XOF",
        "country": country,
        "mno": (payload.mno or "").upper(),
        "msisdn": msisdn_clean,
        "description": payload.description,
        "environment": env,
        "status": initial_status,
        "api_status": api_status or None,
        "api_message": _pawapay_str(api_resp.get("failureReason") or api_resp.get("rejectionReason") or api_resp.get("message")),
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.payments.insert_one(doc.copy())
    doc.pop("_id", None)
    if api_resp.get("status") == "REJECTED":
        return {"ok": False, "deposit_id": deposit_id, "status": "failed", "reason": _pawapay_str(api_resp.get("rejectionReason")), "payment": doc}
    return {"ok": True, "deposit_id": deposit_id, "status": initial_status, "payment": doc}


@api.get("/me/payments", tags=["Portail Client"])
async def me_list_payments(user: dict = Depends(get_current_user)):
    """List the calling user's recent payments. Admin/superviseur see all.
    Plain users see only their own (privacy : amounts can be sensitive)."""
    if user.get("role") in ("admin", "superviseur"):
        items = await db.payments.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    else:
        items = await db.payments.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@api.get("/me/payments/{deposit_id}", tags=["Portail Client"])
async def me_get_payment(deposit_id: str, user: dict = Depends(get_current_user)):
    """Polling endpoint — refreshes the payment by querying PawaPay if still pending."""
    p = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    if user.get("role") not in ("admin", "superviseur") and p.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Accès non autorisé")
    if p.get("status") not in ("pending",):
        return p
    # Live refresh
    s = await db.settings.find_one({"_id": "global"}) or {}
    token = _pawapay_active_token(s)
    if not token:
        return p
    env = (p.get("environment") or s.get("pawapay_environment") or "sandbox").lower()
    host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(f"{host}/deposits/{deposit_id}", headers={"Authorization": f"Bearer {token}"})
            arr = r.json() if r.status_code < 400 else []
            entry = arr[0] if isinstance(arr, list) and arr else (arr if isinstance(arr, dict) else {})
            api_status = (entry.get("status") or "").upper()
            new_status = {
                "COMPLETED": "completed",
                "FAILED": "failed",
                "REJECTED": "failed",
                "ACCEPTED": "pending",
                "PROCESSING": "pending",
                "SUBMITTED": "pending",
                "PENDING": "pending",
            }.get(api_status, p.get("status") or "pending")
            await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {
                "status": new_status,
                "api_status": api_status,
                "api_message": _pawapay_str(entry.get("failureReason") or entry.get("rejectionReason")),
                "completed_at": entry.get("respondedTimestamp") or (None if new_status == "pending" else _now()),
                "updated_at": _now(),
                "raw_response": entry,
            }})
            p = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pawapay-poll] %s — %s", deposit_id, exc)
    return p


@api.post("/webhooks/pawapay/{secret}", tags=["Webhooks"])
async def webhook_pawapay(secret: str, request: Request):
    """PawaPay callback — flips local status. Validated via path secret."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    expected = (s.get("pawapay_callback_secret") or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Secret invalide")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    deposit_id = payload.get("depositId") or payload.get("deposit_id")
    if not deposit_id:
        return {"ok": False, "reason": "depositId manquant"}
    api_status = (payload.get("status") or "").upper()
    new_status = {
        "COMPLETED": "completed",
        "FAILED": "failed",
        "REJECTED": "failed",
    }.get(api_status, "pending")
    await db.payments.update_one(
        {"deposit_id": deposit_id},
        {"$set": {
            "status": new_status,
            "api_status": api_status,
            "api_message": _pawapay_str(payload.get("failureReason") or payload.get("rejectionReason")),
            "completed_at": payload.get("respondedTimestamp") or _now(),
            "updated_at": _now(),
            "raw_response": payload,
        }},
    )
    return {"ok": True, "deposit_id": deposit_id, "status": new_status}


# ============================================================
# Payments Dashboard 360 — KPIs, channel attribution, conversion.
# Crosses payments + payment_links + whatsapp_messages + sms_messages.
# Channel attribution : a message containing the substring "/pay/{slug}"
# in its body is considered to have driven any payment recorded for that
# slug (best-effort heuristic — works because every link is unique).
# ============================================================
@api.get("/me/payments-dashboard", tags=["Portail Client"])
async def me_payments_dashboard(days: int = 30, user: dict = Depends(get_current_user)):
    days = max(1, min(int(days or 30), 365))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    is_admin = user.get("role") in ("admin", "superviseur")
    client_scope = (user.get("client_id") or user["id"])
    pay_q: Dict[str, Any] = {} if is_admin else {"client_id": client_scope}
    pay_q["created_at"] = {"$gte": since}
    payments = await db.payments.find(pay_q, {"_id": 0}).to_list(2000)
    links_q: Dict[str, Any] = {} if is_admin else {"client_id": client_scope}
    links = await db.payment_links.find(links_q, {"_id": 0}).to_list(1000)
    for li in links:
        li["status"] = _payment_link_status(li)
    slugs = [l["slug"] for l in links if l.get("slug")]
    by_channel = {"whatsapp": 0, "sms": 0, "direct": 0}
    sent_by_channel = {"whatsapp": 0, "sms": 0}
    if slugs:
        # Prefer the persisted payment_link_slug field (set since it. 42)
        wa_q: Dict[str, Any] = {"created_at": {"$gte": since}, "payment_link_slug": {"$in": slugs}}
        sms_q: Dict[str, Any] = {"created_at": {"$gte": since}, "payment_link_slug": {"$in": slugs}}
        if not is_admin:
            wa_q["client_id"] = client_scope
            sms_q["client_id"] = client_scope
        sent_by_channel["whatsapp"] = await db.whatsapp_messages.count_documents(wa_q)
        sent_by_channel["sms"] = await db.sms_messages.count_documents(sms_q)
    by_status = {"pending": 0, "completed": 0, "failed": 0}
    by_mno = {"ORANGE": 0, "MOOV": 0, "TELECEL": 0, "OTHER": 0}
    total_amount_completed = 0.0
    daily: Dict[str, Dict[str, float]] = {}
    for p in payments:
        st = p.get("status") or "pending"
        by_status[st] = by_status.get(st, 0) + 1
        m = (p.get("mno") or "").upper() or "OTHER"
        by_mno[m if m in by_mno else "OTHER"] += 1
        if st == "completed":
            total_amount_completed += float(p.get("amount") or 0)
        src = (p.get("source") or "").lower()
        if src == "payment_link":
            by_channel["direct"] += 1
        ts = (p.get("created_at") or "")[:10]
        if ts:
            daily.setdefault(ts, {"count": 0, "amount": 0.0})
            daily[ts]["count"] += 1
            if st == "completed":
                daily[ts]["amount"] += float(p.get("amount") or 0)
    today = datetime.now(timezone.utc).date()
    daily_arr = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        e = daily.get(d) or {"count": 0, "amount": 0.0}
        daily_arr.append({"date": d, "count": int(e["count"]), "amount": round(e["amount"], 2)})
    sorted_links = sorted(links, key=lambda x: (x.get("uses_count") or 0), reverse=True)[:5]
    top_links = [
        {
            "slug": l.get("slug"),
            "label": l.get("label"),
            "amount": l.get("amount"),
            "uses_count": l.get("uses_count") or 0,
            "max_uses": l.get("max_uses"),
            "status": l.get("status"),
        }
        for l in sorted_links
    ]
    sent_total = sent_by_channel["whatsapp"] + sent_by_channel["sms"]
    completed_count = by_status.get("completed", 0)
    conversion_rate = round(100.0 * completed_count / max(sent_total, 1), 1) if sent_total else None
    return {
        "period_days": days,
        "totals": {
            "links": len(links),
            "links_active": sum(1 for l in links if l["status"] == "active"),
            "links_disabled": sum(1 for l in links if l["status"] == "disabled"),
            "links_expired": sum(1 for l in links if l["status"] == "expired"),
            "links_exhausted": sum(1 for l in links if l["status"] == "exhausted"),
            "payments_count": len(payments),
            "payments_completed": completed_count,
            "payments_pending": by_status.get("pending", 0),
            "payments_failed": by_status.get("failed", 0),
            "amount_completed": round(total_amount_completed, 2),
        },
        "by_status": by_status,
        "by_mno": by_mno,
        "channels": {
            "sent": sent_by_channel,
            "payments_attributed": by_channel,
            "conversion_rate_pct": conversion_rate,
        },
        "daily": daily_arr,
        "top_links": top_links,
    }





# ============================================================
# Payment Links — shareable URLs that let anyone pay via PawaPay
# without having a portal account. Each link is owned by a client
# (or a tracked user of that client) and reuses the PawaPay flow.
# Public URL : /pay/{slug}  (rendered by the React app).
# ============================================================
class PaymentLinkCreate(BaseModel):
    label: str
    amount: Optional[float] = None  # None → open amount (payer chooses)
    currency: str = "XOF"
    description: Optional[str] = None
    allowed_mnos: Optional[List[str]] = None  # subset of the client's MNOs
    expires_at: Optional[str] = None  # ISO8601 UTC
    max_uses: Optional[int] = None  # None → unlimited


def _gen_slug(n: int = 8) -> str:
    import string
    alpha = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alpha) for _ in range(n))


def _payment_link_status(d: Dict[str, Any]) -> str:
    if d.get("disabled"):
        return "disabled"
    exp = d.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(str(exp).replace("Z", "+00:00")) < datetime.now(timezone.utc):
                return "expired"
        except Exception:  # noqa: BLE001
            pass
    mu = d.get("max_uses")
    if mu and (d.get("uses_count") or 0) >= mu:
        return "exhausted"
    return "active"


@api.post("/me/payment-links", tags=["Portail Client"])
async def me_create_payment_link(payload: PaymentLinkCreate, user: dict = Depends(get_current_user)):
    await _enforce_demo_quota(user, QUOTA_KEY_PAYMENTS)  # Iter35h
    parent_id = user.get("client_id") or user["id"]
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1, "pawapay_mnos": 1, "company": 1, "logo_url": 1})
    if user.get("role") not in ("admin", "superviseur"):
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("payments"):
            raise HTTPException(status_code=403, detail="Paiements non autorisés pour votre compte")
    client_mnos = _normalize_pawapay_mnos((parent or {}).get("pawapay_mnos"))
    requested = [m.upper() for m in (payload.allowed_mnos or client_mnos)]
    invalid = [m for m in requested if m not in client_mnos]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Opérateurs non autorisés : {', '.join(invalid)}")
    if not requested:
        raise HTTPException(status_code=400, detail="Aucun opérateur disponible — configurez d'abord les MNO du client")
    if payload.amount is not None and payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Montant invalide")
    if payload.max_uses is not None and payload.max_uses <= 0:
        raise HTTPException(status_code=400, detail="Nombre d'utilisations invalide")
    if not (payload.label or "").strip():
        raise HTTPException(status_code=400, detail="Libellé requis")
    slug = None
    for _ in range(8):
        cand = _gen_slug(8)
        if not await db.payment_links.find_one({"slug": cand}):
            slug = cand
            break
    if not slug:
        raise HTTPException(status_code=500, detail="Impossible de générer un slug unique")
    doc = {
        "id": _uuid(),
        "slug": slug,
        "client_id": parent_id,
        "owner_user_id": user["id"],
        "owner_email": user.get("email"),
        "owner_label": user.get("full_name") or user.get("email"),
        "label": payload.label.strip()[:120],
        "amount": float(payload.amount) if payload.amount is not None else None,
        "currency": (payload.currency or "XOF").upper(),
        "description": (payload.description or "").strip()[:200],
        "allowed_mnos": requested,
        "expires_at": payload.expires_at,
        "max_uses": payload.max_uses,
        "uses_count": 0,
        "disabled": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.payment_links.insert_one(doc.copy())
    doc.pop("_id", None)
    doc["status"] = _payment_link_status(doc)
    # Iter34y — activity feed (payment link)
    try:
        client_id_log = doc.get("client_id") or user.get("parent_client_id") or user.get("client_id") or user["id"]
        amount_str = f"{doc.get('amount')} {doc.get('currency') or ''}".strip()
        await _log_activity(client_id=client_id_log, kind="payment", action="created", label=f"Lien — {amount_str} ({doc.get('description') or '—'})", actor=user, target_id=doc["id"])
    except Exception:
        pass
    return doc


@api.get("/me/payment-links", tags=["Portail Client"])
async def me_list_payment_links(user: dict = Depends(get_current_user)):
    if user.get("role") in ("admin", "superviseur"):
        items = await db.payment_links.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    else:
        items = await db.payment_links.find(
            {"client_id": user.get("client_id") or user["id"]}, {"_id": 0}
        ).sort("created_at", -1).to_list(200)
    for it in items:
        it["status"] = _payment_link_status(it)
    return items


@api.patch("/me/payment-links/{link_id}", tags=["Portail Client"])
async def me_toggle_payment_link(link_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    pl = await db.payment_links.find_one({"id": link_id}, {"_id": 0})
    if not pl:
        raise HTTPException(status_code=404, detail="Lien introuvable")
    if user.get("role") not in ("admin", "superviseur") and pl.get("client_id") != (user.get("client_id") or user["id"]):
        raise HTTPException(status_code=403, detail="Accès refusé")
    update: Dict[str, Any] = {"updated_at": _now()}
    if "disabled" in payload:
        update["disabled"] = bool(payload["disabled"])
    await db.payment_links.update_one({"id": link_id}, {"$set": update})
    refreshed = await db.payment_links.find_one({"id": link_id}, {"_id": 0})
    if refreshed:
        refreshed["status"] = _payment_link_status(refreshed)
    return refreshed or {"ok": True}


@api.delete("/me/payment-links/{link_id}", tags=["Portail Client"])
async def me_delete_payment_link(link_id: str, user: dict = Depends(get_current_user)):
    pl = await db.payment_links.find_one({"id": link_id}, {"_id": 0})
    if not pl:
        raise HTTPException(status_code=404, detail="Lien introuvable")
    if user.get("role") not in ("admin", "superviseur") and pl.get("client_id") != (user.get("client_id") or user["id"]):
        raise HTTPException(status_code=403, detail="Accès refusé")
    await db.payment_links.delete_one({"id": link_id})
    return {"ok": True}


@api.get("/public/pay/{slug}", tags=["Public"])
async def public_get_payment_link(slug: str):
    pl = await db.payment_links.find_one({"slug": slug}, {"_id": 0})
    if not pl:
        raise HTTPException(status_code=404, detail="Lien de paiement introuvable")
    parent = await db.users.find_one(
        {"id": pl.get("client_id")},
        {"_id": 0, "company": 1, "logo_url": 1, "branding": 1, "full_name": 1},
    )
    branding_logo = None
    if parent:
        branding_logo = parent.get("logo_url")
        if not branding_logo and isinstance(parent.get("branding"), dict):
            branding_logo = parent["branding"].get("logo_url")
    return {
        "slug": pl["slug"],
        "label": pl.get("label"),
        "amount": pl.get("amount"),
        "currency": pl.get("currency") or "XOF",
        "description": pl.get("description"),
        "allowed_mnos": pl.get("allowed_mnos") or [],
        "expires_at": pl.get("expires_at"),
        "status": _payment_link_status(pl),
        "uses_count": pl.get("uses_count") or 0,
        "max_uses": pl.get("max_uses"),
        "branding": {
            "company": (parent or {}).get("company") or (parent or {}).get("full_name"),
            "logo_url": branding_logo,
        },
    }


class PublicPayRequest(BaseModel):
    msisdn: str
    mno: str
    amount: Optional[float] = None  # mandatory only when link has open amount
    payer_name: Optional[str] = None


@api.post("/public/pay/{slug}/deposit", tags=["Public"])
async def public_pay_deposit(slug: str, payload: PublicPayRequest, request: Request):
    pl = await db.payment_links.find_one({"slug": slug}, {"_id": 0})
    if not pl:
        raise HTTPException(status_code=404, detail="Lien de paiement introuvable")
    status = _payment_link_status(pl)
    if status != "active":
        raise HTTPException(status_code=409, detail=f"Lien non utilisable (statut : {status})")
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not s.get("pawapay_enabled"):
        raise HTTPException(status_code=503, detail="PawaPay non activé")
    token = _pawapay_active_token(s)
    if not token:
        raise HTTPException(status_code=503, detail="Clé API PawaPay non configurée")
    if pl.get("amount") is not None:
        amount = float(pl["amount"])
    else:
        if payload.amount is None or payload.amount <= 0:
            raise HTTPException(status_code=400, detail="Montant requis pour ce lien")
        amount = float(payload.amount)
    mno = (payload.mno or "").upper()
    allowed = pl.get("allowed_mnos") or []
    if mno not in allowed:
        raise HTTPException(status_code=400, detail=f"Opérateur non autorisé. Disponibles : {', '.join(allowed)}")
    msisdn_clean = "".join(ch for ch in (payload.msisdn or "") if ch.isdigit())
    if len(msisdn_clean) < 8:
        raise HTTPException(status_code=400, detail="Numéro mobile invalide")
    env = (s.get("pawapay_environment") or "sandbox").lower()
    host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
    country = (s.get("pawapay_country") or "BFA").upper()
    deposit_id = _uuid()
    body = {
        "depositId": deposit_id,
        "amount": str(amount),
        "currency": pl.get("currency") or "XOF",
        "country": country,
        "correspondent": _pawapay_correspondent(mno, country),
        "payer": {"type": "MSISDN", "address": {"value": msisdn_clean}},
        "customerTimestamp": _now(),
        "statementDescription": (pl.get("label") or "SAWALI")[:22],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(
                f"{host}/deposits",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
            api_resp: Dict[str, Any] = {}
            try:
                api_resp = r.json()
            except Exception:  # noqa: BLE001
                api_resp = {"raw": r.text[:500]}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à PawaPay")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erreur PawaPay : {exc}"[:300])
    api_status = (api_resp.get("status") or "").upper()
    initial_status = "pending" if api_status in ("ACCEPTED", "PENDING", "") else "failed"
    doc = {
        "id": _uuid(),
        "deposit_id": deposit_id,
        "client_id": pl["client_id"],
        "user_id": pl.get("owner_user_id"),
        "user_email": pl.get("owner_email"),
        "user_label": pl.get("owner_label"),
        "amount": amount,
        "currency": pl.get("currency") or "XOF",
        "country": country,
        "mno": mno,
        "msisdn": msisdn_clean,
        "description": pl.get("label"),
        "environment": env,
        "status": initial_status,
        "api_status": api_status or None,
        "api_message": _pawapay_str(api_resp.get("failureReason") or api_resp.get("rejectionReason") or api_resp.get("message")),
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "source": "payment_link",
        "payment_link_slug": slug,
        "payment_link_id": pl["id"],
        "payer_name": (payload.payer_name or "").strip()[:80] or None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.payments.insert_one(doc.copy())
    doc.pop("_id", None)
    if initial_status != "failed":
        await db.payment_links.update_one(
            {"id": pl["id"]},
            {"$inc": {"uses_count": 1}, "$set": {"updated_at": _now()}},
        )
    if api_resp.get("status") == "REJECTED":
        return {"ok": False, "deposit_id": deposit_id, "status": "failed", "reason": _pawapay_str(api_resp.get("rejectionReason"))}
    return {"ok": True, "deposit_id": deposit_id, "status": initial_status}


@api.get("/public/pay/{slug}/status/{deposit_id}", tags=["Public"])
async def public_pay_status(slug: str, deposit_id: str):
    """Polling endpoint for the public payment landing page (no auth)."""
    p = await db.payments.find_one({"deposit_id": deposit_id, "payment_link_slug": slug}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    # If still pending, refresh from PawaPay live
    if p.get("status") == "pending":
        s = await db.settings.find_one({"_id": "global"}) or {}
        token = _pawapay_active_token(s)
        if token:
            env = (p.get("environment") or s.get("pawapay_environment") or "sandbox").lower()
            host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
            try:
                async with httpx.AsyncClient(timeout=15) as http:
                    rr = await http.get(f"{host}/deposits/{deposit_id}", headers={"Authorization": f"Bearer {token}"})
                    arr = rr.json() if rr.status_code < 400 else []
                    entry = arr[0] if isinstance(arr, list) and arr else (arr if isinstance(arr, dict) else {})
                    api_status = (entry.get("status") or "").upper()
                    new_status = {
                        "COMPLETED": "completed", "FAILED": "failed", "REJECTED": "failed",
                        "ACCEPTED": "pending", "PROCESSING": "pending", "SUBMITTED": "pending", "PENDING": "pending",
                    }.get(api_status, p.get("status"))
                    if new_status != p.get("status"):
                        await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {
                            "status": new_status,
                            "api_status": api_status,
                            "api_message": _pawapay_str(entry.get("failureReason") or entry.get("rejectionReason")),
                            "completed_at": entry.get("respondedTimestamp") or (None if new_status == "pending" else _now()),
                            "updated_at": _now(),
                        }})
                        p = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
            except Exception as exc:  # noqa: BLE001
                logger.warning("[pay-link-poll] %s — %s", deposit_id, exc)
    return {
        "status": p.get("status"),
        "api_message": p.get("api_message"),
        "amount": p.get("amount"),
        "currency": p.get("currency") or "XOF",
    }





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
    refreshed = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    asyncio.create_task(_fire_agenda_n8n("updated", refreshed or {**existing, **update}, user))
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
    asyncio.create_task(_fire_agenda_n8n("deleted", existing, user))
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
    # Shared per-client scope: even tracked users land their RDV on the parent client_id
    client_scope = user.get("client_id") or user["id"]
    doc = {
        "id": _uuid(),
        "client_id": client_scope,
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
    # Iter34y — activity feed (appointment)
    await _log_activity(client_id=user["id"], kind="appointment", action="created", label=doc.get("subject") or "(rendez-vous)", actor=user, target_id=doc["id"])
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
    asyncio.create_task(_fire_agenda_n8n("created", doc, user))
    return doc


@api.get("/me/documents", tags=["Portail Client"])
async def me_documents(user: dict = Depends(get_current_user)):
    """RGPD: anonymizes uploaded_by_email/name for non-privileged roles."""
    if _can_consult_all_docs(user):
        items = await db.documents.find({}, {"_id": 0}).to_list(5000)
    else:
        effective_client_id = user.get("parent_client_id") or user["id"]
        items = await db.documents.find(
            {"$or": [{"client_id": effective_client_id}, {"is_public": True}]}, {"_id": 0}
        ).to_list(500)
    return await _maybe_anon_list(user, items, _apply_anon_to_document)


@api.get("/me/interventions", tags=["Portail Client"])
async def me_interventions(user: dict = Depends(get_current_user)):
    """RGPD: anonymizes the technician name for non-privileged roles."""
    if _is_elevated_creator(user):
        items = await db.interventions.find({}, {"_id": 0}).to_list(2000)
    else:
        effective_client_id = user.get("parent_client_id") or user["id"]
        items = await db.interventions.find({"client_id": effective_client_id}, {"_id": 0}).to_list(1000)
    items = sorted(items, key=lambda x: x.get("intervention_date", ""), reverse=True)
    items = await _maybe_anon_list(user, items, _apply_anon_to_intervention)
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
async def admin_list_clients(
    include_roles: Optional[str] = None,
    _: dict = Depends(get_current_admin),
):
    """List all users that should be visible in the Admin → Clients module.

    Iter34p — Default scope widened to include `admin` (client roots) and
    `moderateur` so the admin can see and manage every account. The
    SAWALI super-admin (admin@sawalismartsystems.com) is always excluded
    because the platform itself owns this row.

    Optional query param `include_roles` (comma-separated) overrides the
    default scope. Example: ``?include_roles=client,superviseur``.
    """
    if include_roles:
        roles = [r.strip() for r in include_roles.split(",") if r.strip()]
    else:
        roles = ["client", "superviseur", "admin", "moderateur"]
    users = await db.users.find(
        {
            "role": {"$in": roles},
            "email": {"$nin": ["admin@sawalismartsystems.com"]},
        },
        {"_id": 0, "password_hash": 0},
    ).to_list(2000)
    return users


@api.post("/admin/clients", tags=["Admin"])
async def admin_create_client(payload: UserCreateAdmin, _: dict = Depends(get_current_admin)):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Cet email est déjà utilisé")
    # iter32 — Resolve canonical-link hint. The frontend may pass
    # `link_to_client_id` after the admin accepts a "company already exists"
    # suggestion. When set, we mirror parent_client_id + client_id so the new
    # user inherits the existing client's scope (visible contacts, RGPD flags,
    # features, billing). Without this, every new admin created with the same
    # company name silently becomes a separate root → exactly the bug iter30
    # exposed.
    parent_client_id: Optional[str] = None
    mirrored_client_id: Optional[str] = None
    if payload.link_to_client_id:
        canon = await db.users.find_one(
            {"id": payload.link_to_client_id},
            {"_id": 0, "id": 1, "company": 1, "logo_url": 1},
        )
        if not canon:
            raise HTTPException(status_code=404, detail="Client canonique introuvable")
        parent_client_id = canon["id"]
        mirrored_client_id = canon["id"]
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
        "parent_client_id": parent_client_id,
        "client_id": mirrored_client_id,
        # Iter35h — demo role: persist quota + expiry, default 14 days if unset
        "demo_expires_at": (
            payload.demo_expires_at
            or ((datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
                if payload.role == "demo" else None)
        ),
        "demo_quotas": payload.demo_quotas or None,
        "demo_usage": {} if payload.role == "demo" else None,
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


# ============================================================
# Per-client SMART Communications feature flags
# Stored on the client doc as `features` dict and inherited by every
# tracked user belonging to that client (resolved live in /me/features).
# Default = all disabled so a brand-new client can't unintentionally
# consume paid services until the admin enables them.
# ============================================================
DEFAULT_CLIENT_FEATURES = {
    "whatsapp": False,
    "sms": False,
    "ai": False,
    "payments": False,
    "webhook_returns": False,  # Show outbound-webhook execution result modals on POST/PUT/DELETE
    # RGPD anonymization toggles — when ON, the corresponding field is masked
    # in API responses for users whose role is NOT one of: admin, superviseur,
    # moderateur. Inherited automatically by tracked users of this client.
    "anon_name": False,
    "anon_company": False,  # split out from anon_name so admin can mask the
                              # name without masking the company (and vice-versa)
    "anon_email": False,
    "anon_phone": False,
    "anon_whatsapp": False,
    # Iter34u — Content-level restrictions: when ON, each resource of the
    # given kind is visible ONLY to its creator (created_by_id == viewer.id)
    # plus privileged roles (admin/superviseur/moderateur). Listing endpoints
    # filter them out from the response; detail endpoints return 403.
    "anon_rapports": False,        # restricts reports (kind=rapport)
    "anon_suivis": False,          # restricts follow-ups (kind=suivi)
    "anon_communications": False,  # restricts SMS, WhatsApp & payment_links
    # Allow tracked users to enable the WhatsApp inbound sound alert. When OFF,
    # the sound toggle is hidden in their portal sidebar.
    "wa_sound_alerts": True,
}

# Per-client list of authorized PawaPay MNO codes (ORANGE, MOOV, TELECEL).
# Stored alongside features on the client doc.
DEFAULT_CLIENT_PAWAPAY_MNOS: List[str] = ["ORANGE", "MOOV", "TELECEL"]


def _normalize_pawapay_mnos(raw: Optional[Any]) -> List[str]:
    if not isinstance(raw, list):
        return list(DEFAULT_CLIENT_PAWAPAY_MNOS)
    out = []
    for x in raw:
        v = str(x).upper().strip()
        if v in DEFAULT_CLIENT_PAWAPAY_MNOS and v not in out:
            out.append(v)
    return out


def _normalize_features(raw: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    out = dict(DEFAULT_CLIENT_FEATURES)
    if isinstance(raw, dict):
        for k in DEFAULT_CLIENT_FEATURES:
            out[k] = bool(raw.get(k, DEFAULT_CLIENT_FEATURES[k]))
    return out


# ---------- RGPD anonymization (per-client toggles inherited by tracked users) ----------
RGPD_PRIVILEGED_ROLES = {"admin", "superviseur", "moderateur"}


def _anon_name(name: Optional[str]) -> Optional[str]:
    """Anonymize a person/company name as `J*** D***`. Each whitespace-token
    keeps its first character followed by 3 stars. Single-token names get
    the same treatment. Empty input is returned as-is."""
    if not name:
        return name
    parts = (name or "").strip().split()
    if not parts:
        return name
    return " ".join((p[0] + "***") if p else "" for p in parts)


def _anon_email(email: Optional[str]) -> Optional[str]:
    """Anonymize an email as `j***@gmail.com` (1st letter + stars + domain)."""
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def _anon_phone(phone: Optional[str]) -> Optional[str]:
    """Anonymize a phone as `+225 07 ** ** ** 89`. Keeps non-digit prefixes
    (e.g. country code), masks the middle, keeps the last 2 digits."""
    if not phone:
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 4:
        return "***"
    keep_last = digits[-2:]
    masked_middle = "*" * max(0, len(digits) - 4)
    keep_first = digits[:2]
    return f"+{keep_first} {masked_middle[:2]} {masked_middle[2:4]} {masked_middle[4:6]} {keep_last}".replace("  ", " ").strip()


async def _resolve_real_phone(contact_id: Optional[str], field: str, fallback: str = "") -> str:
    """Iter34h — RGPD anonymization preserves real phone numbers in the DB but
    masks them in API responses. When the user clicks "Send SMS/WhatsApp" the
    frontend ships a masked value back. This helper restores the REAL phone
    number from the directory_contacts row, bypassing the anonymization.

    Args:
        contact_id: Optional contact UUID. When provided, fetch the row and
            return its `phone` (for SMS) or `whatsapp` (for WhatsApp).
        field: "phone" or "whatsapp"
        fallback: The masked/raw value submitted by the frontend. Used when
            contact_id is missing or the row has no value in that field.

    Returns: the real phone number ready to send to SMS/WA providers.
    """
    if not contact_id:
        return (fallback or "").strip()
    try:
        row = await db.directory_contacts.find_one(
            {"id": contact_id},
            {"_id": 0, "phone": 1, "whatsapp": 1},
        )
        if row:
            real = (row.get(field) or "").strip()
            if real:
                return real
    except Exception:
        pass
    return (fallback or "").strip()




async def _resolve_content_restrictions(viewer: dict) -> Dict[str, bool]:
    """Iter34u — Return the anon_rapports / anon_suivis / anon_communications
    flags that apply to the given viewer. Privileged roles always see
    everything (flags reported as False). Other users inherit the parent
    client's configuration (parent_client_id priority over client_id)."""
    role = (viewer.get("role") or "").lower()
    if role in RGPD_PRIVILEGED_ROLES:
        return {"anon_rapports": False, "anon_suivis": False, "anon_communications": False}
    parent_id = viewer.get("parent_client_id") or viewer.get("client_id") or viewer.get("id")
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
    feats = _normalize_features((parent or {}).get("features"))
    return {
        "anon_rapports": bool(feats.get("anon_rapports")),
        "anon_suivis": bool(feats.get("anon_suivis")),
        "anon_communications": bool(feats.get("anon_communications")),
    }


async def _resolve_anon_flags(viewer: dict) -> Dict[str, bool]:
    """Return the anon_* flags that apply to the current viewer.
    Privileged roles (admin/superviseur/moderateur) get all flags as False so
    they always see the data in clear. Other users inherit the parent client's
    flags — false (no anonymization) by default.

    Iter34p — Resolution priority for `parent_id`:
      1. `parent_client_id` (the explicit canonical pointer set by iter28/m)
      2. `client_id` (legacy field, may equal self for root users)
      3. `id` (last resort fallback)
    Previously we only checked `client_id or id`, so a tracked/child user
    whose `client_id` happened to be null or self-id would skip the parent's
    RGPD settings entirely.
    """
    role = (viewer.get("role") or "").lower()
    if role in RGPD_PRIVILEGED_ROLES:
        return {"anon_name": False, "anon_company": False, "anon_email": False, "anon_phone": False, "anon_whatsapp": False}
    parent_id = viewer.get("parent_client_id") or viewer.get("client_id") or viewer.get("id")
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
    feats = _normalize_features((parent or {}).get("features"))
    return {
        "anon_name": bool(feats.get("anon_name")),
        "anon_company": bool(feats.get("anon_company")),
        "anon_email": bool(feats.get("anon_email")),
        "anon_phone": bool(feats.get("anon_phone")),
        "anon_whatsapp": bool(feats.get("anon_whatsapp")),
    }


def _apply_anon_to_contact(c: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Mutate a copy of a contact dict to mask sensitive fields per flags.
    The `contact_code` field is NEVER masked — it's the stable identifier
    used to reference the contact even when other fields are anonymized."""
    out = dict(c)
    if flags.get("anon_name"):
        out["name"] = _anon_name(out.get("name")) or out.get("name")
    if flags.get("anon_company"):
        out["company"] = _anon_name(out.get("company")) or out.get("company")
    if flags.get("anon_email"):
        out["email"] = _anon_email(out.get("email")) or out.get("email")
    if flags.get("anon_phone"):
        out["phone"] = _anon_phone(out.get("phone")) or out.get("phone")
    if flags.get("anon_whatsapp"):
        out["whatsapp"] = _anon_phone(out.get("whatsapp")) or out.get("whatsapp")
    return out


def _apply_anon_to_appointment(a: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Anonymize the customer fields of an appointment (RDV)."""
    out = dict(a)
    if flags.get("anon_name"):
        out["name"] = _anon_name(out.get("name")) or out.get("name")
    if flags.get("anon_company"):
        out["company"] = _anon_name(out.get("company")) or out.get("company")
    if flags.get("anon_email"):
        out["email"] = _anon_email(out.get("email")) or out.get("email")
    if flags.get("anon_phone"):
        out["phone"] = _anon_phone(out.get("phone")) or out.get("phone")
    return out


def _apply_anon_to_intervention(i: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Anonymize the technician name on an intervention card."""
    out = dict(i)
    if flags.get("anon_name"):
        out["technician"] = _anon_name(out.get("technician")) or out.get("technician")
    return out


def _apply_anon_to_document(d: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Anonymize uploader-related fields on a document."""
    out = dict(d)
    if flags.get("anon_name"):
        out["uploaded_by_name"] = _anon_name(out.get("uploaded_by_name")) or out.get("uploaded_by_name")
        out["client_name"] = _anon_name(out.get("client_name")) or out.get("client_name")
    if flags.get("anon_email"):
        out["uploaded_by_email"] = _anon_email(out.get("uploaded_by_email")) or out.get("uploaded_by_email")
    return out


def _apply_anon_to_access_log(log: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Anonymize identity fields on an access-log entry."""
    out = dict(log)
    if flags.get("anon_name"):
        out["user_name"] = _anon_name(out.get("user_name")) or out.get("user_name")
    if flags.get("anon_email"):
        out["user_email"] = _anon_email(out.get("user_email")) or out.get("user_email")
    return out


async def _maybe_anon_list(viewer: dict, items: List[Dict[str, Any]], applier) -> List[Dict[str, Any]]:
    """Generic helper: applies the chosen `applier` to each item only if at
    least one anon flag is True for the viewer. No-op otherwise."""
    flags = await _resolve_anon_flags(viewer)
    if not any(flags.values()):
        return items
    return [applier(x, flags) for x in items]


class ClientFeaturesUpdate(BaseModel):
    whatsapp: Optional[bool] = None
    sms: Optional[bool] = None
    ai: Optional[bool] = None
    payments: Optional[bool] = None
    webhook_returns: Optional[bool] = None
    anon_name: Optional[bool] = None
    anon_company: Optional[bool] = None
    anon_email: Optional[bool] = None
    anon_phone: Optional[bool] = None
    anon_whatsapp: Optional[bool] = None
    wa_sound_alerts: Optional[bool] = None
    pawapay_mnos: Optional[List[str]] = None  # subset of ORANGE/MOOV/TELECEL


@api.get("/admin/clients/{client_id}/features", tags=["Admin"])
async def admin_get_client_features(client_id: str, _: dict = Depends(get_current_admin)):
    u = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "features": 1, "pawapay_mnos": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return {
        "client": {"id": u["id"], "full_name": u.get("full_name"), "company": u.get("company")},
        "features": _normalize_features(u.get("features")),
        "pawapay_mnos": _normalize_pawapay_mnos(u.get("pawapay_mnos")),
    }


@api.put("/admin/clients/{client_id}/features", tags=["Admin"])
async def admin_update_client_features(client_id: str, payload: ClientFeaturesUpdate, _: dict = Depends(get_current_admin)):
    u = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "features": 1, "pawapay_mnos": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Client introuvable")
    current = _normalize_features(u.get("features"))
    update_dict = payload.model_dump(exclude_none=True)
    mnos = update_dict.pop("pawapay_mnos", None)
    current.update({k: bool(v) for k, v in update_dict.items()})
    set_doc: Dict[str, Any] = {"features": current, "features_updated_at": _now()}
    if mnos is not None:
        set_doc["pawapay_mnos"] = _normalize_pawapay_mnos(mnos)
    await db.users.update_one(
        {"id": client_id},
        {"$set": set_doc},
    )
    return {
        "ok": True,
        "features": current,
        "pawapay_mnos": set_doc.get("pawapay_mnos") or _normalize_pawapay_mnos(u.get("pawapay_mnos")),
    }


@api.get("/admin/rgpd-preview/{client_id}", tags=["Admin"])
async def admin_rgpd_preview(client_id: str, _: dict = Depends(get_current_admin)):
    """Preview what a non-privileged user of `client_id` would see in their
    portal — applies the parent client's anon flags to a sample of records
    from each anonymized collection (contacts, appointments, interventions,
    documents). Admins use this to audit the RGPD setup without having to
    create a test user account.

    Returns up to 5 records per collection with both the original and the
    masked version side-by-side so the admin can verify the mapping."""
    parent = await db.users.find_one({"id": client_id}, {"_id": 0, "features": 1, "full_name": 1, "company": 1})
    if not parent:
        raise HTTPException(status_code=404, detail="Client introuvable")
    feats = _normalize_features(parent.get("features"))
    flags = {
        "anon_name": bool(feats.get("anon_name")),
        "anon_company": bool(feats.get("anon_company")),
        "anon_email": bool(feats.get("anon_email")),
        "anon_phone": bool(feats.get("anon_phone")),
        "anon_whatsapp": bool(feats.get("anon_whatsapp")),
    }

    contacts = await db.directory_contacts.find({"client_id": client_id}, {"_id": 0}).limit(5).to_list(5)
    appointments = await db.appointments.find({"client_id": client_id}, {"_id": 0}).limit(5).to_list(5)
    interventions = await db.interventions.find({"client_id": client_id}, {"_id": 0}).limit(5).to_list(5)
    documents = await db.documents.find({"client_id": client_id}, {"_id": 0}).limit(5).to_list(5)

    def _pair(items, applier):
        return [{"original": x, "masked": applier(x, flags)} for x in items]

    return {
        "client_id": client_id,
        "client_name": parent.get("full_name") or parent.get("company"),
        "flags": flags,
        "contacts": _pair(contacts, _apply_anon_to_contact),
        "appointments": _pair(appointments, _apply_anon_to_appointment),
        "interventions": _pair(interventions, _apply_anon_to_intervention),
        "documents": _pair(documents, _apply_anon_to_document),
    }



@api.get("/me/features", tags=["Portail Client"])
async def me_get_features(user: dict = Depends(get_current_user)):
    """Resolve the SMART Communications feature flags for the calling user.
    Admin & superviseur always have everything enabled. Tracked users inherit
    from their parent client. Plain client users read from their own doc."""
    if user.get("role") in ("admin", "superviseur"):
        return {
            "features": {k: True for k in DEFAULT_CLIENT_FEATURES},
            "pawapay_mnos": list(DEFAULT_CLIENT_PAWAPAY_MNOS),
            "inherited_from": None,
        }
    parent_id = user.get("parent_client_id") or user.get("client_id") or user["id"]
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "features": 1, "pawapay_mnos": 1})
    feats = _normalize_features((parent or {}).get("features"))
    mnos = _normalize_pawapay_mnos((parent or {}).get("pawapay_mnos"))
    return {
        "features": feats,
        "pawapay_mnos": mnos,
        "inherited_from": {
            "id": parent_id,
            "full_name": (parent or {}).get("full_name"),
            "company": (parent or {}).get("company"),
        } if parent and parent_id != user["id"] else None,
    }


def _check_feature(user: dict, feature: str) -> None:
    """Hook for future enforcement of per-client feature flags. Currently a
    no-op: the frontend disables the UI for unavailable features, and we keep
    this stub in place so a single line change can flip backend enforcement on.
    Admin/superviseur always bypass."""
    if user.get("role") in ("admin", "superviseur"):
        return
    # NOTE: enforcement intentionally deferred — see /me/features for the
    # resolved feature dict consumed by the UI.
    return


# ============================================================
# Admin Usage Dashboard — consolidates the paid-service consumption
# (WhatsApp / AI summaries / audio transcriptions / PawaPay) per client.
# Used by /admin/usage to support billing & heavy-user detection.
# ============================================================
@api.get("/admin/usage/summary", tags=["Admin"])
async def admin_usage_summary(days: int = 30, _: dict = Depends(get_current_admin)):
    """Aggregate usage metrics per client over the last N days.
    Returns: {period_days, totals, per_client[], daily_series[]}."""
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()

    # Clients lookup (id → {full_name, company, features, wa_unit_cost, wa_currency})
    clients_cur = db.users.find(
        {"role": {"$in": ["client", "admin", "superviseur"]}},
        {"_id": 0, "id": 1, "full_name": 1, "company": 1, "features": 1, "wa_unit_cost": 1, "wa_currency": 1},
    )
    clients = {c["id"]: c async for c in clients_cur}

    # Aggregations
    wa_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": "$client_id",
            "sent_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "inbound": {"$sum": {"$cond": [{"$eq": ["$direction", "inbound"]}, 1, 0]}},
            "total": {"$sum": 1},
        }},
    ]
    wa_agg = {doc["_id"]: doc async for doc in db.whatsapp_messages.aggregate(wa_pipeline)}

    ai_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
    ]
    ai_agg = {doc["_id"]: doc["count"] async for doc in db.ai_summaries.aggregate(ai_pipeline)}

    # SMS aggregation per client × per provider (sent_ok + sent_ko + total)
    sms_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": {"client_id": "$client_id", "provider": "$provider"},
            "sent_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "total": {"$sum": 1},
        }},
    ]
    sms_by_client: Dict[str, Dict[str, Any]] = {}
    sms_by_provider: Dict[str, Dict[str, int]] = {}
    async for doc in db.sms_messages.aggregate(sms_pipeline):
        cid = (doc.get("_id") or {}).get("client_id")
        prov = ((doc.get("_id") or {}).get("provider") or "?").upper()
        ok = int(doc.get("sent_ok", 0))
        ko = int(doc.get("sent_ko", 0))
        tot = int(doc.get("total", 0))
        if cid:
            client_row = sms_by_client.setdefault(cid, {"sent_ok": 0, "sent_ko": 0, "total": 0, "by_provider": {}})
            client_row["sent_ok"] += ok
            client_row["sent_ko"] += ko
            client_row["total"] += tot
            pp = client_row["by_provider"].setdefault(prov, {"sent_ok": 0, "sent_ko": 0, "total": 0})
            pp["sent_ok"] += ok
            pp["sent_ko"] += ko
            pp["total"] += tot
        prov_row = sms_by_provider.setdefault(prov, {"sent_ok": 0, "sent_ko": 0, "total": 0})
        prov_row["sent_ok"] += ok
        prov_row["sent_ko"] += ko
        prov_row["total"] += tot

    # Per-client assembly
    per_client = []
    tot = {"wa_sent_ok": 0, "wa_sent_ko": 0, "wa_inbound": 0, "wa_total": 0, "wa_cost": 0.0, "ai_count": 0,
           "sms_sent_ok": 0, "sms_sent_ko": 0, "sms_total": 0, "sms_cost": 0.0}
    for cid, c in clients.items():
        wa = wa_agg.get(cid, {})
        unit_cost = float(c.get("wa_unit_cost") or 0)
        currency = c.get("wa_currency") or "XOF"
        wa_ok = int(wa.get("sent_ok", 0))
        wa_ko = int(wa.get("sent_ko", 0))
        wa_inbound = int(wa.get("inbound", 0))
        wa_total = int(wa.get("total", 0))
        wa_cost = wa_ok * unit_cost
        ai_count = int(ai_agg.get(cid, 0))
        sms_row = sms_by_client.get(cid, {"sent_ok": 0, "sent_ko": 0, "total": 0, "by_provider": {}})
        sms_unit_cost = float(c.get("sms_unit_cost") or 0)
        sms_cost = int(sms_row["sent_ok"]) * sms_unit_cost
        features = _normalize_features(c.get("features"))
        per_client.append({
            "client_id": cid,
            "full_name": c.get("full_name"),
            "company": c.get("company"),
            "features": features,
            "wa_sent_ok": wa_ok,
            "wa_sent_ko": wa_ko,
            "wa_inbound": wa_inbound,
            "wa_total": wa_total,
            "wa_unit_cost": unit_cost,
            "wa_currency": currency,
            "wa_cost": wa_cost,
            "ai_summaries": ai_count,
            "sms_sent_ok": int(sms_row["sent_ok"]),
            "sms_sent_ko": int(sms_row["sent_ko"]),
            "sms_total": int(sms_row["total"]),
            "sms_by_provider": sms_row["by_provider"],
            "sms_unit_cost": sms_unit_cost,
            "sms_cost": sms_cost,
        })
        tot["wa_sent_ok"] += wa_ok
        tot["wa_sent_ko"] += wa_ko
        tot["wa_inbound"] += wa_inbound
        tot["wa_total"] += wa_total
        tot["wa_cost"] += wa_cost
        tot["ai_count"] += ai_count
        tot["sms_sent_ok"] += int(sms_row["sent_ok"])
        tot["sms_sent_ko"] += int(sms_row["sent_ko"])
        tot["sms_total"] += int(sms_row["total"])
        tot["sms_cost"] += sms_cost
    per_client.sort(key=lambda r: r["wa_cost"] + r["sms_cost"] + r["ai_summaries"], reverse=True)

    # Daily series — stacked bar data for the 30-day chart (WA + AI + SMS)
    daily = {}
    start_day = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date()
    for i in range(days):
        d = (start_day + timedelta(days=i)).isoformat()
        daily[d] = {"day": d, "wa": 0, "ai": 0, "sms": 0}

    async for m in db.whatsapp_messages.find(
        {"created_at": {"$gte": since_iso}, "status": "sent"},
        {"_id": 0, "created_at": 1},
    ):
        day = (m.get("created_at") or "")[:10]
        if day in daily:
            daily[day]["wa"] += 1
    async for s in db.ai_summaries.find(
        {"created_at": {"$gte": since_iso}},
        {"_id": 0, "created_at": 1},
    ):
        day = (s.get("created_at") or "")[:10]
        if day in daily:
            daily[day]["ai"] += 1
    async for s in db.sms_messages.find(
        {"created_at": {"$gte": since_iso}, "status": "sent"},
        {"_id": 0, "created_at": 1},
    ):
        day = (s.get("created_at") or "")[:10]
        if day in daily:
            daily[day]["sms"] += 1

    return {
        "period_days": days,
        "totals": tot,
        "per_client": per_client,
        "sms_by_provider": sms_by_provider,
        "daily_series": sorted(daily.values(), key=lambda d: d["day"]),
        "generated_at": _now(),
    }


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


# ============================================================
# Iter34f — User activity summary (last logins + page visits).
# Period: today | week | month | days={N}. Optional company filter to scope
# to a single client's users. Reads from db.access_logs (recorded by the SPA
# on every route change) and joins with db.users for company labels.
# ============================================================
@api.get("/admin/user-activity", tags=["Admin"])
async def admin_user_activity(
    period: str = "week",
    company: Optional[str] = None,
    limit: int = 10,
    _: dict = Depends(get_current_admin),
):
    """Returns:
      - last_logins[]: { user_email, user_name, role, company, last_seen_at, hits, last_page }
      - top_pages[]:   { module, page, hits, unique_users }
      - totals: { hits, unique_users, unique_companies }
    """
    period_norm = (period or "week").lower()
    now = datetime.now(timezone.utc)
    days_map = {"today": 1, "day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}
    days = days_map.get(period_norm, 7)
    if period_norm.startswith("days="):
        try:
            days = max(1, min(int(period_norm.split("=", 1)[1]), 365))
        except Exception:
            days = 7
    since = (now - timedelta(days=days)).isoformat()

    # Build the email→company mapping (case-insensitive company filter)
    user_q: Dict[str, Any] = {}
    if company:
        user_q["company"] = {"$regex": f"^{re.escape(company)}$", "$options": "i"}
    users_by_email: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(user_q, {"_id": 0, "email": 1, "full_name": 1, "company": 1, "role": 1}):
        em = (u.get("email") or "").lower()
        if em:
            users_by_email[em] = u

    log_q: Dict[str, Any] = {"created_at": {"$gte": since}}
    if company:
        if not users_by_email:
            return {"period": period_norm, "days": days, "company": company,
                    "last_logins": [], "top_pages": [],
                    "totals": {"hits": 0, "unique_users": 0, "unique_companies": 0},
                    "company_options": []}
        log_q["user_email"] = {"$in": list(users_by_email.keys())}

    user_pipeline = [
        {"$match": log_q},
        {"$group": {
            "_id": "$user_email",
            "user_name": {"$last": "$user_name"},
            "role": {"$last": "$role"},
            "last_seen_at": {"$max": "$created_at"},
            "last_page": {"$last": "$page"},
            "last_module": {"$last": "$module"},
            "hits": {"$sum": 1},
        }},
        {"$sort": {"last_seen_at": -1}},
        {"$limit": max(1, min(limit, 100))},
    ]
    last_logins: List[Dict[str, Any]] = []
    async for r in db.access_logs.aggregate(user_pipeline):
        email = (r.get("_id") or "").lower()
        u = users_by_email.get(email) if users_by_email else None
        if not u:
            u = await db.users.find_one({"email": email}, {"_id": 0, "company": 1, "full_name": 1, "role": 1}) or {}
        last_logins.append({
            "user_email": r.get("_id"),
            "user_name": r.get("user_name") or u.get("full_name"),
            "role": r.get("role") or u.get("role"),
            "company": u.get("company"),
            "last_seen_at": r.get("last_seen_at"),
            "last_page": r.get("last_page"),
            "last_module": r.get("last_module"),
            "hits": r.get("hits", 0),
        })

    page_pipeline = [
        {"$match": log_q},
        {"$group": {
            "_id": {"module": "$module", "page": "$page"},
            "hits": {"$sum": 1},
            "users": {"$addToSet": "$user_email"},
        }},
        {"$project": {
            "module": "$_id.module",
            "page": "$_id.page",
            "hits": 1,
            "unique_users": {"$size": "$users"},
        }},
        {"$sort": {"hits": -1}},
        {"$limit": max(1, min(limit, 100))},
    ]
    top_pages: List[Dict[str, Any]] = []
    async for r in db.access_logs.aggregate(page_pipeline):
        top_pages.append({
            "module": r.get("module") or "—",
            "page": r.get("page") or "—",
            "hits": r.get("hits", 0),
            "unique_users": r.get("unique_users", 0),
        })

    totals_pipeline = [
        {"$match": log_q},
        {"$group": {
            "_id": None,
            "hits": {"$sum": 1},
            "users": {"$addToSet": "$user_email"},
        }},
    ]
    totals = {"hits": 0, "unique_users": 0, "unique_companies": 0}
    async for r in db.access_logs.aggregate(totals_pipeline):
        emails = [(e or "").lower() for e in (r.get("users") or [])]
        totals["hits"] = r.get("hits", 0)
        totals["unique_users"] = len(emails)
        if emails:
            comps = await db.users.distinct(
                "company",
                {"email": {"$in": emails}, "company": {"$nin": [None, ""]}},
            )
            totals["unique_companies"] = len(comps)

    company_options = await db.users.distinct(
        "company", {"company": {"$nin": [None, ""]}, "role": {"$in": ["client", "admin", "superviseur"]}}
    )
    company_options = sorted([c for c in company_options if c])

    return {
        "period": period_norm,
        "days": days,
        "company": company,
        "since": since,
        "last_logins": last_logins,
        "top_pages": top_pages,
        "totals": totals,
        "company_options": company_options,
    }


@api.get("/admin/user-activity/heatmap", tags=["Admin"])
async def admin_user_activity_heatmap(
    period: str = "month",
    company: Optional[str] = None,
    _: dict = Depends(get_current_admin),
):
    """Returns a 7×24 grid of hit counts (rows = weekdays 0..6 Mon→Sun,
    cols = hours 0..23 UTC). Useful for identifying peak activity windows.
    Period accepts: today | week | month | quarter | year | days=N (1..365)."""
    period_norm = (period or "month").lower()
    now = datetime.now(timezone.utc)
    days_map = {"today": 1, "day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}
    days = days_map.get(period_norm, 30)
    if period_norm.startswith("days="):
        try:
            days = max(1, min(int(period_norm.split("=", 1)[1]), 365))
        except Exception:
            days = 30
    since = (now - timedelta(days=days)).isoformat()
    log_q: Dict[str, Any] = {"created_at": {"$gte": since}}

    # Company filter — same logic as /admin/user-activity
    if company:
        emails = await db.users.distinct(
            "email",
            {"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}},
        )
        emails = [(e or "").lower() for e in emails if e]
        if not emails:
            return {"period": period_norm, "days": days, "company": company,
                    "matrix": [[0] * 24 for _ in range(7)], "total": 0, "peak": {"day": None, "hour": None, "count": 0}}
        log_q["user_email"] = {"$in": emails}

    matrix = [[0] * 24 for _ in range(7)]
    total = 0
    peak = {"day": None, "hour": None, "count": 0}
    try:
        cursor = db.access_logs.find(log_q, {"_id": 0, "created_at": 1})
        async for r in cursor:
            iso = r.get("created_at") or ""
            try:
                d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            # Python weekday: Monday=0..Sunday=6 (matches our grid)
            wd = d.weekday()
            hr = d.hour
            matrix[wd][hr] += 1
            total += 1
            if matrix[wd][hr] > peak["count"]:
                peak = {"day": wd, "hour": hr, "count": matrix[wd][hr]}
    except Exception:
        pass

    return {
        "period": period_norm,
        "days": days,
        "company": company,
        "since": since,
        "matrix": matrix,  # 7 rows (Mon→Sun) × 24 cols (0h→23h)
        "total": total,
        "peak": peak,
        "weekdays": ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"],
    }




@api.get("/admin/migrate-orphan-data", tags=["Admin"])
async def admin_inspect_orphan_data(_: dict = Depends(get_current_admin)):
    """Inspect what the iter28 orphan-data migration WOULD do (no writes).
    Returns per-user and per-collection counts. Use the POST variant below to
    actually apply the migration."""
    return await _migrate_orphan_client_data(dry_run=True)


@api.post("/admin/migrate-orphan-data", tags=["Admin"])
async def admin_run_orphan_data_migration(_: dict = Depends(get_current_admin)):
    """Apply the iter28 orphan-data migration. Idempotent — re-running won't
    re-migrate already-migrated rows (guarded by `client_id_legacy` presence).
    """
    return await _migrate_orphan_client_data(dry_run=False)


# ============================================================
# iter34 — DB Snapshots (Production → Preview safe restore)
#
# Admin can export the current MongoDB state to a gzipped JSON file,
# download it, and import it on another environment (typically: prod → preview)
# without ever touching binary uploads on disk. All snapshots are listed
# with their author, date, size and a free-text comment that can be edited.
#
# Sensitive credentials (API tokens, SMTP password, webhook secrets) are
# masked at export time so the file can be safely shared. User password
# hashes are PRESERVED (admins want to log in with their prod password
# on preview); only API/3rd-party secrets are masked.
# ============================================================
SNAPSHOTS_DIR = Path("/app/backend/snapshots")
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_COLLECTIONS = [
    "users", "directory_contacts", "contacts", "appointments", "interventions",
    "documents", "tracked_users", "contents", "client_notes", "client_tasks",
    "user_notes", "user_reports", "user_suivis", "user_notes_personal",
    "user_tasks_personal",  # Iter35g — personal portal notes & tasks
    "document_categories",
    "client_categories", "subscription_categories", "subscription_plans",
    "subscription_orders", "formations", "formation_modules",
    "formation_enrollments", "blog_posts", "case_studies", "testimonials",
    "deployments", "newsletter", "incidents", "settings", "automations",
    "payments", "payment_links", "sms_schedules", "whatsapp_schedules",
    "forms", "form_submissions", "media_library", "roadmap_actions",
]

SENSITIVE_SETTINGS_KEYS = {
    "smtp_password", "google_client_secret", "recaptcha_secret_key",
    "tracking_auth_header", "webhook_token", "webhook_basic_pass",
    "notes_webhook_token", "notes_webhook_basic_pass",
    "health_webhook_token", "health_webhook_basic_pass",
    "wa_access_token", "wa_verify_token", "openai_api_key", "openai_chat_api_key",
    "n8n_webhook_token", "n8n_webhook_basic_pass",
    "sms_orange_token", "sms_orange_basic_pass", "sms_orange_header_value",
    "sms_orange_client_secret",  # Iter35i — Orange OAuth client_credentials
    "sms_moov_token", "sms_moov_basic_pass", "sms_moov_header_value",
    "sms_moov_client_secret",
    "sms_telecel_token", "sms_telecel_basic_pass", "sms_telecel_header_value",
    "sms_telecel_client_secret",
    "sms_ovh_application_secret", "sms_ovh_consumer_key",
    "pawapay_api_token",
}
SNAPSHOT_MASK = "***MASKED***"


def _mask_settings_doc(doc: dict) -> dict:
    out = dict(doc)
    for k in SENSITIVE_SETTINGS_KEYS:
        if k in out and out[k]:
            out[k] = SNAPSHOT_MASK
    return out


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    try:
        return str(obj)
    except Exception:
        return None


async def _build_snapshot_payload(mask_secrets: bool = True) -> tuple[dict, dict]:
    """Returns (payload, stats). payload is the full snapshot dict ready to be
    serialized to JSON. stats is a {collection: count} mapping."""
    collections: Dict[str, List[Dict[str, Any]]] = {}
    stats: Dict[str, int] = {}
    for name in SNAPSHOT_COLLECTIONS:
        cursor = db[name].find({}, {"_id": 0})
        rows = [r async for r in cursor]
        if name == "settings" and mask_secrets:
            rows = [_mask_settings_doc(r) for r in rows]
        collections[name] = rows
        stats[name] = len(rows)
    payload = {
        "version": 1,
        "exported_at": _now(),
        "mask_secrets": bool(mask_secrets),
        "collections": collections,
        "stats": stats,
    }
    return payload, stats


async def _apply_snapshot(payload: dict, mode: str, dry_run: bool = False) -> dict:
    """Restore a snapshot. mode='replace' wipes each collection before insert.
    mode='merge' upserts by `id` field (or by `email` for users). Returns a
    summary dict {collection: {before, after, action, error?}}.

    Hardened (iter35a): per-collection try/except so one bad collection
    doesn't 500 the whole import; insert_many uses ordered=False to skip
    duplicate-key rows; settings is special-cased to preserve the
    `_id='global'` singleton anchor.
    """
    collections = payload.get("collections") or {}
    summary: Dict[str, Dict[str, Any]] = {}
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail=f"mode invalide: {mode}")

    INSERT_CHUNK = 500
    # Settings docs are singletons keyed by string _id (e.g., 'global'). The
    # snapshot strips _id on export → we must restore it for these docs.
    SETTINGS_SINGLETON_COLLECTIONS = {"settings"}

    def _strip_id(r: dict) -> dict:
        return {k: v for k, v in r.items() if k != "_id"}

    def _settings_anchor_id(r: dict) -> str:
        # If we ever export with _id preserved use it; otherwise default to 'global'.
        return r.get("_id_anchor") or r.get("settings_key") or "global"

    for name in SNAPSHOT_COLLECTIONS:
        # Only act on collections that are actually present in the snapshot.
        # A partial snapshot must NOT cascade-wipe unrelated collections.
        if name not in collections:
            continue
        rows = collections.get(name) or []
        try:
            before = await db[name].count_documents({})
        except Exception as exc:  # noqa: BLE001
            summary[name] = {"before": None, "incoming": len(rows), "action": "error", "error": f"count failed: {exc}"}
            continue

        if dry_run:
            summary[name] = {"before": before, "incoming": len(rows), "action": "dry-run"}
            continue

        try:
            if mode == "replace":
                await db[name].delete_many({})
                inserted_n = 0
                errors: List[str] = []
                if rows:
                    if name in SETTINGS_SINGLETON_COLLECTIONS:
                        # Singleton(s) with string _id — insert one-by-one and
                        # re-anchor the `_id` to its canonical value so future
                        # `find_one({"_id": "global"})` still resolves.
                        for r in rows:
                            doc = _strip_id(r)
                            doc["_id"] = _settings_anchor_id(r)
                            try:
                                await db[name].replace_one({"_id": doc["_id"]}, doc, upsert=True)
                                inserted_n += 1
                            except Exception as exc:  # noqa: BLE001
                                errors.append(str(exc)[:150])
                    else:
                        clean = [_strip_id(r) for r in rows]
                        # Chunked, unordered: keep going on duplicate-key / validation errors
                        for i in range(0, len(clean), INSERT_CHUNK):
                            batch = clean[i:i + INSERT_CHUNK]
                            try:
                                res = await db[name].insert_many(batch, ordered=False)
                                inserted_n += len(res.inserted_ids)
                            except Exception as exc:  # noqa: BLE001
                                # BulkWriteError still inserts the non-conflicting docs
                                details = getattr(exc, "details", None) or {}
                                ok_n = (details.get("nInserted") if isinstance(details, dict) else None)
                                if isinstance(ok_n, int):
                                    inserted_n += ok_n
                                errors.append(f"batch {i // INSERT_CHUNK}: {str(exc)[:200]}")
                after = await db[name].count_documents({})
                entry = {"before": before, "after": after, "incoming": len(rows),
                         "inserted": inserted_n, "action": "replaced"}
                if errors:
                    entry["errors"] = errors[:5]
                    entry["error_count"] = len(errors)
                summary[name] = entry

            else:  # merge
                merged = 0
                inserted_n = 0
                errors: List[str] = []
                for r in rows:
                    try:
                        key = None
                        if name == "users" and r.get("email"):
                            key = {"email": r["email"]}
                        elif name in SETTINGS_SINGLETON_COLLECTIONS:
                            key = {"_id": _settings_anchor_id(r)}
                        elif r.get("id"):
                            key = {"id": r["id"]}
                        doc = _strip_id(r)
                        if name in SETTINGS_SINGLETON_COLLECTIONS:
                            doc["_id"] = _settings_anchor_id(r)
                        if not key:
                            await db[name].insert_one(doc)
                            inserted_n += 1
                            continue
                        res = await db[name].update_one(key, {"$set": doc}, upsert=True)
                        if res.upserted_id is not None:
                            inserted_n += 1
                        else:
                            merged += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(str(exc)[:200])
                after = await db[name].count_documents({})
                entry = {"before": before, "after": after, "incoming": len(rows),
                         "merged": merged, "inserted": inserted_n, "action": "merged"}
                if errors:
                    entry["errors"] = errors[:5]
                    entry["error_count"] = len(errors)
                summary[name] = entry

        except Exception as exc:  # noqa: BLE001
            logger.exception("snapshot apply collection=%s failed", name)
            summary[name] = {"before": before, "incoming": len(rows), "action": "error",
                             "error": str(exc)[:300]}
            continue

    return summary


@api.get("/admin/snapshots", tags=["Admin"])
async def admin_list_snapshots(_: dict = Depends(get_current_admin)):
    """List all snapshots ordered by created_at desc."""
    docs = [r async for r in db.db_snapshots.find({}, {"_id": 0}).sort("created_at", -1)]
    return {"snapshots": docs, "count": len(docs)}


async def _create_snapshot_record(comment: str, mask_secrets: bool, author_id: Optional[str], author_email: Optional[str], kind: str = "manual") -> dict:
    """Build a snapshot file on disk + insert metadata into db.db_snapshots.
    Reusable from the HTTP endpoint and the weekly cron. Returns the metadata
    dict (already _id-stripped via serialize)."""
    snap_id = _uuid()
    file_name = f"snapshot_{snap_id}.json.gz"
    file_path = SNAPSHOTS_DIR / file_name
    snap_payload, stats = await _build_snapshot_payload(mask_secrets=mask_secrets)
    raw = json.dumps(snap_payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=6)
    file_path.write_bytes(compressed)
    meta = {
        "id": snap_id,
        "created_at": _now(),
        "author_id": author_id,
        "author_email": author_email,
        "comment": (comment or "").strip()[:500],
        "size_bytes": len(compressed),
        "raw_size_bytes": len(raw),
        "collections_count": len([k for k, v in stats.items() if v > 0]),
        "total_documents": sum(stats.values()),
        "stats": stats,
        "mask_secrets": mask_secrets,
        "file_name": file_name,
        "kind": kind,  # "manual" | "auto"
    }
    await db.db_snapshots.insert_one(dict(meta))
    return serialize(meta)


@api.post("/admin/snapshots", tags=["Admin"])
async def admin_create_snapshot(payload: Dict[str, Any] = Body(default={}), user: dict = Depends(get_current_admin)):
    """Create a new snapshot of all business collections.
    Body: {comment?: str, mask_secrets?: bool=True}
    """
    comment = (payload.get("comment") or "").strip()[:500]
    mask_secrets = bool(payload.get("mask_secrets", True))
    return await _create_snapshot_record(
        comment=comment,
        mask_secrets=mask_secrets,
        author_id=user.get("id"),
        author_email=user.get("email"),
        kind="manual",
    )


@api.get("/admin/snapshots/{snap_id}/download", tags=["Admin"])
async def admin_download_snapshot(snap_id: str, _: dict = Depends(get_current_admin)):
    meta = await db.db_snapshots.find_one({"id": snap_id}, {"_id": 0})
    if not meta:
        raise HTTPException(status_code=404, detail="Snapshot introuvable")
    file_path = SNAPSHOTS_DIR / meta["file_name"]
    if not file_path.exists():
        raise HTTPException(status_code=410, detail="Fichier physique manquant")
    return FileResponse(str(file_path), media_type="application/gzip", filename=meta["file_name"])


@api.patch("/admin/snapshots/{snap_id}", tags=["Admin"])
async def admin_update_snapshot(snap_id: str, payload: Dict[str, Any] = Body(...), _: dict = Depends(get_current_admin)):
    update: Dict[str, Any] = {}
    if "comment" in payload:
        update["comment"] = (payload.get("comment") or "").strip()[:500]
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    update["updated_at"] = _now()
    res = await db.db_snapshots.update_one({"id": snap_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Snapshot introuvable")
    meta = await db.db_snapshots.find_one({"id": snap_id}, {"_id": 0})
    return serialize(meta)


@api.delete("/admin/snapshots/{snap_id}", tags=["Admin"])
async def admin_delete_snapshot(snap_id: str, _: dict = Depends(get_current_admin)):
    meta = await db.db_snapshots.find_one({"id": snap_id}, {"_id": 0})
    if not meta:
        raise HTTPException(status_code=404, detail="Snapshot introuvable")
    file_path = SNAPSHOTS_DIR / meta["file_name"]
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Snapshot %s file delete failed: %s", snap_id, exc)
    await db.db_snapshots.delete_one({"id": snap_id})
    return {"ok": True, "id": snap_id}


# ============================================================
# Auto-snapshot — weekly cron + admin-controlled toggle/run-now.
# Keeps only the last N (default 4) auto snapshots; manual ones never rotate.
# Driven by settings.auto_snapshot_enabled, .auto_snapshot_keep (int) and
# logged into db.db_snapshots with kind='auto'.
# ============================================================
AUTO_SNAPSHOT_DEFAULT_KEEP = 4


async def _run_auto_snapshot(triggered_by: str = "cron:weekly") -> dict:
    """Create an auto snapshot then prune older auto snapshots beyond the
    rotation window. Idempotent (safe to call manually too). If
    settings.auto_snapshot_email_enabled and a recipient is configured, the
    .json.gz file is sent as an SMTP attachment to that address."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    keep = int(s.get("auto_snapshot_keep") or AUTO_SNAPSHOT_DEFAULT_KEEP)
    keep = max(1, min(keep, 52))  # clamp 1..52 weeks
    meta = await _create_snapshot_record(
        comment=f"Sauvegarde automatique — {triggered_by}",
        mask_secrets=True,
        author_id=None,
        author_email="(système)",
        kind="auto",
    )
    # Rotation: delete older auto snapshots beyond `keep`
    autos_cursor = db.db_snapshots.find(
        {"kind": "auto"}, {"_id": 0, "id": 1, "file_name": 1, "created_at": 1}
    ).sort("created_at", -1)
    autos = [a async for a in autos_cursor]
    to_delete = autos[keep:]
    deleted = 0
    for a in to_delete:
        fp = SNAPSHOTS_DIR / (a.get("file_name") or "")
        try:
            if fp.exists():
                fp.unlink()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto-snapshot %s file delete failed: %s", a.get("id"), exc)
        await db.db_snapshots.delete_one({"id": a["id"]})
        deleted += 1
    # Email delivery (best-effort, never blocks rotation)
    email_status: Dict[str, Any] = {"enabled": bool(s.get("auto_snapshot_email_enabled")), "sent": False, "to": None}
    if s.get("auto_snapshot_email_enabled"):
        recipient = (s.get("auto_snapshot_email_to") or "").strip()
        if recipient and "@" in recipient:
            email_status["to"] = recipient
            try:
                file_path = SNAPSHOTS_DIR / meta["file_name"]
                if file_path.exists():
                    content = file_path.read_bytes()
                    pretty_size = f"{len(content)/1024:.1f} kB"
                    # Build the companion weekly health report PDF
                    pdf_bytes = b""
                    pdf_attached = False
                    try:
                        from health_report import build_weekly_health_pdf
                        pdf_bytes = await build_weekly_health_pdf(snapshot_meta=meta)
                        pdf_attached = bool(pdf_bytes)
                    except Exception as pdf_exc:  # noqa: BLE001
                        logger.warning("Weekly PDF generation failed: %s", pdf_exc)
                    subject = f"[SAWALI] Sauvegarde DB + Rapport hebdomadaire — {meta['file_name']}"
                    html = (
                        f"<div style=\"font-family:Arial,sans-serif;line-height:1.5\">"
                        f"<h2 style=\"color:#0E1F3D\">SAWALI — Sauvegarde DB &amp; Rapport hebdomadaire</h2>"
                        f"<p>Bonjour,</p>"
                        f"<p>Voici votre sauvegarde automatique accompagnée du rapport de santé de la plateforme.</p>"
                        f"<ul>"
                        f"<li><strong>Date</strong> : {meta['created_at']}</li>"
                        f"<li><strong>Déclencheur</strong> : <code>{triggered_by}</code></li>"
                        f"<li><strong>Documents</strong> : {meta['total_documents']} sur {meta['collections_count']} collections</li>"
                        f"<li><strong>Taille snapshot</strong> : {pretty_size}</li>"
                        f"<li><strong>Secrets masqués</strong> : {'oui' if meta.get('mask_secrets') else 'non'}</li>"
                        f"<li><strong>Rapport PDF</strong> : {'joint' if pdf_attached else 'non disponible'}</li>"
                        f"</ul>"
                        f"<p>Pièces jointes : <code>{meta['file_name']}</code>"
                        f"{' + <code>rapport-hebdomadaire.pdf</code>' if pdf_attached else ''}</p>"
                        f"<p style=\"color:#64748B;font-size:12px\">Pour désactiver l'envoi par email, "
                        f"rendez-vous dans Paramètres → Sauvegarde de la base.</p>"
                        f"</div>"
                    )
                    text = (
                        f"Sauvegarde DB SAWALI — {meta['file_name']}\n"
                        f"Date: {meta['created_at']}\n"
                        f"Déclencheur: {triggered_by}\n"
                        f"Documents: {meta['total_documents']} ({meta['collections_count']} collections)\n"
                        f"Taille snapshot: {pretty_size}\n"
                        f"Rapport PDF joint: {'oui' if pdf_attached else 'non'}\n"
                    )
                    atts = [{
                        "filename": meta["file_name"],
                        "content": content,
                        "mime_type": "application/gzip",
                    }]
                    if pdf_attached:
                        atts.append({
                            "filename": f"rapport-hebdomadaire-{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf",
                            "content": pdf_bytes,
                            "mime_type": "application/pdf",
                        })
                    sent = await send_email(
                        recipient, subject, html, text,
                        attachments=atts,
                    )
                    email_status["sent"] = bool(sent)
                    email_status["pdf_attached"] = pdf_attached
                else:
                    email_status["error"] = "fichier introuvable"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto-snapshot email failed: %s", exc)
                email_status["error"] = str(exc)
        else:
            email_status["error"] = "auto_snapshot_email_to non configuré"
    # Persist last_run marker on settings for the UI
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "auto_snapshot_last_run_at": _now(),
            "auto_snapshot_last_run_id": meta["id"],
            "auto_snapshot_last_run_trigger": triggered_by,
            "auto_snapshot_last_email_sent": email_status.get("sent", False),
            "auto_snapshot_last_email_to": email_status.get("to"),
        }},
        upsert=True,
    )
    return {"snapshot": meta, "deleted": deleted, "kept": min(len(autos) + 1 - deleted, keep), "email": email_status}


@api.post("/admin/snapshots/auto-run", tags=["Admin"])
async def admin_run_auto_snapshot(user: dict = Depends(get_current_admin)):
    """Trigger the weekly auto-snapshot logic immediately (manual)."""
    return await _run_auto_snapshot(triggered_by=f"manual:{user.get('email','admin')}")


@api.get("/admin/snapshots/weekly-report-preview", tags=["Admin"])
async def admin_preview_weekly_report(_: dict = Depends(get_current_admin)):
    """Render the weekly health-report PDF on-demand. Useful for the admin
    to verify what gets attached to the snapshot email."""
    try:
        from health_report import build_weekly_health_pdf
        pdf_bytes = await build_weekly_health_pdf(snapshot_meta=None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Génération PDF échouée: {exc}")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="rapport-hebdomadaire-preview.pdf"'},
    )


# ============================================================
# Iter34h — Roadmap actions tracker
# Auto-numbered log of every dev iteration (manual seed below). Admins can
# edit only the `observations` column from the UI. All other fields are
# auto-populated by the developer when each task lands.
# ============================================================
DEFAULT_ROADMAP_HOURLY_RATE_XOF = 25000  # ~50 USD/h dev rate, adjustable below

# Seed list — chronological ordering preserved. `code` is the human-readable
# auto number ("ACT-0001"…) and is the canonical ID on disk. Done items have
# `done_at` set; pending items keep it null.
ROADMAP_SEED: List[Dict[str, Any]] = [
    {"code": "ACT-0001", "created_at": "2026-05-09T00:00:00+00:00", "done_at": "2026-05-09T18:30:00+00:00",
     "title": "Diagnostic des données orphelines", "backlog_ref": "Iter28",
     "duration_h": 2.0, "done": True,
     "details": "Endpoint /api/admin/migrate-orphan-data + UI bouton dans /admin/settings pour réaligner contacts/RDV/interventions sans client_id valide."},
    {"code": "ACT-0002", "created_at": "2026-05-10T00:00:00+00:00", "done_at": "2026-05-10T08:00:00+00:00",
     "title": "Contact Collaborative Model (shared by default)", "backlog_ref": "Iter29",
     "duration_h": 1.5, "done": True,
     "details": "Le champ `shared=true` est désormais le défaut sur les nouveaux contacts."},
    {"code": "ACT-0003", "created_at": "2026-05-10T08:00:00+00:00", "done_at": "2026-05-10T11:30:00+00:00",
     "title": "Cohérence multi-utilisateurs (canary + UI Realignment)", "backlog_ref": "Iter30+31",
     "duration_h": 3.0, "done": True,
     "details": "Diagnostic visibilité par utilisateur + bouton 'Résoudre' qui réaligne automatiquement client_id."},
    {"code": "ACT-0004", "created_at": "2026-05-10T11:30:00+00:00", "done_at": "2026-05-10T13:00:00+00:00",
     "title": "Auto-link user→company à la création", "backlog_ref": "Iter32",
     "duration_h": 1.0, "done": True,
     "details": "Au moment de la création d'un user tracked, son client_id est lié automatiquement au parent de la même `company`."},
    {"code": "ACT-0005", "created_at": "2026-05-10T13:00:00+00:00", "done_at": "2026-05-10T15:00:00+00:00",
     "title": "Recherche/filtre + bulles NOUVEAU dans /admin/settings", "backlog_ref": "Iter33",
     "duration_h": 2.0, "done": True,
     "details": "Toolbar sticky avec input de recherche, dropdown 'Aller à', 9 sections marquées NOUVEAU avec fade automatique après 3 jours."},
    {"code": "ACT-0006", "created_at": "2026-05-10T15:00:00+00:00", "done_at": "2026-05-10T17:00:00+00:00",
     "title": "DB Snapshots — Export/Import depuis /admin/settings", "backlog_ref": "Iter34",
     "duration_h": 2.0, "done": True,
     "details": "6 endpoints /api/admin/snapshots* : create/list/download/patch/delete/import. Masquage automatique des secrets. Modes replace/merge + dry-run."},
    {"code": "ACT-0007", "created_at": "2026-05-10T17:00:00+00:00", "done_at": "2026-05-10T17:30:00+00:00",
     "title": "Société autocomplete (datalist) dans Contacts.jsx", "backlog_ref": "Iter34",
     "duration_h": 0.5, "done": True,
     "details": "Champ Société → <input list> HTML5 avec datalist (filtrage natif + saisie libre)."},
    {"code": "ACT-0008", "created_at": "2026-05-10T17:30:00+00:00", "done_at": "2026-05-10T18:00:00+00:00",
     "title": "Visibilité partagée des contacts entre utilisateurs même société", "backlog_ref": "Iter34/Issue 3",
     "duration_h": 0.5, "done": True,
     "details": "Helper _resolve_visible_client_ids() bridge contacts entre users du même `company` (case-insensitive)."},
    {"code": "ACT-0009", "created_at": "2026-05-10T18:00:00+00:00", "done_at": "2026-05-10T18:30:00+00:00",
     "title": "Auto-snapshot hebdomadaire (cron dimanche 03:00)", "backlog_ref": "Iter34b",
     "duration_h": 0.5, "done": True,
     "details": "APScheduler `db_auto_snapshot_weekly` + endpoint /api/admin/snapshots/auto-run + UI toggle + rotation configurable (1..52)."},
    {"code": "ACT-0010", "created_at": "2026-05-10T18:30:00+00:00", "done_at": "2026-05-10T19:00:00+00:00",
     "title": "Envoi email du snapshot + Rapport PDF hebdomadaire", "backlog_ref": "Iter34c+d",
     "duration_h": 0.5, "done": True,
     "details": "send_email() étendu pour pièces jointes multiples. Module health_report.py génère un PDF reportlab (charte SAWALI). Bouton 'Aperçu PDF' dans /admin/settings."},
    {"code": "ACT-0011", "created_at": "2026-05-10T19:00:00+00:00", "done_at": "2026-05-10T19:30:00+00:00",
     "title": "Tendance 30 jours + WoW arrows dans le rapport PDF", "backlog_ref": "Iter34e+f",
     "duration_h": 0.5, "done": True,
     "details": "3 sparklines (contacts/RDV/WA) via reportlab LinePlot. Comparaison Semaine vs S-1 avec arrows ↑↓= colorés sur 7 KPIs."},
    {"code": "ACT-0012", "created_at": "2026-05-10T19:30:00+00:00", "done_at": "2026-05-10T20:00:00+00:00",
     "title": "KPI 'Connexions & pages visitées' dans /admin/usage", "backlog_ref": "Iter34f",
     "duration_h": 0.5, "done": True,
     "details": "GET /api/admin/user-activity avec filtres période + société. UserActivityCard avec 3 mini-KPIs + 2 tables (derniers logins, top pages)."},
    {"code": "ACT-0013", "created_at": "2026-05-10T20:00:00+00:00", "done_at": "2026-05-10T20:30:00+00:00",
     "title": "Carte de chaleur 7×24 (Lun-Dim × 0h-23h)", "backlog_ref": "Iter34g",
     "duration_h": 0.5, "done": True,
     "details": "GET /api/admin/user-activity/heatmap. Frontend ActivityHeatmap (cellules cliquables, tooltips). Rendu PDF avec coloration RGB pré-mélangée."},
    {"code": "ACT-0014", "created_at": "2026-05-10T20:30:00+00:00", "done_at": "2026-05-10T20:45:00+00:00",
     "title": "Bug fix: Jauge support invisible sur mobile", "backlog_ref": "Iter34g",
     "duration_h": 0.25, "done": True,
     "details": "Cause: `hidden md:block` dans MarketingNav.jsx. Fix: gauge inline compacte sur mobile avec label tronqué."},
    {"code": "ACT-0015", "created_at": "2026-05-10T21:00:00+00:00", "done_at": "2026-05-10T21:30:00+00:00",
     "title": "Suivi des actions (Roadmap tracker) dans /admin/settings", "backlog_ref": "Iter34h",
     "duration_h": 0.5, "done": True,
     "details": "Nouvelle collection db.roadmap_actions + 2 endpoints (GET liste, PATCH observations). UI tableau dans /admin/settings filtrable avec numéro auto, dates, durée, coût estimé, observations éditables admin."},
    {"code": "ACT-0016", "created_at": "2026-05-10T21:30:00+00:00", "done_at": "2026-05-10T21:45:00+00:00",
     "title": "Bug fix RGPD: SMS/WhatsApp envoyaient le numéro masqué", "backlog_ref": "Iter34h",
     "duration_h": 0.25, "done": True,
     "details": "Helper _resolve_real_phone(contact_id, field) restaure le numéro réel depuis la DB au moment de l'envoi. Appliqué à /me/whatsapp/send, /me/whatsapp/send-text, /me/sms/send."},
    {"code": "ACT-0017", "created_at": "2026-05-10T22:00:00+00:00", "done_at": "2026-05-10T22:10:00+00:00",
     "title": "Export CSV du Suivi des actions", "backlog_ref": "Iter34i",
     "duration_h": 0.2, "done": True,
     "details": "Bouton 'Exporter CSV' avec séparateur `;` + BOM UTF-8 (Excel-FR friendly). Échappement RFC 4180. Filename auto-daté."},
    {"code": "ACT-0018", "created_at": "2026-05-10T22:10:00+00:00", "done_at": "2026-05-10T22:25:00+00:00",
     "title": "Création/Toggle/Suppression d'actions depuis l'UI admin", "backlog_ref": "Iter34i",
     "duration_h": 0.4, "done": True,
     "details": "POST /api/admin/roadmap-actions (création auto-numérotée). PATCH étendu pour toggler `done` (auto-rempli `done_at`). DELETE protège les 16 entrées du seed historique."},
    {"code": "ACT-0019", "created_at": "2026-05-10T22:25:00+00:00", "done_at": "2026-05-10T22:30:00+00:00",
     "title": "Version auto-bumpée depuis le compteur d'actions livrées", "backlog_ref": "Iter34i",
     "duration_h": 0.15, "done": True,
     "details": "Endpoint /api/version calcule désormais `1.<N>` où N = nombre d'actions roadmap réalisées. Visible en bas-gauche de chaque page via VersionStamp."},
    {"code": "ACT-0020", "created_at": "2026-05-10T22:30:00+00:00", "done_at": "2026-05-10T22:40:00+00:00",
     "title": "Bouton 'Réinitialiser' dans Usage & Facturation", "backlog_ref": "Iter34i",
     "duration_h": 0.2, "done": True,
     "details": "Bouton avec panneau de confirmation : mode 'Mettre à 0' (offset, données conservées) ou 'Purge complète' (suppression définitive des visits + access_logs). Confirm fort en cas de purge."},
    {"code": "ACT-0021", "created_at": "2026-05-10T22:45:00+00:00", "done_at": "2026-05-10T23:10:00+00:00",
     "title": "Vue Kanban (À faire / En cours / Réalisée)", "backlog_ref": "Iter34j",
     "duration_h": 0.5, "done": True,
     "details": "Nouveau champ `status` (todo|in_progress|done) sur roadmap_actions, backfill auto. Vue Kanban click-to-move 3 colonnes. Switcher Tableau/Kanban. Cartes avec code+titre+backlog+durée+coût+boutons déplacer."},
    {"code": "ACT-0022", "created_at": "2026-05-10T23:15:00+00:00", "done_at": "2026-05-10T23:35:00+00:00",
     "title": "Page 'Mon compte' (informations utilisateur lecture seule)", "backlog_ref": "Iter34k",
     "duration_h": 0.5, "done": True,
     "details": "Endpoints /me/account-detail (identity+parent_client+last_seen+counters Rapports/Suivis/Contacts) + /me/profile-update-request. Page /portal/my-account cliquable depuis le profil dans la sidebar. Lecture seule avec icône cadenas + formulaire de demande de modification à l'admin (checkboxes des champs + message)."},
    {"code": "ACT-0024", "created_at": "2026-05-10T23:45:00+00:00", "done_at": "2026-05-11T00:30:00+00:00",
     "title": "Admin UI — Demandes de modification de profil (utilisateurs)", "backlog_ref": "Iter34l",
     "duration_h": 0.75, "done": True,
     "details": "Endpoints GET/PATCH /admin/profile-requests (filtres pending/processed/all, note interne, marquer traitée/rouvrir). Section dédiée dans /admin/settings avec badge 'X en attente' + filtres + note admin. Compteur `admin_profile_requests` ajouté à /me/notifications/counts → badge sur le lien Paramètres du sidebar (clear automatique quand pending=0). 7 tests pytest verts."},
    {"code": "ACT-0025", "created_at": "2026-05-11T00:30:00+00:00", "done_at": "2026-05-11T01:15:00+00:00",
     "title": "Bug fix — Détection & réparation du pointeur parent_client_id périmé", "backlog_ref": "Iter34m",
     "duration_h": 0.75, "done": True,
     "details": "Cas rabo.f@sawalismartsystems.com : `company` typé 'SAWALI SMART SYSTEMS' mais `parent_client_id` pointait encore vers 'Clinique CMCO'. Le diagnostic disait 'Aucun désalignement' car il faisait confiance au parent_client_id. Fix: cross-check de la company du parent vs typed company → bascule sur la company typée si admin canonical trouvé, nouvelle action `relink_parent`, exposé en UI dans /admin/settings (alert rose + ligne dans le plan de réalignement). 2 tests E2E pytest verts."},
    {"code": "ACT-0026", "created_at": "2026-05-11T01:20:00+00:00", "done_at": "2026-05-11T02:00:00+00:00",
     "title": "Garde-fou auto-realign quand `company` change dans /admin/clients", "backlog_ref": "Iter34n",
     "duration_h": 0.5, "done": True,
     "details": "PUT /admin/clients/{id} détecte les changements de `company` et déclenche en arrière-plan la même logique que /admin/realign-user-to-client (relink_parent + retag rows + set client_id). Le payload de réponse expose `auto_realign: {applied, to_company, to_canonical_id, actions_count}` ou `{applied:false, reason:'no_canonical_for_company'}` quand la société typée ne matche aucun admin/primaire. Frontend AdminClients.jsx affiche un toast vert succès ou un toast warning explicite. 3 tests pytest verts (auto-fix, typo unresolvable, no-change-no-action)."},
    {"code": "ACT-0027", "created_at": "2026-05-11T08:30:00+00:00", "done_at": "2026-05-11T09:30:00+00:00",
     "title": "Bug fix critique — Retag trop large + endpoint de restauration + auto-scroll chat", "backlog_ref": "Iter34o",
     "duration_h": 1.0, "done": True,
     "details": "ROOT CAUSE: le retag de iter34m/n bougeait toutes les rows partageant client_id=old_scope (ex: tous les contacts CMCO migraient vers SAWALI quand on alignait rabo.f). FIX prospectif: filtrage owner_id/sender_id/created_by/author_id/user_id → seules les rows démontrablement appartenant à l'utilisateur réaligné bougent. FIX rétroactif: nouvel endpoint POST /admin/contacts/revert-retag (dry-run + apply, idempotent, filtres from/to/collections, restaure users.parent_client_id_legacy aussi). UI: section dédiée dans /admin/settings (cases à cocher par collection, aperçu avant action). BONUS UX: la fenêtre de discussion WhatsApp dans /portal/contacts auto-scrolle désormais sur le dernier message (initial 'auto', suivants 'smooth'). 4 tests pytest verts (retag owner-scoped, dry-run, apply+idempotent, from-filter)."},
    {"code": "ACT-0028", "created_at": "2026-05-11T10:00:00+00:00", "done_at": "2026-05-11T13:30:00+00:00",
     "title": "Visibilité cross-scope + Héritage RGPD + UI Centre Messagerie/Clients", "backlog_ref": "Iter34p",
     "duration_h": 2.5, "done": True,
     "details": "7 fixes en un seul shot. (1) Bug 'Contact introuvable' : /me/contacts/{cid}/messages, /me/contacts/{cid}/messages/mark-read, /me/whatsapp/unread et /me/sms/messages utilisent désormais _resolve_visible_client_ids (au lieu de client_scope seul). (2) Héritage RGPD : /me/features et _resolve_anon_flags utilisent désormais parent_client_id en priorité sur client_id. (3) Centre Messagerie: header affiche société + client lié dans des pills sky/emerald. (4) Centre Messagerie: colonne email réduite à 140px, mobile-only context phone passé en bleu. (5) Module Clients: endpoint /admin/clients inclut admin + moderateur (sauf SAWALI seed), UI groupée par rôle avec en-tête coloré. (6) Hover highlight (hover:bg-sky-50 + hover:ring-1 hover:ring-sky-200) sur lignes contacts, lignes clients et bulles de message. (7) Numéros de contact en text-sky-600 (téléphone + whatsapp). 3 tests pytest verts (admin_clients roles, cross-scope messages, RGPD inheritance via JWT forge)."},
    {"code": "ACT-0029", "created_at": "2026-05-11T14:00:00+00:00", "done_at": "2026-05-11T14:30:00+00:00",
     "title": "Filtres rapides par rôle avec compteurs dans le module Clients", "backlog_ref": "Iter34q",
     "duration_h": 0.5, "done": True,
     "details": "Pills cliquables au-dessus du tableau (Tous / Admins clients / Superviseurs / Clients / Modérateurs / Autres) avec compteurs en direct. Filtrage actif via useMemo + roleFilter state. Pills colorées (sky/amber/fuchsia/slate) selon le rôle, état actif distinct, hover. Compteurs respectent le scope visible (admin SAWALI seed exclu). Empty-state contextualisé quand filtre vide. UX inspirée des filtres GitHub Issues."},
    {"code": "ACT-0030", "created_at": "2026-05-11T15:00:00+00:00", "done_at": "2026-05-11T15:20:00+00:00",
     "title": "Filtres rapides 'Partagés/Privés/Non-lus' au Centre de Messagerie", "backlog_ref": "Iter34r",
     "duration_h": 0.3, "done": True,
     "details": "4 pills cliquables au-dessus du tableau Centre de Messagerie (Tous / Partagés équipe / Privés / Non-lus) avec compteurs vivants qui respectent les autres filtres (search + société). Couleurs slate/emerald/amber/rose par catégorie, état actif distinct (background fort), inactif (hover coloré subtil). Toggle 100% client-side via useMemo."},
    {"code": "ACT-0031", "created_at": "2026-05-11T16:00:00+00:00", "done_at": "2026-05-11T16:20:00+00:00",
     "title": "Raccourci SMART Communications sur 'Mon compte' + titres bleus des groupes Clients", "backlog_ref": "Iter34s",
     "duration_h": 0.3, "done": True,
     "details": "1) /portal/my-account : nouvelle carte 'SMART Communications' (admin/superviseur only) avec gradient fuchsia/sky, badge ADMIN, mène vers /admin/clients/{user.id}/features. Permet à l'admin SAWALI de paramétrer RGPD/WA/SMS/IA/paiements depuis sa propre fiche — réglages hérités par tous les utilisateurs liés (logique iter34p). 2) /admin/clients : les en-têtes de groupe (ADMINS CLIENTS, CLIENTS, etc.) passent en text-sawali-blue avec gradient sky-100 — bien plus visibles que le slate précédent."},
    {"code": "ACT-0032", "created_at": "2026-05-12T22:00:00+00:00", "done_at": "2026-05-12T23:00:00+00:00",
     "title": "Anonymisation des contenus + Exports contacts + Toasts live + Anti-doublon formulaires + Code en bleu", "backlog_ref": "Iter34tuvwx",
     "duration_h": 3.5, "done": True,
     "details": "6 demandes utilisateur livrées en parallèle. (#1) 3 nouveaux flags anon_rapports / anon_suivis / anon_communications avec helper _resolve_content_restrictions + enforcement sur me_list_notes, me_contact_messages, me_sms_messages. UI dans SMART Communications. (#2) Code unique contacts en font-bold + text-sky-600. (#3) Endpoints /me/contacts/export.{csv,json,pdf} + dropdown UI dans Contacts.jsx (ContactsExportMenu). (#4) Activity feed via polling : table activity_events + endpoint /me/recent-activity + hook useActivityFeedNotifier.js (toasts Sonner toutes les 8s pour Contact/Rapport/Suivi/SMS/WhatsApp, suppression auto des actions du viewer). (#5) Endpoint /me/forms/{form_id}/submissions-table + composant SubmissionsTable dans FormAnalyticsDetail (tableau brut visible + ligne hover sky). (#6) Endpoint /me/forms/title-suggestions + check 409 sur POST /me/forms et PUT /me/forms/{id} si nom dupliqué. UI : modal de création avec datalist autocomplete + détection live du conflit (bordure rose + message + bouton Créer désactivé). 31/31 tests iter34 verts."},
    {"code": "ACT-0033", "created_at": "2026-05-13T00:00:00+00:00", "done_at": "2026-05-13T00:30:00+00:00",
     "title": "Activity feed élargi (rdv/intervention/paiement) + Interventions UI (Client picker + voice note + filtre) + Filtre client Suivis", "backlog_ref": "Iter34y",
     "duration_h": 1.5, "done": True,
     "details": "Élargissement de l'activity feed iter34x: _log_activity wired aussi sur appointments.insert, interventions.insert/delete, payment_links.insert (kinds = appointment / intervention / payment), 3 nouveaux labels FR dans useActivityFeedNotifier. Page Interventions entièrement refondue: dropdown filtre dans l'en-tête de colonne Client lié (compteurs par client), colonne 'Note vocale' avec audio player inline, modal de création avec select Client lié (chargé depuis /me/clients) et nouveau composant VoiceNoteRecorder (MediaRecorder → /me/upload → voice_note_url). Models InterventionCreate/Update + UserNoteCreate/Update enrichis du champ voice_note_url. Page Suivis (UserNotes.jsx) reçoit un select 'Tous les clients liés' avec compteurs par client, useMemo filtré côté front. 31/31 tests iter34 verts maintenus."},
    {"code": "ACT-0034", "created_at": "2026-05-13T00:30:00+00:00", "done_at": "2026-05-13T00:45:00+00:00",
     "title": "Transcription automatique des notes vocales (Whisper)", "backlog_ref": "Iter34z",
     "duration_h": 0.25, "done": True,
     "details": "VoiceNoteRecorder appelle /transcribe (Whisper) automatiquement après l'upload réussi. Affiche un textarea éditable sous le lecteur audio + bouton 'Re-transcrire' (réutilise le blob en mémoire). Stockage du texte dans voice_note_transcript (ajouté aux models InterventionCreate/Update + UserNoteCreate/Update). Toast Info dégradé quand OpenAI non configuré (503) — la note vocale est sauvegardée quand même. Affichage du transcript en italique sur la liste des interventions sous le player (line-clamp-2 + tooltip)."},
]


async def _seed_roadmap_actions() -> int:
    """Insert any missing seed entries into db.roadmap_actions. Idempotent."""
    inserted = 0
    for entry in ROADMAP_SEED:
        existing = await db.roadmap_actions.find_one({"code": entry["code"]}, {"_id": 0, "code": 1})
        if existing:
            continue
        doc = {
            "id": _uuid(),
            "code": entry["code"],
            "created_at": entry["created_at"],
            "done_at": entry.get("done_at"),
            "title": entry["title"],
            "backlog_ref": entry.get("backlog_ref") or "",
            "details": entry.get("details") or "",
            "duration_h": float(entry.get("duration_h") or 0),
            "cost_xof": int(round(float(entry.get("duration_h") or 0) * DEFAULT_ROADMAP_HOURLY_RATE_XOF)),
            "done": bool(entry.get("done")),
            "status": "done" if entry.get("done") else "todo",
            "observations": "",
        }
        await db.roadmap_actions.insert_one(doc)
        inserted += 1
    return inserted


@api.get("/admin/roadmap-actions", tags=["Admin"])
async def admin_list_roadmap_actions(_: dict = Depends(get_current_admin)):
    """List every roadmap action ordered by code asc. Seeds on first call.
    Iter34j: One-shot backfill of `status` for rows that pre-date the field."""
    await _seed_roadmap_actions()
    # Iter34j backfill: rows without `status` get inferred from `done`
    try:
        await db.roadmap_actions.update_many({"status": {"$exists": False}, "done": True}, {"$set": {"status": "done"}})
        await db.roadmap_actions.update_many({"status": {"$exists": False}}, {"$set": {"status": "todo"}})
    except Exception:
        pass
    items = [r async for r in db.roadmap_actions.find({}, {"_id": 0}).sort("code", 1)]
    total_h = sum(float(r.get("duration_h") or 0) for r in items if r.get("done"))
    total_xof = sum(int(r.get("cost_xof") or 0) for r in items if r.get("done"))
    return {
        "items": items,
        "totals": {
            "count": len(items),
            "done": sum(1 for r in items if r.get("status") == "done" or r.get("done")),
            "in_progress": sum(1 for r in items if r.get("status") == "in_progress"),
            "pending": sum(1 for r in items if (r.get("status") or "todo") == "todo" and not r.get("done")),
            "duration_h": round(total_h, 2),
            "cost_xof": total_xof,
            "hourly_rate_xof": DEFAULT_ROADMAP_HOURLY_RATE_XOF,
        },
    }


@api.patch("/admin/roadmap-actions/{code}", tags=["Admin"])
async def admin_patch_roadmap_action(code: str, payload: Dict[str, Any] = Body(...), _: dict = Depends(get_current_admin)):
    """Admins can edit `observations`, `done`/`status`, and (for their own
    pending actions) `title`, `backlog_ref`, `details`, `duration_h`.

    Iter34j: `status` field supports the Kanban view: "todo" | "in_progress"
    | "done". `done` boolean is kept in sync for backward compat. Setting
    `status=done` flips `done=true` and stamps `done_at`."""
    update: Dict[str, Any] = {}
    if "observations" in payload:
        update["observations"] = (payload.get("observations") or "")[:2000]
    if "title" in payload:
        update["title"] = (payload.get("title") or "").strip()[:200]
    if "backlog_ref" in payload:
        update["backlog_ref"] = (payload.get("backlog_ref") or "").strip()[:100]
    if "details" in payload:
        update["details"] = (payload.get("details") or "").strip()[:1000]
    if "duration_h" in payload:
        try:
            duration_h = max(0.0, float(payload["duration_h"]))
        except Exception:
            raise HTTPException(status_code=400, detail="duration_h invalide")
        update["duration_h"] = duration_h
        update["cost_xof"] = int(round(duration_h * DEFAULT_ROADMAP_HOURLY_RATE_XOF))
    existing = await db.roadmap_actions.find_one({"code": code}, {"_id": 0, "done": 1, "done_at": 1, "status": 1})
    if "status" in payload:
        status = (payload.get("status") or "").strip().lower()
        if status not in ("todo", "in_progress", "done"):
            raise HTTPException(status_code=400, detail="status invalide (todo|in_progress|done)")
        update["status"] = status
        if status == "done":
            update["done"] = True
            if not existing or not existing.get("done_at"):
                update["done_at"] = _now()
        else:
            update["done"] = False
            update["done_at"] = None
    elif "done" in payload:
        new_done = bool(payload["done"])
        update["done"] = new_done
        update["status"] = "done" if new_done else "todo"
        if new_done and (not existing or not existing.get("done_at")):
            update["done_at"] = _now()
        elif not new_done:
            update["done_at"] = None
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ modifiable fourni")
    update["updated_at"] = _now()
    res = await db.roadmap_actions.update_one({"code": code}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Action introuvable")
    item = await db.roadmap_actions.find_one({"code": code}, {"_id": 0})
    return item


def _next_roadmap_code(existing_codes: List[str]) -> str:
    """Compute the next sequential `ACT-####` based on the maximum existing
    numeric suffix. New entries always start with 'ACT-' to remain sortable
    alphabetically with the seed."""
    max_n = 0
    for c in existing_codes:
        try:
            n = int((c or "").split("-")[-1])
            if n > max_n:
                max_n = n
        except Exception:
            continue
    return f"ACT-{max_n + 1:04d}"


@api.post("/admin/roadmap-actions", tags=["Admin"])
async def admin_create_roadmap_action(payload: Dict[str, Any] = Body(...), _: dict = Depends(get_current_admin)):
    """Admin-driven creation of a pending action. Auto-numbered. Default
    `done=False`; can be flipped via the existing PATCH endpoint when
    delivered."""
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Le titre est obligatoire")
    await _seed_roadmap_actions()
    existing_codes = await db.roadmap_actions.distinct("code")
    code = _next_roadmap_code(existing_codes)
    duration_h = 0.0
    try:
        duration_h = max(0.0, float(payload.get("duration_h") or 0))
    except Exception:
        duration_h = 0.0
    done = bool(payload.get("done"))
    status = (payload.get("status") or ("done" if done else "todo")).lower()
    if status not in ("todo", "in_progress", "done"):
        status = "todo"
    if status == "done":
        done = True
    doc = {
        "id": _uuid(),
        "code": code,
        "created_at": _now(),
        "done_at": _now() if done else None,
        "title": title[:200],
        "backlog_ref": (payload.get("backlog_ref") or "").strip()[:100],
        "details": (payload.get("details") or "").strip()[:1000],
        "duration_h": duration_h,
        "cost_xof": int(round(duration_h * DEFAULT_ROADMAP_HOURLY_RATE_XOF)),
        "done": done,
        "status": status,
        "observations": "",
    }
    await db.roadmap_actions.insert_one(doc)
    out = dict(doc)
    out.pop("_id", None)
    return out


@api.delete("/admin/roadmap-actions/{code}", tags=["Admin"])
async def admin_delete_roadmap_action(code: str, _: dict = Depends(get_current_admin)):
    """Only admin-created (non-seed) entries can be deleted to keep the
    historical log intact. Seed entries start with ACT-0001..ACT-0016 and are
    protected — admins can edit them but not delete."""
    seed_codes = {e["code"] for e in ROADMAP_SEED}
    if code in seed_codes:
        raise HTTPException(status_code=403, detail="Les actions du seed historique ne peuvent pas être supprimées")
    res = await db.roadmap_actions.delete_one({"code": code})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Action introuvable")
    return {"ok": True, "code": code}




async def _dispatch_snapshot_import_recap(
    summary: dict,
    *,
    mode: str,
    comment: str,
    source_filename: Optional[str],
    size_bytes: int,
    user: dict,
) -> dict:
    """Iter35c — Send a recap of a snapshot import to the admin by email
    and (best-effort) WhatsApp. Returns {email: {...}, whatsapp: {...}}.

    Email is mandatory if SMTP is configured. WhatsApp uses `_wa_send_text`,
    which only works inside Meta's 24h customer service window — we attempt
    it anyway and capture the error in the result so the UI can show
    "WA non disponible (fenêtre 24h)" instead of failing the whole call.
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    # Build the summary table -- ignore unchanged collections (incoming=0 and before=0)
    rows = []
    total_after = 0
    total_before = 0
    total_incoming = 0
    has_error = False
    error_lines: List[str] = []
    for name, info in (summary or {}).items():
        before = info.get("before") if info.get("before") is not None else 0
        after = info.get("after") if info.get("after") is not None else before
        incoming = info.get("incoming") or 0
        action = info.get("action") or "?"
        if action == "error":
            has_error = True
            error_lines.append(f"{name}: {info.get('error', 'erreur')}")
        if incoming == 0 and (before or 0) == 0 and action not in ("error",):
            continue
        rows.append({"name": name, "before": before, "after": after, "incoming": incoming, "action": action})
        total_after += (after or 0)
        total_before += (before or 0)
        total_incoming += incoming
    rows.sort(key=lambda r: r["name"])

    when_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    actor = user.get("email") or user.get("full_name") or "Admin"
    headline = (
        "✅ Import de snapshot appliqué"
        if not has_error
        else "⚠️ Import de snapshot terminé AVEC ERREURS"
    )

    # ---------- Email body ----------
    table_rows = "".join(
        f"<tr><td style='padding:4px 8px;border:1px solid #E2E8F0;font-family:monospace;'>{r['name']}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{r['before']}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{r['after']}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{r['incoming']}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;'>{r['action']}</td></tr>"
        for r in rows
    ) or "<tr><td colspan='5' style='padding:8px;color:#94A3B8;text-align:center;'>Aucune collection impactée</td></tr>"
    errors_html = ""
    if error_lines:
        errors_html = (
            "<p style='color:#B91C1C;font-weight:600;margin-top:12px;'>Erreurs rencontrées :</p>"
            f"<ul style='color:#7F1D1D;'>{''.join(f'<li><code>{e}</code></li>' for e in error_lines[:10])}</ul>"
        )
    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:720px;'>"
        f"<h3 style='color:{'#16A34A' if not has_error else '#D97706'};margin-bottom:8px;'>{headline}</h3>"
        f"<p style='margin:4px 0;color:#475569;'>Effectué le <b>{when_str}</b> par <b>{actor}</b>.</p>"
        f"<p style='margin:4px 0;color:#475569;'>Fichier : <code>{source_filename or '—'}</code> "
        f"({(size_bytes / 1024):.1f} Ko) · Mode : <b>{mode}</b>" +
        (f" · Commentaire : <i>{comment}</i>" if (comment or '').strip() else "") +
        f"</p>"
        f"<table style='border-collapse:collapse;margin-top:8px;font-size:13px;'>"
        f"<thead style='background:#F1F5F9;'><tr>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:left;'>Collection</th>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>Avant</th>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>Après</th>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>Entrants</th>"
        f"<th style='padding:4px 8px;border:1px solid #E2E8F0;text-align:left;'>Action</th>"
        f"</tr></thead><tbody>{table_rows}</tbody>"
        f"<tfoot style='background:#F8FAFC;font-weight:bold;'>"
        f"<tr><td style='padding:4px 8px;border:1px solid #E2E8F0;'>TOTAL</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{total_before}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{total_after}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;text-align:right;'>{total_incoming}</td>"
        f"<td style='padding:4px 8px;border:1px solid #E2E8F0;'>—</td></tr></tfoot>"
        f"</table>"
        f"{errors_html}"
        f"<p style='color:#64748B;font-size:12px;margin-top:16px;'>Notification automatique — SAWALI Smart Systems CRM.</p>"
        f"</div>"
    )
    text = (
        f"{headline}\n"
        f"Effectué le {when_str} par {actor}.\n"
        f"Fichier {source_filename or '—'} ({(size_bytes / 1024):.1f} Ko) · mode={mode}"
        + (f" · commentaire={comment}" if (comment or '').strip() else "")
        + f"\n\nCollections impactées ({len(rows)}):\n"
        + "\n".join(f"  • {r['name']}: {r['before']}→{r['after']} (entrants {r['incoming']}, {r['action']})" for r in rows[:20])
        + (f"\n\nErreurs:\n" + "\n".join(f"  ! {e}" for e in error_lines[:10]) if error_lines else "")
    )

    # ---------- Send email ----------
    email_recipient = (s.get("auto_snapshot_email_to") or s.get("health_email_to") or SUPER_ADMIN_EMAIL or "").strip().lower()
    email_status: Dict[str, Any] = {"to": email_recipient, "sent": False, "error": None}
    if email_recipient and "@" in email_recipient:
        try:
            from email_service import send_email
            sent = await send_email(
                email_recipient,
                f"[SAWALI] {headline} ({len(rows)} collection(s))",
                html,
                text,
            )
            email_status["sent"] = bool(sent)
            if not sent:
                email_status["error"] = "send_email retourne False (SMTP non configuré ?)"
        except Exception as exc:  # noqa: BLE001
            email_status["error"] = str(exc)[:200]
            logger.warning("snapshot import recap email failed: %s", exc)
    else:
        email_status["error"] = "Aucune adresse destinataire configurée"

    # ---------- Send WhatsApp recap (best effort) ----------
    wa_status: Dict[str, Any] = {"attempts": [], "any_sent": False}
    wa_recipients_raw = s.get("liluvine_remote_admin_phones") or []
    if not wa_recipients_raw and s.get("company_whatsapp"):
        wa_recipients_raw = [s.get("company_whatsapp")]
    # Dedup & normalize
    seen_set = set()
    wa_recipients: List[str] = []
    for p in wa_recipients_raw:
        digits = "".join(ch for ch in (p or "") if ch.isdigit())
        if digits and digits not in seen_set:
            seen_set.add(digits)
            wa_recipients.append(digits)

    if wa_recipients:
        wa_text = (
            f"{headline}\n"
            f"{when_str} · par {actor}\n"
            f"Fichier: {source_filename or '—'} ({(size_bytes / 1024):.0f} Ko)\n"
            f"Mode: {mode} · {len(rows)} collection(s) impactée(s)\n"
            f"Total: {total_before} → {total_after} (entrants {total_incoming})"
            + (f"\n⚠️ {len(error_lines)} erreur(s)" if error_lines else "")
        )
        for phone in wa_recipients[:5]:  # cap at 5 admins
            try:
                wr = await _wa_send_text(phone, wa_text)
                wa_status["attempts"].append({
                    "to": phone,
                    "ok": bool(wr.get("ok")),
                    "error": wr.get("error") if not wr.get("ok") else None,
                })
                if wr.get("ok"):
                    wa_status["any_sent"] = True
            except Exception as exc:  # noqa: BLE001
                wa_status["attempts"].append({"to": phone, "ok": False, "error": str(exc)[:200]})
    else:
        wa_status["error"] = "Aucun numéro admin WhatsApp configuré (Paramètres → Liluvine)"

    return {"email": email_status, "whatsapp": wa_status, "has_error": has_error, "rows_count": len(rows)}



@api.post("/admin/snapshots/import", tags=["Admin"])
async def admin_import_snapshot(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    dry_run: str = Form("false"),
    comment: str = Form(""),
    user: dict = Depends(get_current_admin),
):
    """Import a snapshot file. mode = 'replace' | 'merge'. dry_run='true' to
    preview what would happen. Always logs into db.db_snapshots with
    kind='import'.

    Iter35c — on a non-dry-run import, also dispatches a recap notification
    by email and (best-effort) WhatsApp to the admin, with the per-collection
    summary table and a global success/error headline."""
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail="mode doit être 'replace' ou 'merge'")
    is_dry = str(dry_run).lower() in ("1", "true", "yes", "on")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Fichier vide")
    # Try gzip then plain JSON
    try:
        if file.filename and file.filename.endswith(".gz"):
            data = gzip.decompress(raw)
        else:
            try:
                data = gzip.decompress(raw)
            except Exception:
                data = raw
        payload = json.loads(data.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fichier invalide: {e}")
    if not isinstance(payload, dict) or "collections" not in payload:
        raise HTTPException(status_code=400, detail="Format de snapshot non reconnu")
    try:
        summary = await _apply_snapshot(payload, mode=mode, dry_run=is_dry)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("snapshot import crashed (dry_run=%s, mode=%s)", is_dry, mode)
        raise HTTPException(
            status_code=500,
            detail=f"Échec de l'importation: {str(exc)[:300]}",
        )
    # Persist an import log entry
    log = {
        "id": _uuid(),
        "kind": "import",
        "created_at": _now(),
        "author_id": user.get("id"),
        "author_email": user.get("email"),
        "comment": (comment or "").strip()[:500],
        "mode": mode,
        "dry_run": is_dry,
        "source_filename": file.filename,
        "size_bytes": len(raw),
        "summary": summary,
        "exported_at": payload.get("exported_at"),
    }
    await db.db_snapshot_imports.insert_one(dict(log))

    # Iter35c — on real imports only (not dry-run), notify admin by email + WA.
    notifications: Optional[Dict[str, Any]] = None
    if not is_dry:
        try:
            notifications = await _dispatch_snapshot_import_recap(
                summary,
                mode=mode,
                comment=(comment or "").strip(),
                source_filename=file.filename,
                size_bytes=len(raw),
                user=user,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("snapshot import recap dispatch failed: %s", exc)
            notifications = {"error": str(exc)[:200]}

    return {
        "ok": True,
        "dry_run": is_dry,
        "mode": mode,
        "summary": summary,
        "import_id": log["id"],
        "notifications": notifications,
    }


@api.get("/admin/snapshots/imports", tags=["Admin"])
async def admin_list_snapshot_imports(_: dict = Depends(get_current_admin)):
    docs = [r async for r in db.db_snapshot_imports.find({}, {"_id": 0}).sort("created_at", -1).limit(50)]
    return {"imports": docs, "count": len(docs)}


# ============================================================
# Iter35e — Secrets Vault.
#
# Why: when production has an incident (snapshot wipe, env reset, fresh
# install), the admin currently has to re-enter every API token by hand
# (WA, SMTP, SMS providers, PawaPay, OpenAI, Google…). The Vault solves
# this with an offline, password-encrypted bundle the admin can keep on
# their own device and restore in one click.
#
# Crypto: PBKDF2-HMAC-SHA256 (200k iterations) → AES-256-GCM. The output
# file is a JSON envelope:
#   { "v": 1, "alg": "AES-256-GCM/PBKDF2-SHA256-200k", "salt": b64, "nonce": b64, "ct": b64 }
# We never persist the password. We never persist the bundle on the server.
# ============================================================
# Allow-list of settings keys (a superset of SENSITIVE_SETTINGS_KEYS adds
# every other field that is awkward/painful to re-enter — Google client_id,
# Whatsapp WABA id, SMTP host, etc).
VAULT_KEYS = sorted(SENSITIVE_SETTINGS_KEYS | {
    # Iter35u — Public base URL (DB-backed override of the env var)
    "public_base_url",
    # WhatsApp Business (non-secret but needed)
    "wa_business_account_id", "wa_phone_number_id", "wa_app_id", "wa_default_language",
    # SMTP (smtp_password is already in sensitive, add the rest)
    "smtp_host", "smtp_port", "smtp_user", "smtp_from_email", "smtp_use_tls",
    # Google OAuth & calendar (non-secret IDs)
    "google_client_id", "google_calendar_email", "google_calendar_password_hint",
    # reCAPTCHA site key
    "recaptcha_site_key", "recaptcha_enabled",
    # Webhook urls (the secret is the token/pass)
    "webhook_base_url", "webhook_auth_type", "webhook_basic_user",
    "notes_webhook_url", "notes_webhook_auth_type", "notes_webhook_basic_user",
    "health_webhook_url", "health_webhook_auth_type", "health_webhook_basic_user",
    "n8n_webhook_url", "n8n_webhook_auth_type", "n8n_webhook_basic_user",
    # SMS providers — URLs + auth types + senders
    "sms_orange_enabled", "sms_orange_url", "sms_orange_method", "sms_orange_auth_type",
    "sms_orange_basic_user", "sms_orange_header_name", "sms_orange_sender",
    "sms_orange_oauth_url", "sms_orange_client_id", "sms_orange_sender_msisdn",  # Iter35i
    "sms_moov_enabled", "sms_moov_url", "sms_moov_method", "sms_moov_auth_type",
    "sms_moov_basic_user", "sms_moov_header_name", "sms_moov_sender",
    "sms_moov_oauth_url", "sms_moov_client_id", "sms_moov_sender_msisdn",
    "sms_telecel_enabled", "sms_telecel_url", "sms_telecel_method", "sms_telecel_auth_type",
    "sms_telecel_basic_user", "sms_telecel_header_name", "sms_telecel_sender",
    "sms_telecel_oauth_url", "sms_telecel_client_id", "sms_telecel_sender_msisdn",
    "sms_ovh_enabled", "sms_ovh_application_key", "sms_ovh_service_name", "sms_ovh_sender",
    # PawaPay
    "pawapay_environment", "pawapay_api_token_sandbox", "pawapay_api_token_production",
    "pawapay_callback_secret", "pawapay_default_country",
    # OpenAI
    "openai_whisper_model", "openai_chat_model", "ai_summary_provider",
    # Tracking
    "tracking_base_url", "tracking_endpoint",
    # Agenda / Liluvine
    "agenda_n8n_outbound_token", "agenda_n8n_outbound_basic_pass", "agenda_n8n_inbound_secret",
    "support_load_webhook_secret", "liluvine_remote_secret", "liluvine_remote_admin_phones",
})


def _vault_encrypt(plaintext: bytes, password: str) -> dict:
    """Encrypt the plaintext bundle with a user-chosen password.
    Uses PBKDF2-HMAC-SHA256 (200k iterations) for key derivation, then
    AES-256-GCM for authenticated encryption."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64
    import os as _os

    if not password or len(password) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit faire au moins 8 caractères")
    salt = _os.urandom(16)
    nonce = _os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    key = kdf.derive(password.encode("utf-8"))
    aes = AESGCM(key)
    ct = aes.encrypt(nonce, plaintext, associated_data=b"sawali-vault-v1")
    return {
        "v": 1,
        "alg": "AES-256-GCM/PBKDF2-SHA256-200k",
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
        "created_at": _now(),
    }


def _vault_decrypt(envelope: dict, password: str) -> bytes:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    import base64

    if not isinstance(envelope, dict) or "ct" not in envelope or envelope.get("v") != 1:
        raise HTTPException(status_code=400, detail="Format de coffre-fort non reconnu")
    try:
        salt = base64.b64decode(envelope["salt"])
        nonce = base64.b64decode(envelope["nonce"])
        ct = base64.b64decode(envelope["ct"])
    except Exception:
        raise HTTPException(status_code=400, detail="Format de coffre-fort corrompu")
    if not password:
        raise HTTPException(status_code=400, detail="Mot de passe requis")
    # AES-GCM requires nonce=12 bytes; validate up-front to give a clean
    # 400 instead of leaking a ValueError from the crypto lib.
    if len(nonce) != 12 or len(salt) < 8:
        raise HTTPException(status_code=400, detail="Coffre-fort altéré (champ salt/nonce invalide)")
    try:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
        key = kdf.derive(password.encode("utf-8"))
        aes = AESGCM(key)
        return aes.decrypt(nonce, ct, associated_data=b"sawali-vault-v1")
    except InvalidTag:
        raise HTTPException(status_code=400, detail="Mot de passe incorrect ou fichier altéré")
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Coffre-fort illisible: {exc}")


@api.get("/admin/secrets/keys", tags=["Admin"])
async def admin_list_vault_keys(_: dict = Depends(get_current_admin)):
    """List the settings keys saved by the vault, and which of them are
    currently populated (without revealing values)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    out = []
    for k in VAULT_KEYS:
        v = s.get(k)
        if isinstance(v, bool):
            populated = True  # toggles are always meaningful
        elif isinstance(v, (int, float)):
            populated = v != 0
        elif isinstance(v, list):
            populated = len(v) > 0
        else:
            populated = bool((v or "").strip()) if isinstance(v, str) else (v is not None)
        out.append({"key": k, "populated": populated, "is_secret": k in SENSITIVE_SETTINGS_KEYS})
    out.sort(key=lambda x: (not x["populated"], x["key"]))
    return {"keys": out, "total": len(out), "populated": sum(1 for x in out if x["populated"])}


@api.post("/admin/secrets/export", tags=["Admin"])
async def admin_vault_export(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
    """Export an AES-256-GCM encrypted bundle of every vaultable setting.
    Body: {"password": str, "comment": str?}. Returns a JSON envelope the
    admin must download and store offline. Never persisted on the server."""
    password = (payload.get("password") or "").strip()
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (8 caractères minimum)")
    s = await db.settings.find_one({"_id": "global"}) or {}
    bundle = {k: s.get(k) for k in VAULT_KEYS if k in s}
    plaintext = json.dumps({
        "kind": "sawali-secrets-vault",
        "version": 1,
        "exported_at": _now(),
        "exported_by": user.get("email"),
        "comment": (payload.get("comment") or "").strip()[:200],
        "settings": bundle,
    }, ensure_ascii=False, default=_json_default).encode("utf-8")
    envelope = _vault_encrypt(plaintext, password)
    # Audit log (no secrets!)
    try:
        await db.vault_audit.insert_one({
            "id": _uuid(),
            "action": "export",
            "created_at": _now(),
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "keys_count": len(bundle),
            "comment": (payload.get("comment") or "").strip()[:200],
        })
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "envelope": envelope,
        "filename": f"sawali-vault-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json",
        "keys_count": len(bundle),
    }


@api.post("/admin/secrets/import", tags=["Admin"])
async def admin_vault_import(
    file: UploadFile = File(...),
    password: str = Form(...),
    dry_run: str = Form("false"),
    overwrite_filled: str = Form("false"),
    user: dict = Depends(get_current_admin),
):
    """Restore a previously-exported vault.
    - dry_run=true : decrypt + return the list of keys that would be
      restored (without applying them).
    - dry_run=false : apply.
    - overwrite_filled=false : only restore keys that are EMPTY in the
      current settings doc (safe default — never clobber a freshly typed
      value with an older one).
    - overwrite_filled=true : restore every key from the bundle."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Fichier vide")
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Fichier non parsable: {exc}")
    is_dry = str(dry_run).lower() in ("1", "true", "yes", "on")
    overwrite = str(overwrite_filled).lower() in ("1", "true", "yes", "on")
    plaintext = _vault_decrypt(envelope, password)
    try:
        bundle_doc = json.loads(plaintext.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Contenu déchiffré invalide")
    if bundle_doc.get("kind") != "sawali-secrets-vault":
        raise HTTPException(status_code=400, detail="Ce fichier ne semble pas être un coffre-fort SAWALI")
    incoming = bundle_doc.get("settings") or {}
    current = await db.settings.find_one({"_id": "global"}) or {}

    plan: List[Dict[str, Any]] = []
    update: Dict[str, Any] = {}
    for k in VAULT_KEYS:
        if k not in incoming:
            continue
        new_v = incoming[k]
        if new_v is None or new_v == "":
            continue
        old_v = current.get(k)
        was_filled = bool(old_v) if not isinstance(old_v, bool) else True
        will_apply = (not was_filled) or overwrite
        plan.append({
            "key": k,
            "was_filled": was_filled,
            "will_apply": will_apply,
            "is_secret": k in SENSITIVE_SETTINGS_KEYS,
        })
        if will_apply and not is_dry:
            update[k] = new_v

    if not is_dry and update:
        update["updated_at"] = _now()
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)

    try:
        await db.vault_audit.insert_one({
            "id": _uuid(),
            "action": "import_dry" if is_dry else "import",
            "created_at": _now(),
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "incoming_count": len(incoming),
            "applied_count": len(update),
            "overwrite_filled": overwrite,
            "bundle_exported_at": bundle_doc.get("exported_at"),
            "bundle_exported_by": bundle_doc.get("exported_by"),
        })
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "dry_run": is_dry,
        "overwrite_filled": overwrite,
        "bundle_exported_at": bundle_doc.get("exported_at"),
        "bundle_exported_by": bundle_doc.get("exported_by"),
        "bundle_comment": bundle_doc.get("comment"),
        "incoming_count": len(incoming),
        "applied_count": len(update),
        "plan": plan,
    }


@api.get("/admin/secrets/audit", tags=["Admin"])
async def admin_vault_audit(_: dict = Depends(get_current_admin)):
    """Audit trail of every vault export/import action."""
    items = await db.vault_audit.find({}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return {"items": items, "count": len(items)}



# ============================================================
# iter30 — Per-user client-scope diagnostic & realignment.
#
# When two users belong to the same business client but see different sets of
# contacts, the root cause is almost always one of these:
#
#   1. Their `users.client_id` fields point to different values (mis-bridged)
#   2. Their contacts/messages were created under different `client_id` scopes
#   3. One user has no `parent_client_id` so iter28's auto-mirror didn't fire
#
# This endpoint accepts an email and returns:
#   • The user's full identity chain (id, role, parent_client_id, client_id,
#     tracked_user_id)
#   • The canonical client_id for that user (resolved via parent_client_id, or
#     by looking up another user with the same company name & admin role)
#   • A peer list (other users sharing the same canonical client_id)
#   • Per-user contact counts (each peer's visible scope)
#   • A realign plan: which fields/rows need to be retagged to put this user
#     in sync with the canonical scope
#
# Together with the POST sibling (`/admin/realign-user-to-client`) the admin
# can repair production without ad-hoc SQL.
# ============================================================
@api.get("/admin/client-data-diagnostic", tags=["Admin"])
async def admin_client_data_diagnostic(email: str, _: dict = Depends(get_current_admin)):
    email_norm = (email or "").strip().lower()
    if not email_norm:
        raise HTTPException(status_code=400, detail="Email requis")
    user = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(email_norm)}$", "$options": "i"}},
        {"_id": 0, "password_hash": 0},
    )
    if not user:
        raise HTTPException(status_code=404, detail=f"Utilisateur introuvable : {email_norm}")

    uid = user["id"]
    declared_client_id = user.get("client_id")
    parent_client_id = user.get("parent_client_id")
    company = (user.get("company") or "").strip()
    role = user.get("role")

    # Canonical client_id resolution priority:
    #   1) parent_client_id (set when this user was created via tracked-user bridge)
    #   2) For admin/superviseur users: their OWN id (they ARE the client root)
    #   3) Otherwise: look up another admin/superviseur with the same company name
    canonical: Optional[str] = None
    canonical_source = None
    canonical_user: Optional[dict] = None
    if parent_client_id:
        canonical = parent_client_id
        canonical_source = "parent_client_id"
    elif role in ("admin", "superviseur"):
        canonical = uid
        canonical_source = "self (admin/superviseur)"
    elif company:
        # Find an admin or superviseur with the same company; case-insensitive trim
        same_company = await db.users.find_one(
            {
                "company": {"$regex": f"^\\s*{re.escape(company)}\\s*$", "$options": "i"},
                "role": {"$in": ["admin", "superviseur"]},
            },
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1},
        )
        if same_company:
            canonical = same_company["id"]
            canonical_source = f"company match → {same_company.get('email')}"
            canonical_user = same_company
    # Hydrate the canonical user if we have an id but didn't already fetch it
    if canonical and not canonical_user:
        canonical_user = await db.users.find_one(
            {"id": canonical},
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1, "role": 1},
        )

    # Iter34m — Stale-parent detection.
    # When an admin edits a user's `company` text without updating
    # `parent_client_id`, the pointer keeps anchoring them to the old client
    # (e.g. rabo.f@sawalismartsystems.com had company="SAWALI SMART SYSTEMS"
    # typed but parent_client_id still pointed to "Clinique CMCO"). The
    # original diagnostic trusted parent_client_id and reported "Aucun
    # désalignement détecté". Now we cross-check the canonical's company
    # against the user's typed company; if they differ, we try to recompute
    # the canonical via the typed company, override it, and emit a new
    # `relink_parent` action so the realign endpoint can patch
    # `parent_client_id` in addition to retagging rows.
    parent_company_mismatch = False
    parent_company_observed: Optional[str] = None
    typed_company_norm = company.lower().strip()
    if (
        canonical_source == "parent_client_id"
        and typed_company_norm
        and canonical_user
    ):
        parent_company_observed = (canonical_user.get("company") or "").strip() or None
        canonical_company_norm = (parent_company_observed or "").lower().strip()
        if canonical_company_norm and typed_company_norm != canonical_company_norm:
            # The typed company and the parent's company disagree — find a
            # better canonical anchor from the typed company (admin first,
            # then any user marked as primary client for that company).
            better = await db.users.find_one(
                {
                    "company": {"$regex": f"^\\s*{re.escape(company)}\\s*$", "$options": "i"},
                    "role": {"$in": ["admin", "superviseur"]},
                },
                {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1, "role": 1},
            )
            if not better:
                better = await db.users.find_one(
                    {
                        "company": {"$regex": f"^\\s*{re.escape(company)}\\s*$", "$options": "i"},
                        "is_primary_client": True,
                    },
                    {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1, "role": 1},
                )
            if better and better["id"] != canonical:
                parent_company_mismatch = True
                canonical = better["id"]
                canonical_source = f"company match (parent_client_id obsolète) → {better.get('email')}"
                canonical_user = better
                # Recompute peers under the corrected canonical
                # (the next block already walks db.users with the new canonical)
            else:
                # Surface the mismatch even when we cannot auto-fix it.
                parent_company_mismatch = True

    effective_scope = declared_client_id or uid

    # Peers — users that the canonical client_id should encompass
    peers: List[dict] = []
    if canonical:
        async for p in db.users.find(
            {
                "$or": [
                    {"id": canonical},
                    {"client_id": canonical},
                    {"parent_client_id": canonical},
                ],
            },
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "client_id": 1, "parent_client_id": 1},
        ):
            # For each peer, count contacts they currently see (apply the
            # iter29 read rule: filter on their effective scope).
            peer_scope = p.get("client_id") or p["id"]
            peer_contacts = await db.directory_contacts.count_documents({"client_id": peer_scope})
            p["effective_scope"] = peer_scope
            p["scope_matches_canonical"] = (peer_scope == canonical)
            p["visible_contacts"] = peer_contacts
            peers.append(p)

    # Realign plan — what needs to change to put this user in sync
    realign_plan: Dict[str, Any] = {"needed": False, "actions": []}
    # Iter34m — first emit the relink_parent action when a stale parent
    # pointer was detected AND auto-resolved to a new canonical.
    if parent_company_mismatch and canonical and parent_client_id and parent_client_id != canonical:
        realign_plan["needed"] = True
        realign_plan["actions"].append({
            "type": "relink_parent",
            "user_id": uid,
            "from_parent": parent_client_id,
            "to_parent": canonical,
        })
    if canonical and canonical != effective_scope:
        realign_plan["needed"] = True
        # Action 1 — fix the user's own client_id field
        if declared_client_id != canonical:
            realign_plan["actions"].append({
                "type": "set_user_client_id",
                "from": declared_client_id,
                "to": canonical,
                "user_id": uid,
            })
        # Action 2 — count rows tagged under the wrong client_id that should be retagged.
        # Iter34o — CRITICAL: filter by owner_id/sender_id/etc. so we ONLY
        # move rows demonstrably owned by THIS user. Before this fix the
        # retag moved ALL rows at wrong_scope (e.g. all CMCO contacts when
        # realigning rabo.f), breaking the legitimate users of the source
        # client. The visible-scope bridge in _resolve_visible_client_ids
        # already handles cross-client visibility via company matching, so
        # we no longer need a wholesale retag.
        wrong_scope = effective_scope
        owner_filter: Dict[str, Any] = {"$or": [
            {"owner_id": uid},
            {"sender_id": uid},
            {"created_by": uid},
            {"author_id": uid},
            {"user_id": uid},
        ]}
        for coll in ["directory_contacts", "whatsapp_messages", "sms_messages",
                     "whatsapp_schedules", "payment_links"]:
            q: Dict[str, Any] = {"client_id": wrong_scope, **owner_filter}
            cnt = await db[coll].count_documents(q)
            if cnt > 0:
                realign_plan["actions"].append({
                    "type": "retag_rows",
                    "collection": coll,
                    "from": wrong_scope,
                    "to": canonical,
                    "count": cnt,
                    "owner_uid": uid,  # remembered so the apply step uses the same filter
                })

    return {
        "user": {
            "id": uid,
            "email": user.get("email"),
            "full_name": user.get("full_name"),
            "company": company,
            "role": role,
            "client_id": declared_client_id,
            "parent_client_id": parent_client_id,
            "tracked_user_id": user.get("tracked_user_id"),
            "effective_scope": effective_scope,
        },
        "canonical": {
            "client_id": canonical,
            "source": canonical_source,
            "user": canonical_user,
        },
        "parent_company_mismatch": parent_company_mismatch,
        "parent_company_observed": parent_company_observed,
        "peers": peers,
        "realign_plan": realign_plan,
    }


@api.post("/admin/realign-user-to-client", tags=["Admin"])
async def admin_realign_user_to_client(
    payload: Dict[str, Any] = Body(...),
    _: dict = Depends(get_current_admin),
):
    """Apply the realign_plan returned by /admin/client-data-diagnostic.

    Body: ``{"email": "user@example.com", "dry_run": false}``.
    The endpoint re-runs the diagnostic, then applies the proposed actions
    atomically per collection: stamps `client_id` to the canonical value and
    keeps the previous one in `client_id_legacy` (for traceability).
    Idempotent.
    """
    email = (payload.get("email") or "").strip().lower()
    dry_run = bool(payload.get("dry_run"))
    if not email:
        raise HTTPException(status_code=400, detail="Email requis")
    diag = await admin_client_data_diagnostic(email=email, _={"role": "admin"})
    plan = diag["realign_plan"]
    if not plan["needed"]:
        return {"ok": True, "applied": False, "reason": "Aucun désalignement détecté"}
    if dry_run:
        return {"ok": True, "applied": False, "diagnostic": diag, "dry_run": True}

    applied: List[Dict[str, Any]] = []
    for action in plan["actions"]:
        if action["type"] == "set_user_client_id":
            await db.users.update_one(
                {"id": action["user_id"]},
                {"$set": {"client_id": action["to"], "client_id_legacy": action.get("from"),
                          "updated_at": _now()}},
            )
            applied.append(action)
        elif action["type"] == "relink_parent":
            # Iter34m — Stale-parent fix. Update parent_client_id and mirror
            # client_id to the new canonical so subsequent queries scope
            # correctly. Preserve the old value in *_legacy fields.
            await db.users.update_one(
                {"id": action["user_id"]},
                {"$set": {
                    "parent_client_id": action["to_parent"],
                    "parent_client_id_legacy": action.get("from_parent"),
                    "client_id": action["to_parent"],
                    "updated_at": _now(),
                }},
            )
            applied.append(action)
        elif action["type"] == "retag_rows":
            # Iter34o — Use the same owner_uid filter to scope the retag.
            owner_uid = action.get("owner_uid")
            base_q: Dict[str, Any] = {"client_id": action["from"], "client_id_legacy": {"$exists": False}}
            if owner_uid:
                base_q["$or"] = [
                    {"owner_id": owner_uid},
                    {"sender_id": owner_uid},
                    {"created_by": owner_uid},
                    {"author_id": owner_uid},
                    {"user_id": owner_uid},
                ]
            res = await db[action["collection"]].update_many(
                base_q,
                {"$set": {"client_id": action["to"], "client_id_legacy": action["from"]}},
            )
            applied.append({**action, "modified_count": int(getattr(res, "modified_count", 0) or 0)})

    return {"ok": True, "applied": True, "actions": applied, "diagnostic_after": await admin_client_data_diagnostic(email=email, _={"role": "admin"})}


# ============================================================
# Iter34o — Recovery endpoint for the over-broad retag bug.
# ----------------------------------------------------------
# Before iter34o the retag step moved every row at `client_id == old_scope`
# regardless of ownership. When the admin realigned rabo.f@SAWALI the
# entire CMCO contact base ended up tagged SAWALI. The original values are
# safely preserved in `client_id_legacy` — this endpoint restores them.
# ============================================================
@api.post("/admin/contacts/revert-retag", tags=["Admin"])
async def admin_revert_retag(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    _: dict = Depends(get_current_admin),
):
    """Restore `client_id ← client_id_legacy` on every row where the legacy
    field is set across all retag-affected collections.

    Body (all optional):
      • ``dry_run`` (bool, default true) — preview the counts without writing.
      • ``collections`` (list[str]) — limit to a specific subset (e.g. only
        ``directory_contacts``). Default: all five.
      • ``from_client_id`` (str) — restrict to rows previously tagged with this
        ``client_id_legacy`` value (case: only revert one client's data).
      • ``to_client_id`` (str) — restrict to rows currently tagged with this
        ``client_id`` (case: only revert what was moved into this canonical).

    Idempotent: once a row is reverted, the legacy field is deleted so a
    second run is a no-op.
    """
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    requested = payload.get("collections")
    all_colls = ["directory_contacts", "whatsapp_messages", "sms_messages",
                 "whatsapp_schedules", "payment_links"]
    if requested:
        colls = [c for c in requested if c in all_colls]
        if not colls:
            raise HTTPException(status_code=400, detail=f"Aucune collection valide. Options: {all_colls}")
    else:
        colls = all_colls
    base_filter: Dict[str, Any] = {"client_id_legacy": {"$exists": True, "$nin": [None, ""]}}
    if payload.get("from_client_id"):
        base_filter["client_id_legacy"] = payload["from_client_id"]
    if payload.get("to_client_id"):
        base_filter["client_id"] = payload["to_client_id"]

    results: List[Dict[str, Any]] = []
    for coll in colls:
        cnt = await db[coll].count_documents(base_filter)
        action: Dict[str, Any] = {"collection": coll, "count": cnt}
        if not dry_run and cnt > 0:
            # Use the aggregation pipeline update form so we can use $unset
            # and copy a field value into another in a single pass.
            res = await db[coll].update_many(
                base_filter,
                [
                    {"$set": {"client_id": "$client_id_legacy"}},
                    {"$unset": "client_id_legacy"},
                ],
            )
            action["modified_count"] = int(getattr(res, "modified_count", 0) or 0)
        results.append(action)

    # Also revert users.parent_client_id_legacy + users.client_id_legacy when
    # present, so the user-pointer side of iter34m is also undone.
    user_filter: Dict[str, Any] = {"parent_client_id_legacy": {"$exists": True, "$nin": [None, ""]}}
    user_count = await db.users.count_documents(user_filter)
    user_action: Dict[str, Any] = {"collection": "users", "count": user_count}
    if not dry_run and user_count > 0:
        res = await db.users.update_many(
            user_filter,
            [
                {"$set": {"parent_client_id": "$parent_client_id_legacy"}},
                {"$unset": ["parent_client_id_legacy", "client_id_legacy"]},
            ],
        )
        user_action["modified_count"] = int(getattr(res, "modified_count", 0) or 0)
    results.append(user_action)

    return {
        "ok": True,
        "dry_run": dry_run,
        "filter": {k: str(v) if not isinstance(v, dict) else v for k, v in base_filter.items()},
        "results": results,
        "total_rows": sum(r["count"] for r in results),
    }


# ============================================================
# iter31 — Client-consistency canary
# ----------------------------------------------------------
# Scans every user grouped by their normalized `company` name and detects
# whether all members of a company share the same canonical client_id.
# A canonical client_id is determined as:
#   1) The id of an admin/superviseur in the group (if any), else
#   2) The most common non-null client_id in the group, else
#   3) None (signal: company has no canonical anchor — admin must intervene)
#
# This runs at boot time (logs WARNING summary if any group is misaligned)
# and is also exposed via the /admin/clients-consistency endpoint that the
# settings UI panoramic section consumes.
# ============================================================
async def _scan_clients_consistency() -> Dict[str, Any]:
    groups: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(
        {"company": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1,
         "company": 1, "client_id": 1, "parent_client_id": 1, "account_status": 1},
    ):
        # Skip disabled/deleted accounts so we don't flag old data
        if u.get("account_status") in ("disabled", "deleted", "blocked"):
            continue
        key = (u.get("company") or "").strip().lower()
        if not key:
            continue
        g = groups.setdefault(key, {"company": (u.get("company") or "").strip(), "members": []})
        g["members"].append(u)

    misaligned_groups: List[Dict[str, Any]] = []
    aligned_groups = 0
    total_misaligned_users = 0

    for key, g in groups.items():
        members = g["members"]
        if len(members) < 2:
            # Solo accounts cannot be inconsistent with peers
            aligned_groups += 1
            continue
        # Resolve canonical:
        admins = [m for m in members if m.get("role") in ("admin", "superviseur")]
        canonical: Optional[str] = None
        canonical_via = None
        if admins:
            canonical = admins[0]["id"]
            canonical_via = f"admin/superviseur ({admins[0].get('email')})"
        else:
            # Fallback: most common non-null client_id
            counts: Dict[str, int] = {}
            for m in members:
                cid = m.get("client_id")
                if cid:
                    counts[cid] = counts.get(cid, 0) + 1
            if counts:
                canonical = max(counts.items(), key=lambda x: x[1])[0]
                canonical_via = "most common client_id"

        # Compare each member's effective scope to the canonical
        misaligned: List[Dict[str, Any]] = []
        for m in members:
            scope = m.get("client_id") or m["id"]
            if canonical and scope != canonical:
                misaligned.append({
                    "id": m["id"],
                    "email": m.get("email"),
                    "full_name": m.get("full_name"),
                    "role": m.get("role"),
                    "client_id": m.get("client_id"),
                    "parent_client_id": m.get("parent_client_id"),
                    "effective_scope": scope,
                })
        if misaligned:
            misaligned_groups.append({
                "company": g["company"],
                "canonical_client_id": canonical,
                "canonical_via": canonical_via,
                "members_total": len(members),
                "misaligned_count": len(misaligned),
                "misaligned": misaligned,
            })
            total_misaligned_users += len(misaligned)
        else:
            aligned_groups += 1

    return {
        "scanned_groups": len(groups),
        "aligned_groups": aligned_groups,
        "misaligned_groups": len(misaligned_groups),
        "misaligned_users_total": total_misaligned_users,
        "groups": misaligned_groups,
    }


@api.get("/admin/clients-consistency", tags=["Admin"])
async def admin_clients_consistency(_: dict = Depends(get_current_admin)):
    """Panoramic view of every multi-user company and whether all its members
    share the same canonical client_id. Read-only; pair with
    /admin/realign-user-to-client to fix outliers."""
    return await _scan_clients_consistency()


# ============================================================
# iter32 — Auto-suggest canonical client when admin types a company name
# in the "create user" form. The frontend calls this endpoint on blur and
# offers to auto-link the new user to the existing canonical client.
# ============================================================
@api.get("/admin/resolve-company", tags=["Admin"])
async def admin_resolve_company(company: str, _: dict = Depends(get_current_admin)):
    """Resolve the canonical client for a given company name.

    Returns ``{found: bool, canonical_user, member_count}``. The frontend uses
    this to offer auto-link when creating a new user with a known company.
    Match is case-insensitive and trim-tolerant.
    """
    name = (company or "").strip()
    if not name:
        return {"found": False, "company_input": ""}
    pattern = f"^\\s*{re.escape(name)}\\s*$"
    members = await db.users.find(
        {
            "company": {"$regex": pattern, "$options": "i"},
            "account_status": {"$nin": ["disabled", "deleted", "blocked"]},
        },
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "company": 1},
    ).to_list(50)
    if not members:
        return {"found": False, "company_input": name}
    # Canonical = first admin/superviseur, else first member
    admins = [m for m in members if m.get("role") in ("admin", "superviseur")]
    canonical = admins[0] if admins else members[0]
    return {
        "found": True,
        "company_input": name,
        "canonical_user": {
            "id": canonical["id"],
            "email": canonical.get("email"),
            "full_name": canonical.get("full_name"),
            "role": canonical.get("role"),
            "company": canonical.get("company"),
        },
        "member_count": len(members),
    }


# ============================================================
# Campaign Efficiency dashboard — quantifies the WhatsApp-first
# strategy versus SMS:
#   • WA delivery rate (sent_ok / total)
#   • SMS delivery rate (sent_ok / total, all-time and as fallback only)
#   • Fallback rate (% of WA failures that triggered an SMS retry, and the
#     success rate of those retries)
#   • Estimated cost savings (each successful WA = one SMS not sent → save
#     `sms_unit_cost`). Helps justify the WA-first strategy to clients.
# Admin-only; aggregates across all clients (no per-client breakdown here —
# that already exists in /admin/usage/summary). Daily series capped at 30 days.
# ============================================================
@api.get("/admin/campaign-efficiency", tags=["Admin"])
async def admin_campaign_efficiency(days: int = 30, _: dict = Depends(get_current_admin)):
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()

    # Helper to extract a YYYY-MM-DD bucket from a string created_at field.
    day_expr = {"$substr": ["$created_at", 0, 10]}

    # 1) WA stats — outbound only (inbound is excluded from delivery rate).
    wa_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}, "direction": {"$ne": "inbound"}}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "sent_ok": {"$sum": {"$cond": [{"$or": [{"$eq": ["$ok", True]}, {"$eq": ["$wa_status", "sent"]}]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$ok", False]}, {"$eq": ["$wa_status", "failed"]}]}, 1, 0]}},
        }},
    ]
    wa_doc = await db.whatsapp_messages.aggregate(wa_pipeline).to_list(1)
    wa = (wa_doc[0] if wa_doc else {"total": 0, "sent_ok": 0, "sent_ko": 0})
    wa_delivery_rate = (wa["sent_ok"] / wa["total"] * 100.0) if wa["total"] else 0.0

    # 2) SMS stats — all SMS sent, and fallback-only subset.
    sms_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "sent_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "fallback_total": {"$sum": {"$cond": [{"$eq": ["$wa_fallback", True]}, 1, 0]}},
            "fallback_ok": {"$sum": {"$cond": [{"$and": [{"$eq": ["$wa_fallback", True]}, {"$eq": ["$status", "sent"]}]}, 1, 0]}},
        }},
    ]
    sms_doc = await db.sms_messages.aggregate(sms_pipeline).to_list(1)
    sms = (sms_doc[0] if sms_doc else {"total": 0, "sent_ok": 0, "sent_ko": 0, "fallback_total": 0, "fallback_ok": 0})
    sms_delivery_rate = (sms["sent_ok"] / sms["total"] * 100.0) if sms["total"] else 0.0
    fallback_success_rate = (sms["fallback_ok"] / sms["fallback_total"] * 100.0) if sms["fallback_total"] else 0.0
    # % of WA failures that triggered an SMS retry
    fallback_trigger_rate = (sms["fallback_total"] / wa["sent_ko"] * 100.0) if wa["sent_ko"] else 0.0

    # 3) Cost savings — average sms_unit_cost across configured clients.
    cost_pipeline = [
        {"$match": {"sms_unit_cost": {"$gt": 0}}},
        {"$group": {"_id": None, "avg": {"$avg": "$sms_unit_cost"}, "count": {"$sum": 1}}},
    ]
    cost_doc = await db.users.aggregate(cost_pipeline).to_list(1)
    sms_unit_cost_avg = float((cost_doc[0] if cost_doc else {}).get("avg") or 0.0)
    estimated_savings = round(wa["sent_ok"] * sms_unit_cost_avg, 2)

    # 4) Daily series — WA OK, WA KO, SMS OK, SMS KO, fallback OK per day.
    daily_wa = {}
    async for d in db.whatsapp_messages.aggregate([
        {"$match": {"created_at": {"$gte": since_iso}, "direction": {"$ne": "inbound"}}},
        {"$group": {
            "_id": day_expr,
            "wa_ok": {"$sum": {"$cond": [{"$or": [{"$eq": ["$ok", True]}, {"$eq": ["$wa_status", "sent"]}]}, 1, 0]}},
            "wa_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$ok", False]}, {"$eq": ["$wa_status", "failed"]}]}, 1, 0]}},
        }},
    ]):
        daily_wa[d["_id"]] = {"wa_ok": int(d.get("wa_ok") or 0), "wa_ko": int(d.get("wa_ko") or 0)}

    daily_sms = {}
    async for d in db.sms_messages.aggregate([
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": day_expr,
            "sms_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sms_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "fallback_ok": {"$sum": {"$cond": [{"$and": [{"$eq": ["$wa_fallback", True]}, {"$eq": ["$status", "sent"]}]}, 1, 0]}},
        }},
    ]):
        daily_sms[d["_id"]] = {
            "sms_ok": int(d.get("sms_ok") or 0),
            "sms_ko": int(d.get("sms_ko") or 0),
            "fallback_ok": int(d.get("fallback_ok") or 0),
        }

    daily = []
    end_day = datetime.now(timezone.utc).date()
    # Strict `days` consecutive buckets ending today (inclusive). Earlier we
    # used `since.date()` which could yield days+1 buckets across the UTC
    # midnight boundary — the testing agent flagged this; tighten it here.
    cur_day = end_day - timedelta(days=days - 1)
    while cur_day <= end_day:
        key = cur_day.isoformat()
        wa_row = daily_wa.get(key, {"wa_ok": 0, "wa_ko": 0})
        sms_row = daily_sms.get(key, {"sms_ok": 0, "sms_ko": 0, "fallback_ok": 0})
        daily.append({"day": key, **wa_row, **sms_row})
        cur_day += timedelta(days=1)

    return {
        "period_days": days,
        "wa": {
            "total": int(wa["total"]),
            "sent_ok": int(wa["sent_ok"]),
            "sent_ko": int(wa["sent_ko"]),
            "delivery_rate": round(wa_delivery_rate, 2),
        },
        "sms": {
            "total": int(sms["total"]),
            "sent_ok": int(sms["sent_ok"]),
            "sent_ko": int(sms["sent_ko"]),
            "delivery_rate": round(sms_delivery_rate, 2),
        },
        "fallback": {
            "triggered": int(sms["fallback_total"]),
            "succeeded": int(sms["fallback_ok"]),
            "success_rate": round(fallback_success_rate, 2),
            "trigger_rate_on_wa_failures": round(fallback_trigger_rate, 2),
        },
        "cost_savings": {
            "sms_unit_cost_avg": round(sms_unit_cost_avg, 4),
            "wa_success_count": int(wa["sent_ok"]),
            "estimated_savings_xof": estimated_savings,
        },
        "daily": daily,
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
    voice_note_url: Optional[str] = None  # Iter35g — note vocale facultative
    voice_note_transcript: Optional[str] = None  # Iter35g — transcription Whisper auto


class ClientTaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_at: Optional[str] = None  # ISO-8601 (date or datetime)
    remind_via_whatsapp: bool = False
    voice_note_url: Optional[str] = None  # Iter35g
    voice_note_transcript: Optional[str] = None  # Iter35g


class ClientTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[str] = None
    status: Optional[str] = None  # 'open' | 'done'
    remind_via_whatsapp: Optional[bool] = None
    voice_note_url: Optional[str] = None  # Iter35g
    voice_note_transcript: Optional[str] = None  # Iter35g


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
        "voice_note_url": payload.voice_note_url or None,  # Iter35g
        "voice_note_transcript": payload.voice_note_transcript or None,  # Iter35g
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
        "voice_note_url": payload.voice_note_url or None,  # Iter35g
        "voice_note_transcript": payload.voice_note_transcript or None,  # Iter35g
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
    # Iter35f — handle email updates safely (normalize + uniqueness check).
    # Prior to iter35f, the `email` field was missing from UserUpdateAdmin
    # so the admin UI silently dropped any change. Now we normalize to
    # lowercase + strip whitespace, then make sure no other account holds
    # the same email before writing.
    if "email" in update:
        new_email = (update["email"] or "").strip().lower()
        if not new_email or "@" not in new_email:
            raise HTTPException(status_code=400, detail="Adresse email invalide")
        update["email"] = new_email
        clash = await db.users.find_one(
            {"email": new_email, "id": {"$ne": client_id}},
            {"_id": 0, "id": 1, "email": 1},
        )
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"L'email {new_email} est déjà utilisé par un autre compte",
            )
    if payload.password:
        update["password_hash"] = hash_password(payload.password)
    update["updated_at"] = _now()

    # Iter34n — Auto-guard: when admin changes the `company` text, the user's
    # parent_client_id might still anchor to a stale company (the rabo.f
    # bug fixed in iter34m). Detect the mismatch BEFORE writing the update
    # and try to auto-realign so the UI stays internally consistent
    # without forcing the admin to run the diagnostic manually.
    auto_realign: Optional[Dict[str, Any]] = None
    if "company" in update:
        before = await db.users.find_one(
            {"id": client_id},
            {"_id": 0, "id": 1, "email": 1, "company": 1, "role": 1},
        )
        if before:
            new_company = (update.get("company") or "").strip()
            old_company = (before.get("company") or "").strip()
            company_changed = new_company.lower() != old_company.lower()
            if company_changed and new_company and before.get("role") not in ("admin",):
                # Apply the user update first, then trigger the same logic
                # the diagnostic uses. We reuse the existing endpoint as a
                # function call so behaviour stays in sync.
                await db.users.update_one({"id": client_id}, {"$set": update})
                try:
                    diag = await admin_client_data_diagnostic(
                        email=before.get("email") or "", _={"role": "admin"}
                    )
                    plan = diag.get("realign_plan") or {}
                    if plan.get("needed") and diag.get("parent_company_mismatch"):
                        # Auto-apply silently. Same rules as the manual
                        # /admin/realign-user-to-client endpoint.
                        for action in plan["actions"]:
                            if action["type"] == "relink_parent":
                                await db.users.update_one(
                                    {"id": action["user_id"]},
                                    {"$set": {
                                        "parent_client_id": action["to_parent"],
                                        "parent_client_id_legacy": action.get("from_parent"),
                                        "client_id": action["to_parent"],
                                        "updated_at": _now(),
                                    }},
                                )
                            elif action["type"] == "set_user_client_id":
                                await db.users.update_one(
                                    {"id": action["user_id"]},
                                    {"$set": {
                                        "client_id": action["to"],
                                        "client_id_legacy": action.get("from"),
                                        "updated_at": _now(),
                                    }},
                                )
                            elif action["type"] == "retag_rows":
                                # Iter34o — owner-scoped retag.
                                owner_uid = action.get("owner_uid")
                                base_q: Dict[str, Any] = {"client_id": action["from"], "client_id_legacy": {"$exists": False}}
                                if owner_uid:
                                    base_q["$or"] = [
                                        {"owner_id": owner_uid},
                                        {"sender_id": owner_uid},
                                        {"created_by": owner_uid},
                                        {"author_id": owner_uid},
                                        {"user_id": owner_uid},
                                    ]
                                await db[action["collection"]].update_many(
                                    base_q,
                                    {"$set": {"client_id": action["to"], "client_id_legacy": action["from"]}},
                                )
                        auto_realign = {
                            "applied": True,
                            "to_company": (diag.get("canonical") or {}).get("user", {}).get("company") if diag.get("canonical") else None,
                            "to_canonical_id": (diag.get("canonical") or {}).get("client_id"),
                            "actions_count": len(plan["actions"]),
                        }
                    elif diag.get("parent_company_mismatch"):
                        # Mismatch detected but no canonical resolvable
                        # (e.g. typo in company name, or no admin/primary
                        # carries that exact name). Surface it instead of
                        # silently leaving the user broken.
                        auto_realign = {
                            "applied": False,
                            "reason": "no_canonical_for_company",
                            "typed_company": new_company,
                        }
                except Exception:
                    pass
                return {"ok": True, "auto_realign": auto_realign}
    await db.users.update_one({"id": client_id}, {"$set": update})
    return {"ok": True, "auto_realign": auto_realign}


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
    # Iter35q — Mirror to Emergent Object Storage so the file survives prod redeploys.
    # We keep the local disk copy as a hot cache; the remote copy is the source of truth.
    storage_path = None
    storage_error = None
    try:
        from storage import upload_bytes, storage_available
        if storage_available():
            data = target.read_bytes()
            storage_path = upload_bytes(
                f"files/{safe_name}", data,
                file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream",
            )
    except Exception as exc:  # noqa: BLE001
        storage_error = str(exc)[:300]
        logger.warning("[admin_upload] storage mirror failed: %s", storage_error)
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
        # Iter35q — remote storage pointer for persistence across redeploys
        "storage_path": storage_path,
        "storage_error": storage_error,
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
# Iter35q — Storage diagnostics & backfill (admin only).
#   - GET /admin/files/orphans      → list files whose disk binary is missing
#                                     AND not yet mirrored to Emergent storage.
#   - POST /admin/files/backfill    → for every file row that has disk binary
#                                     but no storage_path, push it to remote.
#                                     Returns {mirrored, skipped, errors}.
# ====================================================================
@api.get("/admin/files/orphans", tags=["Admin"])
async def admin_files_orphans(_: dict = Depends(get_current_admin)):
    """List file rows that are unrecoverable (disk gone + no remote copy)."""
    orphans: List[Dict[str, Any]] = []
    cursor = db.files.find({}, {"_id": 0, "id": 1, "filename": 1, "stored_name": 1, "size": 1, "uploaded_at": 1, "uploaded_by_email": 1, "storage_path": 1})
    async for f in cursor:
        on_disk = (UPLOAD_DIR / (f.get("stored_name") or "")).exists() if f.get("stored_name") else False
        in_remote = bool(f.get("storage_path"))
        if not on_disk and not in_remote:
            orphans.append({
                "id": f["id"],
                "filename": f.get("filename"),
                "size": f.get("size"),
                "uploaded_at": f.get("uploaded_at"),
                "uploaded_by_email": f.get("uploaded_by_email"),
            })
    return {"count": len(orphans), "items": orphans}


@api.post("/admin/files/backfill", tags=["Admin"])
async def admin_files_backfill(_: dict = Depends(get_current_admin)):
    """For every file row that has its binary on disk but no `storage_path`,
    push it to Emergent storage and update the DB row. Best-effort."""
    from storage import upload_bytes, storage_available
    if not storage_available():
        raise HTTPException(status_code=503, detail="Stockage objet non disponible.")
    mirrored = 0
    skipped = 0
    errors: List[Dict[str, Any]] = []
    cursor = db.files.find({"storage_path": {"$in": [None, ""]}}, {"_id": 0, "id": 1, "stored_name": 1, "content_type": 1})
    async for f in cursor:
        try:
            target = UPLOAD_DIR / (f.get("stored_name") or "")
            if not target.exists():
                skipped += 1
                continue
            sp = upload_bytes(
                f"files/{f['stored_name']}", target.read_bytes(),
                f.get("content_type") or "application/octet-stream",
            )
            await db.files.update_one({"id": f["id"]}, {"$set": {"storage_path": sp}})
            mirrored += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": f["id"], "error": str(exc)[:200]})
    return {"mirrored": mirrored, "skipped_no_disk": skipped, "errors": errors}


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


@api.api_route("/public/policies/{slot}", methods=["GET", "HEAD"], tags=["Public"])
async def public_policy(slot: str, request: Request):
    """Serve a policy PDF inline so 3rd parties (Google, Facebook…) can verify it.
    Both GET (renders the PDF) and HEAD (existence check used by the public
    /politiques/{slug} page to decide whether to show the iframe) are supported."""
    if slot not in POLICY_SLOTS:
        raise HTTPException(status_code=404, detail="Politique introuvable")
    p = _policy_path(slot)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Politique non publiée")
    meta = await db.policies.find_one({"slot": slot}, {"_id": 0})
    download_name = (meta or {}).get("filename") or f"{slot}.pdf"
    if request.method == "HEAD":
        # Mirror the GET headers so HEAD probes can verify existence + size without
        # reading the bytes — required by the iframe gate on the public page.
        return Response(
            status_code=200,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(p.stat().st_size),
                "Content-Disposition": f'inline; filename="{download_name}"',
                "Cache-Control": "public, max-age=3600",
                "X-Robots-Tag": "all",
            },
        )
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
    # Iter35q — When the local file is missing (ephemeral container after a redeploy),
    # try to rehydrate from Emergent Object Storage. The DB stays the source of truth.
    if not path.exists():
        rehydrated = False
        storage_path = meta.get("storage_path") or f"files/{meta['stored_name']}"
        try:
            from storage import fetch_bytes, storage_available
            if storage_available():
                data, _ct = fetch_bytes(storage_path)
                if data:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    rehydrated = True
                    logger.info("[serve_file] rehydrated %s from storage (%d bytes)", file_id, len(data))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[serve_file] rehydrate failed for %s: %s", file_id, exc)
        if not rehydrated:
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
async def me_media_library(
    source: Optional[str] = None,  # Iter35n — filter by `source` (e.g. "whatsapp_inbound")
    user: dict = Depends(get_current_user),
):
    """All media items uploaded by users of the same client. Shared bank.

    Iter35n — `source` query filter narrows the listing (typically
    `?source=whatsapp_inbound` to isolate WhatsApp re-saved media).
    """
    client_scope = user.get("client_id") or user.get("id")
    q: Dict[str, Any] = {"client_id": client_scope}
    if source:
        q["source"] = source
    items = await db.media_library.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


@api.post("/me/media-library", tags=["Portail Client"])
async def me_media_library_create(
    request: Request,
    file: UploadFile = File(...),
    label: str = Form(""),
    target_client_id: str = Form(""),  # Admin-only: attach the upload to a specific client's library
    user: dict = Depends(get_current_user),
):
    """Upload + register a media in the shared client library, returns a stable public URL
    (with the file extension, accepted by Meta WhatsApp Cloud API as a header media)."""
    if not (_is_tracked_user(user) or _is_elevated_creator(user) or user.get("role") in ("client", "admin")):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    # Resolve client_id: admin can override via target_client_id, others always use their own
    client_scope = user.get("client_id") or user.get("id")
    if (target_client_id or "").strip() and user.get("role") == "admin":
        client_scope = target_client_id.strip()
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
        "client_id": client_scope,
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


# Iter35n — Cleanup unused WhatsApp media library entries. "Unused" means the
# underlying file_id is not referenced by any rapport/suivi/note image. Admin
# can dry-run first to preview what will be deleted.
@api.post("/me/media-library/wa-cleanup", tags=["Portail Client"])
async def me_media_library_wa_cleanup(
    dry_run: bool = Query(default=True),
    user: dict = Depends(get_current_user),
):
    """Delete WhatsApp-sourced media library entries whose underlying file is
    no longer referenced anywhere else. Admin/superviseur/admin-tracked only."""
    if not (user.get("role") in ("admin", "superviseur") or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Réservé aux rôles élevés")
    client_scope = user.get("client_id") or user.get("id")
    candidates = await db.media_library.find(
        {"client_id": client_scope, "source": "whatsapp_inbound"},
        {"_id": 0, "id": 1, "file_id": 1, "label": 1, "public_url": 1, "kind": 1, "created_at": 1},
    ).to_list(2000)
    if not candidates:
        return {"ok": True, "dry_run": dry_run, "examined": 0, "to_delete": [], "deleted": 0}

    file_ids = [c.get("file_id") for c in candidates if c.get("file_id")]

    # Collect every file_id referenced anywhere else in user content. We look
    # at notes/reports/suivis images arrays + interventions attachments.
    referenced: set[str] = set()
    for coll_name, field in (
        ("user_reports", "images"),
        ("user_suivis", "images"),
        ("user_notes_personal", "images"),
        ("user_tasks_personal", "images"),
        ("interventions", "attachments"),
    ):
        try:
            cursor = db[coll_name].find({field: {"$exists": True, "$ne": []}}, {"_id": 0, field: 1})
            async for d in cursor:
                for img in d.get(field) or []:
                    fid = (img or {}).get("file_id") or (img or {}).get("id")
                    if fid:
                        referenced.add(fid)
                    url = (img or {}).get("url") or ""
                    # /api/files/{file_id}.ext — extract the bare id
                    if "/api/files/" in url:
                        bare = url.split("/api/files/", 1)[1].split(".", 1)[0].split("?", 1)[0]
                        if bare:
                            referenced.add(bare)
        except Exception as exc:  # noqa: BLE001
            logger.warning("wa-cleanup ref scan failed for %s: %s", coll_name, exc)

    to_delete = [c for c in candidates if c.get("file_id") and c["file_id"] not in referenced]
    deleted = 0
    if not dry_run and to_delete:
        ids_to_remove = [c["id"] for c in to_delete]
        res = await db.media_library.delete_many({"id": {"$in": ids_to_remove}, "client_id": client_scope})
        deleted = res.deleted_count or 0
    return {
        "ok": True,
        "dry_run": dry_run,
        "examined": len(candidates),
        "to_delete": [{"id": c["id"], "label": c.get("label"), "kind": c.get("kind")} for c in to_delete],
        "deleted": deleted,
    }


# ============================================================
# Audio transcription — used by Reports/Suivis to dictate the body.
# Calls OpenAI Whisper (whisper-1 by default) using the API key
# stored in admin settings (configurable from /admin/settings).
# ============================================================
@api.post("/transcribe", tags=["Portail Client"])
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("fr"),
    user: dict = Depends(get_current_user),
):
    """Accepts a short audio file (webm/mp3/m4a/wav/ogg, ≤25 Mo) and returns
    the transcribed text using OpenAI Whisper."""
    await _enforce_demo_quota(user, QUOTA_KEY_TRANSCRIBE)  # Iter35h
    s = await db.settings.find_one({"_id": "global"}) or {}
    api_key = (s.get("openai_api_key") or "").strip()
    model = (s.get("openai_whisper_model") or "whisper-1").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Transcription audio non configurée. Demandez à l'admin d'ajouter une clé OpenAI dans /admin/settings.",
        )
    # Stream the upload into memory (capped) — Whisper limit is 25 Mo
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier audio trop volumineux (max 25 Mo)")
    if len(raw) < 200:
        raise HTTPException(status_code=400, detail="Audio vide")
    fname = file.filename or "audio.webm"
    mime = file.content_type or "audio/webm"
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            files = {"file": (fname, raw, mime)}
            data = {"model": model, "language": (language or "fr")[:5]}
            r = await http.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )
            if r.status_code >= 300:
                try:
                    err = r.json().get("error", {}).get("message") or r.text[:300]
                except Exception:
                    err = r.text[:300]
                raise HTTPException(status_code=502, detail=f"OpenAI Whisper a retourné HTTP {r.status_code} — {err}")
            payload = r.json()
            return {
                "ok": True,
                "text": (payload.get("text") or "").strip(),
                "model": model,
                "language": data["language"],
                "duration_bytes": len(raw),
            }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à OpenAI Whisper")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("[transcribe] unexpected exception: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)[:300])


# ============================================================
# AI Summary — used by the dashboard "Synthèse IA" button.
# Two providers are supported (toggle by admin in /admin/settings):
#   • "openai" → POST https://api.openai.com/v1/chat/completions
#   • "n8n"    → POST <n8n_webhook_url> (AgentAI-style webhook)
# Body: { messages: [{role,content,…}], context: str?, target?: str }
# Returns: { ok, provider, model?, summary }
# ============================================================
class AiSummaryRequest(BaseModel):
    messages: List[Dict[str, Any]]  # arbitrary objects (WA history rows or plain texts)
    context: Optional[str] = None  # extra prose hint, e.g. "Conversations avec ACME du 1er au 5 mai"
    target: Optional[str] = None   # e.g. client name, displayed in the prompt


def _format_messages_for_prompt(rows: List[Dict[str, Any]]) -> str:
    """Render a compact human-readable text from a heterogeneous list of WA rows."""
    lines = []
    for r in rows[:200]:  # safety cap
        if not isinstance(r, dict):
            lines.append(str(r)[:400])
            continue
        ts = r.get("created_at") or r.get("ts") or ""
        if ts and isinstance(ts, str):
            ts = ts.split("T")[0] + " " + ts.split("T")[1][:5] if "T" in ts else ts
        direction = r.get("direction") or ("outbound" if r.get("to") else "inbound")
        who = r.get("to") if direction == "outbound" else (r.get("from") or "—")
        body = (r.get("body") or r.get("text") or "").strip()
        if not body and r.get("template_name"):
            body = f"[Template {r['template_name']}]"
        if not body:
            continue
        lines.append(f"[{ts}] {direction.upper()} {who}: {body[:600]}")
    return "\n".join(lines) or "(aucun contenu)"


async def _persist_ai_summary(user: dict, provider: str, model: Optional[str], payload: AiSummaryRequest, summary: str) -> str:
    """Insert the generated summary into db.ai_summaries so it shows up in the
    history tab. Best-effort: any DB failure is logged but never bubbles up to
    the caller (the AI call already succeeded — losing the audit row mustn't
    break the user-facing response)."""
    try:
        doc = {
            "id": _uuid(),
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "user_label": user.get("full_name") or user.get("email"),
            "client_id": user.get("client_id") or user.get("id"),
            "provider": provider,
            "model": model,
            "context": (payload.context or "")[:500],
            "target": (payload.target or "")[:200],
            "messages_count": len(payload.messages or []),
            "summary": (summary or "")[:8000],
            "created_at": _now(),
        }
        await db.ai_summaries.insert_one(doc.copy())
        return doc["id"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ai-summary persist] failed: %s", exc)
        return ""


@api.post("/me/ai/summarize", tags=["Portail Client"])
async def me_ai_summarize(payload: AiSummaryRequest, user: dict = Depends(get_current_user)):
    await _enforce_demo_quota(user, QUOTA_KEY_AI)  # Iter35h
    s = await db.settings.find_one({"_id": "global"}) or {}
    provider = (s.get("ai_summary_provider") or "openai").lower()
    if provider not in ("openai", "n8n"):
        provider = "openai"
    formatted = _format_messages_for_prompt(payload.messages or [])
    sys_prompt = (
        "Tu es un assistant qui rédige des synthèses concises et professionnelles "
        "en français. Analyse précisément le CONTENU des messages WhatsApp ci-dessous "
        "(et non pas seulement les métadonnées) en 5 à 10 lignes maximum, en mettant "
        "en évidence : (1) les sujets/thèmes abordés, (2) les décisions et accords, "
        "(3) les demandes ou questions clients, (4) les blocages ou points sensibles, "
        "(5) les prochaines étapes attendues. Reste factuel ; cite si pertinent une "
        "phrase courte entre guillemets. Utilise des puces si cela aide à la lisibilité."
    )
    target_line = f"\nClient/cible : {payload.target}" if payload.target else ""
    context_line = f"\nContexte : {payload.context}" if payload.context else ""
    user_prompt = f"{target_line}{context_line}\n\nMessages :\n{formatted}".strip()

    # ---------- OpenAI ChatGPT branch ----------
    if provider == "openai":
        api_key = (s.get("openai_chat_api_key") or "").strip()
        model = (s.get("openai_chat_model") or "gpt-4o-mini").strip()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="ChatGPT non configuré. Demandez à l'admin d'ajouter une clé OpenAI ChatGPT dans /admin/settings.",
            )
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        try:
            async with httpx.AsyncClient(timeout=45) as http:
                r = await http.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                if r.status_code >= 300:
                    try:
                        err = r.json().get("error", {}).get("message") or r.text[:300]
                    except Exception:
                        err = r.text[:300]
                    raise HTTPException(status_code=502, detail=f"OpenAI a retourné HTTP {r.status_code} — {err}")
                data = r.json()
                summary = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                summary = summary.strip()
                await _persist_ai_summary(user, "openai", model, payload, summary)
                return {"ok": True, "provider": "openai", "model": model, "summary": summary}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à OpenAI ChatGPT")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ai-summary openai] unexpected: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)[:300])

    # ---------- n8n webhook branch ----------
    url = (s.get("n8n_webhook_url") or "").strip()
    if not url:
        raise HTTPException(
            status_code=503,
            detail="Webhook n8n non configuré. Renseignez l'URL dans /admin/settings.",
        )
    auth_type = (s.get("n8n_webhook_auth_type") or "none").lower()
    headers = {"Content-Type": "application/json"}
    auth = None
    if auth_type == "bearer":
        tok = (s.get("n8n_webhook_token") or "").strip()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
    elif auth_type == "basic":
        bu = (s.get("n8n_webhook_basic_user") or "").strip()
        bp = (s.get("n8n_webhook_basic_pass") or "").strip()
        if bu and bp:
            auth = (bu, bp)
    payload_n8n = {
        "type": "ai_summary",
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "company": user.get("company"),
            "client_id": user.get("client_id"),
        },
        "context": payload.context,
        "target": payload.target,
        "system_prompt": sys_prompt,
        "user_prompt": user_prompt,
        "messages": payload.messages,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.post(url, headers=headers, auth=auth, json=payload_n8n)
            if r.status_code >= 300:
                raise HTTPException(status_code=502, detail=f"n8n a retourné HTTP {r.status_code} — {r.text[:300]}")
            try:
                data = r.json()
            except Exception:
                data = {"summary": r.text}
            # n8n returns whatever the workflow defines — accept the most common shapes:
            summary = data.get("summary") or data.get("text") or data.get("output") or data.get("message") or ""
            if not summary and isinstance(data, list) and data:
                summary = data[0].get("summary") or data[0].get("text") or ""
            if not summary:
                summary = json.dumps(data)[:2000]
            summary = str(summary).strip()
            await _persist_ai_summary(user, "n8n", None, payload, summary)
            return {"ok": True, "provider": "n8n", "summary": summary}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel au webhook n8n")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ai-summary n8n] unexpected: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)[:300])


@api.get("/me/ai/summaries", tags=["Portail Client"])
async def me_list_ai_summaries(limit: int = 50, user: dict = Depends(get_current_user)):
    """List the calling user's saved AI summaries (admins see everything,
    sorted by created_at desc). Capped at 200 per request to keep UI snappy."""
    cap = min(max(limit, 1), 200)
    if user.get("role") == "admin":
        query = {}
    else:
        # Regular users see their own summaries — they shouldn't read other
        # users of the same client (privacy: a summary may contain free-text
        # context that the author considered private).
        query = {"user_id": user["id"]}
    items = await db.ai_summaries.find(query, {"_id": 0}).sort("created_at", -1).to_list(cap)
    return items


@api.delete("/me/ai/summaries/{sid}", tags=["Portail Client"])
async def me_delete_ai_summary(sid: str, user: dict = Depends(get_current_user)):
    existing = await db.ai_summaries.find_one({"id": sid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Synthèse introuvable")
    if user.get("role") != "admin" and existing.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Suppression non autorisée")
    await db.ai_summaries.delete_one({"id": sid})
    return {"ok": True}


class AiSummaryToReport(BaseModel):
    title: Optional[str] = None
    is_private: Optional[bool] = True  # default privé to err on the safe side
    client_id: Optional[str] = None  # if provided, creates a "suivi" instead of a "report"


@api.post("/me/ai/summaries/{sid}/to-report", tags=["Portail Client"])
async def me_summary_to_report(sid: str, payload: AiSummaryToReport, request: Request, user: dict = Depends(get_current_user)):
    """Convert a saved AI summary into a Report (or a Suivi if a client_id is
    provided alongside an event_date built from the summary date). The body of
    the report contains the rendered summary plus a tiny attribution footer."""
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Rôle insuffisant")
    s = await db.ai_summaries.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Synthèse introuvable")
    if user.get("role") != "admin" and s.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Conversion non autorisée")

    title = (payload.title or "").strip() or f"Synthèse IA — {s.get('target') or s.get('created_at', '')[:10]}"
    body = (s.get("summary") or "").strip()
    # Convert plain newlines into HTML paragraphs so the rich-text editor renders them well
    paragraphs = "".join(f"<p>{p.replace('<', '&lt;').replace('>', '&gt;')}</p>" for p in body.split("\n") if p.strip())
    footer = (
        f'<hr/><p style="font-size:11px;color:#64748b;">'
        f'Généré automatiquement le {s.get("created_at", "")[:16].replace("T", " ")} '
        f'via {s.get("provider", "—")}{" · " + s.get("model") if s.get("model") else ""}'
        f'{" · cible : " + s["target"] if s.get("target") else ""}'
        f"</p>"
    )
    content_html = paragraphs + footer

    is_suivi = bool(payload.client_id)
    kind = "suivis" if is_suivi else "reports"
    coll = _user_notes_collection(kind)
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
        "content_html": content_html,
        "tags": ["ia", s.get("provider") or "ia"],
        "client_id": payload.client_id if is_suivi else None,
        "event_date": s.get("created_at") if is_suivi else None,
        "images": [],
        "is_private": bool(payload.is_private),
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
        "updated_at": _now(),
        "source_summary_id": sid,
    }
    await coll.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "kind": kind, "report": doc}


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
    """Returns the running build's version + last-restart time.

    Iter34i: The minor version auto-bumps from the count of delivered
    roadmap actions stored in `db.roadmap_actions`. Manual major releases
    can be forced via the APP_VERSION env var (then we append the action
    count as a build number). Result format: `1.<N>` or `<APP_VERSION>.<N>`.
    """
    try:
        done_count = await db.roadmap_actions.count_documents({"done": True})
    except Exception:
        done_count = 0
    env_ver = (os.environ.get("APP_VERSION") or "").strip()
    if env_ver:
        version = f"{env_ver}.{done_count}"
    else:
        version = f"1.{done_count}"
    return {"version": version, "started_at": _BUILD_TIME_ISO, "actions_done": done_count}


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


# ============================================================
# Iter35g — Bulk transfer of tracked users to another client.
# Admin selects a list of tracked-user IDs and a target client_id; we
# update both `tracked_users.client_id` AND the bridged
# `users.parent_client_id` + `users.client_id` so the next login picks up
# the new scope. Returns a per-row summary so the UI can show which rows
# moved (and which were skipped because already there or unknown).
# ============================================================
class BulkTransferTrackedRequest(BaseModel):
    tracked_user_ids: List[str]
    target_client_id: str


@api.post("/admin/tracked-users/bulk-transfer", tags=["Admin"])
async def admin_bulk_transfer_tracked(
    payload: BulkTransferTrackedRequest,
    admin_user: dict = Depends(get_current_admin),
):
    if not payload.tracked_user_ids:
        raise HTTPException(status_code=400, detail="Aucun utilisateur sélectionné")
    if len(payload.tracked_user_ids) > 200:
        raise HTTPException(status_code=400, detail="Maximum 200 utilisateurs par transfert")
    target_id = (payload.target_client_id or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="Client cible requis")
    target = await db.users.find_one(
        {"id": target_id, "role": {"$in": ["client", "superviseur"]}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1},
    )
    if not target:
        raise HTTPException(status_code=404, detail="Client cible introuvable")

    moved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    now_iso = _now()
    for tu_id in payload.tracked_user_ids:
        tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
        if not tu:
            skipped.append({"id": tu_id, "reason": "introuvable"})
            continue
        old_client_id = tu.get("client_id")
        if old_client_id == target_id:
            skipped.append({"id": tu_id, "name": tu.get("name") or tu.get("email"), "reason": "déjà sur ce client"})
            continue
        # Update tracked_users row
        await db.tracked_users.update_one(
            {"id": tu_id},
            {"$set": {
                "client_id": target_id,
                "previous_client_id": old_client_id,
                "transferred_at": now_iso,
                "transferred_by_id": admin_user.get("id"),
                "transferred_by_label": admin_user.get("full_name") or admin_user.get("email"),
                "updated_at": now_iso,
            }},
        )
        # Update bridged users row if any (so login next time picks up the new scope)
        if tu.get("user_account_id"):
            await db.users.update_one(
                {"id": tu["user_account_id"]},
                {"$set": {
                    "client_id": target_id,
                    "parent_client_id": target_id,
                    "client_id_legacy": old_client_id,
                    "parent_client_id_legacy": old_client_id,
                    "updated_at": now_iso,
                }},
            )
        moved.append({
            "id": tu_id,
            "name": tu.get("name") or tu.get("email"),
            "from": old_client_id,
            "to": target_id,
        })
    # Audit log
    try:
        await db.tracked_user_transfers.insert_one({
            "id": _uuid(),
            "created_at": now_iso,
            "actor_id": admin_user.get("id"),
            "actor_email": admin_user.get("email"),
            "target_client_id": target_id,
            "target_company": target.get("company"),
            "moved_count": len(moved),
            "skipped_count": len(skipped),
            "moved": moved,
            "skipped": skipped,
        })
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "target": {"id": target_id, "company": target.get("company"), "email": target.get("email")},
        "moved": moved,
        "skipped": skipped,
        "moved_count": len(moved),
        "skipped_count": len(skipped),
    }


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
                # Mirror the parent client id on the legacy `client_id` field so
                # every endpoint that resolves scope via `user.client_id or
                # user.id` (50+ call sites) correctly inherits the parent's
                # feature flags + RGPD toggles + shared contacts.
                "client_id": tu.get("client_id"),
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
            # Mirror the parent client id (see comment above).
            "client_id": tu.get("client_id"),
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
    # Iter35g — extended with "notes" and "tasks" — personal notes & tasks
    # for portal users (same UI/model as reports/suivis, voice + transcription
    # inherited for free). Separate from the admin per-client `client_notes`
    # / `client_tasks` collections which stay unchanged.
    mapping = {
        "reports": db.user_reports,
        "suivis": db.user_suivis,
        "notes": db.user_notes_personal,
        "tasks": db.user_tasks_personal,
    }
    if kind not in mapping:
        raise HTTPException(status_code=404, detail="Type inconnu")
    return mapping[kind]


@api.get("/me/notes/{kind}", tags=["Portail Client"])
async def me_list_notes(
    kind: str,
    author: Optional[str] = None,
    q: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    # Privacy scoping: an elevated user sees ALL notes of their scope, BUT
    # private notes (is_private=True) authored by *other* users remain hidden
    # unless the caller is admin/superviseur (those two see everything).
    # Iter35m — Targeted visibility: a private note may also list explicit
    # target_user_ids. Any of those targets can see the note in addition to
    # the author and admin/superviseur.
    if user.get("role") in ("admin", "superviseur"):
        base: Dict[str, Any] = {}
    elif _is_elevated_creator(user):
        base = {
            "$or": [
                {"is_private": {"$ne": True}},
                {"owner_id": user["id"]},
                {"target_user_ids": user["id"]},
            ],
        }
    else:
        base = {
            "$or": [
                {"owner_id": user["id"]},
                {"target_user_ids": user["id"]},
            ]
        }
    query: Dict[str, Any] = dict(base)
    if author:
        query["owner_email"] = {"$regex": re.escape(author), "$options": "i"}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        # Combine with a possible $or already present in `base` by wrapping in $and
        text_or = [
            {"title": rx},
            {"content_html": rx},
            {"numero": rx},
            {"tags": rx},
        ]
        if "$or" in query:
            existing_or = query.pop("$or")
            query["$and"] = [{"$or": existing_or}, {"$or": text_or}]
        else:
            query["$or"] = text_or
    items = await coll.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    # Iter34u — Apply content-level restrictions (anon_rapports / anon_suivis)
    # when active. Privileged roles already bypass via the helper.
    restrictions = await _resolve_content_restrictions(user)
    restricted = (kind == "rapport" and restrictions.get("anon_rapports")) or \
                 (kind == "suivi" and restrictions.get("anon_suivis"))
    if restricted:
        items = [it for it in items if it.get("owner_id") == user["id"]]
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
    # Iter35g — prefix per kind
    prefix_map = {"reports": "RPT", "suivis": "SUI", "notes": "NTE", "tasks": "TSK"}
    prefix = prefix_map.get(kind, "DOC")
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
        "is_private": bool(payload.is_private),
        # Iter35m — Targeted visibility (only honored when is_private=True)
        "target_user_ids": list(payload.target_user_ids or []),
        # Iter35g — Voice note + Whisper transcription fields (already in the
        # UserNoteCreate model since iter34y/34z, just need to persist them).
        "voice_note_url": payload.voice_note_url or None,
        "voice_note_transcript": payload.voice_note_transcript or None,
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await coll.insert_one(doc.copy())
    doc.pop("_id", None)
    # Iter34x — activity feed (rapport / suivi / note / tâche)
    activity_kind_map = {"reports": "rapport", "suivis": "suivi", "notes": "note", "tasks": "tache"}
    activity_kind = activity_kind_map.get(kind, "note")
    user_client = user.get("parent_client_id") or user.get("client_id") or user["id"]
    await _log_activity(client_id=user_client, kind=activity_kind, action="created", label=title, actor=user, target_id=doc["id"])
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
    activity_kind = "rapport" if kind == "reports" else "suivi"
    user_client = user.get("parent_client_id") or user.get("client_id") or user["id"]
    await _log_activity(client_id=user_client, kind=activity_kind, action="updated", label=refreshed.get("title") or "(sans titre)", actor=user, target_id=note_id)
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
        activity_kind = "rapport" if kind == "reports" else "suivi"
        user_client = user.get("parent_client_id") or user.get("client_id") or user["id"]
        await _log_activity(client_id=user_client, kind=activity_kind, action="deleted", label=existing.get("title") or "(sans titre)", actor=user, target_id=note_id)
        webhook_result = await _fire_notes_webhook("deleted", kind, existing, user)
        return {"ok": True, "webhook_result": webhook_result}
    return {"ok": True}


@api.get("/me/notes-targets", tags=["Portail Client"])
async def me_notes_targets(user: dict = Depends(get_current_user)):
    """Iter35m — Return the list of users that a note/task can be addressed to
    when `is_private=True`. The list always starts with "Moi-même" (the caller),
    followed by every other user that shares the same effective client_id —
    i.e. the linked client + every tracked user / admin / superviseur attached
    to that client. Used to populate the targeting dropdown in the UI.

    Schema returned: { items: [{ id, full_name, email, role, is_self }] }
    """
    me = {
        "id": user["id"],
        "full_name": user.get("full_name") or user.get("email") or "Moi-même",
        "email": user.get("email"),
        "role": user.get("role") or user.get("tracked_role"),
        "is_self": True,
    }
    out: List[Dict[str, Any]] = [me]
    seen: set = {user["id"]}

    # Effective client scope: prefer parent_client_id (typed link), then client_id, then own id
    effective_client_id = user.get("parent_client_id") or user.get("client_id") or user["id"]

    # 1) Other admin/superviseur/client users attached to the same client_id (or parent)
    try:
        cursor = db.users.find(
            {
                "$or": [
                    {"id": effective_client_id},
                    {"client_id": effective_client_id},
                    {"parent_client_id": effective_client_id},
                ],
                "id": {"$ne": user["id"]},
            },
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1},
        )
        async for u in cursor:
            uid = u.get("id")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            out.append({
                "id": uid,
                "full_name": u.get("full_name") or u.get("email") or "—",
                "email": u.get("email"),
                "role": u.get("role"),
                "is_self": False,
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("notes-targets users lookup failed: %s", exc)

    # 2) Tracked users (employees) attached to the same client
    try:
        cursor = db.tracked_users.find(
            {"client_id": effective_client_id},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1},
        )
        async for tu in cursor:
            tid = tu.get("id")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append({
                "id": tid,
                "full_name": tu.get("full_name") or tu.get("email") or "—",
                "email": tu.get("email"),
                "role": tu.get("role") or "tracked",
                "is_self": False,
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("notes-targets tracked_users lookup failed: %s", exc)

    return {"items": out, "count": len(out), "effective_client_id": effective_client_id}


@api.get("/me/notes-summary", tags=["Portail Client"])
async def me_notes_summary(user: dict = Depends(get_current_user)):
    """Returns counts and last update timestamps to display dashboard buttons.
    Elevated users see global counts (all notes); others see only their own.

    Iter35g — extended with "notes" and "tasks" kinds (personal user notes/tasks,
    same model as reports/suivis with voice + transcription baked in).
    """
    base = {} if _is_elevated_creator(user) else {"owner_id": user["id"]}
    rep_count = await db.user_reports.count_documents(base)
    sui_count = await db.user_suivis.count_documents(base)
    notes_count = await db.user_notes_personal.count_documents(base)
    tasks_count = await db.user_tasks_personal.count_documents(base)
    rep_last = await db.user_reports.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    sui_last = await db.user_suivis.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    notes_last = await db.user_notes_personal.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    tasks_last = await db.user_tasks_personal.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    return {
        "reports": {"count": rep_count, "last_updated": (rep_last or {}).get("updated_at")},
        "suivis": {"count": sui_count, "last_updated": (sui_last or {}).get("updated_at")},
        "notes": {"count": notes_count, "last_updated": (notes_last or {}).get("updated_at")},
        "tasks": {"count": tasks_count, "last_updated": (tasks_last or {}).get("updated_at")},
    }


@api.get("/me/demo/status", tags=["Portail Client"])
async def me_demo_status(user: dict = Depends(get_current_user)):
    """Iter35h — Frontend uses this endpoint to render the persistent
    demo-account banner (countdown + quota gauges). Returns 200 with
    `is_demo: false` for every non-demo account so the front can call it
    unconditionally without 4xx handling."""
    if not _is_demo(user):
        return {"is_demo": False}
    from models import DEMO_DEFAULT_QUOTAS
    overrides = user.get("demo_quotas") or {}
    usage = user.get("demo_usage") or {}
    keys = list(set(list(DEMO_DEFAULT_QUOTAS.keys()) + list(overrides.keys())))
    quotas = {}
    for k in keys:
        limit = int(overrides.get(k, DEMO_DEFAULT_QUOTAS.get(k, 0)) or 0)
        if k == QUOTA_KEY_CONTACTS:
            used = await db.directory_contacts.count_documents({"client_id": user["id"]})
        else:
            used = int(usage.get(k, 0))
        quotas[k] = {"used": used, "limit": limit, "percent": min(100, int((used / limit) * 100)) if limit else 0}
    expires_at = user.get("demo_expires_at")
    days_left = None
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            delta = exp_dt - datetime.now(timezone.utc)
            days_left = max(0, int(delta.total_seconds() // 86400)) if delta.total_seconds() > 0 else 0
        except Exception:
            pass
    return {
        "is_demo": True,
        "expires_at": expires_at,
        "days_left": days_left,
        "quotas": quotas,
    }


@api.get("/admin/demo/expiry-events", tags=["Admin"])
async def admin_list_demo_expiry_events(
    only_unresolved: bool = Query(default=True),
    _: dict = Depends(get_current_admin),
):
    """Demo accounts that have expired — admin reviews and decides:
    keep disabled, extend the expiry, or delete entirely."""
    q = {}
    if only_unresolved:
        q = {"resolved": {"$ne": True}}
    items = await db.demo_expiry_events.find(q, {"_id": 0}).sort("detected_at", -1).limit(200).to_list(200)
    return {"items": items, "count": len(items)}


@api.post("/admin/demo/expiry-events/{ev_id}/resolve", tags=["Admin"])
async def admin_resolve_demo_expiry(ev_id: str, _: dict = Depends(get_current_admin)):
    res = await db.demo_expiry_events.update_one(
        {"id": ev_id, "resolved": {"$ne": True}},
        {"$set": {"resolved": True, "resolved_at": _now()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Événement introuvable")
    return {"ok": True}




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
    # Iter34y — activity feed (intervention)
    await _log_activity(client_id=payload.client_id, kind="intervention", action="created", label=doc.get("title") or doc.get("intervention_number") or "(intervention)", actor=user, target_id=doc["id"])
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
    existing = await db.interventions.find_one({"id": int_id}, {"_id": 0})
    res = await db.interventions.delete_one({"id": int_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    # Iter34y — activity feed
    if existing:
        await _log_activity(client_id=existing.get("client_id"), kind="intervention", action="deleted", label=existing.get("title") or existing.get("intervention_number") or "(intervention)", actor=user, target_id=int_id)
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
    if not _can_consult_all_docs(user) and not _is_demo(user):
        raise HTTPException(status_code=403, detail="Téléversement réservé aux rôles Modération / Administrateur / Superviseur")
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    target = UPLOAD_DIR / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    size = target.stat().st_size
    # Iter35h — demo storage cap (post-write check, rollback if exceeded).
    if _is_demo(user):
        try:
            await _enforce_demo_quota(user, QUOTA_KEY_STORAGE, increment=size)
        except HTTPException:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
            raise
    ext_suffix = (suffix.lstrip(".") or "").lower()
    public_path = f"/api/files/{file_id}{('.' + ext_suffix) if ext_suffix else ''}"
    # Iter35q — Mirror to Emergent Object Storage (best-effort)
    storage_path = None
    storage_error = None
    try:
        from storage import upload_bytes, storage_available
        if storage_available():
            storage_path = upload_bytes(
                f"files/{safe_name}", target.read_bytes(),
                file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream",
            )
    except Exception as exc:  # noqa: BLE001
        storage_error = str(exc)[:300]
        logger.warning("[me_upload] storage mirror failed: %s", storage_error)
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
        "storage_path": storage_path,
        "storage_error": storage_error,
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
RATEABLE_KINDS = ("reports", "suivis", "interventions", "formations", "notes", "tasks")


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
        # Iter35r — Notes & Tasks personnelles
        "notes": db.user_notes_personal,
        "tasks": db.user_tasks_personal,
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
    "user_module_visits", "forms", "form_submissions", "directory_contacts", "whatsapp_messages", "whatsapp_schedules", "automations", "client_notes", "client_tasks", "policies", "ai_summaries", "payments",
    "subscription_plans", "subscription_categories", "subscription_orders", "wa_pending_imports",
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
    for k in ("smtp_password", "google_client_secret", "recaptcha_secret_key", "google_calendar_password_hint", "tracking_auth_header", "webhook_token", "webhook_basic_pass", "notes_webhook_token", "notes_webhook_basic_pass", "health_webhook_token", "health_webhook_basic_pass", "wa_access_token", "wa_verify_token", "openai_api_key", "openai_chat_api_key", "n8n_webhook_token", "n8n_webhook_basic_pass",
                "sms_orange_token", "sms_orange_basic_pass", "sms_orange_header_value", "sms_orange_client_secret",
                "sms_moov_token", "sms_moov_basic_pass", "sms_moov_header_value", "sms_moov_client_secret",
                "sms_telecel_token", "sms_telecel_basic_pass", "sms_telecel_header_value", "sms_telecel_client_secret",
                "sms_ovh_application_secret", "sms_ovh_consumer_key",
                "pawapay_api_token", "pawapay_api_token_sandbox", "pawapay_api_token_production", "pawapay_callback_secret",
                "agenda_n8n_outbound_token", "agenda_n8n_outbound_basic_pass", "agenda_n8n_inbound_secret"):
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
        "openai_api_key", "openai_chat_api_key",
        "n8n_webhook_token", "n8n_webhook_basic_pass",
        "sms_orange_token", "sms_orange_basic_pass", "sms_orange_header_value", "sms_orange_client_secret",
        "sms_moov_token", "sms_moov_basic_pass", "sms_moov_header_value", "sms_moov_client_secret",
        "sms_telecel_token", "sms_telecel_basic_pass", "sms_telecel_header_value", "sms_telecel_client_secret",
        "sms_ovh_application_secret", "sms_ovh_consumer_key",
        "pawapay_api_token", "pawapay_api_token_sandbox", "pawapay_api_token_production", "pawapay_callback_secret",
        "agenda_n8n_outbound_token", "agenda_n8n_outbound_basic_pass", "agenda_n8n_inbound_secret",
        "support_load_webhook_secret", "liluvine_remote_secret",
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
    # Iter35u — Hot-reload the public_base_url cache so subsequent background
    # jobs (cron emails, webhooks, scheduled WA sends) use the new value.
    if "public_base_url" in update:
        await _refresh_public_base_url_cache()
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
    # Iter34aa — Module Paiements (était envoyé par le sidebar mais absent du dict
    # → /me/notifications/mark-seen retournait 400 "Module inconnu : payments")
    "payments": ("payment_links", "created_at", "client_id"),
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


async def _resolve_visible_client_ids(user: dict) -> List[str]:
    """Iter34 — Resolve ALL client_ids whose contacts/messages this user
    legitimately sees. Bridges historical client_id misalignments by including:
      • the user's canonical client_id and parent_client_id
      • their own id (legacy contacts created when the row was self-owned)
      • every other admin/parent user sharing the SAME `company` (case-insensitive)

    This guarantees that two users typed with the same employer name see each
    other's directory even if their client_id pointers were never re-aligned.
    """
    ids: set[str] = set()
    for k in ("client_id", "parent_client_id", "id"):
        v = user.get(k)
        if v:
            ids.add(v)
    company = (user.get("company") or "").strip()
    if company:
        try:
            cursor = db.users.find(
                {"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}},
                {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1},
            )
            async for u in cursor:
                for k in ("id", "client_id", "parent_client_id"):
                    v = u.get(k)
                    if v:
                        ids.add(v)
        except Exception:
            pass
    return list(ids) if ids else [user.get("id")]


# ============================================================
# Iter34x — Real-time activity feed (polling-based).
# Every CUD on Contact, Rapport, Suivi, SMS, WhatsApp is logged into
# `activity_events` with `{client_id, kind, action, label, actor, ts}`.
# Connected clients poll /me/recent-activity every 8 seconds to learn
# what happened since their `since` cursor; the frontend then shows a
# Sonner toast (suppressing actions performed by the polling user itself).
# ============================================================
async def _log_activity(*, client_id: str, kind: str, action: str, label: str, actor: dict, target_id: Optional[str] = None):
    """Best-effort write of a single activity event. Never raises."""
    try:
        await db.activity_events.insert_one({
            "id": _uuid(),
            "client_id": client_id,
            "kind": kind,         # contact | rapport | suivi | sms | whatsapp
            "action": action,     # created | updated | deleted | received | sent
            "label": (label or "")[:160],
            "target_id": target_id,
            "actor_id": actor.get("id"),
            "actor_label": actor.get("full_name") or actor.get("email") or "—",
            "ts": _now(),
        })
    except Exception:
        pass


@api.get("/me/recent-activity", tags=["Portail Client"])
async def me_recent_activity(
    since: Optional[str] = None,
    limit: int = 20,
    user: dict = Depends(get_current_user),
):
    """Return new activity events for the user's visible scope since the
    `since` ISO timestamp. The frontend uses this to display floating
    toasts in near real-time. Events triggered by the requester are
    returned so the client can decide to suppress them locally."""
    visible_scope = await _resolve_visible_client_ids(user)
    q: Dict[str, Any] = {"client_id": {"$in": visible_scope}}
    if since:
        try:
            # The `ts` field on activity_events is an ISO string (from _now()),
            # so the comparison is string-based.
            q["ts"] = {"$gt": since}
        except Exception:
            pass
    items = await db.activity_events.find(q, {"_id": 0}).sort("ts", -1).to_list(min(max(limit, 1), 100))
    items.reverse()  # chronological order for toast stacking
    return {
        "events": items,
        "server_now": _now(),
        "viewer_id": user.get("id"),
    }


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
    # Special: WhatsApp inbound unread (not based on last_visited_at — uses read_by_us_at).
    try:
        wa_q: Dict[str, Any] = {"direction": "inbound", "read_by_us_at": None}
        if not is_admin:
            wa_q["client_id"] = client_scope
        counts["contacts_unread"] = await db.whatsapp_messages.count_documents(wa_q)
    except Exception:
        counts["contacts_unread"] = 0
    # Iter34l — Admin-only: pending profile-update requests (status-driven, not visit-driven)
    try:
        if is_admin:
            counts["admin_profile_requests"] = await db.profile_update_requests.count_documents({"status": "pending"})
        else:
            counts["admin_profile_requests"] = 0
    except Exception:
        counts["admin_profile_requests"] = 0
    return {"counts": counts, "generated_at": _now()}


class MarkSeenRequest(BaseModel):
    module: str


# ====================================================================
# PHASE 3 — WhatsApp Business API (Meta / Facebook Business Portfolio)
# Sends approved TEMPLATE messages via Meta Graph API /v{version}/{phone-number-id}/messages
# Credentials configured globally by super-admin in /admin/settings.
# ====================================================================
WA_GRAPH_VERSION = "v21.0"  # Meta Graph API version (update as Meta ships new)


def _normalize_wa_phone(raw: Optional[str]) -> str:
    """Sanitize a WhatsApp/phone number into the format Meta Cloud API expects:
    digits-only with country code, no leading +.
    Strips all non-digit characters (spaces, parens, dots, dashes, plus).
    Returns "" when nothing usable was provided so callers can short-circuit cleanly."""
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits


async def _wa_send_template(to_e164: str, template_name: str, language_code: str = "fr", components: Optional[list] = None) -> dict:
    """Send a WhatsApp template message. Returns {ok, status, message_id, error, raw}."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    phone_number_id = s.get("wa_phone_number_id")
    if not access_token or not phone_number_id:
        return {"ok": False, "error": "WhatsApp non configuré (token ou phone_number_id manquant)", "status": None, "message_id": None, "raw": None}
    # Sanitize the destination — Meta rejects spaces, parens, dots, etc. and
    # Cloud API forbids the leading +. Numbers shorter than 6 digits cannot be valid.
    to_clean = _normalize_wa_phone(to_e164)
    if len(to_clean) < 6:
        return {
            "ok": False, "status": None, "message_id": None,
            "error": f"Numéro invalide « {to_e164} » — il doit contenir un indicatif pays (ex: 225XXXXXXXX)",
            "raw": None,
        }
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{phone_number_id}/messages"
    body = {
        "messaging_product": "whatsapp",
        "to": to_clean,
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
    photo_url: Optional[str] = None  # Manually uploaded avatar (à la WhatsApp profile picture)


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    shared: Optional[bool] = None
    photo_url: Optional[str] = None


@api.get("/me/contacts/export.csv", tags=["Portail Client"])
async def me_export_contacts_csv(user: dict = Depends(get_current_user)):
    """Iter34w — Export the directory as CSV (Excel-compatible, UTF-8 BOM)."""
    client_ids = await _resolve_visible_client_ids(user)
    items = await db.directory_contacts.find({"client_id": {"$in": client_ids}}, {"_id": 0}).sort("name", 1).to_list(5000)
    flags = await _resolve_anon_flags(user)
    if any(flags.values()):
        items = [_apply_anon_to_contact(c, flags) for c in items]
    import csv, io
    buf = io.StringIO()
    buf.write("\ufeff")  # Excel UTF-8 BOM
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Code unique", "Nom", "Société", "Téléphone", "WhatsApp", "Email", "Tags", "Partagé", "Créé le"])
    for c in items:
        writer.writerow([
            c.get("unique_code") or "",
            c.get("name") or "",
            c.get("company") or "",
            c.get("phone") or "",
            c.get("whatsapp") or "",
            c.get("email") or "",
            ", ".join(c.get("tags") or []),
            "Oui" if c.get("shared") else "Non",
            (c.get("created_at") or ""),
        ])
    body = buf.getvalue().encode("utf-8")
    fname = f"contacts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
    return Response(content=body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api.get("/me/contacts/export.json", tags=["Portail Client"])
async def me_export_contacts_json(user: dict = Depends(get_current_user)):
    client_ids = await _resolve_visible_client_ids(user)
    items = await db.directory_contacts.find({"client_id": {"$in": client_ids}}, {"_id": 0}).sort("name", 1).to_list(5000)
    flags = await _resolve_anon_flags(user)
    if any(flags.values()):
        items = [_apply_anon_to_contact(c, flags) for c in items]
    body = json.dumps({"generated_at": _now(), "count": len(items), "contacts": items}, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    fname = f"contacts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    return Response(content=body, media_type="application/json; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api.get("/me/contacts/export.pdf", tags=["Portail Client"])
async def me_export_contacts_pdf(user: dict = Depends(get_current_user)):
    """Iter34w — Generate a PDF listing of the visible directory (ReportLab)."""
    client_ids = await _resolve_visible_client_ids(user)
    items = await db.directory_contacts.find({"client_id": {"$in": client_ids}}, {"_id": 0}).sort("name", 1).to_list(5000)
    flags = await _resolve_anon_flags(user)
    if any(flags.values()):
        items = [_apply_anon_to_contact(c, flags) for c in items]
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    import io
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=24, bottomMargin=24, leftMargin=24, rightMargin=24, title="Liste des contacts")
    styles = getSampleStyleSheet()
    now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M')
    story = [
        Paragraph("<b>SAWALI Smart Systems — Liste des contacts</b>", styles["Title"]),
        Paragraph(f"Généré le {now_str} — {len(items)} contact(s) — Utilisateur : {user.get('email') or user.get('id')}", styles["Normal"]),
        Spacer(1, 10),
    ]
    head = ["#", "Code", "Nom", "Société", "Téléphone", "WhatsApp", "Email"]
    data: List[List[str]] = [head]
    for i, c in enumerate(items, start=1):
        data.append([
            str(i),
            c.get("unique_code") or "",
            (c.get("name") or "")[:48],
            (c.get("company") or "")[:32],
            c.get("phone") or "",
            c.get("whatsapp") or "",
            (c.get("email") or "")[:42],
        ])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E90FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    doc.build(story)
    body = buf.getvalue()
    fname = f"contacts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.pdf"
    return Response(content=body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api.get("/me/contacts", tags=["Portail Client"])
async def me_list_contacts(user: dict = Depends(get_current_user)):
    """List ALL contacts of the user's client scope.

    Sharing model (iter29 onward, refined iter34): every contact created by
    ANY user of a client is visible to every other user of the same client
    (mirrors the shared-bank model already used by the Media Library). The
    legacy `shared` boolean is preserved on existing rows for traceability but
    no longer gates visibility. Iter34 widens the scope by also including any
    other client_id belonging to a peer user with the SAME company name —
    this bridges historical client_id misalignments without forcing a manual
    realign. RGPD: per-client anonymization flags still apply for non-
    privileged roles, regardless of who owns the contact.
    """
    client_ids = await _resolve_visible_client_ids(user)
    items = await db.directory_contacts.find(
        {"client_id": {"$in": client_ids}}, {"_id": 0},
    ).sort("name", 1).to_list(2000)
    flags = await _resolve_anon_flags(user)
    if any(flags.values()):
        items = [_apply_anon_to_contact(c, flags) for c in items]
    return items


@api.post("/me/contacts", tags=["Portail Client"])
async def me_create_contact(payload: ContactCreate, user: dict = Depends(get_current_user)):
    # Iter35h — demo: enforce contact-count cap (uses live row count).
    await _enforce_demo_quota(user, QUOTA_KEY_CONTACTS, increment=1)
    # Enforce admin-configured "tag mandatory" policy: at least one tag is
    # required when settings.contacts_require_tag is True. Helps keep the
    # directory searchable / categorized.
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("contacts_require_tag") and not (payload.tags and any((t or "").strip() for t in payload.tags)):
        raise HTTPException(status_code=400, detail="Au moins un tag est requis (politique d'administration)")
    client_scope = (user.get("client_id") or user.get("id"))
    # Generate the inalterable unique business code (YYYY-CLIENTCODE-NNNN).
    # We pull the parent client doc to derive the prefix; fall back to a slug
    # if the parent has no `client_code` set.
    client_doc = await db.users.find_one(
        {"id": client_scope},
        {"_id": 0, "id": 1, "client_code": 1, "company": 1, "full_name": 1},
    ) or {"id": client_scope}
    unique_code = await _next_contact_unique_code(client_doc)
    payload_data = payload.model_dump()
    # Iter29 collaborative model: every contact is shared across the client's
    # users by design. The `shared` flag is forced True so any legacy code path
    # that still inspects it (filters, exports, integrations) keeps working
    # correctly without an explicit override.
    payload_data["shared"] = True
    doc = {
        "id": _uuid(),
        "client_id": client_scope,
        "owner_id": user["id"],
        "owner_label": user.get("full_name") or user.get("email"),
        **payload_data,
        "unique_code": unique_code,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.directory_contacts.insert_one(doc.copy())
    doc.pop("_id", None)
    # Iter34x — activity feed for live toasts
    await _log_activity(client_id=doc["client_id"], kind="contact", action="created", label=doc.get("name") or "(sans nom)", actor=user, target_id=doc["id"])
    return doc


def _is_anon_masked_value(value: Any) -> bool:
    """Iter35f — Detect if a string was produced by our RGPD anonymizers
    (`_anon_name` → `J***`, `_anon_email` → `j***@gmail.com`, `_anon_phone`
    → `+22 ** ** ** 89`). Used by update endpoints to AVOID saving the
    masked sentinel back into the DB and clobbering the real value when
    the user leaves a RGPD-masked field untouched.

    Heuristic: any string containing TWO OR MORE consecutive asterisks is
    considered a mask. Real customer data should never legitimately contain
    `**` (phone masks use `**`, name/email masks use `***`).
    """
    return isinstance(value, str) and "**" in value


@api.put("/me/contacts/{cid}", tags=["Portail Client"])
async def me_update_contact(cid: str, payload: ContactUpdate, user: dict = Depends(get_current_user)):
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    # Iter29 collaborative model: any user within the same client_scope can edit
    # any contact (matches the visibility rule). Iter34 widens scope to include
    # peer users sharing the same company name. Privileged roles can edit
    # cross-client too. Legacy admin override is still respected.
    client_ids = await _resolve_visible_client_ids(user)
    if existing.get("client_id") not in client_ids and user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Modification non autorisée")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Iter35f — RGPD: a frontend that displays anonymized values may resend
    # them back on save (the user didn't touch the field). Detect the
    # `***` sentinel and DROP that key so we never overwrite the real
    # value with its mask. Applies to name, company, email, phone, whatsapp.
    masked_skipped: List[str] = []
    for k in ("name", "company", "email", "phone", "whatsapp"):
        if k in update and _is_anon_masked_value(update[k]):
            update.pop(k)
            masked_skipped.append(k)
    # Same policy on update: if tags is explicitly cleared while the policy is on, reject
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("contacts_require_tag") and "tags" in update:
        new_tags = update.get("tags") or []
        if not any((t or "").strip() for t in new_tags):
            raise HTTPException(status_code=400, detail="Au moins un tag est requis (politique d'administration)")
    update["updated_at"] = _now()
    # Track the last-editor for auditability when the editor isn't the owner
    if existing.get("owner_id") != user["id"]:
        update["last_edited_by_id"] = user["id"]
        update["last_edited_by_label"] = user.get("full_name") or user.get("email")
        update["last_edited_at"] = _now()
    await db.directory_contacts.update_one({"id": cid}, {"$set": update})
    await _log_activity(client_id=existing.get("client_id"), kind="contact", action="updated", label=existing.get("name") or "(sans nom)", actor=user, target_id=cid)
    return {"ok": True, "masked_skipped": masked_skipped}


@api.delete("/me/contacts/{cid}", tags=["Portail Client"])
async def me_delete_contact(cid: str, user: dict = Depends(get_current_user)):
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        return {"ok": True}  # already gone, idempotent
    # Iter29 collaborative model: any user within the same client_scope can
    # delete any contact (matches the visibility/edit rules). Iter34 widens to
    # peers sharing the same company name.
    client_ids = await _resolve_visible_client_ids(user)
    if existing.get("client_id") not in client_ids and user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Suppression non autorisée")
    await db.directory_contacts.delete_one({"id": cid})
    await _log_activity(client_id=existing.get("client_id"), kind="contact", action="deleted", label=existing.get("name") or "(sans nom)", actor=user, target_id=cid)
    return {"ok": True}


@api.post("/me/contacts/{cid}/photo", tags=["Portail Client"])
async def me_upload_contact_photo(cid: str, request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Upload a profile picture for a contact (à la WhatsApp avatar). Stored in
    /api/files/ and the contact's `photo_url` field is set to the public URL.
    Owner or admin only. Max 5 MiB. PNG/JPEG/WEBP only."""
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    if existing.get("owner_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Modification non autorisée")
    ctype = (file.content_type or "").lower()
    if ctype not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(status_code=400, detail="Format invalide — PNG/JPEG/WEBP uniquement")
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower() or ".png"
    safe_name = f"{file_id}{suffix}"
    target = UPLOAD_DIR / safe_name
    size = 0
    with target.open("wb") as f:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 5 * 1024 * 1024:
                f.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Photo trop lourde (max 5 Mo)")
            f.write(chunk)
    ext_suffix = suffix.lstrip(".")
    public_path = f"/api/files/{file_id}.{ext_suffix}" if ext_suffix else f"/api/files/{file_id}"
    await db.files.insert_one({
        "id": file_id, "filename": file.filename, "stored_name": safe_name,
        "extension": ext_suffix or None, "content_type": ctype, "size": size,
        "url": public_path, "uploaded_at": _now(), "uploaded_by_id": user.get("id"),
    })
    await db.directory_contacts.update_one(
        {"id": cid},
        {"$set": {"photo_url": public_path, "photo_updated_at": _now()}},
    )
    return {"ok": True, "photo_url": public_path}


@api.delete("/me/contacts/{cid}/photo", tags=["Portail Client"])
async def me_delete_contact_photo(cid: str, user: dict = Depends(get_current_user)):
    """Remove a contact's profile picture (sets photo_url to null)."""
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    if existing.get("owner_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Modification non autorisée")
    await db.directory_contacts.update_one(
        {"id": cid},
        {"$set": {"photo_url": None, "photo_updated_at": _now()}},
    )
    return {"ok": True}


# ---------- WhatsApp profile sync (manual button + auto on first inbound) ----------
# IMPORTANT: Meta Cloud API does NOT expose third-party profile pictures or
# `about` fields — privacy by design. The only field we can reliably retrieve
# is `profile.name` from the `contacts[]` array of inbound webhooks. The
# button below therefore reads the most recent inbound for the contact's
# phone and pulls the latest `from_profile_name` we logged. It does NOT make
# a real-time API call to Meta (no such endpoint exists).
@api.post("/me/contacts/{cid}/wa-sync", tags=["Portail Client"])
async def me_contact_wa_sync(cid: str, user: dict = Depends(get_current_user)):
    """Read the latest WhatsApp profile name we observed for this contact's
    phone in inbound messages and store it on the contact. Returns the
    suggested name so the UI can prompt the user before overwriting."""
    contact = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    if contact.get("owner_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Modification non autorisée")

    digits = []
    for raw in (contact.get("whatsapp") or "", contact.get("phone") or ""):
        d = "".join(ch for ch in (raw or "") if ch.isdigit())
        if d:
            digits.append(d)
    if not digits:
        raise HTTPException(status_code=400, detail="Aucun numéro de téléphone configuré sur ce contact")

    msg = await db.whatsapp_messages.find_one(
        {
            "direction": "inbound",
            "phone_digits": {"$in": digits},
            "from_profile_name": {"$nin": [None, ""]},
        },
        {"_id": 0, "from_profile_name": 1, "received_at": 1, "created_at": 1},
        sort=[("created_at", -1)],
    )
    if not msg:
        return {
            "ok": False,
            "reason": "no_inbound",
            "message": "Aucun message reçu de ce contact pour le moment. La synchronisation s'effectuera automatiquement dès qu'il vous écrira sur WhatsApp.",
        }

    suggested = (msg.get("from_profile_name") or "").strip()
    if not suggested:
        return {"ok": False, "reason": "no_profile_name", "message": "Le contact n'a pas de nom de profil WhatsApp public."}

    await db.directory_contacts.update_one(
        {"id": cid},
        {"$set": {"wa_profile_name": suggested, "wa_profile_synced_at": _now()}},
    )
    return {
        "ok": True,
        "suggested_name": suggested,
        "current_name": contact.get("name"),
        "observed_at": msg.get("received_at") or msg.get("created_at"),
        "note": "Meta Cloud API n'expose pas la photo de profil. Téléversez-la manuellement.",
    }


@api.get("/me/wa-pending-imports", tags=["Portail Client"])
async def me_list_wa_pending_imports(user: dict = Depends(get_current_user)):
    """List unknown phone numbers that have written to our WhatsApp Business
    line but aren't yet in the directory. Sorted by last_seen_at desc."""
    client_scope = (user.get("client_id") or user.get("id"))
    q = {} if user.get("role") == "admin" else {"client_id": client_scope}
    items = await db.wa_pending_imports.find(q, {"_id": 0}).sort("last_seen_at", -1).to_list(50)
    return items


class WaPendingImportRequest(BaseModel):
    name: Optional[str] = None  # If empty, fallback to wa_profile_name
    company: Optional[str] = None
    email: Optional[str] = None


@api.post("/me/wa-pending-imports/{pending_id}/import", tags=["Portail Client"])
async def me_import_wa_pending(pending_id: str, payload: WaPendingImportRequest, user: dict = Depends(get_current_user)):
    """Promote a pending WA inbound to a full directory contact. Optionally
    overrides the suggested name."""
    pending = await db.wa_pending_imports.find_one({"id": pending_id}, {"_id": 0})
    if not pending:
        raise HTTPException(status_code=404, detail="Inconnu")
    client_scope = (user.get("client_id") or user.get("id"))
    if user.get("role") != "admin" and pending.get("client_id") != client_scope:
        raise HTTPException(status_code=403, detail="Hors de votre périmètre")
    name = (payload.name or pending.get("wa_profile_name") or pending.get("from") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nom requis")
    new_id = _uuid()
    contact = {
        "id": new_id,
        "client_id": client_scope,
        "owner_id": user["id"],
        "name": name,
        "phone": pending.get("from") or "",
        "whatsapp": pending.get("from") or "",
        "email": (payload.email or "").strip(),
        "company": (payload.company or "").strip(),
        "notes": f"Importé depuis WhatsApp ({pending.get('messages_count', 0)} message(s) reçu(s))",
        "tags": ["wa-import"],
        "shared": False,
        "photo_url": None,
        "wa_profile_name": pending.get("wa_profile_name"),
        "wa_profile_synced_at": _now(),
        "created_at": _now(),
    }
    await db.directory_contacts.insert_one(contact.copy())
    # Re-link past inbound messages to the new contact
    digits = pending.get("phone_digits") or ""
    if digits:
        await db.whatsapp_messages.update_many(
            {"client_id": client_scope, "direction": "inbound", "phone_digits": digits, "contact_id": None},
            {"$set": {"contact_id": new_id, "contact_name": name}},
        )
    await db.wa_pending_imports.delete_one({"id": pending_id})
    contact.pop("_id", None)
    return {"ok": True, "contact": contact}


@api.delete("/me/wa-pending-imports/{pending_id}", tags=["Portail Client"])
async def me_dismiss_wa_pending(pending_id: str, user: dict = Depends(get_current_user)):
    """Permanently dismiss a pending WA inbound (won't reappear unless they
    write to us again)."""
    pending = await db.wa_pending_imports.find_one({"id": pending_id}, {"_id": 0})
    if not pending:
        raise HTTPException(status_code=404, detail="Inconnu")
    client_scope = (user.get("client_id") or user.get("id"))
    if user.get("role") != "admin" and pending.get("client_id") != client_scope:
        raise HTTPException(status_code=403, detail="Hors de votre périmètre")
    await db.wa_pending_imports.delete_one({"id": pending_id})
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
    # Iter34h — RGPD: resolve real WhatsApp number from contact_id if available,
    # to bypass any frontend-side anonymization mask.
    to = await _resolve_real_phone(payload.contact_id, "whatsapp", payload.to or "")
    if not to:
        raise HTTPException(status_code=400, detail="Numéro destinataire requis")
    result = await _wa_send_template(to, payload.template_name, payload.language_code or "fr", payload.components)
    # Extract any /pay/{slug} URL embedded in the template variables for channel attribution
    pay_slug = None
    try:
        blob = json.dumps(payload.components or [], ensure_ascii=False)
        pay_slug = _extract_pay_slug(blob)
    except Exception:  # noqa: BLE001
        pass
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
        "payment_link_slug": pay_slug,
        "created_at": _now(),
    }
    try: await db.whatsapp_messages.insert_one(log.copy())
    except Exception: pass
    if log.get("status") in ("sent", "queued") and log.get("client_id"):
        await _log_activity(client_id=log["client_id"], kind="whatsapp", action="sent", label=f"→ {contact_doc.get('name') or to_number}", actor=user, target_id=log.get("id"))
    log.pop("_id", None)
    return {"ok": result["ok"], "message_id": result["message_id"], "error": result.get("error"), "http_status": result["status"]}


@api.get("/me/whatsapp/history", tags=["Portail Client"])
async def me_whatsapp_history(limit: int = 100, user: dict = Depends(get_current_user)):
    client_scope = (user.get("client_id") or user.get("id"))
    query = {"client_id": client_scope} if user.get("role") != "admin" else {}
    items = await db.whatsapp_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    return items


# ---------- Free-form text within Meta 24h customer service window ----------
WA_24H_WINDOW_SECONDS = 24 * 3600


async def _wa_send_text(to_e164: str, text: str) -> dict:
    """Send a free-form WhatsApp text message (Cloud API type=text).
    ONLY allowed inside the 24h customer service window (after the user wrote first).
    Caller is responsible for verifying the window before invocation.
    Returns the same shape as `_wa_send_template`."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    phone_number_id = s.get("wa_phone_number_id")
    if not access_token or not phone_number_id:
        return {"ok": False, "error": "WhatsApp non configuré (token ou phone_number_id manquant)", "status": None, "message_id": None, "raw": None}
    to_clean = _normalize_wa_phone(to_e164)
    if len(to_clean) < 6:
        return {"ok": False, "status": None, "message_id": None,
                "error": f"Numéro invalide « {to_e164} » — il doit contenir un indicatif pays", "raw": None}
    body = {
        "messaging_product": "whatsapp",
        "to": to_clean,
        "type": "text",
        "text": {"body": text or "", "preview_url": True},
    }
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=12) as http:
            r = await http.post(url, json=body, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:2000]}
            if r.status_code < 300:
                mid = None
                if isinstance(raw, dict) and raw.get("messages"):
                    mid = raw["messages"][0].get("id")
                return {"ok": True, "status": r.status_code, "message_id": mid, "error": None, "raw": raw}
            err_msg = None
            err_code = None
            if isinstance(raw, dict):
                err_obj = raw.get("error") or {}
                err_msg = err_obj.get("message") or str(raw)[:500]
                err_code = err_obj.get("code")
                details = (err_obj.get("error_data") or {}).get("details")
                if details:
                    err_msg = f"{err_msg} — {details}"
            return {"ok": False, "status": r.status_code, "message_id": None,
                    "error": err_msg or f"HTTP {r.status_code}", "error_code": err_code, "raw": raw}
    except httpx.TimeoutException:
        return {"ok": False, "status": None, "message_id": None, "error": "Timeout", "raw": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "message_id": None, "error": str(exc)[:500], "raw": None}


# =====================================================================
# Iter35l — WhatsApp media (inbound download + outbound send + watermark)
# =====================================================================
WA_MEDIA_MAX_BYTES = 64 * 1024 * 1024  # Meta's hard cap is 100MB for video/document, 16MB for image. We pick a safe 64MB.
WA_MEDIA_KIND_BY_MIME = {
    "image/jpeg": "image", "image/jpg": "image", "image/png": "image", "image/webp": "image",
    "audio/aac": "audio", "audio/mp4": "audio", "audio/mpeg": "audio", "audio/amr": "audio",
    "audio/ogg": "audio", "audio/opus": "audio", "audio/webm": "audio",
    "video/mp4": "video", "video/3gpp": "video",
    "application/pdf": "document",
}

_EXT_BY_MIME = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "audio/aac": ".aac", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
    "audio/amr": ".amr", "audio/ogg": ".ogg", "audio/opus": ".opus", "audio/webm": ".webm",
    "video/mp4": ".mp4", "video/3gpp": ".3gp",
    "application/pdf": ".pdf",
}


def _wa_kind_for_mime(mime: str) -> str:
    """Map a MIME type to one of (image|audio|video|document)."""
    base = (mime or "").split(";", 1)[0].strip().lower()
    if base in WA_MEDIA_KIND_BY_MIME:
        return WA_MEDIA_KIND_BY_MIME[base]
    if base.startswith("image/"):
        return "image"
    if base.startswith("audio/"):
        return "audio"
    if base.startswith("video/"):
        return "video"
    return "document"


async def _wa_download_inbound_media(media_id: str) -> dict:
    """Download a Meta WhatsApp inbound media binary using its media_id.

    1) GET https://graph.facebook.com/{version}/{media_id} → returns metadata
       containing a short-lived `url` and `mime_type`.
    2) GET that url with the same Bearer token → returns the raw binary.

    The binary is persisted under UPLOAD_DIR with a stable filename based on
    the file_id, mirrored into db.files so /api/files/{id}.ext can serve it,
    and the public URL is returned alongside MIME / size metadata.

    Returns: {ok, file_id?, public_url?, mime_type?, size_bytes?, filename?, error?}
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    if not access_token:
        return {"ok": False, "error": "WhatsApp non configuré (token manquant)"}
    if not media_id:
        return {"ok": False, "error": "media_id manquant"}
    meta_url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{media_id}"
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(meta_url, headers={"Authorization": f"Bearer {access_token}"})
            if r.status_code >= 300:
                return {"ok": False, "error": f"HTTP {r.status_code} sur Graph media metadata"}
            meta = r.json() or {}
            bin_url = meta.get("url")
            mime = (meta.get("mime_type") or "application/octet-stream").split(";", 1)[0].strip()
            declared_size = int(meta.get("file_size") or 0)
            if not bin_url:
                return {"ok": False, "error": "URL binaire manquante dans la réponse Meta"}
            if declared_size and declared_size > WA_MEDIA_MAX_BYTES:
                return {"ok": False, "error": f"Média trop volumineux ({declared_size} octets)"}
            # Download the binary (still authenticated)
            r2 = await http.get(bin_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=60)
            if r2.status_code >= 300:
                return {"ok": False, "error": f"HTTP {r2.status_code} lors du téléchargement"}
            raw = r2.content
            if len(raw) > WA_MEDIA_MAX_BYTES:
                return {"ok": False, "error": "Média trop volumineux"}
            ext = _EXT_BY_MIME.get(mime) or mimetypes.guess_extension(mime) or ".bin"
            file_id = _uuid()
            stored_name = f"{file_id}{ext}"
            target = UPLOAD_DIR / stored_name
            try:
                target.write_bytes(raw)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"Écriture disque échouée: {exc!r}"}
            display_name = f"wa-inbound{ext}"
            file_doc = {
                "id": file_id,
                "filename": display_name,
                "stored_name": stored_name,
                "extension": ext.lstrip(".") if ext else None,
                "content_type": mime,
                "size": len(raw),
                "url": f"/api/files/{file_id}{ext}",
                "uploaded_at": _now(),
                "uploaded_by_id": "_wa_webhook_",
                "uploaded_by_email": "whatsapp-webhook",
                "uploaded_from_ip": None,
                "wa_media_id": media_id,
            }
            try:
                await db.files.insert_one(file_doc.copy())
            except Exception:
                pass
            return {
                "ok": True,
                "file_id": file_id,
                "stored_name": stored_name,
                "public_url": f"/api/files/{file_id}{ext}",
                "mime_type": mime,
                "size_bytes": len(raw),
                "filename": display_name,
                "kind": _wa_kind_for_mime(mime),
            }
    except httpx.TimeoutException:
        return {"ok": False, "error": "Timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def _wa_apply_image_watermark_qr(
    src_path: Path,
    *,
    watermark_text: Optional[str],
    qr_payload: Optional[str],
) -> Path:
    """Burn a discrete watermark (bottom-right) + optional QR code on the source
    image and write the result to a new file alongside the original. Returns the
    new Path. If both inputs are falsy or processing fails, returns the original.
    """
    if not (watermark_text or qr_payload):
        return src_path
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return src_path
    try:
        img = Image.open(src_path).convert("RGBA")
    except Exception:
        return src_path
    W, H = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # ----- Watermark text (bottom-right, semi-transparent white on dark pill) -----
    if (watermark_text or "").strip():
        text = watermark_text.strip()[:120]
        # Pick a font scale ~ 2.2% of the image height (min 14, max 36)
        font_size = max(14, min(36, int(H * 0.022)))
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = font_size * len(text) // 2, font_size
        pad = max(6, font_size // 3)
        x = W - tw - pad * 2 - 12
        y = H - th - pad * 2 - 12
        # Dark pill background
        draw.rounded_rectangle((x, y, x + tw + pad * 2, y + th + pad * 2), radius=pad, fill=(0, 0, 0, 140))
        draw.text((x + pad, y + pad - 2), text, font=font, fill=(255, 255, 255, 235))
    # ----- QR code (top-left, ~10% of width, slight white border) -----
    if (qr_payload or "").strip():
        try:
            import qrcode  # local import — heavy
            qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=1)
            qr.add_data(qr_payload.strip())
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
            qr_size = max(72, min(220, int(W * 0.12)))
            qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
            qx, qy = 16, 16
            # White rounded backdrop for contrast
            draw.rounded_rectangle((qx - 6, qy - 6, qx + qr_size + 6, qy + qr_size + 6), radius=8, fill=(255, 255, 255, 235))
            overlay.alpha_composite(qr_img, (qx, qy))
        except Exception:
            pass
    out = Image.alpha_composite(img, overlay).convert("RGB")
    dst = src_path.with_name(src_path.stem + "_wm.jpg")
    try:
        out.save(dst, format="JPEG", quality=88, optimize=True)
    except Exception:
        return src_path
    return dst


async def _wa_send_media(
    to_e164: str,
    kind: str,
    *,
    public_url: str,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
) -> dict:
    """Send a free-form WhatsApp media message (image/document/audio/video).
    ONLY allowed inside the 24h customer service window. Caller is responsible
    for verifying the window before invocation."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    access_token = s.get("wa_access_token")
    phone_number_id = s.get("wa_phone_number_id")
    if not access_token or not phone_number_id:
        return {"ok": False, "error": "WhatsApp non configuré", "status": None, "message_id": None, "raw": None}
    to_clean = _normalize_wa_phone(to_e164)
    if len(to_clean) < 6:
        return {"ok": False, "status": None, "message_id": None,
                "error": f"Numéro invalide « {to_e164} »", "raw": None}
    if kind not in ("image", "document", "audio", "video"):
        return {"ok": False, "status": None, "message_id": None, "error": f"Type média non géré: {kind}", "raw": None}
    media_obj: Dict[str, Any] = {"link": public_url}
    if caption and kind in ("image", "document", "video"):
        media_obj["caption"] = caption[:1024]
    if kind == "document" and filename:
        media_obj["filename"] = filename
    body = {
        "messaging_product": "whatsapp",
        "to": to_clean,
        "type": kind,
        kind: media_obj,
    }
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(url, json=body, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:2000]}
            if r.status_code < 300:
                mid = None
                if isinstance(raw, dict) and raw.get("messages"):
                    mid = raw["messages"][0].get("id")
                return {"ok": True, "status": r.status_code, "message_id": mid, "error": None, "raw": raw}
            err_msg = None
            err_code = None
            if isinstance(raw, dict):
                err_obj = raw.get("error") or {}
                err_msg = err_obj.get("message") or str(raw)[:500]
                err_code = err_obj.get("code")
            return {"ok": False, "status": r.status_code, "message_id": None,
                    "error": err_msg or f"HTTP {r.status_code}", "error_code": err_code, "raw": raw}
    except httpx.TimeoutException:
        return {"ok": False, "status": None, "message_id": None, "error": "Timeout", "raw": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "message_id": None, "error": str(exc)[:500], "raw": None}


async def _wa_transcribe_audio_file(path: Path, language: str = "fr") -> Optional[str]:
    """Best-effort Whisper transcription of a saved audio file. Returns None on failure.
    Used by the WhatsApp inbound webhook when `wa_voice_transcribe_enabled` is on."""
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        api_key = (s.get("openai_api_key") or "").strip()
        model = (s.get("openai_whisper_model") or "whisper-1").strip()
        if not api_key:
            return None
        if not path.exists() or path.stat().st_size < 200:
            return None
        if path.stat().st_size > 25 * 1024 * 1024:
            return None
        raw = path.read_bytes()
        async with httpx.AsyncClient(timeout=60) as http:
            files = {"file": (path.name, raw, mimetypes.guess_type(path.name)[0] or "audio/ogg")}
            data = {"model": model, "language": (language or "fr")[:5]}
            r = await http.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )
            if r.status_code >= 300:
                return None
            payload = r.json()
            return (payload.get("text") or "").strip() or None
    except Exception:
        return None


# =====================================================================
# Iter35n — WhatsApp reply-time tracker.
# When a user sends an outbound text/media to a contact, we look up the most
# recent unanswered inbound from that contact (in the visible scope) and
# compute the elapsed seconds. The result is stamped on the outbound
# message document (`reply_to_inbound_id`, `reply_seconds`) so dashboards
# can aggregate the per-user average. The lookup is "unanswered" in the
# sense that no other outbound by ANY user in the scope was sent between
# the inbound and now — once one user replies, the timer is consumed for
# all teammates (this matches the way agents share an inbox).
# =====================================================================
async def _wa_compute_reply_window(
    client_scope: Any,
    *,
    contact_id: Optional[str] = None,
    phone_digits: Optional[str] = None,
    now_iso: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve `{inbound_id, inbound_received_at, reply_seconds}` for the most
    recent unanswered inbound from the given contact, or None when nothing
    qualifies (no inbound in the last 7 days, or last activity is outbound).
    """
    or_clauses: List[Dict[str, Any]] = []
    if contact_id:
        or_clauses.append({"contact_id": contact_id})
    if phone_digits:
        or_clauses.append({"phone_digits": phone_digits})
    if not or_clauses:
        return None
    scope_q: Dict[str, Any]
    if isinstance(client_scope, (list, set, tuple)):
        scope_list = [s for s in client_scope if s]
        scope_q = {"client_id": {"$in": scope_list}} if scope_list else {}
    elif client_scope:
        scope_q = {"client_id": client_scope}
    else:
        scope_q = {}
    # Look at the latest message of either direction. If it's outbound, the
    # inbound was already answered, so we don't stamp anything.
    last_msg = await db.whatsapp_messages.find_one(
        {**scope_q, "$or": or_clauses},
        {"_id": 0, "id": 1, "direction": 1, "received_at": 1, "created_at": 1},
        sort=[("created_at", -1)],
    )
    if not last_msg or last_msg.get("direction") != "inbound":
        return None
    inbound_id = last_msg.get("id")
    inbound_at = last_msg.get("received_at") or last_msg.get("created_at")
    if not inbound_at:
        return None
    try:
        ts = datetime.fromisoformat(inbound_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        return None
    now_dt = datetime.now(timezone.utc)
    if now_iso:
        try:
            now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    delta = (now_dt - ts).total_seconds()
    # Cap at 7 days — anything older is rarely a "reply" and skews averages.
    if delta < 0 or delta > 7 * 24 * 3600:
        return None
    return {
        "inbound_id": inbound_id,
        "inbound_received_at": inbound_at,
        "reply_seconds": int(delta),
    }


async def _wa_last_inbound_iso(client_scope: Any, *, contact_id: Optional[str] = None, phone_digits: Optional[str] = None) -> Optional[str]:
    """Return the ISO timestamp of the most recent inbound WA message in the user's scope
    matching either the contact_id or the phone_digits. Used to compute the 24h window.

    Iter35f — `client_scope` may now be a list[str] (from _resolve_visible_client_ids)
    so a user whose own `client_id` differs from where the webhook anchored
    the inbound (e.g. on the primary superviseur) still finds the message
    and can answer within the 24h window. Backwards-compat: a single string
    is still accepted.
    """
    or_clauses: List[Dict[str, Any]] = []
    if contact_id:
        or_clauses.append({"contact_id": contact_id})
    if phone_digits:
        or_clauses.append({"phone_digits": phone_digits})
    if not or_clauses:
        return None
    scope_q: Dict[str, Any]
    if isinstance(client_scope, (list, set, tuple)):
        scope_list = [s for s in client_scope if s]
        scope_q = {"client_id": {"$in": scope_list}} if scope_list else {}
    elif client_scope:
        scope_q = {"client_id": client_scope}
    else:
        scope_q = {}
    q = {**scope_q, "direction": "inbound", "$or": or_clauses}
    doc = await db.whatsapp_messages.find_one(q, {"_id": 0, "received_at": 1, "created_at": 1}, sort=[("created_at", -1)])
    if not doc:
        return None
    return doc.get("received_at") or doc.get("created_at")


def _wa_window_open(last_inbound_iso: Optional[str]) -> bool:
    """Return True when the last inbound is within the 24h Meta customer service window."""
    if not last_inbound_iso:
        return False
    try:
        ts = datetime.fromisoformat(last_inbound_iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - ts).total_seconds() < WA_24H_WINDOW_SECONDS


class WhatsAppSendTextRequest(BaseModel):
    to: str
    text: str
    contact_id: Optional[str] = None
    tracked_user_id: Optional[str] = None


@api.post("/me/whatsapp/send-text", tags=["Portail Client"])
async def me_whatsapp_send_text(payload: WhatsAppSendTextRequest, user: dict = Depends(get_current_user)):
    """Send a free-form text WhatsApp message — only allowed within the Meta 24h
    customer service window (i.e. the contact has written to us in the last 24h)."""
    allowed = (
        user.get("role") in ("client", "admin", "demo")
        or _is_elevated_creator(user)
        or _is_tracked_user(user)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des messages WhatsApp")
    await _enforce_demo_quota(user, QUOTA_KEY_WA)  # Iter35h
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Le message ne peut pas être vide")
    if len(text) > 4096:
        raise HTTPException(status_code=400, detail="Message trop long (4096 caractères max)")
    # Iter34h — RGPD: resolve real WhatsApp number from contact_id if available
    to = await _resolve_real_phone(payload.contact_id, "whatsapp", payload.to or "")
    if not to:
        raise HTTPException(status_code=400, detail="Numéro destinataire requis")

    client_scope = (user.get("client_id") or user.get("id"))
    digits_only = "".join(ch for ch in to if ch.isdigit())

    # Verify 24h window: must have a recent inbound from this contact/phone
    # Iter35f — widen the lookup to every visible client_id of the user
    # (the webhook may have anchored the inbound on the primary superviseur,
    # whose client_id differs from the user's own).
    visible_scope = await _resolve_visible_client_ids(user)
    last_iso = await _wa_last_inbound_iso(visible_scope, contact_id=payload.contact_id, phone_digits=digits_only)
    if not _wa_window_open(last_iso):
        raise HTTPException(
            status_code=409,
            detail="Fenêtre 24h fermée — aucun message reçu de ce contact dans les dernières 24 heures. Utilisez un template Meta approuvé.",
        )

    result = await _wa_send_text(to, text)
    # Iter35n — Compute reply-time for the most recent unanswered inbound
    reply_window = None
    if result.get("ok"):
        try:
            reply_window = await _wa_compute_reply_window(
                visible_scope, contact_id=payload.contact_id, phone_digits=digits_only,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("WA reply-window calc failed (text): %s", exc)
    log = {
        "id": _uuid(),
        "client_id": client_scope,
        "direction": "outbound",
        "sender_id": user["id"],
        "sender_label": user.get("full_name") or user.get("email"),
        "to": to,
        "phone_digits": digits_only,
        "template_name": None,
        "language_code": None,
        "message_type": "text",
        "body": text,
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
    if reply_window:
        log["reply_to_inbound_id"] = reply_window["inbound_id"]
        log["reply_to_inbound_received_at"] = reply_window["inbound_received_at"]
        log["reply_seconds"] = reply_window["reply_seconds"]
    try:
        await db.whatsapp_messages.insert_one(log.copy())
    except Exception:
        pass
    log.pop("_id", None)
    return {"ok": result["ok"], "message_id": result["message_id"], "error": result.get("error"), "http_status": result["status"], "reply_seconds": (reply_window or {}).get("reply_seconds")}


# =====================================================================
# Iter35l — POST /me/whatsapp/send-media
# Send an image/document/audio/video to a contact (multipart upload).
# Constraints:
#   - 24h Meta customer-service window (same rule as send-text).
#   - Images: optional watermark + QR (admin-configurable in settings).
#   - Files are persisted via the media_library so each public URL is
#     stable and ext-visible (e.g. /api/files/{id}.jpg) — accepted by Meta.
# =====================================================================
WA_SEND_MEDIA_MAX_BYTES = 16 * 1024 * 1024  # 16MB — Meta image cap; safe for our PoC for all types


@api.post("/me/whatsapp/send-media", tags=["Portail Client"])
async def me_whatsapp_send_media(
    request: Request,
    to: str = Form(...),
    contact_id: Optional[str] = Form(None),
    tracked_user_id: Optional[str] = Form(None),
    caption: Optional[str] = Form(None),
    add_watermark: Optional[str] = Form(None),  # "1"/"0"/empty (defaults to admin setting)
    add_qr: Optional[str] = Form(None),         # "1"/"0"/empty (defaults to admin setting)
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Send a free-form WhatsApp media message inside the Meta 24h window."""
    allowed = (
        user.get("role") in ("client", "admin", "demo")
        or _is_elevated_creator(user)
        or _is_tracked_user(user)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des médias WhatsApp")

    # Admin-level RGPD toggle: terminal upload of media may be globally disabled
    s_root = await db.settings.find_one({"_id": "global"}) or {}
    if not bool(s_root.get("wa_allow_terminal_media", True)):
        raise HTTPException(status_code=403, detail="L'envoi de médias depuis ce terminal a été désactivé par l'administrateur.")

    await _enforce_demo_quota(user, QUOTA_KEY_WA)

    # Resolve real phone (RGPD anonymization restore)
    real_to = await _resolve_real_phone(contact_id, "whatsapp", to or "")
    if not real_to:
        raise HTTPException(status_code=400, detail="Numéro destinataire requis")

    digits_only = "".join(ch for ch in real_to if ch.isdigit())

    # 24h customer-service window
    visible_scope = await _resolve_visible_client_ids(user)
    last_iso = await _wa_last_inbound_iso(visible_scope, contact_id=contact_id, phone_digits=digits_only)
    if not _wa_window_open(last_iso):
        raise HTTPException(
            status_code=409,
            detail="Fenêtre 24h fermée — aucun message reçu de ce contact dans les dernières 24 heures.",
        )

    # Save the upload locally
    suffix = Path(file.filename or "").suffix.lower()
    content_type = (file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream").split(";", 1)[0].strip()
    kind = _wa_kind_for_mime(content_type)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(raw) > WA_SEND_MEDIA_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {WA_SEND_MEDIA_MAX_BYTES // (1024*1024)} Mo)")

    file_id = _uuid()
    safe_name = f"{file_id}{suffix}"
    target = UPLOAD_DIR / safe_name
    target.write_bytes(raw)

    # Optional image watermark + QR
    if kind == "image":
        wm_on = bool(s_root.get("wa_watermark_enabled", True))
        qr_on = bool(s_root.get("wa_qr_enabled", True))
        # Allow per-request override (form fields). Treat empty string as "use default".
        if isinstance(add_watermark, str) and add_watermark.strip() in ("0", "false", "no"):
            wm_on = False
        elif isinstance(add_watermark, str) and add_watermark.strip() in ("1", "true", "yes"):
            wm_on = True
        if isinstance(add_qr, str) and add_qr.strip() in ("0", "false", "no"):
            qr_on = False
        elif isinstance(add_qr, str) and add_qr.strip() in ("1", "true", "yes"):
            qr_on = True
        wm_text = (s_root.get("wa_watermark_text") or s_root.get("company_name") or "SAWALI SMART SYSTEMS").strip() if wm_on else None
        qr_payload = (s_root.get("wa_qr_payload") or s_root.get("company_website") or "").strip() if qr_on else None
        if not qr_payload and qr_on:
            # Fallback to public base url so the QR always means something
            base = _public_base_url(request) or (PUBLIC_BASE_URL or "")
            qr_payload = (base or "").rstrip("/") or None
        if wm_text or qr_payload:
            new_path = _wa_apply_image_watermark_qr(target, watermark_text=wm_text, qr_payload=qr_payload)
            if new_path != target:
                # Replace stored bytes with the watermarked version (new ext .jpg)
                try:
                    target.unlink(missing_ok=True)
                except Exception:
                    pass
                suffix = new_path.suffix
                safe_name = f"{file_id}{suffix}"
                target = UPLOAD_DIR / safe_name
                new_path.rename(target)
                content_type = "image/jpeg"
                kind = "image"
                raw = target.read_bytes()  # refresh size

    # Persist into files collection so /api/files/{id}.ext can serve it externally (Meta accesses by URL)
    ext = suffix.lstrip(".") or ""
    public_path = f"/api/files/{file_id}{('.' + ext) if ext else ''}"
    public_url = f"{(_public_base_url(request) or str(request.base_url).rstrip('/'))}{public_path}"
    file_doc = {
        "id": file_id,
        "filename": file.filename or safe_name,
        "stored_name": safe_name,
        "extension": ext or None,
        "content_type": content_type,
        "size": target.stat().st_size,
        "url": public_path,
        "public_url": public_url,
        "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"),
        "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
    }
    try:
        await db.files.insert_one(file_doc.copy())
    except Exception:
        pass

    # Send to WhatsApp Cloud API
    result = await _wa_send_media(
        real_to,
        kind,
        public_url=public_url,
        caption=caption,
        filename=file.filename,
    )

    # Iter35n — Compute reply-time for the most recent unanswered inbound
    reply_window = None
    if result.get("ok"):
        try:
            reply_window = await _wa_compute_reply_window(
                visible_scope, contact_id=contact_id, phone_digits=digits_only,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("WA reply-window calc failed (media): %s", exc)

    # Log into whatsapp_messages
    client_scope = (user.get("client_id") or user.get("id"))
    log = {
        "id": _uuid(),
        "client_id": client_scope,
        "direction": "outbound",
        "sender_id": user["id"],
        "sender_label": user.get("full_name") or user.get("email"),
        "to": real_to,
        "phone_digits": digits_only,
        "template_name": None,
        "language_code": None,
        "message_type": kind,
        "body": caption or f"[{kind} envoyé]",
        "media_id": file_id,
        "media_url": public_path,
        "media_mime_type": content_type,
        "media_filename": file.filename,
        "media_size_bytes": file_doc["size"],
        "media_kind": kind,
        "media_caption": caption,
        "contact_id": contact_id,
        "tracked_user_id": tracked_user_id,
        "ok": result["ok"],
        "status": result["status"],
        "message_id": result["message_id"],
        "error": result.get("error"),
        "wa_status": "sent" if result["ok"] else "failed",
        "sent_at": _now() if result["ok"] else None,
        "failed_at": None if result["ok"] else _now(),
        "created_at": _now(),
    }
    if reply_window:
        log["reply_to_inbound_id"] = reply_window["inbound_id"]
        log["reply_to_inbound_received_at"] = reply_window["inbound_received_at"]
        log["reply_seconds"] = reply_window["reply_seconds"]
    try:
        await db.whatsapp_messages.insert_one(log.copy())
    except Exception:
        pass
    log.pop("_id", None)
    return {
        "ok": result["ok"],
        "message_id": result["message_id"],
        "error": result.get("error"),
        "http_status": result["status"],
        "media_url": public_path,
        "kind": kind,
    }


# =====================================================================
# Iter35m — POST /me/whatsapp/messages/{msg_id}/save-to-library
# Re-use an inbound media (typically a photo received from a contact) by
# registering it in the shared media library. Does NOT re-upload the binary
# — it just creates a media_library entry pointing at the existing files row.
# =====================================================================
class SaveToLibraryRequest(BaseModel):
    label: Optional[str] = None


@api.post("/me/whatsapp/messages/{msg_id}/save-to-library", tags=["Portail Client"])
async def me_whatsapp_save_to_library(
    msg_id: str,
    payload: SaveToLibraryRequest = Body(default=None),
    user: dict = Depends(get_current_user),
):
    """Register an inbound WhatsApp media in the shared client media library."""
    allowed = (
        user.get("role") in ("client", "admin", "demo")
        or _is_elevated_creator(user)
        or _is_tracked_user(user)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Rôle non autorisé")

    visible_scope = await _resolve_visible_client_ids(user)
    msg = await db.whatsapp_messages.find_one(
        {"id": msg_id, "client_id": {"$in": visible_scope}}, {"_id": 0},
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message WhatsApp introuvable")
    if msg.get("direction") != "inbound":
        raise HTTPException(status_code=400, detail="Seuls les messages reçus peuvent être réutilisés")
    file_id = msg.get("media_id")
    media_url = msg.get("media_url")
    media_mime = msg.get("media_mime_type")
    if not file_id or not media_url:
        raise HTTPException(status_code=400, detail="Ce message ne contient pas de média téléchargé")

    # The underlying file must still exist in the files collection
    file_row = await db.files.find_one({"id": file_id}, {"_id": 0})
    if not file_row:
        raise HTTPException(status_code=410, detail="Fichier source introuvable (peut-être expiré)")

    # Idempotence: if a library entry for this file already exists in the same
    # client scope, return it instead of duplicating.
    client_scope = user.get("client_id") or user["id"]
    existing = await db.media_library.find_one(
        {"file_id": file_id, "client_id": client_scope}, {"_id": 0},
    )
    if existing:
        return {"ok": True, "media": existing, "already_existed": True}

    kind = msg.get("media_kind") or _wa_kind_for_mime(media_mime or "")
    # Build the label: user-provided OR contact name OR sender phone
    if payload and (payload.label or "").strip():
        label = payload.label.strip()[:200]
    else:
        contact_label = msg.get("contact_name") or msg.get("from_profile_name") or msg.get("from") or "WhatsApp"
        ts = (msg.get("received_at") or msg.get("created_at") or "")[:10]
        label = f"WA · {contact_label} · {ts}".strip(" ·")[:200]

    media = {
        "id": _uuid(),
        "file_id": file_id,
        "client_id": client_scope,
        "uploaded_by_id": user.get("id"),
        "uploaded_by_label": user.get("full_name") or user.get("email"),
        "label": label,
        "filename": file_row.get("filename") or msg.get("media_filename"),
        "kind": kind,
        "content_type": file_row.get("content_type") or media_mime,
        "extension": file_row.get("extension"),
        "size": file_row.get("size") or msg.get("media_size_bytes"),
        "public_url": file_row.get("public_url") or media_url,
        "source": "whatsapp_inbound",
        "source_message_id": msg_id,
        "created_at": _now(),
    }
    await db.media_library.insert_one(media.copy())
    media.pop("_id", None)
    return {"ok": True, "media": media, "already_existed": False}


# =====================================================================
# Iter35m — GET /me/dashboard/wa-media-summary?days=7|30|90
# Surface a quick overview of inbound WhatsApp media (images/audio/video/PDF)
# received in the trailing window — used by the portal dashboard card.
# =====================================================================
@api.get("/me/dashboard/wa-media-summary", tags=["Portail Client"])
async def me_wa_media_summary(
    days: int = Query(default=7, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    """Return a synthesis of WhatsApp inbound media received in the last `days`.

    Shape:
      {
        days, counts: {image, audio, video, document, total},
        top_contacts: [ {phone_digits, contact_name, count} … ],
        last_items: [ {id, kind, media_url, media_filename, from, contact_name, received_at, voice_note_transcript?} … ],
      }
    """
    visible_scope = await _resolve_visible_client_ids(user)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {
        "client_id": {"$in": visible_scope},
        "direction": "inbound",
        "media_url": {"$exists": True, "$ne": None},
        "$or": [
            {"received_at": {"$gte": since}},
            {"created_at": {"$gte": since}},
        ],
    }

    # Iter34u — anon_communications restriction (own messages only)
    restrictions = await _resolve_content_restrictions(user)
    if restrictions.get("anon_communications"):
        base_q["$and"] = [{"$or": [{"sender_id": user["id"]}, {"owner_id": user["id"]}]}]

    # Counts by kind
    counts = {"image": 0, "audio": 0, "video": 0, "document": 0, "total": 0}
    pipeline_kinds = [
        {"$match": base_q},
        {"$group": {"_id": "$media_kind", "n": {"$sum": 1}}},
    ]
    async for row in db.whatsapp_messages.aggregate(pipeline_kinds):
        kind = row.get("_id") or "document"
        if kind in counts:
            counts[kind] = row["n"]
        else:
            counts["document"] += row["n"]
        counts["total"] += row["n"]

    # Top 5 contacts (by phone_digits)
    pipeline_top = [
        {"$match": base_q},
        {"$group": {
            "_id": "$phone_digits",
            "count": {"$sum": 1},
            "contact_name": {"$last": "$contact_name"},
            "profile_name": {"$last": "$from_profile_name"},
            "from": {"$last": "$from"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_contacts: List[Dict[str, Any]] = []
    async for row in db.whatsapp_messages.aggregate(pipeline_top):
        top_contacts.append({
            "phone_digits": row.get("_id"),
            "contact_name": row.get("contact_name") or row.get("profile_name") or row.get("from"),
            "count": row["count"],
        })

    # Last 5 items
    last_items_cursor = db.whatsapp_messages.find(
        base_q,
        {
            "_id": 0, "id": 1, "media_url": 1, "media_kind": 1, "media_mime_type": 1,
            "media_filename": 1, "from": 1, "contact_name": 1, "from_profile_name": 1,
            "received_at": 1, "created_at": 1, "voice_note_transcript": 1, "contact_id": 1,
        },
    ).sort("created_at", -1).limit(5)
    last_items = [doc async for doc in last_items_cursor]

    return {
        "days": days,
        "counts": counts,
        "top_contacts": top_contacts,
        "last_items": last_items,
    }


# =====================================================================
# Iter35n — GET /me/dashboard/wa-reply-stats?days=7|30|90
# Surface the WhatsApp reply-time score for the current user (and the
# team's leaderboard for elevated viewers) so the dashboard can highlight
# "dynamic" responders.
# =====================================================================
@api.get("/me/dashboard/wa-reply-stats", tags=["Portail Client"])
async def me_wa_reply_stats(
    days: int = Query(default=7, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    """Return per-user WhatsApp reply-time aggregates for the trailing window.

    Shape:
      {
        days,
        me: {avg_seconds, median_seconds, replies, fastest_seconds},
        team: [{user_id, label, avg_seconds, replies, fastest_seconds} …]  // elevated only
      }
    """
    visible_scope = await _resolve_visible_client_ids(user)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {
        "client_id": {"$in": visible_scope},
        "direction": "outbound",
        "reply_seconds": {"$exists": True, "$ne": None, "$gt": 0},
        "$or": [
            {"sent_at": {"$gte": since}},
            {"created_at": {"$gte": since}},
        ],
    }

    # ---- Per-user (me) ----
    my_q = {**base_q, "sender_id": user["id"]}
    my_durations: List[int] = []
    async for d in db.whatsapp_messages.find(my_q, {"_id": 0, "reply_seconds": 1}):
        rs = int(d.get("reply_seconds") or 0)
        if rs > 0:
            my_durations.append(rs)
    my_durations.sort()
    me_block = {
        "avg_seconds": int(sum(my_durations) / len(my_durations)) if my_durations else None,
        "median_seconds": my_durations[len(my_durations) // 2] if my_durations else None,
        "replies": len(my_durations),
        "fastest_seconds": my_durations[0] if my_durations else None,
    }

    # ---- Team leaderboard (elevated viewers only) ----
    team: List[Dict[str, Any]] = []
    if _is_elevated_creator(user) or user.get("role") in ("admin", "superviseur"):
        pipeline = [
            {"$match": base_q},
            {"$group": {
                "_id": "$sender_id",
                "label": {"$last": "$sender_label"},
                "avg_seconds": {"$avg": "$reply_seconds"},
                "replies": {"$sum": 1},
                "fastest_seconds": {"$min": "$reply_seconds"},
            }},
            {"$sort": {"avg_seconds": 1}},
            {"$limit": 10},
        ]
        async for row in db.whatsapp_messages.aggregate(pipeline):
            if not row.get("_id"):
                continue
            team.append({
                "user_id": row["_id"],
                "label": row.get("label") or row["_id"][:8],
                "avg_seconds": int(row["avg_seconds"]) if row.get("avg_seconds") is not None else None,
                "replies": row.get("replies") or 0,
                "fastest_seconds": int(row["fastest_seconds"]) if row.get("fastest_seconds") is not None else None,
            })

    return {"days": days, "me": me_block, "team": team}


# ---------- Unread inbound counters + mark-read ----------
@api.get("/me/whatsapp/unread", tags=["Portail Client"])
async def me_whatsapp_unread(user: dict = Depends(get_current_user)):
    """Return per-contact unread counts plus a global total of inbound WA messages
    where `read_by_us_at` is null. Used by the sidebar badge and per-contact pastille.

    Iter34p — Uses _resolve_visible_client_ids so pastilles stay accurate
    after a realignment (the contact_ids reported here match the ones the
    user sees through /me/contacts)."""
    visible_scope = await _resolve_visible_client_ids(user)
    base_q: Dict[str, Any] = {"direction": "inbound", "read_by_us_at": None}
    if user.get("role") != "admin":
        base_q["client_id"] = {"$in": visible_scope}
    pipeline = [
        {"$match": base_q},
        {"$group": {"_id": "$contact_id", "n": {"$sum": 1}}},
    ]
    by_contact: Dict[str, int] = {}
    total = 0
    async for row in db.whatsapp_messages.aggregate(pipeline):
        cid = row.get("_id") or "_unknown"
        n = int(row.get("n") or 0)
        by_contact[cid] = n
        total += n
    return {"total": total, "by_contact": by_contact}


@api.post("/me/contacts/{cid}/messages/mark-read", tags=["Portail Client"])
async def me_contact_messages_mark_read(cid: str, user: dict = Depends(get_current_user)):
    """Mark all inbound WA messages of a given contact as read (sets read_by_us_at)."""
    # Iter34p — Use the visible-scope resolution so we find the contact even
    # when its client_id is one of the historical/peer values (rabo.f-style
    # data is now legitimately accessed via the company bridge).
    visible_scope = await _resolve_visible_client_ids(user)
    contact = await db.directory_contacts.find_one(
        {"id": cid, "client_id": {"$in": visible_scope}}, {"_id": 0},
    )
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    norm_phones: List[str] = []
    for raw in (contact.get("whatsapp") or "", contact.get("phone") or ""):
        clean = "".join(ch for ch in (raw or "") if ch.isdigit())
        if clean:
            norm_phones.append(clean)
    or_clauses: List[Dict[str, Any]] = [{"contact_id": cid}]
    if norm_phones:
        or_clauses.append({"phone_digits": {"$in": norm_phones}})
    res = await db.whatsapp_messages.update_many(
        {"client_id": {"$in": visible_scope}, "direction": "inbound", "read_by_us_at": None, "$or": or_clauses},
        {"$set": {"read_by_us_at": _now(), "read_by_us_id": user["id"]}},
    )
    return {"ok": True, "updated": int(getattr(res, "modified_count", 0) or 0)}


# ============================================================
# SMS multi-provider gateway (Orange BFA / Moov BFA / Telecel BFA / OVH)
# Each Burkina provider is a configurable HTTP webhook (URL + method +
# auth + payload template). OVH uses its official HMAC-SHA1 signed API.
# Outbound usage is recorded in db.sms_messages for audit + analytics.
# ============================================================
SMS_BFA_PROVIDERS = ("orange", "moov", "telecel")


def _sms_substitute(template: str, mapping: Dict[str, str]) -> str:
    """Replace {phone}, {message}, {sender} (and any custom key) inside a string."""
    out = template or ""
    for k, v in (mapping or {}).items():
        out = out.replace("{" + k + "}", str(v if v is not None else ""))
    return out


def _sms_provider_cfg(s: Dict[str, Any], provider: str) -> Optional[Dict[str, Any]]:
    p = (provider or "").lower().strip()
    if p in SMS_BFA_PROVIDERS:
        if not s.get(f"sms_{p}_enabled"):
            return None
        return {
            "kind": "generic",
            "name": p,
            "url": s.get(f"sms_{p}_url"),
            "method": (s.get(f"sms_{p}_method") or "POST").upper(),
            "auth_type": (s.get(f"sms_{p}_auth_type") or "none").lower(),
            "token": s.get(f"sms_{p}_token"),
            "basic_user": s.get(f"sms_{p}_basic_user"),
            "basic_pass": s.get(f"sms_{p}_basic_pass"),
            "header_name": s.get(f"sms_{p}_header_name"),
            "header_value": s.get(f"sms_{p}_header_value"),
            "sender": s.get(f"sms_{p}_sender"),
            "payload_template": s.get(f"sms_{p}_payload_template"),
            "content_type": (s.get(f"sms_{p}_content_type") or "json").lower(),
            # Iter35i — Orange Developer OAuth2 client_credentials flow
            "oauth_url": s.get(f"sms_{p}_oauth_url"),
            "client_id": s.get(f"sms_{p}_client_id"),
            "client_secret": s.get(f"sms_{p}_client_secret"),
            "sender_msisdn": s.get(f"sms_{p}_sender_msisdn"),
        }
    if p == "ovh":
        if not s.get("sms_ovh_enabled"):
            return None
        return {
            "kind": "ovh",
            "name": "ovh",
            "endpoint": (s.get("sms_ovh_endpoint") or "ovh-eu").lower(),
            "application_key": s.get("sms_ovh_application_key"),
            "application_secret": s.get("sms_ovh_application_secret"),
            "consumer_key": s.get("sms_ovh_consumer_key"),
            "service_name": s.get("sms_ovh_service_name"),
            "sender": s.get("sms_ovh_sender") or "OVHSMS",
        }
    return None


def _sms_active_providers(s: Dict[str, Any]) -> List[str]:
    out = [p for p in SMS_BFA_PROVIDERS if s.get(f"sms_{p}_enabled")]
    if s.get("sms_ovh_enabled"):
        out.append("ovh")
    return out


def _sms_pick_default(s: Dict[str, Any], msisdn: str) -> Optional[str]:
    """Pick a default provider when caller passes 'auto' or omits provider."""
    explicit = (s.get("sms_default_provider") or "auto").lower()
    if explicit and explicit != "auto":
        return explicit if _sms_provider_cfg(s, explicit) else None
    actives = _sms_active_providers(s)
    if not actives:
        return None
    digits = "".join(ch for ch in (msisdn or "") if ch.isdigit())
    if digits.startswith("226"):
        for c in ("orange", "moov", "telecel"):
            if c in actives:
                return c
    if "ovh" in actives:
        return "ovh"
    return actives[0]


def _ovh_host(endpoint: str) -> str:
    e = (endpoint or "ovh-eu").lower()
    if e == "ovh-ca":
        return "https://ca.api.ovh.com/1.0"
    return "https://eu.api.ovh.com/1.0"


async def _sms_send_ovh(cfg: Dict[str, Any], msisdn_e164: str, message: str, sender: Optional[str]) -> Dict[str, Any]:
    """Send an SMS via OVH official API. Uses HMAC-SHA1 signing scheme."""
    if not all([cfg.get("application_key"), cfg.get("application_secret"), cfg.get("consumer_key"), cfg.get("service_name")]):
        return {"ok": False, "status": "failed", "api_message": "OVH credentials incomplete"}
    host = _ovh_host(cfg.get("endpoint"))
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            tr = await http.get(f"{host}/auth/time")
            ts = str(int(tr.text.strip())) if tr.status_code == 200 else str(int(datetime.now(timezone.utc).timestamp()))
    except Exception:  # noqa: BLE001
        ts = str(int(datetime.now(timezone.utc).timestamp()))
    url = f"{host}/sms/{cfg['service_name']}/jobs"
    body = {
        "charset": "UTF-8",
        "class": "phoneDisplay",
        "coding": "8bit",
        "message": message,
        "noStopClause": False,
        "priority": "high",
        "receivers": [msisdn_e164 if msisdn_e164.startswith("+") else f"+{msisdn_e164}"],
        "senderForResponse": False,
        "sender": sender or cfg.get("sender") or "OVHSMS",
        "validityPeriod": 2880,
    }
    body_str = json.dumps(body)
    to_sign = "+".join([cfg["application_secret"], cfg["consumer_key"], "POST", url, body_str, ts])
    signature = "$1$" + hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
    headers = {
        "X-Ovh-Application": cfg["application_key"],
        "X-Ovh-Consumer": cfg["consumer_key"],
        "X-Ovh-Timestamp": ts,
        "X-Ovh-Signature": signature,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(url, headers=headers, content=body_str)
            try:
                resp = r.json()
            except Exception:  # noqa: BLE001
                resp = {"raw": r.text[:500]}
            if r.status_code >= 300:
                return {"ok": False, "status": "failed", "http_status": r.status_code, "api_message": _safe_text(resp.get("message") if isinstance(resp, dict) else None) or f"HTTP {r.status_code}", "raw_response": resp}
            invalid = (resp.get("invalidReceivers") or []) if isinstance(resp, dict) else []
            valid = (resp.get("validReceivers") or []) if isinstance(resp, dict) else []
            if invalid and not valid:
                return {"ok": False, "status": "failed", "api_message": f"Numéro rejeté : {', '.join(invalid)}", "raw_response": resp}
            return {"ok": True, "status": "sent", "http_status": r.status_code, "api_message": _safe_text(resp.get("message") if isinstance(resp, dict) else None), "raw_response": resp}
    except httpx.TimeoutException:
        return {"ok": False, "status": "failed", "api_message": "OVH timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "failed", "api_message": str(exc)[:300]}


# ============================================================
# Iter35i — Orange Developer SMS API (OAuth2 client_credentials).
#
# Orange's official SMS API at https://api.orange.com/smsmessaging/v1 needs:
#  1. POST {oauth_url} with `Authorization: Basic base64(client_id:client_secret)`
#     and body `grant_type=client_credentials` ENCODED AS form-urlencoded.
#     This was the failing step — the generic flow sent JSON / no body, so
#     Orange answered: {"error":"invalid_request","error_description":"Missing grant_type in body"}
#  2. POST {url}/outbound/tel%3A%2B<sender>/requests with the OAuth Bearer
#     and a specific JSON envelope `outboundSMSMessageRequest`.
#
# We cache the access_token in memory for `expires_in - 60s` to avoid
# pestering the token endpoint on every send.
# ============================================================
_ORANGE_TOKEN_CACHE: Dict[str, Dict[str, Any]] = {}


async def _orange_get_token(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch (and cache) the OAuth2 client_credentials access token.

    Returns the parsed token document on success or {"error": ...} otherwise.
    The cache key combines the OAuth URL + client_id so re-configuring
    credentials invalidates the cached token.
    """
    oauth_url = (cfg.get("oauth_url") or "https://api.orange.com/oauth/v3/token").strip()
    client_id = (cfg.get("client_id") or "").strip()
    client_secret = (cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        return {"error": "Identifiants OAuth Orange manquants (client_id ou client_secret)"}
    cache_key = f"{oauth_url}|{client_id}"
    cached = _ORANGE_TOKEN_CACHE.get(cache_key)
    now_ts = datetime.now(timezone.utc).timestamp()
    if cached and cached.get("expires_at", 0) > now_ts + 5:
        return {"access_token": cached["access_token"], "cached": True}
    import base64 as _b64
    basic = _b64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    # Iter35i-fix2 — belt-and-suspenders : send `data=dict` (httpx encodes
    # AND sets Content-Type) AND also explicit Content-Type header (some
    # corporate proxies strip auto-headers). + verbose logging on failure.
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {"grant_type": "client_credentials"}
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(oauth_url, headers=headers, data=data)
            try:
                doc = r.json()
            except Exception:
                doc = {"raw": r.text[:300]}
            if r.status_code >= 300:
                logger.warning(
                    "Orange OAuth fail %s url=%s req_ct=%s req_body=%s resp=%s",
                    r.status_code, oauth_url,
                    r.request.headers.get("Content-Type"),
                    r.request.content[:200] if r.request.content else b"",
                    str(doc)[:300],
                )
                err_msg = doc.get("error_description") or doc.get("error") or str(doc)[:300]
                return {"error": f"OAuth Orange {r.status_code}: {err_msg}"}
            access_token = (doc or {}).get("access_token")
            expires_in = int((doc or {}).get("expires_in") or 3600)
            if not access_token:
                return {"error": f"OAuth Orange: pas d'access_token dans la réponse ({doc})"}
            _ORANGE_TOKEN_CACHE[cache_key] = {
                "access_token": access_token,
                "expires_at": now_ts + max(60, expires_in - 60),
            }
            return {"access_token": access_token, "expires_in": expires_in, "cached": False}
    except httpx.TimeoutException:
        return {"error": "OAuth Orange: timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"OAuth Orange: {exc!r}"[:300]}


async def _sms_send_orange_oauth(cfg: Dict[str, Any], msisdn_digits: str, message: str, sender: Optional[str]) -> Dict[str, Any]:
    """Send via Orange Developer SMS API using the cached OAuth bearer."""
    tok = await _orange_get_token(cfg)
    if "error" in tok:
        return {"ok": False, "status": "failed", "api_message": tok["error"]}
    access_token = tok["access_token"]

    # Sender: Orange expects the registered MSISDN in international format,
    # URL-encoded inside the path (tel:+22507..., where + → %2B).
    sender_msisdn = (sender or cfg.get("sender_msisdn") or cfg.get("sender") or "").strip()
    if not sender_msisdn:
        return {"ok": False, "status": "failed", "api_message": "Numéro émetteur (sender_msisdn) requis pour Orange OAuth"}
    sender_clean = sender_msisdn if sender_msisdn.startswith("+") else f"+{sender_msisdn}"

    # Build endpoint URL — allow the admin's configured URL to be either:
    #   - the bare base (https://api.orange.com/smsmessaging/v1) → we append
    #     /outbound/tel%3A%2B<sender>/requests
    #   - the fully-resolved one with tel placeholder
    import urllib.parse as _urlp
    base_url = (cfg.get("url") or "https://api.orange.com/smsmessaging/v1").strip().rstrip("/")
    encoded_sender = _urlp.quote(f"tel:{sender_clean}", safe="")
    if "/outbound/" not in base_url:
        endpoint = f"{base_url}/outbound/{encoded_sender}/requests"
    else:
        endpoint = base_url  # admin gave the full URL

    dest = msisdn_digits if msisdn_digits.startswith("+") else f"+{msisdn_digits}"
    body = {
        "outboundSMSMessageRequest": {
            "address": f"tel:{dest}",
            "senderAddress": f"tel:{sender_clean}",
            "outboundSMSTextMessage": {"message": message},
        }
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(endpoint, headers=headers, json=body)
            try:
                resp = r.json()
            except Exception:
                resp = {"raw": r.text[:500]}
            if r.status_code == 401:
                # Token may have just expired between cache check and request:
                # purge cache and retry ONCE.
                cache_key = f"{(cfg.get('oauth_url') or 'https://api.orange.com/oauth/v3/token').strip()}|{(cfg.get('client_id') or '').strip()}"
                _ORANGE_TOKEN_CACHE.pop(cache_key, None)
                tok2 = await _orange_get_token(cfg)
                if "access_token" in tok2:
                    headers["Authorization"] = f"Bearer {tok2['access_token']}"
                    r = await http.post(endpoint, headers=headers, json=body)
                    try:
                        resp = r.json()
                    except Exception:
                        resp = {"raw": r.text[:500]}
            ok = 200 <= r.status_code < 300
            api_msg = None
            if isinstance(resp, dict):
                # Orange's error shape varies; surface the most useful field
                fault = (resp.get("requestError") or {}).get("serviceException") or (resp.get("requestError") or {}).get("policyException")
                if fault:
                    api_msg = f"{fault.get('messageId', '')}: {fault.get('text', '')}"
                else:
                    api_msg = resp.get("message") or None
            return {
                "ok": ok,
                "status": "sent" if ok else "failed",
                "http_status": r.status_code,
                "api_message": _safe_text(api_msg) or (None if ok else f"HTTP {r.status_code}"),
                "raw_response": resp,
            }
    except httpx.TimeoutException:
        return {"ok": False, "status": "failed", "api_message": "Orange OAuth send timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "failed", "api_message": str(exc)[:300]}


async def _sms_send_via_webhook(cfg: Dict[str, Any], msisdn: str, message: str, sender: Optional[str]) -> Dict[str, Any]:
    """Iter35k — Bridge mode: POST a simple JSON payload to a user-controlled
    webhook (typically an n8n / Make / Zapier workflow). The webhook does
    the heavy lifting (OAuth, retries, provider-specific format) and returns
    a response that we surface to the admin UI.

    Outbound payload sent to the webhook:
        {
            "provider": "orange|moov|telecel",
            "phone": "+22607332313",
            "message": "Hello",
            "sender": "+22677000155"   # may be None
        }

    Expected webhook response shape (anything else is best-effort parsed):
        {
            "status": "sent" | "failed",         # OR
            "ok": true | false,                  # OR
            "success": true | false,
            "api_message": "Optional human readable message",
            "raw": { ...provider raw response... }
        }
    Webhook may also include `Authorization: Bearer <token>` if
    `auth_type=webhook` AND `token` (in sms_*_token) is set — used to
    secure your n8n endpoint.
    """
    url = (cfg.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "status": "failed", "api_message": "URL webhook invalide (vide ou non http(s))"}
    payload = {
        "provider": cfg.get("name") or "unknown",
        "phone": msisdn if msisdn.startswith("+") else f"+{msisdn}",
        "message": message,
        "sender": (sender or cfg.get("sender") or cfg.get("sender_msisdn")),
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = (cfg.get("token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(url, headers=headers, json=payload)
            try:
                resp = r.json()
            except Exception:
                resp = {"raw": r.text[:500]}
            # Tolerant success detection
            ok_http = 200 <= r.status_code < 300
            ok_body = False
            api_msg = None
            if isinstance(resp, dict):
                status_val = (resp.get("status") or "").lower()
                ok_body = (
                    resp.get("ok") is True
                    or resp.get("success") is True
                    or status_val in ("sent", "ok", "success", "delivered")
                )
                # n8n's $json.error.* shape from your workflow
                err = resp.get("error") or {}
                if isinstance(err, dict) and (err.get("status") not in (None, 200, "200")):
                    ok_body = False
                    api_msg = f"{err.get('status')} {err.get('code', '')}: {err.get('message', '')}".strip()
                else:
                    api_msg = (
                        resp.get("api_message")
                        or resp.get("message")
                        or resp.get("maReponse")
                        or None
                    )
                # If the webhook responds 200 with NO explicit ok/status field,
                # consider it a success (your workflow does this).
                if ok_http and not ok_body and "ok" not in resp and "status" not in resp and "success" not in resp and not (isinstance(err, dict) and err):
                    ok_body = True
            ok = ok_http and ok_body
            return {
                "ok": ok,
                "status": "sent" if ok else "failed",
                "http_status": r.status_code,
                "api_message": _safe_text(api_msg) or (None if ok else f"HTTP {r.status_code}"),
                "raw_response": resp,
            }
    except httpx.TimeoutException:
        return {"ok": False, "status": "failed", "api_message": "Webhook timeout (>30s)"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "failed", "api_message": str(exc)[:300]}



async def _sms_send_generic(cfg: Dict[str, Any], msisdn: str, message: str, sender: Optional[str]) -> Dict[str, Any]:
    """Send via a generic configurable HTTP webhook (Orange/Moov/Telecel BFA)."""
    # Iter35i — branch off to the dedicated Orange Developer OAuth2 flow.
    if (cfg.get("auth_type") or "").lower() == "orange_oauth":
        return await _sms_send_orange_oauth(cfg, msisdn, message, sender)
    # Iter35k — branch off to the n8n-style webhook bridge: we just POST
    # {phone, message, sender, provider} as JSON to the configured URL
    # (the user's workflow handles all the provider-specific OAuth/SMS calls)
    # and we parse whatever the webhook returns.
    if (cfg.get("auth_type") or "").lower() == "webhook":
        return await _sms_send_via_webhook(cfg, msisdn, message, sender)
    url = (cfg.get("url") or "").strip()
    if not url:
        return {"ok": False, "status": "failed", "api_message": f"URL non configurée pour {cfg.get('name')}"}
    method = (cfg.get("method") or "POST").upper()
    final_sender = sender or cfg.get("sender") or "SAWALI"
    mapping = {"phone": msisdn, "message": message, "sender": final_sender}
    final_url = _sms_substitute(url, mapping)
    headers: Dict[str, str] = {}
    auth = (cfg.get("auth_type") or "none").lower()
    httpx_auth = None
    if auth == "bearer" and cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    elif auth == "basic" and cfg.get("basic_user"):
        httpx_auth = (cfg.get("basic_user") or "", cfg.get("basic_pass") or "")
    elif auth == "header" and cfg.get("header_name"):
        headers[cfg["header_name"]] = _sms_substitute(cfg.get("header_value") or "", mapping)
    payload_tpl = cfg.get("payload_template")
    body_obj: Any = None
    body_str: Optional[str] = None
    content_type = (cfg.get("content_type") or "json").lower()
    if method != "GET" and payload_tpl:
        rendered = _sms_substitute(payload_tpl, mapping)
        if content_type == "form":
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            body_str = rendered
        else:
            headers.setdefault("Content-Type", "application/json")
            try:
                body_obj = json.loads(rendered)
            except Exception:  # noqa: BLE001
                body_str = rendered
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            req_kwargs: Dict[str, Any] = {"headers": headers}
            if httpx_auth:
                req_kwargs["auth"] = httpx_auth
            if body_obj is not None:
                req_kwargs["json"] = body_obj
            elif body_str is not None:
                req_kwargs["content"] = body_str
            r = await http.request(method, final_url, **req_kwargs)
            try:
                resp = r.json()
            except Exception:  # noqa: BLE001
                resp = {"raw": r.text[:500]}
            ok = 200 <= r.status_code < 300
            return {
                "ok": ok,
                "status": "sent" if ok else "failed",
                "http_status": r.status_code,
                "api_message": _safe_text(resp.get("message") if isinstance(resp, dict) else None) or (None if ok else f"HTTP {r.status_code}"),
                "raw_response": resp,
            }
    except httpx.TimeoutException:
        return {"ok": False, "status": "failed", "api_message": "Timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "failed", "api_message": str(exc)[:300]}


async def _sms_dispatch(provider: str, msisdn: str, message: str, sender: Optional[str] = None) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}) or {}
    actual_provider = provider
    if not actual_provider or actual_provider == "auto":
        actual_provider = _sms_pick_default(s, msisdn)
    if not actual_provider:
        return {"ok": False, "status": "failed", "api_message": "Aucun fournisseur SMS disponible", "provider": None}
    cfg = _sms_provider_cfg(s, actual_provider)
    if not cfg:
        return {"ok": False, "status": "failed", "api_message": f"Fournisseur '{actual_provider}' non activé", "provider": actual_provider}
    msisdn_clean = "".join(ch for ch in (msisdn or "") if ch.isdigit() or ch == "+")
    if cfg["kind"] == "ovh":
        result = await _sms_send_ovh(cfg, msisdn_clean if msisdn_clean.startswith("+") else f"+{msisdn_clean}", message, sender)
    else:
        result = await _sms_send_generic(cfg, msisdn_clean.lstrip("+"), message, sender)
    result["provider"] = actual_provider
    return result


class MeSmsSendRequest(BaseModel):
    to: str
    message: str
    provider: Optional[str] = None
    sender: Optional[str] = None
    contact_id: Optional[str] = None


@api.get("/me/sms/providers", tags=["Portail Client"])
async def me_sms_providers(user: dict = Depends(get_current_user)):
    """Tell the portal which SMS providers are configured + the default one."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    return {
        "default": (s.get("sms_default_provider") or "auto").lower(),
        "active": _sms_active_providers(s),
        "ovh_enabled": bool(s.get("sms_ovh_enabled")),
    }


@api.post("/me/sms/send", tags=["Portail Client"])
async def me_sms_send(payload: MeSmsSendRequest, request: Request, user: dict = Depends(get_current_user)):
    parent_id = user.get("client_id") or user["id"]
    if user.get("role") not in ("admin", "superviseur"):
        parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("sms") and user.get("role") != "demo":
            raise HTTPException(status_code=403, detail="SMS non autorisé pour votre compte")
    await _enforce_demo_quota(user, QUOTA_KEY_SMS)  # Iter35h
    if not (payload.message or "").strip():
        raise HTTPException(status_code=400, detail="Message vide")
    if len(payload.message) > 800:
        raise HTTPException(status_code=400, detail="Message trop long (>800 caractères)")
    # Iter34h — RGPD: resolve real phone number from contact_id if available
    real_to = await _resolve_real_phone(payload.contact_id, "phone", payload.to or "")
    if not real_to:
        raise HTTPException(status_code=400, detail="Destinataire requis")
    result = await _sms_dispatch(payload.provider or "auto", real_to, payload.message, payload.sender)
    pay_slug = _extract_pay_slug(payload.message)
    doc = {
        "id": _uuid(),
        "client_id": parent_id,
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_label": user.get("full_name") or user.get("email"),
        "contact_id": payload.contact_id,
        "provider": result.get("provider"),
        "sender": payload.sender,
        "msisdn": real_to,
        "msisdn_digits": "".join(ch for ch in real_to if ch.isdigit()),
        "message": payload.message,
        "length": len(payload.message),
        "status": result.get("status"),
        "api_message": result.get("api_message"),
        "http_status": result.get("http_status"),
        "raw_response": result.get("raw_response"),
        "payment_link_slug": pay_slug,
        "ip": _client_ip_from_request(request),
        "created_at": _now(),
    }
    await db.sms_messages.insert_one(doc.copy())
    doc.pop("_id", None)
    if result.get("ok"):
        await _log_activity(client_id=parent_id, kind="sms", action="sent", label=f"→ {real_to}", actor=user, target_id=doc["id"])
    return {"ok": result.get("ok"), "provider": result.get("provider"), "status": result.get("status"),
            "error": None if result.get("ok") else _safe_text(result.get("api_message")),
            "http_status": result.get("http_status"), "id": doc["id"]}


@api.get("/me/sms/messages", tags=["Portail Client"])
async def me_sms_messages(limit: int = 100, contact_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    # Iter34p — Resolve full visible scope so SMS stays visible after a
    # realignment/migration (same fix as me_contact_messages).
    if user.get("role") == "admin":
        query: Dict[str, Any] = {}
    else:
        visible_scope = await _resolve_visible_client_ids(user)
        query = {"client_id": {"$in": visible_scope}}
    if contact_id:
        query["contact_id"] = contact_id
    items = await db.sms_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    # Iter34u — When anon_communications is ON, restrict to SMS exchanged by
    # the current user only.
    restrictions = await _resolve_content_restrictions(user)
    if restrictions.get("anon_communications"):
        items = [m for m in items if (m.get("sender_id") == user["id"] or m.get("owner_id") == user["id"])]
    return items


class AdminSmsTestRequest(BaseModel):
    provider: str
    to: str
    message: Optional[str] = None
    sender: Optional[str] = None


@api.post("/admin/sms/test", tags=["Admin"])
async def admin_sms_test(payload: AdminSmsTestRequest, request: Request, user: dict = Depends(get_current_admin)):
    """Send a test SMS using a chosen provider — surfaces the full HTTP response
    so the admin can debug the credentials / payload template quickly."""
    msg = (payload.message or "Test SMS depuis SAWALI Admin — il s'agit d'un message de validation.").strip()
    if len(msg) > 600:
        raise HTTPException(status_code=400, detail="Message trop long")
    result = await _sms_dispatch(payload.provider or "auto", payload.to, msg, payload.sender)
    doc = {
        "id": _uuid(),
        "client_id": "admin-test",
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_label": user.get("full_name") or user.get("email"),
        "provider": result.get("provider"),
        "sender": payload.sender,
        "msisdn": payload.to,
        "msisdn_digits": "".join(ch for ch in (payload.to or "") if ch.isdigit()),
        "message": msg,
        "length": len(msg),
        "status": result.get("status"),
        "api_message": result.get("api_message"),
        "http_status": result.get("http_status"),
        "raw_response": result.get("raw_response"),
        "ip": _client_ip_from_request(request),
        "kind": "admin_test",
        "created_at": _now(),
    }
    await db.sms_messages.insert_one(doc.copy())
    doc.pop("_id", None)
    return {
        "ok": result.get("ok"),
        "provider": result.get("provider"),
        "status": result.get("status"),
        "http_status": result.get("http_status"),
        "api_message": result.get("api_message"),
        "raw_response": result.get("raw_response"),
        "id": doc["id"],
    }



# ============================================================
# SMS Phase 2 — Bulk send + Scheduled sends
# ============================================================
def _personalize_sms(template: str, ctx: Dict[str, Any]) -> str:
    """Replace {{name}}/{{company}}/{{phone}}/{{whatsapp}}/{{email}} tokens
    inside an SMS body using the recipient's contact attributes."""
    out = template or ""
    for k, v in (ctx or {}).items():
        out = out.replace("{{" + k + "}}", str(v if v is not None else ""))
    return out


def _build_sms_ctx(contact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": contact.get("name") or "",
        "company": contact.get("company") or "",
        "phone": contact.get("phone") or "",
        "whatsapp": contact.get("whatsapp") or "",
        "email": contact.get("email") or "",
        "tag": ", ".join(contact.get("tags") or []),
    }


def _extract_pay_slug(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"/pay/([a-z0-9]{4,16})", text)
    return m.group(1) if m else None


class MeSmsBulkRequest(BaseModel):
    contact_ids: List[str]
    message: str
    provider: Optional[str] = None
    sender: Optional[str] = None
    scheduled_at: Optional[str] = None  # ISO8601 — if set, schedule instead of send


@api.post("/me/sms/bulk", tags=["Portail Client"])
async def me_sms_bulk(payload: MeSmsBulkRequest, request: Request, user: dict = Depends(get_current_user)):
    parent_id = user.get("client_id") or user["id"]
    if user.get("role") not in ("admin", "superviseur"):
        parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("sms"):
            raise HTTPException(status_code=403, detail="SMS non autorisé pour votre compte")
    if not (payload.message or "").strip():
        raise HTTPException(status_code=400, detail="Message vide")
    if len(payload.message) > 800:
        raise HTTPException(status_code=400, detail="Message trop long (>800 caractères)")
    if not payload.contact_ids:
        raise HTTPException(status_code=400, detail="Aucun destinataire sélectionné")
    if len(payload.contact_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 destinataires par envoi")
    contacts = await db.directory_contacts.find(
        {"id": {"$in": payload.contact_ids}, "client_id": parent_id}, {"_id": 0}
    ).to_list(len(payload.contact_ids))

    # Schedule for later if requested
    if payload.scheduled_at:
        try:
            sched_dt = datetime.fromisoformat(str(payload.scheduled_at).replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(status_code=400, detail="Date de planification invalide")
        if sched_dt < datetime.now(timezone.utc) + timedelta(seconds=30):
            raise HTTPException(status_code=400, detail="La date de planification doit être au moins +30 secondes")
        sched_doc = {
            "id": _uuid(),
            "kind": "sms",
            "client_id": parent_id,
            "created_by_id": user["id"],
            "created_by_label": user.get("full_name") or user.get("email"),
            "provider": payload.provider or "auto",
            "sender": payload.sender,
            "message_template": payload.message,
            "contact_ids": payload.contact_ids,
            "scheduled_at": sched_dt.astimezone(timezone.utc).isoformat(),
            "status": "pending",
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.sms_schedules.insert_one(sched_doc.copy())
        sched_doc.pop("_id", None)
        return {"ok": True, "scheduled": True, "id": sched_doc["id"], "scheduled_at": sched_doc["scheduled_at"], "recipients": len(payload.contact_ids)}

    # Live bulk send (synchronous, capped at 500 to keep request <30s)
    results = []
    skipped = []
    pay_slug = _extract_pay_slug(payload.message)
    for c in contacts:
        target = c.get("phone") or c.get("whatsapp")
        if not target:
            skipped.append({"label": c.get("name"), "reason": "Pas de numéro"})
            continue
        ctx = _build_sms_ctx(c)
        body = _personalize_sms(payload.message, ctx)
        result = await _sms_dispatch(payload.provider or "auto", target, body, payload.sender)
        doc = {
            "id": _uuid(), "client_id": parent_id, "user_id": user["id"],
            "user_email": user.get("email"), "user_label": user.get("full_name") or user.get("email"),
            "contact_id": c.get("id"),
            "provider": result.get("provider"), "sender": payload.sender,
            "msisdn": target, "msisdn_digits": "".join(ch for ch in target if ch.isdigit()),
            "message": body, "length": len(body),
            "status": result.get("status"), "api_message": result.get("api_message"),
            "http_status": result.get("http_status"), "raw_response": result.get("raw_response"),
            "bulk": True,
            "payment_link_slug": pay_slug,
            "ip": _client_ip_from_request(request),
            "created_at": _now(),
        }
        await db.sms_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        results.append({"label": c.get("name"), "phone": target, "ok": result.get("ok"),
                        "status": result.get("status"), "error": None if result.get("ok") else result.get("api_message")})
    return {"ok": True, "scheduled": False, "sent_ok": sum(1 for r in results if r["ok"]),
            "sent_ko": len([r for r in results if not r["ok"]]), "skipped": skipped, "results": results}


@api.get("/me/sms/schedules", tags=["Portail Client"])
async def me_sms_schedules(user: dict = Depends(get_current_user)):
    is_admin = user.get("role") in ("admin", "superviseur")
    q: Dict[str, Any] = {} if is_admin else {"client_id": user.get("client_id") or user["id"]}
    items = await db.sms_schedules.find(q, {"_id": 0}).sort("scheduled_at", -1).to_list(200)
    return items


@api.delete("/me/sms/schedules/{sid}", tags=["Portail Client"])
async def me_sms_schedule_cancel(sid: str, user: dict = Depends(get_current_user)):
    sched = await db.sms_schedules.find_one({"id": sid}, {"_id": 0})
    if not sched:
        raise HTTPException(status_code=404, detail="Planification introuvable")
    is_admin = user.get("role") in ("admin", "superviseur")
    if not is_admin and sched.get("client_id") != (user.get("client_id") or user["id"]):
        raise HTTPException(status_code=403, detail="Accès refusé")
    if sched.get("status") == "running":
        raise HTTPException(status_code=409, detail="Envoi déjà en cours")
    if sched.get("status") in ("done", "failed"):
        await db.sms_schedules.delete_one({"id": sid})
        return {"ok": True, "status": "deleted"}
    await db.sms_schedules.update_one({"id": sid}, {"$set": {"status": "cancelled", "updated_at": _now()}})
    return {"ok": True, "status": "cancelled"}


async def _run_scheduled_sms():
    """APScheduler tick (every minute) — drain pending SMS schedules."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        due = await db.sms_schedules.find(
            {"status": "pending", "scheduled_at": {"$lte": now_iso}}, {"_id": 0},
        ).to_list(50)
        for sc in due:
            claimed = await db.sms_schedules.update_one(
                {"id": sc["id"], "status": "pending"},
                {"$set": {"status": "running", "started_at": _now(), "updated_at": _now()}},
            )
            if claimed.modified_count == 0:
                continue
            cids = sc.get("contact_ids") or []
            contacts = await db.directory_contacts.find(
                {"id": {"$in": cids}, "client_id": sc["client_id"]}, {"_id": 0}
            ).to_list(len(cids))
            tpl = sc.get("message_template") or ""
            pay_slug = _extract_pay_slug(tpl)
            results = []
            skipped = []
            for c in contacts:
                target = c.get("phone") or c.get("whatsapp")
                if not target:
                    skipped.append({"label": c.get("name"), "reason": "Pas de numéro"})
                    continue
                ctx = _build_sms_ctx(c)
                body = _personalize_sms(tpl, ctx)
                try:
                    result = await _sms_dispatch(sc.get("provider") or "auto", target, body, sc.get("sender"))
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "status": "failed", "api_message": str(exc)[:200]}
                doc = {
                    "id": _uuid(), "client_id": sc["client_id"],
                    "user_id": sc.get("created_by_id"), "user_label": sc.get("created_by_label"),
                    "contact_id": c.get("id"),
                    "provider": result.get("provider"), "sender": sc.get("sender"),
                    "msisdn": target, "msisdn_digits": "".join(ch for ch in target if ch.isdigit()),
                    "message": body, "length": len(body),
                    "status": result.get("status"), "api_message": result.get("api_message"),
                    "http_status": result.get("http_status"), "raw_response": result.get("raw_response"),
                    "bulk": True, "scheduled": True, "schedule_id": sc["id"],
                    "payment_link_slug": pay_slug, "created_at": _now(),
                }
                try:
                    await db.sms_messages.insert_one(doc.copy())
                except Exception:  # noqa: BLE001
                    pass
                results.append({"label": c.get("name"), "phone": target, "ok": result.get("ok"),
                                "status": result.get("status"), "error": None if result.get("ok") else result.get("api_message")})
            sent_ok = sum(1 for r in results if r["ok"])
            final_status = "done" if (sent_ok > 0 or not results) else "failed"
            await db.sms_schedules.update_one(
                {"id": sc["id"]},
                {"$set": {"status": final_status, "result_summary": {
                    "requested": len(cids), "sent_ok": sent_ok, "sent_ko": len(results) - sent_ok,
                    "skipped_count": len(skipped), "skipped": skipped, "results": results,
                }, "finished_at": _now(), "updated_at": _now()}},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduled_sms runner failed: %s", exc)








# ---------- Portal WhatsApp scheduling (mirrors admin endpoints, scoped by client) ----------
class MeScheduleCreate(BaseModel):
    title: Optional[str] = None
    recipients: List[Dict[str, Any]]
    template_name: str
    language_code: Optional[str] = "fr"
    components: Optional[list] = None
    variables: Optional[List[str]] = None
    header_text: Optional[str] = None
    header_media: Optional[Dict[str, Any]] = None
    button_vars: Optional[List[List[str]]] = None
    scheduled_at: str  # ISO-8601 UTC


def _can_send_wa(user: dict) -> bool:
    if user.get("role") in ("admin", "client", "superviseur"):
        return True
    return _is_elevated_creator(user)


@api.get("/me/messaging/schedules", tags=["Portail Client"])
async def me_list_schedules(user: dict = Depends(get_current_user)):
    """List the user's WhatsApp scheduled sends. Admins see everything; portal users
    see schedules they created (created_by_id=user.id)."""
    if not _can_send_wa(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    query = {} if user.get("role") == "admin" else {"created_by_id": user["id"]}
    items = await db.whatsapp_schedules.find(query, {"_id": 0}).sort("scheduled_at", -1).to_list(500)
    return items


@api.post("/me/messaging/schedules", tags=["Portail Client"])
async def me_create_schedule(payload: MeScheduleCreate, user: dict = Depends(get_current_user)):
    if not _can_send_wa(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    if not payload.recipients:
        raise HTTPException(status_code=400, detail="Aucun destinataire")
    if not payload.template_name:
        raise HTTPException(status_code=400, detail="Template requis")
    try:
        sched = datetime.fromisoformat(payload.scheduled_at.replace("Z", "+00:00"))
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Date invalide (ISO-8601 attendu)")
    if sched <= datetime.now(timezone.utc) - timedelta(minutes=1):
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
        # Capture the user origin (used by /me/messaging/schedules to filter)
        "created_by_id": user["id"],
        "created_by_label": user.get("full_name") or user.get("email"),
        "created_by_role": user.get("role"),
        "client_id": user.get("client_id") or user.get("id"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.whatsapp_schedules.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


# ----- WhatsApp Bulk send (mirrors SMS bulk; supports per-contact personalization) -----
class MeWaBulkRequest(BaseModel):
    contact_ids: List[str]
    template_name: str
    language_code: Optional[str] = "fr"
    variables: Optional[List[str]] = None  # Body positional vars, may contain {{name}} tokens
    header_text: Optional[str] = None
    header_media: Optional[Dict[str, Any]] = None
    button_vars: Optional[List[List[str]]] = None
    scheduled_at: Optional[str] = None  # ISO-8601 — if set, schedule instead of live send
    title: Optional[str] = None  # Friendly label for the schedule row
    # SMS fallback: when WhatsApp delivery fails for a contact (no number, not on WA,
    # outside 24h window, Meta error…), automatically retry as SMS using
    # `sms_fallback_message` (which supports the same {{name}}/{{company}}/etc. tokens).
    sms_fallback: bool = False
    sms_fallback_message: Optional[str] = None
    sms_fallback_provider: Optional[str] = None  # "auto" / "orange" / "moov" / "telecel" / "ovh"
    sms_fallback_sender: Optional[str] = None


@api.post("/me/whatsapp/bulk", tags=["Portail Client"])
async def me_whatsapp_bulk(payload: MeWaBulkRequest, user: dict = Depends(get_current_user)):
    """Send a Meta-approved WhatsApp template to many CRM contacts at once,
    with per-contact variable personalization (`{{name}}`, `{{company}}`,
    `{{phone}}`, `{{email}}`, `{{client_code}}` = contact's unique_code, etc).
    Optional `scheduled_at` defers execution to the cron runner.
    Caps at 500 recipients per call (same as SMS bulk)."""
    if not _can_send_wa(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des messages WhatsApp")
    parent_id = user.get("client_id") or user["id"]
    # Feature gate: tracked/regular users must have whatsapp enabled by their parent client
    if user.get("role") not in ("admin", "superviseur"):
        parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("whatsapp"):
            raise HTTPException(status_code=403, detail="WhatsApp non autorisé pour votre compte")
    if not (payload.template_name or "").strip():
        raise HTTPException(status_code=400, detail="Template requis")
    if not payload.contact_ids:
        raise HTTPException(status_code=400, detail="Aucun destinataire sélectionné")
    if len(payload.contact_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 destinataires par envoi")

    # Iter35h — demo: each recipient counts as one send (pre-resolve check).
    await _enforce_demo_quota(user, QUOTA_KEY_WA, increment=len(payload.contact_ids))

    # Iter35f — widen lookup to every visible client_id (so contacts that
    # were retagged to a peer/legacy client_id remain reachable). Before
    # this fix, a strict {client_id: parent_id} filter returned 0 contacts
    # after an admin retag → bulk send silently reported "0 message envoyé".
    visible_scope = await _resolve_visible_client_ids(user)
    contacts = await db.directory_contacts.find(
        {"id": {"$in": payload.contact_ids}, "client_id": {"$in": visible_scope}},
        {"_id": 0},
    ).to_list(len(payload.contact_ids))

    # Iter35f — fail fast with a clear error when NO contact resolves
    # (was silently returning sent_ok=0 → frontend toast "0 message envoyé"
    # which looked like a delivery problem rather than a scope mismatch).
    if not contacts:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Aucun contact retrouvé parmi les {len(payload.contact_ids)} ID(s) sélectionné(s). "
                "Vos contacts ont peut-être été réassignés à un autre client — actualisez la liste."
            ),
        )

    # Schedule-for-later branch: persist recipients and let the cron pick it up.
    if payload.scheduled_at:
        try:
            sched_dt = datetime.fromisoformat(str(payload.scheduled_at).replace("Z", "+00:00"))
            if sched_dt.tzinfo is None:
                sched_dt = sched_dt.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=400, detail="Date de planification invalide (ISO-8601 attendu)")
        if sched_dt < datetime.now(timezone.utc) + timedelta(seconds=30):
            raise HTTPException(status_code=400, detail="La date de planification doit être au moins +30 secondes")
        recipients = []
        for c in contacts:
            phone = (c.get("whatsapp") or c.get("phone") or "").strip()
            recipients.append({
                "kind": "contact",
                "id": c.get("id"),
                "phone": phone,
                "label": c.get("name") or c.get("company") or phone,
            })
        sched_doc = {
            "id": _uuid(),
            "title": (payload.title or "").strip() or f"WA bulk {payload.template_name}",
            "recipients": recipients,
            "template_name": payload.template_name,
            "language_code": payload.language_code or "fr",
            "components": None,
            "variables": payload.variables,
            "header_text": payload.header_text,
            "header_media": payload.header_media,
            "button_vars": payload.button_vars,
            "scheduled_at": sched_dt.astimezone(timezone.utc).isoformat(),
            "status": "pending",
            "result_summary": None,
            "created_by_id": user["id"],
            "created_by_label": user.get("full_name") or user.get("email"),
            "created_by_role": user.get("role"),
            "client_id": parent_id,
            "bulk": True,
            # SMS fallback config (cron runner will apply per-recipient on failure)
            "sms_fallback": bool(payload.sms_fallback),
            "sms_fallback_message": payload.sms_fallback_message,
            "sms_fallback_provider": payload.sms_fallback_provider,
            "sms_fallback_sender": payload.sms_fallback_sender,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.whatsapp_schedules.insert_one(sched_doc.copy())
        sched_doc.pop("_id", None)
        return {
            "ok": True,
            "scheduled": True,
            "id": sched_doc["id"],
            "scheduled_at": sched_doc["scheduled_at"],
            "recipients": len(recipients),
        }

    # Live-send branch: iterate contacts, build per-contact ctx, send template now.
    results = []
    skipped = []
    fallback_results = []  # SMS fallback attempts (when sms_fallback=True)
    for c in contacts:
        phone = (c.get("whatsapp") or c.get("phone") or "").strip()
        label = c.get("name") or c.get("company") or phone or "—"
        if not phone:
            skipped.append({"label": label, "reason": "Pas de numéro WhatsApp"})
            continue
        # Re-use _build_recipient_ctx with a contact-shaped doc so {{name}},
        # {{company}}, {{client_code}} (= unique_code) etc. resolve naturally.
        user_doc = {
            "full_name": c.get("name"),
            "company": c.get("company"),
            "email": c.get("email"),
            "phone": c.get("phone") or c.get("whatsapp"),
            "client_code": c.get("unique_code"),
        }
        ctx = _build_recipient_ctx("contact", user_doc, phone, label)
        components = _build_components(
            payload.variables, ctx,
            header_text=payload.header_text,
            header_media=payload.header_media,
            button_vars=payload.button_vars,
        )
        try:
            wr = await _wa_send_template(
                phone, payload.template_name, payload.language_code or "fr", components,
            )
        except Exception as exc:  # noqa: BLE001
            wr = {"ok": False, "status": 0, "message_id": None, "error": str(exc)[:200]}
        # Capture any /pay/{slug} URL embedded for analytics attribution
        pay_slug = None
        try:
            pay_slug = _extract_pay_slug(json.dumps((payload.variables or []) + [(payload.header_text or "")], ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
        log = {
            "id": _uuid(),
            "client_id": parent_id,
            "direction": "outbound",
            "sender_id": user["id"],
            "sender_label": user.get("full_name") or user.get("email"),
            "to": phone,
            "phone_digits": "".join(ch for ch in phone if ch.isdigit()),
            "template_name": payload.template_name,
            "language_code": payload.language_code or "fr",
            "contact_id": c.get("id"),
            "recipient_kind": "contact",
            "recipient_label": label,
            "bulk": True,
            "ok": wr["ok"],
            "status": wr["status"],
            "message_id": wr["message_id"],
            "error": wr.get("error"),
            "wa_status": "sent" if wr["ok"] else "failed",
            "sent_at": _now() if wr["ok"] else None,
            "failed_at": None if wr["ok"] else _now(),
            "payment_link_slug": pay_slug,
            "created_at": _now(),
        }
        try:
            await db.whatsapp_messages.insert_one(log.copy())
        except Exception:  # noqa: BLE001
            pass
        results.append({
            "label": label, "phone": phone, "ok": wr["ok"],
            "status": wr["status"], "message_id": wr["message_id"],
            "error": None if wr["ok"] else (wr.get("error") or "Échec"),
        })
        # ---- SMS fallback on failure ----
        if not wr["ok"] and payload.sms_fallback and (payload.sms_fallback_message or "").strip():
            sms_target = (c.get("phone") or c.get("whatsapp") or "").strip()
            if sms_target:
                try:
                    sms_ctx = _build_sms_ctx(c)
                    sms_body = _personalize_sms(payload.sms_fallback_message, sms_ctx)
                    sms_res = await _sms_dispatch(
                        payload.sms_fallback_provider or "auto",
                        sms_target, sms_body, payload.sms_fallback_sender,
                    )
                    sms_doc = {
                        "id": _uuid(), "client_id": parent_id, "user_id": user["id"],
                        "user_email": user.get("email"),
                        "user_label": user.get("full_name") or user.get("email"),
                        "contact_id": c.get("id"),
                        "provider": sms_res.get("provider"),
                        "sender": payload.sms_fallback_sender,
                        "msisdn": sms_target,
                        "msisdn_digits": "".join(ch for ch in sms_target if ch.isdigit()),
                        "message": sms_body, "length": len(sms_body),
                        "status": sms_res.get("status"),
                        "api_message": sms_res.get("api_message"),
                        "http_status": sms_res.get("http_status"),
                        "raw_response": sms_res.get("raw_response"),
                        "bulk": True,
                        "wa_fallback": True,  # marks this row as the SMS fallback of a WA failure
                        "payment_link_slug": _extract_pay_slug(payload.sms_fallback_message),
                        "created_at": _now(),
                    }
                    await db.sms_messages.insert_one(sms_doc.copy())
                    fallback_results.append({
                        "label": label, "phone": sms_target,
                        "ok": bool(sms_res.get("ok")),
                        "status": sms_res.get("status"),
                        "error": None if sms_res.get("ok") else (sms_res.get("api_message") or "Échec SMS"),
                    })
                except Exception as exc:  # noqa: BLE001
                    fallback_results.append({"label": label, "phone": sms_target, "ok": False, "status": "failed", "error": str(exc)[:200]})
            else:
                fallback_results.append({"label": label, "phone": "", "ok": False, "status": "no_phone", "error": "Pas de numéro de téléphone pour le repli SMS"})
    return {
        "ok": True,
        "scheduled": False,
        "sent_ok": sum(1 for r in results if r["ok"]),
        "sent_ko": sum(1 for r in results if not r["ok"]),
        "skipped": skipped,
        "results": results,
        "fallback_used": bool(payload.sms_fallback),
        "fallback_results": fallback_results,
        "fallback_ok": sum(1 for r in fallback_results if r["ok"]),
    }


@api.delete("/me/messaging/schedules/{sid}", tags=["Portail Client"])
async def me_delete_schedule(sid: str, user: dict = Depends(get_current_user)):
    if not _can_send_wa(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    existing = await db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Planification introuvable")
    # Portal users can only cancel their own schedules
    if user.get("role") != "admin" and existing.get("created_by_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Suppression non autorisée")
    if existing.get("status") in ("running", "done"):
        await db.whatsapp_schedules.update_one(
            {"id": sid},
            {"$set": {"status": "cancelled", "updated_at": _now()}},
        )
        return {"ok": True, "status": "cancelled"}
    await db.whatsapp_schedules.delete_one({"id": sid})
    return {"ok": True, "status": "deleted"}


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
    (sent/delivered/read/failed) with timestamps.

    Iter34p — Uses _resolve_visible_client_ids so the contact stays
    accessible after a realignment/migration even if its client_id matches
    a peer/legacy value rather than the viewer's own client_id."""
    visible_scope = await _resolve_visible_client_ids(user)
    contact = await db.directory_contacts.find_one(
        {"id": cid, "client_id": {"$in": visible_scope}}, {"_id": 0},
    )
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
        {"client_id": {"$in": visible_scope}, "$or": or_clauses},
        {"_id": 0},
    ).sort("created_at", 1).to_list(1000)
    # Iter34u — When anon_communications is ON, restrict to messages
    # exchanged by the current user only (sender_id or owner_id match).
    restrictions = await _resolve_content_restrictions(user)
    if restrictions.get("anon_communications"):
        items = [m for m in items if (m.get("sender_id") == user["id"] or m.get("owner_id") == user["id"])]
    # Compute the 24h Meta customer service window from the latest inbound
    last_inbound_at: Optional[str] = None
    for m in reversed(items):
        if m.get("direction") == "inbound":
            last_inbound_at = m.get("received_at") or m.get("created_at")
            break
    can_send_text = _wa_window_open(last_inbound_at)
    window_expires_at: Optional[str] = None
    if last_inbound_at:
        try:
            ts = datetime.fromisoformat(last_inbound_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            window_expires_at = (ts + timedelta(seconds=WA_24H_WINDOW_SECONDS)).isoformat()
        except Exception:
            window_expires_at = None
    return {
        "contact": contact,
        "messages": items,
        "can_send_text": can_send_text,
        "last_inbound_at": last_inbound_at,
        "window_expires_at": window_expires_at,
    }


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
    Shape: {object:'whatsapp_business_account', entry:[{changes:[{value:{...}}]}]}

    Hardened (iter35a): every webhook hit is persisted to
    `db.wa_webhook_logs` (capped to ~200 entries) with the raw payload + an
    extraction summary so production issues can be diagnosed without server
    access. Lookup via GET /api/admin/whatsapp/webhook-logs.
    """
    raw_bytes = b""
    try:
        raw_bytes = await request.body()
    except Exception:  # noqa: BLE001
        pass

    body: Dict[str, Any] = {}
    parse_error = None
    try:
        body = json.loads(raw_bytes.decode("utf-8")) if raw_bytes else {}
    except Exception as exc:  # noqa: BLE001
        parse_error = str(exc)[:200]

    # ------------------------------------------------------------------
    # Persist a debug log entry (best-effort, never blocks Meta).
    # We keep only the last ~200 entries via a periodic prune.
    # ------------------------------------------------------------------
    extracted_messages = 0
    extracted_statuses = 0
    inserted_messages = 0
    errors: List[str] = []

    client_scope = None  # our app uses per-install WABA, so scope = primary client/superviseur
    try:
        primary = await db.users.find_one({"role": "superviseur"}, {"_id": 0, "id": 1})
        client_scope = (primary or {}).get("id")
    except Exception:
        pass

    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            val = change.get("value") or {}
            # Build a wa_id → profile.name map from the contacts array (Meta
            # always includes it alongside inbound messages). Used to:
            #  1. fill `from_profile_name` on inbound messages
            #  2. suggest a name when an unknown contact writes for the first time
            profile_by_wa: Dict[str, Optional[str]] = {}
            for c in val.get("contacts") or []:
                wa_id = c.get("wa_id") or ""
                pname = ((c.get("profile") or {}).get("name") or "").strip() or None
                if wa_id:
                    profile_by_wa[wa_id] = pname
            # --- Inbound messages ---
            for msg in val.get("messages") or []:
                extracted_messages += 1
                try:
                    from_num = msg.get("from") or ""
                    digits_only = "".join(ch for ch in from_num if ch.isdigit())
                    profile_name = profile_by_wa.get(from_num) or profile_by_wa.get(digits_only)
                    mtype = msg.get("type") or "text"
                    text_body = None
                    media_info: Optional[Dict[str, Any]] = None  # populated when we download a binary
                    media_caption: Optional[str] = None
                    if mtype == "text":
                        text_body = (msg.get("text") or {}).get("body")
                    elif mtype in ("image", "document", "audio", "video", "sticker"):
                        # Iter35l — Try to download the binary from Meta Graph
                        # (URL expires ~5min) and persist it locally so the chat
                        # UI can render the actual media (image/audio/PDF/etc.).
                        media_obj = msg.get(mtype) or {}
                        media_caption = (media_obj.get("caption") or "").strip() or None
                        media_id_in = media_obj.get("id")
                        if media_id_in:
                            try:
                                dl = await _wa_download_inbound_media(media_id_in)
                            except Exception as exc:  # noqa: BLE001
                                dl = {"ok": False, "error": f"download crash: {exc!r}"}
                            if dl.get("ok"):
                                media_info = dl
                                text_body = media_caption or f"[{mtype} reçu]"
                            else:
                                text_body = f"[{mtype} reçu — téléchargement échoué: {dl.get('error') or 'inconnu'}]"
                        else:
                            text_body = f"[{mtype} reçu]"
                    elif mtype == "button":
                        # Quick-reply button on a template — `button.text` is
                        # the visible label, `button.payload` the data.
                        btn = msg.get("button") or {}
                        text_body = btn.get("text") or btn.get("payload")
                    elif mtype == "interactive":
                        interactive = msg.get("interactive") or {}
                        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                        text_body = reply.get("title") or reply.get("id")
                    elif mtype == "reaction":
                        text_body = f"[réaction {((msg.get('reaction') or {}).get('emoji') or '')}]"
                    elif mtype == "location":
                        loc = msg.get("location") or {}
                        text_body = f"[position {loc.get('latitude')},{loc.get('longitude')}]"
                    elif mtype == "contacts":
                        text_body = "[carte de contact reçue]"
                    else:
                        text_body = f"[{mtype} non géré]"
                    ts_raw = int(msg.get("timestamp") or 0)
                    ts_iso = datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat() if ts_raw else _now()
                    # Find contact by phone within the scope
                    contact = await db.directory_contacts.find_one(
                        {"$or": [{"whatsapp": {"$regex": digits_only}}, {"phone": {"$regex": digits_only}}]},
                        {"_id": 0, "id": 1, "client_id": 1, "name": 1, "wa_profile_name": 1},
                    ) if digits_only else None
                    scope_for_msg = (contact or {}).get("client_id") or client_scope
                    doc = {
                        "id": _uuid(),
                        "client_id": scope_for_msg,
                        "direction": "inbound",
                        "contact_id": (contact or {}).get("id"),
                        "contact_name": (contact or {}).get("name"),
                        "from": from_num,
                        "from_profile_name": profile_name,
                        "phone_digits": digits_only,
                        "body": text_body,
                        "message_type": mtype,
                        "wa_message_id": msg.get("id"),
                        "received_at": ts_iso,
                        "created_at": _now(),
                        "read_by_us_at": None,
                    }
                    if media_info:
                        doc["media_id"] = media_info.get("file_id")
                        doc["media_wa_id"] = (msg.get(mtype) or {}).get("id")
                        doc["media_url"] = media_info.get("public_url")
                        doc["media_mime_type"] = media_info.get("mime_type")
                        doc["media_filename"] = media_info.get("filename")
                        doc["media_size_bytes"] = media_info.get("size_bytes")
                        doc["media_kind"] = media_info.get("kind")
                        if media_caption:
                            doc["media_caption"] = media_caption
                        # Iter35l — auto-transcribe voice notes when toggle ON
                        if media_info.get("kind") == "audio":
                            try:
                                s_root = await db.settings.find_one({"_id": "global"}) or {}
                                if bool(s_root.get("wa_voice_transcribe_enabled", True)):
                                    stored = UPLOAD_DIR / media_info["stored_name"]
                                    transcript = await _wa_transcribe_audio_file(stored, language="fr")
                                    if transcript:
                                        doc["voice_note_transcript"] = transcript
                                        # Prepend a hint so the bubble's primary text shows the transcript
                                        doc["body"] = transcript if not media_caption else f"{media_caption}\n— {transcript}"
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("WA voice transcribe failed: %s", exc)
                    await db.whatsapp_messages.insert_one(doc)
                    inserted_messages += 1
                    # Iter34x — activity log for inbound WA
                    await _log_activity(
                        client_id=scope_for_msg,
                        kind="whatsapp",
                        action="received",
                        label=f"← {profile_name or (contact or {}).get('name') or from_num}",
                        actor={"id": "_system_", "full_name": "WhatsApp webhook"},
                        target_id=doc.get("id"),
                    )
                    # Persist the latest profile name on the contact (or create a
                    # "wa_unmapped" record so the admin can review and import it).
                    if profile_name:
                        if contact:
                            # Auto-fill the contact's main `name` field if it is
                            # empty OR still equal to the bare phone number (a
                            # common state for contacts created from inbound WA
                            # before any human review). We only overwrite blank-
                            # ish names — never a real, user-entered name.
                            existing_name = (contact.get("name") or "").strip()
                            phone_only = bool(re.fullmatch(r"\+?\d[\d\s().-]*", existing_name)) if existing_name else False
                            patch = {
                                "wa_profile_name": profile_name,
                                "wa_profile_synced_at": _now(),
                            }
                            if not existing_name or phone_only:
                                patch["name"] = profile_name
                                patch["updated_at"] = _now()
                            await db.directory_contacts.update_one(
                                {"id": contact["id"]},
                                {"$set": patch},
                            )
                        else:
                            # Unknown sender — upsert a `wa_pending_imports` record
                            # so the admin can decide to create a contact or ignore.
                            await db.wa_pending_imports.update_one(
                                {"phone_digits": digits_only, "client_id": client_scope},
                                {
                                    "$setOnInsert": {
                                        "id": _uuid(),
                                        "phone_digits": digits_only,
                                        "from": from_num,
                                        "client_id": client_scope,
                                        "first_seen_at": _now(),
                                    },
                                    "$set": {
                                        "wa_profile_name": profile_name,
                                        "last_seen_at": _now(),
                                        "last_message": (text_body or "")[:200],
                                    },
                                    "$inc": {"messages_count": 1},
                                },
                                upsert=True,
                            )
                    # Liluvine remote command? (only on plain text messages)
                    if mtype == "text" and text_body and (text_body.strip().startswith("!") or text_body.strip().startswith("/")):
                        try:
                            await _try_handle_liluvine_wa_command(from_num, text_body)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("liluvine cmd parse failed: %s", exc)
                except Exception as exc:  # noqa: BLE001
                    err = f"inbound[{mtype if 'mtype' in locals() else '?'}]: {exc!r}"
                    errors.append(err[:250])
                    logger.warning("WA inbound parse failed: %s", exc)
            # --- Status updates for outbound ---
            for st in val.get("statuses") or []:
                extracted_statuses += 1
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
                    # Match by both possible keys (legacy schema used `message_id`,
                    # new inbound schema uses `wa_message_id`). Try both.
                    res = await db.whatsapp_messages.update_one(
                        {"$or": [{"message_id": mid}, {"wa_message_id": mid}]},
                        {"$set": update},
                    )
                    if res.matched_count == 0:
                        # Stash so the matching outbound row can self-heal later
                        await db.wa_pending_statuses.update_one(
                            {"message_id": mid},
                            {"$set": {**update, "message_id": mid, "received_at": _now()}},
                            upsert=True,
                        )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"status: {exc!r}"[:250])
                    logger.warning("WA status parse failed: %s", exc)

    # Persist the debug log entry (best-effort)
    try:
        log_entry = {
            "id": _uuid(),
            "received_at": _now(),
            "client_ip": (request.client.host if request.client else None),
            "headers": {k: v for k, v in request.headers.items() if k.lower() in (
                "user-agent", "x-hub-signature", "x-hub-signature-256", "content-type", "x-forwarded-for",
            )},
            "raw_bytes_len": len(raw_bytes),
            "parse_error": parse_error,
            "object": body.get("object"),
            "entry_count": len(body.get("entry") or []),
            "extracted_messages": extracted_messages,
            "extracted_statuses": extracted_statuses,
            "inserted_messages": inserted_messages,
            "errors": errors[:10],
            "body": body if len(raw_bytes) < 30000 else {"_truncated": True, "preview": (raw_bytes[:2000].decode("utf-8", errors="replace") if raw_bytes else "")},
        }
        await db.wa_webhook_logs.insert_one(log_entry)
        # Cap retention at 200 entries (delete oldest beyond)
        total = await db.wa_webhook_logs.count_documents({})
        if total > 220:
            cutoff = await db.wa_webhook_logs.find(
                {}, {"_id": 0, "received_at": 1}
            ).sort("received_at", -1).skip(200).limit(1).to_list(1)
            if cutoff:
                await db.wa_webhook_logs.delete_many({"received_at": {"$lt": cutoff[0]["received_at"]}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("wa_webhook_logs persist failed: %s", exc)

    return {"ok": True}


@api.get("/admin/whatsapp/webhook-logs", tags=["Admin"])
async def admin_list_wa_webhook_logs(
    limit: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(get_current_admin),
):
    """Iter35a — Read the last `limit` raw webhook payloads received from
    Meta. Useful when inbound messages stop appearing in the UI: lets the
    admin verify Meta is actually hitting the endpoint and inspect the
    exact payload shape (button vs interactive vs text)."""
    items = await db.wa_webhook_logs.find({}, {"_id": 0}).sort("received_at", -1).to_list(limit)
    return {"items": items, "count": len(items)}


@api.delete("/admin/whatsapp/webhook-logs", tags=["Admin"])
async def admin_clear_wa_webhook_logs(_: dict = Depends(get_current_admin)):
    """Purge all stored webhook payloads."""
    res = await db.wa_webhook_logs.delete_many({})
    return {"ok": True, "deleted": res.deleted_count}


# ============================================================
# Iter35b — WhatsApp inbound silence detector.
#
# Why: when Meta stops calling our webhook (token mismatch, ad-account
# review, regional outage, …) the symptom is invisible to the user — they
# see their outbound bulk sends succeed but never get the replies. The
# CRM looks empty even though customers ARE replying.
#
# How: every 4 hours we count outbound WA messages sent in the trailing
# `window_hours` (default 24) and webhook hits received in the same
# window. If outbound >= `threshold` AND inbound == 0, we fire an alert
# (email + optional Discord) and stamp `wa_silence_alert_last_fired_at`
# to avoid spamming. The check is also exposed as a manual admin endpoint.
# ============================================================
async def _run_wa_silence_check(triggered_by: str = "cron") -> dict:
    s = await db.settings.find_one({"_id": "global"}) or {}
    enabled = bool(s.get("wa_silence_alert_enabled"))
    threshold = int(s.get("wa_silence_alert_threshold") or 3)
    window_hours = max(1, min(int(s.get("wa_silence_alert_window_hours") or 24), 168))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    cutoff_iso = cutoff.isoformat()

    # Count outbound WA messages sent in the window (direction != inbound).
    # The schema mixes legacy {to, template_name} rows and new {direction: 'outbound'}
    # rows, so we count any message that isn't explicitly marked inbound.
    outbound_n = await db.whatsapp_messages.count_documents({
        "$and": [
            {"created_at": {"$gte": cutoff_iso}},
            {"direction": {"$ne": "inbound"}},
        ],
    })
    inbound_webhook_n = await db.wa_webhook_logs.count_documents({
        "received_at": {"$gte": cutoff_iso},
    })
    # Optional: also count inbound messages persisted (catches the case where
    # webhook IS firing but logs got purged).
    inbound_msg_n = await db.whatsapp_messages.count_documents({
        "$and": [
            {"created_at": {"$gte": cutoff_iso}},
            {"direction": "inbound"},
        ],
    })

    silent = (outbound_n >= threshold) and (inbound_webhook_n == 0) and (inbound_msg_n == 0)

    result = {
        "ok": True,
        "enabled": enabled,
        "window_hours": window_hours,
        "threshold": threshold,
        "outbound_count": outbound_n,
        "inbound_webhook_count": inbound_webhook_n,
        "inbound_message_count": inbound_msg_n,
        "silent": silent,
        "fired": False,
        "triggered_by": triggered_by,
        "checked_at": _now(),
    }

    if not (enabled and silent):
        return result

    # Throttle — only fire once per window_hours
    last_fired = s.get("wa_silence_alert_last_fired_at")
    if last_fired:
        try:
            last_dt = datetime.fromisoformat(last_fired.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < window_hours * 3600:
                result["fired"] = False
                result["throttled_until"] = (last_dt + timedelta(hours=window_hours)).isoformat()
                return result
        except Exception:  # noqa: BLE001
            pass

    # ----- Fire the alert -----
    recipient = (s.get("wa_silence_alert_email_to") or s.get("health_email_to") or SUPER_ADMIN_EMAIL).strip().lower()
    discord_url = (s.get("wa_silence_alert_discord_webhook") or "").strip()

    subject = f"[SAWALI ALERT] WhatsApp silence ({window_hours}h)"
    html = (
        f"<div style='font-family:Arial,sans-serif;'>"
        f"<h3 style='color:#EF4444'>🚨 Aucun webhook WhatsApp reçu depuis {window_hours} h</h3>"
        f"<p>Votre instance a envoyé <b>{outbound_n}</b> message(s) WhatsApp ces dernières <b>{window_hours}</b> heures, "
        f"mais Meta n'a appelé votre webhook <code>/api/whatsapp/webhook</code> <b>0 fois</b>.</p>"
        f"<p>Symptômes probables :</p>"
        f"<ul>"
        f"<li>Verify Token modifié côté Meta sans mise à jour ici (ou vice-versa)</li>"
        f"<li>URL du webhook expirée / fermée côté Meta Business Suite</li>"
        f"<li>Numéro de téléphone WABA temporairement suspendu</li>"
        f"<li>Incident régional côté Meta (vérifier <a href='https://metastatus.com/'>metastatus.com</a>)</li>"
        f"</ul>"
        f"<p><b>Action recommandée :</b> ouvrez <a href='https://business.facebook.com/wa/manage/home/'>Meta Business Suite → WhatsApp → Configuration</a> "
        f"et cliquez « Tester » sur la ligne du webhook. Puis ouvrez votre panneau d'admin → Paramètres → "
        f"« Inspecter les payloads Meta entrants » pour confirmer.</p>"
        f"<hr/><p style='color:#64748B;font-size:12px;'>Détection automatique — {result['checked_at']}.</p>"
        f"</div>"
    )
    text = (
        f"WA SILENCE — {outbound_n} outbound, 0 inbound on the last {window_hours}h.\n"
        f"Check Meta Business Suite → WhatsApp → Configuration."
    )

    sent_email = False
    try:
        from email_service import send_email
        sent_email = bool(await send_email(recipient, subject, html, text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("WA silence alert email failed: %s", exc)

    sent_discord = False
    if discord_url and discord_url.startswith("http"):
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                disc_payload = {
                    "content": (
                        f"🚨 **WhatsApp silence** — {outbound_n} message(s) envoyé(s) en {window_hours} h, "
                        f"0 webhook reçu. Vérifiez Meta Business Suite → WhatsApp → Configuration."
                    ),
                }
                r = await http.post(discord_url, json=disc_payload)
                sent_discord = r.status_code < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("WA silence discord alert failed: %s", exc)

    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"wa_silence_alert_last_fired_at": _now(), "updated_at": _now()}},
        upsert=True,
    )
    # Audit trail
    try:
        await db.wa_silence_alerts.insert_one({
            "id": _uuid(),
            "fired_at": _now(),
            "window_hours": window_hours,
            "outbound_count": outbound_n,
            "inbound_webhook_count": inbound_webhook_n,
            "inbound_message_count": inbound_msg_n,
            "email_to": recipient if sent_email else None,
            "email_sent": sent_email,
            "discord_sent": sent_discord,
            "triggered_by": triggered_by,
        })
    except Exception:  # noqa: BLE001
        pass

    result.update({"fired": True, "email_sent": sent_email, "discord_sent": sent_discord, "email_to": recipient})
    return result


@api.post("/admin/whatsapp/silence-check", tags=["Admin"])
async def admin_run_wa_silence_check(_: dict = Depends(get_current_admin)):
    """Manually run the WhatsApp silence detector (also runs every 4h via cron).
    Returns the counts and whether an alert was fired. Useful for testing
    your email/Discord webhook configuration."""
    return await _run_wa_silence_check(triggered_by="manual")


@api.get("/admin/whatsapp/silence-alerts", tags=["Admin"])
async def admin_list_wa_silence_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(get_current_admin),
):
    """List past silence alerts (audit trail)."""
    items = await db.wa_silence_alerts.find({}, {"_id": 0}).sort("fired_at", -1).to_list(limit)
    return {"items": items, "count": len(items)}





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
         "phone": 1, "whatsapp_number": 1, "account_status": 1, "client_code": 1, "country": 1, "city": 1},
    ).to_list(3000)
    tracked = await db.tracked_users.find(
        {}, {"_id": 0, "id": 1, "name": 1, "full_name": 1, "email": 1, "phone": 1, "whatsapp_number": 1,
             "client_id": 1, "role": 1, "status": 1},
    ).to_list(5000)
    # Build client lookup for tracked-users labels
    client_map = {u["id"]: (u.get("company") or u.get("full_name") or u.get("email")) for u in users}

    clients_rows = []
    for u in users:
        # Prefer the dedicated WhatsApp number; fall back to the regular phone field
        wa = (u.get("whatsapp_number") or "").strip()
        phone_only = (u.get("phone") or "").strip()
        phone = wa or phone_only
        clients_rows.append({
            "kind": "client",
            "id": u["id"],
            "full_name": u.get("full_name") or "—",
            "email": u.get("email"),
            "company": u.get("company") or "",
            "phone": phone,
            "whatsapp_number": wa or None,
            "client_code": u.get("client_code"),
            "country": u.get("country"),
            "city": u.get("city"),
            "account_status": u.get("account_status"),
            "has_phone": bool(phone),
        })

    tracked_rows = []
    for t in tracked:
        wa = (t.get("whatsapp_number") or "").strip()
        phone_only = (t.get("phone") or "").strip()
        phone = wa or phone_only
        tracked_rows.append({
            "kind": "tracked",
            "id": t["id"],
            "full_name": t.get("full_name") or t.get("name") or "—",
            "email": t.get("email"),
            "client_id": t.get("client_id"),
            "client_label": client_map.get(t.get("client_id") or "") or "—",
            "phone": phone,
            "whatsapp_number": wa or None,
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
            u = await db.users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "full_name": 1, "email": 1, "company": 1, "client_code": 1})
            if u:
                user_doc = u
                if not phone:
                    # Prefer the dedicated WhatsApp number, fall back to the regular phone field
                    phone = (u.get("whatsapp_number") or u.get("phone") or "").strip()
                label = label or u.get("company") or u.get("full_name") or u.get("email")
        elif kind == "tracked" and rid:
            t = await db.tracked_users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "name": 1, "full_name": 1, "email": 1, "client_id": 1})
            if t:
                user_doc = t
                if not phone:
                    phone = (t.get("whatsapp_number") or t.get("phone") or "").strip()
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
    # Collect a compact list of distinct error messages so the frontend can show why
    # an envoi failed (e.g. "(#100) Param 'to' invalid" → user fixes the number once).
    error_summary = []
    seen_err = set()
    for r in results:
        if not r["ok"] and r.get("error"):
            e = str(r["error"])[:240]
            if e not in seen_err:
                seen_err.add(e)
                error_summary.append(e)
            if len(error_summary) >= 3:
                break
    return {
        "requested": len(payload.recipients),
        "sent_ok": sent_ok,
        "sent_ko": len(results) - sent_ok,
        "skipped": [{"label": s["label"], "reason": "Pas de numéro de téléphone"} for s in skipped],
        "results": results,
        "error_summary": error_summary,
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
    """Cron job (runs every minute) — execute any pending schedule whose scheduled_at <= now.

    Iter35a hardening: per-schedule try/except so one failing schedule doesn't
    leave others stuck in `running`. The final status update also captures
    a top-level `error` string in result_summary on hard failure.
    """
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
                    u = await db.users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "full_name": 1, "company": 1, "email": 1, "client_code": 1})
                    if u:
                        user_doc = u
                        if not phone:
                            phone = (u.get("whatsapp_number") or u.get("phone") or "").strip()
                        label = label or u.get("company") or u.get("full_name") or u.get("email")
                elif kind == "tracked" and rid:
                    t = await db.tracked_users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "name": 1, "full_name": 1, "email": 1})
                    if t:
                        user_doc = t
                        if not phone:
                            phone = (t.get("whatsapp_number") or t.get("phone") or "").strip()
                        label = label or t.get("full_name") or t.get("name") or t.get("email")
                elif kind == "contact" and rid:
                    # Directory contact (CRM). Pull name/company/email/whatsapp/phone.
                    c = await db.directory_contacts.find_one(
                        {"id": rid},
                        {"_id": 0, "name": 1, "company": 1, "email": 1, "phone": 1, "whatsapp": 1, "unique_code": 1},
                    )
                    if c:
                        user_doc = {
                            "full_name": c.get("name"),
                            "company": c.get("company"),
                            "email": c.get("email"),
                            "phone": c.get("phone") or c.get("whatsapp"),
                            "client_code": c.get("unique_code"),
                        }
                        if not phone:
                            phone = (c.get("whatsapp") or c.get("phone") or "").strip()
                        label = label or c.get("name") or c.get("company") or c.get("email")
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
                    "client_id": rid if kind == "client" else (sc.get("client_id") if kind == "contact" else None),
                    "sender_id": sc.get("created_by_id"),
                    "sender_label": sc.get("created_by_label"),
                    "to": phone,
                    "template_name": sc["template_name"],
                    "language_code": sc.get("language_code"),
                    "tracked_user_id": rid if kind == "tracked" else None,
                    "contact_id": rid if kind == "contact" else None,
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
                # ---- SMS fallback for scheduled bulk on WA failure (kind="contact" only)
                fallback_status = None
                if (
                    not wr["ok"] and sc.get("sms_fallback") and kind == "contact"
                    and (sc.get("sms_fallback_message") or "").strip() and user_doc
                ):
                    sms_target = (user_doc.get("phone") or phone or "").strip()
                    if sms_target:
                        try:
                            # Reconstruct a contact-like dict for _build_sms_ctx
                            sms_ctx = _build_sms_ctx({
                                "name": user_doc.get("full_name"),
                                "company": user_doc.get("company"),
                                "phone": user_doc.get("phone"),
                                "whatsapp": phone,
                                "email": user_doc.get("email"),
                                "tags": [],
                                "unique_code": user_doc.get("client_code"),
                            })
                            sms_body = _personalize_sms(sc.get("sms_fallback_message") or "", sms_ctx)
                            sms_res = await _sms_dispatch(
                                sc.get("sms_fallback_provider") or "auto",
                                sms_target, sms_body, sc.get("sms_fallback_sender"),
                            )
                            sms_doc = {
                                "id": _uuid(),
                                "client_id": sc.get("client_id"),
                                "user_id": sc.get("created_by_id"),
                                "user_email": None,
                                "user_label": sc.get("created_by_label"),
                                "contact_id": rid,
                                "provider": sms_res.get("provider"),
                                "sender": sc.get("sms_fallback_sender"),
                                "msisdn": sms_target,
                                "msisdn_digits": "".join(ch for ch in sms_target if ch.isdigit()),
                                "message": sms_body, "length": len(sms_body),
                                "status": sms_res.get("status"),
                                "api_message": sms_res.get("api_message"),
                                "http_status": sms_res.get("http_status"),
                                "raw_response": sms_res.get("raw_response"),
                                "bulk": True,
                                "wa_fallback": True,
                                "schedule_id": sc["id"],
                                "created_at": _now(),
                            }
                            await db.sms_messages.insert_one(sms_doc.copy())
                            fallback_status = "ok" if sms_res.get("ok") else "failed"
                        except Exception as exc:  # noqa: BLE001
                            fallback_status = f"err:{str(exc)[:80]}"
                results.append({
                    "label": label, "phone": phone, "kind": kind,
                    "ok": wr["ok"], "status": wr["status"],
                    "message_id": wr["message_id"], "error": wr.get("error"),
                    "fallback": fallback_status,
                })
            sent_ok = sum(1 for x in results if x["ok"])
            final_status = "done" if sent_ok > 0 or not results else "failed"
            # Iter35a — surface a human-readable reason when the whole batch failed
            # so the user can debug from the UI (was previously a silent "failed"
            # without any reason in result_summary).
            top_error = None
            if final_status == "failed":
                if results:
                    first_err = next((x.get("error") for x in results if not x.get("ok") and x.get("error")), None)
                    if first_err:
                        top_error = first_err
                    else:
                        top_error = f"Tous les envois ont échoué ({len(results)}/{len(results)})"
                elif skipped:
                    top_error = f"Aucun destinataire valide ({len(skipped)} ignorés)"
                else:
                    top_error = "Aucun destinataire dans la programmation"
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
                        "error": top_error,
                    },
                    "finished_at": _now(),
                    "updated_at": _now(),
                }},
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("scheduled_whatsapp runner failed")
        # Release any schedule we may have left stuck in `running` so a retry can re-claim it
        try:
            await db.whatsapp_schedules.update_many(
                {"status": "running", "started_at": {"$lte": _now()}},
                {"$set": {
                    "status": "failed",
                    "result_summary": {"error": f"Crash interne du planificateur: {str(exc)[:200]}"},
                    "finished_at": _now(),
                    "updated_at": _now(),
                }},
            )
        except Exception:  # noqa: BLE001
            pass


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
    type: str  # text | textarea | number | boolean | select | multiselect | date |
               # datetime | email | tel | url | location | table | file | signature
    label: str
    required: bool = False
    options: Optional[List[str]] = None
    placeholder: Optional[str] = None
    default_value: Optional[Any] = None
    # Position inside a 12-column responsive grid
    col_start: int = 1      # 1..12
    col_span: int = 12      # 1..12 (col_start + col_span <= 13)
    row: int = 0
    # Type-specific extras
    columns: Optional[List[Dict[str, Any]]] = None  # for type=table : [{key,label,type:text|number|date}]
    accept: Optional[str] = None  # for type=file : MIME / extensions filter


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
    # Iter34t — Reject duplicate form titles within the same client scope
    # (case-insensitive, trimmed). The frontend exposes /me/forms/title-suggestions
    # so users can autocomplete + check before submitting.
    title_norm = (payload.title or "").strip()
    if not title_norm:
        raise HTTPException(status_code=400, detail="Titre requis")
    existing = await db.forms.find_one(
        {"client_id": client_scope, "title": {"$regex": f"^\\s*{re.escape(title_norm)}\\s*$", "$options": "i"}},
        {"_id": 0, "id": 1, "title": 1, "number": 1},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Un formulaire portant le titre « {existing.get('title')} » existe déjà ({existing.get('number')}). Choisissez un autre titre.",
        )
    client = await db.users.find_one({"id": client_scope}, {"_id": 0, "client_code": 1, "company": 1, "full_name": 1})
    code = (client or {}).get("client_code") or _slugify_code((client or {}).get("company") or (client or {}).get("full_name") or "X")
    number = await _next_form_number(code)
    doc = {
        "id": _uuid(),
        "client_id": client_scope,
        "client_code": code,
        "number": f"FORM-{code}-{number:04d}",
        "title": title_norm,
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


# Iter34t — Expose existing form titles for the same client scope so the
# create form UI can suggest them as a datalist (prevents typo duplicates).
@api.get("/me/forms/title-suggestions", tags=["Formulaires"])
async def me_forms_title_suggestions(user: dict = Depends(get_current_user)):
    client_scope = (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else user["id"]
    items = await db.forms.find({"client_id": client_scope}, {"_id": 0, "title": 1, "number": 1}).sort("created_at", -1).to_list(500)
    seen = set()
    out: List[Dict[str, str]] = []
    for it in items:
        t = (it.get("title") or "").strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": t, "number": it.get("number")})
    return {"items": out}


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
    # Iter34t — block rename to a name already in use by another form of the
    # same client scope.
    if "title" in update:
        new_title = (update["title"] or "").strip()
        if not new_title:
            raise HTTPException(status_code=400, detail="Titre requis")
        dup = await db.forms.find_one(
            {
                "client_id": form.get("client_id"),
                "id": {"$ne": form_id},
                "title": {"$regex": f"^\\s*{re.escape(new_title)}\\s*$", "$options": "i"},
            },
            {"_id": 0, "id": 1, "title": 1, "number": 1},
        )
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"Un autre formulaire porte déjà ce titre ({dup.get('number')}).",
            )
        update["title"] = new_title
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


@api.post("/me/forms/{form_id}/upload", tags=["Formulaires"])
async def me_form_upload_file(
    form_id: str,
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Per-form file attachment uploader (max 1 Mo). Used by the new "file" field
    type. Returns a stable public URL stored on the submission's data dict."""
    raw = await file.read()
    if len(raw) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 1 Mo)")
    if len(raw) < 1:
        raise HTTPException(status_code=400, detail="Fichier vide")
    form = await db.forms.find_one({"id": form_id}, {"_id": 0, "client_id": 1})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    target = UPLOAD_DIR / safe_name
    target.write_bytes(raw)
    ext = (suffix.lstrip(".") or "").lower()
    public_path = f"/api/files/{file_id}{('.' + ext) if ext else ''}"
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    public_url = f"{(_public_base_url(request) or str(request.base_url).rstrip('/'))}{public_path}"
    file_doc = {
        "id": file_id, "filename": file.filename, "stored_name": safe_name,
        "extension": ext, "content_type": content_type, "size": len(raw),
        "url": public_path, "public_url": public_url, "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"), "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
        "context": "form_attachment",
        "form_id": form_id,
    }
    await db.files.insert_one(file_doc)
    return {
        "ok": True,
        "file_id": file_id,
        "filename": file.filename,
        "size": len(raw),
        "content_type": content_type,
        "public_url": public_url,
    }


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


# Iter34v — Tabular view of submissions for a form.
# Used by the UI to render submissions inline (instead of relying solely on
# the aggregated analytics) so the admin can confirm the data BEFORE exporting.
@api.get("/me/forms/{form_id}/submissions-table", tags=["Formulaires"])
async def me_form_submissions_table(
    form_id: str,
    user: dict = Depends(get_current_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    form = await db.forms.find_one({"id": form_id}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable")
    await _require_owner_or_admin(form, user)
    df = _parse_date(date_from); dt = _parse_date(date_to)
    match: Dict[str, Any] = {"form_id": form_id}
    rng: Dict[str, Any] = {}
    if df: rng["$gte"] = df.isoformat()
    if dt: rng["$lte"] = dt.isoformat()
    if rng:
        match["created_at"] = rng
    # Flatten the form pages into ordered (id, label) tuples for the columns
    columns: List[Dict[str, str]] = []
    seen = set()
    for page in (form.get("pages") or []):
        for field in (page.get("fields") or []):
            fid = field.get("id")
            if fid and fid not in seen:
                seen.add(fid)
                columns.append({"id": fid, "label": field.get("label") or fid, "type": field.get("type") or "text"})
    subs = await db.form_submissions.find(match, {"_id": 0}).sort("created_at", -1).to_list(limit)
    rows: List[Dict[str, Any]] = []
    for s in subs:
        ts = s.get("created_at")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts or "")
        row: Dict[str, Any] = {
            "id": s.get("id"),
            "created_at": ts_str,
            "user_label": s.get("user_label") or "—",
            "anonymous": bool(s.get("anonymous")),
            "respondent_email": s.get("respondent_email") or "",
            "geo": s.get("geo") or {},
            "source_ip": s.get("source_ip") or "",
        }
        data = s.get("data") or {}
        for col in columns:
            v = data.get(col["id"])
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            row[col["id"]] = v
        rows.append(row)
    return {
        "form": {"id": form["id"], "number": form.get("number"), "title": form.get("title")},
        "columns": columns,
        "rows": rows,
        "total": len(rows),
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
async def admin_reset_visit_counter(payload: Dict[str, Any] = Body(default={}), _: dict = Depends(get_current_admin)):
    """Resets the publicly displayed visits counter to zero (real visits
    remain in DB by default — only the offset moves).

    Iter34i: When `purge_access_logs=true`, also wipes `db.access_logs` and
    `db.visits` so the platform restarts from a clean analytics slate. The
    setting `usage_reset_at` is recorded so the UI can show "Compteur réinitialisé
    le …" rather than confusing the admin with stale histograms."""
    purge = bool(payload.get("purge_access_logs"))
    real = await db.visits.count_documents({})
    access_log_count = 0
    if purge:
        access_log_count = await db.access_logs.count_documents({})
        await db.access_logs.delete_many({})
        await db.visits.delete_many({})
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"visits_counter_offset": 0, "usage_reset_at": _now(), "updated_at": _now()}},
            upsert=True,
        )
        return {"ok": True, "displayed_count": 0, "real_count": 0, "purged_visits": real, "purged_access_logs": access_log_count}
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"visits_counter_offset": -real, "updated_at": _now()}},
        upsert=True,
    )
    return {"ok": True, "displayed_count": 0, "real_count": real, "purged_visits": 0, "purged_access_logs": 0}


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


@app.on_event("startup")
async def on_startup():
    # Iter35q — Initialize Emergent Object Storage (best-effort, non-blocking).
    try:
        from storage import init_storage as _init_storage
        _init_storage()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[startup] storage init skipped: %s", exc)
    # Iter35u — Pull the DB-stored public_base_url into the in-memory cache.
    await _refresh_public_base_url_cache()
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
    await db.directory_contacts.create_index("unique_code")
    # One-shot backfill: assign a stable unique_code to any pre-existing contact
    # that doesn't have one yet. The code is generated per client/year using
    # the same counter as new contacts so sequencing is preserved.
    try:
        missing_cursor = db.directory_contacts.find(
            {"$or": [{"unique_code": {"$exists": False}}, {"unique_code": None}, {"unique_code": ""}]},
            {"_id": 0, "id": 1, "client_id": 1, "created_at": 1},
        ).sort("created_at", 1)
        client_cache: Dict[str, dict] = {}
        async for c in missing_cursor:
            cid = c.get("client_id")
            if not cid:
                continue
            client_doc = client_cache.get(cid)
            if client_doc is None:
                client_doc = await db.users.find_one(
                    {"id": cid},
                    {"_id": 0, "id": 1, "client_code": 1, "company": 1, "full_name": 1},
                ) or {"id": cid}
                client_cache[cid] = client_doc
            uc = await _next_contact_unique_code(client_doc)
            await db.directory_contacts.update_one({"id": c["id"]}, {"$set": {"unique_code": uc}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("contact unique_code backfill failed: %s", exc)

    # One-shot migration: fill `client_id` on bridged tracked-user accounts that
    # were created before we started mirroring `parent_client_id` → `client_id`.
    # Without this, legacy ~50 endpoints that resolve scope via
    # `user.get("client_id") or user["id"]` fall back to the user's own id and
    # tracked users never inherit RGPD/feature flags from their parent client.
    try:
        await db.users.update_many(
            {
                "role": "client",
                "parent_client_id": {"$exists": True, "$nin": [None, ""]},
                "$or": [{"client_id": {"$exists": False}}, {"client_id": None}, {"client_id": ""}],
            },
            [{"$set": {"client_id": "$parent_client_id"}}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tracked-user client_id mirror backfill failed: %s", exc)

    # ============================================================
    # iter28 HOTFIX — Re-tag historical CRM data orphaned by iter24.
    #
    # Context: iter24's `client_id` mirror migration set `users.client_id =
    # parent_client_id` on bridged tracked-user accounts. Reads now resolve
    # scope via `user.client_id`, but historical contacts/messages/schedules
    # created BEFORE iter24 are still tagged with the user's OWN id (because
    # back then `client_scope = user.client_id || user.id` fell back to the
    # user id when client_id was empty). Result: those rows became invisible
    # to the bridged user after iter24.
    #
    # This migration re-tags those rows to the parent_client_id and stores
    # the previous value in `client_id_legacy` for traceability/rollback.
    # Idempotent — guarded by `client_id_legacy` not existing yet.
    # ============================================================
    try:
        result = await _migrate_orphan_client_data()
        if result["total_migrated"] > 0:
            logger.info("iter28 orphan-data migration: %s", result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("iter28 orphan-data migration failed: %s", exc)

    # Regression sentinel: dry-run after migration to confirm no orphans remain.
    # If any new orphan appears (e.g. introduced by a future code change), this
    # warning will surface in the logs and admins can re-run via the UI button.
    try:
        post_check = await _migrate_orphan_client_data(dry_run=True)
        if post_check["total_migrated"] > 0:
            logger.warning(
                "iter28 sentinel: %d orphan rows STILL present after auto-migration "
                "across %d user(s) — investigate /admin/migrate-orphan-data",
                post_check["total_migrated"], len(post_check["affected_users"]),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("iter28 sentinel check failed: %s", exc)

    # Iter29 — Force every CRM contact into the new shared model. This is a
    # no-op for new contacts (they already get shared:true at creation), but
    # normalizes legacy private contacts so any code path that still inspects
    # the boolean keeps working. Idempotent.
    try:
        res29 = await db.directory_contacts.update_many(
            {"$or": [{"shared": False}, {"shared": {"$exists": False}}]},
            {"$set": {"shared": True}},
        )
        if int(getattr(res29, "modified_count", 0) or 0) > 0:
            logger.info(
                "iter29 contacts shared-by-default migration: %d rows normalized",
                res29.modified_count,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("iter29 contacts shared migration failed: %s", exc)

    # Iter31 — Client-consistency canary. Surfaces misaligned users at boot
    # so admins are warned BEFORE the affected user complains. Read-only.
    try:
        scan = await _scan_clients_consistency()
        if scan["misaligned_users_total"] > 0:
            logger.warning(
                "iter31 client-consistency canary: %d user(s) misaligned across %d company group(s) — "
                "see /admin/clients-consistency or Settings → 'Cohérence multi-utilisateurs'",
                scan["misaligned_users_total"], scan["misaligned_groups"],
            )
            for g in scan["groups"][:10]:
                logger.warning(
                    "  • %s — canonical=%s via %s — %d/%d misaligned: %s",
                    g["company"], (g["canonical_client_id"] or "")[:8],
                    g["canonical_via"], g["misaligned_count"], g["members_total"],
                    ", ".join(m.get("email") or m["id"][:8] for m in g["misaligned"][:5]),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("iter31 client-consistency canary failed: %s", exc)

    await db.whatsapp_messages.create_index("client_id")
    await db.whatsapp_messages.create_index("created_at")
    await db.whatsapp_schedules.create_index("status")
    await db.whatsapp_schedules.create_index("scheduled_at")
    await db.whatsapp_messages.create_index("payment_link_slug")
    # SMS Phase 1+2
    await db.sms_messages.create_index("client_id")
    await db.sms_messages.create_index("created_at")
    await db.sms_messages.create_index("payment_link_slug")
    await db.sms_messages.create_index([("contact_id", 1), ("created_at", -1)])
    await db.sms_schedules.create_index("status")
    await db.sms_schedules.create_index("scheduled_at")
    await db.sms_schedules.create_index([("client_id", 1), ("status", 1)])
    # Payment links (Iterations 38+)
    await db.payment_links.create_index("slug", unique=True)
    await db.payment_links.create_index("client_id")
    await db.payments.create_index("client_id")
    await db.payments.create_index("deposit_id", unique=True)
    await db.payments.create_index("payment_link_slug")
    await db.automations.create_index("event")
    await db.automations.create_index("enabled")
    await db.client_notes.create_index("client_id")
    await db.client_tasks.create_index("client_id")
    await db.client_tasks.create_index("status")
    await db.client_tasks.create_index("due_at")
    await db.policies.create_index("slot", unique=True)
    await db.ai_summaries.create_index("user_id")
    await db.ai_summaries.create_index([("user_id", 1), ("created_at", -1)])
    await db.ai_summaries.create_index("created_at")
    await db.payments.create_index("deposit_id", unique=True)
    await db.payments.create_index([("user_id", 1), ("created_at", -1)])
    await db.payments.create_index([("client_id", 1), ("created_at", -1)])
    await db.payments.create_index("status")

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
            # Iter35b — every 4h check whether Meta is calling our WA webhook.
            async def _scheduled_wa_silence():
                await _run_wa_silence_check(triggered_by="cron:4h")
            _scheduler.add_job(
                _scheduled_wa_silence,
                CronTrigger(hour="*/4", minute=20, timezone="Africa/Abidjan"),
                id="wa_silence_detector_4h",
                replace_existing=True,
                misfire_grace_time=900,
            )
            # Minute-level WhatsApp scheduler — drains pending schedules due for send.
            _scheduler.add_job(
                _run_scheduled_whatsapp,
                CronTrigger(minute="*", timezone="Africa/Abidjan"),
                id="whatsapp_scheduler_minutely",
                replace_existing=True,
                misfire_grace_time=120,
            )
            # Minute-level SMS scheduler — drains pending SMS schedules due for send.
            _scheduler.add_job(
                _run_scheduled_sms,
                CronTrigger(minute="*", timezone="Africa/Abidjan"),
                id="sms_scheduler_minutely",
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
            # Weekly DB auto-snapshot — Sunday 03:00 (Africa/Abidjan), gated by
            # settings.auto_snapshot_enabled. Keeps the last N (settings
            # .auto_snapshot_keep, default 4) auto snapshots; manual ones
            # never rotate.
            async def _scheduled_auto_snapshot():
                try:
                    s = await db.settings.find_one({"_id": "global"}) or {}
                    if not s.get("auto_snapshot_enabled"):
                        return
                    await _run_auto_snapshot(triggered_by="cron:weekly-sun-03")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Auto-snapshot cron failed: %s", exc)
            _scheduler.add_job(
                _scheduled_auto_snapshot,
                CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="Africa/Abidjan"),
                id="db_auto_snapshot_weekly",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            _scheduler.start()
            logger.info("Scheduler started — weekly digest Fri 05:00 + auth check H:00 + uptime H:05 (Africa/Abidjan)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scheduler init failed: %s", exc)


# ====================================================================
# SUBSCRIPTIONS MODULE — admin CRUD + public list + public order endpoint.
#
# • subscription_categories : 4 max categories (admin-defined groupings).
# • subscription_plans : individual offers shown on the public page.
#   Code format: FML + YYYY + 4-digit sequence reset every year.
# • subscription_orders : public-side leads. Triggers a WhatsApp
#   notification (+ optional automation webhook) when validated.
# ====================================================================
async def _next_subscription_code() -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"FML{year}"
    cursor = db.subscription_plans.find({"code": {"$regex": f"^{prefix}"}}, {"_id": 0, "code": 1}).sort("code", -1).limit(1)
    last = None
    async for d in cursor:
        last = d.get("code")
        break
    if last and len(last) == len(prefix) + 4:
        try:
            n = int(last[len(prefix):]) + 1
        except Exception:
            n = 1
    else:
        n = 1
    return f"{prefix}{n:04d}"


class SubscriptionCategoryCreate(BaseModel):
    label: str
    color: Optional[str] = "#0D6EFD"
    position: Optional[int] = 0
    animated: Optional[bool] = True


class SubscriptionCategoryUpdate(BaseModel):
    label: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None
    animated: Optional[bool] = None


class SubscriptionPlanCreate(BaseModel):
    name: str
    category_id: Optional[str] = None
    description: Optional[str] = ""
    price_monthly_xof: int = 0
    price_annual_xof: int = 0
    featured: Optional[bool] = False
    active: Optional[bool] = True
    automation_url: Optional[str] = ""
    whatsapp_notify_to: Optional[str] = ""


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[str] = None
    description: Optional[str] = None
    price_monthly_xof: Optional[int] = None
    price_annual_xof: Optional[int] = None
    featured: Optional[bool] = None
    active: Optional[bool] = None
    automation_url: Optional[str] = None
    whatsapp_notify_to: Optional[str] = None


class SubscriptionOrderCreate(BaseModel):
    plan_id: str
    period: str  # "monthly" | "annual"
    customer_name: str
    customer_email: Optional[str] = ""
    customer_phone: str
    message: Optional[str] = ""


@api.get("/admin/subscriptions/categories", tags=["Admin"])
async def admin_list_subscription_categories(user: dict = Depends(get_current_admin)):
    items = await db.subscription_categories.find({}, {"_id": 0}).sort("position", 1).to_list(20)
    return items


@api.post("/admin/subscriptions/categories", tags=["Admin"])
async def admin_create_subscription_category(payload: SubscriptionCategoryCreate, user: dict = Depends(get_current_admin)):
    n = await db.subscription_categories.count_documents({})
    if n >= 4:
        raise HTTPException(status_code=400, detail="Maximum 4 catégories autorisées")
    doc = {
        "id": _uuid(),
        "label": payload.label.strip()[:60],
        "color": (payload.color or "#0D6EFD")[:20],
        "position": int(payload.position or 0),
        "animated": bool(payload.animated if payload.animated is not None else True),
        "created_at": _now(),
    }
    await db.subscription_categories.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/subscriptions/categories/{cat_id}", tags=["Admin"])
async def admin_update_subscription_category(cat_id: str, payload: SubscriptionCategoryUpdate, user: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Aucune modification")
    await db.subscription_categories.update_one({"id": cat_id}, {"$set": update})
    doc = await db.subscription_categories.find_one({"id": cat_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    return doc


@api.delete("/admin/subscriptions/categories/{cat_id}", tags=["Admin"])
async def admin_delete_subscription_category(cat_id: str, user: dict = Depends(get_current_admin)):
    await db.subscription_categories.delete_one({"id": cat_id})
    await db.subscription_plans.update_many({"category_id": cat_id}, {"$set": {"category_id": None}})
    return {"ok": True}


@api.get("/admin/subscriptions/plans", tags=["Admin"])
async def admin_list_subscription_plans(user: dict = Depends(get_current_admin)):
    items = await db.subscription_plans.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@api.post("/admin/subscriptions/plans", tags=["Admin"])
async def admin_create_subscription_plan(payload: SubscriptionPlanCreate, user: dict = Depends(get_current_admin)):
    code = await _next_subscription_code()
    doc = {
        "id": _uuid(),
        "code": code,
        "name": payload.name.strip()[:120],
        "category_id": payload.category_id,
        "description": (payload.description or "").strip(),
        "price_monthly_xof": max(0, int(payload.price_monthly_xof or 0)),
        "price_annual_xof": max(0, int(payload.price_annual_xof or 0)),
        "featured": bool(payload.featured),
        "active": bool(payload.active if payload.active is not None else True),
        "automation_url": (payload.automation_url or "").strip(),
        "whatsapp_notify_to": (payload.whatsapp_notify_to or "").strip(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.subscription_plans.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/subscriptions/plans/{plan_id}", tags=["Admin"])
async def admin_update_subscription_plan(plan_id: str, payload: SubscriptionPlanUpdate, user: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Aucune modification")
    update["updated_at"] = _now()
    await db.subscription_plans.update_one({"id": plan_id}, {"$set": update})
    doc = await db.subscription_plans.find_one({"id": plan_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Formule introuvable")
    return doc


@api.delete("/admin/subscriptions/plans/{plan_id}", tags=["Admin"])
async def admin_delete_subscription_plan(plan_id: str, user: dict = Depends(get_current_admin)):
    await db.subscription_plans.delete_one({"id": plan_id})
    return {"ok": True}


@api.get("/admin/subscriptions/orders", tags=["Admin"])
async def admin_list_subscription_orders(user: dict = Depends(get_current_admin)):
    items = await db.subscription_orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@api.get("/public/subscriptions", tags=["Public"])
async def public_list_subscriptions():
    """Public: returns active plans grouped by category (max 4 categories)."""
    cats = await db.subscription_categories.find({}, {"_id": 0}).sort("position", 1).to_list(4)
    plans = await db.subscription_plans.find({"active": True}, {"_id": 0, "automation_url": 0, "whatsapp_notify_to": 0}).sort("created_at", 1).to_list(100)
    return {"categories": cats, "plans": plans}


@api.post("/public/subscriptions/order", tags=["Public"])
async def public_create_subscription_order(payload: SubscriptionOrderCreate, request: Request):
    plan = await db.subscription_plans.find_one({"id": payload.plan_id, "active": True}, {"_id": 0})
    if not plan:
        raise HTTPException(status_code=404, detail="Formule introuvable ou désactivée")
    if payload.period not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="Période invalide")
    if not (payload.customer_name or "").strip() or not (payload.customer_phone or "").strip():
        raise HTTPException(status_code=400, detail="Nom et téléphone requis")
    amount = plan.get("price_monthly_xof") if payload.period == "monthly" else plan.get("price_annual_xof")
    order = {
        "id": _uuid(),
        "plan_id": payload.plan_id,
        "plan_code": plan.get("code"),
        "plan_name": plan.get("name"),
        "period": payload.period,
        "amount_xof": amount,
        "customer_name": payload.customer_name.strip()[:120],
        "customer_email": (payload.customer_email or "").strip()[:200],
        "customer_phone": payload.customer_phone.strip()[:30],
        "message": (payload.message or "").strip()[:1000],
        "ip": _client_ip_from_request(request),
        "status": "pending",
        "created_at": _now(),
    }
    await db.subscription_orders.insert_one(order.copy())
    order.pop("_id", None)

    notify_to = (plan.get("whatsapp_notify_to") or "").strip()
    if notify_to:
        try:
            text = (
                f"🆕 Nouvelle souscription\n"
                f"Formule : {plan.get('name')} ({plan.get('code')})\n"
                f"Période : {'Mensuel' if payload.period == 'monthly' else 'Annuel'} — {amount:,} XOF\n"
                f"Client : {order['customer_name']}\n"
                f"Téléphone : {order['customer_phone']}\n"
                f"Email : {order['customer_email'] or '—'}\n"
                f"Message : {order['message'] or '—'}"
            )
            await _wa_send_text(notify_to, text)
            await db.subscription_orders.update_one({"id": order["id"]}, {"$set": {"status": "notified"}})
        except Exception as exc:  # noqa: BLE001
            logger.warning("subscription wa-notify failed: %s", exc)

    auto_url = (plan.get("automation_url") or "").strip()
    if auto_url:
        try:
            async with httpx.AsyncClient(timeout=8) as http:
                await http.post(auto_url, json=order)
        except Exception as exc:  # noqa: BLE001
            logger.warning("subscription automation webhook failed: %s", exc)

    # Auto-create a public PawaPay payment link so the visitor can pay
    # immediately after submitting. Best-effort: skipped if PawaPay is not
    # enabled, or if amount is 0, or if no admin client is configured.
    pay_link_url = None
    pay_link_slug = None
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if s.get("pawapay_enabled") and amount and int(amount) > 0:
            primary = await db.users.find_one({"role": "superviseur"}, {"_id": 0, "id": 1})
            if not primary:
                # Fallback to first admin so the link still gets created in
                # development / single-admin setups.
                primary = await db.users.find_one({"role": "admin"}, {"_id": 0, "id": 1})
            client_scope = (primary or {}).get("id")
            if client_scope:
                slug = None
                for _ in range(8):
                    cand = _gen_slug(8)
                    if not await db.payment_links.find_one({"slug": cand}):
                        slug = cand
                        break
                if slug:
                    link_doc = {
                        "id": _uuid(),
                        "slug": slug,
                        "client_id": client_scope,
                        "owner_user_id": None,
                        "owner_email": None,
                        "owner_label": "Souscription publique",
                        "label": f"Souscription : {plan.get('name')} ({'mensuel' if payload.period == 'monthly' else 'annuel'})",
                        "amount": float(amount),
                        "currency": "XOF",
                        "description": f"Code {plan.get('code')} — {payload.customer_name.strip()[:60]}",
                        "allowed_mnos": list(DEFAULT_CLIENT_PAWAPAY_MNOS),
                        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                        "max_uses": 1,
                        "uses_count": 0,
                        "disabled": False,
                        "subscription_order_id": order["id"],
                        "subscription_plan_code": plan.get("code"),
                        "prefill_phone": order["customer_phone"],
                        "prefill_name": order["customer_name"],
                        "created_at": _now(),
                        "updated_at": _now(),
                    }
                    await db.payment_links.insert_one(link_doc.copy())
                    pay_link_slug = slug
                    pay_link_url = f"/pay/{slug}"
                    await db.subscription_orders.update_one(
                        {"id": order["id"]},
                        {"$set": {"payment_link_slug": slug, "payment_link_url": pay_link_url}},
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning("subscription pay-link creation failed: %s", exc)

    return {
        "ok": True,
        "order_id": order["id"],
        "next_step": "Notre équipe vous contactera sous 24h pour finaliser votre souscription.",
        "payment_link_slug": pay_link_slug,
        "payment_link_url": pay_link_url,
    }



@app.on_event("shutdown")
async def on_shutdown():
    try:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        pass



# ====================================================================
# Iter35o — Support tickets (intervention tickets opened from WA chat)
#
# • Numérotation par client: TKT-YYYY-NNNN, séquence remise à zéro par
#   année et par client_id. Stockée dans db.counters
#   (id="tickets_{client_id}_{year}").
# • Un seul ticket "non clôturé" par contact à la fois — la création
#   d'un nouveau ticket est bloquée tant que le précédent n'est pas
#   en statut "done" ou "cancelled".
# • Statuts: open (en attente) → in_progress → done|cancelled,
#   et suspended à tout moment (avant clôture).
# • Notifications WhatsApp via templates Meta paramétrables dans
#   /admin/settings (wa_template_ticket_open, wa_template_ticket_close).
# ====================================================================
TICKET_OPEN_STATUSES = {"open", "in_progress", "suspended"}
TICKET_CLOSED_STATUSES = {"done", "cancelled"}
TICKET_ALL_STATUSES = TICKET_OPEN_STATUSES | TICKET_CLOSED_STATUSES


async def _next_ticket_number(client_id: str) -> str:
    """Atomic counter: TKT-YYYY-NNNN. Resets every Jan 1st per client."""
    year = datetime.now(timezone.utc).year
    counter_id = f"tickets_{client_id}_{year}"
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    seq = (res or {}).get("seq", 1)
    return f"TKT-{year}-{seq:04d}"


def _ticket_components(number: str, motif: str = "", duration: str = "") -> list:
    """Build Meta template `components` array for a ticket-open/close template.
    Body variables: {1}=ticket number, {2}=motif OR duration."""
    second_var = motif if motif else duration
    return [{
        "type": "body",
        "parameters": [
            {"type": "text", "text": number[:60]},
            {"type": "text", "text": (second_var or "—")[:200]},
        ],
    }]


def _format_ticket_duration(opened_iso: str, closed_iso: str) -> str:
    try:
        o = datetime.fromisoformat(opened_iso.replace("Z", "+00:00"))
        c = datetime.fromisoformat(closed_iso.replace("Z", "+00:00"))
        secs = int((c - o).total_seconds())
        if secs < 60:
            return f"{secs} s"
        if secs < 3600:
            return f"{secs // 60} min"
        if secs < 86400:
            h = secs // 3600
            m = (secs % 3600) // 60
            return f"{h} h {m} min" if m else f"{h} h"
        d = secs // 86400
        h = (secs % 86400) // 3600
        return f"{d} j {h} h" if h else f"{d} j"
    except Exception:
        return "—"


async def _ticket_scope_for_user(user: dict) -> Dict[str, Any]:
    """Mongo query filter restricting tickets to the user's effective client scope."""
    scope = await _resolve_visible_client_ids(user)
    return {"client_id": {"$in": scope}} if scope else {"client_id": "__none__"}


@api.post("/me/contacts/{cid}/ticket", tags=["Portail Client"])
async def me_open_ticket(
    cid: str,
    payload: TicketOpenPayload,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Open a new support ticket from the WhatsApp chat window. Blocks if
    the contact already has a non-closed ticket (open|in_progress|suspended)."""
    motif = (payload.motif or "").strip()
    if not motif:
        raise HTTPException(status_code=400, detail="Le motif est obligatoire.")
    if len(motif) > 200:
        raise HTTPException(status_code=400, detail="Le motif doit faire au maximum 200 caractères.")

    scope_filter = await _ticket_scope_for_user(user)
    # Iter35o-fix — Contacts WhatsApp/manuels sont stockés dans `directory_contacts`
    # (la collection `contacts` est utilisée par l'ancien CRM admin). Tomber en
    # rétrocompat sur `contacts` si rien n'est trouvé.
    contact = (
        await db.directory_contacts.find_one({**scope_filter, "id": cid}, {"_id": 0})
        or await db.contacts.find_one({**scope_filter, "id": cid}, {"_id": 0})
    )
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable.")
    # Block when the contact has an already-open ticket
    existing = await db.support_tickets.find_one(
        {"contact_id": cid, "status": {"$in": list(TICKET_OPEN_STATUSES)}},
        {"_id": 0, "number": 1, "status": 1, "opened_at": 1},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Le ticket {existing['number']} est encore ouvert (statut: {existing['status']}). Clôturez-le avant d'en créer un nouveau.",
        )

    client_id = contact.get("client_id") or user.get("client_id") or user["id"]
    number = await _next_ticket_number(client_id)
    now_iso = _now()
    ticket = {
        "id": _uuid(),
        "number": number,
        "client_id": client_id,
        "contact_id": cid,
        "contact_name": contact.get("name"),
        "contact_phone": contact.get("whatsapp") or contact.get("phone"),
        "motif": motif,
        "status": "open",
        "notes": None,
        "opened_at": now_iso,
        "opened_by_id": user["id"],
        "opened_by_label": user.get("full_name") or user.get("email"),
        "closed_at": None,
        "closed_by_id": None,
        "closed_by_label": None,
        "outcome": None,
        "resolution_note": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    await db.support_tickets.insert_one(ticket.copy())

    # Iter35p — Activity feed
    try:
        await _log_activity(
            client_id=client_id, kind="ticket", action="created",
            label=f"{number} — {motif[:80]}", actor=user, target_id=ticket["id"],
        )
    except Exception:
        pass

    # Optional WhatsApp notification (template) — best-effort, never blocks
    s = await db.settings.find_one({"_id": "global"}) or {}
    notify = bool(s.get("notify_on_ticket_open", True))
    tpl_name = (s.get("wa_template_ticket_open") or "").strip()
    notification = {"sent": False, "error": None}
    if notify and tpl_name and ticket["contact_phone"]:
        comps = _ticket_components(number, motif=motif)
        try:
            wr = await _wa_send_template(
                ticket["contact_phone"], tpl_name,
                (s.get("wa_template_ticket_language") or "fr").strip() or "fr",
                comps,
            )
            notification = {"sent": bool(wr.get("ok")), "error": wr.get("error")}
        except Exception as exc:  # noqa: BLE001
            notification = {"sent": False, "error": str(exc)[:200]}

    ticket.pop("_id", None)
    return {"ok": True, "ticket": ticket, "notification": notification}


@api.get("/me/tickets", tags=["Portail Client"])
async def me_list_tickets(
    status: Optional[str] = None,  # one of TICKET_ALL_STATUSES, or "open_all" for any non-closed
    contact_id: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(get_current_user),
):
    scope_filter = await _ticket_scope_for_user(user)
    q: Dict[str, Any] = {**scope_filter}
    if contact_id:
        q["contact_id"] = contact_id
    if status:
        if status == "open_all":
            q["status"] = {"$in": list(TICKET_OPEN_STATUSES)}
        elif status in TICKET_ALL_STATUSES:
            q["status"] = status
    items = await db.support_tickets.find(q, {"_id": 0}).sort("opened_at", -1).to_list(min(max(limit, 1), 1000))
    # Iter35r — Enrich each ticket with client_label / company_label + age &
    # active-pause durations so the UI can spotlight "dormant" tickets.
    client_ids = list({(t.get("client_id") or "") for t in items if t.get("client_id")})
    clients_map: Dict[str, Dict[str, Any]] = {}
    if client_ids:
        async for c in db.users.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "email": 1}):
            clients_map[c["id"]] = c
    now_dt = datetime.now(timezone.utc)
    for t in items:
        c = clients_map.get(t.get("client_id"))
        t["client_label"] = (c or {}).get("full_name") or (c or {}).get("email")
        t["company_label"] = (c or {}).get("company")
        # Age = depuis l'ouverture jusqu'à aujourd'hui (si non clôturé) ou clôture sinon
        try:
            o = datetime.fromisoformat((t.get("opened_at") or "").replace("Z", "+00:00"))
            ref = (t.get("closed_at") or "").replace("Z", "+00:00")
            ref_dt = datetime.fromisoformat(ref) if ref else now_dt
            t["age_seconds"] = max(0, int((ref_dt - o).total_seconds()))
        except Exception:
            t["age_seconds"] = None
        # Pause cumulative — inclut le timer courant si statut=suspended
        total_pause = int(t.get("suspended_total_seconds") or 0)
        if t.get("status") == "suspended" and t.get("suspended_started_at"):
            try:
                s_dt = datetime.fromisoformat(t["suspended_started_at"].replace("Z", "+00:00"))
                total_pause += max(0, int((now_dt - s_dt).total_seconds()))
            except Exception:
                pass
        t["pause_seconds"] = total_pause
    return items


@api.get("/me/tickets/pending-count", tags=["Portail Client"])
async def me_tickets_pending_count(user: dict = Depends(get_current_user)):
    """Return the number of non-closed tickets in the user's scope.
    Used by the sidebar/dashboard badges."""
    scope_filter = await _ticket_scope_for_user(user)
    q = {**scope_filter, "status": {"$in": list(TICKET_OPEN_STATUSES)}}
    count = await db.support_tickets.count_documents(q)
    by_status: Dict[str, int] = {}
    pipeline = [{"$match": q}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    async for row in db.support_tickets.aggregate(pipeline):
        by_status[row["_id"]] = row["n"]
    return {"count": count, "by_status": by_status}


@api.patch("/me/tickets/{tid}", tags=["Portail Client"])
async def me_update_ticket(
    tid: str,
    payload: TicketUpdatePayload,
    user: dict = Depends(get_current_user),
):
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    if ticket["status"] in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail=f"Ticket déjà clôturé ({ticket['status']}). Réouverture interdite.")
    update: Dict[str, Any] = {}
    if payload.status is not None:
        if payload.status in TICKET_CLOSED_STATUSES:
            raise HTTPException(status_code=400, detail="Utilisez l'endpoint /close pour clôturer un ticket.")
        if payload.status not in TICKET_OPEN_STATUSES:
            raise HTTPException(status_code=400, detail=f"Statut invalide. Valeurs: {sorted(TICKET_OPEN_STATUSES)}")
        # Iter35r — Track cumulative pause time (status=suspended).
        # When transitioning INTO suspended → stamp suspended_started_at.
        # When transitioning OUT of suspended → add elapsed to suspended_total_seconds.
        old_status = ticket.get("status")
        if old_status != "suspended" and payload.status == "suspended":
            update["suspended_started_at"] = _now()
        elif old_status == "suspended" and payload.status != "suspended":
            started = ticket.get("suspended_started_at")
            if started:
                try:
                    s_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    elapsed = int((datetime.now(timezone.utc) - s_dt).total_seconds())
                    if elapsed > 0:
                        update["suspended_total_seconds"] = (ticket.get("suspended_total_seconds") or 0) + elapsed
                    update["suspended_started_at"] = None
                except Exception:
                    update["suspended_started_at"] = None
        update["status"] = payload.status
    if payload.motif is not None:
        m = payload.motif.strip()
        if not m or len(m) > 200:
            raise HTTPException(status_code=400, detail="Motif invalide (1..200 caractères).")
        update["motif"] = m
    if payload.notes is not None:
        update["notes"] = (payload.notes or "").strip()[:2000] or None
    if not update:
        return {"ok": True, "ticket": ticket, "changed": False}
    update["updated_at"] = _now()
    await db.support_tickets.update_one({"id": tid}, {"$set": update})
    ticket.update(update)
    return {"ok": True, "ticket": ticket, "changed": True}


@api.post("/me/tickets/{tid}/close", tags=["Portail Client"])
async def me_close_ticket(
    tid: str,
    payload: TicketClosePayload,
    user: dict = Depends(get_current_user),
):
    if payload.outcome not in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=400, detail="outcome doit être 'done' ou 'cancelled'.")
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    if ticket["status"] in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail=f"Déjà clôturé ({ticket['status']}).")
    now_iso = _now()
    res_note = (payload.resolution_note or "").strip()[:2000] or None
    update = {
        "status": payload.outcome,
        "outcome": payload.outcome,
        "resolution_note": res_note,
        "closed_at": now_iso,
        "closed_by_id": user["id"],
        "closed_by_label": user.get("full_name") or user.get("email"),
        "updated_at": now_iso,
    }
    # Iter35r — Flush running suspend timer if closed while suspended
    if ticket.get("status") == "suspended" and ticket.get("suspended_started_at"):
        try:
            s_dt = datetime.fromisoformat(ticket["suspended_started_at"].replace("Z", "+00:00"))
            elapsed = int((datetime.now(timezone.utc) - s_dt).total_seconds())
            if elapsed > 0:
                update["suspended_total_seconds"] = (ticket.get("suspended_total_seconds") or 0) + elapsed
            update["suspended_started_at"] = None
        except Exception:
            update["suspended_started_at"] = None
    await db.support_tickets.update_one({"id": tid}, {"$set": update})
    ticket.update(update)

    # Iter35p — Activity feed for close
    try:
        await _log_activity(
            client_id=ticket["client_id"], kind="ticket", action="closed",
            label=f"{ticket['number']} → {payload.outcome}", actor=user, target_id=ticket["id"],
        )
    except Exception:
        pass

    # WhatsApp notification on closure (best-effort)
    s = await db.settings.find_one({"_id": "global"}) or {}
    admin_default_notify = bool(s.get("notify_on_ticket_close", True))
    if payload.notify_contact is None:
        notify = admin_default_notify
    else:
        notify = bool(payload.notify_contact)
    tpl_name = (s.get("wa_template_ticket_close") or "").strip()
    notification = {"sent": False, "error": None}
    if notify and tpl_name and ticket.get("contact_phone"):
        duration = _format_ticket_duration(ticket["opened_at"], now_iso)
        comps = _ticket_components(ticket["number"], duration=duration)
        try:
            wr = await _wa_send_template(
                ticket["contact_phone"], tpl_name,
                (s.get("wa_template_ticket_language") or "fr").strip() or "fr",
                comps,
            )
            notification = {"sent": bool(wr.get("ok")), "error": wr.get("error")}
        except Exception as exc:  # noqa: BLE001
            notification = {"sent": False, "error": str(exc)[:200]}

    return {"ok": True, "ticket": ticket, "notification": notification}


@api.get("/me/contacts/{cid}/active-ticket", tags=["Portail Client"])
async def me_contact_active_ticket(cid: str, user: dict = Depends(get_current_user)):
    """Convenience: returns the non-closed ticket for a contact (if any).
    Used by the chat UI to swap "Generate ticket" → "View open ticket"."""
    scope_filter = await _ticket_scope_for_user(user)
    contact = (
        await db.directory_contacts.find_one({**scope_filter, "id": cid}, {"_id": 0, "id": 1})
        or await db.contacts.find_one({**scope_filter, "id": cid}, {"_id": 0, "id": 1})
    )
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable.")
    t = await db.support_tickets.find_one(
        {"contact_id": cid, "status": {"$in": list(TICKET_OPEN_STATUSES)}},
        {"_id": 0},
        sort=[("opened_at", -1)],
    )
    return {"active": t is not None, "ticket": t}


# ====================================================================
# Iter35p — Ticket enhancements:
#   1) Assignment to a user-suivi (notify via activity_events).
#   2) Reopen — creates a sibling TKT-YYYY-NNNN-R{k} linked to parent.
#   3) Motif templates — CRUD for reusable motif snippets.
#   4) Resolution-time stats — dashboard score per user + team leaderboard.
# ====================================================================
@api.post("/me/tickets/{tid}/assign", tags=["Portail Client"])
async def me_assign_ticket(
    tid: str,
    payload: TicketAssignPayload,
    user: dict = Depends(get_current_user),
):
    """Assign a ticket to a user (or unassign when user_id is empty)."""
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    if ticket["status"] in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail="Ticket clôturé — affectation impossible.")
    uid = (payload.user_id or "").strip() or None
    update: Dict[str, Any] = {"updated_at": _now()}
    if uid is None:
        update["assigned_to_id"] = None
        update["assigned_to_label"] = None
        update["assigned_at"] = None
        update["assigned_by_id"] = None
    else:
        # The target must be in the same scope (users OR tracked_users)
        eff_client = user.get("parent_client_id") or user.get("client_id") or user["id"]
        target = await db.users.find_one(
            {"id": uid, "$or": [{"id": eff_client}, {"client_id": eff_client}, {"parent_client_id": eff_client}]},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1},
        )
        if not target:
            target = await db.tracked_users.find_one({"id": uid, "client_id": eff_client}, {"_id": 0, "id": 1, "full_name": 1, "email": 1})
        if not target:
            raise HTTPException(status_code=400, detail="Utilisateur destinataire hors périmètre.")
        update["assigned_to_id"] = target["id"]
        update["assigned_to_label"] = target.get("full_name") or target.get("email") or target["id"][:8]
        update["assigned_at"] = _now()
        update["assigned_by_id"] = user["id"]
    await db.support_tickets.update_one({"id": tid}, {"$set": update})
    ticket.update(update)
    # Activity feed → assignee gets a toast in real-time
    try:
        await _log_activity(
            client_id=ticket["client_id"], kind="ticket", action="assigned",
            label=f"{ticket['number']} → {update.get('assigned_to_label') or 'aucun'}",
            actor=user, target_id=tid,
        )
    except Exception:
        pass
    return {"ok": True, "ticket": ticket}


@api.post("/me/tickets/{tid}/reopen", tags=["Portail Client"])
async def me_reopen_ticket(
    tid: str,
    payload: TicketReopenPayload,
    user: dict = Depends(get_current_user),
):
    """Re-open a closed ticket as a *new* sibling whose number ends with -R{k}.

    Example chain : TKT-2026-0014 (done) → /reopen → TKT-2026-0014-R1 (open) →
    if closed and reopened again → TKT-2026-0014-R2.

    The parent must already be closed. The new ticket carries:
      - parent_ticket_id (the very first ticket of the chain)
      - root_number (the original number, for grouping)
      - the same contact / client_id
    """
    scope_filter = await _ticket_scope_for_user(user)
    parent = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not parent:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    if parent["status"] not in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail="Le ticket doit être clôturé avant d'être rouvert.")
    # Also ensure the contact does not already have another open ticket
    existing_open = await db.support_tickets.find_one(
        {"contact_id": parent["contact_id"], "status": {"$in": list(TICKET_OPEN_STATUSES)}},
        {"_id": 0, "number": 1},
    )
    if existing_open:
        raise HTTPException(status_code=409, detail=f"{existing_open['number']} est déjà ouvert pour ce contact.")
    root_number = parent.get("root_number") or parent["number"]
    # Count how many siblings (including parent) share this root → suffix index
    chain_count = await db.support_tickets.count_documents({
        "$or": [{"number": root_number}, {"root_number": root_number}],
    })
    suffix_idx = chain_count  # next suffix
    new_number = f"{root_number}-R{suffix_idx}"
    motif = (payload.motif or "").strip() or (parent.get("motif") or "Réouverture")
    if len(motif) > 200:
        motif = motif[:200]
    now_iso = _now()
    new_ticket = {
        "id": _uuid(),
        "number": new_number,
        "root_number": root_number,
        "parent_ticket_id": parent["id"],
        "client_id": parent["client_id"],
        "contact_id": parent["contact_id"],
        "contact_name": parent.get("contact_name"),
        "contact_phone": parent.get("contact_phone"),
        "motif": motif,
        "status": "open",
        "notes": None,
        "opened_at": now_iso,
        "opened_by_id": user["id"],
        "opened_by_label": user.get("full_name") or user.get("email"),
        "closed_at": None,
        "closed_by_id": None,
        "closed_by_label": None,
        "outcome": None,
        "resolution_note": None,
        # Carry-over assignment if present on parent
        "assigned_to_id": parent.get("assigned_to_id"),
        "assigned_to_label": parent.get("assigned_to_label"),
        "assigned_at": now_iso if parent.get("assigned_to_id") else None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    await db.support_tickets.insert_one(new_ticket.copy())
    try:
        await _log_activity(
            client_id=new_ticket["client_id"], kind="ticket", action="reopened",
            label=f"{new_number} (depuis {parent['number']})", actor=user, target_id=new_ticket["id"],
        )
    except Exception:
        pass
    return {"ok": True, "ticket": new_ticket, "parent_number": parent["number"]}


# ---- Motif templates (reusable snippets) ------------------------------
@api.get("/me/ticket-motif-templates", tags=["Portail Client"])
async def me_list_ticket_motif_templates(user: dict = Depends(get_current_user)):
    scope = user.get("parent_client_id") or user.get("client_id") or user["id"]
    items = await db.ticket_motif_templates.find({"client_id": scope}, {"_id": 0}).sort("label", 1).to_list(100)
    return items


@api.post("/me/ticket-motif-templates", tags=["Portail Client"])
async def me_create_ticket_motif_template(
    payload: TicketMotifTemplatePayload,
    user: dict = Depends(get_current_user),
):
    # Only admin / superviseur / elevated_creator can manage templates
    if not (user.get("role") in ("admin", "superviseur") or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Rôle non autorisé.")
    label = (payload.label or "").strip()
    motif = (payload.motif or "").strip()
    if not label or not motif:
        raise HTTPException(status_code=400, detail="label et motif sont obligatoires.")
    if len(label) > 60 or len(motif) > 200:
        raise HTTPException(status_code=400, detail="Longueur maximale dépassée (label 60, motif 200).")
    scope = user.get("parent_client_id") or user.get("client_id") or user["id"]
    doc = {
        "id": _uuid(),
        "client_id": scope,
        "label": label,
        "motif": motif,
        "created_at": _now(),
        "created_by_id": user["id"],
    }
    await db.ticket_motif_templates.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "template": doc}


@api.delete("/me/ticket-motif-templates/{tpl_id}", tags=["Portail Client"])
async def me_delete_ticket_motif_template(tpl_id: str, user: dict = Depends(get_current_user)):
    if not (user.get("role") in ("admin", "superviseur") or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Rôle non autorisé.")
    scope = user.get("parent_client_id") or user.get("client_id") or user["id"]
    res = await db.ticket_motif_templates.delete_one({"id": tpl_id, "client_id": scope})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    return {"ok": True}


# ---- Resolution-time stats --------------------------------------------
@api.get("/me/dashboard/ticket-stats", tags=["Portail Client"])
async def me_dashboard_ticket_stats(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    """Per-user ticket resolution score (only `done` tickets count) over the
    trailing `days` window. Surfaced on the dashboard so teams can compare
    who resolves the fastest. Elevated viewers (admin/superviseur) also get
    a leaderboard of the top 10 fastest closers."""
    visible_scope = await _resolve_visible_client_ids(user)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {
        "client_id": {"$in": visible_scope},
        "status": "done",
        "closed_at": {"$gte": since},
        "opened_at": {"$exists": True, "$ne": None},
    }
    me_q = {**base_q, "closed_by_id": user["id"]}
    my_durations: List[int] = []
    async for d in db.support_tickets.find(me_q, {"_id": 0, "opened_at": 1, "closed_at": 1}):
        try:
            o = datetime.fromisoformat(d["opened_at"].replace("Z", "+00:00"))
            c = datetime.fromisoformat(d["closed_at"].replace("Z", "+00:00"))
            secs = int((c - o).total_seconds())
            if secs > 0:
                my_durations.append(secs)
        except Exception:
            pass
    my_durations.sort()
    me_block = {
        "avg_seconds": int(sum(my_durations) / len(my_durations)) if my_durations else None,
        "median_seconds": my_durations[len(my_durations) // 2] if my_durations else None,
        "fastest_seconds": my_durations[0] if my_durations else None,
        "closed_count": len(my_durations),
    }

    team: List[Dict[str, Any]] = []
    if _is_elevated_creator(user) or user.get("role") in ("admin", "superviseur"):
        pipeline = [
            {"$match": base_q},
            {"$addFields": {
                "opened_dt": {"$dateFromString": {"dateString": "$opened_at"}},
                "closed_dt": {"$dateFromString": {"dateString": "$closed_at"}},
            }},
            {"$addFields": {"_resolution_secs": {"$divide": [{"$subtract": ["$closed_dt", "$opened_dt"]}, 1000]}}},
            {"$match": {"_resolution_secs": {"$gt": 0}}},
            {"$group": {
                "_id": "$closed_by_id",
                "label": {"$last": "$closed_by_label"},
                "avg_seconds": {"$avg": "$_resolution_secs"},
                "fastest_seconds": {"$min": "$_resolution_secs"},
                "closed_count": {"$sum": 1},
            }},
            {"$sort": {"avg_seconds": 1}},
            {"$limit": 10},
        ]
        async for row in db.support_tickets.aggregate(pipeline):
            if not row.get("_id"):
                continue
            team.append({
                "user_id": row["_id"],
                "label": row.get("label") or row["_id"][:8],
                "avg_seconds": int(row["avg_seconds"]) if row.get("avg_seconds") is not None else None,
                "fastest_seconds": int(row["fastest_seconds"]) if row.get("fastest_seconds") is not None else None,
                "closed_count": row.get("closed_count") or 0,
            })

    return {"days": days, "me": me_block, "team": team}


# Register the API router at the very end, after every endpoint has been
# declared. This is critical: include_router() snapshots routes at call time,
# so any @api.* decorator added below this line would NOT be exposed.


# =====================================================================
# Iter35r — GET /me/welcome-briefing
# Aggregated briefing shown right after login: pending tickets (open +
# suspended), unread WA/SMS messages, and recent personal notes created
# within the configurable window (default 3 days).
# =====================================================================
@api.get("/me/welcome-briefing", tags=["Portail Client"])
async def me_welcome_briefing(user: dict = Depends(get_current_user)):
    s = await db.settings.find_one({"_id": "global"}) or {}
    notes_days = int(s.get("welcome_modal_notes_days") or 3)
    since_notes = (datetime.now(timezone.utc) - timedelta(days=notes_days)).isoformat()
    scope_filter = await _ticket_scope_for_user(user)

    # 1) Tickets en attente + suspendus
    tickets = await db.support_tickets.find(
        {**scope_filter, "status": {"$in": ["open", "suspended"]}},
        {"_id": 0, "id": 1, "number": 1, "motif": 1, "status": 1, "opened_at": 1, "contact_name": 1},
    ).sort("opened_at", -1).limit(50).to_list(50)

    # 2) Messages non lus (WhatsApp + SMS) — best-effort via /me/notifications/counts shape
    visible_scope = await _resolve_visible_client_ids(user)
    unread_wa = await db.whatsapp_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "inbound",
        "read_by_us_at": None,
    })
    unread_sms = await db.sms_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "inbound",
        "read_by_us_at": None,
    })

    # 3) Notes personnelles récentes (auteur = moi)
    recent_notes_cur = db.user_notes_personal.find(
        {"owner_id": user["id"], "created_at": {"$gte": since_notes}},
        {"_id": 0, "id": 1, "title": 1, "is_private": 1, "created_at": 1, "target_user_ids": 1},
    ).sort("created_at", -1).limit(50)
    recent_notes = [n async for n in recent_notes_cur]

    # 4) Iter35t — Santé quotidienne (motivation mini-dashboard)
    now = datetime.now(timezone.utc)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    since_24h = (now - timedelta(hours=24)).isoformat()

    # Tickets résolus hier (status closed dans la fenêtre d'hier)
    tickets_resolved_yesterday = await db.support_tickets.count_documents({
        **scope_filter,
        "status": "closed",
        "closed_at": {"$gte": yesterday_start, "$lt": yesterday_end},
    })
    # Tickets ouverts aujourd'hui
    tickets_opened_today = await db.support_tickets.count_documents({
        **scope_filter,
        "opened_at": {"$gte": today_start},
    })

    # Taux de réponse WhatsApp 24h : sortants / entrants (capé à 100%)
    wa_inbound_24h = await db.whatsapp_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "inbound",
        "received_at": {"$gte": since_24h},
    })
    wa_outbound_24h = await db.whatsapp_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "outbound",
        "sent_at": {"$gte": since_24h},
    })
    if wa_inbound_24h > 0:
        wa_response_rate = min(100, round(100 * wa_outbound_24h / wa_inbound_24h))
    else:
        wa_response_rate = None  # aucun inbound = pas de métrique pertinente

    # Messages envoyés aujourd'hui (WA + SMS)
    wa_sent_today = await db.whatsapp_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "outbound",
        "sent_at": {"$gte": today_start},
    })
    sms_sent_today = await db.sms_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "outbound",
        "sent_at": {"$gte": today_start},
    })

    daily_health = {
        "tickets_resolved_yesterday": tickets_resolved_yesterday,
        "tickets_opened_today": tickets_opened_today,
        "wa_response_rate_24h": wa_response_rate,  # None si pas d'inbound
        "wa_inbound_24h": wa_inbound_24h,
        "wa_outbound_24h": wa_outbound_24h,
        "messages_sent_today": wa_sent_today + sms_sent_today,
    }

    return {
        "tickets": tickets,
        "tickets_count": len(tickets),
        "unread_messages": {"whatsapp": unread_wa, "sms": unread_sms, "total": unread_wa + unread_sms},
        "recent_notes": recent_notes,
        "recent_notes_count": len(recent_notes),
        "recent_notes_window_days": notes_days,
        "daily_health": daily_health,
    }


app.include_router(api)
