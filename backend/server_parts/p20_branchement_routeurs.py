# server_parts/p20_branchement_routeurs.py — Branchement des routeurs des modules routes/* (SMS, chat, caisse, GRH, Meta, etc.).
# Morceau de l'ancien server.py (lignes 25326 à 26420), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# =====================================================================
# Iter35z — SMS Dashboard router (extracted to routes/sms_dashboard.py)
# Mounted under /api/admin/sms/dashboard alongside the rest of admin API.
# =====================================================================
from routes.sms_dashboard import make_router as _make_sms_dashboard_router  # noqa: E402
_sms_dashboard_router = _make_sms_dashboard_router(db=db, get_current_admin=get_current_admin)
api.include_router(_sms_dashboard_router)

# =====================================================================
# Iter36k — Internal real-time chat router (REST + WebSocket).
# REST routes live under /api/me/chat/... ; WS at /api/ws/chat?token=<jwt>.
# =====================================================================
from routes.internal_chat import make_router as _make_chat_router  # noqa: E402
from auth import decode_token as _decode_token  # noqa: E402
_chat_router = _make_chat_router(db=db, get_current_user=get_current_user, decode_token=_decode_token)
api.include_router(_chat_router)

# =====================================================================
# Iter36u — Caisse & Facturation router (receipts, invoices, products,
# business_clients, payment_methods, public QR verification).
# =====================================================================
from routes.cashier import make_router as _make_cashier_router  # noqa: E402
_cashier_router, _run_auto_relance_cashier = _make_cashier_router(
    db=db,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
    get_current_supervisor=get_admin_or_supervisor,
    wa_send_text=_wa_send_text,
    wa_send_template=_wa_send_template,  # Iter37g — for receipts/invoices templates
    send_email=send_email,
)
api.include_router(_cashier_router)

# =====================================================================
# Iter38 — GRH (Gestion des Ressources Humaines) router.
# Phases 1+2+3: Personnel, Salaires, Présence (computed from access_logs).
# =====================================================================
from routes.hr import make_router as _make_hr_router  # noqa: E402
_hr_router = _make_hr_router(db=db, get_current_user=get_current_user)
api.include_router(_hr_router)

# =====================================================================
# Iter38b — Tenant country / dial-prefix metadata.
# =====================================================================
from routes.tenant_meta import make_router as _make_tenant_meta_router  # noqa: E402
_tm_router = _make_tenant_meta_router(
    db=db,
    get_current_user=get_current_user,
    get_current_admin=get_admin_or_supervisor,
)
api.include_router(_tm_router)

# =====================================================================
# Iter38c — Cashier Expenses module (Dépenses caisse/chèque, justification
# avec délai admin-configurable, intégration paie).
# =====================================================================
from routes.cashier_expenses import make_router as _make_expenses_router  # noqa: E402
_exp_router = _make_expenses_router(db=db, get_current_user=get_current_user)
api.include_router(_exp_router)

# =====================================================================
# Iter38d — Payroll webhooks (outbound to n8n + inbound from n8n).
# =====================================================================
from routes.payroll_webhooks import make_router as _make_payroll_webhooks_router  # noqa: E402
_pwh_router = _make_payroll_webhooks_router(
    db=db,
    get_current_user=get_current_user,
    get_current_admin=get_admin_or_supervisor,
    compute_payslip=_hr_router.compute_payslip,
)
api.include_router(_pwh_router)

# =====================================================================
# Iter38h — Meta Graph API integration (Pages + Messenger + Ads).
# =====================================================================
from routes.meta import setup_meta_routes as _setup_meta_routes  # noqa: E402

async def _meta_save_settings(updates: dict) -> None:
    """Persist a partial settings update under the singleton {_id:'global'} doc."""
    if not updates:
        return
    await db.settings.update_one({"_id": "global"}, {"$set": updates}, upsert=True)

_setup_meta_routes(
    db=db,
    api=api,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
    get_settings_doc=_get_settings_doc,
    save_settings=_meta_save_settings,
    public_base_url_fn=_public_base_url,
    _normalize_features=_normalize_features,
)

# =====================================================================
# Iter38i — Unified omnichannel inbox (WhatsApp + Messenger).
# =====================================================================
from routes.unified_inbox import setup_unified_inbox_routes as _setup_inbox_routes  # noqa: E402
# =====================================================================
# Iter38k — Unified inbox helper for SMS dispatch (uses the existing
# _sms_dispatch pipeline). Returns the standard {ok, id, error} shape.
# =====================================================================
async def _inbox_sms_send_helper(user: dict, msisdn: str, text: str) -> dict:  # noqa: ANN001
    try:
        result = await _sms_dispatch("auto", msisdn, text, None)
        parent_id = user.get("client_id") or user["id"]
        doc = {
            "id": _uuid(),
            "client_id": parent_id,
            "user_id": user["id"],
            "user_email": user.get("email"),
            "user_label": user.get("full_name") or user.get("email"),
            "provider": result.get("provider"),
            "msisdn": msisdn,
            "msisdn_digits": "".join(ch for ch in msisdn if ch.isdigit()),
            "message": text,
            "length": len(text),
            "status": result.get("status"),
            "api_message": result.get("api_message"),
            "http_status": result.get("http_status"),
            "created_at": _now(),
        }
        await db.sms_messages.insert_one(doc.copy())
        doc.pop("_id", None)
        return {
            "ok": bool(result.get("ok")),
            "id": doc["id"],
            "status": result.get("status"),
            "error": None if result.get("ok") else _safe_text(result.get("api_message")),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}

INBOX_SMS_HELPER_DEFINED = True


# Iter43-fix24b — Bird SMS sender adapter pour l'inbox unifiée
async def _inbox_bird_send_helper(to: str, text: str) -> dict:  # noqa: ANN001
    """Wrapper async qui appelle send_bird_sms et persiste dans bird_sms_messages."""
    try:
        from routes.bird_sms import send_bird_sms as _send_bird
        res = await _send_bird(db, to=to, text=text)
        await db.bird_sms_messages.insert_one({
            "id": _uuid(),
            "direction": "outbound",
            "from": "portal",
            "to": to,
            "phone_digits": "".join(ch for ch in to if ch.isdigit()),
            "text": text,
            "bird_response": res,
            "provider": "bird",
            "created_at": _now().isoformat(),
        })
        return {"ok": True, "id": res.get("id") or "", "response": res}
    except HTTPException as he:
        raise he
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


_setup_inbox_routes(
    db=db, api=api, get_current_user=get_current_user,
    _normalize_features=_normalize_features,
    wa_send_text=_wa_send_text,
    sms_send_text=_inbox_sms_send_helper,
    bird_send_text=_inbox_bird_send_helper,
)

# =====================================================================
# Lot 60 — Appels WhatsApp (API Calling de Meta) : sonnerie dans le portail,
# décroché depuis le navigateur, rappel avec autorisation du client, journal.
# =====================================================================
from routes.appels_wa import setup_appels_wa_routes as _setup_appels_wa  # noqa: E402
_setup_appels_wa(
    db=db, api=api, get_current_user=get_current_user,
    resolve_visible_client_ids=_resolve_visible_client_ids,
    graph_version=WA_GRAPH_VERSION,
)

# Lot 67 — Liluvine prévient le propriétaire (relais + appel vocal WhatsApp) à chaque message d'un client
from routes.appel_proprietaire import setup_appel_proprietaire_routes as _setup_appel_proprio  # noqa: E402
_setup_appel_proprio(db=db, api=api, get_current_user=get_current_user, graph_version=WA_GRAPH_VERSION)

# Lot 61 — liste noire des numéros interdits aux commandes « ! » (administration)
from routes.liste_noire_commandes import setup_liste_noire_commandes_routes as _setup_liste_noire_cmd  # noqa: E402
_setup_liste_noire_cmd(db=db, api=api, get_current_user=get_current_user)
# Lot 64.2 — diagnostic de la barrière anti-rafale WhatsApp pour un numéro
from routes.barriere_wa import setup_barriere_wa_routes as _setup_barriere_wa  # noqa: E402
_setup_barriere_wa(db=db, api=api, get_current_user=get_current_user,
                   resolve_visible_client_ids=_resolve_visible_client_ids)
