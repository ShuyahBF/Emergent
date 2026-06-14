"""Iter38r-fix9r — Home Assistant Voice Notifications.

Lets each tenant route key business events (new invoice, critical ticket,
payment received, etc.) as TTS announcements on their Amazon Echo / Alexa
speakers via a Home Assistant server (using `alexa_media_player` integration).

Features
--------
- Per-tenant Home Assistant configuration (URL + Long-Lived Token + speaker)
- Built-in catalog of business events (label / module / db_table / default
  TTS / available variables)
- Custom events: admin can add arbitrary entries (e.g. "Caisse ouverte",
  "Backup terminé") that are not yet hardcoded
- Rules: each event (built-in or custom) has an enable toggle + TTS template
- Manual test endpoint to verify the HA pipeline
- `trigger_voice_event(...)` helper called by internal code paths to dispatch

Endpoints
---------
GET  /api/admin/voice-notifications/catalog
GET  /api/admin/voice-notifications/config
PUT  /api/admin/voice-notifications/config
GET  /api/admin/voice-notifications/rules
PUT  /api/admin/voice-notifications/rules/{event_key}
POST /api/admin/voice-notifications/custom-events
DEL  /api/admin/voice-notifications/custom-events/{event_key}
POST /api/admin/voice-notifications/test
POST /api/voice-notifications/trigger     (internal: trusted code or auth-gated)

DB collections
--------------
- voice_notifications_config  {_id=tenant_id, ha_url, ha_token, ha_speaker, enabled, notify_service, updated_at}
- voice_notifications_rules   {tenant_id, event_key, enabled, tts_template, speaker_override, updated_at}
- voice_notifications_custom  {tenant_id, event_key, label, module, page, db_table, variables[], created_at}
- voice_notifications_log     {tenant_id, event_key, message, ha_status, ha_response, created_at}
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger("sawali.voice_notifications")


# ---------------------------------------------------------------------------
# Built-in catalog (extendable by tenants via voice_notifications_custom)
# ---------------------------------------------------------------------------
BUILTIN_CATALOG: List[Dict[str, Any]] = [
    {
        "key": "invoice_created",
        "label": "Nouvelle facture émise",
        "module": "Caisse / Facturation",
        "page": "/portal/caisse",
        "db_table": "caisse_invoices",
        "default_tts": "Nouvelle facture {invoice_number} de {amount} XOF pour {client_name}.",
        "variables": ["client_name", "amount", "invoice_number"],
        "category": "billing",
    },
    {
        "key": "invoice_paid",
        "label": "Facture encaissée à la caisse",
        "module": "Caisse / Facturation",
        "page": "/portal/caisse",
        "db_table": "caisse_invoices",
        "default_tts": "Paiement encaissé : {amount} XOF de {client_name}.",
        "variables": ["client_name", "amount", "invoice_number"],
        "category": "billing",
    },
    {
        "key": "ticket_created",
        "label": "Nouveau ticket d'intervention",
        "module": "Tickets",
        "page": "/portal/tickets",
        "db_table": "tickets",
        "default_tts": "Nouveau ticket {ticket_code} : {subject} pour {client_name}.",
        "variables": ["client_name", "subject", "ticket_code", "priority"],
        "category": "support",
    },
    {
        "key": "ticket_critical",
        "label": "Ticket critique ouvert",
        "module": "Tickets",
        "page": "/portal/tickets",
        "db_table": "tickets",
        "default_tts": "Alerte ticket critique : {subject} chez {client_name}.",
        "variables": ["client_name", "subject", "ticket_code", "priority"],
        "category": "support",
    },
    {
        "key": "payment_pawapay_received",
        "label": "Paiement PawaPay reçu",
        "module": "Paiements PawaPay",
        "page": "/portal/payments",
        "db_table": "payment_links",
        "default_tts": "Paiement Mobile Money reçu : {amount} XOF de {client_name}.",
        "variables": ["client_name", "amount", "provider", "msisdn"],
        "category": "payments",
    },
    {
        "key": "payment_stripe_received",
        "label": "Paiement Stripe reçu",
        "module": "Paiements Stripe",
        "page": "/portal/payments",
        "db_table": "stripe_transactions",
        "default_tts": "Paiement Stripe reçu : {amount} {currency} de {client_name}.",
        "variables": ["client_name", "amount", "currency", "product_name"],
        "category": "payments",
    },
    {
        "key": "hr_leave_request_created",
        "label": "Nouvelle demande de congé",
        "module": "GRH",
        "page": "/portal/grh",
        "db_table": "hr_leave_requests",
        "default_tts": "Nouvelle demande de congé de {employee_name} du {start_date} au {end_date}.",
        "variables": ["employee_name", "start_date", "end_date", "leave_type"],
        "category": "hr",
    },
    {
        "key": "cash_session_unclosed",
        "label": "Caisse non clôturée",
        "module": "Caisse",
        "page": "/portal/caisse",
        "db_table": "cash_sessions",
        "default_tts": "Attention : caisse {register_name} non clôturée depuis {hours_open} heures.",
        "variables": ["register_name", "hours_open", "cashier_name"],
        "category": "alerts",
    },
    {
        "key": "new_client_signup",
        "label": "Nouveau client inscrit",
        "module": "Clients",
        "page": "/portal/clients",
        "db_table": "users",
        "default_tts": "Nouveau client inscrit : {full_name}, société {company}.",
        "variables": ["full_name", "company", "email"],
        "category": "crm",
    },
    {
        "key": "catalog_order",
        "label": "Nouvelle commande catalogue produit",
        "module": "Catalogue produits",
        "page": "/portal/catalog",
        "db_table": "product_orders",
        "default_tts": "Nouvelle commande : {product_name} pour {amount} XOF.",
        "variables": ["product_name", "amount", "client_name"],
        "category": "sales",
    },
    {
        "key": "appointment_created",
        "label": "Nouveau rendez-vous planifié",
        "module": "Calendrier",
        "page": "/portal/calendar",
        "db_table": "appointments",
        "default_tts": "Nouveau rendez-vous avec {client_name} le {date}.",
        "variables": ["client_name", "date", "subject"],
        "category": "calendar",
    },
    {
        "key": "incident_critical",
        "label": "Incident critique signalé",
        "module": "Incidents",
        "page": "/portal/incidents",
        "db_table": "incidents",
        "default_tts": "Incident critique : {title}.",
        "variables": ["title", "severity", "reporter"],
        "category": "alerts",
    },
    {
        "key": "expense_recorded",
        "label": "Nouvelle dépense caisse enregistrée",
        "module": "Dépenses Caisse",
        "page": "/portal/cashier-expenses",
        "db_table": "cashier_expenses",
        "default_tts": "Nouvelle dépense de {amount} XOF : {label}.",
        "variables": ["amount", "label", "category"],
        "category": "billing",
    },
    {
        "key": "wa_message_received",
        "label": "Nouveau message WhatsApp client",
        "module": "Inbox unifiée",
        "page": "/portal/inbox",
        "db_table": "wa_messages",
        "default_tts": "Nouveau message WhatsApp de {client_name}.",
        "variables": ["client_name", "preview"],
        "category": "communications",
    },
    {
        "key": "campaign_completed",
        "label": "Campagne SMS/WA terminée",
        "module": "Campagnes Bulk",
        "page": "/portal/campaigns",
        "db_table": "campaigns",
        "default_tts": "Campagne {campaign_name} terminée : {delivered} sur {total} envoyés.",
        "variables": ["campaign_name", "delivered", "total", "failed"],
        "category": "communications",
    },
]


BUILTIN_KEYS = {e["key"] for e in BUILTIN_CATALOG}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_admin(user: dict) -> None:
    role = (user or {}).get("role")
    if role not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")


def _tenant_id(user: dict) -> str:
    return user.get("client_id") or user.get("parent_client_id") or user["id"]


_VAR_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _render_template(template: str, context: Dict[str, Any]) -> str:
    """Replace `{var}` placeholders with values from context. Missing vars are
    rendered as their key in angle brackets so the admin notices the gap."""
    if not template:
        return ""
    def repl(m: re.Match) -> str:
        k = m.group(1)
        v = context.get(k)
        if v is None or v == "":
            return f"<{k}>"
        return str(v)
    return _VAR_PATTERN.sub(repl, template)


async def trigger_voice_event(
    db,
    tenant_id: str,
    event_key: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Internal hook called by feature code (invoice creation, ticket etc.).
    Returns a small report; never raises (best-effort by design).

    Iter38r-fix9x — Supports two providers:
      • home_assistant : POST to {ha_url}/api/services/notify/{notify_service}
      • voice_monkey   : POST to the saved Voice Monkey webhook URL
        (announcement param replaced with the rendered TTS template).
    """
    context = context or {}
    try:
        cfg = await db.voice_notifications_config.find_one({"_id": tenant_id}, {"_id": 0}) or {}
        if not cfg or not cfg.get("enabled"):
            return {"ok": False, "reason": "disabled"}
        rule = await db.voice_notifications_rules.find_one(
            {"tenant_id": tenant_id, "event_key": event_key},
            {"_id": 0},
        )
        if not rule or not rule.get("enabled"):
            return {"ok": False, "reason": "no_rule_or_disabled"}
        message = _render_template(rule.get("tts_template") or "", context).strip()
        if not message:
            return {"ok": False, "reason": "empty_message"}
        provider = (cfg.get("provider") or "home_assistant").strip().lower()
        speaker = rule.get("speaker_override") or cfg.get("ha_speaker") or ""
        status_code = 0
        response_text = ""

        if provider == "voice_monkey":
            url = (cfg.get("voice_monkey_url") or "").strip()
            if not url:
                return {"ok": False, "reason": "voice_monkey_url_missing"}
            # Voice Monkey accepts `announcement` either as a query string param
            # or in a JSON body. We POST a JSON payload — the webhook already
            # carries the token + device in the URL.
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    r = await client.post(url, json={
                        "announcement": message,
                        "event": event_key,
                        "source": "sawali-portal",
                    })
                    status_code = r.status_code
                    response_text = (r.text or "")[:500]
            except httpx.HTTPError as exc:
                response_text = f"HTTPError: {exc}"[:500]
        else:
            ha_url = (cfg.get("ha_url") or "").rstrip("/")
            ha_token = cfg.get("ha_token") or ""
            notify_service = cfg.get("notify_service") or "alexa_media"
            if not ha_url or not ha_token:
                return {"ok": False, "reason": "ha_not_configured"}
            endpoint = f"{ha_url}/api/services/notify/{notify_service}"
            payload = {"message": message}
            if speaker:
                payload["target"] = speaker
            headers = {
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json",
            }
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    r = await client.post(endpoint, headers=headers, json=payload)
                    status_code = r.status_code
                    response_text = (r.text or "")[:500]
            except httpx.HTTPError as exc:
                response_text = f"HTTPError: {exc}"[:500]

        await db.voice_notifications_log.insert_one({
            "tenant_id": tenant_id,
            "event_key": event_key,
            "provider": provider,
            "message": message,
            "speaker": speaker,
            "ha_status": status_code,
            "ha_response": response_text,
            "created_at": _now_iso(),
        })
        return {"ok": 200 <= status_code < 300, "provider": provider, "ha_status": status_code, "message": message}
    except Exception as exc:
        logger.exception("[voice-notif] trigger failed")
        return {"ok": False, "reason": f"exception:{str(exc)[:80]}"}


