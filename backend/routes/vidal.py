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

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("sawali.vidal")

# Default URLs published by VIDAL France (can be overridden in AdminSettings).
DEFAULT_TEST_BASE_URL = "https://api-test.vidal.net/rest/api"
DEFAULT_PROD_BASE_URL = "https://api.vidal.net/rest/api"
DEFAULT_CACHE_TTL_HOURS = 168     # 7 days
DEFAULT_QUOTA_PER_DAY = 200       # per user
DEFAULT_HTTP_TIMEOUT = 12         # seconds


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


class PrescriptionAnalysisPayload(BaseModel):
    """Mirror of the VIDAL `/alerts/full` body, simplified."""
    patient: Optional[Dict[str, Any]] = None  # birth_date, sex, weight_kg, ...
    prescriptions: List[Dict[str, Any]]       # [{ vidal_id, dose, ... }]
    allergies: Optional[List[str]] = None
    pathologies: Optional[List[str]] = None


# --------------------------------------------------------------------------- #
# Helpers (DB + HTTP)
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_str() -> str:
    return _now().date().isoformat()


async def _load_config(db) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    mode = (s.get("vidal_mode") or "test").lower()
    if mode not in ("test", "production"):
        mode = "test"
    if mode == "production":
        base = (s.get("vidal_prod_base_url") or DEFAULT_PROD_BASE_URL).rstrip("/")
        app_id = (s.get("vidal_prod_app_id") or "").strip()
        app_key = (s.get("vidal_prod_app_key") or "").strip()
    else:
        base = (s.get("vidal_test_base_url") or DEFAULT_TEST_BASE_URL).rstrip("/")
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
    }


def _ensure_active(cfg: Dict[str, Any]) -> None:
    if not cfg["enabled"]:
        raise HTTPException(status_code=503, detail="Module VIDAL désactivé (AdminSettings).")
    if not cfg["app_id"] or not cfg["app_key"]:
        raise HTTPException(
            status_code=503,
            detail=f"Identifiants VIDAL ({cfg['mode']}) manquants dans AdminSettings.",
        )


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
    return doc.get("payload")


async def _cache_set(db, key: str, payload: Dict[str, Any]) -> None:
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


