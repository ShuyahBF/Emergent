"""Iter38r-fix9a — Liluvine PRO native WhatsApp auto-reply.

Hooked into the WhatsApp Meta webhook (`/api/whatsapp/webhook`). When a new
inbound TEXT message lands, this helper decides whether Liluvine PRO should
answer it automatically (no n8n required) — and if so, generates a reply via
Claude Sonnet (with the same keyword-RAG injection as the chat UI) and pushes
it back via Meta Graph API.

Decision rules (admin-configurable in settings) :
  - Global toggle  : `liluvine_wa_autoreply_enabled` (bool, default False)
  - Allow-list     : `liluvine_wa_autoreply_allow_phones` (list of msisdn digits)
  - Deny-list      : `liluvine_wa_autoreply_deny_phones` (list of msisdn digits)
  - Allow-mode     : `liluvine_wa_autoreply_allow_mode` (`any` | `whitelist`)
  - Schedule       : `liluvine_wa_autoreply_schedule`  ∈
                       `always` | `outside_hours` | `business_hours`
  - Keywords       : `liluvine_wa_autoreply_keywords` (list of triggers; empty=any)
  - Anti-flood     : `liluvine_wa_autoreply_cooldown_seconds` (default 60s)
  - Signature      : `liluvine_wa_autoreply_signature`
                     (default "🤖 Réponse automatique Liluvine PRO")

Anti-flood works per-(client_id, phone_digits) — we store the last reply time
in `liluvine_wa_autoreply_state`.

Every outgoing auto-reply is logged in `liluvine_pro_messages` with
`external_source = "whatsapp_native"` so it appears in the audit history.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.liluvine_wa_autoreply")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _norm_keywords(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        return [p.strip().lower() for p in raw.split(",") if p.strip()]
    return []


def _norm_phones(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [_digits(x) for x in raw if _digits(x)]
    if isinstance(raw, str):
        return [_digits(p) for p in raw.split(",") if _digits(p)]
    return []


def _hour_in_range(now_h: int, open_h: int, close_h: int) -> bool:
    """Inclusive open / exclusive close. Wraps over midnight if needed."""
    if open_h <= close_h:
        return open_h <= now_h < close_h
    return now_h >= open_h or now_h < close_h  # wraps midnight


async def should_autoreply(
    db, *, settings: Dict[str, Any], phone_digits: str, text: str, contact: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Return {"ok": bool, "reason": str}. Inspects all rules without sending."""
    if not bool(settings.get("liluvine_wa_autoreply_enabled")):
        return {"ok": False, "reason": "disabled"}
    if not (text or "").strip():
        return {"ok": False, "reason": "empty_text"}
    # Allow / deny
    allow_list = _norm_phones(settings.get("liluvine_wa_autoreply_allow_phones"))
    deny_list = _norm_phones(settings.get("liluvine_wa_autoreply_deny_phones"))
    mode = (settings.get("liluvine_wa_autoreply_allow_mode") or "any").lower()
    if phone_digits in deny_list:
        return {"ok": False, "reason": "denylisted"}
    if mode == "whitelist" and allow_list and phone_digits not in allow_list:
        return {"ok": False, "reason": "not_whitelisted"}
    # Schedule
    schedule = (settings.get("liluvine_wa_autoreply_schedule") or "always").lower()
    if schedule in ("outside_hours", "business_hours"):
        try:
            open_h = int(str(settings.get("business_open_time") or "09:00").split(":", 1)[0])
            close_h = int(str(settings.get("business_close_time") or "18:00").split(":", 1)[0])
            now_h = datetime.now(timezone.utc).hour
            in_hours = _hour_in_range(now_h, open_h, close_h)
            if schedule == "business_hours" and not in_hours:
                return {"ok": False, "reason": "outside_business_hours"}
            if schedule == "outside_hours" and in_hours:
                return {"ok": False, "reason": "inside_business_hours"}
        except Exception:
            pass
    # Keywords
    keywords = _norm_keywords(settings.get("liluvine_wa_autoreply_keywords"))
    if keywords:
        low = text.lower()
        if not any(k in low for k in keywords):
            return {"ok": False, "reason": "no_keyword_match"}
    # Anti-flood
    try:
        cooldown = max(0, int(settings.get("liluvine_wa_autoreply_cooldown_seconds") or 60))
    except Exception:
        cooldown = 60
    if cooldown > 0:
        state = await db.liluvine_wa_autoreply_state.find_one(
            {"phone_digits": phone_digits}, {"_id": 0, "last_replied_at": 1}
        )
        if state and state.get("last_replied_at"):
            try:
                last = datetime.fromisoformat(state["last_replied_at"].replace("Z", "+00:00"))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                delta = (datetime.now(timezone.utc) - last).total_seconds()
                if delta < cooldown:
                    return {"ok": False, "reason": f"cooldown ({int(cooldown - delta)}s left)"}
            except Exception:
                pass
    return {"ok": True, "reason": "matched"}


