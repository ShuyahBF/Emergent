# server_parts/p18_abonnements_tickets.py — Abonnements, tickets d'intervention et leurs exports.
# Morceau de l'ancien server.py (lignes 23053 à 24990), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# Lot 54 — tickets partagés par client, clôture vers l'historique, sessions WhatsApp minutées
import tickets_clients as _tickets_clients  # noqa: E402

# ====================================================================
# SUBSCRIPTIONS MODULE — admin CRUD + public list + public order endpoint.
#
# • subscription_categories : 4 max categories (admin-defined groupings).
# • subscription_plans : individual offers shown on the public page.
#   Code format: FML + YYYY + 4-digit sequence reset every year.
# • subscription_orders : public-side leads. Triggers a WhatsApp
#   notification (+ optional automation webhook) when validated.
# ====================================================================
async def _next_subscription_code() -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"FML{year}"
    cursor = db.subscription_plans.find({"code": {"$regex": f"^{prefix}"}}, {"_id": 0, "code": 1}).sort("code", -1).limit(1)
    last = None
    async for d in cursor:
        last = d.get("code")
        break
    if last and len(last) == len(prefix) + 4:
        try:
            n = int(last[len(prefix):]) + 1
        except Exception:
            n = 1
    else:
        n = 1
    return f"{prefix}{n:04d}"


class SubscriptionCategoryCreate(BaseModel):
    label: str
    color: Optional[str] = "#0D6EFD"
    position: Optional[int] = 0
    animated: Optional[bool] = True


class SubscriptionCategoryUpdate(BaseModel):
    label: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None
    animated: Optional[bool] = None


class SubscriptionPlanCreate(BaseModel):
    name: str
    category_id: Optional[str] = None
    description: Optional[str] = ""
    price_monthly_xof: int = 0
    price_annual_xof: int = 0
    featured: Optional[bool] = False
    active: Optional[bool] = True
    automation_url: Optional[str] = ""
    whatsapp_notify_to: Optional[str] = ""


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[str] = None
    description: Optional[str] = None
    price_monthly_xof: Optional[int] = None
    price_annual_xof: Optional[int] = None
    featured: Optional[bool] = None
    active: Optional[bool] = None
    automation_url: Optional[str] = None
    whatsapp_notify_to: Optional[str] = None


class SubscriptionOrderCreate(BaseModel):
    plan_id: str
    period: str  # "monthly" | "annual"
    customer_name: str
    customer_email: Optional[str] = ""
    customer_phone: str
    message: Optional[str] = ""


@api.get("/admin/subscriptions/categories", tags=["Admin"])
async def admin_list_subscription_categories(user: dict = Depends(get_current_admin)):
    items = await db.subscription_categories.find({}, {"_id": 0}).sort("position", 1).to_list(20)
    return items


@api.post("/admin/subscriptions/categories", tags=["Admin"])
async def admin_create_subscription_category(payload: SubscriptionCategoryCreate, user: dict = Depends(get_current_admin)):
    n = await db.subscription_categories.count_documents({})
    if n >= 4:
        raise HTTPException(status_code=400, detail="Maximum 4 catégories autorisées")
    doc = {
        "id": _uuid(),
        "label": payload.label.strip()[:60],
        "color": (payload.color or "#0D6EFD")[:20],
        "position": int(payload.position or 0),
        "animated": bool(payload.animated if payload.animated is not None else True),
        "created_at": _now(),
    }
    await db.subscription_categories.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/subscriptions/categories/{cat_id}", tags=["Admin"])
