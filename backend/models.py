"""Pydantic models for SAWALI SMART SYSTEMS API."""
from datetime import datetime, timezone
from typing import Optional, List
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
    role: str = "Consultation"  # one of TRACKED_USER_ROLES
    department: Optional[str] = None
    last_seen: Optional[str] = None
    status: str = "active"


class TrackedUserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    department: Optional[str] = None
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


class UserNoteUpdate(BaseModel):
    title: Optional[str] = None
    content_html: Optional[str] = None
    tags: Optional[List[str]] = None
    client_id: Optional[str] = None
    event_date: Optional[str] = None
    images: Optional[List[dict]] = None


class RatingCreate(BaseModel):
    stars: int  # 1..5
    comment: Optional[str] = None


class AccessLogCreate(BaseModel):
    module: str
    page: Optional[str] = None



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
