# server_parts/p19_briefing_accueil.py — Briefing d'accueil après connexion.
# Morceau de l'ancien server.py (lignes 24991 à 25325), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# =====================================================================
# Iter35r — GET /me/welcome-briefing
# Aggregated briefing shown right after login: pending tickets (open +
# suspended), unread WA/SMS messages, and recent personal notes created
# within the configurable window (default 3 days).
# =====================================================================
@api.get("/me/welcome-briefing", tags=["Portail Client"])
async def me_welcome_briefing(
    last_seen_at: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    s = await db.settings.find_one({"_id": "global"}) or {}
    notes_days = int(s.get("welcome_modal_notes_days") or 3)
    since_notes = (datetime.now(timezone.utc) - timedelta(days=notes_days)).isoformat()
    scope_filter = await _ticket_scope_for_user(user)

    # 1) Tickets en attente + suspendus
    tickets = await db.support_tickets.find(
        {**scope_filter, "status": {"$in": ["open", "suspended"]}},
        {"_id": 0, "id": 1, "number": 1, "motif": 1, "status": 1, "opened_at": 1, "contact_name": 1},
    ).sort("opened_at", -1).limit(50).to_list(50)

    # 2) Messages non lus (WhatsApp + SMS) — best-effort via /me/notifications/counts shape
    # Iter37f — Bound by last_seen_at (or fallback 7 days) so legacy/never-read
    # messages don't accumulate forever. Matches the user's "only count what's
    # actually new" expectation. /me/whatsapp/unread (sidebar) keeps the lifetime
    # logic so the per-contact pastille stays sticky until the user opens the thread.
    #
    # Iter37f — Admin-configurable mode:
    #   - settings.welcome_unread_mode = "bounded" (default, behavior above)
    #   - settings.welcome_unread_mode = "lifetime" (count all unread inbound)
    visible_scope = await _resolve_visible_client_ids(user)
    _settings = await db.settings.find_one({"_id": "global"}) or {}
    unread_mode = (_settings.get("welcome_unread_mode") or "bounded").strip().lower()
    base_unread_wa: Dict[str, Any] = {
        "client_id": {"$in": visible_scope},
        "direction": "inbound",
        "read_by_us_at": None,
    }
    base_unread_sms: Dict[str, Any] = {
        "client_id": {"$in": visible_scope},
        "direction": "inbound",
        "read_by_us_at": None,
    }
    if unread_mode != "lifetime":
        now_for_bound = datetime.now(timezone.utc)
        unread_lower_bound = last_seen_at or (now_for_bound - timedelta(days=7)).isoformat()
        base_unread_wa["received_at"] = {"$gte": unread_lower_bound}
        base_unread_sms["received_at"] = {"$gte": unread_lower_bound}
    unread_wa = await db.whatsapp_messages.count_documents(base_unread_wa)
    unread_sms = await db.sms_messages.count_documents(base_unread_sms)

    # 3) Notes personnelles récentes (auteur = moi)
    recent_notes_cur = db.user_notes_personal.find(
        {"owner_id": user["id"], "created_at": {"$gte": since_notes}},
        {"_id": 0, "id": 1, "title": 1, "is_private": 1, "created_at": 1, "target_user_ids": 1},
    ).sort("created_at", -1).limit(50)
    recent_notes = [n async for n in recent_notes_cur]

    # 4) Iter35t — Santé quotidienne (motivation mini-dashboard)
    now = datetime.now(timezone.utc)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    since_24h = (now - timedelta(hours=24)).isoformat()

    # Tickets résolus hier (status closed dans la fenêtre d'hier)
    tickets_resolved_yesterday = await db.support_tickets.count_documents({
        **scope_filter,
        "status": "closed",
        "closed_at": {"$gte": yesterday_start, "$lt": yesterday_end},
    })
    # Tickets ouverts aujourd'hui
    tickets_opened_today = await db.support_tickets.count_documents({
        **scope_filter,
        "opened_at": {"$gte": today_start},
    })

    # Taux de réponse WhatsApp 24h : sortants / entrants (capé à 100%)
    wa_inbound_24h = await db.whatsapp_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "inbound",
        "received_at": {"$gte": since_24h},
    })
    wa_outbound_24h = await db.whatsapp_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "outbound",
        "sent_at": {"$gte": since_24h},
    })
    if wa_inbound_24h > 0:
        wa_response_rate = min(100, round(100 * wa_outbound_24h / wa_inbound_24h))
    else:
        wa_response_rate = None  # aucun inbound = pas de métrique pertinente

    # Messages envoyés aujourd'hui (WA + SMS)
    wa_sent_today = await db.whatsapp_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "outbound",
        "sent_at": {"$gte": today_start},
    })
    sms_sent_today = await db.sms_messages.count_documents({
        "client_id": {"$in": visible_scope},
        "direction": "outbound",
        "sent_at": {"$gte": today_start},
    })

    daily_health = {
        "tickets_resolved_yesterday": tickets_resolved_yesterday,
        "tickets_opened_today": tickets_opened_today,
        "wa_response_rate_24h": wa_response_rate,  # None si pas d'inbound
        "wa_inbound_24h": wa_inbound_24h,
        "wa_outbound_24h": wa_outbound_24h,
        "messages_sent_today": wa_sent_today + sms_sent_today,
    }

    # Iter36g — "Nouveaux depuis votre dernière visite": tickets + WA + notes
    # created strictly after last_seen_at (sent by the frontend from localStorage).
    since_last_visit = None
    if last_seen_at:
        try:
            # Parse to make sure it's a valid ISO timestamp
            _ = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
            new_tickets_cur = db.support_tickets.find(
                {**scope_filter, "opened_at": {"$gt": last_seen_at}},
                {"_id": 0, "id": 1, "number": 1, "motif": 1, "status": 1, "opened_at": 1, "contact_name": 1},
            ).sort("opened_at", -1).limit(50)
            new_tickets = [t async for t in new_tickets_cur]
            new_wa = await db.whatsapp_messages.count_documents({
                "client_id": {"$in": visible_scope},
                "direction": "inbound",
                "received_at": {"$gt": last_seen_at},
            })
            new_notes_cur = db.user_notes_personal.find(
                {"owner_id": user["id"], "created_at": {"$gt": last_seen_at}},
                {"_id": 0, "id": 1, "title": 1, "is_private": 1, "created_at": 1, "kind": 1, "numero": 1},
            ).sort("created_at", -1).limit(20)
            new_notes = [n async for n in new_notes_cur]
            # Iter36m — Chat interne : messages reçus depuis last_seen_at ET non
            # encore lus par l'utilisateur (preuve qu'il ne les a pas vus dans
            # le panneau de chat). On compte les DM adressés à lui + les messages
            # du fil collectif qu'il n'a pas lu, à condition que le chat soit
            # activé pour au moins un client dont il est membre.
            new_chat_messages = await db.internal_chat_messages.count_documents({
                "created_at": {"$gt": last_seen_at},
                "read_by": {"$nin": [user["id"]]},
                "$or": [
                    {"recipient_id": user["id"]},
                    {"recipient_id": None, "sender_id": {"$ne": user["id"]}},
                ],
            })
            since_last_visit = {
                "last_seen_at": last_seen_at,
                "new_tickets": new_tickets,
                "new_tickets_count": len(new_tickets),
                "new_whatsapp_count": new_wa,
                "new_notes": new_notes,
                "new_notes_count": len(new_notes),
                "new_chat_messages_count": int(new_chat_messages),
                "total_count": len(new_tickets) + new_wa + len(new_notes) + int(new_chat_messages),
            }
        except (ValueError, TypeError):
            # Invalid ISO timestamp → silently skip
            since_last_visit = None

    # Iter38d — Expense reminder for tracked users with cashier access:
    # Sum of unjustified expenses for the current month + count of those
    # already past the deadline (will be deducted from payslip).
    expense_reminder = None
    try:
        # Iter38m — Show reminder for ANY user with pending unjustified
        # expenses attributed to them (either they created it OR an
        # admin/cashier attributed it to them as employee).
        from routes.cashier_expenses import _is_late_unjustified  # local import
        s_global = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        try:
            deadline_h = int(s_global.get("expense_justification_deadline_hours", 72))
        except (TypeError, ValueError):
            deadline_h = 72
        cur_month = now.strftime("%Y-%m")
        # Iter38m — Include expenses ATTRIBUTED to me as employee
        cursor = db.cashier_expenses.find({
            "is_justified": False,
            "deleted_at": None,
            "expense_date": {"$gte": f"{cur_month}-01", "$lt": f"{cur_month}-32"},
            "$or": [
                {"created_by": user["id"]},
                {"employee_user_id": user["id"]},
            ],
        }, {"_id": 0, "amount": 1, "created_at": 1, "currency": 1})
        total_unj = 0.0
        late_unj = 0.0
        cur = "XOF"
        cnt = 0
        async for e in cursor:
            amt = float(e.get("amount") or 0)
            total_unj += amt
            cnt += 1
            if e.get("currency"):
                cur = e["currency"]
            if _is_late_unjustified(e, deadline_h):
                late_unj += amt
        if cnt > 0:
            expense_reminder = {
                "count": cnt,
                "total_unjustified": round(total_unj, 2),
                "late_unjustified": round(late_unj, 2),
                "deadline_hours": deadline_h,
                "currency": cur,
                "month": cur_month,
            }
    except Exception:
        expense_reminder = None

    return {
        "tickets": tickets,
        "tickets_count": len(tickets),
        "unread_messages": {"whatsapp": unread_wa, "sms": unread_sms, "total": unread_wa + unread_sms},
        "recent_notes": recent_notes,
        "recent_notes_count": len(recent_notes),
        "recent_notes_window_days": notes_days,
        "daily_health": daily_health,
        "since_last_visit": since_last_visit,
        "expense_reminder": expense_reminder,
        "notes_kpis": await _build_welcome_notes_kpis(user),
        "liluvine_autoreply_today": await _build_liluvine_autoreply_stats(user),
        "wa_demo_recent": await _build_wa_demo_recent_stats(user),
        "server_now": _now(),
    }


