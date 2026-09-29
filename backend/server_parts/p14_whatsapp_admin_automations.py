# server_parts/p14_whatsapp_admin_automations.py — Messagerie WhatsApp groupée (admin), automatisations, envois WhatsApp planifiés.
# Morceau de l'ancien server.py (lignes 19344 à 20410), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# ADMIN — Messagerie WhatsApp groupée (clients + tracked users)
# ====================================================================
@api.get("/admin/messaging/audience", tags=["Admin"])
async def admin_messaging_audience(_: dict = Depends(get_current_admin)):
    """Return all contactable recipients (clients with phone/whatsapp + tracked users with phone).

    S-iter39d (fix #5) — Each row is enriched with `last_message_at`, the
    timestamp of the most recent inbound or outbound WhatsApp/SMS message
    associated with the row's phone digits. The Messaging Center frontend
    sorts on this field so that recently-touched contacts surface first.
    """
    users = await db.users.find(
        {"role": {"$in": ["client", "superviseur"]}},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1, "company": 1,
         "phone": 1, "whatsapp_number": 1, "account_status": 1, "client_code": 1, "country": 1, "city": 1},
    ).to_list(3000)
    tracked = await db.tracked_users.find(
        {}, {"_id": 0, "id": 1, "name": 1, "full_name": 1, "email": 1, "phone": 1, "whatsapp_number": 1,
             "client_id": 1, "role": 1, "status": 1},
    ).to_list(5000)
    # Build client lookup for tracked-users labels
    client_map = {u["id"]: (u.get("company") or u.get("full_name") or u.get("email")) for u in users}

    # S-iter39d (fix #5) — Pre-compute last message timestamp per phone-digits.
    # Strips non-digits and keeps the last 10 digits for fuzzy matching across
    # international prefixes.
    import re as _re

    def _digits10(s: Optional[str]) -> str:
        d = _re.sub(r"\D", "", s or "")
        return d[-10:] if len(d) >= 10 else d

    all_phones = set()
    for u in users:
        all_phones.add(_digits10(u.get("whatsapp_number") or u.get("phone")))
    for t in tracked:
        all_phones.add(_digits10(t.get("whatsapp_number") or t.get("phone")))
    all_phones.discard("")
    last_by_phone: Dict[str, str] = {}
    if all_phones:
        # WhatsApp messages — collection wa_messages, fields: from/to/timestamp
        try:
            async for msg in db.wa_messages.find(
                {}, {"_id": 0, "from": 1, "to": 1, "timestamp": 1, "created_at": 1},
            ).sort("timestamp", -1).limit(20000):
                ts = msg.get("timestamp") or msg.get("created_at")
                if not ts:
                    continue
                for k in ("from", "to"):
                    d10 = _digits10(msg.get(k))
                    if d10 in all_phones:
                        if d10 not in last_by_phone or str(ts) > last_by_phone[d10]:
                            last_by_phone[d10] = str(ts)
        except Exception:
            pass
        # SMS messages (best-effort)
        try:
            async for msg in db.sms_messages.find(
                {}, {"_id": 0, "to": 1, "from": 1, "sent_at": 1, "created_at": 1, "received_at": 1},
            ).sort("created_at", -1).limit(20000):
                ts = msg.get("sent_at") or msg.get("received_at") or msg.get("created_at")
                if not ts:
                    continue
                for k in ("from", "to"):
                    d10 = _digits10(msg.get(k))
                    if d10 in all_phones:
                        if d10 not in last_by_phone or str(ts) > last_by_phone[d10]:
                            last_by_phone[d10] = str(ts)
        except Exception:
            pass

    clients_rows = []
    for u in users:
        # Prefer the dedicated WhatsApp number; fall back to the regular phone field
        wa = (u.get("whatsapp_number") or "").strip()
        phone_only = (u.get("phone") or "").strip()
        phone = wa or phone_only
        d10 = _digits10(phone)
        clients_rows.append({
            "kind": "client",
            "id": u["id"],
            "full_name": u.get("full_name") or "—",
            "email": u.get("email"),
            "company": u.get("company") or "",
            "phone": phone,
            "whatsapp_number": wa or None,
            "client_code": u.get("client_code"),
            "country": u.get("country"),
            "city": u.get("city"),
            "account_status": u.get("account_status"),
            "has_phone": bool(phone),
            "last_message_at": last_by_phone.get(d10),
        })

    tracked_rows = []
    for t in tracked:
        wa = (t.get("whatsapp_number") or "").strip()
        phone_only = (t.get("phone") or "").strip()
        phone = wa or phone_only
        d10 = _digits10(phone)
        tracked_rows.append({
            "kind": "tracked",
            "id": t["id"],
            "full_name": t.get("full_name") or t.get("name") or "—",
            "email": t.get("email"),
            "client_id": t.get("client_id"),
            "client_label": client_map.get(t.get("client_id") or "") or "—",
            "phone": phone,
            "whatsapp_number": wa or None,
            "role": t.get("role"),
            "status": t.get("status"),
            "has_phone": bool(phone),
            "last_message_at": last_by_phone.get(d10),
        })
    return {"clients": clients_rows, "tracked_users": tracked_rows}


class AdminBulkSendRequest(BaseModel):
    recipients: List[Dict[str, Any]]  # [{kind:'client'|'tracked'|'raw', id?, phone?}]
    template_name: str
    language_code: Optional[str] = "fr"
    components: Optional[list] = None
    variables: Optional[List[str]] = None  # Positional body-variable recipes with {{token}} tokens
    header_text: Optional[str] = None  # Optional header TEXT variable (with token substitution)
    header_media: Optional[Dict[str, Any]] = None  # {link, kind, filename?} for header IMAGE/DOC/VIDEO
    button_vars: Optional[List[List[str]]] = None  # [[urlVar1,...], ...] indexed by button position
    button_specs: Optional[List[Dict[str, Any]]] = None  # Iter43-fix24aj — explicit sub_type per button


