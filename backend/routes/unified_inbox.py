"""
Iter38i — Unified omnichannel inbox.
Aggregates threads from WhatsApp (db.whatsapp_messages) and Messenger
(db.meta_messenger_messages) into a single per-thread, recency-sorted view.

Endpoints:
  GET  /api/me/inbox/unified                — list threads (most recent first)
  GET  /api/me/inbox/unified/{thread_key}   — list messages of a single thread
"""
from __future__ import annotations
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.inbox")


class InboxSendPayload(BaseModel):
    channel: str = Field(..., pattern="^(whatsapp|sms|messenger)$")
    thread_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=4000)
    page_id: Optional[str] = None  # required for messenger


def setup_unified_inbox_routes(*, db, api, get_current_user, _normalize_features, wa_send_text=None, sms_send_text=None, meta_get_meta_settings=None):
    """Mount the unified inbox endpoints on the provided `api` router.

    Optional integrations:
      - wa_send_text(to_e164, text) -> dict({"ok", "message_id", "status", "error"})
      - sms_send_text(user, msisdn, text) -> dict({"ok", "id", "status", "error"})
      - meta_get_meta_settings() -> dict with meta_app_secret / graph_version  (currently unused;
        Messenger sends will route through Graph using the stored page token).
    """

    async def _tenant_id(user: dict) -> str:
        return user.get("client_id") or user.get("id")

    async def _tenant_features(tid: str) -> Dict[str, bool]:
        u = await db.users.find_one({"id": tid}, {"_id": 0, "features": 1})
        return _normalize_features((u or {}).get("features") or {})

    def _ts_to_iso(value: Any) -> str:
        """Best-effort coercion of various stored shapes (ISO string, datetime, epoch_ms) to ISO."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, (int, float)):
            # Heuristic: ms vs seconds
            seconds = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        return str(value)

    @api.get("/me/inbox/unified", tags=["Portail Client — Inbox"])
    async def unified_inbox(limit: int = Query(40, ge=1, le=200), user: dict = Depends(get_current_user)):
        """Return up to `limit` threads from WhatsApp + Messenger, recency-sorted.

        Each thread groups messages by:
          - WhatsApp: phone number (`to_number` for outbound, `from` for inbound)
          - Messenger: `(page_id, peer_psid)` where peer_psid is the non-page participant

        For each thread we include: channel, peer_id, peer_name, preview, last_at,
        unread_count, and the underlying counts.
        """
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        threads: List[Dict[str, Any]] = []

        # ---- WhatsApp ----
        wa_query: Dict[str, Any] = {"client_id": tid} if user.get("role") != "admin" else {}
        # Aggregate last 500 messages by phone
        wa_msgs = await db.whatsapp_messages.find(
            wa_query, {"_id": 0, "to_number": 1, "to": 1, "from": 1, "direction": 1,
                       "text": 1, "body": 1, "message_type": 1, "media_url": 1,
                       "phone_digits": 1, "created_at": 1, "read_by_us_at": 1,
                       "contact_name": 1, "name": 1, "ai_generated": 1},
        ).sort("created_at", -1).to_list(500)

        # Iter38r-fix9i — Pre-fetch contacts and build a phone→contact index so
        # we can hydrate peer_name/avatar/code for inbox threads.
        contact_index: Dict[str, Dict[str, Any]] = {}
        try:
            async for c in db.directory_contacts.find(
                {"owner_id": tid} if user.get("role") != "admin" else {},
                {"_id": 0, "id": 1, "name": 1, "phone": 1, "phone_digits": 1,
                 "code": 1, "photo_url": 1, "email": 1},
            ):
                digits = (c.get("phone_digits") or "").lstrip("+")
                if not digits and c.get("phone"):
                    digits = "".join(ch for ch in c["phone"] if ch.isdigit())
                if digits:
                    contact_index[digits] = c
        except Exception:
            pass

        def _digits(s: Any) -> str:
            return "".join(ch for ch in (str(s or "")) if ch.isdigit())

        wa_by_peer: Dict[str, Dict[str, Any]] = {}
        for m in wa_msgs:
            # Outbound messages use either `to` or `to_number`. Inbound uses `from`.
            raw_peer = m.get("from") if m.get("direction") == "inbound" else (m.get("to") or m.get("to_number"))
            peer = raw_peer or m.get("phone_digits") or "unknown"
            digits = _digits(peer)
            matched = contact_index.get(digits) or (digits and contact_index.get(digits.lstrip("0")))
            slot = wa_by_peer.setdefault(peer, {
                "channel": "whatsapp", "peer_id": peer,
                "peer_name": (matched or {}).get("name") or m.get("contact_name") or m.get("name") or (f"+{digits}" if digits else peer),
                "peer_phone": digits and f"+{digits}",
                "peer_photo_url": (matched or {}).get("photo_url"),
                "peer_code": (matched or {}).get("code"),
                "contact_id": (matched or {}).get("id"),
                "preview": (m.get("body") or m.get("text") or ("📎 média" if m.get("media_url") else ""))[:120],
                "last_at": _ts_to_iso(m.get("created_at")),
                "unread_count": 0, "total_count": 0,
                "ai_replies_count": 0,
            })
            slot["total_count"] += 1
            if m.get("ai_generated"):
                slot["ai_replies_count"] += 1
            if m.get("direction") == "inbound" and not m.get("read_by_us_at"):
                slot["unread_count"] += 1
        threads.extend(wa_by_peer.values())

        # ---- SMS (outbound only — no inbound webhook for SMS yet) ----
        sms_query: Dict[str, Any] = {"client_id": tid} if user.get("role") != "admin" else {}
        sms_msgs = await db.sms_messages.find(
            sms_query, {"_id": 0, "msisdn": 1, "message": 1, "created_at": 1, "status": 1, "provider": 1},
        ).sort("created_at", -1).to_list(500)
        sms_by_peer: Dict[str, Dict[str, Any]] = {}
        for m in sms_msgs:
            peer = m.get("msisdn") or "unknown"
            slot = sms_by_peer.setdefault(peer, {
                "channel": "sms", "peer_id": peer, "peer_name": peer,
                "preview": (m.get("message") or "")[:120],
                "last_at": _ts_to_iso(m.get("created_at")),
                "unread_count": 0, "total_count": 0,
                "provider": m.get("provider"),
            })
            slot["total_count"] += 1
        threads.extend(sms_by_peer.values())

        # ---- Messenger ----
        if feats.get("meta_messenger"):
            mg_msgs = await db.meta_messenger_messages.find(
                {"tenant_id": tid},
                {"_id": 0, "page_id": 1, "sender_id": 1, "recipient_id": 1, "text": 1,
                 "created_at": 1, "timestamp_ms": 1, "read_by_us_at": 1},
            ).sort("created_at", -1).to_list(500)
            # Resolve page IDs to names from the integration doc
            integ = await db.meta_integrations.find_one({"tenant_id": tid}, {"_id": 0, "pages": 1})
            page_names = {p["page_id"]: p.get("name") for p in (integ or {}).get("pages") or []}
            mg_by_peer: Dict[str, Dict[str, Any]] = {}
            for m in mg_msgs:
                page_id = m.get("page_id")
                # The non-page participant is the customer
                sender = m.get("sender_id")
                recipient = m.get("recipient_id")
                peer = sender if sender != page_id else recipient
                key = f"{page_id}:{peer}"
                slot = mg_by_peer.setdefault(key, {
                    "channel": "messenger", "peer_id": peer, "peer_name": peer or "Utilisateur Messenger",
                    "page_id": page_id, "page_name": page_names.get(page_id, ""),
                    "preview": (m.get("text") or "")[:120],
                    "last_at": _ts_to_iso(m.get("created_at") or m.get("timestamp_ms")),
                    "unread_count": 0, "total_count": 0,
                })
                slot["total_count"] += 1
                # Inbound = sender != page_id (the customer is talking to the page)
                if sender and sender != page_id and not m.get("read_by_us_at"):
                    slot["unread_count"] += 1
            threads.extend(mg_by_peer.values())

        # Sort by last_at desc, truncate
        threads.sort(key=lambda x: x.get("last_at") or "", reverse=True)
        threads = threads[:limit]

        return {
            "items": threads,
            "total": len(threads),
            "channels_enabled": {
                "whatsapp": True,
                "sms": True,
                "messenger": bool(feats.get("meta_messenger")),
            },
            "totals": {
                "unread": sum(t.get("unread_count", 0) for t in threads),
                "whatsapp": sum(1 for t in threads if t["channel"] == "whatsapp"),
                "sms": sum(1 for t in threads if t["channel"] == "sms"),
                "messenger": sum(1 for t in threads if t["channel"] == "messenger"),
            },
        }

    @api.get("/me/inbox/unified/{channel}/{thread_id}", tags=["Portail Client — Inbox"])
    async def thread_messages(
        channel: str, thread_id: str, page_id: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=200), user: dict = Depends(get_current_user),
    ):
        """Return ordered messages of a single thread."""
        tid = await _tenant_id(user)
        if channel == "whatsapp":
            # Iter38r-fix9i — Match peer by raw OR by digits-only form so it
            # works for both formats (+22890XXXX vs 22890XXXX).
            digits = "".join(ch for ch in thread_id if ch.isdigit())
            phone_alt = f"+{digits}" if digits else thread_id
            peer_clauses = [
                {"to_number": thread_id}, {"to": thread_id}, {"from": thread_id},
                {"to_number": phone_alt}, {"to": phone_alt}, {"from": phone_alt},
                {"phone_digits": digits},
            ]
            wa_query = {
                "$and": [
                    {"client_id": tid} if user.get("role") != "admin" else {},
                    {"$or": peer_clauses},
                ],
            }
            msgs = await db.whatsapp_messages.find(
                wa_query,
                {"_id": 0, "id": 1, "direction": 1, "text": 1, "body": 1,
                 "created_at": 1, "to_number": 1, "to": 1, "from": 1,
                 "wa_status": 1, "contact_name": 1, "name": 1, "media_url": 1,
                 "message_type": 1, "ai_generated": 1, "ai_source": 1,
                 "media_filename": 1, "media_content_type": 1},
            ).sort("created_at", 1).to_list(limit)
            return {"channel": "whatsapp", "thread_id": thread_id, "messages": [
                {
                    "id": m.get("id", ""),
                    "direction": m.get("direction") or "outbound",
                    "text": m.get("body") or m.get("text") or "",
                    "at": _ts_to_iso(m.get("created_at")),
                    "media_url": m.get("media_url"),
                    "media_filename": m.get("media_filename"),
                    "media_content_type": m.get("media_content_type"),
                    "message_type": m.get("message_type") or ("media" if m.get("media_url") else "text"),
                    "status": m.get("wa_status"),
                    "ai_generated": bool(m.get("ai_generated")),
                    "ai_source": m.get("ai_source"),
                } for m in msgs
            ]}
        if channel == "messenger":
            feats = await _tenant_features(tid)
            if not feats.get("meta_messenger"):
                raise HTTPException(status_code=403, detail="Module Messenger désactivé.")
            q: Dict[str, Any] = {"tenant_id": tid}
            if page_id:
                q["page_id"] = page_id
            q["$or"] = [{"sender_id": thread_id}, {"recipient_id": thread_id}]
            msgs = await db.meta_messenger_messages.find(
                q, {"_id": 0, "sender_id": 1, "recipient_id": 1, "page_id": 1,
                    "text": 1, "created_at": 1, "timestamp_ms": 1},
            ).sort("created_at", 1).to_list(limit)
            return {"channel": "messenger", "thread_id": thread_id, "messages": [
                {
                    "id": "",
                    "direction": "inbound" if m.get("sender_id") == thread_id else "outbound",
                    "text": m.get("text") or "",
                    "at": _ts_to_iso(m.get("created_at") or m.get("timestamp_ms")),
                    "page_id": m.get("page_id"),
                } for m in msgs
            ]}
        if channel == "sms":
            # SMS are outbound-only; list by msisdn (current tenant only)
            q: Dict[str, Any] = {"msisdn": thread_id}
            if user.get("role") != "admin":
                q["client_id"] = tid
            msgs = await db.sms_messages.find(
                q, {"_id": 0, "id": 1, "message": 1, "created_at": 1, "status": 1, "provider": 1},
            ).sort("created_at", 1).to_list(limit)
            return {"channel": "sms", "thread_id": thread_id, "messages": [
                {
                    "id": m.get("id", ""), "direction": "outbound",
                    "text": m.get("message") or "",
                    "at": _ts_to_iso(m.get("created_at")),
                    "status": m.get("status"), "provider": m.get("provider"),
                } for m in msgs
            ]}
        raise HTTPException(status_code=400, detail="Canal inconnu (whatsapp | sms | messenger)")

    # =========================================================================
    # Iter38j — Send a message from the unified inbox.
    # Routes to WhatsApp or Messenger depending on `channel`.
    # =========================================================================
    @api.post("/me/inbox/send", tags=["Portail Client — Inbox"])
    async def inbox_send(payload: InboxSendPayload, user: dict = Depends(get_current_user)):
        tid = await _tenant_id(user)
        feats = await _tenant_features(tid)
        now_iso = datetime.now(timezone.utc).isoformat()

        if payload.channel == "whatsapp":
            if wa_send_text is None:
                raise HTTPException(status_code=503, detail="WhatsApp sender non configuré.")
            r = await wa_send_text(payload.thread_id, payload.text)
            if not r.get("ok"):
                raise HTTPException(status_code=502, detail=r.get("error") or "Échec WhatsApp")
            # Persist outbound message into the existing collection so it
            # appears in the unified inbox via the regular aggregator.
            await db.whatsapp_messages.insert_one({
                "id": secrets.token_urlsafe(12),
                "client_id": tid,
                "direction": "outbound",
                "to_number": payload.thread_id,
                "text": payload.text,
                "wa_message_id": r.get("message_id"),
                "wa_status": "sent",
                "created_at": now_iso,
            })
            return {"ok": True, "message_id": r.get("message_id"), "channel": "whatsapp"}

        # ---- SMS ----
        if payload.channel == "sms":
            if sms_send_text is None:
                raise HTTPException(status_code=503, detail="SMS sender non configuré.")
            r = await sms_send_text(user, payload.thread_id, payload.text)
            if not r.get("ok"):
                raise HTTPException(status_code=502, detail=r.get("error") or "Échec SMS")
            return {"ok": True, "message_id": r.get("id"), "channel": "sms"}

        # ---- Messenger ----
        if payload.channel == "messenger":
            if not feats.get("meta_messenger"):
                raise HTTPException(status_code=403, detail="Module Messenger désactivé.")
            if not payload.page_id:
                raise HTTPException(status_code=400, detail="page_id requis pour Messenger.")
            integ = await db.meta_integrations.find_one({"tenant_id": tid}, {"_id": 0, "pages": 1})
            page = next((p for p in (integ or {}).get("pages") or [] if p.get("page_id") == payload.page_id), None)
            if not page or not page.get("page_access_token"):
                raise HTTPException(status_code=404, detail="Page Messenger introuvable ou token absent.")
            # Resolve graph version from settings
            s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "meta_graph_version": 1}) or {}
            gv = (s.get("meta_graph_version") or "v20.0").strip()
            url = f"https://graph.facebook.com/{gv}/{payload.page_id}/messages"
            body = {
                "recipient": {"id": payload.thread_id},
                "message": {"text": payload.text},
                "messaging_type": "RESPONSE",
            }
            async with httpx.AsyncClient(timeout=30.0) as c:
                resp = await c.post(url, params={"access_token": page["page_access_token"]}, json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"Meta error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            # Persist outbound for the unified inbox
            await db.meta_messenger_messages.insert_one({
                "id": secrets.token_urlsafe(12),
                "tenant_id": tid,
                "page_id": payload.page_id,
                "sender_id": payload.page_id,
                "recipient_id": payload.thread_id,
                "text": payload.text,
                "created_at": now_iso,
            })
            return {"ok": True, "message_id": data.get("message_id"), "channel": "messenger"}

        raise HTTPException(status_code=400, detail="Canal inconnu.")

    # =========================================================================
    # Iter38j — Mark a thread as read (resets unread_count for inbound msgs).
    # =========================================================================
    @api.post("/me/inbox/mark-read/{channel}/{thread_id}", tags=["Portail Client — Inbox"])
    async def inbox_mark_read(
        channel: str, thread_id: str, page_id: Optional[str] = Query(None),
        user: dict = Depends(get_current_user),
    ):
        tid = await _tenant_id(user)
        now_iso = datetime.now(timezone.utc).isoformat()
        if channel == "whatsapp":
            q: Dict[str, Any] = {
                "$or": [{"to_number": thread_id}, {"from": thread_id}],
                "direction": "inbound",
                "read_by_us_at": None,
            }
            if user.get("role") != "admin":
                q["client_id"] = tid
            res = await db.whatsapp_messages.update_many(q, {"$set": {"read_by_us_at": now_iso}})
            return {"ok": True, "channel": "whatsapp", "marked": res.modified_count}
        if channel == "messenger":
            feats = await _tenant_features(tid)
            if not feats.get("meta_messenger"):
                raise HTTPException(status_code=403, detail="Module Messenger désactivé.")
            q = {"tenant_id": tid, "sender_id": thread_id, "read_by_us_at": None}
            if page_id:
                q["page_id"] = page_id
            res = await db.meta_messenger_messages.update_many(q, {"$set": {"read_by_us_at": now_iso}})
            return {"ok": True, "channel": "messenger", "marked": res.modified_count}
        raise HTTPException(status_code=400, detail="Canal inconnu.")


    # ----------------------------------------------------------------
    # Iter38r-fix9o — Item 3: import an inbox conversant as a contact
    # ----------------------------------------------------------------
    @api.post("/me/inbox/import-contact", tags=["Portail Client — Inbox"])
    async def inbox_import_contact(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_current_user),
    ):
        """Create a contact from an inbox thread that has no matching contact
        yet. For WhatsApp channels, also try to pull the public profile (name,
        profile picture URL) via Meta Graph API as a best-effort sync."""
        import uuid
        channel = (payload.get("channel") or "").lower()
        identifier = (payload.get("identifier") or "").strip()
        display_name = (payload.get("display_name") or "").strip()
        if not channel or not identifier:
            raise HTTPException(status_code=400, detail="channel et identifier requis")
        tid = await _tenant_id(user)
        phone_digits = "".join(ch for ch in identifier if ch.isdigit())
        # Dedupe
        or_clauses: List[Dict[str, Any]] = []
        if phone_digits:
            or_clauses.append({"phone_digits": phone_digits})
        or_clauses.append({"whatsapp": identifier})
        or_clauses.append({"facebook_sender_id": identifier})
        existing = await db.contacts.find_one(
            {"tenant_id": tid, "$or": or_clauses},
            {"_id": 0, "id": 1},
        )
        if existing:
            return {"ok": True, "already_exists": True, "id": existing["id"]}
        now_iso = datetime.now(timezone.utc).isoformat()
        contact_id = str(uuid.uuid4())
        wa_profile: Dict[str, Any] = {}
        tags = ["Importé Inbox"]
        if channel == "whatsapp":
            tags.append("Connecté WhatsApp")
            try:
                if meta_get_meta_settings:
                    settings = await meta_get_meta_settings(tid)
                    token = settings.get("whatsapp_access_token") if settings else None
                    if token and phone_digits:
                        import httpx
                        async with httpx.AsyncClient(timeout=8.0) as client:
                            r = await client.get(
                                f"https://graph.facebook.com/v21.0/{phone_digits}",
                                params={"fields": "profile{name,profile_pic}"},
                                headers={"Authorization": f"Bearer {token}"},
                            )
                            if r.status_code == 200:
                                wa_profile = r.json().get("profile", {})
            except Exception:
                pass
        contact_doc = {
            "id": contact_id,
            "tenant_id": tid,
            "client_id": tid,
            "owner_id": user["id"],
            "full_name": display_name or wa_profile.get("name") or (f"+{phone_digits}" if phone_digits else identifier),
            "phone": f"+{phone_digits}" if phone_digits else None,
            "phone_digits": phone_digits or None,
            "whatsapp": f"+{phone_digits}" if phone_digits and channel == "whatsapp" else None,
            "facebook_sender_id": identifier if channel == "messenger" else None,
            "tags": tags,
            "source": f"inbox_{channel}",
            "wa_profile": wa_profile,
            "wa_profile_pic_url": wa_profile.get("profile_pic"),
            "created_at": now_iso,
            "updated_at": now_iso,
            "last_interaction_at": now_iso,
        }
        await db.contacts.insert_one(contact_doc.copy())
        contact_doc.pop("_id", None)
        return {"ok": True, "already_exists": False, "contact": contact_doc}
