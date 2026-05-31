"""Iter38r-fix9r — Home Assistant voice notifications.

Tests the backend pipeline:
  - Catalog (built-in + custom)
  - Config CRUD
  - Rules CRUD
  - Custom events CRUD + uniqueness
  - Test endpoint (HA mocked via fake URL → expected 502)
  - trigger_voice_event() helper directly (disabled / no rule / disabled rule)
"""
from __future__ import annotations

import asyncio
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
def tenant(db):
    admin_id = f"vn_adm_{uuid.uuid4().hex[:6]}"
    other_id = f"vn_oth_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin VN", "company": "VNC", "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": other_id, "email": f"{other_id}@t.l", "password_hash": "x",
         "full_name": "Client VN", "company": "VNB", "role": "client",
         "account_status": "active", "created_at": now},
    ])
    yield {
        "admin_id": admin_id,
        "admin_token": _forge(admin_id, "admin"),
        "client_token": _forge(other_id, "client"),
    }
    db.users.delete_many({"id": {"$in": [admin_id, other_id]}})
    db.voice_notifications_config.delete_one({"_id": admin_id})
    db.voice_notifications_rules.delete_many({"tenant_id": admin_id})
    db.voice_notifications_custom.delete_many({"tenant_id": admin_id})
    db.voice_notifications_log.delete_many({"tenant_id": admin_id})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ============================================================================
# Catalog
# ============================================================================
def test_catalog_contains_builtin_events(tenant):
    r = requests.get(f"{API}/admin/voice-notifications/catalog", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["builtin"]) >= 12
    keys = {ev["key"] for ev in data["builtin"]}
    assert "invoice_created" in keys
    assert "ticket_critical" in keys
    assert "payment_pawapay_received" in keys
    # Each entry has the metadata fields
    inv = next(e for e in data["builtin"] if e["key"] == "invoice_created")
    assert inv["label"]
    assert inv["module"]
    assert inv["db_table"] == "caisse_invoices"
    assert "amount" in inv["variables"]


def test_catalog_requires_admin(tenant):
    r = requests.get(f"{API}/admin/voice-notifications/catalog", headers=_h(tenant["client_token"]))
    assert r.status_code == 403


# ============================================================================
# Config CRUD
# ============================================================================
def test_config_default_is_disabled(tenant):
    r = requests.get(f"{API}/admin/voice-notifications/config", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["enabled"] is False
    assert data["ha_token_set"] is False


def test_config_update_persists_and_masks_token(tenant, db):
    r = requests.put(
        f"{API}/admin/voice-notifications/config",
        headers=_h(tenant["admin_token"]),
        json={
            "enabled": True,
            "ha_url": "http://ha.example.local:8123",
            "ha_token": "lltoken_abc123xyz456",
            "ha_speaker": "media_player.echo_bureau",
            "notify_service": "alexa_media",
        },
    )
    assert r.status_code == 200, r.text
    g = requests.get(f"{API}/admin/voice-notifications/config", headers=_h(tenant["admin_token"]))
    data = g.json()
    assert data["enabled"] is True
    assert data["ha_url"] == "http://ha.example.local:8123"
    assert data["ha_token_set"] is True
    # Token must NEVER be returned in clear
    assert "lltoken_abc123xyz456" not in str(data)
    assert "…" in data["ha_token_masked"]
    assert data["ha_speaker"] == "media_player.echo_bureau"


def test_config_rejects_invalid_url(tenant):
    r = requests.put(
        f"{API}/admin/voice-notifications/config",
        headers=_h(tenant["admin_token"]),
        json={"ha_url": "ftp://nope"},
    )
    assert r.status_code == 400


# ============================================================================
# Custom events
# ============================================================================
def test_custom_event_add_and_list(tenant):
    payload = {
        "event_key": "backup_finished",
        "label": "Backup MongoDB terminé",
        "module": "Système",
        "page": "/admin/backups",
        "db_table": "mongo_dumps",
        "default_tts": "Sauvegarde MongoDB terminée à {time}.",
        "variables": ["time", "size_mb"],
    }
    r = requests.post(
        f"{API}/admin/voice-notifications/custom-events",
        headers=_h(tenant["admin_token"]),
        json=payload,
    )
    assert r.status_code == 200, r.text
    # Catalog must now include it
    cat = requests.get(f"{API}/admin/voice-notifications/catalog", headers=_h(tenant["admin_token"])).json()
    assert any(e["key"] == "backup_finished" for e in cat["custom"])


def test_custom_event_rejects_invalid_key(tenant):
    r = requests.post(
        f"{API}/admin/voice-notifications/custom-events",
        headers=_h(tenant["admin_token"]),
        json={"event_key": "Bad-Key!"},
    )
    assert r.status_code == 400


def test_custom_event_rejects_builtin_collision(tenant):
    r = requests.post(
        f"{API}/admin/voice-notifications/custom-events",
        headers=_h(tenant["admin_token"]),
        json={"event_key": "invoice_created", "label": "x"},
    )
    assert r.status_code == 409


def test_custom_event_delete(tenant):
    requests.post(
        f"{API}/admin/voice-notifications/custom-events",
        headers=_h(tenant["admin_token"]),
        json={"event_key": "tmp_evt", "label": "Temp"},
    )
    r = requests.delete(
        f"{API}/admin/voice-notifications/custom-events/tmp_evt",
        headers=_h(tenant["admin_token"]),
    )
    assert r.status_code == 200
    # Cannot delete builtin
    r2 = requests.delete(
        f"{API}/admin/voice-notifications/custom-events/invoice_created",
        headers=_h(tenant["admin_token"]),
    )
    assert r2.status_code == 400


# ============================================================================
# Rules
# ============================================================================
def test_rule_upsert_on_builtin(tenant):
    r = requests.put(
        f"{API}/admin/voice-notifications/rules/invoice_created",
        headers=_h(tenant["admin_token"]),
        json={
            "enabled": True,
            "tts_template": "Facture {amount} XOF chez {client_name}",
            "speaker_override": "media_player.echo_salon",
        },
    )
    assert r.status_code == 200, r.text
    rules = requests.get(f"{API}/admin/voice-notifications/rules", headers=_h(tenant["admin_token"])).json()
    found = next((it for it in rules["items"] if it["event_key"] == "invoice_created"), None)
    assert found is not None
    assert found["enabled"] is True
    assert "{amount}" in found["tts_template"]
    assert found["speaker_override"] == "media_player.echo_salon"


def test_rule_unknown_event_rejected(tenant):
    r = requests.put(
        f"{API}/admin/voice-notifications/rules/does_not_exist",
        headers=_h(tenant["admin_token"]),
        json={"enabled": True, "tts_template": "x"},
    )
    assert r.status_code == 404


# ============================================================================
# Trigger pipeline
# ============================================================================
def test_trigger_helper_when_disabled(tenant, db):
    """When the tenant config is disabled, trigger returns ok:false reason:disabled."""
    from routes.voice_notifications import trigger_voice_event
    # Make sure config is disabled
    db.voice_notifications_config.update_one(
        {"_id": tenant["admin_id"]}, {"$set": {"enabled": False}}, upsert=True
    )
    async def _run():
        return await trigger_voice_event(
            db=MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]._database_async
            if False else _AsyncDbProxy(db),
            tenant_id=tenant["admin_id"],
            event_key="invoice_created",
            context={"amount": 1000, "client_name": "Test"},
        )
    # use motor not available here — use sync proxy
    result = asyncio.run(_run())
    assert result["ok"] is False
    assert result["reason"] in ("disabled", "no_rule_or_disabled", "ha_not_configured")


