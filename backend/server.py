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
from typing import Optional, List, Any, Dict, Tuple

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
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, Response, PlainTextResponse, HTMLResponse, StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, EmailStr, Field, field_validator

from db import db, serialize, serialize_many
from models import (
    _upper,
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

# Lot 49 — dossiers portables (backend/chemins.py) : variable UPLOAD_DIR, sinon
# /app/backend/uploads (Emergent), sinon le dossier du projet. Jamais d'erreur au démarrage.
from chemins import UPLOAD_DIR, sous_dossier as _sous_dossier  # noqa: E402
POLICIES_DIR = _sous_dossier(UPLOAD_DIR, "policies")
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


# =====================================================================
# Iter35x → Iter35y — Alexa Echo voice notifications via Voice Monkey
# Helpers extracted to /app/backend/services/alexa.py for modularity.
# Aliases kept here as thin wrappers so existing call sites still work.
# =====================================================================
from services.alexa import (  # noqa: E402  (re-export)
    ALEXA_EVENT_TYPES,
    alexa_notify as _alexa_notify_impl,
    alexa_notify_async as _alexa_notify_async_impl,
)


async def _alexa_notify(event_type: str, message: str) -> None:
    """Thin wrapper that injects `db` into the service-level helper."""
    await _alexa_notify_impl(db, event_type, message)


def _alexa_notify_async(event_type: str, message: str) -> None:
    """Sync wrapper that injects `db` into the service-level helper."""
    _alexa_notify_async_impl(db, event_type, message)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sawali")

app = FastAPI(
    title="SAWALI SMART SYSTEMS API",
    version="1.0.0",
    description=(
        "API officielle pour le site web de SAWALI SMART SYSTEMS. "
        "Tous les endpoints sont préfixés par /api. "
        "Documentation interactive : /api/docs (Swagger) et /api/redoc."
    ),
    # Iter43-fix15 (2026-03) — Swagger/Redoc/OpenAPI doivent être sous /api/*
    # pour passer par l'ingress Kubernetes (sinon 404 en production).
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    # Iter38p — Expose custom headers (e.g., X-Blocking-Ticket-Number sent by
    # the ticket-create endpoint on 409) so the frontend can read them.
    # Lot 11 — X-Ordonnance-Id : la réponse de /vidal/ordonnance/generate est
    # le PDF lui-même (Content-Type application/pdf), pas du JSON ; l'id doit
    # donc voyager en en-tête pour que le bouton "Envoi WA" puisse l'utiliser.
    expose_headers=["X-Blocking-Ticket-Id", "X-Blocking-Ticket-Number", "X-Ordonnance-Id"],
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
    # Lot 55 — IP réelle derrière Render (premier élément de X-Forwarded-For) : ip_client.py
    from ip_client import ip_reelle
    return ip_reelle(request)


def _ip_in_cidr(ip: str, cidr: str) -> bool:
    """Lot 25 — Vrai si l'adresse IP `ip` fait partie de l'entrée `cidr`
    (IP seule ou plage CIDR). Renvoie Faux si l'une des deux est invalide."""
    try:
        ip_obj = ipaddress.ip_address((ip or "").strip())
        cidr = (cidr or "").strip()
        # Même conversion que _reload_blacklist : une IP seule devient /32 (IPv4) ou /128 (IPv6).
        net = ipaddress.ip_network(cidr if "/" in cidr else (f"{cidr}/32" if "." in cidr else f"{cidr}/128"), strict=False)
        return ip_obj in net
    except (ValueError, TypeError):
        return False


async def _request_is_super_admin(request) -> bool:
    """Lot 25 — Vrai si la requête porte le jeton (Bearer) du super-admin SAWALI.

    Utilisé par le filtre IP : le super-admin n'est JAMAIS bloqué par la liste
    noire, pour qu'il puisse toujours corriger une erreur de blocage.
    En cas de jeton absent, invalide ou expiré → Faux (aucune exception)."""
    auth_header = request.headers.get("authorization") or ""
    if not auth_header.startswith("Bearer "):
        return False
    try:
        from auth import decode_token  # import local, comme ailleurs dans ce fichier
        token_data = decode_token(auth_header.split(" ", 1)[1])
        user_id = (token_data or {}).get("sub")
        if not user_id:
            return False
        u = await db.users.find_one({"id": user_id}, {"_id": 0, "email": 1})
        return bool(u) and _is_super_admin(u)
    except Exception:  # noqa: BLE001
        return False


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
                        # Lot 25 — Le super-admin SAWALI n'est jamais bloqué (vérifié
                        # seulement quand l'IP est bloquée, donc sans coût pour les autres).
                        if await _request_is_super_admin(request):
                            break
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "Adresse IP bloquée par l'administrateur."},
                        )
        except (ValueError, TypeError):
            pass
    return await call_next(request)


