# server_parts/p02_portail_client_paiements.py — Portail client, agent agenda n8n, PawaPay, tableau de bord paiements, liens de paiement, accès barre latérale, facturation des interventions.
# Morceau de l'ancien server.py (lignes 1839 à 3963), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# CLIENT PORTAL
# ====================================================================
# Iter38r-fix9z10 — Suggestion S009 — Auto-logout config readable by any
# authenticated user. Returns idle minutes (0 = disabled). Frontend uses this
# to schedule the idle timer + warning modal.
@api.get("/me/idle-config", tags=["Portail Client"])
async def me_idle_config(user: dict = Depends(get_current_user)):
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "auto_logout_minutes": 1}) or {}
    return {
        "auto_logout_minutes": int(settings.get("auto_logout_minutes") or 0),
        "warning_seconds": 30,
    }



@api.get("/me/account", tags=["Portail Client"])
async def me_account(user: dict = Depends(get_current_user)):
    appts = await db.appointments.find({"client_id": user["id"]}, {"_id": 0}).to_list(500)
    interventions = await db.interventions.find({"client_id": user["id"]}, {"_id": 0}).to_list(500)
    docs = await db.documents.find(
        {"$or": [{"client_id": user["id"]}, {"is_public": True}]}, {"_id": 0}
    ).to_list(500)
    return {
        "user": _to_user_public(user),
        "stats": {
            "appointments": len(appts),
            "appointments_pending": sum(1 for a in appts if a["status"] == "pending"),
            "interventions": len(interventions),
            "documents": len(docs),
        },
        "recent_appointments": sorted(appts, key=lambda x: x["scheduled_at"], reverse=True)[:5],
        "recent_interventions": sorted(
            interventions, key=lambda x: x.get("intervention_date", ""), reverse=True
        )[:5],
    }


@api.get("/me/account-detail", tags=["Portail Client"])
async def me_account_detail(user: dict = Depends(get_current_user)):
    """Iter34k — Read-only account profile shown in the user-menu "Mon
    compte" page. Returns identity + company hierarchy + phone numbers +
    last-login (excluding the current session) + counters for Rapports,
    Suivis, Contacts (shared by the same company/client).
    """
    parent_id = user.get("parent_client_id") or user.get("client_id") or user.get("id")
    # Parent client information (employer/company owner)
    parent = await db.users.find_one(
        {"id": parent_id}, {"_id": 0, "full_name": 1, "company": 1, "email": 1}
    ) if parent_id and parent_id != user.get("id") else None
    # Previous login: ignore the very last access_log row (current session)
    prev_logins_cursor = db.access_logs.find(
        {"user_email": (user.get("email") or "").lower()},
        {"_id": 0, "created_at": 1},
    ).sort("created_at", -1).limit(2)
    prev_logins = [r async for r in prev_logins_cursor]
    last_seen = prev_logins[1]["created_at"] if len(prev_logins) >= 2 else None

    # Counters scoped to the user's effective client_id span
    client_ids = await _resolve_visible_client_ids(user)
    reports_count = await db.user_reports.count_documents({"user_id": user["id"]})
    suivis_count = await db.user_suivis.count_documents({"user_id": user["id"]})
    contacts_count = await db.directory_contacts.count_documents(
        {"client_id": {"$in": client_ids}}
    )

    return {
        "identity": {
            "full_name": user.get("full_name"),
            "email": user.get("email"),
            "role": user.get("role"),
            "phone": user.get("phone"),
            "whatsapp": user.get("whatsapp") or user.get("phone"),
            "avatar_url": user.get("avatar_url"),
            "company": user.get("company"),
            "birth_date": user.get("birth_date"),
        },
        "parent_client": {
            "id": parent_id if parent else None,
            "full_name": parent.get("full_name") if parent else None,
            "company": parent.get("company") if parent else None,
            "email": parent.get("email") if parent else None,
        } if parent else None,
        "last_seen_at": last_seen,
        "counters": {
            "reports": reports_count,
            "suivis": suivis_count,
            "contacts": contacts_count,
        },
    }