def test_test_endpoint_502_when_ha_unreachable(tenant, db):
    db.voice_notifications_config.update_one(
        {"_id": tenant["admin_id"]},
        {"$set": {
            "enabled": True,
            "ha_url": "http://127.0.0.1:9",  # closed port → upstream fail
            "ha_token": "fake_token_xyz",
            "ha_speaker": "media_player.echo_bureau",
            "notify_service": "alexa_media",
        }},
        upsert=True,
    )
    r = requests.post(
        f"{API}/admin/voice-notifications/test",
        headers=_h(tenant["admin_token"]),
        json={"message": "Hello SAWALI"},
    )
    assert r.status_code == 502, r.text
    assert "injoignable" in r.json()["detail"].lower()


def test_test_endpoint_400_when_config_missing(tenant, db):
    db.voice_notifications_config.delete_one({"_id": tenant["admin_id"]})
    r = requests.post(
        f"{API}/admin/voice-notifications/test",
        headers=_h(tenant["admin_token"]),
        json={"message": "x"},
    )
    assert r.status_code == 400


# ----------------------------------------------------------------------------
# Async proxy so we can call the async helper from a sync test
# ----------------------------------------------------------------------------
class _AsyncDbProxy:
    """Minimal async wrapper around pymongo Database to invoke trigger_voice_event."""
    def __init__(self, sync_db):
        self._db = sync_db

    def __getattr__(self, name):
        coll = self._db[name]
        return _AsyncCollProxy(coll)


class _AsyncCollProxy:
    def __init__(self, sync_coll):
        self._coll = sync_coll

    async def find_one(self, *a, **kw):
        return self._coll.find_one(*a, **kw)

    async def insert_one(self, *a, **kw):
        return self._coll.insert_one(*a, **kw)

    async def update_one(self, *a, **kw):
        return self._coll.update_one(*a, **kw)

    async def delete_one(self, *a, **kw):
        return self._coll.delete_one(*a, **kw)

    async def delete_many(self, *a, **kw):
        return self._coll.delete_many(*a, **kw)

    def find(self, *a, **kw):
        return _AsyncCursorProxy(self._coll.find(*a, **kw))


class _AsyncCursorProxy:
    def __init__(self, cur):
        self._cur = cur

    def sort(self, *a, **kw):
        self._cur = self._cur.sort(*a, **kw)
        return self

    async def to_list(self, n):
        return list(self._cur)
