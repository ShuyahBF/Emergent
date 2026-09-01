"""Iter43-fix24ay (2026-02-26) — Google Calendar Watch API (Phase 2 push sync).

Registers a Google Calendar **watch channel** so any external change in the
admin's calendar (new event, update, delete) triggers a webhook on our backend
within seconds. We then call `events.list?syncToken=...` to pull the delta
and reflect it in `db.appointments`.

Endpoints :
  - POST /api/admin/google/calendar/watch         — start watch (admin)
  - DELETE /api/admin/google/calendar/watch       — stop watch (admin)
  - GET    /api/admin/google/calendar/watch       — current watch status
  - POST   /api/google/calendar/webhook           — receives push notifications
                                                      (Google calls this, no auth header)
  - POST   /api/admin/google/calendar/sync-now    — force a one-shot sync

Storage in `settings.global` :
  - `google_calendar_watch_channel_id` (str, unique UUID we generate)
  - `google_calendar_watch_resource_id` (str, returned by Google — required to STOP the watch)
  - `google_calendar_watch_resource_uri`
  - `google_calendar_watch_expiration` (datetime ISO)
  - `google_calendar_sync_token` (str, opaque, for incremental events.list)
  - `google_calendar_watch_last_notification` (datetime ISO)
  - `google_calendar_webhook_secret` (str, our shared secret in the channel token)
  - `google_calendar_watch_renewed_at` (datetime ISO)

Cron :
  - Every 6 hours, renew the watch channel if expiration is < 24 h away.
"""
from __future__ import annotations

import logging
import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Body, Depends, HTTPException, Request

import google_calendar as gcal

logger = logging.getLogger("sawali.google_calendar.watch")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


def _compute_webhook_url(request: Request, settings: Dict[str, Any]) -> str:
    """Build the public HTTPS URL where Google will POST notifications.
    Google REQUIRES HTTPS — preview & prod both are."""
    explicit = (settings.get("google_calendar_watch_webhook_url") or "").strip()
    if explicit:
        return explicit
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    fwd_proto = request.headers.get("x-forwarded-proto") or "https"
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}/api/google/calendar/webhook"
    raise HTTPException(status_code=500, detail="Impossible de calculer l'URL webhook (X-Forwarded-Host manquant)")


async def _start_watch(db, calendar_id: str, webhook_url: str) -> Dict[str, Any]:
    service = await gcal._build_service()  # noqa: SLF001 — internal helper
    if not service:
        raise HTTPException(status_code=400, detail="Google Calendar non configuré. Connectez-le d'abord (Admin → Settings → Google Calendar).")
    channel_id = f"sawali-{pysecrets.token_urlsafe(20)}"
    secret = pysecrets.token_urlsafe(32)
    body = {
        "id": channel_id,
        "type": "web_hook",
        "address": webhook_url,
        "token": secret,  # Google echoes this back in X-Goog-Channel-Token
        "params": {"ttl": "604800"},  # 7 days max for Calendar events watch
    }
    try:
        resp = service.events().watch(calendarId=calendar_id, body=body).execute()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Échec watch Google : {exc}") from exc

    # Returns: kind, id, resourceId, resourceUri, token, expiration (ms epoch)
    expiration_ms = int(resp.get("expiration") or 0)
    expiration_dt = datetime.fromtimestamp(expiration_ms / 1000, tz=timezone.utc) if expiration_ms else None

    # Initialize sync token via events.list (full sync), then store nextSyncToken
    try:
        ev = service.events().list(calendarId=calendar_id, maxResults=1, showDeleted=False, singleEvents=True).execute()
        sync_token = ev.get("nextSyncToken") or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("[gcal.watch] events.list initial sync failed: %s", exc)
        sync_token = ""

    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "google_calendar_watch_channel_id": channel_id,
            "google_calendar_watch_resource_id": resp.get("resourceId", ""),
            "google_calendar_watch_resource_uri": resp.get("resourceUri", ""),
            "google_calendar_watch_expiration": expiration_dt.isoformat() if expiration_dt else None,
            "google_calendar_watch_webhook_url": webhook_url,
            "google_calendar_watch_calendar_id": calendar_id,
            "google_calendar_webhook_secret": secret,
            "google_calendar_sync_token": sync_token,
            "google_calendar_watch_renewed_at": _now_iso(),
        }},
    )
    return {
        "channel_id": channel_id,
        "resource_id": resp.get("resourceId", ""),
        "expiration": expiration_dt.isoformat() if expiration_dt else None,
        "webhook_url": webhook_url,
        "calendar_id": calendar_id,
    }