@api.post("/me/profile-update-request", tags=["Portail Client"])
async def me_request_profile_update(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    """Iter34k — Soumet une demande libre à l'admin pour corriger l'identité,
    surname spelling, birth date, phone numbers, etc. Stored in
    `db.profile_update_requests` for admin review; admin sees them in
    `/admin/settings` (separate section in a follow-up iter)."""
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Le message est obligatoire")
    if len(message) > 1500:
        raise HTTPException(status_code=400, detail="Message trop long (1500 caractères max)")
    fields = payload.get("fields") or []
    if not isinstance(fields, list):
        fields = []
    doc = {
        "id": _uuid(),
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_full_name": user.get("full_name"),
        "company": user.get("company"),
        "parent_client_id": user.get("parent_client_id") or user.get("client_id"),
        "fields": [str(f)[:60] for f in fields[:10]],
        "message": message,
        "status": "pending",
        "created_at": _now(),
        "resolved_at": None,
        "admin_note": "",
    }
    await db.profile_update_requests.insert_one(doc)
    out = dict(doc)
    out.pop("_id", None)
    return out


# ----- Admin side (Iter34l) ---------------------------------------------
@api.get("/admin/profile-requests", tags=["Admin"])
async def admin_profile_requests_list(
    status: str = "all",
    limit: int = 200,
    _: dict = Depends(get_current_admin),
):
    """Iter34l — Liste les demandes de mise à jour de profil soumises par les utilisateurs.
    `status` = pending | processed | all. Newest first."""
    q: Dict[str, Any] = {}
    if status in ("pending", "processed"):
        q["status"] = status
    items = await db.profile_update_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(max(1, min(int(limit or 200), 1000)))
    pending_count = await db.profile_update_requests.count_documents({"status": "pending"})
    return {"items": items, "pending_count": pending_count}


@api.patch("/admin/profile-requests/{req_id}", tags=["Admin"])
async def admin_profile_requests_update(
    req_id: str,
    payload: Dict[str, Any] = Body(...),
    admin: dict = Depends(get_current_admin),
):
    """Iter34l — Marque une demande de mise à jour de profil comme traitée (ou en attente)
    and optionally attach an admin note."""
    existing = await db.profile_update_requests.find_one({"id": req_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    update: Dict[str, Any] = {}
    if "status" in payload:
        new_status = (payload.get("status") or "").strip().lower()
        if new_status not in ("pending", "processed"):
            raise HTTPException(status_code=400, detail="Statut invalide (pending | processed)")
        update["status"] = new_status
        update["resolved_at"] = _now() if new_status == "processed" else None
        update["resolved_by_email"] = admin.get("email") if new_status == "processed" else None
    if "admin_note" in payload:
        note = (payload.get("admin_note") or "").strip()
        if len(note) > 2000:
            raise HTTPException(status_code=400, detail="Note trop longue (2000 caractères max)")
        update["admin_note"] = note
    if not update:
        raise HTTPException(status_code=400, detail="Rien à mettre à jour")
    await db.profile_update_requests.update_one({"id": req_id}, {"$set": update})
    out = await db.profile_update_requests.find_one({"id": req_id}, {"_id": 0})
    return out


@api.get("/me/appointments", tags=["Portail Client"])
async def me_appointments(user: dict = Depends(get_current_user)):
    """All users belonging to the same client see the same set of RDV.
    Only the SAWALI super-admin sees ALL tenants (Iter43-fix24az-l). Regular
    client-admin/superviseur are tenant-scoped. RGPD: anonymizes customer
    fields per parent-client flags for non-privileged roles."""
    if _is_super_admin(user):
        items = await db.appointments.find({}, {"_id": 0}).to_list(2000)
    elif user.get("role") in ("admin", "superviseur"):
        scope = await _resolve_visible_client_ids(user)
        items = await db.appointments.find({"client_id": {"$in": scope}}, {"_id": 0}).to_list(2000)
    else:
        scope = user.get("client_id") or user["id"]
        items = await db.appointments.find({"client_id": scope}, {"_id": 0}).to_list(2000)
    items = await _maybe_anon_list(user, items, _apply_anon_to_appointment)
    return sorted(items, key=lambda x: x["scheduled_at"], reverse=True)


# ============================================================
# n8n Agenda Agent — outbound webhook notifications
# Fired (best-effort, non-blocking) on every manual appointment CRUD so
# the n8n AI workflow can sync external systems / notify the user.
# Inbound endpoint: POST /webhooks/agenda/{secret}
# ============================================================
async def _fire_agenda_n8n(action: str, appointment: Dict[str, Any], user: Optional[Dict[str, Any]] = None) -> None:
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not s.get("agenda_n8n_outbound_enabled"):
        return
    url = (s.get("agenda_n8n_outbound_url") or "").strip()
    if not url:
        return
    headers = {"Content-Type": "application/json"}
    auth = None
    auth_type = (s.get("agenda_n8n_outbound_auth_type") or "none").lower()
    if auth_type == "bearer":
        tok = (s.get("agenda_n8n_outbound_token") or "").strip()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
    elif auth_type == "basic":
        bu = (s.get("agenda_n8n_outbound_basic_user") or "").strip()
        bp = (s.get("agenda_n8n_outbound_basic_pass") or "").strip()
        if bu and bp:
            auth = (bu, bp)
    safe_appt = {k: v for k, v in appointment.items() if k != "_id"}
    payload = {
        "type": "agenda",
        "action": action,  # created | updated | deleted | reactor
        "appointment": safe_appt,
        "user": (
            {
                "id": user.get("id"),
                "email": user.get("email"),
                "full_name": user.get("full_name"),
                "client_id": user.get("client_id") or user.get("id"),
                "role": user.get("role"),
            }
            if user
            else None
        ),
        "fired_at": _now(),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            await http.post(url, headers=headers, auth=auth, json=payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[agenda-n8n outbound] %s — %s", action, exc)


class AgendaWebhookCreate(BaseModel):
    action: str  # "create" | "update" | "delete" | "list"
    client_email: Optional[str] = None  # used to scope when the AI agent acts on behalf of a user
    appointment_id: Optional[str] = None  # required for update/delete
    subject: Optional[str] = None
    message: Optional[str] = None
    scheduled_at: Optional[str] = None  # ISO-8601
    duration_min: Optional[int] = None
    status: Optional[str] = None  # pending|confirmed|cancelled|completed


@api.post("/webhooks/agenda/{secret}", tags=["Webhooks"])
async def webhook_agenda_n8n(secret: str, payload: AgendaWebhookCreate, request: Request):
    """Inbound webhook from n8n AI Agent. Allows CRUD on appointments using a
    secret path token. The n8n workflow must scope by client_email when acting
    on behalf of a specific user — admin can act globally."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not s.get("agenda_n8n_inbound_enabled"):
        raise HTTPException(status_code=503, detail="Webhook entrant Agenda n8n désactivé")
    expected = (s.get("agenda_n8n_inbound_secret") or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Secret invalide")

    action = (payload.action or "").lower().strip()
    if action not in {"create", "update", "delete", "list"}:
        raise HTTPException(status_code=400, detail="Action inconnue")

    # Resolve scope: action targets a single client when client_email given
    scope_user = None
    if payload.client_email:
        scope_user = await db.users.find_one(
            {"email": payload.client_email.lower().strip()},
            {"_id": 0, "id": 1, "email": 1, "full_name": 1, "phone": 1, "company": 1, "client_id": 1, "role": 1},
        )
        if not scope_user:
            raise HTTPException(status_code=404, detail="Client introuvable")

    if action == "list":
        query = {"client_id": (scope_user.get("client_id") or scope_user["id"])} if scope_user else {}
        items = await db.appointments.find(query, {"_id": 0}).sort("scheduled_at", -1).to_list(500)
        return {"ok": True, "items": items}

    if action == "create":
        if not (payload.scheduled_at and payload.subject):
            raise HTTPException(status_code=400, detail="scheduled_at + subject requis")
        if not scope_user:
            raise HTTPException(status_code=400, detail="client_email requis pour create")
        ok, reason = await _check_slot_available(payload.scheduled_at, payload.duration_min or 30)
        if not ok:
            raise HTTPException(status_code=409, detail=reason)
        doc = {
            "id": _uuid(),
            "client_id": scope_user.get("client_id") or scope_user["id"],
            "name": scope_user["full_name"],
            "email": scope_user["email"],
            "phone": scope_user.get("phone"),
            "company": scope_user.get("company"),
            "subject": payload.subject,
            "message": payload.message,
            "scheduled_at": payload.scheduled_at,
            "duration_min": payload.duration_min or 30,
            "status": payload.status or "pending",
            "notes": None,
            "gcal_event_id": None,
            "source": "n8n",
            "created_at": _now(),
        }
        await db.appointments.insert_one(doc.copy())
        doc.pop("_id", None)
        return {"ok": True, "appointment": doc}

    if action == "update":
        if not payload.appointment_id:
            raise HTTPException(status_code=400, detail="appointment_id requis pour update")
        existing = await db.appointments.find_one({"id": payload.appointment_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
        update = {
            k: v
            for k, v in {
                "subject": payload.subject,
                "message": payload.message,
                "scheduled_at": payload.scheduled_at,
                "duration_min": payload.duration_min,
                "status": payload.status,
            }.items()
            if v is not None
        }
        update["updated_at"] = _now()
        await db.appointments.update_one({"id": payload.appointment_id}, {"$set": update})
        refreshed = await db.appointments.find_one({"id": payload.appointment_id}, {"_id": 0})
        return {"ok": True, "appointment": refreshed}

    # delete
    if not payload.appointment_id:
        raise HTTPException(status_code=400, detail="appointment_id requis pour delete")
    existing = await db.appointments.find_one({"id": payload.appointment_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    await db.appointments.delete_one({"id": payload.appointment_id})
    return {"ok": True, "deleted_id": payload.appointment_id}


# ============================================================
# PawaPay — mobile money "deposit" (encaissement) flow.
# Two API tokens stored: sandbox + production. The active token is
# selected via settings.pawapay_environment ("sandbox" | "production").
# Webhook callback : POST /api/webhooks/pawapay/{secret}
# Docs : https://docs.pawapay.io/v2/api-reference/deposits
# ============================================================
PAWAPAY_HOSTS = {
    "sandbox": "https://api.sandbox.pawapay.io",
    "production": "https://api.pawapay.io",
}


def _pawapay_str(field: Any) -> Optional[str]:
    """PawaPay v2 returns failureReason / rejectionReason as objects
    {failureCode, failureMessage} or {rejectionCode, rejectionMessage}.
    v1 sometimes returned strings. Coerce to a printable single string so
    React can render it without crashing."""
    if field is None:
        return None
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        msg = field.get("failureMessage") or field.get("rejectionMessage") or field.get("message")
        code = field.get("failureCode") or field.get("rejectionCode") or field.get("code")
        if msg and code:
            return f"{code} — {msg}"
        return msg or code or json.dumps(field)[:300]
    return str(field)[:300]


def _safe_text(field: Any, max_len: int = 300) -> Optional[str]:
    """Generic coercer for upstream API messages that may arrive as nested
    dicts or lists. Always returns a single short printable string (or None)
    so React JSX never receives a raw object → "Objects are not valid as a
    React child" crash. Use this for any value piped into the frontend that
    was originally produced by a third-party API response."""
    if field is None:
        return None
    if isinstance(field, str):
        return field[:max_len]
    if isinstance(field, dict):
        # Try common message keys first, then fall back to compact JSON
        for k in ("message", "description", "detail", "error", "errorMessage", "text"):
            v = field.get(k)
            if isinstance(v, str) and v:
                return v[:max_len]
        try:
            return json.dumps(field, default=str)[:max_len]
        except Exception:
            return str(field)[:max_len]
    if isinstance(field, list):
        try:
            return ", ".join(_safe_text(x, max_len) or "" for x in field if x is not None)[:max_len]
        except Exception:
            return str(field)[:max_len]
    return str(field)[:max_len]


def _pawapay_active_token(s: Dict[str, Any]) -> Optional[str]:
    env = (s.get("pawapay_environment") or "sandbox").lower()
    if env == "production":
        return s.get("pawapay_api_token_production") or s.get("pawapay_api_token")
    return s.get("pawapay_api_token_sandbox") or s.get("pawapay_api_token")


class PawaPayDepositCreate(BaseModel):
    amount: float
    msisdn: str  # E.164 (without leading +)
    mno: str  # ORANGE | MOOV | TELECEL
    description: Optional[str] = None


def _pawapay_correspondent(mno: str, country: str = "BFA") -> str:
    """Map MNO + country to the PawaPay "correspondent" code expected by the API.
    Fallback chain: MNO_<COUNTRY>_MTN. Burkina-specific mappings here are best-
    effort and can be overriden later via a settings field if PawaPay renames."""
    m = (mno or "").upper().strip()
    c = (country or "BFA").upper().strip()
    table = {
        "BFA": {"ORANGE": "ORANGE_BFA", "MOOV": "MOOV_BFA", "TELECEL": "TELECEL_BFA"},
    }
    return table.get(c, {}).get(m) or f"{m}_{c}"


# ISO-3 country code → ISO-4217 currency for PawaPay deposits.
# Used to build the v2 `amountDetails.currency` field. UEMOA zone shares XOF.
_PAWAPAY_CURRENCY_BY_COUNTRY = {
    "BFA": "XOF", "BEN": "XOF", "CIV": "XOF", "GNB": "XOF",
    "MLI": "XOF", "NER": "XOF", "SEN": "XOF", "TGO": "XOF",
    "CMR": "XAF", "CAF": "XAF", "TCD": "XAF", "COG": "XAF", "GAB": "XAF", "GNQ": "XAF",
    "KEN": "KES", "UGA": "UGX", "TZA": "TZS", "RWA": "RWF", "ZMB": "ZMW",
    "GHA": "GHS", "NGA": "NGN", "MWI": "MWK", "ZWE": "ZWL", "MOZ": "MZN",
    "MDG": "MGA", "SLE": "SLE", "COD": "CDF",
}


def _pawapay_currency_for_country(country: str) -> str:
    return _PAWAPAY_CURRENCY_BY_COUNTRY.get((country or "BFA").upper(), "XOF")


def _pawapay_split_provider(provider: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse a PawaPay v2 provider code ('ORANGE_BFA', 'MTN_MOMO_ZMB',
    'TELECEL_BFA'…) into ('MNO_short', 'COUNTRY_ISO3').
    'MTN_MOMO_ZMB' → ('MTN', 'ZMB') so it matches our short labels.
    """
    if not provider:
        return None, None
    parts = [p for p in (provider or "").strip().upper().split("_") if p]
    if not parts:
        return None, None
    if len(parts) >= 2:
        country = parts[-1]
        mno_full = "_".join(parts[:-1])
        # Strip common suffix used by PawaPay for MTN/Airtel etc.
        mno = mno_full.replace("_MOMO", "").replace("_MONEY", "")
        return mno or mno_full, country
    return parts[0], None




# Iter38r — The legacy direct /deposits endpoint is intentionally removed.
# All callers now go through the hosted PaymentPage flow defined below
# (which handles MSISDN + PIN/OTP collection natively).


@api.post("/me/payments/pawapay/deposit", tags=["Portail Client"])
async def me_pawapay_deposit(payload: PawaPayDepositCreate, request: Request, user: dict = Depends(get_current_user)):
    """DEPRECATED (Iter38r) — Replaced by the hosted Payment Page flow because
    the direct /deposits endpoint does NOT collect the customer's PIN/OTP from
    our merchant UI (the OTP is prompted on the customer's phone via USSD,
    which often fails / is not transparent to the user). The new flow uses
    PawaPay's hosted page which handles MSISDN + PIN collection natively.

    This endpoint now forwards to the Payment Page endpoint, building a
    response shaped identically to the legacy success payload so that
    pre-v38r clients (mobile apps, embedded checkouts) keep working until
    they migrate.
    """
    pp_payload = PawaPayPaymentPageCreate(
        amount=payload.amount,
        msisdn=payload.msisdn,
        country=None,
        reason=(payload.description or "")[:50] or None,
        return_url=None,
    )
    res = await me_pawapay_payment_page(pp_payload, request, user)
    return {
        "ok": True,
        "deposit_id": res["deposit_id"],
        "status": "initiated",
        "redirect_url": res["redirect_url"],
        "deprecated": True,
        "message": "Veuillez utiliser /me/payments/pawapay/payment-page (Iter38r).",
    }


class PawaPayPaymentPageCreate(BaseModel):
    amount: Optional[float] = Field(None, gt=0)
    # Optional — pre-fixes the MSISDN on the hosted page. When omitted the
    # customer enters it on the PawaPay page.
    msisdn: Optional[str] = None
    country: Optional[str] = None  # ISO-3 (BFA, CIV, SEN…). Defaults to settings.pawapay_country.
    reason: Optional[str] = Field(None, max_length=50)
    # Where PawaPay redirects the customer after they "Pay" / abandon. Defaults
    # to {origin}/portal/payments/return.
    return_url: Optional[str] = Field(None, max_length=500)


@api.post("/me/payments/pawapay/payment-page", tags=["Portail Client"])
async def me_pawapay_payment_page(
    payload: PawaPayPaymentPageCreate, request: Request, user: dict = Depends(get_current_user)
):
    """Iter38r — Initiate a hosted PawaPay Payment Page session.

    The hosted page collects the MSISDN + PIN/OTP. We persist the payment row
    BEFORE calling PawaPay so reconciliation is guaranteed even on network
    error (per PawaPay's recommended best-practice).
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not s.get("pawapay_enabled"):
        raise HTTPException(status_code=503, detail="PawaPay non activé")
    token = _pawapay_active_token(s)
    if not token:
        raise HTTPException(status_code=503, detail="Clé API PawaPay non configurée")
    # Feature gating
    parent_id = user.get("client_id") or user["id"]
    parent = await db.users.find_one(
        {"id": parent_id},
        {"_id": 0, "features": 1, "pawapay_mnos": 1, "pawapay_fix_msisdn": 1, "phone": 1, "whatsapp": 1, "id": 1, "company": 1},
    )
    if user.get("role") not in ("admin", "superviseur"):
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("payments"):
            raise HTTPException(status_code=403, detail="Paiements non autorisés pour votre client")
    # MSISDN policy: per-client toggle (None = inherit global; True = always fix; False = leave open)
    fix_msisdn_pref = (parent or {}).get("pawapay_fix_msisdn")
    if fix_msisdn_pref is None:
        fix_msisdn_pref = s.get("pawapay_fix_msisdn_default", True)
    msisdn_final: Optional[str] = None
    if fix_msisdn_pref:
        # Use explicit payload msisdn, then user profile fallback
        candidate = (payload.msisdn or user.get("whatsapp") or user.get("phone") or "").strip()
        msisdn_final = "".join(ch for ch in candidate if ch.isdigit()) or None
        if msisdn_final and len(msisdn_final) < 8:
            msisdn_final = None  # Too short → let PawaPay collect it instead
    elif payload.msisdn:
        # Free mode but caller passed an explicit number → honor it
        msisdn_final = "".join(ch for ch in payload.msisdn if ch.isdigit()) or None
    env = (s.get("pawapay_environment") or "sandbox").lower()
    host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
    country = (payload.country or s.get("pawapay_country") or "BFA").upper()
    deposit_id = _uuid()
    # Build return URL from explicit payload, else from request Origin/Referer
    origin = (
        payload.return_url
        or _frontend_origin_from_request(request)
        or "https://sawalismartsystems.com"
    ).rstrip("/")
    return_url = (
        payload.return_url
        if payload.return_url
        else f"{origin}/portal/payments/return?depositId={deposit_id}"
    )
    body: Dict[str, Any] = {
        "depositId": deposit_id,
        "returnUrl": return_url,
    }
    if payload.amount and payload.amount > 0:
        # v2 — amount is nested under amountDetails with explicit currency.
        amt_str = str(int(payload.amount)) if float(payload.amount).is_integer() else f"{payload.amount:.2f}"
        body["amountDetails"] = {
            "amount": amt_str,
            "currency": _pawapay_currency_for_country(country),
        }
    # Country is always sent — restricts the wallet selection to that country.
    body["country"] = country
    if msisdn_final:
        # v2 — `msisdn` was renamed to `phoneNumber`. Must be digits-only, no '+'.
        body["phoneNumber"] = msisdn_final
    if payload.reason:
        body["reason"] = payload.reason[:50]
    # Persist FIRST (PawaPay best-practice: never lose track of a depositId)
    payment_doc = {
        "id": _uuid(),
        "deposit_id": deposit_id,
        "client_id": parent_id,
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_label": user.get("full_name") or user.get("email"),
        "amount": float(payload.amount) if payload.amount else None,
        "currency": "XOF",
        "country": country,
        "mno": None,  # determined by customer on hosted page
        "msisdn": msisdn_final,
        "description": payload.reason,
        "environment": env,
        "flow": "payment_page",
        "status": "initiated",
        "api_status": None,
        "api_message": None,
        "return_url": return_url,
        "redirect_url": None,
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.payments.insert_one(payment_doc.copy())
    payment_doc.pop("_id", None)
    # Call PawaPay
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(
                f"{host}/v2/paymentpage",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
            try:
                api_resp = r.json()
            except Exception:
                api_resp = {"raw": r.text[:500]}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à PawaPay")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erreur PawaPay : {str(exc)[:200]}") from exc
    redirect_url = (api_resp or {}).get("redirectUrl")
    if not redirect_url:
        # API call failed — mark as failed for reconciliation visibility
        await db.payments.update_one(
            {"deposit_id": deposit_id},
            {"$set": {
                "status": "failed",
                "api_status": "PAYMENT_PAGE_REJECTED",
                "api_message": _pawapay_str(api_resp.get("failureReason") or api_resp.get("message") or api_resp),
                "updated_at": _now(),
            }},
        )
        raise HTTPException(
            status_code=502,
            detail=_pawapay_str(api_resp.get("failureReason") or api_resp.get("message")) or "PawaPay n'a pas renvoyé de lien de paiement.",
        )
    await db.payments.update_one(
        {"deposit_id": deposit_id},
        {"$set": {"redirect_url": redirect_url, "updated_at": _now()}},
    )
    return {
        "ok": True,
        "deposit_id": deposit_id,
        "redirect_url": redirect_url,
        "return_url": return_url,
        "msisdn_fixed": bool(msisdn_final),
    }


def _frontend_origin_from_request(request: Request) -> Optional[str]:
    """Best-effort extraction of the caller's web origin (for buildling
    return_url). Prefers Origin, falls back to Referer."""
    o = request.headers.get("origin") or ""
    if o.startswith("http"):
        return o
    ref = request.headers.get("referer") or ""
    if ref.startswith("http"):
        from urllib.parse import urlparse
        u = urlparse(ref)
        if u.scheme and u.netloc:
            return f"{u.scheme}://{u.netloc}"
    return None


@api.get("/me/payments", tags=["Portail Client"])
async def me_list_payments(user: dict = Depends(get_current_user)):
    """Liste les paiements récents. Only SAWALI super-admin sees ALL tenants.
    Client-admin sees their tenant. Plain users see only their own.
    Iter43-fix24az-l — cross-tenant leak fix."""
    if _is_super_admin(user):
        items = await db.payments.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    elif user.get("role") in ("admin", "superviseur"):
        scope = await _resolve_visible_client_ids(user)
        items = await db.payments.find(
            {"$or": [{"user_id": {"$in": scope}}, {"client_id": {"$in": scope}}]},
            {"_id": 0}
        ).sort("created_at", -1).to_list(500)
    else:
        items = await db.payments.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return items


@api.get("/me/payments/{deposit_id}", tags=["Portail Client"])
async def me_get_payment(deposit_id: str, user: dict = Depends(get_current_user)):
    """Polling endpoint — refreshes the payment by querying PawaPay if still pending."""
    p = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    if user.get("role") not in ("admin", "superviseur") and p.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Accès non autorisé")
    if p.get("status") not in ("pending", "initiated"):
        return p
    # Live refresh
    s = await db.settings.find_one({"_id": "global"}) or {}
    token = _pawapay_active_token(s)
    if not token:
        return p
    env = (p.get("environment") or s.get("pawapay_environment") or "sandbox").lower()
    host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            # Iter38r — use v2 endpoint (returns FOUND/NOT_FOUND wrapper)
            r = await http.get(f"{host}/v2/deposits/{deposit_id}", headers={"Authorization": f"Bearer {token}"})
            data = r.json() if r.status_code < 400 else {}
            # v2 returns {status: "FOUND", data: {...}} or {status: "NOT_FOUND"}
            wrapper_status = (data.get("status") or "").upper() if isinstance(data, dict) else ""
            entry: Dict[str, Any] = {}
            if wrapper_status == "FOUND":
                entry = data.get("data") or {}
            elif isinstance(data, list) and data:
                # Defensive fallback for v1 shape
                entry = data[0]
            elif isinstance(data, dict) and data.get("depositId"):
                entry = data
            api_status = (entry.get("status") or "").upper()
            new_status = {
                "COMPLETED": "completed",
                "FAILED": "failed",
                "REJECTED": "failed",
                "ACCEPTED": "pending",
                "PROCESSING": "pending",
                "SUBMITTED": "pending",
                "PENDING": "pending",
            }.get(api_status, p.get("status") or "pending")
            # Iter38r-fix2 — Enrich with provider (MNO) + phoneNumber from PawaPay
            extracted_mno, extracted_country = _pawapay_split_provider(entry.get("provider"))
            extracted_phone = _pawapay_str(entry.get("phoneNumber"))
            set_doc: Dict[str, Any] = {
                "status": new_status,
                "api_status": api_status,
                "api_message": _pawapay_str(entry.get("failureReason") or entry.get("rejectionReason")),
                "completed_at": entry.get("respondedTimestamp") or (None if new_status == "pending" else _now()),
                "updated_at": _now(),
                "raw_response": entry,
            }
            if extracted_mno:
                set_doc["mno"] = extracted_mno
            if entry.get("provider"):
                set_doc["provider"] = entry.get("provider")  # full code, audit
            if extracted_country and not p.get("country"):
                set_doc["country"] = extracted_country
            if extracted_phone and not p.get("msisdn"):
                set_doc["msisdn"] = extracted_phone
            await db.payments.update_one({"deposit_id": deposit_id}, {"$set": set_doc})
            p = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pawapay-poll] %s — %s", deposit_id, exc)
    return p


# Lot 36 — actions à lancer quand un paiement passe à « completed » (ex. Liluvine
# « !formulaire » : mise en ligne du formulaire payé). Les modules s'y inscrivent
# (p20) ; chaque action est idempotente et appelée avec le document `payments`.
_HOOKS_APRES_PAIEMENT: List[Any] = []


async def _apres_paiement_complete(deposit_id: str) -> None:
    payment = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
    if not payment or payment.get("status") != "completed":
        return
    for hook in list(_HOOKS_APRES_PAIEMENT):
        try:
            await hook(payment)
        except Exception:  # noqa: BLE001
            logger.warning("[paiement] action après paiement en échec (%s)", deposit_id, exc_info=True)


async def _pawapay_webhook_apply(payload: Dict[str, Any], op_type: str) -> Dict[str, Any]:
    """Iter38r-fix2 — Shared handler for PawaPay deposit/refund webhooks.
    `op_type` ∈ {"deposit", "refund"} — currently only deposit flips status;
    refund webhooks are persisted for audit but do not mutate the source
    payment row (refunds get their own collection later).
    """
    deposit_id = payload.get("depositId") or payload.get("deposit_id") or payload.get("refundId")
    if not deposit_id:
        return {"ok": False, "reason": "depositId/refundId manquant"}
    api_status = (payload.get("status") or "").upper()
    new_status = {
        "COMPLETED": "completed",
        "FAILED": "failed",
        "REJECTED": "failed",
        "ACCEPTED": "pending",
        "PROCESSING": "pending",
        "SUBMITTED": "pending",
        "PENDING": "pending",
    }.get(api_status, "pending")
    # Enrich with provider (MNO) + phoneNumber if present
    extracted_mno, extracted_country = _pawapay_split_provider(payload.get("provider"))
    extracted_phone = _pawapay_str(payload.get("phoneNumber"))
    set_doc: Dict[str, Any] = {
        "status": new_status,
        "api_status": api_status,
        "api_message": _pawapay_str(payload.get("failureReason") or payload.get("rejectionReason")),
        "completed_at": payload.get("respondedTimestamp") or _now(),
        "updated_at": _now(),
        "raw_response": payload,
        "last_webhook_op": op_type,
    }
    if extracted_mno:
        set_doc["mno"] = extracted_mno
    if payload.get("provider"):
        set_doc["provider"] = payload.get("provider")
    if extracted_country:
        set_doc["country_from_provider"] = extracted_country
    if extracted_phone:
        set_doc["msisdn_from_webhook"] = extracted_phone
    await db.payments.update_one({"deposit_id": deposit_id}, {"$set": set_doc})
    if new_status == "completed":
        await _apres_paiement_complete(deposit_id)          # lot 36
    # Iter38r-fix9w — Voice notification on completed PawaPay deposit
    if new_status == "completed":
        try:
            payment = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
            if payment and payment.get("client_id"):
                await _voice_notify(payment["client_id"], "payment_pawapay_received", {
                    "amount": payment.get("amount") or 0,
                    "client_name": payment.get("payer_name") or payment.get("description") or "—",
                    "provider": extracted_mno or "Mobile Money",
                    "msisdn": extracted_phone or payment.get("msisdn") or "",
                })
        except Exception:
            pass
    return {"ok": True, "deposit_id": deposit_id, "status": new_status, "op": op_type}


async def _pawapay_webhook_entry(secret: str, request: Request, op_type: str) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}) or {}
    expected = (s.get("pawapay_callback_secret") or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Secret invalide")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return await _pawapay_webhook_apply(payload, op_type)


@api.post("/webhooks/pawapay/deposits/{secret}", tags=["Webhooks"])
async def webhook_pawapay_deposits(secret: str, request: Request):
    """Iter38r-fix2 — PawaPay deposit callback. URL à coller dans le tableau
    de bord PawaPay → Configuration → Callback URLs → Deposits."""
    return await _pawapay_webhook_entry(secret, request, "deposit")


@api.post("/webhooks/pawapay/refunds/{secret}", tags=["Webhooks"])
async def webhook_pawapay_refunds(secret: str, request: Request):
    """Iter38r-fix2 — PawaPay refund callback. URL à coller dans le tableau
    de bord PawaPay → Configuration → Callback URLs → Refunds."""
    return await _pawapay_webhook_entry(secret, request, "refund")


@api.post("/webhooks/pawapay/{secret}", tags=["Webhooks"])
async def webhook_pawapay(secret: str, request: Request):
    """Legacy generic PawaPay callback (kept for pre-Iter38r-fix2 configs).
    Detects deposit vs refund from payload presence of `depositId` / `refundId`."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    expected = (s.get("pawapay_callback_secret") or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Secret invalide")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    op_type = "refund" if payload.get("refundId") and not payload.get("depositId") else "deposit"
    return await _pawapay_webhook_apply(payload, op_type)


@api.get("/admin/pawapay/callback-urls", tags=["Admin"])
async def admin_pawapay_callback_urls(request: Request, _: dict = Depends(get_current_admin)):
    """Iter38r-fix2 — Renvoie les 2 URLs de callback à coller dans le dashboard PawaPay
    dashboard. Auto-generates `pawapay_callback_secret` if missing so the
    URLs are always usable. The base host is derived from the incoming
    request so admins on preview get preview URLs and admins on production
    get production URLs."""
    import secrets as _secrets
    s = await db.settings.find_one({"_id": "global"}) or {}
    secret = (s.get("pawapay_callback_secret") or "").strip()
    if not secret:
        secret = _secrets.token_urlsafe(32)
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"pawapay_callback_secret": secret, "pawapay_callback_secret_generated_at": _now()}},
            upsert=True,
        )
    # Prefer the X-Forwarded-Host (Kubernetes ingress) + scheme, fall back to request.url
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    fwd_scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    base = f"{fwd_scheme}://{fwd_host}".rstrip("/") if fwd_host else str(request.base_url).rstrip("/")
    return {
        "deposits_url": f"{base}/api/webhooks/pawapay/deposits/{secret}",
        "refunds_url": f"{base}/api/webhooks/pawapay/refunds/{secret}",
        "legacy_url": f"{base}/api/webhooks/pawapay/{secret}",
        "secret_preview": secret[:6] + "…" + secret[-4:],
        "generated_at": s.get("pawapay_callback_secret_generated_at"),
    }