# Lot 61.1 — écran « Activité des plateformes » (adLyn, beAuthentik…)
from routes.rapport_plateformes import setup_rapport_plateformes_routes as _setup_rapport_plateformes  # noqa: E402
_setup_rapport_plateformes(db=db, api=api, get_current_user=get_current_user)
# Lot 65 — versions déployées (SAWALI, plateformes web, Loois et ses postes)
from routes.versions_deployees import setup_versions_deployees_routes as _setup_versions_deployees  # noqa: E402
_setup_versions_deployees(db=db, api=api, get_current_user=get_current_user, lire_version=version)
# Lot 68 — synchro des tables HFSQL des clients Loois vers MongoDB (page Plateformes → Loois → Synchro)
from routes.loois_synchro import setup_loois_synchro_routes as _setup_loois_synchro  # noqa: E402
_setup_loois_synchro(db=db, api=api, get_current_user=get_current_user)

# =====================================================================
# Iter38k — Gemini Nano Banana image generation (icons + media generator).
# =====================================================================
from routes.ai_media import setup_ai_media_routes as _setup_ai_media_routes  # noqa: E402
_setup_ai_media_routes(db=db, api=api, get_current_user=get_current_user)

# =====================================================================
# Iter38n — Catalogue public analytics (vues, partages, devis).
# =====================================================================
from routes.catalog_analytics import setup_catalog_analytics_routes as _setup_catalog_analytics  # noqa: E402
_CATALOG_ANALYTICS = _setup_catalog_analytics(
    db=db, api=api, get_current_user=get_current_user,
)

# Iter38o — Stripe Checkout for paid formations.
from routes.payments_stripe import setup_stripe_routes as _setup_stripe_routes  # noqa: E402
_setup_stripe_routes(db=db, api=api, get_current_user=get_current_user, send_email_fn=send_email)

# Iter43-fix20 (2026-06) — Météo widget (Open-Meteo + IP geolocation).
from routes.weather import setup_weather_routes as _setup_weather_routes  # noqa: E402
_setup_weather_routes(db=db, api=api)

# Iter43-fix22 (2026-06) — Garde planning hebdomadaire + WA requests tracker.
from routes.garde_planning import setup_garde_planning_routes as _setup_garde_routes  # noqa: E402
_setup_garde_routes(db=db, api=api, get_current_admin=get_current_admin)
from routes.liluvine_wa_requests import setup_liluvine_wa_requests_routes as _setup_wa_req_routes  # noqa: E402
from auth import get_current_admin_or_moderator  # noqa: E402
_setup_wa_req_routes(db=db, api=api, get_user_with_roles=get_current_admin_or_moderator)

# Iter43-fix23b (2026-06) — Bird.com 2-Way SMS Integration (remplace Africa's Talking)
from routes.bird_sms import setup_bird_sms_routes as _setup_bird_routes  # noqa: E402
_setup_bird_routes(db=db, api=api, get_current_admin=get_current_admin)

# Iter43-fix23 (2026-06) — Webhook inventaire officines (Bearer token)
from routes.officines_inventory_webhook import setup_officines_inventory_webhook_routes as _setup_inv_wh  # noqa: E402
_setup_inv_wh(db=db, api=api)

# Iter38r-fix5 — AI Quotas & Usage Tracking per Client Lié.
from routes.ai_quotas import setup_ai_quotas_routes as _setup_ai_quotas_routes, track_ai_usage as _track_ai_usage  # noqa: E402, F401
_setup_ai_quotas_routes(
    db=db, api=api,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
)

# Iter38r-fix6 — Liluvine PRO / Assistant SAWALI interne.
from routes.liluvine_pro import setup_liluvine_pro_routes as _setup_liluvine_pro_routes  # noqa: E402
_setup_liluvine_pro_routes(db=db, api=api, get_current_user=get_current_user, wa_send_text=_wa_send_text)

# Iter40 (2026-02) — Business RAG ACL admin endpoints
from routes.liluvine_business_rag import attach_admin_acl_routes as _attach_business_acl  # noqa: E402
_attach_business_acl(api=api, db=db, get_current_user=get_current_user)

# S045 Phase 2 (2026-02) — Admin settings & incidents read-only endpoints
from routes.admin_settings import attach_admin_settings_routes as _attach_admin_settings  # noqa: E402
_attach_admin_settings(
    api=api, db=db,
    get_current_admin=get_current_admin,
    get_settings_doc=_get_settings_doc,
)

# Iter40 (2026-02) — Contact groups for SMS/WA bulk targeting
from routes.contact_groups import attach_contact_groups_routes as _attach_contact_groups  # noqa: E402
_attach_contact_groups(api=api, db=db, get_current_user=get_current_user)


# Lot 27 — Sondages WhatsApp (routes/wa_surveys.py) : conception, envoi à
# plusieurs contacts (lien personnel par destinataire), mesure des retours.
async def _wa_enabled_for(user: dict) -> bool:
    """Module WhatsApp autorisé pour ce compte (même règle que l'envoi en masse)."""
    if user.get("role") in ("admin", "superviseur"):
        return True
    parent = await db.users.find_one({"id": user.get("client_id") or user["id"]}, {"_id": 0, "features": 1})
    return bool(_normalize_features((parent or {}).get("features")).get("whatsapp"))


async def _sms_enabled_for(user: dict) -> bool:
    """Lot 35 — module SMS autorisé pour ce compte (même règle que /me/features)."""
    if user.get("role") in ("admin", "superviseur"):
        return True
    parent_id = user.get("parent_client_id") or user.get("client_id") or user["id"]
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
    return bool(_normalize_features((parent or {}).get("features")).get("sms"))


def _is_preview_environment() -> bool:
    """Même détection que le planificateur : adresse « .preview. »."""
    env_url = (os.environ.get("PUBLIC_BASE_URL", "") or os.environ.get("preview_endpoint", "")
               or os.environ.get("REACT_APP_BACKEND_URL", ""))
    return ".preview." in env_url


from routes.wa_surveys import attach_wa_survey_routes as _attach_wa_surveys  # noqa: E402


async def _signaler_reponse_sondage(sondage: dict, invitation: dict) -> None:
    """Lot 41 — automatisation « Nouvelle réponse à un sondage » (en tâche de fond)."""
    async def _go():
        try:
            if not sondage.get("client_id"):
                return
            n = await db.wa_survey_responses.count_documents({"survey_id": sondage["id"]})
            await _emit_event("survey.responded", {"client_id": sondage["client_id"], "extra_ctx": {
                "sondage": sondage.get("title") or "", "repondant": invitation.get("name") or "Anonyme",
                "nb_reponses": str(n)}})
        except Exception:  # noqa: BLE001
            logger.warning("[automations] survey.responded non émis", exc_info=True)
    asyncio.create_task(_go())
# Lot 42 — plages horaires d'envoi (Paramètres de l'Admin) : les envois de sondages et de
# liens de formulaires n'ont lieu que dans ces plages, et reprennent seuls à la suivante.
from routes.plages_envoi import attach_plages_envoi_routes as _attach_plages_envoi  # noqa: E402
_plages_envoi = _attach_plages_envoi(api=api, db=db, get_current_admin=get_current_admin,
                                     get_current_user=get_current_user)
# Lot 34 — routes des sondages réservées aux comptes dont « Formulaires et Sondages »
# est activé (SMART Communications) ; liens publics : même contrôle sur le propriétaire.
_wa_surveys = _attach_wa_surveys(
    api=api, db=db, get_current_user=_utilisateur_formulaires, uuid_fn=_uuid,
    can_send_wa=_can_send_wa, is_admin_like=_is_admin_or_superviseur,
    resolve_visible_client_ids=_resolve_visible_client_ids, wa_enabled_for=_wa_enabled_for,
    enforce_demo_quota=lambda user, n: _enforce_demo_quota(user, QUOTA_KEY_WA, increment=n),
    wa_send_template=_wa_send_template, wa_send_text=_wa_send_text,
    wa_window_open=_wa_window_open, build_recipient_ctx=_build_recipient_ctx,
    build_components=_build_components, public_base_url=_public_base_url,
    is_preview_env=_is_preview_environment,
    owner_enabled=lambda client_id: _fonction_active_pour_compte(client_id, "forms_surveys"),
    # Lot 35 — envoi du lien personnel par SMS (opérateur par défaut de la plateforme)
    sms_enabled_for=_sms_enabled_for,
    sms_send=lambda numero, texte: _sms_dispatch("auto", numero, texte, None),
    enforce_sms_quota=lambda user, n: _enforce_demo_quota(user, QUOTA_KEY_SMS, increment=n),
    on_reponse=_signaler_reponse_sondage,          # lot 41 : automatisation « survey.responded »
    plages=_plages_envoi,                          # lot 42 : plages horaires et envois programmés
)