def setup_voice_notifications_routes(app, db, get_current_user):
    api: APIRouter = app

    async def _resolve_event(tenant_id: str, event_key: str) -> Optional[Dict[str, Any]]:
        """Return the event meta for either a built-in or a tenant-custom event."""
        for ev in BUILTIN_CATALOG:
            if ev["key"] == event_key:
                return {**ev, "is_builtin": True}
        custom = await db.voice_notifications_custom.find_one(
            {"tenant_id": tenant_id, "event_key": event_key},
            {"_id": 0},
        )
        if custom:
            return {
                "key": custom["event_key"],
                "label": custom.get("label", custom["event_key"]),
                "module": custom.get("module", ""),
                "page": custom.get("page", ""),
                "db_table": custom.get("db_table", ""),
                "default_tts": custom.get("default_tts", ""),
                "variables": custom.get("variables") or [],
                "category": custom.get("category", "custom"),
                "is_builtin": False,
            }
        return None

    # ---------------- Catalog ----------------
    @api.get("/admin/voice-notifications/catalog", tags=["Admin — Voice Notifications"])
    async def get_catalog(user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        custom_cursor = db.voice_notifications_custom.find({"tenant_id": tid}, {"_id": 0})
        custom = await custom_cursor.to_list(500)
        custom_items = [{
            "key": c["event_key"],
            "label": c.get("label", c["event_key"]),
            "module": c.get("module", ""),
            "page": c.get("page", ""),
            "db_table": c.get("db_table", ""),
            "default_tts": c.get("default_tts", ""),
            "variables": c.get("variables") or [],
            "category": c.get("category", "custom"),
            "is_builtin": False,
        } for c in custom]
        builtin = [{**ev, "is_builtin": True} for ev in BUILTIN_CATALOG]
        return {"builtin": builtin, "custom": custom_items, "total": len(builtin) + len(custom_items)}

    # ---------------- Tenant config ----------------
    @api.get("/admin/voice-notifications/config", tags=["Admin — Voice Notifications"])
    async def get_config(user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        cfg = await db.voice_notifications_config.find_one({"_id": tid}) or {}
        # Mask the token in the response — never expose it raw
        masked_token = ""
        if cfg.get("ha_token"):
            tk = str(cfg["ha_token"])
            masked_token = f"{tk[:4]}…{tk[-4:]}" if len(tk) > 10 else "****"
        # Iter38r-fix9x — Mask the Voice Monkey webhook URL too (contains token)
        vm_url = cfg.get("voice_monkey_url") or ""
        vm_masked = ""
        if vm_url:
            try:
                # Show only the first 30 chars + the device param
                vm_masked = vm_url[:30] + "…" + vm_url[-12:] if len(vm_url) > 50 else vm_url
            except Exception:
                vm_masked = "****"
        return {
            "enabled": bool(cfg.get("enabled")),
            "provider": cfg.get("provider") or "home_assistant",
            "ha_url": cfg.get("ha_url", ""),
            "ha_token_set": bool(cfg.get("ha_token")),
            "ha_token_masked": masked_token,
            "ha_speaker": cfg.get("ha_speaker", ""),
            "notify_service": cfg.get("notify_service", "alexa_media"),
            "voice_monkey_url_set": bool(vm_url),
            "voice_monkey_url_masked": vm_masked,
            "updated_at": cfg.get("updated_at"),
        }

    @api.put("/admin/voice-notifications/config", tags=["Admin — Voice Notifications"])
    async def update_config(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        update: Dict[str, Any] = {"updated_at": _now_iso()}
        if "enabled" in payload:
            update["enabled"] = bool(payload["enabled"])
        if "provider" in payload:
            prov = (payload.get("provider") or "home_assistant").strip().lower()
            if prov not in ("home_assistant", "voice_monkey"):
                raise HTTPException(status_code=400, detail="provider doit être 'home_assistant' ou 'voice_monkey'")
            update["provider"] = prov
        if "ha_url" in payload:
            url = (payload.get("ha_url") or "").strip()
            if url and not (url.startswith("http://") or url.startswith("https://")):
                raise HTTPException(status_code=400, detail="L'URL Home Assistant doit commencer par http:// ou https://")
            update["ha_url"] = url
        if "ha_token" in payload:
            tk = (payload.get("ha_token") or "").strip()
            if tk:  # only update if non-empty (keep existing on blank)
                update["ha_token"] = tk
        if "ha_speaker" in payload:
            update["ha_speaker"] = (payload.get("ha_speaker") or "").strip()
        if "notify_service" in payload:
            update["notify_service"] = (payload.get("notify_service") or "alexa_media").strip()
        if "voice_monkey_url" in payload:
            vm = (payload.get("voice_monkey_url") or "").strip()
            if vm and not (vm.startswith("http://") or vm.startswith("https://")):
                raise HTTPException(status_code=400, detail="L'URL Voice Monkey doit commencer par http:// ou https://")
            if vm:  # only update on non-empty
                update["voice_monkey_url"] = vm
        await db.voice_notifications_config.update_one(
            {"_id": tid}, {"$set": update}, upsert=True,
        )
        return {"ok": True}

    # ---------------- Rules ----------------
    @api.get("/admin/voice-notifications/rules", tags=["Admin — Voice Notifications"])
    async def list_rules(user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        rows = await db.voice_notifications_rules.find({"tenant_id": tid}, {"_id": 0}).to_list(500)
        return {"items": rows, "count": len(rows)}

    @api.put("/admin/voice-notifications/rules/{event_key}", tags=["Admin — Voice Notifications"])
    async def upsert_rule(event_key: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        meta = await _resolve_event(tid, event_key)
        if not meta:
            raise HTTPException(status_code=404, detail="Évènement inconnu. Ajoutez-le d'abord comme évènement personnalisé.")
        update = {
            "tenant_id": tid,
            "event_key": event_key,
            "enabled": bool(payload.get("enabled", False)),
            "tts_template": (payload.get("tts_template") or meta.get("default_tts") or "").strip(),
            "speaker_override": (payload.get("speaker_override") or "").strip() or None,
            "updated_at": _now_iso(),
        }
        await db.voice_notifications_rules.update_one(
            {"tenant_id": tid, "event_key": event_key},
            {"$set": update},
            upsert=True,
        )
        return {"ok": True, "rule": {k: v for k, v in update.items()}}

    # ---------------- Custom events ----------------
    @api.post("/admin/voice-notifications/custom-events", tags=["Admin — Voice Notifications"])
    async def add_custom_event(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        key = (payload.get("event_key") or "").strip().lower()
        if not key or not re.match(r"^[a-z][a-z0-9_]{2,40}$", key):
            raise HTTPException(status_code=400, detail="Clé invalide. Lettres minuscules, chiffres et _ uniquement (3 à 41 caractères).")
        if key in BUILTIN_KEYS:
            raise HTTPException(status_code=409, detail="Cette clé est déjà utilisée par un évènement intégré.")
        existing = await db.voice_notifications_custom.find_one({"tenant_id": tid, "event_key": key}, {"_id": 0})
        if existing:
            raise HTTPException(status_code=409, detail="Un évènement personnalisé avec cette clé existe déjà.")
        doc = {
            "tenant_id": tid,
            "event_key": key,
            "label": (payload.get("label") or "").strip() or key,
            "module": (payload.get("module") or "").strip(),
            "page": (payload.get("page") or "").strip(),
            "db_table": (payload.get("db_table") or "").strip(),
            "default_tts": (payload.get("default_tts") or "").strip(),
            "variables": [str(v).strip() for v in (payload.get("variables") or []) if str(v).strip()],
            "category": (payload.get("category") or "custom").strip(),
            "created_at": _now_iso(),
        }
        await db.voice_notifications_custom.insert_one(doc.copy())
        return {"ok": True, "event": {k: v for k, v in doc.items() if k != "_id"}}

    @api.delete("/admin/voice-notifications/custom-events/{event_key}", tags=["Admin — Voice Notifications"])
    async def delete_custom_event(event_key: str, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        if event_key in BUILTIN_KEYS:
            raise HTTPException(status_code=400, detail="Les évènements intégrés ne peuvent pas être supprimés.")
        res = await db.voice_notifications_custom.delete_one({"tenant_id": tid, "event_key": event_key})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Évènement personnalisé introuvable")
        # Also drop the corresponding rule if any
        await db.voice_notifications_rules.delete_many({"tenant_id": tid, "event_key": event_key})
        return {"ok": True}

    # ---------------- Test pipeline ----------------
    @api.post("/admin/voice-notifications/test", tags=["Admin — Voice Notifications"])
    async def test_voice(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        message = (payload.get("message") or "Test SAWALI : la passerelle vocale fonctionne.").strip()
        speaker = (payload.get("speaker") or "").strip()
        cfg = await db.voice_notifications_config.find_one({"_id": tid}, {"_id": 0}) or {}
        provider = (cfg.get("provider") or "home_assistant").strip().lower()

        if provider == "voice_monkey":
            vm_url = (cfg.get("voice_monkey_url") or "").strip()
            if not vm_url:
                raise HTTPException(status_code=400, detail="URL Voice Monkey manquante.")
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    r = await client.post(vm_url, json={
                        "announcement": message,
                        "event": "__test__",
                        "source": "sawali-portal",
                    })
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=f"Voice Monkey injoignable : {exc}")
            ok = 200 <= r.status_code < 300
            await db.voice_notifications_log.insert_one({
                "tenant_id": tid, "event_key": "__test__", "provider": "voice_monkey",
                "message": message, "speaker": None, "ha_status": r.status_code,
                "ha_response": (r.text or "")[:500], "created_at": _now_iso(),
            })
            return {"ok": ok, "provider": "voice_monkey", "ha_status": r.status_code,
                    "ha_response": (r.text or "")[:500], "message": message}

        # Default: Home Assistant
        if not cfg.get("ha_url") or not cfg.get("ha_token"):
            raise HTTPException(status_code=400, detail="Configuration Home Assistant incomplète (URL + Token requis).")
        ha_url = cfg["ha_url"].rstrip("/")
        ha_token = cfg["ha_token"]
        notify_service = cfg.get("notify_service") or "alexa_media"
        endpoint = f"{ha_url}/api/services/notify/{notify_service}"
        body: Dict[str, Any] = {"message": message}
        target = speaker or cfg.get("ha_speaker")
        if target:
            body["target"] = target
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Home Assistant injoignable : {exc}")
        ok = 200 <= r.status_code < 300
        await db.voice_notifications_log.insert_one({
            "tenant_id": tid, "event_key": "__test__", "provider": "home_assistant",
            "message": message, "speaker": target, "ha_status": r.status_code,
            "ha_response": (r.text or "")[:500], "created_at": _now_iso(),
        })
        return {"ok": ok, "provider": "home_assistant", "ha_status": r.status_code,
                "ha_response": (r.text or "")[:500], "message": message, "target": target}

    @api.get("/admin/voice-notifications/log", tags=["Admin — Voice Notifications"])
    async def get_log(limit: int = 50, user: dict = Depends(get_current_user)):
        _ensure_admin(user)
        tid = _tenant_id(user)
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 50
        cursor = db.voice_notifications_log.find({"tenant_id": tid}, {"_id": 0}).sort("created_at", -1)
        items = await cursor.to_list(limit)
        return {"items": items, "count": len(items)}

    # ---------------- Manual trigger (auth-gated) ----------------
    @api.post("/voice-notifications/trigger", tags=["Voice Notifications"])
    async def manual_trigger(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Utilisé par les utilisateurs suivis ou l'admin pour envoyer une notification vocale
        explicitly (e.g. button in the UI). The rule must be enabled."""
        tid = _tenant_id(user)
        event_key = (payload.get("event_key") or "").strip()
        if not event_key:
            raise HTTPException(status_code=400, detail="event_key requis")
        context = payload.get("context") or {}
        if not isinstance(context, dict):
            raise HTTPException(status_code=400, detail="context doit être un objet JSON")
        result = await trigger_voice_event(db, tid, event_key, context)
        return result

    return api
