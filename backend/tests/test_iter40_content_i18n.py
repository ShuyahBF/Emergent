"""Iter40-content-i18n — Multilingual content overrides.

Validates:
 - ContentUpsert accepts a `translations` dict
 - GET /content?lang=xx applies per-lang overrides (title, body_html, metadata)
 - GET /content/{slug}?lang=xx returns the translated version
 - When lang is omitted, defaults (FR base) are returned
 - When lang exists but has no override for that slug, defaults are returned
 - metadata deep-merges (override values win; non-overridden keys preserved)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def admin(db):
    admin_id = f"ci_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin")
    db.users.delete_one({"id": admin_id})


@pytest.fixture
def slug(db):
    s = f"test_iter40_content_{uuid.uuid4().hex[:6]}"
    yield s
    db.contents.delete_many({"slug": s})


def test_upsert_with_translations(admin, slug, db):
    payload = {
        "slug": slug,
        "title": "Bienvenue",
        "body_html": "<p>Bonjour</p>",
        "metadata": {"kicker": "Salut", "extra": "garde-moi"},
        "translations": {
            "en": {"title": "Welcome", "body_html": "<p>Hello</p>", "metadata": {"kicker": "Hi"}},
            "ar": {"title": "مرحبا"},
        },
    }
    r = requests.put(f"{API}/admin/content/{slug}",
                     json=payload,
                     headers={"Authorization": f"Bearer {admin}"},
                     timeout=10)
    assert r.status_code == 200, r.text
    doc = db.contents.find_one({"slug": slug}, {"_id": 0})
    assert doc["translations"]["en"]["title"] == "Welcome"
    assert doc["translations"]["ar"]["title"] == "مرحبا"


def test_get_content_without_lang_returns_default(admin, slug):
    requests.put(f"{API}/admin/content/{slug}", json={
        "slug": slug, "title": "Bienvenue", "body_html": "<p>FR</p>", "metadata": {},
        "translations": {"en": {"title": "Welcome"}},
    }, headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    r = requests.get(f"{API}/content/{slug}", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Bienvenue"
    assert "lang_applied" not in body


def test_get_content_with_lang_applies_override(admin, slug):
    requests.put(f"{API}/admin/content/{slug}", json={
        "slug": slug,
        "title": "Bienvenue",
        "body_html": "<p>FR</p>",
        "metadata": {"kicker": "Salut"},
        "translations": {"en": {"title": "Welcome", "body_html": "<p>EN</p>"}},
    }, headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    r = requests.get(f"{API}/content/{slug}?lang=en", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Welcome"
    assert body["body_html"] == "<p>EN</p>"
    assert body["lang_applied"] == "en"


def test_get_content_with_unknown_lang_returns_default(admin, slug):
    requests.put(f"{API}/admin/content/{slug}", json={
        "slug": slug, "title": "Bienvenue", "body_html": "<p>FR</p>", "metadata": {},
        "translations": {"en": {"title": "Welcome"}},
    }, headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    r = requests.get(f"{API}/content/{slug}?lang=de", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Bienvenue"  # no override → default


def test_metadata_deep_merge_preserves_default_keys(admin, slug):
    """When an override only sets metadata.kicker, the other default metadata
    keys must still be present in the response."""
    requests.put(f"{API}/admin/content/{slug}", json={
        "slug": slug,
        "title": "Bienvenue",
        "body_html": "<p>FR</p>",
        "metadata": {"kicker": "Salut", "items": [{"title": "A"}, {"title": "B"}], "extra": "keep"},
        "translations": {"en": {"metadata": {"kicker": "Hi"}}},  # only kicker overridden
    }, headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    r = requests.get(f"{API}/content/{slug}?lang=en", timeout=10)
    body = r.json()
    assert body["metadata"]["kicker"] == "Hi"           # overridden
    assert body["metadata"]["extra"] == "keep"          # preserved
    assert body["metadata"]["items"] == [{"title": "A"}, {"title": "B"}]  # preserved


def test_list_content_applies_lang_to_all_items(admin, db):
    """GET /content?lang=xx applies the language to every returned doc."""
    s1 = f"ci_a_{uuid.uuid4().hex[:6]}"
    s2 = f"ci_b_{uuid.uuid4().hex[:6]}"
    try:
        requests.put(f"{API}/admin/content/{s1}", json={
            "slug": s1, "title": "FR-A", "translations": {"en": {"title": "EN-A"}},
        }, headers={"Authorization": f"Bearer {admin}"}, timeout=10)
        requests.put(f"{API}/admin/content/{s2}", json={
            "slug": s2, "title": "FR-B", "translations": {"en": {"title": "EN-B"}},
        }, headers={"Authorization": f"Bearer {admin}"}, timeout=10)
        r = requests.get(f"{API}/content?lang=en", timeout=10)
        assert r.status_code == 200
        by_slug = {it["slug"]: it for it in r.json() if it["slug"] in (s1, s2)}
        assert by_slug[s1]["title"] == "EN-A"
        assert by_slug[s2]["title"] == "EN-B"
    finally:
        db.contents.delete_many({"slug": {"$in": [s1, s2]}})