# ============================================================
# Payments Dashboard 360 — KPIs, channel attribution, conversion.
# Crosses payments + payment_links + whatsapp_messages + sms_messages.
# Channel attribution : a message containing the substring "/pay/{slug}"
# in its body is considered to have driven any payment recorded for that
# slug (best-effort heuristic — works because every link is unique).
# ============================================================
@api.get("/me/payments-dashboard", tags=["Portail Client"])
async def me_payments_dashboard(days: int = 30, user: dict = Depends(get_current_user)):
    days = max(1, min(int(days or 30), 365))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    is_admin = user.get("role") in ("admin", "superviseur")
    client_scope = (user.get("client_id") or user["id"])
    pay_q: Dict[str, Any] = {} if is_admin else {"client_id": client_scope}
    pay_q["created_at"] = {"$gte": since}
    payments = await db.payments.find(pay_q, {"_id": 0}).to_list(2000)
    links_q: Dict[str, Any] = {} if is_admin else {"client_id": client_scope}
    links = await db.payment_links.find(links_q, {"_id": 0}).to_list(1000)
    for li in links:
        li["status"] = _payment_link_status(li)
    slugs = [l["slug"] for l in links if l.get("slug")]
    by_channel = {"whatsapp": 0, "sms": 0, "direct": 0}
    sent_by_channel = {"whatsapp": 0, "sms": 0}
    if slugs:
        # Prefer the persisted payment_link_slug field (set since it. 42)
        wa_q: Dict[str, Any] = {"created_at": {"$gte": since}, "payment_link_slug": {"$in": slugs}}
        sms_q: Dict[str, Any] = {"created_at": {"$gte": since}, "payment_link_slug": {"$in": slugs}}
        if not is_admin:
            wa_q["client_id"] = client_scope
            sms_q["client_id"] = client_scope
        sent_by_channel["whatsapp"] = await db.whatsapp_messages.count_documents(wa_q)
        sent_by_channel["sms"] = await db.sms_messages.count_documents(sms_q)
    by_status = {"pending": 0, "completed": 0, "failed": 0}
    by_mno = {"ORANGE": 0, "MOOV": 0, "TELECEL": 0, "OTHER": 0}
    total_amount_completed = 0.0
    daily: Dict[str, Dict[str, float]] = {}
    for p in payments:
        st = p.get("status") or "pending"
        by_status[st] = by_status.get(st, 0) + 1
        m = (p.get("mno") or "").upper() or "OTHER"
        by_mno[m if m in by_mno else "OTHER"] += 1
        if st == "completed":
            total_amount_completed += float(p.get("amount") or 0)
        src = (p.get("source") or "").lower()
        if src == "payment_link":
            by_channel["direct"] += 1
        ts = (p.get("created_at") or "")[:10]
        if ts:
            daily.setdefault(ts, {"count": 0, "amount": 0.0})
            daily[ts]["count"] += 1
            if st == "completed":
                daily[ts]["amount"] += float(p.get("amount") or 0)
    today = datetime.now(timezone.utc).date()
    daily_arr = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        e = daily.get(d) or {"count": 0, "amount": 0.0}
        daily_arr.append({"date": d, "count": int(e["count"]), "amount": round(e["amount"], 2)})
    sorted_links = sorted(links, key=lambda x: (x.get("uses_count") or 0), reverse=True)[:5]
    top_links = [
        {
            "slug": l.get("slug"),
            "label": l.get("label"),
            "amount": l.get("amount"),
            "uses_count": l.get("uses_count") or 0,
            "max_uses": l.get("max_uses"),
            "status": l.get("status"),
        }
        for l in sorted_links
    ]
    sent_total = sent_by_channel["whatsapp"] + sent_by_channel["sms"]
    completed_count = by_status.get("completed", 0)
    conversion_rate = round(100.0 * completed_count / max(sent_total, 1), 1) if sent_total else None
    return {
        "period_days": days,
        "totals": {
            "links": len(links),
            "links_active": sum(1 for l in links if l["status"] == "active"),
            "links_disabled": sum(1 for l in links if l["status"] == "disabled"),
            "links_expired": sum(1 for l in links if l["status"] == "expired"),
            "links_exhausted": sum(1 for l in links if l["status"] == "exhausted"),
            "payments_count": len(payments),
            "payments_completed": completed_count,
            "payments_pending": by_status.get("pending", 0),
            "payments_failed": by_status.get("failed", 0),
            "amount_completed": round(total_amount_completed, 2),
        },
        "by_status": by_status,
        "by_mno": by_mno,
        "channels": {
            "sent": sent_by_channel,
            "payments_attributed": by_channel,
            "conversion_rate_pct": conversion_rate,
        },
        "daily": daily_arr,
        "top_links": top_links,
    }





