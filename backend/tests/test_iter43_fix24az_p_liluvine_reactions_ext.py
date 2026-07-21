"""Iter43-fix24az-p (2026-07-22) — Liluvine Reactions extended features tests.

Validates :
  1. Native WA media sending (uses _wa_send_media, not URL concat)
  2. Contact history endpoint returns timeline of matched interactions
  3. Unmatched messages capture + suggestion CRUD (list/convert/dismiss)
  4. CSV bulk upload creates multiple templates in one shot
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(db):
    u = db.users.find_one({"email": "admin@sawalismartsystems.com"})
    return pyjwt.encode({
        "sub": u["id"], "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


def h(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1) NATIVE MEDIA — Unit test of the ad template branch
# ---------------------------------------------------------------------------
def test_try_reply_ad_template_calls_wa_send_media_when_url(db):
    """When a template has response_media_url + kind=image, wa_send_media
    must be invoked with the correct params (NOT wa_send_text with concat)."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        adb = client[os.environ["DB_NAME"]]
        tid = "test-media-" + uuid.uuid4().hex[:8]
        await adb.liluvine_ad_templates.insert_one({
            "id": tid,
            "tenant_id": None,
            "name": "PromoImg",
            "trigger_text": "je veux la promo image",
            "trigger_variations": [],
            "response_text": "Voici la promo",
            "response_media_url": "https://example.com/promo.jpg",
            "response_media_kind": "image",
            "active": True,
            "received_count": 0,
            "replied_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        calls = {"text": [], "media": []}
        async def fake_send_text(to, body, **kw):
            calls["text"].append({"to": to, "body": body})
            return {"ok": True, "message_id": "t-out-1"}
        async def fake_send_media(to, kind, **kw):
            calls["media"].append({"to": to, "kind": kind, **kw})
            return {"ok": True, "message_id": "m-out-1"}

        from routes.liluvine_reactions import attach_liluvine_reactions_routes
        class _FakeApi:
            def get(self, *a, **k):
                return lambda f: f
            def post(self, *a, **k):
                return lambda f: f
            def put(self, *a, **k):
                return lambda f: f
            def delete(self, *a, **k):
                return lambda f: f
        fresh_helpers = attach_liluvine_reactions_routes(
            api=_FakeApi(), db=adb,
            get_current_user=lambda: None, get_current_admin=lambda: None,
            _is_super_admin=lambda u: False,
            _resolve_visible_client_ids=lambda u: [],
            wa_send_media=fake_send_media,
        )
        res = await fresh_helpers["try_reply_ad_template"](
            "je veux la promo image", fake_send_text, "+22677889900",
            phone_digits="22677889900",
            contact={"id": "cx", "name": "Alice", "phone_digits": "22677889900"},
            tenant_id=None,
            wa_inbound_id="in-1",
        )
        assert res and res.get("sent") is True
        assert len(calls["media"]) == 1, calls
        assert calls["media"][0]["kind"] == "image"
        assert calls["media"][0]["public_url"] == "https://example.com/promo.jpg"
        assert calls["media"][0]["caption"] == "Voici la promo"
        assert len(calls["text"]) == 0

        # Cleanup
        await adb.liluvine_ad_templates.delete_one({"id": tid})
        await adb.liluvine_contact_interactions.delete_many({"phone_digits": "22677889900"})
        client.close()

    asyncio.run(_run())


def test_try_reply_ad_template_fallback_text_when_no_media(db):
    """When template has no media_url, wa_send_text is used (regression safety)."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        adb = client[os.environ["DB_NAME"]]
        tid = "test-text-" + uuid.uuid4().hex[:8]
        await adb.liluvine_ad_templates.insert_one({
            "id": tid,
            "tenant_id": None,
            "name": "Promo TextOnly",
            "trigger_text": "je veux la promo texte",
            "trigger_variations": [],
            "response_text": "Voici les conditions.",
            "response_media_url": None,
            "response_media_kind": None,
            "active": True,
            "received_count": 0,
            "replied_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        calls = {"text": [], "media": []}
        async def fake_send_text(to, body, **kw):
            calls["text"].append(body)
            return {"ok": True, "message_id": "t-only-1"}
        async def fake_send_media(*a, **kw):
            calls["media"].append(1)
            return {"ok": False}

        from routes.liluvine_reactions import attach_liluvine_reactions_routes
        class _FakeApi:
            def get(self, *a, **k):
                return lambda f: f
            def post(self, *a, **k):
                return lambda f: f
            def put(self, *a, **k):
                return lambda f: f
            def delete(self, *a, **k):
                return lambda f: f
        fresh = attach_liluvine_reactions_routes(
            api=_FakeApi(), db=adb,
            get_current_user=lambda: None, get_current_admin=lambda: None,
            _is_super_admin=lambda u: False,
            _resolve_visible_client_ids=lambda u: [],
            wa_send_media=fake_send_media,
        )
        res = await fresh["try_reply_ad_template"](
            "je veux la promo texte", fake_send_text, "+22677889901",
            phone_digits="22677889901",
        )
        assert res and res.get("sent") is True
        assert len(calls["text"]) == 1
        assert calls["text"][0] == "Voici les conditions."
        assert len(calls["media"]) == 0

        await adb.liluvine_ad_templates.delete_one({"id": tid})
        client.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 2) CONTACT HISTORY ENDPOINT
# ---------------------------------------------------------------------------
def test_contact_history_returns_interactions(admin_token, db):
    """POST fake interactions then GET /me/contacts/{cid}/liluvine-history."""
    # Ensure test contact exists
    cid = "test-c-" + uuid.uuid4().hex[:8]
    admin_id = db.users.find_one({"email": "admin@sawalismartsystems.com"})["id"]
    db.directory_contacts.insert_one({
        "id": cid, "client_id": admin_id,
        "name": "Test Contact History", "phone": "+22699887766",
        "whatsapp": "+22699887766", "phone_digits": "22699887766",
        "shared": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Insert fake interactions
    for i in range(3):
        db.liluvine_contact_interactions.insert_one({
            "id": f"int-{uuid.uuid4().hex[:6]}",
            "phone_digits": "22699887766",
            "contact_id": cid,
            "contact_name": "Test Contact History",
            "tenant_id": admin_id,
            "kind": "ad_template" if i % 2 == 0 else "fuzzy_cmd",
            "template_id": f"tid-{i}",
            "template_name": f"Template {i}",
            "matched_command": None if i % 2 == 0 else "garde",
            "matched_score": None if i % 2 == 0 else 82.5,
            "inbound_text": f"message test {i}",
            "response_text": f"réponse {i}",
            "response_media_url": None,
            "response_media_kind": None,
            "wa_inbound_id": None,
            "wa_out_message_id": None,
            "created_at": (datetime.now(timezone.utc) - timedelta(minutes=i)).isoformat(),
        })
    # Fetch
    r = requests.get(f"{API}/me/contacts/{cid}/liluvine-history", headers=h(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["contact_id"] == cid
    assert data["count"] >= 3
    assert data["phone_digits"] == "22699887766"
    kinds = {it.get("kind") for it in data["items"]}
    assert "ad_template" in kinds and "fuzzy_cmd" in kinds

    # Cleanup
    db.directory_contacts.delete_one({"id": cid})
    db.liluvine_contact_interactions.delete_many({"contact_id": cid})


def test_contact_history_404_when_contact_missing(admin_token):
    r = requests.get(f"{API}/me/contacts/does-not-exist-9999/liluvine-history",
                     headers=h(admin_token), timeout=15)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3) UNMATCHED SUGGESTIONS
# ---------------------------------------------------------------------------
def test_unmatched_suggestions_lifecycle(admin_token, db):
    """Insert unmatched messages via direct DB, list them, convert one, dismiss one."""
    admin_id = db.users.find_one({"email": "admin@sawalismartsystems.com"})["id"]
    sid1 = "sugg-" + uuid.uuid4().hex[:8]
    sid2 = "sugg-" + uuid.uuid4().hex[:8]
    db.liluvine_unmatched_messages.insert_many([
        {
            "id": sid1, "tenant_id": admin_id, "phone_digits": "22600001111",
            "contact_name": "TestUser1",
            "body": "quelle est votre offre du jour",
            "normalized_body": "quelle est votre offre du jour",
            "count": 3,
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "converted_template_id": None, "dismissed": False,
        },
        {
            "id": sid2, "tenant_id": admin_id, "phone_digits": "22600002222",
            "contact_name": "TestUser2",
            "body": "spam abcdef",
            "normalized_body": "spam abcdef",
            "count": 1,
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "converted_template_id": None, "dismissed": False,
        },
    ])
    # LIST
    r = requests.get(f"{API}/admin/liluvine/unmatched-suggestions?limit=100",
                     headers=h(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert sid1 in ids and sid2 in ids

    # CONVERT sid1
    r = requests.post(
        f"{API}/admin/liluvine/unmatched-suggestions/{sid1}/convert",
        headers=h(admin_token),
        json={"name": "Offre du jour", "response_text": "Voici notre offre du jour."},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    tpl_id = r.json()["template_id"]
    # The suggestion must now be marked converted
    sugg = db.liluvine_unmatched_messages.find_one({"id": sid1})
    assert sugg["converted_template_id"] == tpl_id
    # And a new template exists
    assert db.liluvine_ad_templates.find_one({"id": tpl_id}) is not None

    # DISMISS sid2
    r = requests.delete(f"{API}/admin/liluvine/unmatched-suggestions/{sid2}",
                        headers=h(admin_token), timeout=15)
    assert r.status_code == 200
    sugg2 = db.liluvine_unmatched_messages.find_one({"id": sid2})
    assert sugg2["dismissed"] is True

    # LIST again — both should be excluded (converted + dismissed)
    r = requests.get(f"{API}/admin/liluvine/unmatched-suggestions?limit=100",
                     headers=h(admin_token), timeout=15)
    ids2 = [it["id"] for it in r.json()["items"]]
    assert sid1 not in ids2
    assert sid2 not in ids2

    # Cleanup
    db.liluvine_unmatched_messages.delete_many({"id": {"$in": [sid1, sid2]}})
    db.liluvine_ad_templates.delete_one({"id": tpl_id})


# ---------------------------------------------------------------------------
# 4) CSV BULK UPLOAD
# ---------------------------------------------------------------------------
def test_csv_bulk_upload_creates_templates(admin_token, db):
    csv_body = (
        "name,trigger_text,response_text,trigger_variations,response_media_url,response_media_kind,active\n"
        "AutoTest1,je veux les infos,Voici les infos,plus d'infos|infos svp,,,true\n"
        "AutoTest2,je veux commander,Voici la procédure,acheter|commande,https://ex.com/img.jpg,image,true\n"
    )
    r = requests.post(
        f"{API}/admin/liluvine/reactions-templates/bulk-csv",
        headers=h(admin_token),
        json={"csv": csv_body, "dry_run": False},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["errors"] == []

    # Verify presence
    created = list(db.liluvine_ad_templates.find({"name": {"$in": ["AutoTest1", "AutoTest2"]}}))
    assert len(created) == 2
    at2 = next(t for t in created if t["name"] == "AutoTest2")
    assert at2["response_media_url"] == "https://ex.com/img.jpg"
    assert at2["response_media_kind"] == "image"

    # Cleanup
    db.liluvine_ad_templates.delete_many({"name": {"$in": ["AutoTest1", "AutoTest2"]}})


def test_csv_bulk_upload_dry_run_no_insert(admin_token, db):
    csv_body = "name,trigger_text,response_text\nDryRunTest,test dry,réponse dry\n"
    r = requests.post(
        f"{API}/admin/liluvine/reactions-templates/bulk-csv",
        headers=h(admin_token),
        json={"csv": csv_body, "dry_run": True},
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["created"] == 0
    assert len(body["rows"]) == 1
    # Nothing must be inserted
    assert db.liluvine_ad_templates.find_one({"name": "DryRunTest"}) is None


def test_csv_bulk_upload_rejects_missing_columns(admin_token):
    r = requests.post(
        f"{API}/admin/liluvine/reactions-templates/bulk-csv",
        headers=h(admin_token),
        json={"csv": "name,trigger_text\nfoo,bar\n"},
        timeout=15,
    )
    assert r.status_code == 400
    assert "response_text" in r.text.lower() or "colonnes" in r.text.lower()


def test_csv_bulk_upload_semicolon_delimiter(admin_token, db):
    """Test that ;-delimited CSV (French Excel default) also works."""
    csv_body = (
        "name;trigger_text;response_text\n"
        "AutoSemi1;trigger semi;response semi\n"
    )
    r = requests.post(
        f"{API}/admin/liluvine/reactions-templates/bulk-csv",
        headers=h(admin_token),
        json={"csv": csv_body, "dry_run": False},
        timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["created"] == 1
    db.liluvine_ad_templates.delete_one({"name": "AutoSemi1"})


# ---------------------------------------------------------------------------
# 5) ADMIN CONFIG — new unmatched_capture_enabled field
# ---------------------------------------------------------------------------
def test_config_supports_unmatched_capture_toggle(admin_token, db):
    r = requests.put(
        f"{API}/admin/liluvine/reactions-config",
        headers=h(admin_token),
        json={"unmatched_capture_enabled": False},
        timeout=15,
    )
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["unmatched_capture_enabled"] is False
    # Turn back on
    r = requests.put(
        f"{API}/admin/liluvine/reactions-config",
        headers=h(admin_token),
        json={"unmatched_capture_enabled": True},
        timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["config"]["unmatched_capture_enabled"] is True


# ---------------------------------------------------------------------------
# 6) AUTH GATES
# ---------------------------------------------------------------------------
def test_admin_endpoints_require_admin_auth():
    r = requests.get(f"{API}/admin/liluvine/unmatched-suggestions", timeout=15)
    assert r.status_code in (401, 403)
    r = requests.post(f"{API}/admin/liluvine/reactions-templates/bulk-csv",
                      json={"csv": "name,trigger_text,response_text\na,b,c"}, timeout=15)
    assert r.status_code in (401, 403)