async def admin_update_subscription_category(cat_id: str, payload: SubscriptionCategoryUpdate, user: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Aucune modification")
    await db.subscription_categories.update_one({"id": cat_id}, {"$set": update})
    doc = await db.subscription_categories.find_one({"id": cat_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    return doc


@api.delete("/admin/subscriptions/categories/{cat_id}", tags=["Admin"])
async def admin_delete_subscription_category(cat_id: str, user: dict = Depends(get_current_admin)):
    await db.subscription_categories.delete_one({"id": cat_id})
    await db.subscription_plans.update_many({"category_id": cat_id}, {"$set": {"category_id": None}})
    return {"ok": True}


@api.get("/admin/subscriptions/plans", tags=["Admin"])
async def admin_list_subscription_plans(user: dict = Depends(get_current_admin)):
    items = await db.subscription_plans.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@api.post("/admin/subscriptions/plans", tags=["Admin"])
async def admin_create_subscription_plan(payload: SubscriptionPlanCreate, user: dict = Depends(get_current_admin)):
    code = await _next_subscription_code()
    doc = {
        "id": _uuid(),
        "code": code,
        "name": payload.name.strip()[:120],
        "category_id": payload.category_id,
        "description": (payload.description or "").strip(),
        "price_monthly_xof": max(0, int(payload.price_monthly_xof or 0)),
        "price_annual_xof": max(0, int(payload.price_annual_xof or 0)),
        "featured": bool(payload.featured),
        "active": bool(payload.active if payload.active is not None else True),
        "automation_url": (payload.automation_url or "").strip(),
        "whatsapp_notify_to": (payload.whatsapp_notify_to or "").strip(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.subscription_plans.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/subscriptions/plans/{plan_id}", tags=["Admin"])
async def admin_update_subscription_plan(plan_id: str, payload: SubscriptionPlanUpdate, user: dict = Depends(get_current_admin)):
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Aucune modification")
    update["updated_at"] = _now()
    await db.subscription_plans.update_one({"id": plan_id}, {"$set": update})
    doc = await db.subscription_plans.find_one({"id": plan_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Formule introuvable")
    return doc


@api.delete("/admin/subscriptions/plans/{plan_id}", tags=["Admin"])
async def admin_delete_subscription_plan(plan_id: str, user: dict = Depends(get_current_admin)):
    await db.subscription_plans.delete_one({"id": plan_id})
    return {"ok": True}


@api.get("/admin/subscriptions/orders", tags=["Admin"])
async def admin_list_subscription_orders(user: dict = Depends(get_current_admin)):
    items = await db.subscription_orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@api.get("/public/subscriptions", tags=["Public"])
async def public_list_subscriptions():
    """Public : renvoie les plans actifs groupés par catégorie (max 4 catégories)."""
    cats = await db.subscription_categories.find({}, {"_id": 0}).sort("position", 1).to_list(4)
    plans = await db.subscription_plans.find({"active": True}, {"_id": 0, "automation_url": 0, "whatsapp_notify_to": 0}).sort("created_at", 1).to_list(100)
    return {"categories": cats, "plans": plans}


@api.post("/public/subscriptions/order", tags=["Public"])
async def public_create_subscription_order(payload: SubscriptionOrderCreate, request: Request):
    plan = await db.subscription_plans.find_one({"id": payload.plan_id, "active": True}, {"_id": 0})
    if not plan:
        raise HTTPException(status_code=404, detail="Formule introuvable ou désactivée")
    if payload.period not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="Période invalide")
    if not (payload.customer_name or "").strip() or not (payload.customer_phone or "").strip():
        raise HTTPException(status_code=400, detail="Nom et téléphone requis")
    amount = plan.get("price_monthly_xof") if payload.period == "monthly" else plan.get("price_annual_xof")
    order = {
        "id": _uuid(),
        "plan_id": payload.plan_id,
        "plan_code": plan.get("code"),
        "plan_name": plan.get("name"),
        "period": payload.period,
        "amount_xof": amount,
        "customer_name": payload.customer_name.strip()[:120],
        "customer_email": (payload.customer_email or "").strip()[:200],
        "customer_phone": payload.customer_phone.strip()[:30],
        "message": (payload.message or "").strip()[:1000],
        "ip": _client_ip_from_request(request),
        "status": "pending",
        "created_at": _now(),
    }
    await db.subscription_orders.insert_one(order.copy())
    order.pop("_id", None)

    notify_to = (plan.get("whatsapp_notify_to") or "").strip()
    if notify_to:
        try:
            text = (
                f"🆕 Nouvelle souscription\n"
                f"Formule : {plan.get('name')} ({plan.get('code')})\n"
                f"Période : {'Mensuel' if payload.period == 'monthly' else 'Annuel'} — {amount:,} XOF\n"
                f"Client : {order['customer_name']}\n"
                f"Téléphone : {order['customer_phone']}\n"
                f"Email : {order['customer_email'] or '—'}\n"
                f"Message : {order['message'] or '—'}"
            )
            await _wa_send_text(notify_to, text)
            await db.subscription_orders.update_one({"id": order["id"]}, {"$set": {"status": "notified"}})
        except Exception as exc:  # noqa: BLE001
            logger.warning("subscription wa-notify failed: %s", exc)

    auto_url = (plan.get("automation_url") or "").strip()
    if auto_url:
        try:
            async with httpx.AsyncClient(timeout=8) as http:
                await http.post(auto_url, json=order)
        except Exception as exc:  # noqa: BLE001
            logger.warning("subscription automation webhook failed: %s", exc)

    # Auto-create a public PawaPay payment link so the visitor can pay
    # immediately after submitting. Best-effort: skipped if PawaPay is not
    # enabled, or if amount is 0, or if no admin client is configured.
    pay_link_url = None
    pay_link_slug = None
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        if s.get("pawapay_enabled") and amount and int(amount) > 0:
            primary = await db.users.find_one({"role": "superviseur"}, {"_id": 0, "id": 1})
            if not primary:
                # Fallback to first admin so the link still gets created in
                # development / single-admin setups.
                primary = await db.users.find_one({"role": "admin"}, {"_id": 0, "id": 1})
            client_scope = (primary or {}).get("id")
            if client_scope:
                slug = None
                for _ in range(8):
                    cand = _gen_slug(8)
                    if not await db.payment_links.find_one({"slug": cand}):
                        slug = cand
                        break
                if slug:
                    link_doc = {
                        "id": _uuid(),
                        "slug": slug,
                        "client_id": client_scope,
                        "owner_user_id": None,
                        "owner_email": None,
                        "owner_label": "Souscription publique",
                        "label": f"Souscription : {plan.get('name')} ({'mensuel' if payload.period == 'monthly' else 'annuel'})",
                        "amount": float(amount),
                        "currency": "XOF",
                        "description": f"Code {plan.get('code')} — {payload.customer_name.strip()[:60]}",
                        "allowed_mnos": list(DEFAULT_CLIENT_PAWAPAY_MNOS),
                        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                        "max_uses": 1,
                        "uses_count": 0,
                        "disabled": False,
                        "subscription_order_id": order["id"],
                        "subscription_plan_code": plan.get("code"),
                        "prefill_phone": order["customer_phone"],
                        "prefill_name": order["customer_name"],
                        "created_at": _now(),
                        "updated_at": _now(),
                    }
                    await db.payment_links.insert_one(link_doc.copy())
                    pay_link_slug = slug
                    pay_link_url = f"/pay/{slug}"
                    await db.subscription_orders.update_one(
                        {"id": order["id"]},
                        {"$set": {"payment_link_slug": slug, "payment_link_url": pay_link_url}},
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning("subscription pay-link creation failed: %s", exc)

    return {
        "ok": True,
        "order_id": order["id"],
        "next_step": "Notre équipe vous contactera sous 24h pour finaliser votre souscription.",
        "payment_link_slug": pay_link_slug,
        "payment_link_url": pay_link_url,
    }



@app.on_event("shutdown")
async def on_shutdown():
    try:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        pass



# ====================================================================
# Iter35o — Support tickets (intervention tickets opened from WA chat)
#
# • Numérotation par client: TKT-YYYY-NNNN, séquence remise à zéro par
#   année et par client_id. Stockée dans db.counters
#   (id="tickets_{client_id}_{year}").
# • Un seul ticket "non clôturé" par contact à la fois — la création
#   d'un nouveau ticket est bloquée tant que le précédent n'est pas
#   en statut "done" ou "cancelled".
# • Statuts: open (en attente) → in_progress → done|cancelled,
#   et suspended à tout moment (avant clôture).
# • Notifications WhatsApp via templates Meta paramétrables dans
#   /admin/settings (wa_template_ticket_open, wa_template_ticket_close).
# ====================================================================
TICKET_OPEN_STATUSES = {"open", "in_progress", "suspended"}
TICKET_CLOSED_STATUSES = {"done", "cancelled"}
TICKET_ALL_STATUSES = TICKET_OPEN_STATUSES | TICKET_CLOSED_STATUSES
# Iter37c — Cost fields are restricted to elevated viewers (admin/superviseur/moderateur)
TICKET_COST_FIELDS = (
    "cost_amount", "cost_mode", "cost_hourly_rate", "cost_flat_rate",
    "cost_currency", "active_hours",
)


def _strip_ticket_cost_fields(ticket: dict) -> dict:
    """Remove cost fields in-place (idempotent) and return the same dict."""
    if not isinstance(ticket, dict):
        return ticket
    for f in TICKET_COST_FIELDS:
        ticket.pop(f, None)
    return ticket


# Iter38p — Orphan-ticket auto-cleanup.
#
# Scenario reported by user (TKT-2026-0001 / Diane): a support ticket created
# from a WhatsApp conversation persists in `support_tickets` with status=open
# even after its contact (`directory_contacts` / `contacts`) was deleted. This
# blocks any future ticket creation for that contact because the open-ticket
# check raises 409 ("ticket encore ouvert"). The orphan also lingers in
# `/me/contacts/{cid}/active-ticket` responses, causing the chat UI to show a
# stale "View ticket" link.
#
# Fix: when an open ticket is found whose contact no longer exists in either
# `directory_contacts` or `contacts`, auto-close it with
# outcome="orphan_contact_deleted" and return it as the cleaned-up record so
# downstream logic can treat the slot as free.
async def _auto_close_orphan_ticket_if_contact_missing(
    ticket: dict, *, actor_id: Optional[str] = None
) -> bool:
    """Close `ticket` as an orphan if its contact_id no longer resolves.

    Returns True when the ticket was closed (orphan), False otherwise."""
    if not ticket or ticket.get("status") not in TICKET_OPEN_STATUSES:
        return False
    cid = ticket.get("contact_id")
    if not cid:
        return False
    contact_exists = await db.directory_contacts.find_one(
        {"id": cid}, {"_id": 0, "id": 1}
    )
    if not contact_exists:
        contact_exists = await db.contacts.find_one(
            {"id": cid}, {"_id": 0, "id": 1}
        )
    if contact_exists:
        return False
    now_iso = _now()
    await db.support_tickets.update_one(
        {"id": ticket["id"]},
        {"$set": {
            "status": "closed",
            "closed_at": now_iso,
            "closed_by_id": actor_id or "system",
            "closed_by_label": "Système (contact supprimé)",
            "outcome": "orphan_contact_deleted",
            "resolution_note": (
                "Fermeture automatique : le contact lié à ce ticket a été supprimé "
                "de la base de données."
            ),
            "updated_at": now_iso,
        }},
    )
    try:
        await _log_activity(
            client_id=ticket.get("client_id", ""),
            kind="ticket", action="orphan_closed",
            label=f"{ticket.get('number', '?')} — contact supprimé",
            actor={"id": actor_id or "system", "full_name": "Système"},
            target_id=ticket.get("id"),
        )
    except Exception:
        pass
    return True


async def _next_ticket_number(client_id: str) -> str:
    """Iter37c — Atomic counter: {CLIENT_SLUG}-YYYY-NNNN (chronological per client).
    The client slug is read from db.users (company || full_name) at most once
    per call, slugified. Falls back to the legacy 'TKT' prefix if the slug
    cannot be resolved.
    """
    year = datetime.now(timezone.utc).year
    counter_id = f"tickets_{client_id}_{year}"
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    seq = (res or {}).get("seq", 1)
    # Resolve a human-friendly prefix from the client (tenant) user doc
    prefix = "TKT"
    try:
        client_doc = await db.users.find_one({"id": client_id}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        raw = client_doc.get("company") or client_doc.get("full_name") or ""
        slug = re.sub(r"[^A-Za-z0-9]+", " ", str(raw)).strip().upper().replace(" ", " ")
        slug = re.sub(r"\s+", " ", slug)[:20].strip()
        if slug:
            prefix = slug
    except Exception:  # noqa: BLE001
        pass
    return f"{prefix}-{year}-{seq:04d}"


def _ticket_components(number: str, motif: str = "", duration: str = "") -> list:
    """Build Meta template `components` array for a ticket-open/close template.
    Body variables: {1}=ticket number, {2}=motif OR duration."""
    second_var = motif if motif else duration
    return [{
        "type": "body",
        "parameters": [
            {"type": "text", "text": number[:60]},
            {"type": "text", "text": (second_var or "—")[:200]},
        ],
    }]


def _format_ticket_duration(opened_iso: str, closed_iso: str) -> str:
    try:
        o = datetime.fromisoformat(opened_iso.replace("Z", "+00:00"))
        c = datetime.fromisoformat(closed_iso.replace("Z", "+00:00"))
        secs = int((c - o).total_seconds())
        if secs < 60:
            return f"{secs} s"
        if secs < 3600:
            return f"{secs // 60} min"
        if secs < 86400:
            h = secs // 3600
            m = (secs % 3600) // 60
            return f"{h} h {m} min" if m else f"{h} h"
        d = secs // 86400
        h = (secs % 86400) // 3600
        return f"{d} j {h} h" if h else f"{d} j"
    except Exception:
        return "—"


async def _ticket_scope_for_user(user: dict) -> Dict[str, Any]:
    """Mongo query filter restricting tickets to the user's effective client scope.

    Iter43-fix24az-l (2026-02-26) — Cross-tenant leak fix.
    Only the SAWALI super-admin (SUPER_ADMIN_EMAIL) sees ALL tenants' tickets.
    Client-admin/superviseur (e.g. ISISPHARMA admin) are scoped to their own
    tenant via `_resolve_visible_client_ids` (matches on company/parent_client_id).

    2026-02 fork (P1) — Own-creation fallback. A user with a `company` that
    differs from the target client's tenant (e.g. `support@sawalismartsystems.com`
    creating tickets against various client companies) could not see the tickets
    they opened themselves because the filter matched on `client_id ∈ scope`
    only. We now always OR-merge a `opened_by_id = user.id` clause so a user
    ALWAYS sees the tickets they authored — regardless of the ticket's client_id.

    Note : moderators can SEE all tickets within their tenant (they pilot the
    interventions) but cannot DELETE them — the delete endpoint enforces that
    via `_can_delete_records()` which only allows admin/superviseur.
    """
    if _is_super_admin(user):
        return {}
    scope = await _resolve_visible_client_ids(user)
    scope_clause = {"client_id": {"$in": scope}} if scope else {"client_id": "__none__"}
    own_clauses = [{"opened_by_id": user.get("id")}, {"owner_id": user.get("id")}]
    # Lot 58.3 — les tickets du « Support Loois » (créés à l'acceptation d'une session) sont visibles de TOUTE
    # l'équipe du support (administrateurs + comptes de LOOIS_SUPPORT_ADMIN_EMAIL), quel que soit le client
    try:
        from routes import support_loois as _support_loois
        if user.get("role") == "admin" or _support_loois.est_compte_support(user):
            own_clauses.append({"source": "support_loois"})
    except Exception:  # noqa: BLE001
        pass
    return {"$or": [scope_clause, *own_clauses]}


@api.post("/me/contacts/{cid}/ticket", tags=["Portail Client"])
async def me_open_ticket(
    cid: str,
    payload: TicketOpenPayload,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Open a new support ticket from the WhatsApp chat window. Blocks if
    the contact already has a non-closed ticket (open|in_progress|suspended)."""
    motif = (payload.motif or "").strip()
    if not motif:
        raise HTTPException(status_code=400, detail="Le motif est obligatoire.")
    if len(motif) > 200:
        raise HTTPException(status_code=400, detail="Le motif doit faire au maximum 200 caractères.")

    scope_filter = await _ticket_scope_for_user(user)
    # Iter35o-fix — Contacts WhatsApp/manuels sont stockés dans `directory_contacts`
    # (la collection `contacts` est utilisée par l'ancien CRM admin). Tomber en
    # rétrocompat sur `contacts` si rien n'est trouvé.
    contact = (
        await db.directory_contacts.find_one({**scope_filter, "id": cid}, {"_id": 0})
        or await db.contacts.find_one({**scope_filter, "id": cid}, {"_id": 0})
    )
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable.")
    # Iter36k — Le client lié est désormais EXPLICITEMENT choisi via le
    # dropdown frontend (TicketOpenPayload.client_id). Si absent, on
    # n'auto-hérite plus de contact.client_id (qui était souvent erroné).
    requested_client_id = (payload.client_id or "").strip()
    if not requested_client_id:
        raise HTTPException(
            status_code=400,
            detail="Veuillez sélectionner le client lié à ce ticket.",
        )
    # Validate that the requested client_id is reachable by this user
    # (admins / superviseur / moderateur : any user ; otherwise: own scope only).
    if _is_elevated_creator(user):
        owner = await db.users.find_one(
            {"id": requested_client_id, "role": {"$in": ["client", "superviseur", "admin"]}},
            {"_id": 0, "id": 1},
        )
    else:
        effective_id = user.get("parent_client_id") or user["id"]
        owner = (
            {"id": effective_id} if requested_client_id == effective_id else None
        )
    if not owner:
        raise HTTPException(
            status_code=403,
            detail="Client lié non autorisé pour cet utilisateur.",
        )
    client_id = requested_client_id
    # Block when the contact has an already-open ticket
    # Iter38q — exclude archived tickets from this check
    existing = await db.support_tickets.find_one(
        {
            "contact_id": cid,
            "status": {"$in": list(TICKET_OPEN_STATUSES)},
            "archived_at": {"$in": [None, ""]},
        },
        {"_id": 0, "id": 1, "number": 1, "status": 1, "opened_at": 1, "contact_id": 1, "client_id": 1},
    )
    # Lot 54 — Ticket valable pour TOUT le client lié : si un ticket est ouvert pour ce client
    # (via n'importe lequel de ses contacts), le contact y est rattaché au lieu d'en créer un autre.
    if not existing:
        partage = await _tickets_clients.ticket_ouvert_du_client(client_id)
        if partage and payload.force_release and _is_elevated_creator(user):
            existing = partage   # clôture forcée ci-dessous, comme pour le ticket du contact
        elif partage:
            partage = await _tickets_clients.rattacher_contact(partage, cid, par=user)
            return {"ok": True, "ticket": partage, "rattache": True,
                    "notification": {"sent": False, "error": None},
                    "message": f"Le ticket {partage.get('number')} est déjà ouvert pour ce client : "
                               "ce contact y est rattaché."}
    if existing:
        # Iter38p — Auto-cleanup: if the "blocking" open ticket actually
        # points to a contact that no longer exists, close it as orphan and
        # proceed with the new ticket creation. This unblocks the case where
        # an old contact was deleted but its ticket survived.
        was_orphan = await _auto_close_orphan_ticket_if_contact_missing(
            existing, actor_id=user.get("id"),
        )
        if not was_orphan:
            # Iter38p — Optional force-release for elevated users (admin /
            # superviseur / moderateur). When the client passes
            # `force_release: true`, close the blocking ticket as
            # `force_released` and proceed. This is the explicit escape hatch
            # for production stuck-ticket cases like TKT-2026-0001.
            if payload.force_release and _is_elevated_creator(user):
                now_iso = _now()
                await db.support_tickets.update_one(
                    {"id": existing["id"]},
                    {"$set": {
                        "status": "closed",
                        "closed_at": now_iso,
                        "closed_by_id": user["id"],
                        "closed_by_label": user.get("full_name") or user.get("email"),
                        "outcome": "force_released",
                        "resolution_note": (
                            "Clôture forcée pour débloquer la création d'un nouveau ticket "
                            "(orphelin ou bloqué)."
                        ),
                        "updated_at": now_iso,
                    }},
                )
                try:
                    await _log_activity(
                        client_id=existing.get("client_id", ""),
                        kind="ticket", action="force_released",
                        label=f"{existing.get('number', '?')} — clôture forcée",
                        actor=user, target_id=existing.get("id"),
                    )
                except Exception:
                    pass
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"Le ticket {existing['number']} est encore ouvert (statut: {existing['status']}). Clôturez-le avant d'en créer un nouveau.",
                    headers={"X-Blocking-Ticket-Id": existing["id"], "X-Blocking-Ticket-Number": existing["number"]},
                )

    number = await _next_ticket_number(client_id)
    now_iso = _now()
    ticket = {
        "id": _uuid(),
        "number": number,
        "client_id": client_id,
        "contact_id": cid,
        "contact_name": contact.get("name"),
        "contact_phone": contact.get("whatsapp") or contact.get("phone"),
        "motif": motif,
        "status": "open",
        "notes": None,
        "opened_at": now_iso,
        "opened_by_id": user["id"],
        "opened_by_label": user.get("full_name") or user.get("email"),
        "closed_at": None,
        "closed_by_id": None,
        "closed_by_label": None,
        "outcome": None,
        "resolution_note": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        # Lot 54 — contacts couverts, session WhatsApp minutée, validité (clients non contractuels)
        "contact_ids": [cid],
        **_tickets_clients.champs_creation(await _tickets_clients.lire_client(client_id), now_iso),
    }
    await db.support_tickets.insert_one(ticket.copy())

    # Iter35p — Activity feed
    try:
        await _log_activity(
            client_id=client_id, kind="ticket", action="created",
            label=f"{number} — {motif[:80]}", actor=user, target_id=ticket["id"],
        )
    except Exception:
        pass

    # Iter38r-fix9w — Home Assistant voice notification
    await _voice_notify(client_id, "ticket_created", {
        "ticket_code": number,
        "subject": motif,
        "client_name": contact.get("name") or "",
        "priority": ticket.get("priority") or "normal",
    })

    # Optional WhatsApp notification (template) — best-effort, never blocks
    s = await db.settings.find_one({"_id": "global"}) or {}
    notify = bool(s.get("notify_on_ticket_open", True))
    tpl_name = (s.get("wa_template_ticket_open") or "").strip()
    notification = {"sent": False, "error": None}
    if notify and tpl_name and ticket["contact_phone"]:
        comps = _ticket_components(number, motif=motif)
        try:
            wr = await _wa_send_template(
                ticket["contact_phone"], tpl_name,
                (s.get("wa_template_ticket_language") or "fr").strip() or "fr",
                comps,
            )
            notification = {"sent": bool(wr.get("ok")), "error": wr.get("error")}
        except Exception as exc:  # noqa: BLE001
            notification = {"sent": False, "error": str(exc)[:200]}

    ticket.pop("_id", None)
    return {"ok": True, "ticket": ticket, "notification": notification}


# Iter38r-fix9o (Item 6) — Quick-ticket creation from the floating bubble.
# Difference vs `/me/contacts/{cid}/ticket`: no contact_id is required;
# the optional `contact_phone` is auto-matched to an existing
# `directory_contacts` row OR a lightweight contact is created on the fly.
DEFAULT_INTERVENTION_REASONS: List[str] = [
    "Logiciel bloqué",
    "Erreur d'enregistrement",
    "Demande de formation",
    "Demande d'évolution",
    "Problème d'impression",
    "Problème réseau / connexion",
    "Sauvegarde / restauration",
    "Configuration matérielle",
    "Autre (préciser)",
]


@api.get("/me/intervention-reasons", tags=["Portail Client"])
async def me_intervention_reasons(user: dict = Depends(get_current_user)):
    """Return the (admin-configurable) list of preset reasons used by the
    floating TicketsBubble. Stored at `settings.global.intervention_reasons`.
    Falls back to `DEFAULT_INTERVENTION_REASONS` when none configured."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "intervention_reasons": 1}) or {}
    raw = s.get("intervention_reasons") or []
    out: List[Dict[str, str]] = []
    if isinstance(raw, list) and raw:
        for idx, x in enumerate(raw):
            label = (str(x) or "").strip() if not isinstance(x, dict) else (str(x.get("label") or "").strip())
            if label:
                out.append({"id": f"r{idx}", "label": label})
    if not out:
        out = [{"id": f"r{i}", "label": lab} for i, lab in enumerate(DEFAULT_INTERVENTION_REASONS)]
    return {"items": out}


class QuickTicketPayload(BaseModel):
    client_id: str
    reason: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_whatsapp: Optional[str] = None
    incident_at: Optional[str] = None
    software: Optional[str] = None
    notes: Optional[str] = None
    attach_wa_sms_history: Optional[bool] = False
    # Iter43 — Partage tenant
    shared_with_tenant: Optional[bool] = None
    editable_by_tenant: Optional[bool] = None

    # Convention SAWALI (bulle flottante "Nouveau ticket") : mêmes champs texte
    # que le ticket créé depuis Contacts.jsx, toujours en MAJUSCULES.
    @field_validator("reason", "contact_name", "software", "notes", mode="before")
    @classmethod
    def _uppercase_text_fields(cls, v):
        return _upper(v)


@api.post("/me/tickets", tags=["Portail Client"])
async def me_create_ticket_quick(
    payload: QuickTicketPayload,
    user: dict = Depends(get_current_user),
):
    """Iter38r-fix9o — Quick-create a ticket from the floating bubble.
    Behavior:
      - Validates `client_id` is reachable by the caller.
      - Generates a sequential ticket number for that tenant.
      - Resolves or creates a lightweight contact (directory_contacts) from
        `contact_phone` (or `contact_name`) when provided. No contact row
        is created if neither is given.
      - Sends the configured WA template (notify_on_ticket_open) when a
        phone is present.
      - Persists `software`, `incident_at` and `attach_wa_sms_history` flag
        directly on the ticket doc (free-form fields).
    """
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Le motif est obligatoire.")
    if len(reason) > 200:
        raise HTTPException(status_code=400, detail="Le motif doit faire au maximum 200 caractères.")
    requested_client_id = (payload.client_id or "").strip()
    if not requested_client_id:
        raise HTTPException(status_code=400, detail="Veuillez sélectionner le client lié.")

    # Authorize the client_id (same rules as `/me/contacts/{cid}/ticket`)
    if _is_elevated_creator(user):
        owner = await db.users.find_one(
            {"id": requested_client_id, "role": {"$in": ["client", "superviseur", "admin"]}},
            {"_id": 0, "id": 1},
        )
    else:
        effective_id = user.get("parent_client_id") or user["id"]
        owner = {"id": effective_id} if requested_client_id == effective_id else None
    if not owner:
        raise HTTPException(status_code=403, detail="Client lié non autorisé pour cet utilisateur.")
    client_id = requested_client_id

    # Optional: resolve/create the contact (by phone preferred, then by name)
    contact = None
    cname = (payload.contact_name or "").strip() or None
    cphone = (payload.contact_phone or "").strip() or None
    cwhatsapp = (payload.contact_whatsapp or "").strip() or None
    # If only WhatsApp was provided, treat it as the lookup phone too
    if not cphone and cwhatsapp:
        cphone = cwhatsapp
    phone_digits = "".join(ch for ch in (cphone or "") if ch.isdigit())
    if phone_digits:
        contact = await db.directory_contacts.find_one(
            {"client_id": client_id, "phone_digits": phone_digits},
            {"_id": 0},
        )
        if not contact:
            new_cid = str(uuid.uuid4())
            contact = {
                "id": new_cid,
                "client_id": client_id,
                "owner_id": user["id"],
                "owner_label": user.get("full_name") or user.get("email"),
                "name": cname or f"+{phone_digits}",
                "phone": cphone,
                "whatsapp": cwhatsapp or (cphone if cphone.startswith("+") else f"+{phone_digits}"),
                "phone_digits": phone_digits,
                "tags": ["Ticket bubble"],
                "shared": True,
                "source": "tickets_bubble",
                "created_at": _now(),
                "updated_at": _now(),
            }
            await db.directory_contacts.insert_one(contact.copy())
            contact.pop("_id", None)
    elif cname:
        # Name-only contact placeholder (no WA template will fire)
        contact = {"id": None, "name": cname, "phone": None, "whatsapp": None}

    # Lot 54 — un ticket ouvert couvre tous les contacts du client : pas de second ticket.
    partage = await _tickets_clients.ticket_ouvert_du_client(client_id)
    if partage:
        partage = await _tickets_clients.rattacher_contact(partage, (contact or {}).get("id"), par=user)
        return {"ok": True, "id": partage["id"], "ticket": partage, "rattache": True,
                "notification": {"sent": False, "error": None},
                "message": f"Le ticket {partage.get('number')} est déjà ouvert pour ce client : "
                           "la demande y est rattachée."}

    number = await _next_ticket_number(client_id)
    now_iso = _now()
    ticket = {
        "id": _uuid(),
        "number": number,
        "client_id": client_id,
        "contact_id": (contact or {}).get("id"),
        "contact_name": (contact or {}).get("name") or cname,
        "contact_phone": (contact or {}).get("whatsapp") or (contact or {}).get("phone") or cphone,
        "motif": reason,
        "status": "open",
        "notes": (payload.notes or "").strip() or None,
        "software": (payload.software or "").strip() or None,
        "incident_at": (payload.incident_at or "").strip() or None,
        "attach_wa_sms_history": bool(payload.attach_wa_sms_history),
        "source": "tickets_bubble",
        "opened_at": now_iso,
        "opened_by_id": user["id"],
        "opened_by_label": user.get("full_name") or user.get("email"),
        # Iter43 — Snapshot société/rattachement + partage tenant
        "owner_id": user["id"],
        "owner_company": (user.get("company") or "").strip() or None,
        "owner_parent_client_id": user.get("parent_client_id"),
        "shared_with_tenant": bool(payload.shared_with_tenant),
        "editable_by_tenant": bool(payload.editable_by_tenant),
        "closed_at": None,
        "closed_by_id": None,
        "closed_by_label": None,
        "outcome": None,
        "resolution_note": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        # Lot 54 — contacts couverts, session WhatsApp minutée, validité (clients non contractuels)
        "contact_ids": [c for c in [(contact or {}).get("id")] if c],
        **_tickets_clients.champs_creation(await _tickets_clients.lire_client(client_id), now_iso),
    }
    await db.support_tickets.insert_one(ticket.copy())
    try:
        await _log_activity(
            client_id=client_id, kind="ticket", action="created",
            label=f"{number} — {reason[:80]}", actor=user, target_id=ticket["id"],
        )
    except Exception:
        pass

    # Iter38r-fix9w — Home Assistant voice notification (tickets bubble path)
    await _voice_notify(client_id, "ticket_created", {
        "ticket_code": number,
        "subject": reason,
        "client_name": ticket.get("contact_name") or "",
        "priority": ticket.get("priority") or "normal",
    })

    # WA template (best-effort)
    s = await db.settings.find_one({"_id": "global"}) or {}
    notify = bool(s.get("notify_on_ticket_open", True))
    tpl_name = (s.get("wa_template_ticket_open") or "").strip()
    notification = {"sent": False, "error": None}
    if notify and tpl_name and ticket["contact_phone"]:
        comps = _ticket_components(number, motif=reason)
        try:
            wr = await _wa_send_template(
                ticket["contact_phone"], tpl_name,
                (s.get("wa_template_ticket_language") or "fr").strip() or "fr",
                comps,
            )
            notification = {"sent": bool(wr.get("ok")), "error": wr.get("error")}
        except Exception as exc:  # noqa: BLE001
            notification = {"sent": False, "error": str(exc)[:200]}

    ticket.pop("_id", None)
    return {"ok": True, "id": ticket["id"], "ticket": ticket, "notification": notification}




@api.get("/me/tickets", tags=["Portail Client"])
async def me_list_tickets(
    status: Optional[str] = None,  # one of TICKET_ALL_STATUSES, or "open_all" for any non-closed
    contact_id: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(get_current_user),
):
    scope_filter = await _ticket_scope_for_user(user)
    q: Dict[str, Any] = {**scope_filter}
    # Iter38q — exclude archived tickets (corbeille) from normal listings
    q["archived_at"] = {"$in": [None, ""]}
    if contact_id:
        q["contact_id"] = contact_id
    if status:
        if status == "open_all":
            q["status"] = {"$in": list(TICKET_OPEN_STATUSES)}
        elif status in TICKET_ALL_STATUSES:
            q["status"] = status
    # Iter43 — Cross-tenant share: also include tickets created by colleagues
    # (same société/rattachement) flagged shared_with_tenant=True.
    try:
        from routes.tenant_sharing import resolve_visible_owner_ids  # noqa: E402
        visible_owner_ids = await resolve_visible_owner_ids(db, user)
        colleague_ids = [oid for oid in visible_owner_ids if oid != user["id"]]
    except Exception:
        colleague_ids = []
    if colleague_ids:
        share_clause = {
            "owner_id": {"$in": colleague_ids},
            "shared_with_tenant": True,
            "archived_at": {"$in": [None, ""]},
        }
        if contact_id:
            share_clause["contact_id"] = contact_id
        if status:
            if status == "open_all":
                share_clause["status"] = {"$in": list(TICKET_OPEN_STATUSES)}
            elif status in TICKET_ALL_STATUSES:
                share_clause["status"] = status
        q = {"$or": [q, share_clause]}
    items = await db.support_tickets.find(q, {"_id": 0}).sort("opened_at", -1).to_list(min(max(limit, 1), 1000))
    # Iter37c — Hide cost fields from non-elevated viewers
    if not _is_elevated_creator(user):
        for _t in items:
            _strip_ticket_cost_fields(_t)
    # Iter35r — Enrich each ticket with client_label / company_label + age &
    # active-pause durations so the UI can spotlight "dormant" tickets.
    client_ids = list({(t.get("client_id") or "") for t in items if t.get("client_id")})
    clients_map: Dict[str, Dict[str, Any]] = {}
    if client_ids:
        async for c in db.users.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "email": 1}):
            clients_map[c["id"]] = c
    now_dt = datetime.now(timezone.utc)
    for t in items:
        c = clients_map.get(t.get("client_id"))
        t["client_label"] = (c or {}).get("full_name") or (c or {}).get("email")
        t["company_label"] = (c or {}).get("company")
        # Age = depuis l'ouverture jusqu'à aujourd'hui (si non clôturé) ou clôture sinon
        try:
            o = datetime.fromisoformat((t.get("opened_at") or "").replace("Z", "+00:00"))
            ref = (t.get("closed_at") or "").replace("Z", "+00:00")
            ref_dt = datetime.fromisoformat(ref) if ref else now_dt
            t["age_seconds"] = max(0, int((ref_dt - o).total_seconds()))
        except Exception:
            t["age_seconds"] = None
        # Pause cumulative — inclut le timer courant si statut=suspended
        total_pause = int(t.get("suspended_total_seconds") or 0)
        if t.get("status") == "suspended" and t.get("suspended_started_at"):
            try:
                s_dt = datetime.fromisoformat(t["suspended_started_at"].replace("Z", "+00:00"))
                total_pause += max(0, int((now_dt - s_dt).total_seconds()))
            except Exception:
                pass
        t["pause_seconds"] = total_pause
    return items


@api.get("/me/tickets/pending-count", tags=["Portail Client"])
async def me_tickets_pending_count(user: dict = Depends(get_current_user)):
    """Renvoie le nombre de tickets non-clos dans le scope de l'utilisateur.
    Used by the sidebar/dashboard badges."""
    scope_filter = await _ticket_scope_for_user(user)
    # Iter38q — exclude archived tickets from counters
    q = {**scope_filter, "status": {"$in": list(TICKET_OPEN_STATUSES)}, "archived_at": {"$in": [None, ""]}}
    count = await db.support_tickets.count_documents(q)
    by_status: Dict[str, int] = {}
    pipeline = [{"$match": q}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    async for row in db.support_tickets.aggregate(pipeline):
        by_status[row["_id"]] = row["n"]
    return {"count": count, "by_status": by_status}


@api.patch("/me/tickets/{tid}", tags=["Portail Client"])
async def me_update_ticket(
    tid: str,
    payload: TicketUpdatePayload,
    user: dict = Depends(get_current_user),
):
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    # Iter38q — Archived tickets are read-only (corbeille)
    if ticket.get("archived_at"):
        raise HTTPException(status_code=409, detail="Ticket dans la corbeille — modification interdite.")
    if ticket["status"] in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail=f"Ticket déjà clôturé ({ticket['status']}). Réouverture interdite.")
    update: Dict[str, Any] = {}
    if payload.status is not None:
        if payload.status in TICKET_CLOSED_STATUSES:
            raise HTTPException(status_code=400, detail="Utilisez l'endpoint /close pour clôturer un ticket.")
        if payload.status not in TICKET_OPEN_STATUSES:
            raise HTTPException(status_code=400, detail=f"Statut invalide. Valeurs: {sorted(TICKET_OPEN_STATUSES)}")
        # Iter35r — Track cumulative pause time (status=suspended).
        # When transitioning INTO suspended → stamp suspended_started_at.
        # When transitioning OUT of suspended → add elapsed to suspended_total_seconds.
        old_status = ticket.get("status")
        if old_status != "suspended" and payload.status == "suspended":
            update["suspended_started_at"] = _now()
        elif old_status == "suspended" and payload.status != "suspended":
            started = ticket.get("suspended_started_at")
            if started:
                try:
                    s_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    elapsed = int((datetime.now(timezone.utc) - s_dt).total_seconds())
                    if elapsed > 0:
                        update["suspended_total_seconds"] = (ticket.get("suspended_total_seconds") or 0) + elapsed
                    update["suspended_started_at"] = None
                except Exception:
                    update["suspended_started_at"] = None
        update["status"] = payload.status
    if payload.motif is not None:
        m = payload.motif.strip()
        if not m or len(m) > 200:
            raise HTTPException(status_code=400, detail="Motif invalide (1..200 caractères).")
        update["motif"] = m
    if payload.notes is not None:
        update["notes"] = (payload.notes or "").strip()[:2000] or None
    # 0-4 (2026-02) — Reassign ticket to a different client/tenant.
    # Restricted to elevated roles (admin/superviseur/moderateur).
    if payload.client_id is not None:
        new_cid = (payload.client_id or "").strip()
        if not new_cid:
            raise HTTPException(status_code=400, detail="client_id requis pour réaffectation.")
        if not _is_elevated_creator(user):
            raise HTTPException(status_code=403, detail="Seuls admin/superviseur/modérateur peuvent réaffecter un ticket.")
        if new_cid != ticket.get("client_id"):
            new_client = await db.users.find_one({"id": new_cid}, {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1})
            if not new_client:
                raise HTTPException(status_code=404, detail="Client cible introuvable.")
            old_cid = ticket.get("client_id")
            update["client_id"] = new_cid
            update["client_company_snapshot"] = (new_client.get("company") or new_client.get("full_name") or new_client.get("email") or "")[:200]
            update["reassigned_from"] = old_cid
            update["reassigned_at"] = _now()
            update["reassigned_by"] = user.get("id")
    if not update:
        return {"ok": True, "ticket": ticket, "changed": False}
    update["updated_at"] = _now()
    await db.support_tickets.update_one({"id": tid}, {"$set": update})
    ticket.update(update)
    return {"ok": True, "ticket": ticket, "changed": True}


@api.get("/me/tickets/cost-summary", tags=["Portail Client"])
async def me_tickets_cost_summary(
    months_back: int = Query(0, ge=0, le=24),
    user: dict = Depends(get_current_user),
):
    """Iter37d — Monthly cost aggregate for closed tickets.
    Returns total + per-client breakdown for the requested month (0 = current).
    Restricted to elevated viewers (admin/superviseur/moderateur).
    """
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Accès refusé")
    now = datetime.now(timezone.utc)
    # Compute target month window
    y, m = now.year, now.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    month_start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        month_end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    scope_filter = await _ticket_scope_for_user(user)
    q = {
        **scope_filter,
        "status": {"$in": list(TICKET_CLOSED_STATUSES)},
        "closed_at": {"$gte": month_start.isoformat(), "$lt": month_end.isoformat()},
    }
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$client_id",
            "total_cost": {"$sum": {"$ifNull": ["$cost_amount", 0]}},
            "total_hours": {"$sum": {"$ifNull": ["$active_hours", 0]}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"total_cost": -1}},
    ]
    rows: List[Dict[str, Any]] = []
    grand_total = 0.0
    grand_hours = 0.0
    grand_count = 0
    async for row in db.support_tickets.aggregate(pipeline):
        client_id = row.get("_id")
        client_doc = await db.users.find_one({"id": client_id}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        name = client_doc.get("company") or client_doc.get("full_name") or "—"
        amount = float(row.get("total_cost") or 0)
        hours = round(float(row.get("total_hours") or 0), 2)
        count = int(row.get("count") or 0)
        rows.append({
            "client_id": client_id, "client_name": name,
            "total_cost": amount, "total_hours": hours, "count": count,
        })
        grand_total += amount
        grand_hours += hours
        grand_count += count
    return {
        "month": month_start.strftime("%Y-%m"),
        "period_start": month_start.isoformat(),
        "period_end": month_end.isoformat(),
        "currency": "XOF",
        "grand_total": grand_total,
        "grand_hours": round(grand_hours, 2),
        "grand_count": grand_count,
        "by_client": rows,
    }


# ---------------------------------------------------------------------
# Iter37e — Internal helper reused by CSV/PDF exporters below
# ---------------------------------------------------------------------
async def _tickets_cost_summary_data(user: dict, months_back: int) -> Dict[str, Any]:
    """Same data the JSON endpoint returns, callable internally."""
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Accès refusé")
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    month_start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        month_end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    scope_filter = await _ticket_scope_for_user(user)
    q = {
        **scope_filter,
        "status": {"$in": list(TICKET_CLOSED_STATUSES)},
        "closed_at": {"$gte": month_start.isoformat(), "$lt": month_end.isoformat()},
    }
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$client_id",
            "total_cost": {"$sum": {"$ifNull": ["$cost_amount", 0]}},
            "total_hours": {"$sum": {"$ifNull": ["$active_hours", 0]}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"total_cost": -1}},
    ]
    rows: List[Dict[str, Any]] = []
    grand_total = 0.0
    grand_hours = 0.0
    grand_count = 0
    async for row in db.support_tickets.aggregate(pipeline):
        client_id = row.get("_id")
        client_doc = await db.users.find_one({"id": client_id}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        name = client_doc.get("company") or client_doc.get("full_name") or "—"
        amount = float(row.get("total_cost") or 0)
        hours = round(float(row.get("total_hours") or 0), 2)
        count = int(row.get("count") or 0)
        rows.append({
            "client_id": client_id, "client_name": name,
            "total_cost": amount, "total_hours": hours, "count": count,
        })
        grand_total += amount
        grand_hours += hours
        grand_count += count
    return {
        "month": month_start.strftime("%Y-%m"),
        "period_start": month_start.isoformat(),
        "period_end": month_end.isoformat(),
        "currency": "XOF",
        "grand_total": grand_total,
        "grand_hours": round(grand_hours, 2),
        "grand_count": grand_count,
        "by_client": rows,
    }


@api.get("/me/tickets/cost-summary.csv", tags=["Portail Client"])
async def me_tickets_cost_summary_csv(
    months_back: int = Query(0, ge=0, le=24),
    user: dict = Depends(get_current_user),
):
    """Iter37e — CSV export du coût mensuel des interventions clôturées.
    Format Excel-friendly : UTF-8 BOM, séparateur `;`.
    """
    import csv as _csv
    import io
    data = await _tickets_cost_summary_data(user, months_back)
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = _csv.writer(buf, delimiter=";")
    writer.writerow(["SAWALI Smart Systems — Coût des interventions clôturées"])
    writer.writerow([f"Période : {data['month']}", f"Total : {data['grand_total']:.0f} {data['currency']}",
                     f"Heures actives : {data['grand_hours']}", f"Tickets clôturés : {data['grand_count']}"])
    writer.writerow([])
    writer.writerow(["Client Lié", "Tickets clôturés", "Heures actives", f"Coût total ({data['currency']})"])
    for row in data["by_client"]:
        writer.writerow([row["client_name"], row["count"], f"{row['total_hours']}", f"{row['total_cost']:.0f}"])
    writer.writerow([])
    writer.writerow(["TOTAL", data["grand_count"], data["grand_hours"], f"{data['grand_total']:.0f}"])
    fname = f"cout-interventions-{data['month']}.csv"
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/me/tickets/cost-summary.pdf", tags=["Portail Client"])
async def me_tickets_cost_summary_pdf(
    months_back: int = Query(0, ge=0, le=24),
    user: dict = Depends(get_current_user),
):
    """Iter37e — PDF export du coût mensuel des interventions clôturées (A4 paysage)."""
    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    data = await _tickets_cost_summary_data(user, months_back)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            topMargin=28, bottomMargin=28, leftMargin=28, rightMargin=28,
                            title=f"Coût interventions {data['month']}")
    styles = getSampleStyleSheet()
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    story: List[Any] = [
        Paragraph("<b>SAWALI Smart Systems — Coût des interventions clôturées</b>", styles["Title"]),
        Paragraph(
            f"<b>Période :</b> {data['month']} &nbsp;&nbsp; "
            f"<b>Total :</b> {data['grand_total']:,.0f} {data['currency']} &nbsp;&nbsp; "
            f"<b>Heures :</b> {data['grand_hours']}h &nbsp;&nbsp; "
            f"<b>Tickets :</b> {data['grand_count']}".replace(",", " "),
            styles["Normal"],
        ),
        Paragraph(f"Généré le {now_str}", styles["Normal"]),
        Spacer(1, 12),
    ]
    table_data: List[List[Any]] = [["Client Lié", "Tickets clôturés", "Heures actives", f"Coût ({data['currency']})"]]
    for row in data["by_client"]:
        table_data.append([
            row["client_name"][:50],
            str(row["count"]),
            f"{row['total_hours']}",
            f"{row['total_cost']:,.0f}".replace(",", " "),
        ])
    # Totals footer row
    table_data.append([
        "TOTAL",
        str(data["grand_count"]),
        f"{data['grand_hours']}",
        f"{data['grand_total']:,.0f}".replace(",", " "),
    ])
    tbl = Table(table_data, repeatRows=1, colWidths=[280, 100, 100, 140])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E90FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fef3c7")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)
    # Iter43-fix24az-l retest — Offload reportlab doc.build to thread pool
    # to avoid blocking uvicorn's single-worker event loop (CF 520 mitigation).
    await asyncio.to_thread(doc.build, story)
    fname = f"cout-interventions-{data['month']}.pdf"
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.post("/me/tickets/{tid}/close", tags=["Portail Client"])
async def me_close_ticket(
    tid: str,
    payload: TicketClosePayload,
    user: dict = Depends(get_current_user),
):
    if payload.outcome not in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=400, detail="outcome doit être 'done' ou 'cancelled'.")
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    if ticket["status"] in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail=f"Déjà clôturé ({ticket['status']}).")
    res_note = (payload.resolution_note or "").strip()[:2000] or None
    # Lot 54 — clôture commune (manuelle ou automatique) : tickets_clients.cloturer_ticket.
    # Coût : durée active < seuil (5 h par défaut, fiche client) → horaire × durée, sinon forfait.
    # L'intervention créée porte la date/heure de début (création du ticket) et de fin (clôture)
    # et un lien vers le ticket.
    cloture = await _tickets_clients.cloturer_ticket(
        ticket, outcome=payload.outcome, acteur=user, note=res_note,
        numeroteur=_next_intervention_number,
    )
    if not cloture["ok"]:
        raise HTTPException(status_code=409, detail="Ticket déjà clôturé.")
    ticket = cloture["ticket"]
    now_iso = ticket["closed_at"]
    intervention_summary = cloture["intervention"]

    # WhatsApp notification on closure (best-effort)
    s = await db.settings.find_one({"_id": "global"}) or {}
    admin_default_notify = bool(s.get("notify_on_ticket_close", True))
    if payload.notify_contact is None:
        notify = admin_default_notify
    else:
        notify = bool(payload.notify_contact)
    tpl_name = (s.get("wa_template_ticket_close") or "").strip()
    notification = {"sent": False, "error": None}
    if notify and tpl_name and ticket.get("contact_phone"):
        duration = _format_ticket_duration(ticket["opened_at"], now_iso)
        comps = _ticket_components(ticket["number"], duration=duration)
        try:
            wr = await _wa_send_template(
                ticket["contact_phone"], tpl_name,
                (s.get("wa_template_ticket_language") or "fr").strip() or "fr",
                comps,
            )
            notification = {"sent": bool(wr.get("ok")), "error": wr.get("error")}
        except Exception as exc:  # noqa: BLE001
            notification = {"sent": False, "error": str(exc)[:200]}

    return {"ok": True, "ticket": ticket, "notification": notification, "intervention": intervention_summary}


@api.get("/me/contacts/{cid}/active-ticket", tags=["Portail Client"])
async def me_contact_active_ticket(cid: str, user: dict = Depends(get_current_user)):
    """Convenience: returns the non-closed ticket for a contact (if any).
    Used by the chat UI to swap "Generate ticket" → "View open ticket".

    Iter38p — If the open ticket actually points to a contact that no longer
    exists, auto-close it as orphan and return active=false so the UI lets the
    user create a fresh ticket.
    Iter38q — Archived tickets (corbeille) are NEVER returned as active.
    """
    scope_filter = await _ticket_scope_for_user(user)
    contact = (
        await db.directory_contacts.find_one({**scope_filter, "id": cid}, {"_id": 0, "id": 1})
        or await db.contacts.find_one({**scope_filter, "id": cid}, {"_id": 0, "id": 1})
    )
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable.")
    t = await db.support_tickets.find_one(
        {
            "contact_id": cid,
            "status": {"$in": list(TICKET_OPEN_STATUSES)},
            "archived_at": {"$in": [None, ""]},  # Iter38q — exclude trashed
        },
        {"_id": 0},
        sort=[("opened_at", -1)],
    )
    if t:
        was_orphan = await _auto_close_orphan_ticket_if_contact_missing(
            t, actor_id=user.get("id"),
        )
        if was_orphan:
            return {"active": False, "ticket": None, "cleaned_up": True}
    if t is None:
        # Lot 54 — ticket ouvert pour le client lié via un AUTRE de ses contacts : il couvre
        # aussi ce contact (la conversation affiche « Voir le ticket » au lieu de « Générer »).
        t = await _tickets_clients.ticket_ouvert_pour_contact(
            cid, scope_conversation=user.get("parent_client_id") or user.get("client_id") or user.get("id"))
        if t:
            return {"active": True, "ticket": t, "partage": True}
    return {"active": t is not None, "ticket": t}


# Iter38q — Archive (corbeille) a ticket — IRREVERSIBLE.
# Admin/Superviseur only. Once archived, the ticket is:
#   • Excluded from list/active-ticket/lookup queries.
#   • Cannot be reopened (the reopen endpoint refuses archived parents).
#   • Cannot be unarchived (there is intentionally no /unarchive endpoint).
# The archive is stored as a soft-delete: row remains in DB with
# `archived_at` + `archived_by_*` so audit trails are preserved.
class TicketArchivePayload(BaseModel):
    # Iter38r-fix3 — When true, also clears `contact_id` on the ticket so the
    # contact's chat window is fully released and a fresh ticket can be opened.
    also_unlink: bool = False


@api.post("/me/tickets/{tid}/archive", tags=["Portail Client"])
async def me_archive_ticket(
    tid: str,
    payload: Optional[TicketArchivePayload] = None,
    user: dict = Depends(get_current_user),
):
    role = (user or {}).get("role")
    if role not in ("admin", "superviseur"):
        raise HTTPException(
            status_code=403,
            detail="Action réservée aux administrateurs et superviseurs.",
        )
    also_unlink = bool(payload and payload.also_unlink)
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    if ticket.get("archived_at"):
        # Already archived — but the user may still want to unlink the
        # contact reference to fully release the chat window.
        if also_unlink and ticket.get("contact_id"):
            old_cid = ticket.get("contact_id")
            await db.support_tickets.update_one(
                {"id": tid},
                {"$set": {
                    "contact_id": None,
                    "archived_contact_id": old_cid,
                    "unlinked_at": _now(),
                    "unlinked_by_id": user["id"],
                    "updated_at": _now(),
                }},
            )
            return {"ok": True, "id": tid, "already_archived": True, "unlinked": True}
        raise HTTPException(status_code=409, detail="Ticket déjà dans la corbeille.")
    now_iso = _now()
    update = {
        "archived_at": now_iso,
        "archived_by_id": user["id"],
        "archived_by_label": user.get("full_name") or user.get("email"),
        "updated_at": now_iso,
    }
    # If still open, also force-close it (cannot be a "live" archived ticket)
    if ticket.get("status") in TICKET_OPEN_STATUSES:
        update.update({
            "status": "closed",
            "closed_at": now_iso,
            "closed_by_id": user["id"],
            "closed_by_label": user.get("full_name") or user.get("email"),
            "outcome": "archived_to_trash",
            "resolution_note": "Mis à la corbeille — toutes références supprimées.",
        })
    if also_unlink and ticket.get("contact_id"):
        # Move the original contact_id to an audit field and clear the live one
        update["archived_contact_id"] = ticket.get("contact_id")
        update["contact_id"] = None
        update["unlinked_at"] = now_iso
        update["unlinked_by_id"] = user["id"]
    await db.support_tickets.update_one({"id": tid}, {"$set": update})
    try:
        await _log_activity(
            client_id=ticket.get("client_id", ""),
            kind="ticket", action="archived",
            label=f"{ticket.get('number', '?')} → corbeille" + (" (lien contact retiré)" if also_unlink else ""),
            actor=user, target_id=tid,
        )
    except Exception:
        pass
    return {"ok": True, "id": tid, "archived_at": now_iso, "unlinked": also_unlink}


# Iter38q — Trash listing — admin/superviseur only. Read-only (no restore).
@api.get("/me/tickets/trash", tags=["Portail Client"])
async def me_list_trashed_tickets(
    limit: int = 100, user: dict = Depends(get_current_user)
):
    role = (user or {}).get("role")
    if role not in ("admin", "superviseur"):
        raise HTTPException(
            status_code=403,
            detail="Action réservée aux administrateurs et superviseurs.",
        )
    scope_filter = await _ticket_scope_for_user(user)
    q = {**scope_filter, "archived_at": {"$nin": [None, ""]}}
    cursor = db.support_tickets.find(q, {"_id": 0}).sort("archived_at", -1).limit(max(1, min(limit, 500)))
    items = await cursor.to_list(length=limit)
    items = [_strip_ticket_cost_fields(i) for i in items]
    return items



# Iter43 (2026-03) — Bulk delete + Reset (multi-sélection UI). Admin/Sup only.
class TicketBulkIdsPayload(BaseModel):
    ids: List[str] = Field(default_factory=list, max_length=5000)


@api.post("/me/tickets/bulk-delete", tags=["Portail Client"])
async def me_bulk_delete_tickets(
    payload: TicketBulkIdsPayload = Body(...),
    user: dict = Depends(get_current_user),
):
    """Hard-delete les tickets sélectionnés par leurs ids. Admin/Sup uniquement."""
    role = (user.get("role") or "").lower()
    if role not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Suppression réservée Admin/Superviseur")
    ids = [i for i in (payload.ids or []) if isinstance(i, str) and i]
    if not ids:
        raise HTTPException(status_code=400, detail="Aucun id fourni")
    res = await db.support_tickets.delete_many({"id": {"$in": ids}})
    return {"ok": True, "deleted": res.deleted_count}


@api.post("/me/tickets/reset", tags=["Portail Client"])
async def me_reset_all_tickets(user: dict = Depends(get_current_user)):
    """Hard-delete TOUS les tickets (remise à zéro complète). Réservé Admin/Superviseur."""
    role = (user.get("role") or "").lower()
    if role not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Réservé Admin/Superviseur")
    res = await db.support_tickets.delete_many({})
    return {"ok": True, "deleted": res.deleted_count}



# ====================================================================
# Iter35p — Ticket enhancements:
#   1) Assignment to a user-suivi (notify via activity_events).
#   2) Reopen — creates a sibling TKT-YYYY-NNNN-R{k} linked to parent.
#   3) Motif templates — CRUD for reusable motif snippets.
#   4) Resolution-time stats — dashboard score per user + team leaderboard.
# ====================================================================
@api.post("/me/tickets/{tid}/assign", tags=["Portail Client"])
async def me_assign_ticket(
    tid: str,
    payload: TicketAssignPayload,
    user: dict = Depends(get_current_user),
):
    """Assign a ticket to a user (or unassign when user_id is empty)."""
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    if ticket["status"] in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail="Ticket clôturé — affectation impossible.")
    uid = (payload.user_id or "").strip() or None
    update: Dict[str, Any] = {"updated_at": _now()}
    if uid is None:
        update["assigned_to_id"] = None
        update["assigned_to_label"] = None
        update["assigned_at"] = None
        update["assigned_by_id"] = None
    else:
        # The target must be in the same scope (users OR tracked_users)
        eff_client = user.get("parent_client_id") or user.get("client_id") or user["id"]
        target = await db.users.find_one(
            {"id": uid, "$or": [{"id": eff_client}, {"client_id": eff_client}, {"parent_client_id": eff_client}]},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1},
        )
        if not target:
            target = await db.tracked_users.find_one({"id": uid, "client_id": eff_client}, {"_id": 0, "id": 1, "full_name": 1, "email": 1})
        if not target:
            raise HTTPException(status_code=400, detail="Utilisateur destinataire hors périmètre.")
        update["assigned_to_id"] = target["id"]
        update["assigned_to_label"] = target.get("full_name") or target.get("email") or target["id"][:8]
        update["assigned_at"] = _now()
        update["assigned_by_id"] = user["id"]
    await db.support_tickets.update_one({"id": tid}, {"$set": update})
    ticket.update(update)
    # Activity feed → assignee gets a toast in real-time
    try:
        await _log_activity(
            client_id=ticket["client_id"], kind="ticket", action="assigned",
            label=f"{ticket['number']} → {update.get('assigned_to_label') or 'aucun'}",
            actor=user, target_id=tid,
        )
    except Exception:
        pass
    return {"ok": True, "ticket": ticket}


