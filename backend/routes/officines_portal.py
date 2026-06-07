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
import random
import secrets as pysecrets
import uuid
from datetime import datetime, timedelta, timezone
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
            r = await wa_send_text(phone, msg)
            if not r.get("ok"):
                raise HTTPException(status_code=502, detail=f"Envoi WhatsApp échoué : {r.get('error', 'erreur inconnue')[:200]}")
            sent_via = "whatsapp"
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
) -> None:
    """Admin-only routes for officine validation/management.

    Mounted under /api/admin/officines-registry/*
    """

    @api.get("/admin/officines-registry", tags=["Admin — Officines Registry"])
    async def list_registry(
        status: Optional[str] = Query(None, pattern="^(pending|active|suspended)$"),
        q: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        user: dict = Depends(get_current_admin),
    ):
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        if q:
            query["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"email": {"$regex": q, "$options": "i"}},
                {"phone_digits": {"$regex": q}},
                {"city": {"$regex": q, "$options": "i"}},
            ]
        cur = db.officines.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        items = await cur.to_list(limit)
        # Counts by status (utile pour le dashboard)
        counts = {"pending": 0, "active": 0, "suspended": 0}
        async for d in db.officines.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
            if d.get("_id") in counts:
                counts[d["_id"]] = int(d.get("n") or 0)
        return {"items": items, "count": len(items), "counts": counts}

    @api.get("/admin/officines-registry/{officine_id}", tags=["Admin — Officines Registry"])
    async def detail(officine_id: str, user: dict = Depends(get_current_admin)):
        doc = await db.officines.find_one({"id": officine_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Officine introuvable")
        # Inventaire + items count
        items_count = await db.officine_inventory_items.count_documents({"officine_id": officine_id})
        history_count = await db.officine_audit_log.count_documents({"officine_id": officine_id})
        return {"officine": doc, "items_count": items_count, "history_count": history_count}

    @api.post("/admin/officines-registry/{officine_id}/approve", tags=["Admin — Officines Registry"])
    async def approve(officine_id: str, user: dict = Depends(get_current_admin)):
        r = await db.officines.update_one(
            {"id": officine_id, "status": {"$ne": "active"}},
            {"$set": {"status": "active", "validated_at": _now(), "validated_by": user.get("email")}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Officine introuvable ou déjà active")
        await db.officine_audit_log.insert_one({
            "id": str(uuid.uuid4()), "officine_id": officine_id,
            "action": "approve", "actor": user.get("email"),
            "details": {}, "created_at": _now(),
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

    logger.info("[officines_portal] admin registry routes mounted")
