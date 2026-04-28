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


class UserCreateAdmin(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "client"  # client | admin
    phone: Optional[str] = None
    company: Optional[str] = None
    client_code: Optional[str] = None  # short code, used for intervention numbering
    account_status: str = "active"


class UserUpdateAdmin(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    client_code: Optional[str] = None
    account_status: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


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


class InterventionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    intervention_date: Optional[str] = None
    technician: Optional[str] = None
    duration_hours: Optional[float] = None
    attachments: Optional[List[str]] = None


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
