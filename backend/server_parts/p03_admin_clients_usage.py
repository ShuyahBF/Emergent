# server_parts/p03_admin_clients_usage.py — Portail superviseur, Admin → Clients, fonctionnalités SMART Communications, tableau d'usage, activité des utilisateurs.
# Morceau de l'ancien server.py (lignes 3964 à 5227), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# PORTAIL SUPERVISEUR (Client Primaire) — gère les comptes "Admin client"
# ====================================================================
@api.get("/me/admin-clients", tags=["Portail Client"])
async def supervisor_list_admin_clients(user: dict = Depends(get_current_supervisor)):
    """Le client Primaire (Superviseur) voit tous les autres clients ayant le rôle 'admin'.
    Note : les comptes 'admin' ici désignent des clients promus admin, pas l'admin SAWALI."""
    # Match all users with role=admin OR role=client (so superviseur can manage every account
    # except SAWALI's own super-admin marked specifically). For now we expose all role==admin
    # client-promoted accounts.
    users = await db.users.find(
        {"role": "admin", "id": {"$ne": user["id"]}},
        {"_id": 0, "password_hash": 0},
    ).to_list(2000)
    return users


@api.put("/me/admin-clients/{target_id}", tags=["Portail Client"])
async def supervisor_update_admin_client(
    target_id: str,
    payload: UserUpdateAdmin,
    user: dict = Depends(get_current_supervisor),
):
    target = await db.users.find_one({"id": target_id}, {"_id": 0})
    if not target or target.get("role") != "admin":
        raise HTTPException(status_code=404, detail="Compte admin introuvable")
    update = {k: v for k, v in payload.model_dump().items() if v is not None and k != "password"}
    if "client_code" in update:
        update["client_code"] = (update["client_code"] or "").strip().upper() or None
    # Superviseur cannot self-promote/demote: ignore is_primary_client/role tampering
    update.pop("is_primary_client", None)
    update.pop("role", None)
    if payload.password:
        update["password_hash"] = hash_password(payload.password)
    update["updated_at"] = _now()
    await db.users.update_one({"id": target_id}, {"$set": update})
    return {"ok": True}


# ====================================================================
# ADMIN - Clients
# ====================================================================
@api.get("/me/access-clients-list", tags=["Portail Client"])
async def me_access_clients_list(user: dict = Depends(get_current_user)):
    """2026-02 fork (bug fix) — Liste minimale de clients/tenants pour peupler
    le multi-select `access_client_ids` (Documents / Formations / Formulaires).

    Autorisé à :
      - `role in (admin, superviseur, moderateur)`
      - OU `tracked_role in ELEVATED_TRACKED_ROLES` (Administrateur / Superviseur / Moderation)

    Cela évite le 403 silencieux subi par le compte `support@` en production
    (tracked-Administrateur → sidebar admin OK mais `/admin/clients` refusait).
    """
    # Lot 25 — Rôle modérateur accepté sous ses deux orthographes (moderateur / moderator).
    role_ok = user.get("role") in ("admin", "superviseur", "moderateur", "moderator")
    tracked_ok = user.get("tracked_role") in ELEVATED_TRACKED_ROLES
    if not (role_ok or tracked_ok):
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs / superviseurs / modérateurs")
    # Return the same shape /admin/clients uses so the FE can swap without changes.
    items = await db.users.find(
        # Lot 25 — Les deux orthographes du rôle modérateur sont listées.
        {"role": {"$in": ["client", "superviseur", "admin", "moderateur", "moderator"]},
         "email": {"$nin": [SUPER_ADMIN_EMAIL]}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1, "role": 1},
    ).sort("full_name", 1).to_list(1000)
    return items


@api.get("/admin/clients", tags=["Admin"])
async def admin_list_clients(
    include_roles: Optional[str] = None,
    source: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    _: dict = Depends(get_current_admin),
):
    """List all users that should be visible in the Admin → Clients module.

    Iter34p — Default scope widened to include `admin` (client roots) and
    `moderateur` so the admin can see and manage every account. The
    SAWALI super-admin (admin@sawalismartsystems.com) is always excluded
    because the platform itself owns this row.

    Optional query params:
      - ``include_roles`` (csv) — override the default scope
      - ``source`` (str)         — filter by users.source (e.g. ``wa_otp_login``)
      - ``sort_by`` (str)        — ``created_at`` | ``last_login_at`` | ``full_name``
      - ``sort_order`` (str)     — ``asc`` (default) | ``desc``
    """
    if include_roles:
        roles = [r.strip() for r in include_roles.split(",") if r.strip()]
    else:
        # Iter42c (2026-02) — Inclut tous les rôles métier (pharmacien, regulateur,
        # medecin, editeur_vidal) pour éviter qu'un client ne disparaisse de la
        # liste après changement de rôle. La pill "Autres rôles" côté UI permet
        # de filtrer si nécessaire.
        # Lot 25 — « moderator » ajouté : même rôle que « moderateur », autre orthographe.
        roles = [
            "client", "superviseur", "admin", "moderateur", "moderator",
            "regulateur", "pharmacien", "medecin", "editeur_vidal",
        ]
    query: Dict[str, Any] = {
        "role": {"$in": roles},
        "email": {"$nin": ["admin@sawalismartsystems.com"]},
    }
    if source:
        query["source"] = source
    cursor = db.users.find(query, {"_id": 0, "password_hash": 0})
    # Iter38r-fix9v — Sorting (whitelist to prevent injection)
    sort_field = sort_by if sort_by in ("created_at", "last_login_at", "full_name") else None
    if sort_field:
        direction = -1 if (sort_order or "").lower() == "desc" else 1
        cursor = cursor.sort(sort_field, direction)
    users = await cursor.to_list(2000)
    return users


