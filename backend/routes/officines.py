"""Iter41 Phase 3 (2026-02) — Module "Officines"

Proxies a configurable external POST API that returns the list of pharmacies
(officines) where a given product is available, with average price.

Three entry points :
  1. `POST /api/officines/lookup` — admin/superviseur/regulateur lookup
     (full payload, no rate limit).
  2. WhatsApp command `!aizenta <nom>` — public (any phone), rate-limited
     to N requests / day / phone (default 10).
  3. Helper used by the VIDAL fiche modal ("Voir les officines" button).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("sawali.officines")

DEFAULT_TIMEOUT = 12
DEFAULT_PUBLIC_QUOTA = 10  # /day /phone for !aizenta


class OfficineLookupPayload(BaseModel):
    product_name: str
    cip_codes: Optional[List[str]] = None
    requester_role: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().date().isoformat()


async def _load_config(db) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    return {
        "url": (s.get("officines_api_url") or "").strip(),
        "token": (s.get("officines_api_token") or "").strip(),
        "timeout": int(s.get("officines_api_timeout") or DEFAULT_TIMEOUT),
        "public_quota": int(s.get("officines_public_quota_per_day") or DEFAULT_PUBLIC_QUOTA),
    }


async def _call_external(cfg: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST to the configured Officines API and return parsed JSON.

    Expected response format :
        {
          "officines": [
            {
              "name": "Pharmacie XYZ",
              "address": "...",
              "phone": "...",
              "price_avg": 1500,        // optional, XOF or EUR
              "available": true,
              "product_found": "Doliprane 1000mg"
            }, ...
          ]
        }
    """
    if not cfg["url"]:
        raise HTTPException(
            status_code=503,
            detail="URL de l'API Officines non configurée (AdminSettings).",
        )
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"
    try:
        async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
            r = await client.post(cfg["url"], json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"API Officines injoignable : {str(exc)[:200]}") from exc
    if r.status_code >= 400:
        snippet = (r.text or "")[:300]
        raise HTTPException(
            status_code=502 if r.status_code >= 500 else 400,
            detail=f"API Officines a renvoyé {r.status_code} : {snippet}",
        )
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {"raw": r.text}


