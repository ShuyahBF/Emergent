"""S045 Phase 2 (2026-02) — Admin settings & incidents read-only endpoints.

Extraits depuis `server.py` sans changement comportemental :
  GET    /admin/settings                       — get full settings (sensitive masked)
  POST   /admin/settings/test-url              — dry-run http test on a configured URL
  GET    /admin/secrets/change-audit           — vault tracker audit list
  GET    /admin/incidents                      — incident history
  DELETE /admin/incidents/{id}                 — soft-delete an incident
  GET    /admin/incidents/export.csv           — CSV export

NOTE : `PUT /admin/settings` reste dans `server.py` car son corps mélange la
mise à jour avec la création/résolution d'incidents et de nombreux side-effects
(broadcast subscribers, audit secret-changes, refresh public_base_url cache).
Ce bloc fera l'objet d'une sous-phase dédiée.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("sawali.admin_settings")


# These must match the lists in server.py.
GET_MASK_FIELDS = (
    "smtp_password", "google_client_secret", "recaptcha_secret_key",
    "google_calendar_password_hint", "tracking_auth_header",
    "webhook_token", "webhook_basic_pass", "notes_webhook_token",
    "notes_webhook_basic_pass", "health_webhook_token", "health_webhook_basic_pass",
    "wa_access_token", "wa_verify_token",
    "openai_api_key", "openai_chat_api_key",
    "n8n_webhook_token", "n8n_webhook_basic_pass",
    "sms_orange_token", "sms_orange_basic_pass", "sms_orange_header_value", "sms_orange_client_secret",
    "sms_moov_token", "sms_moov_basic_pass", "sms_moov_header_value", "sms_moov_client_secret",
    "sms_telecel_token", "sms_telecel_basic_pass", "sms_telecel_header_value", "sms_telecel_client_secret",
    "sms_ovh_application_secret", "sms_ovh_consumer_key",
    "pawapay_api_token", "pawapay_api_token_sandbox", "pawapay_api_token_production", "pawapay_callback_secret",
    "agenda_n8n_outbound_token", "agenda_n8n_outbound_basic_pass", "agenda_n8n_inbound_secret",
    "stripe_webhook_secret",
    "vidal_test_app_key", "vidal_prod_app_key",
    "officines_api_token",
    "officines_register_hmac_secret",
    # Iter43-fix23b — Bird.com (sensible) + officines inventory webhook
    "bird_access_key",
    "bird_webhook_secret",
    "officines_inventory_webhook_token",
    # Iter43-fix24au — LinkedIn integration secrets
    "linkedin_client_secret",
    "linkedin_access_token",
    "linkedin_refresh_token",
    # Iter43-fix24aw — Google Maps geocoding API key
    "google_maps_api_key",
    # Iter43-fix24ax — Twitter (X) integration secrets
    "twitter_client_secret",
    "twitter_access_token",
    "twitter_refresh_token",
    # Iter43-fix24ax — Facebook Page integration secrets
    "facebook_app_secret",
    "facebook_user_access_token",
    "facebook_page_access_token",
)


TESTABLE_URL_KEYS: Set[str] = {
    "public_base_url",
    "tracking_base_url",  # tested in combination with tracking_endpoint
    "webhook_base_url",
    "notes_webhook_url",
    "health_webhook_url",
    "n8n_webhook_url",
    "alexa_webhook_url",
}


class CriticalUrlTestRequest(BaseModel):
    key: str
    method: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def attach_admin_settings_routes(*, api, db, get_current_admin, get_settings_doc):
    """Mount admin settings/secrets/incidents read-only endpoints.

    Args:
      api: the FastAPI APIRouter already mounted as `/api`
      db:  the motor AsyncIOMotor database
      get_current_admin: FastAPI dependency for the admin token
      get_settings_doc:  coroutine returning the global settings doc (no mask)
    """

    @api.get("/admin/settings", tags=["Admin"])
    async def admin_get_settings(_: dict = Depends(get_current_admin)):
        s = await get_settings_doc()
        masked = dict(s)
        for k in GET_MASK_FIELDS:
            if masked.get(k):
                masked[k] = "********"
        masked["google_calendar_connected"] = bool(
            (await db.settings.find_one({"_id": "global"}) or {}).get("google_refresh_token")
        )
        return masked

    @api.post("/admin/settings/test-url", tags=["Admin"])
    async def admin_test_critical_url(
        payload: CriticalUrlTestRequest = Body(...),
        _: dict = Depends(get_current_admin),
    ):
        key = (payload.key or "").strip()
        if key not in TESTABLE_URL_KEYS:
            raise HTTPException(status_code=400, detail=f"Clé non testable : {key}")
        s = await db.settings.find_one({"_id": "global"}) or {}
        raw_url = (s.get(key) or "").strip()
        if not raw_url:
            raise HTTPException(status_code=400, detail=f"{key} n'est pas configuré")
        if key == "tracking_base_url":
            ep = (s.get("tracking_endpoint") or "").strip()
            final_url = raw_url.rstrip("/") + (ep if ep.startswith("/") else f"/{ep}" if ep else "")
        else:
            final_url = raw_url
        if not final_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="URL invalide (doit commencer par http:// ou https://)")

        method = (payload.method or ("GET" if key == "public_base_url" else "POST")).upper()
        body = {
            "dry_run": True,
            "source": "sawali-coffre-fort-test",
            "key": key,
            "timestamp": _now(),
            "message": "Ping de test depuis le Coffre-fort. Aucune action attendue.",
        }
        started = datetime.now(timezone.utc)
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                if method == "GET":
                    r = await http.get(final_url)
                else:
                    r = await http.post(final_url, json=body, headers={"Accept": "application/json"})
            elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            try:
                resp_body = r.json()
                resp_kind = "json"
            except Exception:  # noqa: BLE001
                resp_body = (r.text or "")[:1000]
                resp_kind = "text"
            ok = 200 <= r.status_code < 400
            return {
                "ok": ok,
                "key": key,
                "method": method,
                "final_url": final_url,
                "http_status": r.status_code,
                "elapsed_ms": elapsed_ms,
                "response_kind": resp_kind,
                "response": resp_body,
            }
        except httpx.TimeoutException:
            return {"ok": False, "key": key, "method": method, "final_url": final_url, "error": "Timeout (>15s)"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "key": key, "method": method, "final_url": final_url, "error": str(exc)[:300]}

    @api.get("/admin/secrets/change-audit", tags=["Admin"])
    async def admin_secret_change_audit(
        key: Optional[str] = None,
        limit: int = 100,
        _: dict = Depends(get_current_admin),
    ):
        """Audit trail of vault-tracked key changes (no values, only fingerprints)."""
        q: Dict[str, Any] = {}
        if key:
            q["key"] = key
        items = await db.secret_change_audit.find(q, {"_id": 0}).sort("ts", -1).to_list(min(max(limit, 1), 1000))
        return {"items": items, "total": len(items)}

    @api.get("/admin/incidents", tags=["Admin"])
    async def admin_list_incidents(
        limit: int = 200,
        _: dict = Depends(get_current_admin),
    ):
        items = await db.incidents.find({}, {"_id": 0}).sort("started_at", -1).to_list(min(max(limit, 1), 1000))
        return items

    @api.delete("/admin/incidents/{incident_id}", tags=["Admin"])
    async def admin_delete_incident(incident_id: str, _: dict = Depends(get_current_admin)):
        res = await db.incidents.delete_one({"id": incident_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Incident introuvable")
        return {"ok": True}

    @api.get("/admin/incidents/export.csv", tags=["Admin"])
    async def admin_export_incidents_csv(_: dict = Depends(get_current_admin)):
        items = await db.incidents.find({}, {"_id": 0}).sort("started_at", -1).to_list(2000)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "started_at", "resolved_at", "duration_minutes", "severity", "status",
            "message", "link_url", "created_by", "resolved_by", "updates_count",
        ])
        for it in items:
            writer.writerow([
                it.get("started_at", ""), it.get("resolved_at") or "",
                it.get("duration_minutes") if it.get("duration_minutes") is not None else "",
                it.get("severity", ""), it.get("status", ""),
                (it.get("message") or "")[:500], it.get("link_url") or "",
                it.get("created_by") or "", it.get("resolved_by") or "",
                len(it.get("updates") or []),
            ])
        return JSONResponse(content={"csv": buf.getvalue()}, headers={"Cache-Control": "no-store"})


__all__ = ["attach_admin_settings_routes", "GET_MASK_FIELDS", "TESTABLE_URL_KEYS"]
