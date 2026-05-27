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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger("sawali.inbox")


def setup_unified_inbox_routes(*, db, api, get_current_user, _normalize_features):
    """Mount the unified inbox endpoints on the provided `api` router."""

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
            wa_query, {"_id": 0, "to_number": 1, "from": 1, "direction": 1, "text": 1,
                       "created_at": 1, "read_by_us_at": 1, "contact_name": 1, "name": 1},
        ).sort("created_at", -1).to_list(500)
        wa_by_peer: Dict[str, Dict[str, Any]] = {}
        for m in wa_msgs:
            peer = (m.get("from") if m.get("direction") == "inbound" else m.get("to_number")) or "unknown"
            slot = wa_by_peer.setdefault(peer, {
                "channel": "whatsapp", "peer_id": peer, "peer_name": m.get("contact_name") or m.get("name") or peer,
                "preview": (m.get("text") or "")[:120], "last_at": _ts_to_iso(m.get("created_at")),
                "unread_count": 0, "total_count": 0,
            })
            slot["total_count"] += 1
            if m.get("direction") == "inbound" and not m.get("read_by_us_at"):
                slot["unread_count"] += 1
        threads.extend(wa_by_peer.values())

        # ---- Messenger ----
        if feats.get("meta_messenger"):
            mg_msgs = await db.meta_messenger_messages.find(
                {"tenant_id": tid},
                {"_id": 0, "page_id": 1, "sender_id": 1, "recipient_id": 1, "text": 1,
                 "created_at": 1, "timestamp_ms": 1},
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
                # Inbound = sender != page_id
                if sender and sender != page_id:
                    slot["unread_count"] += 1  # naive: until UI explicit-read
            threads.extend(mg_by_peer.values())

        # Sort by last_at desc, truncate
        threads.sort(key=lambda x: x.get("last_at") or "", reverse=True)
        threads = threads[:limit]

        return {
            "items": threads,
            "total": len(threads),
            "channels_enabled": {
                "whatsapp": True,
                "messenger": bool(feats.get("meta_messenger")),
            },
            "totals": {
                "unread": sum(t.get("unread_count", 0) for t in threads),
                "whatsapp": sum(1 for t in threads if t["channel"] == "whatsapp"),
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
            wa_query = {
                "$and": [
                    {"client_id": tid} if user.get("role") != "admin" else {},
                    {"$or": [{"to_number": thread_id}, {"from": thread_id}]},
                ],
            }
            msgs = await db.whatsapp_messages.find(
                wa_query,
                {"_id": 0, "direction": 1, "text": 1, "created_at": 1, "to_number": 1,
                 "from": 1, "wa_status": 1, "contact_name": 1, "name": 1, "media_url": 1},
            ).sort("created_at", 1).to_list(limit)
            return {"channel": "whatsapp", "thread_id": thread_id, "messages": [
                {
                    "id": m.get("id", ""),
                    "direction": m.get("direction") or "outbound",
                    "text": m.get("text") or "",
                    "at": _ts_to_iso(m.get("created_at")),
                    "media_url": m.get("media_url"),
                    "status": m.get("wa_status"),
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
        raise HTTPException(status_code=400, detail="Canal inconnu (whatsapp | messenger)")