# Lot 42 — envoi du lien d'un formulaire public à des contacts (WhatsApp ou SMS),
# immédiat ou programmé, dans les plages horaires ; destinataires calculés comme les sondages.
from routes.envois_formulaires import attach_envois_formulaires_routes as _attach_envois_formulaires  # noqa: E402
_envois_formulaires = _attach_envois_formulaires(
    api=api, db=db, get_current_user=_utilisateur_formulaires, uuid_fn=_uuid,
    can_send_wa=_can_send_wa, is_admin_like=_is_admin_or_superviseur, wa_enabled_for=_wa_enabled_for,
    enforce_demo_quota=lambda user, n: _enforce_demo_quota(user, QUOTA_KEY_WA, increment=n),
    wa_send_template=_wa_send_template, wa_send_text=_wa_send_text,
    build_recipient_ctx=_build_recipient_ctx, build_components=_build_components,
    public_base_url=_public_base_url, resolve_contacts=_wa_surveys["resolve_contacts"],
    open_window_digits=_wa_surveys["open_window_digits"], plages=_plages_envoi,
    is_preview_env=_is_preview_environment, sms_enabled_for=_sms_enabled_for,
    sms_send=lambda numero, texte: _sms_dispatch("auto", numero, texte, None),
    enforce_sms_quota=lambda user, n: _enforce_demo_quota(user, QUOTA_KEY_SMS, increment=n),
)


# Lot 27 — Facturation du portefeuille formulaires & sondages par client :
# tarifs + prompt IA (page SMART Communications du client), bilan de période
# (chiffres, analyse IA, PDF) et facture dans la Caisse (routes/portfolio_billing.py).
from routes.portfolio_billing import attach_portfolio_billing_routes as _attach_portfolio_billing  # noqa: E402
from routes.ai_quotas import track_ai_usage as _track_ai_usage_pf  # noqa: E402
_attach_portfolio_billing(
    api=api, db=db, get_current_admin=get_current_admin, uuid_fn=_uuid,
    get_billing_manager=get_admin_or_supervisor,     # le Superviseur facture (et choisit la TVA)
    public_base_url=_public_base_url,
    create_invoice_for_client=getattr(_cashier_router, "create_invoice_for_client", None),
    track_ai_usage=_track_ai_usage_pf,
)


@app.on_event("startup")
async def _resume_wa_surveys():
    """Reprend un envoi de sondage interrompu par un redémarrage (hors preview)."""
    asyncio.create_task(_wa_surveys["resume"]())
    asyncio.create_task(_envois_formulaires["demarrer"]())      # lot 42 : envois de formulaires

# Iter40 (2026-02) — Form categories (max 6 per tenant)
from routes.form_categories import attach_form_categories_routes as _attach_form_categories  # noqa: E402
_attach_form_categories(api=api, db=db, get_current_user=_utilisateur_formulaires)  # lot 34

# Lot 33 — « Créer depuis un document » : Word, Excel, PDF ou photos d'un questionnaire
# → brouillon de formulaire ou de sondage WhatsApp (routes/import_formulaire.py).
from routes.import_formulaire import attach_import_formulaire_routes as _attach_import_formulaire  # noqa: E402
_attach_import_formulaire(
    api=api, db=db, get_current_user=_utilisateur_formulaires, uuid_fn=_uuid,   # lot 34
    next_form_number=_next_form_number, slugify_code=_slugify_code, is_admin_like=_is_admin_or_superviseur,
)

# Lot 36 — Commande WhatsApp « !formulaire » (Liluvine) : document ou photo → formulaire
# privé, tarif selon le type de client, paiement Mobile Money, puis mise en ligne avec un
# lien crypté de saisie et un lien crypté des réponses (routes/liluvine_formulaire.py).
from routes.liluvine_formulaire import attach_liluvine_formulaire_routes as _attach_liluvine_formulaire  # noqa: E402


async def _journal_liluvine_formulaire(*, label: str, target_id: str = None):
    """Lot 41 — entrée du journal d'activité (visible par l'Admin de la plateforme)."""
    admin = await db.users.find_one({"role": "admin"}, {"_id": 0, "id": 1}) or {}
    await _log_activity(client_id=admin.get("id"), kind="liluvine", action="blacklisted", label=label,
                        actor={"id": "liluvine", "full_name": "Liluvine"}, target_id=target_id)


_liluvine_formulaire = _attach_liluvine_formulaire(
    api=api, db=db, uuid_fn=_uuid, get_admin_or_supervisor=get_admin_or_supervisor,
    get_current_admin=get_current_admin, wa_send_text=_wa_send_text,
    lire_media=lambda info: (UPLOAD_DIR / info["stored_name"]).read_bytes(),
    public_base_url=_public_base_url, next_form_number=_next_form_number, slugify_code=_slugify_code,
    gen_slug=_gen_slug, mnos=DEFAULT_CLIENT_PAWAPAY_MNOS, secret=LINK_JWT_SECRET,
    # Lot 37 — sondage de satisfaction : repli SMS si WhatsApp refuse (fenêtre de 24 h fermée)
    sms_send=lambda numero, texte: _sms_dispatch("auto", numero, texte, None),
    # Lot 41 — liste noire : entrée au journal d'activité
    journal_activite=_journal_liluvine_formulaire,
    # Lot 41 — automatisation « Nouvelle soumission de formulaire » (lien crypté)
    on_soumission=_signaler_soumission,
)
_HOOKS_APRES_PAIEMENT.append(_liluvine_formulaire["apres_paiement"])

# Lot 41 — Maintenance des équipements confiés (fonction activable) : routes/maintenance_equipements.py
from routes.maintenance_equipements import attach_maintenance_routes as _attach_maintenance  # noqa: E402


import object_storage as _obj_storage_mnt  # noqa: E402 — lot 43 (même module que plus bas)


async def _maintenance_mnos(compte_id: str) -> list:
    """Lot 43 — opérateurs Mobile Money du compte (sinon ceux de la plateforme par défaut)."""
    u = await db.users.find_one({"id": compte_id}, {"_id": 0, "pawapay_mnos": 1}) or {}
    return _normalize_pawapay_mnos(u.get("pawapay_mnos")) or list(DEFAULT_CLIENT_PAWAPAY_MNOS)


async def _maintenance_paiements_autorises(user: dict) -> bool:
    """Lot 43 — même règle que les liens de paiement du portail (fonction « payments »)."""
    if _is_admin_or_superviseur(user):
        return True
    parent = await db.users.find_one({"id": user.get("client_id") or user["id"]}, {"_id": 0, "features": 1}) or {}
    return bool(_normalize_features(parent.get("features")).get("payments"))


_attach_maintenance(api=api, db=db, get_current_user=get_current_user, fonction_active=_fonction_active,
                    slugify_code=_slugify_code, is_admin_like=_is_admin_or_superviseur,
                    # Lot 43 — photos, envoi WhatsApp, lien de paiement, facturation
                    save_and_log=_obj_storage_mnt.save_and_log,
                    base_publique=lambda: _public_base_url() or _PUBLIC_BASE_URL,
                    wa_send_text=_wa_send_text, wa_send_media=_wa_send_media, wa_send_template=_wa_send_template,
                    build_components=_build_components, fenetres_ouvertes=_wa_surveys["open_window_digits"],
                    gen_slug=_gen_slug, mnos_du_compte=_maintenance_mnos,
                    paiements_autorises=_maintenance_paiements_autorises,
                    create_invoice_for_client=getattr(_cashier_router, "create_invoice_for_client", None))

# Lot 47 — Parc informatique (fonction activable) : équipements, interventions, rapport public
# signé par le responsable du client — routes/parc_informatique.py.
from routes.parc_informatique import attach_parc_routes as _attach_parc  # noqa: E402


async def _parc_envoyer_email(a: str, sujet: str, corps_html: str, texte: str) -> bool:
    """Lot 47 — envoi du lien du rapport par e-mail (SMTP existant)."""
    from email_service import send_email as _send_email_parc
    return bool(await _send_email_parc(a, sujet, corps_html, texte))


async def _parc_notifier_admin(sujet: str, texte: str) -> dict:
    """Lot 47 — rapport signé : message « 🤖 Liluvine » aux numéros admin (même envoi que le
    rapport des sauvegardes programmées : texte dans les 24 h, sinon modèle réglé, sinon e-mail)."""
    from routes.migration_programmation import envoyer_rapport as _rapport_liluvine, lire_reglage as _reglage_liluvine
    return await _rapport_liluvine(sujet, texte, await _reglage_liluvine(), important=True)


_attach_parc(api=api, db=db, get_current_user=get_current_user, fonction_active=_fonction_active,
             slugify_code=_slugify_code, is_admin_like=_is_admin_or_superviseur,
             save_and_log=_obj_storage_mnt.save_and_log,
             base_publique=lambda: _public_base_url() or _PUBLIC_BASE_URL,
             wa_send_text=_wa_send_text, wa_send_template=_wa_send_template,
             build_components=_build_components, fenetres_ouvertes=_wa_surveys["open_window_digits"],
             envoyer_email=_parc_envoyer_email, notifier_admin=_parc_notifier_admin,
             client_ip=_client_ip_from_request)

