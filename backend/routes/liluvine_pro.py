"""Iter38r-fix6 — Liluvine PRO / Assistant SAWALI.

Assistant interne propulsé par Claude Sonnet 4.6 (Emergent LLM Key) avec :
  - Sessions de conversation multi-tour persistées dans MongoDB
  - Injection automatique de contexte (RAG simple) : quand l'utilisateur évoque
    contacts/tickets/paiements/RDV, on récupère les 10 dernières lignes pertinentes
    de la DB et on les ajoute au system message
  - Tracking automatique de la consommation via `routes.ai_quotas.track_ai_usage`
    (resource="chat", units=tokens estimés)
  - Multi-tenant strict : un utilisateur ne voit que les sessions sous son
    client_id (admin parent).

Endpoints :
  POST   /api/me/liluvine-pro/chat
  GET    /api/me/liluvine-pro/sessions
  GET    /api/me/liluvine-pro/sessions/{sid}
  PATCH  /api/me/liluvine-pro/sessions/{sid}    (rename)
  DELETE /api/me/liluvine-pro/sessions/{sid}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.liluvine_pro")

# Iter38r-fix9t — Claude Haiku 4.5 (Anthropic) for the chat workload.
# ~3× faster than Sonnet 4.6 with comparable quality on short Q&A.
LILUVINE_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_MESSAGE = """Tu es Liluvine PRO, l'assistant IA interne de SAWALI SMART SYSTEMS.
Tu réponds toujours en **français** de façon concise (3-6 phrases max sauf si on te demande un détail).
Tu as accès en lecture seule aux données métier de l'utilisateur (contacts, tickets, paiements, RDV, notes).
Quand on te pose une question portant sur ces données, le contexte récent est injecté ci-dessous (CONTEXTE DB).
- Si le contexte n'est pas suffisant, demande poliment plus de précision.
- N'invente jamais de données — ne mentionne que ce qui apparaît dans le contexte.
- Tu peux aider à rédiger des SMS, des messages WhatsApp, des emails, des notes, des résumés.
- Tu peux expliquer les fonctionnalités du CRM (Caisse, Facturation, GRH, Tickets, etc.).

[S041 — Illustration par images]
Si le bloc « [IMAGES DISPONIBLES POUR ILLUSTRER TA RÉPONSE] » apparaît dans le contexte
ci-dessous, c'est qu'une ou plusieurs images de la base de connaissance correspondent à
la question. Inclus celles qui sont VRAIMENT pertinentes EXACTEMENT au format Markdown :
  ![titre court](url)
