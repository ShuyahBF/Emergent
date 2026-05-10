"""Pydantic models for SAWALI SMART SYSTEMS API."""
from datetime import datetime, timezone
from typing import Optional, List, Any
from pydantic import BaseModel, Field, EmailStr, ConfigDict
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    # iter32 — Optional canonical-link hint sent by the admin form. When
    # present, the new user's `client_id` and `parent_client_id` are aligned
    # to the given canonical client (same company), preventing the "user
    # creates a fresh root that nobody else sees" footgun.
    link_to_client_id: Optional[str] = None


class UserUpdateAdmin(BaseModel):
    full_name: Optional[str] = None
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


USER_ROLES = ["client", "admin", "superviseur"]


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


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None  # pending|confirmed|cancelled|completed
    notes: Optional[str] = None
    scheduled_at: Optional[str] = None
    duration_min: Optional[int] = None
    subject: Optional[str] = None
    message: Optional[str] = None


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


class InterventionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    intervention_date: Optional[str] = None
    technician: Optional[str] = None
    duration_hours: Optional[float] = None
    attachments: Optional[List[str]] = None
    images: Optional[List[dict]] = None


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


# ====================================================================
# CMS CONTENT (mission, about, specialisations, etc.)
# ====================================================================
class ContentUpsert(BaseModel):
    slug: str  # mission|about|specialisations|experience|home_hero|...
    title: str
    body_html: str = ""
    images: List[str] = []
    metadata: dict = {}


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
TRACKED_USER_ROLES = ["Consultation", "Edition", "Moderation", "Administrateur", "Superviseur"]


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
    recaptcha_site_key: Optional[str] = None
    recaptcha_secret_key: Optional[str] = None
    recaptcha_enabled: Optional[bool] = None

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
    smtp_use_tls: Optional[bool] = None

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
    health_webhook_url: Optional[str] = None
    health_webhook_auth_type: Optional[str] = None  # none | bearer | basic
    health_webhook_token: Optional[str] = None
    health_webhook_basic_user: Optional[str] = None
    health_webhook_basic_pass: Optional[str] = None
    health_email_to: Optional[str] = None  # default: SUPER_ADMIN_EMAIL
    health_timezone: Optional[str] = None  # default Africa/Abidjan

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


class BlacklistedIPCreate(BaseModel):
    cidr: str  # supports single IP or CIDR like 192.168.1.0/24
    reason: Optional[str] = None


# ====================================================================
# REPORTS & SUIVIS — user-authored notes with rich text content
# Stored per authenticated user (client / superviseur / admin / tracked-user via portal)
# ====================================================================
class UserNoteCreate(BaseModel):
    title: str
    content_html: Optional[str] = ""
    tags: Optional[List[str]] = None
    client_id: Optional[str] = None  # required for suivis (validated server-side)
    event_date: Optional[str] = None  # ISO datetime ; required for suivis
    images: Optional[List[dict]] = None  # max 10
    is_private: Optional[bool] = None  # True → only the author + admins; False/None → shared within client


class UserNoteUpdate(BaseModel):
    title: Optional[str] = None
    content_html: Optional[str] = None
    tags: Optional[List[str]] = None
    client_id: Optional[str] = None
    event_date: Optional[str] = None
    images: Optional[List[dict]] = None
    is_private: Optional[bool] = None


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


class FormationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    available: Optional[bool] = None
    access: Optional[str] = None
    price: Optional[float] = None
    default_credits: Optional[int] = None
    cover_image_url: Optional[str] = None


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