# Lot 44 — « Voir en tant que » (super-admin, lecture seule par défaut, journal) et comptes
# de test en un clic : routes/voir_en_tant_que.py. Le contrôle des sessions « en tant que »
# est un intergiciel HTTP placé devant toutes les routes (ajouté au plus près des routes).
from routes.voir_en_tant_que import attach_voir_en_tant_que_routes as _attach_voir_en_tant_que  # noqa: E402
import jwt as _pyjwt_imp  # noqa: E402
from auth import JWT_SECRET as _JWT_SECRET_IMP, JWT_ALGORITHM as _JWT_ALGO_IMP, decode_token as _decode_token_imp  # noqa: E402


async def _journal_voir_en_tant_que(*, action: str, admin: dict, cible_id: Optional[str], label: str):
    """Lot 44 — entrée du journal d'activité (visible par l'Admin de la plateforme)."""
    await _log_activity(client_id=admin.get("id"), kind="voir_en_tant_que", action=action, label=label,
                        actor=admin, target_id=cible_id)


_attach_voir_en_tant_que(
    app=app, api=api, db=db, get_current_user=get_current_user, get_current_admin=get_current_admin,
    encode_jwt=lambda charge: _pyjwt_imp.encode(charge, _JWT_SECRET_IMP, algorithm=_JWT_ALGO_IMP),
    decode_jwt=_decode_token_imp, hash_password=hash_password, client_ip=_client_ip_from_request,
    roles_suivi=TRACKED_USER_ROLES, to_user_public=_to_user_public,
    # le lien de connexion des comptes de test suit l'adresse d'où l'Admin travaille
    base_publique=lambda req: _public_base_url(req) or _PUBLIC_BASE_URL,
    journal_activite=_journal_voir_en_tant_que, super_admin_email=SUPER_ADMIN_EMAIL)

# Lot 41 — calendrier dans la discussion WhatsApp : moments occupés (RDV, planning, Google
# Calendar de la plateforme, créneaux bloqués) et lien public de disponibilités.
from routes.calendrier_partage import attach_calendrier_partage_routes as _attach_calendrier  # noqa: E402
_attach_calendrier(api=api, db=db, get_current_user=get_current_user,
                   public_base_url=lambda: _public_base_url() or _PUBLIC_BASE_URL,
                   google_freebusy=gcal.freebusy, is_admin_like=_is_admin_or_superviseur)

# Lot 41 — nouvelles données reçues (formulaires / sondages) : bulles verte et bleue de
# la barre latérale et puce verte sur chaque formulaire ou sondage — routes/nouveautes_formulaires.py.
from routes.nouveautes_formulaires import attach_nouveautes_formulaires_routes as _attach_nouveautes_fs  # noqa: E402
_attach_nouveautes_fs(api=api, db=db, get_current_user=get_current_user, fonction_active=_fonction_active,
                      is_admin_like=_is_admin_or_superviseur)


@app.on_event("startup")
async def _relances_sondage_liluvine():
    """Lot 37 — relances du sondage de satisfaction « !formulaire » (toutes les 30 min, hors preview)."""
    if not _is_preview_environment():
        asyncio.create_task(_liluvine_formulaire["boucle_relances"]())

# Iter40 (2026-02) — Registre des erreurs (logiciels externes)
from routes.error_registry import attach_error_registry_routes as _attach_error_registry  # noqa: E402
_attach_error_registry(api=api, db=db, get_current_user=get_current_user)

# Iter41 (2026-02) — Module VIDAL France (médicaments / monographies / alertes)
from routes.vidal import attach_vidal_routes as _attach_vidal  # noqa: E402
_attach_vidal(
    api=api, db=db,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
    # Lot 11 — "Envoi WA" de l'ordonnance sécurisée : mêmes coroutines déjà
    # utilisées pour !doc/!rech, déjà résolues plus haut (_wa_helpers).
    wa_send_media=_wa_send_media,
    wa_send_text=_wa_send_text,
)

# Iter43-fix24at (2026-02-26) — Favoris VIDAL par utilisateur
from routes.vidal_favorites import attach_vidal_favorites_routes as _attach_vidal_favorites  # noqa: E402
_attach_vidal_favorites(api=api, db=db, get_current_user=get_current_user)

# Portage site-meetafrican — Fiche produit VIDAL (voies + documents + vmp_id),
# recherche structurée, équivalences, proxy documents et Posologie (expérimental).
from routes.vidal_fiche import attach_vidal_fiche_routes as _attach_vidal_fiche  # noqa: E402
_vidal_fiche = _attach_vidal_fiche(api=api, db=db, get_current_user=get_current_user)

# ============================================================
# Lot 39 — Stock des produits par client/dépôt (fin de pointage + envoi Loois)
# et vérification des ordonnances : routes/ordonnances_stock.py. Équivalents
# cherchés avec le module VIDAL ci-dessus (même accès, cache et quota).
# ============================================================
from routes.ordonnances_stock import attach_ordonnances_stock_routes as _attach_ordonnances_stock  # noqa: E402
_attach_ordonnances_stock(
    api=api, db=db, get_current_user=get_current_user, fonction_active=_fonction_active,
    vidal_rechercher=(_vidal_fiche or {}).get("rechercher"),
    vidal_equivalents=(_vidal_fiche or {}).get("equivalents"),
)

# Portage site-meetafrican — cache local du référentiel produits VIDAL :
# boucle de fond qui relance une synchronisation complète quand la
# fréquence configurée par l'admin est écoulée (désactivée par défaut,
# voir routes/vidal_sync.py::get_sync_config).
from routes.vidal_sync import sync_scheduler_loop as _vidal_sync_scheduler_loop  # noqa: E402

@app.on_event("startup")
async def _start_vidal_sync_scheduler():
    asyncio.create_task(_vidal_sync_scheduler_loop(db))

# Iter43-fix24au (2026-02-26) — Intégration LinkedIn (OAuth2 + Posts API)
from routes.linkedin import attach_linkedin_routes as _attach_linkedin  # noqa: E402
_attach_linkedin(
    api=api, db=db,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
)

# Iter43-fix24av (2026-02-26) — LinkedIn weekly auto-post (Liluvine + cron)
from routes.linkedin_autopost import (  # noqa: E402
    attach_linkedin_autopost_routes as _attach_linkedin_autopost,
    run_linkedin_autopost_tick as _run_linkedin_autopost_tick,
    handle_linkedin_autopost_wa_reply as _handle_linkedin_autopost_wa_reply,
)
_attach_linkedin_autopost(api=api, db=db, get_current_admin=get_current_admin)

# Iter43-fix24aw (2026-02-26) — Officines GPS geocoding (Google Maps + OSM)
from routes.officines_geocode import attach_officines_geocode_routes as _attach_officines_geocode  # noqa: E402
_attach_officines_geocode(api=api, db=db, get_current_admin=get_current_admin)

# Iter43-fix24az-f (2026-02-26) — Production module (Fabricant tenants)
from routes.production import attach_production_routes as _attach_production  # noqa: E402
_attach_production(api=api, db=db, get_current_user=get_current_user)

# Iter43-fix24ax (2026-02-26) — Twitter (X) API v2 integration
from routes.twitter import attach_twitter_routes as _attach_twitter  # noqa: E402
_attach_twitter(api=api, db=db, get_current_user=get_current_user, get_current_admin=get_current_admin)

# Iter43-fix24ax (2026-02-26) — Facebook Page integration
from routes.facebook import attach_facebook_routes as _attach_facebook  # noqa: E402
_attach_facebook(api=api, db=db, get_current_user=get_current_user, get_current_admin=get_current_admin)

# Iter43-fix24ay (2026-02-26) — Google Calendar Watch API (push notifications)
from routes.google_calendar_watch import (  # noqa: E402
    attach_google_calendar_watch_routes as _attach_gcal_watch,
    run_google_calendar_watch_renewal_tick as _run_gcal_watch_renewal,
)
_attach_gcal_watch(api=api, db=db, get_current_admin=get_current_admin, get_current_user=get_current_user)

# 2026-02 — Configurable WhatsApp inbound notification sound
from routes.wa_notification_sound import attach_notification_sound_routes as _attach_wa_notif_sound  # noqa: E402
_attach_wa_notif_sound(api=api, db=db, get_current_admin=get_current_admin, upload_dir=UPLOAD_DIR)

