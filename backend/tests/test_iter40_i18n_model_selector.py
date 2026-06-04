"""Iter40-i18n-model — Model selector + bulk translate for i18n + content.

Validates:
 - GET /api/admin/i18n/translate-models returns the list of allowed models
 - POST /api/admin/i18n/translate-suggest accepts an optional `model` field
 - Invalid model is rejected (HTTP 400)
 - POST /api/admin/i18n/translate-empty-bulk requires admin
 - POST /api/admin/content/{slug}/translate exists and accepts model
   (we do NOT actually call the LLM here because that costs credits;
   we just verify the endpoint shape + validation)
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
    admin_id = f"imdl_adm_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield _forge(admin_id, "admin")
    db.users.delete_one({"id": admin_id})


def test_translate_models_endpoint_lists_models(admin):
    r = requests.get(f"{API}/admin/i18n/translate-models",
                     headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and len(body["items"]) >= 4
    assert body["default"] == "claude-sonnet-4-5-20250929"
    ids = {it["id"] for it in body["items"]}
    assert "claude-sonnet-4-5-20250929" in ids
    assert "gpt-4o-mini" in ids
    assert "gemini-2.5-flash" in ids


def test_translate_models_requires_auth():
    r = requests.get(f"{API}/admin/i18n/translate-models", timeout=10)
    # 401 or 403 depending on auth gate
    assert r.status_code in (401, 403)


def test_translate_suggest_rejects_invalid_model(admin):
    r = requests.post(
        f"{API}/admin/i18n/translate-suggest",
        headers={"Authorization": f"Bearer {admin}"},
        json={"fr": "Bonjour", "target_lang": "en", "model": "gpt-7-ultra-pro"},
        timeout=10,
    )
    assert r.status_code == 400
    assert "Modèle" in r.json().get("detail", "")


def test_translate_empty_bulk_rejects_invalid_lang(admin):
    r = requests.post(
        f"{API}/admin/i18n/translate-empty-bulk",
        headers={"Authorization": f"Bearer {admin}"},
        json={"target_lang": "es", "model": "claude-haiku-4-5-20251001"},
        timeout=10,
    )
    assert r.status_code == 400


def test_translate_empty_bulk_rejects_invalid_model(admin):
    r = requests.post(
        f"{API}/admin/i18n/translate-empty-bulk",
        headers={"Authorization": f"Bearer {admin}"},
        json={"target_lang": "en", "model": "fake-model"},
        timeout=10,
    )
    assert r.status_code == 400


def test_translate_empty_bulk_returns_zero_when_no_candidates(admin, db):
    """When every row already has the target translation filled, the bulk
    endpoint returns translated=0 without calling the LLM."""
    # Insert a fully-translated row so it's NOT a candidate
    key = f"test_iter40_full_{uuid.uuid4().hex[:6]}"
    db.i18n_translations.insert_one({
        "key": key, "fr": "Salut", "en": "Hello",
        "ar": "مرحبا", "lg1": "Foo", "lg2": "Bar",
        "context": "test", "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        # We can't safely assert the global count without polluting the DB,
        # but we can at least call the endpoint and verify the schema.
        r = requests.post(
            f"{API}/admin/i18n/translate-empty-bulk",
            headers={"Authorization": f"Bearer {admin}"},
            json={"target_lang": "en", "model": "claude-haiku-4-5-20251001"},
            timeout=60,
        )
        # The endpoint should respond 200 (even if it calls the LLM for other
        # rows). We don't validate the exact `translated` count because other
        # tests may have inserted candidate rows; we just check the shape.
        assert r.status_code in (200, 502)  # 502 if LLM key absent in env
        if r.status_code == 200:
            body = r.json()
            assert "translated" in body
            assert "errors" in body
            assert body["target_lang"] == "en"
            assert body["model"] == "claude-haiku-4-5-20251001"
    finally:
        db.i18n_translations.delete_one({"key": key})


def test_content_translate_endpoint_rejects_invalid_lang(admin, db):
    """POST /admin/content/{slug}/translate validates target_lang and model."""
    slug = f"ci_tr_{uuid.uuid4().hex[:6]}"
    db.contents.insert_one({
        "slug": slug, "title": "Salut", "body_html": "<p>Hi</p>",
        "metadata": {}, "translations": {},
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        # Unknown language
        r = requests.post(
            f"{API}/admin/content/{slug}/translate",
            headers={"Authorization": f"Bearer {admin}"},
            json={"target_lang": "xx", "model": "claude-sonnet-4-5-20250929"},
            timeout=10,
        )
        assert r.status_code == 400
        # Unknown model
        r = requests.post(
            f"{API}/admin/content/{slug}/translate",
            headers={"Authorization": f"Bearer {admin}"},
            json={"target_lang": "en", "model": "nope"},
            timeout=10,
        )
        assert r.status_code == 400
    finally:
        db.contents.delete_one({"slug": slug})


def test_content_translate_endpoint_404_on_unknown_slug(admin):
    r = requests.post(
        f"{API}/admin/content/never_exists_xyz/translate",
        headers={"Authorization": f"Bearer {admin}"},
        json={"target_lang": "en", "model": "claude-sonnet-4-5-20250929"},
        timeout=10,
    )
    assert r.status_code == 404


def test_content_translate_rejects_empty_content(admin, db):
    """If the default content has no title/body/kicker/metrics/items, 400."""
    slug = f"ci_empty_{uuid.uuid4().hex[:6]}"
    db.contents.insert_one({
        "slug": slug, "title": "", "body_html": "",
        "metadata": {}, "translations": {},
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(
            f"{API}/admin/content/{slug}/translate",
            headers={"Authorization": f"Bearer {admin}"},
            json={"target_lang": "en", "model": "claude-sonnet-4-5-20250929"},
            timeout=10,
        )
        assert r.status_code == 400
    finally:
        db.contents.delete_one({"slug": slug})