L'interface chat les affichera automatiquement sous forme de carrousel numéroté
(n°1, n°2, n°3…). Le visiteur pourra ainsi te dire « C'est l'image n°2 » pour préciser
de quoi il parle. Ne fabrique jamais d'URL : utilise UNIQUEMENT celles fournies dans le
contexte. N'inclus pas d'image si aucune ne convient vraiment à la question."""


# ============================================================
# Pydantic
# ============================================================
class ChatMessage(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[str] = None


class RenameSession(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)


# Iter38r-fix9e — Branding payload (must be at module level for FastAPI)
class BrandingPayload(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    avatar_url: Optional[str] = Field(None, max_length=2000)
    color: Optional[str] = Field(None, pattern="^(fuchsia|violet|indigo|sky|emerald|amber|rose)$")
    tagline: Optional[str] = Field(None, max_length=160)


# Iter38r-fix9a — Auto-reply WhatsApp configuration payload
class AutoreplyConfigPayload(BaseModel):
    enabled: Optional[bool] = None
    allow_phones: Optional[List[str]] = None
    deny_phones: Optional[List[str]] = None
    allow_mode: Optional[str] = Field(None, pattern="^(any|whitelist)$")
    schedule: Optional[str] = Field(None, pattern="^(always|outside_hours|business_hours)$")
    keywords: Optional[List[str]] = None
    cooldown_seconds: Optional[int] = Field(None, ge=0, le=3600)
    signature: Optional[str] = Field(None, max_length=200)
    # Iter43-fix24h — Fallback `…` pour les `!commandes` inconnues
    unknown_cmd_reply: Optional[str] = Field(None, max_length=500)
    unknown_cmd_fallback_enabled: Optional[bool] = None
    # Iter43-fix24j — Profil "marque/HQ" pour les commandes !adresse / !horaires / !contact
    brand_name: Optional[str] = Field(None, max_length=200)
    brand_phone: Optional[str] = Field(None, max_length=40)
    brand_whatsapp: Optional[str] = Field(None, max_length=40)
    brand_email: Optional[str] = Field(None, max_length=200)
    brand_address: Optional[str] = Field(None, max_length=300)
    brand_city: Optional[str] = Field(None, max_length=100)
    brand_country: Optional[str] = Field(None, max_length=100)
    brand_location_hint: Optional[str] = Field(None, max_length=300)
    brand_latitude: Optional[float] = Field(None, ge=-90, le=90)
    brand_longitude: Optional[float] = Field(None, ge=-180, le=180)
    brand_hours: Optional[str] = Field(None, max_length=2000)
    brand_maps_url: Optional[str] = Field(None, max_length=500)


# Bypass list (2026-02) — Admin payload to overwrite the email allowlist.
class BypassPayload(BaseModel):
    emails: List[str] = Field(default_factory=list)


# Cross-tenant import payload (2026-02).
class CrossTenantImportPayload(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32)
    include_messages: bool = False


# ============================================================
# Helpers
# ============================================================
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_scope(user: dict) -> str:
    """Tenant scope = parent admin id for tracked users, self for admins.

    Bugfix (2026-02) — `moderateur` users (Sawali support staff working
    inside an admin/superviseur tenant) had no scope resolved : their
    `tracked_user_id` is empty and they don't own a tenant. Falling back
    to `parent_client_id` correctly anchors them to the admin tenant
    that created them, so feature checks (ai_liluvine_pro, etc.) resolve
    to that tenant — not to their own personal account.
    """
    if user.get("role") in ("admin", "superviseur"):
        return user["id"]
    return (
        user.get("tracked_user_id")
        or user.get("client_id")
        or user.get("parent_client_id")
        or user["id"]
    )


# ============================================================
# Bypass list (2026-02) — Per-user override for `ai_liluvine_pro`.
#
# Admin sets `settings.liluvine_pro_bypass_emails` (space/comma-separated
# string OR list) to grant individual users Liluvine PRO access even when
# the parent tenant feature flag is OFF. Typical case: a moderator like
# `rabo.f@sawalismartsystems.com` whose tenant hasn't been migrated yet,
# but who needs immediate access to the assistant for support work.
# ============================================================
def _parse_bypass_emails(raw: Any) -> set:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        items = re.split(r"[\s,;]+", raw)
    else:
        items = []
    return {str(x).strip().lower() for x in items if str(x).strip()}


async def _liluvine_pro_allowed(db, user: dict) -> Dict[str, Any]:
    """Return {"allowed": bool, "reason": str, "via_bypass": bool}.

    Resolution order :
      1. If the parent tenant has `features.ai_liluvine_pro = True` → allow.
      2. If the user's email matches `settings.liluvine_pro_bypass_emails` → allow.
      3. Otherwise → deny (with a friendly French reason).
    """
    scope_uid = _client_scope(user)
    parent = await db.users.find_one({"id": scope_uid}, {"_id": 0, "features": 1, "email": 1})
    feats = (parent or {}).get("features") or {}
    if feats.get("ai_liluvine_pro"):
        return {"allowed": True, "reason": "tenant_feature_on", "via_bypass": False}
    settings_doc = await db.settings.find_one({"_id": "global"}) or {}
    bypass = _parse_bypass_emails(settings_doc.get("liluvine_pro_bypass_emails"))
    email = (user.get("email") or "").lower().strip()
    if email and email in bypass:
        return {"allowed": True, "reason": "user_in_bypass_list", "via_bypass": True}
    return {
        "allowed": False,
        "reason": "Liluvine PRO n'est pas activé pour votre compte. Contactez votre administrateur.",
        "via_bypass": False,
    }


async def _diagnose_wa_inbound(db, phone: str) -> Dict[str, Any]:
    """Bugfix helper (2026-02) — explain what would happen when WhatsApp
    receives an inbound message from this phone number. Used by the
    admin /diagnose endpoint to give a clear root-cause hint."""
    out: Dict[str, Any] = {"phone": phone}
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    out["phone_digits"] = digits
    # 1) Which tenant scope would the webhook resolve?
    primary = await db.users.find_one({"role": "superviseur"}, {"_id": 0, "id": 1, "email": 1})
    if not primary:
        primary = await db.users.find_one(
            {"role": "admin", "email": {"$ne": "admin@sawalismartsystems.com"}},
            {"_id": 0, "id": 1, "email": 1},
        )
    if not primary:
        primary = await db.users.find_one(
            {"email": "admin@sawalismartsystems.com"}, {"_id": 0, "id": 1, "email": 1},
        )
    out["resolved_webhook_tenant"] = primary or None
    # 2) Settings for the auto-reply
    s = await db.settings.find_one({"_id": "global"}) or {}
    out["autoreply_enabled"] = bool(s.get("liluvine_wa_autoreply_enabled"))
    out["allow_mode"] = s.get("liluvine_wa_autoreply_allow_mode") or "any"
    keywords = (s.get("liluvine_wa_autoreply_keywords") or "").strip()
    out["keywords_filter"] = keywords or "(aucun — accepte tout)"
    out["cooldown_seconds"] = s.get("liluvine_wa_autoreply_cooldown_seconds") or 60
    deny_raw = s.get("liluvine_wa_autoreply_deny_phones") or ""
    allow_raw = s.get("liluvine_wa_autoreply_allow_phones") or ""
    # Robust: accept either a comma-separated string OR a list of strings.
    deny_list = deny_raw if isinstance(deny_raw, list) else [p.strip() for p in str(deny_raw).split(",") if p.strip()]
    allow_list = allow_raw if isinstance(allow_raw, list) else [p.strip() for p in str(allow_raw).split(",") if p.strip()]
    deny_digits = {"".join(ch for ch in p if ch.isdigit()) for p in deny_list}
    allow_digits = {"".join(ch for ch in p if ch.isdigit()) for p in allow_list}
    out["denylisted"] = digits in deny_digits if digits else False
    out["whitelist_required"] = out["allow_mode"] == "whitelist"
    out["in_whitelist"] = digits in allow_digits if digits else False
    # 3) Human takeover ?
    if primary:
        sid = f"wa:{primary['id']}:{digits}"
        sess = await db.liluvine_pro_sessions.find_one(
            {"id": sid}, {"_id": 0, "human_takeover": 1, "human_takeover_until": 1},
        )
        out["human_takeover_active"] = bool(sess and sess.get("human_takeover"))
    # 4) Tenant feature
    if primary:
        tenant = await db.users.find_one({"id": primary["id"]}, {"_id": 0, "features": 1, "email": 1}) or {}
        feats = tenant.get("features") or {}
        out["tenant_ai_liluvine_pro"] = bool(feats.get("ai_liluvine_pro"))
        out["tenant_email"] = tenant.get("email")
    # 5) Anti-flood state for this phone
    state = await db.liluvine_wa_autoreply_state.find_one(
        {"phone_digits": digits}, {"_id": 0, "last_replied_at": 1},
    )
    out["last_replied_at"] = (state or {}).get("last_replied_at")
    # 6) Conclusion
    reasons = []
    if not out["autoreply_enabled"]:
        reasons.append("L'auto-réponse WhatsApp Liluvine est DÉSACTIVÉE dans les Réglages.")
    if out["denylisted"]:
        reasons.append(f"Le numéro {digits} est dans la liste DENY.")
    if out["whitelist_required"] and not out["in_whitelist"]:
        reasons.append(f"Mode whitelist actif et {digits} n'y est pas.")
    if out.get("human_takeover_active"):
        reasons.append("Un humain a repris la conversation (human_takeover actif).")
    if out.get("tenant_ai_liluvine_pro") is False:
        reasons.append(
            f"La feature 'ai_liluvine_pro' n'est PAS activée sur le tenant {out.get('tenant_email')}."
        )
    if not primary:
        reasons.append("Aucun tenant primaire (admin/superviseur) trouvé pour router le message.")
    out["blocking_reasons"] = reasons or ["Aucun blocage évident — vérifiez les keywords + cooldown."]
    return out


async def _diagnose_contact_visibility(db, *, phone: str, user: Optional[dict] = None) -> Dict[str, Any]:
    """Bugfix (2026-02 — bug #3 rabo.f) — explain why a phone number's contact
    name may be missing in /portal/contacts. Scans `directory_contacts`,
    `wa_pending_imports` and recent `whatsapp_messages` for the given phone.

    If `user` is provided, also resolves the user's `visible_client_ids` so we
    can flag contacts that live outside the user's viewing scope (a frequent
    cross-tenant cause of missing contacts).
    """
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    out: Dict[str, Any] = {"phone": phone, "phone_digits": digits}
    if not digits:
        out["error"] = "Numéro vide ou invalide."
        return out

    # 1) ALL directory_contacts rows matching this phone (across tenants)
    contacts: List[Dict[str, Any]] = []
    async for c in db.directory_contacts.find(
        {"$or": [{"whatsapp": {"$regex": digits}}, {"phone": {"$regex": digits}}]},
        {"_id": 0, "id": 1, "client_id": 1, "owner_id": 1, "name": 1,
         "wa_profile_name": 1, "phone": 1, "whatsapp": 1, "email": 1,
         "company": 1, "created_at": 1, "updated_at": 1},
    ):
        contacts.append(c)
    out["directory_contacts_count"] = len(contacts)
    out["directory_contacts"] = contacts

    # 2) wa_pending_imports matches
    pending: List[Dict[str, Any]] = []
    async for p in db.wa_pending_imports.find(
        {"phone_digits": digits},
        {"_id": 0, "id": 1, "client_id": 1, "phone_digits": 1, "from": 1,
         "wa_profile_name": 1, "last_message": 1, "last_seen_at": 1},
    ):
        pending.append(p)
    out["wa_pending_imports_count"] = len(pending)
    out["wa_pending_imports"] = pending

    # 3) Last 5 inbound whatsapp_messages from this phone
    recent_msgs = await db.whatsapp_messages.find(
        {"phone_digits": digits, "direction": "inbound"},
        {"_id": 0, "id": 1, "client_id": 1, "contact_id": 1, "contact_name": 1,
         "from": 1, "from_profile_name": 1, "received_at": 1, "body": 1},
    ).sort("received_at", -1).to_list(5)
    out["recent_inbound_messages"] = recent_msgs

    # 4) Resolve the user's viewing scope, if a user context is provided
    if user is not None:
        try:
            # Mirror the same `_resolve_visible_client_ids` logic from server.py
            ids: set = set()
            for k in ("client_id", "parent_client_id", "id"):
                v = user.get(k)
                if v:
                    ids.add(v)
            company = (user.get("company") or "").strip()
            if company:
                async for u in db.users.find(
                    {"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}},
                    {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1},
                ):
                    for k in ("id", "client_id", "parent_client_id"):
                        v = u.get(k)
                        if v:
                            ids.add(v)
            visible = list(ids)
            out["user_visible_client_ids"] = visible
            in_scope = [c for c in contacts if c.get("client_id") in visible]
            out_of_scope = [c for c in contacts if c.get("client_id") not in visible]
            out["contacts_in_user_scope"] = len(in_scope)
            out["contacts_out_of_scope"] = len(out_of_scope)
            out["contacts_in_user_scope_detail"] = in_scope
            out["contacts_out_of_scope_detail"] = out_of_scope
        except Exception as exc:  # noqa: BLE001
            out["scope_resolution_error"] = str(exc)[:200]

    # 5) Conclusion — flag the likely root cause
    diagnosis: List[str] = []
    if not contacts and not pending:
        diagnosis.append(
            "Aucun contact (directory_contacts) ni pending import pour ce numéro. "
            "Probable : aucun message inbound n'a été reçu de ce numéro, OU le contact "
            "n'a jamais été créé."
        )
    if pending and not contacts:
        diagnosis.append(
            "Numéro présent dans wa_pending_imports (non importé) mais SANS contact "
            "dans directory_contacts. Importer le pending via /me/wa-pending-imports."
        )
    if contacts:
        blank = [c for c in contacts if not (c.get("name") or "").strip()]
        if blank:
            diagnosis.append(
                f"{len(blank)} contact(s) ont un champ `name` vide. La liste de "
                "messagerie affichera une ligne sans nom."
            )
        phone_like = [
            c for c in contacts
            if (c.get("name") or "").strip() and
               re.fullmatch(r"\+?\d[\d\s().-]*", c.get("name").strip())
        ]
        if phone_like:
            diagnosis.append(
                f"{len(phone_like)} contact(s) ont un `name` qui n'est qu'un numéro "
                "de téléphone (jamais renommé)."
            )
    if user is not None and out.get("contacts_out_of_scope", 0):
        diagnosis.append(
            f"{out['contacts_out_of_scope']} contact(s) existent mais hors scope "
            "visible de l'utilisateur — ils n'apparaîtront pas dans /portal/contacts. "
            "Exécutez POST /admin/contacts/repair-user-contact pour réparer."
        )
    if user is not None and out.get("contacts_in_user_scope", 0) > 1:
        diagnosis.append(
            f"{out['contacts_in_user_scope']} contacts DUPLIQUÉS dans le scope visible. "
            "Recommandé : exécuter le repair pour fusionner."
        )
    out["diagnosis"] = diagnosis or [
        "Aucune anomalie évidente — le contact devrait s'afficher correctement."
    ]
    return out


# Lightweight keyword → fetcher map. The point is to inject a small,
# truncated context relevant to the user's question. Each fetcher returns
# a short markdown-like snippet (max ~2 KB) — no PII overload.
async def _fetch_context_snippets(db, user: dict, text: str) -> str:
    """Inspect `text` for keywords and pull relevant data from MongoDB.
    Returns a single concatenated snippet or empty string.

    Iter38r-fix9t — Fetchers are launched in parallel via asyncio.gather().
    """
    scope = _client_scope(user)
    t = (text or "").lower()

    async def _list_contacts():
        items = await db.directory_contacts.find(
            {"client_id": scope}, {"_id": 0, "name": 1, "code": 1, "phone": 1, "whatsapp": 1, "email": 1, "company": 1},
        ).sort("created_at", -1).to_list(10)
        if not items:
            return "Aucun contact enregistré pour ce client."
        lines = [f"- {c.get('code', '?')} · {c.get('name', '?')} · {c.get('company', '')} · {c.get('phone') or c.get('whatsapp') or c.get('email') or '—'}"
                 for c in items]
        return "**10 derniers contacts** :\n" + "\n".join(lines)

    async def _list_tickets():
        items = await db.support_tickets.find(
            {"client_id": scope, "archived_at": {"$in": [None, ""]}},
            {"_id": 0, "number": 1, "motif": 1, "status": 1, "contact_name": 1, "opened_at": 1, "priority": 1},
        ).sort("opened_at", -1).to_list(10)
        if not items:
            return "Aucun ticket d'intervention actif."
        lines = [f"- {t.get('number', '?')} · {t.get('motif', '—')[:60]} · {t.get('contact_name', '—')} · statut={t.get('status', '?')} · priorité={t.get('priority', '—')}"
                 for t in items]
        return "**10 derniers tickets actifs** :\n" + "\n".join(lines)

    async def _list_payments():
        items = await db.payments.find(
            {"client_id": scope},
            {"_id": 0, "amount": 1, "currency": 1, "status": 1, "mno": 1, "msisdn": 1, "description": 1, "created_at": 1},
        ).sort("created_at", -1).to_list(10)
        if not items:
            return "Aucun paiement encore."
        lines = [f"- {(p.get('created_at') or '')[:10]} · {p.get('amount', 0)} {p.get('currency', 'XOF')} · {p.get('mno') or '—'} · {p.get('msisdn') or ''} · {p.get('status', '?')} · {(p.get('description') or '')[:40]}"
                 for p in items]
        return "**10 derniers paiements** :\n" + "\n".join(lines)

    async def _list_appointments():
        items = await db.appointments.find(
            {"$or": [{"client_id": scope}, {"created_by": scope}]},
            {"_id": 0, "title": 1, "date": 1, "time": 1, "contact_name": 1, "status": 1},
        ).sort("date", -1).to_list(10)
        if not items:
            return "Aucun rendez-vous enregistré."
        lines = [f"- {a.get('date', '?')} {a.get('time', '')} · {a.get('title') or a.get('contact_name') or '—'} · {a.get('status', '?')}"
                 for a in items]
        return "**10 derniers rendez-vous** :\n" + "\n".join(lines)

    async def _list_notes():
        items = await db.client_notes.find(
            {"client_id": scope, "deleted_at": {"$in": [None, ""]}},
            {"_id": 0, "kind": 1, "title": 1, "summary": 1, "content": 1, "created_at": 1},
        ).sort("created_at", -1).to_list(8)
        if not items:
            return "Aucune note ou rapport encore."
        lines = []
        for n in items:
            snippet = (n.get("summary") or n.get("content") or "")[:120]
            lines.append(f"- [{n.get('kind', '?')}] {(n.get('title') or '—')[:50]} · {snippet}…")
        return "**8 dernières notes/rapports** :\n" + "\n".join(lines)

    # Iter38r-fix9t — Fan out matching fetchers in parallel
    coros = []
    if re.search(r"\b(contact|client|annuaire)s?\b", t):
        coros.append(_list_contacts())
    if re.search(r"\b(ticket|intervention|incident|demande)s?\b", t):
        coros.append(_list_tickets())
    if re.search(r"\b(paiement|payment|encaissement|pawapay|mobile.{0,3}money|stripe)s?\b", t):
        coros.append(_list_payments())
    if re.search(r"\b(rdv|rendez.vous|appointment|réunion|reunion|meeting)s?\b", t):
        coros.append(_list_appointments())
    if re.search(r"\b(note|rapport|suivi|compte.rendu|résumé|resume)s?\b", t):
        coros.append(_list_notes())

    if not coros:
        return ""
    snippets = await asyncio.gather(*coros, return_exceptions=False)
    return "\n\n--- CONTEXTE DB ---\n" + "\n\n".join(s for s in snippets if s) + "\n--- FIN CONTEXTE ---"


# ============================================================
# Route setup
# ============================================================
def setup_liluvine_pro_routes(*, db, api, get_current_user, wa_send_text=None):
    """Mount Liluvine PRO endpoints on the provided api router."""

    api_key = os.environ.get("EMERGENT_LLM_KEY")

    async def _track(user, units, model, metadata=None):
        try:
            from routes.ai_quotas import track_ai_usage
        except ImportError:
            return {"allowed": True, "reason": None}
        return await track_ai_usage(
            db, user=user, resource="chat", units=units,
            model=model, metadata=metadata or {},
        )

    async def _pre_check(user, model):
        try:
            from routes.ai_quotas import track_ai_usage
        except ImportError:
            return {"allowed": True}
        # Estimate ~500 tokens per turn for the pre-check
        return await track_ai_usage(
            db, user=user, resource="chat", units=500,
            model=model, pre_check=True,
        )

    # Iter38r-fix9o (Item 1) — Tenant-configurable system prompt + escalation
    ESCALATION_TOKEN = "[ESCALATION_HUMAINE]"
    ESCALATION_KEYWORDS = (
        "agent humain", "humain", "parler à quelqu'un", "parler a quelqu'un",
        "vrai agent", "support humain", "un humain", "responsable",
    )

    async def _resolve_system_prompt(scope_uid: str) -> str:
        """Tenant-level override (`liluvine_pro_system_prompt`) takes priority,
        fallback to the global `SYSTEM_MESSAGE` constant. Always appends the
        escalation rule so Liluvine knows to emit the marker when it can't
        answer."""
        tenant_doc = await db.users.find_one(
            {"id": scope_uid},
            {"_id": 0, "liluvine_pro_system_prompt": 1, "full_name": 1, "company": 1},
        ) or {}
        base = (tenant_doc.get("liluvine_pro_system_prompt") or "").strip() or SYSTEM_MESSAGE
        escalation_rule = (
            "\n\n[RÈGLE D'ESCALADE — IMPORTANT]\n"
            "Si tu ne sais pas répondre, si la demande dépasse ton champ d'action, "
            "si le contact insiste pour avoir un humain, ou si la situation requiert "
            "un humain (litige, sensibilité, urgence), termine ta réponse par le "
            f"marqueur exact `{ESCALATION_TOKEN}` (sans guillemets) suivi d'un message "
            "rassurant et bref de transition vers l'humain (ex: « Je transmets votre "
            "demande à un conseiller, il revient vers vous très vite. »)."
        )
        return base + escalation_rule

    @api.put("/admin/liluvine-pro/system-prompt", tags=["Admin — Liluvine PRO"])
    async def admin_set_system_prompt(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Admin/superviseur seulement")
        prompt = (payload.get("system_prompt") or "").strip()
        scope_uid = _client_scope(user)
        await db.users.update_one({"id": scope_uid}, {"$set": {"liluvine_pro_system_prompt": prompt}})
        return {"ok": True, "length": len(prompt)}

    @api.get("/admin/liluvine-pro/system-prompt", tags=["Admin — Liluvine PRO"])
    async def admin_get_system_prompt(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Admin/superviseur seulement")
        scope_uid = _client_scope(user)
        u = await db.users.find_one({"id": scope_uid}, {"_id": 0, "liluvine_pro_system_prompt": 1}) or {}
        return {"system_prompt": u.get("liluvine_pro_system_prompt") or "", "default": SYSTEM_MESSAGE}

    async def _flag_escalation(session_id: str, scope_uid: str, source: str) -> None:
        """Mark the session and emit a realtime broadcast for the toast."""
        now = _now()
        await db.liluvine_pro_sessions.update_one(
            {"id": session_id},
            {"$set": {
                "human_assistance_requested": True,
                "human_assistance_requested_at": now,
                "human_assistance_source": source,
            }},
        )
        # Best-effort email to admins of this tenant (defaults to disabled)
        try:
            sess = await db.liluvine_pro_sessions.find_one({"id": session_id}, {"_id": 0, "user_label": 1, "title": 1})
            admins = db.users.find(
                {"role": {"$in": ["admin", "superviseur", "moderateur"]},
                 "$or": [{"id": scope_uid}, {"parent_client_id": scope_uid}, {"client_id": scope_uid}]},
                {"_id": 0, "email": 1},
            )
            from server import send_email  # type: ignore
            async for a in admins:
                if a.get("email"):
                    try:
                        await send_email(
                            to_email=a["email"],
                            subject="🆘 SAWALI — Liluvine PRO demande un humain",
                            html_body=(
                                f"<p>Liluvine PRO a déclenché une <strong>demande d'assistance humaine</strong> "
                                f"sur la conversation <code>{(sess or {}).get('user_label') or session_id}</code>.</p>"
                                f"<p>Source: <code>{source}</code></p>"
                            ),
                            text_body=f"Escalation Liluvine — session {session_id} ({source})",
                        )
                    except Exception:
                        pass
        except Exception:
            logger.warning("[liluvine] escalation email loop failed", exc_info=True)

    async def _build_memory_block(sid: str, current_text: str, limit: int = 10) -> str:
        """Iter40 (2026-02) — Conversation memory.

        EmergentIntegrations `LlmChat` is stateless across instances, so we must
        inject the last N exchanges of the current session into the user prompt
        ourselves. This helper is used by every non-streaming `_llm_send` call
        site (web chat fallback, WhatsApp inbound, vision chat). The streaming
        endpoint uses an inline variant for parallel `asyncio.gather`.
        """
        try:
            rows = await db.liluvine_pro_messages.find(
                {"session_id": sid, "role": {"$in": ["user", "assistant"]}},
                {"_id": 0, "role": 1, "content": 1, "created_at": 1},
            ).sort("created_at", -1).limit(limit + 1).to_list(limit + 1)
        except Exception:  # noqa: BLE001
            return ""
        # Drop the message the caller just inserted (matched by exact text)
        rows = [r for r in rows if (r.get("content") or "") != current_text][:limit]
        if not rows:
            return ""
        rows.reverse()
        lines = ["[HISTORIQUE DE LA CONVERSATION (du plus ancien au plus récent)]"]
        for r in rows:
            prefix = "Utilisateur" if r["role"] == "user" else "Liluvine"
            body = (r.get("content") or "")[:1500]
            lines.append(f"{prefix}: {body}")
        lines.append("[FIN HISTORIQUE]\n")
        return "\n".join(lines)

    async def _llm_send(session_id: str, system_text: str, user_text: str) -> Dict[str, Any]:
        """Spin a fresh LlmChat instance, send the message, return reply + token estimate.

        Iter38r-fix9t — Switched from claude-sonnet-4-6 to claude-haiku-4-5-20251001
        (≈3× faster, suitable for the chat workload). The full model identifier
        is kept in `LILUVINE_MODEL` so a future rollback is one-line.
        """
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=f"Bibliothèque IA absente : {exc}") from exc
        if not api_key:
            raise HTTPException(status_code=503, detail="EMERGENT_LLM_KEY manquant côté serveur.")
        chat = LlmChat(
            api_key=api_key,
            session_id=session_id,
            system_message=system_text,
        ).with_model("anthropic", LILUVINE_MODEL)
        # S031 — Record LLM outcome for the budget-exceeded banner
        try:
            reply = await chat.send_message(UserMessage(text=user_text))
            try:
                from routes.llm_health import record_llm_outcome
                await record_llm_outcome(db, ok=True, context="liluvine_chat")
            except Exception:  # noqa: BLE001
                pass
        except Exception as _llm_exc:
            try:
                from routes.llm_health import record_llm_outcome
                await record_llm_outcome(db, ok=False, error=str(_llm_exc), context="liluvine_chat")
            except Exception:  # noqa: BLE001
                pass
            raise
        # Token estimation : ~4 chars per token. Used for quota accounting.
        tokens = max(int((len(system_text) + len(user_text) + len(reply or "")) / 4), 1)
        return {"reply": reply or "", "tokens": tokens, "model": LILUVINE_MODEL}

    # ----------------------------------------------------------
    # Iter38r-fix9a — Admin Auto-reply WhatsApp config
    # ----------------------------------------------------------
    AUTOREPLY_FIELDS = {
        "enabled": "liluvine_wa_autoreply_enabled",
        "allow_phones": "liluvine_wa_autoreply_allow_phones",
        "deny_phones": "liluvine_wa_autoreply_deny_phones",
        "allow_mode": "liluvine_wa_autoreply_allow_mode",
        "schedule": "liluvine_wa_autoreply_schedule",
        "keywords": "liluvine_wa_autoreply_keywords",
        "cooldown_seconds": "liluvine_wa_autoreply_cooldown_seconds",
        "signature": "liluvine_wa_autoreply_signature",
        # Iter43-fix24h — Catch-all fallback `…`
        "unknown_cmd_reply": "liluvine_wa_unknown_cmd_reply",
        "unknown_cmd_fallback_enabled": "liluvine_wa_unknown_cmd_fallback_enabled",
        # Iter43-fix24j — Profil "marque/HQ" pour !adresse / !horaires
        "brand_name": "liluvine_wa_brand_name",
        "brand_phone": "liluvine_wa_brand_phone",
        "brand_whatsapp": "liluvine_wa_brand_whatsapp",
        "brand_email": "liluvine_wa_brand_email",
        "brand_address": "liluvine_wa_brand_address",
        "brand_city": "liluvine_wa_brand_city",
        "brand_country": "liluvine_wa_brand_country",
        "brand_location_hint": "liluvine_wa_brand_location_hint",
        "brand_latitude": "liluvine_wa_brand_latitude",
        "brand_longitude": "liluvine_wa_brand_longitude",
        "brand_hours": "liluvine_wa_brand_hours",
        "brand_maps_url": "liluvine_wa_brand_maps_url",
    }

    @api.get("/admin/liluvine-pro/wa-autoreply", tags=["Admin — Liluvine PRO"])
    async def admin_get_autoreply(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        return {
            "enabled": bool(s.get("liluvine_wa_autoreply_enabled")),
            "allow_phones": s.get("liluvine_wa_autoreply_allow_phones") or [],
            "deny_phones": s.get("liluvine_wa_autoreply_deny_phones") or [],
            "allow_mode": s.get("liluvine_wa_autoreply_allow_mode") or "any",
            "schedule": s.get("liluvine_wa_autoreply_schedule") or "always",
            "keywords": s.get("liluvine_wa_autoreply_keywords") or [],
            "cooldown_seconds": int(s.get("liluvine_wa_autoreply_cooldown_seconds") or 60),
            "signature": s.get("liluvine_wa_autoreply_signature") or "— 🤖 Réponse automatique Liluvine PRO",
            # Iter43-fix24h
            "unknown_cmd_reply": s.get("liluvine_wa_unknown_cmd_reply") or "",
            "unknown_cmd_fallback_enabled": bool(s.get("liluvine_wa_unknown_cmd_fallback_enabled", True)),
            # Iter43-fix24j — Brand
            "brand_name": s.get("liluvine_wa_brand_name") or "",
            "brand_phone": s.get("liluvine_wa_brand_phone") or "",
            "brand_whatsapp": s.get("liluvine_wa_brand_whatsapp") or "",
            "brand_email": s.get("liluvine_wa_brand_email") or "",
            "brand_address": s.get("liluvine_wa_brand_address") or "",
            "brand_city": s.get("liluvine_wa_brand_city") or "",
            "brand_country": s.get("liluvine_wa_brand_country") or "",
            "brand_location_hint": s.get("liluvine_wa_brand_location_hint") or "",
            "brand_latitude": s.get("liluvine_wa_brand_latitude"),
            "brand_longitude": s.get("liluvine_wa_brand_longitude"),
            "brand_hours": s.get("liluvine_wa_brand_hours") or "",
            "brand_maps_url": s.get("liluvine_wa_brand_maps_url") or "",
        }

    @api.put("/admin/liluvine-pro/wa-autoreply", tags=["Admin — Liluvine PRO"])
    async def admin_set_autoreply(payload: AutoreplyConfigPayload = Body(...), user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        update: Dict[str, Any] = {}
        for k, dbkey in AUTOREPLY_FIELDS.items():
            v = getattr(payload, k)
            if v is not None:
                if k in ("allow_phones", "deny_phones"):
                    # Normalize to digits
                    update[dbkey] = ["".join(ch for ch in str(x) if ch.isdigit()) for x in v if str(x).strip()]
                elif k == "keywords":
                    update[dbkey] = [str(x).strip().lower() for x in v if str(x).strip()]
                else:
                    update[dbkey] = v
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["liluvine_wa_autoreply_updated_at"] = _now()
        update["liluvine_wa_autoreply_updated_by"] = user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    @api.get("/admin/liluvine-pro/wa-autoreply/history", tags=["Admin — Liluvine PRO"])
    async def admin_autoreply_history(limit: int = 50, user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        cursor = db.liluvine_pro_messages.find(
            {"external_source": "whatsapp_native", "role": "assistant"},
            {"_id": 0, "id": 1, "session_id": 1, "content": 1, "wa_message_id_out": 1,
             "tokens": 1, "created_at": 1, "context_injected": 1},
        ).sort("created_at", -1).limit(min(max(limit, 1), 200))
        items = await cursor.to_list(min(max(limit, 1), 200))
        # Enrich with the originating session label
        sids = list({i.get("session_id") for i in items if i.get("session_id")})
        sessions = await db.liluvine_pro_sessions.find(
            {"id": {"$in": sids}}, {"_id": 0, "id": 1, "user_label": 1, "title": 1}
        ).to_list(len(sids))
        sess_by_id = {s["id"]: s for s in sessions}
        for it in items:
            sess = sess_by_id.get(it.get("session_id")) or {}
            it["session_label"] = sess.get("user_label") or sess.get("title") or ""
        return {"items": items, "count": len(items)}

    # Iter38r-fix9e — Recent auto-reply events for the live toast feed.
    # Polled every 20s by the portal layout. Returns only events after `since`.
    @api.get("/me/liluvine-pro/autoreply-feed", tags=["Portail Client — Liluvine PRO"])
    async def autoreply_feed(since: Optional[str] = None, user: dict = Depends(get_current_user)):
        # Scope to the user's tenant
        tenant_id = user.get("id")
        if user.get("role") not in ("admin", "superviseur"):
            # Tracked users inherit parent tenant
            tu = await db.tracked_users.find_one({"email": user.get("email")}, {"_id": 0, "client_id": 1})
            tenant_id = (tu or {}).get("client_id") or user.get("id")
        query = {
            "client_id": tenant_id,
            "external_source": "whatsapp_native",
            "role": "assistant",
        }
        if since:
            query["created_at"] = {"$gt": since}
        cursor = db.liluvine_pro_messages.find(
            query,
            {"_id": 0, "id": 1, "session_id": 1, "content": 1, "created_at": 1, "tokens": 1},
        ).sort("created_at", -1).limit(20)
        items = await cursor.to_list(20)
        sids = list({i.get("session_id") for i in items if i.get("session_id")})
        sessions = await db.liluvine_pro_sessions.find(
            {"id": {"$in": sids}},
            {"_id": 0, "id": 1, "user_label": 1, "external_payload": 1},
        ).to_list(len(sids))
        sess_by_id = {s["id"]: s for s in sessions}
        # Iter40 (2026-02) — Filtre no-toast WA : si activé, exclure les
        # messages provenant des numéros silencieux (matching sur les 9
        # derniers chiffres pour ignorer le code pays).
        s_global = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_silent_phones_enabled": 1, "wa_silent_phones": 1}) or {}
        silent_tails: set = set()
        if s_global.get("wa_silent_phones_enabled"):
            for p in (s_global.get("wa_silent_phones") or []):
                d = "".join(ch for ch in (p or "") if ch.isdigit())
                if d:
                    silent_tails.add(d[-9:])
        filtered = []
        for it in items:
            sess = sess_by_id.get(it.get("session_id")) or {}
            phone = ((sess.get("external_payload") or {}).get("phone_digits")) or ""
            if silent_tails and phone:
                tail = "".join(ch for ch in phone if ch.isdigit())[-9:]
                if tail in silent_tails:
                    continue  # skip — caller is on the silent list
            it["contact_label"] = sess.get("user_label") or "Contact WhatsApp"
            it["phone_digits"] = phone
            if len(it.get("content") or "") > 140:
                it["content_preview"] = it["content"][:140] + "…"
            else:
                it["content_preview"] = it["content"]
            filtered.append(it)
        return {
            "items": filtered,
            "server_now": _now(),
            "count": len(filtered),
        }


    # ----------------------------------------------------------
    # Public branding for Liluvine PRO (frontend uses this)
    # ----------------------------------------------------------
    @api.get("/me/liluvine-pro/branding", tags=["Portail Client — Liluvine PRO"])
    async def get_branding(user: dict = Depends(get_current_user)):
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        return {
            "name": s.get("liluvine_pro_name") or "Liluvine PRO",
            "avatar_url": s.get("liluvine_pro_avatar_url") or "",
            "color": s.get("liluvine_pro_color") or "fuchsia",
            "tagline": s.get("liluvine_pro_tagline") or "Assistant IA SAWALI",
        }

    # Iter38r-fix9e — Admin endpoints to manage Liluvine PRO branding
    @api.get("/admin/liluvine-pro/branding", tags=["Admin — Liluvine PRO"])
    async def admin_get_branding(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        return {
            "name": s.get("liluvine_pro_name") or "Liluvine PRO",
            "avatar_url": s.get("liluvine_pro_avatar_url") or "",
            "color": s.get("liluvine_pro_color") or "fuchsia",
            "tagline": s.get("liluvine_pro_tagline") or "Assistant IA SAWALI",
        }

    @api.put("/admin/liluvine-pro/branding", tags=["Admin — Liluvine PRO"])
    async def admin_set_branding(payload: BrandingPayload = Body(...), user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        update: Dict[str, Any] = {}
        if payload.name is not None:
            update["liluvine_pro_name"] = payload.name.strip() or "Liluvine PRO"
        if payload.avatar_url is not None:
            update["liluvine_pro_avatar_url"] = payload.avatar_url.strip()
        if payload.color is not None:
            update["liluvine_pro_color"] = payload.color
        if payload.tagline is not None:
            update["liluvine_pro_tagline"] = payload.tagline.strip()
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["liluvine_pro_branding_updated_at"] = _now()
        update["liluvine_pro_branding_updated_by"] = user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    # ----------------------------------------------------------
    # Inbound webhook — n8n, WhatsApp, Facebook can POST prompts.
    # The path-secret protects against random POSTs. Source identifies
    # the channel for the reply routing.
    # ----------------------------------------------------------
    @api.post("/webhooks/liluvine-pro/{source}/{secret}", tags=["Webhooks"])
    async def liluvine_inbound(source: str, secret: str, request: Request):
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        expected = (s.get("liluvine_pro_inbound_secret") or "").strip()
        if not expected or secret != expected:
            raise HTTPException(status_code=403, detail="Secret invalide")
        if source not in ("n8n", "whatsapp", "facebook", "custom"):
            raise HTTPException(status_code=400, detail="Source non supportée. Utilisez n8n|whatsapp|facebook|custom.")
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        text = (payload.get("text") or payload.get("message") or payload.get("prompt") or "").strip()
        client_id_hint = payload.get("client_id") or payload.get("tenant_id")
        session_id_hint = payload.get("session_id")
        # Resolve user: by client_id if provided, else use the first admin
        client_id = client_id_hint
        if not client_id:
            admin = await db.users.find_one({"role": "admin"}, {"_id": 0, "id": 1})
            client_id = admin["id"] if admin else None
        if not client_id or not text:
            raise HTTPException(status_code=400, detail="Champ 'text' et 'client_id' (ou admin par défaut) requis.")
        # Find a user we can attribute the request to
        user_doc = await db.users.find_one({"id": client_id}, {"_id": 0})
        if not user_doc:
            raise HTTPException(status_code=404, detail="client_id introuvable")
        # Persist the inbound message + log it for audit
        sid = session_id_hint or secrets.token_urlsafe(12)
        if not session_id_hint:
            await db.liluvine_pro_sessions.insert_one({
                "id": sid, "client_id": client_id, "user_id": user_doc["id"],
                "user_label": f"[{source.upper()}] {payload.get('from') or 'externe'}",
                "title": f"{source.upper()} · {text[:40]}",
                "created_at": _now(), "updated_at": _now(),
                "message_count": 0, "external_source": source,
                "external_payload": {k: v for k, v in payload.items() if k != "text"},
            })
        await db.liluvine_pro_messages.insert_one({
            "id": secrets.token_urlsafe(12),
            "session_id": sid, "client_id": client_id,
            "user_id": user_doc["id"], "role": "user", "content": text,
            "external_source": source,
            "created_at": _now(),
        })
        # Fetch context + call LLM
        ctx = await _fetch_context_snippets(db, user_doc, text)
        # Iter38r-fix9c — Inject the Knowledge Base content
        # S038 — pass the user query so build_kb_context can run a RAG
        # search across Qdrant collections (when enabled).
        try:
            from routes.liluvine_kb import build_kb_context
            kb = await build_kb_context(db, query=text)
        except Exception:
            kb = ""
        system_text = (await _resolve_system_prompt(client_id)) + (("\n" + ctx) if ctx else "") + (("\n\n" + kb) if kb else "")
        # Iter38r-fix9o (Item 1) — Keyword pre-check for explicit human-handoff requests
        _user_lower = text.lower()
        _escalate_pre = any(k in _user_lower for k in ESCALATION_KEYWORDS)
        # Iter40-fix (2026-02) — Inject the conversation memory so Liluvine
        # remembers the previous exchanges of this session.
        memory_block = await _build_memory_block(sid, text)
        try:
            llm = await _llm_send(sid, system_text, (memory_block + text) if memory_block else text)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[liluvine-pro-inbound] LLM failure")
            raise HTTPException(status_code=502, detail=f"LLM indisponible : {str(exc)[:160]}") from exc
        # Iter38r-fix9o (Item 1) — Strip the escalation marker from the visible
        # reply, but capture the event for the admin notification toast/email.
        reply_text = llm["reply"] or ""
        _escalate_llm = ESCALATION_TOKEN in reply_text
        if _escalate_llm:
            reply_text = reply_text.replace(ESCALATION_TOKEN, "").strip()
        escalated = _escalate_pre or _escalate_llm
        msg_id = secrets.token_urlsafe(12)
        await db.liluvine_pro_messages.insert_one({
            "id": msg_id, "session_id": sid, "client_id": client_id,
            "user_id": user_doc["id"], "role": "assistant", "content": reply_text,
            "tokens": llm["tokens"], "model": llm["model"],
            "context_injected": bool(ctx), "external_source": source,
            "escalation": bool(escalated),
            "created_at": _now(),
        })
        if escalated:
            await _flag_escalation(sid, client_id,
                                   source="keyword" if _escalate_pre else "llm")
        await db.liluvine_pro_sessions.update_one(
            {"id": sid}, {"$inc": {"message_count": 2}, "$set": {"updated_at": _now()}},
        )
        await _track(user_doc, llm["tokens"], llm["model"],
                     metadata={"source": source, "session_id": sid})
        # Outbound forward to n8n if configured (so n8n can dispatch to WhatsApp/Facebook)
        n8n_url = (s.get("liluvine_pro_n8n_outbound_url") or "").strip()
        n8n_token = (s.get("liluvine_pro_n8n_outbound_token") or "").strip()
        forwarded = False
        if n8n_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=8.0) as cli:
                    fwd_headers = {"Content-Type": "application/json"}
                    if n8n_token:
                        fwd_headers["Authorization"] = f"Bearer {n8n_token}"
                    await cli.post(n8n_url, headers=fwd_headers, json={
                        "source": source,
                        "session_id": sid,
                        "reply": llm["reply"],
                        "original_text": text,
                        "from": payload.get("from"),
                        "to": payload.get("to"),
                        "metadata": payload.get("metadata"),
                    })
                forwarded = True
            except Exception:
                logger.exception("[liluvine-pro] n8n forward failed")
        return {
            "ok": True, "session_id": sid, "message_id": msg_id,
            "reply": llm["reply"], "tokens": llm["tokens"], "model": llm["model"],
            "forwarded_to_n8n": forwarded,
        }

    # ----------------------------------------------------------
    # Admin — return the inbound URLs for n8n/WhatsApp/Facebook integration
    # ----------------------------------------------------------
    @api.get("/admin/liluvine-pro/inbound-urls", tags=["Admin — Liluvine PRO"])
    async def admin_inbound_urls(request: Request, _: dict = Depends(get_current_user)):
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        secret = (s.get("liluvine_pro_inbound_secret") or "").strip()
        if not secret:
            secret = secrets.token_urlsafe(32)
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"liluvine_pro_inbound_secret": secret,
                          "liluvine_pro_inbound_secret_generated_at": _now()}},
                upsert=True,
            )
        fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        fwd_scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        base = f"{fwd_scheme}://{fwd_host}".rstrip("/") if fwd_host else str(request.base_url).rstrip("/")
        return {
            "n8n_url": f"{base}/api/webhooks/liluvine-pro/n8n/{secret}",
            "whatsapp_url": f"{base}/api/webhooks/liluvine-pro/whatsapp/{secret}",
            "facebook_url": f"{base}/api/webhooks/liluvine-pro/facebook/{secret}",
            "custom_url": f"{base}/api/webhooks/liluvine-pro/custom/{secret}",
            "secret_preview": secret[:6] + "…" + secret[-4:],
        }

    # ----------------------------------------------------------
    # POST /chat — send a message
    # ----------------------------------------------------------
    @api.post("/me/liluvine-pro/chat", tags=["Portail Client — Liluvine PRO"])
    async def chat(payload: ChatMessage, user: dict = Depends(get_current_user)):
        # Iter38r-fix7 + Bypass (2026-02): allow if tenant feature ON OR
        # the user's email is in the admin bypass list.
        gate = await _liluvine_pro_allowed(db, user)
        if not gate["allowed"]:
            raise HTTPException(status_code=403, detail=gate["reason"])
        chk = await _pre_check(user, "claude-haiku-4-5-20251001")
        if not chk.get("allowed"):
            raise HTTPException(status_code=429, detail=chk.get("reason") or "Quota IA atteint.")
        scope = _client_scope(user)
        sid = payload.session_id
        # Create a new session if needed
        if not sid:
            sid = secrets.token_urlsafe(12)
            await db.liluvine_pro_sessions.insert_one({
                "id": sid,
                "client_id": scope,
                "user_id": user["id"],
                "user_label": user.get("full_name") or user.get("email") or "—",
                "title": payload.text[:60].strip() or "Nouvelle conversation",
                "created_at": _now(),
                "updated_at": _now(),
                "message_count": 0,
            })
        else:
            session = await db.liluvine_pro_sessions.find_one(
                {"id": sid, "client_id": scope}, {"_id": 0},
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session introuvable.")
        # Persist the user message
        await db.liluvine_pro_messages.insert_one({
            "id": secrets.token_urlsafe(12),
            "session_id": sid,
            "client_id": scope,
            "user_id": user["id"],
            "role": "user",
            "content": payload.text,
            "created_at": _now(),
        })
        # Fetch RAG context based on keywords in the user's text
        ctx = await _fetch_context_snippets(db, user, payload.text)
        # Iter38r-fix9c — Inject the Knowledge Base content for the main chat too
        # S038 — query-aware: triggers RAG semantic search via Qdrant.
        try:
            from routes.liluvine_kb import build_kb_context
            kb = await build_kb_context(db, query=payload.text)
        except Exception:
            kb = ""
        system_text = (await _resolve_system_prompt(scope)) + (("\n" + ctx) if ctx else "") + (("\n\n" + kb) if kb else "")
        # Iter38r-fix9o (Item 1) — Keyword pre-check
        _escalate_pre = any(k in payload.text.lower() for k in ESCALATION_KEYWORDS)
        # Iter40-fix (2026-02) — Inject the conversation memory so Liluvine
        # remembers previous exchanges (LlmChat is stateless across instances).
        memory_block = await _build_memory_block(sid, payload.text)
        # Call the LLM (history is injected manually via memory_block above)
        try:
            llm = await _llm_send(sid, system_text, (memory_block + payload.text) if memory_block else payload.text)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[liluvine-pro] LLM failure")
            raise HTTPException(status_code=502, detail=f"Liluvine indisponible : {str(exc)[:160]}") from exc
        # Iter38r-fix9o (Item 1) — Strip the escalation marker before persisting
        reply_text = llm["reply"] or ""
        _escalate_llm = ESCALATION_TOKEN in reply_text
        if _escalate_llm:
            reply_text = reply_text.replace(ESCALATION_TOKEN, "").strip()
        escalated = _escalate_pre or _escalate_llm
        # Persist the assistant reply
        msg_id = secrets.token_urlsafe(12)
        await db.liluvine_pro_messages.insert_one({
            "id": msg_id,
            "session_id": sid,
            "client_id": scope,
            "user_id": user["id"],
            "role": "assistant",
            "content": reply_text,
            "tokens": llm["tokens"],
            "model": llm["model"],
            "context_injected": bool(ctx),
            "escalation": bool(escalated),
            "created_at": _now(),
        })
        if escalated:
            await _flag_escalation(sid, scope,
                                   source="keyword" if _escalate_pre else "llm")
        # Bump session counter
        await db.liluvine_pro_sessions.update_one(
            {"id": sid},
            {"$inc": {"message_count": 2},
             "$set": {"updated_at": _now()}},
        )
        # Log quota (post)
        track_result = await _track(
            user, llm["tokens"], llm["model"],
            metadata={"session_id": sid, "context_injected": bool(ctx)},
        )
        return {
            "ok": True,
            "session_id": sid,
            "message_id": msg_id,
            "reply": reply_text,
            "tokens": llm["tokens"],
            "model": llm["model"],
            "context_injected": bool(ctx),
            "escalation": bool(escalated),
            "warn": track_result.get("warn", False),
        }

    # ----------------------------------------------------------
    # S044 (2026-02) — POST /chat-with-image
    # Liluvine "sees" a client screenshot: Claude Vision extracts the
    # OCR + visual summary, then Qdrant finds the closest SAWALI image
    # in the knowledge base. The LLM is fed the analysis + matches so
    # it can identify the screen and propose the relevant procedure.
    # ----------------------------------------------------------
    @api.post("/me/liluvine-pro/chat-with-image", tags=["Portail Client — Liluvine PRO"])
    async def chat_with_image(
        file: UploadFile = File(...),
        text: str = Form(""),
        session_id: Optional[str] = Form(None),
        user: dict = Depends(get_current_user),
    ):
        # Same feature gate as /chat (with bypass)
        gate = await _liluvine_pro_allowed(db, user)
        if not gate["allowed"]:
            raise HTTPException(status_code=403, detail=gate["reason"])
        chk = await _pre_check(user, LILUVINE_MODEL)
        if not chk.get("allowed"):
            raise HTTPException(status_code=429, detail=chk.get("reason") or "Quota IA atteint.")
        ct = (file.content_type or "").lower()
        if not ct.startswith("image/"):
            raise HTTPException(status_code=400, detail="Fichier image attendu (JPEG, PNG, WebP).")
        if ct not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            raise HTTPException(status_code=400, detail=f"Format non supporté : {ct}")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        if len(content) > 15 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image > 15 Mo.")
        # 1) Persist the client's image so we can show it back in the chat
        try:
            import object_storage as _obj_storage
            ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
            ext = ext_map.get(ct, "bin")
            stored = await _obj_storage.save_and_log(
                db, data=content, kind="liluvine_user_image",
                tenant_id="sawali_global", ext=ext, content_type=ct,
                original_filename=file.filename or f"upload.{ext}",
                user_id=user.get("id"),
                metadata={"session_id": session_id or ""},
            )
            client_image_url = stored.get("url")
        except Exception:  # noqa: BLE001
            logger.exception("[liluvine-chat-image] storing failed")
            client_image_url = None
        # 2) Run Claude Vision on the client's image
        analysis = {"ocr_text": "", "visual_summary": ""}
        try:
            from routes.qdrant_rag import describe_image_with_vision
            analysis = await describe_image_with_vision(content, ct) or analysis
        except Exception:  # noqa: BLE001
            logger.exception("[liluvine-chat-image] Claude Vision failed")
        # 3) Search Qdrant for similar SAWALI screenshots
        matches: list = []
        try:
            from routes.qdrant_rag import search_similar_images
            search_query = "\n".join([
                p for p in [text, analysis.get("visual_summary"), analysis.get("ocr_text")] if p
            ]).strip()
            if search_query:
                matches = await search_similar_images(db, query=search_query, top_k=3)
        except Exception:  # noqa: BLE001
            logger.exception("[liluvine-chat-image] Qdrant image search failed")
        # 4) Create / pick session
        scope = _client_scope(user)
        sid = session_id
        first_line = (text or "").strip().splitlines()[0] if text.strip() else "📸 Capture d'écran"
        if not sid:
            sid = secrets.token_urlsafe(12)
            await db.liluvine_pro_sessions.insert_one({
                "id": sid,
                "client_id": scope,
                "user_id": user["id"],
                "user_label": user.get("full_name") or user.get("email") or "—",
                "title": first_line[:60] or "Capture d'écran",
                "created_at": _now(),
                "updated_at": _now(),
                "message_count": 0,
            })
        else:
            session = await db.liluvine_pro_sessions.find_one(
                {"id": sid, "client_id": scope}, {"_id": 0},
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session introuvable.")
        # 5) Build a rich user prompt that the LLM will see
        prompt_parts: list[str] = []
        if text.strip():
            prompt_parts.append(text.strip())
        prompt_parts.append("\n[ANALYSE DE LA CAPTURE D'ÉCRAN ENVOYÉE PAR LE CLIENT]")
        if analysis.get("visual_summary"):
            prompt_parts.append(f"Description visuelle : {analysis['visual_summary']}")
        if analysis.get("ocr_text"):
            ocr = analysis["ocr_text"][:1500]
            prompt_parts.append(f"Texte visible (OCR) :\n{ocr}")
        if not analysis.get("visual_summary") and not analysis.get("ocr_text"):
            prompt_parts.append("(Aucun texte ou élément visuel notable n'a pu être extrait — l'image est peut-être floue ou vide.)")
        if matches:
            prompt_parts.append("\n[ÉCRANS SAWALI POSSIBLEMENT CORRESPONDANTS — IDENTIFIE LE BON]")
            for i, m in enumerate(matches, start=1):
                line = f"  {i}. {m['title'] or '(sans titre)'}  (score {m['score']:.2f})"
                if m.get("visual_summary"):
                    line += f"\n     → {m['visual_summary'][:250]}"
                prompt_parts.append(line)
            prompt_parts.append(
                "\nQuand tu réponds, indique si l'une de ces images SAWALI correspond exactement à "
                "l'écran du client (ex: « Vous êtes sur l'écran X. Voici la procédure : … ») et "
                "inclus l'image en Markdown ![titre](url) en utilisant les URLs ci-dessous :"
            )
            for m in matches:
                prompt_parts.append(f"  - {m['title'] or 'écran'}: {m['image_url']}")
        else:
            prompt_parts.append("\n(Aucune image SAWALI ne correspond — réponds en t'appuyant sur l'analyse + ta connaissance générale du CRM SAWALI.)")
        enriched_user_text = "\n".join(prompt_parts)
        # 6) Persist the user message (text + image URL)
        await db.liluvine_pro_messages.insert_one({
            "id": secrets.token_urlsafe(12),
            "session_id": sid,
            "client_id": scope,
            "user_id": user["id"],
            "role": "user",
            "content": text or "📸 Capture d'écran envoyée",
            "user_image_url": client_image_url,
            "image_analysis": analysis,
            "matched_images": matches,
            "created_at": _now(),
        })
        # 7) Call the LLM with the enriched prompt
        ctx = await _fetch_context_snippets(db, user, text or analysis.get("visual_summary") or "")
        system_text = (await _resolve_system_prompt(scope)) + (("\n" + ctx) if ctx else "")
        # Iter40-fix (2026-02) — Inject conversation memory for vision chat too.
        memory_block = await _build_memory_block(sid, text or "📸 Capture d'écran envoyée")
        try:
            llm = await _llm_send(sid, system_text, (memory_block + enriched_user_text) if memory_block else enriched_user_text)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[liluvine-chat-image] LLM failure")
            raise HTTPException(status_code=502, detail=f"Liluvine indisponible : {str(exc)[:160]}") from exc
        reply_text = (llm["reply"] or "").strip()
        # 8) Persist the assistant reply
        msg_id = secrets.token_urlsafe(12)
        await db.liluvine_pro_messages.insert_one({
            "id": msg_id,
            "session_id": sid,
            "client_id": scope,
            "user_id": user["id"],
            "role": "assistant",
            "content": reply_text,
            "tokens": llm["tokens"],
            "model": llm["model"],
            "vision_used": True,
            "created_at": _now(),
        })
        await db.liluvine_pro_sessions.update_one(
            {"id": sid}, {"$inc": {"message_count": 2}, "$set": {"updated_at": _now()}},
        )
        track_result = await _track(
            user, llm["tokens"], llm["model"],
            metadata={"session_id": sid, "vision": True, "matches": len(matches)},
        )
        return {
            "ok": True,
            "session_id": sid,
            "message_id": msg_id,
            "reply": reply_text,
            "tokens": llm["tokens"],
            "model": llm["model"],
            "user_image_url": client_image_url,
            "image_analysis": analysis,
            "matched_images": matches,
            "warn": track_result.get("warn", False),
        }

    # ----------------------------------------------------------
    # Iter38r-fix9t — POST /chat/stream — Server-Sent Events streaming
    # ----------------------------------------------------------
    # The underlying emergentintegrations library does NOT expose native
    # token streaming, so we implement a pseudo-streaming pipeline:
    #   1) call _llm_send() to obtain the full reply (Haiku 4.5 is fast)
    #   2) chunk the reply (~6 chars at a time, ~25 ms cadence)
    #   3) emit SSE `data:` lines so the browser displays a typewriter effect
    # Combined with Haiku 4.5 (≈1.0-1.5 s) + KB cache + parallel fetchers,
    # the first visible token appears within ~1.0 s and the full reply
    # streams over ~2-3 s instead of arriving as a 4-7 s blocking response.
    # ----------------------------------------------------------
    @api.post("/me/liluvine-pro/chat/stream", tags=["Portail Client — Liluvine PRO"])
    async def chat_stream(payload: ChatMessage, user: dict = Depends(get_current_user)):
        gate = await _liluvine_pro_allowed(db, user)
        if not gate["allowed"]:
            raise HTTPException(status_code=403, detail=gate["reason"])
        chk = await _pre_check(user, LILUVINE_MODEL)
        if not chk.get("allowed"):
            raise HTTPException(status_code=429, detail=chk.get("reason") or "Quota IA atteint.")
        scope = _client_scope(user)
        sid = payload.session_id
        if not sid:
            sid = secrets.token_urlsafe(12)
            await db.liluvine_pro_sessions.insert_one({
                "id": sid, "client_id": scope, "user_id": user["id"],
                "user_label": user.get("full_name") or user.get("email") or "—",
                "title": payload.text[:60].strip() or "Nouvelle conversation",
                "created_at": _now(), "updated_at": _now(), "message_count": 0,
            })
        else:
            session = await db.liluvine_pro_sessions.find_one(
                {"id": sid, "client_id": scope}, {"_id": 0},
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session introuvable.")
        await db.liluvine_pro_messages.insert_one({
            "id": secrets.token_urlsafe(12), "session_id": sid, "client_id": scope,
            "user_id": user["id"], "role": "user", "content": payload.text,
            "created_at": _now(),
        })

        async def _event_stream():
            try:
                # Emit early "session" event so the frontend can render the id
                yield f"event: session\ndata: {json.dumps({'session_id': sid})}\n\n"
                # Heavy lifting — context + LLM call
                ctx_task = _fetch_context_snippets(db, user, payload.text)
                kb_task = _resolve_kb_context(payload.text)
                sys_task = _resolve_system_prompt(scope)
                # Iter40 (2026-02) — Mémoire de conversation : on récupère les 10
                # derniers messages de la session pour les inclure dans le user
                # prompt. EmergentIntegrations LlmChat est stateless donc sans
                # cette injection, Liluvine oublie le contexte d'un message à
                # l'autre. Le message courant (`payload.text`) vient d'être
                # inséré au-dessus → on le retire des derniers.
                hist_task = db.liluvine_pro_messages.find(
                    {"session_id": sid, "role": {"$in": ["user", "assistant"]}},
                    {"_id": 0, "role": 1, "content": 1, "created_at": 1},
                ).sort("created_at", -1).limit(11).to_list(11)
                ctx, kb, base_sys, hist = await asyncio.gather(ctx_task, kb_task, sys_task, hist_task)
                # hist[0] = le message qu'on vient d'insérer → on l'enlève.
                # Puis on remet en ordre chronologique.
                hist = [h for h in hist if h.get("content") != payload.text][:10]
                hist.reverse()
                memory_block = ""
                if hist:
                    lines = ["[HISTORIQUE DE LA CONVERSATION (du plus ancien au plus récent)]"]
                    for h in hist:
                        prefix = "Utilisateur" if h["role"] == "user" else "Liluvine"
                        body = (h.get("content") or "")[:1500]
                        lines.append(f"{prefix}: {body}")
                    lines.append("[FIN HISTORIQUE]\n")
                    memory_block = "\n".join(lines)
                system_text = base_sys + (("\n" + ctx) if ctx else "") + (("\n\n" + kb) if kb else "")
                _escalate_pre = any(k in payload.text.lower() for k in ESCALATION_KEYWORDS)
                # Notify the client we're now waiting on the LLM
                yield f"event: status\ndata: {json.dumps({'phase': 'llm'})}\n\n"
                llm = await _llm_send(sid, system_text, (memory_block + payload.text) if memory_block else payload.text)
                reply_text = (llm["reply"] or "").replace(ESCALATION_TOKEN, "").strip()
                _escalate_llm = ESCALATION_TOKEN in (llm["reply"] or "")
                escalated = _escalate_pre or _escalate_llm
                msg_id = secrets.token_urlsafe(12)
                await db.liluvine_pro_messages.insert_one({
                    "id": msg_id, "session_id": sid, "client_id": scope,
                    "user_id": user["id"], "role": "assistant", "content": reply_text,
                    "tokens": llm["tokens"], "model": llm["model"],
                    "context_injected": bool(ctx), "escalation": bool(escalated),
                    "created_at": _now(),
                })
                if escalated:
                    await _flag_escalation(sid, scope,
                                           source="keyword" if _escalate_pre else "llm")
                await db.liluvine_pro_sessions.update_one(
                    {"id": sid},
                    {"$inc": {"message_count": 2}, "$set": {"updated_at": _now()}},
                )
                track_result = await _track(
                    user, llm["tokens"], llm["model"],
                    metadata={"session_id": sid, "context_injected": bool(ctx)},
                )
                # Stream the reply in small chunks (~6 chars / 25 ms typewriter)
                CHUNK = 8
                for i in range(0, len(reply_text), CHUNK):
                    piece = reply_text[i:i + CHUNK]
                    yield f"event: token\ndata: {json.dumps({'text': piece})}\n\n"
                    await asyncio.sleep(0.025)
                # Final "done" event with metadata
                yield "event: done\ndata: " + json.dumps({
                    "message_id": msg_id,
                    "session_id": sid,
                    "tokens": llm["tokens"],
                    "model": llm["model"],
                    "context_injected": bool(ctx),
                    "escalation": bool(escalated),
                    "warn": track_result.get("warn", False),
                }) + "\n\n"
            except HTTPException as exc:
                yield "event: error\ndata: " + json.dumps({"detail": exc.detail, "status": exc.status_code}) + "\n\n"
            except Exception as exc:
                logger.exception("[liluvine-pro] stream failure")
                yield "event: error\ndata: " + json.dumps({"detail": f"Liluvine indisponible : {str(exc)[:160]}"}) + "\n\n"

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable nginx/proxy buffering
            },
        )

    async def _resolve_kb_context(query: str = "") -> str:
        """S038 — passes the user query so Qdrant RAG semantic search
        actually triggers (it's a no-op without the query). The KB
        helper falls back to MongoDB-only KB when Qdrant is disabled or
        returns nothing.

        Iter41 Phase 2 — Also pulls a VIDAL_db excerpt so Liluvine can
        cite the right médicament when the user asks about a drug.
        """
        chunks: list[str] = []
        try:
            from routes.liluvine_kb import build_kb_context
            kb = await build_kb_context(db, query=(query or None))
            if kb:
                chunks.append(kb)
        except Exception:
            pass
        try:
            from routes.vidal_rag import build_vidal_rag_context
            vidal = await build_vidal_rag_context(db, query=query, max_chars=3000)
            if vidal:
                chunks.append(vidal)
        except Exception:
            pass
        return "\n\n".join(chunks)


    # ----------------------------------------------------------
    # GET /sessions — list user's sessions
    # ----------------------------------------------------------
    @api.get("/me/liluvine-pro/sessions", tags=["Portail Client — Liluvine PRO"])
    async def list_sessions(user: dict = Depends(get_current_user)):
        scope = _client_scope(user)
        # Tracked users see only their own sessions. Admins see all sessions
        # under their tenant for auditing.
        query: Dict[str, Any] = {"client_id": scope}
        if user.get("role") not in ("admin", "superviseur"):
            query["user_id"] = user["id"]
        items = await db.liluvine_pro_sessions.find(
            query, {"_id": 0},
        ).sort("updated_at", -1).to_list(200)
        return {"items": items, "count": len(items)}

    # ----------------------------------------------------------
    # GET /sessions/{sid} — fetch session messages
    # ----------------------------------------------------------
    @api.get("/me/liluvine-pro/sessions/{sid}", tags=["Portail Client — Liluvine PRO"])
    async def get_session(sid: str, user: dict = Depends(get_current_user)):
        scope = _client_scope(user)
        session = await db.liluvine_pro_sessions.find_one(
            {"id": sid, "client_id": scope}, {"_id": 0},
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session introuvable.")
        if user.get("role") not in ("admin", "superviseur") and session.get("user_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Accès refusé à cette conversation.")
        messages = await db.liluvine_pro_messages.find(
            {"session_id": sid}, {"_id": 0},
        ).sort("created_at", 1).to_list(2000)
        return {"session": session, "messages": messages}

    # ----------------------------------------------------------
    # PATCH /sessions/{sid} — rename session
    # ----------------------------------------------------------
    @api.patch("/me/liluvine-pro/sessions/{sid}", tags=["Portail Client — Liluvine PRO"])
    async def rename_session(sid: str, payload: RenameSession, user: dict = Depends(get_current_user)):
        scope = _client_scope(user)
        session = await db.liluvine_pro_sessions.find_one({"id": sid, "client_id": scope}, {"_id": 0})
        if not session:
            raise HTTPException(status_code=404, detail="Session introuvable.")
        if user.get("role") not in ("admin", "superviseur") and session.get("user_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Accès refusé.")
        await db.liluvine_pro_sessions.update_one(
            {"id": sid},
            {"$set": {"title": payload.title.strip()[:120], "updated_at": _now()}},
        )
        return {"ok": True, "id": sid, "title": payload.title.strip()[:120]}

    # ----------------------------------------------------------
    # DELETE /sessions/{sid}
    # ----------------------------------------------------------
    @api.delete("/me/liluvine-pro/sessions/{sid}", tags=["Portail Client — Liluvine PRO"])
    async def delete_session(sid: str, user: dict = Depends(get_current_user)):
        scope = _client_scope(user)
        session = await db.liluvine_pro_sessions.find_one({"id": sid, "client_id": scope}, {"_id": 0})
        if not session:
            raise HTTPException(status_code=404, detail="Session introuvable.")
        if user.get("role") not in ("admin", "superviseur") and session.get("user_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Accès refusé.")
        await db.liluvine_pro_sessions.delete_one({"id": sid})
        await db.liluvine_pro_messages.delete_many({"session_id": sid})
        return {"ok": True, "id": sid}

    # ----------------------------------------------------------
    # S037 — User-initiated escalation to admin via WhatsApp.
    # Any authenticated portal user (collaborator, moderator, etc.) can
    # click "Demander de l'aide" in the Liluvine PRO chat UI and send a
    # contextual WhatsApp ping to the admin with their note + last 3
    # messages of the current session.
    # ----------------------------------------------------------
    @api.post("/me/liluvine-pro/request-help", tags=["Portail Client — Liluvine PRO"])
    async def request_help(payload: Dict[str, Any] = Body(default={}), user: dict = Depends(get_current_user)):
        if wa_send_text is None:
            raise HTTPException(status_code=503, detail="WhatsApp non disponible côté serveur")
        note = (payload.get("note") or "").strip()
        if not note:
            raise HTTPException(status_code=400, detail="Veuillez préciser pourquoi vous avez besoin d'aide.")
        if len(note) > 500:
            note = note[:500] + "…"
        session_id = (payload.get("session_id") or "").strip() or None

        # Pull the last 3 messages (oldest → newest) from the session for
        # context. Best-effort — silently ignore failures.
        history = []
        if session_id:
            try:
                cursor = db.liluvine_pro_messages.find(
                    {"session_id": session_id},
                    {"_id": 0, "role": 1, "content": 1, "created_at": 1},
                ).sort("created_at", -1).limit(3)
                msgs = await cursor.to_list(length=3)
                msgs.reverse()
                history = [{"role": m.get("role"), "text": m.get("content") or ""} for m in msgs]
            except Exception:
                pass

        # Identify the collaborator (full_name → email → id) and use the
        # email as the throttle key so multiple collaborators don't block
        # each other.
        collaborator = (user.get("full_name") or user.get("email") or user["id"]).strip()
        throttle_key = (user.get("email") or user["id"]).strip().lower()
        phone_digits = "".join(ch for ch in (user.get("phone") or "") if ch.isdigit())

        try:
            from routes.liluvine_escalation import notify_admin
            res = await notify_admin(
                db,
                contact_name=collaborator,
                contact_phone_digits=phone_digits,
                last_user_message=note,
                reason=f"Demande d'aide manuelle du collaborateur — {note[:120]}",
                send_wa=wa_send_text,
                session_id=session_id,
                history=history,
                initiator="human",
                throttle_key=throttle_key,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Erreur escalade : {exc!s}") from exc
        return res

    # ----------------------------------------------------------
    # Iter38r-fix9i — "Reprendre la conversation" : human takeover
    # ----------------------------------------------------------
    # Allowed to: admin / superviseur / moderateur (and tracked users with
    # an elevated "tracked_role"). Marks a Liluvine session as "owned by a
    # human now" so the WhatsApp auto-reply skips it. Auto-expires after
    # `duration_minutes` (default 120).
    # S-iter39b — Include "moderation" (tracked_role value stored in DB) and
    # "administrateur" so tracked-Moderation/Administrateur users can take over.
    _TAKEOVER_ROLES = {"admin", "superviseur", "moderateur", "moderation", "administrateur"}

    def _can_takeover(u: Dict[str, Any]) -> bool:
        if (u.get("role") or "") in _TAKEOVER_ROLES:
            return True
        # Tracked users may inherit an elevated tracked_role
        if (u.get("tracked_role") or "").lower() in _TAKEOVER_ROLES:
            return True
        return False

    @api.post("/admin/liluvine-pro/sessions/{sid}/takeover", tags=["Admin — Liluvine PRO"])
    async def takeover_session(sid: str, payload: Dict[str, Any] = Body(default={}), user: dict = Depends(get_current_user)):
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé aux rôles administrateur / superviseur / modération")
        scope = _client_scope(user)
        session = await db.liluvine_pro_sessions.find_one({"id": sid, "client_id": scope}, {"_id": 0})
        if not session:
            raise HTTPException(status_code=404, detail="Conversation introuvable")
        # 2026-02 (#3) — Default takeover duration is now admin-configurable
        # via settings.liluvine_takeover_default_minutes. Defaults to 30 min
        # (vs the old hardcoded 120 min that the user found "too long").
        settings_doc = await db.settings.find_one({"_id": "global"}) or {}
        admin_default = int(settings_doc.get("liluvine_takeover_default_minutes") or 30)
        try:
            requested = payload.get("duration_minutes")
            if requested is None:
                duration_minutes = admin_default
            else:
                duration_minutes = max(5, min(int(requested), 7 * 24 * 60))
        except Exception:
            duration_minutes = admin_default
        from datetime import timedelta
        until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        await db.liluvine_pro_sessions.update_one(
            {"id": sid},
            {"$set": {
                "human_takeover": True,
                "human_takeover_by": user.get("email"),
                "human_takeover_at": _now(),
                "human_takeover_until": until.isoformat(),
                "human_takeover_minutes": duration_minutes,
                "updated_at": _now(),
            }},
        )
        # Extract the phone_digits for the redirect
        phone_digits = ((session.get("external_payload") or {}).get("phone_digits")) or ""
        return {
            "ok": True, "id": sid,
            "human_takeover_until": until.isoformat(),
            "phone_digits": phone_digits,
            "contact_id": ((session.get("external_payload") or {}).get("contact_id")),
            "duration_minutes": duration_minutes,
        }

    @api.post("/admin/liluvine-pro/sessions/{sid}/release", tags=["Admin — Liluvine PRO"])
    async def release_session(sid: str, user: dict = Depends(get_current_user)):
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé aux rôles administrateur / superviseur / modération")
        scope = _client_scope(user)
        session = await db.liluvine_pro_sessions.find_one({"id": sid, "client_id": scope}, {"_id": 0})
        if not session:
            raise HTTPException(status_code=404, detail="Conversation introuvable")
        await db.liluvine_pro_sessions.update_one(
            {"id": sid},
            {"$set": {
                "human_takeover": False,
                "human_takeover_released_by": user.get("email"),
                "human_takeover_released_at": _now(),
                "updated_at": _now(),
            }},
        )
        return {"ok": True, "id": sid}

    # Iter38r-fix9i — Aggregated history for the dedicated admin page
    # `/admin/liluvine-history`. Returns sessions enriched with last message
    # snippet, message_count, channel, takeover status. Server-side filters
    # by channel / date range / search keyword.
    @api.get("/admin/liluvine-pro/sessions-history", tags=["Admin — Liluvine PRO"])
    async def admin_sessions_history(
        channel: Optional[str] = None,
        date_range: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 100,
        user: dict = Depends(get_current_user),
    ):
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé aux rôles administrateur / superviseur / modération")
        scope = _client_scope(user)
        query: Dict[str, Any] = {"client_id": scope}
        if channel and channel != "all":
            if channel == "web":
                # web sessions have no external_source flag and don't start with wa:/fb:/sms:
                query["$and"] = [
                    {"$or": [{"external_source": {"$exists": False}}, {"external_source": None}, {"external_source": "web"}]},
                ]
            elif channel == "whatsapp":
                query["$or"] = [{"external_source": "whatsapp_native"}, {"external_source": "whatsapp"}]
            elif channel == "facebook":
                query["external_source"] = "facebook"
            elif channel == "sms":
                query["external_source"] = "sms"
        if date_range and date_range != "all":
            from datetime import timedelta
            windows = {"today": 1, "7d": 7, "30d": 30, "90d": 90}
            days = windows.get(date_range)
            if days:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                query["updated_at"] = {"$gte": cutoff.isoformat()}
        if q:
            rgx = {"$regex": re.escape(q), "$options": "i"}
            query["$or"] = (query.get("$or") or []) + [
                {"title": rgx}, {"user_label": rgx},
            ]
        cap = min(max(limit, 1), 500)
        items = await db.liluvine_pro_sessions.find(query, {"_id": 0}).sort("updated_at", -1).to_list(cap)
        # Enrich with last message preview
        sids = [it["id"] for it in items if it.get("id")]
        last_msgs: Dict[str, Dict[str, Any]] = {}
        if sids:
            cursor = db.liluvine_pro_messages.find(
                {"session_id": {"$in": sids}},
                {"_id": 0, "session_id": 1, "content": 1, "role": 1, "created_at": 1},
            ).sort("created_at", -1)
            async for m in cursor:
                sid = m.get("session_id")
                if sid and sid not in last_msgs:
                    last_msgs[sid] = m
        for it in items:
            sid = it.get("id") or ""
            src = (it.get("external_source") or "").lower()
            if sid.startswith("wa:") or src in ("whatsapp_native", "whatsapp"):
                it["channel"] = "whatsapp"
            elif sid.startswith("fb:") or src == "facebook":
                it["channel"] = "facebook"
            elif sid.startswith("sms:") or src == "sms":
                it["channel"] = "sms"
            else:
                it["channel"] = "web"
            lm = last_msgs.get(it.get("id"))
            if lm:
                preview = (lm.get("content") or "").replace("\n", " ").strip()
                it["last_message_preview"] = preview[:160] + ("…" if len(preview) > 160 else "")
                it["last_message_role"] = lm.get("role")
                it["last_message_at"] = lm.get("created_at")
        return {"items": items, "count": len(items)}

    # ----------------------------------------------------------
    # #1 (2026-02 — suite S044) — Screenshots history + top screens
    # ----------------------------------------------------------
    @api.get("/admin/liluvine-pro/screenshots-history", tags=["Admin — Liluvine PRO"])
    async def admin_screenshots_history(
        days: int = 30,
        limit: int = 100,
        user: dict = Depends(get_current_user),
    ):
        """Liste les captures d'écran envoyées par les clients à Liluvine PRO via
        /chat-with-image endpoint. Each entry includes the sender, the
        original client screenshot URL, the Vision analysis (OCR + summary),
        and the top SAWALI matches that Liluvine proposed."""
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé admin/sup/modération")
        scope = _client_scope(user)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
        query = {
            "client_id": scope,
            "role": "user",
            "user_image_url": {"$ne": None, "$exists": True},
            "created_at": {"$gte": cutoff},
        }
        cap = min(max(limit, 1), 500)
        cursor = db.liluvine_pro_messages.find(query, {"_id": 0}).sort("created_at", -1)
        items = await cursor.to_list(cap)
        sids = list({it.get("session_id") for it in items if it.get("session_id")})
        sess_map: Dict[str, dict] = {}
        if sids:
            async for s in db.liluvine_pro_sessions.find(
                {"id": {"$in": sids}}, {"_id": 0, "id": 1, "user_label": 1, "user_id": 1, "title": 1, "external_source": 1},
            ):
                sess_map[s["id"]] = s
        for it in items:
            sess = sess_map.get(it.get("session_id") or "") or {}
            it["sender_label"] = sess.get("user_label") or "—"
            it["sender_user_id"] = sess.get("user_id")
            it["session_title"] = sess.get("title") or ""
            it["session_channel"] = sess.get("external_source") or "web"
        return {"items": items, "count": len(items), "days": days}

    @api.get("/admin/liluvine-pro/top-screens", tags=["Admin — Liluvine PRO"])
    async def admin_top_screens(
        days: int = 30,
        limit: int = 20,
        user: dict = Depends(get_current_user),
    ):
        """Aggregate the most-matched SAWALI screens across all client
        screenshots. Useful to spot pages that need better onboarding /
        documentation (high-traffic = source of confusion)."""
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé admin/sup/modération")
        scope = _client_scope(user)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
        pipeline = [
            {"$match": {
                "client_id": scope,
                "role": "user",
                "matched_images": {"$exists": True, "$ne": []},
                "created_at": {"$gte": cutoff},
            }},
            {"$unwind": "$matched_images"},
            {"$group": {
                "_id": "$matched_images.image_url",
                "count": {"$sum": 1},
                "title": {"$first": "$matched_images.title"},
                "avg_score": {"$avg": "$matched_images.score"},
                "collection": {"$first": "$matched_images.collection"},
                "last_seen": {"$max": "$created_at"},
            }},
            {"$sort": {"count": -1}},
            {"$limit": min(max(limit, 1), 100)},
            {"$project": {
                "_id": 0, "image_url": "$_id",
                "count": 1, "title": 1, "collection": 1,
                "avg_score": {"$round": ["$avg_score", 3]},
                "last_seen": 1,
            }},
        ]
        top = await db.liluvine_pro_messages.aggregate(pipeline).to_list(100)
        total_screenshots = await db.liluvine_pro_messages.count_documents({
            "client_id": scope,
            "role": "user",
            "user_image_url": {"$ne": None, "$exists": True},
            "created_at": {"$gte": cutoff},
        })
        return {"items": top, "total_screenshots": total_screenshots, "days": days}

    # ----------------------------------------------------------
    # Bugfix (2026-02 — rabo.f case) — Diagnostic endpoint to
    # explain *why* Liluvine PRO is/isn't available for a given user
    # or phone number. Admin/sup/moderation only. No state mutation.
    # ----------------------------------------------------------
    @api.get("/admin/liluvine-pro/diagnose", tags=["Admin — Liluvine PRO"])
    async def admin_diagnose(
        email: Optional[str] = None,
        phone: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé admin/sup/modération")
        if not email and not phone:
            raise HTTPException(status_code=400, detail="Fournissez email OU phone.")
        target = None
        if email:
            target = await db.users.find_one({"email": email.lower().strip()}, {"_id": 0, "password_hash": 0})
        if not target and phone:
            digits = "".join(ch for ch in phone if ch.isdigit())
            # Try multiple normalized forms
            candidates = [phone.strip(), f"+{digits}", digits]
            target = await db.users.find_one({"phone": {"$in": candidates}}, {"_id": 0, "password_hash": 0})
        report = {
            "input": {"email": email, "phone": phone},
            "user_found": bool(target),
        }
        if not target:
            # Even if no user, the inbound WA flow may still trigger via auto-reply
            # against the global tenant. Diagnose that path too.
            report["wa_inbound_path"] = await _diagnose_wa_inbound(db, phone or "")
            report["contact_visibility"] = await _diagnose_contact_visibility(
                db, phone=phone or "", user=None,
            )
            return report
        # Resolve the tenant scope used by Liluvine for this user
        scope_uid = _client_scope(target)
        parent = await db.users.find_one({"id": scope_uid}, {"_id": 0, "email": 1, "full_name": 1, "role": 1, "features": 1}) or {}
        report["user"] = {
            "id": target.get("id"),
            "email": target.get("email"),
            "full_name": target.get("full_name"),
            "role": target.get("role"),
            "phone": target.get("phone"),
            "account_status": target.get("account_status"),
            "parent_client_id": target.get("parent_client_id"),
            "tracked_user_id": target.get("tracked_user_id"),
            "client_id_field": target.get("client_id"),
        }
        report["resolved_tenant_scope"] = {
            "scope_uid": scope_uid,
            "parent_email": parent.get("email"),
            "parent_role": parent.get("role"),
            "features": parent.get("features") or {},
            "ai_liluvine_pro_enabled": bool((parent.get("features") or {}).get("ai_liluvine_pro")),
        }
        # Also describe the inbound-WA path even when we know the user
        report["wa_inbound_path"] = await _diagnose_wa_inbound(db, target.get("phone") or phone or "")
        # Bug #3 (rabo.f) — diagnose why the contact name may be missing in
        # /portal/contacts. Pass the target user so the helper can flag
        # contacts that live outside their visible scope.
        report["contact_visibility"] = await _diagnose_contact_visibility(
            db, phone=target.get("phone") or phone or "", user=target,
        )
        # Hint
        if not report["resolved_tenant_scope"]["ai_liluvine_pro_enabled"]:
            report["hint"] = (
                f"Activez la feature 'ai_liluvine_pro' sur le compte "
                f"{parent.get('email')} (id={scope_uid}) via /admin/clients/{scope_uid}/features."
            )
        return report

    # ----------------------------------------------------------
    # Bugfix (2026-02 — bug #3 rabo.f) — Repair a user's directory contact.
    #
    # Cases handled :
    #   • No contact in user's scope → create one with full_name as name.
    #   • Contact exists but `name` is empty/phone-only → fill from full_name.
    #   • Duplicate contacts in other tenants → archive (set `archived_at`)
    #     to keep the canonical one in the user's scope.
    #   • Reattach orphan `whatsapp_messages` (contact_id=None) to the
    #     canonical contact and backfill `contact_name`.
    #   • Delete matching `wa_pending_imports` rows (the contact now exists).
    # ----------------------------------------------------------
    @api.post("/admin/contacts/repair-user-contact", tags=["Admin — Liluvine PRO"])
    async def admin_repair_user_contact(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_user),
    ):
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé admin/sup/modération")
        email = (payload.get("email") or "").lower().strip()
        user_id = (payload.get("user_id") or "").strip()
        dry_run = bool(payload.get("dry_run", False))
        if not email and not user_id:
            raise HTTPException(status_code=400, detail="Fournissez email ou user_id.")

        target = None
        if user_id:
            target = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
        if not target and email:
            target = await db.users.find_one({"email": email}, {"_id": 0, "password_hash": 0})
        if not target:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        phone_raw = (target.get("phone") or "").strip()
        digits = "".join(ch for ch in phone_raw if ch.isdigit())
        if not digits:
            raise HTTPException(
                status_code=400,
                detail=f"L'utilisateur {target.get('email')} n'a pas de numéro de téléphone.",
            )

        # Canonical scope = the user's parent tenant (admin/superviseur tenant
        # for tracked/moderation users, self for admin/superviseur themselves).
        canonical_scope = _client_scope(target)
        full_name = (target.get("full_name") or "").strip() or target.get("email") or "—"

        # Find ALL existing contacts matching this phone
        all_matches = await db.directory_contacts.find(
            {"$or": [{"whatsapp": {"$regex": digits}}, {"phone": {"$regex": digits}}]},
            {"_id": 0},
        ).to_list(50)

        report: Dict[str, Any] = {
            "target_user": {
                "id": target.get("id"),
                "email": target.get("email"),
                "full_name": target.get("full_name"),
                "phone": phone_raw,
                "phone_digits": digits,
                "role": target.get("role"),
            },
            "canonical_scope": canonical_scope,
            "matches_before": len(all_matches),
            "dry_run": dry_run,
            "actions": [],
        }

        # Pick (or create) the canonical contact in the canonical scope.
        canonical = next(
            (c for c in all_matches if c.get("client_id") == canonical_scope),
            None,
        )

        if canonical is None:
            # Create a new directory_contacts row in the canonical scope.
            new_doc = {
                "id": str(uuid.uuid4()),
                "client_id": canonical_scope,
                "owner_id": target.get("id"),
                "owner_label": full_name,
                "name": full_name,
                "phone": phone_raw,
                "whatsapp": phone_raw,
                "email": target.get("email"),
                "company": target.get("company"),
                "tags": ["utilisateur-système"],
                "shared": True,
                "wa_profile_name": (target.get("full_name") or "").strip() or None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            if not dry_run:
                await db.directory_contacts.insert_one(new_doc.copy())
            new_doc.pop("_id", None)
            canonical = new_doc
            report["actions"].append({
                "type": "created_canonical_contact",
                "client_id": canonical_scope,
                "contact_id": canonical["id"],
                "name": full_name,
            })
        else:
            # Fix name if it's blank or phone-only
            existing_name = (canonical.get("name") or "").strip()
            phone_only = bool(re.fullmatch(r"\+?\d[\d\s().-]*", existing_name)) if existing_name else False
            patch: Dict[str, Any] = {}
            if not existing_name or phone_only:
                patch["name"] = full_name
            # Always keep WA profile name in sync if we have a better one
            if (target.get("full_name") or "").strip() and not canonical.get("wa_profile_name"):
                patch["wa_profile_name"] = target["full_name"].strip()
            # Ensure phone/whatsapp/email are set if missing
            if not (canonical.get("phone") or "").strip():
                patch["phone"] = phone_raw
            if not (canonical.get("whatsapp") or "").strip():
                patch["whatsapp"] = phone_raw
            if not (canonical.get("email") or "").strip() and target.get("email"):
                patch["email"] = target.get("email")
            if patch:
                patch["updated_at"] = _now()
                if not dry_run:
                    await db.directory_contacts.update_one(
                        {"id": canonical["id"]}, {"$set": patch},
                    )
                report["actions"].append({
                    "type": "patched_canonical_contact",
                    "contact_id": canonical["id"],
                    "patch": patch,
                })

        # Archive (or delete) duplicates in OTHER tenants.
        for c in all_matches:
            if c.get("id") == canonical["id"]:
                continue
            if c.get("client_id") == canonical_scope:
                # Same scope dup → keep the canonical, archive this one
                if not dry_run:
                    await db.directory_contacts.update_one(
                        {"id": c["id"]},
                        {"$set": {
                            "archived_at": _now(),
                            "archived_reason": f"merged into {canonical['id']} by repair-user-contact",
                        }},
                    )
                report["actions"].append({
                    "type": "archived_same_scope_duplicate",
                    "contact_id": c["id"],
                })
            else:
                # Cross-tenant duplicate — flag but don't delete (RGPD)
                if not dry_run:
                    await db.directory_contacts.update_one(
                        {"id": c["id"]},
                        {"$set": {
                            "wa_user_link": target.get("id"),
                            "wa_user_link_canonical": canonical["id"],
                        }},
                    )
                report["actions"].append({
                    "type": "flagged_cross_tenant_duplicate",
                    "contact_id": c["id"],
                    "client_id": c.get("client_id"),
                })

        # Reattach orphan whatsapp_messages (contact_id=null) to canonical
        if not dry_run:
            res = await db.whatsapp_messages.update_many(
                {
                    "phone_digits": digits,
                    "direction": "inbound",
                    "$or": [{"contact_id": None}, {"contact_id": {"$exists": False}}],
                },
                {"$set": {"contact_id": canonical["id"], "contact_name": full_name}},
            )
            report["actions"].append({
                "type": "reattached_orphan_inbound_messages",
                "matched": res.matched_count,
                "modified": res.modified_count,
            })
            # Also re-tag messages that point to the now-archived duplicates
            res2 = await db.whatsapp_messages.update_many(
                {
                    "phone_digits": digits,
                    "client_id": canonical_scope,
                    "contact_id": {"$ne": canonical["id"]},
                },
                {"$set": {"contact_id": canonical["id"], "contact_name": full_name}},
            )
            report["actions"].append({
                "type": "retagged_misrouted_messages",
                "matched": res2.matched_count,
                "modified": res2.modified_count,
            })
        else:
            report["actions"].append({"type": "skipped_message_reattach_due_to_dry_run"})

        # Clean wa_pending_imports for this phone (contact now exists)
        if not dry_run:
            res3 = await db.wa_pending_imports.delete_many({"phone_digits": digits})
            report["actions"].append({
                "type": "deleted_wa_pending_imports",
                "count": res3.deleted_count,
            })

        # Sync the Liluvine session label too (cosmetic improvement)
        session_id = f"wa:{canonical_scope}:{digits}"
        if not dry_run:
            res4 = await db.liluvine_pro_sessions.update_one(
                {"id": session_id},
                {"$set": {"user_label": full_name, "updated_at": _now()}},
            )
            report["actions"].append({
                "type": "patched_liluvine_session_label",
                "session_id": session_id,
                "matched": res4.matched_count,
                "modified": res4.modified_count,
            })

        report["canonical_contact_id"] = canonical["id"]
        report["canonical_contact_name"] = full_name
        return report

    # ----------------------------------------------------------
    # Bypass list (2026-02) — Admin endpoints to manage the
    # `settings.liluvine_pro_bypass_emails` list. Emails in this list get
    # Liluvine PRO access (web chat + WA auto-reply) even when their
    # parent tenant's `ai_liluvine_pro` feature is OFF.
    # ----------------------------------------------------------
    @api.get("/admin/liluvine-pro/bypass-emails", tags=["Admin — Liluvine PRO"])
    async def admin_get_bypass_emails(user: dict = Depends(get_current_user)):
        if (user.get("role") or "") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_pro_bypass_emails": 1}) or {}
        raw = s.get("liluvine_pro_bypass_emails") or ""
        emails = sorted(_parse_bypass_emails(raw))
        return {"emails": emails, "count": len(emails)}

    class _BypassPayload(BaseModel):
        emails: List[str] = Field(default_factory=list)

    @api.patch("/admin/liluvine-pro/bypass-emails", tags=["Admin — Liluvine PRO"])
    async def admin_patch_bypass_emails(
        payload: BypassPayload, user: dict = Depends(get_current_user)
    ):
        if (user.get("role") or "") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        cleaned = sorted({(e or "").strip().lower() for e in payload.emails if (e or "").strip()})
        # Quick sanity : reject obvious non-emails (we don't try to RFC-validate).
        bad = [e for e in cleaned if "@" not in e or "." not in e.split("@")[-1]]
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"Emails invalides : {', '.join(bad[:5])}",
            )
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"liluvine_pro_bypass_emails": cleaned, "updated_at": _now()}},
            upsert=True,
        )
        return {"ok": True, "emails": cleaned, "count": len(cleaned)}

    # ----------------------------------------------------------
    # Cross-tenant contact search & import (2026-02).
    #
    # Use case : in production, a user's contact card may end up in the
    # wrong tenant scope (legacy migration, cross-tenant pollution…). The
    # user opens /portal/contacts, doesn't see the contact, and has no way
    # to recover it. These endpoints let them :
    #
    #   1. SEARCH a phone number across ALL tenants (admin-level look-up).
    #      Returns a sanitized contact card (no tenant identifier leaked).
    #   2. IMPORT that contact into their OWN tenant scope as a fresh row.
    #      Only the card is copied by default (RGPD-safe). Admin/superviseur
    #      may additionally copy the WhatsApp message history.
    # ----------------------------------------------------------
    class _CrossTenantImportPayload(BaseModel):
        phone: str = Field(..., min_length=4, max_length=32)
        include_messages: bool = False

    @api.get("/me/contacts/search-cross-tenant", tags=["Portail Client"])
    async def search_cross_tenant_contacts(
        phone: str,
        user: dict = Depends(get_current_user),
    ):
        """Recherche un numéro de téléphone à travers TOUS les tenants. Renvoie une fiche
        contact cards (name, phone, whatsapp, email, company, tags only —
        no client_id, owner_id, internal flags). Available to every
        authenticated user (the leak risk is bounded : caller must already
        know the phone number)."""
        digits = "".join(ch for ch in (phone or "") if ch.isdigit())
        if len(digits) < 4:
            raise HTTPException(status_code=400, detail="Numéro trop court (min 4 chiffres).")
        results: List[Dict[str, Any]] = []
        async for c in db.directory_contacts.find(
            {"$or": [{"whatsapp": {"$regex": digits}}, {"phone": {"$regex": digits}}]},
            {
                "_id": 0, "id": 1, "name": 1, "phone": 1, "whatsapp": 1,
                "email": 1, "company": 1, "tags": 1, "wa_profile_name": 1,
                "archived_at": 1, "created_at": 1, "client_id": 1,
            },
        ):
            if c.get("archived_at"):
                continue
            results.append(c)

        # Compute the caller's visible scope so the UI can flag rows that
        # already live in the caller's tenant (= no need to re-import).
        visible_ids: set = set()
        for k in ("client_id", "parent_client_id", "id"):
            v = user.get(k)
            if v:
                visible_ids.add(v)
        company = (user.get("company") or "").strip()
        if company:
            async for u in db.users.find(
                {"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}},
                {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1},
            ):
                for k in ("id", "client_id", "parent_client_id"):
                    v = u.get(k)
                    if v:
                        visible_ids.add(v)

        # Sanitize : strip tenant ids before returning. Just keep an
        # `in_current_scope` flag so the UI can disable the import button.
        sanitized: List[Dict[str, Any]] = []
        for c in results:
            in_scope = c.get("client_id") in visible_ids
            sanitized.append({
                "id": c.get("id"),
                "name": c.get("name") or "",
                "wa_profile_name": c.get("wa_profile_name") or "",
                "phone": c.get("phone") or "",
                "whatsapp": c.get("whatsapp") or "",
                "email": c.get("email") or "",
                "company": c.get("company") or "",
                "tags": c.get("tags") or [],
                "in_current_scope": in_scope,
                "created_at": c.get("created_at"),
            })
        return {
            "items": sanitized,
            "count": len(sanitized),
            "phone_digits": digits,
        }

    @api.post("/me/contacts/import-cross-tenant", tags=["Portail Client"])
    async def import_cross_tenant_contact(
        payload: CrossTenantImportPayload,
        user: dict = Depends(get_current_user),
    ):
        """Crée un contact dans le scope du tenant de l'appelant depuis n'importe quel
        matching cross-tenant record. By default only the contact card
        is copied. Admin/superviseur may set `include_messages=True` to
        also pull the WhatsApp history (RGPD-controlled)."""
        digits = "".join(ch for ch in (payload.phone or "") if ch.isdigit())
        if len(digits) < 4:
            raise HTTPException(status_code=400, detail="Numéro trop court.")
        # Pick the most complete cross-tenant match (prefer rows with a
        # non-blank `name`, fallback to most recent).
        candidates: List[Dict[str, Any]] = []
        async for c in db.directory_contacts.find(
            {
                "$or": [{"whatsapp": {"$regex": digits}}, {"phone": {"$regex": digits}}],
                "archived_at": {"$in": [None, ""]},
            },
            {"_id": 0},
        ):
            candidates.append(c)
        if not candidates:
            raise HTTPException(status_code=404, detail="Aucune fiche contact trouvée pour ce numéro.")
        def _score(c: Dict[str, Any]) -> tuple:
            name = (c.get("name") or "").strip()
            has_name = 1 if (name and not re.fullmatch(r"\+?\d[\d\s().-]*", name)) else 0
            return (has_name, c.get("created_at") or "")
        candidates.sort(key=_score, reverse=True)
        src = candidates[0]

        # Caller's canonical scope
        caller_scope = (
            user.get("client_id") or user.get("parent_client_id") or user["id"]
        )

        # Anti-duplicate : if the caller's scope already has a non-archived
        # contact for this phone, return it instead of creating a duplicate.
        existing = await db.directory_contacts.find_one(
            {
                "client_id": caller_scope,
                "$or": [{"whatsapp": {"$regex": digits}}, {"phone": {"$regex": digits}}],
                "archived_at": {"$in": [None, ""]},
            },
            {"_id": 0},
        )
        include_messages = bool(payload.include_messages)
        allow_messages = (user.get("role") or "") in ("admin", "superviseur")
        if include_messages and not allow_messages:
            raise HTTPException(
                status_code=403,
                detail="Seuls admin et superviseur peuvent importer l'historique des messages.",
            )

        if existing:
            doc = existing
            created = False
        else:
            doc = {
                "id": str(uuid.uuid4()),
                "client_id": caller_scope,
                "owner_id": user.get("id"),
                "owner_label": user.get("full_name") or user.get("email"),
                "name": (src.get("name") or src.get("wa_profile_name") or f"+{digits}").strip(),
                "phone": src.get("phone") or f"+{digits}",
                "whatsapp": src.get("whatsapp") or src.get("phone") or f"+{digits}",
                "email": src.get("email"),
                "company": src.get("company"),
                "tags": list(src.get("tags") or ["importé-cross-tenant"]),
                "wa_profile_name": src.get("wa_profile_name"),
                "shared": True,
                "imported_from_contact_id": src.get("id"),
                "created_at": _now(),
                "updated_at": _now(),
            }
            await db.directory_contacts.insert_one(doc.copy())
            doc.pop("_id", None)
            created = True

        msg_copied = 0
        if include_messages and allow_messages:
            # Copy inbound WhatsApp messages (caller_scope only sees its own scope).
            # We re-write client_id & contact_id to keep the data consistent.
            async for m in db.whatsapp_messages.find(
                {"phone_digits": digits, "client_id": src.get("client_id")},
                {"_id": 0},
            ):
                m["id"] = str(uuid.uuid4())
                m["client_id"] = caller_scope
                m["contact_id"] = doc["id"]
                m["contact_name"] = doc["name"]
                m["imported_at"] = _now()
                m["imported_from_client_id"] = src.get("client_id")
                await db.whatsapp_messages.insert_one(m)
                msg_copied += 1

        return {
            "ok": True,
            "created": created,
            "contact": {
                "id": doc.get("id"),
                "name": doc.get("name"),
                "phone": doc.get("phone"),
                "whatsapp": doc.get("whatsapp"),
                "email": doc.get("email"),
                "company": doc.get("company"),
            },
            "messages_imported": msg_copied,
            "include_messages_requested": include_messages,
            "include_messages_allowed": allow_messages,
        }

    # ----------------------------------------------------------
    # #2 (2026-02 — suite #1) — Generate documentation draft from a SAWALI
    # screen's real customer questions. Uses Claude (via emergentintegrations)
    # to summarize all questions clients asked about this exact screen, and
    # produce a clean Markdown step-by-step guide.
    # ----------------------------------------------------------
    @api.post("/admin/liluvine-pro/generate-doc-draft", tags=["Admin — Liluvine PRO"])
    async def admin_generate_doc_draft(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_user),
    ):
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé admin/sup/modération")
        image_url = (payload.get("image_url") or "").strip()
        title = (payload.get("title") or "").strip() or "Écran SAWALI"
        days = int(payload.get("days") or 30)
        if not image_url:
            raise HTTPException(status_code=400, detail="image_url requis.")
        chk = await _pre_check(user, LILUVINE_MODEL)
        if not chk.get("allowed"):
            raise HTTPException(status_code=429, detail=chk.get("reason") or "Quota IA atteint.")
        scope = _client_scope(user)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
        # Find all client questions about this exact screen
        cursor = db.liluvine_pro_messages.find(
            {
                "client_id": scope,
                "role": "user",
                "matched_images.image_url": image_url,
                "created_at": {"$gte": cutoff},
            },
            {"_id": 0, "content": 1, "image_analysis": 1, "created_at": 1},
        ).sort("created_at", -1)
        rows = await cursor.to_list(30)
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"Aucune question client trouvée pour cet écran sur les {days} derniers jours.",
            )
        # Build the prompt
        questions_block = []
        for i, r in enumerate(rows, start=1):
            text = (r.get("content") or "").strip()
            ana = r.get("image_analysis") or {}
            ocr = (ana.get("ocr_text") or "").strip()[:300]
            summary = (ana.get("visual_summary") or "").strip()[:200]
            line = f"\n### Question #{i}\n"
            if text and text != "📸 Capture d'écran envoyée":
                line += f"**Texte du client** : {text[:400]}\n"
            if summary:
                line += f"**Description visuelle (Vision)** : {summary}\n"
            if ocr:
                line += f"**Texte visible (OCR)** : {ocr}\n"
            questions_block.append(line)
        prompt = (
            f"Je veux que tu génères un article de documentation Markdown propre, structuré et "
            f"pédagogique pour l'écran SAWALI suivant :\n\n"
            f"**Titre de l'écran** : {title}\n\n"
            f"Tu as accès à {len(rows)} VRAIES questions clients reçues ces {days} derniers "
            f"jours qui concernent cet écran (extraites automatiquement par Claude Vision + Qdrant). "
            f"Voici ces questions :\n"
            + "".join(questions_block) +
            "\n\n---\n\n"
            "À partir de ces vraies questions, génère un article de documentation Markdown qui :\n"
            "1. Commence par un **titre H1** clair et un **paragraphe d'introduction** (1-2 phrases) "
            "qui explique à quoi sert l'écran.\n"
            "2. Contient une section **« Procédure pas-à-pas »** numérotée (étapes 1, 2, 3…).\n"
            "3. Contient une section **« Questions fréquentes »** sous forme de FAQ Markdown, en "
            "regroupant les questions clients similaires et en y répondant clairement.\n"
            "4. Termine par une section **« En cas de problème »** avec 2-3 conseils de dépannage.\n"
            "5. Reste en **FRANÇAIS** et utilise un ton professionnel mais accessible.\n"
            "6. Ne mentionne pas les questions individuelles brutes — synthétise.\n\n"
            "Renvoie UNIQUEMENT le Markdown, sans phrase d'introduction."
        )
        try:
            llm = await _llm_send(
                f"docgen-{scope}-{uuid.uuid4().hex[:6]}",
                "Tu es un rédacteur technique expert en documentation logicielle SAWALI. Tu écris en français.",
                prompt,
            )
        except Exception as exc:
            logger.exception("[doc-draft] LLM failure")
            raise HTTPException(status_code=502, detail=f"Claude indisponible : {str(exc)[:160]}") from exc
        track_result = await _track(
            user, llm["tokens"], llm["model"],
            metadata={"feature": "doc_draft", "image_url": image_url, "questions_used": len(rows)},
        )
        return {
            "ok": True,
            "markdown": llm["reply"] or "",
            "questions_used": len(rows),
            "model": llm["model"],
            "tokens": llm["tokens"],
            "image_url": image_url,
            "title": title,
            "warn": track_result.get("warn", False),
        }

    # ----------------------------------------------------------
    # #2bis (2026-02) — Coverage gaps : list client questions sent with a
    # screenshot but for which Qdrant returned NO match (or weak matches).
    # These are the "blind spots" of the knowledge base.
    # ----------------------------------------------------------
    @api.get("/admin/liluvine-pro/coverage-gaps", tags=["Admin — Liluvine PRO"])
    async def admin_coverage_gaps(
        days: int = 30,
        min_score: float = 0.5,
        limit: int = 50,
        user: dict = Depends(get_current_user),
    ):
        """Renvoie les messages image utilisateur dont le meilleur match Qdrant est sous
        `min_score` (or no matches at all). These are gaps in the KB:
        clients asked about something the KB doesn't cover. Each entry
        keeps the client image, the Vision analysis, and the user's text
        — perfect input to enrich Qdrant via the admin UI."""
        if not _can_takeover(user):
            raise HTTPException(status_code=403, detail="Réservé admin/sup/modération")
        scope = _client_scope(user)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
        cursor = db.liluvine_pro_messages.find(
            {
                "client_id": scope,
                "role": "user",
                "user_image_url": {"$ne": None, "$exists": True},
                "created_at": {"$gte": cutoff},
            },
            {"_id": 0},
        ).sort("created_at", -1)
        all_user_msgs = await cursor.to_list(500)
        gaps = []
        for m in all_user_msgs:
            matches = m.get("matched_images") or []
            if not matches:
                gap_reason = "no_match"
                top_score = 0.0
            else:
                top_score = max(float(x.get("score") or 0.0) for x in matches)
                if top_score >= min_score:
                    continue
                gap_reason = "low_score"
            gaps.append({
                "id": m.get("id"),
                "session_id": m.get("session_id"),
                "user_image_url": m.get("user_image_url"),
                "content": m.get("content") or "",
                "image_analysis": m.get("image_analysis") or {},
                "top_score": round(top_score, 3),
                "gap_reason": gap_reason,
                "created_at": m.get("created_at"),
            })
            if len(gaps) >= min(max(limit, 1), 200):
                break
        # Compute KB blindspot rate as denominator info
        total_screenshots = len(all_user_msgs)
        return {
            "items": gaps,
            "total_screenshots": total_screenshots,
            "gaps_count": len(gaps),
            "blindspot_rate": round((len(gaps) / total_screenshots) if total_screenshots else 0.0, 3),
            "days": days,
            "min_score": min_score,
        }