async def _stop_watch(db) -> bool:
    s = await db.settings.find_one({"_id": "global"}) or {}
    cid = s.get("google_calendar_watch_channel_id")
    rid = s.get("google_calendar_watch_resource_id")
    if not cid or not rid:
        return False
    service = await gcal._build_service()  # noqa: SLF001
    if not service:
        return False
    try:
        service.channels().stop(body={"id": cid, "resourceId": rid}).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[gcal.watch] stop failed (channel may already be expired): %s", exc)
    await db.settings.update_one(
        {"_id": "global"},
        {"$unset": {
            "google_calendar_watch_channel_id": "",
            "google_calendar_watch_resource_id": "",
            "google_calendar_watch_resource_uri": "",
            "google_calendar_watch_expiration": "",
            "google_calendar_watch_webhook_url": "",
            "google_calendar_watch_calendar_id": "",
            "google_calendar_webhook_secret": "",
        }},
    )
    return True


async def _sync_events_incremental(db, calendar_id: str) -> Dict[str, Any]:
    """Pull changes since last sync_token. Returns counts of created/updated/deleted."""
    service = await gcal._build_service()  # noqa: SLF001
    if not service:
        raise HTTPException(status_code=400, detail="Google Calendar non configuré")
    s = await db.settings.find_one({"_id": "global"}) or {}
    sync_token = s.get("google_calendar_sync_token") or ""

    created = updated = deleted = 0
    page_token = None
    new_sync_token = sync_token

    while True:
        kwargs: Dict[str, Any] = {"calendarId": calendar_id, "maxResults": 250}
        if page_token:
            kwargs["pageToken"] = page_token
        elif sync_token:
            kwargs["syncToken"] = sync_token
        else:
            # First sync — last 24h only to avoid pulling all history
            kwargs["timeMin"] = (_now_dt() - timedelta(hours=24)).isoformat()
            kwargs["showDeleted"] = True

        try:
            resp = service.events().list(**kwargs).execute()
        except Exception as exc:  # noqa: BLE001
            # 410 Gone = sync_token expired → restart full sync
            msg = str(exc)
            if "410" in msg or "Gone" in msg or "syncTokenInvalid" in msg:
                logger.info("[gcal.watch] sync_token expired, restarting full sync")
                await db.settings.update_one(
                    {"_id": "global"}, {"$unset": {"google_calendar_sync_token": ""}}
                )
                return {"created": 0, "updated": 0, "deleted": 0, "sync_token_expired": True}
            raise HTTPException(status_code=502, detail=f"Sync incrémental échoué : {exc}") from exc

        for ev in resp.get("items", []):
            event_id = ev.get("id")
            status = ev.get("status")
            if status == "cancelled":
                r = await db.appointments.update_one(
                    {"google_event_id": event_id},
                    {"$set": {"status": "cancelled", "google_synced_at": _now_iso()}},
                )
                if r.modified_count:
                    deleted += 1
            else:
                doc = {
                    "google_event_id": event_id,
                    "summary": ev.get("summary", ""),
                    "description": ev.get("description", ""),
                    "start": (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date"),
                    "end": (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date"),
                    "attendees": [a.get("email") for a in (ev.get("attendees") or []) if a.get("email")],
                    "google_calendar_id": calendar_id,
                    "google_synced_at": _now_iso(),
                    "status": "confirmed",
                }
                r = await db.appointments.update_one(
                    {"google_event_id": event_id},
                    {"$set": doc, "$setOnInsert": {"id": event_id, "created_at": _now_iso(), "source": "google_watch"}},
                    upsert=True,
                )
                if r.upserted_id:
                    created += 1
                elif r.modified_count:
                    updated += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            new_sync_token = resp.get("nextSyncToken") or new_sync_token
            break

    if new_sync_token and new_sync_token != sync_token:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "google_calendar_sync_token": new_sync_token,
                "google_calendar_last_sync_at": _now_iso(),
            }},
        )
    return {"created": created, "updated": updated, "deleted": deleted, "sync_token_expired": False}


async def run_google_calendar_watch_renewal_tick(db):
    """Cron tick (every 6h) : renew the watch channel if expiration < 24h away."""
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        exp_iso = s.get("google_calendar_watch_expiration")
        if not exp_iso:
            return
        try:
            exp_dt = datetime.fromisoformat(exp_iso)
        except (TypeError, ValueError):
            return
        # Refresh if less than 24h left
        if exp_dt - _now_dt() > timedelta(hours=24):
            return
        webhook_url = s.get("google_calendar_watch_webhook_url") or ""
        calendar_id = s.get("google_calendar_watch_calendar_id") or s.get("google_calendar_email") or "primary"
        if not webhook_url:
            logger.warning("[gcal.watch] cannot auto-renew: webhook_url missing")
            return
        # Stop the current one, then re-create
        await _stop_watch(db)
        result = await _start_watch(db, calendar_id, webhook_url)
        logger.info("[gcal.watch] auto-renewed → expires %s", result.get("expiration"))
    except Exception as exc:  # noqa: BLE001
        logger.error("[gcal.watch] renewal tick error: %s", exc, exc_info=True)