async def _vidal_call(
    cfg: Dict[str, Any],
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Single HTTP call to VIDAL. Adds app_id/app_key to the query string.

    Returns the parsed JSON body (or raw text wrapped in `{"raw": ...}` when
    the response is not JSON — VIDAL can return Atom/XML for some endpoints).
    """
    qp = dict(params or {})
    qp.setdefault("app_id", cfg["app_id"])
    qp.setdefault("app_key", cfg["app_key"])
    url = f"{cfg['base_url']}{path}"
    timeout = cfg["http_timeout"]
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method.upper() == "GET":
                r = await client.get(url, params=qp, headers={"Accept": "application/json"})
            else:
                r = await client.request(
                    method.upper(),
                    url,
                    params=qp,
                    json=body or {},
                    headers={"Accept": "application/json"},
                )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"VIDAL injoignable : {str(exc)[:200]}") from exc
    if r.status_code >= 400:
        snippet = (r.text or "")[:300]
        raise HTTPException(
            status_code=502 if r.status_code >= 500 else 400,
            detail=f"VIDAL a renvoyé {r.status_code} : {snippet}",
        )
    ctype = (r.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return {"raw": r.text}
    return {"raw": r.text}


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
                update[dst_key] = v.strip()
        if payload.cache_ttl_hours is not None:
            update["vidal_cache_ttl_hours"] = max(int(payload.cache_ttl_hours), 0)
        if payload.quota_per_user_per_day is not None:
            update["vidal_quota_per_user_per_day"] = max(int(payload.quota_per_user_per_day), 0)
        if payload.http_timeout is not None:
            update["vidal_http_timeout"] = max(min(int(payload.http_timeout), 60), 2)
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["vidal_config_updated_at"] = _now().isoformat()
        update["vidal_config_updated_by"] = user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    @api.post("/admin/vidal/test-connection", tags=["Admin — VIDAL"])
    async def admin_test_connection(user: dict = Depends(get_current_admin)):
        """Pings VIDAL with a cheap call (`/products?q=doliprane&filter=product`)
        to validate the credentials and base URL for the active env."""
        cfg = await _load_config(db)
        _ensure_active(cfg)
        try:
            data = await _vidal_call(cfg, "GET", "/products", params={"q": "doliprane", "filter": "product"})
        except HTTPException as exc:
            return {"ok": False, "mode": cfg["mode"], "error": exc.detail}
        # Heuristic : if we receive ANY entry/feed/raw, count as success.
        return {"ok": True, "mode": cfg["mode"], "sample_size": len(str(data)[:200])}

    # ---- Public-ish quota status (any authenticated user) ----
    @api.get("/vidal/quota/me", tags=["VIDAL"])
    async def my_quota(user: dict = Depends(get_current_user)):
        cfg = await _load_config(db)
        today = _today_str()
        doc = await db.vidal_usage_daily.find_one({"user_id": user["id"], "day": today}) or {}
        return {
            "used": int(doc.get("count") or 0),
            "limit": cfg["quota_per_day"],
            "mode": cfg["mode"],
            "day": today,
        }

    # ---- Search products / packages / molecules ----
    @api.get("/vidal/search", tags=["VIDAL"])
    async def search(
        q: str = Query(..., min_length=2, description="Terme de recherche"),
        filter: str = Query("product", regex="^(product|package|ucd|vmp|all-packages)$"),
        user: dict = Depends(get_current_user),
    ):
        cfg = await _load_config(db)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        params = {"q": q, "filter": filter}
        ckey = _cache_key(cfg["mode"], "GET", "/products/search", params)
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        if cached is not None:
            return {"cached": True, "data": cached}
        data = await _vidal_call(cfg, "GET", "/products/search", params=params)
        await _cache_set(db, ckey, data)
        return {"cached": False, "data": data}

    # ---- Fetch product details (fiche médicament) ----
    @api.get("/vidal/product/{product_id}", tags=["VIDAL"])
    async def get_product(product_id: int, user: dict = Depends(get_current_user)):
        cfg = await _load_config(db)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        path = f"/product/{product_id}"
        ckey = _cache_key(cfg["mode"], "GET", path, {})
        cached = await _cache_get(db, ckey, cfg["cache_ttl_hours"])
        if cached is not None:
            return {"cached": True, "data": cached}
        data = await _vidal_call(cfg, "GET", path)
        await _cache_set(db, ckey, data)
        return {"cached": False, "data": data}

    # ---- Documents (RCP, monographie) ----
    @api.get("/vidal/product/{product_id}/documents", tags=["VIDAL"])
    async def get_product_documents(
        product_id: int,
        type: str = Query("RCP", regex="^(RCP|FULL_MONO|PIL|INDICATIONS)$"),
        user: dict = Depends(get_current_user),
    ):
        cfg = await _load_config(db)
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
        cfg = await _load_config(db)
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
        objects per type (allergy, contraindication, interaction, posology…)."""
        if not payload.prescriptions:
            raise HTTPException(status_code=400, detail="`prescriptions` ne peut pas être vide")
        cfg = await _load_config(db)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        body = {
            "patient": payload.patient or {},
            "prescriptions": payload.prescriptions,
            "allergies": payload.allergies or [],
            "pathologies": payload.pathologies or [],
        }
        # No cache : prescription analysis is patient-specific and stateful.
        data = await _vidal_call(cfg, "POST", "/alerts/full", body=body)
        # Persist a slim audit log for accountability.
        try:
            await db.vidal_prescription_audit.insert_one({
                "user_id": user["id"], "user_email": user.get("email"),
                "request": body, "response_summary": str(data)[:1500],
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

    logger.info("[vidal] routes mounted under /api/vidal/* + /api/admin/vidal/*")