# Iter38r-fix8b — Compact KPIs for the Welcome modal so the user always
# sees a quick summary of Rapports / Suivis / Notes / Tâches even when
# nothing else is pending. Mirrors the logic of /me/notes-summary but
# also surfaces "overdue" tasks (due_at past).
async def _build_welcome_notes_kpis(user: dict) -> Dict[str, Any]:
    base = {} if _is_elevated_creator(user) else {"owner_id": user["id"]}
    now_iso = datetime.now(timezone.utc).isoformat()

    async def _kpi(coll, label: str) -> Dict[str, Any]:
        cnt = await coll.count_documents(base)
        last = await coll.find_one(base, {"_id": 0, "updated_at": 1, "title": 1}, sort=[("updated_at", -1)])
        return {
            "label": label,
            "count": cnt,
            "last_updated": (last or {}).get("updated_at"),
            "last_title": (last or {}).get("title") or "",
        }

    rep = await _kpi(db.user_reports, "Rapports")
    sui = await _kpi(db.user_suivis, "Suivis")
    notes = await _kpi(db.user_notes_personal, "Notes")
    tasks = await _kpi(db.user_tasks_personal, "Tâches")
    # Overdue tasks (due_at past, status != done) — best-effort
    overdue = await db.user_tasks_personal.count_documents({
        **base,
        "due_at": {"$lt": now_iso, "$ne": None},
        "status": {"$nin": ["done", "completed", "closed"]},
    })
    tasks["overdue"] = int(overdue)
    # Iter38r-fix9h — Recent shared items addressed to me this week
    week_iso = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    shared_counts = {"reports": 0, "suivis": 0, "notes": 0, "tasks": 0}
    if not _is_elevated_creator(user):
        my_tenant = user.get("parent_client_id") or user.get("client_id") or user["id"]
        for kind_key, coll_name in (("reports", "user_reports"), ("suivis", "user_suivis"),
                                     ("notes", "user_notes_personal"), ("tasks", "user_tasks_personal")):
            coll = getattr(db, coll_name)
            q = {
                "owner_id": {"$ne": user["id"]},
                "created_at": {"$gte": week_iso},
                "$or": [
                    {"target_user_ids": user["id"]},
                    {"is_private": {"$ne": True}, "tenant_id": my_tenant},
                ],
            }
            try:
                shared_counts[kind_key] = await coll.count_documents(q)
            except Exception:
                pass
    shared_total = sum(shared_counts.values())
    return {"reports": rep, "suivis": sui, "notes": notes, "tasks": tasks,
            "shared_recent": {"total": shared_total, "by_kind": shared_counts, "window_days": 7}}


