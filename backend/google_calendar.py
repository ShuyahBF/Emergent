"""Google Calendar integration with admin-configurable OAuth credentials.

Credentials (client_id, client_secret, refresh_token) are stored in the
`settings` collection. The admin obtains the refresh_token by completing the
OAuth flow via /api/admin/google/auth-url + /api/admin/google/callback.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from db import db

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


async def _get_settings() -> dict:
    return await db.settings.find_one({"_id": "global"}) or {}


async def is_configured() -> bool:
    s = await _get_settings()
    return bool(
        s.get("google_client_id")
        and s.get("google_client_secret")
        and s.get("google_refresh_token")
    )


async def _build_service():
    """Build authenticated calendar service or return None if not configured."""
    if not await is_configured():
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GoogleRequest
        from googleapiclient.discovery import build
    except ImportError as e:
        logger.error("google libs missing: %s", e)
        return None

    s = await _get_settings()
    creds = Credentials(
        token=s.get("google_access_token"),
        refresh_token=s.get("google_refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s["google_client_id"],
        client_secret=s["google_client_secret"],
        scopes=SCOPES,
    )
    if not creds.valid:
        try:
            creds.refresh(GoogleRequest())
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"google_access_token": creds.token}},
            )
        except Exception as e:
            logger.error("Google token refresh failed: %s", e)
            return None
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _build_oauth_flow(client_id: str, client_secret: str, redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


async def get_auth_url(redirect_uri: str) -> Optional[str]:
    s = await _get_settings()
    if not s.get("google_client_id") or not s.get("google_client_secret"):
        return None
    flow = _build_oauth_flow(s["google_client_id"], s["google_client_secret"], redirect_uri)
    # IMPORTANT:
    #   - access_type=offline  -> required to receive a refresh_token
    #   - prompt=consent       -> force Google to re-deliver refresh_token even after past grants
    #   - DO NOT pass include_granted_scopes: it makes Google skip refresh_token issuance when
    #     the scope was already granted (current bug we're fixing).
    url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent select_account",
    )
    # Iter43-fix24an (2026-06-17) — PKCE: google_auth_oauthlib génère
    # automatiquement un `code_verifier` + `code_challenge` (S256). Le challenge
    # est envoyé à Google dans l'URL auth ; le verifier doit accompagner le
    # `code` lors du POST `/token` (sinon Google répond "Missing code verifier").
    # Comme `get_auth_url` et `exchange_code` sont 2 requêtes HTTP distinctes,
    # on persiste le `code_verifier` dans `settings` pour le récupérer ensuite.
    cv = getattr(flow, "code_verifier", None)
    if cv:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"google_oauth_code_verifier": cv}},
            upsert=True,
        )
    else:
        # Aucun verifier généré → flux non-PKCE. On nettoie tout résidu.
        await db.settings.update_one(
            {"_id": "global"},
            {"$unset": {"google_oauth_code_verifier": ""}},
        )
    return url


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for tokens, store refresh token."""
    import httpx

    s = await _get_settings()
    if not s.get("google_client_id") or not s.get("google_client_secret"):
        raise RuntimeError("Google OAuth client not configured")

    # Iter43-fix24an (2026-06-17) — Récupère le `code_verifier` PKCE stocké
    # par `get_auth_url`. Sans lui, Google répond "Missing code verifier".
    data = {
        "code": code,
        "client_id": s["google_client_id"],
        "client_secret": s["google_client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    code_verifier = s.get("google_oauth_code_verifier")
    if code_verifier:
        data["code_verifier"] = code_verifier

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://oauth2.googleapis.com/token",
            data=data,
        )
        token = r.json()

    if "refresh_token" not in token:
        # If Google didn't return a refresh_token, it means the user has previously
        # granted access to this OAuth client. We must force re-consent.
        # On surface l'erreur Google explicite (`error` / `error_description`)
        # pour aider l'admin à diagnostiquer (ex: "Missing code verifier",
        # "invalid_grant", "redirect_uri_mismatch"…).
        err = token.get("error") or ""
        msg = token.get("error_description") or err or "OK mais pas de refresh_token"
        raise RuntimeError(
            "Aucun refresh_token reçu. Allez sur https://myaccount.google.com/permissions, "
            "supprimez l'accès de cette app, puis recommencez. "
            f"(Détail Google : {msg})"
        )
    update = {
        "google_refresh_token": token["refresh_token"],
        "google_access_token": token.get("access_token"),
    }
    # Nettoie le verifier après usage (one-shot — pas réutilisable).
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": update, "$unset": {"google_oauth_code_verifier": ""}},
        upsert=True,
    )
    return {"ok": True}