@api.post("/admin/messaging/bulk-send", tags=["Admin"])
async def admin_messaging_bulk_send(
    payload: AdminBulkSendRequest,
    admin_user: dict = Depends(get_current_admin),
):
    """Envoie le même modèle WhatsApp à une liste de destinataires. Renvoie un résultat par destinataire."""
    if not payload.recipients:
        raise HTTPException(status_code=400, detail="Aucun destinataire")
    if not payload.template_name:
        raise HTTPException(status_code=400, detail="Template requis")

    # Resolve each recipient into an E.164 phone + user doc for variable context
    resolved = []
    for r in payload.recipients:
        kind = (r.get("kind") or "").lower()
        rid = r.get("id")
        phone = (r.get("phone") or "").strip()
        label = r.get("label")
        user_doc: Optional[dict] = None
        if kind == "client" and rid:
            u = await db.users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "full_name": 1, "email": 1, "company": 1, "client_code": 1})
            if u:
                user_doc = u
                if not phone:
                    # Prefer the dedicated WhatsApp number, fall back to the regular phone field
                    phone = (u.get("whatsapp_number") or u.get("phone") or "").strip()
                label = label or u.get("company") or u.get("full_name") or u.get("email")
        elif kind == "tracked" and rid:
            t = await db.tracked_users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "name": 1, "full_name": 1, "email": 1, "client_id": 1})
            if t:
                user_doc = t
                if not phone:
                    phone = (t.get("whatsapp_number") or t.get("phone") or "").strip()
                label = label or t.get("full_name") or t.get("name") or t.get("email")
        resolved.append({"kind": kind or "raw", "id": rid, "phone": phone, "label": label or phone or "—", "user_doc": user_doc})

    # Validate phones (basic)
    to_send = [x for x in resolved if x["phone"]]
    skipped = [x for x in resolved if not x["phone"]]

    # Send sequentially to avoid burst rate-limits (Meta Cloud ~80 msg/s max)
    results = []
    for x in to_send:
        # Build per-recipient components from either the static `components` or dynamic `variables`/header/buttons
        if payload.variables or payload.header_text or payload.header_media or payload.button_vars or payload.button_specs:
            ctx = _build_recipient_ctx(x["kind"], x["user_doc"], x["phone"], x["label"])
            components = _build_components(
                payload.variables, ctx,
                header_text=payload.header_text,
                header_media=payload.header_media,
                button_vars=payload.button_vars,
                button_specs=payload.button_specs,
            )
        else:
            components = payload.components
        try:
            r = await _wa_send_template(x["phone"], payload.template_name, payload.language_code or "fr", components)
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "status": 0, "message_id": None, "error": str(exc)[:200]}
        log = {
            "id": _uuid(),
            "client_id": x.get("id") if x.get("kind") == "client" else None,
            "sender_id": admin_user["id"],
            "sender_label": admin_user.get("full_name") or admin_user.get("email"),
            "to": x["phone"],
            "template_name": payload.template_name,
            "language_code": payload.language_code,
            "contact_id": None,
            "tracked_user_id": x.get("id") if x.get("kind") == "tracked" else None,
            "recipient_kind": x.get("kind"),
            "recipient_label": x.get("label"),
            "bulk": True,
            "ok": r["ok"],
            "status": r["status"],
            "message_id": r["message_id"],
            "error": r.get("error"),
            "created_at": _now(),
        }
        try:
            await db.whatsapp_messages.insert_one(log.copy())
        except Exception:
            pass
        results.append({
            "label": x["label"],
            "phone": x["phone"],
            "kind": x["kind"],
            "ok": r["ok"],
            "status": r["status"],
            "message_id": r["message_id"],
            "error": r.get("error"),
        })

    sent_ok = sum(1 for r in results if r["ok"])
    # Collect a compact list of distinct error messages so the frontend can show why
    # an envoi failed (e.g. "(#100) Param 'to' invalid" → user fixes the number once).
    error_summary = []
    seen_err = set()
    for r in results:
        if not r["ok"] and r.get("error"):
            e = str(r["error"])[:240]
            if e not in seen_err:
                seen_err.add(e)
                error_summary.append(e)
            if len(error_summary) >= 3:
                break
    return {
        "requested": len(payload.recipients),
        "sent_ok": sent_ok,
        "sent_ko": len(results) - sent_ok,
        "skipped": [{"label": s["label"], "reason": "Pas de numéro de téléphone"} for s in skipped],
        "results": results,
        "error_summary": error_summary,
    }


@api.get("/admin/messaging/history", tags=["Admin"])
async def admin_messaging_history(
    limit: int = 200,
    _: dict = Depends(get_current_admin),
):
    items = await db.whatsapp_messages.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 1000))
    return items


@api.get("/admin/messaging/variable-tokens", tags=["Admin"])
async def admin_messaging_variable_tokens(_: dict = Depends(get_current_admin)):
    """Liste des tokens de substitution que l'admin peut insérer dans les variables de modèle.
    Resolved per-recipient at send time from the client or tracked-user profile."""
    return _wa_variable_tokens()


@api.get("/me/messaging/variable-tokens", tags=["Portail Client"])
async def me_messaging_variable_tokens(user: dict = Depends(get_current_user)):
    """Portal mirror of variable tokens. Same resolution at send time."""
    if user.get("role") not in ("client", "admin") and not _is_elevated_creator(user) and not _is_tracked_user(user):
        raise HTTPException(status_code=403, detail="Rôle non autorisé")
    return _wa_variable_tokens()


