"""S045 Phase 1 (2026-02) — Regression suite for the extracted /auth/* routes.

These tests are the new contract for the auth module after extracting it
from server.py into routes/auth.py. ZERO behavior change expected.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from passlib.hash import bcrypt

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def internal_user(db):
    """Create an internal-domain user (sawalismartsystems.com) so login
    returns dev_otp directly (no SMTP needed)."""
    uid = f"auth_{uuid.uuid4().hex[:8]}"
    email = f"{uid}@sawalismartsystems.com"
    pwd = "MySecret@2026!"
    db.users.insert_one({
        "id": uid, "email": email,
        "password_hash": bcrypt.hash(pwd),
        "full_name": "Auth Refactor Test",
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": uid, "email": email, "password": pwd}
    db.users.delete_many({"id": uid})
    db.otps.delete_many({"user_id": uid})


def test_captcha_config_public_endpoint():
    r = requests.get(f"{API}/auth/captcha-config", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body and "site_key" in body


def test_login_invalid_credentials():
    r = requests.post(f"{API}/auth/login", json={
        "email": "doesnotexist@sawalismartsystems.com",
        "password": "wrong",
        "captcha_token": "",
    }, timeout=10)
    assert r.status_code == 401
    assert "Identifiants invalides" in r.json().get("detail", "")


def test_login_internal_domain_returns_dev_otp(internal_user):
    r = requests.post(f"{API}/auth/login", json={
        "email": internal_user["email"],
        "password": internal_user["password"],
        "captcha_token": "",
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["needs_otp"] is True
    assert body["dev_otp"]  # internal domain reveals the OTP
    assert "Plateforme Interne" in body["message"]
    assert body["session_token"]


def test_verify_otp_full_flow(internal_user):
    # Login → get session + dev_otp
    r = requests.post(f"{API}/auth/login", json={
        "email": internal_user["email"],
        "password": internal_user["password"],
        "captcha_token": "",
    }, timeout=15)
    body = r.json()
    session = body["session_token"]
    otp = body["dev_otp"]
    # Verify OTP
    r2 = requests.post(f"{API}/auth/verify-otp", json={
        "session_token": session, "code": otp,
    }, timeout=15)
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == internal_user["email"]
    # /auth/me with the token
    r3 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}, timeout=10)
    assert r3.status_code == 200
    assert r3.json()["email"] == internal_user["email"]


def test_verify_otp_bad_session():
    r = requests.post(f"{API}/auth/verify-otp", json={
        "session_token": "NON_EXISTENT", "code": "123456",
    }, timeout=10)
    assert r.status_code == 400
    assert "Session invalide" in r.json().get("detail", "")


def test_verify_otp_bad_code(internal_user):
    r = requests.post(f"{API}/auth/login", json={
        "email": internal_user["email"], "password": internal_user["password"],
        "captcha_token": "",
    }, timeout=15)
    session = r.json()["session_token"]
    r2 = requests.post(f"{API}/auth/verify-otp", json={
        "session_token": session, "code": "000000",
    }, timeout=10)
    assert r2.status_code == 400
    assert "Code incorrect" in r2.json().get("detail", "")


def test_change_password(internal_user):
    # Login first
    r = requests.post(f"{API}/auth/login", json={
        "email": internal_user["email"], "password": internal_user["password"],
        "captcha_token": "",
    }, timeout=15)
    body = r.json()
    r2 = requests.post(f"{API}/auth/verify-otp", json={
        "session_token": body["session_token"], "code": body["dev_otp"],
    }, timeout=10)
    token = r2.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Change password
    new_pwd = "NewSecret@2026!"
    r3 = requests.post(f"{API}/auth/change-password", headers=headers, json={
        "current_password": internal_user["password"],
        "new_password": new_pwd,
    }, timeout=10)
    assert r3.status_code == 200
    assert r3.json()["ok"] is True
    # Old password should now fail
    r4 = requests.post(f"{API}/auth/login", json={
        "email": internal_user["email"], "password": internal_user["password"],
        "captcha_token": "",
    }, timeout=10)
    assert r4.status_code == 401
    # New password should work
    r5 = requests.post(f"{API}/auth/login", json={
        "email": internal_user["email"], "password": new_pwd,
        "captcha_token": "",
    }, timeout=10)
    assert r5.status_code == 200


def test_change_password_wrong_current(internal_user):
    r = requests.post(f"{API}/auth/login", json={
        "email": internal_user["email"], "password": internal_user["password"],
        "captcha_token": "",
    }, timeout=15)
    body = r.json()
    r2 = requests.post(f"{API}/auth/verify-otp", json={
        "session_token": body["session_token"], "code": body["dev_otp"],
    }, timeout=10)
    token = r2.json()["access_token"]
    r3 = requests.post(f"{API}/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "WRONG", "new_password": "Any@2026!"}, timeout=10)
    assert r3.status_code == 400
    assert "incorrect" in r3.json().get("detail", "").lower()


def test_me_without_token():
    r = requests.get(f"{API}/auth/me", timeout=10)
    assert r.status_code in (401, 403)


def test_resend_otp(internal_user):
    r = requests.post(f"{API}/auth/login", json={
        "email": internal_user["email"], "password": internal_user["password"],
        "captcha_token": "",
    }, timeout=15)
    session = r.json()["session_token"]
    r2 = requests.post(f"{API}/auth/resend-otp?session_token={session}", timeout=10)
    assert r2.status_code == 200
    assert "dev_otp" in r2.json()


def test_resend_otp_bad_session():
    r = requests.post(f"{API}/auth/resend-otp?session_token=NON_EXISTENT", timeout=10)
    assert r.status_code == 400