@api.post("/me/tickets/{tid}/reopen", tags=["Portail Client"])
async def me_reopen_ticket(
    tid: str,
    payload: TicketReopenPayload,
    user: dict = Depends(get_current_user),
):
    """Re-open a closed ticket as a *new* sibling whose number ends with -R{k}.

    Example chain : TKT-2026-0014 (done) → /reopen → TKT-2026-0014-R1 (open) →
    if closed and reopened again → TKT-2026-0014-R2.

    The parent must already be closed. The new ticket carries:
      - parent_ticket_id (the very first ticket of the chain)
      - root_number (the original number, for grouping)
      - the same contact / client_id
    """
    scope_filter = await _ticket_scope_for_user(user)
    parent = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not parent:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    # Iter38q — Archived parents cannot be reopened (corbeille is final)
    if parent.get("archived_at"):
        raise HTTPException(status_code=409, detail="Ce ticket est dans la corbeille — réouverture interdite.")
    if parent["status"] not in TICKET_CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail="Le ticket doit être clôturé avant d'être rouvert.")
    # Also ensure the contact does not already have another open ticket
    existing_open = await db.support_tickets.find_one(
        {
            "contact_id": parent["contact_id"],
            "status": {"$in": list(TICKET_OPEN_STATUSES)},
            "archived_at": {"$in": [None, ""]},
        },
        {"_id": 0, "id": 1, "number": 1, "status": 1, "contact_id": 1, "client_id": 1},
    )
    if existing_open:
        # Iter38p — Auto-clean orphan blocker
        was_orphan = await _auto_close_orphan_ticket_if_contact_missing(
            existing_open, actor_id=user.get("id"),
        )
        if not was_orphan:
            raise HTTPException(status_code=409, detail=f"{existing_open['number']} est déjà ouvert pour ce contact.")
    # Lot 54 — un ticket ouvert couvre tous les contacts du client : pas de réouverture en parallèle
    partage = await _tickets_clients.ticket_ouvert_du_client(parent.get("client_id"))
    if partage:
        raise HTTPException(status_code=409, detail=f"{partage['number']} est déjà ouvert pour ce client "
                                                    "(il couvre tous ses contacts).")
    root_number = parent.get("root_number") or parent["number"]
    # Count how many siblings (including parent) share this root → suffix index
    chain_count = await db.support_tickets.count_documents({
        "$or": [{"number": root_number}, {"root_number": root_number}],
    })
    suffix_idx = chain_count  # next suffix
    new_number = f"{root_number}-R{suffix_idx}"
    motif = (payload.motif or "").strip() or (parent.get("motif") or "Réouverture")
    if len(motif) > 200:
        motif = motif[:200]
    now_iso = _now()
    new_ticket = {
        "id": _uuid(),
        "number": new_number,
        "root_number": root_number,
        "parent_ticket_id": parent["id"],
        "client_id": parent["client_id"],
        "contact_id": parent["contact_id"],
        "contact_name": parent.get("contact_name"),
        "contact_phone": parent.get("contact_phone"),
        "motif": motif,
        "status": "open",
        "notes": None,
        "opened_at": now_iso,
        "opened_by_id": user["id"],
        "opened_by_label": user.get("full_name") or user.get("email"),
        "closed_at": None,
        "closed_by_id": None,
        "closed_by_label": None,
        "outcome": None,
        "resolution_note": None,
        # Carry-over assignment if present on parent
        "assigned_to_id": parent.get("assigned_to_id"),
        "assigned_to_label": parent.get("assigned_to_label"),
        "assigned_at": now_iso if parent.get("assigned_to_id") else None,
        "created_at": now_iso,
        "updated_at": now_iso,
        # Lot 54 — contacts couverts, session WhatsApp minutée, validité (clients non contractuels)
        "contact_ids": [c for c in [parent.get("contact_id")] if c],
        **_tickets_clients.champs_creation(await _tickets_clients.lire_client(parent["client_id"]), now_iso),
    }
    await db.support_tickets.insert_one(new_ticket.copy())
    try:
        await _log_activity(
            client_id=new_ticket["client_id"], kind="ticket", action="reopened",
            label=f"{new_number} (depuis {parent['number']})", actor=user, target_id=new_ticket["id"],
        )
    except Exception:
        pass
    return {"ok": True, "ticket": new_ticket, "parent_number": parent["number"]}