@api.post("/admin/clients", tags=["Admin"])
async def admin_create_client(payload: UserCreateAdmin, _: dict = Depends(get_current_admin)):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Cet email est déjà utilisé")
    # iter32 — Resolve canonical-link hint. The frontend may pass
    # `link_to_client_id` after the admin accepts a "company already exists"
    # suggestion. When set, we mirror parent_client_id + client_id so the new
    # user inherits the existing client's scope (visible contacts, RGPD flags,
    # features, billing). Without this, every new admin created with the same
    # company name silently becomes a separate root → exactly the bug iter30
    # exposed.
    parent_client_id: Optional[str] = None
    mirrored_client_id: Optional[str] = None
    if payload.link_to_client_id:
        canon = await db.users.find_one(
            {"id": payload.link_to_client_id},
            {"_id": 0, "id": 1, "company": 1, "logo_url": 1},
        )
        if not canon:
            raise HTTPException(status_code=404, detail="Client canonique introuvable")
        parent_client_id = canon["id"]
        mirrored_client_id = canon["id"]
    doc = {
        "id": _uuid(),
        "email": payload.email.lower(),
        "full_name": payload.full_name,
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "phone": payload.phone,
        "company": payload.company,
        "client_code": (payload.client_code or "").strip().upper() or None,
        "category_slug": payload.category_slug,
        "country": payload.country,
        "city": payload.city,
        "logo_url": payload.logo_url,
        "account_status": payload.account_status,
        "is_primary_client": False,
        "parent_client_id": parent_client_id,
        "client_id": mirrored_client_id,
        # Iter35h — demo role: persist quota + expiry, default 14 days if unset
        "demo_expires_at": (
            payload.demo_expires_at
            or ((datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
                if payload.role == "demo" else None)
        ),
        "demo_quotas": payload.demo_quotas or None,
        "demo_usage": {} if payload.role == "demo" else None,
        # Iter43-fix24az-f — Business type (fabricant → limited sidebar)
        "business_type": (payload.business_type or "").strip().lower() or None,
        # 2026-02 fork iter103 — Contract tracking (optional at creation).
        "contract_number": (payload.contract_number or "").strip() or None,
        "contract_signed_at": (payload.contract_signed_at or "").strip() or None,
        "contract_amount": payload.contract_amount if payload.contract_amount is not None else None,
        "contract_currency": (payload.contract_currency or "").strip().upper() or None,
        "last_payment_at": (payload.last_payment_at or "").strip() or None,
        # 2026-02 fork iter104 — Overdue threshold + payment template.
        "contract_overdue_days": payload.contract_overdue_days if payload.contract_overdue_days is not None else None,
        "payment_confirmation_template": (payload.payment_confirmation_template or "").strip() or None,
        # 2026-02 fork iter108 — S158 (Recurring billing) + S159 (Auto-suspend).
        "contract_billing_period": (payload.contract_billing_period or "").strip().lower() or None,
        "auto_suspend_after_overdue_days": payload.auto_suspend_after_overdue_days if payload.auto_suspend_after_overdue_days is not None else None,
        # Lot Liluvine (2026-09) — accès Ouvert/Restreint pour ce contrat.
        "contract_access_mode": (payload.contract_access_mode or "").strip().lower() or None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.users.insert_one(doc.copy())
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    # Fire automation: client.created
    try:
        asyncio.create_task(_emit_event("client.created", {
            "client_id": doc["id"],
            "phone": doc.get("phone"),
            "extra_ctx": {},
        }))
    except Exception:
        pass
    # Iter38r-fix9w — Voice notification (the rule lives under the parent tenant)
    parent_tenant = parent_client_id or doc["id"]
    await _voice_notify(parent_tenant, "new_client_signup", {
        "full_name": doc.get("full_name") or "",
        "company": doc.get("company") or "",
        "email": doc.get("email") or "",
    })
    return doc


@api.get("/admin/clients/{client_id}", tags=["Admin"])
async def admin_get_client(client_id: str, _: dict = Depends(get_current_admin)):
    u = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return u


# ============================================================
# Per-client SMART Communications feature flags
# Stored on the client doc as `features` dict and inherited by every
# tracked user belonging to that client (resolved live in /me/features).
# Default = all disabled so a brand-new client can't unintentionally
# consume paid services until the admin enables them.
# ============================================================
DEFAULT_CLIENT_FEATURES = {
    "whatsapp": False,
    "sms": False,
    "ai": False,
    "payments": False,
    "webhook_returns": False,  # Show outbound-webhook execution result modals on POST/PUT/DELETE
    # RGPD anonymization toggles — when ON, the corresponding field is masked
    # in API responses for users whose role is NOT one of: admin, superviseur,
    # moderateur. Inherited automatically by tracked users of this client.
    "anon_name": False,
    "anon_company": False,  # split out from anon_name so admin can mask the
                              # name without masking the company (and vice-versa)
    "anon_email": False,
    "anon_phone": False,
    "anon_whatsapp": False,
    # Iter34u — Content-level restrictions: when ON, each resource of the
    # given kind is visible ONLY to its creator (created_by_id == viewer.id)
    # plus privileged roles (admin/superviseur/moderateur). Listing endpoints
    # filter them out from the response; detail endpoints return 403.
    "anon_rapports": False,        # restricts reports (kind=rapport)
    "anon_suivis": False,          # restricts follow-ups (kind=suivi)
    "anon_communications": False,  # restricts SMS, WhatsApp & payment_links
    # Allow tracked users to enable the WhatsApp inbound sound alert. When OFF,
    # the sound toggle is hidden in their portal sidebar.
    "wa_sound_alerts": True,
    # Iter36k — Chat interne temps réel entre les utilisateurs suivis d'un même
    # client. Quand activé, tous les "suiveurs" (admin + tracked_users + role
    # client) peuvent ouvrir un panneau de discussion 1-à-1 et un fil collectif
    # (#general) propre à ce client. Hérité par tous les utilisateurs suivis.
    "internal_chat": False,
    # Iter38g — Meta integration toggles (Pages, Messenger, Ads).
    # When OFF (default), the integration code paths are gated and the UI hides
    # the related modules. Activation requires the admin to first complete the
    # Meta App connection in Admin Settings (App ID + secret + access tokens).
    "meta_pages": False,        # Facebook Pages management (publish posts, comments)
    "meta_messenger": False,    # Messenger inbox unified with WhatsApp inbox
    "meta_ads": False,          # Meta Ads Manager — campaign creation & monitoring
    # Iter38o — AI media generation (Nano Banana images, Sora 2 videos).
    # When OFF, calls to /api/me/ai/generate-image|edit-image|generate-video
    # are rejected with 403. Default OFF (paid LLM credits).
    "ai_image_gen": False,
    "ai_video_gen": False,
    # Iter38r-fix7 — Liluvine PRO assistant interne (Claude Sonnet)
    "ai_liluvine_pro": False,
    # Iter38r-fix9o (Item 2) — Per-client OCR control. Cost and monthly cap
    # are also configurable per-tenant (defaults 0 = inherit global).
    "kb_ocr_enabled": True,
    "kb_ocr_xof_per_page": 0,
    "kb_ocr_xof_monthly_cap": 0,
    "kb_ocr_pdf_max_pages": 0,
    # Iter38r-fix9p — Voice generation (ElevenLabs)
    "ai_voice_gen": False,
    # Iter38r-fix9o (Item 6) — Floating "Open intervention ticket" bubble.
    # Visible only when ON (default OFF — admin opts in).
    "tickets_bubble": False,
    # Iter41 Phase 2 (2026-02) — VIDAL France module per-tenant gating.
    # When OFF, /portal/vidal is hidden + VIDAL endpoints reject the user with 403.
    "vidal_enabled": False,
    # "inherit" = use the global vidal_mode from AdminSettings.
    # "test"|"production" = override globally — useful when a tenant is paying
    # for prod VIDAL while the platform default stays in test.
    "vidal_mode": "inherit",
}

# Per-client list of authorized PawaPay MNO codes (ORANGE, MOOV, TELECEL).
# Stored alongside features on the client doc.
DEFAULT_CLIENT_PAWAPAY_MNOS: List[str] = ["ORANGE", "MOOV", "TELECEL"]


def _normalize_pawapay_mnos(raw: Optional[Any]) -> List[str]:
    if not isinstance(raw, list):
        return list(DEFAULT_CLIENT_PAWAPAY_MNOS)
    out = []
    for x in raw:
        v = str(x).upper().strip()
        if v in DEFAULT_CLIENT_PAWAPAY_MNOS and v not in out:
            out.append(v)
    return out


def _normalize_features(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(DEFAULT_CLIENT_FEATURES)
    # Iter38r-fix9p — Numeric/typed fields that must NOT be coerced to bool.
    NUMERIC_FIELDS = {"kb_ocr_xof_per_page", "kb_ocr_xof_monthly_cap", "kb_ocr_pdf_max_pages"}
    # Iter43-fix24af (2026-06-17) — String enum fields that must NOT be coerced
    # to bool. Without this, `vidal_mode="inherit"` would degrade to `True` on
    # every save, breaking the PUT /admin/clients/{id}/features endpoint
    # (Pydantic rejected `vidal_mode: True` because the model expects `str`).
    STRING_FIELDS = {"vidal_mode"}
    if isinstance(raw, dict):
        for k, default in DEFAULT_CLIENT_FEATURES.items():
            v = raw.get(k, default)
            if k in NUMERIC_FIELDS:
                # Keep int (None preserved → fallback to global later)
                try:
                    out[k] = int(v) if v not in (None, "", False) else default
                except (TypeError, ValueError):
                    out[k] = default
            elif k in STRING_FIELDS:
                # Preserve string enum; coerce stray legacy bool → default.
                if isinstance(v, str) and v:
                    out[k] = v.lower().strip()
                else:
                    out[k] = default
            else:
                out[k] = bool(v)
    return out


# ---------- RGPD anonymization (per-client toggles inherited by tracked users) ----------
# Lot 25 — Rôle modérateur accepté sous ses deux orthographes (moderateur / moderator).
RGPD_PRIVILEGED_ROLES = {"admin", "superviseur", "moderateur", "moderator"}


def _anon_name(name: Optional[str]) -> Optional[str]:
    """Anonymize a person/company name as `J*** D***`. Each whitespace-token
    keeps its first character followed by 3 stars. Single-token names get
    the same treatment. Empty input is returned as-is."""
    if not name:
        return name
    parts = (name or "").strip().split()
    if not parts:
        return name
    return " ".join((p[0] + "***") if p else "" for p in parts)


def _anon_email(email: Optional[str]) -> Optional[str]:
    """Anonymize an email as `j***@gmail.com` (1st letter + stars + domain)."""
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def _anon_phone(phone: Optional[str]) -> Optional[str]:
    """Anonymize a phone as `+225 07 ** ** ** 89`. Keeps non-digit prefixes
    (e.g. country code), masks the middle, keeps the last 2 digits."""
    if not phone:
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 4:
        return "***"
    keep_last = digits[-2:]
    masked_middle = "*" * max(0, len(digits) - 4)
    keep_first = digits[:2]
    return f"+{keep_first} {masked_middle[:2]} {masked_middle[2:4]} {masked_middle[4:6]} {keep_last}".replace("  ", " ").strip()


async def _resolve_real_phone(contact_id: Optional[str], field: str, fallback: str = "") -> str:
    """Iter34h — RGPD anonymization preserves real phone numbers in the DB but
    masks them in API responses. When the user clicks "Send SMS/WhatsApp" the
    frontend ships a masked value back. This helper restores the REAL phone
    number from the directory_contacts row, bypassing the anonymization.

    Args:
        contact_id: Optional contact UUID. When provided, fetch the row and
            return its `phone` (for SMS) or `whatsapp` (for WhatsApp).
        field: "phone" or "whatsapp"
        fallback: The masked/raw value submitted by the frontend. Used when
            contact_id is missing or the row has no value in that field.

    Returns: the real phone number ready to send to SMS/WA providers.
    """
    if not contact_id:
        return (fallback or "").strip()
    try:
        row = await db.directory_contacts.find_one(
            {"id": contact_id},
            {"_id": 0, "phone": 1, "whatsapp": 1},
        )
        if row:
            real = (row.get(field) or "").strip()
            if real:
                return real
    except Exception:
        pass
    return (fallback or "").strip()




async def _resolve_content_restrictions(viewer: dict) -> Dict[str, bool]:
    """Iter34u — Return the anon_rapports / anon_suivis / anon_communications
    flags that apply to the given viewer. Privileged roles always see
    everything (flags reported as False). Other users inherit the parent
    client's configuration (parent_client_id priority over client_id)."""
    role = (viewer.get("role") or "").lower()
    if role in RGPD_PRIVILEGED_ROLES:
        return {"anon_rapports": False, "anon_suivis": False, "anon_communications": False}
    parent_id = viewer.get("parent_client_id") or viewer.get("client_id") or viewer.get("id")
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
    feats = _normalize_features((parent or {}).get("features"))
    return {
        "anon_rapports": bool(feats.get("anon_rapports")),
        "anon_suivis": bool(feats.get("anon_suivis")),
        "anon_communications": bool(feats.get("anon_communications")),
    }


async def _resolve_anon_flags(viewer: dict) -> Dict[str, bool]:
    """Return the anon_* flags that apply to the current viewer.
    Privileged roles (admin/superviseur/moderateur) get all flags as False so
    they always see the data in clear. Other users inherit the parent client's
    flags — false (no anonymization) by default.

    Iter34p — Resolution priority for `parent_id`:
      1. `parent_client_id` (the explicit canonical pointer set by iter28/m)
      2. `client_id` (legacy field, may equal self for root users)
      3. `id` (last resort fallback)
    Previously we only checked `client_id or id`, so a tracked/child user
    whose `client_id` happened to be null or self-id would skip the parent's
    RGPD settings entirely.
    """
    role = (viewer.get("role") or "").lower()
    if role in RGPD_PRIVILEGED_ROLES:
        return {"anon_name": False, "anon_company": False, "anon_email": False, "anon_phone": False, "anon_whatsapp": False}
    parent_id = viewer.get("parent_client_id") or viewer.get("client_id") or viewer.get("id")
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "features": 1})
    feats = _normalize_features((parent or {}).get("features"))
    return {
        "anon_name": bool(feats.get("anon_name")),
        "anon_company": bool(feats.get("anon_company")),
        "anon_email": bool(feats.get("anon_email")),
        "anon_phone": bool(feats.get("anon_phone")),
        "anon_whatsapp": bool(feats.get("anon_whatsapp")),
    }


def _apply_anon_to_contact(c: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Mutate a copy of a contact dict to mask sensitive fields per flags.
    The `contact_code` field is NEVER masked — it's the stable identifier
    used to reference the contact even when other fields are anonymized."""
    out = dict(c)
    if flags.get("anon_name"):
        out["name"] = _anon_name(out.get("name")) or out.get("name")
    if flags.get("anon_company"):
        out["company"] = _anon_name(out.get("company")) or out.get("company")
    if flags.get("anon_email"):
        out["email"] = _anon_email(out.get("email")) or out.get("email")
    if flags.get("anon_phone"):
        out["phone"] = _anon_phone(out.get("phone")) or out.get("phone")
    if flags.get("anon_whatsapp"):
        out["whatsapp"] = _anon_phone(out.get("whatsapp")) or out.get("whatsapp")
    return out


def _apply_anon_to_appointment(a: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Anonymize the customer fields of an appointment (RDV)."""
    out = dict(a)
    if flags.get("anon_name"):
        out["name"] = _anon_name(out.get("name")) or out.get("name")
    if flags.get("anon_company"):
        out["company"] = _anon_name(out.get("company")) or out.get("company")
    if flags.get("anon_email"):
        out["email"] = _anon_email(out.get("email")) or out.get("email")
    if flags.get("anon_phone"):
        out["phone"] = _anon_phone(out.get("phone")) or out.get("phone")
    return out


def _apply_anon_to_intervention(i: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Anonymize the technician name on an intervention card."""
    out = dict(i)
    if flags.get("anon_name"):
        out["technician"] = _anon_name(out.get("technician")) or out.get("technician")
    return out


def _apply_anon_to_document(d: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Anonymize uploader-related fields on a document."""
    out = dict(d)
    if flags.get("anon_name"):
        out["uploaded_by_name"] = _anon_name(out.get("uploaded_by_name")) or out.get("uploaded_by_name")
        out["client_name"] = _anon_name(out.get("client_name")) or out.get("client_name")
    if flags.get("anon_email"):
        out["uploaded_by_email"] = _anon_email(out.get("uploaded_by_email")) or out.get("uploaded_by_email")
    return out


def _apply_anon_to_access_log(log: Dict[str, Any], flags: Dict[str, bool]) -> Dict[str, Any]:
    """Anonymize identity fields on an access-log entry."""
    out = dict(log)
    if flags.get("anon_name"):
        out["user_name"] = _anon_name(out.get("user_name")) or out.get("user_name")
    if flags.get("anon_email"):
        out["user_email"] = _anon_email(out.get("user_email")) or out.get("user_email")
    return out


async def _maybe_anon_list(viewer: dict, items: List[Dict[str, Any]], applier) -> List[Dict[str, Any]]:
    """Generic helper: applies the chosen `applier` to each item only if at
    least one anon flag is True for the viewer. No-op otherwise."""
    flags = await _resolve_anon_flags(viewer)
    if not any(flags.values()):
        return items
    return [applier(x, flags) for x in items]


class ClientFeaturesUpdate(BaseModel):
    whatsapp: Optional[bool] = None
    sms: Optional[bool] = None
    ai: Optional[bool] = None
    payments: Optional[bool] = None
    webhook_returns: Optional[bool] = None
    anon_name: Optional[bool] = None
    anon_company: Optional[bool] = None
    anon_email: Optional[bool] = None
    anon_phone: Optional[bool] = None
    anon_whatsapp: Optional[bool] = None
    anon_rapports: Optional[bool] = None
    anon_suivis: Optional[bool] = None
    anon_communications: Optional[bool] = None
    wa_sound_alerts: Optional[bool] = None
    internal_chat: Optional[bool] = None  # Iter36k — chat interne temps réel
    # Iter38g — Meta integration
    meta_pages: Optional[bool] = None
    meta_messenger: Optional[bool] = None
    meta_ads: Optional[bool] = None
    # Iter38o — AI media generation toggles
    ai_image_gen: Optional[bool] = None
    ai_video_gen: Optional[bool] = None
    # Iter38r-fix8c — Liluvine PRO assistant interne (Claude Sonnet).
    # Bug correctif : ce champ était absent du modèle Pydantic, du coup
    # quand le toggle "Liluvine PRO" était activé dans SMART Communications,
    # Pydantic le supprimait silencieusement avant l'enregistrement en base.
    ai_liluvine_pro: Optional[bool] = None
    # Iter38r-fix9p — Voice generation (ElevenLabs cloning + TTS) toggle
    ai_voice_gen: Optional[bool] = None
    # Iter38r-fix9p — OCR (PDF/image) toggle in Liluvine KB
    kb_ocr_enabled: Optional[bool] = None
    # Iter38r-fix9p (correction) — OCR pricing & quotas per tenant.
    # Read by routes/liluvine_kb.py with fallback on settings.global.
    kb_ocr_xof_per_page: Optional[int] = None
    kb_ocr_xof_monthly_cap: Optional[int] = None
    kb_ocr_pdf_max_pages: Optional[int] = None
    # Iter38r-fix9o (Item 6) — Floating "Open intervention ticket" bubble.
    tickets_bubble: Optional[bool] = None
    # Iter41 Phase 2 (2026-02) — VIDAL France module per-tenant gating.
    vidal_enabled: Optional[bool] = None
    vidal_mode: Optional[str] = None  # "inherit" | "test" | "production"
    pawapay_mnos: Optional[List[str]] = None  # subset of ORANGE/MOOV/TELECEL
    # Iter38r — Pre-fix MSISDN on PawaPay Payment Page (true) or let the
    # customer enter it themselves on the hosted page (false). When null,
    # the server-side default `settings.pawapay_fix_msisdn_default` applies.
    pawapay_fix_msisdn: Optional[bool] = None

    # Iter43-fix24af (2026-06-17) — Defensive coercion: legacy data in DB
    # had `vidal_mode: True` (bool) due to a bug in `_normalize_features`.
    # Old admin forms now send back that bool — instead of 422-rejecting,
    # we coerce bool → "inherit" so the save succeeds.
    @field_validator("vidal_mode", mode="before")
    @classmethod
    def _coerce_vidal_mode(cls, v):
        if isinstance(v, bool):
            return "inherit"
        if v is None:
            return None
        s = str(v).lower().strip()
        return s if s in ("inherit", "test", "production") else "inherit"


@api.get("/admin/clients/{client_id}/features", tags=["Admin"])
async def admin_get_client_features(client_id: str, _: dict = Depends(get_current_admin)):
    u = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "features": 1, "pawapay_mnos": 1, "pawapay_fix_msisdn": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return {
        "client": {"id": u["id"], "full_name": u.get("full_name"), "company": u.get("company")},
        "features": _normalize_features(u.get("features")),
        "pawapay_mnos": _normalize_pawapay_mnos(u.get("pawapay_mnos")),
        "pawapay_fix_msisdn": u.get("pawapay_fix_msisdn"),
    }


@api.put("/admin/clients/{client_id}/features", tags=["Admin"])
async def admin_update_client_features(client_id: str, payload: ClientFeaturesUpdate, _: dict = Depends(get_current_admin)):
    u = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "features": 1, "pawapay_mnos": 1, "pawapay_fix_msisdn": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Client introuvable")
    current = _normalize_features(u.get("features"))
    update_dict = payload.model_dump(exclude_none=True)
    mnos = update_dict.pop("pawapay_mnos", None)
    fix_msisdn = update_dict.pop("pawapay_fix_msisdn", None)
    # Iter38r-fix9p — Preserve numeric OCR pricing fields (don't coerce to bool)
    NUMERIC_FIELDS = {"kb_ocr_xof_per_page", "kb_ocr_xof_monthly_cap", "kb_ocr_pdf_max_pages"}
    # Iter41 Phase 2 — `vidal_mode` is a string enum, not a bool.
    STRING_FIELDS = {"vidal_mode"}
    for k, v in update_dict.items():
        if k in NUMERIC_FIELDS:
            try:
                current[k] = int(v) if v not in (None, "") else 0
            except (TypeError, ValueError):
                current[k] = 0
        elif k in STRING_FIELDS:
            sv = str(v or "").lower().strip()
            if k == "vidal_mode" and sv not in ("inherit", "test", "production"):
                sv = "inherit"
            current[k] = sv
        else:
            current[k] = bool(v)
    set_doc: Dict[str, Any] = {"features": current, "features_updated_at": _now()}
    if mnos is not None:
        set_doc["pawapay_mnos"] = _normalize_pawapay_mnos(mnos)
    if fix_msisdn is not None:
        set_doc["pawapay_fix_msisdn"] = bool(fix_msisdn)
    await db.users.update_one(
        {"id": client_id},
        {"$set": set_doc},
    )
    return {
        "ok": True,
        "features": current,
        "pawapay_mnos": set_doc.get("pawapay_mnos") or _normalize_pawapay_mnos(u.get("pawapay_mnos")),
        "pawapay_fix_msisdn": set_doc.get("pawapay_fix_msisdn", u.get("pawapay_fix_msisdn")),
    }


@api.get("/admin/rgpd-preview/{client_id}", tags=["Admin"])
async def admin_rgpd_preview(client_id: str, _: dict = Depends(get_current_admin)):
    """Prévisualise ce qu'un utilisateur non-privilégié de `client_id` verrait dans son
    portal — applies the parent client's anon flags to a sample of records
    from each anonymized collection (contacts, appointments, interventions,
    documents). Admins use this to audit the RGPD setup without having to
    create a test user account.

    Returns up to 5 records per collection with both the original and the
    masked version side-by-side so the admin can verify the mapping."""
    parent = await db.users.find_one({"id": client_id}, {"_id": 0, "features": 1, "full_name": 1, "company": 1})
    if not parent:
        raise HTTPException(status_code=404, detail="Client introuvable")
    feats = _normalize_features(parent.get("features"))
    flags = {
        "anon_name": bool(feats.get("anon_name")),
        "anon_company": bool(feats.get("anon_company")),
        "anon_email": bool(feats.get("anon_email")),
        "anon_phone": bool(feats.get("anon_phone")),
        "anon_whatsapp": bool(feats.get("anon_whatsapp")),
    }

    contacts = await db.directory_contacts.find({"client_id": client_id}, {"_id": 0}).limit(5).to_list(5)
    appointments = await db.appointments.find({"client_id": client_id}, {"_id": 0}).limit(5).to_list(5)
    interventions = await db.interventions.find({"client_id": client_id}, {"_id": 0}).limit(5).to_list(5)
    documents = await db.documents.find({"client_id": client_id}, {"_id": 0}).limit(5).to_list(5)

    def _pair(items, applier):
        return [{"original": x, "masked": applier(x, flags)} for x in items]

    return {
        "client_id": client_id,
        "client_name": parent.get("full_name") or parent.get("company"),
        "flags": flags,
        "contacts": _pair(contacts, _apply_anon_to_contact),
        "appointments": _pair(appointments, _apply_anon_to_appointment),
        "interventions": _pair(interventions, _apply_anon_to_intervention),
        "documents": _pair(documents, _apply_anon_to_document),
    }



@api.get("/me/features", tags=["Portail Client"])
async def me_get_features(user: dict = Depends(get_current_user)):
    """Résout les feature flags SMART Communications pour l'utilisateur appelant.
    Admin & superviseur always have everything enabled. Tracked users inherit
    from their parent client. Plain client users read from their own doc."""
    # Iter38r-fix9k — Global tenant settings exposed via /me/features
    g = await db.settings.find_one({"_id": "global"}) or {}
    extra_flags = {
        "notes_strict_tasks_only": bool(g.get("notes_strict_tasks_only", False)),
    }
    # WhatsApp inbound notification sound (2026-02 configurable sound).
    # Exposed on the top-level payload so the frontend hook can play the
    # tenant-wide default without a separate round-trip.
    _wa_sound_meta = {
        "wa_notification_sound": g.get("wa_notification_sound") or "bip",
        "wa_notification_sound_url": g.get("wa_notification_sound_url") or None,
        "wa_notification_volume": (
            float(g["wa_notification_volume"])
            if isinstance(g.get("wa_notification_volume"), (int, float))
            else 0.4
        ),
    }
    if user.get("role") in ("admin", "superviseur"):
        return {
            "features": {**{k: True for k in DEFAULT_CLIENT_FEATURES}, **extra_flags},
            "pawapay_mnos": list(DEFAULT_CLIENT_PAWAPAY_MNOS),
            "inherited_from": None,
            **_wa_sound_meta,
        }
    parent_id = user.get("parent_client_id") or user.get("client_id") or user["id"]
    parent = await db.users.find_one({"id": parent_id}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "features": 1, "pawapay_mnos": 1})
    feats = _normalize_features((parent or {}).get("features"))
    feats.update(extra_flags)  # tenant-global override
    mnos = _normalize_pawapay_mnos((parent or {}).get("pawapay_mnos"))
    return {
        "features": feats,
        "pawapay_mnos": mnos,
        "inherited_from": {
            "id": parent_id,
            "full_name": (parent or {}).get("full_name"),
            "company": (parent or {}).get("company"),
        } if parent and parent_id != user["id"] else None,
        **_wa_sound_meta,
    }


def _check_feature(user: dict, feature: str) -> None:
    """Hook for future enforcement of per-client feature flags. Currently a
    no-op: the frontend disables the UI for unavailable features, and we keep
    this stub in place so a single line change can flip backend enforcement on.
    Admin/superviseur always bypass."""
    if user.get("role") in ("admin", "superviseur"):
        return
    # NOTE: enforcement intentionally deferred — see /me/features for the
    # resolved feature dict consumed by the UI.
    return


# ============================================================
# Admin Usage Dashboard — consolidates the paid-service consumption
# (WhatsApp / AI summaries / audio transcriptions / PawaPay) per client.
# Used by /admin/usage to support billing & heavy-user detection.
# ============================================================
@api.get("/admin/usage/summary", tags=["Admin"])
async def admin_usage_summary(days: int = 30, _: dict = Depends(get_current_admin)):
    """Aggregate usage metrics per client over the last N days.
    Returns: {period_days, totals, per_client[], daily_series[]}."""
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()

    # Clients lookup (id → {full_name, company, features, wa_unit_cost, wa_currency})
    clients_cur = db.users.find(
        {"role": {"$in": ["client", "admin", "superviseur"]}},
        {"_id": 0, "id": 1, "full_name": 1, "company": 1, "features": 1, "wa_unit_cost": 1, "wa_currency": 1},
    )
    clients = {c["id"]: c async for c in clients_cur}

    # Aggregations
    wa_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": "$client_id",
            "sent_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "inbound": {"$sum": {"$cond": [{"$eq": ["$direction", "inbound"]}, 1, 0]}},
            "total": {"$sum": 1},
        }},
    ]
    wa_agg = {doc["_id"]: doc async for doc in db.whatsapp_messages.aggregate(wa_pipeline)}

    ai_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
    ]
    ai_agg = {doc["_id"]: doc["count"] async for doc in db.ai_summaries.aggregate(ai_pipeline)}

    # SMS aggregation per client × per provider (sent_ok + sent_ko + total)
    sms_pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": {"client_id": "$client_id", "provider": "$provider"},
            "sent_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "total": {"$sum": 1},
        }},
    ]
    sms_by_client: Dict[str, Dict[str, Any]] = {}
    sms_by_provider: Dict[str, Dict[str, int]] = {}
    async for doc in db.sms_messages.aggregate(sms_pipeline):
        cid = (doc.get("_id") or {}).get("client_id")
        prov = ((doc.get("_id") or {}).get("provider") or "?").upper()
        ok = int(doc.get("sent_ok", 0))
        ko = int(doc.get("sent_ko", 0))
        tot = int(doc.get("total", 0))
        if cid:
            client_row = sms_by_client.setdefault(cid, {"sent_ok": 0, "sent_ko": 0, "total": 0, "by_provider": {}})
            client_row["sent_ok"] += ok
            client_row["sent_ko"] += ko
            client_row["total"] += tot
            pp = client_row["by_provider"].setdefault(prov, {"sent_ok": 0, "sent_ko": 0, "total": 0})
            pp["sent_ok"] += ok
            pp["sent_ko"] += ko
            pp["total"] += tot
        prov_row = sms_by_provider.setdefault(prov, {"sent_ok": 0, "sent_ko": 0, "total": 0})
        prov_row["sent_ok"] += ok
        prov_row["sent_ko"] += ko
        prov_row["total"] += tot

    # Per-client assembly
    per_client = []
    tot = {"wa_sent_ok": 0, "wa_sent_ko": 0, "wa_inbound": 0, "wa_total": 0, "wa_cost": 0.0, "ai_count": 0,
           "sms_sent_ok": 0, "sms_sent_ko": 0, "sms_total": 0, "sms_cost": 0.0}
    for cid, c in clients.items():
        wa = wa_agg.get(cid, {})
        unit_cost = float(c.get("wa_unit_cost") or 0)
        currency = c.get("wa_currency") or "XOF"
        wa_ok = int(wa.get("sent_ok", 0))
        wa_ko = int(wa.get("sent_ko", 0))
        wa_inbound = int(wa.get("inbound", 0))
        wa_total = int(wa.get("total", 0))
        wa_cost = wa_ok * unit_cost
        ai_count = int(ai_agg.get(cid, 0))
        sms_row = sms_by_client.get(cid, {"sent_ok": 0, "sent_ko": 0, "total": 0, "by_provider": {}})
        sms_unit_cost = float(c.get("sms_unit_cost") or 0)
        sms_cost = int(sms_row["sent_ok"]) * sms_unit_cost
        features = _normalize_features(c.get("features"))
        per_client.append({
            "client_id": cid,
            "full_name": c.get("full_name"),
            "company": c.get("company"),
            "features": features,
            "wa_sent_ok": wa_ok,
            "wa_sent_ko": wa_ko,
            "wa_inbound": wa_inbound,
            "wa_total": wa_total,
            "wa_unit_cost": unit_cost,
            "wa_currency": currency,
            "wa_cost": wa_cost,
            "ai_summaries": ai_count,
            "sms_sent_ok": int(sms_row["sent_ok"]),
            "sms_sent_ko": int(sms_row["sent_ko"]),
            "sms_total": int(sms_row["total"]),
            "sms_by_provider": sms_row["by_provider"],
            "sms_unit_cost": sms_unit_cost,
            "sms_cost": sms_cost,
        })
        tot["wa_sent_ok"] += wa_ok
        tot["wa_sent_ko"] += wa_ko
        tot["wa_inbound"] += wa_inbound
        tot["wa_total"] += wa_total
        tot["wa_cost"] += wa_cost
        tot["ai_count"] += ai_count
        tot["sms_sent_ok"] += int(sms_row["sent_ok"])
        tot["sms_sent_ko"] += int(sms_row["sent_ko"])
        tot["sms_total"] += int(sms_row["total"])
        tot["sms_cost"] += sms_cost
    per_client.sort(key=lambda r: r["wa_cost"] + r["sms_cost"] + r["ai_summaries"], reverse=True)

    # Daily series — stacked bar data for the 30-day chart (WA + AI + SMS)
    daily = {}
    start_day = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date()
    for i in range(days):
        d = (start_day + timedelta(days=i)).isoformat()
        daily[d] = {"day": d, "wa": 0, "ai": 0, "sms": 0}

    async for m in db.whatsapp_messages.find(
        {"created_at": {"$gte": since_iso}, "status": "sent"},
        {"_id": 0, "created_at": 1},
    ):
        day = (m.get("created_at") or "")[:10]
        if day in daily:
            daily[day]["wa"] += 1
    async for s in db.ai_summaries.find(
        {"created_at": {"$gte": since_iso}},
        {"_id": 0, "created_at": 1},
    ):
        day = (s.get("created_at") or "")[:10]
        if day in daily:
            daily[day]["ai"] += 1
    async for s in db.sms_messages.find(
        {"created_at": {"$gte": since_iso}, "status": "sent"},
        {"_id": 0, "created_at": 1},
    ):
        day = (s.get("created_at") or "")[:10]
        if day in daily:
            daily[day]["sms"] += 1

    return {
        "period_days": days,
        "totals": tot,
        "per_client": per_client,
        "sms_by_provider": sms_by_provider,
        "daily_series": sorted(daily.values(), key=lambda d: d["day"]),
        "generated_at": _now(),
    }


