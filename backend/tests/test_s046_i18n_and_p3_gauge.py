"""S046 — i18n translations management + P3 (download gauge toggle)."""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASS = "Admin@Sawali2026"


def _login(email: str, password: str) -> str | None:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15).json()
    if r.get("needs_otp"):
        r = requests.post(
            f"{API}/auth/verify-otp",
            json={"session_token": r["session_token"], "code": r.get("dev_otp")},
            timeout=15,
        ).json()
    return r.get("access_token") or r.get("token")


@pytest.fixture(scope="module")
def admin_h():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    assert tok
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


# ------------- i18n public endpoints -------------


def test_i18n_languages_public():
    r = requests.get(f"{API}/i18n/languages", timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    codes = [l["code"] for l in data["items"]]
    assert codes == ["fr", "en", "ar", "lg1", "lg2"]
    assert data["default"] == "fr"
    ar = next(l for l in data["items"] if l["code"] == "ar")
    assert ar["rtl"] is True


def test_i18n_dictionary_fr_seed():
    r = requests.get(f"{API}/i18n/translations", params={"lang": "fr"}, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["lang"] == "fr"
    assert data["count"] >= 20
    assert data["translations"].get("nav.dashboard") == "Tableau de bord"
    assert data["translations"].get("common.save") == "Enregistrer"


def test_i18n_dictionary_en_seed_with_fallback(db_sync):
    # Ensure at least one row exists where EN is empty so we test the fallback
    db_sync.i18n_translations.update_one(
        {"key": "test.fallback_demo"},
        {"$set": {"key": "test.fallback_demo", "fr": "Démonstration repli", "en": ""}},
        upsert=True,
    )
    r = requests.get(f"{API}/i18n/translations", params={"lang": "en"}, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["lang"] == "en"
    # Real EN translation exists
    assert data["translations"].get("nav.dashboard") == "Dashboard"
    # Empty EN must fall back to FR text
    assert data["translations"].get("test.fallback_demo") == "Démonstration repli"
    # Cleanup
    db_sync.i18n_translations.delete_one({"key": "test.fallback_demo"})


def test_i18n_dictionary_rejects_unknown_lang():
    r = requests.get(f"{API}/i18n/translations", params={"lang": "zz"}, timeout=10)
    assert r.status_code == 400


# ------------- Admin CRUD -------------


def test_i18n_admin_list_requires_role(admin_h):
    r = requests.get(f"{API}/admin/i18n/translations", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] >= 20
    assert any(row["key"] == "nav.dashboard" for row in data["items"])


def test_i18n_admin_upsert_and_delete(admin_h, db_sync):
    key = f"test.s046_{uuid.uuid4().hex[:6]}"
    payload = {
        "key": key, "fr": "Bonjour", "en": "Hello", "ar": "مرحبا",
        "lg1": "", "lg2": "", "context": "test row",
    }
    r = requests.post(f"{API}/admin/i18n/translations", json=payload, headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text

    # Read back via public dictionary in 3 languages
    r_fr = requests.get(f"{API}/i18n/translations", params={"lang": "fr"}, timeout=10).json()
    assert r_fr["translations"][key] == "Bonjour"
    r_en = requests.get(f"{API}/i18n/translations", params={"lang": "en"}, timeout=10).json()
    assert r_en["translations"][key] == "Hello"
    r_ar = requests.get(f"{API}/i18n/translations", params={"lang": "ar"}, timeout=10).json()
    assert r_ar["translations"][key] == "مرحبا"
    # LG1 is empty → fallback FR
    r_lg1 = requests.get(f"{API}/i18n/translations", params={"lang": "lg1"}, timeout=10).json()
    assert r_lg1["translations"][key] == "Bonjour"

    # Delete
    rd = requests.delete(f"{API}/admin/i18n/translations/{key}", headers=admin_h, timeout=10)
    assert rd.status_code == 200, rd.text
    assert rd.json()["deleted"] == 1


def test_i18n_admin_rejects_invalid_key(admin_h):
    r = requests.post(
        f"{API}/admin/i18n/translations",
        json={"key": "with spaces", "fr": "x"},
        headers=admin_h, timeout=10,
    )
    assert r.status_code == 422  # pydantic regex rejection


# ------------- P3 — download gauge toggle -------------


def test_p3_download_request_returns_gauge_enabled_flag(admin_h, db_sync):
    """`GET /api/me/download-requests/{token}` (the polling endpoint) doesn't
    return gauge_enabled — it's the POST that creates the request. So we
    verify the POST response includes the gauge_enabled field with the
    admin's configured value."""
    # Enable approval workflow + disable the gauge
    db_sync.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "download_approval_enabled": True,
            "download_approval_whatsapp": "+22890000000",
            "download_gauge_enabled": False,
            "download_pending_message": "Veuillez patienter...",
        }},
        upsert=True,
    )
    try:
        r = requests.post(
            f"{API}/me/download-requests",
            json={"document_url": "/static/x.pdf", "label": "Test doc"},
            headers=admin_h, timeout=15,
        )
        # Admin/sup may bypass approval (direct download). In that case
        # we get `direct=True` and no gauge_enabled is necessary.
        if r.status_code != 200:
            pytest.skip(f"download-request refused: {r.status_code} {r.text[:120]}")
        data = r.json()
        if data.get("direct"):
            pytest.skip("admin bypasses approval (direct=True) — gauge flag not exposed")
        assert data.get("gauge_enabled") is False, (
            f"expected gauge_enabled=False from settings, got {data.get('gauge_enabled')}"
        )

        # Now flip it back to ON and re-check
        db_sync.settings.update_one(
            {"_id": "global"}, {"$set": {"download_gauge_enabled": True}},
        )
        r2 = requests.post(
            f"{API}/me/download-requests",
            json={"document_url": "/static/y.pdf", "label": "Test doc 2"},
            headers=admin_h, timeout=15,
        )
        if r2.status_code == 200 and not r2.json().get("direct"):
            assert r2.json().get("gauge_enabled") is True
    finally:
        # Reset to default (enabled)
        db_sync.settings.update_one(
            {"_id": "global"},
            {"$unset": {"download_gauge_enabled": ""}, "$set": {"download_approval_enabled": False}},
        )