# Iter43-fix24az-l retest (2026-02-26) — Cloudflare 520 diagnostic middleware.
# CF 520 usually means the origin returned an empty/malformed response or reset
# the connection. Our single-worker uvicorn (--workers 1) is vulnerable to
# event-loop starvation caused by blocking sync operations (PDF generation,
# PIL watermarking, large MongoDB .to_list() calls). This middleware logs any
# request that takes > 5s so we can pinpoint the offending route.
# It also exposes an X-Process-Time header for the frontend to observe.
import time as _time_perf  # local alias — avoid clashing with other `time` uses


# Lot 29 (performances) — statistiques de temps de réponse PAR ROUTE (lectures
# comprises), gardées en mémoire depuis le dernier démarrage du serveur :
# nombre d'appels, temps total, temps maximum, appels de plus d'une seconde.
# Consultables par l'admin : GET /api/admin/perf/routes (page Santé applicative).
_PERF_STATS: Dict[str, List[float]] = {}
_PERF_SINCE = datetime.now(timezone.utc).isoformat()


def _perf_record(request, duration: float) -> None:
    """Ajoute une mesure pour la route (modèle d'URL, ex. /api/me/contacts/{cid}/messages)."""
    try:
        route = request.scope.get("route")
        tpl = getattr(route, "path", None)
        # seules les routes réelles de l'API (une adresse inconnue n'est pas comptée)
        if not tpl or not tpl.startswith("/api/"):
            return
        key = f"{request.method} {tpl}"
        s = _PERF_STATS.get(key)
        if s is None:
            if len(_PERF_STATS) > 1500:        # garde-fou mémoire
                return
            s = _PERF_STATS[key] = [0, 0.0, 0.0, 0]
        s[0] += 1
        s[1] += duration
        if duration > s[2]:
            s[2] = duration
        if duration > 1.0:
            s[3] += 1
    except Exception:  # noqa: BLE001
        pass