# ============================================================
# Payment Links — shareable URLs that let anyone pay via PawaPay
# without having a portal account. Each link is owned by a client
# (or a tracked user of that client) and reuses the PawaPay flow.
# Public URL : /pay/{slug}  (rendered by the React app).
# ============================================================
class PaymentLinkCreate(BaseModel):
    label: str
    amount: Optional[float] = None  # None → open amount (payer chooses)
    currency: str = "XOF"
    description: Optional[str] = None
    allowed_mnos: Optional[List[str]] = None  # subset of the client's MNOs
    expires_at: Optional[str] = None  # ISO8601 UTC
    max_uses: Optional[int] = None  # None → unlimited


def _gen_slug(n: int = 8) -> str:
    import string
    alpha = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alpha) for _ in range(n))


def _payment_link_status(d: Dict[str, Any]) -> str:
    if d.get("disabled"):
        return "disabled"
    exp = d.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(str(exp).replace("Z", "+00:00")) < datetime.now(timezone.utc):
                return "expired"
        except Exception:  # noqa: BLE001
            pass
    mu = d.get("max_uses")
    if mu and (d.get("uses_count") or 0) >= mu:
        return "exhausted"
    return "active"


@api.post("/me/payment-links", tags=["Portail Client"])
async def me_create_payment_link(payload: PaymentLinkCreate, user: dict = Depends(get_current_user)):
    await _enforce_demo_quota(user, QUOTA_KEY_PAYMENTS)  # Iter35h
    parent_id = user.get("client_id") or user["id"]
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1, "pawapay_mnos": 1, "company": 1, "logo_url": 1})
    if user.get("role") not in ("admin", "superviseur"):
        feats = _normalize_features((parent or {}).get("features"))
        if not feats.get("payments"):
            raise HTTPException(status_code=403, detail="Paiements non autorisés pour votre compte")
    client_mnos = _normalize_pawapay_mnos((parent or {}).get("pawapay_mnos"))
    requested = [m.upper() for m in (payload.allowed_mnos or client_mnos)]
    invalid = [m for m in requested if m not in client_mnos]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Opérateurs non autorisés : {', '.join(invalid)}")
    if not requested:
        raise HTTPException(status_code=400, detail="Aucun opérateur disponible — configurez d'abord les MNO du client")
    if payload.amount is not None and payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Montant invalide")
    if payload.max_uses is not None and payload.max_uses <= 0:
        raise HTTPException(status_code=400, detail="Nombre d'utilisations invalide")
    if not (payload.label or "").strip():
        raise HTTPException(status_code=400, detail="Libellé requis")
    slug = None
    for _ in range(8):
        cand = _gen_slug(8)
        if not await db.payment_links.find_one({"slug": cand}):
            slug = cand
            break
    if not slug:
        raise HTTPException(status_code=500, detail="Impossible de générer un slug unique")
    doc = {
        "id": _uuid(),
        "slug": slug,
        "client_id": parent_id,
        "owner_user_id": user["id"],
        "owner_email": user.get("email"),
        "owner_label": user.get("full_name") or user.get("email"),
        "label": payload.label.strip()[:120],
        "amount": float(payload.amount) if payload.amount is not None else None,
        "currency": (payload.currency or "XOF").upper(),
        "description": (payload.description or "").strip()[:200],
        "allowed_mnos": requested,
        "expires_at": payload.expires_at,
        "max_uses": payload.max_uses,
        "uses_count": 0,
        "disabled": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.payment_links.insert_one(doc.copy())
    doc.pop("_id", None)
    doc["status"] = _payment_link_status(doc)
    # Iter34y — activity feed (payment link)
    try:
        client_id_log = doc.get("client_id") or user.get("parent_client_id") or user.get("client_id") or user["id"]
        amount_str = f"{doc.get('amount')} {doc.get('currency') or ''}".strip()
        await _log_activity(client_id=client_id_log, kind="payment", action="created", label=f"Lien — {amount_str} ({doc.get('description') or '—'})", actor=user, target_id=doc["id"])
    except Exception:
        pass
    return doc


@api.get("/me/payment-links", tags=["Portail Client"])
async def me_list_payment_links(user: dict = Depends(get_current_user)):
    """Iter43-fix24az-l — cross-tenant leak fix. Only SAWALI super-admin sees
    all; client-admin scoped to their tenant."""
    if _is_super_admin(user):
        items = await db.payment_links.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    elif user.get("role") in ("admin", "superviseur"):
        scope = await _resolve_visible_client_ids(user)
        items = await db.payment_links.find(
            {"client_id": {"$in": scope}}, {"_id": 0}
        ).sort("created_at", -1).to_list(500)
    else:
        items = await db.payment_links.find(
            {"client_id": user.get("client_id") or user["id"]}, {"_id": 0}
        ).sort("created_at", -1).to_list(200)
    for it in items:
        it["status"] = _payment_link_status(it)
    return items


@api.patch("/me/payment-links/{link_id}", tags=["Portail Client"])
async def me_toggle_payment_link(link_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    pl = await db.payment_links.find_one({"id": link_id}, {"_id": 0})
    if not pl:
        raise HTTPException(status_code=404, detail="Lien introuvable")
    if user.get("role") not in ("admin", "superviseur") and pl.get("client_id") != (user.get("client_id") or user["id"]):
        raise HTTPException(status_code=403, detail="Accès refusé")
    update: Dict[str, Any] = {"updated_at": _now()}
    if "disabled" in payload:
        update["disabled"] = bool(payload["disabled"])
    await db.payment_links.update_one({"id": link_id}, {"$set": update})
    refreshed = await db.payment_links.find_one({"id": link_id}, {"_id": 0})
    if refreshed:
        refreshed["status"] = _payment_link_status(refreshed)
    return refreshed or {"ok": True}


@api.delete("/me/payment-links/{link_id}", tags=["Portail Client"])
async def me_delete_payment_link(link_id: str, user: dict = Depends(get_current_user)):
    pl = await db.payment_links.find_one({"id": link_id}, {"_id": 0})
    if not pl:
        raise HTTPException(status_code=404, detail="Lien introuvable")
    if user.get("role") not in ("admin", "superviseur") and pl.get("client_id") != (user.get("client_id") or user["id"]):
        raise HTTPException(status_code=403, detail="Accès refusé")
    await db.payment_links.delete_one({"id": link_id})
    return {"ok": True}


@api.get("/public/pay/{slug}", tags=["Public"])
async def public_get_payment_link(slug: str):
    pl = await db.payment_links.find_one({"slug": slug}, {"_id": 0})
    if not pl:
        raise HTTPException(status_code=404, detail="Lien de paiement introuvable")
    parent = await db.users.find_one(
        {"id": pl.get("client_id")},
        {"_id": 0, "company": 1, "logo_url": 1, "branding": 1, "full_name": 1},
    )
    branding_logo = None
    if parent:
        branding_logo = parent.get("logo_url")
        if not branding_logo and isinstance(parent.get("branding"), dict):
            branding_logo = parent["branding"].get("logo_url")
    return {
        "slug": pl["slug"],
        "label": pl.get("label"),
        "amount": pl.get("amount"),
        "currency": pl.get("currency") or "XOF",
        "description": pl.get("description"),
        "allowed_mnos": pl.get("allowed_mnos") or [],
        "expires_at": pl.get("expires_at"),
        "status": _payment_link_status(pl),
        "uses_count": pl.get("uses_count") or 0,
        "max_uses": pl.get("max_uses"),
        "branding": {
            "company": (parent or {}).get("company") or (parent or {}).get("full_name"),
            "logo_url": branding_logo,
        },
    }


class PublicPayRequest(BaseModel):
    msisdn: str
    mno: str
    amount: Optional[float] = None  # mandatory only when link has open amount
    payer_name: Optional[str] = None


@api.post("/public/pay/{slug}/deposit", tags=["Public"])
async def public_pay_deposit(slug: str, payload: PublicPayRequest, request: Request):
    pl = await db.payment_links.find_one({"slug": slug}, {"_id": 0})
    if not pl:
        raise HTTPException(status_code=404, detail="Lien de paiement introuvable")
    status = _payment_link_status(pl)
    if status != "active":
        raise HTTPException(status_code=409, detail=f"Lien non utilisable (statut : {status})")
    s = await db.settings.find_one({"_id": "global"}) or {}
    if not s.get("pawapay_enabled"):
        raise HTTPException(status_code=503, detail="PawaPay non activé")
    token = _pawapay_active_token(s)
    if not token:
        raise HTTPException(status_code=503, detail="Clé API PawaPay non configurée")
    if pl.get("amount") is not None:
        amount = float(pl["amount"])
    else:
        if payload.amount is None or payload.amount <= 0:
            raise HTTPException(status_code=400, detail="Montant requis pour ce lien")
        amount = float(payload.amount)
    mno = (payload.mno or "").upper()
    allowed = pl.get("allowed_mnos") or []
    if mno not in allowed:
        raise HTTPException(status_code=400, detail=f"Opérateur non autorisé. Disponibles : {', '.join(allowed)}")
    msisdn_clean = "".join(ch for ch in (payload.msisdn or "") if ch.isdigit())
    if len(msisdn_clean) < 8:
        raise HTTPException(status_code=400, detail="Numéro mobile invalide")
    env = (s.get("pawapay_environment") or "sandbox").lower()
    host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
    country = (s.get("pawapay_country") or "BFA").upper()
    deposit_id = _uuid()
    body = {
        "depositId": deposit_id,
        "amount": str(amount),
        "currency": pl.get("currency") or "XOF",
        "country": country,
        "correspondent": _pawapay_correspondent(mno, country),
        "payer": {"type": "MSISDN", "address": {"value": msisdn_clean}},
        "customerTimestamp": _now(),
        "statementDescription": (pl.get("label") or "SAWALI")[:22],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(
                f"{host}/deposits",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
            api_resp: Dict[str, Any] = {}
            try:
                api_resp = r.json()
            except Exception:  # noqa: BLE001
                api_resp = {"raw": r.text[:500]}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à PawaPay")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erreur PawaPay : {exc}"[:300])
    api_status = (api_resp.get("status") or "").upper()
    initial_status = "pending" if api_status in ("ACCEPTED", "PENDING", "") else "failed"
    doc = {
        "id": _uuid(),
        "deposit_id": deposit_id,
        "client_id": pl["client_id"],
        "user_id": pl.get("owner_user_id"),
        "user_email": pl.get("owner_email"),
        "user_label": pl.get("owner_label"),
        "amount": amount,
        "currency": pl.get("currency") or "XOF",
        "country": country,
        "mno": mno,
        "msisdn": msisdn_clean,
        "description": pl.get("label"),
        "environment": env,
        "status": initial_status,
        "api_status": api_status or None,
        "api_message": _pawapay_str(api_resp.get("failureReason") or api_resp.get("rejectionReason") or api_resp.get("message")),
        "ip": _client_ip_from_request(request),
        "user_agent": request.headers.get("user-agent"),
        "source": "payment_link",
        "payment_link_slug": slug,
        "payment_link_id": pl["id"],
        "payer_name": (payload.payer_name or "").strip()[:80] or None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.payments.insert_one(doc.copy())
    doc.pop("_id", None)
    if initial_status != "failed":
        await db.payment_links.update_one(
            {"id": pl["id"]},
            {"$inc": {"uses_count": 1}, "$set": {"updated_at": _now()}},
        )
    if api_resp.get("status") == "REJECTED":
        return {"ok": False, "deposit_id": deposit_id, "status": "failed", "reason": _pawapay_str(api_resp.get("rejectionReason"))}
    return {"ok": True, "deposit_id": deposit_id, "status": initial_status}


@api.get("/public/pay/{slug}/status/{deposit_id}", tags=["Public"])
async def public_pay_status(slug: str, deposit_id: str):
    """Polling endpoint for the public payment landing page (no auth)."""
    p = await db.payments.find_one({"deposit_id": deposit_id, "payment_link_slug": slug}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    # If still pending, refresh from PawaPay live
    if p.get("status") == "pending":
        s = await db.settings.find_one({"_id": "global"}) or {}
        token = _pawapay_active_token(s)
        if token:
            env = (p.get("environment") or s.get("pawapay_environment") or "sandbox").lower()
            host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
            try:
                async with httpx.AsyncClient(timeout=15) as http:
                    rr = await http.get(f"{host}/deposits/{deposit_id}", headers={"Authorization": f"Bearer {token}"})
                    arr = rr.json() if rr.status_code < 400 else []
                    entry = arr[0] if isinstance(arr, list) and arr else (arr if isinstance(arr, dict) else {})
                    api_status = (entry.get("status") or "").upper()
                    new_status = {
                        "COMPLETED": "completed", "FAILED": "failed", "REJECTED": "failed",
                        "ACCEPTED": "pending", "PROCESSING": "pending", "SUBMITTED": "pending", "PENDING": "pending",
                    }.get(api_status, p.get("status"))
                    if new_status != p.get("status"):
                        await db.payments.update_one({"deposit_id": deposit_id}, {"$set": {
                            "status": new_status,
                            "api_status": api_status,
                            "api_message": _pawapay_str(entry.get("failureReason") or entry.get("rejectionReason")),
                            "completed_at": entry.get("respondedTimestamp") or (None if new_status == "pending" else _now()),
                            "updated_at": _now(),
                        }})
                        p = await db.payments.find_one({"deposit_id": deposit_id}, {"_id": 0})
                        if new_status == "completed":
                            await _apres_paiement_complete(deposit_id)   # lot 36
            except Exception as exc:  # noqa: BLE001
                logger.warning("[pay-link-poll] %s — %s", deposit_id, exc)
    return {
        "status": p.get("status"),
        "api_message": p.get("api_message"),
        "amount": p.get("amount"),
        "currency": p.get("currency") or "XOF",
    }





@api.put("/me/appointments/{appt_id}", tags=["Portail Client"])
async def me_update_appointment(
    appt_id: str, payload: AppointmentUpdate, user: dict = Depends(get_current_user),
):
    """Client may edit their own upcoming appointments (pending/confirmed)."""
    existing = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    # Access control: owner (client_id) or elevated tracked users
    owner_scope = existing.get("client_id")
    if owner_scope != (user.get("client_id") or user.get("id")) and not _is_elevated_creator(user) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès refusé")
    if (existing.get("status") or "") == "completed":
        raise HTTPException(status_code=400, detail="Un rendez-vous terminé ne peut être modifié")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Re-check slot availability if rescheduling
    if "scheduled_at" in update or "duration_min" in update:
        new_sched = update.get("scheduled_at") or existing.get("scheduled_at")
        new_dur = update.get("duration_min") or existing.get("duration_min") or 30
        ok, reason = await _check_slot_available(new_sched, new_dur, exclude_id=appt_id)
        if not ok:
            raise HTTPException(status_code=409, detail=reason)
    update["updated_at"] = _now()
    await db.appointments.update_one({"id": appt_id}, {"$set": update})
    refreshed = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    asyncio.create_task(_fire_agenda_n8n("updated", refreshed or {**existing, **update}, user))
    # Sync Google Calendar if linked
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
    # 2026-02 fork iter107 — Notifier les participants lors d'une mise à jour.
    try:
        asyncio.create_task(_dispatch_appointment_participants(
            refreshed or {**existing, **update}, user, event="appointment.updated",
        ))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


@api.delete("/me/appointments/{appt_id}", tags=["Portail Client"])
async def me_delete_appointment(appt_id: str, user: dict = Depends(get_current_user)):
    existing = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    owner_scope = existing.get("client_id")
    if owner_scope != (user.get("client_id") or user.get("id")) and not _is_elevated_creator(user) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès refusé")
    await db.appointments.delete_one({"id": appt_id})
    asyncio.create_task(_fire_agenda_n8n("deleted", existing, user))
    if existing.get("gcal_event_id"):
        try:
            await gcal.delete_event(existing["gcal_event_id"])
        except Exception as exc:
            logger.warning("GCal delete failed: %s", exc)
    return {"ok": True}


@api.post("/me/appointments", tags=["Portail Client"])
async def me_create_appointment(
    payload: ClientAppointmentRequest, user: dict = Depends(get_current_user)
):
    ok, reason = await _check_slot_available(payload.scheduled_at, payload.duration_min)
    if not ok:
        raise HTTPException(status_code=409, detail=reason)
    # Shared per-client scope: even tracked users land their RDV on the parent client_id
    client_scope = user.get("client_id") or user["id"]
    doc = {
        "id": _uuid(),
        "client_id": client_scope,
        "name": user["full_name"],
        "email": user["email"],
        "phone": user.get("phone"),
        "company": user.get("company"),
        "subject": payload.subject,
        "message": payload.message,
        "scheduled_at": payload.scheduled_at,
        "duration_min": payload.duration_min,
        "status": "pending",
        "notes": None,
        "gcal_event_id": None,
        # 2026-02 fork iter107 — Participants + reminder_minutes.
        "participants": payload.participants or [],
        "reminder_minutes": payload.reminder_minutes,
        "created_at": _now(),
    }
    end_iso = (
        datetime.fromisoformat(payload.scheduled_at).replace(tzinfo=timezone.utc)
        + timedelta(minutes=payload.duration_min)
    ).isoformat()
    event_id = await gcal.create_event(
        summary=f"RDV client : {payload.subject}",
        description=f"Client : {user['full_name']} <{user['email']}>\n{payload.message or ''}",
        start_iso=payload.scheduled_at,
        end_iso=end_iso,
        attendee_email=user["email"],
    )
    doc["gcal_event_id"] = event_id
    await db.appointments.insert_one(doc.copy())
    doc.pop("_id", None)
    # Iter34y — activity feed (appointment)
    await _log_activity(client_id=user["id"], kind="appointment", action="created", label=doc.get("subject") or "(rendez-vous)", actor=user, target_id=doc["id"])
    # Fire automation: appointment.created
    try:
        sched_human = doc["scheduled_at"]
        try:
            sched_human = datetime.fromisoformat(doc["scheduled_at"].replace("Z", "+00:00")).strftime("%d/%m/%Y à %Hh%M")
        except Exception:
            pass
        asyncio.create_task(_emit_event("appointment.created", {
            "client_id": user["id"],
            "phone": user.get("phone"),
            "extra_ctx": {
                "appointment_date": sched_human,
                "appointment_subject": doc.get("subject") or "",
            },
        }))
    except Exception:
        pass
    asyncio.create_task(_fire_agenda_n8n("created", doc, user))
    # 2026-02 fork iter107 — Dispatch WA aux participants sélectionnés.
    asyncio.create_task(_dispatch_appointment_participants(
        doc, user, event="appointment.created",
    ))
    return doc



# =============================================================================
# 2026-02 fork iter105 — Sidebar access summary
# Returns whether the CURRENT user has at least one visible item in each of
# the tenant-scoped sections (Documents / Formations / Formulaires). Used by
# the frontend PortalLayout to hide sidebar entries that would land the user
# on an empty page. Admins/super-admins always see the entries.
# =============================================================================
@api.get("/me/access-summary", tags=["Portail Client"])
async def me_access_summary(user: dict = Depends(get_current_user)):
    """Ultra-light probe : counts documents/formations/forms visible to the
    current user, respecting `access_client_ids` gates and tenant scope. Only
    returns booleans (has_XXX)."""
    # Super-admin / admin / superviseur : always visible.
    # Lot 25 — Rôle modérateur accepté sous ses deux orthographes (moderateur / moderator).
    if _is_super_admin(user) or (user.get("role") in ("admin", "superviseur", "moderator", "moderateur")):
        return {"has_documents": True, "has_formations": True, "has_forms": True}

    # Resolve the tenant scope.
    effective_client_id = user.get("parent_client_id") or user.get("client_id") or user.get("id")

    async def _probe(coll_name: str) -> bool:
        try:
            cursor = db[coll_name].find(
                {"$or": [{"client_id": effective_client_id}, {"is_public": True}]},
                {"_id": 0, "access_client_ids": 1, "client_id": 1, "is_public": 1},
            )
            async for doc in cursor:
                if _item_accessible_by_tenant(doc, user):
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    has_docs = await _probe("documents")
    has_forms = await _probe("forms")
    has_formations = await _probe("formations")
    return {
        "has_documents": has_docs,
        "has_formations": has_formations,
        "has_forms": has_forms,
    }



@api.get("/me/documents", tags=["Portail Client"])
async def me_documents(user: dict = Depends(get_current_user)):
    """RGPD: anonymizes uploaded_by_email/name for non-privileged roles.
    Iter43-fix24az-l — cross-tenant leak fix. Only super-admin sees ALL; client
    admin/superviseur scoped to their tenant.

    2026-02 fork (P5) — Filtre supplémentaire `access_client_ids` : quand
    non-vide, restreint aux tenants explicitement autorisés.
    """
    if _is_super_admin(user):
        items = await db.documents.find({}, {"_id": 0}).to_list(5000)
    elif _can_consult_all_docs(user):
        scope = await _resolve_visible_client_ids(user)
        items = await db.documents.find(
            {"$or": [{"client_id": {"$in": scope}}, {"is_public": True}]}, {"_id": 0}
        ).to_list(5000)
    else:
        effective_client_id = user.get("parent_client_id") or user["id"]
        items = await db.documents.find(
            {"$or": [{"client_id": effective_client_id}, {"is_public": True}]}, {"_id": 0}
        ).to_list(500)
    # 2026-02 fork (P5) — enforce access_client_ids gate for non-admin
    items = [it for it in items if _item_accessible_by_tenant(it, user)]
    return await _maybe_anon_list(user, items, _apply_anon_to_document)


@api.get("/me/interventions", tags=["Portail Client"])
async def me_interventions(user: dict = Depends(get_current_user)):
    """RGPD: anonymizes the technician name for non-privileged roles.
    Iter43-fix24az-l — cross-tenant leak fix. Only super-admin sees ALL; client
    admin/elevated_creator scoped to their tenant."""
    if _is_super_admin(user):
        items = await db.interventions.find({}, {"_id": 0}).to_list(2000)
    elif _is_elevated_creator(user):
        scope = await _resolve_visible_client_ids(user)
        # 2026-02 fork (P1) — Own-creation fallback : a user always sees the
        # interventions they authored themselves, even if the target client_id
        # is outside their tenant scope (e.g. `support@sawali` opening
        # interventions against various client tenants).
        base_q: Dict[str, Any] = {"$or": [{"client_id": {"$in": scope}}, {"owner_id": user["id"]}]}
        # Iter43 — Cross-tenant share: include interventions created by colleagues
        try:
            from routes.tenant_sharing import resolve_visible_owner_ids  # noqa: E402
            visible_owner_ids = await resolve_visible_owner_ids(db, user)
            colleague_ids = [oid for oid in visible_owner_ids if oid != user["id"]]
        except Exception:
            colleague_ids = []
        if colleague_ids:
            q = {"$or": [base_q, {"owner_id": {"$in": colleague_ids}, "shared_with_tenant": True}]}
        else:
            q = base_q
        items = await db.interventions.find(q, {"_id": 0}).to_list(2000)
    else:
        effective_client_id = user.get("parent_client_id") or user["id"]
        # 2026-02 fork (P1) — Own-creation fallback (see comment above).
        base_q = {"$or": [{"client_id": effective_client_id}, {"owner_id": user["id"]}]}
        try:
            from routes.tenant_sharing import resolve_visible_owner_ids  # noqa: E402
            visible_owner_ids = await resolve_visible_owner_ids(db, user)
            colleague_ids = [oid for oid in visible_owner_ids if oid != user["id"]]
        except Exception:
            colleague_ids = []
        if colleague_ids:
            q = {"$or": [base_q, {"owner_id": {"$in": colleague_ids}, "shared_with_tenant": True}]}
        else:
            q = base_q
        items = await db.interventions.find(q, {"_id": 0}).to_list(1000)
    items = sorted(items, key=lambda x: x.get("intervention_date", ""), reverse=True)
    items = await _maybe_anon_list(user, items, _apply_anon_to_intervention)
    return await _attach_my_rating(items, "interventions", user["id"])


# Iter43-fix (2026-03) — Historique des interventions : taux horaire + PDF
DEFAULT_INTERVENTION_HOURLY_RATE_XOF = 15000


async def _resolve_hourly_rate_xof(user: dict) -> int:
    """Iter43-fix — Résout le taux horaire d'intervention pour un utilisateur.

    Ordre de priorité :
      1. `hourly_rate` sur la fiche du tenant parent (admin client) — champ
         existant déjà utilisé pour la facturation des tickets
      2. `default_intervention_hourly_rate_xof` dans settings.global
      3. 15 000 XOF (constante)
    """
    tid = user.get("parent_client_id") or user["id"]
    parent = await db.users.find_one({"id": tid}, {"_id": 0, "hourly_rate": 1})
    if parent and parent.get("hourly_rate"):
        try:
            r = float(parent["hourly_rate"])
            if r > 0:
                return int(r)
        except (TypeError, ValueError):
            pass
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "default_intervention_hourly_rate_xof": 1}) or {}
    if s.get("default_intervention_hourly_rate_xof"):
        try:
            return int(s["default_intervention_hourly_rate_xof"])
        except (TypeError, ValueError):
            pass
    return DEFAULT_INTERVENTION_HOURLY_RATE_XOF


@api.get("/me/interventions/hourly-rate", tags=["Portail Client"])
async def me_interventions_hourly_rate(user: dict = Depends(get_current_user)):
    """Retourne le taux horaire en XOF résolu pour l'utilisateur courant."""
    rate = await _resolve_hourly_rate_xof(user)
    return {"hourly_rate_xof": rate}


@api.get("/me/interventions/pdf", tags=["Portail Client"])
async def me_interventions_pdf(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """PDF de l'historique des interventions selon les filtres (date + client + statut).

    Colonnes : Référence, Date, Client, Titre, Statut, Technicien, Durée (h), Coût (XOF).
    Footer : total durée + total coût (durée × taux horaire résolu).

    Iter43-fix — Réservé Admin/Superviseur (la colonne Coût est confidentielle).
    """
    role = (user.get("role") or "").lower()
    if role not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="PDF réservé Admin/Superviseur")
    if _is_elevated_creator(user):
        items = await db.interventions.find({}, {"_id": 0}).to_list(5000)
    else:
        effective_client_id = user.get("parent_client_id") or user["id"]
        base_q: Dict[str, Any] = {"client_id": effective_client_id}
        try:
            from routes.tenant_sharing import resolve_visible_owner_ids  # noqa: E402
            visible_owner_ids = await resolve_visible_owner_ids(db, user)
            colleague_ids = [oid for oid in visible_owner_ids if oid != user["id"]]
        except Exception:
            colleague_ids = []
        q = {"$or": [base_q, {"owner_id": {"$in": colleague_ids}, "shared_with_tenant": True}]} if colleague_ids else base_q
        items = await db.interventions.find(q, {"_id": 0}).to_list(5000)

    def _in_range(d_iso: Optional[str]) -> bool:
        if not (from_date or to_date):
            return True
        d = (d_iso or "")[:10]
        if from_date and d < from_date:
            return False
        if to_date and d > to_date:
            return False
        return True
    items = [
        i for i in items
        if _in_range(i.get("intervention_date"))
        and (not client_id or i.get("client_id") == client_id)
        and (not status or i.get("status") == status)
    ]
    items = sorted(items, key=lambda x: x.get("intervention_date", ""), reverse=True)
    items = await _maybe_anon_list(user, items, _apply_anon_to_intervention)

    client_ids = list({i.get("client_id") for i in items if i.get("client_id")})
    clients_map: Dict[str, str] = {}
    if client_ids:
        async for u in db.users.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "company": 1, "full_name": 1}):
            clients_map[u["id"]] = u.get("company") or u.get("full_name") or u["id"][:8]

    hourly_rate = await _resolve_hourly_rate_xof(user)

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    import io as _io
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=24, bottomMargin=24, leftMargin=24, rightMargin=24, title="Historique des interventions")
    styles = getSampleStyleSheet()
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M")
    period_str = ""
    if from_date or to_date:
        period_str = f" — Période : {from_date or '…'} → {to_date or '…'}"
    story = [
        Paragraph("<b>SAWALI Smart Systems — Historique des interventions</b>", styles["Title"]),
        Paragraph(
            f"Généré le {now_str} — {len(items)} intervention(s){period_str} — Taux horaire : "
            f"{hourly_rate:,} XOF/h".replace(",", " "),
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]
    head = ["#", "Référence", "Date", "Client", "Titre", "Statut", "Technicien", "Durée (h)", "Coût (XOF)"]
    data: List[List[str]] = [head]
    total_hours = 0.0
    total_cost = 0
    STATUS_LABEL = {"planned": "Planifiée", "in_progress": "En cours", "completed": "Terminée", "cancelled": "Annulée"}
    for idx, i in enumerate(items, start=1):
        dh = float(i.get("duration_hours") or 0)
        cost = int(round(dh * hourly_rate))
        total_hours += dh
        total_cost += cost
        iso = (i.get("intervention_date") or "")[:10]
        date_fmt = ""
        if iso:
            try:
                date_fmt = datetime.fromisoformat(iso).strftime("%d/%m/%Y")
            except Exception:
                date_fmt = iso
        data.append([
            str(idx),
            (i.get("intervention_number") or "")[:18],
            date_fmt,
            (clients_map.get(i.get("client_id") or "") or "—")[:32],
            (i.get("title") or "")[:60],
            STATUS_LABEL.get(i.get("status") or "", i.get("status") or "—"),
            (i.get("technician") or "—")[:24],
            f"{dh:.2f}" if dh else "—",
            f"{cost:,}".replace(",", " ") if cost else "—",
        ])
    data.append([
        "", "", "", "", "", "", "TOTAL",
        f"{total_hours:.2f}",
        f"{total_cost:,}".replace(",", " "),
    ])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E90FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (7, 1), (8, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E0F2FE")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(tbl)
    # Iter43-fix24az-l retest — Offload reportlab doc.build to thread pool
    # to avoid blocking uvicorn's single-worker event loop (CF 520 mitigation).
    await asyncio.to_thread(doc.build, story)
    body = buf.getvalue()
    fname = f"interventions-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.pdf"
    return Response(content=body, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})



# =====================================================================
# Iter43-fix4 (2026-03) — Facturation depuis l'historique des interventions
# =====================================================================
class InterventionInvoicePayload(BaseModel):
    intervention_ids: List[str] = Field(default_factory=list, max_length=500)


async def _next_invoice_number(year: int) -> str:
    """Auto-numérotation INV-YYYY-00001."""
    from routes._counters import next_seq
    seq = await next_seq(db, f"interventions_invoices-{year}")
    return f"INV-{year}-{str(seq).zfill(5)}"


@api.post("/me/invoices/from-interventions", tags=["Portail Client"])
async def me_create_invoices_from_interventions(
    payload: InterventionInvoicePayload = Body(...),
    user: dict = Depends(get_current_user),
):
    """Génère 1 facture par tenant à partir d'interventions sélectionnées.

    - Filtre : interventions existantes ET non encore facturées
    - Groupe par `client_id` (tenant)
    - Pour chaque groupe : facture auto-numérotée, motif « Intervention(s) n°<liste> »
    - Lignes : date, n°, technicien, durée, sous-total = durée × taux horaire résolu
    - Marque chaque intervention `invoiced=True` + `invoice_id` + `invoice_number`
    - Réservé Admin/Superviseur
    """
    role = (user.get("role") or "").lower()
    if role not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Réservé Admin/Superviseur")
    ids = [i for i in (payload.intervention_ids or []) if isinstance(i, str) and i]
    if not ids:
        raise HTTPException(status_code=400, detail="Aucune intervention sélectionnée")
    # Récupère seulement les non-facturées
    cursor = db.interventions.find(
        {"id": {"$in": ids}, "invoiced": {"$ne": True}},
        {"_id": 0},
    )
    items = await cursor.to_list(len(ids))
    if not items:
        raise HTTPException(status_code=409, detail="Toutes les interventions sélectionnées sont déjà facturées")
    # Groupe par tenant (client_id) — interventions sans client_id sont rejetées
    by_tenant: Dict[str, List[Dict[str, Any]]] = {}
    for i in items:
        cid = i.get("client_id")
        if not cid:
            continue
        by_tenant.setdefault(cid, []).append(i)
    if not by_tenant:
        raise HTTPException(status_code=400, detail="Aucune intervention rattachée à un tenant")

    # Résout les noms tenants en un lookup
    tenants = await db.users.find(
        {"id": {"$in": list(by_tenant.keys())}},
        {"_id": 0, "id": 1, "company": 1, "full_name": 1, "email": 1, "hourly_rate": 1, "phone": 1, "whatsapp": 1},
    ).to_list(len(by_tenant))
    tenants_map = {t["id"]: t for t in tenants}
    global_settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "default_intervention_hourly_rate_xof": 1}) or {}
    global_default = global_settings.get("default_intervention_hourly_rate_xof") or DEFAULT_INTERVENTION_HOURLY_RATE_XOF

    year = datetime.now(timezone.utc).year
    created: List[Dict[str, Any]] = []
    for cid, interv_list in by_tenant.items():
        t = tenants_map.get(cid) or {}
        # Résout le taux horaire spécifique au tenant
        try:
            rate = int(float(t.get("hourly_rate") or 0))
        except (TypeError, ValueError):
            rate = 0
        if rate <= 0:
            rate = int(global_default)
        # Construit les lignes (triées par date)
        sorted_iv = sorted(interv_list, key=lambda x: x.get("intervention_date") or "")
        lines = []
        total = 0
        for iv in sorted_iv:
            dh = float(iv.get("duration_hours") or 0)
            subtotal = int(round(dh * rate))
            total += subtotal
            lines.append({
                "intervention_id": iv["id"],
                "intervention_number": iv.get("intervention_number") or "—",
                "intervention_date": iv.get("intervention_date") or "",
                "title": iv.get("title") or "",
                "technician": iv.get("technician") or "—",
                "duration_hours": dh,
                "hourly_rate_xof": rate,
                "subtotal_xof": subtotal,
            })
        num = await _next_invoice_number(year)
        numbers_list = ", ".join(l["intervention_number"] for l in lines if l["intervention_number"] != "—")
        invoice = {
            "id": _uuid(),
            "invoice_number": num,
            "tenant_id": cid,
            "tenant_name": t.get("company") or t.get("full_name") or t.get("email"),
            "tenant_phone": t.get("phone") or t.get("whatsapp"),
            "motif": f"Intervention(s) n° {numbers_list}" if numbers_list else "Interventions",
            "hourly_rate_xof": rate,
            "lines": lines,
            "total_xof": total,
            "currency": "XOF",
            "status": "draft",
            "intervention_ids": [iv["id"] for iv in sorted_iv],
            "created_at": _now(),
            "created_by_id": user["id"],
            "created_by_label": user.get("full_name") or user.get("email"),
            "cancelled_at": None,
            # Iter43-fix6 — Suivi de paiement
            "deposited_at": None,   # Date/heure de dépôt physique de la facture (renseigne le délai)
            "paid_at": None,        # Date/heure du règlement
            "due_days": 30,         # Délai d'échéance par défaut (jours après dépôt)
        }
        await db.interventions_invoices.insert_one(invoice.copy())
        # Verrouille les interventions
        await db.interventions.update_many(
            {"id": {"$in": invoice["intervention_ids"]}},
            {"$set": {
                "invoiced": True, "invoice_id": invoice["id"],
                "invoice_number": num, "invoiced_at": _now(),
                "invoiced_by": user.get("email"),
            }},
        )
        invoice.pop("_id", None)
        created.append(invoice)
    return {"ok": True, "invoices": created, "count": len(created)}