async def autoreply_to_inbound(
    db,
    *,
    inbound_doc: Dict[str, Any],
    contact: Optional[Dict[str, Any]],
    settings_doc: Dict[str, Any],
    wa_send_text,  # callable(to_e164, text, reply_to_message_id=None)
) -> Dict[str, Any]:
    """Top-level entrypoint called from the webhook handler. Decides + sends.

    Args:
      inbound_doc: the freshly-inserted whatsapp_messages doc (must have
                   `from`, `phone_digits`, `body`, `wa_message_id`, `client_id`).
      contact:     the matched directory_contacts row (or None).
      settings_doc: the cached `settings` doc.
      wa_send_text: a coroutine to send a text WA message.

    Returns a status dict (logged into wa_webhook_logs as `autoreply`).
    """
    phone_digits = inbound_doc.get("phone_digits") or _digits(inbound_doc.get("from", ""))
    text = (inbound_doc.get("body") or "").strip()
    if (inbound_doc.get("message_type") or "text") != "text":
        return {"ok": False, "reason": "non_text_message"}
    # Skip if the message is a Liluvine remote command (! / / prefix already handled)
    if text.startswith("!") or text.startswith("/"):
        return {"ok": False, "reason": "command_prefix"}

    decision = await should_autoreply(
        db, settings=settings_doc, phone_digits=phone_digits, text=text, contact=contact
    )
    if not decision["ok"]:
        return decision

    # Iter38r-fix9i — "Reprendre la conversation" : if a human has taken
    # over this WA session, skip auto-reply until the takeover expires (or
    # is manually released).
    scope_uid_pre = inbound_doc.get("client_id")
    if scope_uid_pre:
        session_id_pre = f"wa:{scope_uid_pre}:{phone_digits}"
        existing = await db.liluvine_pro_sessions.find_one(
            {"id": session_id_pre},
            {"_id": 0, "human_takeover": 1, "human_takeover_until": 1},
        )
        if existing and existing.get("human_takeover"):
            until = existing.get("human_takeover_until")
            still_active = True
            if until:
                try:
                    until_dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
                    if until_dt.tzinfo is None:
                        until_dt = until_dt.replace(tzinfo=timezone.utc)
                    still_active = datetime.now(timezone.utc) < until_dt
                except Exception:
                    still_active = True
            if still_active:
                return {"ok": False, "reason": "human_takeover_active"}

    # Tenant feature gate — only if Liluvine PRO is enabled on the parent admin
    # OR the inbound number is matched to a user whose email is in the bypass list.
    scope_uid = inbound_doc.get("client_id")
    if scope_uid:
        parent = await db.users.find_one({"id": scope_uid}, {"_id": 0, "features": 1})
        feats = (parent or {}).get("features") or {}
        if not feats.get("ai_liluvine_pro"):
            # Bypass check : settings.liluvine_pro_bypass_emails may grant
            # access to specific user emails matched via their phone number.
            settings_doc_local = await db.settings.find_one({"_id": "global"}) or {}
            bypass_raw = settings_doc_local.get("liluvine_pro_bypass_emails") or ""
            bypass = set()
            if isinstance(bypass_raw, list):
                bypass = {str(x).strip().lower() for x in bypass_raw if str(x).strip()}
            else:
                bypass = {p.strip().lower() for p in re.split(r"[\s,;]+", str(bypass_raw)) if p.strip()}
            phone_user = None
            if phone_digits and bypass:
                phone_user = await db.users.find_one(
                    {"phone": {"$regex": phone_digits}},
                    {"_id": 0, "email": 1},
                )
            sender_email = ((phone_user or {}).get("email") or "").lower().strip()
            if not (sender_email and sender_email in bypass):
                return {"ok": False, "reason": "liluvine_pro_not_enabled"}

    # Build the LLM context (reuse the same RAG helper as the chat UI)
    try:
        from routes.liluvine_pro import _fetch_context_snippets, SYSTEM_MESSAGE
    except Exception as exc:
        logger.warning("[wa_autoreply] could not import liluvine helpers: %s", exc)
        return {"ok": False, "reason": f"liluvine_import_failed: {exc!r}"}

    # The "user" for context scoping = the parent admin (so the assistant
    # sees their tenant's data exactly like the dashboard does).
    if not scope_uid:
        return {"ok": False, "reason": "no_tenant_scope"}
    user_doc = await db.users.find_one({"id": scope_uid}, {"_id": 0})
    if not user_doc:
        return {"ok": False, "reason": "tenant_user_not_found"}

    ctx = await _fetch_context_snippets(db, user_doc, text)
    # Iter40 (2026-02) — Business RAG : queries on RDV/Tickets/HR/Caisse…
    # Filtré par ACL (liste blanche par module/numéro).
    try:
        from routes.liluvine_business_rag import build_business_rag_context
        biz_ctx = await build_business_rag_context(db, phone_digits=phone_digits, query=text)
    except Exception:  # noqa: BLE001
        biz_ctx = ""
    # Iter38r-fix9c — Also inject the Knowledge Base for WhatsApp auto-reply
    try:
        from routes.liluvine_kb import build_kb_context
        kb = await build_kb_context(db, max_chars=4000, query=text)  # smaller budget for WA
    except Exception:
        kb = ""
    contact_tag = ""
    if contact and contact.get("name"):
        contact_tag = f"\n\nContact qui écrit : {contact['name']} ({contact.get('code') or phone_digits})"
    sys_text = (
        SYSTEM_MESSAGE
        + "\n\n[IMPORTANT — Mode auto-réponse WhatsApp]\n"
        "Tu réponds à un message reçu sur WhatsApp. Sois courtois et concis (3-4 phrases max). "
        "Ne réponds JAMAIS comme un humain — tu es Liluvine PRO, l'assistant SAWALI. "
        "Si la question dépasse tes capacités, dis-lui qu'un agent humain va le recontacter rapidement."
        + (("\n" + ctx) if ctx else "")
        + (("\n" + biz_ctx) if biz_ctx else "")
        + (("\n\n" + kb) if kb else "")
        + contact_tag
    )
    # S036 — Allow Liluvine to flag herself as needing human help. The
    # marker [ESCALATE: <reason>] will be stripped from the user-facing
    # reply and trigger a WhatsApp notification to the admin.
    try:
        from routes.liluvine_escalation import ESCALATE_PROMPT_HINT
        sys_text = sys_text + ESCALATE_PROMPT_HINT
    except Exception:  # noqa: BLE001
        pass

    # Call the LLM
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        try:
            from routes.llm_health import record_llm_outcome
            await record_llm_outcome(db, ok=False, error="EMERGENT_LLM_KEY missing", context="liluvine_wa_autoreply")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "reason": "EMERGENT_LLM_KEY missing"}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as exc:
        return {"ok": False, "reason": f"llm_import_failed: {exc!r}"}
    # Reuse a stable session per phone so the bot keeps context if the user
    # writes again within the same conversation.
    session_id = f"wa:{scope_uid}:{phone_digits}"
    try:
        chat = LlmChat(
            api_key=api_key, session_id=session_id, system_message=sys_text,
        ).with_model("anthropic", "claude-haiku-4-5-20251001")
        reply = await chat.send_message(UserMessage(text=text))
        try:
            from routes.llm_health import record_llm_outcome
            await record_llm_outcome(db, ok=True, context="liluvine_wa_autoreply")
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:
        logger.exception("[wa_autoreply] LLM error")
        try:
            from routes.llm_health import record_llm_outcome
            await record_llm_outcome(db, ok=False, error=str(exc), context="liluvine_wa_autoreply")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "reason": f"llm_error: {str(exc)[:160]}"}
    reply = (reply or "").strip()
    if not reply:
        return {"ok": False, "reason": "empty_reply"}

    # S036 — Parse escalation marker, strip from user-facing reply,
    # and trigger an async notification to the admin.
    escalation_reason: Optional[str] = None
    try:
        from routes.liluvine_escalation import strip_escalation_marker, notify_admin
        reply, escalation_reason = strip_escalation_marker(reply)
        if escalation_reason:
            await notify_admin(
                db,
                contact_name=(contact or {}).get("name") if contact else None,
                contact_phone_digits=phone_digits,
                last_user_message=text,
                reason=escalation_reason,
                send_wa=wa_send_text,
                session_id=session_id,
                history=[{"role": "user", "text": text}, {"role": "assistant", "text": reply}],
            )
    except Exception:  # noqa: BLE001
        logger.exception("[wa_autoreply] escalation hook failed")
    # If after stripping the marker the reply is empty, fall back to a
    # safe "we'll get back to you" message and still consider it a success.
    if not reply.strip():
        reply = "Merci pour votre message. Un agent humain va vous recontacter rapidement."

    signature = (settings_doc.get("liluvine_wa_autoreply_signature") or "").strip()
    if signature is None or signature == "":
        signature = "— 🤖 Réponse automatique Liluvine PRO"
    final_text = f"{reply}\n\n{signature}" if signature else reply

    # Send via Meta Graph API
    quote_mid = inbound_doc.get("wa_message_id")
    send_res = await wa_send_text(inbound_doc.get("from") or f"+{phone_digits}", final_text,
                                  reply_to_message_id=quote_mid)
    if not send_res.get("ok"):
        return {"ok": False, "reason": f"send_failed: {send_res.get('error')}", "send": send_res}

    # Quota tracking
    tokens = max(int((len(sys_text) + len(text) + len(final_text)) / 4), 1)
    try:
        from routes.ai_quotas import track_ai_usage
        await track_ai_usage(
            db, user=user_doc, resource="chat", units=tokens,
            model="claude-haiku-4-5-20251001",
            metadata={"source": "whatsapp_native", "phone_digits": phone_digits},
        )
    except Exception:
        pass

    # Persist the conversation (creates/updates a Liluvine session)
    session_doc = await db.liluvine_pro_sessions.find_one(
        {"id": session_id}, {"_id": 0, "id": 1}
    )
    if not session_doc:
        await db.liluvine_pro_sessions.insert_one({
            "id": session_id,
            "client_id": scope_uid,
            "user_id": user_doc["id"],
            "user_label": (contact or {}).get("name") or f"WA +{phone_digits}",
            "title": f"WA · +{phone_digits} · {text[:40]}",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "message_count": 0,
            "external_source": "whatsapp_native",
            "external_payload": {"phone_digits": phone_digits, "contact_id": (contact or {}).get("id")},
        })
    await db.liluvine_pro_messages.insert_one({
        "id": secrets.token_urlsafe(12),
        "session_id": session_id, "client_id": scope_uid,
        "user_id": user_doc["id"], "role": "user", "content": text,
        "external_source": "whatsapp_native",
        "wa_message_id_quoted": quote_mid,
        "created_at": _now_iso(),
    })
    out_msg_id = secrets.token_urlsafe(12)
    await db.liluvine_pro_messages.insert_one({
        "id": out_msg_id,
        "session_id": session_id, "client_id": scope_uid,
        "user_id": user_doc["id"], "role": "assistant", "content": final_text,
        "tokens": tokens, "model": "claude-haiku-4-5-20251001",
        "context_injected": bool(ctx),
        "external_source": "whatsapp_native",
        "wa_message_id_out": send_res.get("message_id"),
        "created_at": _now_iso(),
    })
    await db.liluvine_pro_sessions.update_one(
        {"id": session_id},
        {"$inc": {"message_count": 2}, "$set": {"updated_at": _now_iso()}},
    )
    # Anti-flood state
    await db.liluvine_wa_autoreply_state.update_one(
        {"phone_digits": phone_digits},
        {"$set": {
            "phone_digits": phone_digits, "last_replied_at": _now_iso(),
            "last_message_in": text[:200], "last_message_out": final_text[:200],
            "tenant_id": scope_uid,
        }},
        upsert=True,
    )

    # Iter38r-fix9i — Also mirror the outgoing message into `whatsapp_messages`
    # so the conversation thread (Inbox Unifié, Centre de Messages, contact
    # detail panel) shows Liluvine's auto-reply inline with human messages.
    try:
        wa_log = {
            "id": secrets.token_urlsafe(12),
            "client_id": scope_uid,
            "tenant_id": scope_uid,
            "direction": "outbound",
            "from": "liluvine-pro",
            "to": inbound_doc.get("from") or f"+{phone_digits}",
            "phone_digits": phone_digits,
            "message_type": "text",
            "body": final_text,
            "wa_message_id": send_res.get("message_id"),
            "status": "sent",
            "wa_status": "sent",
            "sent_at": _now_iso(),
            "created_at": _now_iso(),
            "ai_generated": True,
            "ai_source": "liluvine_pro_autoreply",
            "ai_session_id": session_id,
            "reply_to_wa_message_id": quote_mid,
            "contact_id": (contact or {}).get("id"),
        }
        await db.whatsapp_messages.insert_one(wa_log.copy())
    except Exception:  # noqa: BLE001
        logger.warning("[wa_autoreply] mirror to whatsapp_messages failed", exc_info=True)

    return {
        "ok": True, "reason": "sent",
        "wa_out_message_id": send_res.get("message_id"),
        "session_id": session_id, "reply_message_id": out_msg_id,
        "tokens": tokens,
    }
