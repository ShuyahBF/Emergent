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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
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
- Tu peux expliquer les fonctionnalités du CRM (Caisse, Facturation, GRH, Tickets, etc.)."""


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


# ============================================================
# Helpers
# ============================================================
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_scope(user: dict) -> str:
    """Tenant scope = parent admin id for tracked users, self for admins."""
    if user.get("role") in ("admin", "superviseur"):
        return user["id"]
    return user.get("tracked_user_id") or user.get("client_id") or user["id"]


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
def setup_liluvine_pro_routes(*, db, api, get_current_user):
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
        reply = await chat.send_message(UserMessage(text=user_text))
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
        for it in items:
            sess = sess_by_id.get(it.get("session_id")) or {}
            it["contact_label"] = sess.get("user_label") or "Contact WhatsApp"
            it["phone_digits"] = ((sess.get("external_payload") or {}).get("phone_digits")) or ""
            # Truncate content for the toast bubble
            if len(it.get("content") or "") > 140:
                it["content_preview"] = it["content"][:140] + "…"
            else:
                it["content_preview"] = it["content"]
        return {
            "items": items,
            "server_now": _now(),
            "count": len(items),
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
        try:
            from routes.liluvine_kb import build_kb_context
            kb = await build_kb_context(db)
        except Exception:
            kb = ""
        system_text = (await _resolve_system_prompt(client_id)) + (("\n" + ctx) if ctx else "") + (("\n\n" + kb) if kb else "")
        # Iter38r-fix9o (Item 1) — Keyword pre-check for explicit human-handoff requests
        _user_lower = text.lower()
        _escalate_pre = any(k in _user_lower for k in ESCALATION_KEYWORDS)
        try:
            llm = await _llm_send(sid, system_text, text)
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
        # Iter38r-fix7 — Feature gate: tenant must have ai_liluvine_pro enabled.
        # Resolve to the parent admin and inspect their features field.
        scope_uid = _client_scope(user)
        parent = await db.users.find_one({"id": scope_uid}, {"_id": 0, "features": 1})
        feats = (parent or {}).get("features") or {}
        if not feats.get("ai_liluvine_pro"):
            raise HTTPException(
                status_code=403,
                detail="Liluvine PRO n'est pas activé pour votre compte. Contactez votre administrateur.",
            )
        chk = await _pre_check(user, "claude-sonnet-4-6")
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
        try:
            from routes.liluvine_kb import build_kb_context
            kb = await build_kb_context(db)
        except Exception:
            kb = ""
        system_text = (await _resolve_system_prompt(scope)) + (("\n" + ctx) if ctx else "") + (("\n\n" + kb) if kb else "")
        # Iter38r-fix9o (Item 1) — Keyword pre-check
        _escalate_pre = any(k in payload.text.lower() for k in ESCALATION_KEYWORDS)
        # Call the LLM (the LlmChat library handles multi-turn history via session_id
        # internally, but ours is keyed by sid which guarantees per-conversation memory)
        try:
            llm = await _llm_send(sid, system_text, payload.text)
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
        scope_uid = _client_scope(user)
        parent = await db.users.find_one({"id": scope_uid}, {"_id": 0, "features": 1})
        feats = (parent or {}).get("features") or {}
        if not feats.get("ai_liluvine_pro"):
            raise HTTPException(status_code=403, detail="Liluvine PRO n'est pas activé pour votre compte.")
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
                kb_task = _resolve_kb_context()
                sys_task = _resolve_system_prompt(scope)
                ctx, kb, base_sys = await asyncio.gather(ctx_task, kb_task, sys_task)
                system_text = base_sys + (("\n" + ctx) if ctx else "") + (("\n\n" + kb) if kb else "")
                _escalate_pre = any(k in payload.text.lower() for k in ESCALATION_KEYWORDS)
                # Notify the client we're now waiting on the LLM
                yield f"event: status\ndata: {json.dumps({'phase': 'llm'})}\n\n"
                llm = await _llm_send(sid, system_text, payload.text)
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

    async def _resolve_kb_context() -> str:
        try:
            from routes.liluvine_kb import build_kb_context
            return await build_kb_context(db)
        except Exception:
            return ""


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
    # Iter38r-fix9i — "Reprendre la conversation" : human takeover
    # ----------------------------------------------------------
    # Allowed to: admin / superviseur / moderateur (and tracked users with
    # an elevated "tracked_role"). Marks a Liluvine session as "owned by a
    # human now" so the WhatsApp auto-reply skips it. Auto-expires after
    # `duration_minutes` (default 120).
    _TAKEOVER_ROLES = {"admin", "superviseur", "moderateur"}

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
        try:
            duration_minutes = max(5, min(int(payload.get("duration_minutes") or 120), 7 * 24 * 60))
        except Exception:
            duration_minutes = 120
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
