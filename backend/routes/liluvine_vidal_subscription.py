"""Abonnements Liluvine VIDAL (essai, quota gratuit, formules payantes).

Portage fidèle des règles métier documentées dans PORTAGE-SAWALI-VIDAL.md
("Liluvine — requêtes produit par WhatsApp"), jamais implémentées côté
serveur dans le prototype d'origine (tout y vivait en mémoire navigateur) :

  - Un numéro non autorisé reçoit une invitation polie à s'inscrire, ET une
    notification est envoyée à l'Admin (réutilise `liluvine_escalation.
    notify_admin`, déjà throttlée par numéro).
  - L'Admin autorise un numéro → essai gratuit de `trial_days` jours
    (3 par défaut, réglable).
  - `free_requests_threshold` requêtes gratuites (3 par défaut, réglable —
    distinct de `trial_days` bien que la valeur par défaut soit la même),
    puis abonnement obligatoire à partir de la requête N+1 : formules jour /
    semaine / mois / trimestriel / annuel, chacune avec sa durée et son
    coût (montants FCFA de DÉMONSTRATION dans DEFAULT_CONFIG — à fixer
    réellement par l'utilisateur via l'admin).
  - `manual_blocked` : état bloqué indépendant du compteur, pour couper
    l'accès d'un numéro abusif sans toucher à son historique.

Stockage : R2 (bucket VIDAL dédié), PAS MongoDB — demande explicite de
l'utilisateur (voir r2_vidal_client.py). Le champ `vidal_riche` déjà
existant sur `directory_contacts` (voir vidal_riche.py, PR précédente)
reste un OVERRIDE admin : un contact `vidal_riche=true` contourne
entièrement cette passerelle essai/quota/abonnement (accès illimité, ex.
compte de test interne ou médecin VIP) — c'est la réconciliation entre les
deux mécanismes, les deux restent nécessaires.

Portée volontairement limitée aux commandes `!doc`/`!rech` (voir
vidal_riche.build_riche_command_reply) — PAS aux questions libres relayées
aux agents Liluvine PRO : ce canal est un assistant IA générique
multi-tenant utilisé par toute la plateforme SAWALI (quota IA séparé,
`ai_quotas.py`), pas seulement par VIDAL. Étendre cette passerelle aux
questions libres changerait le comportement de tous les autres tenants
Liluvine PRO — hors périmètre de ce lot, à cadrer séparément si voulu.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Path as FastApiPath
from pydantic import BaseModel, Field

import r2_vidal_client as r2

logger = logging.getLogger("sawali.vidal.liluvine_subscription")

_CONFIG_KEY = "liluvine/config.json"
_NUMBER_PREFIX = "liluvine/numbers/"

DEFAULT_CONFIG: Dict[str, Any] = {
    "free_requests_threshold": 3,
    "trial_days": 3,
    # Montants de démonstration (FCFA) — à fixer réellement par l'utilisateur
    # via `PUT /admin/vidal/liluvine/config`.
    "formulas": {
        "jour": {"duration_days": 1, "price_fcfa": 500},
        "semaine": {"duration_days": 7, "price_fcfa": 2500},
        "mois": {"duration_days": 30, "price_fcfa": 8000},
        "trimestriel": {"duration_days": 90, "price_fcfa": 20000},
        "annuel": {"duration_days": 365, "price_fcfa": 70000},
    },
}

_CONFIG_CACHE_TTL_SECONDS = 30
_config_cache: Dict[str, Any] = {"value": None, "at": 0.0}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _number_key(phone_digits: str) -> str:
    safe = re.sub(r"[^0-9]", "", phone_digits or "")
    return f"{_NUMBER_PREFIX}{safe}.json"


def _empty_number(phone_digits: str) -> Dict[str, Any]:
    return {
        "phone": phone_digits,
        "authorized": False,
        "manual_blocked": False,
        "request_count": 0,
        "free_requests_used": 0,
        "first_request_at": None,
        "last_request_at": None,
        "trial_expires_at": None,
        "subscription": None,
    }


# ---------------------------------------------------------------------------
# Config (R2, cache mémoire court pour éviter un aller-retour R2 par message WA)
# ---------------------------------------------------------------------------
async def get_config(force_refresh: bool = False) -> Dict[str, Any]:
    if not force_refresh and _config_cache["value"] is not None:
        if time.monotonic() - _config_cache["at"] < _CONFIG_CACHE_TTL_SECONDS:
            return _config_cache["value"]
    try:
        raw = await asyncio.to_thread(r2.get_json, _CONFIG_KEY, None)
    except Exception:  # noqa: BLE001
        logger.exception("[liluvine_subscription] get_config failed — fallback defaults")
        raw = None
    config = raw if raw else dict(DEFAULT_CONFIG)
    _config_cache["value"] = config
    _config_cache["at"] = time.monotonic()
    return config


async def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    current = await get_config(force_refresh=True)
    merged = {**current, **{k: v for k, v in patch.items() if v is not None}}
    if "formulas" in patch and patch["formulas"] is not None:
        merged["formulas"] = patch["formulas"]
    await asyncio.to_thread(r2.put_json, _CONFIG_KEY, merged)
    _config_cache["value"] = merged
    _config_cache["at"] = time.monotonic()
    return merged


# ---------------------------------------------------------------------------
# Numéros (R2)
# ---------------------------------------------------------------------------
async def get_number(phone_digits: str) -> Dict[str, Any]:
    try:
        raw = await asyncio.to_thread(r2.get_json, _number_key(phone_digits), None)
    except Exception:  # noqa: BLE001
        logger.exception("[liluvine_subscription] get_number failed for %s", phone_digits)
        raw = None
    return raw if raw else _empty_number(phone_digits)


async def save_number(phone_digits: str, record: Dict[str, Any]) -> None:
    await asyncio.to_thread(r2.put_json, _number_key(phone_digits), record)


async def list_numbers(limit: int = 200) -> List[Dict[str, Any]]:
    try:
        keys = await asyncio.to_thread(r2.list_keys, _NUMBER_PREFIX)
    except Exception:  # noqa: BLE001
        logger.exception("[liluvine_subscription] list_numbers failed")
        return []
    keys = keys[:limit]
    records: List[Dict[str, Any]] = []
    for key in keys:
        try:
            doc = await asyncio.to_thread(r2.get_json, key, None)
        except Exception:  # noqa: BLE001
            continue
        if doc:
            records.append(doc)
    return records


def _formula_expiry(config: Dict[str, Any], formula: str, started_at: datetime) -> Optional[datetime]:
    f = (config.get("formulas") or {}).get(formula)
    if not f:
        return None
    return started_at + timedelta(days=int(f.get("duration_days") or 0))


# ---------------------------------------------------------------------------
# Passerelle d'accès — appelée par vidal_riche.build_riche_command_reply
# ---------------------------------------------------------------------------
async def check_access(
    *,
    phone_digits: str,
    contact: Optional[Dict[str, Any]],
    notify_admin_fn: Callable[..., Awaitable[Any]],
    send_wa_fn: Callable[[str, str], Awaitable[dict]],
) -> Dict[str, Any]:
    """Retourne {"allowed": bool, "reply_override": Optional[str]}.

    `reply_override` n'est renseigné QUE quand `allowed=False` (ou pour le
    message d'invitation à un numéro non autorisé) — l'appelant doit
    envoyer ce texte tel quel au lieu du contenu normalement généré par
    `!doc`/`!rech`.
    """
    # Iter — Override admin : contact taggé `vidal_riche=true` (champ dédié
    # sur directory_contacts, PR précédente) → accès illimité, cette
    # passerelle essai/quota/abonnement ne s'applique pas du tout.
    if bool((contact or {}).get("vidal_riche")):
        return {"allowed": True, "reply_override": None}

    config = await get_config()
    number = await get_number(phone_digits)
    now = _now()

    if number.get("manual_blocked"):
        return {
            "allowed": False,
            "reply_override": "🔒 Votre accès à Liluvine VIDAL a été suspendu. Contactez l'administrateur pour plus d'informations.",
        }

    if not number.get("authorized"):
        try:
            await notify_admin_fn(
                contact_name=(contact or {}).get("name") if contact else None,
                contact_phone_digits=phone_digits,
                last_user_message="(demande d'accès Liluvine VIDAL)",
                reason="Nouveau numéro Liluvine VIDAL non autorisé — !doc/!rech",
                send_wa=send_wa_fn,
            )
        except Exception:  # noqa: BLE001
            logger.exception("[liluvine_subscription] notify_admin failed for %s", phone_digits)
        return {
            "allowed": False,
            "reply_override": (
                "👋 Bienvenue sur Liluvine VIDAL !\n\n"
                "Votre numéro n'est pas encore autorisé à utiliser ce service. "
                "Votre demande a été transmise à notre équipe — vous recevrez un "
                f"essai gratuit de {config.get('trial_days', 3)} jour(s) dès validation."
            ),
        }

    trial_expires_at = _parse_dt(number.get("trial_expires_at"))
    trial_active = bool(trial_expires_at and now < trial_expires_at)

    sub = number.get("subscription") or None
    sub_expires_at = _parse_dt((sub or {}).get("expires_at"))
    sub_active = bool(sub and sub_expires_at and now < sub_expires_at)

    free_used = int(number.get("free_requests_used") or 0)
    threshold = int(config.get("free_requests_threshold") or 0)

    allowed = False
    reply_override: Optional[str] = None

    if trial_active or sub_active:
        allowed = True
    elif free_used < threshold:
        allowed = True
        number["free_requests_used"] = free_used + 1
    else:
        formulas = config.get("formulas") or {}
        lines = [
            "🔒 Vous avez atteint votre quota de requêtes gratuites Liluvine VIDAL.",
            "", "Souscrivez une formule pour continuer :",
        ]
        for name, f in formulas.items():
            lines.append(f"• {name.capitalize()} — {f.get('price_fcfa')} FCFA / {f.get('duration_days')} jour(s)")
        lines.append("\nContactez l'administrateur pour activer une formule.")
        reply_override = "\n".join(lines)

    # Comptage temps réel — sur toute tentative d'interaction (autorisée ou
    # non par quota, mais numéro authorized=true à ce stade).
    number["request_count"] = int(number.get("request_count") or 0) + 1
    if not number.get("first_request_at"):
        number["first_request_at"] = now.isoformat()
    number["last_request_at"] = now.isoformat()
    try:
        await save_number(phone_digits, number)
    except Exception:  # noqa: BLE001
        logger.exception("[liluvine_subscription] save_number failed for %s", phone_digits)

    return {"allowed": allowed, "reply_override": reply_override}


# ---------------------------------------------------------------------------
# Pydantic — admin
# ---------------------------------------------------------------------------
class FormulaPayload(BaseModel):
    duration_days: int = Field(..., ge=1, le=3650)
    price_fcfa: float = Field(..., ge=0)


class LiluvineConfigPayload(BaseModel):
    free_requests_threshold: Optional[int] = Field(None, ge=0)
    trial_days: Optional[int] = Field(None, ge=0)
    formulas: Optional[Dict[str, FormulaPayload]] = None


class SubscriptionPayload(BaseModel):
    formula: str
    started_at: Optional[str] = None
    price_fcfa: Optional[float] = None


def attach_liluvine_vidal_subscription_routes(*, api, get_current_admin):
    """Monte `/api/admin/vidal/liluvine/*` — config des formules + gestion
    des numéros (autoriser, bloquer, souscription manuelle)."""

    @api.get("/admin/vidal/liluvine/config", tags=["Admin — VIDAL"])
    async def get_liluvine_config(_: dict = Depends(get_current_admin)):
        return await get_config(force_refresh=True)

    @api.put("/admin/vidal/liluvine/config", tags=["Admin — VIDAL"])
    async def set_liluvine_config(payload: LiluvineConfigPayload = Body(...), _: dict = Depends(get_current_admin)):
        patch: Dict[str, Any] = {}
        if payload.free_requests_threshold is not None:
            patch["free_requests_threshold"] = payload.free_requests_threshold
        if payload.trial_days is not None:
            patch["trial_days"] = payload.trial_days
        if payload.formulas is not None:
            patch["formulas"] = {k: v.model_dump() for k, v in payload.formulas.items()}
        if not patch:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        return await save_config(patch)

    @api.get("/admin/vidal/liluvine/numbers", tags=["Admin — VIDAL"])
    async def list_liluvine_numbers(_: dict = Depends(get_current_admin)):
        return {"numbers": await list_numbers()}

    @api.post("/admin/vidal/liluvine/numbers/{phone}/authorize", tags=["Admin — VIDAL"])
    async def authorize_number(phone: str = FastApiPath(...), _: dict = Depends(get_current_admin)):
        config = await get_config()
        number = await get_number(phone)
        now = _now()
        number["authorized"] = True
        number["trial_expires_at"] = (now + timedelta(days=int(config.get("trial_days") or 3))).isoformat()
        await save_number(phone, number)
        return number

    @api.post("/admin/vidal/liluvine/numbers/{phone}/block", tags=["Admin — VIDAL"])
    async def block_number(phone: str = FastApiPath(...), _: dict = Depends(get_current_admin)):
        number = await get_number(phone)
        number["manual_blocked"] = True
        await save_number(phone, number)
        return number

    @api.post("/admin/vidal/liluvine/numbers/{phone}/unblock", tags=["Admin — VIDAL"])
    async def unblock_number(phone: str = FastApiPath(...), _: dict = Depends(get_current_admin)):
        number = await get_number(phone)
        number["manual_blocked"] = False
        await save_number(phone, number)
        return number

    @api.put("/admin/vidal/liluvine/numbers/{phone}/subscription", tags=["Admin — VIDAL"])
    async def set_subscription(
        phone: str = FastApiPath(...),
        payload: SubscriptionPayload = Body(...),
        _: dict = Depends(get_current_admin),
    ):
        config = await get_config()
        if payload.formula not in (config.get("formulas") or {}):
            raise HTTPException(status_code=400, detail=f"Formule inconnue : {payload.formula}")
        number = await get_number(phone)
        started_at = _parse_dt(payload.started_at) or _now()
        expires_at = _formula_expiry(config, payload.formula, started_at)
        price = payload.price_fcfa
        if price is None:
            price = (config.get("formulas") or {}).get(payload.formula, {}).get("price_fcfa")
        number["subscription"] = {
            "formula": payload.formula,
            "started_at": started_at.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "price_fcfa": price,
        }
        await save_number(phone, number)
        return number

    logger.info("[liluvine_vidal_subscription] routes mounted under /api/admin/vidal/liluvine/*")
