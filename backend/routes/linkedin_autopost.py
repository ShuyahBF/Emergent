"""Iter43-fix24av (2026-02-26) — LinkedIn weekly auto-post (Liluvine-generated).

Allows SAWALI to publish a weekly LinkedIn post automatically. Each week at
the configured day/time, the scheduler :
  1. Calls Claude Sonnet 4.5 (via Emergent LLM key) with the user's prompt
     seed + recent SAWALI context (latest officines, last Iter, etc.)
  2. Stores the generated draft in `db.settings.linkedin_autopost_pending_draft`
  3. If `validation_mode == "auto"` → publishes immediately
  4. If `validation_mode == "wa_approval"` → sends the draft via WhatsApp to
     the configured admin phone with reply instructions ("OK" to publish,
     "STOP" to cancel, "REGEN" to regenerate). The actual WA reply handling
     lives in the WhatsApp router (server.py).

Stored in `settings.global` :
  - `linkedin_autopost_enabled` (bool)
  - `linkedin_autopost_day_of_week` (0=Mon … 6=Sun, default 4=Fri)
  - `linkedin_autopost_hour` (0-23, default 9)
  - `linkedin_autopost_minute` (0-59, default 0)
  - `linkedin_autopost_topic_prompt` (str, custom seed used in LLM prompt)
  - `linkedin_autopost_author_type` ("member" | "organization")
  - `linkedin_autopost_organization_urn` (str if org)
  - `linkedin_autopost_validation_mode` ("auto" | "wa_approval")
  - `linkedin_autopost_validation_phone` (E.164 str — receives draft for approval)
  - `linkedin_autopost_last_run_at` (datetime)
  - `linkedin_autopost_last_post_urn` (str)
  - `linkedin_autopost_pending_draft` (object: {text, image_url?, created_at, sent_to_wa_at?})
  - `linkedin_autopost_history` (list of {date, post_urn, text_preview})

Public functions exported :
  - `attach_linkedin_autopost_routes(api, db, …)` — mounts CRUD endpoints
  - `run_linkedin_autopost_tick(db, …)` — to be called minute by minute
  - `handle_linkedin_autopost_wa_reply(db, …, phone, text)` — invoked by WA
    router when a reply is received from the validation_phone
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.linkedin.autopost")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


# Default prompt seed
DEFAULT_TOPIC_PROMPT = (
    "Génère un post LinkedIn engageant en français pour SAWALI SMART SYSTEMS, "
    "éditeur de logiciels au Burkina Faso (Ouagadougou). Notre offre phare : "
    "Liluvine PRO — assistant IA pour officines pharmaceutiques + CRM "
    "complet (WhatsApp, paiements PawaPay/Stripe, RGPD, prescription VIDAL).\n\n"
    "Style : professionnel mais accessible, 2-3 paragraphes courts, "
    "pas d'emoji excessif, max 1500 caractères. Termine par un appel à l'action "
    "(visiter le site, demander une démo).\n\n"
    "⚠️ IMPÉRATIF : la DERNIÈRE ligne du post DOIT contenir EXACTEMENT 5 "
    "hashtags séparés par des espaces — choisis-les pertinents parmi : "
    "#PharmacieAfrique #DigitalHealth #BurkinaFaso #IntelligenceArtificielle "
    "#LiluvinePro #Pharmacien #SantéNumérique #Sahel #Afrique #SAWALI #CRM. "
    "Aucun post n'est valide sans cette ligne finale de hashtags.\n\n"
    "Cette semaine, parle de [SUJET ALÉATOIRE PARMI : "
    "(1) bénéfices de la digitalisation des officines au Sahel, "
    "(2) conformité RGPD et anonymisation patient en Afrique de l'Ouest, "
    "(3) IA générative au service du pharmacien, "
    "(4) WhatsApp comme canal médical sécurisé, "
    "(5) prescription assistée VIDAL pour réduire les interactions médicamenteuses]."
)

# Fallback hashtags appended server-side if the LLM forgot (rare but possible)
FALLBACK_HASHTAGS = "#LiluvinePro #PharmacieAfrique #DigitalHealth #BurkinaFaso #SAWALI"


# --------------------------------------------------------------------------- #
# Payloads
# --------------------------------------------------------------------------- #
class AutopostConfigPayload(BaseModel):
    enabled: Optional[bool] = None
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    hour: Optional[int] = Field(None, ge=0, le=23)
    minute: Optional[int] = Field(None, ge=0, le=59)
    topic_prompt: Optional[str] = None
    author_type: Optional[str] = None  # "member" | "organization"
    organization_urn: Optional[str] = None
    validation_mode: Optional[str] = None  # "auto" | "wa_approval"
    validation_phone: Optional[str] = None
    # Iter43-fix24ax — Multi-canal social
    also_post_twitter: Optional[bool] = None
    also_post_facebook: Optional[bool] = None


# --------------------------------------------------------------------------- #
# Draft generation (Claude Sonnet 4.5 via Emergent LLM key)
# --------------------------------------------------------------------------- #
async def _generate_draft(db, topic_prompt: str, session_id: str) -> str:
    """Generate a LinkedIn post draft using Claude Sonnet 4.5.

    Returns the draft text. Raises HTTPException on failure.
    """
    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    if not emergent_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY non configurée")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"Bibliothèque IA absente : {exc}") from exc

    # Pull a little business context (best-effort)
    context_lines: List[str] = []
    try:
        offc_count = await db.officines.count_documents({})
        if offc_count:
            context_lines.append(f"- {offc_count} officines partenaires dans la base SAWALI")
    except Exception:  # noqa: BLE001
        pass
    try:
        wa_msg_count = await db.whatsapp_messages.count_documents({})
        if wa_msg_count:
            context_lines.append(f"- {wa_msg_count} messages WhatsApp traités jusqu'à présent")
    except Exception:  # noqa: BLE001
        pass

    sys_msg = (
        "Tu es un community manager senior pour SAWALI SMART SYSTEMS. "
        "Tu rédiges UNIQUEMENT le texte du post LinkedIn — pas de markdown, "
        "pas de '```', pas de commentaires sur le post. Maximum 1500 caractères. "
        "Pas d'emoji excessif. Toujours en français. Toujours avec un appel à l'action."
    )
    user_msg = topic_prompt
    if context_lines:
        user_msg += "\n\nContexte interne SAWALI (à utiliser si pertinent) :\n" + "\n".join(context_lines)

    try:
        chat = LlmChat(
            api_key=emergent_key,
            session_id=session_id,
            system_message=sys_msg,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        raw = (await chat.send_message(UserMessage(text=user_msg))) or ""
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Génération IA échouée : {str(exc)[:200]}") from exc

    # Cleanup
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
    # Iter43-fix24av-fix1 — Ensure at least one hashtag is present (rare but
    # Claude occasionally omits them). Append the fallback set on the last
    # line if none found.
    if "#" not in text:
        text = text.rstrip() + "\n\n" + FALLBACK_HASHTAGS
    # Hard cap at 3000 chars (LinkedIn max), but the prompt asks for 1500
    if len(text) > 3000:
        text = text[:2997] + "…"
    return text


# --------------------------------------------------------------------------- #
# WhatsApp notification helper
# --------------------------------------------------------------------------- #
async def _send_wa_draft(db, phone: str, draft_text: str) -> bool:
    """Send the draft to the validation phone via WhatsApp (Meta API)."""
    try:
        # Re-use the existing WA send function from server (avoids circular import)
        import server  # noqa: WPS433
        msg_body = (
            "🤖 *Brouillon LinkedIn auto-post hebdomadaire*\n\n"
            "Voici le post généré par Liluvine pour publication aujourd'hui :\n\n"
            "—————————————\n"
            f"{draft_text}\n"
            "—————————————\n\n"
            "📲 Répondez :\n"
            "• *OK* pour publier maintenant\n"
            "• *STOP* pour annuler ce brouillon\n"
            "• *REGEN* pour régénérer un autre texte"
        )
        send_fn = getattr(server, "_wa_send_text", None)
        if not callable(send_fn):
            logger.warning("[linkedin.autopost] _wa_send_text not found in server module")
            return False
        result = await send_fn(phone, msg_body)
        return bool(result and not result.get("error"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[linkedin.autopost] WA send error: %s", exc)
        return False


# --------------------------------------------------------------------------- #
# Publication helper — reuses the same logic as routes/linkedin.py
# --------------------------------------------------------------------------- #
async def _publish_draft(db, draft_text: str, image_url: Optional[str] = None) -> str:
    """Publish the draft directly via the same logic as /api/linkedin/posts."""
    from routes.linkedin import (
        _ensure_token_valid,
        _create_post,
        _upload_image_from_url,
        _load_settings,
    )
    s = await _load_settings(db)
    access = await _ensure_token_valid(db, s)
    author_type = s.get("linkedin_autopost_author_type") or "member"
    if author_type == "organization":
        org_urn = s.get("linkedin_autopost_organization_urn") or ""
        allowed = {o.get("urn") for o in (s.get("linkedin_organizations") or [])}
        if not org_urn or org_urn not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"organization_urn invalide ou non autorisée : {org_urn}",
            )
        author_urn = org_urn
    else:
        author_urn = s.get("linkedin_member_urn") or ""
        if not author_urn:
            raise HTTPException(status_code=400, detail="member_urn manquant. Reconnectez LinkedIn.")

    image_urn = None
    if image_url:
        image_urn = await _upload_image_from_url(access, author_urn, image_url)
    post_urn = await _create_post(access, author_urn, draft_text, image_urn)

    # Persist history + clear pending
    await db.settings.update_one(
        {"_id": "global"},
        {
            "$set": {
                "linkedin_autopost_last_post_urn": post_urn,
                "linkedin_autopost_last_run_at": _now_iso(),
                "linkedin_autopost_pending_draft": None,
            },
            "$push": {
                "linkedin_autopost_history": {
                    "$each": [{
                        "date": _now_iso(),
                        "post_urn": post_urn,
                        "text_preview": draft_text[:200],
                        "author_type": author_type,
                        "author_urn": author_urn,
                    }],
                    "$slice": -20,  # keep only last 20
                }
            },
        },
    )
    return post_urn


def _shorten_for_twitter(text: str, max_len: int = 270) -> str:
    """Twitter limit is 280 chars. We keep 270 to leave room for URL shortener
    artifacts. Truncate intelligently at the last whitespace before max_len-1
    and append « … »."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len - 1]
    sp = cut.rfind(" ")
    if sp > max_len // 2:
        cut = cut[:sp]
    return cut.rstrip() + "…"


