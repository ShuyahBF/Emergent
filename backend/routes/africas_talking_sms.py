"""Iter43-fix23 (2026-06) — Africa's Talking Two-Way SMS Integration.

Permet aux clients en zones à faible couverture internet (notamment au Burkina
Faso) d'envoyer un SMS standard à Liluvine et de recevoir une réponse IA.

Architecture :
  - Webhook entrant : `POST /api/webhooks/africas-talking/incoming-sms`
    Africa's Talking POST y envoie chaque SMS reçu sur le shortcode/Sender ID.
    Le payload contient (form-encoded) :
      from   : numéro de l'expéditeur (E.164)
      to     : shortcode / sender ID
      text   : corps du message
      date   : ISO timestamp
      id     : identifiant unique du message
      linkId : (optionnel) pour tracer la conversation
  - Webhook delivery reports : `POST /api/webhooks/africas-talking/delivery-report`
  - Envoi sortant via le SDK Python `africastalking` (sms.send).

Toutes les credentials sont stockées dans `settings.global` :
  - africas_talking_enabled       : bool — toggle maître
  - africas_talking_env           : "sandbox" | "live"
  - africas_talking_username      : str ("sandbox" pour mode sandbox)
  - africas_talking_api_key       : str (sensible, masqué en GET)
  - africas_talking_shortcode     : str (ex. "15555" pour sandbox)
  - africas_talking_signature     : str (signature optionnelle ajoutée à chaque réponse)
  - africas_talking_use_liluvine  : bool — si true, route vers Liluvine pour réponse IA

Sécurité :
  - Africa's Talking ne signe pas les webhooks par défaut. On ajoute un secret
    optionnel `africas_talking_webhook_secret` dans le path/query si besoin.

Tous les SMS sont logués dans la collection `africas_talking_sms_messages`.
"""
from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Body, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

logger = logging.getLogger("sawali.africas_talking_sms")


class ATSendPayload(BaseModel):
    to: str
    text: str
    sender: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


async def _get_at_config(db) -> Dict[str, Any]:
    """Récupère la configuration Africa's Talking depuis settings.global."""
    s = await db.settings.find_one(
        {"_id": "global"},
        {
            "_id": 0,
            "africas_talking_enabled": 1,
            "africas_talking_env": 1,
            "africas_talking_username": 1,
            "africas_talking_api_key": 1,
            "africas_talking_shortcode": 1,
            "africas_talking_signature": 1,
            "africas_talking_use_liluvine": 1,
            "africas_talking_webhook_secret": 1,
        },
    ) or {}
    return {
        "enabled": bool(s.get("africas_talking_enabled")),
        "env": (s.get("africas_talking_env") or "sandbox").lower(),
        "username": (s.get("africas_talking_username") or "").strip(),
        "api_key": (s.get("africas_talking_api_key") or "").strip(),
        "shortcode": (s.get("africas_talking_shortcode") or "").strip() or None,
        "signature": (s.get("africas_talking_signature") or "").strip(),
        "use_liluvine": bool(s.get("africas_talking_use_liluvine", True)),
        "webhook_secret": (s.get("africas_talking_webhook_secret") or "").strip() or None,
    }


def _init_sdk(cfg: Dict[str, Any]):
    """Initialise le SDK africastalking avec les credentials courants.

    Le SDK utilise un singleton global, mais on le ré-initialise pour chaque
    appel afin de gérer le toggle Sandbox/Live dynamiquement.
    """
    import africastalking  # type: ignore
    username = cfg["username"] or ("sandbox" if cfg["env"] == "sandbox" else "")
    api_key = cfg["api_key"]
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Africa's Talking API key non configuré (voir Coffre-fort des secrets).",
        )
    africastalking.initialize(username, api_key)
    return africastalking.SMS


