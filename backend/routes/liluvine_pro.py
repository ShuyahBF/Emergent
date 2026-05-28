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

import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.liluvine_pro")

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
    Returns a single concatenated snippet or empty string."""
    scope = _client_scope(user)
    t = (text or "").lower()
    snippets: List[str] = []

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

    # Pattern → fetcher mapping. Multiple patterns may fire and all snippets are appended.
    if re.search(r"\b(contact|client|annuaire)s?\b", t):
        snippets.append(await _list_contacts())
    if re.search(r"\b(ticket|intervention|incident|demande)s?\b", t):
        snippets.append(await _list_tickets())
    if re.search(r"\b(paiement|payment|encaissement|pawapay|mobile.{0,3}money|stripe)s?\b", t):
        snippets.append(await _list_payments())
    if re.search(r"\b(rdv|rendez.vous|appointment|réunion|reunion|meeting)s?\b", t):
        snippets.append(await _list_appointments())
    if re.search(r"\b(note|rapport|suivi|compte.rendu|résumé|resume)s?\b", t):
        snippets.append(await _list_notes())

    if not snippets:
        return ""
    return "\n\n--- CONTEXTE DB ---\n" + "\n\n".join(snippets) + "\n--- FIN CONTEXTE ---"


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

    async def _llm_send(session_id: str, system_text: str, user_text: str) -> Dict[str, Any]:
        """Spin a fresh LlmChat instance, send the message, return reply + token estimate."""
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
        ).with_model("anthropic", "claude-sonnet-4-6")
        reply = await chat.send_message(UserMessage(text=user_text))
        # Token estimation : ~4 chars per token. Used for quota accounting.
        tokens = max(int((len(system_text) + len(user_text) + len(reply or "")) / 4), 1)
        return {"reply": reply or "", "tokens": tokens, "model": "claude-sonnet-4-6"}

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
        }

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
        system_text = SYSTEM_MESSAGE + (("\n" + ctx) if ctx else "")
        try:
            llm = await _llm_send(sid, system_text, text)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[liluvine-pro-inbound] LLM failure")
            raise HTTPException(status_code=502, detail=f"LLM indisponible : {str(exc)[:160]}") from exc
        msg_id = secrets.token_urlsafe(12)
        await db.liluvine_pro_messages.insert_one({
            "id": msg_id, "session_id": sid, "client_id": client_id,
            "user_id": user_doc["id"], "role": "assistant", "content": llm["reply"],
            "tokens": llm["tokens"], "model": llm["model"],
            "context_injected": bool(ctx), "external_source": source,
            "created_at": _now(),
        })
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
        system_text = SYSTEM_MESSAGE + (("\n" + ctx) if ctx else "")
        # Call the LLM (the LlmChat library handles multi-turn history via session_id
        # internally, but ours is keyed by sid which guarantees per-conversation memory)
        try:
            llm = await _llm_send(sid, system_text, payload.text)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[liluvine-pro] LLM failure")
            raise HTTPException(status_code=502, detail=f"Liluvine indisponible : {str(exc)[:160]}") from exc
        # Persist the assistant reply
        msg_id = secrets.token_urlsafe(12)
        await db.liluvine_pro_messages.insert_one({
            "id": msg_id,
            "session_id": sid,
            "client_id": scope,
            "user_id": user["id"],
            "role": "assistant",
            "content": llm["reply"],
            "tokens": llm["tokens"],
            "model": llm["model"],
            "context_injected": bool(ctx),
            "created_at": _now(),
        })
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
            "reply": llm["reply"],
            "tokens": llm["tokens"],
            "model": llm["model"],
            "context_injected": bool(ctx),
            "warn": track_result.get("warn", False),
        }

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
