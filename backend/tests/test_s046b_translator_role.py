"""Translator role + admin coverage + Liluvine takeover config (2026-02)."""
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


@pytest.fixture()
def translator_user(db_sync):
    """Spawn a Traducteur user with EN allowed + a rate of 5.0/word."""
    import sys
    sys.path.insert(0, "/app/backend")
    from auth import hash_password  # type: ignore

    suffix = uuid.uuid4().hex[:6]
    email = f"trad_{suffix}@example.com"
    password = "Password123!"
    parent = db_sync.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": hash_password(password),
        "full_name": "Trad Test",
        "company": "TradCo",
        "phone": f"+228{suffix}77",
        "role": "tracked_user",
        "tracked_role": "Traducteur",
        "translator_languages": ["en", "ar"],
        "translator_rate_per_word": 5.0,
        "parent_client_id": parent["id"],
        "client_id": parent["id"],
        "account_status": "active",
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    }
    db_sync.users.insert_one(user_doc)
    tok = _login(email, password)
    yield {"user": user_doc, "headers": {"Authorization": f"Bearer {tok}"}}
    db_sync.users.delete_one({"id": user_doc["id"]})
    db_sync.i18n_translator_log.delete_many({"translator_email": email})


def test_admin_list_returns_coverage(admin_h):
    r = requests.get(f"{API}/admin/i18n/translations", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "coverage" in data
    cov = data["coverage"]
    # All seed keys have FR + EN + AR populated → high coverage for these langs
    assert cov.get("en", 0) >= 90
    assert cov.get("ar", 0) >= 90
    # LG1/LG2 are intentionally empty in the seed → 0%
    assert cov.get("lg1", 0) == 0
    assert cov.get("lg2", 0) == 0
    assert data.get("viewer_role") == "admin"


def test_translator_can_list_and_sees_allowed_langs(translator_user):
    r = requests.get(f"{API}/admin/i18n/translations", headers=translator_user["headers"], timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["viewer_role"] == "translator"
    assert set(data["allowed_languages"]) == {"en", "ar"}
    assert data["rate_per_word"] == 5.0


def test_translator_can_only_patch_allowed_language(translator_user, db_sync, admin_h):
    # Create a row first with empty AR/EN values so the translator can fill them
    key = f"test.trans_{uuid.uuid4().hex[:6]}"
    db_sync.i18n_translations.insert_one({
        "key": key, "fr": "Bonjour", "en": "", "ar": "", "lg1": "", "lg2": "",
        "context": "", "updated_at": "2026-02-01T00:00:00+00:00",
    })
    try:
        # Translator patches EN + LG1. Only EN must take effect (LG1 not allowed).
        r = requests.post(
            f"{API}/admin/i18n/translations",
            json={"key": key, "fr": "ignored", "en": "Hello world from test",
                  "lg1": "FORBIDDEN_VALUE"},
            headers=translator_user["headers"], timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # 3 words counted ("Hello world from"… actually 4: Hello, world, from, test)
        assert data["words_added"] == 4
        # Verify in DB : EN populated, LG1 still empty, FR unchanged
        row = db_sync.i18n_translations.find_one({"key": key}, {"_id": 0})
        assert row["en"] == "Hello world from test"
        assert row["lg1"] == ""
        assert row["fr"] == "Bonjour"
        # Verify the log entry exists with amount = 4 * 5.0
        log = db_sync.i18n_translator_log.find_one(
            {"key": key, "translator_email": translator_user["user"]["email"]},
            {"_id": 0},
        )
        assert log is not None
        assert log["words_added"] == 4
        assert log["amount"] == 20.0
    finally:
        db_sync.i18n_translations.delete_one({"key": key})


def test_translator_cannot_create_new_key(translator_user):
    r = requests.post(
        f"{API}/admin/i18n/translations",
        json={"key": "test.never_existed_" + uuid.uuid4().hex[:6], "fr": "x", "en": "y"},
        headers=translator_user["headers"], timeout=15,
    )
    assert r.status_code == 403
    assert "administrateur" in r.text.lower()


def test_translator_cannot_delete(translator_user):
    r = requests.delete(
        f"{API}/admin/i18n/translations/nav.dashboard",
        headers=translator_user["headers"], timeout=15,
    )
    assert r.status_code in (403,), f"expected 403, got {r.status_code}: {r.text}"


def test_translator_score_endpoint(translator_user, db_sync):
    # Insert a fake log entry to verify aggregation
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db_sync.i18n_translator_log.insert_many([
        {
            "id": "x1", "translator_id": translator_user["user"]["id"],
            "translator_email": translator_user["user"]["email"],
            "key": "k1", "words_added": 10, "amount": 50.0,
            "day": today, "month": today[:7],
        },
        {
            "id": "x2", "translator_id": translator_user["user"]["id"],
            "translator_email": translator_user["user"]["email"],
            "key": "k2", "words_added": 7, "amount": 35.0,
            "day": today, "month": today[:7],
        },
    ])
    r = requests.get(f"{API}/admin/i18n/translator-score",
                     headers=translator_user["headers"], timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["day"]["words"] >= 17
    assert data["day"]["amount"] >= 85.0
    assert data["month"]["words"] >= 17
    assert data["total"]["words"] >= 17


def test_admin_can_see_other_translator_score(admin_h, translator_user, db_sync):
    db_sync.i18n_translator_log.insert_one({
        "id": "y1",
        "translator_email": translator_user["user"]["email"],
        "words_added": 3, "amount": 15.0,
        "day": "2026-01-01", "month": "2026-01",
    })
    r = requests.get(
        f"{API}/admin/i18n/translator-score",
        params={"translator_email": translator_user["user"]["email"]},
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"]["words"] >= 3


def test_liluvine_takeover_minutes_setting_validates(admin_h, db_sync):
    r = requests.put(f"{API}/admin/settings",
                     json={"liluvine_takeover_default_minutes": 4},
                     headers=admin_h, timeout=10)
    assert r.status_code == 400
    r2 = requests.put(f"{API}/admin/settings",
                      json={"liluvine_takeover_default_minutes": 45},
                      headers=admin_h, timeout=10)
    assert r2.status_code == 200, r2.text
    s = db_sync.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_takeover_default_minutes": 1})
    assert s["liluvine_takeover_default_minutes"] == 45
