"""S045 Phase 1 (2026-02) — Authentication endpoints extracted from
server.py to keep the monolith maintainable. ZERO behavior change — this
is a pure refactor. Every endpoint mirrors exactly the previous inline
definition. Run the regression suite after any change here.

Provided endpoints (under /api/auth/*):
    POST /auth/login           — credentials + captcha → OTP delivery
    POST /auth/verify-otp      — OTP → JWT access token
    POST /auth/resend-otp      — regenerate the OTP for an active session
    GET  /auth/me              — current user payload (requires JWT)
    POST /auth/change-password — change password (requires JWT)
    GET  /auth/captcha-config  — public reCAPTCHA configuration
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

# Pydantic models — imported at MODULE LEVEL so FastAPI's get_type_hints()
# can resolve them properly when introspecting endpoint signatures (FastAPI
# fails to detect body params when the model type lives in a closure).
from models import (  # noqa: E402
    AuthTokenResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    OtpVerifyRequest,
    UserPublic,
)

logger = logging.getLogger("sawali.auth")


def attach_auth_routes(
    api: APIRouter | FastAPI,
    *,
    db,
    helpers: Dict[str, Any],
) -> None:
    """Register the /auth/* routes onto the given router.

    `helpers` must contain all the runtime helpers consumed by these
    endpoints. All keys must be provided — we fail loud if anything is missing.
    """
    verify_password: Callable[..., bool] = helpers["verify_password"]
    hash_password: Callable[..., str] = helpers["hash_password"]
    verify_recaptcha: Callable[..., Awaitable[Dict[str, Any]]] = helpers["verify_recaptcha"]
    generate_otp: Callable[[], str] = helpers["generate_otp"]
    generate_session_token: Callable[[], str] = helpers["generate_session_token"]
    send_otp_email: Callable[..., Awaitable[bool]] = helpers["send_otp_email"]
    create_access_token: Callable[[str, str], str] = helpers["create_access_token"]
    get_current_user: Callable[..., Awaitable[dict]] = helpers["get_current_user"]
    _to_user_public: Callable[[dict], Any] = helpers["_to_user_public"]
    _uuid: Callable[[], str] = helpers["_uuid"]
    _now: Callable[[], str] = helpers["_now"]
    # 2026-02 fork (P3a) — Optional login automation hook. Fire-and-forget.
    emit_login_event = helpers.get("emit_login_event")

    @api.post("/auth/login", response_model=LoginResponse, tags=["Authentification"])
    async def auth_login(payload: LoginRequest, request: Request):
        user = await db.users.find_one({"email": payload.email.lower()})
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Identifiants invalides")
        if user.get("account_status") != "active":
            # 2026-02 fork iter108 — S159 : Friendlier message when the account
            # has been auto-suspended because of overdue payments. The admin
            # dashboard can lift the suspension by recording a payment.
            status = (user.get("account_status") or "").lower()
            if status == "suspended":
                reason = user.get("suspended_reason") or "Suspension pour retard de paiement."
                raise HTTPException(status_code=403, detail=f"Compte suspendu : {reason} Contactez votre administrateur.")
            raise HTTPException(status_code=403, detail="Compte désactivé")
        captcha = await verify_recaptcha(payload.captcha_token, request=request)
        if not captcha["success"]:
            raise HTTPException(status_code=400, detail=f"Captcha invalide ({captcha['reason']})")
        code = generate_otp()
        session = generate_session_token()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        await db.otps.insert_one({
            "id": _uuid(),
            "user_id": user["id"],
            "session_token": session,
            "code": code,
            "expires_at": expires_at,
            "used": False,
            "created_at": _now(),
        })
        email_domain = (user["email"].split("@", 1)[-1] or "").lower().strip()
        settings_doc = await db.settings.find_one({"_id": "global"}) or {}
        internal_list = [
            d.strip().lower().lstrip("@")
            for d in (settings_doc.get("internal_domains") or "sawalismartsystems.com").split(",")
            if d.strip()
        ]
        is_internal_user = email_domain in internal_list
        if is_internal_user:
            dev_otp = code
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
    async def auth_verify_otp(payload: OtpVerifyRequest, request: Request):
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
        # 2026-02 fork (P3a) — Emit the `user.login` automation event so the
        # admin can be alerted (email/phone/role/ip) via a configured WA template.
        if emit_login_event is not None:
            try:
                import asyncio
                asyncio.create_task(emit_login_event(user, request))
            except Exception:  # noqa: BLE001
                pass
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
        payload: ChangePasswordRequest, user: dict = Depends(get_current_user),
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


__all__ = ["attach_auth_routes"]