async def send_at_sms(
    db,
    *,
    to: str,
    text: str,
    sender: Optional[str] = None,
) -> Dict[str, Any]:
    """Envoie un SMS via Africa's Talking. Retourne le résultat brut du SDK."""
    cfg = await _get_at_config(db)
    if not cfg["enabled"]:
        raise HTTPException(status_code=503, detail="Africa's Talking SMS est désactivé.")
    sms = _init_sdk(cfg)
    from_sc = sender or cfg["shortcode"]
    recipients = [to] if isinstance(to, str) else list(to)
    try:
        # Appel synchrone (le SDK utilise requests sous le capot)
        params: Dict[str, Any] = {}
        if from_sc:
            params["sender_id"] = from_sc  # SDK accepte sender_id ou from_
        response = sms.send(text, recipients, **params)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[africas_talking] send failed")
        raise HTTPException(status_code=502, detail=f"Échec envoi AT SMS : {exc}") from exc
    return response


def setup_africas_talking_routes(*, db, api, get_current_admin):
    """Monte les routes Africa's Talking SMS sur l'API FastAPI."""

    # ===================================================================
    # WEBHOOK ENTRANT — POST /api/webhooks/africas-talking/incoming-sms
    # ===================================================================
    @api.post(
        "/webhooks/africas-talking/incoming-sms",
        tags=["Webhooks — Africa's Talking"],
    )
    async def incoming_sms_webhook(
        request: Request,
        secret: Optional[str] = Query(None),
    ):
        """Africa's Talking POST y envoie chaque SMS entrant.

        Format attendu (form-data) :
            from    : MSISDN expéditeur (ex. +22670000000)
            to      : shortcode destinataire (ex. 15555)
            text    : corps du message
            date    : ISO timestamp d'arrivée
            id      : identifiant message AT
            linkId  : (optionnel)

        Le handler :
          1. Persiste le SMS dans `africas_talking_sms_messages`
          2. Si Liluvine est activé, génère une réponse IA et l'envoie via AT
          3. Retourne 200 OK (Africa's Talking attend un simple OK)
        """
        cfg = await _get_at_config(db)
        # Validation secret optionnel
        if cfg["webhook_secret"] and secret != cfg["webhook_secret"]:
            raise HTTPException(status_code=401, detail="Secret webhook invalide")

        # Parse form-encoded body (AT envoie en application/x-www-form-urlencoded)
        try:
            form = await request.form()
            payload = {k: str(v) for k, v in form.items()}
        except Exception:
            try:
                payload = await request.json()
                payload = {k: str(v) for k, v in (payload or {}).items()}
            except Exception:
                payload = {}

        from_msisdn = (payload.get("from") or "").strip()
        to_shortcode = (payload.get("to") or "").strip()
        text = (payload.get("text") or "").strip()
        at_message_id = (payload.get("id") or "").strip()
        link_id = (payload.get("linkId") or "").strip() or None
        at_date = (payload.get("date") or "").strip()

        # Persist inbound
        phone_digits = "".join(ch for ch in from_msisdn if ch.isdigit())
        inbound_doc = {
            "id": uuid.uuid4().hex,
            "direction": "inbound",
            "from": from_msisdn,
            "to": to_shortcode,
            "phone_digits": phone_digits,
            "text": text,
            "at_message_id": at_message_id,
            "link_id": link_id,
            "at_date": at_date,
            "provider": "africas_talking",
            "env": cfg["env"],
            "created_at": _now_iso(),
        }
        try:
            await db.africas_talking_sms_messages.insert_one(inbound_doc.copy())
        except Exception:  # noqa: BLE001
            logger.exception("[at_incoming] persist failed")

        # Si Africa's Talking est désactivé ou Liluvine n'est pas demandé, on ack
        if not cfg["enabled"] or not cfg["use_liluvine"] or not text:
            return PlainTextResponse("OK")

        # Génère la réponse via Liluvine
        try:
            reply_text = await _generate_liluvine_reply(db, from_msisdn, text)
        except Exception:  # noqa: BLE001
            logger.exception("[at_incoming] liluvine failed")
            reply_text = "Désolé, le service Liluvine est temporairement indisponible. Réessayez plus tard."

        # Ajoute signature si configurée
        sig = cfg["signature"]
        if sig and sig not in reply_text:
            reply_text = f"{reply_text}\n\n{sig}"

        # Trim pour rester sous la limite SMS (10 SMS max chained → ~1600 chars)
        if len(reply_text) > 1500:
            reply_text = reply_text[:1497] + "..."

        # Envoi de la réponse via AT
        try:
            send_res = await send_at_sms(db, to=from_msisdn, text=reply_text)
            outbound_doc = {
                "id": uuid.uuid4().hex,
                "direction": "outbound",
                "from": "liluvine",
                "to": from_msisdn,
                "phone_digits": phone_digits,
                "text": reply_text,
                "at_response": str(send_res)[:2000],
                "in_reply_to": inbound_doc["id"],
                "provider": "africas_talking",
                "env": cfg["env"],
                "ai_generated": True,
                "ai_source": "liluvine_at_autoreply",
                "created_at": _now_iso(),
            }
            await db.africas_talking_sms_messages.insert_one(outbound_doc.copy())
        except HTTPException as he:
            logger.warning("[at_incoming] reply send failed: %s", he.detail)
        except Exception:  # noqa: BLE001
            logger.exception("[at_incoming] reply send failed")

        return PlainTextResponse("OK")

    # ===================================================================
    # WEBHOOK RAPPORTS DE LIVRAISON
    # ===================================================================
    @api.post(
        "/webhooks/africas-talking/delivery-report",
        tags=["Webhooks — Africa's Talking"],
    )
    async def delivery_report_webhook(
        request: Request,
        secret: Optional[str] = Query(None),
    ):
        cfg = await _get_at_config(db)
        if cfg["webhook_secret"] and secret != cfg["webhook_secret"]:
            raise HTTPException(status_code=401, detail="Secret webhook invalide")
        try:
            form = await request.form()
            payload = {k: str(v) for k, v in form.items()}
        except Exception:
            try:
                payload = await request.json()
                payload = {k: str(v) for k, v in (payload or {}).items()}
            except Exception:
                payload = {}
        try:
            await db.africas_talking_delivery_reports.insert_one({
                "id": uuid.uuid4().hex,
                "payload": payload,
                "provider": "africas_talking",
                "env": cfg["env"],
                "created_at": _now_iso(),
            })
        except Exception:  # noqa: BLE001
            logger.exception("[at_delivery] persist failed")
        return PlainTextResponse("OK")

    # ===================================================================
    # ADMIN — Envoi manuel d'un SMS via AT (test/debug)
    # ===================================================================
    @api.post(
        "/admin/africas-talking/send-sms",
        tags=["Admin — Africa's Talking"],
    )
    async def admin_send_at_sms(
        payload: ATSendPayload = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        if not payload.to.strip() or not payload.text.strip():
            raise HTTPException(status_code=400, detail="`to` et `text` requis")
        res = await send_at_sms(
            db,
            to=payload.to.strip(),
            text=payload.text.strip(),
            sender=payload.sender.strip() if payload.sender else None,
        )
        await db.africas_talking_sms_messages.insert_one({
            "id": uuid.uuid4().hex,
            "direction": "outbound",
            "from": "admin",
            "to": payload.to.strip(),
            "phone_digits": "".join(ch for ch in payload.to if ch.isdigit()),
            "text": payload.text.strip(),
            "at_response": str(res)[:2000],
            "provider": "africas_talking",
            "sent_by": user.get("email"),
            "created_at": _now_iso(),
        })
        return {"ok": True, "response": res}

    # ===================================================================
    # ADMIN — Liste/recherche des messages SMS AT
    # ===================================================================
    @api.get(
        "/admin/africas-talking/messages",
        tags=["Admin — Africa's Talking"],
    )
    async def admin_list_at_messages(
        limit: int = Query(200, ge=1, le=2000),
        direction: Optional[str] = Query(None, pattern="^(inbound|outbound)$"),
        q: Optional[str] = Query(None),
        _: dict = Depends(get_current_admin),
    ):
        query: Dict[str, Any] = {"provider": "africas_talking"}
        if direction:
            query["direction"] = direction
        if q:
            digits = "".join(ch for ch in q if ch.isdigit())
            query["$or"] = [
                {"text": {"$regex": q, "$options": "i"}},
                {"from": {"$regex": q, "$options": "i"}},
                {"to": {"$regex": q, "$options": "i"}},
            ]
            if digits:
                query["$or"].append({"phone_digits": {"$regex": digits}})
        cur = db.africas_talking_sms_messages.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        items = await cur.to_list(limit)
        total = await db.africas_talking_sms_messages.count_documents(query)
        return {"items": items, "count": len(items), "total": total}

    # ===================================================================
    # ADMIN — Statut config AT (non-sensible)
    # ===================================================================
    @api.get(
        "/admin/africas-talking/status",
        tags=["Admin — Africa's Talking"],
    )
    async def admin_at_status(_: dict = Depends(get_current_admin)):
        cfg = await _get_at_config(db)
        return {
            "enabled": cfg["enabled"],
            "env": cfg["env"],
            "username_set": bool(cfg["username"]),
            "api_key_set": bool(cfg["api_key"]),
            "shortcode": cfg["shortcode"],
            "use_liluvine": cfg["use_liluvine"],
            "webhook_url_template": "https://<your-domain>/api/webhooks/africas-talking/incoming-sms",
            "delivery_url_template": "https://<your-domain>/api/webhooks/africas-talking/delivery-report",
            "secret_required": bool(cfg["webhook_secret"]),
            "messages_count": await db.africas_talking_sms_messages.count_documents({"provider": "africas_talking"}),
        }

    logger.info("[africas_talking] routes mounted under /api/webhooks/africas-talking/* and /api/admin/africas-talking/*")


# ===========================================================================
# Liluvine reply generator (réutilise le LLM Claude via emergentintegrations)
# ===========================================================================
async def _generate_liluvine_reply(db, from_msisdn: str, text: str) -> str:
    """Génère une réponse Liluvine via Claude Haiku, en lui injectant les KBs
    (Knowledge Base + Business RAG) pour la cohérence avec le canal WA.

    Cette fonction est une variante simplifiée de `routes.liluvine_wa_autoreply`
    adaptée au canal SMS (réponses plus courtes, sans Markdown WhatsApp).
    """
    phone_digits = "".join(ch for ch in from_msisdn if ch.isdigit())
    session_id = f"sms:at:{phone_digits}"

    # Récupère la KB et le contexte business
    try:
        from routes.liluvine_kb import build_kb_context
        kb = await build_kb_context(db, max_chars=2500, query=text)
    except Exception:  # noqa: BLE001
        kb = ""
    try:
        from routes.liluvine_business_rag import build_business_rag_context
        biz_ctx = await build_business_rag_context(db, phone_digits=phone_digits, query=text)
    except Exception:  # noqa: BLE001
        biz_ctx = ""

    sys_text = (
        "Tu es Liluvine PRO, l'assistant IA de SAWALI Smart Systems. "
        "Tu réponds par SMS (canal limité : pas de Markdown, pas d'emoji décoratif, max 320 caractères). "
        "Sois courtois, concis et factuel. Si tu ne sais pas, dis-le simplement et propose un canal alternatif (WhatsApp / appel)."
        + (("\n\nContexte SAWALI :\n" + kb) if kb else "")
        + (("\n\nDonnées métier :\n" + biz_ctx) if biz_ctx else "")
    )

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return "Service IA temporairement indisponible. Merci de réessayer plus tard."

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=api_key,
            session_id=session_id,
            system_message=sys_text,
        ).with_model("anthropic", "claude-haiku-4-5-20251001")
        reply = await chat.send_message(UserMessage(text=text))
    except Exception:  # noqa: BLE001
        logger.exception("[at_liluvine] LLM error")
        return "Une erreur technique est survenue. Merci de réessayer dans quelques minutes."

    reply = (reply or "").strip()
    if not reply:
        return "Désolé, je n'ai pas pu générer de réponse. Réessayez en reformulant."

    # Log dans liluvine_pro_messages pour audit historique
    try:
        await db.liluvine_pro_messages.insert_one({
            "id": secrets.token_urlsafe(12),
            "session_id": session_id,
            "role": "user",
            "content": text,
            "external_source": "africas_talking_sms",
            "external_payload": {"phone_digits": phone_digits, "from": from_msisdn},
            "created_at": _now_iso(),
        })
        await db.liluvine_pro_messages.insert_one({
            "id": secrets.token_urlsafe(12),
            "session_id": session_id,
            "role": "assistant",
            "content": reply,
            "model": "claude-haiku-4-5-20251001",
            "external_source": "africas_talking_sms",
            "created_at": _now_iso(),
        })
    except Exception:  # noqa: BLE001
        pass

    return reply