@app.middleware("http")
async def request_timing_middleware(request, call_next):
    _start = _time_perf.time()
    try:
        response = await call_next(request)
        duration = _time_perf.time() - _start
        _perf_record(request, duration)
        if duration > 5.0:
            try:
                logger.warning(
                    "[slow-request] %s %s took %.2fs status=%s",
                    request.method,
                    request.url.path,
                    duration,
                    getattr(response, "status_code", "?"),
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            response.headers["X-Process-Time"] = f"{duration:.3f}"
        except Exception:  # noqa: BLE001
            pass
        return response
    except Exception as exc:
        duration = _time_perf.time() - _start
        try:
            logger.error(
                "[failed-request] %s %s failed after %.2fs: %s: %s",
                request.method,
                request.url.path,
                duration,
                exc.__class__.__name__,
                str(exc)[:200],
            )
        except Exception:  # noqa: BLE001
            pass
        raise


# Iter43-fix24az-l (2026-02-26) — Cloudflare Error 520 mitigation.
# 520 is triggered when the origin returns a malformed/empty response, which
# in FastAPI can happen when an unhandled exception bubbles up above the ASGI
# middleware stack. We register a catch-all exception handler that guarantees
# a well-formed JSON response even for unexpected errors. This turns "invalid
# response" into "500 with body {detail: ...}", which Cloudflare passes back
# to the client cleanly instead of showing a 520 page.
@app.exception_handler(Exception)
async def _sawali_global_exception_handler(request, exc):
    from fastapi.exceptions import HTTPException as _FastHTTP
    if isinstance(exc, _FastHTTP):
        # Let FastAPI's normal handler do its job.
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    # Log the traceback so we can post-mortem later.
    try:
        logger.error("[unhandled] %s %s → %s: %s",
                     request.method, request.url.path,
                     exc.__class__.__name__, str(exc)[:400], exc_info=True)
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(status_code=500, content={
        "detail": "Erreur interne du serveur. Notre équipe a été notifiée.",
        "error_type": exc.__class__.__name__,
    })


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
        "can_cash": bool(u.get("can_cash", False)),
        # 2026-02 — Translator user fields exposed to /me/me
        "translator_languages": u.get("translator_languages") or [],
        "translator_rate_per_word": u.get("translator_rate_per_word") or 0,
        # 2026-02 (#5) — Admin can force logout without confirm at idle timeout
        "force_logout_on_idle": bool(u.get("force_logout_on_idle", False)),
        # 2026-02 fork (P4) — Per-user visibility overrides. None → default.
        "show_dashboard": u.get("show_dashboard"),
        "show_welcome_modal": u.get("show_welcome_modal"),
        "show_messaging_notifs": u.get("show_messaging_notifs"),
        # Iter43-fix24az-f (2026-02-26) — Business type of the tenant. Used
        # by PortalLayout.jsx to render a Fabricant-specific sidebar.
        "business_type": u.get("business_type") or "",
        # 2026-02 fork iter103 — Contract tracking (only rendered when set).
        "contract_number": u.get("contract_number") or None,
        "contract_signed_at": u.get("contract_signed_at") or None,
        "contract_amount": u.get("contract_amount") if u.get("contract_amount") is not None else None,
        "contract_currency": u.get("contract_currency") or None,
        "last_payment_at": u.get("last_payment_at") or None,
        # 2026-02 fork iter104 — Per-tenant overdue threshold + payment template.
        "contract_overdue_days": u.get("contract_overdue_days") if u.get("contract_overdue_days") is not None else None,
        "payment_confirmation_template": u.get("payment_confirmation_template") or None,
        # 2026-02 fork iter108 — S158 (Recurring billing) + S159 (Auto-suspend).
        "contract_billing_period": u.get("contract_billing_period") or None,
        "auto_suspend_after_overdue_days": u.get("auto_suspend_after_overdue_days") if u.get("auto_suspend_after_overdue_days") is not None else None,
        # Lot Liluvine (2026-09, point 4) — accès Ouvert (24/7) ou Restreint
        # (jours+heures ouvrés uniquement) pour ce contrat. Forcé à
        # "restricted" côté logique (liluvine_wa_autoreply.py) si
        # contract_amount est sous le seuil global contract_min_amount_full_access,
        # indépendamment de la valeur ici — ce champ reste néanmoins le choix
        # explicite de l'admin quand le montant est au-dessus du seuil.
        "contract_access_mode": u.get("contract_access_mode") or None,
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


# Iter43-fix24az-l (2026-02-26) — Cross-tenant data leak fix.
# The historical pattern `if user.get("role") in ("admin", "superviseur"):
# db.collection.find({})` was leaking data across tenants : a client-admin
# (e.g. ISISPHARMA admin) with role=admin could see data belonging to another
# client-tenant (e.g. SAWALI SMART SYSTEMS). Only the SAWALI internal
# super-admin (`SUPER_ADMIN_EMAIL`) should have that cross-tenant view.
def _is_super_admin(user: dict) -> bool:
    """The SAWALI internal super-admin (SUPER_ADMIN_EMAIL) has cross-tenant
    read on every collection. All other admin/superviseur roles are scoped to
    their own tenant/company via `_resolve_visible_client_ids`.

    Iter43-fix24az-l — Fixes the leak on : Rapports / Suivis / Notes / Tâches /
    Brochures / PVs / Écran de Bienvenue / Documentations / Tickets /
    Interventions / Rendez-vous / Paiements / Payment Links.
    """
    email = (user.get("email") or "").strip().lower()
    if not email:
        return False
    super_email = (os.environ.get("SUPER_ADMIN_EMAIL") or "admin@sawalismartsystems.com").strip().lower()
    return email == super_email


def _can_delete_records(user: dict) -> bool:
    """Can delete reports / suivis / interventions: only role admin/superviseur or tracked Admin/Superviseur."""
    if _is_admin_or_superviseur(user):
        return True
    return _user_tracked_role(user) in ADMIN_LEVEL_TRACKED_ROLES


# 2026-02 fork (P5) — Tenant gating helper for Formations / Formulaires /
# Documents. When an item exposes a non-empty `access_client_ids` list, only
# users whose tenant (parent_client_id or own id) figures in the list can see
# it. Admin/super-admin roles always bypass the gate.
def _tenant_id_for_gate(user: dict) -> str:
    return user.get("parent_client_id") or user.get("client_id") or user.get("id") or ""


def _item_accessible_by_tenant(item: dict, user: dict) -> bool:
    """Return True when the item is visible under the P5 access gate.

    - Admin/super-admin (role) → always True.
    - `access_client_ids` empty / missing → True (legacy behaviour).
    - Otherwise → True only if the user's tenant is listed.
    """
    if _is_admin_or_superviseur(user):
        return True
    allow = item.get("access_client_ids") or []
    if not allow:
        return True
    return _tenant_id_for_gate(user) in allow


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


async def _check_descent_window(action_label: str = "enregistrement", user: Optional[dict] = None) -> None:
    """Raise HTTP 403 if current time is past `descent_time + 1h`.
    `descent_time` is a HH:MM stored in settings (today's reference). If unset, no check.

    Iter36j — Admin / Superviseur / Moderation are NEVER blocked by this
    window: they can record reports / suivis / notes at any time. The lock
    only applies to standard tracked users (agents on site).
    """
    if user is not None and _is_elevated_creator(user):
        return  # Bypass the 1h lock for elevated creators
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


# =====================================================================
# Découpage physique de server.py (lot 28) — voir server_parts/README.md
# Chaque partie ci-dessous est un morceau de l'ancien server.py, recopié à
# l'identique et exécuté ICI, dans le même espace de noms que ce fichier :
# mêmes variables globales, même ordre d'exécution qu'avant le découpage.
# =====================================================================
def _inclure_partie(nom: str) -> None:
    """Exécute server_parts/<nom> dans l'espace de noms de server.py."""
    import __future__ as _fut
    _chemin = ROOT_DIR / "server_parts" / nom
    # même option que ce fichier (from __future__ import annotations)
    _code = compile(_chemin.read_text(encoding="utf-8"), str(_chemin), "exec",
                    flags=_fut.annotations.compiler_flag, dont_inherit=True)
    exec(_code, globals())  # noqa: S102 — code du projet, pas de donnée externe


_inclure_partie("p01_sante_auth_public.py")  # Santé, authentification, pages publiques (catalogue, RDV, contact), jauge support, redirection Liluvine


_inclure_partie("p02_portail_client_paiements.py")  # Portail client, agent agenda n8n, PawaPay, tableau de bord paiements, liens de paiement, accès barre latérale, facturation des interventions


_inclure_partie("p03_admin_clients_usage.py")  # Portail superviseur, Admin → Clients, fonctionnalités SMART Communications, tableau d'usage, activité des utilisateurs


_inclure_partie("p04_admin_sauvegardes_diagnostics.py")  # Instantanés de base, sauvegarde auto, feuille de route, coffre de secrets, diagnostics clients, efficacité des campagnes


_inclure_partie("p05_admin_crm_documents.py")  # CRM, paiements des tenants, rendez-vous, interventions, documents, catégories, déploiements, téléversement, stockage, politiques


_inclure_partie("p06_medias_ia_version_cms.py")  # Médiathèque, transcription audio, synthèse IA, version de la plateforme, contenus du site (CMS)


_inclure_partie("p07_admin_utilisateurs_suivis.py")  # Utilisateurs suivis, transfert, messages reçus, liste noire IP, logo du portail


_inclure_partie("p08_notes_portail_journaux.py")  # Rapports & suivis, note de service, portail (interventions, documents, contacts), notes étoilées, journaux d'accès, traces API


_inclure_partie("p09_supervision_parametres.py")  # Supervision santé, contrôle d'authentification, disponibilité, Admin → Paramètres, audit des secrets, abonnés incidents, documentation API


_inclure_partie("p10_site_public_marketing.py")  # Témoignages NPS, sitemap/robots, études de cas, blog, newsletter, pastilles du menu, fil d'activité


_inclure_partie("p11_whatsapp.py")  # WhatsApp Business API : répertoire de contacts, envois, médias, statistiques, rapprochement des messages


_inclure_partie("p12_sms.py")  # Passerelle SMS multi-opérateurs, Orange, envois groupés et planifiés


_inclure_partie("p13_whatsapp_supervision.py")  # Détecteur de silence WhatsApp, santé des intégrations, simulation de message entrant


_inclure_partie("p14_whatsapp_admin_automations.py")  # Messagerie WhatsApp groupée (admin), automatisations, envois WhatsApp planifiés


_inclure_partie("p15_formulaires.py")  # Formulaires dynamiques et leurs statistiques


_inclure_partie("p16_liens_visiteurs_formations.py")  # Liens cryptés, suivi des visiteurs, formations


_inclure_partie("p17_demarrage_planificateur.py")  # Démarrage, alertes contrats en retard, rappels de facturation, planificateur (APScheduler)


_inclure_partie("p18_abonnements_tickets.py")  # Abonnements, tickets d'intervention et leurs exports


_inclure_partie("p19_briefing_accueil.py")  # Briefing d'accueil après connexion


_inclure_partie("p20_branchement_routeurs.py")  # Branchement des routeurs des modules routes/* (SMS, chat, caisse, GRH, Meta, etc.)



# Migration vers Render : sauvegarde complète (base -> MongoDB Atlas, fichiers/archives/secrets -> R2)
from routes.migration_render import router as _migration_render_router  # noqa: E402
api.include_router(_migration_render_router)

# Lot 47 — sauvegardes de migration programmées, rétention dans R2 et rapport Liluvine à l'admin.
# Envoi WhatsApp (texte ou modèle Meta) et e-mail : fonctions existantes du serveur.
from routes.migration_programmation import (  # noqa: E402
    router as _migration_programmation_router, configurer as _migration_programmation_configurer,
    demarrer as _migration_programmation_demarrer,
)
api.include_router(_migration_programmation_router)
_migration_programmation_configurer(envoyer_wa_texte=_wa_send_text, envoyer_wa_modele=_wa_send_template,
                                    email_defaut=SUPER_ADMIN_EMAIL)

# Lot 49 — sauvegarde / transfert des données : export et import complets chiffrés, restauration
# initiale d'un site neuf (page /restauration), sauvegarde quotidienne vers R2 (planifiée dans p17).
from routes.sauvegarde_complete import (  # noqa: E402
    router as _sauvegarde_complete_router, router_public as _sauvegarde_complete_public,
    configurer as _sauvegarde_complete_configurer,
)
api.include_router(_sauvegarde_complete_router)
api.include_router(_sauvegarde_complete_public)
_sauvegarde_complete_configurer(envoyer_email=send_email, email_defaut=SUPER_ADMIN_EMAIL)

# Lot 50 — maintenance de la plateforme (déconnexion de tous les utilisateurs, règle R8),
# abonnements (grâce puis coupure côté serveur), sessions des comptes (limite d'appareils,
# inactivité contrôlée par le serveur), date de la dernière sauvegarde. Les contrôles de chaque
# requête sont faits dans auth.get_current_user (controle_acces.py) ; les refus portent un code
# lisible par le site ({"detail", "code"}).
from controle_acces import RefusAcces as _RefusAcces, gestionnaire_refus as _gestionnaire_refus  # noqa: E402
from routes.maintenance_plateforme import public as _maintenance_public, admin as _maintenance_admin  # noqa: E402
from routes.abonnements_sessions import router as _abonnements_sessions_router  # noqa: E402
app.add_exception_handler(_RefusAcces, _gestionnaire_refus)
api.include_router(_maintenance_public)
api.include_router(_maintenance_admin)
api.include_router(_abonnements_sessions_router)


# Lot 51 — cycle de vie du non-renouvellement (spécification commune, point C) : suspension à J+110,
# archive chiffrée vérifiée puis suppression à J+113, avertissements J+103 / J+110 / J+112,
# conservation des archives, réouverture avec frais. Interrupteur désactivé par défaut ; tâche
# quotidienne programmée dans p17 (jamais avec DISABLE_SCHEDULER=1 ni dans la preview).
from routes.cycle_vie_abonnements import router as _cycle_vie_router  # noqa: E402
import cycle_vie_abonnements as _cycle_vie  # noqa: E402
api.include_router(_cycle_vie_router)
_cycle_vie.configurer(envoyer_email=send_email, envoyer_wa=_wa_send_text, email_admin=SUPER_ADMIN_EMAIL)


@app.on_event("shutdown")
async def _sentinelle_arret():
    """Lot 73 — arrêt du serveur : la sentinelle ne compte plus l'arrêt normal comme un blocage."""
    try:
        import sentinelle_boucle
        sentinelle_boucle.arreter()
    except Exception:  # noqa: BLE001
        pass


@app.on_event("startup")
async def _sentinelle_et_prechauffage():
    """Lot 71.1 — (1) sentinelle : écrit dans les journaux la ligne de code qui fige le serveur si la
    boucle principale ne répond plus pendant 1,5 s ; (2) préchauffage : importe qdrant_client dans un
    fil séparé, pour que la première ouverture des Paramètres ne fige plus le serveur. Jamais bloquant."""
    try:
        import sentinelle_boucle
        sentinelle_boucle.demarrer()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sentinelle] non démarrée : %s", exc)
    try:
        from routes.qdrant_rag import prechauffer_modules
        asyncio.get_running_loop().run_in_executor(None, prechauffer_modules)  # en arrière-plan, sans attendre
        # Lot 71.2 — SDK d'IA (anthropic, openai, google.genai) préchargés aussi : le premier message
        # WhatsApp après un redémarrage figeait le serveur ~3 s (import d'anthropic dans la boucle)
        from ia_client import prechauffer_sdk
        asyncio.get_running_loop().run_in_executor(None, prechauffer_sdk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[prechauffage] non lancé : %s", exc)


@app.on_event("startup")
async def _index_cycle_vie():
    """Lot 51 — index des avertissements (envoi unique) et du journal : jamais bloquant."""
    try:
        await _cycle_vie.assurer_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cycle-vie] index non créés au démarrage : %s", exc)