# Iter38r-fix9p (P1) — SMS providers detail: latency + last failure + cost.
# Complements `sms_by_provider` from /admin/usage/summary which only carries
# the counts. This adds a slow-path read on the last failure record and an
# aggregation for the average send latency.
@api.get("/admin/usage/sms-providers", tags=["Admin"])
async def admin_usage_sms_providers(days: int = 30, _: dict = Depends(get_current_admin)):
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()

    # Per-provider counts + average latency (ms between created_at and sent_at)
    pipeline = [
        {"$match": {"created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": {"$toUpper": {"$ifNull": ["$provider", "?"]}},
            "sent_ok": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
            "sent_ko": {"$sum": {"$cond": [{"$or": [{"$eq": ["$status", "failed"]}, {"$eq": ["$status", "error"]}]}, 1, 0]}},
            "total": {"$sum": 1},
            # Latency only on successfully sent messages with both timestamps
            "latency_samples": {"$push": {
                "$cond": [
                    {"$and": [{"$eq": ["$status", "sent"]}, {"$ne": ["$sent_at", None]}, {"$ne": ["$created_at", None]}]},
                    {"$subtract": [
                        {"$dateFromString": {"dateString": "$sent_at", "onError": None}},
                        {"$dateFromString": {"dateString": "$created_at", "onError": None}},
                    ]},
                    None,
                ],
            }},
        }},
    ]
    items: List[Dict[str, Any]] = []
    async for doc in db.sms_messages.aggregate(pipeline):
        prov = doc.get("_id") or "?"
        samples = [s for s in (doc.get("latency_samples") or []) if isinstance(s, (int, float))]
        avg_ms = round(sum(samples) / len(samples)) if samples else None
        # Last failure (separate query — bounded by 1)
        # Avoid regex (provider may contain `?` placeholder which breaks $regex).
        prov_clauses: List[Dict[str, Any]] = [
            {"provider": prov},
            {"provider": prov.lower()},
            {"provider": prov.capitalize()},
        ]
        last_fail = await db.sms_messages.find_one(
            {"$or": prov_clauses,
             "status": {"$in": ["failed", "error"]},
             "created_at": {"$gte": since_iso}},
            {"_id": 0, "created_at": 1, "error_message": 1, "to": 1},
            sort=[("created_at", -1)],
        )
        # Cost from global unit_cost setting per provider
        s = await db.settings.find_one({"_id": "global"}) or {}
        unit_cost_key = f"sms_unit_cost_{prov.lower()}"
        unit_cost = float(s.get(unit_cost_key) or 0.0)
        sent_ok = int(doc.get("sent_ok", 0))
        items.append({
            "provider": prov,
            "sent_ok": sent_ok,
            "sent_ko": int(doc.get("sent_ko", 0)),
            "total": int(doc.get("total", 0)),
            "avg_latency_ms": avg_ms,
            "avg_latency_human": _human_latency(avg_ms) if avg_ms is not None else None,
            "unit_cost": unit_cost,
            "estimated_cost": round(sent_ok * unit_cost, 2),
            "last_failure": last_fail,
        })
    items.sort(key=lambda x: x["total"], reverse=True)
    return {"period_days": days, "items": items, "generated_at": _now()}