# 2026-02 fork (P0) — Tenant KYC + per-tenant Smart Communications
from routes.tenant_kyc import attach_tenant_kyc_routes as _attach_tenant_kyc  # noqa: E402
_attach_tenant_kyc(
    api=api, db=db,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
    upload_dir=UPLOAD_DIR,
    is_super_admin=_is_super_admin,
    super_admin_email=SUPER_ADMIN_EMAIL,
)

# Iter41 Phase 2 (2026-02) — Table AMM (régulateurs)
from routes.amm import attach_amm_routes as _attach_amm  # noqa: E402
_attach_amm(api=api, db=db, get_current_user=get_current_user)

# Iter41 Phase 3 (2026-02) — API Officines (lookup + WA !aizenta)
from routes.officines import attach_officines_routes as _attach_officines  # noqa: E402
_attach_officines(api=api, db=db, get_current_user=get_current_user)

# Iter41 Phase 4 (2026-02) — VIDAL usage dashboard + public officines inscription
from routes.vidal_dashboard import (  # noqa: E402
    attach_vidal_dashboard_routes as _attach_vidal_dashboard,
    attach_public_officines_routes as _attach_public_officines,
)
_attach_vidal_dashboard(api=api, db=db, get_current_admin=get_current_admin)
_attach_public_officines(api=api, db=db)

# Iter42 (2026-02) — Self-Service Portal pour Officines (auth dédiée, JWT,
# OTP WA/SMS, magic link email, inventaire CRUD, historique CSV, validation
# admin requise avant activation).
from routes.officines_portal import (  # noqa: E402
    attach_officines_portal_routes as _attach_officines_portal,
    attach_officines_portal_admin_routes as _attach_officines_portal_admin,
    attach_synthese_otp_admin_routes as _attach_synthese_otp_admin,
    make_get_current_officine as _make_get_current_officine,
)
from routes.iter42d_incidents_and_lookup import (  # noqa: E402
    attach_iter42d_routes as _attach_iter42d,
)
from auth import JWT_SECRET as _JWT_SECRET, JWT_ALGORITHM as _JWT_ALGO  # noqa: E402

_PUBLIC_BASE_URL = (os.environ.get("PUBLIC_APP_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")

_attach_officines_portal(
    api=api,
    db=db,
    jwt_secret=_JWT_SECRET,
    jwt_algorithm=_JWT_ALGO,
    wa_send_text=_wa_send_text,
    sms_send=_sms_dispatch,
    email_send=send_email,
    public_base_url=_PUBLIC_BASE_URL,
)
_attach_officines_portal_admin(
    api=api, db=db, get_current_admin=get_current_admin,
    # Iter43-fix24n — get_current_user permet la délégation aux non-admin
    get_current_user=get_current_user,
)
_attach_synthese_otp_admin(
    api=api, db=db, get_current_admin=get_current_admin,
    wa_send_text=_wa_send_text,
)
# Iter42d (2026-02) — Webhook incidents entrant + Lookup AMM
_attach_iter42d(
    api=api, db=db, get_current_admin=get_current_admin,
    get_current_officine=_make_get_current_officine(db=db, jwt_secret=_JWT_SECRET, jwt_algorithm=_JWT_ALGO),
)

# Iter43-fix10 (2026-03) — Story Studio (AI video generation + WhatsApp share)
from routes.story_studio import attach_story_studio_routes as _attach_story_studio  # noqa: E402
_attach_story_studio(
    api=api, db=db,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
    get_admin_or_supervisor=get_admin_or_supervisor,
)

# Iter43-fix24az-m (2026-07-18) — Planning médecins (webhook + calendrier)
from routes.planning import attach_planning_routes as _attach_planning  # noqa: E402
import jwt as _pyjwt_planning  # noqa: E402
def _planning_jwt_decode(token: str) -> dict:
    return _pyjwt_planning.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
_planning_helpers = _attach_planning(
    api=api, db=db,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
    _is_admin_or_superviseur=_is_admin_or_superviseur,
    _resolve_visible_client_ids=_resolve_visible_client_ids,
    _is_super_admin=_is_super_admin,
    _public_base_url=_public_base_url,
    wa_send_text=_wa_send_text,
    wa_send_template=_wa_send_template,
    jwt_decode=_planning_jwt_decode,
)
_run_planning_wa_reminders = _planning_helpers["run_planning_wa_reminders"]

# Iter43-fix24az-o (2026-07-21) — Liluvine Reactions (fuzzy commands + ad templates + auto-contact)
from routes.liluvine_reactions import attach_liluvine_reactions_routes as _attach_liluvine_reactions  # noqa: E402
_liluvine_reactions_helpers = _attach_liluvine_reactions(
    api=api, db=db,
    get_current_user=get_current_user,
    get_current_admin=get_current_admin,
    _is_super_admin=_is_super_admin,
    _resolve_visible_client_ids=_resolve_visible_client_ids,
    wa_send_media=_wa_send_media,  # Iter43-fix24az-p — native media responses
)
# Expose globalement pour que autoreply_to_inbound puisse les appeler
LILUVINE_REACTIONS_HELPERS = _liluvine_reactions_helpers

# Iter38r-fix9c — Liluvine PRO Knowledge Base
from routes.liluvine_kb import setup_liluvine_kb_routes as _setup_liluvine_kb_routes  # noqa: E402
_setup_liluvine_kb_routes(app=api, db=db, get_current_user=get_current_user)

# Iter38r-fix9j — PawaPay Payouts (v2) for BFA
from routes.pawapay_payouts import setup_pawapay_payout_routes as _setup_pawapay_payout_routes  # noqa: E402
_setup_pawapay_payout_routes(app=api, db=db, get_current_user=get_current_user)

# Iter38r-fix9l — Bonus pack: WA tasks bidirectional sync, Liluvine weekly digest,
# GDPR automated anonymization, "Export my data" endpoint.
from routes.bonus_pack_9l import (  # noqa: E402
    setup_bonus_pack_routes as _setup_bonus_pack_routes,
    parse_task_ack as _parse_task_ack,
    apply_task_ack_for_user as _apply_task_ack_for_user,
    run_wa_tasks_digest as _run_wa_tasks_digest,
    run_liluvine_weekly_digest as _run_liluvine_weekly_digest,
    run_gdpr_anonymization as _run_gdpr_anonymization,
)


async def _send_wa_text_for_digest(to: str, text: str, scope_user: Optional[dict] = None) -> bool:
    """Lightweight wrapper used by the WA tasks digest cron. Returns True if the
    Cloud API accepted the message.

    2026-02 fork (P0.5) — Uses per-tenant Smart Comm credentials when
    `scope_user` carries a `parent_client_id` / `client_id` / `id`.
    """
    try:
        tid: Optional[str] = None
        if scope_user:
            tid = (
                scope_user.get("parent_client_id")
                or scope_user.get("client_id")
                or scope_user.get("id")
                or None
            )
        r = await _wa_send_text(to, text, tenant_id=tid)
        return bool(r.get("ok"))
    except Exception:
        logger.exception("[wa_digest] _wa_send_text failed")
        return False


async def _get_settings_async() -> Dict[str, Any]:
    return await db.settings.find_one({"_id": "global"}) or {}


# 2026-02 fork (P0.5) — Diagnostic endpoint to verify the tenant Smart Comm
# WA credentials resolver. Read-only; secrets never returned verbatim.
@api.get("/admin/wa-credentials-resolver-diag", tags=["Admin"])
async def admin_wa_credentials_resolver_diag(
    tenant_id: Optional[str] = None,
    _: dict = Depends(get_current_admin),
):
    creds = await _resolve_wa_credentials(tenant_id)
    tok = creds.get("access_token") or ""
    return {
        "source": creds["source"],
        "tenant_id": creds.get("tenant_id"),
        "phone_number_id": creds.get("phone_number_id") or "",
        "access_token_len": len(tok),
        "access_token_present": bool(tok),
    }


# 2026-02 fork (P0.5 extended) — Multi-channel resolver diagnostic.
# Same guarantees as the WA-only variant: read-only, secrets masked.
_SECRET_FIELD_NAMES = {
    "wa_access_token", "wa_verify_token",
    "meta_app_secret", "meta_page_access_token",
    "instagram_access_token",
    "linkedin_client_secret", "linkedin_access_token",
    "x_api_secret", "x_access_secret", "x_access_token",
    "tiktok_client_secret", "tiktok_access_token",
}


@api.get("/admin/smart-comm/resolver-diag", tags=["Admin"])
async def admin_smart_comm_resolver_diag(
    channel: str,
    tenant_id: Optional[str] = None,
    _: dict = Depends(get_current_admin),
):
    if channel not in _smart_comm_resolver.channels():
        raise HTTPException(status_code=400, detail=f"Canal invalide. Valeurs : {', '.join(_smart_comm_resolver.channels())}")
    creds = await _smart_comm_resolver.resolve(channel, tenant_id)
    masked: Dict[str, Any] = {"source": creds["source"], "tenant_id": creds.get("tenant_id"), "channel": channel}
    for k, v in creds.items():
        if k in ("source", "tenant_id"):
            continue
        if k in _SECRET_FIELD_NAMES:
            s = v if isinstance(v, str) else ""
            masked[f"{k}_len"] = len(s)
            masked[f"{k}_present"] = bool(s)
        else:
            masked[k] = v
    return masked


_setup_bonus_pack_routes(app=api, db=db, get_current_user=get_current_user)

# 2026-02 fork (P3) — Envoi quotidien du planning RDV du médecin par WhatsApp
from routes.medecin_planning_digest import (  # noqa: E402
    run_medecin_planning_digest as _run_medecin_planning_digest,
    setup_medecin_planning_digest_routes as _setup_medecin_planning_digest_routes,
)
_setup_medecin_planning_digest_routes(app=api, db=db, get_current_user=get_current_user)

# 2026-02 fork (P0.5 extended) — Tenant-scoped social senders (LinkedIn/Meta/X)
from routes.smart_comm_senders import setup_smart_comm_senders  # noqa: E402
setup_smart_comm_senders(
    app=api, db=db,
    resolver=_smart_comm_resolver,
    get_current_user=get_current_user,
)

# Iter38r-fix9m — AI Media additional models (Veo 3, Imagen 4, ElevenLabs v3)
from routes.ai_media_9m import setup_ai_media_routes as _setup_ai_media_routes  # noqa: E402
_setup_ai_media_routes(app=api, db=db, get_current_user=get_current_user)

# Iter38r-fix9n — Public product checkout (Stripe) + coupons
from routes.product_checkout_9n import setup_product_checkout_routes as _setup_product_checkout_routes  # noqa: E402
_setup_product_checkout_routes(app=api, db=db, get_current_user=get_current_user, send_email_fn=send_email)

# Iter38r-fix9o (Items 6 + 8) — WhatsApp OTP login + DEMO SAWALI tenant
from routes.wa_otp_login_9o import setup_wa_otp_routes as _setup_wa_otp_routes  # noqa: E402
async def _create_jwt_token_wrapper(u: Dict[str, Any], request: Optional[Request] = None) -> str:
    # Lot 50 — connexion WhatsApp : session du compte ouverte (limite d'appareils)
    from auth import create_session_token as _create_session_token
    return await _create_session_token(u, request, methode="code_whatsapp")   # lot 55 : journal des connexions

_setup_wa_otp_routes(
    app=api, db=db, get_current_user=get_current_user,
    create_jwt_token=_create_jwt_token_wrapper,
    hash_password=hash_password,
)

# Iter38r-fix8 — Emergent Object Storage proxy.
# Files persisted via object_storage.save_and_log() are served via this proxy
# so the frontend can use a simple URL (DB stays the source of truth).
import object_storage as _obj_storage  # noqa: E402

@app.on_event("startup")
async def _init_object_storage_on_startup():
    try:
        await _obj_storage.init_storage()
    except Exception:
        logger.exception("[object_storage] startup init failed")


@app.on_event("startup")
async def _migrate_ad_banner_absolute_urls():
    """Iter38r-fix9z — One-shot cleanup of legacy absolute URLs saved in the
    `ad_banners` collection. Converts any "https?://host/api/files/X" to the
    relative "/api/files/X" so the same row works in preview AND production.
    Safe to run on every boot — no-op once cleaned."""
    try:
        import re as _re
        fixed = 0
        cursor = db.ad_banners.find({}, {"_id": 0, "id": 1, "image_url": 1, "target_url": 1})
        rows = await cursor.to_list(5000)
        for r in rows:
            patch = {}
            for field in ("image_url", "target_url"):
                v = r.get(field) or ""
                m = _re.match(r"^https?://[^/]+(/api/files/.+)$", v)
                if m:
                    patch[field] = m.group(1)
            if patch:
                await db.ad_banners.update_one({"id": r["id"]}, {"$set": patch})
                fixed += 1
        if fixed:
            logger.info("[ad_banners] migrated %s rows with absolute origins → relative", fixed)
    except Exception:
        logger.exception("[ad_banners] startup migration failed")


@api.get("/files/{file_path:path}", tags=["Files"])
async def proxy_file_download(file_path: str, request: Request):
    """Iter38r-fix8 — Endpoint proxy servant les fichiers depuis Emergent Object Storage.
    Path matches the value `save_and_log()` returned. Public by default for
    most assets (catalog images, avatars, AI media that are already accessible
    by URL); private files would add an auth check here in the future."""
    if not file_path or ".." in file_path:
        raise HTTPException(status_code=400, detail="Chemin invalide")
    # Look up the registered object to fetch its DB-recorded content_type
    rec = await db.stored_objects.find_one(
        {"storage_path": file_path, "is_deleted": False},
        {"_id": 0, "content_type": 1, "kind": 1},
    )
    try:
        data, ct = await _obj_storage.get_object(file_path)
    except Exception as exc:
        logger.warning("[object_storage] download failed for %s: %s", file_path, exc)
        raise HTTPException(status_code=404, detail="Fichier introuvable") from exc
    content_type = (rec or {}).get("content_type") or ct or "application/octet-stream"
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "public, max-age=3600"})