def _wa_variable_tokens() -> dict:
    return {
        "tokens": [
            {"token": "{{full_name}}", "label": "Nom complet", "example": "Jean Dupont"},
            {"token": "{{identity}}", "label": "Identité (nom ou email)", "example": "Jean Dupont"},
            {"token": "{{company}}", "label": "Société", "example": "Acme Corp"},
            {"token": "{{linked_client}}", "label": "Client lié (tenant parent)", "example": "SAWALI SMART SYSTEMS"},
            {"token": "{{phone}}", "label": "Téléphone", "example": "+225 01 23 45 67"},
            {"token": "{{email}}", "label": "Email", "example": "client@example.com"},
            {"token": "{{client_code}}", "label": "Code client", "example": "ACME"},
            {"token": "{{tracked_role}}", "label": "Rôle utilisateur suivi", "example": "Comptable"},
            {"token": "{{today}}", "label": "Date du jour", "example": datetime.now(timezone.utc).strftime("%d/%m/%Y")},
            {"token": "{{tomorrow}}", "label": "Date de demain", "example": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d/%m/%Y")},
            # 2026-02 fork iter106 — Tokens spécifiques login / relais
            {"token": "{{login_email}}", "label": "Email de login", "example": "user@example.com"},
            {"token": "{{login_ip}}", "label": "Adresse IP de connexion", "example": "102.23.45.12"},
            {"token": "{{login_time}}", "label": "Date/heure de connexion", "example": "27/08/2026 15:32 UTC"},
            {"token": "{{login_full_name}}", "label": "Nom complet (login)", "example": "Jean Dupont"},
            {"token": "{{login_role}}", "label": "Rôle (login)", "example": "superviseur"},
            {"token": "{{login_tracked_role}}", "label": "Rôle métier (login)", "example": "Administrateur"},
        ]
    }


# ====================================================================
# AUTOMATIONS — Triggered WhatsApp messages on system events
# Supported events: appointment.created, appointment.reminder,
#                   intervention.created, client.created
# Recipient strategy: 'event_target' → resolve phone from event payload
#                     (typically client_id → users.phone OR tracked_user)
# ====================================================================
SUPPORTED_AUTOMATION_EVENTS = {
    "appointment.created",
    "appointment.reminder",
    "intervention.created",
    "client.created",
    "task.reminder",
    # 2026-02 fork (P3a) — Nouvelle connexion à la plateforme (login OTP validé).
    # Context tokens exposed : {login_email}, {login_full_name}, {login_role},
    # {login_tracked_role}, {login_ip}, {login_time}.
    "user.login",
    # 2026-02 fork (P3b) — Nouveau message WhatsApp entrant. Context tokens :
    # {wa_from}, {wa_sender_name}, {wa_message}, {wa_reply_code}. L'admin peut
    # répondre en préfixant sa réponse par le code (ex: "#R7X2 Bonjour..."),
    # Liluvine relaye au client sans exposer le numéro admin.
    "whatsapp.received",
    # Lot 27 — Formulaire WhatsApp (Flow) complété par un client. Context tokens :
    # {wa_from}, {wa_sender_name}, {wa_flow_template}, {wa_flow_summary}.
    "whatsapp.flow_completed",
    # Lot 41 — nouvelles données des Formulaires & Sondages. Destinataire « cible de
    # l'événement » = le client propriétaire du formulaire / sondage. Context tokens :
    # {formulaire}, {formulaire_numero}, {repondant}, {nb_reponses} ;
    # {sondage}, {repondant}, {nb_reponses}.
    "form.submitted",
    "survey.responded",
}


class AutomationCreate(BaseModel):
    title: str
    event: str
    template_name: str
    language_code: Optional[str] = "fr"
    variables: Optional[List[str]] = None
    delay_minutes: int = 0      # 0 = immédiat ; >0 = planifié
    target: str = "event_target"  # placeholder for future targets (e.g. fixed phone)
    target_phone: Optional[str] = None  # used when target='fixed'
    enabled: bool = True
    # 2026-02 fork (bug fix) — Email de secours envoyé quand le WA échoue OU
    # quand le WA n'est pas configuré. Un email différent peut être défini
    # sur chaque automation. Vide = pas de fallback.
    notification_email: Optional[EmailStr] = None
    # 2026-02 fork iter102 (bug fix) — Numéro WA de secours utilisé lorsque le
    # destinataire résolu par `event_target` n'a pas de téléphone (typique
    # du compte super-admin qui n'a pas de `phone` renseigné). Format E.164
    # (ex: `22670000000`). Vide = pas de fallback → l'email prend le relais.
    notification_phone: Optional[str] = None


class AutomationUpdate(BaseModel):
    title: Optional[str] = None
    template_name: Optional[str] = None
    language_code: Optional[str] = None
    variables: Optional[List[str]] = None
    delay_minutes: Optional[int] = None
    target: Optional[str] = None
    target_phone: Optional[str] = None
    enabled: Optional[bool] = None
    notification_email: Optional[EmailStr] = None
    notification_phone: Optional[str] = None


@api.get("/admin/automations", tags=["Admin"])
async def admin_list_automations(_: dict = Depends(get_current_admin)):
    items = await db.automations.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


@api.get("/admin/automations/events", tags=["Admin"])
async def admin_automation_events(_: dict = Depends(get_current_admin)):
    return {
        "events": [
            {"value": "appointment.created", "label": "RDV créé",
             "description": "Confirmation immédiate envoyée au client après création d'un RDV."},
            {"value": "appointment.reminder", "label": "Rappel RDV (J-1)",
             "description": "Rappel automatique envoyé 24h avant l'heure du RDV (cron horaire)."},
            {"value": "intervention.created", "label": "Intervention créée",
             "description": "Notification au client lorsqu'une intervention est enregistrée."},
            {"value": "client.created", "label": "Nouveau client",
             "description": "Message de bienvenue à un client fraîchement créé."},
            {"value": "task.reminder", "label": "Rappel de tâche",
             "description": "Rappel WhatsApp envoyé 1h avant l'échéance d'une tâche client (cron horaire)."},
            {"value": "user.login", "label": "Connexion utilisateur",
             "description": "Nouvelle connexion validée (post-OTP). Contexte : {login_email}, {login_full_name}, {login_role}, {login_tracked_role}, {login_ip}, {login_time}."},
            {"value": "whatsapp.received", "label": "Nouveau message WhatsApp reçu",
             "description": "Message WA entrant. Contexte : {wa_from}, {wa_sender_name}, {wa_message}, {wa_reply_code}. L'admin peut répondre en préfixant `#R<code>` — Liluvine relaye au client sans exposer son numéro."},
            {"value": "whatsapp.flow_completed", "label": "Formulaire WhatsApp (Flow) complété",
             "description": "Un client a rempli le formulaire ouvert par un bouton « Flux » d'un modèle. Contexte : {wa_from}, {wa_sender_name}, {wa_flow_template}, {wa_flow_summary}."},
            # Lot 41
            {"value": "form.submitted", "label": "Nouvelle soumission de formulaire",
             "description": "Une réponse arrive sur un formulaire (portail, lien public ou lien crypté « !formulaire »). Envoyé au client propriétaire du formulaire (ou au numéro fixe). Contexte : {formulaire}, {formulaire_numero}, {repondant}, {nb_reponses}."},
            {"value": "survey.responded", "label": "Nouvelle réponse à un sondage",
             "description": "Un destinataire répond à un sondage WhatsApp. Envoyé au client propriétaire du sondage (ou au numéro fixe). Contexte : {sondage}, {repondant}, {nb_reponses}."},
        ]
    }


@api.post("/admin/automations", tags=["Admin"])
async def admin_create_automation(payload: AutomationCreate, admin_user: dict = Depends(get_current_admin)):
    if payload.event not in SUPPORTED_AUTOMATION_EVENTS:
        raise HTTPException(status_code=400, detail=f"Événement non supporté. Valeurs : {sorted(SUPPORTED_AUTOMATION_EVENTS)}")
    if not payload.template_name.strip():
        raise HTTPException(status_code=400, detail="Template requis")
    if (payload.delay_minutes or 0) < 0:
        raise HTTPException(status_code=400, detail="delay_minutes doit être ≥ 0")
    if payload.target == "fixed" and not (payload.target_phone or "").strip():
        raise HTTPException(status_code=400, detail="target_phone requis quand target='fixed'")
    doc = {
        "id": _uuid(),
        **payload.model_dump(),
        "created_by_id": admin_user["id"],
        "created_by_label": admin_user.get("full_name") or admin_user.get("email"),
        "created_at": _now(),
        "updated_at": _now(),
        "trigger_count": 0,
    }
    await db.automations.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/automations/{aid}", tags=["Admin"])
async def admin_update_automation(aid: str, payload: AutomationUpdate, _: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    res = await db.automations.update_one({"id": aid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Automation introuvable")
    refreshed = await db.automations.find_one({"id": aid}, {"_id": 0})
    return refreshed


@api.delete("/admin/automations/{aid}", tags=["Admin"])
async def admin_delete_automation(aid: str, _: dict = Depends(get_current_admin)):
    res = await db.automations.delete_one({"id": aid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Automation introuvable")
    return {"ok": True}



async def _dispatch_appointment_participants(
    appt_doc: dict,
    actor_user: dict,
    *,
    event: str = "appointment.created",
) -> None:
    """2026-02 fork iter107 — Envoie un template WA à chaque participant listé
    sur le RDV.

    - Si `appt_doc.participants` est vide → no-op (comportement demandé : « Si des
      noms figurent parmi la liste des participants, un modèle de message WA est
      envoyé à tous les noms, sinon aucun envoi »).
    - Le template Meta utilisé est déterminé par les automations actives pour
      `event` — on route chaque participant comme un `event_target` distinct.
    """
    parts = appt_doc.get("participants") or []
    if not parts:
        return
    try:
        sched_human = appt_doc.get("scheduled_at") or ""
        try:
            sched_human = datetime.fromisoformat(sched_human.replace("Z", "+00:00")).strftime("%d/%m/%Y à %Hh%M")
        except Exception:  # noqa: BLE001
            pass
        for p in parts:
            phone = (p.get("phone") or p.get("whatsapp") or "").strip()
            if not phone:
                continue
            await _emit_event(event, {
                "phone": phone,
                "extra_ctx": {
                    "full_name": p.get("name") or phone,
                    "appointment_date": sched_human,
                    "appointment_subject": appt_doc.get("subject") or "",
                    "linked_client": actor_user.get("company") or actor_user.get("full_name") or "",
                    "reminder_minutes": str(appt_doc.get("reminder_minutes") or ""),
                    "organizer_name": actor_user.get("full_name") or "",
                },
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[appointment/participants] dispatch failed: %s", exc)



async def _emit_event(event: str, target: dict) -> None:
    """Fire-and-forget : exécute toutes les automations actives pour cet event.

    target dict supports the following keys (best-effort; missing → blank in templates):
      - client_id: str  → resolves via db.users (provides full_name, company, phone, email, client_code)
      - tracked_user_id: str → resolves via db.tracked_users (provides full_name, phone, email)
      - phone: str (fallback if no id given)
      - extra_ctx: dict (additional substitution tokens, e.g. {"appointment_date": "..."})
    """
    if event not in SUPPORTED_AUTOMATION_EVENTS:
        return
    automations = await db.automations.find(
        {"event": event, "enabled": True}, {"_id": 0}
    ).to_list(50)
    if not automations:
        return

    # Resolve user_doc + phone once for the whole event
    user_doc: Optional[dict] = None
    phone = (target.get("phone") or "").strip()
    label: Optional[str] = None
    kind = "raw"
    rid: Optional[str] = None
    if target.get("client_id"):
        rid = target["client_id"]
        kind = "client"
        u = await db.users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "full_name": 1, "email": 1, "company": 1, "client_code": 1})
        if u:
            user_doc = u
            # 2026-02 fork bugfix — Fallback sur `whatsapp_number` si `phone` vide.
            phone = phone or (u.get("phone") or "").strip() or (u.get("whatsapp_number") or "").strip()
            label = u.get("company") or u.get("full_name") or u.get("email")
    elif target.get("tracked_user_id"):
        rid = target["tracked_user_id"]
        kind = "tracked"
        t = await db.tracked_users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "name": 1, "full_name": 1, "email": 1})
        if t:
            user_doc = t
            # 2026-02 fork bugfix — Fallback sur `whatsapp_number` si `phone` vide.
            phone = phone or (t.get("phone") or "").strip() or (t.get("whatsapp_number") or "").strip()
            label = t.get("full_name") or t.get("name") or t.get("email")
    label = label or phone or "—"

    for au in automations:
        # Choose recipient
        if (au.get("target") or "event_target") == "fixed":
            to_phone = (au.get("target_phone") or "").strip()
            ctx_phone = to_phone
            ctx_label = to_phone or "Fixed"
            ctx_user_doc = None
            ctx_kind = "raw"
            ctx_rid = None
        else:
            to_phone = phone
            ctx_phone = phone
            ctx_label = label
            ctx_user_doc = user_doc
            ctx_kind = kind
            ctx_rid = rid

        # 2026-02 fork iter105 — Priorité inversée sur demande utilisateur :
        # Le `notification_phone` défini sur l'automation prend le PAS sur le
        # téléphone du destinataire résolu (auparavant c'était l'inverse). Le
        # cas d'usage cible = automations "relais admin" (`relais_messagewa_pouradmin`,
        # `nouvellecnx_loois`) où l'administrateur veut recevoir le message sur
        # SON numéro, pas sur celui du destinataire d'événement.
        fallback_phone = (au.get("notification_phone") or "").strip()
        if fallback_phone:
            # Notification_phone défini → il gagne, même si `to_phone` existe.
            if to_phone and to_phone != fallback_phone:
                ctx_label = f"{ctx_label} → {fallback_phone}" if ctx_label and ctx_label != "—" else fallback_phone
            to_phone = fallback_phone
            ctx_phone = fallback_phone

        if not to_phone:
            # 2026-02 fork (bug fix) — Email de secours si l'automation
            # ne peut PAS envoyer le WA (numéro manquant).
            fallback_email = (au.get("notification_email") or "").strip()
            email_sent = False
            email_error: Optional[str] = None
            base_ctx = _build_recipient_ctx(ctx_kind, ctx_user_doc, ctx_phone or "", ctx_label)
            for k, v in (target.get("extra_ctx") or {}).items():
                base_ctx[k] = str(v) if v is not None else ""
            if fallback_email:
                try:
                    subject = f"[SAWALI Automation] {au.get('title') or event} (WA impossible)"
                    body_lines = [
                        f"L'automation « {au.get('title') or au['template_name']} » n'a pas pu envoyer de WhatsApp : aucun numéro renseigné pour le destinataire.",
                        "",
                        f"Événement : {event}",
                        f"Destinataire prévu : {ctx_label}",
                        f"Template WA : {au['template_name']} ({au.get('language_code') or 'fr'})",
                        "",
                        "Contexte substitué :",
                    ]
                    for k, v in (base_ctx or {}).items():
                        body_lines.append(f"  · {k} = {v}")
                    body_text = "\n".join(body_lines)
                    from email_service import send_email as _send_email
                    email_sent = await _send_email(fallback_email, subject, body_text)
                except Exception as exc:  # noqa: BLE001
                    email_error = str(exc)[:200]
                    email_sent = False
            # Skipped WA (cannot send) but still log a tracking row
            try:
                await db.whatsapp_messages.insert_one({
                    "id": _uuid(),
                    "client_id": ctx_rid if ctx_kind == "client" else None,
                    "tracked_user_id": ctx_rid if ctx_kind == "tracked" else None,
                    "to": "",
                    "template_name": au["template_name"],
                    "language_code": au.get("language_code"),
                    "recipient_kind": ctx_kind,
                    "recipient_label": ctx_label,
                    "automation_id": au["id"],
                    "automation_event": event,
                    "ok": False,
                    "status": None,
                    "message_id": None,
                    "error": "Pas de numéro de téléphone",
                    "notification_email": fallback_email or None,
                    "email_fallback_sent": email_sent if fallback_email else None,
                    "email_fallback_error": email_error,
                    "created_at": _now(),
                })
            except Exception:
                pass
            continue

        # Build per-recipient ctx + components
        base_ctx = _build_recipient_ctx(ctx_kind, ctx_user_doc, ctx_phone, ctx_label)
        for k, v in (target.get("extra_ctx") or {}).items():
            base_ctx[k] = str(v) if v is not None else ""
        components = _build_components(au.get("variables"), base_ctx)
        delay = int(au.get("delay_minutes") or 0)

        if delay > 0:
            # Schedule for later — leverage the existing whatsapp_schedules pipeline
            sched_at = (datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat()
            await db.whatsapp_schedules.insert_one({
                "id": _uuid(),
                "title": f"Auto: {au.get('title') or au['template_name']}",
                "recipients": [{"kind": ctx_kind, "id": ctx_rid, "phone": to_phone, "label": ctx_label}],
                "template_name": au["template_name"],
                "language_code": au.get("language_code") or "fr",
                "components": None,
                "variables": au.get("variables"),
                "scheduled_at": sched_at,
                "status": "pending",
                "result_summary": None,
                "automation_id": au["id"],
                "automation_event": event,
                "extra_ctx": target.get("extra_ctx") or {},
                "created_by_id": "automation",
                "created_by_label": f"Automation: {au.get('title') or au['template_name']}",
                "created_at": _now(),
                "updated_at": _now(),
            })
        else:
            try:
                wr = await _wa_send_template(to_phone, au["template_name"], au.get("language_code") or "fr", components)
            except Exception as exc:  # noqa: BLE001
                wr = {"ok": False, "status": 0, "message_id": None, "error": str(exc)[:200]}
            # 2026-02 fork (bug fix) — Email de secours quand le WA échoue OU
            # que le WA n'est pas configuré. Ne bloque jamais.
            fallback_email = (au.get("notification_email") or "").strip()
            email_sent = False
            email_error: Optional[str] = None
            if fallback_email and not wr.get("ok"):
                try:
                    subject = f"[SAWALI Automation] {au.get('title') or event}"
                    body_lines = [
                        f"L'automation « {au.get('title') or au['template_name']} » n'a pas pu envoyer le WhatsApp attendu.",
                        "",
                        f"Événement : {event}",
                        f"Destinataire prévu : {ctx_label} ({to_phone or 'sans numéro'})",
                        f"Template WA : {au['template_name']} ({au.get('language_code') or 'fr'})",
                        f"Erreur WA : {wr.get('error') or wr.get('status') or 'inconnue'}",
                        "",
                        "Contexte substitué :",
                    ]
                    for k, v in (base_ctx or {}).items():
                        body_lines.append(f"  · {k} = {v}")
                    body_text = "\n".join(body_lines)
                    from email_service import send_email as _send_email  # local import — module-level triangle
                    email_sent = await _send_email(fallback_email, subject, body_text)
                except Exception as exc:  # noqa: BLE001
                    email_error = str(exc)[:200]
                    email_sent = False
            try:
                await db.whatsapp_messages.insert_one({
                    "id": _uuid(),
                    "client_id": ctx_rid if ctx_kind == "client" else None,
                    "tracked_user_id": ctx_rid if ctx_kind == "tracked" else None,
                    "to": to_phone,
                    "template_name": au["template_name"],
                    "language_code": au.get("language_code"),
                    "recipient_kind": ctx_kind,
                    "recipient_label": ctx_label,
                    "automation_id": au["id"],
                    "automation_event": event,
                    "ok": wr["ok"],
                    "status": wr["status"],
                    "message_id": wr["message_id"],
                    "error": wr.get("error"),
                    "notification_email": fallback_email or None,
                    "email_fallback_sent": email_sent if fallback_email else None,
                    "email_fallback_error": email_error,
                    "created_at": _now(),
                })
            except Exception:
                pass

        # Counter (fire-and-forget)
        try:
            await db.automations.update_one({"id": au["id"]}, {"$inc": {"trigger_count": 1}})
        except Exception:
            pass


async def _appointment_reminder_cron():
    """Hourly cron: find appointments scheduled in (now+23h, now+25h) window and emit reminders."""
    now_utc = datetime.now(timezone.utc)
    win_start = (now_utc + timedelta(hours=23)).isoformat()
    win_end = (now_utc + timedelta(hours=25)).isoformat()
    appts = await db.appointments.find(
        {"scheduled_at": {"$gte": win_start, "$lte": win_end},
         "status": {"$nin": ["cancelled", "rejected"]},
         "reminder_sent_at": {"$exists": False}},
        {"_id": 0, "id": 1, "client_id": 1, "scheduled_at": 1, "subject": 1, "phone": 1},
    ).to_list(200)
    for ap in appts:
        try:
            sched_dt = datetime.fromisoformat(ap["scheduled_at"].replace("Z", "+00:00"))
            sched_human = sched_dt.strftime("%d/%m/%Y à %Hh%M")
        except Exception:
            sched_human = ap.get("scheduled_at") or ""
        await _emit_event("appointment.reminder", {
            "client_id": ap.get("client_id"),
            "phone": ap.get("phone"),
            "extra_ctx": {
                "appointment_date": sched_human,
                "appointment_subject": ap.get("subject") or "",
            },
        })
        # Iter35x — Alexa voice notification for upcoming appointment
        _alexa_notify_async(
            "appointment_due",
            f"Rendez-vous demain {sched_human} : {ap.get('subject') or ''}".strip(),
        )
        try:
            await db.appointments.update_one(
                {"id": ap["id"]},
                {"$set": {"reminder_sent_at": _now()}},
            )
        except Exception:
            pass


# ====================================================================
# ADMIN — Envois WhatsApp planifiés (scheduler minute-based)
# ====================================================================
class AdminScheduleCreate(BaseModel):
    title: Optional[str] = None
    recipients: List[Dict[str, Any]]
    template_name: str
    language_code: Optional[str] = "fr"
    components: Optional[list] = None
    variables: Optional[List[str]] = None  # Positional body-variable recipes
    header_text: Optional[str] = None
    header_media: Optional[Dict[str, Any]] = None
    button_vars: Optional[List[List[str]]] = None
    button_specs: Optional[List[Dict[str, Any]]] = None  # Iter43-fix24aj
    scheduled_at: str  # ISO-8601 UTC, e.g. "2026-05-10T14:30:00+00:00"


@api.get("/admin/messaging/schedules", tags=["Admin"])
async def admin_list_schedules(_: dict = Depends(get_current_admin)):
    items = await db.whatsapp_schedules.find({}, {"_id": 0}).sort("scheduled_at", -1).to_list(1000)
    return items


@api.post("/admin/messaging/schedules", tags=["Admin"])
async def admin_create_schedule(
    payload: AdminScheduleCreate,
    admin_user: dict = Depends(get_current_admin),
):
    if not payload.recipients:
        raise HTTPException(status_code=400, detail="Aucun destinataire")
    if not payload.template_name:
        raise HTTPException(status_code=400, detail="Template requis")
    # Parse + validate datetime
    try:
        sched = datetime.fromisoformat(payload.scheduled_at.replace("Z", "+00:00"))
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Date invalide (ISO-8601 attendu)")
    now_utc = datetime.now(timezone.utc)
    if sched <= now_utc - timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="La date planifiée doit être dans le futur")

    doc = {
        "id": _uuid(),
        "title": (payload.title or "").strip() or f"Envoi {payload.template_name}",
        "recipients": payload.recipients,
        "template_name": payload.template_name,
        "language_code": payload.language_code or "fr",
        "components": payload.components,
        "variables": payload.variables,
        "header_text": payload.header_text,
        "header_media": payload.header_media,
        "button_vars": payload.button_vars,
        "button_specs": payload.button_specs,
        "scheduled_at": sched.isoformat(),
        "status": "pending",
        "result_summary": None,
        "created_by_id": admin_user["id"],
        "created_by_label": admin_user.get("full_name") or admin_user.get("email"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.whatsapp_schedules.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.delete("/admin/messaging/schedules/{sid}", tags=["Admin"])
async def admin_delete_schedule(sid: str, _: dict = Depends(get_current_admin)):
    existing = await db.whatsapp_schedules.find_one({"id": sid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Planification introuvable")
    if existing.get("status") in ("running", "done"):
        # Don't hard-delete an active one — mark cancelled for audit
        await db.whatsapp_schedules.update_one(
            {"id": sid},
            {"$set": {"status": "cancelled", "updated_at": _now()}},
        )
        return {"ok": True, "status": "cancelled"}
    await db.whatsapp_schedules.delete_one({"id": sid})
    return {"ok": True, "status": "deleted"}


# Lot 27 — les tâches planifiées ont été inactives pendant des mois (bloc de
# démarrage jamais exécuté). À leur réactivation, un envoi programmé en retard
# de plus de SCHEDULE_MAX_LATE_HOURS ne part plus tout seul : il est annulé avec
# un motif clair, visible dans l'historique, et peut être reprogrammé à la main.
# (Évite d'envoyer d'un coup à des clients des messages vieux de plusieurs mois.)
SCHEDULE_MAX_LATE_HOURS = 3


async def _expire_stale_schedules(collection, kind: str) -> int:
    """Annule les envois programmés encore « pending » mais trop en retard."""
    limit_iso = (datetime.now(timezone.utc) - timedelta(hours=SCHEDULE_MAX_LATE_HOURS)).isoformat()
    try:
        res = await collection.update_many(
            {"status": "pending", "scheduled_at": {"$lt": limit_iso}},
            {"$set": {
                "status": "cancelled",
                "cancelled_reason": "stale",
                "cancelled_at": _now(),
                "updated_at": _now(),
                "result_summary": {"error": f"Non envoyé : en retard de plus de {SCHEDULE_MAX_LATE_HOURS} h "
                                            f"(planificateur inactif). Reprogrammez-le si besoin."},
            }},
        )
        if res.modified_count:
            logger.warning("[%s-scheduler] %s envoi(s) programmé(s) trop ancien(s) annulé(s)", kind, res.modified_count)
        return res.modified_count
    except Exception:  # noqa: BLE001
        logger.exception("[%s-scheduler] annulation des envois trop anciens échouée", kind)
        return 0


async def _run_scheduled_whatsapp():
    """Cron job (runs every minute) — execute any pending schedule whose scheduled_at <= now.

    Iter35a hardening: per-schedule try/except so one failing schedule doesn't
    leave others stuck in `running`. The final status update also captures
    a top-level `error` string in result_summary on hard failure.
    """
    try:
        await _expire_stale_schedules(db.whatsapp_schedules, "wa")  # lot 27 : pas de rattrapage massif
        now_iso = datetime.now(timezone.utc).isoformat()
        due = await db.whatsapp_schedules.find(
            {"status": "pending", "scheduled_at": {"$lte": now_iso}},
            {"_id": 0},
        ).to_list(50)
        for sc in due:
            # Claim it (atomic update to running)
            claimed = await db.whatsapp_schedules.update_one(
                {"id": sc["id"], "status": "pending"},
                {"$set": {"status": "running", "started_at": _now(), "updated_at": _now()}},
            )
            if claimed.modified_count == 0:
                continue  # Someone else got it (defensive)

            # Resolve + send (same logic as bulk-send, simplified)
            results = []
            skipped = []
            variables = sc.get("variables") or []
            static_components = sc.get("components")
            for r in (sc.get("recipients") or []):
                kind = (r.get("kind") or "").lower()
                rid = r.get("id")
                phone = (r.get("phone") or "").strip()
                label = r.get("label")
                user_doc: Optional[dict] = None
                if kind == "client" and rid:
                    u = await db.users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "full_name": 1, "company": 1, "email": 1, "client_code": 1})
                    if u:
                        user_doc = u
                        if not phone:
                            phone = (u.get("whatsapp_number") or u.get("phone") or "").strip()
                        label = label or u.get("company") or u.get("full_name") or u.get("email")
                elif kind == "tracked" and rid:
                    t = await db.tracked_users.find_one({"id": rid}, {"_id": 0, "phone": 1, "whatsapp_number": 1, "name": 1, "full_name": 1, "email": 1})
                    if t:
                        user_doc = t
                        if not phone:
                            phone = (t.get("whatsapp_number") or t.get("phone") or "").strip()
                        label = label or t.get("full_name") or t.get("name") or t.get("email")
                elif kind == "contact" and rid:
                    # Directory contact (CRM). Pull name/company/email/whatsapp/phone.
                    c = await db.directory_contacts.find_one(
                        {"id": rid},
                        {"_id": 0, "name": 1, "company": 1, "email": 1, "phone": 1, "whatsapp": 1, "unique_code": 1},
                    )
                    if c:
                        user_doc = {
                            "full_name": c.get("name"),
                            "company": c.get("company"),
                            "email": c.get("email"),
                            "phone": c.get("phone") or c.get("whatsapp"),
                            "client_code": c.get("unique_code"),
                        }
                        if not phone:
                            phone = (c.get("whatsapp") or c.get("phone") or "").strip()
                        label = label or c.get("name") or c.get("company") or c.get("email")
                label = label or phone or "—"
                if not phone:
                    skipped.append({"label": label, "reason": "Pas de numéro de téléphone"})
                    continue
                # Per-recipient dynamic components
                if variables or sc.get("header_text") or sc.get("header_media") or sc.get("button_vars") or sc.get("button_specs"):
                    ctx = _build_recipient_ctx(kind, user_doc, phone, label)
                    components = _build_components(
                        variables, ctx,
                        header_text=sc.get("header_text"),
                        header_media=sc.get("header_media"),
                        button_vars=sc.get("button_vars"),
                        button_specs=sc.get("button_specs"),
                    )
                else:
                    components = static_components
                try:
                    wr = await _wa_send_template(
                        phone, sc["template_name"], sc.get("language_code") or "fr", components,
                    )
                except Exception as exc:  # noqa: BLE001
                    wr = {"ok": False, "status": 0, "message_id": None, "error": str(exc)[:200]}
                log = {
                    "id": _uuid(),
                    "client_id": rid if kind == "client" else (sc.get("client_id") if kind == "contact" else None),
                    "sender_id": sc.get("created_by_id"),
                    "sender_label": sc.get("created_by_label"),
                    "to": phone,
                    "template_name": sc["template_name"],
                    "language_code": sc.get("language_code"),
                    "tracked_user_id": rid if kind == "tracked" else None,
                    "contact_id": rid if kind == "contact" else None,
                    "recipient_kind": kind,
                    "recipient_label": label,
                    "bulk": True,
                    "scheduled": True,
                    "schedule_id": sc["id"],
                    "ok": wr["ok"],
                    "status": wr["status"],
                    "message_id": wr["message_id"],
                    "error": wr.get("error"),
                    "created_at": _now(),
                }
                try:
                    await db.whatsapp_messages.insert_one(log.copy())
                except Exception:
                    pass
                # ---- SMS fallback for scheduled bulk on WA failure (kind="contact" only)
                fallback_status = None
                if (
                    not wr["ok"] and sc.get("sms_fallback") and kind == "contact"
                    and (sc.get("sms_fallback_message") or "").strip() and user_doc
                ):
                    sms_target = (user_doc.get("phone") or phone or "").strip()
                    if sms_target:
                        try:
                            # Reconstruct a contact-like dict for _build_sms_ctx
                            sms_ctx = _build_sms_ctx({
                                "name": user_doc.get("full_name"),
                                "company": user_doc.get("company"),
                                "phone": user_doc.get("phone"),
                                "whatsapp": phone,
                                "email": user_doc.get("email"),
                                "tags": [],
                                "unique_code": user_doc.get("client_code"),
                            })
                            sms_body = _personalize_sms(sc.get("sms_fallback_message") or "", sms_ctx)
                            sms_res = await _sms_dispatch(
                                sc.get("sms_fallback_provider") or "auto",
                                sms_target, sms_body, sc.get("sms_fallback_sender"),
                            )
                            sms_doc = {
                                "id": _uuid(),
                                "client_id": sc.get("client_id"),
                                "user_id": sc.get("created_by_id"),
                                "user_email": None,
                                "user_label": sc.get("created_by_label"),
                                "contact_id": rid,
                                "provider": sms_res.get("provider"),
                                "sender": sc.get("sms_fallback_sender"),
                                "msisdn": sms_target,
                                "msisdn_digits": "".join(ch for ch in sms_target if ch.isdigit()),
                                "message": sms_body, "length": len(sms_body),
                                "status": sms_res.get("status"),
                                "api_message": sms_res.get("api_message"),
                                "http_status": sms_res.get("http_status"),
                                "raw_response": sms_res.get("raw_response"),
                                "bulk": True,
                                "wa_fallback": True,
                                "schedule_id": sc["id"],
                                "created_at": _now(),
                            }
                            await db.sms_messages.insert_one(sms_doc.copy())
                            fallback_status = "ok" if sms_res.get("ok") else "failed"
                        except Exception as exc:  # noqa: BLE001
                            fallback_status = f"err:{str(exc)[:80]}"
                results.append({
                    "label": label, "phone": phone, "kind": kind,
                    "ok": wr["ok"], "status": wr["status"],
                    "message_id": wr["message_id"], "error": wr.get("error"),
                    "fallback": fallback_status,
                })
            sent_ok = sum(1 for x in results if x["ok"])
            final_status = "done" if sent_ok > 0 or not results else "failed"
            # Iter35a — surface a human-readable reason when the whole batch failed
            # so the user can debug from the UI (was previously a silent "failed"
            # without any reason in result_summary).
            top_error = None
            if final_status == "failed":
                if results:
                    first_err = next((x.get("error") for x in results if not x.get("ok") and x.get("error")), None)
                    if first_err:
                        top_error = first_err
                    else:
                        top_error = f"Tous les envois ont échoué ({len(results)}/{len(results)})"
                elif skipped:
                    top_error = f"Aucun destinataire valide ({len(skipped)} ignorés)"
                else:
                    top_error = "Aucun destinataire dans la programmation"
            await db.whatsapp_schedules.update_one(
                {"id": sc["id"]},
                {"$set": {
                    "status": final_status,
                    "result_summary": {
                        "requested": len(sc.get("recipients") or []),
                        "sent_ok": sent_ok,
                        "sent_ko": len(results) - sent_ok,
                        "skipped_count": len(skipped),
                        "skipped": skipped,
                        "results": results,
                        "error": top_error,
                    },
                    "finished_at": _now(),
                    "updated_at": _now(),
                }},
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("scheduled_whatsapp runner failed")
        # Release any schedule we may have left stuck in `running` so a retry can re-claim it
        try:
            await db.whatsapp_schedules.update_many(
                {"status": "running", "started_at": {"$lte": _now()}},
                {"$set": {
                    "status": "failed",
                    "result_summary": {"error": f"Crash interne du planificateur: {str(exc)[:200]}"},
                    "finished_at": _now(),
                    "updated_at": _now(),
                }},
            )
        except Exception:  # noqa: BLE001
            pass
