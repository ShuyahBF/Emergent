"""Iter38r-fix9o — Items 6 + 8 : Tickets bubble templates & WhatsApp OTP login.

Endpoints:
  POST /api/auth/wa-otp/request    — public: send OTP via WA template
  POST /api/auth/wa-otp/verify     — public: verify OTP, create demo user, return JWT
  GET  /api/admin/wa-demo/recent   — dashboard widget : last N WA demo users
  POST /api/admin/contacts/{id}/mark-seen  — moderator marks WA-onboarded contact as seen
"""
from __future__ import annotations

import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from routes._counters import gen_internal_id

logger = logging.getLogger("sawali.wa_otp_login_9o")

DEMO_TENANT_EMAIL = "demo@sawalismartsystems.com"
DEMO_TENANT_NAME = "DEMO SAWALI"
DEMO_TRACKED_ROLE = "Admin (Limité)"

# Features pack granted to WA-onboarded tracked users (Item 8.e).
DEMO_FEATURES = {
    "ai_media_generator": True,
    "reports": True,
    "suivis": True,
    "tasks": True,
    "formations": True,
    "forms": True,         # capped at 2 (enforced at usage time)
    "tickets": True,       # capped at 2 client-side
    "interventions": True, # capped at 5 client-side
    # Caps used in /me/features
    "_caps": {"forms": 2, "tickets": 2, "interventions": 5},
}


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_wa_otp_routes(app, db, get_current_user, create_jwt_token, hash_password):
    api: APIRouter = app

    async def _ensure_demo_tenant() -> Dict[str, Any]:
        u = await db.users.find_one({"email": DEMO_TENANT_EMAIL}, {"_id": 0})
        if u:
            return u
        tenant_id = str(uuid.uuid4())
        doc = {
            "id": tenant_id,
            "email": DEMO_TENANT_EMAIL,
            "full_name": DEMO_TENANT_NAME,
            "company": DEMO_TENANT_NAME,
            "role": "admin",
            "is_primary_client": True,
            "account_status": "active",
            "password_hash": hash_password(uuid.uuid4().hex),  # unguessable
            "created_at": _now_iso(),
        }
        await db.users.insert_one(doc.copy())
        doc.pop("_id", None)
        logger.info("[wa_otp] created DEMO SAWALI tenant %s", tenant_id)
        return doc

    @api.post("/auth/wa-otp/request", tags=["Auth — WhatsApp OTP"])
    async def request_wa_otp(payload: Dict[str, Any] = Body(...), request: Request = None):
        msisdn = _digits(payload.get("msisdn") or "")
        if len(msisdn) < 8:
            raise HTTPException(status_code=400, detail="Numéro invalide")
        s = await db.settings.find_one({"_id": "global"}) or {}
        access_token = s.get("wa_access_token") or ""
        phone_number_id = s.get("wa_phone_number_id") or ""
        if not access_token or not phone_number_id:
            raise HTTPException(status_code=503, detail="Configuration WhatsApp Cloud API manquante")
        code = f"{random.randint(0, 999999):06d}"
        # Persist
        await db.wa_otp_requests.update_one(
            {"msisdn": msisdn},
            {"$set": {
                "msisdn": msisdn,
                "code": code,
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                "attempts": 0,
                "created_at": _now_iso(),
            }},
            upsert=True,
        )
        # Try template first (24h fenêtre fermée), fallback à un message texte direct
        template_name = (s.get("wa_otp_template") or "").strip()
        lang = (s.get("wa_otp_template_lang") or "fr").strip() or "fr"
        url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}"}

        async def _send_template_authentication():
            """Authentication category — body + URL/copy-code button both required."""
            body = {
                "messaging_product": "whatsapp",
                "to": msisdn,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": lang},
                    "components": [
                        {"type": "body", "parameters": [{"type": "text", "text": code}]},
                        {"type": "button", "sub_type": "url", "index": "0",
                         "parameters": [{"type": "text", "text": code}]},
                    ],
                },
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                return await client.post(url, json=body, headers=headers)

        async def _send_template_utility():
            """Utility/Marketing category — body parameter only."""
            body = {
                "messaging_product": "whatsapp",
                "to": msisdn,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": lang},
                    "components": [{"type": "body", "parameters": [{"type": "text", "text": code}]}],
                },
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                return await client.post(url, json=body, headers=headers)

        async def _send_text():
            body = {
                "messaging_product": "whatsapp",
                "to": msisdn,
                "type": "text",
                "text": {"body": f"SAWALI — Votre code de connexion est : {code}. Valable 10 min."},
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                return await client.post(url, json=body, headers=headers)

        # Resolve the cached category for this template (admin/healthcheck stores it)
        cached_cat = (s.get("wa_otp_template_category") or "").upper()
        sent_via = "text"
        meta_errors: List[str] = []
        try:
            if template_name:
                # Strategy: try cached category first; if unknown, try Authentication first
                # (most OTP templates), then Utility/Marketing.
                attempts = []
                if cached_cat == "AUTHENTICATION":
                    attempts = [("authentication", _send_template_authentication),
                                ("utility", _send_template_utility)]
                elif cached_cat in ("UTILITY", "MARKETING"):
                    attempts = [("utility", _send_template_utility),
                                ("authentication", _send_template_authentication)]
                else:
                    attempts = [("authentication", _send_template_authentication),
                                ("utility", _send_template_utility)]
                template_succeeded = False
                for label, fn in attempts:
                    r = await fn()
                    if r.status_code == 200:
                        sent_via = f"template_{label}"
                        template_succeeded = True
                        # Cache the working category for next runs
                        await db.settings.update_one(
                            {"_id": "global"},
                            {"$set": {"wa_otp_template_category": label.upper()}},
                            upsert=True,
                        )
                        break
                    else:
                        meta_errors.append(f"[{label}] HTTP {r.status_code}: {r.text[:300]}")
                        logger.warning("[wa_otp] template send failed (%s): %s", label, r.text[:300])
                if not template_succeeded:
                    # Final fallback: plain text (works only within 24h session window)
                    r2 = await _send_text()
                    if r2.status_code != 200:
                        meta_errors.append(f"[text] HTTP {r2.status_code}: {r2.text[:300]}")
                        # Surface ALL collected errors so the admin can debug
                        raise HTTPException(
                            status_code=502,
                            detail="WhatsApp template + text fallback failed. " + " | ".join(meta_errors),
                        )
                    sent_via = "text"
            else:
                r = await _send_text()
                if r.status_code != 200:
                    raise HTTPException(status_code=502, detail=f"WhatsApp send failed: {r.text[:300]}")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"WA error: {exc}")
        return {"ok": True, "sent_via": sent_via, "expires_in_minutes": 10}

    @api.post("/auth/wa-otp/verify", tags=["Auth — WhatsApp OTP"])
    async def verify_wa_otp(payload: Dict[str, Any] = Body(...)):
        msisdn = _digits(payload.get("msisdn") or "")
        code = (payload.get("code") or "").strip()
        if not msisdn or not code:
            raise HTTPException(status_code=400, detail="msisdn et code requis")
        req = await db.wa_otp_requests.find_one({"msisdn": msisdn}, {"_id": 0})
        if not req:
            raise HTTPException(status_code=404, detail="Aucune demande OTP en cours")
        # Expiry
        try:
            exp = datetime.fromisoformat(str(req.get("expires_at")).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                raise HTTPException(status_code=410, detail="Code expiré, redemandez-en un")
        except (ValueError, TypeError):
            pass
        # Throttle
        attempts = int(req.get("attempts") or 0)
        if attempts >= 5:
            raise HTTPException(status_code=429, detail="Trop de tentatives, redemandez un nouveau code")
        if req.get("code") != code:
            await db.wa_otp_requests.update_one({"msisdn": msisdn}, {"$inc": {"attempts": 1}})
            raise HTTPException(status_code=401, detail="Code invalide")
        await db.wa_otp_requests.delete_one({"msisdn": msisdn})
        # Iter38r-fix9v — Deduplication: a phone number may already belong to
        # an existing tenant (admin) or tracked user. In that case we reuse
        # the account (no demo created) and skip the heavy "ensure tenant" call.
        existing_user = await db.users.find_one(
            {"$or": [{"whatsapp": f"+{msisdn}"}, {"phone_digits": msisdn}]},
            {"_id": 0},
        )
        if existing_user:
            user = existing_user
            # Bump last_login_at for traceability on the Clients page
            await db.users.update_one(
                {"id": user["id"]},
                {"$set": {"last_login_at": _now_iso(), "last_wa_login_at": _now_iso()}},
            )
        else:
            # First time on this number — ensure the demo tenant + create the user
            tenant = await _ensure_demo_tenant()
            user_id = str(uuid.uuid4())
            user_no = await gen_internal_id(db, "DEM")
            user = {
                "id": user_id,
                "user_no": user_no,
                "email": f"wa-{msisdn}@demo.sawalismartsystems.com",
                "full_name": payload.get("display_name") or f"Démo WA +{msisdn}",
                "phone": f"+{msisdn}",
                "phone_digits": msisdn,
                "whatsapp": f"+{msisdn}",
                "role": "client",
                "tracked_role": DEMO_TRACKED_ROLE,
                "parent_client_id": tenant["id"],
                "client_id": tenant["id"],
                "features": DEMO_FEATURES,
                "account_status": "active",
                "source": "wa_otp_login",
                "is_demo": True,
                "password_hash": hash_password(uuid.uuid4().hex),
                "created_at": _now_iso(),
                "last_login_at": _now_iso(),
                "last_wa_login_at": _now_iso(),
                "wa_onboarding_seen_by": None,
            }
            await db.users.insert_one(user.copy())
            # Mirror as a contact under the DEMO tenant
            await db.contacts.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant["id"],
                "client_id": tenant["id"],
                "owner_id": tenant["id"],
                "full_name": user["full_name"],
                "phone": f"+{msisdn}",
                "phone_digits": msisdn,
                "whatsapp": f"+{msisdn}",
                "tags": ["Connecté WhatsApp", "DEMO SAWALI"],
                "source": "wa_otp_login",
                "linked_user_id": user_id,
                "created_at": _now_iso(),
                "last_interaction_at": _now_iso(),
            })
            user.pop("_id", None)
        # Mint JWT
        token = create_jwt_token(user)
        return {
            "ok": True,
            "token": token,
            "access_token": token,
            "user": {
                "id": user["id"], "full_name": user["full_name"],
                "email": user["email"], "role": user["role"],
                "tracked_role": user.get("tracked_role"),
                "is_demo": bool(user.get("is_demo")),
                "source": user.get("source"),
            },
        }

    @api.get("/admin/wa-demo/recent", tags=["Admin — Bonus"])
    async def admin_wa_demo_recent(limit: int = 5, user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur", "moderateur"):
            raise HTTPException(status_code=403, detail="Réservé aux admins/modérateurs")
        cap = min(max(limit, 1), 50)
        items = await db.users.find(
            {"source": "wa_otp_login", "is_demo": True},
            {"_id": 0, "password_hash": 0, "features": 0},
        ).sort("created_at", -1).limit(cap).to_list(cap)
        # KPI counts
        total = await db.users.count_documents({"source": "wa_otp_login", "is_demo": True})
        unseen = await db.users.count_documents({"source": "wa_otp_login", "is_demo": True, "wa_onboarding_seen_by": None})
        return {"items": items, "total": total, "unseen": unseen}

    @api.post("/admin/wa-demo/{user_id}/mark-seen", tags=["Admin — Bonus"])
    async def mark_seen(user_id: str, user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur", "moderateur"):
            raise HTTPException(status_code=403, detail="Réservé aux admins/modérateurs")
        r = await db.users.update_one(
            {"id": user_id, "source": "wa_otp_login"},
            {"$set": {"wa_onboarding_seen_by": user.get("email"), "wa_onboarding_seen_at": _now_iso()}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        return {"ok": True}

    # Iter38r-fix9o (Item 8 — debug) — Admin endpoint to test the OTP template
    # without needing to log out. Sends a real OTP to the provided number and
    # returns the Meta API response (or detailed error) for debugging.
    @api.post("/admin/wa-otp/test", tags=["Admin — WhatsApp OTP"])
    async def admin_test_wa_otp(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        msisdn = _digits(payload.get("msisdn") or "")
        if len(msisdn) < 8:
            raise HTTPException(status_code=400, detail="Numéro invalide")
        s = await db.settings.find_one({"_id": "global"}) or {}
        access_token = s.get("wa_access_token") or ""
        phone_number_id = s.get("wa_phone_number_id") or ""
        template_name = (s.get("wa_otp_template") or "").strip()
        lang = (s.get("wa_otp_template_lang") or "fr").strip() or "fr"
        if not access_token or not phone_number_id:
            raise HTTPException(status_code=503, detail="Configuration WhatsApp Cloud API manquante")
        if not template_name:
            raise HTTPException(status_code=400, detail="Aucun template OTP configuré dans Admin Settings")
        code = f"{random.randint(0, 999999):06d}"
        url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}"}
        results: List[Dict[str, Any]] = []
        # Try Authentication first (with button)
        for label, components in [
            ("authentication", [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                {"type": "button", "sub_type": "url", "index": "0",
                 "parameters": [{"type": "text", "text": code}]},
            ]),
            ("utility", [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
            ]),
        ]:
            body = {
                "messaging_product": "whatsapp", "to": msisdn, "type": "template",
                "template": {"name": template_name, "language": {"code": lang}, "components": components},
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(url, json=body, headers=headers)
                results.append({
                    "category_tried": label,
                    "http_status": r.status_code,
                    "meta_response": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:500],
                    "ok": r.status_code == 200,
                })
                if r.status_code == 200:
                    # Cache the working category
                    await db.settings.update_one(
                        {"_id": "global"},
                        {"$set": {"wa_otp_template_category": label.upper()}},
                        upsert=True,
                    )
                    return {
                        "ok": True,
                        "sent_via": f"template_{label}",
                        "test_code": code,
                        "attempts": results,
                    }
            except Exception as exc:
                results.append({"category_tried": label, "exception": str(exc)[:300], "ok": False})
        return {"ok": False, "test_code": code, "attempts": results, "hint": "Vérifiez : (1) le nom du template, (2) la langue (code BCP-47), (3) l'approbation Meta, (4) la catégorie (Authentication vs Utility)."}



    return api