# Lot 52 — choix du service d'envoi des e-mails (Resend, ZeptoMail, Brevo, SMTP), réservé au
# super-admin. `send_email` garde sa signature ; clés et mot de passe SMTP chiffrés en base.
from routes.fournisseurs_email import router as _email_fournisseur_router  # noqa: E402
import email_fournisseurs as _email_fournisseurs  # noqa: E402
api.include_router(_email_fournisseur_router)


@app.on_event("startup")
async def _demarrer_email_fournisseurs():
    """Lot 52 — index des journaux d'envoi et chiffrement de l'ancien mot de passe SMTP : jamais bloquant."""
    try:
        await _email_fournisseurs.assurer_index()
        await _email_fournisseurs.migrer_ancien_mot_de_passe_smtp()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[email] index ou migration du mot de passe SMTP non faits au démarrage : %s", exc)


# Lot 54 — pastille de présence des utilisateurs suivis (vert / orange / rouge, sessions du lot 50) ;
# tickets partagés par client et sessions WhatsApp minutées : tickets_clients.py (routes dans p18,
# tâche minute dans p17) ; rôle « Auxiliaire en Pharmacie » : roles_restreints.py (controle_acces).
from routes.presence_utilisateurs import router as _presence_router  # noqa: E402
api.include_router(_presence_router)