async def create_event(
    summary: str,
    description: str,
    start_iso: str,
    end_iso: str,
    attendee_email: Optional[str] = None,
    timezone_str: str = "UTC",
) -> Optional[str]:
    """Create event on configured calendar. Returns event id or None."""
    service = await _build_service()
    if service is None:
        return None
    s = await _get_settings()
    calendar_id = s.get("google_calendar_email") or "primary"

    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": timezone_str},
        "end": {"dateTime": end_iso, "timeZone": timezone_str},
    }
    if attendee_email:
        body["attendees"] = [{"email": attendee_email}]

    try:
        event = service.events().insert(calendarId=calendar_id, body=body).execute()
        return event.get("id")
    except Exception as e:
        logger.error("GCal create_event failed: %s", e)
        return None


async def freebusy(start_iso: str, end_iso: str) -> list[dict]:
    """Return list of busy intervals from configured calendar."""
    service = await _build_service()
    if service is None:
        return []
    s = await _get_settings()
    calendar_id = s.get("google_calendar_email") or "primary"
    try:
        body = {"timeMin": start_iso, "timeMax": end_iso, "items": [{"id": calendar_id}]}
        res = service.freebusy().query(body=body).execute()
        return res.get("calendars", {}).get(calendar_id, {}).get("busy", [])
    except Exception as e:
        logger.error("GCal freebusy failed: %s", e)
        return []


# Iter43-fix24ao (2026-06-17) — Diagnostic helper used by the admin
# "Tester connexion" button. Lists the N next upcoming events on the
# configured calendar to confirm OAuth + API access work end-to-end.
async def list_upcoming_events(max_results: int = 3) -> list[dict]:
    """List upcoming events on the configured calendar.

    Raises an Exception (RuntimeError / Google API error) if the service
    cannot be built or the API call fails. The caller is expected to
    catch and surface the message to the admin.
    """
    service = await _build_service()
    if service is None:
        raise RuntimeError(
            "Impossible de construire le service Google Calendar. Le refresh_token "
            "est peut-être expiré ou révoqué — recommencez la connexion."
        )
    s = await _get_settings()
    calendar_id = s.get("google_calendar_email") or "primary"
    now_iso = datetime.now(timezone.utc).isoformat()
    res = service.events().list(
        calendarId=calendar_id,
        timeMin=now_iso,
        maxResults=int(max_results),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    items = res.get("items", []) or []
    # Return a compact, JSON-serializable summary (not the raw bloated Google obj)
    return [
        {
            "id": ev.get("id"),
            "summary": ev.get("summary") or "(sans titre)",
            "start": (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date"),
            "end": (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date"),
            "html_link": ev.get("htmlLink"),
            "status": ev.get("status"),
        }
        for ev in items
    ]


async def update_event(
    event_id: str,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    timezone_str: str = "UTC",
) -> bool:
    """Patch an event on the configured calendar."""
    service = await _build_service()
    if service is None:
        return False
    s = await _get_settings()
    calendar_id = s.get("google_calendar_email") or "primary"
    body: dict = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if start_iso is not None:
        body["start"] = {"dateTime": start_iso, "timeZone": timezone_str}
    if end_iso is not None:
        body["end"] = {"dateTime": end_iso, "timeZone": timezone_str}
    if not body:
        return True
    try:
        service.events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute()
        return True
    except Exception as e:
        logger.error("GCal update_event failed: %s", e)
        return False


async def delete_event(event_id: str) -> bool:
    service = await _build_service()
    if service is None:
        return False
    s = await _get_settings()
    calendar_id = s.get("google_calendar_email") or "primary"
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return True
    except Exception as e:
        logger.error("GCal delete_event failed: %s", e)
        return False