def attach_google_calendar_watch_routes(*, api, db, get_current_admin, get_current_user=None):

    @api.get("/admin/google/calendar/watch", tags=["Admin — Google Calendar"])
    async def get_watch_status(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        active = bool(s.get("google_calendar_watch_channel_id"))
        return {
            "active": active,
            "channel_id": s.get("google_calendar_watch_channel_id", ""),
            "resource_id": s.get("google_calendar_watch_resource_id", ""),
            "webhook_url": s.get("google_calendar_watch_webhook_url", ""),
            "calendar_id": s.get("google_calendar_watch_calendar_id", ""),
            "expiration": s.get("google_calendar_watch_expiration"),
            "renewed_at": s.get("google_calendar_watch_renewed_at"),
            "last_notification_at": s.get("google_calendar_watch_last_notification"),
            "last_sync_at": s.get("google_calendar_last_sync_at"),
            "sync_token_set": bool(s.get("google_calendar_sync_token")),
        }

    @api.post("/admin/google/calendar/watch", tags=["Admin — Google Calendar"])
    async def start_watch(
        request: Request,
        payload: Optional[Dict[str, Any]] = Body(None),
        _: dict = Depends(get_current_admin),
    ) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        calendar_id = (payload or {}).get("calendar_id") or s.get("google_calendar_email") or "primary"
        webhook_url = (payload or {}).get("webhook_url") or _compute_webhook_url(request, s)
        # Stop any pre-existing watch before starting a fresh one
        await _stop_watch(db)
        result = await _start_watch(db, calendar_id, webhook_url)
        return {"ok": True, **result}

    @api.delete("/admin/google/calendar/watch", tags=["Admin — Google Calendar"])
    async def stop_watch(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        ok = await _stop_watch(db)
        return {"ok": ok}

    @api.post("/admin/google/calendar/sync-now", tags=["Admin — Google Calendar"])
    async def sync_now(_: dict = Depends(get_current_admin)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        calendar_id = s.get("google_calendar_watch_calendar_id") or s.get("google_calendar_email") or "primary"
        result = await _sync_events_incremental(db, calendar_id)
        return {"ok": True, **result}

    # 2026-02 fork iter107 — Bouton "Synchroniser" côté portail client
    # (/portal/appointments) : accessible à tout utilisateur authentifié,
    # renvoie le même résumé que le sync admin.
    # 2026-02 fork iter108 fix — Ajout de l'auth pour prévenir un abus
    # d'endpoint anonyme (rapport testing_agent iter97).
    _auth_dep = get_current_user or get_current_admin
    @api.post("/me/appointments/gcal-sync", tags=["Portail Client"])
    async def me_gcal_sync_now(_: dict = Depends(_auth_dep)) -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        calendar_id = s.get("google_calendar_watch_calendar_id") or s.get("google_calendar_email") or "primary"
        result = await _sync_events_incremental(db, calendar_id)
        return {"ok": True, **result}

    @api.post("/google/calendar/webhook", tags=["Google Calendar"], include_in_schema=False)
    async def receive_webhook(request: Request) -> Dict[str, Any]:
        """Google calls this on every calendar change. Verify the channel token,
        then fetch the delta via syncToken."""
        ch_id = request.headers.get("x-goog-channel-id", "")
        ch_token = request.headers.get("x-goog-channel-token", "")
        resource_state = request.headers.get("x-goog-resource-state", "")
        resource_id = request.headers.get("x-goog-resource-id", "")
        msg_no = request.headers.get("x-goog-message-number", "")
        s = await db.settings.find_one({"_id": "global"}) or {}
        expected_id = s.get("google_calendar_watch_channel_id", "")
        expected_secret = s.get("google_calendar_webhook_secret", "")
        if not expected_id or ch_id != expected_id or ch_token != expected_secret:
            logger.warning(
                "[gcal.watch] webhook rejected: ch_id=%s expected=%s token_match=%s",
                ch_id, expected_id, ch_token == expected_secret,
            )
            raise HTTPException(status_code=403, detail="Invalid channel id/token")

        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"google_calendar_watch_last_notification": _now_iso()}},
        )
        # 'sync' is the initial confirmation message — don't fetch events yet
        if resource_state == "sync":
            logger.info("[gcal.watch] webhook init OK (sync msg)")
            return {"ok": True, "state": "sync"}

        # 'exists' (event added/updated) or 'not_exists' (event deleted)
        calendar_id = s.get("google_calendar_watch_calendar_id") or s.get("google_calendar_email") or "primary"
        try:
            result = await _sync_events_incremental(db, calendar_id)
            logger.info(
                "[gcal.watch] notif #%s state=%s rid=%s → created=%d updated=%d deleted=%d",
                msg_no, resource_state, resource_id,
                result.get("created", 0), result.get("updated", 0), result.get("deleted", 0),
            )
            return {"ok": True, "state": resource_state, **result}
        except HTTPException as exc:
            logger.error("[gcal.watch] webhook sync error: %s", exc.detail)
            # Always 200 to Google to avoid Google disabling the channel
            return {"ok": False, "error": exc.detail}

    logger.info("[gcal.watch] routes mounted under /api/admin/google/calendar/watch + /api/google/calendar/webhook")
