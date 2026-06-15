"""Iter43-fix24g (2026-06) — Bird.com comme SMS provider sélectionnable.

Vérifie :
  - `_sms_active_providers` retourne 'bird' si bird_enabled + workspace_id + channel_id + access_key
  - `_sms_provider_cfg("bird", s)` retourne kind="bird"
  - Endpoint /api/me/sms/providers expose Bird dans la liste `active`
  - Le drapeau `bird_enabled` du payload reflète bien la complétude de la config
"""
import os

import httpx
import pytest
from pymongo import MongoClient

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sawalismartsystems.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@Sawali2026")


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_token():
    with httpx.Client(timeout=15) as client:
        r1 = client.post(
            f"{API_BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        data1 = r1.json()
        if not data1.get("needs_otp"):
            return data1.get("access_token") or data1.get("token")
        sess = data1["session_token"]
        otp = data1.get("dev_otp")
        r2 = client.post(
            f"{API_BASE}/auth/verify-otp",
            json={"session_token": sess, "code": otp},
        )
        return r2.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


class TestBirdProvider:
    def _save_orig(self, db):
        return db.settings.find_one({"_id": "global"}) or {}

    def _patch(self, db, **kw):
        db.settings.update_one({"_id": "global"}, {"$set": kw}, upsert=True)

    def test_bird_not_active_when_incomplete(self, db, auth_headers):
        orig = self._save_orig(db)
        try:
            # bird_enabled=True mais champs vides → pas dans active
            self._patch(
                db,
                bird_enabled=True,
                bird_workspace_id="",
                bird_channel_id="",
                bird_access_key="",
            )
            with httpx.Client(timeout=15) as client:
                r = client.get(f"{API_BASE}/me/sms/providers", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            assert "bird" not in data["active"], data
            assert data["bird_enabled"] is False, data
        finally:
            # restore
            self._patch(
                db,
                bird_enabled=bool(orig.get("bird_enabled")),
                bird_workspace_id=orig.get("bird_workspace_id") or "",
                bird_channel_id=orig.get("bird_channel_id") or "",
                bird_access_key=orig.get("bird_access_key") or "",
            )

    def test_bird_active_when_complete(self, db, auth_headers):
        orig = self._save_orig(db)
        try:
            self._patch(
                db,
                bird_enabled=True,
                bird_workspace_id="ws-test-uuid",
                bird_channel_id="ch-test-uuid",
                bird_access_key="key-test",
                bird_api_base_url="https://api.bird.com",
            )
            with httpx.Client(timeout=15) as client:
                r = client.get(f"{API_BASE}/me/sms/providers", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            assert "bird" in data["active"], data
            assert data["bird_enabled"] is True, data
        finally:
            self._patch(
                db,
                bird_enabled=bool(orig.get("bird_enabled")),
                bird_workspace_id=orig.get("bird_workspace_id") or "",
                bird_channel_id=orig.get("bird_channel_id") or "",
                bird_access_key=orig.get("bird_access_key") or "",
                bird_api_base_url=orig.get("bird_api_base_url") or "https://api.bird.com",
            )

    def test_bird_provider_cfg_helper(self, db):
        """Test direct du helper côté serveur (pas via API)."""
        import importlib
        srv = importlib.import_module("server")
        s_ok = {
            "bird_enabled": True,
            "bird_workspace_id": "ws",
            "bird_channel_id": "ch",
            "bird_access_key": "key",
            "bird_api_base_url": "https://api.bird.com/",
            "bird_default_sender": "+22500000000",
        }
        cfg = srv._sms_provider_cfg(s_ok, "bird")
        assert cfg is not None
        assert cfg["kind"] == "bird"
        assert cfg["workspace_id"] == "ws"
        assert cfg["channel_id"] == "ch"
        assert cfg["access_key"] == "key"
        # api_base_url stripped de trailing slash
        assert cfg["api_base_url"] == "https://api.bird.com"

        # Si incomplet → None
        s_ko = dict(s_ok)
        s_ko["bird_access_key"] = ""
        assert srv._sms_provider_cfg(s_ko, "bird") is None

        # Si disabled → None
        s_off = dict(s_ok)
        s_off["bird_enabled"] = False
        assert srv._sms_provider_cfg(s_off, "bird") is None
