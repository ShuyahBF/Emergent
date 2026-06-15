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
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

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
    # EXCEPT for the public commands `!Garde` and `!Meteo`/`!Météo` (handled below).
    cmd_lower = text.lower()
    is_public_cmd = (
        cmd_lower.startswith("!garde") or cmd_lower.startswith("!pharmacie")
        or cmd_lower.startswith("!meteo") or cmd_lower.startswith("!météo")
    )
    if (text.startswith("!") or text.startswith("/")) and not is_public_cmd:
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

    # Iter43-fix22 (2026-06) — Slash-style commands publiques : `!Garde`, `!Meteo`.
    # Court-circuite l'appel LLM (économie de tokens + réponse instantanée).
    # Pas besoin de feature gate `ai_liluvine_pro` puisque ce sont des
    # commandes utilitaires (annuaire / météo), pas de l'IA.
    if is_public_cmd:
        if cmd_lower.startswith("!garde") or cmd_lower.startswith("!pharmacie"):
            reply = await _build_garde_reply(db)
        else:
            reply = await _build_meteo_reply(db, cmd_lower, phone_digits)
        # Send back via the provided sender
        to_e164 = inbound_doc.get("from") or f"+{phone_digits}"
        try:
            send_res = await wa_send_text(to_e164, reply, reply_to_message_id=inbound_doc.get("wa_message_id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply][cmd] send failed: %s", exc)
            send_res = {"ok": False, "error": str(exc)}
        await db.whatsapp_messages.insert_one({
            "id": uuid.uuid4().hex, "direction": "outbound",
            "to": to_e164, "phone_digits": phone_digits,
            "body": reply, "client_id": inbound_doc.get("client_id"),
            "wa_message_id": (send_res or {}).get("message_id"),
            "auto_reply": True, "command": cmd_lower.split()[0],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"ok": True, "command": cmd_lower.split()[0], "send": send_res}

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



# ====================================================================
# Iter43-fix22 (2026-06) — Public WA commands : !Garde, !Meteo
# ====================================================================
async def _build_garde_reply(db) -> str:
    """Construit la réponse pour la commande `!Garde` : liste des officines
    de garde de la semaine en cours + message de prompt rétablissement."""
    today = datetime.now(timezone.utc).date()
    iso = today.isocalendar()
    year, week = iso[0], iso[1]
    # Récupère le planning pour cette semaine
    entry = await db.garde_planning.find_one({"year": year, "week_number": week}, {"_id": 0})
    if not entry:
        # Calcule la rotation auto
        groups_set: set = set()
        async for o in db.officines.find({"groupe_garde": {"$nin": [None, ""]}}, {"groupe_garde": 1, "_id": 0}):
            try:
                groups_set.add(int(o["groupe_garde"]))
            except (TypeError, ValueError):
                continue
        if not groups_set:
            return ("📅 Aucun groupe de garde n'est encore configuré.\n\n"
                    "Pour configurer le planning des gardes, rendez-vous sur "
                    "https://sawalismartsystems.com/admin/garde-planning.")
        groups = sorted(groups_set)
        gg = groups[(week - 1) % len(groups)]
    else:
        gg = entry.get("groupe_garde")
    # Liste des officines
    officines: List[Dict[str, Any]] = []
    async for o in db.officines.find(
        {"groupe_garde": gg, "status": "active"},
        {"_id": 0, "name": 1, "intitule": 1, "phone": 1, "whatsapp": 1, "address": 1, "city": 1, "location_hint": 1},
    ).sort("name", 1):
        officines.append(o)
    try:
        monday = date.fromisocalendar(year, week, 1).strftime("%d/%m")
        sunday = date.fromisocalendar(year, week, 7).strftime("%d/%m")
    except ValueError:
        monday, sunday = "?", "?"
    lines = [
        f"🏥 *Officines de garde — Semaine {week}* ({monday} au {sunday})",
        f"*Groupe {gg}* — {len(officines)} officine{'s' if len(officines) > 1 else ''}",
        "",
    ]
    if not officines:
        lines.append("_Aucune officine active dans ce groupe pour cette semaine._")
    else:
        for o in officines[:25]:  # WhatsApp ~4096 char limit safety
            name = o.get("name") or o.get("intitule") or "—"
            addr_bits = [o.get("location_hint") or o.get("address"), o.get("city")]
            addr = ", ".join([b for b in addr_bits if b]).strip()
            ph = o.get("whatsapp") or o.get("phone") or ""
            lines.append(f"• *{name}*")
            if addr:
                lines.append(f"  📍 {addr}")
            if ph:
                lines.append(f"  📞 {ph}")
        if len(officines) > 25:
            lines.append(f"\n_…et {len(officines) - 25} autre(s) — liste complète sur le site_")
    lines.append("\n💚 _Prompt rétablissement et bonne santé !_")
    lines.append("\n_— Liluvine PRO 🤖_")
    return "\n".join(lines)


async def _build_meteo_reply(db, cmd_text: str, phone_digits: str) -> str:
    """Construit la réponse pour la commande `!Meteo [+N]`.

    `!Meteo`     → météo actuelle de la ville détectée du visiteur
    `!Meteo +3`  → prévisions à +1h, +2h, +3h (max +5h)
    """
    # Parse offset
    m = re.match(r"^[!/](?:meteo|météo)\s*(?:\+\s*(\d+))?\s*(.*)$", cmd_text.strip(), re.IGNORECASE)
    offset = 0
    explicit_city = ""
    if m:
        if m.group(1):
            try:
                offset = max(0, min(5, int(m.group(1))))
            except (TypeError, ValueError):
                offset = 0
        explicit_city = (m.group(2) or "").strip()
    # Ville par défaut depuis settings
    settings_doc = await db.settings.find_one({"_id": "global"}, {"_id": 0,
        "weather_widget_default_city": 1, "weather_widget_default_country": 1,
        "company_city": 1, "company_country": 1}) or {}
    city = explicit_city or settings_doc.get("weather_widget_default_city") \
           or settings_doc.get("company_city") or "Ouagadougou"
    # Geocode + weather
    try:
        async with httpx.AsyncClient(timeout=6.0) as http:
            geo_r = await http.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "fr"},
            )
            if geo_r.status_code >= 300:
                return f"☁️ Impossible de localiser la ville « {city} »."
            geo = geo_r.json().get("results") or []
            if not geo:
                return f"☁️ Ville inconnue : « {city} ». Essayez `!meteo Ouagadougou` ou `!meteo Paris`."
            top = geo[0]
            lat, lon = top["latitude"], top["longitude"]
            city_name = top.get("name") or city
            country = top.get("country_code") or ""
            w_r = await http.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                    "hourly": "temperature_2m,weather_code,precipitation_probability",
                    "forecast_days": 1,
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "timezone": "auto",
                },
            )
            if w_r.status_code >= 300:
                return "☁️ Service météo indisponible. Réessayez plus tard."
            data = w_r.json() or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[wa_meteo] HTTP error: %s", exc)
        return "☁️ Erreur réseau lors de la récupération de la météo. Réessayez."
    cur = data.get("current") or {}
    code = int(cur.get("weather_code") or 0)
    # Mini map des codes WMO → emoji + libellé FR
    icon_label = {
        0: ("☀️", "ensoleillé"), 1: ("🌤️", "principalement clair"),
        2: ("⛅", "partiellement nuageux"), 3: ("☁️", "couvert"),
        45: ("🌫️", "brouillard"), 48: ("🌫️", "brouillard givrant"),
        51: ("🌦️", "bruine légère"), 53: ("🌦️", "bruine"), 55: ("🌦️", "bruine dense"),
        61: ("🌧️", "pluie légère"), 63: ("🌧️", "pluie modérée"), 65: ("🌧️", "pluie forte"),
        71: ("🌨️", "neige légère"), 73: ("🌨️", "neige"), 75: ("🌨️", "neige forte"),
        80: ("🌦️", "averses"), 81: ("🌧️", "averses modérées"), 82: ("⛈️", "averses violentes"),
        95: ("⛈️", "orage"), 96: ("⛈️", "orage + grêle"), 99: ("⛈️", "orage violent"),
    }
    emo, label = icon_label.get(code, ("☁️", "conditions inconnues"))
    lines = [
        f"{emo} *Météo {city_name}* ({country})" if country else f"{emo} *Météo {city_name}*",
        f"*{round(cur.get('temperature_2m') or 0)}°C* · {label}",
        f"_Ressenti {round(cur.get('apparent_temperature') or 0)}°C · "
        f"Vent {round(cur.get('wind_speed_10m') or 0)} km/h · "
        f"Humidité {cur.get('relative_humidity_2m')}%_",
    ]
    if offset > 0:
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        codes = hourly.get("weather_code") or []
        probs = hourly.get("precipitation_probability") or []
        # Trouver l'index "current hour" dans la liste horaire
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
        try:
            idx = next(i for i, t in enumerate(times) if t >= now_iso)
        except StopIteration:
            idx = 0
        lines.append("\n*Prochaines heures :*")
        for h in range(1, offset + 1):
            i = idx + h
            if i >= len(times):
                break
            t = times[i].split("T")[-1]
            c = codes[i] if i < len(codes) else 0
            emo_h, lbl_h = icon_label.get(int(c), ("☁️", ""))
            p = probs[i] if i < len(probs) else 0
            lines.append(f"  • {t} · {emo_h} {round(temps[i])}°C · pluie {p}%")
    lines.append("\n_— Liluvine PRO 🤖_")
    return "\n".join(lines)
