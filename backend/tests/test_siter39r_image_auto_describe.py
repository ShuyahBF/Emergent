"""S046 — End-to-end HTTP tests for the new `auto_describe` form field
on POST /api/admin/qdrant/collections/{name}/points/image.

Validates:
  1. auto_describe='off' → no vision call, response has empty ocr_text and
     visual_summary, but the image is indexed (ok=true, id, image_url).
  2. auto_describe='on' → response includes the keys visual_summary and
     ocr_text (string type). Does NOT crash if Claude is unreachable.
"""
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30).json()
    if not r.get("needs_otp"):
        return r["access_token"]
    return requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": r["session_token"], "code": r["dev_otp"]},
        timeout=30,
    ).json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


def _make_jpeg_with_features() -> bytes:
    """Generate a small JPEG with real visual features (rectangles, circles,
    text) — complies with /app/image_testing.md (no uniform images)."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (320, 240), color=(180, 220, 250))  # light blue sky
    draw = ImageDraw.Draw(img)
    # Sun
    draw.ellipse([240, 20, 300, 80], fill=(255, 220, 30), outline=(220, 180, 0))
    # Mountain
    draw.polygon([(20, 200), (120, 80), (220, 200)], fill=(80, 110, 60))
    # House
    draw.rectangle([140, 150, 220, 210], fill=(200, 80, 80), outline=(0, 0, 0))
    draw.polygon([(135, 150), (180, 110), (225, 150)], fill=(120, 50, 50))
    # Text label
    try:
        font = ImageFont.load_default()
        draw.text((30, 215), "Test Vision OK", fill=(0, 0, 0), font=font)
    except Exception:
        pass
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture(scope="module")
def temp_collection(admin_h):
    """Create a temp collection for the suite, delete it at teardown."""
    name = f"test_p1_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/admin/qdrant/collections", headers=admin_h,
                      json={"name": name, "description": "Vision auto_describe e2e"}, timeout=30)
    assert r.status_code == 200, r.text
    yield name
    requests.delete(f"{API}/admin/qdrant/collections/{name}", headers=admin_h, timeout=30)


def test_image_upsert_auto_describe_off_skips_vision(admin_h, temp_collection):
    img_bytes = _make_jpeg_with_features()
    files = {"file": ("test_off.jpg", img_bytes, "image/jpeg")}
    data = {
        "title": "Test sans Vision",
        "caption": "petit visuel de test",
        "auto_describe": "off",
    }
    r = requests.post(
        f"{API}/admin/qdrant/collections/{temp_collection}/points/image",
        headers=admin_h, files=files, data=data, timeout=90,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert isinstance(body.get("id"), str) and len(body["id"]) > 0
    assert isinstance(body.get("image_url"), str) and body["image_url"]
    # Vision skipped → must be empty
    assert body.get("ocr_text", "") == ""
    assert body.get("visual_summary", "") == ""


def test_image_upsert_auto_describe_on_returns_vision_keys(admin_h, temp_collection):
    img_bytes = _make_jpeg_with_features()
    files = {"file": ("test_on.jpg", img_bytes, "image/jpeg")}
    data = {
        "title": "Test avec Vision",
        "caption": "scène avec maison soleil montagne",
        "auto_describe": "on",
    }
    r = requests.post(
        f"{API}/admin/qdrant/collections/{temp_collection}/points/image",
        headers=admin_h, files=files, data=data, timeout=120,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert isinstance(body.get("id"), str)
    assert isinstance(body.get("image_url"), str) and body["image_url"]
    # Keys must always exist (may be empty string if Claude unreachable)
    assert "visual_summary" in body
    assert "ocr_text" in body
    assert isinstance(body["visual_summary"], str)
    assert isinstance(body["ocr_text"], str)
    # Soft check : if EMERGENT_LLM_KEY is set, expect non-empty summary
    if os.environ.get("EMERGENT_LLM_KEY"):
        # NB: do not hard-fail if Anthropic is rate-limited; just log
        if not body["visual_summary"]:
            pytest.skip("Claude Vision returned empty (network/quota), key exists but no answer")
        assert len(body["visual_summary"]) > 5
