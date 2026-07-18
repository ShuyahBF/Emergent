"""Iter41 (2026-02) — Module VIDAL France (REST API Sécurisation 2025.12).

Wraps the VIDAL REST API to provide three high-value capabilities inside the
SAWALI portal:

  1. **Recherche médicament + monographie (RCP)** — search a drug and pull its
     `FULL_MONO` / `RCP` documents.
  2. **Catalogue produits & statuts réglementaires** — filter by `NEW`,
     `AVAILABLE`, `DELETED`, `PHARMACO`.
  3. **Analyse de prescription / alertes interactions** — POST a patient +
     prescription set to `/alerts/full` and surface the alerts (allergies,
     contre-indications, interactions, posologies suspectes…).

Design choices:
  - Two credential sets (test / production) live in `settings.global` and are
    masked via `GET_MASK_FIELDS` in `routes/admin_settings.py`.
  - `vidal_mode = "test" | "production"` selects which one is used.
  - Mongo cache `vidal_cache` keyed by `(env, method, path, query_sig)` with a
    configurable TTL (default 7 days). Honors `Cache-Control: no-cache`-style
    bypass via `?_fresh=1`.
  - Per-user daily quota stored in `vidal_usage_daily`. 0 = unlimited.
  - All HTTP errors from VIDAL bubble up as 502 with a sanitized detail.

The router is mounted by `server.py` via `attach_vidal_routes(api, db, …)`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import Body, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

logger = logging.getLogger("sawali.vidal")

# Default URLs published by VIDAL France (can be overridden in AdminSettings).
DEFAULT_TEST_BASE_URL = "https://api-test.vidal.net/rest/api"
DEFAULT_PROD_BASE_URL = "https://api.vidal.net/rest/api"
DEFAULT_CACHE_TTL_HOURS = 168     # 7 days
DEFAULT_QUOTA_PER_DAY = 200       # per user
DEFAULT_HTTP_TIMEOUT = 12         # seconds

# Iter43-fix24u (2026-06-16) — Public path prefix for the in-process proxy that
# transmits HTTP requests to VIDAL on behalf of the iframe-rendered Angular SPA.
# When the iframe renders the VIDAL HTML response, all relative resources
# (CSS, JS, XHR endpoints) resolve against `<base href>` injected by the
# backend — pointing here makes them transit through our proxy and reach the
# VIDAL origin without CORS issues.
VIDAL_PROXY_PREFIX = "/api/vidal/proxy"


# --------------------------------------------------------------------------- #
# Pydantic payloads
# --------------------------------------------------------------------------- #
class VidalConfigPayload(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None  # "test" | "production"
    test_base_url: Optional[str] = None
    test_app_id: Optional[str] = None
    test_app_key: Optional[str] = None
    prod_base_url: Optional[str] = None
    prod_app_id: Optional[str] = None
    prod_app_key: Optional[str] = None
    cache_ttl_hours: Optional[int] = None
    quota_per_user_per_day: Optional[int] = None
    http_timeout: Optional[int] = None
    # Iter43-fix24az-k (2026-02-26) — VIDAL webhook proxy config.
    # When webhook_enabled=True, every VIDAL call is routed through
    # `webhook_outbound_url` (POST JSON) and the backend waits synchronously
    # for the external system to callback `/api/vidal/webhook/callback` with
    # the JSON response. Fallback to direct VIDAL when disabled.
    webhook_enabled: Optional[bool] = None
    webhook_outbound_url: Optional[str] = None
    webhook_timeout_seconds: Optional[int] = None


class VidalWebhookCallbackPayload(BaseModel):
    """Payload received on the inbound callback endpoint.
    The external system MUST include the `correlation_id` returned in the
    original outbound POST, plus the VIDAL response body + metadata.
    """
    correlation_id: str
    status_code: Optional[int] = 200
    content_type: Optional[str] = "application/json"
    # Either `body` (parsed JSON dict/list) OR `raw` (raw string) — one of the two.
    body: Optional[Any] = None
    raw: Optional[str] = None
    error: Optional[str] = None


class PrescriptionAnalysisPayload(BaseModel):
    """Mirror of the VIDAL `/alerts/full` body, simplified.

    Iter43-fix24y — VIDAL exige du XML pour `/alerts/full`. On accepte deux
    modes : (a) champs structurés que le backend convertit en XML, ou
    (b) `xml_body` raw que le backend envoie tel quel à VIDAL (utile pour
    coller la structure exacte du manuel d'intégration VIDAL).
    """
    patient: Optional[Dict[str, Any]] = None  # birth_date, sex, weight_kg, ...
    prescriptions: List[Dict[str, Any]] = []  # [{ vidal_id, dose, ... }]
    allergies: Optional[List[str]] = None
    pathologies: Optional[List[str]] = None
    xml_body: Optional[str] = None             # Override : XML brut


def _build_alerts_xml(patient: Dict[str, Any], prescriptions: List[Dict[str, Any]],
                      allergies: List[str], pathologies: List[str]) -> str:
    """Construit un body XML pour POST /alerts/full.

    Best-effort en attendant la spec exacte du manuel d'intégration VIDAL.
    L'utilisateur peut passer `xml_body` raw pour bypasser cette construction.
    """
    import xml.etree.ElementTree as ET
    root = ET.Element("alertsRequest")
    if patient:
        p = ET.SubElement(root, "patient")
        for k, v in patient.items():
            if v is None:
                continue
            ET.SubElement(p, str(k)).text = str(v)
    if prescriptions:
        pres = ET.SubElement(root, "prescriptions")
        for prescription in prescriptions:
            pr = ET.SubElement(pres, "prescription")
            for k, v in (prescription or {}).items():
                if v is None:
                    continue
                ET.SubElement(pr, str(k)).text = str(v)
    if allergies:
        a = ET.SubElement(root, "allergies")
        for al in allergies:
            ET.SubElement(a, "allergy").text = str(al)
    if pathologies:
        path = ET.SubElement(root, "pathologies")
        for pa in pathologies:
            ET.SubElement(path, "pathology").text = str(pa)
    xml_str = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


# --------------------------------------------------------------------------- #
# Helpers (DB + HTTP)
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_str() -> str:
    return _now().date().isoformat()


def _clean_vidal_base_url(raw: str) -> str:
    """Sanitize a VIDAL base_url that the admin may have mis-pasted.

    Iter43-fix24ab (2026-06-16) — Cas connus à corriger automatiquement :
        Bon  : https://api.vidal.fr/rest/api
        Mauvais 1 : http://api.vidal.fr/#!/rest/api  (URL Angular API explorer)
        Mauvais 2 : http://api.vidal.fr/#!/rest/api/authentication  (endpoint test only)
        Mauvais 3 : https://api.vidal.fr/rest/api/authentication  (endpoint test only)

    Le `/authentication` n'est PAS un préfixe d'API — c'est l'endpoint que le
    navigateur Angular utilise pour tester les credentials manuellement. Il ne
    doit jamais être concaténé devant les vraies actions (`/products`, etc.).
    On le retire automatiquement si présent en suffixe du base_url.

    On déplie aussi le hashbang (`#!/`) et on force HTTPS.
    """
    if not raw:
        return ""
    u = str(raw).strip()
    # 1) Déplie le hashbang Angular en URL serveur normale
    if "#" in u:
        before, after = u.split("#", 1)
        after = after.lstrip("!")
        if after and after.strip("/"):
            u = before.rstrip("/") + ("/" + after.lstrip("/"))
        else:
            u = before
    # 2) Force HTTPS (VIDAL n'accepte pas HTTP)
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    # 3) Nettoyage du trailing slash
    u = u.rstrip("/")
    # 4) Iter43-fix24ab — Strip `/authentication` suffix if present :
    #    l'admin a confondu l'endpoint de test avec le base_url.
    if u.endswith("/authentication"):
        u = u[: -len("/authentication")]
    return u


async def _load_config(db, tenant_mode_override: Optional[str] = None) -> Dict[str, Any]:
    """Load VIDAL config from settings.global.

    `tenant_mode_override` allows a per-tenant `vidal_mode` (test|production)
    to take precedence over the global `vidal_mode` setting. Use values
    "test", "production" or None/"inherit" to fall back to global.

    Iter43-fix24y (2026-06-16) — Auto-déplie les URLs avec `#!/` (hashbang
    Angular = uniquement pour le navigateur, jamais pour l'API). Force aussi
    `https` car VIDAL refuse les requêtes HTTP. Cf. doc utilisateur :
        Bon  : https://api.vidal.fr/rest/api/products?app_id=X&app_key=Y&q=doliprane
        Mauvais : http://api.vidal.fr/#!/rest/api/products?...
    """
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    # Per-tenant override wins when set to a concrete mode.
    if tenant_mode_override in ("test", "production"):
        mode = tenant_mode_override
    else:
        mode = (s.get("vidal_mode") or "test").lower()
        if mode not in ("test", "production"):
            mode = "test"
    if mode == "production":
        base = _clean_vidal_base_url(s.get("vidal_prod_base_url") or DEFAULT_PROD_BASE_URL)
        app_id = (s.get("vidal_prod_app_id") or "").strip()
        app_key = (s.get("vidal_prod_app_key") or "").strip()
    else:
        base = _clean_vidal_base_url(s.get("vidal_test_base_url") or DEFAULT_TEST_BASE_URL)
        app_id = (s.get("vidal_test_app_id") or "").strip()
        app_key = (s.get("vidal_test_app_key") or "").strip()
    return {
        "enabled": bool(s.get("vidal_enabled")),
        "mode": mode,
        "base_url": base,
        "app_id": app_id,
        "app_key": app_key,
        "cache_ttl_hours": int(s.get("vidal_cache_ttl_hours") or DEFAULT_CACHE_TTL_HOURS),
        "quota_per_day": int(s.get("vidal_quota_per_user_per_day") or DEFAULT_QUOTA_PER_DAY),
        "http_timeout": int(s.get("vidal_http_timeout") or DEFAULT_HTTP_TIMEOUT),
        # Iter43-fix24az-k — webhook proxy config
        "webhook_enabled": bool(s.get("vidal_webhook_enabled")),
        "webhook_outbound_url": (s.get("vidal_webhook_outbound_url") or "").strip(),
        "webhook_timeout_seconds": int(s.get("vidal_webhook_timeout_seconds") or 30),
    }


async def _resolve_tenant_vidal(db, user: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve VIDAL feature flag + per-tenant mode for an authenticated user.

    Returns dict {tenant_enabled: bool, tenant_mode: "test"|"production"|"inherit"}.
    Walks `parent_client_id` chain so moderators inherit the SAME tenant config
    as the admin who created them.
    """
    role = user.get("role")
    scope_uid = user.get("id")
    if role in ("client", "tracked", "moderateur", "regulateur", "pharmacien", "medecin", "editeur_vidal"):
        scope_uid = user.get("parent_client_id") or user.get("client_id") or scope_uid
    tenant = await db.users.find_one({"id": scope_uid}, {"_id": 0, "features": 1, "tenant_type": 1}) or {}
    feats = tenant.get("features") or {}
    return {
        "tenant_enabled": bool(feats.get("vidal_enabled")),
        "tenant_mode": (feats.get("vidal_mode") or "inherit").lower(),
        "tenant_type": (tenant.get("tenant_type") or "").lower(),
        "scope_uid": scope_uid,
    }


def _ensure_active(cfg: Dict[str, Any]) -> None:
    if not cfg["enabled"]:
        raise HTTPException(status_code=503, detail="Module VIDAL désactivé (AdminSettings).")
    if not cfg["app_id"] or not cfg["app_key"]:
        raise HTTPException(
            status_code=503,
            detail=f"Identifiants VIDAL ({cfg['mode']}) manquants dans AdminSettings.",
        )


async def _ensure_tenant_can_access(db, user: Dict[str, Any]) -> Dict[str, Any]:
    """Verify the user's tenant has VIDAL enabled. Returns the cfg with the
    tenant-mode applied. Raises 403 when the feature is OFF for this tenant.
    Admins always pass through.
    """
    if user.get("role") in ("admin", "superviseur"):
        return await _load_config(db)
    tenant_info = await _resolve_tenant_vidal(db, user)
    if not tenant_info["tenant_enabled"]:
        raise HTTPException(
            status_code=403,
            detail="Module VIDAL non activé pour votre établissement. Contactez votre administrateur.",
        )
    return await _load_config(db, tenant_mode_override=tenant_info["tenant_mode"])


def _cache_key(env: str, method: str, path: str, params: Dict[str, Any], body: Optional[Dict[str, Any]] = None) -> str:
    payload = json.dumps({"e": env, "m": method, "p": path, "q": params or {}, "b": body or {}}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _cache_get(db, key: str, ttl_hours: int) -> Optional[Dict[str, Any]]:
    doc = await db.vidal_cache.find_one({"_id": key}, {"payload": 1, "stored_at": 1})
    if not doc:
        return None
    stored_at = doc.get("stored_at")
    if not stored_at:
        return None
    if isinstance(stored_at, str):
        try:
            stored_at = datetime.fromisoformat(stored_at.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return None
    # Mongo returns naive datetimes — normalise to UTC for arithmetic.
    if isinstance(stored_at, datetime) and stored_at.tzinfo is None:
        stored_at = stored_at.replace(tzinfo=timezone.utc)
    if _now() - stored_at > timedelta(hours=ttl_hours):
        return None
    payload = doc.get("payload")
    # Iter43-fix24w (2026-06-16) — Bypass cache for raw HTML/XML responses.
    # These come back when VIDAL returns its Angular API explorer or an error
    # page. They should be re-fetched every time so:
    #   1) The latest `<base>` injection from `_vidal_call` is applied.
    #   2) Users see the current state (not yesterday's cached error page).
    if isinstance(payload, dict) and payload.get("raw"):
        return None
    return payload


async def _cache_set(db, key: str, payload: Dict[str, Any]) -> None:
    # Iter43-fix24w — Ne pas mettre en cache les réponses brutes (HTML/XML).
    # Le cache n'a de valeur que pour les réponses JSON structurées.
    if isinstance(payload, dict) and payload.get("raw"):
        return
    try:
        await db.vidal_cache.update_one(
            {"_id": key},
            {"$set": {"payload": payload, "stored_at": _now()}},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("[vidal] cache_set failed", exc_info=True)


async def _quota_check_and_increment(db, user_id: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Enforce per-user/day quota. Returns {used, limit, blocked}.

    Returns blocked=True with a 429 HTTPException raised when the limit is reached.
    """
    limit = cfg["quota_per_day"]
    if limit <= 0:  # unlimited
        return {"used": 0, "limit": 0, "blocked": False}
    today = _today_str()
    doc = await db.vidal_usage_daily.find_one_and_update(
        {"user_id": user_id, "day": today},
        {"$inc": {"count": 1}, "$set": {"updated_at": _now()}},
        upsert=True,
        return_document=True,
    ) or {}
    used = int(doc.get("count") or 1)
    if used > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Quota VIDAL journalier dépassé ({limit} requêtes/jour).",
        )
    return {"used": used, "limit": limit, "blocked": False}


# ────────────────────────────────────────────────────────────────────────────
# Iter43-fix24az-k (2026-02-26) — VIDAL Webhook proxy
#
# When cfg.webhook_enabled is True, every VIDAL call is routed through an
# external system (e.g. n8n / Zapier / custom bridge) instead of hitting VIDAL
# directly. The flow is :
#
#   1. Backend generates a correlation_id.
#   2. Backend POSTs a JSON envelope to `cfg.webhook_outbound_url` describing
#      the request that would have been sent to VIDAL (method, url, params,
#      body, headers, callback_url).
#   3. Backend blocks (asyncio.Event, up to `webhook_timeout_seconds`).
#   4. External system executes the actual VIDAL request and POSTs the JSON
#      response to `/api/vidal/webhook/callback` with the same correlation_id.
#   5. Backend unblocks and returns the response to the caller as if VIDAL had
#      answered directly.
#
# In-memory correlation map — good enough for a single-instance deployment.
# For multi-instance / horizontally-scaled backends, this should move to
# MongoDB + polling (future work, S089-P3).
# ────────────────────────────────────────────────────────────────────────────

_correlation_lock = asyncio.Lock()
_correlations: Dict[str, Dict[str, Any]] = {}


def _dispatch_callback_url() -> str:
    """Compute the absolute URL of the inbound webhook callback endpoint.

    Priority order:
      1. `PUBLIC_APP_URL` env var (custom prod domain if set separately)
      2. `PUBLIC_BASE_URL` env var — canonical name already used elsewhere in
         SAWALI backend (preview + prod).
      3. `SAWALI_PUBLIC_BASE_URL` (legacy alias)
      4. Hardcoded `https://sawalismartsystems.com` (safe production fallback).
    """
    base = (
        os.environ.get("PUBLIC_APP_URL")
        or os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("SAWALI_PUBLIC_BASE_URL")
        or "https://sawalismartsystems.com"
    ).rstrip("/")
    return f"{base}/api/vidal/webhook/callback"


async def _dispatch_via_webhook(
    cfg: Dict[str, Any],
    method: str,
    path: str,
    params: Optional[Dict[str, Any]],
    body: Optional[Any],
    return_debug: bool = False,
    tenant_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> Dict[str, Any]:
    """Route a single VIDAL request through the configured external webhook.

    Blocks until the callback arrives or the timeout elapses. Returns the
    same shape as `_vidal_call` so the caller code doesn't have to know
    which transport was used.
    """
    outbound = (cfg.get("webhook_outbound_url") or "").strip()
    if not outbound:
        # Config missing — fail loudly so the admin fixes it.
        return {
            "raw": "[VIDAL webhook activé mais webhook_outbound_url manquant]",
            "_error": {
                "status": 0, "content_type": "text/plain",
                "message": "Configuration webhook VIDAL incomplète (URL sortante manquante).",
                "url": "(webhook)",
            },
            "_request": {"method": method.upper(), "url": path, "params": params or {}, "body": body},
        }

    correlation_id = str(uuid.uuid4())
    # Note: we deliberately do NOT append app_id/app_key here — the external
    # system is expected to know how to reach VIDAL. The URL we send is just
    # the endpoint path + base for reference.
    full_url = f"{cfg.get('base_url', '')}{path}"
    envelope = {
        "correlation_id": correlation_id,
        "tenant_id": tenant_id,
        "user_email": user_email,
        "method": method.upper(),
        "url": full_url,
        "path": path,
        "params": params or {},
        "body": body,
        "headers": {
            "Accept": "application/atom+xml, application/xml, application/json;q=0.5",
        },
        "callback_url": _dispatch_callback_url(),
        "timestamp": _now().isoformat(),
        "vidal_mode": cfg.get("mode"),
    }

    debug: Dict[str, Any] = {
        "request": {
            "method": method.upper(),
            "url": outbound,
            "params": {},
            "body": envelope,
            "timeout_seconds": cfg.get("webhook_timeout_seconds") or 30,
            "mode": cfg.get("mode"),
            "transport": "webhook",
        },
        "response": None,
        "error": None,
    }

    # Register the correlation entry before the outbound POST (avoid a race
    # where the external system responds faster than we register).
    ev = asyncio.Event()
    async with _correlation_lock:
        _correlations[correlation_id] = {"event": ev, "response": None, "created_at": _now()}

    try:
        # Fire the outbound POST.
        async with httpx.AsyncClient(timeout=int(cfg.get("webhook_timeout_seconds") or 30)) as client:
            resp = await client.post(outbound, json=envelope, headers={"Content-Type": "application/json"})
        outbound_status = resp.status_code
        outbound_snippet = (resp.text or "")[:400]
        if outbound_status >= 400:
            async with _correlation_lock:
                _correlations.pop(correlation_id, None)
            debug["error"] = f"Outbound webhook returned HTTP {outbound_status}: {outbound_snippet}"
            if return_debug:
                return {"_error": True, "_debug": debug}
            return {
                "raw": f"[Webhook VIDAL erreur {outbound_status}]\n\n{outbound_snippet}",
                "_error": {
                    "status": outbound_status,
                    "content_type": "text/plain",
                    "message": f"Webhook sortant a échoué : HTTP {outbound_status}",
                    "url": outbound,
                },
                "_request": envelope,
            }
    except httpx.HTTPError as exc:
        async with _correlation_lock:
            _correlations.pop(correlation_id, None)
        debug["error"] = f"Outbound webhook HTTPError: {str(exc)[:300]}"
        if return_debug:
            return {"_error": True, "_debug": debug}
        return {
            "raw": f"[Webhook VIDAL injoignable]\n\n{exc!s}",
            "_error": {"status": 0, "content_type": "text/plain",
                       "message": f"Webhook sortant injoignable : {str(exc)[:300]}",
                       "url": outbound},
            "_request": envelope,
        }

    # Wait for the callback with a timeout.
    timeout_s = int(cfg.get("webhook_timeout_seconds") or 30)
    try:
        await asyncio.wait_for(ev.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        async with _correlation_lock:
            _correlations.pop(correlation_id, None)
        debug["error"] = f"Callback timeout after {timeout_s}s"
        if return_debug:
            return {"_error": True, "_debug": debug}
        return {
            "raw": f"[Webhook VIDAL — timeout après {timeout_s}s]",
            "_error": {"status": 504, "content_type": "text/plain",
                       "message": f"Aucune callback reçue après {timeout_s}s (correlation_id={correlation_id}).",
                       "url": outbound},
            "_request": envelope,
        }

    # Callback arrived — grab & cleanup.
    async with _correlation_lock:
        entry = _correlations.pop(correlation_id, None)
    payload = (entry or {}).get("response") or {}

    resp_body = payload.get("body")
    raw_str = payload.get("raw")
    ctype = payload.get("content_type") or "application/json"
    status_code = int(payload.get("status_code") or 200)
    error_msg = payload.get("error")

    debug["response"] = {
        "status_code": status_code,
        "content_type": ctype,
        "elapsed_ms": None,  # not tracked here
        "body_preview": (raw_str or json.dumps(resp_body)[:400] if resp_body is not None else "")[:400],
    }

    if error_msg or status_code >= 400:
        if return_debug:
            return {"_error": True, "_debug": debug}
        return {
            "raw": raw_str or (error_msg or f"[VIDAL webhook error {status_code}]"),
            "_request": envelope,
            "_error": {"status": status_code, "content_type": ctype,
                       "message": error_msg or f"HTTP {status_code}",
                       "url": full_url},
        }

    # Success — return the response body. Try to preserve `_data` field so
    # downstream code (which sometimes reads it) still works.
    result: Dict[str, Any] = {}
    if resp_body is not None:
        if isinstance(resp_body, dict):
            result = dict(resp_body)
        else:
            result = {"_data": resp_body}
    if raw_str is not None:
        result["raw"] = raw_str
    if return_debug:
        result["_debug"] = debug
    return result


async def _webhook_deliver(correlation_id: str, payload: Dict[str, Any]) -> bool:
    """Store the callback response for `correlation_id` and unblock the waiter.

    Returns True if the correlation was found + delivered ; False if unknown
    (e.g. timeout already expired).
    """
    async with _correlation_lock:
        entry = _correlations.get(correlation_id)
        if not entry:
            return False
        entry["response"] = payload
        ev = entry["event"]
    ev.set()
    return True



async def _vidal_call(
    cfg: Dict[str, Any],
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    return_debug: bool = False,
) -> Dict[str, Any]:
    """Single HTTP call to VIDAL. Adds app_id/app_key to the query string.

    Returns the parsed JSON body (or raw text wrapped in `{"raw": ...}` when
    the response is not JSON — VIDAL can return Atom/XML for some endpoints).

    When `return_debug=True`, also returns a `_debug` dict containing the
    exact URL, headers, body and response trace — useful for the admin
    diagnostic UI (`/admin/vidal/test-connection`).
    """
    # Iter43-fix24az-k (2026-02-26) — Route through the configured external
    # webhook when enabled. Fallback = direct VIDAL call (block below).
    if cfg.get("webhook_enabled") and (cfg.get("webhook_outbound_url") or "").strip():
        return await _dispatch_via_webhook(
            cfg, method, path, params, body,
            return_debug=return_debug,
        )
    qp = dict(params or {})
    qp.setdefault("app_id", cfg["app_id"])
    qp.setdefault("app_key", cfg["app_key"])
    url = f"{cfg['base_url']}{path}"
    timeout = cfg["http_timeout"]
    # Build a masked snapshot for the debug panel (never expose the secret).
    masked_qp = {k: ("***" if k == "app_key" else v) for k, v in qp.items()}
    debug: Dict[str, Any] = {
        "request": {
            "method": method.upper(),
            "url": url,
            "params": masked_qp,
            "body": body or None,
            "timeout_seconds": timeout,
            "mode": cfg.get("mode"),
        },
        "response": None,
        "error": None,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method.upper() == "GET":
                # Iter43-fix24y — VIDAL répond en Atom/XML par défaut.
                # On accepte les deux formats ; VIDAL renverra `application/atom+xml`.
                r = await client.get(
                    url,
                    params=qp,
                    headers={"Accept": "application/atom+xml, application/xml, application/json;q=0.5"},
                )
            elif method.upper() == "POST" and body is not None and isinstance(body, str):
                # Iter43-fix24y — Sécurisation prescriptions VIDAL utilise POST
                # avec Content-Type: text/xml et un body XML. Si l'appelant
                # passe `body` en tant que `str`, on l'envoie tel quel comme XML.
                r = await client.post(
                    url,
                    params=qp,
                    content=body.encode("utf-8"),
                    headers={
                        "Accept": "application/atom+xml, application/xml",
                        "Content-Type": "text/xml; charset=utf-8",
                    },
                )
            else:
                r = await client.request(
                    method.upper(),
                    url,
                    params=qp,
                    json=body or {},
                    headers={"Accept": "application/atom+xml, application/xml, application/json;q=0.5"},
                )
    except httpx.HTTPError as exc:
        debug["error"] = f"HTTPError: {str(exc)[:300]}"
        if return_debug:
            return {"_error": True, "_debug": debug}
        # Iter43-fix24aa (2026-06-16) — Ne pas lever : retourner une structure
        # de données avec `_error` pour que l'UI puisse afficher la requête.
        return {
            "raw": f"[Erreur réseau VIDAL]\n\n{exc!s}",
            "_request": dict(debug["request"]),
            "_error": {
                "status": 0,
                "content_type": "text/plain",
                "message": f"VIDAL injoignable : {str(exc)[:300]}",
                "url": url,
            },
        }

    ctype = (r.headers.get("content-type") or "").lower()
    raw_text = r.text or ""
    debug["response"] = {
        "status_code": r.status_code,
        "content_type": ctype,
        "elapsed_ms": int(r.elapsed.total_seconds() * 1000) if r.elapsed else None,
        "body_preview": raw_text[:2000],
        "body_truncated": len(raw_text) > 2000,
    }
    # Iter43-fix24aa (2026-06-16) — Sur erreur HTTP (>= 400), on NE LÈVE PLUS
    # d'HTTPException. À la place, on renvoie la même structure `{raw, _request,
    # _error: {status, content_type, ...}}` que pour une réponse 200. Cela permet
    # à l'UI d'afficher la requête + le body de la réponse, indispensable pour
    # diagnostiquer (demandé explicitement par l'utilisateur).
    error_info: Optional[Dict[str, Any]] = None
    if r.status_code >= 400:
        error_info = {
            "status": r.status_code,
            "content_type": ctype,
            "message": f"VIDAL a renvoyé HTTP {r.status_code}",
            "url": url,
        }
        if return_debug:
            debug["error"] = f"HTTP {r.status_code}"
            return {"_error": True, "_debug": debug}

    if "application/json" in ctype:
        try:
            data = r.json()
            # Si JSON parsable, on l'enveloppe pour pouvoir attacher _request/_error
            if not isinstance(data, dict):
                data = {"json": data, "_request": dict(debug["request"])}
            else:
                data["_request"] = dict(debug["request"])
        except Exception:  # noqa: BLE001
            data = {"raw": raw_text, "_request": dict(debug["request"])}
    else:
        # Iter43-fix24u (2026-06-16) — Pour les réponses HTML (typiquement la
        # page Angular API explorer de VIDAL), on injecte deux choses :
        #   1) `<base href="{VIDAL_PROXY_PREFIX}/">` — les ressources relatives
        #      (CSS/JS/img) et les XHR Angular résolvent vers notre proxy
        #      backend qui transmet à VIDAL avec les credentials côté serveur.
        #   2) Un attribut data-vidal-origin sur <html> pour debug.
        if raw_text and "<html" in raw_text[:500].lower():
            import re as _re
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            base_tag = f'<base href="{VIDAL_PROXY_PREFIX}/">'
            head_re = _re.compile(r"(<head[^>]*>)", _re.IGNORECASE)
            html_re = _re.compile(r"(<html[^>]*>)", _re.IGNORECASE)
            if head_re.search(raw_text):
                raw_text = head_re.sub(lambda m: m.group(1) + base_tag, raw_text, count=1)
            elif html_re.search(raw_text):
                raw_text = html_re.sub(lambda m: m.group(1) + "<head>" + base_tag + "</head>", raw_text, count=1)
            else:
                raw_text = base_tag + raw_text
            # Annotation debug (non-fonctionnelle, juste informative)
            raw_text = html_re.sub(
                lambda m: m.group(0).replace("<html", f'<html data-vidal-origin="{origin}"', 1),
                raw_text, count=1,
            )
        # Iter43-fix24w (2026-06-16) — Attache la requête envoyée pour que l'UI
        # puisse l'afficher (méthode, URL, params masqués, body) et générer
        # une commande curl reproductible côté admin.
        data = {"raw": raw_text, "_request": dict(debug["request"])}

    # Iter43-fix24aa — Attache l'info d'erreur si présent (rendue par l'UI sans
    # bloquer l'affichage de la requête / du body).
    if error_info:
        data["_error"] = error_info

    if return_debug:
        return {"_data": data, "_debug": debug}
    return data


# --------------------------------------------------------------------------- #
# Route attachment
# --------------------------------------------------------------------------- #
def attach_vidal_routes(*, api, db, get_current_user, get_current_admin):
    """Mount the VIDAL endpoints under `/api/vidal/*` and the admin config
    endpoints under `/api/admin/vidal/*`."""

    # ---- Admin config (GET + PUT) ----
    @api.get("/admin/vidal/config", tags=["Admin — VIDAL"])
    async def admin_get_vidal_config(user: dict = Depends(get_current_admin)):
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        return {
            "enabled": bool(s.get("vidal_enabled")),
            "mode": (s.get("vidal_mode") or "test").lower(),
            "test_base_url": s.get("vidal_test_base_url") or DEFAULT_TEST_BASE_URL,
            "test_app_id": s.get("vidal_test_app_id") or "",
            "test_app_key": "********" if (s.get("vidal_test_app_key") or "") else "",
            "prod_base_url": s.get("vidal_prod_base_url") or DEFAULT_PROD_BASE_URL,
            "prod_app_id": s.get("vidal_prod_app_id") or "",
            "prod_app_key": "********" if (s.get("vidal_prod_app_key") or "") else "",
            "cache_ttl_hours": int(s.get("vidal_cache_ttl_hours") or DEFAULT_CACHE_TTL_HOURS),
            "quota_per_user_per_day": int(s.get("vidal_quota_per_user_per_day") or DEFAULT_QUOTA_PER_DAY),
            "http_timeout": int(s.get("vidal_http_timeout") or DEFAULT_HTTP_TIMEOUT),
            # Iter43-fix24az-k — webhook proxy config
            "webhook_enabled": bool(s.get("vidal_webhook_enabled")),
            "webhook_outbound_url": (s.get("vidal_webhook_outbound_url") or "").strip(),
            "webhook_timeout_seconds": int(s.get("vidal_webhook_timeout_seconds") or 30),
            "webhook_callback_url": _dispatch_callback_url(),
        }

    @api.put("/admin/vidal/config", tags=["Admin — VIDAL"])
    async def admin_set_vidal_config(payload: VidalConfigPayload = Body(...), user: dict = Depends(get_current_admin)):
        update: Dict[str, Any] = {}
        if payload.enabled is not None:
            update["vidal_enabled"] = bool(payload.enabled)
        if payload.mode is not None:
            mode = payload.mode.lower().strip()
            if mode not in ("test", "production"):
                raise HTTPException(status_code=400, detail="mode doit être 'test' ou 'production'")
            update["vidal_mode"] = mode
        for src_key, dst_key in [
            ("test_base_url", "vidal_test_base_url"),
            ("test_app_id", "vidal_test_app_id"),
            ("test_app_key", "vidal_test_app_key"),
            ("prod_base_url", "vidal_prod_base_url"),
            ("prod_app_id", "vidal_prod_app_id"),
            ("prod_app_key", "vidal_prod_app_key"),
        ]:
            v = getattr(payload, src_key)
            if v is not None and v != "********":
                # Iter43-fix24y (2026-06-16) — Nettoyage automatique des URLs
                # de base : déplie `#!/` (hashbang Angular invalide pour API)
                # et force HTTPS. Cf. _clean_vidal_base_url().
                if src_key.endswith("_base_url"):
                    update[dst_key] = _clean_vidal_base_url(v)
                else:
                    update[dst_key] = v.strip()
        if payload.cache_ttl_hours is not None:
            update["vidal_cache_ttl_hours"] = max(int(payload.cache_ttl_hours), 0)
        if payload.quota_per_user_per_day is not None:
            update["vidal_quota_per_user_per_day"] = max(int(payload.quota_per_user_per_day), 0)
        if payload.http_timeout is not None:
            update["vidal_http_timeout"] = max(min(int(payload.http_timeout), 60), 2)
        # Iter43-fix24az-k — webhook proxy config
        if payload.webhook_enabled is not None:
            update["vidal_webhook_enabled"] = bool(payload.webhook_enabled)
        if payload.webhook_outbound_url is not None:
            update["vidal_webhook_outbound_url"] = (payload.webhook_outbound_url or "").strip()
        if payload.webhook_timeout_seconds is not None:
            update["vidal_webhook_timeout_seconds"] = max(min(int(payload.webhook_timeout_seconds), 300), 5)
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["vidal_config_updated_at"] = _now().isoformat()
        update["vidal_config_updated_by"] = user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    @api.post("/admin/vidal/test-connection", tags=["Admin — VIDAL"])
    async def admin_test_connection(user: dict = Depends(get_current_admin)):
        """Pings VIDAL with a cheap call to validate credentials and base URL.

        Returns a full debug payload (URL appelée, params masqués, body, status
        code, content-type, elapsed_ms, body preview) for the admin diagnostic
        UI in `S058VidalSection`.
        """
        cfg = await _load_config(db)
        if not cfg["enabled"]:
            return {"ok": False, "mode": cfg["mode"], "error": "Module VIDAL désactivé.", "debug": None}
        if not cfg["app_id"] or not cfg["app_key"]:
            return {
                "ok": False, "mode": cfg["mode"],
                "error": f"Credentials ({cfg['mode']}) manquants.",
                "debug": {"request": {
                    "url": f"{cfg['base_url']}/products",
                    "params": {"q": "doliprane", "app_id": cfg["app_id"] or "(vide)", "app_key": "(vide)"},
                    "mode": cfg["mode"],
                }, "response": None},
            }
        result = await _vidal_call(
            cfg, "GET", "/products",
            params={"q": "doliprane"},
            return_debug=True,
        )
        if result.get("_error"):
            debug = result.get("_debug") or {}
            return {
                "ok": False, "mode": cfg["mode"],
                "error": (debug.get("error") or
                          f"HTTP {(debug.get('response') or {}).get('status_code')}"),
                "debug": debug,
            }
        return {
            "ok": True, "mode": cfg["mode"],
            "sample_size": len(str(result.get("_data"))[:200]),
            "debug": result.get("_debug"),
        }

    # ─────────────────────────────────────────────────────────────────
    # Iter43-fix24az-k — VIDAL webhook inbound callback
    # Called by the external system (n8n/Zapier/etc.) with the JSON
    # response for a given correlation_id. No auth for now — feature-first
    # per user's spec (S089). HMAC signing to be added in a follow-up.
    # ─────────────────────────────────────────────────────────────────
    @api.post("/vidal/webhook/callback", tags=["VIDAL"])
    async def vidal_webhook_callback(payload: VidalWebhookCallbackPayload = Body(...)):
        cid = (payload.correlation_id or "").strip()
        if not cid:
            raise HTTPException(status_code=400, detail="correlation_id manquant")
        delivered = await _webhook_deliver(cid, {
            "status_code": payload.status_code,
            "content_type": payload.content_type,
            "body": payload.body,
            "raw": payload.raw,
            "error": payload.error,
        })
        if not delivered:
            # Correlation_id inconnu — soit expiré, soit inventé.
            raise HTTPException(status_code=404, detail=f"Correlation ID inconnu ou expiré : {cid}")
        return {"ok": True, "correlation_id": cid}

    # Admin — test webhook trigger (bypass VIDAL, just fire an outbound POST)
    @api.post("/admin/vidal/webhook/test", tags=["Admin — VIDAL"])
    async def admin_test_webhook(user: dict = Depends(get_current_admin)):
        cfg = await _load_config(db)
        if not cfg.get("webhook_enabled"):
            return {"ok": False, "error": "Webhook VIDAL désactivé — activez-le d'abord."}
        if not (cfg.get("webhook_outbound_url") or "").strip():
            return {"ok": False, "error": "webhook_outbound_url manquant."}
        result = await _dispatch_via_webhook(
            cfg, "GET", "/products",
            params={"q": "doliprane", "_test": "true"},
            body=None,
            return_debug=True,
            tenant_id=None,
            user_email=user.get("email"),
        )
        if result.get("_error"):
            debug = result.get("_debug") or {}
            return {
                "ok": False,
                "error": (debug.get("error") or "Erreur inconnue"),
                "debug": debug,
            }
        return {
            "ok": True,
            "sample": (result.get("raw") or json.dumps(result)[:400]),
            "debug": result.get("_debug"),
        }


    # ---- Public-ish quota status (any authenticated user) ----
    @api.get("/vidal/quota/me", tags=["VIDAL"])
    async def my_quota(user: dict = Depends(get_current_user)):
        cfg = await _load_config(db)
        today = _today_str()
        doc = await db.vidal_usage_daily.find_one({"user_id": user["id"], "day": today}) or {}
        # Add tenant access info for the UI gate (sidebar can hide /portal/vidal)
        tenant_info = await _resolve_tenant_vidal(db, user)
        if user.get("role") in ("admin", "superviseur"):
            access = True
        else:
            access = bool(tenant_info["tenant_enabled"]) and bool(cfg["enabled"])
        # When tenant overrides the mode, reflect that in the badge.
        active_mode = (
            tenant_info["tenant_mode"]
            if tenant_info["tenant_mode"] in ("test", "production")
            else cfg["mode"]
        )
        return {
            "used": int(doc.get("count") or 0),
            "limit": cfg["quota_per_day"],
            "mode": active_mode,
            "day": today,
            "access": access,
            "tenant_type": tenant_info["tenant_type"],
        }

    # ---- Iter43-fix24u (2026-06-16) — HTTP proxy for the Angular SPA -------
    # When VIDAL returns an HTML page (Angular API explorer), it loads its CSS,
    # JS, images and dynamic XHR endpoints via *relative* URLs. We rewrite the
    # `<base href>` to point here so all those requests transit through this
    # proxy, which forwards them to the real VIDAL origin with the credentials
    # configured in AdminSettings. This bypasses CORS limitations of sandboxed
    # iframes (origin = null).
    #
    # Security notes:
    #   • VIDAL `app_id` + `app_key` stay server-side (never exposed to client).
    #   • The endpoint is authenticated (same gate as `/api/vidal/search`).
    #   • Allowed methods: GET, POST, PUT, DELETE, OPTIONS.
    #   • Forwards content-type and binary payloads as-is.
    async def _proxy_vidal(request: Request, subpath: str, user: dict):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        # Build the target URL from the configured VIDAL origin and the
        # requested sub-path. We KEEP the user's `base_url` exactly as the
        # admin configured it (including any `#!/` fragment) but only use
        # its *origin* (scheme + host) when proxying.
        parsed = urlparse(cfg["base_url"])
        origin = f"{parsed.scheme}://{parsed.netloc}"
        # Normalise the sub-path: strip leading slashes, preserve query
        clean_sub = (subpath or "").lstrip("/")
        target_url = f"{origin}/{clean_sub}"
        # Merge query: caller params + server-side credentials
        qp: Dict[str, Any] = dict(request.query_params)
        # Don't override caller's `app_id`/`app_key` if any
        qp.setdefault("app_id", cfg["app_id"])
        qp.setdefault("app_key", cfg["app_key"])
        # Forward body for non-GET methods
        body_bytes: Optional[bytes] = None
        if request.method.upper() not in ("GET", "HEAD", "OPTIONS"):
            body_bytes = await request.body()
        # Forward content-type from caller (Angular often sends JSON or form)
        fwd_headers = {"Accept": request.headers.get("accept", "*/*")}
        if request.headers.get("content-type"):
            fwd_headers["Content-Type"] = request.headers["content-type"]
        try:
            async with httpx.AsyncClient(timeout=cfg["http_timeout"], follow_redirects=False) as client:
                r = await client.request(
                    request.method.upper(),
                    target_url,
                    params=qp,
                    content=body_bytes,
                    headers=fwd_headers,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"VIDAL proxy injoignable : {str(exc)[:200]}") from exc
        # Pass through the response. For HTML responses, rewrite again so
        # nested navigation (e.g. when the iframe follows a link) keeps the
        # proxy active.
        resp_ctype = r.headers.get("content-type") or "application/octet-stream"
        body = r.content
        if "text/html" in resp_ctype.lower():
            text = r.text or ""
            if text and "<html" in text[:500].lower():
                import re as _re
                base_tag = f'<base href="{VIDAL_PROXY_PREFIX}/">'
                head_re = _re.compile(r"(<head[^>]*>)", _re.IGNORECASE)
                html_re = _re.compile(r"(<html[^>]*>)", _re.IGNORECASE)
                if head_re.search(text):
                    text = head_re.sub(lambda m: m.group(1) + base_tag, text, count=1)
                elif html_re.search(text):
                    text = html_re.sub(lambda m: m.group(1) + "<head>" + base_tag + "</head>", text, count=1)
                else:
                    text = base_tag + text
            body = text.encode("utf-8")
        # Strip hop-by-hop headers
        SKIP = {
            "content-encoding", "content-length", "transfer-encoding",
            "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
            "te", "trailers", "upgrade",
        }
        passthrough_headers = {k: v for k, v in r.headers.items() if k.lower() not in SKIP}
        return Response(
            content=body,
            status_code=r.status_code,
            media_type=resp_ctype,
            headers=passthrough_headers,
        )

    @api.api_route(
        "/vidal/proxy/{subpath:path}",
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        tags=["VIDAL"],
    )
    async def vidal_proxy(
        subpath: str,
        request: Request,
        user: dict = Depends(get_current_user),
    ):
        """Forward any HTTP request to the configured VIDAL origin.

        Used by the iframe-rendered Angular SPA: `<base href="/api/vidal/proxy/">`
        makes every relative resource go through here.
        """
        return await _proxy_vidal(request, subpath, user)

    # Empty-path companion (when iframe requests the root resource)
    @api.api_route(
        "/vidal/proxy",
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        tags=["VIDAL"],
    )
    async def vidal_proxy_root(
        request: Request,
        user: dict = Depends(get_current_user),
    ):
        return await _proxy_vidal(request, "", user)

    # ---- Search products / packages / molecules ----
    @api.get("/vidal/search", tags=["VIDAL"])
    async def search(
        q: str = Query(..., min_length=2, description="Terme de recherche"),
        filter: Optional[str] = Query(None, regex="^(product|package|ucd|vmp|all-packages)$"),
        user: dict = Depends(get_current_user),
    ):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        # Iter43-fix24ab — `filter` est désormais optionnel. Doc VIDAL :
        # `https://api.vidal.fr/rest/api/products?app_id=X&app_key=Y&q=doliprane`
        # ne nécessite pas de `filter` pour une recherche basique.
        params: Dict[str, Any] = {"q": q}
        if filter:
            params["filter"] = filter
        ckey = _cache_key(cfg["mode"], "GET", "/products", params)
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        if cached is not None:
            return {"cached": True, "data": cached}
        data = await _vidal_call(cfg, "GET", "/products", params=params)
        await _cache_set(db, ckey, data)
        # Iter41 Phase 2 — Hybrid Qdrant ingest (lazy on every search result).
        try:
            from routes.vidal_rag import index_search_results
            await index_search_results(db, data, source="lazy_search")
        except Exception:  # noqa: BLE001
            pass
        return {"cached": False, "data": data}

    # ---- Fetch product details (fiche médicament) ----
    @api.get("/vidal/product/{product_id}", tags=["VIDAL"])
    async def get_product(product_id: int, user: dict = Depends(get_current_user)):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        path = f"/product/{product_id}"
        ckey = _cache_key(cfg["mode"], "GET", path, {})
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        if cached is not None:
            return {"cached": True, "data": cached}
        data = await _vidal_call(cfg, "GET", path)
        await _cache_set(db, ckey, data)
        try:
            from routes.vidal_rag import index_product
            await index_product(db, product_id, data, source="lazy_product")
        except Exception:  # noqa: BLE001
            pass
        return {"cached": False, "data": data}

    # ---- Documents (RCP, monographie) ----
    @api.get("/vidal/product/{product_id}/documents", tags=["VIDAL"])
    async def get_product_documents(
        product_id: int,
        type: str = Query("RCP", regex="^(RCP|FULL_MONO|PIL|INDICATIONS)$"),
        user: dict = Depends(get_current_user),
    ):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        path = f"/product/{product_id}/documents"
        params = {"type": type}
        ckey = _cache_key(cfg["mode"], "GET", path, params)
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        if cached is not None:
            return {"cached": True, "data": cached}
        data = await _vidal_call(cfg, "GET", path, params=params)
        await _cache_set(db, ckey, data)
        return {"cached": False, "data": data}

    # ---- Status catalog (NEW, AVAILABLE, DELETED, PHARMACO) ----
    @api.get("/vidal/products/status", tags=["VIDAL"])
    async def get_products_by_status(
        status: str = Query(..., regex="^(NEW|AVAILABLE|DELETED|PHARMACO)$"),
        user: dict = Depends(get_current_user),
    ):
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        params = {"status": status}
        ckey = _cache_key(cfg["mode"], "GET", "/products/status", params)
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        if cached is not None:
            return {"cached": True, "data": cached}
        data = await _vidal_call(cfg, "GET", "/products/status", params=params)
        await _cache_set(db, ckey, data)
        return {"cached": False, "data": data}

    # ---- Prescription analysis (alerts) ----
    @api.post("/vidal/prescription/analyze", tags=["VIDAL"])
    async def analyze_prescription(
        payload: PrescriptionAnalysisPayload = Body(...),
        user: dict = Depends(get_current_user),
    ):
        """Forwards the payload to VIDAL `/alerts/full`. Result includes alert
        objects per type (allergy, contraindication, interaction, posology…).

        Iter43-fix24y (2026-06-16) — VIDAL exige POST avec `Content-Type:
        text/xml` et un body XML pour `/alerts/full`. On construit l'XML
        best-effort à partir des champs structurés. Si l'utilisateur fournit
        `xml_body` (string), on l'envoie tel quel.
        """
        if not payload.prescriptions and not getattr(payload, "xml_body", None):
            raise HTTPException(status_code=400, detail="`prescriptions` ne peut pas être vide")
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        # Iter43-fix24y — Build XML body (or use the provided raw XML override).
        xml_body = getattr(payload, "xml_body", None)
        if not xml_body:
            xml_body = _build_alerts_xml(
                patient=payload.patient or {},
                prescriptions=payload.prescriptions,
                allergies=payload.allergies or [],
                pathologies=payload.pathologies or [],
            )
        # `_vidal_call` detects str body → POST with `Content-Type: text/xml`.
        data = await _vidal_call(cfg, "POST", "/alerts/full", body=xml_body)
        try:
            await db.vidal_prescription_audit.insert_one({
                "user_id": user["id"], "user_email": user.get("email"),
                "request_xml": xml_body[:4000], "response_summary": str(data)[:1500],
                "mode": cfg["mode"], "created_at": _now(),
            })
        except Exception:  # noqa: BLE001
            pass
        return {"data": data}

    # ---- Cache admin (purge) ----
    @api.delete("/admin/vidal/cache", tags=["Admin — VIDAL"])
    async def purge_cache(user: dict = Depends(get_current_admin)):
        r = await db.vidal_cache.delete_many({})
        return {"ok": True, "deleted": r.deleted_count}

    # Iter43-fix24ac (2026-06-16) — Configurable actions (admin editable).
    from routes.vidal_actions import attach_vidal_actions_routes
    attach_vidal_actions_routes(
        api=api, db=db,
        get_current_user=get_current_user, get_current_admin=get_current_admin,
        vidal_call_fn=_vidal_call,
        ensure_tenant_can_access_fn=_ensure_tenant_can_access,
        ensure_active_fn=_ensure_active,
        quota_check_fn=_quota_check_and_increment,
    )

    logger.info("[vidal] routes mounted under /api/vidal/* + /api/admin/vidal/*")
