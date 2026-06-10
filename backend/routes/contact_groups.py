"""Iter40 (2026-02) — Contact groups (tags) for bulk messaging.

Allows a tenant to group contacts and target SMS/WhatsApp bulk sends to
one or several groups at once (plus optional individual recipients).

Model :
  contact_groups : {
    id, client_id, name, description?, color?,
    contact_ids: [str],            # subset of directory_contacts.id
    created_at, updated_at,
    created_by,
  }

Endpoints (mounted under /api by the factory) :
  GET    /me/contact-groups                          — list groups for tenant
  POST   /me/contact-groups                          — create group
  PUT    /me/contact-groups/{gid}                    — rename / recolor
  DELETE /me/contact-groups/{gid}                    — delete group (contacts kept)
  POST   /me/contact-groups/{gid}/contacts           — add contacts
  DELETE /me/contact-groups/{gid}/contacts/{cid}     — remove a single contact
  POST   /me/contact-groups/resolve                  — expand groups+ids → contact list
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.contact_groups")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_scope(user: dict) -> str:
    """Return the canonical tenant_id (parent client) for this user."""
    return user.get("parent_client_id") or user.get("client_id") or user["id"]


async def _visible_contact_client_ids(db, user: dict) -> List[str]:
    """Iter41 hot-fix (2026-02) — Bug : « ajout de contacts au groupe ne fait
    rien ». Contacts may have been created under a *peer* client_id (same
    company) — the directory listing `/me/contacts` honors this via
    `_resolve_visible_client_ids`, but the add-to-group endpoint was filtering
    by the single canonical client_id, so peer-owned contacts were silently
    rejected (returned in `ignored`, never added).

    This helper duplicates the visibility logic locally to avoid importing
    from server.py (circular). It returns every client_id whose contacts the
    user can legitimately group.
    """
    import re as _re
    ids: set = set()
    for k in ("client_id", "parent_client_id", "id"):
        v = user.get(k)
        if v:
            ids.add(v)
    company = (user.get("company") or "").strip()
    if company:
        try:
            cursor = db.users.find(
                {"company": {"$regex": f"^{_re.escape(company)}$", "$options": "i"}},
                {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1},
            )
            async for u in cursor:
                for k in ("id", "client_id", "parent_client_id"):
                    v = u.get(k)
                    if v:
                        ids.add(v)
        except Exception:  # noqa: BLE001
            pass
    return list(ids) if ids else [user.get("id")]


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=400)
    color: Optional[str] = Field(default=None, max_length=24)
    contact_ids: List[str] = Field(default_factory=list)
    # Iter43 — partage tenant
    shared_with_tenant: bool = False
    editable_by_tenant: bool = False


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=400)
    color: Optional[str] = Field(default=None, max_length=24)
    shared_with_tenant: Optional[bool] = None
    editable_by_tenant: Optional[bool] = None


class AddContactsPayload(BaseModel):
    contact_ids: List[str] = Field(default_factory=list)


class ResolvePayload(BaseModel):
    group_ids: List[str] = Field(default_factory=list)
    contact_ids: List[str] = Field(default_factory=list)


def attach_contact_groups_routes(*, api, db, get_current_user):
    """Mount contact group endpoints."""
    from routes.tenant_sharing import (  # noqa: E402
        build_shared_filter, stamp_ownership, can_edit, can_delete,
        resolve_visible_owner_ids,
    )

    @api.get("/me/contact-groups", tags=["Portail Client — Groupes"])
    async def list_groups(user: dict = Depends(get_current_user)):
        cid = _client_scope(user)
        # Iter43 — partage tenant : OR entre {client_id: cid} (legacy) et
        # {owner_id in visible_ids + shared_with_tenant=True} (nouveau).
        shared_flt = await build_shared_filter(db, user)
        query = {"$or": [{"client_id": cid}, shared_flt]}
        items = await db.contact_groups.find(
            query, {"_id": 0},
        ).sort([("updated_at", -1), ("created_at", -1)]).to_list(500)
        for it in items:
            it["contact_count"] = len(it.get("contact_ids") or [])
            # Marque visuellement les groupes des collègues
            it["_is_shared_from_colleague"] = bool(
                it.get("owner_id") and it.get("owner_id") != user.get("id") and it.get("shared_with_tenant")
            )
        return items

    @api.post("/me/contact-groups", status_code=201, tags=["Portail Client — Groupes"])
    async def create_group(payload: GroupCreate = Body(...), user: dict = Depends(get_current_user)):
        cid = _client_scope(user)
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Nom requis")
        existing = await db.contact_groups.find_one(
            {"client_id": cid, "name": name},
            {"_id": 0, "id": 1},
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Un groupe « {name} » existe déjà.")
        # Validate provided contact_ids belong to a visible tenant (peer-sharing aware).
        contact_ids = list({c for c in (payload.contact_ids or []) if c})
        valid_count = 0
        if contact_ids:
            visible_ids = await _visible_contact_client_ids(db, user)
            valid_count = await db.directory_contacts.count_documents(
                {"client_id": {"$in": visible_ids}, "id": {"$in": contact_ids}},
            )
        doc = {
            "id": str(uuid.uuid4()),
            "client_id": cid,
            "name": name,
            "description": (payload.description or "").strip() or None,
            "color": (payload.color or "").strip() or "#6366f1",
            "contact_ids": contact_ids if valid_count == len(contact_ids) else [],
            "created_at": _now(),
            "updated_at": _now(),
            "created_by": user.get("id"),
        }
        # Iter43 — Stamp ownership pour partage tenant
        stamp_ownership(doc, user,
                        shared=bool(payload.shared_with_tenant),
                        editable=bool(payload.editable_by_tenant))
        await db.contact_groups.insert_one(doc.copy())
        return doc

    @api.put("/me/contact-groups/{gid}", tags=["Portail Client — Groupes"])
    async def update_group(gid: str, payload: GroupUpdate = Body(...), user: dict = Depends(get_current_user)):
        cid = _client_scope(user)
        existing_doc = await db.contact_groups.find_one({"id": gid}, {"_id": 0})
        if not existing_doc:
            raise HTTPException(status_code=404, detail="Groupe introuvable")
        # Iter43 — vérifie permissions (owner OR editable+shared OR admin/sup du tenant)
        vids = await resolve_visible_owner_ids(db, user)
        if not can_edit(existing_doc, user, visible_ids=vids):
            raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier ce groupe")
        upd: Dict[str, Any] = {"updated_at": _now()}
        if payload.name is not None:
            n = payload.name.strip()
            if not n:
                raise HTTPException(status_code=400, detail="Nom requis")
            # Uniqueness check (excluding self)
            clash = await db.contact_groups.find_one(
                {"client_id": cid, "name": n, "id": {"$ne": gid}},
                {"_id": 0, "id": 1},
            )
            if clash:
                raise HTTPException(status_code=409, detail=f"Un autre groupe « {n} » existe déjà.")
            upd["name"] = n
        if payload.description is not None:
            upd["description"] = (payload.description or "").strip() or None
        if payload.color is not None:
            upd["color"] = (payload.color or "").strip() or "#6366f1"
        # Iter43 — toggle shared / editable (seul l'auteur peut basculer)
        if payload.shared_with_tenant is not None and existing_doc.get("owner_id") == user.get("id"):
            upd["shared_with_tenant"] = bool(payload.shared_with_tenant)
        if payload.editable_by_tenant is not None and existing_doc.get("owner_id") == user.get("id"):
            upd["editable_by_tenant"] = bool(payload.editable_by_tenant)
        await db.contact_groups.update_one({"id": gid}, {"$set": upd})
        return await db.contact_groups.find_one({"id": gid}, {"_id": 0})

    @api.delete("/me/contact-groups/{gid}", tags=["Portail Client — Groupes"])
    async def delete_group(gid: str, user: dict = Depends(get_current_user)):
        existing_doc = await db.contact_groups.find_one({"id": gid}, {"_id": 0})
        if not existing_doc:
            raise HTTPException(status_code=404, detail="Groupe introuvable")
        # Iter43 — suppression réservée à l'auteur (+ admin/sup du tenant)
        if not can_delete(existing_doc, user):
            raise HTTPException(status_code=403, detail="Seul l'auteur (ou un admin du tenant) peut supprimer ce groupe")
        await db.contact_groups.delete_one({"id": gid})
        return {"ok": True}

    @api.post("/me/contact-groups/{gid}/contacts", tags=["Portail Client — Groupes"])
    async def add_contacts(gid: str, payload: AddContactsPayload = Body(...), user: dict = Depends(get_current_user)):
        cid = _client_scope(user)
        group = await db.contact_groups.find_one({"id": gid, "client_id": cid}, {"_id": 0})
        if not group:
            raise HTTPException(status_code=404, detail="Groupe introuvable")
        # Accept any contact_id visible to this user (multi-tenant peer sharing).
        wanted = [c for c in (payload.contact_ids or []) if c]
        visible_ids = await _visible_contact_client_ids(db, user)
        valid = await db.directory_contacts.find(
            {"client_id": {"$in": visible_ids}, "id": {"$in": wanted}},
            {"_id": 0, "id": 1},
        ).to_list(len(wanted) or 1)
        valid_ids = {v["id"] for v in valid}
        existing = set(group.get("contact_ids") or [])
        merged = sorted(existing | valid_ids)
        await db.contact_groups.update_one(
            {"id": gid},
            {"$set": {"contact_ids": merged, "updated_at": _now()}},
        )
        return {
            "ok": True,
            "added": sorted(valid_ids - existing),
            "ignored": sorted(set(wanted) - valid_ids),
            "total": len(merged),
        }

    @api.delete("/me/contact-groups/{gid}/contacts/{contact_id}", tags=["Portail Client — Groupes"])
    async def remove_contact(gid: str, contact_id: str, user: dict = Depends(get_current_user)):
        cid = _client_scope(user)
        res = await db.contact_groups.update_one(
            {"id": gid, "client_id": cid},
            {"$pull": {"contact_ids": contact_id}, "$set": {"updated_at": _now()}},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Groupe introuvable")
        group = await db.contact_groups.find_one({"id": gid}, {"_id": 0, "contact_ids": 1})
        return {"ok": True, "remaining": len(group.get("contact_ids") or [])}

    @api.post("/me/contact-groups/resolve", tags=["Portail Client — Groupes"])
    async def resolve_recipients(payload: ResolvePayload = Body(...), user: dict = Depends(get_current_user)):
        """Expand a (groups, contacts) selection into the unique target list.

        Returns the merged set of contact_ids (no duplicates) plus a flat
        list of contact records (id, name, phone, whatsapp) so the caller
        can render a preview AND submit the recipient ids.
        """
        cid = _client_scope(user)
        ids: set = set()
        # Group expansion
        if payload.group_ids:
            cursor = db.contact_groups.find(
                {"id": {"$in": payload.group_ids}, "client_id": cid},
                {"_id": 0, "id": 1, "contact_ids": 1, "name": 1},
            )
            async for g in cursor:
                for cid_inner in (g.get("contact_ids") or []):
                    ids.add(cid_inner)
        # Individual additions
        for c in (payload.contact_ids or []):
            if c:
                ids.add(c)
        # Resolve to contact rows (peer-sharing aware)
        contacts: List[Dict[str, Any]] = []
        if ids:
            visible_ids = await _visible_contact_client_ids(db, user)
            cursor = db.directory_contacts.find(
                {"client_id": {"$in": visible_ids}, "id": {"$in": list(ids)}},
                {"_id": 0, "id": 1, "name": 1, "phone": 1, "whatsapp": 1, "email": 1, "company": 1},
            )
            async for r in cursor:
                contacts.append(r)
        return {
            "total": len(contacts),
            "contact_ids": [c["id"] for c in contacts],
            "contacts": contacts,
        }


__all__ = ["attach_contact_groups_routes"]
