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

    # Iter43-fix24az-o (2026-07-21) — Liluvine Reactions integration :
    # PRIORITÉ 1 : match d'un template Ad configuré → répondre + compter.
    # PRIORITÉ 2 : `!reactions` command → afficher les stats.
    # PRIORITÉ 3 : Fuzzy command detection (ex: "pharmacies de garde" → `!garde`).
    # PRIORITÉ 4 : Auto-add nouveau contact au groupe par défaut.
    from_num = inbound_doc.get("from") or ""
    try:
        import server as _server_module
        reactions_helpers = getattr(_server_module, "LILUVINE_REACTIONS_HELPERS", None) or {}
    except Exception:  # noqa: BLE001
        reactions_helpers = {}

    # Auto-add nouveau contact (silencieux, en tâche annexe)
    if reactions_helpers.get("auto_add_new_contact_if_enabled"):
        try:
            await reactions_helpers["auto_add_new_contact_if_enabled"](
                phone_digits,
                inbound_doc.get("from_profile_name") or inbound_doc.get("contact_name"),
                inbound_doc.get("client_id"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply] auto_add_contact failed: %s", exc)

    # !reactions — commande spéciale : stats Liluvine Reactions
    if cmd_lower.startswith("!reactions") or cmd_lower.startswith("!réactions"):
        if reactions_helpers.get("build_reactions_summary_reply"):
            summary = await reactions_helpers["build_reactions_summary_reply"]()
            try:
                await wa_send_text(from_num, summary)
                return {"ok": True, "command": "!reactions", "reply": summary[:120]}
            except Exception as exc:  # noqa: BLE001
                logger.warning("[wa_autoreply] !reactions send failed: %s", exc)

    # Ad template match (message issu de FB Ads pré-défini par l'annonceur)
    if reactions_helpers.get("try_reply_ad_template"):
        try:
            match = await reactions_helpers["try_reply_ad_template"](
                text, wa_send_text, from_num,
                phone_digits=phone_digits,
                contact=contact,
                tenant_id=inbound_doc.get("client_id"),
                wa_inbound_id=inbound_doc.get("wa_message_id"),
            )
            if match and match.get("sent"):
                return {
                    "ok": True,
                    "command": f"ad_template:{match['template'].get('id', '')[:8]}",
                    "reply": (match["template"].get("response_text") or "")[:120],
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply] ad_template match failed: %s", exc)

    # Fuzzy command detection (texte sans !, ou avec faute de frappe)
    if reactions_helpers.get("try_fuzzy_command_correction") and not text.startswith("!"):
        try:
            fuzzy = await reactions_helpers["try_fuzzy_command_correction"](text)
            if fuzzy and fuzzy.get("cmd"):
                # Réécrit le texte en `!cmd` pour que le dispatcher standard réponde
                # Envoie D'ABORD le message de correction, puis laisse le flux normal
                # exécuter la commande.
                correction = fuzzy.get("correction_prefix") or ""
                if correction:
                    try:
                        await wa_send_text(from_num, correction)
                    except Exception:  # noqa: BLE001
                        pass
                # Iter43-fix24az-p — journalise le match dans la timeline du contact
                if reactions_helpers.get("log_fuzzy_correction"):
                    try:
                        await reactions_helpers["log_fuzzy_correction"](
                            phone_digits=phone_digits,
                            contact=contact,
                            tenant_id=inbound_doc.get("client_id"),
                            cmd=fuzzy["cmd"],
                            score=float(fuzzy.get("score") or 0),
                            inbound_text=text,
                            correction_prefix=correction,
                            wa_inbound_id=inbound_doc.get("wa_message_id"),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                text = f"!{fuzzy['cmd']}"
                cmd_lower = text.lower()
                logger.info("[wa_autoreply] fuzzy corrected to %s (score=%.1f)", text, fuzzy.get("score", 0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply] fuzzy correction failed: %s", exc)

    # Iter43-fix24az-p — Capture les messages non-traités (free-text sans !, sans template
    # match, sans fuzzy). Le hook alimente le panneau "Suggestions" dans AdminSettings.
    if not text.startswith("!") and not text.startswith("/") and reactions_helpers.get("record_unmatched_message"):
        try:
            await reactions_helpers["record_unmatched_message"](
                inbound_text=text,
                phone_digits=phone_digits,
                contact_name=(contact or {}).get("name") or inbound_doc.get("from_profile_name"),
                tenant_id=inbound_doc.get("client_id"),
            )
        except Exception:  # noqa: BLE001
            pass

    is_public_cmd = (
        cmd_lower.startswith("!garde") or cmd_lower.startswith("!pharmacie")
        or cmd_lower.startswith("!meteo") or cmd_lower.startswith("!météo")
        or cmd_lower.startswith("!adresse") or cmd_lower.startswith("!contact")
        or cmd_lower.startswith("!horaire") or cmd_lower.startswith("!horaires")
        or cmd_lower.startswith("!stock") or cmd_lower.startswith("!dispo")
    )
    # Iter43-fix24d (2026-06) — Stocker TOUTES les exclamations (`!xxx`) dans la table
    # dédiée `liluvine_exclamations`, qu'on sache ou non les traiter. Cela permet :
    #   - Audit des commandes inconnues (ex. `!Aizenta` sans handler côté code)
    #   - Roadmap : décider lesquelles automatiser plus tard
    if text.startswith("!"):
        try:
            cmd_match = re.match(r"^!\s*([\w\.\-]+)", text)
            command_token = (cmd_match.group(1) if cmd_match else "").lower()
            tail = text[(cmd_match.end() if cmd_match else 1):].strip()
            await db.liluvine_exclamations.insert_one({
                "id": uuid.uuid4().hex,
                "channel": "whatsapp",
                "direction": "inbound",
                "from": inbound_doc.get("from"),
                "phone_digits": phone_digits,
                "body": text,
                "command": command_token,
                "command_args": tail,
                "from_profile_name": inbound_doc.get("from_profile_name"),
                "contact_id": inbound_doc.get("contact_id"),
                "contact_name": inbound_doc.get("contact_name"),
                "client_id": inbound_doc.get("client_id"),
                "wa_message_id": inbound_doc.get("wa_message_id"),
                "inbound_doc_id": inbound_doc.get("id"),
                "is_known_command": is_public_cmd,
                "handled": False,  # mis à True après envoi de la réponse
                "reply": None,
                "created_at": _now_iso(),
            })
        except Exception:  # noqa: BLE001
            logger.exception("[wa_autoreply] persist exclamation failed")

    # Iter43-fix24i (2026-06) — DECOUPLAGE : les commandes publiques `!xxx` doivent
    # TOUJOURS fonctionner indépendamment du toggle `liluvine_wa_autoreply_enabled`
    # (qui ne contrôle QUE l'auto-reply LLM basé sur le contenu).
    # Auparavant : si l'admin n'avait pas activé l'auto-reply LLM, `!garde`/`!meteo`
    # restaient muettes (decision.ok = False sur `disabled`).
    # Maintenant : les `!commandes` (connues ET inconnues) passent par leur propre
    # branche AVANT le gate `should_autoreply`. Seul filtre commun : denylist phones.
    if text.startswith("!") or text.startswith("/"):
        # Filtre denylist (même pour les commandes — un admin peut vouloir
        # bloquer un harceleur même sur les commandes utilitaires).
        deny_list_cmd = _norm_phones(settings_doc.get("liluvine_wa_autoreply_deny_phones"))
        if phone_digits in deny_list_cmd:
            return {"ok": False, "reason": "denylisted"}

        # Iter43-fix24ac (2026-06-16) — Configurable VIDAL `!commands`.
        # On essaie d'abord de matcher avec une action VIDAL configurée
        # (Admin → Settings → VIDAL Actions). Si la commande correspond,
        # on exécute l'action et on répond. Sinon on continue vers les
        # handlers existants (`!garde`, `!adresse`, etc.).
        vidal_cmd_token = None
        vidal_cmd_args = ""
        m_v = re.match(r"^!\s*([\w\-]+)\s*(.*)$", text)
        if m_v:
            vidal_cmd_token = (m_v.group(1) or "").lower()
            vidal_cmd_args = m_v.group(2) or ""
        if vidal_cmd_token:
            vidal_res = await _build_vidal_reply(
                db, vidal_cmd_token, vidal_cmd_args, phone_digits,
            )
            if vidal_res is not None:
                # The command matched a configured VIDAL action — send reply.
                reply_v = vidal_res.get("text") or "…"
                to_e164_v = inbound_doc.get("from") or f"+{phone_digits}"
                try:
                    send_v = await wa_send_text(
                        to_e164_v, reply_v,
                        reply_to_message_id=inbound_doc.get("wa_message_id"),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[wa_autoreply][vidal] send failed: %s", exc)
                    send_v = {"ok": False, "error": str(exc)}
                try:
                    await db.whatsapp_messages.insert_one({
                        "id": uuid.uuid4().hex, "direction": "outbound",
                        "to": to_e164_v, "phone_digits": phone_digits,
                        "body": reply_v, "client_id": inbound_doc.get("client_id"),
                        "wa_message_id": (send_v or {}).get("message_id"),
                        "auto_reply": True,
                        "command": f"!{vidal_cmd_token} [vidal:{vidal_res.get('action_id')}]",
                        "vidal_action_id": vidal_res.get("action_id"),
                        "vidal_denied": bool(vidal_res.get("denied")),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await db.liluvine_exclamations.update_one(
                        {"wa_message_id": inbound_doc.get("wa_message_id"), "direction": "inbound"},
                        {"$set": {
                            "handled": True,
                            "reply": reply_v[:500],
                            "handled_at": _now_iso(),
                            "vidal_action_id": vidal_res.get("action_id"),
                            "send_ok": bool((send_v or {}).get("ok") if isinstance(send_v, dict) else True),
                        }},
                    )
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "ok": True,
                    "command": f"!{vidal_cmd_token}",
                    "vidal_action_id": vidal_res.get("action_id"),
                    "denied": bool(vidal_res.get("denied")),
                    "send": send_v,
                    "reply": reply_v,
                }
            # vidal_res is None → no matching VIDAL action, fall through.

        if is_public_cmd:
            # Commandes publiques — TOUJOURS exécutées.
            # Sécurisées par try/except : même si le builder plante, on répond.
            location_payload = None  # type=location WA à envoyer en plus du texte
            try:
                if cmd_lower.startswith("!garde") or cmd_lower.startswith("!pharmacie"):
                    reply_pc = await _build_garde_reply(db)
                    cmd_label = "!garde"
                elif cmd_lower.startswith("!adresse") or cmd_lower.startswith("!contact"):
                    addr_res = await _build_adresse_reply(db)
                    reply_pc = addr_res["text"]
                    location_payload = addr_res.get("location")
                    cmd_label = "!adresse"
                elif cmd_lower.startswith("!horaire"):  # couvre !horaire ET !horaires
                    reply_pc = await _build_horaires_reply(db)
                    cmd_label = "!horaires"
                elif cmd_lower.startswith("!stock") or cmd_lower.startswith("!dispo"):
                    # Extract args after the command word
                    m_stock = re.match(r"^!(?:stock|dispo)\s*(.*)$", text, re.IGNORECASE)
                    stock_args = (m_stock.group(1).strip() if m_stock else "")
                    reply_pc = await _build_stock_reply(db, stock_args)
                    cmd_label = "!stock"
                else:
                    reply_pc = await _build_meteo_reply(db, cmd_lower, phone_digits)
                    cmd_label = "!meteo"
                if not reply_pc or not str(reply_pc).strip():
                    reply_pc = "…"
            except Exception:  # noqa: BLE001
                logger.exception("[wa_autoreply][cmd] builder failed for %s", cmd_lower)
                reply_pc = (
                    "⚠️ Désolé, je n'arrive pas à traiter cette commande pour le moment. "
                    "Réessayez dans quelques instants."
                )
                cmd_label = cmd_lower.split()[0] if cmd_lower.split() else "!unknown"
            to_e164_pc = inbound_doc.get("from") or f"+{phone_digits}"
            try:
                send_pc = await wa_send_text(
                    to_e164_pc, reply_pc, reply_to_message_id=inbound_doc.get("wa_message_id"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[wa_autoreply][cmd] send failed: %s", exc)
                send_pc = {"ok": False, "error": str(exc)}
            # Iter43-fix24al + 24aq (2026-06-17) — Pour TOUTES les commandes
            # WhatsApp (`!garde`, `!produits`, `!adresse`, etc.), envoie aussi
            # une image après le texte si configurée dans settings :
            #   - Image SPÉCIFIQUE à la commande : `wa_cmd_<id>_image_url`
            #     (où <id> est l'`id` de l'action sans `!`, ex: `garde`, `produits`)
            #     + `wa_cmd_<id>_image_caption`.
            #   - Image PAR DÉFAUT (fallback) : `wa_default_cmd_image_url`
            #     + `wa_default_cmd_image_caption`.
            #   - Compatibilité ascendante : `garde_reply_image_url` (utilisé
            #     historiquement pour !garde) est encore reconnue.
            # No-op silencieux si aucune image n'est configurée.
            try:
                cmd_id = (cmd_label or "").lstrip("!").lower().strip()
                s_img = await db.settings.find_one(
                    {"_id": "global"},
                    {"_id": 0,
                     f"wa_cmd_{cmd_id}_image_url": 1,
                     f"wa_cmd_{cmd_id}_image_caption": 1,
                     "wa_default_cmd_image_url": 1,
                     "wa_default_cmd_image_caption": 1,
                     "garde_reply_image_url": 1,
                     "garde_reply_image_caption": 1},
                ) or {}
                # Priority order : per-command override → legacy garde → default
                img_url = (
                    s_img.get(f"wa_cmd_{cmd_id}_image_url")
                    or (s_img.get("garde_reply_image_url") if cmd_id == "garde" else "")
                    or s_img.get("wa_default_cmd_image_url")
                    or ""
                )
                img_caption = (
                    s_img.get(f"wa_cmd_{cmd_id}_image_caption")
                    or (s_img.get("garde_reply_image_caption") if cmd_id == "garde" else "")
                    or s_img.get("wa_default_cmd_image_caption")
                    or None
                )
                if img_url:
                    img_res = await _wa_send_image(
                        to_e164_pc, img_url,
                        caption=img_caption, db_ref=db,
                    )
                    logger.info("[wa_autoreply][!%s] image sent: %s", cmd_id, img_res)
            except Exception:  # noqa: BLE001
                logger.exception("[wa_autoreply][!%s] image send failed", cmd_label)
            # Iter43-fix24j — Pour !adresse avec lat/lon configurés, envoie aussi
            # une "carte" WhatsApp type=location (UX native : preview map cliquable).
            if location_payload is not None:
                try:
                    s_local = await db.settings.find_one({"_id": "global"}) or {}
                    loc_res = await _wa_send_location(
                        to_e164_pc,
                        latitude=location_payload["latitude"],
                        longitude=location_payload["longitude"],
                        name=location_payload.get("name"),
                        address=location_payload.get("address"),
                        settings_doc=s_local,
                    )
                    logger.info("[wa_autoreply][!adresse] location sent: %s", loc_res)
                except Exception:  # noqa: BLE001
                    logger.exception("[wa_autoreply][!adresse] location send failed")
            try:
                await db.whatsapp_messages.insert_one({
                    "id": uuid.uuid4().hex, "direction": "outbound",
                    "to": to_e164_pc, "phone_digits": phone_digits,
                    "body": reply_pc, "client_id": inbound_doc.get("client_id"),
                    "wa_message_id": (send_pc or {}).get("message_id"),
                    "auto_reply": True, "command": cmd_label,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:  # noqa: BLE001
                pass
            try:
                await db.liluvine_exclamations.update_one(
                    {"wa_message_id": inbound_doc.get("wa_message_id"), "direction": "inbound"},
                    {"$set": {
                        "handled": True, "reply": reply_pc[:500],
                        "handled_at": _now_iso(),
                        "send_ok": bool((send_pc or {}).get("ok") if isinstance(send_pc, dict) else True),
                    }},
                )
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True, "command": cmd_label, "send": send_pc, "reply": reply_pc}

        # Catch-all pour `!xxx` inconnu / `/xxx` — TOUJOURS exécuté SAUF si
        # l'admin l'a explicitement désactivé via `liluvine_wa_unknown_cmd_fallback_enabled`.
        # Le `True` par défaut garantit qu'aucune commande n'est silencieuse.
        fb_enabled = settings_doc.get("liluvine_wa_unknown_cmd_fallback_enabled")
        if fb_enabled is False:  # explicitement False uniquement (None / absent = True)
            return {"ok": False, "reason": "unknown_fallback_disabled"}
        fallback_reply = (settings_doc.get("liluvine_wa_unknown_cmd_reply") or "…").strip() or "…"
        to_e164_fb = inbound_doc.get("from") or f"+{phone_digits}"
        try:
            send_res_fb = await wa_send_text(
                to_e164_fb, fallback_reply, reply_to_message_id=inbound_doc.get("wa_message_id"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply][fallback] send failed: %s", exc)
            send_res_fb = {"ok": False, "error": str(exc)}
        try:
            await db.whatsapp_messages.insert_one({
                "id": uuid.uuid4().hex, "direction": "outbound",
                "to": to_e164_fb, "phone_digits": phone_digits,
                "body": fallback_reply, "client_id": inbound_doc.get("client_id"),
                "wa_message_id": (send_res_fb or {}).get("message_id"),
                "auto_reply": True, "command": "unknown_fallback",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:  # noqa: BLE001
            pass
        try:
            await db.liluvine_exclamations.update_one(
                {"wa_message_id": inbound_doc.get("wa_message_id"), "direction": "inbound"},
                {"$set": {
                    "handled": True, "reply": fallback_reply[:500],
                    "handled_at": _now_iso(),
                    "send_ok": bool((send_res_fb or {}).get("ok") if isinstance(send_res_fb, dict) else True),
                    "fallback": True,
                }},
            )
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "command": "unknown_fallback", "send": send_res_fb}

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

    # Iter43-fix24i (2026-06) — La gestion des commandes publiques `!Garde`/`!Meteo`
    # est désormais effectuée AVANT `should_autoreply` (voir bloc ci-dessus, ligne ~145).
    # Cette branche est conservée vide pour la lisibilité — toute exclamation `!xxx`
    # a déjà été return-ée par le bloc principal.

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
    de garde de la semaine en cours + message de prompt rétablissement.

    Iter43-fix24ah (2026-06-17) — Le filtre `status="active"` est retiré :
    si un admin a affecté un `groupe_garde` à une officine, elle fait partie
    de la rotation, quel que soit son statut de modération. Le filtre exclut
    désormais uniquement `suspended`.

    Iter43-fix24ai (2026-06-17) — Template configurable depuis Admin Settings
    (`settings.garde_reply_template`) avec syntaxe :
      - `{champ}`  → valeur texte du champ (ex: `{name}`)
      - `[champ]`  → lien cliquable (ex: `[phone]` → `tel:+226…`,
                     `[latitude,longitude]` → maps URL, `[whatsapp]` → wa.me/…)
      - Espace      → séparateur de champs
      - Saut de ligne → nouvelle officine
    Fallback sur le template hardcodé si non configuré.
    """
    today = datetime.now(timezone.utc).date()
    # Iter43-fix24az-e (2026-02-26) — Use centralized garde period resolver so
    # the `!Garde` header dates show the ACTUAL guard period boundaries
    # (Sat → Sat) instead of the ISO week's Mon → Sun in saturday_noon mode.
    try:
        from routes.garde_planning import _current_garde_period as _gp
        period = await _gp(db, now=datetime.now(timezone.utc))
        year, week = period["year"], period["week"]
        period_start, period_end = period["period_start"], period["period_end"]
    except Exception:  # noqa: BLE001
        iso = today.isocalendar()
        year, week = iso[0], iso[1]
        period_start = date.fromisocalendar(year, week, 1)
        period_end = date.fromisocalendar(year, week, 7)
    # Récupère le planning pour cette semaine
    entry = await db.garde_planning.find_one({"year": year, "week_number": week}, {"_id": 0})
    assist_group = None
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
        # Iter43-fix24az-r (2026-07-22) — Groupe d'assistance hebdo
        assist_group = entry.get("assist_group")
    # Liste des officines (status != suspended)
    officines: List[Dict[str, Any]] = []
    async for o in db.officines.find(
        {"groupe_garde": gg, "status": {"$ne": "suspended"}},
        {"_id": 0, "name": 1, "intitule": 1, "phone": 1, "whatsapp": 1,
         "address": 1, "city": 1, "location_hint": 1,
         "latitude": 1, "longitude": 1, "contact_name": 1, "email": 1},
    ).sort("name", 1):
        officines.append(o)
    # Iter43-fix24az-r — Officines du groupe d'assistance (si défini et distinct)
    assist_officines: List[Dict[str, Any]] = []
    if assist_group is not None and assist_group != gg:
        async for o in db.officines.find(
            {"groupe_garde": assist_group, "status": {"$ne": "suspended"}},
            {"_id": 0, "name": 1, "intitule": 1, "phone": 1, "whatsapp": 1,
             "address": 1, "city": 1, "location_hint": 1,
             "latitude": 1, "longitude": 1, "contact_name": 1, "email": 1},
        ).sort("name", 1):
            assist_officines.append(o)
    try:
        monday = period_start.strftime("%d/%m")
        sunday = period_end.strftime("%d/%m")
    except (AttributeError, ValueError):
        monday, sunday = "?", "?"
    # Lookup template configurable + CMS footer/site link (Iter43-fix24al)
    s = await db.settings.find_one(
        {"_id": "global"},
        {"_id": 0, "garde_reply_header": 1, "garde_reply_template": 1,
         "garde_reply_footer": 1, "garde_reply_site_url": 1},
    ) or {}
    template = s.get("garde_reply_template") or DEFAULT_GARDE_REPLY_TEMPLATE
    header_tpl = s.get("garde_reply_header") or DEFAULT_GARDE_REPLY_HEADER
    footer_tpl = s.get("garde_reply_footer") or DEFAULT_GARDE_REPLY_FOOTER
    site_url = s.get("garde_reply_site_url") or "https://sawalismartsystems.com"
    header = _render_garde_header(header_tpl, week=week, year=year, monday=monday,
                                  sunday=sunday, gg=gg, count=len(officines))
    # Iter43-fix24az-v (2026-07-22) — Import split hint constant so the
    # centralised auto-splitter in `_wa_send_text` breaks at the right seam
    # (between the main officines block and the assist officines block).
    try:
        from routes.whatsapp_helpers import _WA_SPLIT_HINT, _WA_TEXT_MAX
    except Exception:  # noqa: BLE001
        _WA_SPLIT_HINT = "\u2063\u2063"
        _WA_TEXT_MAX = 3800
    # Per-section budget: leave ~600 chars margin for header + footer + link.
    _section_budget = _WA_TEXT_MAX - 600
    lines = [header, ""]
    if not officines:
        lines.append("_Aucune officine dans ce groupe pour cette semaine._")
    else:
        rendered_count = 0
        current_len = sum(len(l_) + 1 for l_ in lines)
        for o in officines:
            rendered = _render_garde_officine(template, o)
            if not rendered.strip():
                continue
            piece_len = len(rendered) + 1
            if current_len + piece_len > _section_budget:
                # Budget reached — append site link and stop.
                remaining = len(officines) - rendered_count
                lines.append("")
                lines.append(f"_…et {remaining} autre(s) officine(s) — liste complète :_ {site_url}/garde")
                break
            lines.append(rendered)
            current_len += piece_len
            rendered_count += 1
    # Iter43-fix24az-r (2026-07-22) — Groupe d'assistance hebdo en italique
    # (nouvelle réglementation : chaque semaine un groupe standard est appuyé
    # par un « groupe d'appui » choisi parmi les groupes standards).
    #
    # Iter43-fix24az-s (2026-07-22) — FIX : ne PAS wrapper chaque ligne
    # d'officine dans `_..._` (italique WA), car les noms d'officines
    # contiennent des underscores (`Off_07968122`, `Off_8059c1ee`, ...) qui
    # cassent le pattern d'italique WhatsApp et rendent le message vide côté
    # client. Solution : garder l'italique UNIQUEMENT sur le titre de section
    # (safe, aucun `_` dans le libellé), puis préfixer chaque officine avec
    # `↳ ` pour indiquer visuellement l'appartenance au groupe d'appui.
    #
    # Iter43-fix24az-v (2026-07-22) — Insert an INVISIBLE SPLIT HINT before
    # the assist section so `_wa_send_text` can break the payload into two
    # sequential WhatsApp messages (main / assist) whenever the combined
    # length would exceed the 4096-char cap.
    if assist_officines:
        lines.append("")
        lines.append(_WA_SPLIT_HINT)  # semantic seam for auto-splitter
        lines.append(f"🤝 _Groupe d'appui G{assist_group} — {len(assist_officines)} officine(s) :_")
        assist_rendered = 0
        assist_len = 0
        for o in assist_officines:
            rendered = _render_garde_officine(template, o)
            if not rendered.strip():
                continue
            # Préfixe la 1re ligne avec `↳ ` et indente les suivantes de 2 espaces
            # pour un rendu visuel cohérent (comme une continuation).
            parts = [p for p in rendered.split("\n") if p.strip()]
            if not parts:
                continue
            block_lines = [f"↳ {parts[0].strip()}"]
            for sub in parts[1:]:
                block_lines.append(f"   {sub.strip()}")
            block_text = "\n".join(block_lines)
            piece_len = len(block_text) + 1
            if assist_len + piece_len > _section_budget:
                remaining = len(assist_officines) - assist_rendered
                lines.append(f"↳ _…et {remaining} autre(s) officine(s) d'appui — liste complète :_ {site_url}/garde")
                break
            lines.extend(block_lines)
            assist_len += piece_len
            assist_rendered += 1
    # Iter43-fix24al — Configurable footer (replaces hardcoded "Prompt rétablissement").
    # Also ALWAYS include the site link so contacts can navigate to /garde.
    footer = _render_garde_header(footer_tpl, week=week, year=year, monday=monday,
                                   sunday=sunday, gg=gg, count=len(officines))
    if footer.strip():
        lines.append("")
        lines.append(footer)
    lines.append("")
    lines.append(f"🌐 {site_url}/garde")
    return "\n".join(lines)


# ====================================================================
# Iter43-fix24ai (2026-06-17) — Template configurable pour `!garde`
# ====================================================================
DEFAULT_GARDE_REPLY_HEADER = (
    "🏥 *Officines de garde — Semaine {week}* ({monday} au {sunday})\n"
    "*Groupe {gg}* — {count} officine{plural}"
)

# Template par défaut : nom en gras, adresse, téléphone cliquable, géoloc cliquable.
# `{x}` = valeur texte ; `[x]` = lien cliquable (tel:, wa.me, maps).
# `[latitude,longitude]` est une forme spéciale → ouvre Google Maps.
DEFAULT_GARDE_REPLY_TEMPLATE = (
    "• *{name}*\n"
    "  📍 {location_hint} {city}\n"
    "  📞 [phone]\n"
    "  📍 [latitude,longitude]"
)

# Iter43-fix24al (2026-06-17) — Default footer (used when admin hasn't
# configured `settings.garde_reply_footer`).
DEFAULT_GARDE_REPLY_FOOTER = (
    "💚 _Prompt rétablissement et bonne santé !_\n"
    "_— Liluvine PRO 🤖_"
)


def _render_garde_header(template: str, *, week: int, year: int, monday: str,
                          sunday: str, gg: Any, count: int) -> str:
    """Render header with `{week}`, `{year}`, `{monday}`, `{sunday}`, `{gg}`,
    `{count}`, `{plural}` placeholders."""
    plural = "s" if count > 1 else ""
    ctx = {
        "week": week, "year": year, "monday": monday, "sunday": sunday,
        "gg": gg or "?", "count": count, "plural": plural,
    }
    def _repl(m: "re.Match") -> str:
        k = m.group(1)
        return str(ctx.get(k, m.group(0)))
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _repl, template)


def _format_phone_link(value: str) -> str:
    """Render a phone number as a WhatsApp-friendly clickable link.
    WhatsApp auto-links phone numbers in messages, so we just keep the value.
    For display we also prefix `tel:` is not necessary — WhatsApp clients
    handle phone numbers natively."""
    digits = re.sub(r"[^\d+]", "", value or "")
    if not digits:
        return value
    return digits  # WhatsApp auto-detects this as tappable


def _format_maps_link(lat: Any, lng: Any) -> str:
    """Build a Google Maps URL from lat,lng. WhatsApp will preview the link."""
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return ""
    return f"https://maps.google.com/?q={lat_f},{lng_f}"


def _render_garde_officine(template: str, o: Dict[str, Any]) -> str:
    """Render one officine line(s) using the configurable template.

    Syntax:
      - `{field}`  → plain text value of the field (empty string if missing)
      - `[field]`  → "link" version : phone → just the digits (WhatsApp auto-links),
                     whatsapp → `https://wa.me/<digits>`, email → `mailto:`,
                     latitude,longitude → maps URL.
      - any other text is kept as-is.

    Example template:
        "• *{name}* — [phone] — [latitude,longitude]"
    """
    # Build a lookup that combines plain fields with sensible defaults.
    name = o.get("intitule") or o.get("name") or "—"
    phone = o.get("phone") or ""
    whatsapp = o.get("whatsapp") or ""
    address = o.get("address") or ""
    city = o.get("city") or ""
    location_hint = o.get("location_hint") or ""
    email = o.get("email") or ""
    contact_name = o.get("contact_name") or ""
    latitude = o.get("latitude")
    longitude = o.get("longitude")
    plain = {
        "name": name,
        "phone": phone,
        "whatsapp": whatsapp,
        "address": address,
        "city": city,
        "location_hint": location_hint,
        "email": email,
        "contact_name": contact_name,
        "latitude": "" if latitude is None else str(latitude),
        "longitude": "" if longitude is None else str(longitude),
    }
    # Replace `[latitude,longitude]` first (composite) before single-field [x]
    def _bracket_repl(m: "re.Match") -> str:
        key = m.group(1).strip()
        # Composite: lat,lng → maps URL
        if "," in key:
            keys = [k.strip() for k in key.split(",")]
            if set(keys) == {"latitude", "longitude"} or keys == ["latitude", "longitude"]:
                return _format_maps_link(latitude, longitude)
            # Fallback: join with comma
            return ",".join(plain.get(k, "") for k in keys)
        # Single field link forms
        if key == "phone":
            return _format_phone_link(phone)
        if key == "whatsapp":
            digits = re.sub(r"[^\d]", "", whatsapp or "")
            return f"https://wa.me/{digits}" if digits else ""
        if key == "email":
            return f"mailto:{email}" if email else ""
        if key in ("latitude", "longitude"):
            return _format_maps_link(latitude, longitude)
        return plain.get(key, "")

    def _brace_repl(m: "re.Match") -> str:
        key = m.group(1).strip()
        return str(plain.get(key, ""))

    rendered = re.sub(r"\[([^\[\]]+)\]", _bracket_repl, template)
    rendered = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _brace_repl, rendered)
    # Clean up: collapse multiple spaces (introduced when a field was empty)
    # but preserve newlines.
    cleaned_lines = []
    for line in rendered.split("\n"):
        cleaned_lines.append(re.sub(r" +", " ", line).strip())
    # Drop empty lines that resulted purely from missing fields
    return "\n".join(l for l in cleaned_lines if l)


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



# ====================================================================
# Iter43-fix24j (2026-06) — Commandes publiques étendues : !adresse / !horaires / !stock
# ====================================================================
async def _wa_send_location(
    to_e164: str,
    *,
    latitude: float,
    longitude: float,
    name: Optional[str] = None,
    address: Optional[str] = None,
    settings_doc: Optional[Dict[str, Any]] = None,
    db_ref: Any = None,
) -> Dict[str, Any]:
    """Envoie un message WhatsApp de type `location` (carte avec aperçu Google Maps).

    Utilisé par `!adresse` pour partager la géolocalisation cliquable de l'enseigne
    — l'utilisateur peut ouvrir directement dans son app de cartographie.
    """
    s = settings_doc
    if s is None and db_ref is not None:
        s = await db_ref.settings.find_one({"_id": "global"}) or {}
    s = s or {}
    access_token = s.get("wa_access_token")
    phone_number_id = s.get("wa_phone_number_id")
    wa_graph_version = s.get("wa_graph_version") or "v22.0"
    if not access_token or not phone_number_id:
        return {"ok": False, "error": "WhatsApp non configuré (token ou phone_number_id manquant)"}
    to_clean = "".join(ch for ch in (to_e164 or "") if ch.isdigit())
    if len(to_clean) < 6:
        return {"ok": False, "error": f"Numéro invalide « {to_e164} »"}
    body = {
        "messaging_product": "whatsapp",
        "to": to_clean,
        "type": "location",
        "location": {
            "latitude": str(latitude),
            "longitude": str(longitude),
        },
    }
    if name:
        body["location"]["name"] = str(name)[:200]
    if address:
        body["location"]["address"] = str(address)[:500]
    url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=12) as http:
            r = await http.post(
                url, json=body,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            )
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:500]}
            if r.status_code < 300:
                mid = (raw.get("messages") or [{}])[0].get("id") if isinstance(raw, dict) else None
                return {"ok": True, "message_id": mid, "raw": raw}
            return {"ok": False, "error": str(raw)[:300], "status": r.status_code, "raw": raw}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


# ====================================================================
# Iter43-fix24al (2026-06-17) — `_wa_send_image` helper used by `!garde`
# to send the optional "click-here" capture image as a 2nd WA message.
#
# Accepts either an HTTPS URL (preferred — Meta downloads it) OR a
# data:image/...;base64,... URI (we strip the prefix and POST the bytes
# to /media first to get a media_id, then send by media_id).
# ====================================================================
async def _wa_send_image(
    to_e164: str,
    image_src: str,
    *,
    caption: Optional[str] = None,
    settings_doc: Optional[Dict[str, Any]] = None,
    db_ref=None,
) -> Dict[str, Any]:
    """Send a WhatsApp `image` message.

    Returns {"ok": bool, "message_id"?: str, "error"?: str}.
    Silently no-ops (returns ok=False) when WhatsApp is not configured —
    callers should not crash on this.
    """
    s = settings_doc
    if s is None and db_ref is not None:
        s = await db_ref.settings.find_one({"_id": "global"}) or {}
    s = s or {}
    access_token = s.get("wa_access_token")
    phone_number_id = s.get("wa_phone_number_id")
    wa_graph_version = s.get("wa_graph_version") or "v22.0"
    if not access_token or not phone_number_id:
        return {"ok": False, "error": "WhatsApp non configuré"}
    to_clean = "".join(ch for ch in (to_e164 or "") if ch.isdigit())
    if len(to_clean) < 6:
        return {"ok": False, "error": f"Numéro invalide « {to_e164} »"}
    if not image_src:
        return {"ok": False, "error": "image_src vide"}

    image_block: Dict[str, Any] = {}
    # data: URI → upload first to /media
    if image_src.startswith("data:image/"):
        try:
            import base64 as _b64
            header_part, b64_part = image_src.split(",", 1)
            mime = header_part.split(";")[0][5:]  # "image/png"
            blob = _b64.b64decode(b64_part)
            upload_url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/media"
            async with httpx.AsyncClient(timeout=20) as http:
                files = {"file": ("garde.png", blob, mime)}
                data = {"messaging_product": "whatsapp", "type": mime}
                ru = await http.post(
                    upload_url, headers={"Authorization": f"Bearer {access_token}"},
                    files=files, data=data,
                )
                try:
                    ru_json = ru.json()
                except Exception:
                    ru_json = {"text": ru.text[:500]}
                if ru.status_code >= 300:
                    return {"ok": False, "error": f"media upload failed: {ru_json}", "status": ru.status_code}
                media_id = ru_json.get("id")
                if not media_id:
                    return {"ok": False, "error": f"media upload: no id in {ru_json}"}
                image_block = {"id": media_id}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"data URI parse failed: {exc}"}
    elif image_src.startswith("http://") or image_src.startswith("https://"):
        image_block = {"link": image_src}
    else:
        return {"ok": False, "error": "image_src must be http(s):// or data:image/...;base64,..."}

    if caption:
        image_block["caption"] = str(caption)[:1024]

    body = {
        "messaging_product": "whatsapp",
        "to": to_clean,
        "type": "image",
        "image": image_block,
    }
    url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                url, json=body,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            )
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:500]}
            if r.status_code < 300:
                mid = (raw.get("messages") or [{}])[0].get("id") if isinstance(raw, dict) else None
                return {"ok": True, "message_id": mid, "raw": raw}
            return {"ok": False, "error": str(raw)[:300], "status": r.status_code, "raw": raw}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def _resolve_brand_info(settings_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Compose le profil "marque/HQ" affiché par les commandes publiques.

    Mélange les nouveaux champs `liluvine_wa_brand_*` (prioritaires) avec
    les anciens champs génériques (`company_phone`, `public_brand_name`, etc.).
    """
    s = settings_doc or {}

    def _pick(*keys: str) -> str:
        for k in keys:
            v = s.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _num(v: Any) -> Optional[float]:
        try:
            if v in (None, ""):
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "name": _pick("liluvine_wa_brand_name", "public_brand_name") or "SAWALI SMART SYSTEMS",
        "phone": _pick("liluvine_wa_brand_phone", "company_phone"),
        "whatsapp": _pick("liluvine_wa_brand_whatsapp", "liluvine_wa_brand_phone", "company_phone"),
        "email": _pick("liluvine_wa_brand_email"),
        "address": _pick("liluvine_wa_brand_address"),
        "city": _pick("liluvine_wa_brand_city"),
        "country": _pick("liluvine_wa_brand_country"),
        "location_hint": _pick("liluvine_wa_brand_location_hint"),
        "latitude": _num(s.get("liluvine_wa_brand_latitude")),
        "longitude": _num(s.get("liluvine_wa_brand_longitude")),
        "hours": _pick("liluvine_wa_brand_hours"),
        "maps_url": _pick("liluvine_wa_brand_maps_url"),
    }


def _build_maps_url(brand: Dict[str, Any]) -> str:
    """Génère l'URL Google Maps (priorité au champ personnalisé, sinon coords, sinon recherche texte)."""
    if brand.get("maps_url"):
        return brand["maps_url"]
    lat = brand.get("latitude")
    lon = brand.get("longitude")
    if lat is not None and lon is not None:
        return f"https://www.google.com/maps?q={lat},{lon}"
    bits = [brand.get("address"), brand.get("city"), brand.get("country")]
    q = ", ".join([b for b in bits if b])
    if q:
        import urllib.parse as _urlp
        return f"https://www.google.com/maps/search/?api=1&query={_urlp.quote(q)}"
    return ""


async def _build_adresse_reply(db) -> Dict[str, Any]:
    """Construit la réponse pour `!adresse`.

    Retourne un dict `{text, location}` :
      - `text` : message texte avec nom + phone + WA + adresse + lien maps
      - `location` : si lat/lon configurés → dict pour l'envoi WA type=location
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    brand = _resolve_brand_info(s)
    lines = [f"📍 *{brand['name']}*"]
    if brand["address"] or brand["city"]:
        addr_bits = [brand.get("address"), brand.get("city"), brand.get("country")]
        addr_full = ", ".join([b for b in addr_bits if b])
        lines.append(f"🏠 {addr_full}")
    if brand["location_hint"]:
        lines.append(f"🧭 {brand['location_hint']}")
    if brand["phone"]:
        lines.append(f"📞 {brand['phone']}")
    if brand["whatsapp"] and brand["whatsapp"] != brand["phone"]:
        lines.append(f"💬 WhatsApp : {brand['whatsapp']}")
    if brand["email"]:
        lines.append(f"✉️ {brand['email']}")
    maps_url = _build_maps_url(brand)
    if maps_url:
        lines.append(f"\n🗺️ Itinéraire : {maps_url}")
    if brand["hours"]:
        lines.append(f"\n🕒 *Horaires :*\n{brand['hours']}")
    lines.append("\n_— Liluvine PRO 🤖_")
    text = "\n".join(lines)
    location = None
    if brand["latitude"] is not None and brand["longitude"] is not None:
        location = {
            "latitude": brand["latitude"],
            "longitude": brand["longitude"],
            "name": brand["name"],
            "address": ", ".join(
                [b for b in [brand.get("address"), brand.get("city"), brand.get("country")] if b]
            ) or brand["location_hint"] or None,
        }
    return {"text": text, "location": location, "brand": brand}


_DAY_NAMES_FR = {
    0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi",
    4: "Vendredi", 5: "Samedi", 6: "Dimanche",
}


async def _build_horaires_reply(db) -> str:
    """Construit la réponse pour `!horaires`.

    Lit `liluvine_wa_brand_hours` (texte libre multi-lignes ou format `lun:08-19`).
    Marque visuellement le jour courant (➡️).
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    brand = _resolve_brand_info(s)
    today_idx = datetime.now(timezone.utc).weekday()  # 0=Mon ... 6=Sun
    if not brand["hours"]:
        return (
            f"🕒 *Horaires d'ouverture — {brand['name']}*\n\n"
            "_Les horaires ne sont pas encore configurés. "
            "Contactez-nous au "
            f"{brand['phone'] or '_(non renseigné)_'} pour plus d'info._\n\n"
            "_— Liluvine PRO 🤖_"
        )
    today_lbl = _DAY_NAMES_FR[today_idx].lower()
    out_lines = [f"🕒 *Horaires d'ouverture — {brand['name']}*", ""]
    found_today = False
    for raw in brand["hours"].splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower()
        if today_lbl in lower or lower.startswith(today_lbl[:3]):
            out_lines.append(f"➡️ *{line}*  ← _aujourd'hui_")
            found_today = True
        else:
            out_lines.append(f"   {line}")
    if not found_today:
        out_lines.append(f"\n_Nous sommes {_DAY_NAMES_FR[today_idx]}._")
    out_lines.append("\n_— Liluvine PRO 🤖_")
    return "\n".join(out_lines)


async def _build_stock_reply(db, args: str) -> str:
    """Construit la réponse pour `!stock <médicament>`.

    Recherche `args` (case-insensitive) dans `officine_inventory_items.product_name`,
    join avec `officines` pour récupérer le contact, retourne au max 5 résultats
    classés par quantité décroissante. Ne retourne que les items `available=True`
    avec `quantity > 0` et n'appartenant pas à une officine `suspended`.
    """
    query = (args or "").strip()
    if len(query) < 2:
        return (
            "❓ *Recherche de stock*\n\n"
            "Utilisation : `!stock <nom du médicament>`\n"
            "Exemple : `!stock paracétamol`\n\n"
            "_— Liluvine PRO 🤖_"
        )
    pattern = re.escape(query)
    items: List[Dict[str, Any]] = []
    cursor = db.officine_inventory_items.find(
        {
            "product_name": {"$regex": pattern, "$options": "i"},
            "available": True,
            "quantity": {"$gt": 0},
        },
        {"_id": 0, "officine_id": 1, "product_name": 1, "quantity": 1, "unit_price": 1, "currency": 1, "expiry_date": 1, "cip": 1},
    ).sort("quantity", -1).limit(20)
    async for it in cursor:
        items.append(it)
    if not items:
        return (
            f"🔎 *Recherche : « {query[:50]} »*\n\n"
            "❌ Aucune officine n'a ce produit en stock actuellement.\n\n"
            "_Conseil : essayez avec un nom plus court ou la marque générique._\n\n"
            "_— Liluvine PRO 🤖_"
        )
    officine_ids = list({it["officine_id"] for it in items})
    officines_map: Dict[str, Dict[str, Any]] = {}
    async for o in db.officines.find(
        {"id": {"$in": officine_ids}, "status": {"$ne": "suspended"}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "whatsapp": 1, "city": 1, "location_hint": 1, "latitude": 1, "longitude": 1},
    ):
        officines_map[o["id"]] = o
    items = [it for it in items if it["officine_id"] in officines_map]
    if not items:
        return (
            f"🔎 *Recherche : « {query[:50]} »*\n\n"
            "❌ Le produit existe mais aucune officine active ne le propose actuellement.\n\n"
            "_— Liluvine PRO 🤖_"
        )
    items = items[:5]
    lines = [f"💊 *Stock — « {query[:50]} »*", f"_{len(items)} officine{'s' if len(items) > 1 else ''} avec ce produit_", ""]
    for it in items:
        off = officines_map[it["officine_id"]]
        name = off.get("name") or "—"
        qty = it.get("quantity") or 0
        price = it.get("unit_price")
        currency = it.get("currency") or "XOF"
        line_bits = [f"🏥 *{name}*"]
        addr = ", ".join([b for b in [off.get("location_hint"), off.get("city")] if b])
        if addr:
            line_bits.append(f"  📍 {addr}")
        line_bits.append(f"  📦 {it.get('product_name')} — *{qty}* en stock")
        if price is not None:
            line_bits.append(f"  💰 {price:.0f} {currency}")
        ph = off.get("whatsapp") or off.get("phone")
        if ph:
            line_bits.append(f"  📞 {ph}")
        lines.append("\n".join(line_bits))
        lines.append("")
    lines.append("_💚 Prompt rétablissement !_")
    lines.append("\n_— Liluvine PRO 🤖_")
    return "\n".join(lines)



# ===========================================================================
# Iter43-fix24ac (2026-06-16) — Configurable VIDAL `!commands`
# ===========================================================================
async def _contact_has_vidal_subscription(db, phone_digits: str) -> bool:
    """Returns True if the contact identified by `phone_digits` carries
    the tag "Abonné VIDAL" in `db.contacts`. Used to gate access to
    non-public VIDAL actions over WhatsApp.

    The tag match is case-insensitive and tolerates the diacritic é/e.
    """
    if not phone_digits:
        return False
    # Normalize: VIDAL tag may be stored as "Abonné VIDAL" or "Abonne VIDAL".
    targets = {"abonné vidal", "abonne vidal"}
    contact = await db.contacts.find_one({"phone_digits": phone_digits}) or {}
    if not contact:
        contact = await db.contacts.find_one({"phone": {"$regex": phone_digits[-9:] if len(phone_digits) >= 9 else phone_digits}})
        contact = contact or {}
    tags = contact.get("tags") or contact.get("labels") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    norm = {(t or "").strip().lower() for t in tags if t}
    return bool(norm & targets)


async def _build_vidal_reply(db, command_token: str, command_args: str,
                              phone_digits: str) -> Optional[Dict[str, Any]]:
    """Try to resolve and execute a VIDAL action for an inbound `!cmd args`.

    Returns:
      - None if the command does NOT match any configured VIDAL action
        (so the caller falls through to other handlers)
      - {"text": str, "action_id": str, "denied": bool} if matched
    """
    try:
        from routes.vidal_actions import get_vidal_actions, find_action_by_command, render_action
        from routes.vidal import _load_config, _vidal_call, _ensure_active
    except Exception:  # noqa: BLE001
        logger.exception("[wa_autoreply][vidal] failed to import VIDAL modules")
        return None
    actions = await get_vidal_actions(db)
    action = find_action_by_command(actions, command_token)
    if not action:
        return None
    # Access control : public OR contact has "Abonné VIDAL" tag.
    is_public = bool(action.get("is_public"))
    if not is_public:
        subscribed = await _contact_has_vidal_subscription(db, phone_digits)
        if not subscribed:
            return {
                "text": (
                    f"🔒 La commande `!{command_token}` est réservée aux abonnés VIDAL.\n\n"
                    "Pour y accéder, contactez votre pharmacien afin de souscrire "
                    "à l'option **Abonné VIDAL**."
                ),
                "action_id": action.get("id"),
                "denied": True,
            }
    # Build the user_input dict from the trailing args.
    args_clean = (command_args or "").strip()
    input_param = action.get("input_param") or "q"
    user_input: Dict[str, Any] = {input_param: args_clean}
    # Special case : `interactions` needs two ids → split on whitespace.
    if action.get("id") == "interactions":
        parts = args_clean.split()
        user_input = {"id1": parts[0] if len(parts) >= 1 else "", "id2": parts[1] if len(parts) >= 2 else ""}
    # Execute the call.
    try:
        cfg = await _load_config(db)
        _ensure_active(cfg)
        rendered = render_action(action, user_input)
        data = await _vidal_call(
            cfg, rendered["method"], rendered["path"],
            params=rendered["params"], body=rendered["body"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[wa_autoreply][vidal] call failed for %s", command_token)
        return {
            "text": (
                f"⚠️ Désolé, impossible d'interroger VIDAL pour `!{command_token}` "
                f"actuellement.\n_Erreur : {str(exc)[:120]}_"
            ),
            "action_id": action.get("id"),
            "denied": False,
        }
    # Format the response : prefer Atom entries, else short JSON snippet.
    if (data or {}).get("_error"):
        err = data["_error"]
        return {
            "text": (
                f"❌ VIDAL a refusé la requête `!{command_token}` "
                f"(HTTP {err.get('status')}).\n\n_{err.get('message') or '—'}_"
            ),
            "action_id": action.get("id"),
            "denied": False,
        }
    text = _format_vidal_data_for_wa(action, data)
    return {"text": text, "action_id": action.get("id"), "denied": False}


def _format_vidal_data_for_wa(action: Dict[str, Any], data: Dict[str, Any]) -> str:
    """Format a VIDAL response into a short WhatsApp-friendly text block.

    Iter43-fix24aq (2026-06-17) — Inclut le code produit `<vidal:id>` entre
    parenthèses pour chaque entrée (ex: « 1. DOLIPRANE 100 mg ... (5485) »).
    Extraction par regex sur le XML brut entry-par-entry (pas besoin d'un
    parser DOM côté backend).
    """
    label = action.get("label") or action.get("id")
    head = f"📋 *{label}*"
    raw = data.get("raw") if isinstance(data, dict) else None
    # Try to parse Atom entries from raw XML.
    if isinstance(raw, str) and "<entry" in raw:
        # Split on <entry ...> ... </entry> blocks and extract title + vidal:id per block
        entry_blocks = re.findall(r"<entry\b[^>]*>(.*?)</entry>", raw, flags=re.DOTALL | re.IGNORECASE)
        items: list = []
        for block in entry_blocks:
            title_m = re.search(r"<title[^>]*>([^<]+)</title>", block, flags=re.IGNORECASE)
            title = (title_m.group(1) if title_m else "").strip()
            if not title:
                continue
            # Look for <vidal:id>NNNN</vidal:id> OR <*:id>NNNN</*:id> (any prefix)
            vidal_id_m = re.search(r"<(?:[a-z][a-z0-9]*:)?id>\s*(\d+)\s*</(?:[a-z][a-z0-9]*:)?id>", block, flags=re.IGNORECASE)
            if not vidal_id_m:
                # Fallback: extract trailing digits from atom <id>vidal://product/5485</id>
                atom_id_m = re.search(r"<id[^>]*>([^<]+)</id>", block, flags=re.IGNORECASE)
                if atom_id_m:
                    trailing = re.search(r"(\d+)\s*$", atom_id_m.group(1))
                    if trailing:
                        vidal_id_m = trailing
            vidal_id = vidal_id_m.group(1) if vidal_id_m else ""
            items.append((title, vidal_id))
        if items:
            lines = [head, ""]
            for i, (t, code) in enumerate(items[:8], 1):
                if code:
                    lines.append(f"{i}. {t} (*{code}*)")
                else:
                    lines.append(f"{i}. {t}")
            if len(items) > 8:
                lines.append(f"… (+{len(items) - 8} résultats non affichés)")
            return "\n".join(lines)
        return f"{head}\n\n_Aucun résultat trouvé._"
    # JSON dict fallback
    if isinstance(data, dict) and data.get("entries"):
        entries = data["entries"][:8]
        lines = [head, ""]
        for i, e in enumerate(entries, 1):
            title = (e or {}).get("title") or (e or {}).get("name") or "?"
            code = (e or {}).get("vidal_id") or (e or {}).get("id") or ""
            if isinstance(code, str) and code.isdigit():
                lines.append(f"{i}. {title} (*{code}*)")
            else:
                lines.append(f"{i}. {title}")
        return "\n".join(lines)
    # Anything else → just confirm the call worked
    return f"{head}\n\n_Réponse VIDAL reçue ({len(str(data))} caractères). Consultez le portail pour le détail._"