async def _quota_check_public(db, phone_digits: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Per-phone daily quota for the WhatsApp !aizenta command. 0 = unlimited."""
    limit = cfg["public_quota"]
    if limit <= 0:
        return {"used": 0, "limit": 0, "blocked": False}
    today = _today()
    doc = await db.officines_public_usage.find_one_and_update(
        {"phone": phone_digits, "day": today},
        {"$inc": {"count": 1}, "$set": {"updated_at": _now()}},
        upsert=True,
        return_document=True,
    ) or {}
    used = int(doc.get("count") or 1)
    if used > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Quota journalier officines dépassé ({limit} requêtes/jour).",
        )
    return {"used": used, "limit": limit, "blocked": False}


def attach_officines_routes(*, api, db, get_current_user):
    """Mount /api/officines/* endpoints."""

    @api.post("/officines/lookup", tags=["Officines"])
    async def lookup(payload: OfficineLookupPayload = Body(...), user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur", "regulateur", "pharmacien", "medecin"):
            raise HTTPException(status_code=403, detail="Réservé aux rôles régulateur, pharmacien et médecin")
        cfg = await _load_config(db)
        body = {
            "product_name": payload.product_name,
            "cip_codes": payload.cip_codes or [],
            "requester_role": payload.requester_role or user.get("role"),
            "requester_id": user.get("id"),
        }
        data = await _call_external(cfg, body)
        # Audit
        try:
            await db.officines_audit.insert_one({
                "user_id": user.get("id"), "user_email": user.get("email"),
                "product_name": payload.product_name,
                "cip_codes": payload.cip_codes or [],
                "result_count": len((data.get("officines") if isinstance(data, dict) else []) or []),
                "created_at": _now(),
            })
        except Exception:  # noqa: BLE001
            pass
        return {"data": data}

    @api.post("/admin/officines/test-connection", tags=["Admin — VIDAL"])
    async def admin_officines_test(user: dict = Depends(get_current_user)):
        """Iter41 Phase 4b — Diagnostic verbose pour l'API Officines.

        Effectue un POST réel sur l'URL configurée avec un payload minimal
        (`product_name = "doliprane"`) et retourne :
          - request : URL, headers (token masqué), body envoyé
          - response : status code, content-type, elapsed_ms, body preview
          - error : message en cas de timeout / DNS / TLS
        Aucun audit ni quota — utilisé uniquement pour le débogage admin.
        """
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé admin")
        cfg = await _load_config(db)
        if not cfg["url"]:
            return {"ok": False, "error": "URL non configurée", "debug": None}
        body = {
            "product_name": "doliprane",
            "cip_codes": [],
            "requester_role": "diagnostic",
            "requester_id": user.get("id"),
        }
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if cfg["token"]:
            headers["Authorization"] = f"Bearer {cfg['token']}"
        debug: Dict[str, Any] = {
            "request": {
                "method": "POST",
                "url": cfg["url"],
                "headers": {**headers, **({"Authorization": "Bearer ***"} if cfg["token"] else {})},
                "body": body,
                "timeout_seconds": cfg["timeout"],
            },
            "response": None,
            "error": None,
        }
        import time as _time
        t0 = _time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
                r = await client.post(cfg["url"], json=body, headers=headers)
        except httpx.HTTPError as exc:
            debug["error"] = f"HTTPError: {str(exc)[:300]}"
            return {"ok": False, "error": debug["error"], "debug": debug}
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        ctype = (r.headers.get("content-type") or "").lower()
        raw = r.text or ""
        debug["response"] = {
            "status_code": r.status_code,
            "content_type": ctype,
            "elapsed_ms": elapsed_ms,
            "body_preview": raw[:2000],
            "body_truncated": len(raw) > 2000,
        }
        ok = r.status_code < 400
        return {
            "ok": ok,
            "error": None if ok else f"HTTP {r.status_code}",
            "debug": debug,
        }

    logger.info("[officines] routes mounted under /api/officines/*")


async def lookup_for_wa_aizenta(db, *, phone_digits: str, product_name: str) -> Dict[str, Any]:
    """Used by `!aizenta` WA command. Public access + per-phone quota."""
    cfg = await _load_config(db)
    await _quota_check_public(db, phone_digits, cfg)
    body = {
        "product_name": product_name,
        "cip_codes": [],
        "requester_role": "public_wa",
        "requester_phone": phone_digits,
    }
    return await _call_external(cfg, body)


def format_officines_wa_reply(product_name: str, data: Dict[str, Any]) -> str:
    """Render an Officines lookup response into a WhatsApp-friendly text."""
    items = (data or {}).get("officines") or (data or {}).get("data", {}).get("officines") or []
    if not items:
        return f"❌ Aucune officine référencée pour « {product_name} »."
    lines = [f"🏪 *Officines pour {product_name}*"]
    for i, it in enumerate(items[:10], 1):
        if not isinstance(it, dict):
            continue
        name = it.get("name") or it.get("officine_name") or f"Officine #{i}"
        addr = it.get("address") or ""
        phone = it.get("phone") or ""
        price = it.get("price_avg") or it.get("price") or ""
        available = it.get("available")
        avail_str = "✅ Disponible" if available is True else ("❌ Indispo" if available is False else "❓")
        line = f"\n{i}. *{name}*\n   {avail_str}"
        if price:
            line += f" — {price}"
        if addr:
            line += f"\n   📍 {addr[:80]}"
        if phone:
            line += f"\n   📞 {phone}"
        lines.append(line)
    if len(items) > 10:
        lines.append(f"\n…et {len(items) - 10} autres officines (consulter le portail).")
    return "\n".join(lines)
