"""Iter43-fix24al (2026-06-17) — Tests for the `!garde` WA footer + site
URL + image capture customization.

Verifies:
- `_build_garde_reply` uses `settings.garde_reply_footer` instead of the
  legacy hardcoded "Prompt rétablissement" footer.
- The site URL (admin-configurable or default https://sawalismartsystems.com)
  is ALWAYS appended at the end of the text message.
- The `_wa_send_image` helper exists and validates input (HTTPS or data URI).
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import uuid

import httpx
import pytest


API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")

sys.path.insert(0, "/app/backend")


def _mod():
    if "routes.liluvine_wa_autoreply" not in sys.modules:
        importlib.import_module("routes.liluvine_wa_autoreply")
    return sys.modules["routes.liluvine_wa_autoreply"]


def _login_admin():
    r1 = httpx.post(f"{API_BASE}/auth/login",
                    json={"email": "admin@sawalismartsystems.com", "password": "Admin@Sawali2026"},
                    timeout=15)
    d1 = r1.json()
    r2 = httpx.post(f"{API_BASE}/auth/verify-otp",
                    json={"session_token": d1["session_token"], "code": d1["dev_otp"]},
                    timeout=15)
    return r2.json()["access_token"]


def test_default_footer_constant_exists():
    m = _mod()
    assert hasattr(m, "DEFAULT_GARDE_REPLY_FOOTER")
    assert "Prompt rétablissement" in m.DEFAULT_GARDE_REPLY_FOOTER


def test_wa_send_image_helper_exists():
    m = _mod()
    assert hasattr(m, "_wa_send_image")


@pytest.mark.asyncio
async def test_wa_send_image_rejects_invalid_src():
    m = _mod()
    # Plain string that's not http(s) or data: → must return ok=False
    out = await m._wa_send_image(
        "+22670112233", "garbage-not-url",
        settings_doc={"wa_access_token": "x", "wa_phone_number_id": "1"},
    )
    assert out["ok"] is False
    assert "http" in out["error"].lower() or "src" in out["error"].lower()


@pytest.mark.asyncio
async def test_wa_send_image_rejects_empty_src():
    m = _mod()
    out = await m._wa_send_image(
        "+22670112233", "",
        settings_doc={"wa_access_token": "x", "wa_phone_number_id": "1"},
    )
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_wa_send_image_noop_when_wa_not_configured():
    """Must return ok=False (not raise) when WA isn't configured."""
    m = _mod()
    out = await m._wa_send_image("+22670112233", "https://x/y.png", settings_doc={})
    assert out["ok"] is False
    assert "non configuré" in out["error"]


def test_admin_settings_persists_garde_reply_extended_fields():
    """PUT/GET admin settings round-trips the 4 new fields."""
    token = _login_admin()
    h = {"Authorization": f"Bearer {token}"}
    nonce = uuid.uuid4().hex[:6]
    payload = {
        "garde_reply_footer": f"Bonne journée {nonce}",
        "garde_reply_site_url": f"https://example.com/{nonce}",
        "garde_reply_image_url": f"https://cdn.example.com/{nonce}.png",
        "garde_reply_image_caption": f"Cliquez ici {nonce}",
    }
    r = httpx.put(f"{API_BASE}/admin/settings", headers=h, json=payload, timeout=15)
    assert r.status_code == 200
    s = httpx.get(f"{API_BASE}/admin/settings", headers=h, timeout=15).json()
    for k, v in payload.items():
        assert s.get(k) == v, f"{k}: expected {v}, got {s.get(k)}"
    # cleanup
    httpx.put(f"{API_BASE}/admin/settings", headers=h, json={k: "" for k in payload}, timeout=15)


@pytest.mark.asyncio
async def test_build_garde_reply_uses_configured_footer_and_site_url():
    """_build_garde_reply pulls footer + site_url from settings.

    Uses a fresh Motor client per-test (not the shared global) to avoid
    asyncio loop teardown issues when running alongside other async tests.
    """
    m = _mod()
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    nonce = uuid.uuid4().hex[:6]
    s_before = await db.settings.find_one({"_id": "global"}) or {}
    try:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "garde_reply_footer": f"FOOTERCUSTOM-{nonce}",
                "garde_reply_site_url": f"https://example.test/{nonce}",
            }},
            upsert=True,
        )
        text = await m._build_garde_reply(db)
        assert f"FOOTERCUSTOM-{nonce}" in text
        assert f"https://example.test/{nonce}/garde" in text
    finally:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "garde_reply_footer": s_before.get("garde_reply_footer", "") or "",
                "garde_reply_site_url": s_before.get("garde_reply_site_url", "") or "",
            }},
        )
        client.close()
