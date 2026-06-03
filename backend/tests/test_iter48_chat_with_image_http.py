"""
Iter48 — Live HTTP test for POST /api/me/liluvine-pro/chat-with-image
- Exercises the public BASE_URL (REACT_APP_BACKEND_URL) through ingress
- Uses admin OTP login (dev_otp path)
- Uploads a small valid 2x2 PNG with non-uniform pixels
- Validates the response shape AND verifies persistence via GET session
"""
import io
import os
import struct
import zlib
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or "https://sawali-portal.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _build_png_2x2() -> bytes:
    """Build a valid 2x2 PNG with non-uniform pixels (red, green, blue, white)."""
    def chunk(tag, data):
        crc = zlib.crc32(tag + data)
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)  # 2x2, 8-bit, RGB
    # 2 scanlines, each prefixed with filter byte 0
    raw = b"\x00" + bytes([255, 0, 0, 0, 255, 0]) + b"\x00" + bytes([0, 0, 255, 255, 255, 255])
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture(scope="module")
def admin_token():
    s = requests.Session()
    # Step 1: login -> dev_otp + session_token
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    if data.get("needs_otp"):
        otp = data.get("dev_otp")
        session_token = data.get("session_token")
        assert otp, f"no dev_otp returned: {data}"
        r2 = s.post(f"{BASE_URL}/api/auth/verify-otp",
                    json={"email": ADMIN_EMAIL, "session_token": session_token, "code": otp},
                    timeout=30)
        assert r2.status_code == 200, f"verify-otp failed: {r2.status_code} {r2.text}"
        tok = r2.json().get("access_token") or r2.json().get("token")
    else:
        tok = data.get("access_token") or data.get("token")
    assert tok, "no token returned"
    return tok


def test_chat_with_image_200(admin_token):
    """Admin (ai_liluvine_pro=true) uploads a small PNG → 200 with full response shape."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    png = _build_png_2x2()
    files = {"file": ("screen.png", io.BytesIO(png), "image/png")}
    data = {"text": "Que faire sur cet écran ?"}
    r = requests.post(
        f"{BASE_URL}/api/me/liluvine-pro/chat-with-image",
        headers=headers, files=files, data=data, timeout=120,
    )
    # If feature is OFF for admin, that is a tenant-config issue (report, don't fail hard)
    if r.status_code == 403:
        pytest.skip(f"ai_liluvine_pro disabled for admin tenant: {r.text}")
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:500]}"
    body = r.json()
    assert body.get("ok") is True
    assert isinstance(body.get("session_id"), str) and body["session_id"]
    assert isinstance(body.get("message_id"), str) and body["message_id"]
    assert "reply" in body  # may be empty string if vision/LLM failed gracefully
    assert isinstance(body.get("image_analysis"), dict)
    assert "ocr_text" in body["image_analysis"]
    assert "visual_summary" in body["image_analysis"]
    assert isinstance(body.get("matched_images"), list)
    # user_image_url may be null if storage failed but key must be present
    assert "user_image_url" in body

    sid = body["session_id"]
    # Verify persistence via GET session
    r2 = requests.get(
        f"{BASE_URL}/api/me/liluvine-pro/sessions/{sid}",
        headers=headers, timeout=30,
    )
    assert r2.status_code == 200, f"session GET failed: {r2.status_code} {r2.text[:300]}"
    msgs = r2.json().get("messages") or []
    user_msgs = [m for m in msgs if m.get("role") == "user"]
    asst_msgs = [m for m in msgs if m.get("role") == "assistant"]
    assert len(user_msgs) >= 1, "no user message persisted"
    assert len(asst_msgs) >= 1, "no assistant message persisted"
    last_user = user_msgs[-1]
    # user message must carry image fields
    assert "user_image_url" in last_user
    assert "image_analysis" in last_user
    assert "matched_images" in last_user


def test_chat_with_image_403_when_not_image(admin_token):
    """Non-image content-type returns 400."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    files = {"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")}
    r = requests.post(
        f"{BASE_URL}/api/me/liluvine-pro/chat-with-image",
        headers=headers, files=files, data={"text": "x"}, timeout=30,
    )
    # could be 400 or 403 depending on order — both acceptable
    assert r.status_code in (400, 403), f"unexpected: {r.status_code} {r.text}"
