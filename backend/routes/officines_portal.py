"""Iter42 (2026-02) — Self-Service Portal pour Officines (Pharmacies).

Ce module fournit un portail dédié pour que les officines (pharmacies)
gèrent elles-mêmes :
  - Leur inscription (avec validation admin requise avant activation)
  - Leur authentification (OTP WhatsApp/SMS + Magic Link email)
  - Leur inventaire avancé (quantité + prix + date péremption + lot)
  - Leur secret HMAC (régénération one-shot)
  - Leur historique (consultation + export CSV)

Architecture :
  - JWT séparé (subject = "officine:{id}", role = "officine") pour éviter
    toute confusion avec les comptes CRM (admins, clients, etc.)
  - Collections MongoDB :
      * officines              — entité officine (status pending/active/suspended)
      * officine_otp_codes     — codes OTP éphémères (10 min)
      * officine_magic_tokens  — tokens magic link email (15 min)
      * officine_inventory_items — items individuels (lot + exp + prix)
      * officine_audit_log     — historique des modifications

Auth flows :
  1. POST /api/officines-portal/register
       → status=pending, admin doit approuver
  2. POST /api/officines-portal/auth/request-otp  (channel: wa|sms)
       → envoie un code à 6 chiffres
  3. POST /api/officines-portal/auth/verify-otp
       → retourne JWT
  4. POST /api/officines-portal/auth/magic-link
       → envoie un lien par email
  5. GET  /api/officines-portal/auth/magic-callback?token=...
       → retourne JWT

Endpoints admin (sous /api/admin/officines-registry/*) :
  - GET  list  : liste des officines (filtre status)
  - POST /{id}/approve|suspend|reactivate
  - POST /{id}/link-client : lier à un client CRM existant
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import logging
import os
import random
import secrets as pysecrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import jwt as pyjwt
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger("sawali.officines_portal")

# ---- JWT scope dedicated to officines (different "audience") -------------- #
OFFICINE_JWT_AUDIENCE = "officine-portal"
OTP_TTL_MINUTES = 10
MAGIC_TTL_MINUTES = 15
JWT_TTL_HOURS = 12

_bearer = HTTPBearer(auto_error=False)


def make_get_current_officine(*, db, jwt_secret: str, jwt_algorithm: str = "HS256"):
    """Factory réutilisable pour créer la dependency d'auth officine.

    Permet à d'autres modules (ex: iter42d_incidents_and_lookup) de monter
    des routes nécessitant un JWT officine sans dupliquer la logique.
    """
    def _decode(token: str) -> Dict[str, Any]:
        return pyjwt.decode(
            token, jwt_secret, algorithms=[jwt_algorithm],
            audience=OFFICINE_JWT_AUDIENCE,
        )

    async def get_current_officine(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    ) -> Dict[str, Any]:
        if credentials is None:
            raise HTTPException(status_code=401, detail="Token officine manquant")
        try:
            claims = _decode(credentials.credentials)
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expiré")
        except Exception:
            raise HTTPException(status_code=401, detail="Token officine invalide")
        oid = claims.get("officine_id")
        doc = await db.officines.find_one({"id": oid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=401, detail="Officine introuvable")
        if doc.get("status") != "active":
            raise HTTPException(status_code=403, detail=f"Officine {doc.get('status')} — accès refusé")
        return doc

    return get_current_officine


# --------------------------------------------------------------------------- #
# Pydantic payloads
# --------------------------------------------------------------------------- #
class OfficineRegisterIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    phone: str = Field(..., min_length=6, max_length=30)
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    contact_name: Optional[str] = None
    linked_client_email: Optional[EmailStr] = None  # optionnel : lien CRM


class OtpRequestIn(BaseModel):
    identifier: str  # email OU phone
    channel: str = Field("wa", pattern="^(wa|sms)$")


class OtpVerifyIn(BaseModel):
    identifier: str
    code: str = Field(..., min_length=4, max_length=8)


class MagicLinkRequestIn(BaseModel):
    email: EmailStr


class InventoryItemIn(BaseModel):
    cip: Optional[str] = None           # CIP1-7 (code médicament)
    product_name: str = Field(..., min_length=1, max_length=300)
    lot_number: Optional[str] = None
    expiry_date: Optional[str] = None   # ISO date "YYYY-MM-DD"
    quantity: int = Field(0, ge=0)
    unit_price: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field("XOF", max_length=8)
    available: bool = True
    notes: Optional[str] = None


class LinkClientIn(BaseModel):
    client_email: EmailStr  # email du client CRM existant


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

# Iter43-fix21 (2026-06) — Liste par défaut des rôles d'officines.
# Cette liste est *éditable* depuis l'admin (Admin → Officines → Rôles). Elle est
# stockée dans `db.settings.global.officine_roles` ; ce DEFAULT sert si la clé
# est absente (premier démarrage).
_DEFAULT_OFFICINE_ROLES: List[str] = [
    "Pharmacie",
    "Grossiste pharmaceutique",
    "Laboratoire",
    "Centre de santé",
    "Hôpital / Clinique",
    "Officine de garde",
    "Dépôt pharmaceutique",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: Any) -> Optional[datetime]:
    """Coerce naive datetimes (stored by Motor without tz) to UTC-aware."""
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _now_iso() -> str:
    return _now().isoformat()


def _digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _gen_otp_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _strip_officine(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return {}
    out = {k: v for k, v in doc.items() if k != "_id"}
    return out


# --------------------------------------------------------------------------- #
# Module entry point
# --------------------------------------------------------------------------- #
def attach_officines_portal_routes(
    api: APIRouter | FastAPI,
    *,
    db,
    jwt_secret: str,
    jwt_algorithm: str = "HS256",
    wa_send_text: Optional[Callable[[str, str], Awaitable[Dict[str, Any]]]] = None,
    sms_send: Optional[Callable[[str, str, Optional[str]], Awaitable[Dict[str, Any]]]] = None,
    email_send: Optional[Callable[..., Awaitable[bool]]] = None,
    public_base_url: Optional[str] = None,
) -> None:
    """Register all officines portal routes.

    Required helpers:
      - wa_send_text(to_e164, text) -> dict {ok: bool, ...}
      - sms_send(provider_or_auto, msisdn, message, sender) -> dict
      - email_send(to_email, subject, html_body, text_body) -> bool
      - public_base_url: used to build magic links (e.g. https://app.example.com)
    """

    # ---- JWT helpers (scoped to officine portal) -------------------------- #
    def _mint_officine_token(officine_id: str) -> str:
        payload = {
            "sub": f"officine:{officine_id}",
            "officine_id": officine_id,
            "aud": OFFICINE_JWT_AUDIENCE,
            "iat": int(_now().timestamp()),
            "exp": int((_now() + timedelta(hours=JWT_TTL_HOURS)).timestamp()),
        }
        return pyjwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)

    def _decode_officine_token(token: str) -> Dict[str, Any]:
        return pyjwt.decode(
            token,
            jwt_secret,
            algorithms=[jwt_algorithm],
            audience=OFFICINE_JWT_AUDIENCE,
        )

    async def get_current_officine(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    ) -> Dict[str, Any]:
        if credentials is None:
            raise HTTPException(status_code=401, detail="Token officine manquant")
        try:
            claims = _decode_officine_token(credentials.credentials)
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expiré")
        except Exception:
            raise HTTPException(status_code=401, detail="Token officine invalide")
        oid = claims.get("officine_id")
        doc = await db.officines.find_one({"id": oid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=401, detail="Officine introuvable")
        if doc.get("status") != "active":
            raise HTTPException(status_code=403, detail=f"Officine {doc.get('status')} — accès refusé")
        return doc

    # =========================================================== #
    # 1) Inscription publique (status=pending)
    # =========================================================== #
    @api.post("/officines-portal/register", tags=["Officines Portal"])
    async def register(payload: OfficineRegisterIn = Body(...)):
        email = payload.email.lower().strip()
        phone_digits = _digits(payload.phone)
        if len(phone_digits) < 6:
            raise HTTPException(status_code=400, detail="Numéro de téléphone invalide")
        existing = await db.officines.find_one({"$or": [{"email": email}, {"phone_digits": phone_digits}]})
        if existing:
            raise HTTPException(status_code=409, detail="Une officine avec cet email ou ce numéro existe déjà")
        # Lien client CRM optionnel
        linked_client_id: Optional[str] = None
        if payload.linked_client_email:
            cli = await db.users.find_one(
                {"email": payload.linked_client_email.lower().strip()},
                {"_id": 0, "id": 1, "email": 1},
            )
            if cli:
                linked_client_id = cli["id"]
        oid = str(uuid.uuid4())
        doc = {
            "id": oid,
            "name": payload.name.strip(),
            "email": email,
            "phone": f"+{phone_digits}",
            "phone_digits": phone_digits,
            "address": (payload.address or "").strip() or None,
            "city": (payload.city or "").strip() or None,
            "country": (payload.country or "").strip() or None,
            "contact_name": (payload.contact_name or "").strip() or None,
            "linked_client_id": linked_client_id,
            "status": "pending",
            "created_at": _now(),
            "validated_at": None,
            "validated_by": None,
            "last_login_at": None,
        }
        await db.officines.insert_one(doc.copy())
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()),
            "officine_id": oid,
            "action": "register",
            "actor": "self",
            "details": {"email": email, "phone": doc["phone"]},
            "created_at": _now(),
        })
        return {
            "ok": True,
            "officine_id": oid,
            "status": "pending",
            "message": "Inscription enregistrée. Votre officine sera activée après validation par l'administrateur SAWALI.",
        }

    # =========================================================== #
    # 2) Demande OTP (WhatsApp ou SMS)
    # =========================================================== #
    @api.post("/officines-portal/auth/request-otp", tags=["Officines Portal"])
    async def request_otp(payload: OtpRequestIn = Body(...)):
        ident = payload.identifier.strip().lower()
        # Identifier = email or phone digits
        digits = _digits(ident)
        query: Dict[str, Any] = {"$or": []}
        if "@" in ident:
            query["$or"].append({"email": ident})
        if digits and len(digits) >= 6:
            query["$or"].append({"phone_digits": digits})
        if not query["$or"]:
            raise HTTPException(status_code=400, detail="Identifiant invalide (email ou téléphone)")
        officine = await db.officines.find_one(query, {"_id": 0})
        if not officine:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        if officine.get("status") != "active":
            raise HTTPException(status_code=403, detail=f"Officine non activée ({officine.get('status')})")
        code = _gen_otp_code()
        await db.officine_otp_codes.update_one(
            {"officine_id": officine["id"], "channel": payload.channel},
            {"$set": {
                "officine_id": officine["id"],
                "channel": payload.channel,
                "code_hash": _hash_code(code),
                "expires_at": _now() + timedelta(minutes=OTP_TTL_MINUTES),
                "attempts": 0,
                "created_at": _now(),
            }},
            upsert=True,
        )
        phone = officine.get("phone") or ""
        msg = f"SAWALI Officines — Votre code de connexion : {code}\nValable {OTP_TTL_MINUTES} min."
        sent_via = "noop"
        if payload.channel == "wa":
            if not wa_send_text:
                raise HTTPException(status_code=503, detail="Canal WhatsApp non disponible côté serveur")
            # Iter42b — Si un template `officine_otp_template` est configuré dans
            # Admin Settings, on l'utilise (Authentication d'abord, Utility ensuite,
            # fallback texte). Permet de fonctionner hors fenêtre 24h.
            s = await db.settings.find_one({"_id": "global"}) or {}
            template_name = (s.get("officine_otp_template") or "").strip()
            lang = (s.get("officine_otp_template_lang") or "fr").strip() or "fr"
            access_token = s.get("wa_access_token") or ""
            phone_number_id = s.get("wa_phone_number_id") or ""
            template_sent = False
            if template_name and access_token and phone_number_id:
                import httpx as _httpx
                msisdn = _digits(phone)
                url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
                headers = {"Authorization": f"Bearer {access_token}"}
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
                        async with _httpx.AsyncClient(timeout=10.0) as client:
                            r = await client.post(url, json=body, headers=headers)
                        if r.status_code == 200:
                            template_sent = True
                            sent_via = f"whatsapp_template_{label}"
                            await db.settings.update_one(
                                {"_id": "global"},
                                {"$set": {"officine_otp_template_category": label.upper()}},
                                upsert=True,
                            )
                            break
                    except Exception:  # noqa: BLE001
                        continue
            if not template_sent:
                r = await wa_send_text(phone, msg)
                if not r.get("ok"):
                    raise HTTPException(status_code=502, detail=f"Envoi WhatsApp échoué : {r.get('error', 'erreur inconnue')[:200]}")
                sent_via = "whatsapp_text"
        elif payload.channel == "sms":
            if not sms_send:
                raise HTTPException(status_code=503, detail="Canal SMS non disponible côté serveur")
            r = await sms_send("auto", phone, msg, None)
            if not r.get("ok"):
                raise HTTPException(status_code=502, detail=f"Envoi SMS échoué : {r.get('api_message', 'erreur inconnue')[:200]}")
            sent_via = "sms"
        return {
            "ok": True,
            "sent_via": sent_via,
            "expires_in_minutes": OTP_TTL_MINUTES,
            "masked_target": (phone[:-4] + "****") if len(phone) > 4 else "****",
        }

    # =========================================================== #
    # 3) Vérification OTP → JWT
    # =========================================================== #
    @api.post("/officines-portal/auth/verify-otp", tags=["Officines Portal"])
    async def verify_otp(payload: OtpVerifyIn = Body(...)):
        ident = payload.identifier.strip().lower()
        digits = _digits(ident)
        q: Dict[str, Any] = {"$or": []}
        if "@" in ident:
            q["$or"].append({"email": ident})
        if digits and len(digits) >= 6:
            q["$or"].append({"phone_digits": digits})
        if not q["$or"]:
            raise HTTPException(status_code=400, detail="Identifiant invalide")
        officine = await db.officines.find_one(q, {"_id": 0})
        if not officine:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        # Recherche le code valide (n'importe quel channel)
        rec = await db.officine_otp_codes.find_one(
            {"officine_id": officine["id"]},
            sort=[("created_at", -1)],
        )
        if not rec:
            raise HTTPException(status_code=404, detail="Aucun code OTP en cours")
        if rec.get("attempts", 0) >= 5:
            raise HTTPException(status_code=429, detail="Trop de tentatives — redemandez un code")
        exp = _ensure_utc(rec.get("expires_at"))
        if exp and _now() > exp:
            raise HTTPException(status_code=410, detail="Code expiré — redemandez un code")
        if rec.get("code_hash") != _hash_code(payload.code.strip()):
            await db.officine_otp_codes.update_one(
                {"_id": rec["_id"]}, {"$inc": {"attempts": 1}},
            )
            raise HTTPException(status_code=401, detail="Code invalide")
        await db.officine_otp_codes.delete_many({"officine_id": officine["id"]})
        await db.officines.update_one(
            {"id": officine["id"]},
            {"$set": {"last_login_at": _now()}},
        )
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine["id"],
            "action": "login_otp", "actor": "self",
            "details": {"channel": rec.get("channel")}, "created_at": _now(),
        })
        token = _mint_officine_token(officine["id"])
        return {
            "ok": True, "token": token, "access_token": token,
            "officine": {
                "id": officine["id"], "name": officine.get("name"),
                "email": officine.get("email"), "phone": officine.get("phone"),
                "status": officine.get("status"),
            },
        }

    # =========================================================== #
    # 4) Magic Link (email)
    # =========================================================== #
    @api.post("/officines-portal/auth/magic-link", tags=["Officines Portal"])
    async def magic_link_request(payload: MagicLinkRequestIn = Body(...)):
        email = payload.email.lower().strip()
        officine = await db.officines.find_one({"email": email}, {"_id": 0})
        if not officine:
            # Anti-énumération — toujours répondre OK
            return {"ok": True, "message": "Si un compte existe, un email a été envoyé."}
        if officine.get("status") != "active":
            return {"ok": True, "message": "Si un compte existe, un email a été envoyé."}
        if not email_send:
            raise HTTPException(status_code=503, detail="Service email indisponible")
        raw_token = pysecrets.token_urlsafe(32)
        await db.officine_magic_tokens.insert_one({
            "id": str(uuid.uuid4()),
            "officine_id": officine["id"],
            "token_hash": _hash_code(raw_token),
            "expires_at": _now() + timedelta(minutes=MAGIC_TTL_MINUTES),
            "consumed_at": None,
            "created_at": _now(),
        })
        base = (public_base_url or "").rstrip("/")
        link = f"{base}/officines/magic?token={raw_token}"
        subject = "SAWALI Officines — Votre lien de connexion"
        html = f"""
        <p>Bonjour,</p>
        <p>Voici votre lien de connexion au portail SAWALI Officines :</p>
        <p><a href="{link}" style="background:#0E1F3D;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;">Se connecter</a></p>
        <p>Ce lien est valable {MAGIC_TTL_MINUTES} minutes.</p>
        <p style="color:#777;font-size:12px;">Si vous n'avez pas demandé ce lien, ignorez ce message.</p>
        """
        text = f"Lien de connexion : {link}\n(Valable {MAGIC_TTL_MINUTES} min)"
        ok = await email_send(email, subject, html, text)
        if not ok:
            raise HTTPException(status_code=502, detail="Envoi email échoué")
        return {"ok": True, "message": "Email envoyé.", "expires_in_minutes": MAGIC_TTL_MINUTES}

    @api.get("/officines-portal/auth/magic-callback", tags=["Officines Portal"])
    async def magic_link_callback(token: str = Query(...)):
        if not token:
            raise HTTPException(status_code=400, detail="Token manquant")
        rec = await db.officine_magic_tokens.find_one({"token_hash": _hash_code(token)})
        if not rec:
            raise HTTPException(status_code=404, detail="Lien invalide")
        if rec.get("consumed_at"):
            raise HTTPException(status_code=410, detail="Lien déjà utilisé")
        exp = _ensure_utc(rec.get("expires_at"))
        if exp and _now() > exp:
            raise HTTPException(status_code=410, detail="Lien expiré")
        await db.officine_magic_tokens.update_one(
            {"_id": rec["_id"]}, {"$set": {"consumed_at": _now()}},
        )
        officine = await db.officines.find_one({"id": rec["officine_id"]}, {"_id": 0})
        if not officine or officine.get("status") != "active":
            raise HTTPException(status_code=403, detail="Officine non active")
        await db.officines.update_one(
            {"id": officine["id"]},
            {"$set": {"last_login_at": _now()}},
        )
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine["id"],
            "action": "login_magic", "actor": "self",
            "details": {}, "created_at": _now(),
        })
        jwt_token = _mint_officine_token(officine["id"])
        return {
            "ok": True, "token": jwt_token, "access_token": jwt_token,
            "officine": {
                "id": officine["id"], "name": officine.get("name"),
                "email": officine.get("email"), "phone": officine.get("phone"),
            },
        }

    # =========================================================== #
    # 5) /me — profil officine + features
    # =========================================================== #
    @api.get("/officines-portal/me", tags=["Officines Portal"])
    async def me(officine: dict = Depends(get_current_officine)):
        return {"officine": _strip_officine(officine)}

    @api.post("/officines-portal/me/regenerate-secret", tags=["Officines Portal"])
    async def regenerate_secret(officine: dict = Depends(get_current_officine)):
        # Révoque l'ancien secret puis en crée un nouveau
        await db.officines_secrets.update_many(
            {"officine_id": officine["id"], "revoked_at": None},
            {"$set": {"revoked_at": _now(), "revoked_by": f"officine:{officine['id']}"}},
        )
        new_secret = pysecrets.token_urlsafe(48)
        await db.officines_secrets.insert_one({
            "id": pysecrets.token_urlsafe(12),
            "officine_id": officine["id"],
            "label": officine.get("name"),
            "contact_email": officine.get("email"),
            "secret": new_secret,
            "created_by": f"officine:{officine['id']}",
            "created_at": _now(),
            "revoked_at": None,
            "revoked_by": None,
            "last_used_at": None,
        })
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine["id"],
            "action": "regenerate_secret", "actor": "self",
            "details": {}, "created_at": _now(),
        })
        return {
            "ok": True,
            "secret": new_secret,
            "warning": "Ce secret ne sera plus jamais affiché. Copiez-le immédiatement et conservez-le en lieu sûr.",
        }

    # =========================================================== #
    # 6) Inventaire — CRUD par officine
    # =========================================================== #
    @api.get("/officines-portal/inventory", tags=["Officines Portal"])
    async def list_inventory(
        q: Optional[str] = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        officine: dict = Depends(get_current_officine),
    ):
        query: Dict[str, Any] = {"officine_id": officine["id"]}
        if q:
            query["$or"] = [
                {"product_name": {"$regex": q, "$options": "i"}},
                {"cip": {"$regex": q, "$options": "i"}},
                {"lot_number": {"$regex": q, "$options": "i"}},
            ]
        cur = db.officine_inventory_items.find(query, {"_id": 0}).sort("updated_at", -1).limit(limit)
        items = await cur.to_list(limit)
        return {"items": items, "count": len(items)}

    @api.post("/officines-portal/inventory", tags=["Officines Portal"])
    async def create_inventory(
        payload: InventoryItemIn = Body(...),
        officine: dict = Depends(get_current_officine),
    ):
        item_id = str(uuid.uuid4())
        doc = {
            "id": item_id,
            "officine_id": officine["id"],
            "cip": (payload.cip or "").strip() or None,
            "product_name": payload.product_name.strip(),
            "lot_number": (payload.lot_number or "").strip() or None,
            "expiry_date": (payload.expiry_date or "").strip() or None,
            "quantity": int(payload.quantity),
            "unit_price": float(payload.unit_price) if payload.unit_price is not None else None,
            "currency": (payload.currency or "XOF").upper(),
            "available": bool(payload.available),
            "notes": (payload.notes or "").strip() or None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.officine_inventory_items.insert_one(doc.copy())
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine["id"],
            "action": "inventory_create", "actor": "self",
            "details": {"item_id": item_id, "product_name": doc["product_name"]},
            "created_at": _now(),
        })
        doc.pop("_id", None)
        return {"ok": True, "item": doc}

    @api.put("/officines-portal/inventory/{item_id}", tags=["Officines Portal"])
    async def update_inventory(
        item_id: str,
        payload: InventoryItemIn = Body(...),
        officine: dict = Depends(get_current_officine),
    ):
        existing = await db.officine_inventory_items.find_one(
            {"id": item_id, "officine_id": officine["id"]}, {"_id": 0}
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Item introuvable")
        update_set = {
            "cip": (payload.cip or "").strip() or None,
            "product_name": payload.product_name.strip(),
            "lot_number": (payload.lot_number or "").strip() or None,
            "expiry_date": (payload.expiry_date or "").strip() or None,
            "quantity": int(payload.quantity),
            "unit_price": float(payload.unit_price) if payload.unit_price is not None else None,
            "currency": (payload.currency or "XOF").upper(),
            "available": bool(payload.available),
            "notes": (payload.notes or "").strip() or None,
            "updated_at": _now(),
        }
        await db.officine_inventory_items.update_one(
            {"id": item_id, "officine_id": officine["id"]},
            {"$set": update_set},
        )
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine["id"],
            "action": "inventory_update", "actor": "self",
            "details": {"item_id": item_id, "product_name": update_set["product_name"]},
            "created_at": _now(),
        })
        merged = {**existing, **update_set}
        return {"ok": True, "item": merged}

    @api.delete("/officines-portal/inventory/{item_id}", tags=["Officines Portal"])
    async def delete_inventory(
        item_id: str,
        officine: dict = Depends(get_current_officine),
    ):
        r = await db.officine_inventory_items.delete_one(
            {"id": item_id, "officine_id": officine["id"]}
        )
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Item introuvable")
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine["id"],
            "action": "inventory_delete", "actor": "self",
            "details": {"item_id": item_id}, "created_at": _now(),
        })
        return {"ok": True}

    @api.get("/officines-portal/inventory/export.csv", tags=["Officines Portal"])
    async def export_inventory_csv(officine: dict = Depends(get_current_officine)):
        cur = db.officine_inventory_items.find(
            {"officine_id": officine["id"]}, {"_id": 0}
        ).sort("updated_at", -1)
        items = await cur.to_list(5000)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "cip", "product_name", "lot_number", "expiry_date",
            "quantity", "unit_price", "currency", "available",
            "notes", "updated_at",
        ])
        for it in items:
            w.writerow([
                it.get("cip") or "", it.get("product_name") or "",
                it.get("lot_number") or "", it.get("expiry_date") or "",
                it.get("quantity", 0),
                it.get("unit_price") if it.get("unit_price") is not None else "",
                it.get("currency") or "",
                "oui" if it.get("available") else "non",
                (it.get("notes") or "").replace("\n", " "),
                str(it.get("updated_at") or ""),
            ])
        buf.seek(0)
        fname = f"inventaire_{officine['id'][:8]}_{_now().date()}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )

    # =========================================================== #
    # 7) Historique
    # =========================================================== #
    @api.get("/officines-portal/history", tags=["Officines Portal"])
    async def list_history(
        limit: int = Query(200, ge=1, le=1000),
        officine: dict = Depends(get_current_officine),
    ):
        cur = db.officine_audit_log.find(
            {"officine_id": officine["id"]}, {"_id": 0}
        ).sort("created_at", -1).limit(limit)
        items = await cur.to_list(limit)
        return {"items": items, "count": len(items)}

    @api.get("/officines-portal/history/export.csv", tags=["Officines Portal"])
    async def export_history_csv(officine: dict = Depends(get_current_officine)):
        cur = db.officine_audit_log.find(
            {"officine_id": officine["id"]}, {"_id": 0}
        ).sort("created_at", -1)
        items = await cur.to_list(5000)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["created_at", "action", "actor", "details"])
        for it in items:
            import json
            w.writerow([
                str(it.get("created_at") or ""),
                it.get("action") or "",
                it.get("actor") or "",
                json.dumps(it.get("details") or {}, ensure_ascii=False),
            ])
        buf.seek(0)
        fname = f"historique_{officine['id'][:8]}_{_now().date()}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )

    # =========================================================== #
    # 8) Admin — Registry (validation, suspension, link client)
    # =========================================================== #
    # NB: ces routes admin nécessitent que server.py les wire avec
    #     get_current_admin = ... via `attach_officines_portal_admin_routes`.
    logger.info("[officines_portal] all routes mounted")


def attach_officines_portal_admin_routes(
    api: APIRouter | FastAPI,
    *,
    db,
    get_current_admin,
    get_current_user=None,  # Iter43-fix24n — pour la délégation menu Officines
) -> None:
    """Admin-only routes for officine validation/management.

    Mounted under /api/admin/officines-registry/*

    Iter43-fix24n (2026-06) : ajoute le support de la **délégation du menu
    Officines** à des utilisateurs non-admin listés dans
    `settings.officines_menu_allowed_emails`. Ces utilisateurs ont des droits
    d'édition LIMITÉS (cf. `_OFFICINE_DELEGATED_EDITABLE_FIELDS`).
    """

    # Iter43-fix24n — Champs éditables par un utilisateur délégué (non-admin).
    # Iter43-fix24v (2026-06-16) — Ajout de email, contact_name (Nom du
    # responsable) et groupe_garde (Groupe de Garde) suite à la demande
    # utilisateur lors du test de la délégation.
    # Les autres restent en lecture seule (côté UI grisé + rejet côté backend).
    _OFFICINE_DELEGATED_EDITABLE_FIELDS = {
        "intitule",
        "phone",
        "whatsapp",
        "latitude",
        "longitude",
        "location_hint",
        "activite_principale",
        # Iter43-fix24v additions
        "email",
        "contact_name",
        "groupe_garde",
    }

    async def _get_officines_menu_user(user: dict) -> tuple[dict, str]:
        """Retourne (user, edit_mode) où edit_mode ∈ {"full", "limited"}.

        - Admin / supervisor → "full"
        - Utilisateur listé dans settings.officines_menu_allowed_emails → "limited"
        - Sinon → HTTP 403
        """
        if (user.get("role") or "").lower() in ("admin", "supervisor", "superviseur"):
            return user, "full"
        email = (user.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(status_code=403, detail="Accès Officines refusé")
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "officines_menu_allowed_emails": 1}) or {}
        allowed = s.get("officines_menu_allowed_emails") or []
        allowed_norm = {e.strip().lower() for e in allowed if e and e.strip()}
        if email in allowed_norm:
            return user, "limited"
        raise HTTPException(status_code=403, detail="Accès Officines refusé — contactez un administrateur")

    async def _require_admin_or_delegated(user: dict) -> tuple[dict, str]:
        """Wrapper utilisable par les endpoints qui doivent accepter admin OU délégué."""
        return await _get_officines_menu_user(user)

    if get_current_user is not None:
        @api.get("/me/officines-permissions", tags=["Admin — Officines Registry"])
        async def me_officines_permissions(user: dict = Depends(get_current_user)):
            """Retourne {can_view, edit_mode, editable_fields} pour l'utilisateur courant.

            Utilisé par le frontend pour griser les champs en mode délégué et
            pour le route-guard du menu Officines.
            """
            try:
                _, edit_mode = await _get_officines_menu_user(user)
            except HTTPException:
                return {
                    "can_view": False,
                    "edit_mode": None,
                    "editable_fields": [],
                }
            return {
                "can_view": True,
                "edit_mode": edit_mode,
                "editable_fields": (
                    sorted(_OFFICINE_DELEGATED_EDITABLE_FIELDS) if edit_mode == "limited"
                    else "all"
                ),
            }

    @api.get("/admin/officines-registry", tags=["Admin — Officines Registry"])
    async def list_registry(
        status: Optional[str] = Query(None, pattern="^(pending|active|suspended)$"),
        activite: Optional[str] = Query(None),
        role: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        user: dict = Depends(get_current_user or get_current_admin),
    ):
        # Iter43-fix24n — Délégation : admin OU utilisateur autorisé via setting
        if get_current_user is not None:
            await _get_officines_menu_user(user)
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        # Iter43-fix12 (2026-03) — filtre par activité principale
        if activite:
            query["activite_principale"] = activite
        # Iter43-fix23 (2026-06) — filtre par rôle (remplace activité dans l'UI)
        if role:
            query["role"] = role
        if q:
            query["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"email": {"$regex": q, "$options": "i"}},
                {"phone_digits": {"$regex": q}},
                {"city": {"$regex": q, "$options": "i"}},
                # Iter43-fix23 — Recherche aussi par rôle (regex insensible casse)
                {"role": {"$regex": q, "$options": "i"}},
            ]
        # Iter43-fix12 (2026-03) — tri alphabétique ASC sur le nom (insensible casse)
        cur = db.officines.find(query, {"_id": 0}).collation(
            {"locale": "fr", "strength": 1}
        ).sort("name", 1).limit(limit)
        items = await cur.to_list(limit)
        # Iter43-fix12 — enrichit chaque item avec products_count
        if items:
            officine_ids = [it["id"] for it in items]
            agg = db.officine_products.aggregate([
                {"$match": {"officine_id": {"$in": officine_ids}}},
                {"$group": {"_id": "$officine_id", "n": {"$sum": 1}}},
            ])
            counts_map: Dict[str, int] = {d["_id"]: int(d.get("n") or 0) async for d in agg}
            for it in items:
                it["products_count"] = counts_map.get(it["id"], 0)
        # Counts by status (utile pour le dashboard)
        counts = {"pending": 0, "active": 0, "suspended": 0}
        async for d in db.officines.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
            if d.get("_id") in counts:
                counts[d["_id"]] = int(d.get("n") or 0)
        return {"items": items, "count": len(items), "counts": counts}

    # Iter43-fix21 — Specific routes BEFORE /{officine_id} catch-all (FastAPI ordering)
    @api.get("/admin/officines-registry/roles", tags=["Admin — Officines Registry"])
    async def list_officine_roles_v2(_: dict = Depends(get_current_admin)):
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "officine_roles": 1}) or {}
        roles = s.get("officine_roles") or list(_DEFAULT_OFFICINE_ROLES)
        usage: Dict[str, int] = {}
        async for o in db.officines.find({"role": {"$in": roles}}, {"role": 1, "_id": 0}):
            r = o.get("role")
            if r:
                usage[r] = usage.get(r, 0) + 1
        return {"roles": roles, "usage": usage, "default_roles": _DEFAULT_OFFICINE_ROLES}

    @api.get("/admin/officines-registry/garde-groups", tags=["Admin — Officines Registry"])
    async def list_garde_groups_v2(user: dict = Depends(get_current_user)):
        # Iter43-fix24ag (2026-06-17) — Permettre aussi aux utilisateurs délégués
        # (qui peuvent éditer le champ `groupe_garde` d'une officine) de charger
        # la liste des groupes existants. Sans ce fix, la dropdown était vide
        # pour eux (le `.catch(() => {})` côté frontend avalait le 403).
        await _require_admin_or_delegated(user)
        groups: Dict[int, int] = {}
        async for o in db.officines.find(
            {"groupe_garde": {"$nin": [None, ""]}},
            {"groupe_garde": 1, "_id": 0},
        ):
            try:
                g = int(o["groupe_garde"])
                groups[g] = groups.get(g, 0) + 1
            except (TypeError, ValueError):
                continue
        next_g = (max(groups.keys()) + 1) if groups else 1
        all_keys = sorted(set(list(groups.keys()) + list(range(1, 6))))
        all_groups = [{"groupe_garde": g, "count": groups.get(g, 0)} for g in all_keys]
        return {
            "groups": all_groups,
            "used_groups": [{"groupe_garde": g, "count": groups[g]} for g in sorted(groups.keys())],
            "next_suggested": next_g,
        }

    @api.get("/admin/officines-registry/logos/health", tags=["Admin — Officines Registry"])
    async def officines_logos_health_v2(_: dict = Depends(get_current_admin)):
        broken: List[Dict[str, Any]] = []
        ok_db, ok_disk = 0, 0
        async for o in db.officines.find(
            {"logo_url": {"$nin": [None, ""]}},
            {"_id": 0, "id": 1, "name": 1, "logo_url": 1, "logo_path": 1, "logo_data_b64": 1, "logo_ext": 1},
        ):
            if o.get("logo_data_b64"):
                ok_db += 1
                continue
            lp = o.get("logo_path")
            if lp and Path(lp).exists():
                ok_disk += 1
                continue
            broken.append({"id": o["id"], "name": o.get("name"), "logo_url": o.get("logo_url")})
        return {
            "ok_in_db": ok_db,
            "ok_on_disk_only": ok_disk,
            "broken_count": len(broken),
            "broken": broken[:200],
            "advice": (
                "Re-téléversez les logos cassés depuis la fiche officine. "
                "Une fois en DB (base64), ils survivront aux redéploiements."
            ),
        }

    # Iter43-fix21 — PUT /roles ET POST /bulk-assign doivent aussi être déclarés
    # AVANT /{officine_id} pour éviter le shadowing FastAPI.
    @api.put("/admin/officines-registry/roles", tags=["Admin — Officines Registry"])
    async def update_officine_roles_v2(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        raw_roles = payload.get("roles")
        if not isinstance(raw_roles, list):
            raise HTTPException(status_code=400, detail="`roles` doit être une liste de chaînes")
        clean: List[str] = []
        seen = set()
        for r in raw_roles:
            if not isinstance(r, str):
                continue
            v = r.strip()
            if not v or v.lower() in seen:
                continue
            if len(v) > 60:
                raise HTTPException(status_code=400, detail=f"Rôle trop long (>60 car) : {v!r}")
            clean.append(v)
            seen.add(v.lower())
        if len(clean) > 50:
            raise HTTPException(status_code=400, detail="Trop de rôles (max 50)")
        if not clean:
            raise HTTPException(status_code=400, detail="Au moins un rôle requis")
        used_roles = set()
        async for o in db.officines.find({"role": {"$nin": [None, ""]}}, {"role": 1, "_id": 0}):
            r = o.get("role")
            if r:
                used_roles.add(r)
        removed = used_roles - set(clean)
        if removed:
            raise HTTPException(
                status_code=409,
                detail=f"Impossible de supprimer ces rôles encore utilisés : {sorted(removed)}. Ré-affectez d'abord les officines concernées.",
            )
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"officine_roles": clean, "officine_roles_updated_at": _now(),
                      "officine_roles_updated_by": user.get("email")}},
            upsert=True,
        )
        return {"ok": True, "roles": clean}

    @api.post("/admin/officines-registry/bulk-assign", tags=["Admin — Officines Registry"])
    async def bulk_assign_to_officines_v2(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        ids = [x for x in (payload.get("officine_ids") or []) if isinstance(x, str) and x]
        if not ids:
            raise HTTPException(status_code=400, detail="Aucune officine sélectionnée")
        set_doc: Dict[str, Any] = {}
        role = payload.get("role")
        gg = payload.get("groupe_garde")
        if role is not None:
            role_val = (str(role) or "").strip()
            if role_val:
                s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "officine_roles": 1}) or {}
                roles = s.get("officine_roles") or _DEFAULT_OFFICINE_ROLES
                if role_val not in roles:
                    raise HTTPException(status_code=400, detail=f"Rôle '{role_val}' inconnu")
                set_doc["role"] = role_val
            else:
                set_doc["role"] = None
        if gg is not None and gg != "":
            try:
                set_doc["groupe_garde"] = int(gg)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="groupe_garde doit être un entier")
            if not (1 <= set_doc["groupe_garde"] <= 100):
                raise HTTPException(status_code=400, detail="groupe_garde doit être entre 1 et 100")
        elif gg == "":
            set_doc["groupe_garde"] = None
        if not set_doc:
            raise HTTPException(status_code=400, detail="Préciser au moins `role` ou `groupe_garde`")
        set_doc["updated_at"] = _now()
        set_doc["updated_by"] = user.get("email")
        result = await db.officines.update_many({"id": {"$in": ids}}, {"$set": set_doc})
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": None,
            "action": "bulk_assign", "actor": user.get("email"),
            "details": {"officine_ids": ids, "set": {k: v for k, v in set_doc.items() if k not in ("updated_at", "updated_by")}},
            "created_at": _now(),
        })
        return {"ok": True, "matched": result.matched_count, "modified": result.modified_count}

    @api.get("/admin/officines-registry/{officine_id}", tags=["Admin — Officines Registry"])
    async def detail(officine_id: str, user: dict = Depends(get_current_user or get_current_admin)):
        # Iter43-fix24n — Délégation : admin OU email autorisé
        if get_current_user is not None:
            await _get_officines_menu_user(user)
        doc = await db.officines.find_one({"id": officine_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        # Inventaire + items count
        items_count = await db.officine_inventory_items.count_documents({"officine_id": officine_id})
        history_count = await db.officine_audit_log.count_documents({"officine_id": officine_id})
        return {"officine": doc, "items_count": items_count, "history_count": history_count}

    @api.post("/admin/officines-registry/{officine_id}/approve", tags=["Admin — Officines Registry"])
    async def approve(officine_id: str, user: dict = Depends(get_current_admin)):
        # Iter43-fix9 — Distingue "date d'activation" (activated_at) de "date d'inscription".
        # validated_at est conservé pour rétro-compatibilité avec les tests existants.
        now = _now()
        r = await db.officines.update_one(
            {"id": officine_id, "status": {"$ne": "active"}},
            {"$set": {
                "status": "active",
                "validated_at": now, "validated_by": user.get("email"),
                "activated_at": now, "activated_by": user.get("email"),
                "activated_via": "admin",
            }},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Officine introuvable ou déjà active")
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "approve", "actor": user.get("email"),
            "details": {"via": "admin"}, "created_at": _now(),
        })
        return {"ok": True, "status": "active"}

    @api.post("/admin/officines-registry/{officine_id}/suspend", tags=["Admin — Officines Registry"])
    async def suspend(officine_id: str, user: dict = Depends(get_current_admin)):
        r = await db.officines.update_one(
            {"id": officine_id},
            {"$set": {"status": "suspended", "suspended_at": _now(), "suspended_by": user.get("email")}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "suspend", "actor": user.get("email"),
            "details": {}, "created_at": _now(),
        })
        return {"ok": True, "status": "suspended"}

    @api.post("/admin/officines-registry/{officine_id}/reactivate", tags=["Admin — Officines Registry"])
    async def reactivate(officine_id: str, user: dict = Depends(get_current_admin)):
        r = await db.officines.update_one(
            {"id": officine_id, "status": "suspended"},
            {"$set": {"status": "active", "reactivated_at": _now(), "reactivated_by": user.get("email")}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Officine non suspendue")
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "reactivate", "actor": user.get("email"),
            "details": {}, "created_at": _now(),
        })
        return {"ok": True, "status": "active"}

    @api.post("/admin/officines-registry/{officine_id}/link-client", tags=["Admin — Officines Registry"])
    async def link_client(
        officine_id: str,
        payload: LinkClientIn = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        client = await db.users.find_one(
            {"email": payload.client_email.lower().strip()},
            {"_id": 0, "id": 1, "email": 1, "full_name": 1},
        )
        if not client:
            raise HTTPException(status_code=404, detail="Client CRM introuvable")
        r = await db.officines.update_one(
            {"id": officine_id},
            {"$set": {"linked_client_id": client["id"], "linked_client_email": client.get("email")}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "link_client", "actor": user.get("email"),
            "details": {"client_id": client["id"], "client_email": client.get("email")},
            "created_at": _now(),
        })
        return {"ok": True, "linked_client": {"id": client["id"], "email": client.get("email")}}

    @api.post("/admin/officines-registry/{officine_id}/unlink-client", tags=["Admin — Officines Registry"])
    async def unlink_client(officine_id: str, user: dict = Depends(get_current_admin)):
        r = await db.officines.update_one(
            {"id": officine_id},
            {"$set": {"linked_client_id": None, "linked_client_email": None}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "unlink_client", "actor": user.get("email"),
            "details": {}, "created_at": _now(),
        })
        return {"ok": True}

    # =====================================================================
    # Iter43-fix9 (2026-03) — CSV import / fiche edit / logo / import-to-contacts
    # =====================================================================
    @api.post("/admin/officines-registry/import-csv", tags=["Admin — Officines Registry"])
    async def import_csv(
        request: Request,
        user: dict = Depends(get_current_admin),
    ):
        """Import en masse des officines depuis un fichier CSV.

        Format attendu (séparateur `;`) :
            Nom de la pharmacie;Téléphone;Ville;Indications de localisation;Numéro d'ordre

        Le « Nom de la pharmacie » sert également de code (champ `name`). Les
        lignes sont créées avec status='pending' et un email/phone provisoires
        si non fournis (l'admin pourra compléter via la modale d'édition).
        """
        from fastapi import UploadFile
        form = await request.form()
        upload: Optional[UploadFile] = form.get("file")  # type: ignore[assignment]
        if upload is None:
            raise HTTPException(status_code=400, detail="Fichier CSV manquant (champ `file`)")
        raw = await upload.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"Encodage non supporté : {exc}") from exc
        reader = csv.reader(io.StringIO(text), delimiter=";")
        first_row = next(reader, None)
        if not first_row:
            raise HTTPException(status_code=400, detail="CSV vide")

        # Iter43-fix9a — Auto-détection d'en-tête.
        # On considère que la 1ère ligne est un EN-TÊTE si au moins 2 des 5
        # premières cellules matchent les libellés attendus (insensible à la
        # casse / aux accents). Sinon on traite la 1ère ligne comme donnée.
        def _norm(s: str) -> str:
            return (
                (s or "").strip().lower()
                .replace("é", "e").replace("è", "e").replace("ê", "e")
                .replace("ô", "o").replace("î", "i").replace("'", "'")
                .replace("â", "a").replace("à", "a")
            )
        expected_tokens = {
            "nom de la pharmacie", "nom", "pharmacie",
            "telephone", "tel", "phone",
            "ville", "city",
            "indications de localisation", "indications", "localisation", "adresse",
            "numero d'ordre", "numero ordre", "ordre", "n° d'ordre", "n d'ordre",
        }
        first_norm = [_norm(c) for c in first_row[:5]]
        header_matches = sum(1 for c in first_norm if c in expected_tokens)
        has_header = header_matches >= 2

        # Reset reader if first row was data (no header)
        if not has_header:
            data_iter = iter([first_row] + list(reader))
            first_data_row = 1
        else:
            data_iter = reader
            first_data_row = 2

        results: List[Dict[str, Any]] = []
        created = 0
        skipped = 0
        for offset, row in enumerate(data_iter):
            row_idx = first_data_row + offset
            if not row or not any((c or "").strip() for c in row):
                continue
            row = (row + ["", "", "", "", ""])[:5]
            nom, tel, ville, indications, ordre = [(c or "").strip() for c in row]
            if not nom:
                results.append({"row": row_idx, "skipped": True, "reason": "Nom de la pharmacie manquant"})
                skipped += 1
                continue
            phone_digits = _digits(tel)
            # Anti-doublon : sur le code (=name) OU phone_digits
            existing = await db.officines.find_one({
                "$or": ([{"name": nom}] + ([{"phone_digits": phone_digits}] if phone_digits else []))
            })
            if existing:
                results.append({"row": row_idx, "skipped": True, "reason": "Doublon (nom ou téléphone)", "officine_id": existing.get("id")})
                skipped += 1
                continue
            oid = str(uuid.uuid4())
            doc = {
                "id": oid,
                "name": nom,                           # = code (par contrat utilisateur)
                "code": nom,                           # alias explicite
                "intitule": None,                      # rempli ensuite via fiche
                "email": None,
                "phone": (f"+{phone_digits}" if phone_digits else None),
                "phone_digits": phone_digits or None,
                "whatsapp": None,
                "whatsapp_digits": None,
                "address": None,
                "city": ville or None,
                "country": None,
                "location_hint": indications or None,
                "numero_ordre": ordre or None,
                "contact_name": None,
                "logo_url": None,
                "latitude": None,
                "longitude": None,
                "linked_client_id": None,
                "linked_client_email": None,
                "status": "pending",
                "created_at": _now(),
                "created_via": "csv_import",
                "validated_at": None, "validated_by": None,
                "activated_at": None, "activated_by": None, "activated_via": None,
                "last_login_at": None,
            }
            await db.officines.insert_one(doc.copy())
            await db.officine_audit_log.insert_one({
                "id": str(uuid.uuid4()), "officine_id": oid,
                "action": "csv_import", "actor": user.get("email"),
                "details": {"row": row_idx, "filename": getattr(upload, "filename", None)},
                "created_at": _now(),
            })
            created += 1
            results.append({"row": row_idx, "officine_id": oid, "name": nom})
        return {
            "ok": True,
            "created": created,
            "skipped": skipped,
            "header_detected": has_header,
            "results": results,
        }

    # Iter43-fix23 (2026-06) — Création manuelle d'une officine depuis l'UI Admin
    @api.post("/admin/officines-registry", tags=["Admin — Officines Registry"])
    async def create_officine(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_user or get_current_admin),
    ):
        """Création manuelle d'une officine.

        Champs requis : `name` (sert aussi de `code`).
        Champs optionnels : tous les autres (intitule, email, phone, whatsapp,
        address, city, country, location_hint, numero_ordre, contact_name,
        latitude, longitude, role, groupe_garde, activite_principale).

        Iter43-fix24n : utilisateur "délégué" peut créer une officine avec TOUS
        les champs (la restriction limited s'applique seulement à l'édition).
        """
        # Iter43-fix24n — admin OU délégué
        if get_current_user is not None:
            await _get_officines_menu_user(user)
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="`name` requis")
        # Anti-doublon : vérifie sur le name (= code) ou phone_digits
        phone = (payload.get("phone") or "").strip()
        phone_digits = _digits(phone) or None
        wa = (payload.get("whatsapp") or "").strip()
        wa_digits = _digits(wa) or None
        or_filters: List[Dict[str, Any]] = [{"name": name}]
        if phone_digits:
            or_filters.append({"phone_digits": phone_digits})
        dupe = await db.officines.find_one({"$or": or_filters}, {"_id": 0, "id": 1, "name": 1})
        if dupe:
            raise HTTPException(
                status_code=409,
                detail=f"Doublon détecté : une officine existe déjà avec ce nom ou ce téléphone ({dupe.get('name')}).",
            )
        # Validation rôle si fourni
        role_val = (payload.get("role") or "").strip() or None
        if role_val:
            roles_doc = await db.settings.find_one({"_id": "global"}, {"_id": 0, "officine_roles": 1}) or {}
            roles = roles_doc.get("officine_roles") or _DEFAULT_OFFICINE_ROLES
            if role_val not in roles:
                raise HTTPException(status_code=400, detail=f"Rôle '{role_val}' inconnu. Définissez-le d'abord dans Gérer les rôles.")
        # Validation groupe_garde si fourni
        gg = payload.get("groupe_garde")
        if gg is not None and gg != "":
            try:
                gg = int(gg)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="groupe_garde doit être un entier")
            if gg < 1 or gg > 100:
                raise HTTPException(status_code=400, detail="groupe_garde doit être entre 1 et 100")
        else:
            gg = None
        # Lat/lng numériques
        def _num(v):
            if v in (None, ""):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="latitude/longitude doivent être numériques")

        oid = str(uuid.uuid4())
        doc = {
            "id": oid,
            "name": name,
            "code": name,
            "intitule": (payload.get("intitule") or "").strip() or None,
            "email": (payload.get("email") or "").strip() or None,
            "phone": (f"+{phone_digits}" if phone_digits else None),
            "phone_digits": phone_digits,
            "whatsapp": (f"+{wa_digits}" if wa_digits else None),
            "whatsapp_digits": wa_digits,
            "address": (payload.get("address") or "").strip() or None,
            "city": (payload.get("city") or "").strip() or None,
            "country": (payload.get("country") or "").strip() or None,
            "location_hint": (payload.get("location_hint") or "").strip() or None,
            "numero_ordre": (payload.get("numero_ordre") or "").strip() or None,
            "contact_name": (payload.get("contact_name") or "").strip() or None,
            "logo_url": None,
            "latitude": _num(payload.get("latitude")),
            "longitude": _num(payload.get("longitude")),
            "linked_client_id": None,
            "linked_client_email": None,
            "status": (payload.get("status") or "pending").strip().lower(),
            "role": role_val,
            "groupe_garde": gg,
            "activite_principale": (payload.get("activite_principale") or "").strip() or None,
            "created_at": _now(),
            "created_by": user.get("email"),
            "created_via": "admin_manual",
            "validated_at": None, "validated_by": None,
            "activated_at": None, "activated_by": None, "activated_via": None,
            "last_login_at": None,
        }
        if doc["status"] not in ("pending", "active", "suspended"):
            doc["status"] = "pending"
        # Iter43-fix24v (2026-06-16) — Auto-calcul de `intitule` quand vide :
        # si name + role sont renseignés et intitule vide, intitule = "{role} {name}".
        if not doc["intitule"] and doc["name"] and doc["role"]:
            doc["intitule"] = f"{doc['role']} {doc['name']}"
        await db.officines.insert_one(doc.copy())
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": oid,
            "action": "create_manual", "actor": user.get("email"),
            "details": {"fields": list(payload.keys())}, "created_at": _now(),
        })
        doc.pop("_id", None)
        return {"ok": True, "officine": doc}

    @api.put("/admin/officines-registry/{officine_id}", tags=["Admin — Officines Registry"])
    async def update_officine(
        officine_id: str,
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_user or get_current_admin),
    ):
        """Mise à jour d'une fiche officine. Champs autorisés : name (=code),
        intitule, email, phone, whatsapp, address, city, country, location_hint,
        numero_ordre, contact_name, logo_url, latitude, longitude.

        Iter43-fix24n : un utilisateur "délégué" (non-admin listé dans
        `officines_menu_allowed_emails`) ne peut modifier QUE :
        intitule, phone, whatsapp, latitude, longitude, location_hint,
        activite_principale.
        """
        # Iter43-fix24n — Délégation
        edit_mode = "full"
        if get_current_user is not None:
            _, edit_mode = await _get_officines_menu_user(user)

        existing = await db.officines.find_one({"id": officine_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        allowed = {
            "name", "code", "intitule", "email", "phone", "whatsapp",
            "address", "city", "country", "location_hint",
            "numero_ordre", "contact_name", "logo_url",
            "latitude", "longitude",
            "activite_principale",
            "role", "groupe_garde",
        }
        # Iter43-fix24n — En mode limited, on filtre par la whitelist des champs délégués.
        # Champs envoyés par l'UI mais non autorisés en limited → rejet silencieux
        # (UX : le frontend grise déjà les autres champs).
        if edit_mode == "limited":
            allowed = allowed & _OFFICINE_DELEGATED_EDITABLE_FIELDS
        update: Dict[str, Any] = {}
        for k, v in (payload or {}).items():
            if k not in allowed:
                continue
            if v == "":
                update[k] = None
            else:
                update[k] = v
        # Synchronise phone_digits / whatsapp_digits si phone ou whatsapp changent
        if "phone" in update:
            update["phone_digits"] = _digits(update["phone"] or "") or None
        if "whatsapp" in update:
            update["whatsapp_digits"] = _digits(update["whatsapp"] or "") or None
        # `name` est aussi le code par contrat utilisateur
        if "name" in update and "code" not in update:
            update["code"] = update["name"]
        # Validation lat/lng
        for fld in ("latitude", "longitude"):
            if fld in update and update[fld] is not None:
                try:
                    update[fld] = float(update[fld])
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"{fld} doit être numérique")
        # Iter43-fix21 — Validation Groupe de Garde (entier ≥ 1)
        if "groupe_garde" in update and update["groupe_garde"] is not None:
            try:
                update["groupe_garde"] = int(update["groupe_garde"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="groupe_garde doit être un entier")
            if update["groupe_garde"] < 1 or update["groupe_garde"] > 100:
                raise HTTPException(status_code=400, detail="groupe_garde doit être entre 1 et 100")
        # Iter43-fix21 — Validation rôle (doit exister dans le registre)
        if "role" in update and update["role"] is not None:
            role_value = (update["role"] or "").strip()
            update["role"] = role_value or None
            if role_value:
                roles_doc = await db.settings.find_one({"_id": "global"}, {"_id": 0, "officine_roles": 1}) or {}
                roles = roles_doc.get("officine_roles") or _DEFAULT_OFFICINE_ROLES
                if role_value not in roles:
                    raise HTTPException(status_code=400, detail=f"Rôle '{role_value}' inconnu. Définissez-le d'abord dans Admin → Officines → Rôles.")
        # Iter43-fix24v (2026-06-16) — Auto-calcul de `intitule` quand vide.
        # Règle métier demandée par l'utilisateur : si `intitule` reste vide
        # mais que `name` ET `role` sont renseignés (en valeur effective après
        # mise à jour), alors intitule = "{role} {name}".
        eff_intitule = update.get("intitule") if "intitule" in update else existing.get("intitule")
        eff_intitule_is_empty = not (eff_intitule and str(eff_intitule).strip())
        if eff_intitule_is_empty:
            eff_name = update.get("name") if "name" in update else existing.get("name")
            eff_role = update.get("role") if "role" in update else existing.get("role")
            eff_name_s = (eff_name or "").strip() if isinstance(eff_name, str) else ""
            eff_role_s = (eff_role or "").strip() if isinstance(eff_role, str) else ""
            if eff_name_s and eff_role_s:
                update["intitule"] = f"{eff_role_s} {eff_name_s}"
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ valide à mettre à jour")
        update["updated_at"] = _now()
        update["updated_by"] = user.get("email")
        await db.officines.update_one({"id": officine_id}, {"$set": update})
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "edit", "actor": user.get("email"),
            "details": {"fields": list(update.keys())}, "created_at": _now(),
        })
        fresh = await db.officines.find_one({"id": officine_id}, {"_id": 0})
        return {"ok": True, "officine": fresh}

    @api.post("/admin/officines-registry/{officine_id}/upload-logo", tags=["Admin — Officines Registry"])
    async def upload_logo(
        officine_id: str,
        request: Request,
        user: dict = Depends(get_current_admin),
    ):
        """Upload du logo d'une officine.

        Iter43-fix21 (2026-06) — **Stockage MongoDB (base64)** pour résister
        aux redéploiements Kubernetes. Le disque conteneur `/app/backend/uploads/`
        est éphémère : tous les fichiers étaient perdus à chaque redéploy
        (« les logos marchaient hier, cassés aujourd'hui »). On stocke
        désormais l'image dans `db.officines.logo_data_b64` (persistant).
        """
        from fastapi import UploadFile
        import base64 as _b64
        existing = await db.officines.find_one({"id": officine_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        form = await request.form()
        upload: Optional[UploadFile] = form.get("file")  # type: ignore[assignment]
        if upload is None:
            raise HTTPException(status_code=400, detail="Fichier manquant (champ `file`)")
        raw = await upload.read()
        # Base64 augmente la taille de ~33% → on limite l'upload à 2 Mo
        # pour rester sous 3 Mo une fois encodé (limite MongoDB pratique).
        if len(raw) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Logo trop volumineux (max 2 Mo). Compressez l'image avant de la téléverser.")
        ext = (upload.filename or "logo.png").rsplit(".", 1)[-1].lower()[:5] or "png"
        if ext not in {"png", "jpg", "jpeg", "webp", "svg", "gif"}:
            raise HTTPException(status_code=400, detail="Format non supporté (png/jpg/webp/svg)")
        data_b64 = _b64.b64encode(raw).decode("ascii")
        rel_url = f"/officines-registry/{officine_id}/logo"
        await db.officines.update_one(
            {"id": officine_id},
            {"$set": {
                "logo_url": rel_url,
                "logo_data_b64": data_b64,
                "logo_ext": ext,
                "logo_size_bytes": len(raw),
                "updated_at": _now(),
                "updated_by": user.get("email"),
            },
             # Iter43-fix21 — Purger l'ancien chemin disque devenu obsolète
             "$unset": {"logo_path": ""}},
        )
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "upload_logo", "actor": user.get("email"),
            "details": {"filename": upload.filename or "logo", "size_bytes": len(raw), "storage": "mongo_b64"},
            "created_at": _now(),
        })
        return {"ok": True, "logo_url": rel_url, "size_bytes": len(raw)}

    # Iter43-fix21 — Streaming public du logo. Source : base64 en DB, fallback
    # ancien chemin disque pour les fiches non encore migrées (et qui existent
    # encore localement, ce qui n'est pas garanti après un redéploy).
    @api.get("/officines-registry/{officine_id}/logo", tags=["Officines Registry — Public"])
    async def get_officine_logo(officine_id: str):
        import base64 as _b64
        from fastapi.responses import FileResponse, Response
        doc = await db.officines.find_one(
            {"id": officine_id},
            {"_id": 0, "logo_path": 1, "logo_ext": 1, "logo_url": 1, "logo_data_b64": 1},
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        ext = (doc.get("logo_ext") or "png").lower()
        media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "svg": "image/svg+xml", "gif": "image/gif"}
        media_type = media_map.get(ext, "application/octet-stream")
        # 1. Stockage moderne : base64 en MongoDB
        b64 = doc.get("logo_data_b64")
        if b64:
            try:
                raw = _b64.b64decode(b64)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"Logo corrompu en DB: {exc}") from exc
            return Response(content=raw, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})
        # 2. Fallback legacy : fichier sur disque (peut avoir été perdu au redeploy)
        logo_path = doc.get("logo_path")
        if not logo_path and (doc.get("logo_url") or "").startswith("/uploads/officines/"):
            try:
                from server import UPLOAD_DIR as _U
            except Exception:
                _U = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
            fname = doc["logo_url"].rsplit("/", 1)[-1]
            cand = Path(_U) / "officines" / fname
            if cand.exists():
                logo_path = str(cand)
        if not logo_path or not Path(logo_path).exists():
            raise HTTPException(status_code=404, detail="Logo introuvable (à téléverser à nouveau)")
        # Migrer en MongoDB pour ne plus dépendre du disque éphémère
        try:
            raw = Path(logo_path).read_bytes()
            await db.officines.update_one(
                {"id": officine_id},
                {"$set": {"logo_data_b64": _b64.b64encode(raw).decode("ascii"),
                          "logo_size_bytes": len(raw),
                          "logo_url": f"/officines-registry/{officine_id}/logo"},
                 "$unset": {"logo_path": ""}},
            )
        except Exception:  # noqa: BLE001
            pass
        return FileResponse(
            logo_path,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Iter43-fix21 — Diagnostic des logos (déclaré plus haut, route /logos/health).

    @api.post("/admin/officines-registry/import-to-contacts", tags=["Admin — Officines Registry"])
    async def import_to_contacts(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        """Importe une sélection d'officines dans le répertoire de contacts du
        client_scope de l'utilisateur (admin SAWALI) et les ajoute à un
        groupe « Officine » (créé si nécessaire).

        Body : { officine_ids: [str, ...], group_name?: str (défaut 'Officines') }
        """
        officine_ids = [x for x in (payload.get("officine_ids") or []) if isinstance(x, str) and x]
        if not officine_ids:
            raise HTTPException(status_code=400, detail="Aucune officine sélectionnée")
        group_name = (payload.get("group_name") or "Officines").strip() or "Officines"

        officines = await db.officines.find({"id": {"$in": officine_ids}}, {"_id": 0}).to_list(len(officine_ids))
        if not officines:
            raise HTTPException(status_code=404, detail="Aucune officine trouvée pour ces ids")

        # Scope contacts = client_id de l'admin (= son own id par défaut)
        client_scope = user.get("parent_client_id") or user["id"]

        # Récupère/crée le groupe
        existing_group = await db.contact_groups.find_one(
            {"client_id": client_scope, "name": group_name}, {"_id": 0},
        )
        if existing_group:
            group = existing_group
        else:
            group = {
                "id": str(uuid.uuid4()),
                "client_id": client_scope,
                "name": group_name,
                "description": "Importé automatiquement depuis le Registre des Officines",
                "color": "#0EA5E9",
                "contact_ids": [],
                "created_at": _now(),
                "updated_at": _now(),
                "created_by": user.get("id"),
                "owner_user_id": user.get("id"),
                "owner_user_email": user.get("email"),
                "shared_with_tenant": True,
                "editable_by_tenant": True,
            }
            await db.contact_groups.insert_one(group.copy())

        created_contact_ids: List[str] = []
        existing_contact_ids: List[str] = []
        for off in officines:
            phone = off.get("phone") or ""
            phone_digits = off.get("phone_digits") or ""
            whatsapp = off.get("whatsapp") or off.get("phone") or ""
            # Dédoublonnage : sur (client_scope, name) ou phone_digits
            dup = None
            if phone_digits:
                dup = await db.directory_contacts.find_one(
                    {"client_id": client_scope, "$or": [
                        {"name": off.get("name")},
                        {"phone": {"$regex": phone_digits + "$"}},
                    ]},
                    {"_id": 0, "id": 1},
                )
            else:
                dup = await db.directory_contacts.find_one(
                    {"client_id": client_scope, "name": off.get("name")},
                    {"_id": 0, "id": 1},
                )
            if dup:
                existing_contact_ids.append(dup["id"])
                continue
            cid = str(uuid.uuid4())
            doc = {
                "id": cid,
                "client_id": client_scope,
                "owner_user_id": user.get("id"),
                "owner_user_email": user.get("email"),
                "name": off.get("intitule") or off.get("name") or "",
                "phone": phone,
                "whatsapp": whatsapp,
                "email": off.get("email") or "",
                "company": off.get("name") or "",
                "notes": f"Officine SAWALI • Code: {off.get('name')} • Ordre: {off.get('numero_ordre') or '—'} • Ville: {off.get('city') or '—'}",
                "tags": ["Officine"],
                "shared": True,
                "shared_with_tenant": True,
                "editable_by_tenant": True,
                "officine_id": off["id"],
                "photo_url": off.get("logo_url"),
                "created_at": _now(),
            }
            await db.directory_contacts.insert_one(doc.copy())
            created_contact_ids.append(cid)

        # Met à jour le groupe avec les nouveaux contacts
        all_contact_ids = list(set((group.get("contact_ids") or []) + created_contact_ids + existing_contact_ids))
        await db.contact_groups.update_one(
            {"id": group["id"]},
            {"$set": {"contact_ids": all_contact_ids, "updated_at": _now()}},
        )

        return {
            "ok": True,
            "group_id": group["id"],
            "group_name": group["name"],
            "created": len(created_contact_ids),
            "already_existing": len(existing_contact_ids),
            "total_in_group": len(all_contact_ids),
        }

    # =====================================================================
    # Iter43-fix12 (2026-03) — Activités principales (Task 3)
    # NB: path "/admin/officine-activities" et non "/admin/officines-registry/activities"
    # pour éviter le shadowing par la route paramétrée "/{officine_id}".
    # =====================================================================
    DEFAULT_ACTIVITES = ["Pharmacie", "Grossiste", "Dépôt", "Distributeur"]

    @api.get("/admin/officine-activities", tags=["Admin — Officines Registry"])
    async def list_activities(_: dict = Depends(get_current_admin)):
        doc = await db.settings.find_one({"_id": "global"}) or {}
        acts = doc.get("officines_activities")
        if not acts or not isinstance(acts, list):
            acts = DEFAULT_ACTIVITES
        return {"activities": acts}

    @api.put("/admin/officine-activities", tags=["Admin — Officines Registry"])
    async def update_activities(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        raw = payload.get("activities")
        if not isinstance(raw, list):
            raise HTTPException(status_code=400, detail="`activities` doit être une liste")
        cleaned: List[str] = []
        seen = set()
        for x in raw:
            s = str(x or "").strip()
            if not s or len(s) > 60:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(s)
        if not cleaned:
            raise HTTPException(status_code=400, detail="Au moins une activité requise")
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"officines_activities": cleaned, "officines_activities_updated_at": _now(),
                      "officines_activities_updated_by": user.get("email")}},
            upsert=True,
        )
        return {"ok": True, "activities": cleaned}

    # =====================================================================
    # Iter43-fix12 (2026-03) — Produits par officine (Tasks 1 & 2)
    # =====================================================================
    def _norm_key(s: Any) -> str:
        """Clé de normalisation pour unicité (lower + trim + espaces collapsés)."""
        if s is None:
            return ""
        return " ".join(str(s).strip().lower().split())

    def _detect_csv_delimiter(text: str) -> str:
        first_line = (text.split("\n", 1)[0] or "")
        return ";" if first_line.count(";") > first_line.count(",") else ","

    def _normalize_header(h: str) -> str:
        """Mappe les en-têtes CSV vers nos champs canoniques."""
        h_low = (h or "").strip().lower()
        # Suppression des accents pour matching
        import unicodedata
        h_low = "".join(
            c for c in unicodedata.normalize("NFD", h_low)
            if unicodedata.category(c) != "Mn"
        )
        if h_low in {"code officine", "code", "officine"}:
            return "officine_code"
        if h_low in {"produit", "nom produit", "nom du produit", "designation",
                     "designation produit", "libelle", "libelle produit"}:
            return "product_name"
        if h_low in {"conditionnement", "cond", "presentation", "forme"}:
            return "conditionnement"
        if h_low in {"cip", "code cip", "cip13", "cip7", "cip-13", "cip-7"}:
            return "cip"
        if h_low in {"stock", "quantite", "qte", "qty", "qt"}:
            return "stock"
        return h_low.replace(" ", "_")

    def _flatten_json_products(data: Any) -> List[Dict[str, Any]]:
        """Aplatit n'importe quelle structure JSON imbriquée vers une liste de
        produits. Cherche les dicts qui ressemblent à un produit (champ
        product_name OU produit OU designation présent).

        Exemples acceptés :
        - [{"Produit": "Doliprane", "CIP": "...", "Stock": 10}, ...]
        - {"produits": [...]}
        - {"officine": "X", "items": {"medicaments": [...]}}
        - {"data": {"results": [{"Produit": ...}]}}
        """
        out: List[Dict[str, Any]] = []

        def _looks_like_product(d: Dict[str, Any]) -> bool:
            keys_lower = {str(k).strip().lower() for k in d.keys()}
            return bool(
                keys_lower & {"produit", "product_name", "nom produit", "nom du produit",
                              "designation", "libelle", "libelle produit"}
            )

        def _walk(node: Any):
            if isinstance(node, list):
                for x in node:
                    _walk(x)
            elif isinstance(node, dict):
                if _looks_like_product(node):
                    out.append(node)
                else:
                    for v in node.values():
                        _walk(v)
        _walk(data)
        return out

    @api.post("/admin/officines-registry/{officine_id}/products/import",
              tags=["Admin — Officines Registry"])
    async def import_products(
        officine_id: str,
        request: Request,
        user: dict = Depends(get_current_admin),
    ):
        """Import en masse de produits pour une officine (CSV ou JSON).

        Format CSV (séparateur auto `,` ou `;`) :
            Code Officine,Produit,Conditionnement,CIP,Stock
        Format JSON : liste plate OU structure imbriquée (auto-aplatie).
        Mode : `replace` (vide + ré-importe) OU `append` (ajoute sans toucher).
        Clé d'unicité : (officine_id, product_name, conditionnement) en minuscules.
        """
        from fastapi import UploadFile
        existing = await db.officines.find_one({"id": officine_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Officine introuvable")

        form = await request.form()
        upload: Optional[UploadFile] = form.get("file")  # type: ignore[assignment]
        mode = (str(form.get("mode") or "replace")).lower()
        if mode not in {"replace", "append"}:
            raise HTTPException(status_code=400, detail="mode invalide (replace|append)")
        if upload is None:
            raise HTTPException(status_code=400, detail="Fichier manquant (champ `file`)")
        raw = await upload.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Fichier vide")
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 20 Mo)")

        filename = (upload.filename or "").lower()
        is_json = filename.endswith(".json") or raw.lstrip().startswith((b"{", b"["))

        rows: List[Dict[str, Any]] = []
        header_detected = False
        if is_json:
            import json
            try:
                data = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"JSON invalide : {exc}")
            flat = _flatten_json_products(data)
            for d in flat:
                norm = {_normalize_header(k): v for k, v in d.items()}
                rows.append(norm)
        else:
            text = raw.decode("utf-8-sig", errors="replace")
            delim = _detect_csv_delimiter(text)
            reader = csv.reader(io.StringIO(text), delimiter=delim)
            all_rows = [r for r in reader if any((c or "").strip() for c in r)]
            if not all_rows:
                raise HTTPException(status_code=400, detail="Aucune ligne exploitable")
            # Détection en-tête : si la 1re ligne contient au moins un mot-clé connu
            head_norm = [_normalize_header(h) for h in all_rows[0]]
            known = {"officine_code", "product_name", "conditionnement", "cip", "stock"}
            if any(h in known for h in head_norm):
                header_detected = True
                headers = head_norm
                data_rows = all_rows[1:]
            else:
                # Format positionnel : Code Officine, Produit, Conditionnement, CIP, Stock
                headers = ["officine_code", "product_name", "conditionnement", "cip", "stock"]
                data_rows = all_rows
            for r in data_rows:
                d = {headers[i]: r[i] if i < len(r) else "" for i in range(min(len(headers), len(r)))}
                rows.append(d)

        # Mode replace : vide la collection pour cette officine
        if mode == "replace":
            await db.officine_products.delete_many({"officine_id": officine_id})

        # Officine code (utilisé si la colonne est absente)
        default_code = existing.get("code") or existing.get("name") or ""

        created = 0
        updated = 0
        skipped = 0
        errors: List[Dict[str, Any]] = []
        seen_keys = set()  # pour anti-doublons intra-fichier
        bulk_docs: List[Dict[str, Any]] = []

        for idx, row in enumerate(rows, start=2 if header_detected else 1):
            product_name = str(row.get("product_name") or row.get("produit") or "").strip()
            if not product_name:
                skipped += 1
                if len(errors) < 50:
                    errors.append({"row": idx, "reason": "Nom de produit manquant"})
                continue
            conditionnement = str(row.get("conditionnement") or "").strip()
            cip = str(row.get("cip") or "").strip() or None
            officine_code = str(row.get("officine_code") or default_code).strip()
            stock_raw = row.get("stock")
            try:
                stock = int(str(stock_raw).strip()) if stock_raw not in (None, "", "—") else 0
            except (TypeError, ValueError):
                stock = 0

            key = (_norm_key(product_name), _norm_key(conditionnement))
            if key in seen_keys:
                skipped += 1
                if len(errors) < 50:
                    errors.append({"row": idx, "reason": f"Doublon intra-fichier : {product_name}"})
                continue
            seen_keys.add(key)

            now = _now().isoformat()
            doc = {
                "id": str(uuid.uuid4()),
                "officine_id": officine_id,
                "officine_code": officine_code,
                "product_name": product_name,
                "product_name_norm": _norm_key(product_name),
                "conditionnement": conditionnement,
                "conditionnement_norm": _norm_key(conditionnement),
                "cip": cip,
                "stock": stock,
                "created_at": now,
                "updated_at": now,
                "imported_by": user.get("email"),
            }

            if mode == "replace":
                bulk_docs.append(doc)
                created += 1
            else:
                # Mode append : upsert basé sur la clé d'unicité
                r = await db.officine_products.update_one(
                    {"officine_id": officine_id,
                     "product_name_norm": doc["product_name_norm"],
                     "conditionnement_norm": doc["conditionnement_norm"]},
                    {"$set": {
                        "product_name": product_name,
                        "conditionnement": conditionnement,
                        "cip": cip,
                        "stock": stock,
                        "officine_code": officine_code,
                        "updated_at": now,
                        "updated_by": user.get("email"),
                    },
                     "$setOnInsert": {
                         "id": doc["id"], "officine_id": officine_id,
                         "product_name_norm": doc["product_name_norm"],
                         "conditionnement_norm": doc["conditionnement_norm"],
                         "created_at": now,
                         "imported_by": user.get("email"),
                     }},
                    upsert=True,
                )
                if r.upserted_id:
                    created += 1
                elif r.matched_count:
                    updated += 1

        # Insert en bulk pour le mode replace
        if mode == "replace" and bulk_docs:
            BATCH = 1000
            for i in range(0, len(bulk_docs), BATCH):
                await db.officine_products.insert_many(bulk_docs[i:i + BATCH])

        # Index pour requêtes rapides (idempotent)
        try:
            await db.officine_products.create_index([("officine_id", 1), ("product_name_norm", 1)])
            await db.officine_products.create_index([("officine_id", 1), ("conditionnement_norm", 1)])
        except Exception:  # noqa: BLE001
            pass

        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "products_import",
            "actor": user.get("email"),
            "details": {
                "mode": mode, "format": "json" if is_json else "csv",
                "created": created, "updated": updated, "skipped": skipped,
                "filename": filename,
            },
            "created_at": _now(),
        })

        return {
            "ok": True,
            "mode": mode,
            "format": "json" if is_json else "csv",
            "header_detected": header_detected,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    @api.get("/admin/officines-registry/{officine_id}/products",
             tags=["Admin — Officines Registry"])
    async def list_products(
        officine_id: str,
        q: Optional[str] = Query(None),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
        sort: str = Query("product_name", pattern="^(product_name|cip|stock|conditionnement|created_at)$"),
        order: str = Query("asc", pattern="^(asc|desc)$"),
        _: dict = Depends(get_current_admin),
    ):
        existing = await db.officines.find_one({"id": officine_id}, {"_id": 0, "id": 1, "name": 1})
        if not existing:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        query: Dict[str, Any] = {"officine_id": officine_id}
        if q:
            qstr = q.strip()
            query["$or"] = [
                {"product_name": {"$regex": qstr, "$options": "i"}},
                {"cip": {"$regex": qstr}},
                {"conditionnement": {"$regex": qstr, "$options": "i"}},
            ]
        total = await db.officine_products.count_documents(query)
        sort_dir = 1 if order == "asc" else -1
        cur = (
            db.officine_products.find(query, {"_id": 0})
            .sort(sort, sort_dir)
            .skip(offset)
            .limit(limit)
        )
        items = await cur.to_list(limit)
        return {
            "items": items,
            "total": total,
            "offset": offset,
            "limit": limit,
            "officine": {"id": existing["id"], "name": existing.get("name")},
        }

    @api.delete("/admin/officines-registry/{officine_id}/products",
                tags=["Admin — Officines Registry"])
    async def clear_products(officine_id: str, user: dict = Depends(get_current_admin)):
        existing = await db.officines.find_one({"id": officine_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        r = await db.officine_products.delete_many({"officine_id": officine_id})
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "products_clear",
            "actor": user.get("email"),
            "details": {"deleted": int(r.deleted_count or 0)},
            "created_at": _now(),
        })
        return {"ok": True, "deleted": int(r.deleted_count or 0)}

    @api.get("/admin/officines-registry/{officine_id}/products/export.csv",
             tags=["Admin — Officines Registry"])
    async def export_products_csv(officine_id: str, _: dict = Depends(get_current_admin)):
        existing = await db.officines.find_one({"id": officine_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Officine introuvable")

        async def _stream():
            buf = io.StringIO()
            writer = csv.writer(buf, delimiter=",")
            writer.writerow(["Code Officine", "Produit", "Conditionnement", "CIP", "Stock"])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            async for doc in db.officine_products.find({"officine_id": officine_id}, {"_id": 0}).sort("product_name", 1):
                writer.writerow([
                    doc.get("officine_code") or "",
                    doc.get("product_name") or "",
                    doc.get("conditionnement") or "",
                    doc.get("cip") or "",
                    str(doc.get("stock") or 0),
                ])
                if buf.tell() > 8192:
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate(0)
            if buf.tell():
                yield buf.getvalue()

        safe_name = (existing.get("name") or officine_id).replace(" ", "_")
        return StreamingResponse(
            _stream(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="produits_{safe_name}.csv"'},
        )

    logger.info("[officines_portal] admin registry routes mounted")


def attach_synthese_otp_admin_routes(
    api: APIRouter | FastAPI,
    *,
    db,
    get_current_admin,
    wa_send_text: Optional[Callable[[str, str], Awaitable[Dict[str, Any]]]] = None,
) -> None:
    """Iter42b — Admin endpoints :
      - POST /api/admin/synthese/test          → déclenche la synthèse Liluvine immédiatement
      - POST /api/admin/officine-otp/test      → envoie un OTP test via le template configuré
    """

    @api.post("/admin/synthese/test", tags=["Admin — Synthèse"])
    async def admin_synthese_test(user: dict = Depends(get_current_admin)):
        from routes.synthese import run_synthese_test
        try:
            result = await run_synthese_test(db)
            return result
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Erreur synthèse : {str(exc)[:300]}") from exc

    @api.post("/admin/officine-otp/test", tags=["Admin — Officines OTP"])
    async def admin_officine_otp_test(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        msisdn = "".join(ch for ch in str(payload.get("msisdn") or "") if ch.isdigit())
        if len(msisdn) < 8:
            raise HTTPException(status_code=400, detail="Numéro invalide")
        s = await db.settings.find_one({"_id": "global"}) or {}
        template_name = (s.get("officine_otp_template") or "").strip()
        lang = (s.get("officine_otp_template_lang") or "fr").strip() or "fr"
        access_token = s.get("wa_access_token") or ""
        phone_number_id = s.get("wa_phone_number_id") or ""
        if not access_token or not phone_number_id:
            raise HTTPException(status_code=503, detail="WhatsApp Cloud API non configuré (wa_access_token / wa_phone_number_id)")
        code = f"{random.randint(0, 999999):06d}"
        results: List[Dict[str, Any]] = []
        # Si template configuré, on tente Authentication puis Utility ; sinon, fallback texte
        if template_name:
            import httpx as _httpx
            url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
            headers = {"Authorization": f"Bearer {access_token}"}
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
                    async with _httpx.AsyncClient(timeout=10.0) as client:
                        r = await client.post(url, json=body, headers=headers)
                    ok = r.status_code == 200
                    results.append({
                        "category_tried": label,
                        "http_status": r.status_code,
                        "meta_response": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:500],
                        "ok": ok,
                    })
                    if ok:
                        await db.settings.update_one(
                            {"_id": "global"},
                            {"$set": {"officine_otp_template_category": label.upper()}},
                            upsert=True,
                        )
                        return {
                            "ok": True, "sent_via": f"template_{label}",
                            "test_code": code, "attempts": results,
                        }
                except Exception as exc:  # noqa: BLE001
                    results.append({"category_tried": label, "exception": str(exc)[:300], "ok": False})
        # Fallback: texte brut
        if wa_send_text:
            msg = f"SAWALI Officines (TEST) — Code de connexion : {code}. Valable 10 min."
            r = await wa_send_text(f"+{msisdn}", msg)
            if r.get("ok"):
                return {"ok": True, "sent_via": "text_fallback", "test_code": code, "attempts": results}
            results.append({"category_tried": "text_fallback", "ok": False, "error": r.get("error", "")[:200]})
        return {
            "ok": False, "test_code": code, "attempts": results,
            "hint": "Vérifiez : (1) le nom du template (champ officine_otp_template), (2) la langue, (3) l'approbation Meta, (4) le numéro destinataire au format E.164 sans +.",
        }

    logger.info("[officines_portal] synthese/otp test routes mounted")
