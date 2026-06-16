"""Iter43-fix23b (2026-06) — Bird.com 2-Way SMS Integration (replaces Africa's Talking).

Bird a racheté Africa's Talking et propose une plateforme unifiée. L'utilisateur
a généré une clé API Bird (et non AT) sur app.bird.com → on intègre directement
l'API Bird Channels (httpx direct, pas de SDK).

Architecture :
  - Webhook entrant : `POST /api/webhooks/bird/inbound-sms`
    Bird POST y envoie chaque SMS reçu sur le sender configuré. Le payload
    JSON contient l'expéditeur, le destinataire, le texte, l'id Bird, etc.
    Le header `Bird-Signature` contient une signature HMAC SHA-256 calculée
    sur le body brut avec le webhook secret partagé.
  - Webhook delivery reports : (optionnel) même mécanisme.
  - Envoi sortant : `POST {BIRD_API_BASE_URL}/workspaces/{wid}/channels/{cid}/messages`
    Auth : `Authorization: AccessKey {api_key}`

Toutes les credentials sont stockées dans `settings.global` :
  - bird_enabled            : bool — toggle maître
  - bird_api_base_url       : str — défaut "https://api.bird.com"
  - bird_workspace_id       : str — UUID workspace Bird
  - bird_channel_id         : str — UUID channel SMS Bird
  - bird_access_key         : str (sensible) — Access Key avec policy Messaging
  - bird_webhook_secret     : str (sensible) — signing secret pour Bird-Signature
  - bird_default_sender     : str — sender ID/numéro long
  - bird_signature          : str — signature ajoutée à chaque réponse (texte)
  - bird_use_liluvine       : bool — router les SMS vers Liluvine

Tous les SMS sont logués dans la collection `bird_sms_messages`.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

logger = logging.getLogger("sawali.bird_sms")


class BirdSendPayload(BaseModel):
    to: str
    text: str
    sender: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


async def _get_bird_config(db) -> Dict[str, Any]:
    """Récupère la configuration Bird depuis settings.global."""
    s = await db.settings.find_one(
        {"_id": "global"},
        {
            "_id": 0,
            "bird_enabled": 1,
            "bird_api_base_url": 1,
            "bird_workspace_id": 1,
            "bird_channel_id": 1,
            "bird_access_key": 1,
            "bird_webhook_secret": 1,
            "bird_default_sender": 1,
            "bird_signature": 1,
            "bird_use_liluvine": 1,
        },
    ) or {}
    return {
        "enabled": bool(s.get("bird_enabled")),
        "api_base_url": (s.get("bird_api_base_url") or "https://api.bird.com").rstrip("/"),
        "workspace_id": (s.get("bird_workspace_id") or "").strip(),
        "channel_id": (s.get("bird_channel_id") or "").strip(),
        "access_key": (s.get("bird_access_key") or "").strip(),
        "webhook_secret": (s.get("bird_webhook_secret") or "").strip() or None,
        "default_sender": (s.get("bird_default_sender") or "").strip() or None,
        "signature": (s.get("bird_signature") or "").strip(),
        "use_liluvine": bool(s.get("bird_use_liluvine", True)),
    }


def _verify_bird_signature(secret: str, raw_body: bytes, sig_header: Optional[str]) -> bool:
    """Vérifie le HMAC SHA-256 du body avec le webhook secret partagé.

    Bird envoie la signature dans le header `Bird-Signature`. Le format peut
    être un simple hex digest, ou `t=...,v1=hex` (style Stripe). On gère les
    deux formats robustement.
    """
    if not sig_header or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # Format simple : juste le hex
    if hmac.compare_digest(sig_header.strip(), expected):
        return True
    # Format Stripe-like : "t=12345,v1=abcdef..."
    parts = {}
    for p in sig_header.split(","):
        if "=" in p:
            k, v = p.split("=", 1)
            parts[k.strip()] = v.strip()
    sig_v1 = parts.get("v1") or parts.get("sha256") or parts.get("signature")
    if sig_v1 and hmac.compare_digest(sig_v1, expected):
        return True
    # Format base64 (au cas où)
    import base64
    try:
        expected_b64 = base64.b64encode(
            hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        ).decode("ascii")
        if hmac.compare_digest(sig_header.strip(), expected_b64):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def send_bird_sms(
    db,
    *,
    to: str,
    text: str,
    sender: Optional[str] = None,
) -> Dict[str, Any]:
    """Envoie un SMS via l'API Bird Channels (httpx direct, pas de SDK)."""
    cfg = await _get_bird_config(db)
    if not cfg["enabled"]:
        raise HTTPException(status_code=503, detail="Bird SMS est désactivé.")
    if not cfg["access_key"]:
        raise HTTPException(status_code=503, detail="Bird Access Key non configurée.")
    if not cfg["workspace_id"] or not cfg["channel_id"]:
        raise HTTPException(status_code=503, detail="Bird workspace_id / channel_id non configurés.")

    url = (
        f"{cfg['api_base_url']}/workspaces/{cfg['workspace_id']}"
        f"/channels/{cfg['channel_id']}/messages"
    )
    headers = {
        "Authorization": f"AccessKey {cfg['access_key']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    from_sender = sender or cfg["default_sender"]
    # Format payload Bird Channels API (référence playbook + docs Bird)
    payload: Dict[str, Any] = {
        "receiver": {
            "contacts": [{"identifierValue": to}],
        },
        "body": {
            "type": "text",
            "text": {"text": text},
        },
    }
    if from_sender:
        payload["sender"] = {"connector": {"identifierValue": from_sender}}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.exception("[bird] HTTP error")
        raise HTTPException(status_code=502, detail=f"Bird HTTP error : {exc}") from exc

    if r.status_code >= 400:
        try:
            err = r.json()
        except Exception:  # noqa: BLE001
            err = r.text
        raise HTTPException(status_code=502, detail=f"Bird API error {r.status_code} : {err}")

    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {"raw": r.text}


def setup_bird_sms_routes(*, db, api, get_current_admin):
    """Monte les routes Bird SMS sur l'API FastAPI."""

    # ===================================================================
    # WEBHOOK ENTRANT — POST /api/webhooks/bird/inbound-sms
    # ===================================================================
    @api.post(
        "/webhooks/bird/inbound-sms",
        tags=["Webhooks — Bird"],
    )
    async def bird_inbound_sms(request: Request):
        """Bird POST y envoie chaque SMS entrant (signé HMAC SHA-256).

        Le payload JSON typique contient :
          - id, workspaceId, channelId, direction="inbound"
          - sender / receiver / from / to (dépend du schema Bird)
          - body.text.text ou body.text ou content.text (selon version)
          - timestamps

        Le handler :
          1. Vérifie la signature `Bird-Signature` si webhook_secret configuré
          2. Persiste le SMS dans `bird_sms_messages` (unique sur provider_id)
          3. Si Liluvine est activé, génère une réponse IA et l'envoie via Bird
          4. Retourne 200 OK avec {status:"ok"}
        """
        raw_body = await request.body()
        cfg = await _get_bird_config(db)

        # 1. Vérif signature si secret configuré
        if cfg["webhook_secret"]:
            sig = request.headers.get("Bird-Signature") or request.headers.get("bird-signature")
            if not _verify_bird_signature(cfg["webhook_secret"], raw_body, sig):
                logger.warning("[bird_inbound] signature invalide ou manquante")
                raise HTTPException(status_code=401, detail="Bird-Signature invalide ou manquante")

        # 2. Parse JSON
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Payload JSON invalide")

        # 3. Extraction défensive (Bird schema variations)
        bird_msg_id = (
            payload.get("id")
            or payload.get("messageId")
            or (payload.get("data") or {}).get("id")
            or ""
        )
        direction = payload.get("direction") or "inbound"
        sender_info = payload.get("sender") or payload.get("from") or {}
        receiver_info = payload.get("receiver") or payload.get("to") or {}

        def _extract_phone(obj: Any) -> str:
            if isinstance(obj, str):
                return obj.strip()
            if isinstance(obj, dict):
                for k in ("phoneNumber", "number", "identifierValue", "msisdn", "address"):
                    v = obj.get(k)
                    if v:
                        return str(v).strip()
                # Nested: contacts[0].identifierValue
                contacts = obj.get("contacts")
                if isinstance(contacts, list) and contacts:
                    return _extract_phone(contacts[0])
            return ""

        from_msisdn = _extract_phone(sender_info)
        to_address = _extract_phone(receiver_info)

        # Extract body text (Bird : body.text.text or content.text)
        text = ""
        body_obj = payload.get("body") or payload.get("content") or {}
        if isinstance(body_obj, dict):
            text_obj = body_obj.get("text") or body_obj.get("content") or body_obj
            if isinstance(text_obj, dict):
                text = (text_obj.get("text") or text_obj.get("body") or "").strip()
            elif isinstance(text_obj, str):
                text = text_obj.strip()
        if not text:
            text = (payload.get("text") or payload.get("message") or "").strip()

        phone_digits = "".join(ch for ch in from_msisdn if ch.isdigit())
        inbound_doc = {
            "id": uuid.uuid4().hex,
            "direction": "inbound",
            "from": from_msisdn,
            "to": to_address,
            "phone_digits": phone_digits,
            "text": text,
            "provider_message_id": bird_msg_id,
            "provider": "bird",
            "raw_payload": payload,
            "created_at": _now_iso(),
        }

        # Idempotence : on évite les doublons sur provider_message_id
        if bird_msg_id:
            existing = await db.bird_sms_messages.find_one(
                {"provider_message_id": bird_msg_id, "direction": "inbound"},
                {"_id": 0, "id": 1},
            )
            if existing:
                logger.info("[bird_inbound] duplicate webhook ignored: %s", bird_msg_id)
                return {"status": "ok", "duplicate": True}

        try:
            await db.bird_sms_messages.insert_one(inbound_doc.copy())
        except Exception:  # noqa: BLE001
            logger.exception("[bird_inbound] persist failed")

        # 4. Si Bird est désactivé ou Liluvine non activé, on ack
        if not cfg["enabled"] or not cfg["use_liluvine"] or not text:
            return {"status": "ok"}

        # 5. Génération réponse Liluvine
        try:
            reply_text = await _generate_liluvine_reply(db, from_msisdn, text)
        except Exception:  # noqa: BLE001
            logger.exception("[bird_inbound] liluvine failed")
            reply_text = "Désolé, le service Liluvine est temporairement indisponible. Réessayez plus tard."

        sig_text = cfg["signature"]
        if sig_text and sig_text not in reply_text:
            reply_text = f"{reply_text}\n\n{sig_text}"

        if len(reply_text) > 1500:
            reply_text = reply_text[:1497] + "..."

        # 6. Envoi via Bird
        try:
            send_res = await send_bird_sms(db, to=from_msisdn, text=reply_text)
            outbound_doc = {
                "id": uuid.uuid4().hex,
                "direction": "outbound",
                "from": "liluvine",
                "to": from_msisdn,
                "phone_digits": phone_digits,
                "text": reply_text,
                "bird_response": send_res,
                "in_reply_to": inbound_doc["id"],
                "provider": "bird",
                "ai_generated": True,
                "ai_source": "liluvine_bird_autoreply",
                "created_at": _now_iso(),
            }
            await db.bird_sms_messages.insert_one(outbound_doc.copy())
        except HTTPException as he:
            logger.warning("[bird_inbound] reply send failed: %s", he.detail)
        except Exception:  # noqa: BLE001
            logger.exception("[bird_inbound] reply send failed")

        return {"status": "ok"}

    # ===================================================================
    # WEBHOOK RAPPORTS DE LIVRAISON
    # ===================================================================
    @api.post(
        "/webhooks/bird/delivery-report",
        tags=["Webhooks — Bird"],
    )
    async def bird_delivery_report(request: Request):
        raw_body = await request.body()
        cfg = await _get_bird_config(db)
        if cfg["webhook_secret"]:
            sig = request.headers.get("Bird-Signature") or request.headers.get("bird-signature")
            if not _verify_bird_signature(cfg["webhook_secret"], raw_body, sig):
                raise HTTPException(status_code=401, detail="Bird-Signature invalide")
        try:
            payload = await request.json()
        except Exception:
            payload = {"raw": raw_body.decode("utf-8", errors="replace")}
        try:
            await db.bird_delivery_reports.insert_one({
                "id": uuid.uuid4().hex,
                "payload": payload,
                "provider": "bird",
                "created_at": _now_iso(),
            })
        except Exception:  # noqa: BLE001
            logger.exception("[bird_delivery] persist failed")
        return {"status": "ok"}

    # ===================================================================
    # ADMIN — Envoi manuel d'un SMS via Bird (test/debug)
    # ===================================================================
    # ===================================================================
    # Iter43-fix24l — ADMIN TEST : envoi SMS Bird avec diagnostics complets
    # ===================================================================
    @api.post(
        "/admin/bird/test-sms",
        tags=["Admin — Bird"],
    )
    async def admin_test_bird_sms(
        payload: BirdSendPayload = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        """Test d'envoi SMS Bird avec retour DÉTAILLÉ pour debugging.

        Contrairement à `/admin/bird/send-sms`, cet endpoint :
          - Bypass le toggle `bird_enabled` (permet de tester avant activation)
          - Retourne TOUS les détails : http_status, headers, body, latency_ms, URL appelée
          - Ne persiste PAS le résultat dans bird_sms_messages
        Idéal pour valider la config Workspace ID / Channel ID / Access Key.
        """
        import time as _t
        if not payload.to.strip() or not payload.text.strip():
            raise HTTPException(status_code=400, detail="`to` et `text` requis")
        cfg = await _get_bird_config(db)
        diag: Dict[str, Any] = {
            "ok": False,
            "config_check": {
                "bird_enabled": cfg.get("enabled"),
                "has_access_key": bool(cfg.get("access_key")),
                "has_workspace_id": bool(cfg.get("workspace_id")),
                "has_channel_id": bool(cfg.get("channel_id")),
                "api_base_url": cfg.get("api_base_url"),
                "default_sender": cfg.get("default_sender") or "(non configuré)",
            },
        }
        # Validation explicite
        missing = []
        if not cfg.get("access_key"):
            missing.append("bird_access_key")
        if not cfg.get("workspace_id"):
            missing.append("bird_workspace_id")
        if not cfg.get("channel_id"):
            missing.append("bird_channel_id")
        if missing:
            diag["error"] = f"Configuration incomplète. Champs manquants : {', '.join(missing)}"
            return diag

        url = (
            f"{cfg['api_base_url']}/workspaces/{cfg['workspace_id']}"
            f"/channels/{cfg['channel_id']}/messages"
        )
        headers = {
            "Authorization": f"AccessKey {cfg['access_key'][:4]}…(masqué)",  # pour l'UI uniquement
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        real_headers = {**headers, "Authorization": f"AccessKey {cfg['access_key']}"}
        from_sender = (payload.sender.strip() if payload.sender else None) or cfg["default_sender"]
        bird_payload: Dict[str, Any] = {
            "receiver": {"contacts": [{"identifierValue": payload.to.strip()}]},
            "body": {"type": "text", "text": {"text": payload.text.strip()}},
        }
        if from_sender:
            bird_payload["sender"] = {"connector": {"identifierValue": from_sender}}

        diag["request"] = {
            "method": "POST",
            "url": url,
            "headers_preview": headers,  # access_key masquée
            "payload": bird_payload,
        }

        start = _t.monotonic()
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(url, json=bird_payload, headers=real_headers)
            duration_ms = int((_t.monotonic() - start) * 1000)
            diag["response"] = {
                "http_status": r.status_code,
                "latency_ms": duration_ms,
                "headers": dict(r.headers),
            }
            # Parse body
            try:
                body = r.json()
            except Exception:  # noqa: BLE001
                body = {"raw_text": r.text[:2000]}
            diag["response"]["body"] = body
            # Verdict
            if r.status_code < 300:
                diag["ok"] = True
                diag["verdict"] = (
                    f"✅ Succès — SMS accepté par Bird en {duration_ms} ms. "
                    "Vérifiez la réception sur le téléphone destinataire."
                )
            else:
                diag["ok"] = False
                err_msg = str(body)[:300]
                diag["verdict"] = (
                    f"❌ Échec HTTP {r.status_code} — {err_msg}"
                )
        except httpx.HTTPError as exc:
            duration_ms = int((_t.monotonic() - start) * 1000)
            diag["response"] = {
                "http_status": 0,
                "latency_ms": duration_ms,
                "error": str(exc)[:300],
            }
            diag["ok"] = False
            diag["verdict"] = f"❌ Erreur réseau après {duration_ms} ms : {exc}"
        return diag

    @api.post(
        "/admin/bird/send-sms",
        tags=["Admin — Bird"],
    )
    async def admin_send_bird_sms(
        payload: BirdSendPayload = Body(...),
        user: dict = Depends(get_current_admin),
    ):
        if not payload.to.strip() or not payload.text.strip():
            raise HTTPException(status_code=400, detail="`to` et `text` requis")
        res = await send_bird_sms(
            db,
            to=payload.to.strip(),
            text=payload.text.strip(),
            sender=payload.sender.strip() if payload.sender else None,
        )
        await db.bird_sms_messages.insert_one({
            "id": uuid.uuid4().hex,
            "direction": "outbound",
            "from": "admin",
            "to": payload.to.strip(),
            "phone_digits": "".join(ch for ch in payload.to if ch.isdigit()),
            "text": payload.text.strip(),
            "bird_response": res,
            "provider": "bird",
            "sent_by": user.get("email"),
            "created_at": _now_iso(),
        })
        return {"ok": True, "response": res}

    # ===================================================================
    # ADMIN — Liste/recherche des messages SMS Bird
    # ===================================================================
    @api.get(
        "/admin/bird/messages",
        tags=["Admin — Bird"],
    )
    async def admin_list_bird_messages(
        limit: int = Query(200, ge=1, le=2000),
        direction: Optional[str] = Query(None, pattern="^(inbound|outbound)$"),
        q: Optional[str] = Query(None),
        _: dict = Depends(get_current_admin),
    ):
        query: Dict[str, Any] = {"provider": "bird"}
        if direction:
            query["direction"] = direction
        if q:
            digits = "".join(ch for ch in q if ch.isdigit())
            or_filters: List[Dict[str, Any]] = [
                {"text": {"$regex": q, "$options": "i"}},
                {"from": {"$regex": q, "$options": "i"}},
                {"to": {"$regex": q, "$options": "i"}},
            ]
            if digits:
                or_filters.append({"phone_digits": {"$regex": digits}})
            query["$or"] = or_filters
        cur = db.bird_sms_messages.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        items = await cur.to_list(limit)
        total = await db.bird_sms_messages.count_documents(query)
        return {"items": items, "count": len(items), "total": total}

    # ===================================================================
    # ADMIN — Statut config Bird (non-sensible)
    # ===================================================================
    @api.get(
        "/admin/bird/status",
        tags=["Admin — Bird"],
    )
    async def admin_bird_status(_: dict = Depends(get_current_admin)):
        cfg = await _get_bird_config(db)
        return {
            "enabled": cfg["enabled"],
            "api_base_url": cfg["api_base_url"],
            "workspace_id_set": bool(cfg["workspace_id"]),
            "channel_id_set": bool(cfg["channel_id"]),
            "access_key_set": bool(cfg["access_key"]),
            "webhook_secret_set": bool(cfg["webhook_secret"]),
            "default_sender": cfg["default_sender"],
            "use_liluvine": cfg["use_liluvine"],
            "webhook_url_template": "https://<your-domain>/api/webhooks/bird/inbound-sms",
            "delivery_url_template": "https://<your-domain>/api/webhooks/bird/delivery-report",
            "messages_count": await db.bird_sms_messages.count_documents({"provider": "bird"}),
        }

    @api.get(
        "/admin/bird/cost-daily-series",
        tags=["Admin — Bird"],
    )
    async def admin_bird_cost_daily_series(
        days: int = Query(30, ge=1, le=365),
        _: dict = Depends(get_current_admin),
    ):
        """Iter43-fix24f — Série temporelle journalière des SMS Bird outbound.

        Retourne un tableau de {date, count, cost} pour les N derniers jours,
        utilisé par la page Admin → Bird Cost (graphique).
        """
        cfg_doc = await db.settings.find_one(
            {"_id": "global"},
            {"_id": 0, "bird_cost_per_sms_xof": 1, "bird_cost_currency": 1},
        ) or {}
        unit_cost = float(cfg_doc.get("bird_cost_per_sms_xof") or 25.0)
        currency = (cfg_doc.get("bird_cost_currency") or "XOF").upper()

        from datetime import timedelta
        now = datetime.now(timezone.utc)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days - 1)

        # On charge toutes les rows outbound dans la fenêtre, puis agrège en Python
        # (volume limité — pas besoin d'aggregation MongoDB)
        cursor = db.bird_sms_messages.find(
            {
                "provider": "bird",
                "direction": "outbound",
                "created_at": {"$gte": start.isoformat()},
            },
            {"_id": 0, "created_at": 1},
        )
        buckets: Dict[str, int] = {}
        async for doc in cursor:
            ts = doc.get("created_at")
            if not ts:
                continue
            day = ts[:10]  # YYYY-MM-DD
            buckets[day] = buckets.get(day, 0) + 1

        # Construire la série en remplissant les zéros
        series = []
        for i in range(days):
            d = (start + timedelta(days=i))
            day_key = d.isoformat()[:10]
            cnt = buckets.get(day_key, 0)
            series.append({
                "date": day_key,
                "count": cnt,
                "cost": round(cnt * unit_cost, 2),
            })

        total_count = sum(b["count"] for b in series)
        return {
            "days": days,
            "unit_cost": unit_cost,
            "currency": currency,
            "total_count": total_count,
            "total_cost": round(total_count * unit_cost, 2),
            "series": series,
        }

    @api.get(
        "/admin/bird/cost-summary",
        tags=["Admin — Bird"],
    )
    async def admin_bird_cost_summary(_: dict = Depends(get_current_admin)):
        """Iter43-fix24d — Résumé du coût Bird : aujourd'hui, hier, 7 derniers jours, 30 derniers jours.

        Le coût est calculé en multipliant le nombre de SMS outbound `provider="bird"`
        par `settings.bird_cost_per_sms_xof` (défaut 25 XOF).
        """
        cfg_doc = await db.settings.find_one(
            {"_id": "global"},
            {"_id": 0, "bird_cost_per_sms_xof": 1, "bird_cost_currency": 1},
        ) or {}
        unit_cost = float(cfg_doc.get("bird_cost_per_sms_xof") or 25.0)
        currency = (cfg_doc.get("bird_cost_currency") or "XOF").upper()

        from datetime import timedelta
        now = datetime.now(timezone.utc)

        def _start_of_day(dt: datetime) -> datetime:
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)

        today_start = _start_of_day(now)
        yesterday_start = today_start - timedelta(days=1)
        last7_start = today_start - timedelta(days=7)
        last30_start = today_start - timedelta(days=30)

        async def _count_outbound(since: datetime, until: Optional[datetime] = None) -> int:
            q: Dict[str, Any] = {
                "provider": "bird",
                "direction": "outbound",
                "created_at": {"$gte": since.isoformat()},
            }
            if until:
                q["created_at"]["$lt"] = until.isoformat()
            return await db.bird_sms_messages.count_documents(q)

        n_today = await _count_outbound(today_start)
        n_yesterday = await _count_outbound(yesterday_start, today_start)
        n_last7 = await _count_outbound(last7_start)
        n_last30 = await _count_outbound(last30_start)
        n_total = await db.bird_sms_messages.count_documents({"provider": "bird", "direction": "outbound"})

        return {
            "unit_cost": unit_cost,
            "currency": currency,
            "today": {"count": n_today, "cost": round(n_today * unit_cost, 2)},
            "yesterday": {"count": n_yesterday, "cost": round(n_yesterday * unit_cost, 2)},
            "last_7_days": {"count": n_last7, "cost": round(n_last7 * unit_cost, 2)},
            "last_30_days": {"count": n_last30, "cost": round(n_last30 * unit_cost, 2)},
            "total": {"count": n_total, "cost": round(n_total * unit_cost, 2)},
        }

    logger.info("[bird_sms] routes mounted under /api/webhooks/bird/* and /api/admin/bird/*")


# ===========================================================================
# Liluvine reply generator (réutilise le LLM Claude via emergentintegrations)
# ===========================================================================
async def _generate_liluvine_reply(db, from_msisdn: str, text: str) -> str:
    """Génère une réponse Liluvine via Claude Haiku, en lui injectant les KBs.

    Variante simplifiée de `routes.liluvine_wa_autoreply` adaptée au SMS
    (réponses plus courtes, sans Markdown WhatsApp).
    """
    phone_digits = "".join(ch for ch in from_msisdn if ch.isdigit())
    session_id = f"sms:bird:{phone_digits}"

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
        logger.exception("[bird_liluvine] LLM error")
        return "Une erreur technique est survenue. Merci de réessayer dans quelques minutes."

    reply = (reply or "").strip()
    if not reply:
        return "Désolé, je n'ai pas pu générer de réponse. Réessayez en reformulant."

    try:
        await db.liluvine_pro_messages.insert_one({
            "id": secrets.token_urlsafe(12),
            "session_id": session_id,
            "role": "user",
            "content": text,
            "external_source": "bird_sms",
            "external_payload": {"phone_digits": phone_digits, "from": from_msisdn},
            "created_at": _now_iso(),
        })
        await db.liluvine_pro_messages.insert_one({
            "id": secrets.token_urlsafe(12),
            "session_id": session_id,
            "role": "assistant",
            "content": reply,
            "model": "claude-haiku-4-5-20251001",
            "external_source": "bird_sms",
            "created_at": _now_iso(),
        })
    except Exception:  # noqa: BLE001
        pass

    return reply