# Lot 55 — dernière connexion, IP et historique des connexions des utilisateurs suivis ; blocage
# ou autorisation d'une IP par compte (connexions_ip.py, contrôle dans sessions_comptes.controler).
from routes.connexions_ip import router as _connexions_ip_router  # noqa: E402
api.include_router(_connexions_ip_router)

# Lot 57.8 — Encaissement PI-SPI (BCEAO) : paramètres globaux (super-admin), bloc « Payer par
# PI-SPI » sur les factures émises par SAWALI, encaissements (pispi_transactions), connecteur
# manuel seul actif et route de notification bancaire désactivée : routes/pispi.py.
from routes.pispi import router as _pispi_router  # noqa: E402
api.include_router(_pispi_router)


@app.on_event("startup")
async def _index_connexions_ip():
    """Lot 55 — index (user_id, date), TTL de 180 jours du journal des connexions : jamais bloquant."""
    try:
        import connexions_ip
        await connexions_ip.assurer_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[connexions] index non créés au démarrage : %s", exc)


@app.on_event("startup")
async def _index_tickets_clients():
    """Lot 54 — index des tickets partagés et du journal des sessions WhatsApp : jamais bloquant."""
    try:
        await _tickets_clients.assurer_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[tickets] index non créés au démarrage : %s", exc)