async def _publish_multi_channel(db, draft_text: str, image_url: Optional[str] = None) -> Dict[str, Any]:
    """Publish the draft on LinkedIn (always) + Twitter + Facebook (if enabled
    in settings.global). Returns a dict with per-channel result."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    results: Dict[str, Any] = {"linkedin": None, "twitter": None, "facebook": None}

    # 1) LinkedIn (mandatory — the autopost feature is anchored on LinkedIn)
    try:
        results["linkedin"] = await _publish_draft(db, draft_text, image_url)
    except HTTPException as exc:
        results["linkedin"] = {"_error": exc.detail}

    # 2) Twitter (if enabled and connected)
    if s.get("linkedin_autopost_also_post_twitter") and s.get("twitter_access_token"):
        try:
            from routes.twitter import _ensure_token_valid as _tw_ensure, _post_tweet, _upload_media_from_url
            access = await _tw_ensure(db, s)
            short_text = _shorten_for_twitter(draft_text)
            media_id = None
            if image_url:
                try:
                    media_id = await _upload_media_from_url(access, image_url)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[linkedin.autopost] Twitter media skip: %s", exc)
            tw_res = await _post_tweet(access, short_text, media_id)
            tweet_id = (tw_res.get("data") or {}).get("id", "")
            results["twitter"] = {"tweet_id": tweet_id, "shortened_len": len(short_text)}
        except Exception as exc:  # noqa: BLE001
            results["twitter"] = {"_error": str(exc)[:200]}

    # 3) Facebook (if enabled and Page configured)
    if s.get("linkedin_autopost_also_post_facebook") and s.get("facebook_page_id") and s.get("facebook_page_access_token"):
        try:
            from routes.facebook import _post_to_page
            fb_res = await _post_to_page(s["facebook_page_id"], s["facebook_page_access_token"], draft_text, image_url)
            post_id = fb_res.get("id") or fb_res.get("post_id", "")
            results["facebook"] = {"post_id": post_id}
        except Exception as exc:  # noqa: BLE001
            results["facebook"] = {"_error": str(exc)[:200]}

    return results


# --------------------------------------------------------------------------- #
# Scheduler tick — invoked every minute by APScheduler
# --------------------------------------------------------------------------- #
async def run_linkedin_autopost_tick(db):
    """Called by APScheduler every minute. Generates + publishes the weekly
    LinkedIn post if the current time matches the configured day/hour/minute.

    Safety :
      - Idempotent : if `linkedin_autopost_last_run_at` is < 60 min ago, skip.
      - Honors `enabled` toggle.
      - Falls back gracefully on errors (logs only, never raises).
    """
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("linkedin_autopost_enabled"):
            return
        if not s.get("linkedin_access_token"):
            return  # LinkedIn not connected
        now = datetime.now()  # local time (Africa/Abidjan is set on scheduler)
        # Match day_of_week + hour + minute
        # Python: Mon=0 … Sun=6 — same as our config
        if now.weekday() != int(s.get("linkedin_autopost_day_of_week", 4)):
            return
        if now.hour != int(s.get("linkedin_autopost_hour", 9)):
            return
        if now.minute != int(s.get("linkedin_autopost_minute", 0)):
            return
        # Idempotency : skip if a post was already made in the last 60 min
        last_run = s.get("linkedin_autopost_last_run_at")
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run)
                if (datetime.now(timezone.utc) - last_dt.replace(tzinfo=timezone.utc)).total_seconds() < 3600:
                    return
            except (TypeError, ValueError):
                pass

        prompt = s.get("linkedin_autopost_topic_prompt") or DEFAULT_TOPIC_PROMPT
        validation_mode = s.get("linkedin_autopost_validation_mode") or "wa_approval"
        validation_phone = (s.get("linkedin_autopost_validation_phone") or "").strip()

        logger.info("[linkedin.autopost] Trigger — mode=%s phone=%s", validation_mode, validation_phone)

        # Generate the draft
        session_id = f"linkedin-autopost-{now.strftime('%Y%m%d-%H%M')}"
        try:
            draft = await _generate_draft(db, prompt, session_id)
        except HTTPException as exc:
            logger.error("[linkedin.autopost] Draft generation failed: %s", exc.detail)
            return

        # Persist the draft as pending
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"linkedin_autopost_pending_draft": {
                "text": draft,
                "image_url": None,
                "created_at": _now_iso(),
                "sent_to_wa_at": None,
            }}},
        )

        if validation_mode == "auto":
            # Publish immediately on LinkedIn + Twitter + Facebook (selon config)
            try:
                multi = await _publish_multi_channel(db, draft)
                logger.info("[linkedin.autopost] AUTO multi-channel published → %s", multi)
                # Notify on WA if a phone is configured
                if validation_phone:
                    import server  # noqa: WPS433
                    send_fn = getattr(server, "_wa_send_text", None)
                    if callable(send_fn):
                        summary_lines = ["🤖 ✅ Post hebdomadaire AUTO-publié."]
                        if isinstance(multi.get("linkedin"), str):
                            summary_lines.append(f"• LinkedIn : {multi['linkedin']}")
                        elif multi.get("linkedin"):
                            summary_lines.append(f"• LinkedIn : ❌ {multi['linkedin'].get('_error','?')}")
                        if multi.get("twitter"):
                            tw = multi["twitter"]
                            summary_lines.append(f"• Twitter : {tw.get('tweet_id') or '❌ ' + str(tw.get('_error',''))}")
                        if multi.get("facebook"):
                            fb = multi["facebook"]
                            summary_lines.append(f"• Facebook : {fb.get('post_id') or '❌ ' + str(fb.get('_error',''))}")
                        summary_lines.append(f"\nTexte (200c) : {draft[:200]}…")
                        await send_fn(validation_phone, "\n".join(summary_lines))
            except HTTPException as exc:
                logger.error("[linkedin.autopost] AUTO publish failed: %s", exc.detail)
        else:
            # wa_approval : send to WA + wait for reply
            if not validation_phone:
                logger.warning("[linkedin.autopost] wa_approval mode but no validation_phone configured")
                return
            sent = await _send_wa_draft(db, validation_phone, draft)
            if sent:
                await db.settings.update_one(
                    {"_id": "global"},
                    {"$set": {"linkedin_autopost_pending_draft.sent_to_wa_at": _now_iso()}},
                )
                logger.info("[linkedin.autopost] Draft sent to WA %s for approval", validation_phone)
            else:
                logger.warning("[linkedin.autopost] WA send to %s failed", validation_phone)
    except Exception as exc:  # noqa: BLE001
        logger.error("[linkedin.autopost] Tick error: %s", exc, exc_info=True)


# --------------------------------------------------------------------------- #
# WhatsApp reply handler — to be called from server.py WA router
# --------------------------------------------------------------------------- #
async def handle_linkedin_autopost_wa_reply(db, phone: str, text: str) -> Optional[str]:
    """If `text` matches OK/STOP/REGEN AND a pending draft exists from this
    phone, act on it. Returns a reply text to send back to WA (or None if not
    handled — caller continues normal routing).
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    pending = s.get("linkedin_autopost_pending_draft")
    if not pending:
        return None
    cfg_phone = (s.get("linkedin_autopost_validation_phone") or "").strip()
    # Normalize: strip + and whitespace
    if not cfg_phone:
        return None
    if phone.lstrip("+").strip() != cfg_phone.lstrip("+").strip():
        return None
    cmd = (text or "").strip().lower()
    if cmd in ("ok", "valider", "publier", "yes", "oui", "go"):
        try:
            multi = await _publish_multi_channel(db, pending["text"], pending.get("image_url"))
            lines = ["✅ Publication multi-canal effectuée :"]
            if isinstance(multi.get("linkedin"), str):
                lines.append(f"• LinkedIn : {multi['linkedin']}")
            elif multi.get("linkedin"):
                lines.append(f"• LinkedIn : ❌ {multi['linkedin'].get('_error','?')}")
            if multi.get("twitter"):
                lines.append(f"• Twitter : {multi['twitter'].get('tweet_id') or '❌'}")
            if multi.get("facebook"):
                lines.append(f"• Facebook : {multi['facebook'].get('post_id') or '❌'}")
            return "\n".join(lines)
        except HTTPException as exc:
            return f"❌ Échec publication : {exc.detail}"
    if cmd in ("stop", "annuler", "cancel", "non", "no"):
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"linkedin_autopost_pending_draft": None}},
        )
        return "🛑 Brouillon LinkedIn annulé. Aucune publication."
    if cmd in ("regen", "regenerer", "rerun", "retry", "again"):
        prompt = s.get("linkedin_autopost_topic_prompt") or DEFAULT_TOPIC_PROMPT
        try:
            new_draft = await _generate_draft(db, prompt, f"linkedin-autopost-regen-{_now_iso()}")
        except HTTPException as exc:
            return f"❌ Régénération échouée : {exc.detail}"
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"linkedin_autopost_pending_draft": {
                "text": new_draft,
                "image_url": None,
                "created_at": _now_iso(),
                "sent_to_wa_at": _now_iso(),
            }}},
        )
        return (
            "🔄 *Nouveau brouillon LinkedIn généré*\n\n"
            "—————————————\n"
            f"{new_draft}\n"
            "—————————————\n\n"
            "Répondez : *OK* (publier) | *STOP* (annuler) | *REGEN* (relancer)"
        )
    return None


