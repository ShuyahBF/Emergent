# server_parts/p08_notes_portail_journaux.py — Rapports & suivis, note de service, portail (interventions, documents, contacts), notes étoilées, journaux d'accès, traces API.
# Morceau de l'ancien server.py (lignes 10624 à 11964), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# USER NOTES — Rapports & Suivis
# ====================================================================
def _user_notes_collection(kind: str):
    # Iter35g — extended with "notes" and "tasks" — personal notes & tasks
    # for portal users (same UI/model as reports/suivis, voice + transcription
    # inherited for free). Separate from the admin per-client `client_notes`
    # / `client_tasks` collections which stay unchanged.
    mapping = {
        "reports": db.user_reports,
        "suivis": db.user_suivis,
        "notes": db.user_notes_personal,
        "tasks": db.user_tasks_personal,
    }
    if kind not in mapping:
        raise HTTPException(status_code=404, detail="Type inconnu")
    return mapping[kind]


@api.get("/me/notes/{kind}", tags=["Portail Client"])
async def me_list_notes(
    kind: str,
    author: Optional[str] = None,
    q: Optional[str] = None,
    scope: Optional[str] = None,  # mine | shared | all (default: all I can see)
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    # Iter38r-fix9f — Visibility model:
    #  - owner_id == user.id           → always visible (full edit)
    #  - target_user_ids contains me   → visible read-only
    #  - is_private == False AND same tenant → visible read-only ("Public")
    # admin/superviseur still see EVERYTHING.
    # Iter43 — Also include `shared_with_tenant=True` docs from same société/rattachement
    my_tenant = user.get("parent_client_id") or user.get("client_id") or user["id"]
    # Build cross-company visibility via tenant_sharing helper
    try:
        from routes.tenant_sharing import resolve_visible_owner_ids  # noqa: E402
        visible_owner_ids = await resolve_visible_owner_ids(db, user)
    except Exception:
        visible_owner_ids = [user["id"]]
    cross_clause = {
        "owner_id": {"$in": [oid for oid in visible_owner_ids if oid != user["id"]]},
        "shared_with_tenant": True,
    } if len(visible_owner_ids) > 1 else None
    if _is_super_admin(user):
        base: Dict[str, Any] = {}
    elif user.get("role") in ("admin", "superviseur"):
        # Iter43-fix24az-l — Client-admin scoped to their tenant (was: {})
        scope = await _resolve_visible_client_ids(user)
        base = {
            "$or": [
                {"owner_id": {"$in": scope}},
                {"target_user_ids": {"$in": scope}},
                {"client_id": {"$in": scope}},
            ]
        }
    elif _is_elevated_creator(user):
        clauses = [
            {"is_private": {"$ne": True}},
            {"owner_id": user["id"]},
            {"target_user_ids": user["id"]},
        ]
        if cross_clause:
            clauses.append(cross_clause)
        base = {"$or": clauses}
    else:
        # Tracked users (Consultation/Comptable/etc.) — see own + targeted + public-in-tenant
        clauses = [
            {"owner_id": user["id"]},
            {"target_user_ids": user["id"]},
            {"is_private": {"$ne": True}, "tenant_id": my_tenant},
        ]
        if cross_clause:
            clauses.append(cross_clause)
        base = {"$or": clauses}
    query: Dict[str, Any] = dict(base)
    # Optional scope filter (mine|shared|all) — applies on top of the visibility ACL
    if scope == "mine":
        query = {"owner_id": user["id"]}
    elif scope == "shared":
        # Anything I can see EXCEPT the items I authored
        if "$or" in query:
            query = {"$and": [query, {"owner_id": {"$ne": user["id"]}}]}
        else:
            query["owner_id"] = {"$ne": user["id"]}
    if author:
        query["owner_email"] = {"$regex": re.escape(author), "$options": "i"}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        # Combine with a possible $or already present in `base` by wrapping in $and
        text_or = [
            {"title": rx},
            {"content_html": rx},
            {"numero": rx},
            {"tags": rx},
        ]
        if "$or" in query:
            existing_or = query.pop("$or")
            query["$and"] = [{"$or": existing_or}, {"$or": text_or}]
        else:
            query["$or"] = text_or
    items = await coll.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    # Iter34u — Apply content-level restrictions (anon_rapports / anon_suivis)
    # when active. Privileged roles already bypass via the helper.
    restrictions = await _resolve_content_restrictions(user)
    restricted = (kind == "rapport" and restrictions.get("anon_rapports")) or \
                 (kind == "suivi" and restrictions.get("anon_suivis"))
    if restricted:
        items = [it for it in items if it.get("owner_id") == user["id"]]
    return await _attach_my_rating(items, kind, user["id"])


@api.get("/me/notes/{kind}/authors", tags=["Portail Client"])
async def me_list_note_authors(kind: str, user: dict = Depends(get_current_user)):
    """Distinct authors for the kind — used to populate the filter dropdown."""
    coll = _user_notes_collection(kind)
    base = {} if _is_elevated_creator(user) else {"owner_id": user["id"]}
    pipeline = [
        {"$match": base},
        {"$group": {"_id": "$owner_email", "name": {"$last": "$owner_name"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    items = await coll.aggregate(pipeline).to_list(500)
    return [{"email": a["_id"], "name": a.get("name"), "count": a["count"]} for a in items if a.get("_id")]


@api.post("/me/notes/{kind}", tags=["Portail Client"])
async def me_create_note(
    request: Request,
    kind: str,
    payload: UserNoteCreate,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    # Iter38r-fix9f — Tasks & Notes ouverts à tous les utilisateurs ; Reports
    # et Suivis restent réservés aux profils élevés (documents formels).
    if kind in ("reports", "suivis") and not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Rôle insuffisant pour créer un rapport/suivi")
    await _check_descent_window(action_label="enregistrement", user=user)

    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre requis")

    # Suivis must specify the date and the client concerned
    if kind == "suivis":
        if not (payload.event_date and payload.event_date.strip()):
            raise HTTPException(status_code=400, detail="Date de l'événement requise pour un suivi")
        if not (payload.client_id and payload.client_id.strip()):
            raise HTTPException(status_code=400, detail="Client concerné requis pour un suivi")

    images = _validate_images(payload.images, max_count=10)
    # Iter35g — prefix per kind
    prefix_map = {"reports": "RPT", "suivis": "SUI", "notes": "NTE", "tasks": "TSK"}
    prefix = prefix_map.get(kind, "DOC")
    numero = await _next_simple_number(prefix)

    doc = {
        "id": _uuid(),
        "kind": kind,
        "numero": numero,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "owner_name": user.get("full_name"),
        "owner_role": user.get("tracked_role") or user.get("role"),
        # Iter43 — Snapshot société/rattachement pour partage cross-utilisateur
        "owner_company": (user.get("company") or "").strip() or None,
        "owner_parent_client_id": user.get("parent_client_id"),
        "shared_with_tenant": bool(payload.shared_with_tenant),
        "editable_by_tenant": bool(payload.editable_by_tenant),
        # Iter38r-fix9f — tenant scoping for public visibility within tenant
        "tenant_id": user.get("parent_client_id") or user.get("client_id") or user["id"],
        "title": title,
        "content_html": payload.content_html or "",
        "tags": payload.tags or [],
        "client_id": (payload.client_id or None) if kind == "suivis" else None,
        "event_date": (payload.event_date or None) if kind == "suivis" else None,
        "images": images,
        "is_private": bool(payload.is_private),
        # Iter35m — Targeted visibility (only honored when is_private=True)
        "target_user_ids": list(payload.target_user_ids or []),
        # Iter35g — Voice note + Whisper transcription fields (already in the
        # UserNoteCreate model since iter34y/34z, just need to persist them).
        "voice_note_url": payload.voice_note_url or None,
        "voice_note_transcript": payload.voice_note_transcript or None,
        # Iter38r-fix9k — Checklist items for kind=tasks (Google Keep style)
        "task_items": [
            {**(it.model_dump() if hasattr(it, "model_dump") else dict(it)),
             "id": (it.id if hasattr(it, "id") and it.id else _uuid())}
            for it in (payload.task_items or [])
        ] if kind == "tasks" else None,
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await coll.insert_one(doc.copy())
    doc.pop("_id", None)
    # Iter34x — activity feed (rapport / suivi / note / tâche)
    activity_kind_map = {"reports": "rapport", "suivis": "suivi", "notes": "note", "tasks": "tache"}
    activity_kind = activity_kind_map.get(kind, "note")
    user_client = user.get("parent_client_id") or user.get("client_id") or user["id"]
    await _log_activity(client_id=user_client, kind=activity_kind, action="created", label=title, actor=user, target_id=doc["id"])
    # Await the webhook synchronously so the real upstream status can be
    # returned to the caller (and displayed via popup on the frontend).
    webhook_result = await _fire_notes_webhook("created", kind, doc, user)
    doc["webhook_result"] = webhook_result
    return doc


@api.put("/me/notes/{kind}/{note_id}", tags=["Portail Client"])
async def me_update_note(
    kind: str,
    note_id: str,
    payload: UserNoteUpdate,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    existing = await coll.find_one({"id": note_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Note introuvable")
    # Owner OR elevated user can edit
    # Iter43 — Tenant colleagues can edit if editable_by_tenant=True
    can_collab_edit = False
    if existing.get("owner_id") != user["id"] and not _is_elevated_creator(user):
        if existing.get("shared_with_tenant") and existing.get("editable_by_tenant"):
            try:
                from routes.tenant_sharing import resolve_visible_owner_ids  # noqa: E402
                visible_ids = await resolve_visible_owner_ids(db, user)
                if existing.get("owner_id") in visible_ids:
                    can_collab_edit = True
            except Exception:
                pass
        if not can_collab_edit:
            raise HTTPException(status_code=403, detail="Modification non autorisée")
    # 1h lock from creation (unless admin/superviseur which can always fix)
    if not _is_admin_or_superviseur(user):
        try:
            created = datetime.fromisoformat(existing["created_at"])
        except Exception:
            created = datetime.now(timezone.utc)
        if datetime.now(timezone.utc) > created + timedelta(hours=1):
            raise HTTPException(status_code=403, detail="Modification verrouillée : la fenêtre d'1h après la création est dépassée")

    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "images" in update:
        update["images"] = _validate_images(update["images"], max_count=10)
    # Iter38r-fix9k — Task items: ensure each item has an id, preserve order
    if "task_items" in update and kind == "tasks":
        normalized = []
        for it in update["task_items"]:
            it = dict(it)
            if not it.get("id"):
                it["id"] = _uuid()
            normalized.append(it)
        update["task_items"] = normalized
    update["updated_at"] = _now()
    await coll.update_one({"id": note_id}, {"$set": update})
    refreshed = await coll.find_one({"id": note_id}, {"_id": 0}) or {**existing, **update}
    activity_kind = "rapport" if kind == "reports" else "suivi"
    user_client = user.get("parent_client_id") or user.get("client_id") or user["id"]
    await _log_activity(client_id=user_client, kind=activity_kind, action="updated", label=refreshed.get("title") or "(sans titre)", actor=user, target_id=note_id)
    webhook_result = await _fire_notes_webhook("updated", kind, refreshed, user)
    return {"ok": True, "webhook_result": webhook_result}


@api.delete("/me/notes/{kind}/{note_id}", tags=["Portail Client"])
async def me_delete_note(
    kind: str,
    note_id: str,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Suppression réservée aux rôles Administrateur / Superviseur")
    existing = await coll.find_one({"id": note_id}, {"_id": 0})
    res = await coll.delete_one({"id": note_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Note introuvable")
    if existing:
        activity_kind = "rapport" if kind == "reports" else "suivi"
        user_client = user.get("parent_client_id") or user.get("client_id") or user["id"]
        await _log_activity(client_id=user_client, kind=activity_kind, action="deleted", label=existing.get("title") or "(sans titre)", actor=user, target_id=note_id)
        webhook_result = await _fire_notes_webhook("deleted", kind, existing, user)
        return {"ok": True, "webhook_result": webhook_result}
    return {"ok": True}


# =====================================================================
# Iter36d — Note de Service: send a WhatsApp template broadcast to every
# tracked user of the linked client, using a 3-parameter template
# (default name: notedeservice_fr).
#   {{1}} → numéro de la note
#   {{2}} → nom du destinataire
#   {{3}} → contenu de la note (texte brut)
# =====================================================================
@api.post("/me/notes/{kind}/{note_id}/note-de-service", tags=["Portail Client"])
async def me_send_note_de_service(
    kind: str,
    note_id: str,
    user: dict = Depends(get_current_user),
):
    coll = _user_notes_collection(kind)
    note = await coll.find_one({"id": note_id}, {"_id": 0})
    if not note:
        raise HTTPException(status_code=404, detail="Note introuvable")
    if note.get("owner_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès refusé")
    if note.get("is_private"):
        raise HTTPException(status_code=400, detail="La note doit être publique pour générer une note de service.")
    if not note.get("numero"):
        raise HTTPException(status_code=400, detail="La note doit porter un numéro pour générer une note de service.")
    import re as _re
    content_text = _re.sub(r"<[^>]+>", " ", note.get("content_html") or "").strip()
    content_text = _re.sub(r"\s+", " ", content_text)[:900]
    if not content_text:
        raise HTTPException(status_code=400, detail="Note vide — rien à diffuser.")

    s = await db.settings.find_one({"_id": "global"}) or {}
    tpl_name = (s.get("wa_template_note_service") or "notedeservice_fr").strip()
    tpl_lang = (s.get("wa_template_note_service_language") or "fr").strip() or "fr"

    target_client = note.get("client_id") or user.get("client_id") or user["id"]
    suivis_cursor = db.tracked_users.find(
        {"client_id": target_client, "status": {"$ne": "archived"}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "whatsapp_number": 1, "email": 1},
    )
    suivis = [u async for u in suivis_cursor]
    if not suivis:
        raise HTTPException(status_code=400, detail="Aucun utilisateur suivi actif sur le client lié.")

    sent: list = []
    skipped: list = []
    for s_user in suivis:
        phone = (s_user.get("whatsapp_number") or s_user.get("phone") or "").strip()
        recipient_name = (s_user.get("name") or s_user.get("email") or "Destinataire").strip()
        if not phone:
            skipped.append({"id": s_user["id"], "name": recipient_name, "reason": "no_phone"})
            continue
        components = [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(note.get("numero") or "")[:60]},
                {"type": "text", "text": recipient_name[:60]},
                {"type": "text", "text": content_text},
            ],
        }]
        try:
            r = await _wa_send_template(phone, tpl_name, tpl_lang, components)
            ok = bool(r.get("ok"))
            outbound = {
                "id": _uuid(),
                "client_id": target_client,
                "owner_id": user["id"],
                "direction": "outbound",
                "from": phone,
                "to": phone,
                "phone_digits": "".join(ch for ch in phone if ch.isdigit()),
                "body": f"[Note de Service {note.get('numero')}] {content_text[:300]}",
                "template_name": tpl_name,
                "template_language": tpl_lang,
                "wa_message_id": r.get("message_id"),
                "status": "sent" if ok else "failed",
                "api_message": r.get("error"),
                "tracked_user_id": s_user["id"],
                "tracked_user_name": recipient_name,
                "source": "note_de_service",
                "source_note_id": note_id,
                "source_note_numero": note.get("numero"),
                "sent_at": _now(),
                "created_at": _now(),
            }
            await db.whatsapp_messages.insert_one(outbound.copy())
            (sent if ok else skipped).append({
                "id": s_user["id"], "name": recipient_name, "phone": phone,
                "wa_message_id": r.get("message_id"), "error": r.get("error"),
            })
        except Exception as exc:  # noqa: BLE001
            skipped.append({"id": s_user["id"], "name": recipient_name, "reason": str(exc)[:200]})

    try:
        await _log_activity(
            client_id=target_client, kind="note_service", action="broadcast",
            label=f"Note {note.get('numero')} -> {len(sent)} destinataire(s)",
            actor=user, target_id=note_id,
        )
    except Exception:
        pass
    await coll.update_one(
        {"id": note_id},
        {"$set": {"last_note_service_at": _now(), "last_note_service_count": len(sent)}},
    )
    return {
        "ok": True,
        "note_numero": note.get("numero"),
        "template": tpl_name,
        "sent": sent,
        "skipped": skipped,
        "sent_count": len(sent),
        "skipped_count": len(skipped),
        "total_targets": len(suivis),
    }


# Iter36e — Admin history of Note de Service broadcasts (last 20)
@api.get("/admin/note-service/history", tags=["Admin"])
async def admin_note_service_history(
    limit: int = 20,
    _: dict = Depends(get_current_admin),
):
    """Aggregate the last N Note de Service broadcasts, grouped by source note.
    Each row exposes: note_id, note_numero, last_sent_at, sent_count,
    failed_count, recipient_count, sender (owner_email), recipients list.
    """
    limit = max(1, min(int(limit or 20), 200))
    pipeline = [
        {"$match": {"source": "note_de_service"}},
        {"$group": {
            "_id": "$source_note_id",
            "note_numero": {"$last": "$source_note_numero"},
            "client_id": {"$last": "$client_id"},
            "owner_id": {"$last": "$owner_id"},
            "template_name": {"$last": "$template_name"},
            "last_sent_at": {"$max": "$created_at"},
            "first_sent_at": {"$min": "$created_at"},
            "sent_count": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "failed_count": {"$sum": {"$cond": [{"$ne": ["$status", "sent"]}, 1, 0]}},
            "recipients": {"$push": {
                "tracked_user_id": "$tracked_user_id",
                "tracked_user_name": "$tracked_user_name",
                "phone": "$to",
                "status": "$status",
                "error": "$api_message",
                "wa_message_id": "$wa_message_id",
            }},
        }},
        {"$sort": {"last_sent_at": -1}},
        {"$limit": limit},
    ]
    rows: list[dict] = []
    async for r in db.whatsapp_messages.aggregate(pipeline):
        # Enrich with note title (look up across all note kinds)
        note_title = None
        is_private = None
        note_kind = None
        for kind in ("notes", "tasks", "reports"):
            doc = await _user_notes_collection(kind).find_one(
                {"id": r["_id"]}, {"_id": 0, "title": 1, "is_private": 1, "kind": 1, "numero": 1},
            )
            if doc:
                note_title = doc.get("title")
                is_private = doc.get("is_private")
                note_kind = doc.get("kind") or kind
                break
        owner = await db.users.find_one({"id": r.get("owner_id")}, {"_id": 0, "email": 1, "full_name": 1}) or {}
        rows.append({
            "note_id": r["_id"],
            "note_numero": r.get("note_numero"),
            "note_title": note_title,
            "note_kind": note_kind,
            "is_private": is_private,
            "template_name": r.get("template_name"),
            "last_sent_at": r.get("last_sent_at"),
            "first_sent_at": r.get("first_sent_at"),
            "sent_count": r.get("sent_count", 0),
            "failed_count": r.get("failed_count", 0),
            "recipient_count": r.get("sent_count", 0) + r.get("failed_count", 0),
            "owner_email": owner.get("email"),
            "owner_name": owner.get("full_name"),
            "recipients": r.get("recipients", []),
        })
    return {"items": rows, "total": len(rows), "limit": limit}


# Iter36f — Retry only the failed recipients of a previous Note de Service
@api.post("/admin/note-service/{note_id}/retry-failed", tags=["Admin"])
async def admin_retry_failed_note_service(
    note_id: str,
    _: dict = Depends(get_current_admin),
):
    """Resend a Note de Service ONLY to recipients whose previous attempt
    failed. Useful when a Meta template was paused and has been re-enabled,
    or when a phone number is fixed. Idempotent for KO recipients only:
    successful recipients are NOT touched (no duplicate notifications).
    """
    # 1) Locate the source note across all kinds
    note = None
    note_kind = None
    for kind in ("notes", "tasks", "reports"):
        doc = await _user_notes_collection(kind).find_one({"id": note_id}, {"_id": 0})
        if doc:
            note = doc
            note_kind = kind
            break
    if not note:
        raise HTTPException(status_code=404, detail="Note introuvable")
    if note.get("is_private"):
        raise HTTPException(status_code=400, detail="La note n'est plus publique.")
    if not note.get("numero"):
        raise HTTPException(status_code=400, detail="La note ne porte plus de numéro.")
    import re as _re
    content_text = _re.sub(r"<[^>]+>", " ", note.get("content_html") or "").strip()
    content_text = _re.sub(r"\s+", " ", content_text)[:900]
    if not content_text:
        raise HTTPException(status_code=400, detail="Note vide — rien à diffuser.")

    s = await db.settings.find_one({"_id": "global"}) or {}
    tpl_name = (s.get("wa_template_note_service") or "notedeservice_fr").strip()
    tpl_lang = (s.get("wa_template_note_service_language") or "fr").strip() or "fr"

    # 2) Find KO recipients from the most recent broadcast for this note.
    #    We pick the highest created_at as "last broadcast" and grab all KO
    #    outbound rows up to that moment that aren't superseded by a later OK.
    last_attempt = await db.whatsapp_messages.find_one(
        {"source": "note_de_service", "source_note_id": note_id},
        {"_id": 0, "created_at": 1},
        sort=[("created_at", -1)],
    )
    if not last_attempt:
        raise HTTPException(status_code=400, detail="Aucune diffusion antérieure à retenter.")
    # All recipients ever for this note
    per_recipient: dict[str, dict] = {}
    cur = db.whatsapp_messages.find(
        {"source": "note_de_service", "source_note_id": note_id},
        {"_id": 0, "tracked_user_id": 1, "tracked_user_name": 1, "to": 1,
         "status": 1, "created_at": 1},
    ).sort("created_at", 1)
    async for m in cur:
        tid = m.get("tracked_user_id") or m.get("to")
        if not tid:
            continue
        per_recipient[tid] = m  # last seen wins (we sorted asc → last is most recent)
    # KO = recipients whose LATEST attempt is not 'sent'
    ko_targets = [m for m in per_recipient.values() if m.get("status") != "sent"]
    if not ko_targets:
        return {"ok": True, "sent": [], "skipped": [], "sent_count": 0, "skipped_count": 0,
                "message": "Aucun destinataire en échec — rien à retenter."}

    sent: list = []
    skipped: list = []
    for old in ko_targets:
        phone = (old.get("to") or "").strip()
        recipient_name = (old.get("tracked_user_name") or phone or "Destinataire").strip()
        if not phone:
            skipped.append({"name": recipient_name, "reason": "no_phone"})
            continue
        components = [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(note.get("numero") or "")[:60]},
                {"type": "text", "text": recipient_name[:60]},
                {"type": "text", "text": content_text},
            ],
        }]
        try:
            r = await _wa_send_template(phone, tpl_name, tpl_lang, components)
            ok = bool(r.get("ok"))
            outbound = {
                "id": _uuid(),
                "client_id": note.get("client_id") or "",
                "owner_id": note.get("owner_id"),
                "direction": "outbound",
                "from": phone, "to": phone,
                "phone_digits": "".join(ch for ch in phone if ch.isdigit()),
                "body": f"[Note de Service {note.get('numero')}] {content_text[:300]}",
                "template_name": tpl_name,
                "template_language": tpl_lang,
                "wa_message_id": r.get("message_id"),
                "status": "sent" if ok else "failed",
                "api_message": r.get("error"),
                "tracked_user_id": old.get("tracked_user_id"),
                "tracked_user_name": recipient_name,
                "source": "note_de_service",
                "source_note_id": note_id,
                "source_note_numero": note.get("numero"),
                "is_retry": True,
                "sent_at": _now(),
                "created_at": _now(),
            }
            await db.whatsapp_messages.insert_one(outbound.copy())
            (sent if ok else skipped).append({
                "name": recipient_name, "phone": phone,
                "wa_message_id": r.get("message_id"), "error": r.get("error"),
            })
        except Exception as exc:  # noqa: BLE001
            skipped.append({"name": recipient_name, "reason": str(exc)[:200]})

    try:
        await _log_activity(
            client_id=note.get("client_id") or "", kind="note_service", action="retry_failed",
            label=f"Note {note.get('numero')} -> retry {len(sent)}/{len(ko_targets)}",
            actor={"id": "_system_", "email": "admin"}, target_id=note_id,
        )
    except Exception:
        pass
    return {
        "ok": True,
        "note_numero": note.get("numero"),
        "sent": sent, "skipped": skipped,
        "sent_count": len(sent), "skipped_count": len(skipped),
        "total_targets": len(ko_targets),
    }





@api.get("/me/notes-targets", tags=["Portail Client"])
async def me_notes_targets(user: dict = Depends(get_current_user)):
    """Iter35m — Renvoie la liste des utilisateurs auxquels une note/tâche peut être adressée
    when `is_private=True`. The list always starts with "Moi-même" (the caller),
    followed by every other user that shares the same effective client_id —
    i.e. the linked client + every tracked user / admin / superviseur attached
    to that client. Used to populate the targeting dropdown in the UI.

    Schema returned: { items: [{ id, full_name, email, role, is_self }] }
    """
    me = {
        "id": user["id"],
        "full_name": user.get("full_name") or user.get("email") or "Moi-même",
        "email": user.get("email"),
        "role": user.get("role") or user.get("tracked_role"),
        "is_self": True,
    }
    out: List[Dict[str, Any]] = [me]
    seen: set = {user["id"]}

    # Effective client scope: prefer parent_client_id (typed link), then client_id, then own id
    effective_client_id = user.get("parent_client_id") or user.get("client_id") or user["id"]

    # 1) Other admin/superviseur/client users attached to the same client_id (or parent)
    try:
        cursor = db.users.find(
            {
                "$or": [
                    {"id": effective_client_id},
                    {"client_id": effective_client_id},
                    {"parent_client_id": effective_client_id},
                ],
                "id": {"$ne": user["id"]},
            },
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1},
        )
        async for u in cursor:
            uid = u.get("id")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            out.append({
                "id": uid,
                "full_name": u.get("full_name") or u.get("email") or "—",
                "email": u.get("email"),
                "role": u.get("role"),
                "is_self": False,
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("notes-targets users lookup failed: %s", exc)

    # 2) Tracked users (employees) attached to the same client
    try:
        cursor = db.tracked_users.find(
            {"client_id": effective_client_id},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1},
        )
        async for tu in cursor:
            tid = tu.get("id")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append({
                "id": tid,
                "full_name": tu.get("full_name") or tu.get("email") or "—",
                "email": tu.get("email"),
                "role": tu.get("role") or "tracked",
                "is_self": False,
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("notes-targets tracked_users lookup failed: %s", exc)

    return {"items": out, "count": len(out), "effective_client_id": effective_client_id}


@api.get("/me/notes-summary", tags=["Portail Client"])
async def me_notes_summary(user: dict = Depends(get_current_user)):
    """Renvoie les compteurs et timestamps de dernière mise à jour pour afficher les boutons du dashboard.
    Elevated users see global counts (all notes); others see only their own.

    Iter35g — extended with "notes" and "tasks" kinds (personal user notes/tasks,
    same model as reports/suivis with voice + transcription baked in).
    """
    base = {} if _is_elevated_creator(user) else {"owner_id": user["id"]}
    rep_count = await db.user_reports.count_documents(base)
    sui_count = await db.user_suivis.count_documents(base)
    notes_count = await db.user_notes_personal.count_documents(base)
    tasks_count = await db.user_tasks_personal.count_documents(base)
    rep_last = await db.user_reports.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    sui_last = await db.user_suivis.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    notes_last = await db.user_notes_personal.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    tasks_last = await db.user_tasks_personal.find_one(base, {"_id": 0, "updated_at": 1}, sort=[("updated_at", -1)])
    return {
        "reports": {"count": rep_count, "last_updated": (rep_last or {}).get("updated_at")},
        "suivis": {"count": sui_count, "last_updated": (sui_last or {}).get("updated_at")},
        "notes": {"count": notes_count, "last_updated": (notes_last or {}).get("updated_at")},
        "tasks": {"count": tasks_count, "last_updated": (tasks_last or {}).get("updated_at")},
    }


@api.get("/me/demo/status", tags=["Portail Client"])
async def me_demo_status(user: dict = Depends(get_current_user)):
    """Iter35h — Frontend uses this endpoint to render the persistent
    demo-account banner (countdown + quota gauges). Returns 200 with
    `is_demo: false` for every non-demo account so the front can call it
    unconditionally without 4xx handling."""
    if not _is_demo(user):
        return {"is_demo": False}
    from models import DEMO_DEFAULT_QUOTAS
    overrides = user.get("demo_quotas") or {}
    usage = user.get("demo_usage") or {}
    keys = list(set(list(DEMO_DEFAULT_QUOTAS.keys()) + list(overrides.keys())))
    quotas = {}
    for k in keys:
        limit = int(overrides.get(k, DEMO_DEFAULT_QUOTAS.get(k, 0)) or 0)
        if k == QUOTA_KEY_CONTACTS:
            used = await db.directory_contacts.count_documents({"client_id": user["id"]})
        else:
            used = int(usage.get(k, 0))
        quotas[k] = {"used": used, "limit": limit, "percent": min(100, int((used / limit) * 100)) if limit else 0}
    expires_at = user.get("demo_expires_at")
    days_left = None
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            delta = exp_dt - datetime.now(timezone.utc)
            days_left = max(0, int(delta.total_seconds() // 86400)) if delta.total_seconds() > 0 else 0
        except Exception:
            pass
    return {
        "is_demo": True,
        "expires_at": expires_at,
        "days_left": days_left,
        "quotas": quotas,
    }


@api.get("/admin/demo/expiry-events", tags=["Admin"])
async def admin_list_demo_expiry_events(
    only_unresolved: bool = Query(default=True),
    _: dict = Depends(get_current_admin),
):
    """Demo accounts that have expired — admin reviews and decides:
    keep disabled, extend the expiry, or delete entirely."""
    q = {}
    if only_unresolved:
        q = {"resolved": {"$ne": True}}
    items = await db.demo_expiry_events.find(q, {"_id": 0}).sort("detected_at", -1).limit(200).to_list(200)
    return {"items": items, "count": len(items)}


@api.post("/admin/demo/expiry-events/{ev_id}/resolve", tags=["Admin"])
async def admin_resolve_demo_expiry(ev_id: str, _: dict = Depends(get_current_admin)):
    res = await db.demo_expiry_events.update_one(
        {"id": ev_id, "resolved": {"$ne": True}},
        {"$set": {"resolved": True, "resolved_at": _now()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Événement introuvable")
    return {"ok": True}




# ====================================================================
# PORTAL — Interventions (elevated users)
# ====================================================================
@api.post("/me/interventions", tags=["Portail Client"])
async def me_create_intervention(
    request: Request,
    payload: InterventionCreate,
    user: dict = Depends(get_current_user),
):
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Rôle insuffisant pour créer une intervention")
    await _check_descent_window(action_label="enregistrement", user=user)
    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    intervention_number = await _next_intervention_number(client)
    images = _validate_images(payload.images, max_count=10)
    doc = {
        "id": _uuid(),
        **payload.model_dump(),
        "images": images,
        "intervention_number": intervention_number,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "owner_name": user.get("full_name"),
        "owner_role": user.get("tracked_role") or user.get("role"),
        # Iter43 — Snapshot société/rattachement
        "owner_company": (user.get("company") or "").strip() or None,
        "owner_parent_client_id": user.get("parent_client_id"),
        "shared_with_tenant": bool(payload.shared_with_tenant),
        "editable_by_tenant": bool(payload.editable_by_tenant),
        "ip": _client_ip_from_request(request),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.interventions.insert_one(doc.copy())
    doc.pop("_id", None)
    # Iter34y — activity feed (intervention)
    await _log_activity(client_id=payload.client_id, kind="intervention", action="created", label=doc.get("title") or doc.get("intervention_number") or "(intervention)", actor=user, target_id=doc["id"])
    webhook_result = await _fire_intervention_webhook("created", doc)
    doc["webhook_result"] = webhook_result
    # Fire automation: intervention.created (portal client)
    try:
        asyncio.create_task(_emit_event("intervention.created", {
            "client_id": payload.client_id,
            "extra_ctx": {
                "intervention_number": doc.get("intervention_number") or "",
                "intervention_subject": doc.get("subject") or doc.get("title") or "",
            },
        }))
    except Exception:
        pass
    return doc


@api.delete("/me/interventions/{int_id}", tags=["Portail Client"])
async def me_delete_intervention(int_id: str, user: dict = Depends(get_current_user)):
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Suppression réservée aux rôles Administrateur / Superviseur")
    existing = await db.interventions.find_one({"id": int_id}, {"_id": 0})
    res = await db.interventions.delete_one({"id": int_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    # Iter34y — activity feed
    if existing:
        await _log_activity(client_id=existing.get("client_id"), kind="intervention", action="deleted", label=existing.get("title") or existing.get("intervention_number") or "(intervention)", actor=user, target_id=int_id)
    return {"ok": True}


# ====================================================================
# PORTAL — Documents (Moderation+ can read all & upload, only Admin/Sup delete)
# ====================================================================
@api.post("/me/documents", tags=["Portail Client"])
async def me_create_document(payload: DocumentCreate, user: dict = Depends(get_current_user)):
    if not _can_consult_all_docs(user):
        raise HTTPException(status_code=403, detail="Téléversement de document réservé aux rôles Modération / Administrateur / Superviseur")
    doc = {"id": _uuid(), **payload.model_dump(), "uploaded_by_user_id": user["id"], "uploaded_by_email": user["email"], "created_at": _now()}
    await db.documents.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.delete("/me/documents/{doc_id}", tags=["Portail Client"])
async def me_delete_document(doc_id: str, user: dict = Depends(get_current_user)):
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Suppression réservée aux rôles Administrateur / Superviseur")
    res = await db.documents.delete_one({"id": doc_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return {"ok": True}


# Portal-side file upload — same behaviour as /admin/upload but allowed for Moderation+
@api.post("/me/upload", tags=["Portail Client"])
async def me_upload(request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not _can_consult_all_docs(user) and not _is_demo(user):
        raise HTTPException(status_code=403, detail="Téléversement réservé aux rôles Modération / Administrateur / Superviseur")
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    # 2026-02 fork iter108 — Deploy-safe upload helper (storage-first, local cache).
    from storage import asave_upload_and_cache  # lot 26 : dans un thread, sans figer le serveur
    data = file.file.read()
    size = len(data)
    # Iter35h — demo storage cap (post-read check to avoid disk waste on abort).
    if _is_demo(user):
        await _enforce_demo_quota(user, QUOTA_KEY_STORAGE, increment=size)
    target, storage_path, storage_error = await asave_upload_and_cache(
        upload_dir=UPLOAD_DIR, filename=safe_name, data=data, content_type=content_type,
    )
    ext_suffix = (suffix.lstrip(".") or "").lower()
    public_path = f"/api/files/{file_id}{('.' + ext_suffix) if ext_suffix else ''}"
    if storage_error:
        logger.warning("[me_upload] storage mirror failed: %s", storage_error)
    file_doc = {
        "id": file_id,
        "filename": file.filename,
        "stored_name": safe_name,
        "extension": suffix.lstrip(".") if suffix else None,
        "content_type": file.content_type or mimetypes.guess_type(file.filename or "")[0],
        "size": size,
        "url": public_path,
        # Absolute public URL (used by Meta to fetch headers/media on outbound templates)
        # Include the extension so Meta accepts it as a "valid document/image link".
        "public_url": f"{(_public_base_url(request) or str(request.base_url).rstrip('/'))}{public_path}",
        "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"),
        "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
        "storage_path": storage_path,
        "storage_error": storage_error,
    }
    await db.files.insert_one(file_doc.copy())
    await db.document_logs.insert_one({
        "id": _uuid(),
        "event_type": "upload",
        "file_id": file_id,
        "filename": file.filename,
        "extension": file_doc.get("extension"),
        "size": size,
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "ip": file_doc["uploaded_from_ip"],
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
    })
    file_doc.pop("_id", None)
    return file_doc


# ====================================================================
# PORTAL — Contacts inbox (elevated users)
# ====================================================================
@api.get("/me/contact-inbox", tags=["Portail Client"])
async def me_contact_inbox(user: dict = Depends(get_current_user)):
    """Inbox of messages submitted via the public contact form.
    NOTE: renamed from /me/contacts to avoid collision with the contacts directory.
    """
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Accès aux messages réservé aux rôles Modération / Administrateur / Superviseur")
    items = await db.contacts.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


@api.post("/me/contacts/{contact_id}/save-as-tracked-user", tags=["Portail Client"])
async def me_save_contact_as_tracked(
    contact_id: str,
    payload: SaveContactAsTrackedUser,
    user: dict = Depends(get_current_user),
):
    """Identique à /admin/contacts/{id}/save-as-tracked-user mais auto-génère aussi un mot de passe,
    creates a bridged users row, optionally emails the credentials, and returns the password.
    """
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Accès réservé aux rôles Modération / Administrateur / Superviseur")
    contact = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Message introuvable")
    email = (contact.get("email") or "").strip().lower()
    if not is_valid_email_syntax(email):
        raise HTTPException(status_code=400, detail="Email du message invalide (syntaxe)")
    if payload.role not in TRACKED_USER_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {', '.join(TRACKED_USER_ROLES)}")
    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    existing = await db.tracked_users.find_one({"email": email, "client_id": payload.client_id}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="Cet utilisateur est déjà enregistré pour ce client")

    # Create tracked user
    tu_id = _uuid()
    tu_doc = {
        "id": tu_id,
        "client_id": payload.client_id,
        "name": contact.get("name") or email,
        "email": email,
        "role": payload.role,
        "department": payload.department,
        "phone": contact.get("phone"),
        "company": contact.get("company"),
        "status": "active",
        "source_contact_id": contact_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.tracked_users.insert_one(tu_doc.copy())

    # Auto-generate a strong password & bridge user
    raw_pwd = secrets.token_urlsafe(9)
    user_id = _uuid()
    await db.users.insert_one({
        "id": user_id,
        "email": email,
        "password_hash": hash_password(raw_pwd),
        "full_name": tu_doc["name"],
        "role": "client",
        "phone": tu_doc.get("phone"),
        "company": client.get("company"),
        "logo_url": client.get("logo_url"),
        "account_status": "active",
        "tracked_user_id": tu_id,
        "tracked_role": payload.role,
        "parent_client_id": payload.client_id,
        "created_at": _now(),
        "updated_at": _now(),
    })
    await db.tracked_users.update_one(
        {"id": tu_id},
        {"$set": {"user_account_id": user_id, "has_password": True, "updated_at": _now()}},
    )
    await db.contacts.update_one(
        {"id": contact_id},
        {"$set": {"saved_as_tracked_user_id": tu_id, "updated_at": _now()}},
    )

    # Try to email the credentials (non-blocking, best-effort)
    email_sent = False
    try:
        from email_service import send_email
        s = await db.settings.find_one({"_id": "global"}) or {}
        site = s.get("company_email") or "support@sawalismartsystems.com"
        text_body = (
            f"Bonjour {tu_doc['name']},\n\n"
            f"Un accès au portail SAWALI vient de vous être créé.\n\n"
            f"Identifiant : {email}\n"
            f"Mot de passe initial : {raw_pwd}\n\n"
            f"Connectez-vous via /login. Vous pourrez le modifier depuis votre espace.\n\n"
            f"— L'équipe {site}"
        )
        html_body = text_body.replace("\n", "<br>")
        email_sent = await send_email(email, "Vos identifiants SAWALI", html_body, text_body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email tracked-user credentials failed: %s", exc)

    tu_doc.pop("_id", None)
    return {**tu_doc, "generated_password": raw_pwd, "email_sent": email_sent}


# ====================================================================
# RATINGS — 5-star rating on report / suivi / intervention (Admin/Sup only)
# ====================================================================
RATEABLE_KINDS = ("reports", "suivis", "interventions", "formations", "notes", "tasks")


@api.post("/me/ratings/{kind}/{target_id}", tags=["Portail Client"])
async def me_rate(
    kind: str,
    target_id: str,
    payload: RatingCreate,
    user: dict = Depends(get_current_user),
):
    if kind not in RATEABLE_KINDS:
        raise HTTPException(status_code=404, detail="Type non noté")
    if not _can_rate(user) and not (kind == "formations" and _is_tracked_user(user)):
        raise HTTPException(status_code=403, detail="Notation non autorisée")
    if not 1 <= payload.stars <= 5:
        raise HTTPException(status_code=400, detail="Note invalide (1 à 5)")
    coll_map = {
        "reports": db.user_reports,
        "suivis": db.user_suivis,
        "interventions": db.interventions,
        "formations": db.formations,
        # Iter35r — Notes & Tasks personnelles
        "notes": db.user_notes_personal,
        "tasks": db.user_tasks_personal,
    }
    coll = coll_map[kind]
    target = await coll.find_one({"id": target_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    rating_doc = {
        "id": _uuid(),
        "kind": kind,
        "target_id": target_id,
        "rated_by_user_id": user["id"],
        "rated_by_email": user["email"],
        "stars": int(payload.stars),
        "comment": (payload.comment or "").strip() or None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    # Upsert: one rating per (rater, target)
    await db.ratings.update_one(
        {"kind": kind, "target_id": target_id, "rated_by_user_id": user["id"]},
        {"$set": rating_doc},
        upsert=True,
    )
    return {"ok": True, "stars": rating_doc["stars"]}


@api.delete("/me/ratings/{kind}/{target_id}", tags=["Portail Client"])
async def me_unrate(kind: str, target_id: str, user: dict = Depends(get_current_user)):
    if not _can_rate(user):
        raise HTTPException(status_code=403, detail="Notation réservée aux rôles Administrateur / Superviseur")
    await db.ratings.delete_one(
        {"kind": kind, "target_id": target_id, "rated_by_user_id": user["id"]}
    )
    return {"ok": True}


# ====================================================================
# ACCESS LOGS — every page access in client portal (admin/sup only to view)
# ====================================================================
@api.post("/me/access-log", tags=["Portail Client"])
async def me_log_access(
    request: Request,
    payload: AccessLogCreate,
    user: dict = Depends(get_current_user),
):
    """Enregistre un accès à une page du portail. Appelé par la SPA à chaque changement de route."""
    await db.access_logs.insert_one({
        "id": _uuid(),
        "user_id": user["id"],
        "user_email": user["email"],
        "user_name": user.get("full_name"),
        "role": user.get("role"),
        "tracked_role": user.get("tracked_role"),
        "module": (payload.module or "").strip()[:120],
        "page": (payload.page or "").strip()[:255],
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent", "")[:500],
        "created_at": _now(),
    })
    return {"ok": True}


@api.get("/admin/access-logs", tags=["Admin"])
async def admin_access_logs(
    user_email: Optional[str] = None,
    module: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 1000,
    user: dict = Depends(get_current_user),
):
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Accès réservé aux rôles Administrateur / Superviseur")
    query = {}
    if user_email:
        query["user_email"] = {"$regex": re.escape(user_email), "$options": "i"}
    if module:
        query["module"] = {"$regex": re.escape(module), "$options": "i"}
    if q:
        query["$or"] = [
            {"user_email": {"$regex": re.escape(q), "$options": "i"}},
            {"user_name": {"$regex": re.escape(q), "$options": "i"}},
            {"module": {"$regex": re.escape(q), "$options": "i"}},
            {"page": {"$regex": re.escape(q), "$options": "i"}},
        ]
    items = await db.access_logs.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 10), 5000))
    return items


@api.get("/admin/access-logs/export.csv", tags=["Admin"])
async def admin_access_logs_csv(
    user_email: Optional[str] = None,
    module: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if not _can_delete_records(user):
        raise HTTPException(status_code=403, detail="Accès réservé aux rôles Administrateur / Superviseur")
    items = await admin_access_logs(user_email=user_email, module=module, q=None, limit=5000, user=user)
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "user_email", "user_name", "role", "tracked_role", "module", "page", "ip"])
    for it in items:
        writer.writerow([
            it.get("created_at", ""),
            it.get("user_email", ""),
            it.get("user_name", ""),
            it.get("role", ""),
            it.get("tracked_role", ""),
            it.get("module", ""),
            it.get("page", ""),
            it.get("ip", ""),
        ])
    return JSONResponse(
        content={"csv": buf.getvalue()},
        headers={"Cache-Control": "no-store"},
    )


# ====================================================================
# API TRACE — frontend axios interceptor logs every mutating call here.
# Only the seeded super-admin (admin@sawalismartsystems.com) can read.
# ====================================================================
SUPER_ADMIN_EMAIL = (os.environ.get("SUPER_ADMIN_EMAIL") or "admin@sawalismartsystems.com").lower()
TRACE_MAX_BODY_CHARS = 8000

_scheduler = None  # APScheduler instance (set up in on_startup)
_health_webhook_semaphore = asyncio.Semaphore(5)  # cap concurrent realtime webhooks during error bursts
TRACE_SENSITIVE_KEYS_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|recaptcha|otp|code|session_token|"
    r"smtp_password|smtp_user|api_basic_pass|webhook_token|webhook_basic_pass|"
    r"notes_webhook_token|notes_webhook_basic_pass)",
    re.IGNORECASE,
)


def _redact_sensitive(value):
    """Server-side redaction guard (in case the FE didn't redact)."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        return json.dumps(_redact_sensitive(parsed), ensure_ascii=False, default=str)
    if isinstance(value, list):
        return [_redact_sensitive(v) for v in value]
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if TRACE_SENSITIVE_KEYS_RE.search(k) else _redact_sensitive(v))
            for k, v in value.items()
        }
    return value


def _truncate_for_trace(value):
    if value is None:
        return None
    try:
        if isinstance(value, (dict, list)):
            s = json.dumps(value, ensure_ascii=False, default=str)
        else:
            s = str(value)
    except Exception:
        s = repr(value)
    if len(s) > TRACE_MAX_BODY_CHARS:
        return s[:TRACE_MAX_BODY_CHARS] + f"... (truncated, {len(s)} chars)"
    return s


@api.post("/me/api-trace", tags=["Portail Client"])
async def me_api_trace(
    request: Request,
    payload: ApiTraceCreate,
    user: dict = Depends(get_current_user),
):
    """Records one API call from the frontend (mutations only, set up by the axios interceptor)."""
    safe_req = _redact_sensitive(payload.request_body)
    safe_resp = _redact_sensitive(payload.response_body)
    doc = {
        "id": _uuid(),
        "user_id": user["id"],
        "user_email": user["email"],
        "user_name": user.get("full_name"),
        "role": user.get("role"),
        "tracked_role": user.get("tracked_role"),
        "method": (payload.method or "").upper()[:10],
        "url": (payload.url or "")[:512],
        "status": int(payload.status or 0),
        "request_body": _truncate_for_trace(safe_req),
        "response_body": _truncate_for_trace(safe_resp),
        "duration_ms": int(payload.duration_ms or 0),
        "module": (payload.module or "")[:120],
        "error": (payload.error or "")[:500] if payload.error else None,
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent", "")[:500],
        "created_at": _now(),
    }
    await db.api_traces.insert_one(doc.copy())
    # Fire real-time alert (only on error rows, never block the request)
    try:
        if doc["status"] >= 400:
            asyncio.create_task(_fire_health_realtime(doc))
    except RuntimeError:
        pass
    return {"ok": True}


def _ensure_super_admin(user: dict) -> None:
    if (user.get("email") or "").lower() != SUPER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Accès réservé au superviseur principal")


@api.get("/admin/api-traces", tags=["Admin"])
async def admin_api_traces(
    user_email: Optional[str] = None,
    method: Optional[str] = None,
    status: Optional[int] = None,
    q: Optional[str] = None,
    only_errors: bool = False,
    limit: int = 1000,
    user: dict = Depends(get_current_user),
):
    _ensure_super_admin(user)
    query = {}
    if user_email:
        query["user_email"] = {"$regex": re.escape(user_email), "$options": "i"}
    if method:
        query["method"] = method.upper()
    if status:
        query["status"] = int(status)
    if only_errors:
        query["status"] = {"$gte": 400}
    if q:
        query["$or"] = [
            {"user_email": {"$regex": re.escape(q), "$options": "i"}},
            {"url": {"$regex": re.escape(q), "$options": "i"}},
            {"module": {"$regex": re.escape(q), "$options": "i"}},
            {"request_body": {"$regex": re.escape(q), "$options": "i"}},
            {"response_body": {"$regex": re.escape(q), "$options": "i"}},
        ]
    items = await db.api_traces.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 10), 5000))
    return items


@api.delete("/admin/api-traces", tags=["Admin"])
async def admin_clear_api_traces(user: dict = Depends(get_current_user)):
    _ensure_super_admin(user)
    res = await db.api_traces.delete_many({})
    return {"ok": True, "deleted": res.deleted_count}


@api.get("/admin/api-traces/export.csv", tags=["Admin"])
async def admin_api_traces_csv(
    user_email: Optional[str] = None,
    method: Optional[str] = None,
    only_errors: bool = False,
    user: dict = Depends(get_current_user),
):
    _ensure_super_admin(user)
    items = await admin_api_traces(
        user_email=user_email, method=method, status=None, q=None,
        only_errors=only_errors, limit=5000, user=user,
    )
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "user_email", "method", "url", "status", "duration_ms", "module", "ip", "request_body", "response_body", "error"])
    for it in items:
        writer.writerow([
            it.get("created_at", ""), it.get("user_email", ""), it.get("method", ""),
            it.get("url", ""), it.get("status", ""), it.get("duration_ms", ""),
            it.get("module", ""), it.get("ip", ""),
            (it.get("request_body") or "")[:1000],
            (it.get("response_body") or "")[:1000],
            it.get("error") or "",
        ])
    return JSONResponse(content={"csv": buf.getvalue()}, headers={"Cache-Control": "no-store"})
