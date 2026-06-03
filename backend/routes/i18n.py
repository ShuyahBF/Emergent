"""S046 — i18n translations management (2026-02).

Storage : single `i18n_translations` collection. Each document is one
translation key with all language variants :

    {
        "key": "nav.dashboard",
        "fr": "Tableau de bord",            # source of truth
        "en": "Dashboard",
        "ar": "لوحة القيادة",
        "lg1": "",                          # Gulmancema (filled by humans)
        "lg2": "",                          # Mooré
        "context": "Sidebar navigation",    # admin-only hint
        "updated_at": "...",
        "updated_by_id": "...",
        "updated_by_email": "...",
    }

Endpoints :

    GET   /api/i18n/languages                   — public list of supported langs
    GET   /api/i18n/translations?lang=fr        — public dictionary {key: text}
    GET   /api/admin/i18n/translations          — admin full table
    POST  /api/admin/i18n/translations          — admin upsert one row
    DELETE /api/admin/i18n/translations/{key}    — admin delete
    POST  /api/admin/i18n/translations/bulk     — admin upsert many

The Frontend i18n provider fetches `/api/i18n/translations?lang=…` once on
mount + on language change, then exposes a `t(key)` helper. Fallback to FR
when a key has no entry for the chosen lang.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.i18n")


# Supported languages — fixed list (FR is the source of truth).
SUPPORTED_LANGS = [
    {"code": "fr", "label": "Français", "native": "Français", "rtl": False, "primary": True},
    {"code": "en", "label": "Anglais", "native": "English", "rtl": False},
    {"code": "ar", "label": "Arabe", "native": "العربية", "rtl": True},
    {"code": "lg1", "label": "Gulmancema", "native": "Gulmancema", "rtl": False},
    {"code": "lg2", "label": "Mooré", "native": "Mooré", "rtl": False},
]
LANG_CODES = {lang["code"] for lang in SUPPORTED_LANGS}


# Seed strings — the most-visible UI labels that need translation by default.
SEED_KEYS: List[Dict[str, str]] = [
    # --- Navigation (PortalLayout sidebar) ---
    {"key": "nav.dashboard", "fr": "Tableau de bord", "en": "Dashboard", "context": "Sidebar"},
    {"key": "nav.appointments", "fr": "Mes rendez-vous", "en": "My appointments", "context": "Sidebar"},
    {"key": "nav.documentation", "fr": "Documentation", "en": "Documentation", "context": "Sidebar"},
    {"key": "nav.interventions", "fr": "Historique interventions", "en": "Intervention history", "context": "Sidebar"},
    {"key": "nav.users_tracking", "fr": "Suivi utilisateurs", "en": "Users tracking", "context": "Sidebar"},
    {"key": "nav.reports", "fr": "Mes rapports", "en": "My reports", "context": "Sidebar"},
    {"key": "nav.followups", "fr": "Mes suivis", "en": "My follow-ups", "context": "Sidebar"},
    {"key": "nav.forms", "fr": "Formulaires", "en": "Forms", "context": "Sidebar"},
    {"key": "nav.contacts", "fr": "Centre de Messagerie", "en": "Messaging Center", "context": "Sidebar"},
    {"key": "nav.tickets", "fr": "Tickets", "en": "Tickets", "context": "Sidebar"},
    {"key": "nav.liluvine", "fr": "Liluvine PRO (Assistant IA)", "en": "Liluvine PRO (AI Assistant)", "context": "Sidebar"},
    # --- Common buttons ---
    {"key": "common.save", "fr": "Enregistrer", "en": "Save"},
    {"key": "common.cancel", "fr": "Annuler", "en": "Cancel"},
    {"key": "common.delete", "fr": "Supprimer", "en": "Delete"},
    {"key": "common.edit", "fr": "Modifier", "en": "Edit"},
    {"key": "common.create", "fr": "Créer", "en": "Create"},
    {"key": "common.search", "fr": "Rechercher", "en": "Search"},
    {"key": "common.refresh", "fr": "Actualiser", "en": "Refresh"},
    {"key": "common.confirm", "fr": "Confirmer", "en": "Confirm"},
    {"key": "common.close", "fr": "Fermer", "en": "Close"},
    {"key": "common.loading", "fr": "Chargement…", "en": "Loading…"},
    {"key": "common.yes", "fr": "Oui", "en": "Yes"},
    {"key": "common.no", "fr": "Non", "en": "No"},
    # --- Login page ---
    {"key": "login.title", "fr": "Espace Loois", "en": "Loois Space"},
    {"key": "login.subtitle", "fr": "Saisissez vos identifiants. Un code à usage unique vous sera envoyé.", "en": "Enter your credentials. A one-time code will be sent to you."},
    {"key": "login.email", "fr": "Email", "en": "Email"},
    {"key": "login.password", "fr": "Mot de passe", "en": "Password"},
    {"key": "login.submit", "fr": "Se connecter", "en": "Sign in"},
    {"key": "login.via_whatsapp", "fr": "Se connecter via WhatsApp", "en": "Sign in via WhatsApp"},
    {"key": "login.no_account", "fr": "Pas encore de compte ?", "en": "No account yet?"},
    {"key": "login.request_access", "fr": "Demander un accès", "en": "Request access"},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TranslationUpsert(BaseModel):
    key: str = Field(..., min_length=1, max_length=160, pattern=r"^[a-zA-Z][a-zA-Z0-9._-]*$")
    fr: str = Field(..., max_length=4000)
    en: Optional[str] = Field("", max_length=4000)
    ar: Optional[str] = Field("", max_length=4000)
    lg1: Optional[str] = Field("", max_length=4000)
    lg2: Optional[str] = Field("", max_length=4000)
    context: Optional[str] = Field("", max_length=400)


class TranslationBulkUpsert(BaseModel):
    rows: List[TranslationUpsert]


def attach_i18n_routes(api: APIRouter, *, db: Any, get_current_user: Any) -> None:
    """Mount the i18n routes on the provided FastAPI router."""

    async def _ensure_seed():
        """Insert SEED_KEYS rows if the collection is empty."""
        try:
            count = await db.i18n_translations.estimated_document_count()
        except Exception:
            count = 0
        if count > 0:
            return
        docs = []
        for s in SEED_KEYS:
            doc = {
                "key": s["key"],
                "fr": s.get("fr", ""),
                "en": s.get("en", ""),
                "ar": s.get("ar", ""),
                "lg1": s.get("lg1", ""),
                "lg2": s.get("lg2", ""),
                "context": s.get("context", ""),
                "updated_at": _now(),
                "updated_by_email": "_system_",
            }
            docs.append(doc)
        if docs:
            try:
                await db.i18n_translations.insert_many(docs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[i18n] seed failed: %s", exc)

    # --------- Public ---------
    @api.get("/i18n/languages", tags=["i18n"])
    async def i18n_languages():
        return {"items": SUPPORTED_LANGS, "default": "fr"}

    @api.get("/i18n/translations", tags=["i18n"])
    async def i18n_public_dictionary(lang: str = "fr"):
        """Return {key: text} for the requested language. Falls back to FR
        when the row has an empty value for that language."""
        if lang not in LANG_CODES:
            raise HTTPException(status_code=400, detail=f"Langue non supportée : {lang}")
        await _ensure_seed()
        out: Dict[str, str] = {}
        async for row in db.i18n_translations.find({}, {"_id": 0, "key": 1, "fr": 1, lang: 1}):
            value = (row.get(lang) or "").strip()
            if not value:
                value = row.get("fr") or row.get("key") or ""
            out[row["key"]] = value
        return {"lang": lang, "translations": out, "count": len(out)}

    # --------- Admin ---------
    def _is_admin_or_sup(user: dict) -> bool:
        return (user.get("role") or "") in ("admin", "superviseur")

    @api.get("/admin/i18n/translations", tags=["Admin — i18n"])
    async def admin_list_translations(user: dict = Depends(get_current_user)):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        await _ensure_seed()
        rows: List[Dict[str, Any]] = []
        async for r in db.i18n_translations.find({}, {"_id": 0}).sort("key", 1):
            rows.append(r)
        return {"items": rows, "count": len(rows), "languages": SUPPORTED_LANGS}

    @api.post("/admin/i18n/translations", tags=["Admin — i18n"])
    async def admin_upsert_translation(
        payload: TranslationUpsert, user: dict = Depends(get_current_user)
    ):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        update = {
            "key": payload.key,
            "fr": payload.fr,
            "en": payload.en or "",
            "ar": payload.ar or "",
            "lg1": payload.lg1 or "",
            "lg2": payload.lg2 or "",
            "context": payload.context or "",
            "updated_at": _now(),
            "updated_by_id": user.get("id"),
            "updated_by_email": user.get("email"),
        }
        await db.i18n_translations.update_one(
            {"key": payload.key}, {"$set": update}, upsert=True,
        )
        update.pop("_id", None)
        return {"ok": True, "row": update}

    @api.delete("/admin/i18n/translations/{key}", tags=["Admin — i18n"])
    async def admin_delete_translation(
        key: str, user: dict = Depends(get_current_user)
    ):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9._-]*$", key):
            raise HTTPException(status_code=400, detail="Clé invalide")
        res = await db.i18n_translations.delete_one({"key": key})
        return {"ok": True, "deleted": res.deleted_count}

    @api.post("/admin/i18n/translations/bulk", tags=["Admin — i18n"])
    async def admin_bulk_upsert(
        payload: TranslationBulkUpsert, user: dict = Depends(get_current_user)
    ):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        n = 0
        for row in payload.rows:
            update = {
                "key": row.key,
                "fr": row.fr,
                "en": row.en or "",
                "ar": row.ar or "",
                "lg1": row.lg1 or "",
                "lg2": row.lg2 or "",
                "context": row.context or "",
                "updated_at": _now(),
                "updated_by_id": user.get("id"),
                "updated_by_email": user.get("email"),
            }
            await db.i18n_translations.update_one(
                {"key": row.key}, {"$set": update}, upsert=True,
            )
            n += 1
        return {"ok": True, "upserted": n}