@app.on_event("startup")
async def _index_sessions_comptes():
    """Lot 50 — index des sessions des comptes (TTL sur l'expiration) : jamais bloquant."""
    try:
        import sessions_comptes
        await sessions_comptes.assurer_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sessions] index non créés au démarrage : %s", exc)


@app.on_event("startup")
async def _demarrer_migration_programmation():
    """Boucle des sauvegardes programmées (toutes les 60 s). Jamais dans la preview (sa base est
    une copie de la production) : mêmes règles que le planificateur (DISABLE_SCHEDULER, SCHEDULER_IN_PREVIEW)."""
    if os.environ.get("DISABLE_SCHEDULER") == "1" or (
            _is_preview_environment() and os.environ.get("SCHEDULER_IN_PREVIEW") != "1"):
        logger.info("[migration-programmation] planificateur non démarré (preview ou DISABLE_SCHEDULER)")
        return
    _migration_programmation_demarrer()

# Lot 71.3 — Paramètres → « ⚡ Santé du serveur » : sentinelle active et derniers blocages de la boucle
@api.get("/admin/sentinelle", tags=["Admin"])
async def admin_sentinelle(_: dict = Depends(get_admin_or_supervisor)):
    import sentinelle_boucle
    return sentinelle_boucle.etat()


app.include_router(api)


