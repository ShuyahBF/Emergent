"""Pydantic models for SAWALI SMART SYSTEMS API."""
from datetime import datetime, timezone
from typing import Optional, List, Any, Dict, Union
from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# 2026-02 fork iter108 fix — Normalise appointment `participants` to always be
# List[Dict[str, Any]] on the backend, but accept either List[str] (phone-only
# strings coming from the portal quick form) OR List[Dict] from admin flows.
# Kept as a free function so AppointmentCreate/Update/Appointment can share it.
def _normalise_participants(value: Any) -> Optional[List[Dict[str, Any]]]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("participants must be a list")
    out: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            phone = item.strip()
            if not phone:
                continue
            out.append({"phone": phone, "name": phone})
        else:
            raise ValueError("participants item must be str or dict")
    return out


# ====================================================================
# USERS (clients + admins)
# ====================================================================
class UserPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: EmailStr
    full_name: str
    role: str
    phone: Optional[str] = None
    company: Optional[str] = None
    account_status: str = "active"
    created_at: str
    is_primary_client: Optional[bool] = False
    logo_url: Optional[str] = None
    tracked_role: Optional[str] = None
    tracked_user_id: Optional[str] = None
    parent_client_id: Optional[str] = None
    can_cash: Optional[bool] = False
    # Iter43-fix24az-f (2026-02-26) — Business type of the tenant (fabricant → limited sidebar)
    business_type: Optional[str] = None
    # 2026-02 fork (P4) — Per-user visibility overrides (Dashboard / Welcome
    # briefing modal / Messaging notifications). None = default role-based
    # behaviour ; True/False = admin override on the tracked user's profile.
    show_dashboard: Optional[bool] = None
    show_welcome_modal: Optional[bool] = None
    show_messaging_notifs: Optional[bool] = None
    # 2026-02 fork iter103 — Contract tracking (all optional, hidden when null).
    contract_number: Optional[str] = None
    contract_signed_at: Optional[str] = None
    contract_amount: Optional[float] = None
    contract_currency: Optional[str] = None
    last_payment_at: Optional[str] = None
    # 2026-02 fork iter104 — Per-tenant overdue threshold + payment template.
    contract_overdue_days: Optional[int] = None
    payment_confirmation_template: Optional[str] = None
    # 2026-02 fork iter108 — S158 (Recurring billing) + S159 (Auto-suspend).
    contract_billing_period: Optional[str] = None  # "monthly" | "quarterly" | "annual" | null
    auto_suspend_after_overdue_days: Optional[int] = None  # null = disabled