# Iter38r-fix9p — Public docs (3 PDFs) registered BEFORE include_router
from routes.public_docs import setup_docs_routes as _setup_docs_routes  # noqa: E402
_setup_docs_routes(api=api, get_current_user=get_current_user)

# Iter38r-fix9r — Home Assistant voice notifications
from routes.voice_notifications import setup_voice_notifications_routes as _setup_voice_notif_routes  # noqa: E402
_setup_voice_notif_routes(app=api, db=db, get_current_user=get_current_user)

# Iter38r-fix9u — AI subscription renewal reminders (WhatsApp + Email)
from routes.ai_subscriptions import setup_ai_subscriptions_routes as _setup_ai_subs_routes  # noqa: E402
async def _email_adapter(*, to: str, subject: str, body_text: str):
    return await send_email(to, subject, body_text, body_text)
async def _wa_adapter(*, to: str, body: str):
    return await _wa_send_text(to, body)
_setup_ai_subs_routes(
    app=api, db=db, get_current_user=get_current_user,
    send_email_fn=_email_adapter, send_whatsapp_fn=_wa_adapter,
)

# Iter38r-fix9w — Ad Banners monetization
from routes.ad_banners import setup_ad_banners_routes as _setup_ad_banners_routes  # noqa: E402
_setup_ad_banners_routes(app=api, db=db, get_current_user=get_current_user, wa_send_text=_wa_send_text)

# S-iter39b — PV de réunions internes (Meeting Minutes)
from routes.meetings import make_router as _make_meetings_router  # noqa: E402

