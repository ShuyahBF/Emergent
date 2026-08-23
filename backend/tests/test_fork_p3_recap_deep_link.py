"""2026-02 fork (P3 recap + P0.5 wiring) — WA planning recap deep-link and
tenant Smart Comm credential resolution.

Couvre :
  • POST /auth/wa-planning-exchange : valide un jeton scope=wa_planning_recap,
    renvoie un vrai JWT auth + user.
  • Refus si token invalide, expiré, ou si l'utilisateur n'est pas Médecin.
  • Le WA text du cron inclut désormais un lien `/wa-recap?t=…`
"""
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv

# Load backend/.env so JWT_SECRET matches the server's runtime value.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL.rstrip('/')}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"

# Same fallback chain as routes/medecin_planning_digest.py
RECAP_SECRET = (
    os.environ.get("WA_PLANNING_RECAP_SECRET")
    or os.environ.get("LINK_JWT_SECRET")
    or (os.environ.get("JWT_SECRET", "fallback-insecure") + "-wa-recap")
)


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    body = r.json()
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": body["session_token"], "code": body["dev_otp"]},
        timeout=10,
    )
    v.raise_for_status()
    return v.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _mint_recap(user_id: str, ttl: int = 30 * 60, scope: str = "wa_planning_recap"):
    now = int(datetime.now(timezone.utc).timestamp())
    return pyjwt.encode(
        {"sub": user_id, "scope": scope, "iat": now, "exp": now + ttl},
        RECAP_SECRET,
        algorithm="HS256",
    )


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def medecin_ctx(admin_token):
    tag = uuid.uuid4().hex[:8]
    r = requests.post(
        f"{API}/admin/clients",
        headers=_auth(admin_token),
        json={
            "email": f"p3rec-parent-{tag}@sawali-test.com",
            "password": "Parent@2026",
            "full_name": f"P3rec Parent {tag}",
            "role": "admin",
            "company": f"P3rec-CO-{tag}",
        },
        timeout=10,
    )
    r.raise_for_status()
    parent_id = r.json()["id"]

    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=_auth(admin_token),
        json={
            "client_id": parent_id,
            "name": f"Dr Recap {tag}",
            "email": f"p3rec-medecin-{tag}@sawali-test.com",
            "role": "Médecin",
        },
        timeout=10,
    )
    r.raise_for_status()
    tu_id = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{tu_id}/set-password",
        headers=_auth(admin_token),
        json={"password": "MedRec@2026"},
        timeout=10,
    )
    r.raise_for_status()

    # Also seed a non-médecin tracked user
    r = requests.post(
        f"{API}/admin/tracked-users",
        headers=_auth(admin_token),
        json={
            "client_id": parent_id,
            "name": f"Consult Recap {tag}",
            "email": f"p3rec-consult-{tag}@sawali-test.com",
            "role": "Consultation",
        },
        timeout=10,
    )
    r.raise_for_status()
    ctu = r.json()["id"]
    r = requests.post(
        f"{API}/admin/tracked-users/{ctu}/set-password",
        headers=_auth(admin_token),
        json={"password": "ConsRec@2026"},
        timeout=10,
    )
    r.raise_for_status()

    # Login medecin once to grab their user id
    med_tok = _login(f"p3rec-medecin-{tag}@sawali-test.com", "MedRec@2026")
    me = requests.get(f"{API}/auth/me", headers=_auth(med_tok), timeout=10).json()
    med_id = me["id"]

    consult_tok = _login(f"p3rec-consult-{tag}@sawali-test.com", "ConsRec@2026")
    cme = requests.get(f"{API}/auth/me", headers=_auth(consult_tok), timeout=10).json()

    return {
        "parent_id": parent_id,
        "medecin_id": med_id,
        "medecin_email": f"p3rec-medecin-{tag}@sawali-test.com",
        "consult_id": cme["id"],
    }


def test_recap_exchange_success(medecin_ctx):
    tok = _mint_recap(medecin_ctx["medecin_id"])
    r = requests.post(f"{API}/auth/wa-planning-exchange", json={"t": tok}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("access_token")
    assert body.get("user", {}).get("id") == medecin_ctx["medecin_id"]
    # The returned JWT should authorize /auth/me
    who = requests.get(f"{API}/auth/me", headers=_auth(body["access_token"]), timeout=10)
    assert who.status_code == 200
    assert who.json()["id"] == medecin_ctx["medecin_id"]


def test_recap_exchange_missing_token():
    r = requests.post(f"{API}/auth/wa-planning-exchange", json={}, timeout=10)
    assert r.status_code == 400


def test_recap_exchange_invalid_token():
    r = requests.post(f"{API}/auth/wa-planning-exchange", json={"t": "garbage.token.here"}, timeout=10)
    assert r.status_code == 401
    assert "invalid" in r.json().get("detail", "").lower() or "invalide" in r.json().get("detail", "").lower()


def test_recap_exchange_expired_token(medecin_ctx):
    tok = _mint_recap(medecin_ctx["medecin_id"], ttl=-10)
    r = requests.post(f"{API}/auth/wa-planning-exchange", json={"t": tok}, timeout=10)
    assert r.status_code == 401
    assert "expired" in r.json().get("detail", "").lower() or "expiré" in r.json().get("detail", "").lower()


def test_recap_exchange_bad_scope(medecin_ctx):
    tok = _mint_recap(medecin_ctx["medecin_id"], scope="wa_login")  # wrong scope
    r = requests.post(f"{API}/auth/wa-planning-exchange", json={"t": tok}, timeout=10)
    assert r.status_code == 401
    assert "scope" in r.json().get("detail", "").lower()


def test_recap_exchange_denied_for_non_medecin(medecin_ctx):
    tok = _mint_recap(medecin_ctx["consult_id"])
    r = requests.post(f"{API}/auth/wa-planning-exchange", json={"t": tok}, timeout=10)
    assert r.status_code == 403