# --------------------------------------------------------------------------- #
# Route mounting
# --------------------------------------------------------------------------- #
def attach_linkedin_autopost_routes(*, api, db, get_current_admin):
    """Mount the admin CRUD endpoints under `/api/admin/linkedin/autopost/*`."""

    @api.get("/admin/linkedin/autopost/config", tags=["Admin — LinkedIn"])
    async def get_autopost_config(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {
            "enabled": bool(s.get("linkedin_autopost_enabled")),
            "day_of_week": int(s.get("linkedin_autopost_day_of_week", 4)),
            "hour": int(s.get("linkedin_autopost_hour", 9)),
            "minute": int(s.get("linkedin_autopost_minute", 0)),
            "topic_prompt": s.get("linkedin_autopost_topic_prompt") or DEFAULT_TOPIC_PROMPT,
            "author_type": s.get("linkedin_autopost_author_type") or "member",
            "organization_urn": s.get("linkedin_autopost_organization_urn") or "",
            "validation_mode": s.get("linkedin_autopost_validation_mode") or "wa_approval",
            "validation_phone": s.get("linkedin_autopost_validation_phone") or "",
            "also_post_twitter": bool(s.get("linkedin_autopost_also_post_twitter")),
            "also_post_facebook": bool(s.get("linkedin_autopost_also_post_facebook")),
            "last_run_at": s.get("linkedin_autopost_last_run_at"),
            "last_post_urn": s.get("linkedin_autopost_last_post_urn") or "",
            "pending_draft": s.get("linkedin_autopost_pending_draft"),
            "history": (s.get("linkedin_autopost_history") or [])[-10:],
        }

    @api.put("/admin/linkedin/autopost/config", tags=["Admin — LinkedIn"])
    async def put_autopost_config(
        payload: AutopostConfigPayload = Body(...),
        user: dict = Depends(get_current_admin),
    ) -> Dict[str, Any]:
        update: Dict[str, Any] = {}
        if payload.enabled is not None:
            update["linkedin_autopost_enabled"] = bool(payload.enabled)
        if payload.day_of_week is not None:
            update["linkedin_autopost_day_of_week"] = int(payload.day_of_week)
        if payload.hour is not None:
            update["linkedin_autopost_hour"] = int(payload.hour)
        if payload.minute is not None:
            update["linkedin_autopost_minute"] = int(payload.minute)
        if payload.topic_prompt is not None:
            update["linkedin_autopost_topic_prompt"] = (payload.topic_prompt or "").strip()
        if payload.author_type is not None:
            if payload.author_type not in ("member", "organization"):
                raise HTTPException(status_code=400, detail="author_type doit être 'member' ou 'organization'")
            update["linkedin_autopost_author_type"] = payload.author_type
        if payload.organization_urn is not None:
            update["linkedin_autopost_organization_urn"] = payload.organization_urn.strip()
        if payload.validation_mode is not None:
            if payload.validation_mode not in ("auto", "wa_approval"):
                raise HTTPException(status_code=400, detail="validation_mode doit être 'auto' ou 'wa_approval'")
            update["linkedin_autopost_validation_mode"] = payload.validation_mode
        if payload.validation_phone is not None:
            update["linkedin_autopost_validation_phone"] = payload.validation_phone.strip()
        # Iter43-fix24ax — Multi-canal social toggles
        if payload.also_post_twitter is not None:
            update["linkedin_autopost_also_post_twitter"] = bool(payload.also_post_twitter)
        if payload.also_post_facebook is not None:
            update["linkedin_autopost_also_post_facebook"] = bool(payload.also_post_facebook)
        if not update:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
        update["linkedin_autopost_config_updated_at"] = _now_iso()
        update["linkedin_autopost_config_updated_by"] = user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": update}, upsert=True)
        return {"ok": True, "updated": list(update.keys())}

    @api.post("/admin/linkedin/autopost/generate-draft", tags=["Admin — LinkedIn"])
    async def generate_draft_now(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        """Manually generate a draft without scheduling it. Useful for testing
        the prompt + preview."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        prompt = s.get("linkedin_autopost_topic_prompt") or DEFAULT_TOPIC_PROMPT
        draft = await _generate_draft(db, prompt, f"linkedin-autopost-manual-{_now_iso()}")
        # Persist as pending for review
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"linkedin_autopost_pending_draft": {
                "text": draft,
                "image_url": None,
                "created_at": _now_iso(),
                "sent_to_wa_at": None,
            }}},
        )
        return {"ok": True, "draft": draft, "length": len(draft)}

    @api.post("/admin/linkedin/autopost/publish-pending", tags=["Admin — LinkedIn"])
    async def publish_pending(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        pending = s.get("linkedin_autopost_pending_draft")
        if not pending or not pending.get("text"):
            raise HTTPException(status_code=400, detail="Aucun brouillon en attente")
        multi = await _publish_multi_channel(db, pending["text"], pending.get("image_url"))
        return {"ok": True, "channels": multi}

    @api.delete("/admin/linkedin/autopost/pending", tags=["Admin — LinkedIn"])
    async def delete_pending(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"linkedin_autopost_pending_draft": None}},
        )
        return {"ok": True}

    @api.post("/admin/linkedin/autopost/tick-now", tags=["Admin — LinkedIn"])
    async def tick_now(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        """Force-run the autopost tick (bypasses the day/hour/minute check).
        Useful for end-to-end testing. Idempotency guard still active."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not s.get("linkedin_autopost_enabled"):
            raise HTTPException(status_code=400, detail="Auto-post désactivé")
        if not s.get("linkedin_access_token"):
            raise HTTPException(status_code=400, detail="LinkedIn non connecté")
        prompt = s.get("linkedin_autopost_topic_prompt") or DEFAULT_TOPIC_PROMPT
        draft = await _generate_draft(db, prompt, f"linkedin-autopost-tick-{_now_iso()}")
        validation_mode = s.get("linkedin_autopost_validation_mode") or "wa_approval"
        validation_phone = (s.get("linkedin_autopost_validation_phone") or "").strip()
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"linkedin_autopost_pending_draft": {
                "text": draft, "image_url": None, "created_at": _now_iso(), "sent_to_wa_at": None,
            }}},
        )
        if validation_mode == "auto":
            multi = await _publish_multi_channel(db, draft)
            return {"ok": True, "mode": "auto", "channels": multi, "draft": draft}
        # WA approval
        sent = False
        if validation_phone:
            sent = await _send_wa_draft(db, validation_phone, draft)
            if sent:
                await db.settings.update_one(
                    {"_id": "global"},
                    {"$set": {"linkedin_autopost_pending_draft.sent_to_wa_at": _now_iso()}},
                )
        return {"ok": True, "mode": "wa_approval", "draft": draft, "wa_sent": sent, "phone": validation_phone}

    logger.info("[linkedin.autopost] routes mounted under /api/admin/linkedin/autopost/*")