# ---- Motif templates (reusable snippets) ------------------------------
@api.get("/me/ticket-motif-templates", tags=["Portail Client"])
async def me_list_ticket_motif_templates(user: dict = Depends(get_current_user)):
    scope = user.get("parent_client_id") or user.get("client_id") or user["id"]
    items = await db.ticket_motif_templates.find({"client_id": scope}, {"_id": 0}).sort("label", 1).to_list(100)
    return items


@api.post("/me/ticket-motif-templates", tags=["Portail Client"])
async def me_create_ticket_motif_template(
    payload: TicketMotifTemplatePayload,
    user: dict = Depends(get_current_user),
):
    # Only admin / superviseur / elevated_creator can manage templates
    if not (user.get("role") in ("admin", "superviseur") or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Rôle non autorisé.")
    label = (payload.label or "").strip()
    motif = (payload.motif or "").strip()
    if not label or not motif:
        raise HTTPException(status_code=400, detail="label et motif sont obligatoires.")
    if len(label) > 60 or len(motif) > 200:
        raise HTTPException(status_code=400, detail="Longueur maximale dépassée (label 60, motif 200).")
    scope = user.get("parent_client_id") or user.get("client_id") or user["id"]
    doc = {
        "id": _uuid(),
        "client_id": scope,
        "label": label,
        "motif": motif,
        "created_at": _now(),
        "created_by_id": user["id"],
    }
    await db.ticket_motif_templates.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "template": doc}


