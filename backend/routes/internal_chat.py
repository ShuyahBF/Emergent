"""Iter36k — Internal real-time chat between users who follow ("are tracked
under") the same client.

Concepts
--------
A "client" here = a portal tenant (user with role=client/superviseur). Each
client has zero or more "tracked_users" whose account is bridged to a
real users row (tracked_users.user_account_id → users.id). Together they
form the **members** of that client's chat space.

When the toggle `features.internal_chat` is ON for a client, every member
gains access to:
  - a collective channel  ("#general" of that client)
  - 1-to-1 threads with any other member of the same client

A given user can be member of multiple clients (e.g. admin, superviseur).

Storage
-------
`internal_chat_messages` collection:
    {
      id, client_id, sender_id, sender_name,
      recipient_id  (None for the collective channel),
      text,
      created_at,
      read_by: [user_id, ...]     # who has marked it read
    }

Transport
---------
WebSocket: ``GET /api/ws/chat?token=<jwt>``
    On connect, the user subscribes to every client_id where chat is
    enabled and they are a member. Server broadcasts every new message
    of those clients to all online sockets concerned (sender included,
    so other tabs receive it too).

REST fallback (always available):
    GET  /api/me/chat/clients
    GET  /api/me/chat/{client_id}/members
    GET  /api/me/chat/{client_id}/threads
    GET  /api/me/chat/{client_id}/messages?with_user=<uid|general>&before=<iso>&limit=50
    POST /api/me/chat/{client_id}/messages   {text, recipient_id?}
    POST /api/me/chat/messages/{msg_id}/read
    GET  /api/me/chat/unread-count
    POST /api/me/chat/transcribe (multipart audio) — Iter36l Whisper STT

Public:
    GET /api/public/team-presence — Iter36l "online X/Y" social proof badge
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState  # lot 26 : état de la connexion temps réel
from pydantic import BaseModel, Field
from ia_client import cle_ia as _cle_ia  # noqa: E402 — lot 53 : clé du fournisseur IA
from routes import support_loois  # noqa: E402 — lot 57.12 : espace virtuel « Support Loois »
from routes import support_plateformes  # noqa: E402 — lot 90 : espaces « <plateforme> - Support »
from routes import avis_claude  # noqa: E402 — lot 91 : avis de Claude sur les demandes de fonctionnalités
from routes import synthese_support  # noqa: E402 — lot 92 : synthèse du support (admin + superviseur)

log = logging.getLogger("sawali.internal_chat")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =====================================================================
# In-memory connection manager (per-pod). For a single-pod deployment
# this is enough; for multi-pod we'd swap to Redis Pub/Sub. The chat
# is internal/small, so this is acceptable.
# =====================================================================
class ConnectionManager:
    def __init__(self):
        # user_id → list of websockets (multiple tabs/devices)
        self._conns: Dict[str, List[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.setdefault(user_id, []).append(ws)

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            arr = self._conns.get(user_id)
            if not arr:
                return
            try:
                arr.remove(ws)
            except ValueError:
                pass
            if not arr:
                self._conns.pop(user_id, None)

    def is_online(self, user_id: str) -> bool:
        return bool(self._conns.get(user_id))

    def online_user_ids(self) -> Set[str]:
        """Iter36l — Snapshot of currently connected user ids (for the public
        social-proof badge and admin debug)."""
        return set(uid for uid, arr in self._conns.items() if arr)

    async def send_to_user(self, user_id: str, payload: dict) -> None:
        """Push payload to every websocket of user_id. Errors are swallowed
        and dead sockets pruned."""
        arr = list(self._conns.get(user_id) or [])
        dead: List[WebSocket] = []
        for ws in arr:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)


# =====================================================================
# Pydantic payloads
# =====================================================================
class SendMessagePayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    recipient_id: Optional[str] = None  # None => collective channel
    # Iter36s — Optional reply-to anchor (WhatsApp-style quoted reply)
    reply_to_id: Optional[str] = None


# =====================================================================
# Router factory — receives DB + auth helpers from server.py
# =====================================================================
def make_router(*, db, get_current_user, decode_token):
    router = APIRouter(tags=["Chat interne"])
    manager = ConnectionManager()

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------
    async def _client_chat_enabled(client_id: str) -> bool:
        # Lot 57.12 — espace virtuel « Support Loois » : ouvert si la clé du support est configurée
        if client_id == support_loois.ESPACE_ID:
            return support_loois.actif()
        # Lot 90 — espace « sTer - Support »… : ouvert si le support est activé pour la plateforme
        if support_plateformes.est_espace(client_id):
            return await support_plateformes.espace_actif(db, client_id)
        u = await db.users.find_one({"id": client_id}, {"_id": 0, "features": 1})
        if not u:
            return False
        return bool((u.get("features") or {}).get("internal_chat"))

    async def _list_member_user_ids(client_id: str) -> Set[str]:
        """Members of a client's chat space:
        - the client himself
        - every tracked_user (status != archived) with a bridged user_account_id
        - every admin (so SAWALI staff can talk to any client's team)
        """
        # Lot 57.12 — « Support Loois » : membres = postes Loois + administrateurs (aucun client réel)
        if client_id == support_loois.ESPACE_ID:
            # postes Loois + équipe du support (admins + comptes de LOOIS_SUPPORT_ADMIN_EMAIL)
            return set(await support_loois.ids_postes(db)) | set(await support_loois.ids_admins(db))
        # Lot 90 — espaces des plateformes : utilisateurs de la plateforme + équipe du support
        if support_plateformes.est_espace(client_id):
            return set(await support_plateformes.ids_demandeurs(db, client_id)) | set(await support_loois.ids_admins(db))
        members: Set[str] = {client_id}
        cursor = db.tracked_users.find(
            {"client_id": client_id, "status": {"$ne": "archived"}, "user_account_id": {"$ne": None}},
            {"_id": 0, "user_account_id": 1},
        )
        async for tu in cursor:
            uid = tu.get("user_account_id")
            if uid:
                members.add(uid)
        # Admins can join every client's chat
        admins = db.users.find({"role": "admin"}, {"_id": 0, "id": 1})
        async for a in admins:
            members.add(a["id"])
        return members

    async def _user_visible_clients(user: dict) -> List[dict]:
        """Return clients where (1) chat is enabled and (2) the user is a member."""
        out: List[dict] = []
        # Admin → every client with internal_chat ON
        # Regular user → only the clients they belong to (as member or tracked_user)
        if user.get("role") == "admin":
            # Lot 91 — demande du propriétaire : la liste déroulante n'affiche QUE les applis
            # (Support Loois, « sTer - Support »…), plus les clients / tenants. S'il n'y a aucune appli active,
            # les espaces des clients restent proposés pour que le chat ne disparaisse pas.
            applis = await support_plateformes.espaces(db)
            if support_loois.actif():
                applis.insert(0, {"id": support_loois.ESPACE_ID, "full_name": support_loois.ESPACE_NOM,
                                  "company": support_loois.ESPACE_NOM})
            if applis:
                return applis
            cursor = db.users.find(
                {"role": {"$in": ["client", "superviseur"]}, "features.internal_chat": True},
                {"_id": 0, "id": 1, "full_name": 1, "company": 1},
            )
            async for c in cursor:
                out.append(c)
            # Lot 57.12 — espace virtuel « Support Loois » (administrateurs seulement)
            if support_loois.actif():
                # en TÊTE de liste : c'est l'espace ouvert par défaut dans le chat des administrateurs
                out.insert(0, {"id": support_loois.ESPACE_ID, "full_name": support_loois.ESPACE_NOM,
                               "company": support_loois.ESPACE_NOM})
            # Lot 90 — « sTer - Support », « adLyn - Support »… juste après le Support Loois
            rang = 1 if support_loois.actif() else 0
            out[rang:rang] = await support_plateformes.espaces(db)
            return out

        # Lot 57.13.1 — compte du support désigné (ex. superviseur) : espace « Support Loois » en tête
        if support_loois.actif() and support_loois.est_compte_support(user):
            out.append({"id": support_loois.ESPACE_ID, "full_name": support_loois.ESPACE_NOM,
                        "company": support_loois.ESPACE_NOM})
        # Lot 90 — même équipe pour les espaces des plateformes web
        if support_loois.est_compte_support(user):
            out.extend(await support_plateformes.espaces(db))
            # Lot 91 — équipe du support : seulement les applis dans la liste déroulante
            if out:
                return out

        # Find clients of which user is the client himself
        own = await db.users.find_one(
            {"id": user["id"], "features.internal_chat": True},
            {"_id": 0, "id": 1, "full_name": 1, "company": 1},
        )
        if own:
            out.append(own)

        # Find clients which track this user
        tracked_cursor = db.tracked_users.find(
            {"user_account_id": user["id"], "status": {"$ne": "archived"}},
            {"_id": 0, "client_id": 1},
        )
        client_ids: Set[str] = set()
        async for tu in tracked_cursor:
            cid = tu.get("client_id")
            if cid:
                client_ids.add(cid)
        if client_ids:
            cursor = db.users.find(
                {"id": {"$in": list(client_ids)}, "features.internal_chat": True},
                {"_id": 0, "id": 1, "full_name": 1, "company": 1},
            )
            async for c in cursor:
                if c["id"] not in {x["id"] for x in out}:
                    out.append(c)
        return out

    async def _ensure_member(user: dict, client_id: str) -> None:
        if not await _client_chat_enabled(client_id):
            raise HTTPException(status_code=403, detail="Chat interne désactivé pour ce client.")
        if user.get("role") == "admin":
            return
        members = await _list_member_user_ids(client_id)
        if user["id"] not in members:
            raise HTTPException(status_code=403, detail="Vous n'êtes pas membre de ce client.")

    async def _resolve_display_name(uid: str) -> str:
        # Lot 57.12 — poste Loois : « École — POSTE (utilisateur) »
        nom_poste = await support_loois.nom_du_poste(db, uid) or await support_plateformes.nom_du_demandeur(db, uid)
        if nom_poste:
            return nom_poste
        u = await db.users.find_one({"id": uid}, {"_id": 0, "full_name": 1, "email": 1})
        if u:
            return u.get("full_name") or u.get("email") or uid
        # Maybe a tracked_user not yet bridged
        tu = await db.tracked_users.find_one({"id": uid}, {"_id": 0, "name": 1, "email": 1})
        if tu:
            return tu.get("name") or tu.get("email") or uid
        return uid

    async def _resolve_reply_to(reply_to_id: Optional[str], client_id: str) -> Optional[dict]:
        """Iter36s — Snapshot the message being replied to. We store a
        condensed copy (id, text excerpt, sender_name, media_kind) so that
        editing or deleting the original later doesn't break the quote."""
        rid = (reply_to_id or "").strip()
        if not rid:
            return None
        m = await db.internal_chat_messages.find_one(
            {"id": rid, "client_id": client_id},
            {"_id": 0, "id": 1, "text": 1, "sender_name": 1, "sender_id": 1, "media_kind": 1},
        )
        if not m:
            return None
        excerpt = (m.get("text") or "").strip()
        if len(excerpt) > 140:
            excerpt = excerpt[:137] + "…"
        return {
            "id": m["id"],
            "sender_id": m.get("sender_id"),
            "sender_name": m.get("sender_name") or "",
            "text": excerpt,
            "media_kind": m.get("media_kind") or None,
        }

    # --------------------------------------------------------------
    # REST: list of clients where current user can chat
    # --------------------------------------------------------------
    @router.get("/me/chat/clients")
    async def me_chat_clients(user: dict = Depends(get_current_user)):
        return await _user_visible_clients(user)

    # --------------------------------------------------------------
    # REST: members of a given client
    # --------------------------------------------------------------
    @router.get("/me/chat/{client_id}/members")
    async def me_chat_members(client_id: str, user: dict = Depends(get_current_user)):
        await _ensure_member(user, client_id)
        member_ids = await _list_member_user_ids(client_id)
        # Hydrate name + online state
        cursor = db.users.find(
            {"id": {"$in": list(member_ids)}},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1},
        )
        out = []
        async for u in cursor:
            out.append({
                "id": u["id"],
                "name": u.get("full_name") or u.get("email") or u["id"],
                "email": u.get("email"),
                "role": u.get("role"),
                "online": manager.is_online(u["id"]),
                "is_self": u["id"] == user["id"],
            })
        # Lot 57.12 — postes Loois de l'espace « Support Loois »
        if client_id == support_loois.ESPACE_ID:
            out.extend(await support_loois.membres_postes(db, manager.is_online))
        elif support_plateformes.est_espace(client_id):   # lot 90
            out.extend(await support_plateformes.membres(db, client_id, manager.is_online))
        out.sort(key=lambda x: (not x["online"], x["name"].lower()))
        return out

    # --------------------------------------------------------------
    # REST: thread list (1-to-1s + general) with unread counters
    # --------------------------------------------------------------
    @router.get("/me/chat/{client_id}/threads")
    async def me_chat_threads(client_id: str, user: dict = Depends(get_current_user)):
        await _ensure_member(user, client_id)
        # Lot 57.12.1 — « Support Loois » : un fil par poste, visible par TOUS les administrateurs
        if client_id == support_loois.ESPACE_ID:
            return await support_loois.fils(db, user["id"])
        if support_plateformes.est_espace(client_id):   # lot 90 : un fil par utilisateur de la plateforme
            return await support_plateformes.fils(db, client_id, user["id"])
        # 1) Collective channel — unread count = messages in #general not read by me
        general_unread = await db.internal_chat_messages.count_documents({
            "client_id": client_id,
            "recipient_id": None,
            "sender_id": {"$ne": user["id"]},
            "read_by": {"$nin": [user["id"]]},
        })
        general_last = await db.internal_chat_messages.find_one(
            {"client_id": client_id, "recipient_id": None},
            {"_id": 0},
            sort=[("created_at", -1)],
        )
        threads = [{
            "kind": "general",
            "key": "general",
            "label": "#général",
            "unread": int(general_unread),
            "last_message": general_last,
        }]
        # 2) 1-to-1 threads — distinct counterparts I've ever chatted with
        # in this client scope.
        pipeline = [
            {"$match": {
                "client_id": client_id,
                "recipient_id": {"$ne": None},
                "$or": [
                    {"sender_id": user["id"]},
                    {"recipient_id": user["id"]},
                ],
            }},
            {"$project": {
                "_id": 0,
                "other": {"$cond": [{"$eq": ["$sender_id", user["id"]]}, "$recipient_id", "$sender_id"]},
                "created_at": 1,
                "sender_id": 1,
                "recipient_id": 1,
                "text": 1,
                "read_by": 1,
            }},
            {"$sort": {"created_at": -1}},
            {"$group": {
                "_id": "$other",
                "last_message": {"$first": "$$ROOT"},
            }},
        ]
        async for row in db.internal_chat_messages.aggregate(pipeline):
            other_id = row["_id"]
            unread = await db.internal_chat_messages.count_documents({
                "client_id": client_id,
                "sender_id": other_id,
                "recipient_id": user["id"],
                "read_by": {"$nin": [user["id"]]},
            })
            threads.append({
                "kind": "dm",
                "key": other_id,
                "label": await _resolve_display_name(other_id),
                "unread": int(unread),
                "last_message": row.get("last_message"),
            })
        return threads

    # --------------------------------------------------------------
    # REST: messages of a given thread
    # --------------------------------------------------------------
    @router.get("/me/chat/{client_id}/messages")
    async def me_chat_messages(
        client_id: str,
        with_user: str = Query(..., description="'general' or a user_id"),
        before: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=200),
        user: dict = Depends(get_current_user),
    ):
        await _ensure_member(user, client_id)
        q: Dict[str, Any] = {"client_id": client_id}
        if client_id == support_loois.ESPACE_ID and with_user != "general":
            # Lot 57.12.1 — tout le fil du poste, quel que soit l'administrateur qui a répondu
            q = support_loois.requete_fil(with_user)
        elif support_plateformes.est_espace(client_id) and with_user != "general":   # lot 90
            q = support_plateformes.requete_fil(client_id, with_user)
        elif with_user == "general":
            q["recipient_id"] = None
        else:
            q["recipient_id"] = {"$ne": None}
            q["$or"] = [
                {"sender_id": user["id"], "recipient_id": with_user},
                {"sender_id": with_user, "recipient_id": user["id"]},
            ]
        if before:
            q["created_at"] = {"$lt": before}
        cursor = db.internal_chat_messages.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
        rows = [r async for r in cursor]
        rows.reverse()  # chronological
        return rows

    # --------------------------------------------------------------
    # REST: send a message
    # --------------------------------------------------------------
    @router.post("/me/chat/{client_id}/messages")
    async def me_chat_send(
        client_id: str,
        payload: SendMessagePayload,
        user: dict = Depends(get_current_user),
    ):
        await _ensure_member(user, client_id)
        text = (payload.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Message vide")
        recipient_id = (payload.recipient_id or "").strip() or None
        if recipient_id:
            # Validate that recipient is a member of this client
            members = await _list_member_user_ids(client_id)
            if recipient_id not in members:
                raise HTTPException(status_code=400, detail="Destinataire non membre de ce client")
            if recipient_id == user["id"]:
                raise HTTPException(status_code=400, detail="Vous ne pouvez pas vous écrire à vous-même")
        # Iter36s — Resolve the reply-to anchor (snapshot, not foreign key)
        reply_to = await _resolve_reply_to(payload.reply_to_id, client_id)
        doc = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "sender_id": user["id"],
            "sender_name": user.get("full_name") or user.get("email") or user["id"],
            "recipient_id": recipient_id,
            "text": text[:2000],
            "created_at": _now_iso(),
            "read_by": [user["id"]],  # sender is implicitly "read"
        }
        if reply_to:
            doc["reply_to"] = reply_to
        await db.internal_chat_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        # Push via WS to every concerned member who is online
        # - DM: sender + recipient
        # - General: every member of the client
        if recipient_id:
            targets = {user["id"], recipient_id}
            # Lot 57.12.1 — « Support Loois » : la réponse d'un admin s'affiche aussi chez les autres admins
            if client_id == support_loois.ESPACE_ID or support_plateformes.est_espace(client_id):
                targets |= set(await support_loois.ids_admins(db))
        else:
            targets = await _list_member_user_ids(client_id)
        broadcast_payload = {"type": "message", "client_id": client_id, "message": doc}
        for uid in targets:
            try:
                await manager.send_to_user(uid, broadcast_payload)
            except Exception:
                pass
        # Lot 88 — agent → poste Loois sans session en cours : session et ticket à l'initiative du support
        await support_loois.signaler_message_agent(user, client_id, recipient_id)
        await support_plateformes.apres_message_agent(db, user, client_id, recipient_id)   # lot 90 : requête « en cours »
        return doc

    # --------------------------------------------------------------
    # Iter36n — Photo upload (mobile camera/gallery friendly).
    # MVP: images only (JPEG/PNG/WebP), max 10 MB. Stored on Emergent
    # Object Storage; the message doc keeps media_url pointing to the
    # signed retrieval endpoint below. Optional caption goes in `text`.
    # --------------------------------------------------------------
    @router.post("/me/chat/{client_id}/messages/photo")
    async def me_chat_send_photo(
        client_id: str,
        photo: UploadFile = File(...),
        recipient_id: Optional[str] = Form(None),
        caption: Optional[str] = Form(None),
        reply_to_id: Optional[str] = Form(None),
        user: dict = Depends(get_current_user),
    ):
        await _ensure_member(user, client_id)
        # Validate MIME (mobile cameras typically ship image/jpeg)
        allowed_mimes = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
        mime = (photo.content_type or "").lower()
        if mime not in allowed_mimes:
            # Be lenient on filename-based detection (some browsers omit MIME)
            ext = os.path.splitext(photo.filename or "")[1].lower()
            ext_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                       ".webp": "image/webp", ".heic": "image/heic", ".heif": "image/heif"}
            mime = ext_map.get(ext, "")
            if mime not in allowed_mimes:
                raise HTTPException(status_code=400, detail="Format non supporté. JPEG, PNG ou WebP uniquement.")
        # Read fully, cap at 10 MB
        data = await photo.read()
        if not data:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image trop volumineuse (>10 Mo).")
        return await _poster_image(user, client_id, data, mime, recipient_id=recipient_id,
                                   caption=caption, reply_to_id=reply_to_id)

    # --------------------------------------------------------------
    # Lot 87.3 — trombone : envoi d'un DOCUMENT (PDF, Word, Excel, PowerPoint, texte, CSV) ou d'une
    # VIDÉO (MP4/WebM) dans n'importe quelle discussion du chat. Mêmes types et limites que le Support Loois
    # (support_loois.type_fichier) ; une image envoyée par le trombone part comme une photo.
    # --------------------------------------------------------------
    @router.post("/me/chat/{client_id}/messages/fichier")
    async def me_chat_send_fichier(
        client_id: str,
        fichier: UploadFile = File(...),
        recipient_id: Optional[str] = Form(None),
        caption: Optional[str] = Form(None),
        reply_to_id: Optional[str] = Form(None),
        user: dict = Depends(get_current_user),
    ):
        await _ensure_member(user, client_id)
        nature = support_loois.type_fichier(fichier.content_type, fichier.filename)
        if not nature:
            raise HTTPException(status_code=400, detail="Type de fichier non accepté : images, vidéos MP4/WebM, "
                                                        "PDF, Word, Excel, PowerPoint, texte ou CSV.")
        mime, extension, genre, maximum = nature
        data = await fichier.read()
        if not data:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        if len(data) > maximum:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (plus de {maximum // (1024 * 1024)} Mo).")
        return await _poster_image(user, client_id, data, mime, recipient_id=recipient_id, caption=caption,
                                   reply_to_id=reply_to_id, media_kind=genre, extension=extension,
                                   file_name=support_loois.nom_fichier_propre(fichier.filename, extension))

    # --------------------------------------------------------------
    # Lot 87 — dépôt d'une image dans une discussion (fonction commune) :
    # utilisée par l'envoi de photo ci-dessus ET par l'image générée par l'IA
    # (routes/image_ia_chat.py) : stockage, message, diffusion temps réel.
    # --------------------------------------------------------------
    async def _poster_image(user: dict, client_id: str, data: bytes, mime: str, *,
                            recipient_id: Optional[str] = None, caption: Optional[str] = None,
                            reply_to_id: Optional[str] = None, extra: Optional[dict] = None,
                            media_kind: str = "image", extension: Optional[str] = None,
                            file_name: Optional[str] = None) -> dict:
        # Lot 87.3 — sert aussi aux documents et vidéos (trombone) : media_kind « document » / « video »,
        # extension du fichier stocké et nom affiché dans la bulle (file_name).
        # Validate recipient if DM
        recipient = (recipient_id or "").strip() or None
        if recipient:
            members = await _list_member_user_ids(client_id)
            if recipient not in members:
                raise HTTPException(status_code=400, detail="Destinataire non membre de ce client")
            if recipient == user["id"]:
                raise HTTPException(status_code=400, detail="Vous ne pouvez pas vous écrire à vous-même")
        # Upload to Emergent Object Storage
        msg_id = str(uuid.uuid4())
        ext_for_path = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                        "image/heic": ".heic", "image/heif": ".heif"}.get(mime, extension or ".bin")
        storage_path = None
        try:
            from storage import aupload_bytes, astorage_available  # lot 26 : non bloquant
            if not await astorage_available():
                raise HTTPException(status_code=503, detail="Stockage indisponible — réessayez plus tard.")
            storage_path = await aupload_bytes(
                f"chat/{client_id}/{msg_id}{ext_for_path}",
                data,
                mime,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("chat photo upload failed")
            raise HTTPException(status_code=502, detail=f"Upload échoué : {str(exc)[:160]}")
        # Build the message doc
        caption_clean = ((caption or "").strip())[:500] or None
        reply_to = await _resolve_reply_to(reply_to_id, client_id)
        doc = {
            "id": msg_id,
            "client_id": client_id,
            "sender_id": user["id"],
            "sender_name": user.get("full_name") or user.get("email") or user["id"],
            "recipient_id": recipient,
            "text": caption_clean or "",
            "media_url": f"/api/me/chat/media/{msg_id}",
            "media_mime": mime,
            "media_size": len(data),
            "media_kind": media_kind,
            "storage_path": storage_path,
            "created_at": _now_iso(),
            "read_by": [user["id"]],
        }
        if file_name:
            doc["file_name"] = file_name   # lot 87.3 : nom du document affiché dans la bulle
        if extra:
            doc.update(extra)   # lot 87 : marque « image IA » (prompt, auteur)
        if reply_to:
            doc["reply_to"] = reply_to
        await db.internal_chat_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        # Broadcast (same logic as text send)
        if recipient:
            targets = {user["id"], recipient}
            # Lot 57.13 — « Support Loois » : la photo d'un admin s'affiche aussi chez les autres admins
            if client_id == support_loois.ESPACE_ID or support_plateformes.est_espace(client_id):
                targets |= set(await support_loois.ids_admins(db))
        else:
            targets = await _list_member_user_ids(client_id)
        broadcast_payload = {"type": "message", "client_id": client_id, "message": doc}
        for uid in targets:
            try:
                await manager.send_to_user(uid, broadcast_payload)
            except Exception:
                pass
        # Lot 88 — agent → poste Loois sans session en cours : session et ticket à l'initiative du support
        await support_loois.signaler_message_agent(user, client_id, recipient)
        await support_plateformes.apres_message_agent(db, user, client_id, recipient)   # lot 90
        return doc

    # --------------------------------------------------------------
    # Iter36n — Authenticated media fetch endpoint.
    # The frontend renders <img src="/api/me/chat/media/{msg_id}"> with the
    # axios `Authorization` header; we re-validate membership on every call
    # so a leaked URL can't be used by an outsider.
    # --------------------------------------------------------------
    @router.get("/me/chat/media/{msg_id}")
    async def me_chat_get_media(msg_id: str, user: dict = Depends(get_current_user)):
        m = await db.internal_chat_messages.find_one({"id": msg_id}, {"_id": 0})
        if not m:
            raise HTTPException(status_code=404, detail="Message introuvable")
        await _ensure_member(user, m["client_id"])
        # For DMs, ensure the requester is one of the two parties
        if m.get("recipient_id") and user["id"] not in (m["sender_id"], m["recipient_id"]):
            # Admins still allowed (they see everything in a client's space) ; lot 57.13.1 : toute l'équipe
            # du support voit les images de l'espace « Support Loois » (membre vérifié juste au-dessus)
            if (user.get("role") != "admin" and m["client_id"] != support_loois.ESPACE_ID
                    and not support_plateformes.est_espace(m["client_id"])):
                raise HTTPException(status_code=403, detail="Accès refusé")
        if not m.get("storage_path"):
            raise HTTPException(status_code=404, detail="Média introuvable")
        try:
            from storage import afetch_bytes  # lot 26 : dans un thread
            data, ct = await afetch_bytes(m["storage_path"])
        except Exception:
            log.exception("chat media fetch failed")
            raise HTTPException(status_code=502, detail="Échec récupération média")
        return Response(
            content=data,
            media_type=ct or m.get("media_mime") or "application/octet-stream",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    # --------------------------------------------------------------
    # REST: mark a message read
    # --------------------------------------------------------------
    @router.post("/me/chat/messages/{msg_id}/read")
    async def me_chat_mark_read(msg_id: str, user: dict = Depends(get_current_user)):
        m = await db.internal_chat_messages.find_one({"id": msg_id}, {"_id": 0})
        if not m:
            raise HTTPException(status_code=404, detail="Message introuvable")
        await _ensure_member(user, m["client_id"])
        if user["id"] not in (m.get("read_by") or []):
            await db.internal_chat_messages.update_one(
                {"id": msg_id},
                {"$addToSet": {"read_by": user["id"]}},
            )
            # Push read-receipt event to the original sender
            if m.get("sender_id") and m["sender_id"] != user["id"]:
                try:
                    await manager.send_to_user(m["sender_id"], {
                        "type": "read",
                        "client_id": m["client_id"],
                        "msg_id": msg_id,
                        "by": user["id"],
                    })
                except Exception:
                    pass
        return {"ok": True}

    @router.post("/me/chat/{client_id}/threads/{thread_key}/mark-all-read")
    async def me_chat_mark_thread_read(
        client_id: str, thread_key: str, user: dict = Depends(get_current_user)
    ):
        """Marque en masse tous les messages d'un thread comme lus pour l'utilisateur courant."""
        await _ensure_member(user, client_id)
        q: Dict[str, Any] = {"client_id": client_id, "read_by": {"$nin": [user["id"]]}}
        if client_id == support_loois.ESPACE_ID and thread_key != "general":
            # Lot 57.12.1 — marque lu tout le fil du poste pour cet administrateur
            q = {**support_loois.requete_fil(thread_key), "read_by": {"$nin": [user["id"]]}}
        elif support_plateformes.est_espace(client_id) and thread_key != "general":   # lot 90
            q = {**support_plateformes.requete_fil(client_id, thread_key), "read_by": {"$nin": [user["id"]]}}
        elif thread_key == "general":
            q["recipient_id"] = None
        else:
            q["recipient_id"] = {"$ne": None}
            q["$or"] = [
                {"sender_id": user["id"], "recipient_id": thread_key},
                {"sender_id": thread_key, "recipient_id": user["id"]},
            ]
        res = await db.internal_chat_messages.update_many(q, {"$addToSet": {"read_by": user["id"]}})
        return {"ok": True, "modified": res.modified_count}

    # --------------------------------------------------------------
    # REST: global unread count
    # --------------------------------------------------------------
    @router.get("/me/chat/unread-count")
    async def me_chat_unread_count(user: dict = Depends(get_current_user)):
        clients = await _user_visible_clients(user)
        total = 0
        per_client: Dict[str, int] = {}
        for c in clients:
            # Lot 57.12.1 — « Support Loois » : messages des postes non lus par cet administrateur
            if c["id"] == support_loois.ESPACE_ID:
                n = await db.internal_chat_messages.count_documents(support_loois.requete_non_lus(user["id"]))
                per_client[c["id"]] = int(n)
                total += int(n)
                continue
            if support_plateformes.est_espace(c["id"]):   # lot 90 : messages des utilisateurs non lus par cet agent
                n = await db.internal_chat_messages.count_documents(support_plateformes.requete_non_lus(c["id"], user["id"]))
                per_client[c["id"]] = int(n)
                total += int(n)
                continue
            # General messages not from me + DM messages addressed to me, not yet read
            q = {
                "client_id": c["id"],
                "read_by": {"$nin": [user["id"]]},
                "$or": [
                    {"recipient_id": None, "sender_id": {"$ne": user["id"]}},
                    {"recipient_id": user["id"]},
                ],
            }
            n = await db.internal_chat_messages.count_documents(q)
            per_client[c["id"]] = int(n)
            total += int(n)
        return {"total": total, "per_client": per_client}

    # --------------------------------------------------------------
    # WebSocket endpoint
    # --------------------------------------------------------------
    @router.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket, token: Optional[str] = Query(None)):
        await websocket.accept()
        # Lot 57.14 — jeton reçu dans le PREMIER message (jamais dans l'adresse, qui est journalisée) ;
        # « ?token= » reste accepté pour les onglets encore ouverts avec l'ancienne interface.
        import ws_auth
        token = await ws_auth.lire_jeton(websocket, token)
        if not token:
            await websocket.send_json({"type": "error", "detail": "token manquant"})
            await websocket.close(code=4401)
            return
        try:
            payload = decode_token(token)
            uid = payload.get("sub")
            if not uid:
                raise Exception("invalid token")
            user = await db.users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
            if not user or user.get("account_status") != "active":
                raise Exception("inactive user")
            # Lot 50 — maintenance de la plateforme : discussion interne fermée (sauf Admin)
            import maintenance_plateforme
            if not maintenance_plateforme.jamais_bloque(user, payload) and await maintenance_plateforme.en_maintenance():
                raise Exception("maintenance")
        except Exception:
            await websocket.send_json({"type": "error", "detail": "auth failed"})
            await websocket.close(code=4401)
            return

        await manager.connect(uid, websocket)
        try:
            await websocket.send_json({"type": "hello", "user_id": uid, "ts": _now_iso()})
            # Listen for client-side events (ping, typing, etc.)
            bad_frames = 0
            while True:
                # Lot 26 — la connexion n'est plus ouverte : on sort. Avant, une
                # erreur répétée faisait tourner cette boucle sans jamais rendre
                # la main (« continue » immédiat), ce qui figeait TOUT le serveur.
                if websocket.application_state != WebSocketState.CONNECTED or \
                        websocket.client_state != WebSocketState.CONNECTED:
                    break
                try:
                    data = await websocket.receive_json()
                    bad_frames = 0
                except (WebSocketDisconnect, RuntimeError):
                    break
                except Exception:
                    # Message illisible : ignoré, mais on abandonne après 20 d'affilée
                    bad_frames += 1
                    if bad_frames > 20:
                        break
                    await asyncio.sleep(0)
                    continue
                msg_type = (data or {}).get("type")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "ts": _now_iso()})
                elif msg_type == "typing":
                    # Relay typing indicator to the target user (DM) or client members (general)
                    client_id = (data.get("client_id") or "").strip()
                    target = (data.get("recipient_id") or "").strip() or None
                    if not client_id:
                        continue
                    if not await _client_chat_enabled(client_id):
                        continue
                    if target:
                        await manager.send_to_user(target, {
                            "type": "typing",
                            "client_id": client_id,
                            "from": uid,
                        })
                    else:
                        members = await _list_member_user_ids(client_id)
                        for mid in members:
                            if mid != uid:
                                await manager.send_to_user(mid, {
                                    "type": "typing",
                                    "client_id": client_id,
                                    "from": uid,
                                    "channel": "general",
                                })
                # else: unknown, ignore
        finally:
            await manager.disconnect(uid, websocket)

    # --------------------------------------------------------------
    # Iter36s — Full-text search across the user's accessible chats.
    # Returns the latest 30 matches with thread routing info so the
    # client can jump straight to the conversation + scroll-to message.
    # --------------------------------------------------------------
    @router.get("/me/chat/search")
    async def me_chat_search(
        q: str = Query(..., min_length=1, max_length=120),
        client_id: Optional[str] = Query(None),
        limit: int = Query(30, ge=1, le=100),
        user: dict = Depends(get_current_user),
    ):
        term = q.strip()
        if not term:
            return {"results": []}
        # Resolve which clients this user can see chats in.
        visible = await _user_visible_clients(user)
        visible_ids = {c["id"] for c in visible}
        if client_id:
            if client_id not in visible_ids:
                raise HTTPException(status_code=403, detail="Client non autorisé")
            scope_ids = [client_id]
        else:
            scope_ids = list(visible_ids)
        if not scope_ids:
            return {"results": []}
        # Build the query: case-insensitive substring match on text +
        # sender_name. Scope to messages the user is part of:
        # - general (recipient_id=null) of any visible client
        # - DM where user is sender OR recipient
        import re
        rx = {"$regex": re.escape(term), "$options": "i"}
        query = {
            "client_id": {"$in": scope_ids},
            "$and": [
                {"$or": [{"text": rx}, {"sender_name": rx}]},
                {"$or": [
                    {"recipient_id": None},
                    {"sender_id": user["id"]},
                    {"recipient_id": user["id"]},
                ]},
            ],
        }
        cursor = (
            db.internal_chat_messages.find(query, {"_id": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        # Build thread routing per message so the UI knows where to jump
        results = []
        async for m in cursor:
            if m.get("recipient_id") is None:
                thread_key = "general"
            else:
                # The "other party" relative to the requesting user
                thread_key = (
                    m["sender_id"] if m["recipient_id"] == user["id"] else m["recipient_id"]
                )
            results.append({
                "id": m["id"],
                "client_id": m["client_id"],
                "thread_key": thread_key,
                "sender_id": m.get("sender_id"),
                "sender_name": m.get("sender_name"),
                "text": m.get("text") or "",
                "media_kind": m.get("media_kind"),
                "created_at": m.get("created_at"),
            })
        return {"results": results, "term": term}

    # --------------------------------------------------------------
    # Iter36l — Whisper STT transcription endpoint for the chat composer.
    # Multipart upload (audio/webm,wav,m4a,mp3 — 25 MB max) → French text.
    # Used by the chat panel's microphone button: user records, the audio
    # is transcribed, the text is shown for review, then sent as a regular
    # text message via /me/chat/{cid}/messages. Audio is NOT persisted
    # (conforms to "chat texte seul" spec).
    # --------------------------------------------------------------
    @router.post("/me/chat/transcribe")
    async def me_chat_transcribe(
        audio: UploadFile = File(...),
        language: str = "fr",
        user: dict = Depends(get_current_user),
    ):
        # Validate filename extension (whisper-1 accepts: mp3,mp4,mpeg,mpga,m4a,wav,webm)
        allowed = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}
        ext = os.path.splitext(audio.filename or "")[1].lower() or ".webm"
        if ext not in allowed:
            # Browser MediaRecorder ships .webm by default — be lenient
            ext = ".webm"
        # Read fully (we cap at 25 MB)
        data = await audio.read()
        if not data:
            raise HTTPException(status_code=400, detail="Fichier audio vide.")
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Fichier audio trop volumineux (>25 Mo).")
        # Persist temporarily — Whisper wants a real file handle
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(data)
                tmp_path = f.name
            from ia_client import OpenAISpeechToText
            stt = OpenAISpeechToText(api_key=_cle_ia("openai"))  # lot 53 : Whisper, OPENAI_API_KEY
            with open(tmp_path, "rb") as fh:
                resp = await stt.transcribe(
                    file=fh,
                    model="whisper-1",
                    response_format="json",
                    language=(language or "fr")[:5],
                )
            text = (getattr(resp, "text", None) or "").strip()
            return {"ok": True, "text": text}
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Whisper transcription failed")
            raise HTTPException(status_code=502, detail=f"Transcription échouée : {str(exc)[:160]}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    # --------------------------------------------------------------
    # Iter36l — Public "team online X/Y" social-proof badge.
    # Counts SAWALI staff (admins) currently connected to the WS chat.
    # No identifying information returned (privacy-safe).
    # --------------------------------------------------------------
    @router.get("/public/team-presence")
    async def public_team_presence():
        # Total = active SAWALI staff (admins + superviseur + moderateur).
        # Online = subset currently WS-connected.
        team_ids: List[str] = []
        cursor = db.users.find(
            {
                # Lot 25 — Les deux orthographes du rôle modérateur sont incluses.
                "role": {"$in": ["admin", "superviseur", "moderateur", "moderator"]},
                "account_status": "active",
            },
            {"_id": 0, "id": 1},
        )
        async for u in cursor:
            if u.get("id"):
                team_ids.append(u["id"])
        online_ids = manager.online_user_ids()
        online = sum(1 for tid in team_ids if tid in online_ids)
        total = len(team_ids)
        return {
            "online": online,
            "total": total,
            "ts": _now_iso(),
        }

    # Lot 57.12 — WebSocket des postes Loois (bouton « Ecrire Support »), même gestionnaire de connexions
    support_loois.installer(router=router, db=db, manager=manager, now_iso=_now_iso,
                            get_current_user=get_current_user)
    # Lot 90 — support SAWALI des plateformes web (requêtes signées des plateformes + routes de l'équipe)
    support_plateformes.installer(router=router, db=db, manager=manager, now_iso=_now_iso,
                                  get_current_user=get_current_user)
    # Lot 91 — avis de Claude (Liluvine transmet les demandes de fonctionnalités, le propriétaire décide)
    avis_claude.installer(router=router, db=db, manager=manager, get_current_user=get_current_user)
    # Lot 92 — synthèse du support : non répondues, totaux, demandes transmises à Claude (admin + superviseur)
    synthese_support.installer(router=router, db=db, get_current_user=get_current_user)

    # Lot 87 — fonctions exposées au module « image IA du chat » (routes/image_ia_chat.py)
    router.poster_image = _poster_image
    router.verifier_membre = _ensure_member
    router.espaces_visibles = _user_visible_clients
    router.membres = _list_member_user_ids
    router.nom_affiche = _resolve_display_name
    return router