# =====================================================================
# S036 — Admin endpoint to test the Liluvine escalation flow without
# waiting for Liluvine to emit [ESCALATE]. Sends a synthetic notification
# to the configured admin phone.
# Declared on the FastAPI app directly (the api router has already been
# included above).
# =====================================================================
@app.post("/api/admin/liluvine-escalation/test", tags=["Admin"])
async def admin_test_liluvine_escalation(user: dict = Depends(get_admin_or_supervisor)):
    from routes.liluvine_escalation import notify_admin as _esc_notify
    res = await _esc_notify(
        db,
        contact_name="Contact de test",
        contact_phone_digits="22500000000",
        last_user_message=(
            "Bonjour, j'ai un problème urgent avec ma facture #12345 — pouvez-vous m'aider rapidement ?"
        ),
        reason="Test manuel depuis Admin Settings — vérification du canal WhatsApp",
        send_wa=_wa_send_text,
        session_id="admin-test",
        history=None,
    )
    return res


# =====================================================================
# Iter36i — Kubernetes liveness/readiness probe endpoint.
# The deployment platform hits GET /health every few seconds. Without this
# endpoint the probe receives 404 and eventually marks the pod unhealthy
# (= deployment failure). Returns a lightweight JSON (no DB hit) so the
# probe is fast and resilient to MongoDB hiccups.
# =====================================================================
@app.get("/health", include_in_schema=False)
async def health_check():
    return {"status": "ok", "service": "sawali-backend"}


@app.get("/healthz", include_in_schema=False)
async def health_check_alt():
    return {"status": "ok", "service": "sawali-backend"}