# S026 — Signers notifier: emails + WhatsApp to declared signataires
async def _meeting_signers_notifier(pv_doc: dict) -> None:
    """Notify each declared signataire about a new PV awaiting their signature.

    Channel selection comes from settings.meeting_signers_notify_channel:
      "none" → no-op
      "email" → email only
      "wa"   → WhatsApp text only
      "both" → both channels
    """
    settings = await db.settings.find_one(
        {"_id": "global"},
        {"_id": 0, "meeting_signers_notify_channel": 1, "public_base_url": 1},
    ) or {}
    channel = (settings.get("meeting_signers_notify_channel") or "none").lower()
    if channel == "none":
        return
    signer_ids = pv_doc.get("signers") or []
    if not signer_ids:
        return
    # 2026-02 — signers may mix user_ids (uuid) and free-form emails ('@').
    internal_ids = [x for x in signer_ids if "@" not in x]
    external_emails = [x.lower() for x in signer_ids if "@" in x]
    # Resolve each id → {email, phone, name}
    contacts: List[Dict[str, Any]] = []
    seen = set()
    if internal_ids:
        async for u in db.users.find(
            {"id": {"$in": internal_ids}},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "phone": 1, "whatsapp_number": 1},
        ):
            contacts.append({
                "id": u["id"],
                "name": u.get("full_name") or u.get("email") or "—",
                "email": u.get("email"),
                "phone": (u.get("whatsapp_number") or u.get("phone") or "").strip() or None,
            })
            seen.add(u["id"])
        # Also resolve tracked users whose user_id is in signers
        async for t in db.tracked_users.find(
            {"$or": [{"id": {"$in": internal_ids}}, {"user_id": {"$in": internal_ids}}]},
            {"_id": 0, "id": 1, "user_id": 1, "name": 1, "full_name": 1, "email": 1, "phone": 1, "whatsapp_number": 1},
        ):
            key = t.get("user_id") or t["id"]
            if key in seen:
                continue
            contacts.append({
                "id": key,
                "name": t.get("full_name") or t.get("name") or t.get("email") or "—",
                "email": t.get("email"),
                "phone": (t.get("whatsapp_number") or t.get("phone") or "").strip() or None,
            })
            seen.add(key)
    # External email-only signers (no portal account)
    seen_emails = {(c.get("email") or "").lower() for c in contacts if c.get("email")}
    if external_emails:
        # Try to enrich with a user account if one matches the email
        enriched = {}
        async for u in db.users.find(
            {"email": {"$in": external_emails}},
            {"_id": 0, "email": 1, "full_name": 1, "phone": 1, "whatsapp_number": 1},
        ):
            enriched[(u.get("email") or "").lower()] = u
        for em in external_emails:
            if em in seen_emails:
                continue
            extra = enriched.get(em) or {}
            contacts.append({
                "id": em,
                "name": extra.get("full_name") or em,
                "email": em,
                "phone": (extra.get("whatsapp_number") or extra.get("phone") or "").strip() or None,
            })
            seen_emails.add(em)
    base_url = (settings.get("public_base_url") or os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    pv_link = f"{base_url}/portal/meetings/{pv_doc['id']}" if base_url else "le portail Loois"
    subject = f"[Loois] Vous êtes signataire du PV {pv_doc.get('numero', '')} — {pv_doc.get('title', '')}"
    body_text = (
        f"Bonjour,\n\n"
        f"Vous avez été désigné(e) signataire obligatoire d'un nouveau procès-verbal :\n\n"
        f"• Numéro : {pv_doc.get('numero', '—')}\n"
        f"• Titre : {pv_doc.get('title', '—')}\n"
        f"• Date de réunion : {pv_doc.get('meeting_date', '—')}\n"
        f"• Auteur du PV : {pv_doc.get('author_name', '—')}\n\n"
        f"Merci de consulter le PV et de signer électroniquement :\n{pv_link}\n\n"
        f"— SAWALI Smart Systems"
    )
    wa_text = (
        f"📋 Nouveau PV — Signature requise\n\n"
        f"N° {pv_doc.get('numero', '—')}\n"
        f"« {pv_doc.get('title', '—')} »\n\n"
        f"Vous êtes désigné(e) signataire obligatoire.\n"
        f"Consulter et signer : {pv_link}"
    )
    for c in contacts:
        if channel in ("email", "both") and c.get("email"):
            try:
                await send_email(
                    to_email=c["email"],
                    subject=subject,
                    html_body=body_text.replace("\n", "<br>"),
                    text_body=body_text,
                )
            except Exception:  # noqa: BLE001
                pass
        if channel in ("wa", "both") and c.get("phone"):
            try:
                await _wa_send_text(c["phone"], wa_text)
            except Exception:  # noqa: BLE001
                pass


api.include_router(_make_meetings_router(db=db, get_current_user=get_current_user, signers_notifier=_meeting_signers_notifier))


# S025 — Download approval workflow (WhatsApp template + magic links fallback)
async def _wa_send_template_for_approval(*, to_e164: str, template_name: str, language: str = "fr",
                                          body_params: list = None, button_params: list = None) -> dict:
    """Build a Meta `components` array from positional body/button params then
    delegate to the existing _wa_send_template helper. Used by the download
    approval router and exposed only via that integration."""
    components = []
    if body_params:
        components.append({"type": "body", "parameters": [
            {"type": "text", "text": str(p)} for p in body_params
        ]})
    if button_params:
        components.extend([{"type": "button", **bp} for bp in button_params])
    return await _wa_send_template(to_e164, template_name, language, components or None)


from routes.download_approvals import (  # noqa: E402
    make_router as _make_dl_router,
    make_public_router as _make_dl_public_router,
    handle_button_payload as _dl_handle_button_payload,
)
api.include_router(_make_dl_router(
    db=db,
    get_current_user=get_current_user,
    wa_send_text=_wa_send_text,
    wa_send_template=_wa_send_template_for_approval,
))
api.include_router(_make_dl_public_router(db=db))

# Lot Liluvine (2026-09, point 5) — clic sur le bouton "Souscrire
# temporairement" envoyé quand un contrat est invalide (voir
# routes/liluvine_wa_autoreply.py).
from routes.liluvine_wa_autoreply import (  # noqa: E402
    handle_temp_subscribe_button_payload as _liluvine_handle_temp_subscribe_button_payload,
)

# Lot Liluvine (2026-09, point 6) — webhook entrant HMAC permettant à
# Liluvine d'envoyer un message WhatsApp via SAWALI (numéro cible + secret
# paramétrables dans AdminSettings).
from routes.liluvine_send_webhook import attach_liluvine_send_webhook_routes as _attach_liluvine_send_webhook  # noqa: E402
_attach_liluvine_send_webhook(api=api, db=db, wa_send_text=_wa_send_text, wa_send_template=_wa_send_template,
                              wa_send_media=_wa_send_media)
# Lot 57.5 — lien public (jeton, 7 jours) des fichiers transmis par les plateformes
from routes.liluvine_relais import attach_liluvine_fichiers_route as _attach_liluvine_fichiers  # noqa: E402
_attach_liluvine_fichiers(api=api, db=db)

# Lot 57.4 — Transmission WA Universelle Liluvine : plateformes émettrices
# (une clé HMAC par plateforme) et journal des transmissions (administrateur).
from routes.liluvine_emetteurs import make_liluvine_emetteurs_router as _make_liluvine_emetteurs_router  # noqa: E402
api.include_router(_make_liluvine_emetteurs_router(db=db, get_current_admin=get_current_admin))

# Lot Gestion Stocks (2026-09) — espace documentaire R2 des Pharmaciens
# suivis (sidebar "Gestion de Stocks"). Bloc "Explorateur BD MongoDB Atlas"
# du schéma fourni volontairement pas encore implémenté (voir docstring du
# module) — la partie technique de l'import externe reste à discuter.
from routes.gestion_stocks import attach_gestion_stocks_routes as _attach_gestion_stocks  # noqa: E402
_attach_gestion_stocks(api=api, db=db, get_current_user=get_current_user, get_current_admin=get_current_admin)

# Lot OCR sur Pièces (2026-09) — analyse IA des pièces (factures, bons de
# livraison, reçus…). Logique commune dans backend/ocr_core/ (copie du module
# ocr-core, source unique : dépôt ShuyahBF/Claude) ; adaptateur Sawali
# (accès admin + pharmacies, cloisonnement par tenant) dans routes/ocr_pieces.py.
from routes.ocr_pieces import attach_ocr_pieces_routes as _attach_ocr_pieces  # noqa: E402
# Lot 34 — accès des clients selon la fonction « OCR sur Pièces » (SMART Communications).
# Lot 38 — fin de traitement d'une liste de pointage envoyée par email ([CODE] dans l'objet).
_attach_ocr_pieces(api=api, db=db, get_current_user=get_current_user, fonction_active=_fonction_active,
                   send_email=send_email)

# S031 — Universal Key health monitoring & budget-exceeded banner
from routes.llm_health import make_router as _make_llm_health_router  # noqa: E402
api.include_router(_make_llm_health_router(db=db, get_current_user=get_current_user, send_email=send_email))

# S038 — Qdrant RAG router (admin-only)
from routes.qdrant_rag import make_router as _make_qdrant_router  # noqa: E402
api.include_router(_make_qdrant_router(db=db, get_current_user=get_current_user))

# S-iter39p — Media Library (PDF + video + image library shared in Brochures)
from routes.media_library import setup_media_library_routes  # noqa: E402
setup_media_library_routes(db=db, api=api, get_current_user=get_current_user, save_and_log=_obj_storage.save_and_log)

# ============================================================
# Lot 40 — Carrousel WhatsApp (2 à 10 cartes : produits de la caisse ou cartes
# libres) : portail client vers ses contacts consentants (fonction activable
# `whatsapp_carrousel`) et administration SAWALI vers ses clients.
# Voir routes/carrousel_whatsapp.py.
# ============================================================
from routes.carrousel_whatsapp import attach_carrousel_whatsapp_routes as _attach_carrousel_wa  # noqa: E402
_attach_carrousel_wa(
    api=api, db=db, get_current_user=get_current_user, get_current_admin=get_current_admin,
    fonction_active=_fonction_active, visible_client_ids=_resolve_visible_client_ids,
    wa_send_template=_wa_send_template, resolve_wa_credentials=_resolve_wa_credentials,
    base_publique=lambda: _public_base_url() or _PUBLIC_BASE_URL,   # adresse publique (réglage Admin, sinon PUBLIC_BASE_URL)
    save_and_log=_obj_storage.save_and_log,
)


# S-iter39d (fix #4) — Lecture du registre des suggestions (admin uniquement).
# Permet à l'admin de consulter SUGGESTIONS.md directement depuis l'UI sans
# accéder au serveur de fichiers. Lecture seule, taille bornée à 256 KB.
@api.get("/admin/suggestions-registry", tags=["Admin"])
async def get_suggestions_registry(_: dict = Depends(get_admin_or_supervisor)):
    from chemins import MEMORY_DIR  # lot 49 : /app/memory sur Emergent
    p = MEMORY_DIR / "SUGGESTIONS.md"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Registre des suggestions introuvable")
    try:
        size = p.stat().st_size
        if size > 256 * 1024:
            raise HTTPException(status_code=413, detail="Fichier trop volumineux (256KB max)")
        return {
            "markdown": p.read_text(encoding="utf-8", errors="replace"),
            "size_bytes": size,
            "updated_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erreur lecture: {exc!s}") from exc


# 2026-02 fork iter102 — Parsed suggestions history for the admin Suggestions
# History screen. Extracts each entry (## S### — title) with its status marker
# (🟢 IMPLÉMENTÉE / 🟡 ACCEPTÉE / 🔵 PROPOSÉE / ⚪ DIFFÉRÉE / 🔴 REFUSÉE) and
# best-effort date. Returns a compact list sorted by ID desc.
#
# 2026-02 fork iter103 — Suggestion Vote (S148 follow-up). Adds a MongoDB
# override layer `db.suggestion_overrides` that lets admins/superviseurs change
# a suggestion status from the UI without editing the markdown file directly.
# The override wins over the marker parsed from SUGGESTIONS.md.
SUGGESTION_STATUSES = ("implemented", "accepted", "proposed", "deferred", "refused")
SUGGESTION_STATUS_LABELS = {
    "implemented": "IMPLÉMENTÉE",
    "accepted": "ACCEPTÉE",
    "proposed": "PROPOSÉE",
    "deferred": "DIFFÉRÉE",
    "refused": "REFUSÉE",
}


@api.get("/admin/suggestions-history", tags=["Admin"])
async def get_suggestions_history(
    status: Optional[str] = None,
    _: dict = Depends(get_admin_or_supervisor),
):
    """List parsed suggestions from SUGGESTIONS.md.

    Query params:
      - status : filter by canonical status key (implemented | accepted | proposed | deferred | refused)
    """
    from chemins import MEMORY_DIR  # lot 49 : /app/memory sur Emergent
    p = MEMORY_DIR / "SUGGESTIONS.md"
    if not p.exists():
        return {"items": [], "total": 0, "counts": {}}
    text = p.read_text(encoding="utf-8", errors="replace")

    # Status marker → canonical key.
    STATUS_MARKERS = [
        ("🟢", "implemented", "IMPLÉMENTÉE"),
        ("🟡", "accepted", "ACCEPTÉE"),
        ("🔵", "proposed", "PROPOSÉE"),
        ("⚪", "deferred", "DIFFÉRÉE"),
        ("🔴", "refused", "REFUSÉE"),
    ]

    # 2026-02 fork iter103 — Load overrides in one shot.
    try:
        overrides_docs = await db.suggestion_overrides.find({}, {"_id": 0}).to_list(2000)
    except Exception:  # noqa: BLE001
        overrides_docs = []
    overrides = {o["suggestion_id"]: o for o in overrides_docs if o.get("suggestion_id")}

    import re
    # Split on section headers `## S### — Title` (keeps subsections attached).
    parts = re.split(r"^(##\s+S\d{3}\s+.*)$", text, flags=re.MULTILINE)
    # Result of re.split with capture: [prefix, header, body, header, body, ...]
    items: List[Dict[str, Any]] = []
    for i in range(1, len(parts), 2):
        header = (parts[i] or "").strip()
        body = (parts[i + 1] if i + 1 < len(parts) else "") or ""
        # Extract S### id + title.
        m = re.match(r"##\s+(S\d{3})\s+—\s+(.+)$", header)
        if not m:
            m = re.match(r"##\s+(S\d{3})\s+(.+)$", header)
        if not m:
            continue
        sid, title = m.group(1), (m.group(2) or "").strip()
        # Status detection : first marker found in the body.
        canon = "unknown"
        label = ""
        for marker, key, lab in STATUS_MARKERS:
            if marker in body:
                canon = key
                label = lab
                break
        # Best-effort date : `Fix associé : xxx (YYYY-MM-DD)` OR `2026-XX-XX` on
        # the first 6 lines of the body.
        date_iso = ""
        dm = re.search(r"(20\d{2}-\d{2}-\d{2})", body[:800])
        if dm:
            date_iso = dm.group(1)
        # First non-empty paragraph as summary.
        summary_lines = [line for line in body.splitlines() if line.strip()][:2]
        summary = " ".join(summary_lines)[:240]
        # Apply DB override (if any).
        override = overrides.get(sid) or {}
        overridden_status = (override.get("status") or "").strip().lower() if override else ""
        applied = canon
        applied_label = label
        overridden = False
        if overridden_status in SUGGESTION_STATUSES:
            applied = overridden_status
            applied_label = SUGGESTION_STATUS_LABELS.get(overridden_status, "")
            overridden = True
        items.append({
            "id": sid,
            "title": title,
            "status": applied,
            "status_label": applied_label,
            "original_status": canon,
            "overridden": overridden,
            "override_reason": (override.get("reason") if overridden else None),
            "override_by": (override.get("updated_by_email") if overridden else None),
            "override_at": (override.get("updated_at") if overridden else None),
            "date_iso": date_iso,
            "summary": summary,
        })
    # Sort by numeric id desc.
    items.sort(key=lambda it: int(it["id"][1:] or "0"), reverse=True)
    counts: Dict[str, int] = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    if status:
        want = status.strip().lower()
        items = [it for it in items if it["status"] == want]
    return {"items": items, "total": len(items), "counts": counts}


class SuggestionVotePayload(BaseModel):
    status: str  # implemented | accepted | proposed | deferred | refused
    reason: Optional[str] = None


@api.patch("/admin/suggestions-history/{sid}/status", tags=["Admin"])
async def admin_vote_suggestion_status(
    sid: str,
    payload: SuggestionVotePayload,
    user: dict = Depends(get_admin_or_supervisor),
):
    """2026-02 fork iter103 — Change a suggestion status via UI (override).

    Persists in `db.suggestion_overrides` so the markdown file is left intact.
    The GET endpoint merges the override on top of the parsed status.
    """
    import re as _re
    if not _re.match(r"^S\d{3}$", sid or ""):
        raise HTTPException(status_code=400, detail="Format d'ID invalide, attendu SXXX (ex: S144)")
    canon = (payload.status or "").strip().lower()
    if canon not in SUGGESTION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Statut invalide, attendu l'un de {list(SUGGESTION_STATUSES)}")
    doc = {
        "suggestion_id": sid,
        "status": canon,
        "reason": (payload.reason or "")[:500].strip() or None,
        "updated_by_id": user.get("id"),
        "updated_by_email": user.get("email"),
        "updated_at": _now(),
    }
    await db.suggestion_overrides.update_one(
        {"suggestion_id": sid},
        {"$set": doc, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )
    # Audit trail
    try:
        await db.suggestion_override_audit.insert_one({
            "id": _uuid(),
            **doc,
            "audit_at": _now(),
        })
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **doc}


@api.delete("/admin/suggestions-history/{sid}/status", tags=["Admin"])
async def admin_clear_suggestion_override(
    sid: str,
    user: dict = Depends(get_admin_or_supervisor),
):
    """Clear the DB override → back to the markdown-declared status."""
    import re as _re
    if not _re.match(r"^S\d{3}$", sid or ""):
        raise HTTPException(status_code=400, detail="Format d'ID invalide")
    res = await db.suggestion_overrides.delete_one({"suggestion_id": sid})
    try:
        await db.suggestion_override_audit.insert_one({
            "id": _uuid(),
            "suggestion_id": sid,
            "status": "__cleared__",
            "reason": None,
            "updated_by_id": user.get("id"),
            "updated_by_email": user.get("email"),
            "updated_at": _now(),
            "audit_at": _now(),
        })
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "deleted": res.deleted_count or 0}