@api.delete("/me/ticket-motif-templates/{tpl_id}", tags=["Portail Client"])
async def me_delete_ticket_motif_template(tpl_id: str, user: dict = Depends(get_current_user)):
    if not (user.get("role") in ("admin", "superviseur") or _is_elevated_creator(user)):
        raise HTTPException(status_code=403, detail="Rôle non autorisé.")
    scope = user.get("parent_client_id") or user.get("client_id") or user["id"]
    res = await db.ticket_motif_templates.delete_one({"id": tpl_id, "client_id": scope})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    return {"ok": True}


# 2026-02 fork iter107 — Re-send ticket WA template based on current status.
# Called from the /portal/tickets row expander to nudge the reporter again.
@api.post("/me/tickets/{tid}/resend-wa", tags=["Portail Client"])
async def me_ticket_resend_wa(tid: str, user: dict = Depends(get_current_user)):
    """Renvoie le template WA correspondant au statut courant du ticket au
    rapporteur / contact d'origine. Statuts pris en charge :
      - `open` ou `in_progress` → template d'ouverture (`wa_template_ticket_open`)
      - `closed`                → template de clôture (`wa_template_ticket_close`)
    """
    # Lot 74 (anomalie A3) : les tickets sont enregistrés dans `support_tickets` (et non `tickets`),
    # avec le même filtre de visibilité que l'ouverture et la clôture ; le motif est le champ `motif`,
    # la durée part de `opened_at`, et la langue est celle réglée dans Paramètres.
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    scope = ticket.get("client_id") or user.get("parent_client_id") or user.get("client_id") or user["id"]
    phone = (ticket.get("contact_phone") or ticket.get("contact_whatsapp") or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="Aucun numéro de contact sur ce ticket — impossible de renvoyer un WhatsApp.")
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_template_ticket_open": 1, "wa_template_ticket_close": 1,
                                                       "wa_template_ticket_language": 1}) or {}
    tpl_lang = (s.get("wa_template_ticket_language") or "fr").strip() or "fr"
    status = (ticket.get("status") or "open").lower()
    if status in TICKET_CLOSED_STATUSES or status in ("closed", "resolved"):
        tpl_name = (s.get("wa_template_ticket_close") or "").strip() or "clotureticket"
        duration = _format_ticket_duration(ticket.get("opened_at") or ticket.get("created_at") or "",
                                           ticket.get("closed_at") or _now())
        components = _ticket_components(ticket.get("number") or tid, duration=duration)
    else:
        tpl_name = (s.get("wa_template_ticket_open") or "").strip() or "ouvertureticket"
        motif = (ticket.get("motif") or ticket.get("reason") or "")[:200]
        components = _ticket_components(ticket.get("number") or tid, motif=motif)
    try:
        wr = await _wa_send_template(phone, tpl_name, tpl_lang, components)
    except Exception as exc:  # noqa: BLE001
        wr = {"ok": False, "error": str(exc)[:200]}
    log_entry = {
        "id": _uuid(),
        "ticket_id": tid,
        "client_id": scope,
        "to": phone,
        "template_name": tpl_name,
        "language_code": tpl_lang,
        "ok": bool(wr.get("ok")),
        "status": wr.get("status"),
        "message_id": wr.get("message_id"),
        "error": wr.get("error"),
        "context": "ticket_resend",
        "by_user_id": user.get("id"),
        "by_user_email": user.get("email"),
        "created_at": _now(),
    }
    try:
        await db.whatsapp_messages.insert_one(log_entry.copy())
    except Exception:  # noqa: BLE001
        pass
    return {"ok": bool(wr.get("ok")), "template": tpl_name, "to": phone, "error": wr.get("error")}