def _human_latency(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    if ms < 1000:
        return f"{int(ms)} ms"
    s = ms / 1000.0
    if s < 60:
        return f"{s:.1f} s"
    m = s / 60
    return f"{m:.1f} min"


@api.get("/admin/clients/{client_id}/whatsapp-stats", tags=["Admin"])
async def admin_client_whatsapp_stats(client_id: str, _: dict = Depends(get_current_admin)):
    """WhatsApp consumption summary for a client: messages sent OK/KO,
    inbound, last activity, configured unit cost & total cost."""
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "wa_unit_cost": 1, "wa_currency": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    unit_cost = float(client.get("wa_unit_cost") or 0)
    currency = client.get("wa_currency") or "XOF"
    cur = db.whatsapp_messages.find({"client_id": client_id}, {"_id": 0})
    sent_ok = sent_ko = inbound = 0
    last_at: Optional[str] = None
    last_outbound_at: Optional[str] = None
    last_inbound_at: Optional[str] = None
    async for m in cur:
        if (m.get("direction") or "outbound") == "inbound":
            inbound += 1
            ts = m.get("received_at") or m.get("created_at")
            if ts and (not last_inbound_at or ts > last_inbound_at):
                last_inbound_at = ts
        else:
            ok = m.get("ok")
            if ok is None:
                # Legacy logs may not have ok; infer from wa_status
                ok = (m.get("wa_status") or "").lower() not in ("failed",)
            if ok:
                sent_ok += 1
            else:
                sent_ko += 1
            ts = m.get("sent_at") or m.get("created_at")
            if ts and (not last_outbound_at or ts > last_outbound_at):
                last_outbound_at = ts
        ts_any = m.get("sent_at") or m.get("received_at") or m.get("created_at")
        if ts_any and (not last_at or ts_any > last_at):
            last_at = ts_any
    billable = sent_ok  # only successful sends are billed
    total_cost = round(billable * unit_cost, 4)
    return {
        "client_id": client_id,
        "client_name": client.get("full_name"),
        "client_company": client.get("company"),
        "sent_ok": sent_ok,
        "sent_ko": sent_ko,
        "inbound": inbound,
        "billable_messages": billable,
        "unit_cost": unit_cost,
        "currency": currency,
        "total_cost": total_cost,
        "last_outbound_at": last_outbound_at,
        "last_inbound_at": last_inbound_at,
        "last_activity_at": last_at,
    }


# ============================================================
# Iter34f — User activity summary (last logins + page visits).
# Period: today | week | month | days={N}. Optional company filter to scope
# to a single client's users. Reads from db.access_logs (recorded by the SPA
# on every route change) and joins with db.users for company labels.
# ============================================================
@api.get("/admin/user-activity", tags=["Admin"])
async def admin_user_activity(
    period: str = "week",
    company: Optional[str] = None,
    limit: int = 10,
    _: dict = Depends(get_current_admin),
):
    """Renvoie :
      - last_logins[]: { user_email, user_name, role, company, last_seen_at, hits, last_page }
      - top_pages[]:   { module, page, hits, unique_users }
      - totals: { hits, unique_users, unique_companies }
    """
    period_norm = (period or "week").lower()
    now = datetime.now(timezone.utc)
    days_map = {"today": 1, "day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}
    days = days_map.get(period_norm, 7)
    if period_norm.startswith("days="):
        try:
            days = max(1, min(int(period_norm.split("=", 1)[1]), 365))
        except Exception:
            days = 7
    since = (now - timedelta(days=days)).isoformat()

    # Build the email→company mapping (case-insensitive company filter)
    user_q: Dict[str, Any] = {}
    if company:
        user_q["company"] = {"$regex": f"^{re.escape(company)}$", "$options": "i"}
    users_by_email: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(user_q, {"_id": 0, "email": 1, "full_name": 1, "company": 1, "role": 1}):
        em = (u.get("email") or "").lower()
        if em:
            users_by_email[em] = u

    log_q: Dict[str, Any] = {"created_at": {"$gte": since}}
    if company:
        if not users_by_email:
            return {"period": period_norm, "days": days, "company": company,
                    "last_logins": [], "top_pages": [],
                    "totals": {"hits": 0, "unique_users": 0, "unique_companies": 0},
                    "company_options": []}
        log_q["user_email"] = {"$in": list(users_by_email.keys())}

    user_pipeline = [
        {"$match": log_q},
        {"$group": {
            "_id": "$user_email",
            "user_name": {"$last": "$user_name"},
            "role": {"$last": "$role"},
            "last_seen_at": {"$max": "$created_at"},
            "last_page": {"$last": "$page"},
            "last_module": {"$last": "$module"},
            "hits": {"$sum": 1},
        }},
        {"$sort": {"last_seen_at": -1}},
        {"$limit": max(1, min(limit, 100))},
    ]
    last_logins: List[Dict[str, Any]] = []
    async for r in db.access_logs.aggregate(user_pipeline):
        email = (r.get("_id") or "").lower()
        u = users_by_email.get(email) if users_by_email else None
        if not u:
            u = await db.users.find_one({"email": email}, {"_id": 0, "company": 1, "full_name": 1, "role": 1}) or {}
        last_logins.append({
            "user_email": r.get("_id"),
            "user_name": r.get("user_name") or u.get("full_name"),
            "role": r.get("role") or u.get("role"),
            "company": u.get("company"),
            "last_seen_at": r.get("last_seen_at"),
            "last_page": r.get("last_page"),
            "last_module": r.get("last_module"),
            "hits": r.get("hits", 0),
        })

    page_pipeline = [
        {"$match": log_q},
        {"$group": {
            "_id": {"module": "$module", "page": "$page"},
            "hits": {"$sum": 1},
            "users": {"$addToSet": "$user_email"},
        }},
        {"$project": {
            "module": "$_id.module",
            "page": "$_id.page",
            "hits": 1,
            "unique_users": {"$size": "$users"},
        }},
        {"$sort": {"hits": -1}},
        {"$limit": max(1, min(limit, 100))},
    ]
    top_pages: List[Dict[str, Any]] = []
    async for r in db.access_logs.aggregate(page_pipeline):
        top_pages.append({
            "module": r.get("module") or "—",
            "page": r.get("page") or "—",
            "hits": r.get("hits", 0),
            "unique_users": r.get("unique_users", 0),
        })

    totals_pipeline = [
        {"$match": log_q},
        {"$group": {
            "_id": None,
            "hits": {"$sum": 1},
            "users": {"$addToSet": "$user_email"},
        }},
    ]
    totals = {"hits": 0, "unique_users": 0, "unique_companies": 0}
    async for r in db.access_logs.aggregate(totals_pipeline):
        emails = [(e or "").lower() for e in (r.get("users") or [])]
        totals["hits"] = r.get("hits", 0)
        totals["unique_users"] = len(emails)
        if emails:
            comps = await db.users.distinct(
                "company",
                {"email": {"$in": emails}, "company": {"$nin": [None, ""]}},
            )
            totals["unique_companies"] = len(comps)

    company_options = await db.users.distinct(
        "company", {"company": {"$nin": [None, ""]}, "role": {"$in": ["client", "admin", "superviseur"]}}
    )
    company_options = sorted([c for c in company_options if c])

    return {
        "period": period_norm,
        "days": days,
        "company": company,
        "since": since,
        "last_logins": last_logins,
        "top_pages": top_pages,
        "totals": totals,
        "company_options": company_options,
    }


@api.get("/admin/user-activity/heatmap", tags=["Admin"])
async def admin_user_activity_heatmap(
    period: str = "month",
    company: Optional[str] = None,
    _: dict = Depends(get_current_admin),
):
    """Renvoie une grille 7×24 des compteurs de hits (lignes = jours de semaine 0..6 Lun→Dim,
    cols = hours 0..23 UTC). Useful for identifying peak activity windows.
    Period accepts: today | week | month | quarter | year | days=N (1..365)."""
    period_norm = (period or "month").lower()
    now = datetime.now(timezone.utc)
    days_map = {"today": 1, "day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}
    days = days_map.get(period_norm, 30)
    if period_norm.startswith("days="):
        try:
            days = max(1, min(int(period_norm.split("=", 1)[1]), 365))
        except Exception:
            days = 30
    since = (now - timedelta(days=days)).isoformat()
    log_q: Dict[str, Any] = {"created_at": {"$gte": since}}

    # Company filter — same logic as /admin/user-activity
    if company:
        emails = await db.users.distinct(
            "email",
            {"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}},
        )
        emails = [(e or "").lower() for e in emails if e]
        if not emails:
            return {"period": period_norm, "days": days, "company": company,
                    "matrix": [[0] * 24 for _ in range(7)], "total": 0, "peak": {"day": None, "hour": None, "count": 0}}
        log_q["user_email"] = {"$in": emails}

    matrix = [[0] * 24 for _ in range(7)]
    total = 0
    peak = {"day": None, "hour": None, "count": 0}
    try:
        cursor = db.access_logs.find(log_q, {"_id": 0, "created_at": 1})
        async for r in cursor:
            iso = r.get("created_at") or ""
            try:
                d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            # Python weekday: Monday=0..Sunday=6 (matches our grid)
            wd = d.weekday()
            hr = d.hour
            matrix[wd][hr] += 1
            total += 1
            if matrix[wd][hr] > peak["count"]:
                peak = {"day": wd, "hour": hr, "count": matrix[wd][hr]}
    except Exception:
        pass

    return {
        "period": period_norm,
        "days": days,
        "company": company,
        "since": since,
        "matrix": matrix,  # 7 rows (Mon→Sun) × 24 cols (0h→23h)
        "total": total,
        "peak": peak,
        "weekdays": ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"],
    }




@api.get("/admin/migrate-orphan-data", tags=["Admin"])
async def admin_inspect_orphan_data(_: dict = Depends(get_current_admin)):
    """Inspecte ce que la migration iter28 des données orphelines FERAIT (sans écritures).
    Returns per-user and per-collection counts. Use the POST variant below to
    actually apply the migration."""
    return await _migrate_orphan_client_data(dry_run=True)


@api.post("/admin/migrate-orphan-data", tags=["Admin"])
async def admin_run_orphan_data_migration(_: dict = Depends(get_current_admin)):
    """Applique la migration iter28 des données orphelines. Idempotent — relancer ne
    re-migrate already-migrated rows (guarded by `client_id_legacy` presence).
    """
    return await _migrate_orphan_client_data(dry_run=False)