# Iter38r-fix9o (Item 8) — Welcome modal widget: recent WA-OTP demo signups.
# Admin/superviseur/moderateur only. Returns up to N items + unseen badge.
async def _build_wa_demo_recent_stats(user: dict) -> Optional[Dict[str, Any]]:
    # Lot 25 — Rôle modérateur accepté sous ses deux orthographes (moderateur / moderator).
    if user.get("role") not in ("admin", "superviseur", "moderateur", "moderator"):
        return None
    items = await db.users.find(
        {"source": "wa_otp_login", "is_demo": True},
        {"_id": 0, "id": 1, "full_name": 1, "phone": 1, "whatsapp": 1, "user_no": 1,
         "created_at": 1, "wa_onboarding_seen_by": 1},
    ).sort("created_at", -1).limit(5).to_list(5)
    total = await db.users.count_documents({"source": "wa_otp_login", "is_demo": True})
    unseen = await db.users.count_documents(
        {"source": "wa_otp_login", "is_demo": True, "wa_onboarding_seen_by": None},
    )
    return {"items": items, "total": int(total), "unseen": int(unseen)}




# Iter38r-fix9d — Welcome modal counter "Liluvine a répondu à X messages
# WhatsApp aujourd'hui". Shows ROI of the auto-reply bot at every login.
async def _build_liluvine_autoreply_stats(user: dict) -> Dict[str, Any]:
    """Returns {today, yesterday, last_7d} counts of WA auto-replies sent.

    S-iter39a — Use _resolve_visible_client_ids so the card is shown to ALL
    privileged viewers of the tenant (admin/superviseur AND tracked-role
    "Moderation"/"Administrateur"/"Superviseur"), regardless of whether
    they live in db.users or db.tracked_users. Previously a tracked
    moderator got user.id (their own UUID) and the counts were always 0.
    """
    visible_scope = await _resolve_visible_client_ids(user)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    y_start = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    y_end = today_start
    w_start = (datetime.now(timezone.utc) - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    base = {"client_id": {"$in": visible_scope}, "role": "assistant", "external_source": "whatsapp_native"}
    today_n = await db.liluvine_pro_messages.count_documents({**base, "created_at": {"$gte": today_start}})
    yest_n = await db.liluvine_pro_messages.count_documents({**base, "created_at": {"$gte": y_start, "$lt": y_end}})
    week_n = await db.liluvine_pro_messages.count_documents({**base, "created_at": {"$gte": w_start}})
    # Estimate time saved (1 minute per message handled manually)
    minutes_saved_today = int(today_n)
    return {
        "today": int(today_n),
        "yesterday": int(yest_n),
        "last_7d": int(week_n),
        "minutes_saved_today": minutes_saved_today,
        "enabled": bool((await db.settings.find_one({"_id": "global"}) or {}).get("liluvine_wa_autoreply_enabled")),
    }
