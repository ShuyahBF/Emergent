# server_parts/p17_demarrage_planificateur.py — Démarrage, alertes contrats en retard, rappels de facturation, planificateur (APScheduler).
# Morceau de l'ancien server.py (lignes 21844 à 23052), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# REGISTER & STARTUP
# ====================================================================


@app.on_event("startup")
async def on_startup():
    # Iter35q — Initialize Emergent Object Storage (best-effort, non-blocking :
    # lot 26, l'initialisation part dans un thread d'arrière-plan).
    try:
        from storage import init_storage as _init_storage
        _init_storage()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[startup] storage init skipped: %s", exc)
    # Iter35u — Pull the DB-stored public_base_url into the in-memory cache.
    await _refresh_public_base_url_cache()
    # Iter37e — Backfill tenant_id on legacy Caisse docs (idempotent, fast).
    try:
        from routes.cashier import backfill_tenant_ids as _cashier_backfill
        stats = await _cashier_backfill(db)
        if any(stats.values()):
            logger.info("[startup] cashier tenant backfill: %s", stats)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[startup] cashier tenant backfill skipped: %s", exc)
    # Indexes — critical for performance as collections grow.
    # New indexes are added on every startup (idempotent).
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id")
    await db.otps.create_index("session_token")
    await db.otps.create_index("expires_at")
    await db.appointments.create_index("scheduled_at")
    await db.appointments.create_index("client_id")
    await db.documents.create_index("category")
    await db.documents.create_index("client_id")
    await db.contents.create_index("slug", unique=True)
    await db.api_traces.create_index("created_at")
    await db.api_traces.create_index("status")
    # Visit tracking — hot path, queried by date + page
    await db.visits.create_index("datetime")
    await db.visits.create_index("session_id")
    # Health & uptime monitor — queried by created_at sort
    await db.auth_checks.create_index("created_at")
    await db.uptime_checks.create_index("created_at")
    # Incidents
    await db.incidents.create_index("started_at")
    await db.incidents.create_index("status")
    await db.incident_subscribers.create_index("email", unique=True)
    await db.incident_subscribers.create_index("confirmation_token")
    await db.incident_subscribers.create_index("unsubscribe_token")
    # User notes (rapports/suivis) — queried by user_id + kind + event_date
    await db.user_notes.create_index([("user_id", 1), ("kind", 1)])
    await db.user_notes.create_index("event_date")
    # Interventions
    await db.interventions.create_index("client_id")
    await db.interventions.create_index("created_at")
    # Access logs
    await db.access_logs.create_index("created_at")
    await db.access_logs.create_index("user_email")
    # Document logs
    await db.document_logs.create_index([("document_id", 1), ("created_at", -1)])
    # 2026-02 fork (P3b) — WhatsApp reply-router tokens. Auto-expire tokens
    # 30 minutes after creation to keep the collection lean (matches the
    # "admin usually reads/answers within 30 min" workflow).
    try:
        from datetime import datetime as _dt  # noqa: F401
        # Convert `created_at` (stored as ISO string) to a Date for the TTL to
        # work — we rely on MongoDB parsing. Since our writes store ISO strings
        # (not BSON Date), the TTL will not fire; use a periodic prune instead.
        # Keep this as a compound index for fast lookup by (code, used).
        await db.wa_reply_tokens.create_index([("code", 1), ("used", 1)])
        await db.wa_reply_tokens.create_index("created_at")
        await db.wa_reply_router_audit.create_index("created_at")
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[wa_reply_tokens] index creation failed: %s", _exc)
    # 2026-02 fork (P0) — Tenant KYC + Smart Comm : unique index per tenant
    try:
        await db.tenant_kyc.create_index("tenant_id", unique=True)
        await db.tenant_smart_comm.create_index("tenant_id", unique=True)
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[tenant_kyc/smart_comm] index creation failed: %s", _exc)
    # Notification badges — lookup by (user_id, module)
    await db.user_module_visits.create_index([("user_id", 1), ("module", 1)], unique=True)
    # Dynamic forms (Phase 4)
    await db.forms.create_index("client_id")
    await db.forms.create_index("is_public")
    await db.forms.create_index("created_at")
    await db.form_submissions.create_index([("form_id", 1), ("user_id", 1)], unique=True)
    await db.form_submissions.create_index("client_id")
    # Directory & WhatsApp (Phase 3)
    await db.directory_contacts.create_index("client_id")
    await db.directory_contacts.create_index([("client_id", 1), ("owner_id", 1)])
    await db.directory_contacts.create_index("unique_code")
    # Iter43-fix7 — Indexes message collections pour accélérer last_interaction_at
    await db.whatsapp_messages.create_index([("created_at", -1)])
    await db.whatsapp_messages.create_index([("timestamp", -1)])
    await db.whatsapp_messages.create_index("from")
    await db.whatsapp_messages.create_index("to")
    # Iter43-fix24az-l retest — Speed up wa_message_id dedup lookup on inbound webhook.
    # Sparse=True because outbound rows only get a wa_message_id after Meta ack.
    await db.whatsapp_messages.create_index(
        [("wa_message_id", 1)], sparse=True, name="wa_message_id_sparse"
    )
    await db.sms_messages.create_index([("created_at", -1)])
    await db.sms_messages.create_index("from")
    await db.sms_messages.create_index("to")
    # Iter43-fix6 — Index sur invoices interventions pour list/sort + lookup tenant
    await db.interventions_invoices.create_index([("tenant_id", 1), ("created_at", -1)])
    await db.interventions_invoices.create_index("invoice_number")
    # One-shot backfill: assign a stable unique_code to any pre-existing contact
    # that doesn't have one yet. The code is generated per client/year using
    # the same counter as new contacts so sequencing is preserved.
    try:
        missing_cursor = db.directory_contacts.find(
            {"$or": [{"unique_code": {"$exists": False}}, {"unique_code": None}, {"unique_code": ""}]},
            {"_id": 0, "id": 1, "client_id": 1, "created_at": 1},
        ).sort("created_at", 1)
        client_cache: Dict[str, dict] = {}
        async for c in missing_cursor:
            cid = c.get("client_id")
            if not cid:
                continue
            client_doc = client_cache.get(cid)
            if client_doc is None:
                client_doc = await db.users.find_one(
                    {"id": cid},
                    {"_id": 0, "id": 1, "client_code": 1, "company": 1, "full_name": 1},
                ) or {"id": cid}
                client_cache[cid] = client_doc
            uc = await _next_contact_unique_code(client_doc)
            await db.directory_contacts.update_one({"id": c["id"]}, {"$set": {"unique_code": uc}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("contact unique_code backfill failed: %s", exc)

    # One-shot migration: fill `client_id` on bridged tracked-user accounts that
    # were created before we started mirroring `parent_client_id` → `client_id`.
    # Without this, legacy ~50 endpoints that resolve scope via
    # `user.get("client_id") or user["id"]` fall back to the user's own id and
    # tracked users never inherit RGPD/feature flags from their parent client.
    try:
        await db.users.update_many(
            {
                "role": "client",
                "parent_client_id": {"$exists": True, "$nin": [None, ""]},
                "$or": [{"client_id": {"$exists": False}}, {"client_id": None}, {"client_id": ""}],
            },
            [{"$set": {"client_id": "$parent_client_id"}}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tracked-user client_id mirror backfill failed: %s", exc)

    # ============================================================
    # iter28 HOTFIX — Re-tag historical CRM data orphaned by iter24.
    #
    # Context: iter24's `client_id` mirror migration set `users.client_id =
    # parent_client_id` on bridged tracked-user accounts. Reads now resolve
    # scope via `user.client_id`, but historical contacts/messages/schedules
    # created BEFORE iter24 are still tagged with the user's OWN id (because
    # back then `client_scope = user.client_id || user.id` fell back to the
    # user id when client_id was empty). Result: those rows became invisible
    # to the bridged user after iter24.
    #
    # This migration re-tags those rows to the parent_client_id and stores
    # the previous value in `client_id_legacy` for traceability/rollback.
    # Idempotent — guarded by `client_id_legacy` not existing yet.
    # ============================================================
    try:
        result = await _migrate_orphan_client_data()
        if result["total_migrated"] > 0:
            logger.info("iter28 orphan-data migration: %s", result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("iter28 orphan-data migration failed: %s", exc)

    # Regression sentinel: dry-run after migration to confirm no orphans remain.
    # If any new orphan appears (e.g. introduced by a future code change), this
    # warning will surface in the logs and admins can re-run via the UI button.
    try:
        post_check = await _migrate_orphan_client_data(dry_run=True)
        if post_check["total_migrated"] > 0:
            logger.warning(
                "iter28 sentinel: %d orphan rows STILL present after auto-migration "
                "across %d user(s) — investigate /admin/migrate-orphan-data",
                post_check["total_migrated"], len(post_check["affected_users"]),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("iter28 sentinel check failed: %s", exc)

    # Iter29 — Force every CRM contact into the new shared model. This is a
    # no-op for new contacts (they already get shared:true at creation), but
    # normalizes legacy private contacts so any code path that still inspects
    # the boolean keeps working. Idempotent.
    try:
        res29 = await db.directory_contacts.update_many(
            {"$or": [{"shared": False}, {"shared": {"$exists": False}}]},
            {"$set": {"shared": True}},
        )
        if int(getattr(res29, "modified_count", 0) or 0) > 0:
            logger.info(
                "iter29 contacts shared-by-default migration: %d rows normalized",
                res29.modified_count,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("iter29 contacts shared migration failed: %s", exc)

    # Iter31 — Client-consistency canary. Surfaces misaligned users at boot
    # so admins are warned BEFORE the affected user complains. Read-only.
    try:
        scan = await _scan_clients_consistency()
        if scan["misaligned_users_total"] > 0:
            logger.warning(
                "iter31 client-consistency canary: %d user(s) misaligned across %d company group(s) — "
                "see /admin/clients-consistency or Settings → 'Cohérence multi-utilisateurs'",
                scan["misaligned_users_total"], scan["misaligned_groups"],
            )
            for g in scan["groups"][:10]:
                logger.warning(
                    "  • %s — canonical=%s via %s — %d/%d misaligned: %s",
                    g["company"], (g["canonical_client_id"] or "")[:8],
                    g["canonical_via"], g["misaligned_count"], g["members_total"],
                    ", ".join(m.get("email") or m["id"][:8] for m in g["misaligned"][:5]),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("iter31 client-consistency canary failed: %s", exc)

    await db.whatsapp_messages.create_index("client_id")
    await db.whatsapp_messages.create_index("created_at")
    await db.whatsapp_schedules.create_index("status")
    await db.whatsapp_schedules.create_index("scheduled_at")
    await db.whatsapp_messages.create_index("payment_link_slug")
    # SMS Phase 1+2
    await db.sms_messages.create_index("client_id")
    await db.sms_messages.create_index("created_at")
    await db.sms_messages.create_index("payment_link_slug")
    await db.sms_messages.create_index([("contact_id", 1), ("created_at", -1)])

    # Lot 29 (performances du Centre de Messagerie) — index composés pour les
    # requêtes les plus fréquentes (liste des contacts, non-lus toutes les 15 s).
    # Créés EN ARRIÈRE-PLAN : sur une grosse collection la construction peut
    # prendre du temps, elle ne doit jamais retarder le démarrage. create_index
    # ne fait rien si l'index existe déjà ; une erreur est seulement journalisée.
    async def _lot29_perf_indexes():
        specs = [
            (db.whatsapp_messages, [("client_id", 1), ("created_at", -1)], "lot29_client_created"),
            (db.whatsapp_messages, [("client_id", 1), ("direction", 1), ("read_by_us_at", 1), ("created_at", -1)],
             "lot29_unread"),
            (db.sms_messages, [("client_id", 1), ("created_at", -1)], "lot29_client_created"),
            (db.wa_pending_imports, [("client_id", 1), ("last_seen_at", -1)], "lot29_client_seen"),
        ]
        for coll, keys, name in specs:
            try:
                await coll.create_index(keys, name=name, background=True)
            except Exception as _exc:  # noqa: BLE001
                logger.warning("[lot29] index %s non créé : %s", name, _exc)
    asyncio.create_task(_lot29_perf_indexes())
    await db.sms_schedules.create_index("status")
    await db.sms_schedules.create_index("scheduled_at")
    await db.sms_schedules.create_index([("client_id", 1), ("status", 1)])
    # Payment links (Iterations 38+)
    await db.payment_links.create_index("slug", unique=True)
    await db.payment_links.create_index("client_id")
    await db.payments.create_index("client_id")
    await db.payments.create_index("deposit_id", unique=True)
    await db.payments.create_index("payment_link_slug")
    await db.automations.create_index("event")
    await db.automations.create_index("enabled")
    await db.client_notes.create_index("client_id")
    await db.client_tasks.create_index("client_id")
    await db.client_tasks.create_index("status")
    await db.client_tasks.create_index("due_at")
    await db.policies.create_index("slot", unique=True)
    await db.ai_summaries.create_index("user_id")
    await db.ai_summaries.create_index([("user_id", 1), ("created_at", -1)])
    await db.ai_summaries.create_index("created_at")
    await db.payments.create_index("deposit_id", unique=True)
    await db.payments.create_index([("user_id", 1), ("created_at", -1)])
    await db.payments.create_index([("client_id", 1), ("created_at", -1)])
    await db.payments.create_index("status")

    # Seed initial admin
    init_email = os.environ.get("ADMIN_INIT_EMAIL")
    init_password = os.environ.get("ADMIN_INIT_PASSWORD")
    init_name = os.environ.get("ADMIN_INIT_NAME", "Administrateur")
    if init_email and init_password:
        existing = await db.users.find_one({"email": init_email.lower()})
        if not existing:
            await db.users.insert_one(
                {
                    "id": _uuid(),
                    "email": init_email.lower(),
                    "full_name": init_name,
                    "password_hash": hash_password(init_password),
                    "role": "admin",
                    "phone": None,
                    "company": "SAWALI SMART SYSTEMS",
                    "account_status": "active",
                    "created_at": _now(),
                }
            )
            logger.info("Initial admin seeded: %s", init_email)

    # Seed default settings
    existing_settings = await db.settings.find_one({"_id": "global"})
    if not existing_settings:
        await db.settings.insert_one(
            {
                "_id": "global",
                "recaptcha_enabled": False,
                "smtp_use_tls": True,
                "business_open_time": "09:00",
                "business_close_time": "18:00",
                "business_days": [0, 1, 2, 3, 4],
                "slot_duration_min": 30,
                "company_email": "contact@sawalismartsystems.com",
                "company_phone": "+228 00 00 00 00",
                "company_address": "Lomé, Togo",
                "google_calendar_email": "sup.alphasofti@gmail.com",
                "assistant_enabled": True,
                "assistant_url": "https://agent.jotform.com/0199e26b35a87a6ea156d196e3e180731e7d?embedMode=popup",
                "assistant_label": "Liluvine — Support Technique",
                "assistant_color": "#0075E3",
            }
        )
    else:
        # Backfill assistant defaults if not present (existing installs)
        update_fields = {}
        if "assistant_url" not in existing_settings:
            update_fields.update({
                "assistant_enabled": True,
                "assistant_url": "https://agent.jotform.com/0199e26b35a87a6ea156d196e3e180731e7d?embedMode=popup",
                "assistant_label": "Liluvine — Support Technique",
                "assistant_color": "#0075E3",
            })
        if update_fields:
            await db.settings.update_one({"_id": "global"}, {"$set": update_fields})

    # Seed default contents (only if not present)
    defaults = [
        {
            "slug": "home_hero",
            "title": "L'ingénierie logicielle au service de votre transformation",
            "body_html": "<p>SAWALI SMART SYSTEMS conçoit, déploie et maintient des solutions logicielles métiers pour les entreprises africaines exigeantes.</p>",
            "images": [],
            "metadata": {
                "kicker": "SAWALI SMART SYSTEMS · SOFTWARE ENGINEERING",
            },
        },
        {
            "slug": "mission",
            "title": "Notre Mission",
            "body_html": (
                "<p>Accompagner les entreprises et institutions dans leur transformation digitale "
                "à travers des logiciels sur-mesure, robustes et évolutifs.</p>"
                "<p>Nous combinons rigueur d'ingénierie et proximité humaine pour livrer des "
                "produits qui durent.</p>"
            ),
            "images": [],
            "metadata": {},
        },
        {
            "slug": "experience",
            "title": "Notre Expérience",
            "body_html": (
                "<p>Plus de 10 ans d'expérience cumulée en conception de systèmes critiques, "
                "des bases de données aux applications web et mobiles.</p>"
            ),
            "images": [],
            "metadata": {
                "metrics": [
                    {"label": "Années d'expérience", "value": "10+"},
                    {"label": "Projets livrés", "value": "50+"},
                    {"label": "Clients satisfaits", "value": "30+"},
                    {"label": "Disponibilité", "value": "24/7"},
                ]
            },
        },
        {
            "slug": "specialisations",
            "title": "Nos Spécialisations",
            "body_html": "",
            "images": [],
            "metadata": {
                "items": [
                    {
                        "title": "Développement Web",
                        "icon": "Globe",
                        "desc": "Plateformes web performantes : portails clients, ERP, CRM sur mesure.",
                    },
                    {
                        "title": "Applications Mobiles",
                        "icon": "Smartphone",
                        "desc": "Apps Android & iOS natives ou hybrides, optimisées pour vos usages métier.",
                    },
                    {
                        "title": "Systèmes Métiers",
                        "icon": "Database",
                        "desc": "Conception de bases de données et systèmes back-office hautement disponibles.",
                    },
                    {
                        "title": "Ingénierie & Conseil",
                        "icon": "Cpu",
                        "desc": "Audit, architecture, automatisation et accompagnement DevOps.",
                    },
                ]
            },
        },
        {
            "slug": "about",
            "title": "À propos",
            "body_html": (
                "<p>SAWALI SMART SYSTEMS est une société d'ingénierie logicielle basée en Afrique "
                "de l'Ouest. Nous mettons l'expertise technique au service d'une vision claire : "
                "rendre vos opérations plus simples, plus rapides, plus fiables.</p>"
            ),
            "images": [],
            "metadata": {},
        },
    ]
    for d in defaults:
        if not await db.contents.find_one({"slug": d["slug"]}):
            d_doc = {
                **d,
                "id": _uuid(),
                "created_at": _now(),
                "updated_at": _now(),
            }
            await db.contents.insert_one(d_doc.copy())


# =============================================================================
# 2026-02 fork iter104 — Contract Overdue Alert scheduler helper.
# Sends the super-admin an email (+ WA if configured) once per day per tenant
# that is past its threshold. De-duplicates through `db.contract_overdue_alerts`.
# =============================================================================
async def _run_contract_overdue_alerts() -> Dict[str, Any]:
    """Scan tenants with contract data and dispatch overdue alerts."""
    today = datetime.now(timezone.utc).date()
    settings_doc = await db.settings.find_one({"_id": "global"}) or {}
    default_threshold = int(settings_doc.get("contract_overdue_days_default") or 5)
    # Lot 27 — suspension automatique seulement si l'interrupteur général est
    # activé (Paramètres → Contrats). Les alertes à l'administrateur continuent.
    auto_suspend_on = bool(settings_doc.get("contract_auto_suspend_enabled"))
    # Only clients with either a `last_payment_at` or `contract_signed_at`.
    q = {
        "role": {"$in": ["admin", "client", "client-tracked"]},
        "$or": [
            {"last_payment_at": {"$exists": True, "$nin": [None, ""]}},
            {"contract_signed_at": {"$exists": True, "$nin": [None, ""]}},
        ],
    }
    cursor = db.users.find(q, {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1,
                                "phone": 1, "whatsapp_number": 1, "last_payment_at": 1,
                                "contract_signed_at": 1, "contract_number": 1,
                                "contract_amount": 1, "contract_currency": 1,
                                "contract_overdue_days": 1,
                                "auto_suspend_after_overdue_days": 1,
                                "account_status": 1})
    overdue_tenants: List[Dict[str, Any]] = []
    suspended_tenants: List[Dict[str, Any]] = []
    async for u in cursor:
        ref_iso = (u.get("last_payment_at") or u.get("contract_signed_at") or "")[:10]
        if not ref_iso:
            continue
        try:
            ref_date = datetime.strptime(ref_iso, "%Y-%m-%d").date()
        except Exception:  # noqa: BLE001
            continue
        days = max(0, (today - ref_date).days)
        threshold = int(u.get("contract_overdue_days") or default_threshold)
        # 2026-02 fork iter108 fix — S159 : Auto-suspend must be evaluated
        # INDEPENDENTLY of the alert threshold so a tenant with a low
        # auto_suspend_after_overdue_days (e.g. 1) but a high alert threshold
        # (default 5) still gets suspended on time.
        suspend_threshold = u.get("auto_suspend_after_overdue_days")
        if (
            auto_suspend_on                                   # lot 27 : interrupteur général
            and not _is_super_admin(u)                        # lot 27 : jamais le super-admin
            and suspend_threshold is not None
            and int(suspend_threshold) > 0
            and days >= int(suspend_threshold)
            and (u.get("account_status") or "active").lower() != "suspended"
        ):
            try:
                await db.users.update_one(
                    {"id": u["id"]},
                    {"$set": {
                        "account_status": "suspended",
                        "suspended_at": _now(),
                        "suspended_reason": f"Auto-suspension : {days} jours de retard (seuil {suspend_threshold} j).",
                        "updated_at": _now(),
                    }},
                )
                suspended_tenants.append({
                    "tenant_id": u["id"],
                    "email": u.get("email"),
                    "company": u.get("company"),
                    "days_overdue": days,
                    "threshold": int(suspend_threshold),
                })
                logger.info("[contract-overdue] auto-suspended tenant %s (%d j retard)", u.get("email"), days)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[contract-overdue] auto-suspend failed for %s: %s", u.get("email"), exc)
        # Alert threshold gate — only queue an email/WA alert once we hit it.
        if days < threshold:
            continue
        overdue_tenants.append({
            **u,
            "days_overdue": days,
            "threshold_days": threshold,
            "ref_field": "last_payment_at" if u.get("last_payment_at") else "contract_signed_at",
            "ref_iso": ref_iso,
        })
    # Dispatch alerts (idempotent per-day).
    dispatched = 0
    recipient_email = (settings_doc.get("health_email_to") or SUPER_ADMIN_EMAIL or "").strip().lower()
    for tenant in overdue_tenants:
        alert_key = f"{tenant['id']}::{today.isoformat()}"
        try:
            existing = await db.contract_overdue_alerts.find_one({"key": alert_key})
            if existing:
                continue
        except Exception:  # noqa: BLE001
            existing = None
        subject = f"[SAWALI] Retard de paiement — {tenant.get('company') or tenant.get('email')} ({tenant['days_overdue']} j)"
        body_lines = [
            f"Le client « {tenant.get('company') or tenant.get('full_name') or tenant.get('email')} » a dépassé le seuil de retard de paiement.",
            "",
            f"  · Retard : {tenant['days_overdue']} jour(s) (seuil : {tenant['threshold_days']} j)",
            f"  · Basé sur : {tenant['ref_field']} = {tenant['ref_iso']}",
            f"  · N° contrat : {tenant.get('contract_number') or '—'}",
            f"  · Montant contrat : {tenant.get('contract_amount') or '—'} {tenant.get('contract_currency') or ''}",
            f"  · Email client : {tenant.get('email') or '—'}",
            f"  · Téléphone : {tenant.get('phone') or tenant.get('whatsapp_number') or '—'}",
            "",
            "Consultez l'écran /admin/clients pour prendre une action.",
        ]
        body_text = "\n".join(body_lines)
        email_sent = False
        wa_sent = False
        wa_error: Optional[str] = None
        if recipient_email:
            try:
                email_sent = await send_email(recipient_email, subject, body_text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[contract-overdue] email failed for %s: %s", tenant.get("email"), exc)
        # 2026-02 fork iter107 (S157) — Alerte WhatsApp au super-admin en plus
        # de l'email. Nécessite `settings.super_admin_phone` défini et un
        # template Meta `alerte_retard_paiement` approuvé (variables 1-5).
        super_wa = (settings_doc.get("super_admin_phone") or "").strip()
        wa_template = (settings_doc.get("contract_overdue_wa_template") or "alerte_retard_paiement").strip()
        if super_wa and wa_template:
            ctx = {
                "full_name": tenant.get("company") or tenant.get("full_name") or "—",
                "days_overdue": str(tenant["days_overdue"]),
                "threshold_days": str(tenant["threshold_days"]),
                "contract_number": tenant.get("contract_number") or "—",
                "amount_due": f"{tenant.get('contract_amount') or ''} {tenant.get('contract_currency') or ''}".strip() or "—",
            }
            variables = [
                "{{full_name}}", "{{days_overdue}}", "{{threshold_days}}",
                "{{contract_number}}", "{{amount_due}}",
            ]
            components = _build_components(variables, ctx)
            try:
                wr = await _wa_send_template(super_wa, wa_template, "fr", components)
                wa_sent = bool(wr.get("ok"))
                wa_error = wr.get("error")
            except Exception as exc:  # noqa: BLE001
                wa_error = str(exc)[:200]
                logger.warning("[contract-overdue] WA failed: %s", exc)
        try:
            await db.contract_overdue_alerts.insert_one({
                "id": _uuid(),
                "key": alert_key,
                "tenant_id": tenant["id"],
                "tenant_email": tenant.get("email"),
                "tenant_company": tenant.get("company"),
                "days_overdue": tenant["days_overdue"],
                "threshold_days": tenant["threshold_days"],
                "ref_field": tenant["ref_field"],
                "ref_iso": tenant["ref_iso"],
                "email_recipient": recipient_email,
                "email_sent": email_sent,
                "wa_recipient": super_wa or None,
                "wa_template": wa_template if super_wa else None,
                "wa_sent": wa_sent,
                "wa_error": wa_error,
                "sent_at": _now(),
            })
        except Exception:  # noqa: BLE001
            pass
        dispatched += 1
    return {"scanned": len(overdue_tenants), "dispatched": dispatched, "threshold_default": default_threshold,
            "suspended": len(suspended_tenants), "suspended_details": suspended_tenants}


# =============================================================================
# 2026-02 fork iter108 — S158 : Recurring contract billing reminders.
# Cron-invoked helper. Runs daily at 07:45 Africa/Abidjan. For each tenant with
# `contract_billing_period` set (monthly / quarterly / annual), compute the
# next billing date = `last_payment_at` (or `contract_signed_at`) + period.
# If it falls within the next 3 days (inclusive today), fire a WA + Email
# reminder to the tenant. De-duplicates via `db.billing_reminders`.
# =============================================================================
PERIOD_DAYS_MAP = {"monthly": 30, "quarterly": 90, "annual": 365}


async def _run_recurring_billing_reminders() -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    q = {
        "role": {"$in": ["admin", "client", "client-tracked"]},
        "contract_billing_period": {"$in": list(PERIOD_DAYS_MAP.keys())},
        "$or": [
            {"last_payment_at": {"$exists": True, "$nin": [None, ""]}},
            {"contract_signed_at": {"$exists": True, "$nin": [None, ""]}},
        ],
    }
    cursor = db.users.find(q, {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1,
                                "phone": 1, "whatsapp_number": 1, "last_payment_at": 1,
                                "contract_signed_at": 1, "contract_billing_period": 1,
                                "contract_amount": 1, "contract_currency": 1,
                                "contract_number": 1})
    reminders: List[Dict[str, Any]] = []
    async for u in cursor:
        period = (u.get("contract_billing_period") or "").lower()
        period_days = PERIOD_DAYS_MAP.get(period)
        if not period_days:
            continue
        ref_iso = (u.get("last_payment_at") or u.get("contract_signed_at") or "")[:10]
        if not ref_iso:
            continue
        try:
            ref_date = datetime.strptime(ref_iso, "%Y-%m-%d").date()
        except Exception:  # noqa: BLE001
            continue
        next_billing = ref_date + timedelta(days=period_days)
        days_to_billing = (next_billing - today).days
        # Fire reminder in the [0, 3] day window before due date.
        if days_to_billing < 0 or days_to_billing > 3:
            continue
        reminders.append({
            **u,
            "next_billing": next_billing.isoformat(),
            "days_to_billing": days_to_billing,
        })
    # Dispatch with idempotency per-day.
    dispatched = 0
    for t in reminders:
        key = f"{t['id']}::{t['next_billing']}"
        try:
            if await db.billing_reminders.find_one({"key": key}):
                continue
        except Exception:  # noqa: BLE001
            pass
        subject = f"[SAWALI] Rappel de facturation — {t.get('company') or t.get('email')} (J-{t['days_to_billing']})"
        due_hint = "aujourd'hui" if t['days_to_billing'] == 0 else f"dans {t['days_to_billing']} jour(s)"
        body_text = (
            f"Bonjour {t.get('full_name') or t.get('email')},\n\n"
            f"Votre prochaine échéance contractuelle est le {t['next_billing']} "
            f"({due_hint}).\n\n"
            f"  · Contrat : {t.get('contract_number') or '—'}\n"
            f"  · Montant : {t.get('contract_amount') or '—'} {t.get('contract_currency') or ''}\n"
            f"  · Périodicité : {t.get('contract_billing_period')}\n\n"
            "Merci de préparer le règlement dans les délais pour éviter toute suspension d'accès.\n\n"
            "L'équipe SAWALI SMART SYSTEMS."
        )
        email_sent = False
        wa_sent = False
        wa_error: Optional[str] = None
        recipient_email = (t.get("email") or "").strip().lower()
        if recipient_email:
            try:
                email_sent = await send_email(recipient_email, subject, body_text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[billing-reminder] email failed for %s: %s", recipient_email, exc)
        # Best-effort WA reminder to the tenant's own phone (if configured).
        wa_number = (t.get("whatsapp_number") or t.get("phone") or "").strip()
        if wa_number:
            try:
                # Reuse the confirmation_paiement_avecrecu template as a generic reminder.
                # If the tenant has a more specific template configured, fall back to plain text.
                wr = await _wa_send_text(wa_number, body_text)
                wa_sent = bool(wr.get("ok"))
                wa_error = wr.get("error")
            except Exception as exc:  # noqa: BLE001
                wa_error = str(exc)[:200]
                logger.warning("[billing-reminder] WA failed for %s: %s", wa_number, exc)
        try:
            await db.billing_reminders.insert_one({
                "id": _uuid(),
                "key": key,
                "tenant_id": t["id"],
                "tenant_email": t.get("email"),
                "next_billing": t["next_billing"],
                "days_to_billing": t["days_to_billing"],
                "email_sent": email_sent,
                "wa_sent": wa_sent,
                "wa_error": wa_error,
                "sent_at": _now(),
            })
        except Exception:  # noqa: BLE001
            pass
        dispatched += 1
    # 2026-02 fork iter108 fix — return `details` for parity with contract-overdue/run.
    details = [{
        "tenant_id": t["id"],
        "email": t.get("email"),
        "company": t.get("company"),
        "next_billing": t["next_billing"],
        "days_to_billing": t["days_to_billing"],
    } for t in reminders]
    return {"scanned": len(reminders), "dispatched": dispatched, "details": details}


@api.post("/admin/billing-reminders/run", tags=["Admin"])
async def admin_run_billing_reminders_now(_: dict = Depends(get_current_admin)):
    """2026-02 fork iter108 — Manually trigger the recurring-billing scan
    (for debugging / on-demand run). The daily cron runs at 07:45 Africa/Abidjan."""
    return await _run_recurring_billing_reminders()



@api.post("/admin/contract-overdue/run", tags=["Admin"])
async def admin_run_contract_overdue_now(_: dict = Depends(get_current_admin)):
    """2026-02 fork iter104 — Manually trigger the contract overdue scan (for
    debugging / on-demand run). The daily cron runs at 08:15 Africa/Abidjan."""
    return await _run_contract_overdue_alerts()



# ====================================================================
# Lot 27 — PLANIFICATEUR (APScheduler)
# Ce bloc se trouvait par erreur APRÈS le « return » de
# admin_run_contract_overdue_now : il ne s'exécutait jamais et AUCUNE tâche
# planifiée ne tournait (envois WhatsApp/SMS programmés, rappels, résumés,
# sauvegardes…). Il a maintenant son propre crochet de démarrage.
# Garde-fous ajoutés pour la réactivation : envois programmés trop en retard
# annulés (_expire_stale_schedules), relances Caisse automatiques bornées,
# suspension automatique des comptes derrière un interrupteur général,
# chaque tâche préparée séparément (une erreur n'empêche plus les autres).
# ====================================================================
_SCHEDULER_STATE = "pas encore démarré"


@api.get("/admin/scheduler/status", tags=["Admin"])
async def admin_scheduler_status(_: dict = Depends(get_current_admin)):
    """Lot 27 — état du planificateur : démarré ou non (et pourquoi), liste des
    tâches et date de leur prochain passage."""
    jobs = []
    if _scheduler is not None:
        for j in _scheduler.get_jobs():
            nrt = getattr(j, "next_run_time", None)
            jobs.append({"id": j.id, "next_run": nrt.isoformat() if nrt else None})
    return {"running": bool(_scheduler is not None and _scheduler.running), "state": _SCHEDULER_STATE,
            "jobs": sorted(jobs, key=lambda x: x["id"]), "count": len(jobs),
            "stale_schedule_limit_hours": SCHEDULE_MAX_LATE_HOURS}


@app.on_event("startup")
async def _start_scheduler():
    global _scheduler
    # Lot 27 — JAMAIS dans l'environnement PREVIEW : sa base reçoit des copies
    # de la production (instantanés), il enverrait de vrais messages aux
    # clients en double. Même détection que le résumé hebdomadaire.
    # Variables : DISABLE_SCHEDULER=1 (coupe partout), SCHEDULER_IN_PREVIEW=1
    # (force l'activation dans la preview, pour un test volontaire).
    env_url = (os.environ.get("PUBLIC_BASE_URL", "") or os.environ.get("preview_endpoint", "")
               or os.environ.get("REACT_APP_BACKEND_URL", ""))
    global _SCHEDULER_STATE
    if os.environ.get("DISABLE_SCHEDULER") == "1":
        _SCHEDULER_STATE = "désactivé (DISABLE_SCHEDULER=1)"
        logger.info("[scheduler] %s", _SCHEDULER_STATE)
        return
    if ".preview." in env_url and os.environ.get("SCHEDULER_IN_PREVIEW") != "1":
        _SCHEDULER_STATE = f"non démarré : environnement PREVIEW ({env_url})"
        logger.info("[scheduler] %s", _SCHEDULER_STATE)
        return

    def _safe_add_job(*args, **kwargs):
        """Ajoute une tâche ; en cas d'erreur, on la journalise et on continue."""
        try:
            _scheduler.add_job(*args, **kwargs)
        except Exception:  # noqa: BLE001
            logger.exception("[scheduler] tâche %s non ajoutée", kwargs.get("id"))

    # ---------- Scheduler ----------
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        if _scheduler is None:
            _scheduler = AsyncIOScheduler(timezone="Africa/Abidjan")
            _safe_add_job(
                _send_weekly_digest,
                CronTrigger(day_of_week="fri", hour=5, minute=0, timezone="Africa/Abidjan"),
                id="health_weekly_digest",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            # Hourly auth checker — only fires alert if health_auth_check_enabled is on,
            # but always persists the result to db.auth_checks for the dashboard banner.
            async def _scheduled_auth_check():
                await _run_auth_check(triggered_by="cron:hourly")
            _safe_add_job(
                _scheduled_auth_check,
                CronTrigger(minute=0, timezone="Africa/Abidjan"),
                id="auth_checker_hourly",
                replace_existing=True,
                misfire_grace_time=600,
            )
            # Hourly uptime monitor — multi-endpoint probes (db + public APIs).
            async def _scheduled_uptime():
                await _run_uptime_probes(triggered_by="cron:hourly")
            _safe_add_job(
                _scheduled_uptime,
                CronTrigger(minute=5, timezone="Africa/Abidjan"),  # offset 5min from auth check
                id="uptime_monitor_hourly",
                replace_existing=True,
                misfire_grace_time=600,
            )
            # Iter35b — every 4h check whether Meta is calling our WA webhook.
            async def _scheduled_wa_silence():
                await _run_wa_silence_check(triggered_by="cron:4h")
            _safe_add_job(
                _scheduled_wa_silence,
                CronTrigger(hour="*/4", minute=20, timezone="Africa/Abidjan"),
                id="wa_silence_detector_4h",
                replace_existing=True,
                misfire_grace_time=900,
            )
            # Iter43-fix24ap (2026-06-17) — every 4h, verify Google Calendar
            # refresh_token + Meta webhook subscription. Alerts admin via
            # WhatsApp on failures (throttled 12h to avoid spam).
            async def _scheduled_integration_health():
                await _run_integration_health_check(triggered_by="cron:4h")
            _safe_add_job(
                _scheduled_integration_health,
                CronTrigger(hour="*/4", minute=35, timezone="Africa/Abidjan"),
                id="integration_health_monitor_4h",
                replace_existing=True,
                misfire_grace_time=900,
            )
            # Minute-level WhatsApp scheduler — drains pending schedules due for send.
            _safe_add_job(
                _run_scheduled_whatsapp,
                CronTrigger(minute="*", timezone="Africa/Abidjan"),
                id="whatsapp_scheduler_minutely",
                replace_existing=True,
                misfire_grace_time=120,
            )
            # Iter43-fix24av (2026-02-26) — Minute-level LinkedIn auto-post tick.
            async def _scheduled_linkedin_autopost():
                await _run_linkedin_autopost_tick(db)
            _safe_add_job(
                _scheduled_linkedin_autopost,
                CronTrigger(minute="*", timezone="Africa/Abidjan"),
                id="linkedin_autopost_minutely",
                replace_existing=True,
                misfire_grace_time=120,
            )
            # Iter43-fix24ay (2026-02-26) — Google Calendar Watch channel renewal (every 6h)
            async def _scheduled_gcal_watch_renewal():
                await _run_gcal_watch_renewal(db)
            _safe_add_job(
                _scheduled_gcal_watch_renewal,
                CronTrigger(hour="*/6", timezone="Africa/Abidjan"),
                id="gcal_watch_renewal_6h",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            # Iter43-fix24az-n (2026-07-18) — Rappels WhatsApp 1h avant RDV Planning
            async def _scheduled_planning_wa_reminders():
                try:
                    await _run_planning_wa_reminders()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[planning] reminder job failed: %s", exc)
            _safe_add_job(
                _scheduled_planning_wa_reminders,
                CronTrigger(minute="*/5", timezone="UTC"),
                id="planning_wa_reminders_5min",
                replace_existing=True,
                misfire_grace_time=600,
            )
            # 2026-02 fork iter104 — Contract Overdue Alert (daily at 08:15 Africa/Abidjan).
            # Scan all tenants with contract fields set and email/WhatsApp the
            # super-admin when a tenant is past its threshold.
            async def _scheduled_contract_overdue_alerts():
                try:
                    await _run_contract_overdue_alerts()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[contract-overdue] job failed: %s", exc)
            _safe_add_job(
                _scheduled_contract_overdue_alerts,
                CronTrigger(hour=8, minute=15, timezone="Africa/Abidjan"),
                id="contract_overdue_alerts_daily",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            # 2026-02 fork iter108 — S158 : Recurring billing reminders (daily at 07:45 Africa/Abidjan).
            async def _scheduled_recurring_billing_reminders():
                try:
                    await _run_recurring_billing_reminders()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[billing-reminder] job failed: %s", exc)
            _safe_add_job(
                _scheduled_recurring_billing_reminders,
                CronTrigger(hour=7, minute=45, timezone="Africa/Abidjan"),
                id="recurring_billing_reminders_daily",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            # Iter38d — Monthly payroll outbound webhook (1st of month, 03:00 UTC).
            try:
                _safe_add_job(
                    _pwh_router._scheduled_auto_dispatch,  # type: ignore[attr-defined]
                    CronTrigger(day=1, hour=3, minute=0, timezone="UTC"),
                    id="payroll_outbound_monthly",
                    replace_existing=True,
                    misfire_grace_time=3600,
                )
                logger.info("Iter38d — Scheduled payroll outbound webhook (monthly @ 1st 03:00 UTC).")
            except Exception as _ex:
                logger.warning("Failed to schedule payroll outbound webhook: %s", _ex)
            # Minute-level SMS scheduler — drains pending SMS schedules due for send.
            _safe_add_job(
                _run_scheduled_sms,
                CronTrigger(minute="*", timezone="Africa/Abidjan"),
                id="sms_scheduler_minutely",
                replace_existing=True,
                misfire_grace_time=120,
            )
            # Hourly appointment reminders (J-1 window).
            _safe_add_job(
                _appointment_reminder_cron,
                CronTrigger(minute=15, timezone="Africa/Abidjan"),
                id="appointment_reminder_hourly",
                replace_existing=True,
                misfire_grace_time=600,
            )
            # Iter41 Phase 3 — Daily Liluvine synthèse cron.
            # Reads `synthese_hour` from settings.global ("HH:MM") and dispatches
            # via email / WA / both according to `synthese_channels`. We register
            # an hourly trigger that internally compares the current hour:minute
            # to the configured one — that way the user can change the time
            # without restarting the backend.
            try:
                async def _synthese_minute_check():
                    try:
                        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "synthese_enabled": 1, "synthese_hour": 1}) or {}
                        if not s.get("synthese_enabled"):
                            return
                        from datetime import datetime as _dt
                        now = _dt.now()
                        hhmm = (s.get("synthese_hour") or "08:00").strip()
                        try:
                            h, m = hhmm.split(":")
                            if int(h) != now.hour or int(m) != now.minute:
                                return
                        except (ValueError, AttributeError):
                            return
                        from routes.synthese import run_scheduled_synthese
                        result = await run_scheduled_synthese(db)
                        logger.info("[synthese] scheduled run: %s", result)
                    except Exception:
                        logger.exception("[synthese] minute_check crashed")

                _safe_add_job(
                    _synthese_minute_check,
                    CronTrigger(minute="*", timezone="Africa/Abidjan"),
                    id="liluvine_synthese_minutely",
                    replace_existing=True,
                    misfire_grace_time=120,
                )
                logger.info("Iter41 Phase 3 — Scheduled Liluvine synthèse (minute check).")
            except Exception as _ex:
                logger.warning("Failed to schedule synthèse cron: %s", _ex)
            # Hourly task reminders (1h window before due_at).
            _safe_add_job(
                _task_reminder_cron,
                CronTrigger(minute=20, timezone="Africa/Abidjan"),
                id="task_reminder_hourly",
                replace_existing=True,
                misfire_grace_time=600,
            )

            # Iter38r-fix9l — WA Tasks digest cron (every 5 min, gated by
            # per-user wa_tasks_digest_hour) + Liluvine weekly digest (Monday
            # 8h Africa/Abidjan) + GDPR daily anonymization (03:30).
            async def _scheduled_wa_tasks_digest():
                try:
                    await _run_wa_tasks_digest(db, _send_wa_text_for_digest, _get_settings_async)
                except Exception as exc:
                    logger.warning("[scheduler:wa_tasks_digest] %s", exc)
            _safe_add_job(
                _scheduled_wa_tasks_digest,
                CronTrigger(minute="*/5", timezone="Africa/Abidjan"),
                id="wa_tasks_digest_5min",
                replace_existing=True,
                misfire_grace_time=300,
            )

            # 2026-02 fork (P3) — Médecin planning WA digest (every 5 min,
            # per-user opt-in `planning_wa_digest_enabled` + hour). Idempotent
            # sur `planning_wa_last_digest_at`.
            async def _scheduled_medecin_planning_digest():
                try:
                    from routes.medecin_planning_digest import run_medecin_planning_digest as _rmpd  # noqa: E402
                    await _rmpd(db, _send_wa_text_for_digest)
                except Exception as exc:
                    logger.warning("[scheduler:medecin_planning_digest] %s", exc)
            _safe_add_job(
                _scheduled_medecin_planning_digest,
                CronTrigger(minute="*/5", timezone="Africa/Abidjan"),
                id="medecin_planning_digest_5min",
                replace_existing=True,
                misfire_grace_time=300,
            )

            # Iter43-fix3 (2026-03) — Surveillance quotidienne du token WhatsApp.
            # Alerte par email les admins quand le token expire dans <7 jours ou
            # quand le test fonctionnel échoue (token révoqué, phone suspendu…).
            async def _scheduled_wa_token_health():
                try:
                    s = await db.settings.find_one({"_id": "global"}) or {}
                    access_token = (s.get("wa_access_token") or "").strip()
                    if not access_token:
                        return
                    # Réutilise la logique de admin_wa_token_health en mode interne
                    waba_diag: Dict[str, Any] = {}
                    try:
                        async with httpx.AsyncClient(timeout=8) as http:
                            params = {"input_token": access_token,
                                      "access_token": access_token}
                            app_id = (s.get("meta_app_id") or "").strip()
                            app_secret = (s.get("meta_app_secret") or "").strip()
                            if app_id and app_secret:
                                params["access_token"] = f"{app_id}|{app_secret}"
                            r = await http.get(
                                f"https://graph.facebook.com/{WA_GRAPH_VERSION}/debug_token",
                                params=params,
                            )
                            waba_diag = (r.json() or {}).get("data") or {}
                    except Exception:
                        return
                    is_valid = bool(waba_diag.get("is_valid"))
                    token_type = waba_diag.get("type")
                    exp = waba_diag.get("expires_at") or 0
                    days_left = None
                    if exp and exp > 0:
                        from datetime import datetime as _dt, timezone as _tz
                        days_left = (_dt.fromtimestamp(exp, tz=_tz.utc) - _dt.now(_tz.utc)).total_seconds() / 86400
                    alert = None
                    if not is_valid:
                        alert = "❌ Token WhatsApp INVALIDE — les envois échouent en ce moment."
                    elif token_type == "USER" and days_left is not None and days_left < 7:
                        alert = f"⚠️ Token WhatsApp expire dans {days_left:.1f} jour(s). Régénérez un token SYSTEM_USER permanent."
                    if alert:
                        try:
                            admins = await db.users.find(
                                {"role": "admin", "account_status": "active"},
                                {"_id": 0, "email": 1},
                            ).to_list(20)
                            for a in admins:
                                if a.get("email"):
                                    await send_email(
                                        a["email"],
                                        "[SAWALI] Token WhatsApp à renouveler",
                                        f"<h2>Diagnostic WhatsApp</h2><p>{alert}</p><p>Connectez-vous à AdminSettings → WhatsApp → « Diagnostic du token » pour plus d'infos.</p>",
                                    )
                        except Exception as exc:
                            logger.warning("[scheduler:wa_token_alert] email send failed: %s", exc)
                except Exception as exc:
                    logger.warning("[scheduler:wa_token_health] %s", exc)
            _safe_add_job(
                _scheduled_wa_token_health,
                CronTrigger(hour=7, minute=30, timezone="Africa/Abidjan"),
                id="wa_token_health_daily",
                replace_existing=True,
                misfire_grace_time=3600,
            )



            async def _scheduled_liluvine_weekly_digest():
                try:
                    await _run_liluvine_weekly_digest(db, send_email, _get_settings_async)
                except Exception as exc:
                    logger.warning("[scheduler:liluvine_digest] %s", exc)
            _safe_add_job(
                _scheduled_liluvine_weekly_digest,
                CronTrigger(day_of_week="mon", hour=8, minute=0, timezone="Africa/Abidjan"),
                id="liluvine_weekly_digest_mon",
                replace_existing=True,
                misfire_grace_time=3600,
            )

            async def _scheduled_gdpr_anonymize():
                try:
                    await _run_gdpr_anonymization(db, _get_settings_async)
                except Exception as exc:
                    logger.warning("[scheduler:gdpr_anonymize] %s", exc)
            _safe_add_job(
                _scheduled_gdpr_anonymize,
                CronTrigger(hour=3, minute=30, timezone="Africa/Abidjan"),
                id="gdpr_auto_anonymize_daily",
                replace_existing=True,
                misfire_grace_time=3600,
            )

            # S031 — Universal Key health probe (every 15 min) + daily admin
            # alert email while the key is exhausted.
            # S032 — Also send proactive warning/critical alerts (email + WA)
            # before the budget is fully exhausted.
            from routes.llm_health import (
                ping_emergent_llm as _llm_ping,
                maybe_send_budget_alert_email as _llm_alert,
                maybe_send_budget_warning_alerts as _llm_warning_alerts,
            )
            async def _scheduled_llm_health_ping():
                try:
                    await _llm_ping(db)
                    await _llm_alert(db, send_email)
                    await _llm_warning_alerts(db, send_email, _wa_send_text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[scheduler:llm_health] %s", exc)
            _safe_add_job(
                _scheduled_llm_health_ping,
                CronTrigger(minute=10, timezone="Africa/Abidjan"),
                id="llm_health_ping_15min",
                replace_existing=True,
                misfire_grace_time=300,
            )
            # Weekly DB auto-snapshot — Sunday 03:00 (Africa/Abidjan), gated by
            # settings.auto_snapshot_enabled. Keeps the last N (settings
            # .auto_snapshot_keep, default 4) auto snapshots; manual ones
            # never rotate.
            async def _scheduled_auto_snapshot():
                try:
                    s = await db.settings.find_one({"_id": "global"}) or {}
                    if not s.get("auto_snapshot_enabled"):
                        return
                    await _run_auto_snapshot(triggered_by="cron:weekly-sun-03")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Auto-snapshot cron failed: %s", exc)
            _safe_add_job(
                _scheduled_auto_snapshot,
                CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="Africa/Abidjan"),
                id="db_auto_snapshot_weekly",
                replace_existing=True,
                misfire_grace_time=3600,
            )

            # Lot 49 — Sauvegarde complète quotidienne (03:00 Africa/Abidjan) : export chiffré par
            # SAUVEGARDE_AUTO_PHRASE envoyé dans Cloudflare R2, rétention 7/4/12, rapport e-mail.
            # Sans la phrase ou sans R2, rien n'est fait (alerte dans l'admin).
            async def _scheduled_sauvegarde_complete():
                try:
                    from routes.sauvegarde_complete import sauvegarde_automatique as _sauvegarde_auto
                    await _sauvegarde_auto("cron:quotidienne-03h")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Sauvegarde complète quotidienne en échec : %s", exc)
            _safe_add_job(
                _scheduled_sauvegarde_complete,
                CronTrigger(hour=3, minute=0, timezone="Africa/Abidjan"),
                id="sauvegarde_complete_quotidienne",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
                max_instances=1,
            )

            # Iter36y — Daily auto-relance cron (09:00 Africa/Abidjan). The
            # runner itself checks the master toggle + configured day_of_week
            # before acting, so a single cron entry covers all flavours.
            async def _scheduled_auto_relance():
                try:
                    await _run_auto_relance_cashier(triggered_by="cron:daily-09")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Auto-relance cron failed: %s", exc)
            _safe_add_job(
                _scheduled_auto_relance,
                CronTrigger(hour=9, minute=0, timezone="Africa/Abidjan"),
                id="cashier_auto_relance_daily",
                replace_existing=True,
                misfire_grace_time=3600,
            )

            # Iter38r-fix9u — Daily AI subscription renewal reminders
            # (08:00 Africa/Abidjan). Calls process_due_reminders() which
            # scans active subs and dispatches WA + Email reminders for those
            # within their reminder window. Idempotent per 18 h.
            async def _scheduled_ai_subs_reminders():
                try:
                    from routes.ai_subscriptions import process_due_reminders as _proc
                    async def _email_adapter(*, to: str, subject: str, body_text: str):
                        return await send_email(to, subject, body_text, body_text)
                    async def _wa_adapter(*, to: str, body: str):
                        return await _wa_send_text(to, body)
                    await _proc(db, send_email_fn=_email_adapter, send_whatsapp_fn=_wa_adapter)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("AI subscriptions reminders cron failed: %s", exc)
            _safe_add_job(
                _scheduled_ai_subs_reminders,
                CronTrigger(hour=8, minute=0, timezone="Africa/Abidjan"),
                id="ai_subscriptions_reminders_daily",
                replace_existing=True,
                misfire_grace_time=3600,
            )

            # Iter38r-fix9z6 — Daily ad-banner expiration reminders
            # (09:30 Africa/Abidjan). Emails advertisers with a renewal link
            # when their campaign expiration falls within `reminder_days_before`.
            async def _scheduled_ad_banner_reminders():
                try:
                    from routes.ad_banners import process_expiration_reminders as _proc
                    # Pull public base URL from settings if available, otherwise from env
                    settings = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
                    public_base = (
                        settings.get("public_base_url")
                        or os.environ.get("PUBLIC_BASE_URL")
                        or os.environ.get("REACT_APP_BACKEND_URL")
                        or ""
                    )
                    res = await _proc(
                        db,
                        send_email_fn=send_email,
                        public_base_url=public_base,
                        send_whatsapp_fn=_wa_send_text,
                    )
                    if res.get("sent"):
                        logger.info("Ad banner reminders sent: %s", len(res["sent"]))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Ad banner reminders cron failed: %s", exc)
            _safe_add_job(
                _scheduled_ad_banner_reminders,
                CronTrigger(hour=9, minute=30, timezone="Africa/Abidjan"),
                id="ad_banner_expiration_reminders_daily",
                replace_existing=True,
                misfire_grace_time=3600,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scheduler init failed: %s", exc)
    finally:
        # Lot 27 : le planificateur démarre avec toutes les tâches préparées,
        # même si l'une d'elles a échoué.
        if _scheduler is not None and not _scheduler.running:
            _scheduler.start()
            _SCHEDULER_STATE = f"démarré — {len(_scheduler.get_jobs())} tâche(s) planifiée(s)"
            logger.info("[scheduler] %s", _SCHEDULER_STATE)
