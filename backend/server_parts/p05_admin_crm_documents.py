# server_parts/p05_admin_crm_documents.py — CRM, paiements des tenants, rendez-vous, interventions, documents, catégories, déploiements, téléversement, stockage, politiques.
# Morceau de l'ancien server.py (lignes 7713 à 9206), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# CRM — Notes & Tasks per client
# ====================================================================
class ClientNoteCreate(BaseModel):
    text: str
    voice_note_url: Optional[str] = None  # Iter35g — note vocale facultative
    voice_note_transcript: Optional[str] = None  # Iter35g — transcription Whisper auto


class ClientTaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_at: Optional[str] = None  # ISO-8601 (date or datetime)
    remind_via_whatsapp: bool = False
    voice_note_url: Optional[str] = None  # Iter35g
    voice_note_transcript: Optional[str] = None  # Iter35g


class ClientTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[str] = None
    status: Optional[str] = None  # 'open' | 'done'
    remind_via_whatsapp: Optional[bool] = None
    voice_note_url: Optional[str] = None  # Iter35g
    voice_note_transcript: Optional[str] = None  # Iter35g


async def _ensure_client_exists(client_id: str) -> dict:
    user = await db.users.find_one({"id": client_id}, {"_id": 0, "full_name": 1, "company": 1, "phone": 1, "email": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return user


# =============================================================================
# 2026-02 fork iter104 — Tenant payments (Payment History)
# =============================================================================
class TenantPaymentCreate(BaseModel):
    payment_date: str  # ISO YYYY-MM-DD
    invoice_ref: Optional[str] = None
    amount_due: Optional[float] = None
    amount_paid: float
    payment_method_id: Optional[str] = None
    payment_method_label: Optional[str] = None
    notes: Optional[str] = None
    send_confirmation: Optional[bool] = True


@api.get("/admin/clients/{client_id}/payments", tags=["Admin"])
async def admin_list_client_payments(client_id: str, _: dict = Depends(get_current_admin)):
    await _ensure_client_exists(client_id)
    return await db.tenant_payments.find({"tenant_id": client_id}, {"_id": 0}).sort("payment_date", -1).to_list(500)


@api.post("/admin/clients/{client_id}/payments", tags=["Admin"])
async def admin_create_client_payment(
    client_id: str,
    payload: TenantPaymentCreate,
    admin_user: dict = Depends(get_current_admin),
):
    """Register a payment received from a client and (optionally) fire the WA
    receipt confirmation template.

    Side effects on success:
      1. Inserts a row in `db.tenant_payments`.
      2. Updates `users.last_payment_at` (so the Retard column recomputes).
      3. Sends the WA `payment_confirmation_template` (default
         `confirmation_paiement_avecrecu`) to the client's phone.
    """
    client = await db.users.find_one(
        {"id": client_id},
        {"_id": 0, "phone": 1, "whatsapp_number": 1, "full_name": 1, "email": 1,
         "company": 1, "client_code": 1, "payment_confirmation_template": 1,
         "contract_currency": 1,
         # 2026-02 fork iter108 fix — Required by S159 auto-reactivation branch below.
         "account_status": 1},
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    pdate = (payload.payment_date or "").strip()
    if not pdate:
        raise HTTPException(status_code=400, detail="`payment_date` requise (YYYY-MM-DD)")
    try:
        datetime.strptime(pdate[:10], "%Y-%m-%d")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Format `payment_date` invalide (YYYY-MM-DD attendu) — {exc}") from exc
    amount = float(payload.amount_paid or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="`amount_paid` doit être > 0")
    doc = {
        "id": _uuid(),
        "tenant_id": client_id,
        "payment_date": pdate[:10],
        "invoice_ref": (payload.invoice_ref or "").strip() or None,
        "amount_due": float(payload.amount_due) if payload.amount_due is not None else None,
        "amount_paid": amount,
        "payment_method_id": (payload.payment_method_id or "").strip() or None,
        "payment_method_label": (payload.payment_method_label or "").strip() or None,
        "notes": (payload.notes or "").strip() or None,
        "created_by_id": admin_user.get("id"),
        "created_by_email": admin_user.get("email"),
        "created_at": _now(),
    }
    await db.tenant_payments.insert_one(doc.copy())
    try:
        # 2026-02 fork iter108 — S159 : Auto-reactivate on payment.
        # When a payment is registered on a `suspended` account (because the
        # overdue cron auto-suspended it), we lift the suspension so the
        # tenant can log in again immediately.
        update_fields: Dict[str, Any] = {"last_payment_at": pdate[:10], "updated_at": _now()}
        if (client.get("account_status") or "").lower() == "suspended":
            update_fields["account_status"] = "active"
            update_fields["suspended_at"] = None
            update_fields["suspended_reason"] = None
            update_fields["reactivated_at"] = _now()
            update_fields["reactivated_reason"] = "Paiement reçu — auto-réactivation"
            logger.info("[payment] auto-reactivated suspended tenant %s after payment", client.get("email"))
        await db.users.update_one(
            {"id": client_id},
            {"$set": update_fields},
        )
    except Exception:  # noqa: BLE001
        pass
    wa_result: Optional[dict] = None
    if payload.send_confirmation is not False:
        tpl_name = (client.get("payment_confirmation_template") or "").strip() or "confirmation_paiement_avecrecu"
        to_phone = (client.get("phone") or "").strip() or (client.get("whatsapp_number") or "").strip()
        if to_phone:
            base_ctx = _build_recipient_ctx(
                "client", client, to_phone,
                client.get("company") or client.get("full_name") or client.get("email"),
            )
            currency = (client.get("contract_currency") or "XOF").upper()
            try:
                amt_fmt = f"{amount:,.0f}".replace(",", " ")
            except Exception:  # noqa: BLE001
                amt_fmt = str(amount)
            base_ctx["amount_paid"] = f"{amt_fmt} {currency}"
            base_ctx["payment_date"] = pdate[:10]
            base_ctx["invoice_ref"] = doc.get("invoice_ref") or "—"
            base_ctx["payment_method"] = doc.get("payment_method_label") or "—"
            variables = [
                "{{full_name}}", "{{amount_paid}}", "{{payment_date}}",
                "{{invoice_ref}}", "{{payment_method}}",
            ]
            components = _build_components(variables, base_ctx)
            try:
                wr = await _wa_send_template(to_phone, tpl_name, "fr", components)
            except Exception as exc:  # noqa: BLE001
                wr = {"ok": False, "error": str(exc)[:200]}
            wa_result = {
                "ok": bool(wr.get("ok")),
                "template": tpl_name,
                "to": to_phone,
                "error": wr.get("error"),
            }
            try:
                await db.whatsapp_messages.insert_one({
                    "id": _uuid(),
                    "client_id": client_id,
                    "to": to_phone,
                    "template_name": tpl_name,
                    "language_code": "fr",
                    "ok": bool(wr.get("ok")),
                    "status": wr.get("status"),
                    "message_id": wr.get("message_id"),
                    "error": wr.get("error"),
                    "context": "tenant_payment",
                    "payment_id": doc["id"],
                    "created_at": _now(),
                })
            except Exception:  # noqa: BLE001
                pass
        else:
            wa_result = {"ok": False, "error": "Aucun numéro (phone/whatsapp_number) sur le client"}
    doc["wa_confirmation"] = wa_result
    return doc


@api.delete("/admin/clients/{client_id}/payments/{payment_id}", tags=["Admin"])
async def admin_delete_client_payment(
    client_id: str,
    payment_id: str,
    _: dict = Depends(get_current_admin),
):
    res = await db.tenant_payments.delete_one({"id": payment_id, "tenant_id": client_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    try:
        latest = await db.tenant_payments.find_one(
            {"tenant_id": client_id},
            {"_id": 0, "payment_date": 1},
            sort=[("payment_date", -1)],
        )
        await db.users.update_one(
            {"id": client_id},
            {"$set": {"last_payment_at": (latest or {}).get("payment_date") or None, "updated_at": _now()}},
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "deleted": res.deleted_count}



# ----- Notes -----
@api.get("/admin/clients/{client_id}/notes", tags=["Admin"])
async def admin_list_notes(client_id: str, _: dict = Depends(get_current_admin)):
    await _ensure_client_exists(client_id)
    return await db.client_notes.find({"client_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.post("/admin/clients/{client_id}/notes", tags=["Admin"])
async def admin_create_note(
    client_id: str, payload: ClientNoteCreate, admin_user: dict = Depends(get_current_admin)
):
    await _ensure_client_exists(client_id)
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Le texte de la note est requis")
    if len(text) > 5000:
        raise HTTPException(status_code=400, detail="Note trop longue (5000 caractères max)")
    doc = {
        "id": _uuid(),
        "client_id": client_id,
        "text": text,
        "voice_note_url": payload.voice_note_url or None,  # Iter35g
        "voice_note_transcript": payload.voice_note_transcript or None,  # Iter35g
        "author_id": admin_user["id"],
        "author_label": admin_user.get("full_name") or admin_user.get("email"),
        "created_at": _now(),
    }
    await db.client_notes.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.delete("/admin/clients/{client_id}/notes/{nid}", tags=["Admin"])
async def admin_delete_note(client_id: str, nid: str, _: dict = Depends(get_current_admin)):
    res = await db.client_notes.delete_one({"id": nid, "client_id": client_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Note introuvable")
    return {"ok": True}


# ----- Tasks -----
@api.get("/admin/clients/{client_id}/tasks", tags=["Admin"])
async def admin_list_tasks(client_id: str, _: dict = Depends(get_current_admin)):
    await _ensure_client_exists(client_id)
    return await db.client_tasks.find({"client_id": client_id}, {"_id": 0}).sort("due_at", 1).to_list(500)


@api.post("/admin/clients/{client_id}/tasks", tags=["Admin"])
async def admin_create_task(
    client_id: str, payload: ClientTaskCreate, admin_user: dict = Depends(get_current_admin)
):
    await _ensure_client_exists(client_id)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre de la tâche requis")
    due_iso: Optional[str] = None
    if payload.due_at:
        try:
            d = datetime.fromisoformat(payload.due_at.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            due_iso = d.isoformat()
        except Exception:
            raise HTTPException(status_code=400, detail="Date d'échéance invalide")
    doc = {
        "id": _uuid(),
        "client_id": client_id,
        "title": title,
        "description": (payload.description or "").strip() or None,
        "due_at": due_iso,
        "status": "open",
        "remind_via_whatsapp": bool(payload.remind_via_whatsapp),
        "voice_note_url": payload.voice_note_url or None,  # Iter35g
        "voice_note_transcript": payload.voice_note_transcript or None,  # Iter35g
        "reminder_sent_at": None,
        "author_id": admin_user["id"],
        "author_label": admin_user.get("full_name") or admin_user.get("email"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.client_tasks.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/clients/{client_id}/tasks/{tid}", tags=["Admin"])
async def admin_update_task(
    client_id: str, tid: str, payload: ClientTaskUpdate, _: dict = Depends(get_current_admin)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "status" in update and update["status"] not in ("open", "done"):
        raise HTTPException(status_code=400, detail="Statut invalide (open|done)")
    if "due_at" in update and update["due_at"]:
        try:
            d = datetime.fromisoformat(update["due_at"].replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            update["due_at"] = d.isoformat()
        except Exception:
            raise HTTPException(status_code=400, detail="Date d'échéance invalide")
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    res = await db.client_tasks.update_one({"id": tid, "client_id": client_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    refreshed = await db.client_tasks.find_one({"id": tid, "client_id": client_id}, {"_id": 0})
    return refreshed


@api.delete("/admin/clients/{client_id}/tasks/{tid}", tags=["Admin"])
async def admin_delete_task(client_id: str, tid: str, _: dict = Depends(get_current_admin)):
    res = await db.client_tasks.delete_one({"id": tid, "client_id": client_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return {"ok": True}


async def _task_reminder_cron():
    """Hourly cron: tasks with remind_via_whatsapp=true + due in [now, now+1h] + not yet reminded.
    Emits a 'task.reminder' event so admins can hook a WhatsApp template via /admin/automations.

    2026-02 fork (P3b) — Also prunes wa_reply_tokens older than 30 minutes
    (best-effort) so the collection stays small even without a TTL index (our
    docs store `created_at` as ISO strings, which TTL cannot use directly).
    """
    now_utc = datetime.now(timezone.utc)
    win_end = (now_utc + timedelta(hours=1)).isoformat()
    # Prune expired reply-router tokens (older than 30 min, used OR not).
    try:
        cutoff = (now_utc - timedelta(minutes=30)).isoformat()
        res = await db.wa_reply_tokens.delete_many({"created_at": {"$lt": cutoff}})
        if res.deleted_count:
            logger.info("[wa_reply_tokens prune] removed %d expired tokens", res.deleted_count)
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[wa_reply_tokens prune] failed: %s", _exc)
    tasks = await db.client_tasks.find(
        {
            "remind_via_whatsapp": True,
            "status": "open",
            "due_at": {"$gte": now_utc.isoformat(), "$lte": win_end},
            "reminder_sent_at": None,
        },
        {"_id": 0},
    ).to_list(200)
    for t in tasks:
        try:
            await _emit_event("task.reminder", {
                "client_id": t.get("client_id"),
                "extra_ctx": {
                    "task_title": t.get("title") or "",
                    "task_due": t.get("due_at") or "",
                },
            })
        except Exception:
            pass
        try:
            await db.client_tasks.update_one(
                {"id": t["id"]},
                {"$set": {"reminder_sent_at": _now()}},
            )
        except Exception:
            pass


@api.put("/admin/clients/{client_id}", tags=["Admin"])
async def admin_update_client(
    client_id: str, payload: UserUpdateAdmin, _: dict = Depends(get_admin_or_supervisor)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None and k != "password"}
    if "client_code" in update:
        update["client_code"] = (update["client_code"] or "").strip().upper() or None
    # S-iter39a — Handle "client lié" (parent_client_id) update via dropdown.
    # Must run BEFORE the company-auto-realign block so an explicit admin
    # choice takes precedence. We use model_fields_set to distinguish
    # "not provided" from "explicitly cleared (empty string)".
    if "link_to_client_id" in payload.model_fields_set:
        raw_link = (payload.link_to_client_id or "").strip()
        update.pop("link_to_client_id", None)
        if raw_link:
            if raw_link == client_id:
                raise HTTPException(status_code=400, detail="Un compte ne peut pas être lié à lui-même")
            canon = await db.users.find_one(
                # Lot 25 — Les deux orthographes du rôle modérateur sont acceptées.
                {"id": raw_link, "role": {"$in": ["admin", "superviseur", "moderateur", "moderator", "client"]}},
                {"_id": 0, "id": 1},
            )
            if not canon:
                raise HTTPException(status_code=404, detail="Client canonique introuvable")
            update["parent_client_id"] = canon["id"]
            update["client_id"] = canon["id"]
        else:
            # Empty string → unlink (back to standalone tenant)
            update["parent_client_id"] = None
            update["client_id"] = None
    # Iter35f — handle email updates safely (normalize + uniqueness check).
    # Prior to iter35f, the `email` field was missing from UserUpdateAdmin
    # so the admin UI silently dropped any change. Now we normalize to
    # lowercase + strip whitespace, then make sure no other account holds
    # the same email before writing.
    if "email" in update:
        new_email = (update["email"] or "").strip().lower()
        if not new_email or "@" not in new_email:
            raise HTTPException(status_code=400, detail="Adresse email invalide")
        update["email"] = new_email
        clash = await db.users.find_one(
            {"email": new_email, "id": {"$ne": client_id}},
            {"_id": 0, "id": 1, "email": 1},
        )
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"L'email {new_email} est déjà utilisé par un autre compte",
            )
    if payload.password:
        update["password_hash"] = hash_password(payload.password)
    update["updated_at"] = _now()

    # Iter34n — Auto-guard: when admin changes the `company` text, the user's
    # parent_client_id might still anchor to a stale company (the rabo.f
    # bug fixed in iter34m). Detect the mismatch BEFORE writing the update
    # and try to auto-realign so the UI stays internally consistent
    # without forcing the admin to run the diagnostic manually.
    auto_realign: Optional[Dict[str, Any]] = None
    if "company" in update:
        before = await db.users.find_one(
            {"id": client_id},
            {"_id": 0, "id": 1, "email": 1, "company": 1, "role": 1},
        )
        if before:
            new_company = (update.get("company") or "").strip()
            old_company = (before.get("company") or "").strip()
            company_changed = new_company.lower() != old_company.lower()
            if company_changed and new_company and before.get("role") not in ("admin",):
                # Apply the user update first, then trigger the same logic
                # the diagnostic uses. We reuse the existing endpoint as a
                # function call so behaviour stays in sync.
                await db.users.update_one({"id": client_id}, {"$set": update})
                try:
                    diag = await admin_client_data_diagnostic(
                        email=before.get("email") or "", _={"role": "admin"}
                    )
                    plan = diag.get("realign_plan") or {}
                    if plan.get("needed") and diag.get("parent_company_mismatch"):
                        # Auto-apply silently. Same rules as the manual
                        # /admin/realign-user-to-client endpoint.
                        for action in plan["actions"]:
                            if action["type"] == "relink_parent":
                                await db.users.update_one(
                                    {"id": action["user_id"]},
                                    {"$set": {
                                        "parent_client_id": action["to_parent"],
                                        "parent_client_id_legacy": action.get("from_parent"),
                                        "client_id": action["to_parent"],
                                        "updated_at": _now(),
                                    }},
                                )
                            elif action["type"] == "set_user_client_id":
                                await db.users.update_one(
                                    {"id": action["user_id"]},
                                    {"$set": {
                                        "client_id": action["to"],
                                        "client_id_legacy": action.get("from"),
                                        "updated_at": _now(),
                                    }},
                                )
                            elif action["type"] == "retag_rows":
                                # Iter34o — owner-scoped retag.
                                owner_uid = action.get("owner_uid")
                                base_q: Dict[str, Any] = {"client_id": action["from"], "client_id_legacy": {"$exists": False}}
                                if owner_uid:
                                    base_q["$or"] = [
                                        {"owner_id": owner_uid},
                                        {"sender_id": owner_uid},
                                        {"created_by": owner_uid},
                                        {"author_id": owner_uid},
                                        {"user_id": owner_uid},
                                    ]
                                await db[action["collection"]].update_many(
                                    base_q,
                                    {"$set": {"client_id": action["to"], "client_id_legacy": action["from"]}},
                                )
                        auto_realign = {
                            "applied": True,
                            "to_company": (diag.get("canonical") or {}).get("user", {}).get("company") if diag.get("canonical") else None,
                            "to_canonical_id": (diag.get("canonical") or {}).get("client_id"),
                            "actions_count": len(plan["actions"]),
                        }
                    elif diag.get("parent_company_mismatch"):
                        # Mismatch detected but no canonical resolvable
                        # (e.g. typo in company name, or no admin/primary
                        # carries that exact name). Surface it instead of
                        # silently leaving the user broken.
                        auto_realign = {
                            "applied": False,
                            "reason": "no_canonical_for_company",
                            "typed_company": new_company,
                        }
                except Exception:
                    pass
                return {"ok": True, "auto_realign": auto_realign}
    await db.users.update_one({"id": client_id}, {"$set": update})
    return {"ok": True, "auto_realign": auto_realign}


@api.delete("/admin/clients/{client_id}", tags=["Admin"])
async def admin_delete_client(client_id: str, _: dict = Depends(get_current_admin)):
    await db.users.delete_one({"id": client_id, "role": {"$in": ["client", "superviseur"]}})
    return {"ok": True}


@api.post("/admin/clients/{client_id}/set-primary", tags=["Admin"])
async def admin_set_primary_client(client_id: str, _: dict = Depends(get_current_admin)):
    """Designate ONE client as the primary site owner.
    The primary client is automatically promoted to role=superviseur.
    Any previous primary is unmarked and demoted back to role=client (unless admin).
    """
    target = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    if target.get("role") == "admin":
        raise HTTPException(status_code=400, detail="Un compte admin SAWALI ne peut pas être désigné comme client primaire")

    # Demote previous primary(ies)
    previous_primaries = await db.users.find({"is_primary_client": True}, {"_id": 0}).to_list(50)
    for prev in previous_primaries:
        if prev["id"] == client_id:
            continue
        # Restore previous role if known, default to "client"
        new_role = "client" if prev.get("role") == "superviseur" else prev.get("role", "client")
        await db.users.update_one(
            {"id": prev["id"]},
            {"$set": {"is_primary_client": False, "role": new_role, "updated_at": _now()}},
        )

    await db.users.update_one(
        {"id": client_id},
        {"$set": {"is_primary_client": True, "role": "superviseur", "updated_at": _now()}},
    )
    return {"ok": True, "id": client_id, "role": "superviseur", "is_primary_client": True}


@api.post("/admin/clients/{client_id}/unset-primary", tags=["Admin"])
async def admin_unset_primary_client(client_id: str, _: dict = Depends(get_current_admin)):
    target = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    await db.users.update_one(
        {"id": client_id},
        {"$set": {"is_primary_client": False, "role": "client", "updated_at": _now()}},
    )
    return {"ok": True, "id": client_id}


# ====================================================================
# ADMIN - Appointments
# ====================================================================
@api.get("/admin/appointments", tags=["Admin"])
async def admin_appointments(user: dict = Depends(get_current_admin)):
    """Iter43-fix24az-l retest — Cross-tenant leak fix. Only SAWALI super-admin
    sees ALL appointments across tenants ; client-admin/superviseur roles are
    scoped to their own tenant via `_resolve_visible_client_ids`.
    """
    if _is_super_admin(user):
        query: Dict[str, Any] = {}
    else:
        scope = await _resolve_visible_client_ids(user)
        query = {"client_id": {"$in": scope}}
    items = await db.appointments.find(query, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x.get("scheduled_at") or "", reverse=True)


@api.put("/admin/appointments/{appt_id}", tags=["Admin"])
async def admin_update_appt(
    appt_id: str, payload: AppointmentUpdate, _: dict = Depends(get_current_admin)
):
    existing = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    # Auto-generate feedback token when status becomes "completed"
    if update.get("status") == "completed":
        if not existing.get("feedback_token"):
            update["feedback_token"] = generate_session_token()
            update["feedback_status"] = "pending"
    await db.appointments.update_one({"id": appt_id}, {"$set": update})
    # Sync GCal if the slot changed
    if existing.get("gcal_event_id") and ("scheduled_at" in update or "duration_min" in update or "subject" in update or "message" in update):
        try:
            new_sched = update.get("scheduled_at") or existing.get("scheduled_at")
            new_dur = update.get("duration_min") or existing.get("duration_min") or 30
            new_end = (datetime.fromisoformat(new_sched).replace(tzinfo=timezone.utc) + timedelta(minutes=new_dur)).isoformat()
            await gcal.update_event(
                event_id=existing["gcal_event_id"],
                summary=f"RDV client : {update.get('subject') or existing.get('subject')}",
                description=f"Client : {existing.get('name')} <{existing.get('email')}>\n{update.get('message') or existing.get('message') or ''}",
                start_iso=new_sched,
                end_iso=new_end,
            )
        except Exception as exc:
            logger.warning("GCal update failed: %s", exc)
    return {"ok": True}


@api.delete("/admin/appointments/{appt_id}", tags=["Admin"])
async def admin_delete_appt(appt_id: str, _: dict = Depends(get_current_admin)):
    await db.appointments.delete_one({"id": appt_id})
    return {"ok": True}


# ====================================================================
# ADMIN - Interventions
# ====================================================================
@api.get("/admin/interventions", tags=["Admin"])
async def admin_interventions(user: dict = Depends(get_current_admin)):
    """Iter43-fix24az-l retest — Cross-tenant leak fix. Only SAWALI super-admin
    sees ALL interventions ; client-admin/superviseur scoped to their tenant.
    """
    if _is_super_admin(user):
        query: Dict[str, Any] = {}
    else:
        scope = await _resolve_visible_client_ids(user)
        query = {"client_id": {"$in": scope}}
    items = await db.interventions.find(query, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x.get("intervention_date", ""), reverse=True)


@api.post("/admin/interventions", tags=["Admin"])
async def admin_create_intervention(
    request: Request,
    payload: InterventionCreate,
    user: dict = Depends(get_current_admin),
):
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
        "owner_role": user.get("role"),
        "ip": _client_ip_from_request(request),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.interventions.insert_one(doc.copy())
    doc.pop("_id", None)
    webhook_result = await _fire_intervention_webhook("created", doc)
    doc["webhook_result"] = webhook_result
    # Fire automation: intervention.created (admin)
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


@api.put("/admin/interventions/{int_id}", tags=["Admin"])
async def admin_update_intervention(
    int_id: str, payload: InterventionUpdate, _: dict = Depends(get_admin_or_supervisor)
):
    # Iter43-fix4 (2026-03) — Verrou facturation
    existing = await db.interventions.find_one({"id": int_id}, {"_id": 0, "invoiced": 1, "invoice_number": 1})
    if existing and existing.get("invoiced"):
        raise HTTPException(
            status_code=409,
            detail=f"Intervention déjà facturée ({existing.get('invoice_number') or '—'}). Utilisez /admin/interventions/{int_id}/unlock-invoice avant de modifier.",
        )
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await db.interventions.update_one({"id": int_id}, {"$set": update})
    doc = await db.interventions.find_one({"id": int_id}, {"_id": 0})
    webhook_result = None
    if doc:
        webhook_result = await _fire_intervention_webhook("updated", doc)
    return {"ok": True, "webhook_result": webhook_result}


@api.post("/admin/interventions/{int_id}/unlock-invoice", tags=["Admin"])
async def admin_unlock_intervention(int_id: str, user: dict = Depends(get_admin_or_supervisor)):
    """Iter43-fix4 — Force unlock d'une intervention facturée (admin OU superviseur).
    NB : la facture associée n'est pas modifiée. Si elle doit être annulée,
    voir /admin/invoices/{invoice_id}/cancel."""
    res = await db.interventions.update_one(
        {"id": int_id},
        {
            "$set": {"updated_at": _now(), "unlocked_at": _now(), "unlocked_by": user.get("email")},
            "$unset": {"invoiced": "", "invoice_id": "", "invoice_number": ""},
        },
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    return {"ok": True}


@api.delete("/admin/interventions/{int_id}", tags=["Admin"])
async def admin_delete_intervention(int_id: str, _: dict = Depends(get_current_admin)):
    await db.interventions.delete_one({"id": int_id})
    return {"ok": True}


# ====================================================================
# ADMIN - Documents (catalog, software docs, announcements)
# ====================================================================
@api.get("/admin/documents", tags=["Admin"])
async def admin_documents(user: dict = Depends(get_current_admin)):
    """Iter43-fix24az-l retest — Cross-tenant leak fix. Super-admin sees ALL
    documents (including per-tenant private ones) ; client-admin sees only the
    documents owned by their tenant PLUS public/shared documents
    (client_id is None or empty, or is_public=True).
    """
    if _is_super_admin(user):
        query: Dict[str, Any] = {}
    else:
        scope = await _resolve_visible_client_ids(user)
        query = {
            "$or": [
                {"client_id": {"$in": scope}},
                {"client_id": {"$in": [None, ""]}},
                {"is_public": True},
            ]
        }
    items = await db.documents.find(query, {"_id": 0}).to_list(5000)
    return items


@api.post("/admin/documents", tags=["Admin"])
async def admin_create_document(payload: DocumentCreate, _: dict = Depends(get_current_admin)):
    doc = {"id": _uuid(), **payload.model_dump(), "created_at": _now()}
    await db.documents.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/documents/{doc_id}", tags=["Admin"])
async def admin_update_document(
    doc_id: str, payload: DocumentUpdate, _: dict = Depends(get_current_admin)
):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = _now()
    await db.documents.update_one({"id": doc_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/documents/{doc_id}", tags=["Admin"])
async def admin_delete_document(doc_id: str, _: dict = Depends(get_current_admin)):
    await db.documents.delete_one({"id": doc_id})
    return {"ok": True}


# ---- Document categories CRUD ----
DEFAULT_DOC_CATEGORIES = [
    {"label": "Catalogue", "slug": "catalog", "is_default": True, "icon": "BookOpen", "color": "#1E90FF"},
    {"label": "Documentation", "slug": "documentation", "is_default": True, "icon": "FileText", "color": "#0EA5E9"},
    {"label": "Annonce", "slug": "announcement", "is_default": True, "icon": "Megaphone", "color": "#F59E0B"},
]


async def _ensure_default_categories():
    for c in DEFAULT_DOC_CATEGORIES:
        existing = await db.document_categories.find_one({"slug": c["slug"]})
        if not existing:
            await db.document_categories.insert_one({
                "id": _uuid(),
                "label": c["label"],
                "slug": c["slug"],
                "description": None,
                "icon": c.get("icon"),
                "color": c.get("color"),
                "is_default": True,
                "created_at": _now(),
                "updated_at": _now(),
            })
        elif not existing.get("icon"):
            await db.document_categories.update_one(
                {"slug": c["slug"]},
                {"$set": {"icon": c.get("icon"), "color": c.get("color"), "updated_at": _now()}},
            )


@api.get("/admin/document-categories", tags=["Admin"])
async def admin_list_doc_categories(_: dict = Depends(get_current_admin)):
    await _ensure_default_categories()
    items = await db.document_categories.find({}, {"_id": 0}).sort("label", 1).to_list(500)
    return items


@api.post("/admin/document-categories", tags=["Admin"])
async def admin_create_doc_category(payload: DocumentCategoryCreate, _: dict = Depends(get_current_admin)):
    label = (payload.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Libellé requis")
    slug = (payload.slug or _category_slug(label)).strip().lower()
    if await db.document_categories.find_one({"slug": slug}):
        raise HTTPException(status_code=409, detail="Slug déjà utilisé")
    doc = {
        "id": _uuid(),
        "label": label,
        "slug": slug,
        "description": payload.description,
        "icon": payload.icon,
        "color": payload.color,
        "is_default": bool(payload.is_default),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.document_categories.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/document-categories/{cat_id}", tags=["Admin"])
async def admin_update_doc_category(cat_id: str, payload: DocumentCategoryUpdate, _: dict = Depends(get_current_admin)):
    existing = await db.document_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "slug" in update:
        update["slug"] = update["slug"].strip().lower()
        if update["slug"] != existing["slug"]:
            dup = await db.document_categories.find_one({"slug": update["slug"]})
            if dup:
                raise HTTPException(status_code=409, detail="Slug déjà utilisé")
            # propagate slug renaming on existing documents
            await db.documents.update_many(
                {"category": existing["slug"]},
                {"$set": {"category": update["slug"], "updated_at": _now()}},
            )
    update["updated_at"] = _now()
    await db.document_categories.update_one({"id": cat_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/document-categories/{cat_id}", tags=["Admin"])
async def admin_delete_doc_category(cat_id: str, _: dict = Depends(get_current_admin)):
    existing = await db.document_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        return {"ok": True}
    if existing.get("is_default"):
        raise HTTPException(status_code=400, detail="Impossible de supprimer une catégorie par défaut")
    used = await db.documents.count_documents({"category": existing["slug"]})
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"Catégorie utilisée par {used} document(s). Réaffectez-les avant suppression.",
        )
    await db.document_categories.delete_one({"id": cat_id})
    return {"ok": True}


# ---- Public list of categories (for client portal & public site) ----
@api.get("/document-categories", tags=["Public"])
async def public_doc_categories():
    await _ensure_default_categories()
    items = await db.document_categories.find({}, {"_id": 0}).sort("label", 1).to_list(500)
    return items


# ====================================================================
# CLIENT CATEGORIES (clinique, pharmacie, commerce, etc.)
# ====================================================================
DEFAULT_CLIENT_CATEGORIES = [
    {"label": "Clinique", "slug": "clinique", "icon": "Cross", "color": "#EF4444"},
    {"label": "Pharmacie", "slug": "pharmacie", "icon": "Pill", "color": "#10B981"},
    {"label": "Commerce", "slug": "commerce", "icon": "Store", "color": "#3B82F6"},
    {"label": "Alimentation", "slug": "alimentation", "icon": "UtensilsCrossed", "color": "#F59E0B"},
    {"label": "Industrie", "slug": "industrie", "icon": "Factory", "color": "#6B7280"},
    {"label": "Éducation", "slug": "education", "icon": "GraduationCap", "color": "#8B5CF6"},
    {"label": "Bureautique", "slug": "bureautique", "icon": "Briefcase", "color": "#0EA5E9"},
    {"label": "Autre", "slug": "autre", "icon": "Building2", "color": "#94A3B8"},
]


async def _ensure_default_client_categories():
    for c in DEFAULT_CLIENT_CATEGORIES:
        existing = await db.client_categories.find_one({"slug": c["slug"]})
        if not existing:
            await db.client_categories.insert_one({
                "id": _uuid(),
                "label": c["label"],
                "slug": c["slug"],
                "icon": c["icon"],
                "color": c["color"],
                "is_default": True,
                "created_at": _now(),
                "updated_at": _now(),
            })


@api.get("/admin/client-categories", tags=["Admin"])
async def admin_list_client_categories(_: dict = Depends(get_current_admin)):
    await _ensure_default_client_categories()
    items = await db.client_categories.find({}, {"_id": 0}).sort("label", 1).to_list(500)
    return items


@api.post("/admin/client-categories", tags=["Admin"])
async def admin_create_client_category(payload: ClientCategoryCreate, _: dict = Depends(get_current_admin)):
    label = (payload.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Libellé requis")
    slug = (payload.slug or _category_slug(label)).strip().lower()
    if await db.client_categories.find_one({"slug": slug}):
        raise HTTPException(status_code=409, detail="Slug déjà utilisé")
    doc = {
        "id": _uuid(),
        "label": label,
        "slug": slug,
        "icon": payload.icon,
        "color": payload.color,
        "is_default": bool(payload.is_default),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.client_categories.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/client-categories/{cat_id}", tags=["Admin"])
async def admin_update_client_category(cat_id: str, payload: ClientCategoryUpdate, _: dict = Depends(get_current_admin)):
    existing = await db.client_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "slug" in update:
        update["slug"] = update["slug"].strip().lower()
        if update["slug"] != existing["slug"]:
            dup = await db.client_categories.find_one({"slug": update["slug"]})
            if dup:
                raise HTTPException(status_code=409, detail="Slug déjà utilisé")
            await db.users.update_many(
                {"category_slug": existing["slug"]},
                {"$set": {"category_slug": update["slug"], "updated_at": _now()}},
            )
    update["updated_at"] = _now()
    await db.client_categories.update_one({"id": cat_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/client-categories/{cat_id}", tags=["Admin"])
async def admin_delete_client_category(cat_id: str, _: dict = Depends(get_current_admin)):
    existing = await db.client_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        return {"ok": True}
    if existing.get("is_default"):
        raise HTTPException(status_code=400, detail="Impossible de supprimer une catégorie par défaut")
    used = await db.users.count_documents({"category_slug": existing["slug"]})
    if used:
        raise HTTPException(status_code=400, detail=f"Catégorie utilisée par {used} client(s).")
    await db.client_categories.delete_one({"id": cat_id})
    return {"ok": True}


@api.get("/client-categories", tags=["Public"])
async def public_client_categories():
    await _ensure_default_client_categories()
    items = await db.client_categories.find({}, {"_id": 0}).sort("label", 1).to_list(500)
    return items


# ====================================================================
# DEPLOYMENTS — software installations by country/city
# Composite key: (solution_name lower, country lower)
# ====================================================================
def _deployment_key(solution: str, country: str) -> str:
    return f"{(solution or '').strip().lower()}|{(country or '').strip().lower()}"


@api.get("/admin/deployments", tags=["Admin"])
async def admin_list_deployments(_: dict = Depends(get_current_admin)):
    items = await db.deployments.find({}, {"_id": 0}).sort([("country", 1), ("solution_name", 1)]).to_list(2000)
    return items


@api.post("/admin/deployments", tags=["Admin"])
async def admin_create_deployment(payload: DeploymentCreate, _: dict = Depends(get_current_admin)):
    if not payload.solution_name.strip() or not payload.country.strip():
        raise HTTPException(status_code=400, detail="Solution et pays requis")
    key = _deployment_key(payload.solution_name, payload.country)
    if await db.deployments.find_one({"key": key}):
        raise HTTPException(status_code=409, detail="Cette solution existe déjà pour ce pays — modifiez l'entrée existante")
    doc = {
        "id": _uuid(),
        "key": key,
        "solution_name": payload.solution_name.strip(),
        "country": payload.country.strip(),
        "city": (payload.city or "").strip() or None,
        "installations": max(0, int(payload.installations or 0)),
        "notes": payload.notes,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.deployments.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/deployments/{dep_id}", tags=["Admin"])
async def admin_update_deployment(dep_id: str, payload: DeploymentUpdate, _: dict = Depends(get_current_admin)):
    existing = await db.deployments.find_one({"id": dep_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Déploiement introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "solution_name" in update or "country" in update:
        new_solution = update.get("solution_name", existing["solution_name"])
        new_country = update.get("country", existing["country"])
        new_key = _deployment_key(new_solution, new_country)
        if new_key != existing.get("key"):
            dup = await db.deployments.find_one({"key": new_key})
            if dup and dup.get("id") != dep_id:
                raise HTTPException(status_code=409, detail="Couple (solution, pays) déjà existant")
            update["key"] = new_key
    if "installations" in update:
        update["installations"] = max(0, int(update["installations"]))
    update["updated_at"] = _now()
    await db.deployments.update_one({"id": dep_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/deployments/{dep_id}", tags=["Admin"])
async def admin_delete_deployment(dep_id: str, _: dict = Depends(get_current_admin)):
    await db.deployments.delete_one({"id": dep_id})
    return {"ok": True}


@api.get("/deployments", tags=["Public"])
async def public_deployments():
    """Liste publique, groupée par pays, avec toutes les solutions et le total d'installations.
    Returns: [{country, total_installations, solutions: [{name, installations, city, created_at, updated_at}]}]
    """
    items = await db.deployments.find({}, {"_id": 0}).to_list(2000)
    grouped: dict = {}
    for d in items:
        c = (d.get("country") or "").strip()
        if not c:
            continue
        if c not in grouped:
            grouped[c] = {"country": c, "total_installations": 0, "solutions": []}
        grouped[c]["solutions"].append({
            "name": d.get("solution_name"),
            "installations": int(d.get("installations") or 0),
            "city": d.get("city"),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
        })
        grouped[c]["total_installations"] += int(d.get("installations") or 0)
    out = list(grouped.values())
    out.sort(key=lambda x: x["total_installations"], reverse=True)
    return out


# ====================================================================
# ADMIN - File upload
# ====================================================================
@api.post("/admin/upload", tags=["Admin"])
async def admin_upload(request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_admin)):
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = f"{file_id}{suffix}"
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    # 2026-02 fork iter108 — Deploy-safe upload helper (storage-first, local cache).
    from storage import asave_upload_and_cache  # lot 26 : dans un thread, sans figer le serveur
    data = file.file.read()
    size = len(data)
    target, storage_path, storage_error = await asave_upload_and_cache(
        upload_dir=UPLOAD_DIR, filename=safe_name, data=data, content_type=content_type,
    )
    if storage_error:
        logger.warning("[admin_upload] storage mirror failed: %s", storage_error)
    file_doc = {
        "id": file_id,
        "filename": file.filename,
        "stored_name": safe_name,
        "extension": suffix.lstrip(".") if suffix else None,
        "content_type": file.content_type or mimetypes.guess_type(file.filename or "")[0],
        "size": size,
        "url": f"/api/files/{file_id}",
        "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"),
        "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
        # Iter35q — remote storage pointer for persistence across redeploys
        "storage_path": storage_path,
        "storage_error": storage_error,
    }
    await db.files.insert_one(file_doc.copy())
    # Mirror into document_logs for centralized auditing
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
# Iter35q — Storage diagnostics & backfill (admin only).
#   - GET /admin/files/orphans      → list files whose disk binary is missing
#                                     AND not yet mirrored to Emergent storage.
#   - POST /admin/files/backfill    → for every file row that has disk binary
#                                     but no storage_path, push it to remote.
#                                     Returns {mirrored, skipped, errors}.
# ====================================================================
@api.get("/admin/files/orphans", tags=["Admin"])
async def admin_files_orphans(_: dict = Depends(get_current_admin)):
    """List file rows that are unrecoverable (disk gone + no remote copy)."""
    orphans: List[Dict[str, Any]] = []
    cursor = db.files.find({}, {"_id": 0, "id": 1, "filename": 1, "stored_name": 1, "size": 1, "uploaded_at": 1, "uploaded_by_email": 1, "storage_path": 1})
    async for f in cursor:
        on_disk = (UPLOAD_DIR / (f.get("stored_name") or "")).exists() if f.get("stored_name") else False
        in_remote = bool(f.get("storage_path"))
        if not on_disk and not in_remote:
            orphans.append({
                "id": f["id"],
                "filename": f.get("filename"),
                "size": f.get("size"),
                "uploaded_at": f.get("uploaded_at"),
                "uploaded_by_email": f.get("uploaded_by_email"),
            })
    return {"count": len(orphans), "items": orphans}


@api.post("/admin/files/backfill", tags=["Admin"])
async def admin_files_backfill(_: dict = Depends(get_current_admin)):
    """For every file row that has its binary on disk but no `storage_path`,
    push it to Emergent storage and update the DB row. Best-effort."""
    from storage import aupload_bytes, astorage_available  # lot 26 : non bloquant
    if not await astorage_available():
        raise HTTPException(status_code=503, detail="Stockage objet non disponible.")
    mirrored = 0
    skipped = 0
    errors: List[Dict[str, Any]] = []
    cursor = db.files.find({"storage_path": {"$in": [None, ""]}}, {"_id": 0, "id": 1, "stored_name": 1, "content_type": 1})
    async for f in cursor:
        try:
            target = UPLOAD_DIR / (f.get("stored_name") or "")
            if not target.exists():
                skipped += 1
                continue
            sp = await aupload_bytes(
                f"files/{f['stored_name']}", await asyncio.to_thread(target.read_bytes),
                f.get("content_type") or "application/octet-stream",
            )
            await db.files.update_one({"id": f["id"]}, {"$set": {"storage_path": sp}})
            mirrored += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": f["id"], "error": str(exc)[:200]})
    return {"mirrored": mirrored, "skipped_no_disk": skipped, "errors": errors}


# ====================================================================
# POLICIES — public legal documents (RGPD, services, suppression)
# Stored as files in POLICIES_DIR with a fixed slot name + metadata in DB.
# Public URL: /api/public/policies/{slot} (PDF inline) — shareable to Google,
# Facebook, partners, etc., without authentication.
# ====================================================================
POLICY_SLOTS = {
    "privacy": "Politique de confidentialité (RGPD)",
    "services": "Politique de services",
    "deletion": "Politique de suppression",
}
POLICY_MAX_SIZE = 15 * 1024 * 1024  # 15 MB


def _policy_public_url(request: Request, slot: str) -> str:
    base = _public_base_url(request) or (PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        scheme = request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        base = f"{scheme}://{host}"
    return f"{base}/api/public/policies/{slot}"


def _policy_path(slot: str) -> Path:
    return POLICIES_DIR / f"{slot}.pdf"


@api.get("/admin/policies", tags=["Admin"])
async def admin_list_policies(request: Request, _: dict = Depends(get_current_admin)):
    """Renvoie les 3 slots de politique fixes avec leurs métadonnées + URL de partage public."""
    items = []
    for slot, label in POLICY_SLOTS.items():
        meta = await db.policies.find_one({"slot": slot}, {"_id": 0})
        present = _policy_path(slot).exists()
        items.append({
            "slot": slot,
            "label": label,
            "present": present and bool(meta),
            "filename": (meta or {}).get("filename") if present else None,
            "size": (meta or {}).get("size") if present else None,
            "uploaded_at": (meta or {}).get("uploaded_at") if present else None,
            "uploaded_by_label": (meta or {}).get("uploaded_by_label") if present else None,
            "public_url": _policy_public_url(request, slot),
        })
    return {"items": items}


@api.post("/admin/policies/{slot}/upload", tags=["Admin"])
async def admin_upload_policy(
    slot: str,
    request: Request,
    file: UploadFile = File(...),
    admin_user: dict = Depends(get_current_admin),
):
    if slot not in POLICY_SLOTS:
        raise HTTPException(status_code=400, detail=f"Slot invalide. Valeurs : {sorted(POLICY_SLOTS)}")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pdf" and (file.content_type or "") != "application/pdf":
        raise HTTPException(status_code=400, detail="Format invalide : PDF requis")
    target = _policy_path(slot)
    # 2026-02 fork iter108 — Deploy-safe : read entirely into memory, size-check,
    # then persist via helper (object storage + local cache).
    raw = await file.read()
    size = len(raw)
    if size > POLICY_MAX_SIZE:
        raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {POLICY_MAX_SIZE // (1024*1024)} Mo)")
    if size == 0:
        raise HTTPException(status_code=400, detail="Fichier vide")
    from storage import asave_upload_and_cache  # lot 26 : dans un thread, sans figer le serveur
    await asave_upload_and_cache(
        upload_dir=target.parent, filename=target.name, data=raw,
        content_type="application/pdf", remote_prefix="policies",
    )
    doc = {
        "slot": slot,
        "label": POLICY_SLOTS[slot],
        "filename": file.filename or f"{slot}.pdf",
        "size": size,
        "uploaded_at": _now(),
        "uploaded_by_id": admin_user["id"],
        "uploaded_by_label": admin_user.get("full_name") or admin_user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
    }
    await db.policies.update_one({"slot": slot}, {"$set": doc}, upsert=True)
    return {
        "ok": True,
        **doc,
        "present": True,
        "public_url": _policy_public_url(request, slot),
    }


@api.delete("/admin/policies/{slot}", tags=["Admin"])
async def admin_delete_policy(slot: str, _: dict = Depends(get_current_admin)):
    if slot not in POLICY_SLOTS:
        raise HTTPException(status_code=400, detail=f"Slot invalide. Valeurs : {sorted(POLICY_SLOTS)}")
    p = _policy_path(slot)
    if p.exists():
        p.unlink()
    await db.policies.delete_one({"slot": slot})
    return {"ok": True, "slot": slot}


@api.api_route("/public/policies/{slot}", methods=["GET", "HEAD"], tags=["Public"])
async def public_policy(slot: str, request: Request):
    """Serve a policy PDF inline so 3rd parties (Google, Facebook…) can verify it.
    Both GET (renders the PDF) and HEAD (existence check used by the public
    /politiques/{slug} page to decide whether to show the iframe) are supported."""
    if slot not in POLICY_SLOTS:
        raise HTTPException(status_code=404, detail="Politique introuvable")
    p = _policy_path(slot)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Politique non publiée")
    meta = await db.policies.find_one({"slot": slot}, {"_id": 0})
    download_name = (meta or {}).get("filename") or f"{slot}.pdf"
    if request.method == "HEAD":
        # Mirror the GET headers so HEAD probes can verify existence + size without
        # reading the bytes — required by the iframe gate on the public page.
        return Response(
            status_code=200,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(p.stat().st_size),
                "Content-Disposition": _content_disposition("inline", download_name),
                "Cache-Control": "public, max-age=3600",
                "X-Robots-Tag": "all",
            },
        )
    return FileResponse(
        path=str(p),
        media_type="application/pdf",
        filename=download_name,
        headers={
            "Content-Disposition": _content_disposition("inline", download_name),
            "Cache-Control": "public, max-age=3600",
            "X-Robots-Tag": "all",
        },
    )


def _content_disposition(kind: str, name: str) -> str:
    """Lot 26 — en-tête Content-Disposition sûr pour tout nom de fichier.
    Un nom avec des caractères hors latin-1 (’, œ, €, emoji, arabe…) faisait
    échouer la réponse (erreur 500). On envoie un nom ASCII de secours ET le
    vrai nom encodé (RFC 6266 : filename*=UTF-8'')."""
    import unicodedata
    from urllib.parse import quote
    name = (name or "").replace('"', "").replace("\r", " ").replace("\n", " ").strip()
    if not name:
        return kind
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii") or "fichier"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"

@api.api_route("/files/{file_id}", methods=["GET", "HEAD"], tags=["Public"])
async def serve_file(request: Request, file_id: str):
    # Allow the URL to embed an extension hint (e.g. /api/files/abc-123.pdf) so external
    # consumers like Meta's WhatsApp Cloud API accept the link as a "valid document URL".
    # Also support HEAD requests because Meta probes the URL with HEAD before fetching.
    raw_id = file_id
    bare_id = file_id.split(".", 1)[0] if "." in file_id else file_id
    meta = await db.files.find_one({"id": bare_id}, {"_id": 0}) or await db.files.find_one({"id": raw_id}, {"_id": 0})
    if not meta:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    path = UPLOAD_DIR / meta["stored_name"]
    # Iter35q — When the local file is missing (ephemeral container after a redeploy),
    # try to rehydrate from Emergent Object Storage. The DB stays the source of truth.
    if not path.exists():
        rehydrated = False
        storage_path = meta.get("storage_path") or f"files/{meta['stored_name']}"
        try:
            from storage import arehydrate_from_storage  # lot 26 : dans un thread
            rehydrated = await arehydrate_from_storage(local_path=path, remote_path=storage_path)
            if rehydrated:
                logger.info("[serve_file] rehydrated %s from storage", file_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[serve_file] rehydrate failed for %s: %s", file_id, exc)
        if not rehydrated:
            raise HTTPException(status_code=404, detail="Fichier introuvable")
    # Try to identify the downloader via Authorization header (silent, optional)
    user_id = None
    user_email = None
    auth_header = request.headers.get("authorization") or ""
    if auth_header.startswith("Bearer "):
        try:
            from auth import decode_token  # local import to avoid cycle if any
            token_data = decode_token(auth_header.split(" ", 1)[1])
            if token_data and token_data.get("sub"):
                u = await db.users.find_one({"id": token_data["sub"]}, {"_id": 0, "password_hash": 0})
                if u:
                    user_id = u["id"]
                    user_email = u["email"]
        except Exception:  # noqa: BLE001
            pass
    started = datetime.now(timezone.utc)
    started_ts = started.timestamp()
    # HEAD probes (e.g. Meta validating the URL): return headers without body / log
    if request.method == "HEAD":
        return Response(
            status_code=200,
            headers={
                "Content-Type": meta.get("content_type") or "application/octet-stream",
                "Content-Length": str(meta.get("size") or path.stat().st_size),
                "Accept-Ranges": "bytes",
            },
        )
    # Iter38r-fix9z2 — Inline serving for images / videos / audio / PDFs.
    # FileResponse(filename=…) forces Content-Disposition: attachment which
    # makes browsers download instead of rendering. For media types we serve
    # them inline so <img>, <video> and <audio> work natively, including
    # byte-range streaming (Accept-Ranges).
    content_type = meta.get("content_type") or "application/octet-stream"
    # Fallback: legacy files saved as octet-stream — sniff from extension
    if content_type == "application/octet-stream":
        import mimetypes
        guessed, _ = mimetypes.guess_type(meta.get("filename") or meta.get("stored_name") or "")
        if guessed:
            content_type = guessed
    is_inline_media = (
        content_type.startswith(("image/", "video/", "audio/"))
        or content_type == "application/pdf"
    )
    # Iter38r-fix9z4 — Proper HTTP byte-range handling for <video>/<audio>.
    # FileResponse advertises Accept-Ranges but ignores the Range request
    # header (always returns 200 + full body). Chromium/Safari then reject
    # the playback with MEDIA_ERR_SRC_NOT_SUPPORTED. We honour ranges by
    # streaming the requested slice with HTTP 206 + Content-Range.
    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")
    safe_name = (meta.get("filename") or "").replace('"', "")
    inline_disposition = _content_disposition("inline", safe_name)  # lot 26 : tout nom de fichier
    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
    }
    if is_inline_media:
        common_headers["Content-Disposition"] = inline_disposition
    elif safe_name:
        common_headers["Content-Disposition"] = _content_disposition("attachment", safe_name)

    if range_header and range_header.startswith("bytes="):
        try:
            spec = range_header[len("bytes="):].split(",", 1)[0].strip()
            start_s, _, end_s = spec.partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
            if start < 0 or start >= file_size:
                raise ValueError("range out of bounds")
            end = min(end, file_size - 1)
            length = end - start + 1
        except (ValueError, TypeError):
            response = Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )
            return response

        async def _iter_range(p, s, l, chunk=64 * 1024):
            remaining = l
            with open(p, "rb") as f:
                f.seek(s)
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            **common_headers,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
        }
        response = StreamingResponse(
            _iter_range(path, start, length),
            status_code=206,
            media_type=content_type,
            headers=headers,
        )
    else:
        response = FileResponse(path, media_type=content_type)
        for k, v in common_headers.items():
            response.headers[k] = v
        response.headers["Content-Length"] = str(file_size)
    # Fire-and-forget log of the download (duration is approximate as we log before streaming)
    async def _log_download():
        try:
            await db.document_logs.insert_one({
                "id": _uuid(),
                "event_type": "download",
                "file_id": file_id,
                "filename": meta.get("filename"),
                "extension": meta.get("extension"),
                "size": meta.get("size"),
                "user_id": user_id,
                "user_email": user_email,
                "ip": _client_ip_from_request(request),
                "user_agent": request.headers.get("user-agent"),
                "duration_ms": int((datetime.now(timezone.utc).timestamp() - started_ts) * 1000),
                "created_at": _now(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("download log failed: %s", exc)
    asyncio.create_task(_log_download())
    return response


@api.get("/admin/document-logs", tags=["Admin"])
async def admin_document_logs(file_id: Optional[str] = None, _: dict = Depends(get_current_admin)):
    """Renvoie l'historique combiné upload + download. Admin uniquement."""
    query = {}
    if file_id:
        query["file_id"] = file_id
    items = await db.document_logs.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return items