# ---- Resolution-time stats --------------------------------------------
@api.get("/me/dashboard/ticket-stats", tags=["Portail Client"])
async def me_dashboard_ticket_stats(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    """Per-user ticket resolution score (only `done` tickets count) over the
    trailing `days` window. Surfaced on the dashboard so teams can compare
    who resolves the fastest. Elevated viewers (admin/superviseur) also get
    a leaderboard of the top 10 fastest closers."""
    visible_scope = await _resolve_visible_client_ids(user)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {
        "client_id": {"$in": visible_scope},
        "status": "done",
        "closed_at": {"$gte": since},
        "opened_at": {"$exists": True, "$ne": None},
    }
    me_q = {**base_q, "closed_by_id": user["id"]}
    my_durations: List[int] = []
    async for d in db.support_tickets.find(me_q, {"_id": 0, "opened_at": 1, "closed_at": 1}):
        try:
            o = datetime.fromisoformat(d["opened_at"].replace("Z", "+00:00"))
            c = datetime.fromisoformat(d["closed_at"].replace("Z", "+00:00"))
            secs = int((c - o).total_seconds())
            if secs > 0:
                my_durations.append(secs)
        except Exception:
            pass
    my_durations.sort()
    me_block = {
        "avg_seconds": int(sum(my_durations) / len(my_durations)) if my_durations else None,
        "median_seconds": my_durations[len(my_durations) // 2] if my_durations else None,
        "fastest_seconds": my_durations[0] if my_durations else None,
        "closed_count": len(my_durations),
    }

    team: List[Dict[str, Any]] = []
    if _is_elevated_creator(user) or user.get("role") in ("admin", "superviseur"):
        pipeline = [
            {"$match": base_q},
            {"$addFields": {
                "opened_dt": {"$dateFromString": {"dateString": "$opened_at"}},
                "closed_dt": {"$dateFromString": {"dateString": "$closed_at"}},
            }},
            {"$addFields": {"_resolution_secs": {"$divide": [{"$subtract": ["$closed_dt", "$opened_dt"]}, 1000]}}},
            {"$match": {"_resolution_secs": {"$gt": 0}}},
            {"$group": {
                "_id": "$closed_by_id",
                "label": {"$last": "$closed_by_label"},
                "avg_seconds": {"$avg": "$_resolution_secs"},
                "fastest_seconds": {"$min": "$_resolution_secs"},
                "closed_count": {"$sum": 1},
            }},
            {"$sort": {"avg_seconds": 1}},
            {"$limit": 10},
        ]
        async for row in db.support_tickets.aggregate(pipeline):
            if not row.get("_id"):
                continue
            team.append({
                "user_id": row["_id"],
                "label": row.get("label") or row["_id"][:8],
                "avg_seconds": int(row["avg_seconds"]) if row.get("avg_seconds") is not None else None,
                "fastest_seconds": int(row["fastest_seconds"]) if row.get("fastest_seconds") is not None else None,
                "closed_count": row.get("closed_count") or 0,
            })

    return {"days": days, "me": me_block, "team": team}


# ====================================================================
# Lot 54 — Session WhatsApp d'un ticket (durée, rappels T-10 / T-5, fermeture auto)
# ====================================================================
class TicketSessionWaPayload(BaseModel):
    minutes: int = 0  # 0 = pas de limite pour ce ticket


@api.get("/me/tickets/{tid}/session-wa", tags=["Portail Client"])
async def me_ticket_session_wa(tid: str, user: dict = Depends(get_current_user)):
    """État de la session WhatsApp du ticket : échéance, minutes restantes, rappels envoyés,
    contacts couverts et journal (rappels non envoyés : fenêtre de 24 h fermée, etc.)."""
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    return await _tickets_clients.etat_session(ticket)


@api.put("/me/tickets/{tid}/session-wa", tags=["Portail Client"])
async def me_ticket_set_session_wa(tid: str, payload: TicketSessionWaPayload, user: dict = Depends(get_current_user)):
    """Durée de session WhatsApp propre à ce ticket (le défaut vient de la fiche client)."""
    if not _is_elevated_creator(user):
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs, superviseurs et modérateurs.")
    if payload.minutes < 0 or payload.minutes > 24 * 60:
        raise HTTPException(status_code=400, detail="Durée attendue : de 0 (pas de limite) à 1440 minutes.")
    scope_filter = await _ticket_scope_for_user(user)
    ticket = await db.support_tickets.find_one({**scope_filter, "id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    if ticket.get("status") not in TICKET_OPEN_STATUSES:
        raise HTTPException(status_code=409, detail="Ticket déjà clôturé.")
    ticket = await _tickets_clients.regler_session(ticket, payload.minutes, par=user)
    return await _tickets_clients.etat_session(ticket)


@api.post("/admin/tickets/echeances/executer", tags=["Admin"])
async def admin_tickets_executer_echeances(_: dict = Depends(get_current_admin)):
    """Lance tout de suite le passage du planificateur (rappels, fins de session, fins de validité)."""
    return await _tickets_clients.executer_echeances(envoyer=_wa_send_text)


# Register the API router at the very end, after every endpoint has been
# declared. This is critical: include_router() snapshots routes at call time,
# so any @api.* decorator added below this line would NOT be exposed.
