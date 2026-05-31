"""Iter38r-fix9o (Items 6 + 8) — Tests for the Tickets Bubble & WA OTP login.

Covers:
- POST /me/tickets quick-create endpoint (creates contact + ticket)
- GET /me/intervention-reasons preset list
- POST /auth/wa-otp/request validates msisdn + WA config presence
- POST /auth/wa-otp/verify rejects bad code & expired sessions
- GET /admin/wa-demo/recent + welcome-briefing widget for admin
- ClientFeaturesUpdate accepts `tickets_bubble`
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASS = "Admin@Sawali2026"


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10).json()
    if r.get("needs_otp"):
        r = requests.post(f"{API}/auth/verify-otp",
                          json={"session_token": r["session_token"], "code": r["dev_otp"]},
                          timeout=10).json()
    token = r.get("access_token") or r.get("token")
    assert token, f"login failed: {r}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_id(admin_h):
    r = requests.get(f"{API}/auth/me", headers=admin_h, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


# ---------- GET /me/intervention-reasons ----------

def test_intervention_reasons_returns_defaults(admin_h):
    r = requests.get(f"{API}/me/intervention-reasons", headers=admin_h, timeout=10)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    assert len(items) >= 5
    assert all("label" in x and "id" in x for x in items)


# ---------- POST /me/tickets (quick-create) ----------

def test_quick_ticket_requires_client_id(admin_h):
    r = requests.post(f"{API}/me/tickets", headers=admin_h, json={
        "client_id": "",
        "reason": "Logiciel bloqué",
    }, timeout=10)
    assert r.status_code in (400, 422)


def test_quick_ticket_requires_reason(admin_h, admin_id):
    r = requests.post(f"{API}/me/tickets", headers=admin_h, json={
        "client_id": admin_id,
        "reason": "  ",
    }, timeout=10)
    assert r.status_code == 400


def test_quick_ticket_creates_contact_and_ticket(admin_h, admin_id, db_sync):
    phone = f"+2267{uuid.uuid4().int % 10000000:07d}"
    digits = phone.lstrip("+")
    db_sync.directory_contacts.delete_many({"phone_digits": digits})
    payload = {
        "client_id": admin_id,
        "reason": "Demande de formation",
        "contact_name": "Test Bubble",
        "contact_phone": phone,
        "contact_whatsapp": phone,
        "incident_at": datetime.now(timezone.utc).isoformat(),
        "software": "SAWALI Caisse",
        "notes": "Créé via la bulle",
        "attach_wa_sms_history": True,
    }
    r = requests.post(f"{API}/me/tickets", headers=admin_h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["id"]
    assert body["ticket"]["motif"] == "Demande de formation"
    assert body["ticket"]["software"] == "SAWALI Caisse"
    assert body["ticket"]["attach_wa_sms_history"] is True
    assert body["ticket"]["source"] == "tickets_bubble"
    # Contact was created
    c = db_sync.directory_contacts.find_one({"phone_digits": digits})
    assert c is not None
    assert c["client_id"] == admin_id
    assert "Ticket bubble" in (c.get("tags") or [])
    # Cleanup
    db_sync.support_tickets.delete_one({"id": body["id"]})
    db_sync.directory_contacts.delete_many({"phone_digits": digits})


def test_quick_ticket_accepts_whatsapp_only(admin_h, admin_id, db_sync):
    """Iter38r-fix9o v2: WhatsApp without a phone is enough — backend
    treats WA as the phone for the contact lookup/creation."""
    wa = f"+2267{uuid.uuid4().int % 10000000:07d}"
    digits = wa.lstrip("+")
    db_sync.directory_contacts.delete_many({"phone_digits": digits})
    r = requests.post(f"{API}/me/tickets", headers=admin_h, json={
        "client_id": admin_id, "reason": "Test WA only",
        "contact_name": "WA Only",
        "contact_whatsapp": wa,
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # Cleanup
    db_sync.support_tickets.delete_one({"id": body["id"]})
    db_sync.directory_contacts.delete_many({"phone_digits": digits})


def test_quick_ticket_reuses_existing_contact(admin_h, admin_id, db_sync):
    phone = f"+2267{uuid.uuid4().int % 10000000:07d}"
    digits = phone.lstrip("+")
    existing_cid = str(uuid.uuid4())
    db_sync.directory_contacts.insert_one({
        "id": existing_cid, "client_id": admin_id, "phone_digits": digits,
        "phone": phone, "whatsapp": phone, "name": "Existing",
        "owner_id": admin_id, "tags": ["VIP"], "shared": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.post(f"{API}/me/tickets", headers=admin_h, json={
        "client_id": admin_id, "reason": "Logiciel bloqué",
        "contact_phone": phone,
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticket"]["contact_id"] == existing_cid
    # Cleanup
    db_sync.support_tickets.delete_one({"id": body["id"]})
    db_sync.directory_contacts.delete_one({"id": existing_cid})


# ---------- ClientFeaturesUpdate accepts tickets_bubble ----------

def test_client_features_update_accepts_tickets_bubble(admin_h, admin_id):
    r = requests.put(f"{API}/admin/clients/{admin_id}/features", headers=admin_h,
                     json={"tickets_bubble": True}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["features"]["tickets_bubble"] is True
    # /me/features exposes it (admin always sees True)
    r2 = requests.get(f"{API}/me/features", headers=admin_h, timeout=10)
    assert r2.status_code == 200
    assert r2.json()["features"]["tickets_bubble"] is True


# ---------- WhatsApp OTP login flow ----------

def test_wa_otp_request_validates_msisdn(admin_h):
    r = requests.post(f"{API}/auth/wa-otp/request", json={"msisdn": "123"}, timeout=10)
    assert r.status_code == 400


def test_wa_otp_request_needs_wa_config(db_sync):
    """When WA config keys are missing → 503."""
    # Wipe WA config snapshot before, then restore
    s = db_sync.settings.find_one({"_id": "global"}) or {}
    saved_at = s.get("wa_access_token")
    saved_pn = s.get("wa_phone_number_id")
    db_sync.settings.update_one(
        {"_id": "global"},
        {"$set": {"wa_access_token": "", "wa_phone_number_id": ""}},
        upsert=True,
    )
    try:
        r = requests.post(f"{API}/auth/wa-otp/request", json={"msisdn": "22670000000"}, timeout=10)
        assert r.status_code == 503
    finally:
        db_sync.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "wa_access_token": saved_at or "",
                "wa_phone_number_id": saved_pn or "",
            }},
        )


def test_wa_otp_verify_rejects_bad_code(db_sync):
    msisdn = "22670000001"
    db_sync.wa_otp_requests.update_one(
        {"msisdn": msisdn},
        {"$set": {
            "msisdn": msisdn, "code": "123456",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "attempts": 0,
        }},
        upsert=True,
    )
    try:
        r = requests.post(f"{API}/auth/wa-otp/verify",
                          json={"msisdn": msisdn, "code": "999999"}, timeout=10)
        assert r.status_code == 401
    finally:
        db_sync.wa_otp_requests.delete_one({"msisdn": msisdn})


def test_wa_otp_verify_expired(db_sync):
    msisdn = "22670000002"
    db_sync.wa_otp_requests.update_one(
        {"msisdn": msisdn},
        {"$set": {
            "msisdn": msisdn, "code": "123456",
            "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "attempts": 0,
        }},
        upsert=True,
    )
    try:
        r = requests.post(f"{API}/auth/wa-otp/verify",
                          json={"msisdn": msisdn, "code": "123456"}, timeout=10)
        assert r.status_code == 410
    finally:
        db_sync.wa_otp_requests.delete_one({"msisdn": msisdn})


def test_wa_otp_verify_success_creates_demo_user(db_sync):
    msisdn = f"2267{uuid.uuid4().int % 10000000:07d}"
    db_sync.wa_otp_requests.update_one(
        {"msisdn": msisdn},
        {"$set": {
            "msisdn": msisdn, "code": "246810",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "attempts": 0,
        }},
        upsert=True,
    )
    try:
        r = requests.post(f"{API}/auth/wa-otp/verify",
                          json={"msisdn": msisdn, "code": "246810",
                                "display_name": "Test WA Demo"}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["token"]
        assert body["user"]["is_demo"] is True
        # DEMO tenant created
        tenant = db_sync.users.find_one({"email": "demo@sawalismartsystems.com"})
        assert tenant is not None
        # Linked user has source=wa_otp_login
        u = db_sync.users.find_one({"phone_digits": msisdn})
        assert u is not None
        assert u["source"] == "wa_otp_login"
        assert u["is_demo"] is True
        assert u["parent_client_id"] == tenant["id"]
        # Mirror contact created
        c = db_sync.directory_contacts.find_one({"phone_digits": msisdn})
        # (may be in contacts or directory_contacts; route uses contacts collection)
        c2 = db_sync.contacts.find_one({"phone_digits": msisdn})
        assert (c or c2) is not None
    finally:
        db_sync.users.delete_many({"phone_digits": msisdn})
        db_sync.contacts.delete_many({"phone_digits": msisdn})
        db_sync.directory_contacts.delete_many({"phone_digits": msisdn})
        db_sync.wa_otp_requests.delete_one({"msisdn": msisdn})


# ---------- Admin dashboard widget ----------

def test_admin_wa_demo_recent_endpoint(admin_h, db_sync):
    # Seed two demo users
    mark = uuid.uuid4().hex[:6]
    ids = []
    for i in range(2):
        uid = str(uuid.uuid4())
        ids.append(uid)
        db_sync.users.insert_one({
            "id": uid, "email": f"wa-test-{mark}-{i}@x.local",
            "full_name": f"Demo {mark}-{i}", "phone_digits": f"99{mark}{i}",
            "role": "client", "source": "wa_otp_login", "is_demo": True,
            "wa_onboarding_seen_by": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    try:
        r = requests.get(f"{API}/admin/wa-demo/recent?limit=10", headers=admin_h, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 2
        assert body["unseen"] >= 2
        assert any(it["id"] in ids for it in body["items"])
    finally:
        db_sync.users.delete_many({"id": {"$in": ids}})


def test_welcome_briefing_includes_wa_demo(admin_h, db_sync):
    uid = str(uuid.uuid4())
    db_sync.users.insert_one({
        "id": uid, "email": f"wa-test-wb-{uid}@x.local",
        "full_name": "Demo Welcome", "phone_digits": "99888",
        "role": "client", "source": "wa_otp_login", "is_demo": True,
        "wa_onboarding_seen_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.get(f"{API}/me/welcome-briefing", headers=admin_h, timeout=10)
        assert r.status_code == 200
        wd = r.json().get("wa_demo_recent")
        assert wd is not None
        assert wd["total"] >= 1
    finally:
        db_sync.users.delete_one({"id": uid})


def test_admin_wa_demo_mark_seen(admin_h, db_sync):
    uid = str(uuid.uuid4())
    db_sync.users.insert_one({
        "id": uid, "email": f"wa-test-ms-{uid}@x.local",
        "full_name": "Demo Mark", "phone_digits": "99777",
        "role": "client", "source": "wa_otp_login", "is_demo": True,
        "wa_onboarding_seen_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(f"{API}/admin/wa-demo/{uid}/mark-seen", headers=admin_h, timeout=10)
        assert r.status_code == 200, r.text
        u = db_sync.users.find_one({"id": uid})
        assert u["wa_onboarding_seen_by"] is not None
        assert u["wa_onboarding_seen_at"] is not None
    finally:
        db_sync.users.delete_one({"id": uid})