@api.get("/me/invoices/from-interventions", tags=["Portail Client"])
async def me_list_intervention_invoices(
    user: dict = Depends(get_current_user),
    tenant_id: Optional[str] = None,
    limit: int = 500,
):
    """Liste des factures interventions (admin/sup voient tout, client voit
    uniquement les siennes via tenant_id résolu)."""
    role = (user.get("role") or "").lower()
    q: Dict[str, Any] = {}
    if role in ("admin", "superviseur"):
        if tenant_id:
            q["tenant_id"] = tenant_id
    else:
        q["tenant_id"] = user.get("parent_client_id") or user["id"]
    items = await db.interventions_invoices.find(q, {"_id": 0}).sort("created_at", -1).limit(min(limit, 2000)).to_list(min(limit, 2000))
    # Iter43-fix6 — Enrichit chaque facture avec days_overdue (positif = en retard)
    for inv in items:
        _enrich_invoice_payment(inv)
    return items


def _enrich_invoice_payment(inv: Dict[str, Any]) -> None:
    """Iter43-fix6 — Calcule en place `days_overdue` et `payment_status` :
    - payment_status: 'unpaid' | 'paid' | 'cancelled'
    - days_overdue: int (jours écoulés depuis l'échéance ; 0 si pas encore en retard)
                    None si la facture n'a pas encore été déposée OU si payée/annulée.
    """
    if inv.get("status") == "cancelled":
        inv["payment_status"] = "cancelled"
        inv["days_overdue"] = None
        return
    if inv.get("paid_at"):
        inv["payment_status"] = "paid"
        inv["days_overdue"] = None
        return
    inv["payment_status"] = "unpaid"
    dep = inv.get("deposited_at")
    due_days = int(inv.get("due_days") or 30)
    if not dep:
        inv["days_overdue"] = None
        return
    try:
        dt = datetime.fromisoformat(str(dep).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        inv["days_overdue"] = None
        return
    now = datetime.now(timezone.utc)
    diff_days = (now - dt).days - due_days
    inv["days_overdue"] = max(0, diff_days)


class InvoicePaymentUpdate(BaseModel):
    deposited_at: Optional[str] = None      # ISO datetime ou null pour effacer
    paid_at: Optional[str] = None           # ISO datetime ou null
    due_days: Optional[int] = None          # délai d'échéance (jours)
    clear_deposited_at: bool = False        # True pour reset deposited_at à None
    clear_paid_at: bool = False             # True pour reset paid_at à None
    # Lot 57.8 — Mode de règlement (ex. « PISPI ») et référence bancaire de l'opération
    mode_reglement: Optional[str] = None
    reference_bancaire: Optional[str] = None


@api.put("/admin/invoices/from-interventions/{inv_id}", tags=["Admin"])
async def admin_update_intervention_invoice_payment(
    inv_id: str,
    payload: InvoicePaymentUpdate,
    _: dict = Depends(get_admin_or_supervisor),
):
    """Iter43-fix6 — Renseigne la date/heure de dépôt OU de paiement d'une
    facture. Permet de calculer le retard de règlement.

    Règles :
    - `deposited_at` accepte une string ISO (validée) ; passer `clear_deposited_at=True` pour reset.
    - `paid_at` accepte une string ISO ; passer `clear_paid_at=True` pour reset.
    - `due_days` permet de surcharger le délai (par défaut 30).
    """
    inv = await db.interventions_invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Facture introuvable")

    update: Dict[str, Any] = {}
    unset: Dict[str, str] = {}

    if payload.clear_deposited_at:
        unset["deposited_at"] = ""
    elif payload.deposited_at is not None:
        try:
            datetime.fromisoformat(payload.deposited_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="deposited_at: format ISO invalide")
        update["deposited_at"] = payload.deposited_at

    if payload.clear_paid_at:
        unset["paid_at"] = ""
    elif payload.paid_at is not None:
        try:
            datetime.fromisoformat(payload.paid_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="paid_at: format ISO invalide")
        update["paid_at"] = payload.paid_at

    # Lot 57.8 — Règlement PI-SPI : référence bancaire obligatoire, mode et référence gardés
    # sur la facture, et encaissement tracé dans pispi_transactions (rapproché).
    mode = (payload.mode_reglement or "").strip().upper()
    reglement_pispi = bool(mode == "PISPI" and update.get("paid_at"))
    if reglement_pispi:
        if not (payload.reference_bancaire or "").strip():
            raise HTTPException(status_code=400, detail="Référence bancaire PI-SPI obligatoire")
        update["paid_mode"] = "PISPI"
        update["paid_reference"] = payload.reference_bancaire.strip()
    elif mode and update.get("paid_at"):
        update["paid_mode"] = mode[:30]
        if (payload.reference_bancaire or "").strip():
            update["paid_reference"] = payload.reference_bancaire.strip()[:120]
    if payload.clear_paid_at:
        unset["paid_mode"] = ""
        unset["paid_reference"] = ""

    if payload.due_days is not None:
        if payload.due_days < 0 or payload.due_days > 365:
            raise HTTPException(status_code=400, detail="due_days doit être entre 0 et 365")
        update["due_days"] = int(payload.due_days)

    if not update and not unset:
        raise HTTPException(status_code=400, detail="Aucune modification fournie")

    mongo_update: Dict[str, Any] = {"$set": {**update, "updated_at": _now()}}
    if unset:
        mongo_update["$unset"] = unset
    await db.interventions_invoices.update_one({"id": inv_id}, mongo_update)
    if reglement_pispi:
        try:
            from routes.pispi import enregistrer_transaction as _pispi_transaction
            await _pispi_transaction(
                reference=inv.get("invoice_number") or "", montant=float(inv.get("total_xof") or 0),
                statut="rapproche", source="manuel", reference_bancaire=update["paid_reference"],
                document={"type": "intervention", "id": inv_id, "numero": inv.get("invoice_number")},
                saisi_par=_.get("email"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pispi] transaction non enregistrée : %s", exc)
    fresh = await db.interventions_invoices.find_one({"id": inv_id}, {"_id": 0})
    if fresh:
        _enrich_invoice_payment(fresh)
    return {"ok": True, "invoice": fresh}


@api.get("/me/invoices/from-interventions/{inv_id}/pdf", tags=["Portail Client"])
async def me_intervention_invoice_pdf(inv_id: str, user: dict = Depends(get_current_user)):
    """PDF de la facture (admin/sup OU le tenant propriétaire)."""
    inv = await db.interventions_invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    role = (user.get("role") or "").lower()
    if role not in ("admin", "superviseur"):
        user_tid = user.get("parent_client_id") or user["id"]
        if inv.get("tenant_id") != user_tid:
            raise HTTPException(status_code=403, detail="Accès refusé")

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    import io as _io
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=28, bottomMargin=28, leftMargin=28, rightMargin=28, title=f"Facture {inv['invoice_number']}")
    styles = getSampleStyleSheet()
    fmt_xof = lambda n: f"{int(n):,}".replace(",", " ")
    fmt_date = lambda iso: (datetime.fromisoformat(iso[:10]).strftime("%d/%m/%Y") if iso else "")

    created_dt = inv.get("created_at", "")[:16].replace("T", " ")
    deposited_dt = (inv.get("deposited_at") or "")[:16].replace("T", " ")
    paid_dt = (inv.get("paid_at") or "")[:16].replace("T", " ")
    due_days = int(inv.get("due_days") or 30)
    story = [
        Paragraph("<b>SAWALI Smart Systems</b>", styles["Title"]),
        Paragraph(f"<b>FACTURE {inv['invoice_number']}</b>", styles["Heading2"]),
        Paragraph(f"Émise le {created_dt}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph(f"<b>Client :</b> {inv.get('tenant_name') or '—'}", styles["Normal"]),
        Paragraph(f"<b>Motif :</b> {inv.get('motif', '')}", styles["Normal"]),
        Paragraph(f"<b>Taux horaire appliqué :</b> {fmt_xof(inv.get('hourly_rate_xof', 0))} XOF/h", styles["Normal"]),
        Paragraph(
            f"<b>Date/heure de dépôt :</b> {deposited_dt or '<i>non renseignée</i>'} "
            f"· <b>Échéance :</b> {due_days} jours après dépôt",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    data: List[List[str]] = [["#", "Date", "N° Intervention", "Intitulé", "Technicien", "Durée (h)", "Sous-total (XOF)"]]
    for idx, l in enumerate(inv.get("lines", []), start=1):
        data.append([
            str(idx),
            fmt_date(l.get("intervention_date")),
            l.get("intervention_number", "—"),
            (l.get("title") or "")[:48],
            (l.get("technician") or "—")[:24],
            f"{float(l.get('duration_hours') or 0):.2f}",
            fmt_xof(l.get("subtotal_xof", 0)),
        ])
    data.append(["", "", "", "", "", "TOTAL", fmt_xof(inv.get("total_xof", 0))])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E90FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (5, 1), (6, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E0F2FE")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"<i>Document généré par SAWALI Smart Systems · Total à régler : <b>{fmt_xof(inv.get('total_xof', 0))} XOF</b></i>",
        styles["Normal"],
    ))
    if inv.get("status") == "cancelled":
        story.append(Spacer(1, 6))
        story.append(Paragraph("<font color='red'><b>FACTURE ANNULÉE</b></font>", styles["Normal"]))
    elif paid_dt:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<font color='green'><b>PAYÉE le {paid_dt}</b></font>", styles["Normal"]))
    else:
        # Lot 57.8 — Bloc « Payer par PI-SPI » (QR de la banque de SAWALI, adresse de paiement,
        # montant restant dû, référence = n° de facture) si l'encaissement PI-SPI est actif.
        try:
            from routes.pispi import bloc_facture_intervention, flowables_pdf
            story.extend(flowables_pdf(await bloc_facture_intervention(inv)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pispi] bloc non ajouté à la facture %s : %s", inv.get("invoice_number"), exc)
        # Calcule retard si dépôt renseigné
        _enrich_invoice_payment(inv)
        od = inv.get("days_overdue")
        if isinstance(od, int) and od > 0:
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                f"<font color='red'><b>EN RETARD DE {od} JOUR(S)</b></font>",
                styles["Normal"],
            ))
    # Iter43-fix24az-l retest — Offload reportlab doc.build to thread pool
    # to avoid blocking uvicorn's single-worker event loop (CF 520 mitigation).
    await asyncio.to_thread(doc.build, story)
    body = buf.getvalue()
    fname = f"{inv['invoice_number']}.pdf"
    return Response(content=body, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})





@api.get("/me/users", tags=["Portail Client"])
async def me_users(user: dict = Depends(get_current_user)):
    items = await db.tracked_users.find({"client_id": user["id"]}, {"_id": 0}).to_list(2000)
    return items


@api.get("/me/clients", tags=["Portail Client"])
async def me_clients_light(user: dict = Depends(get_current_user)):
    """Liste client minimale pour utilisateurs élevés (utilisée dans les formulaires suivis/intervention).
    Non-elevated users only see their own client record."""
    if _is_elevated_creator(user):
        cursor = db.users.find({"role": {"$in": ["client", "superviseur"]}}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "client_code": 1})
        items = await cursor.to_list(5000)
    else:
        effective_id = user.get("parent_client_id") or user["id"]
        u = await db.users.find_one({"id": effective_id}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "client_code": 1})
        items = [u] if u else []
    return items
