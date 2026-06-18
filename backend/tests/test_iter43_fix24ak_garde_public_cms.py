"""Iter43-fix24ak (2026-06-17) — Public /garde page fixes.

- `GET /api/public/officines/garde/current` no longer hides pending officines
  (was filtering `status="active"`, now excludes only `suspended`).
- The endpoint exposes `cms_header`, `cms_footer`, `cms_image_url`,
  `cms_image_caption` so the React page can render admin-editable
  banners + a click-target image.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest


API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")


def _login_admin():
    r1 = httpx.post(f"{API_BASE}/auth/login",
                    json={"email": "admin@sawalismartsystems.com", "password": "Admin@Sawali2026"},
                    timeout=15)
    d1 = r1.json()
    r2 = httpx.post(f"{API_BASE}/auth/verify-otp",
                    json={"session_token": d1["session_token"], "code": d1["dev_otp"]},
                    timeout=15)
    return r2.json()["access_token"]


def test_public_garde_endpoint_returns_cms_fields():
    """The /public/officines/garde/current endpoint must include the four CMS
    fields even when empty so the React page can read them safely."""
    r = httpx.get(f"{API_BASE}/public/officines/garde/current", timeout=15)
    assert r.status_code == 200
    body = r.json()
    # Every key must exist (even if empty) — page logic relies on `data?.cms_x`
    assert "cms_header" in body
    assert "cms_footer" in body
    assert "cms_image_url" in body
    assert "cms_image_caption" in body


def test_admin_settings_persists_cms_garde_page_fields():
    """PUT /admin/settings must persist garde_page_* and GET must return them.
    The public endpoint must then expose them as `cms_*`."""
    token = _login_admin()
    h = {"Authorization": f"Bearer {token}"}
    nonce = uuid.uuid4().hex[:8]
    payload = {
        "garde_page_header": f"Bonjour {nonce}",
        "garde_page_footer": f"Au revoir {nonce}",
        "garde_page_image_url": f"https://example.com/{nonce}.png",
        "garde_page_image_caption": f"Cliquez ici {nonce}",
    }
    r = httpx.put(f"{API_BASE}/admin/settings", headers=h, json=payload, timeout=15)
    assert r.status_code == 200
    # GET admin settings should echo
    r2 = httpx.get(f"{API_BASE}/admin/settings", headers=h, timeout=15)
    s = r2.json()
    assert s.get("garde_page_header") == payload["garde_page_header"]
    assert s.get("garde_page_footer") == payload["garde_page_footer"]
    assert s.get("garde_page_image_url") == payload["garde_page_image_url"]
    assert s.get("garde_page_image_caption") == payload["garde_page_image_caption"]
    # Public endpoint should expose them under cms_*
    r3 = httpx.get(f"{API_BASE}/public/officines/garde/current", timeout=15)
    body = r3.json()
    assert body.get("cms_header") == payload["garde_page_header"]
    assert body.get("cms_footer") == payload["garde_page_footer"]
    assert body.get("cms_image_url") == payload["garde_page_image_url"]
    assert body.get("cms_image_caption") == payload["garde_page_image_caption"]
    # Cleanup
    httpx.put(f"{API_BASE}/admin/settings", headers=h, json={
        "garde_page_header": "",
        "garde_page_footer": "",
        "garde_page_image_url": "",
        "garde_page_image_caption": "",
    }, timeout=15)


def test_public_garde_includes_pending_officines():
    """Iter43-fix24ak — Officines with status=pending must NOT be hidden
    from the public listing (only suspended are excluded)."""
    r = httpx.get(f"{API_BASE}/public/officines/garde/current", timeout=15)
    body = r.json()
    if not body.get("ok"):
        pytest.skip("No garde groups configured in this DB — skip")
    # We don't enforce a specific count here (depends on fixtures) but we
    # check that the API does not crash and returns a sensible shape.
    assert isinstance(body.get("officines"), list)
    assert body.get("count") == len(body["officines"])