class UserCreateAdmin(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "client"  # client | admin | superviseur
    phone: Optional[str] = None
    company: Optional[str] = None
    client_code: Optional[str] = None  # short code, used for intervention numbering
    category_slug: Optional[str] = None  # slug of client_categories
    country: Optional[str] = None
    city: Optional[str] = None
    logo_url: Optional[str] = None
    account_status: str = "active"
    is_primary_client: bool = False
    whatsapp_number: Optional[str] = None  # Dedicated WhatsApp number (E.164) — used by /admin/messaging
    # Iter35h — demo role configuration (only meaningful when role=='demo')
    demo_expires_at: Optional[str] = None
    demo_quotas: Optional[Dict[str, Optional[int]]] = None
    # iter32 — Optional canonical-link hint sent by the admin form. When
    # present, the new user's `client_id` and `parent_client_id` are aligned
    # to the given canonical client (same company), preventing the "user
    # creates a fresh root that nobody else sees" footgun.
    link_to_client_id: Optional[str] = None
    # Iter43-fix24az-f — Business type on tenant creation (fabricant → limited sidebar)
    business_type: Optional[str] = None
    # 2026-02 fork iter103 — Contract tracking fields (optional, per-tenant).
    # Only rendered when populated. `contract_amount` in the tenant's currency.
    contract_number: Optional[str] = None
    contract_signed_at: Optional[str] = None  # ISO date "YYYY-MM-DD"
    contract_amount: Optional[float] = None
    contract_currency: Optional[str] = None   # e.g. "XOF", "EUR"
    last_payment_at: Optional[str] = None     # ISO date "YYYY-MM-DD"
    # 2026-02 fork iter104 — Per-tenant overdue threshold (days). If set,
    # overrides `settings.global.contract_overdue_days_default`. Empty = use global.
    contract_overdue_days: Optional[int] = None
    # 2026-02 fork iter104 — WA template used for payment receipts (defaults
    # to `confirmation_paiement_avecrecu` when empty). Sent automatically each
    # time a payment is registered via `/admin/clients/{id}/payments`.
    payment_confirmation_template: Optional[str] = None
    # 2026-02 fork iter108 — S158 (Recurring billing) + S159 (Auto-suspend).
    contract_billing_period: Optional[str] = None  # "monthly" | "quarterly" | "annual" | null
    auto_suspend_after_overdue_days: Optional[int] = None  # null = disabled


class UserUpdateAdmin(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None  # Iter35f — admin email updates were silently dropped before
    phone: Optional[str] = None
    company: Optional[str] = None
    client_code: Optional[str] = None
    category_slug: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    logo_url: Optional[str] = None
    account_status: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    is_primary_client: Optional[bool] = None
    wa_unit_cost: Optional[float] = None  # Per-message cost billed to this client
    wa_currency: Optional[str] = None  # ISO code (XOF, EUR, USD…)
    whatsapp_number: Optional[str] = None  # Dedicated WhatsApp number (E.164) used by /admin/messaging
    # Iter35h — demo role configuration
    demo_expires_at: Optional[str] = None
    demo_quotas: Optional[Dict[str, Optional[int]]] = None
    # Iter37c — Intervention cost configuration (per Client Lié)
    hourly_rate: Optional[float] = None  # Taux horaire en XOF (utilisé si flat_rate vide/0)
    flat_rate: Optional[float] = None  # Forfait fixe par intervention (prioritaire si > 0)
    # Iter37d — Cashier role flag (Caisse/Facturation module access)
    can_cash: Optional[bool] = None
    # S-iter39a — Allow admin/superviseur to re-attach a tenant account to a
    # different canonical "client lié" via dropdown. Empty string clears the
    # link; a UUID points to an existing admin/superviseur/moderateur user.
    link_to_client_id: Optional[str] = None
    # Iter43 (2026-02) — Mode de partage entre comptes de la même société.
    # 'AND' (défaut, restrictif) : il faut que `company` ET `parent_client_id`
    # correspondent pour partager. 'OR' (permissif, multi-succursales) : un
    # seul des deux suffit. À configurer sur la fiche du tenant (admin client).
    tenant_sharing_mode: Optional[str] = None  # "AND" | "OR"
    # Iter43-fix24az-f (2026-02-26) — Business type on the tenant profile.
    # `fabricant` → limited sidebar (Caisse, GRH, Officines RO, Catalogue,
    # Production). Empty/omitted = standard tenant.
    business_type: Optional[str] = None
    # 2026-02 fork iter103 — Contract tracking fields (all optional).
    contract_number: Optional[str] = None
    contract_signed_at: Optional[str] = None
    contract_amount: Optional[float] = None
    contract_currency: Optional[str] = None
    last_payment_at: Optional[str] = None
    # 2026-02 fork iter104
    contract_overdue_days: Optional[int] = None
    payment_confirmation_template: Optional[str] = None
    # 2026-02 fork iter108 — S158 + S159
    contract_billing_period: Optional[str] = None
    auto_suspend_after_overdue_days: Optional[int] = None


USER_ROLES = ["client", "admin", "superviseur", "demo"]

# Iter43-fix24az-f (2026-02-26) — Business type (tenant profile) determines
# which sidebar variant a user sees. Only `fabricant` is treated specially so
# far (limited menu + Production module). Empty/None = standard tenant.
BUSINESS_TYPES = ["", "fabricant"]


# ====================================================================
# Iter35h — Demo role quotas (per-account hard limits enforced on key APIs).
# Keys MUST match the QUOTA_KEY_* constants in server.py.
# ====================================================================
DEMO_DEFAULT_QUOTAS = {
    "whatsapp_sends": 2,        # template + free-form combined
    "sms_sends": 1,
    "ai_generations": 1,
    "transcriptions": 2,
    "directory_contacts": 10,   # max rows in directory_contacts
    "payments": 0,              # no payment link creation
    "attachments_bytes": 5 * 1024 * 1024,  # 5 Mo total storage
}
DEMO_DEFAULT_EXPIRY_DAYS = 14


# ====================================================================
# DOCUMENT CATEGORIES
# ====================================================================
class DocumentCategoryCreate(BaseModel):
    label: str
    slug: Optional[str] = None  # auto-generated if not provided
    description: Optional[str] = None
    icon: Optional[str] = None  # lucide icon name (e.g. "FileText")
    color: Optional[str] = None  # hex color (e.g. "#1E90FF")
    is_default: bool = False


class DocumentCategoryUpdate(BaseModel):
    label: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_default: Optional[bool] = None


# ====================================================================
# CLIENT CATEGORIES (clinique, pharmacie, commerce, alimentation, etc.)
# ====================================================================
class ClientCategoryCreate(BaseModel):
    label: str
    slug: Optional[str] = None
    icon: Optional[str] = None  # lucide icon name
    color: Optional[str] = None
    is_default: bool = False


class ClientCategoryUpdate(BaseModel):
    label: Optional[str] = None
    slug: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_default: Optional[bool] = None


# ====================================================================
# DEPLOYMENTS (software installations by country/city)
# Composite key: (solution_name, country)
# ====================================================================
class DeploymentCreate(BaseModel):
    solution_name: str
    country: str
    city: Optional[str] = None
    installations: int = 1
    notes: Optional[str] = None


class DeploymentUpdate(BaseModel):
    solution_name: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    installations: Optional[int] = None
    notes: Optional[str] = None


# ====================================================================
# AUTH
# ====================================================================
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    captcha_token: Optional[str] = None  # reCAPTCHA token


class LoginResponse(BaseModel):
    needs_otp: bool = True
    session_token: str
    message: str
    dev_otp: Optional[str] = None  # only if SMTP not configured


class OtpVerifyRequest(BaseModel):
    session_token: str
    code: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ====================================================================
# APPOINTMENTS
# ====================================================================
class PublicAppointmentRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str
    company: Optional[str] = None
    subject: str
    message: Optional[str] = None
    scheduled_at: str  # ISO datetime
    duration_min: int = 30


class ClientAppointmentRequest(BaseModel):
    subject: str
    message: Optional[str] = None
    scheduled_at: str
    duration_min: int = 30
    # 2026-02 fork iter107 — Participants : liste d'IDs de contacts pris parmi le
    # registre `directory_contacts` du client lié. Si non vide, un template WA est
    # envoyé à chacun. Format : [{"contact_id": "...", "name": "...", "phone": "..."}].
    # 2026-02 fork iter108 fix — Accepte aussi List[str] (numéros de téléphone bruts
    # depuis le formulaire portail) et normalise en List[Dict].
    participants: Optional[List[Union[str, Dict[str, Any]]]] = None
    # Notification WA envoyée N minutes avant le RDV (défaut = valeur globale du planning).
    reminder_minutes: Optional[int] = None

    @field_validator("participants", mode="before")
    @classmethod
    def _norm_participants(cls, v):  # noqa: N805
        return _normalise_participants(v)


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None  # pending|confirmed|cancelled|completed
    notes: Optional[str] = None
    scheduled_at: Optional[str] = None
    duration_min: Optional[int] = None
    subject: Optional[str] = None
    message: Optional[str] = None
    # 2026-02 fork iter107 + iter108 fix (voir AppointmentCreate)
    participants: Optional[List[Union[str, Dict[str, Any]]]] = None
    reminder_minutes: Optional[int] = None

    @field_validator("participants", mode="before")
    @classmethod
    def _norm_participants(cls, v):  # noqa: N805
        return _normalise_participants(v)


class Appointment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    client_id: Optional[str] = None
    name: str
    email: EmailStr
    phone: Optional[str] = None
    company: Optional[str] = None
    subject: str
    message: Optional[str] = None
    scheduled_at: str
    duration_min: int = 30
    status: str = "pending"
    notes: Optional[str] = None
    gcal_event_id: Optional[str] = None
    # 2026-02 fork iter107
    participants: Optional[List[Dict[str, Any]]] = None
    reminder_minutes: Optional[int] = None
    created_at: str


# ====================================================================
# INTERVENTIONS
# ====================================================================
class InterventionCreate(BaseModel):
    client_id: str
    title: str
    description: Optional[str] = None
    status: str = "completed"  # planned|in_progress|completed|cancelled
    intervention_date: str
    technician: Optional[str] = None
    duration_hours: Optional[float] = None
    attachments: List[str] = []
    images: Optional[List[dict]] = None  # [{file_id, url, filename}], max 10
    # Iter34y/z — Note vocale facultative + transcription Whisper.
    voice_note_url: Optional[str] = None
    voice_note_transcript: Optional[str] = None
    # Iter43 — Partage tenant cross-utilisateur
    shared_with_tenant: Optional[bool] = None
    editable_by_tenant: Optional[bool] = None


class InterventionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    intervention_date: Optional[str] = None
    technician: Optional[str] = None
    duration_hours: Optional[float] = None
    attachments: Optional[List[str]] = None
    images: Optional[List[dict]] = None
    client_id: Optional[str] = None  # iter34y — permet de re-rattacher l'intervention
    voice_note_url: Optional[str] = None
    voice_note_transcript: Optional[str] = None
    # Iter43 — Partage tenant cross-utilisateur
    shared_with_tenant: Optional[bool] = None
    editable_by_tenant: Optional[bool] = None


# ====================================================================
# DOCUMENTS (catalog, software docs, announcements)
# ====================================================================
class DocumentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "documentation"  # catalog|documentation|announcement
    file_id: Optional[str] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None  # pdf|image|text|html
    filename: Optional[str] = None
    file_extension: Optional[str] = None
    body_html: Optional[str] = None  # for text/html docs
    client_id: Optional[str] = None  # null = public/all clients
    is_public: bool = False
    cover_image_url: Optional[str] = None
    # 2026-02 fork (P5) — Liste d'accessibilité stricte : si non-vide, seuls
    # les tracked users dont le parent_client_id ∈ liste peuvent voir ce doc.
    # Si vide → comportement historique (visible via client_id/is_public).
    access_client_ids: Optional[List[str]] = None


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    file_id: Optional[str] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    filename: Optional[str] = None
    file_extension: Optional[str] = None
    body_html: Optional[str] = None
    client_id: Optional[str] = None
    is_public: Optional[bool] = None
    cover_image_url: Optional[str] = None
    access_client_ids: Optional[List[str]] = None


# ====================================================================
# CMS CONTENT (mission, about, specialisations, etc.)
# ====================================================================
class ContentUpsert(BaseModel):
    slug: str  # mission|about|specialisations|experience|home_hero|...
    title: str
    body_html: str = ""
    images: List[str] = []
    metadata: dict = {}
    # Iter40-content-i18n — Per-language overrides. Shape:
    # { "en": {"title": "...", "body_html": "...", "metadata": {...}}, "ar": {...}, ... }
    # When a language is selected on the public page, its overrides replace
    # the default top-level fields. Missing language → fall back to default.
    translations: dict = {}


# ====================================================================
# CONTACTS
# ====================================================================
class ContactCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    company: Optional[str] = None
    subject: Optional[str] = None
    message: str


# ====================================================================
# USERS TRACKING (sub-users of a client)
# ====================================================================
TRACKED_USER_ROLES = ["Consultation", "Edition", "Moderation", "Administrateur", "Superviseur", "Comptable", "Caissier", "Traducteur", "Médecin", "Secrétaire médicale"]


class TrackedUserCreate(BaseModel):
    client_id: str
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    whatsapp_number: Optional[str] = None  # Dedicated WhatsApp number (E.164)
    role: str = "Consultation"  # one of TRACKED_USER_ROLES
    department: Optional[str] = None
    company: Optional[str] = None  # override client.company for this user
    last_seen: Optional[str] = None
    status: str = "active"
    # 2026-02 — Traducteur fields (only relevant when role == "Traducteur")
    translator_languages: Optional[List[str]] = None  # e.g. ["en", "ar", "lg1"]
    translator_rate_per_word: Optional[float] = None  # base in user currency
    # 2026-02 — Force logout toggle (#5)
    force_logout_on_idle: Optional[bool] = None
    # 2026-02 fork (P4) — Overrides per-user pour la visibilité du Tableau
    # de bord, de la modale de bienvenue et des notifications du Centre de
    # Messagerie. Aucune valeur (None) → comportement par défaut du rôle.
    # True → force affichage même si le rôle a un menu réduit. False → masque
    # même pour Consultation/Édition qui le voient d'habitude.
    show_dashboard: Optional[bool] = None
    show_welcome_modal: Optional[bool] = None
    show_messaging_notifs: Optional[bool] = None


class TrackedUserUpdate(BaseModel):
    client_id: Optional[str] = None  # support reassigning to a different client
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    whatsapp_number: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    company: Optional[str] = None
    last_seen: Optional[str] = None
    status: Optional[str] = None
    translator_languages: Optional[List[str]] = None
    translator_rate_per_word: Optional[float] = None
    force_logout_on_idle: Optional[bool] = None
    # 2026-02 fork (P4) — Overrides visibilité (voir TrackedUserCreate)
    show_dashboard: Optional[bool] = None
    show_welcome_modal: Optional[bool] = None
    show_messaging_notifs: Optional[bool] = None


class SaveContactAsTrackedUser(BaseModel):
    client_id: str
    role: str = "Consultation"
    department: Optional[str] = None


class TrackedUserSetPassword(BaseModel):
    password: str  # raw, will be bcrypted


# ====================================================================
# SETTINGS (admin configurable)
# ====================================================================
class SettingsUpdate(BaseModel):
    # Iter43-fix24aq (2026-06-17) — Allow arbitrary `wa_cmd_<id>_image_url`
    # / `wa_cmd_<id>_image_caption` keys (one per VIDAL action). Without
    # `extra="allow"`, Pydantic would silently drop them.
    model_config = ConfigDict(extra="allow")

    recaptcha_site_key: Optional[str] = None
    recaptcha_secret_key: Optional[str] = None
    recaptcha_enabled: Optional[bool] = None

    # --- Iter35x — Public base URL ---
    # Overrides the static PUBLIC_BASE_URL env var. Used for absolute links in
    # background jobs (cron emails, WhatsApp links, OAuth redirects) when no
    # browser request is available. Editable from the Coffre-fort des secrets.
    public_base_url: Optional[str] = None

    # 2026-02 (#3) — Default Liluvine takeover duration in minutes.
    # When a moderator clicks "Reprendre" on a Liluvine session, the AI is
    # paused for this many minutes (default 30). Previous hardcoded value
    # was 120 min, which users found too long. Range 5–10080.
    liluvine_takeover_default_minutes: Optional[int] = None

    # --- Iter38r-fix9z10 — Suggestion S009 — Auto-logout on inactivity ---
    # Idle delay in minutes after which a logged-in user is automatically
    # signed out. A warning modal opens 30 seconds before the timeout.
    # When set to 0, auto-logout is disabled. Range: 0-120 minutes.
    auto_logout_minutes: Optional[int] = None

    # --- Iter40-modal — Global daily cap of public modal ads per visitor ---
    # Max number of distinct popup-modal banners a single visitor sees in a
    # rolling 24h window (tracked client-side via localStorage). 0 = unlimited.
    # Range 0-20. Default 2.
    modal_global_cap_per_day: Optional[int] = None

    # --- Iter40-route-loader — S051 — Toggle the central GlobalRouteLoader ---
    # When false, the mini circular loader shown between page navigations and
    # during in-flight API calls is hidden. Defaults to true. Useful for users
    # who find the indicator intrusive on fast connections.
    global_route_loader_enabled: Optional[bool] = None

    # --- 2026-02 fork iter108 — S164 (Emmy) — Browser Push Notifications ---
    # Global switch enabling native Notification API for portal users (tab-blink
    # + system toast when new ticket/RDV/message arrives while tab is hidden).
    # Infrastructure already exists (BrowserNotifications.jsx). Setting this
    # to false disables both the permission prompt and the toast dispatch
    # globally for all users. Defaults to true.
    browser_notifications_enabled: Optional[bool] = None

    # --- Iter40-ui-flags — Public branding customization ---
    # Exposed via /api/public/ui-flags (anonymous endpoint) so resellers can
    # customize the public site without touching code.
    public_brand_name: Optional[str] = None     # Site title / window.document.title
    public_brand_color: Optional[str] = None    # Primary brand hex (e.g. "#1E90FF")
    public_brand_text_color: Optional[str] = None  # Iter40-ui-flags-text — Text color on brand backgrounds (default white)
    public_logo_url: Optional[str] = None       # Public logo (header / footer)
    public_hero_tagline: Optional[str] = None   # Optional public hero tagline override

    # --- Iter40-ui-flags-bg (S057) — Event/client themed background ---
    # Public site background (marketing pages /, /missions, /spec, /contact, …)
    public_bg_mode: Optional[str] = None        # "default" | "color" | "image"
    public_bg_color: Optional[str] = None       # Hex (#RRGGBB) when mode == "color"
    public_bg_image_url: Optional[str] = None   # URL when mode == "image"
    public_bg_image_position: Optional[str] = None  # "center" | "repeat" | "cover" | "contain"
    # Portal background (logged-in workspace /portal/*, /admin/*)
    portal_bg_mode: Optional[str] = None
    portal_bg_color: Optional[str] = None
    portal_bg_image_url: Optional[str] = None
    portal_bg_image_position: Optional[str] = None

    # Iter40 (2026-02) — Filtre no-toast WA ---
    wa_silent_phones_enabled: Optional[bool] = None
    wa_silent_phones: Optional[List[str]] = None

    # Iter43-fix24n (2026-06) — Délégation menu Officines à des comptes non-admin
    # Liste d'emails autorisés à accéder à /admin/officines sans rôle admin.
    # Ces utilisateurs ne peuvent modifier que : intitule, phone, whatsapp,
    # latitude, longitude, location_hint, activite_principale.
    officines_menu_allowed_emails: Optional[List[str]] = None

    # Iter40 (2026-02) — Token Bearer pour le webhook /api/errors/ingest
    errors_webhook_token: Optional[str] = None

    # Iter43-fix (2026-03) — Taux horaire par défaut pour interventions (XOF)
    default_intervention_hourly_rate_xof: Optional[int] = None

    # Iter43-fix (2026-03) — Mapping des sévérités logiciel → sévérité plateforme.
    # Permet à l'admin d'associer chaque valeur StatutEnCours envoyée par les
    # logiciels métier à une sévérité interne (low/medium/high/critical).
    # Format: { "exception": "high", "fatale": "critical", "warning": "medium", ... }
    error_severity_mapping: Optional[Dict[str, str]] = None

    # --- S057 Day 3+ (2026-02) — Habillage complet ---
    # Sidebar (portail) — global SAWALI defaults (tenant peut override via branding)
    sidebar_bg_color: Optional[str] = None        # ex: "#0E1F3D"
    sidebar_text_color: Optional[str] = None      # ex: "#FFFFFF"
    sidebar_accent_color: Optional[str] = None    # active link / hover ex: "#1E90FF"
    # Login page (page publique)
    login_bg_mode: Optional[str] = None           # "default" | "color" | "image"
    login_bg_color: Optional[str] = None
    login_bg_image_url: Optional[str] = None
    login_text_color: Optional[str] = None
    login_card_bg: Optional[str] = None
    login_card_text_color: Optional[str] = None
    login_button_bg: Optional[str] = None
    login_button_text_color: Optional[str] = None
    # Blocs publics — chaque bloc peut overrider bg+text. JSON storé en dict.
    # Clés possibles : "hero" | "specialisations" | "missions" | "experience" | "about"
    public_blocks_theme: Optional[Dict[str, Any]] = None

    # --- S025 — Download approval workflow (S-iter39e) ---
    # When enabled, non-admin users requesting a private document download
    # trigger a WhatsApp approval flow: a message is sent to the configured
    # approver number with two quick-reply buttons (Autoriser / Refuser).
    # Until the approver clicks, the requester sees a circular gauge with
    # `download_pending_message` (default "En attente d'approbation pour le
    # téléchargement..."). On refusal the requester sees "Désolé,
    # l'opération n'a pas été confirmée".
    download_approval_enabled: Optional[bool] = None
    download_approval_whatsapp: Optional[str] = None  # E.164 approver phone
    download_pending_message: Optional[str] = None  # text in the waiting gauge
    download_approval_template_name: Optional[str] = None  # Meta-approved interactive template
    download_approval_template_lang: Optional[str] = None  # default "fr"
    download_approval_text_body: Optional[str] = None  # fallback text body (used when no template name configured)

    # --- S026 — PV signers notification channel (S-iter39e) ---
    # When a PV (Procès-Verbal) is created with declared signers, notify
    # them via email, WhatsApp, both or none. Default: none.
    meeting_signers_notify_channel: Optional[str] = None  # "none" | "email" | "wa" | "both"

    # --- S032 — Universal Key Emergent — burn-rate thresholds & alerts ---
    # Warning/critical thresholds (% of monthly budget consumed) used by the
    # `LlmHealthBanner` and the daily proactive alerts (Email + WhatsApp).
    # When the cumulative monthly consumption reaches `llm_budget_warning_pct`
    # (default 80) → status_level becomes "warning" and an email + WhatsApp
    # alert are sent to the super-admin (max once per 23h).
    # When it reaches `llm_budget_critical_pct` (default 95) → status_level
    # becomes "critical" with its own throttled alert series.
    # `llm_budget_max_usd` is the configured monthly cap of the Universal Key
    # used as fallback when Emergent has never returned a ground-truth value
    # (typically $3.00 by default). Override here if your plan differs.
    # `llm_budget_notify_wa_phone` is the E.164 number to receive the
    # WhatsApp alerts (defaults to the WA conversation window — must be a
    # number that wrote to the bot within 24h).
    llm_budget_warning_pct: Optional[int] = None  # 50-99, default 80
    llm_budget_critical_pct: Optional[int] = None  # 60-99, default 95
    llm_budget_max_usd: Optional[float] = None  # default 3.0 USD
    llm_budget_notify_email: Optional[bool] = None  # default true
    llm_budget_notify_wa: Optional[bool] = None  # default true
    llm_budget_notify_wa_phone: Optional[str] = None  # E.164

    # --- S033 — WhatsApp keyword to query the budget on demand ---
    # When `llm_budget_wa_query_enabled` is true, any WhatsApp message whose
    # body equals (case-insensitive) `llm_budget_wa_query_keyword` (default
    # "SOLDE") sent FROM `llm_budget_notify_wa_phone` triggers an automatic
    # reply with the current budget summary. The number must have written to
    # the bot in the last 24 h (Meta customer-service window).
    llm_budget_wa_query_enabled: Optional[bool] = None  # default false
    llm_budget_wa_query_keyword: Optional[str] = None  # default "SOLDE"

    # --- S035 — Mute Universal Key alerts via WA cockpit ---
    # ISO timestamp until which the S031/S032 alerts (email + WA) are
    # silenced. Set via the `MUTE` / `NOTIF STOP` WhatsApp cockpit command
    # (24h auto-expiry) and cleared via `UNMUTE` / `NOTIF ON`. The cron
    # `_scheduled_llm_health_ping` honours this value before sending.
    llm_alerts_muted_until: Optional[str] = None

    # --- S036 — Liluvine PRO escalation to admin via WhatsApp ---
    # When enabled, Liluvine can emit a `[ESCALATE: <reason>]` marker at
    # the end of her reply (system-prompt instructed). The backend strips
    # the marker from the customer-facing message and sends a contextual
    # WhatsApp notification to `liluvine_escalation_wa_phone` (defaults to
    # `llm_budget_notify_wa_phone` when unset). Anti-spam : 1 per contact
    # per `liluvine_escalation_cooldown_minutes` (default 30).
    liluvine_escalation_enabled: Optional[bool] = None  # default false
    liluvine_escalation_wa_phone: Optional[str] = None  # E.164
    liluvine_escalation_cooldown_minutes: Optional[int] = None  # default 30 min

    # --- S038 — Qdrant RAG semantic knowledge base ---
    # Master toggle + connection settings (DB takes precedence over env).
    # When `qdrant_enabled` is True, Liluvine PRO (chat + WA auto-reply)
    # runs a semantic search across all collections flagged
    # `enabled_for_liluvine=true` in `qdrant_collection_settings` and
    # injects the top hits as KB context for the LLM.
    qdrant_enabled: Optional[bool] = None
    qdrant_url: Optional[str] = None
    qdrant_api_key: Optional[str] = None
    qdrant_collection_settings: Optional[dict] = None  # name → {enabled_for_liluvine, description}
    # --- P1 (2026-02) — Auto-enrich uploaded images with Claude Vision ---
    # When True (default), uploaded images go through Claude Sonnet 4.6 Vision
    # to extract OCR text + a visual description. These enrich the embedding
    # text so Liluvine can find an image even without a manual caption.
    # Per-upload override available via the `auto_describe` form field.
    qdrant_image_auto_describe: Optional[bool] = None
    # --- 0-2 (2026-02) — Allow opt-in for digest emails to be sent from the
    # PREVIEW environment too (default = skip preview, only send from PROD).
    health_weekly_send_from_preview: Optional[bool] = None

    # --- Iter38r-fix9o (P1) — Stripe webhook signing secret ---
    # Used by `POST /api/webhook/stripe` to verify Stripe event signatures.
    # Stored alongside other secrets in `settings.global`. Takes precedence
    # over the `STRIPE_WEBHOOK_SECRET` env var when set.
    stripe_webhook_secret: Optional[str] = None

    # --- Iter35x — Alexa Echo voice notifications via Voice Monkey ---
    # When enabled, a POST is sent to `alexa_webhook_url` whenever one of the
    # selected events fires (SMS inbound, WhatsApp inbound, appointment due,
    # support load critical). Voice Monkey speaks the message via the linked
    # Echo device. Free tier ≤ 50 calls/day; $5/mo for unlimited.
    alexa_enabled: Optional[bool] = None
    alexa_webhook_url: Optional[str] = None
    alexa_events: Optional[List[str]] = None  # ["sms_inbound", "wa_inbound", "appointment_due", "support_load_critical"]

    # --- Iter35x — Secret change audit & email notification ---
    # When enabled, every modification of a sensitive/vault key emails
    # `secret_audit_email_to` with WHO/WHEN/WHICH key (never the value).
    secret_audit_email_enabled: Optional[bool] = None
    secret_audit_email_to: Optional[str] = None

    # --- Iter35z — SMS dashboard: per-provider unit cost (XOF) + monthly budget ---
    # All costs are quoted in F CFA (XOF). Used by /api/admin/sms/dashboard to
    # estimate spend and warn when the monthly budget is at risk.
    sms_orange_unit_cost_xof: Optional[float] = None
    sms_moov_unit_cost_xof: Optional[float] = None
    sms_telecel_unit_cost_xof: Optional[float] = None
    sms_ovh_unit_cost_xof: Optional[float] = None
    sms_monthly_budget_xof: Optional[float] = None

    # --- Iter36d — Note de Service (broadcast WA template to all suivis) ---
    wa_template_note_service: Optional[str] = None  # default: "notedeservice_fr"
    wa_template_note_service_language: Optional[str] = None  # default: "fr"

    # --- Auto DB Snapshot (iter34) ---
    # Weekly cron creates a snapshot every Sunday 03:00 Africa/Abidjan and
    # rotates older auto snapshots beyond `auto_snapshot_keep` (default 4,
    # max 52). Manual snapshots never rotate.
    auto_snapshot_enabled: Optional[bool] = None
    auto_snapshot_keep: Optional[int] = None  # rotation window (1..52)
    # Email delivery (offsite copy). When enabled, the .json.gz is sent as
    # an SMTP attachment to `auto_snapshot_email_to`.
    auto_snapshot_email_enabled: Optional[bool] = None
    auto_snapshot_email_to: Optional[str] = None  # recipient address

    # --- Support Technique Load Gauge (0-7 — like cellular signal bars) ---
    # Visible at the top of every public page. Configurable from Admin
    # Settings UI or via webhook (POST /api/webhooks/support-load/{secret}).
    support_load_enabled: Optional[bool] = None
    support_load_level: Optional[int] = None  # 0..7
    support_load_label: Optional[str] = None  # short FR label, eg. "Forte affluence ce matin"
    support_load_webhook_secret: Optional[str] = None  # for webhook auth

    # --- Liluvine smart redirect (couples the assistant with the gauge) ---
    # When current support_load_level >= threshold, the floating Liluvine
    # button gets a warning-style label and the assistant panel surfaces an
    # "office is busy" message first. Threshold is admin-tunable; can also
    # be tweaked remotely via a signed link or a WhatsApp command.
    liluvine_alert_enabled: Optional[bool] = None  # opt-in (default off)
    liluvine_alert_threshold: Optional[int] = None  # 0..7 — default 6
    liluvine_alert_message: Optional[str] = None  # FR text (~200 chars)
    liluvine_alert_label: Optional[str] = None  # short button label, eg. "🔴 Forte affluence — chat plutôt"
    liluvine_remote_secret: Optional[str] = None  # HMAC secret for /remote/support/{token}
    liluvine_remote_admin_phones: Optional[List[str]] = None  # WA digits allowed to send `!seuil`/`!niveau`

    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_email: Optional[str] = None
    smtp_from_name: Optional[str] = None
    smtp_use_tls: Optional[bool] = None

    # Iter38r-fix9k — KB OCR cost / cap config
    kb_ocr_xof_per_page: Optional[int] = None
    kb_ocr_xof_monthly_cap: Optional[int] = None
    kb_ocr_pdf_max_pages: Optional[int] = None
    notes_strict_tasks_only: Optional[bool] = None

    # Iter38r-fix9l — Bonus pack settings
    wa_tasks_digest_enabled: Optional[bool] = None
    liluvine_weekly_digest_enabled: Optional[bool] = None
    gdpr_auto_anonymize_enabled: Optional[bool] = None
    gdpr_contact_inactive_months: Optional[int] = None
    gdpr_msg_retention_months: Optional[int] = None
    gdpr_log_retention_days: Optional[int] = None
    public_base_url: Optional[str] = None

    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_calendar_email: Optional[str] = None
    google_calendar_password_hint: Optional[str] = None  # paramétrable, indicatif

    business_open_time: Optional[str] = None  # "09:00"
    business_close_time: Optional[str] = None  # "18:00"
    descent_time: Optional[str] = None  # "08:00" — heure de descente sur site (cutoff = +1h pour create rapport/suivi/intervention)
    business_days: Optional[List[int]] = None  # 0=Mon ... 6=Sun
    slot_duration_min: Optional[int] = None

    company_email: Optional[str] = None
    company_phone: Optional[str] = None
    company_whatsapp: Optional[str] = None
    company_address: Optional[str] = None
    company_city: Optional[str] = None
    company_country: Optional[str] = None

    # Visitor tracking external REST endpoint
    tracking_enabled: Optional[bool] = None
    tracking_base_url: Optional[str] = None
    tracking_endpoint: Optional[str] = None  # e.g. /events/visit
    tracking_auth_header: Optional[str] = None  # e.g. "Bearer xyz"

    # Intervention webhook (POST {base_url}/{action}/{client_code}/{intervention_number})
    webhook_enabled: Optional[bool] = None
    webhook_base_url: Optional[str] = None
    webhook_auth_type: Optional[str] = None  # none | bearer | basic
    webhook_token: Optional[str] = None  # for bearer
    webhook_basic_user: Optional[str] = None
    webhook_basic_pass: Optional[str] = None

    # Hero video on public homepage
    hero_video_enabled: Optional[bool] = None
    hero_video_url: Optional[str] = None  # uploaded MP4 url e.g. /uploads/xxx.mp4
    hero_video_title: Optional[str] = None
    hero_video_description: Optional[str] = None
    hero_video_autoplay: Optional[bool] = None
    hero_video_loop: Optional[bool] = None
    hero_video_muted: Optional[bool] = None
    hero_video_poster_url: Optional[str] = None  # optional cover image

    # Virtual assistant (JotForm or compatible popup chatbot)
    assistant_enabled: Optional[bool] = None
    assistant_url: Optional[str] = None  # external popup URL (e.g. JotForm agent)
    assistant_label: Optional[str] = None  # button label
    assistant_color: Optional[str] = None  # hex color for the floating button

    # Portal feature toggles
    show_reports_button: Optional[bool] = None
    show_suivis_button: Optional[bool] = None

    # Notes webhook (POST on every report/suivi create/update/delete)
    notes_webhook_enabled: Optional[bool] = None
    notes_webhook_url: Optional[str] = None
    notes_webhook_auth_type: Optional[str] = None  # none | bearer | basic
    notes_webhook_token: Optional[str] = None
    notes_webhook_basic_user: Optional[str] = None
    notes_webhook_basic_pass: Optional[str] = None

    # Public visit counter on homepage
    visits_counter_enabled: Optional[bool] = None
    visits_counter_offset: Optional[int] = None  # Added to real count (can be negative to reset)

    # Health monitoring (api_traces email/webhook reporting)
    health_realtime_enabled: Optional[bool] = None  # email + webhook on each error trace
    health_weekly_enabled: Optional[bool] = None  # weekly digest on Friday 05:00
    health_auth_check_enabled: Optional[bool] = None  # alert if hourly auth probe fails
    health_uptime_alerts_enabled: Optional[bool] = None  # alert if any hourly uptime probe fails
    # Iter37f — Welcome briefing: unread counter mode ("bounded" | "lifetime").
    welcome_unread_mode: Optional[str] = None  # bounded (default) bounds by last_seen_at or last 7 days; lifetime counts all unread inbound
    # Iter37g — WhatsApp templates for Caisse (receipt/invoice/proforma)
    wa_template_receipt_name: Optional[str] = None        # default: confirmation_paiement_avecrecu
    wa_template_receipt_language: Optional[str] = None    # default: fr
    wa_template_invoice_name: Optional[str] = None        # default: document_piecejointe_facturation
    wa_template_invoice_language: Optional[str] = None    # default: fr
    # Iter38c — Cashier expense justification deadline (hours). 0 = no limit.
    expense_justification_deadline_hours: Optional[int] = None
    # Incident banner — public sticky bar at top of marketing pages
    incident_banner_enabled: Optional[bool] = None
    incident_banner_severity: Optional[str] = None  # info | warning | critical
    incident_banner_message: Optional[str] = None
    incident_banner_link_url: Optional[str] = None
    incident_banner_link_label: Optional[str] = None
    # WhatsApp Business (Meta Cloud API) — global credentials
    wa_business_account_id: Optional[str] = None    # WABA ID
    wa_phone_number_id: Optional[str] = None         # Phone Number ID (not the number itself)
    wa_access_token: Optional[str] = None            # Permanent System User access token
    wa_app_id: Optional[str] = None                  # Meta App ID (webhook verification)
    wa_verify_token: Optional[str] = None            # Shared secret for webhook GET verification
    wa_default_language: Optional[str] = None        # Default template language code (e.g. 'fr')
    # Iter35b — WhatsApp inbound-silence detector
    # When at least `wa_silence_alert_threshold` outbound messages were sent
    # in the trailing `wa_silence_alert_window_hours` window AND zero webhook
    # hits were received from Meta in the same window, fire an alert.
    # Throttled to once per window via `wa_silence_alert_last_fired_at`.
    wa_silence_alert_enabled: Optional[bool] = None
    wa_silence_alert_threshold: Optional[int] = None  # default 3
    wa_silence_alert_window_hours: Optional[int] = None  # default 24
    wa_silence_alert_email_to: Optional[str] = None  # defaults to health_email_to
    wa_silence_alert_discord_webhook: Optional[str] = None  # optional Discord webhook URL

    # Iter35l — WhatsApp media (inbound/outbound + watermark + QR + RGPD)
    wa_allow_terminal_media: Optional[bool] = None       # default True — allow file picker in chat
    wa_voice_transcribe_enabled: Optional[bool] = None    # default True — auto-Whisper on inbound voice notes
    wa_watermark_enabled: Optional[bool] = None           # default True
    wa_watermark_text: Optional[str] = None               # default = company name
    wa_qr_enabled: Optional[bool] = None                  # default True
    wa_qr_payload: Optional[str] = None                   # default = public base url

    # Iter35o — Support ticket notifications (WhatsApp templates)
    wa_template_ticket_open: Optional[str] = None  # Meta template name, vars {1}=number {2}=motif
    wa_template_ticket_close: Optional[str] = None  # Meta template name, vars {1}=number {2}=duration
    wa_template_ticket_language: Optional[str] = None  # default "fr"
    notify_on_ticket_open: Optional[bool] = None  # default True
    notify_on_ticket_close: Optional[bool] = None  # default True

    # Iter38r-fix9o (Item 8) — WhatsApp OTP login template (reuses the same
    # whatsapp_access_token + whatsapp_phone_number_id as the ticket flows).
    # If empty → fallback to a plain text message (works only inside the
    # 24h WA session window).
    wa_otp_template: Optional[str] = None  # ex. wa_envoiotp_fr — 1 body var = code
    wa_otp_template_lang: Optional[str] = None  # default "fr"
    # Iter42b (2026-02) — Template OTP dédié au portail Self-Service Officines
    officine_otp_template: Optional[str] = None
    officine_otp_template_lang: Optional[str] = None
    officine_otp_template_category: Optional[str] = None  # cached après 1er succès
    # Iter42d (2026-02) — Code pays par défaut pour le catalogue AMM (ISO-2)
    # Le code AMM dépend du pays — chaque pays a sa propre autorité. Si absent,
    # tout AMM créé sera enregistré sans country_code (legacy).
    amm_default_country: Optional[str] = None
    # Iter42d — Webhook incidents entrant (auth par mot de passe simple)
    incidents_webhook_password: Optional[str] = None
    incidents_webhook_rotated_at: Optional[str] = None
    incidents_webhook_rotated_by: Optional[str] = None
    # Iter42e (2026-02) — URL publique du portail (override optionnel).
    # Utilisé pour afficher l'URL exacte du webhook /api/public/incidents et
    # autres endpoints publics dans les exemples curl/Python. Si non défini,
    # le frontend utilise window.location.origin du navigateur courant.
    public_app_url: Optional[str] = None

    # Iter35r — Welcome modal at login (briefing)
    welcome_modal_notes_days: Optional[int] = None  # default 3 — fetch notes created within N days
    health_webhook_url: Optional[str] = None
    health_webhook_auth_type: Optional[str] = None  # none | bearer | basic
    health_webhook_token: Optional[str] = None
    health_webhook_basic_user: Optional[str] = None
    health_webhook_basic_pass: Optional[str] = None
    health_email_to: Optional[str] = None  # default: SUPER_ADMIN_EMAIL
    health_timezone: Optional[str] = None  # default Africa/Abidjan

    # 2026-02 fork iter104 — Contract-overdue alert threshold (in days).
    # Applied to clients WITHOUT a per-tenant `contract_overdue_days` override.
    # Default: 5 days after `last_payment_at` (or `contract_signed_at` if no
    # payment has been recorded yet).
    contract_overdue_days_default: Optional[int] = None

    # OpenAI — used for audio transcription (Whisper) inside Reports/Suivis
    openai_api_key: Optional[str] = None  # secret — masked when read (Whisper)
    openai_whisper_model: Optional[str] = None  # default "whisper-1"

    # AI Summary engine — used by the dashboard "Synthèse IA" button.
    # Two providers are supported and the admin can switch between them at any time:
    #   - "openai" → calls OpenAI ChatGPT (chat.completions) with `openai_chat_api_key`.
    #   - "n8n"    → forwards the payload to a configurable n8n webhook (AgentAI-style).
    ai_summary_provider: Optional[str] = None  # "openai" | "n8n"
    openai_chat_api_key: Optional[str] = None  # secret — masked when read
    openai_chat_model: Optional[str] = None  # default "gpt-4o-mini"
    n8n_webhook_url: Optional[str] = None
    n8n_webhook_auth_type: Optional[str] = None  # "none" | "bearer" | "basic"
    n8n_webhook_token: Optional[str] = None  # secret — masked when read
    n8n_webhook_basic_user: Optional[str] = None
    n8n_webhook_basic_pass: Optional[str] = None  # secret — masked when read

    # ----- SMS — generic webhook providers (Orange / Moov / Telecel Burkina) -----
    # Three independent provider blocks, each shaped like the n8n webhook one
    # so the admin can plug whichever HTTP REST endpoint each operator exposes.
    sms_orange_enabled: Optional[bool] = None
    sms_orange_url: Optional[str] = None
    sms_orange_method: Optional[str] = None  # "GET" | "POST"
    sms_orange_auth_type: Optional[str] = None  # "none" | "bearer" | "basic" | "header"
    sms_orange_token: Optional[str] = None  # secret — masked
    sms_orange_basic_user: Optional[str] = None
    sms_orange_basic_pass: Optional[str] = None  # secret — masked
    sms_orange_header_name: Optional[str] = None  # for auth_type=header
    sms_orange_header_value: Optional[str] = None  # secret — masked
    sms_orange_sender: Optional[str] = None  # caller-id / from
    sms_orange_payload_template: Optional[str] = None  # JSON template with {phone}/{message}/{sender}
    sms_orange_content_type: Optional[str] = None  # "json" | "form" — defaults to json
    # Iter35i — Orange Developer OAuth2 client_credentials flow
    sms_orange_oauth_url: Optional[str] = None  # default https://api.orange.com/oauth/v3/token
    sms_orange_client_id: Optional[str] = None
    sms_orange_client_secret: Optional[str] = None  # masked
    sms_orange_sender_msisdn: Optional[str] = None  # E.164 number registered with Orange

    sms_moov_enabled: Optional[bool] = None
    sms_moov_url: Optional[str] = None
    sms_moov_method: Optional[str] = None
    sms_moov_auth_type: Optional[str] = None
    sms_moov_token: Optional[str] = None  # masked
    sms_moov_basic_user: Optional[str] = None
    sms_moov_basic_pass: Optional[str] = None  # masked
    sms_moov_header_name: Optional[str] = None
    sms_moov_header_value: Optional[str] = None  # masked
    sms_moov_sender: Optional[str] = None
    sms_moov_payload_template: Optional[str] = None
    sms_moov_content_type: Optional[str] = None
    sms_moov_oauth_url: Optional[str] = None
    sms_moov_client_id: Optional[str] = None
    sms_moov_client_secret: Optional[str] = None  # masked
    sms_moov_sender_msisdn: Optional[str] = None

    sms_telecel_enabled: Optional[bool] = None
    sms_telecel_url: Optional[str] = None
    sms_telecel_method: Optional[str] = None
    sms_telecel_auth_type: Optional[str] = None
    sms_telecel_token: Optional[str] = None  # masked
    sms_telecel_basic_user: Optional[str] = None
    sms_telecel_basic_pass: Optional[str] = None  # masked
    sms_telecel_header_name: Optional[str] = None
    sms_telecel_header_value: Optional[str] = None  # masked
    sms_telecel_sender: Optional[str] = None
    sms_telecel_payload_template: Optional[str] = None
    sms_telecel_content_type: Optional[str] = None
    sms_telecel_oauth_url: Optional[str] = None
    sms_telecel_client_id: Optional[str] = None
    sms_telecel_client_secret: Optional[str] = None  # masked
    sms_telecel_sender_msisdn: Optional[str] = None

    # Default SMS provider used when the caller doesn't specify one.
    # Values: "orange" | "moov" | "telecel" | "ovh" | "auto" (auto = pick by phone prefix).
    sms_default_provider: Optional[str] = None

    # ----- OVH SMS — official API (https://api.ovh.com /sms/{serviceName}/jobs) -----
    sms_ovh_enabled: Optional[bool] = None
    sms_ovh_endpoint: Optional[str] = None  # "ovh-eu" | "ovh-ca" — endpoint host
    sms_ovh_application_key: Optional[str] = None
    sms_ovh_application_secret: Optional[str] = None  # masked
    sms_ovh_consumer_key: Optional[str] = None  # masked
    sms_ovh_service_name: Optional[str] = None  # e.g. "sms-xxxx-1"
    sms_ovh_sender: Optional[str] = None  # registered sender / "OVHSMS"

    # ----- PawaPay (mobile money payments) -----
    pawapay_enabled: Optional[bool] = None
    pawapay_api_token_sandbox: Optional[str] = None  # masked
    pawapay_api_token_production: Optional[str] = None  # masked
    pawapay_environment: Optional[str] = None  # "sandbox" | "production"
    pawapay_country: Optional[str] = None  # ISO-3 (e.g. "BFA")
    pawapay_callback_secret: Optional[str] = None  # masked — path token for /webhooks/pawapay/{secret}
    # legacy single key (kept for backwards-compat — not exposed in new UI)
    pawapay_api_token: Optional[str] = None

    # ----- VIDAL France — Médicaments / Monographies / Analyse de prescription (Iter41) -----
    # Two environments (test & production). The active one is picked by `vidal_mode`.
    vidal_enabled: Optional[bool] = None
    vidal_mode: Optional[str] = None  # "test" | "production"
    vidal_test_base_url: Optional[str] = None        # e.g. "https://api-test.vidal.net/rest/api"
    vidal_test_app_id: Optional[str] = None          # masked
    vidal_test_app_key: Optional[str] = None         # masked
    vidal_prod_base_url: Optional[str] = None        # e.g. "https://api.vidal.net/rest/api"
    vidal_prod_app_id: Optional[str] = None          # masked
    vidal_prod_app_key: Optional[str] = None         # masked
    # Cache & quota
    vidal_cache_ttl_hours: Optional[int] = None      # default 168 (7 days)
    vidal_quota_per_user_per_day: Optional[int] = None  # default 200 (0 = unlimited)
    # Timeout for HTTP calls (in seconds)
    vidal_http_timeout: Optional[int] = None         # default 12

    # ----- Iter41 Phase 3 (2026-02) — Synthèse programmée + API officines + sidebar image -----
    synthese_enabled: Optional[bool] = None
    synthese_email_to: Optional[str] = None
    synthese_wa_to: Optional[str] = None         # E.164 sans le +
    synthese_hour: Optional[str] = None          # "HH:MM"
    synthese_prompt: Optional[str] = None
    synthese_channels: Optional[str] = None      # "email" | "wa" | "both"
    officines_api_url: Optional[str] = None
    officines_api_token: Optional[str] = None    # masqué dans /admin/settings
    officines_api_timeout: Optional[int] = None
    officines_public_quota_per_day: Optional[int] = None  # quota /jour /numéro
    sidebar_bg_image_url: Optional[str] = None
    sidebar_bg_image_opacity: Optional[float] = None  # 0..1
    # Iter41 Phase 4 — HMAC secret used by /api/public/officines/register
    officines_register_hmac_secret: Optional[str] = None



    # ----- n8n Agenda Agent — bidirectional webhook for AI-driven RDV CRUD -----
    # Outbound: each manual create/update/delete fires a POST to this URL so
    # the n8n AI Agent can react, sync external calendars or notify users.
    # Inbound: n8n posts to /api/webhooks/agenda/{secret} to create/update/delete
    # appointments on behalf of the AI agent.
    agenda_n8n_outbound_enabled: Optional[bool] = None
    agenda_n8n_outbound_url: Optional[str] = None
    agenda_n8n_outbound_auth_type: Optional[str] = None  # none|bearer|basic
    agenda_n8n_outbound_token: Optional[str] = None  # secret — masked
    agenda_n8n_outbound_basic_user: Optional[str] = None
    agenda_n8n_outbound_basic_pass: Optional[str] = None  # secret — masked

    agenda_n8n_inbound_enabled: Optional[bool] = None
    agenda_n8n_inbound_secret: Optional[str] = None  # secret — masked. Path token for /webhooks/agenda/{secret}

    # ----- Authentication: OTP delivery mode -----
    # Comma-separated list of "internal domains" — emails ending with any of
    # these domains get their OTP displayed directly on the login page (no
    # SMTP). Everyone else receives it by email via the configured SMTP.
    # Use this for staff / in-house accounts to avoid email round-trips.
    internal_domains: Optional[str] = None  # e.g. "sawalismartsystems.com, sawali.local"

    # Forms / Contacts policy
    contacts_require_tag: Optional[bool] = None  # if True, every contact must have at least one tag

    # Version Stamp visual customization (footer pill on every layout)
    version_stamp_color: Optional[str] = None  # any CSS color (hex / rgb / oklch)
    version_stamp_size: Optional[str] = None   # xs | sm | md | lg
    version_stamp_opacity: Optional[int] = None  # 0..100
    version_stamp_style: Optional[str] = None  # normal | bold | italic | bold_italic

    # Iter36y — Auto-relance cron settings (cashier module)
    auto_relance_enabled: Optional[bool] = None  # master toggle
    auto_relance_day_of_week: Optional[int] = None  # 0=Mon .. 6=Sun
    auto_relance_grace_days: Optional[int] = None  # default 30
    auto_relance_email_report_to: Optional[str] = None  # admin email for HTML report

    # Iter43-fix20 (2026-06) — Weather widget (Open-Meteo).
    weather_widget_enabled: Optional[bool] = None        # master toggle
    weather_widget_show_public: Optional[bool] = None    # afficher sur site public
    weather_widget_show_portal: Optional[bool] = None    # afficher dans le portail
    weather_widget_default_city: Optional[str] = None    # fallback (ex: "Ouagadougou")
    weather_widget_default_country: Optional[str] = None  # code ISO 2 lettres (ex: "BF")

    # Iter43-fix23b (2026-06) — Bird.com 2-Way SMS (remplace Africa's Talking)
    bird_enabled: Optional[bool] = None          # toggle maître
    bird_api_base_url: Optional[str] = None      # défaut "https://api.bird.com"
    bird_workspace_id: Optional[str] = None      # UUID workspace Bird
    bird_channel_id: Optional[str] = None        # UUID channel SMS Bird
    bird_access_key: Optional[str] = None        # sensible — masqué
    bird_webhook_secret: Optional[str] = None    # sensible — masqué (HMAC SHA-256)
    bird_default_sender: Optional[str] = None    # sender ID / long number
    bird_signature: Optional[str] = None         # signature texte à ajouter à chaque réponse
    bird_use_liluvine: Optional[bool] = None     # router les SMS vers Liluvine
    # Iter43-fix24d (2026-06) — Estimation de coût Bird
    bird_cost_per_sms_xof: Optional[float] = None  # défaut 25 XOF/SMS (~0.04 EUR)
    bird_cost_currency: Optional[str] = None       # défaut "XOF"

    # Iter43-fix23 (2026-06) — Bearer token pour le webhook d'inventaire officines
    officines_inventory_webhook_token: Optional[str] = None  # sensible — masqué en GET

    # Iter43-fix24e (2026-06) — URL publique du backend (utilisée pour les CopyableUrl webhooks)
    public_base_url: Optional[str] = None  # ex: "https://sawalismartsystems.com"

    # Iter43-fix24ai (2026-06-17) — Template configurable pour `!garde` WhatsApp.
    # Syntaxe: `{champ}` (texte), `[champ]` (lien cliquable). Séparateurs = espace
    # entre champs, \n entre lignes d'une officine. Plusieurs officines séparées
    # par \n\n (auto-géré). Voir `_render_garde_officine` dans liluvine_wa_autoreply.
    garde_reply_header: Optional[str] = None
    garde_reply_template: Optional[str] = None
    # Iter43-fix24al (2026-06-17) — Footer + URL site + image capture pour !garde WA.
    # `garde_reply_footer` : texte affiché en bas (avant le lien site).
    # `garde_reply_site_url` : URL toujours envoyée à la fin du message texte.
    # `garde_reply_image_url` : URL HTTPS ou data:image/...;base64 — envoyée en
    #                            deuxième message WhatsApp (type=image).
    # `garde_reply_image_caption` : Légende sous l'image envoyée.
    garde_reply_footer: Optional[str] = None
    garde_reply_site_url: Optional[str] = None
    garde_reply_image_url: Optional[str] = None
    garde_reply_image_caption: Optional[str] = None

    # Iter43-fix24ap (2026-06-17) — Monitoring intégrations (Google Cal + Meta WA Webhook).
    # `integration_health_alerts_enabled` : active les alertes WhatsApp (défaut: True).
    # `integration_health_alert_wa_phone` : numéro WhatsApp E.164 à notifier en cas d'incident.
    integration_health_alerts_enabled: Optional[bool] = None
    integration_health_alert_wa_phone: Optional[str] = None

    # Iter43-fix24aq (2026-06-17) — Image envoyée par défaut après TOUTE réponse
    # à une commande WhatsApp (!garde, !produits, !adresse, etc.). Une image
    # spécifique par commande peut surcharger via `wa_cmd_<id>_image_url`.
    wa_default_cmd_image_url: Optional[str] = None
    wa_default_cmd_image_caption: Optional[str] = None

    # Iter43-fix24ak (2026-06-17) — Personnalisation de la page publique /garde.
    # `garde_page_header` : texte affiché en haut (ex: "Joyeux Noël !").
    # `garde_page_footer` : texte affiché en bas (ex: "Prompt rétablissement!").
    # `garde_page_image_url` : URL d'une capture/illustration cliquable affichée
    #                          en bas (pointe vers https://sawalismartsystems.com).
    # `garde_page_image_caption` : Légende sous l'image.
    garde_page_header: Optional[str] = None
    garde_page_footer: Optional[str] = None
    garde_page_image_url: Optional[str] = None
    garde_page_image_caption: Optional[str] = None

    # Iter43-fix24az-d (2026-02-26) — Garde rotation schedule toggle.
    # "saturday_noon" (défaut nouveau) : rotation Samedi 12h00 (1 semaine
    # de garde du Samedi 12h00 au Samedi 12h00 suivant).
    # "monday_midnight" (legacy) : rotation Lundi 00h00 (semaine ISO 8601).
    garde_rotation_mode: Optional[str] = None

    # Iter43-fix24az-d — Google Maps API + biais pays pour le géocodage des
    # officines (Google Places + Google Geocode → fallback Nominatim).
    google_maps_api_key: Optional[str] = None
    geocode_country_bias: Optional[str] = None

    # Iter43-fix24az-f (2026-02-26) — Production module: default profit margin (%)
    # used by the Fabricant tenants. Editable from Production settings page.
    production_default_margin_pct: Optional[float] = None


class BlacklistedIPCreate(BaseModel):
    cidr: str  # supports single IP or CIDR like 192.168.1.0/24
    reason: Optional[str] = None


# ====================================================================
# REPORTS & SUIVIS — user-authored notes with rich text content
# Stored per authenticated user (client / superviseur / admin / tracked-user via portal)
# ====================================================================
class TaskItem(BaseModel):
    """Iter38r-fix9k — A single checklist item (Google Keep style)."""
    id: Optional[str] = None  # client-side uuid, server generates if missing
    text: str
    done: bool = False
    order: int = 0
    done_at: Optional[str] = None


class UserNoteCreate(BaseModel):
    title: str
    content_html: Optional[str] = ""
    tags: Optional[List[str]] = None
    client_id: Optional[str] = None  # required for suivis (validated server-side)
    event_date: Optional[str] = None  # ISO datetime ; required for suivis
    images: Optional[List[dict]] = None  # max 10
    is_private: Optional[bool] = None  # True → only the author + targets + admins; False/None → shared within client
    # Iter35m — Targeted visibility (only meaningful when is_private=True).
    # When non-empty, the listed user_ids can see this note in addition to the
    # author and admin/superviseur. Empty list = author+admins only (legacy).
    target_user_ids: Optional[List[str]] = None
    voice_note_url: Optional[str] = None  # iter34y — note vocale facultative
    voice_note_transcript: Optional[str] = None  # iter34z — transcription Whisper
    # Iter38r-fix9k — Checklist items (Google Keep style) for kind=tasks
    task_items: Optional[List[TaskItem]] = None
    # Iter43 — Partage tenant cross-utilisateur (société + rattachement)
    shared_with_tenant: Optional[bool] = None
    editable_by_tenant: Optional[bool] = None


class UserNoteUpdate(BaseModel):
    title: Optional[str] = None
    content_html: Optional[str] = None
    tags: Optional[List[str]] = None
    client_id: Optional[str] = None
    event_date: Optional[str] = None
    images: Optional[List[dict]] = None
    is_private: Optional[bool] = None
    target_user_ids: Optional[List[str]] = None  # Iter35m
    voice_note_url: Optional[str] = None
    voice_note_transcript: Optional[str] = None
    task_items: Optional[List[TaskItem]] = None  # Iter38r-fix9k
    # Iter43 — Partage tenant cross-utilisateur
    shared_with_tenant: Optional[bool] = None
    editable_by_tenant: Optional[bool] = None


class RatingCreate(BaseModel):
    stars: int  # 1..5
    comment: Optional[str] = None


class AccessLogCreate(BaseModel):
    module: str
    page: Optional[str] = None


class ApiTraceCreate(BaseModel):
    method: str
    url: str
    status: int
    request_body: Optional[Any] = None
    response_body: Optional[Any] = None
    duration_ms: Optional[int] = None
    module: Optional[str] = None  # frontend route label
    error: Optional[str] = None



# ====================================================================
# FORMATIONS (Specialized Trainings)
# ====================================================================
class FormationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    available: bool = True
    access: str = "free"  # free | paid
    price: Optional[float] = None
    default_credits: int = 0  # credits granted on enrollment
    cover_image_url: Optional[str] = None
    # 2026-02 fork (P5) — Liste d'accessibilité stricte. Si non-vide, seuls
    # les tracked users dont `parent_client_id` ∈ liste (ou root ∈ liste)
    # peuvent voir cette formation. Vide/None → comportement historique
    # (visible par tout utilisateur suivi si `available=True`).
    access_client_ids: Optional[List[str]] = None


class FormationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    available: Optional[bool] = None
    access: Optional[str] = None
    price: Optional[float] = None
    default_credits: Optional[int] = None
    cover_image_url: Optional[str] = None
    access_client_ids: Optional[List[str]] = None


class FormationModuleCreate(BaseModel):
    name: str
    order: int = 0
    screenshot_url: Optional[str] = None
    software_path: Optional[str] = None
    content_html: Optional[str] = ""
    api_url: Optional[str] = None  # external REST POST endpoint for Q/A
    api_auth_type: Optional[str] = "none"  # none | bearer | basic
    api_token: Optional[str] = None
    api_basic_user: Optional[str] = None
    api_basic_pass: Optional[str] = None


class FormationModuleUpdate(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None
    screenshot_url: Optional[str] = None
    software_path: Optional[str] = None
    content_html: Optional[str] = None
    api_url: Optional[str] = None
    api_auth_type: Optional[str] = None
    api_token: Optional[str] = None
    api_basic_user: Optional[str] = None
    api_basic_pass: Optional[str] = None


class FormationCreditsUpdate(BaseModel):
    credits_delta: int  # positive to add, negative to remove


class FormationStateUpdate(BaseModel):
    state: str  # only "annulée" allowed for admins to set manually


class FormationModuleQuestion(BaseModel):
    question: str
    payload: Optional[dict] = None  # extra fields forwarded to the module's api_url



# =====================================================================
# Iter35o — Support tickets (intervention tickets opened from WA chat)
# =====================================================================
class TicketOpenPayload(BaseModel):
    motif: str  # 1..200 chars — required, brief description of the issue
    # Iter36k — Client lié explicitement choisi par l'utilisateur (dropdown).
    # Si absent ou vide, le backend refuse la création (plus de fallback auto
    # sur le client_id du contact, qui était souvent erroné).
    client_id: Optional[str] = None
    # Iter38p — When True, force-close any open ticket blocking creation for
    # this contact (orphan or stuck). Marked as `outcome="force_released"`.
    force_release: Optional[bool] = False


class TicketUpdatePayload(BaseModel):
    status: Optional[str] = None  # open|in_progress|suspended (closing uses /close)
    motif: Optional[str] = None
    notes: Optional[str] = None
    # 0-4 (2026-02) — Admin / supervisor can re-attach a ticket to a
    # different client (tenant). Must be a real user from the same group.
    client_id: Optional[str] = None


class TicketClosePayload(BaseModel):
    outcome: str  # "done" or "cancelled"
    resolution_note: Optional[str] = None
    notify_contact: Optional[bool] = None  # override admin default


# Iter35p — Ticket enhancements
class TicketAssignPayload(BaseModel):
    user_id: Optional[str] = None  # None / "" → unassign


class TicketReopenPayload(BaseModel):
    motif: Optional[str] = None  # if empty, reuse parent's motif


class TicketMotifTemplatePayload(BaseModel):
    label: str  # short button label (e.g. "Panne onduleur")
    motif: str  # the actual motif text injected when picked
