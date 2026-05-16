"""Iter35l — WhatsApp media (download/watermark/QR + send-media endpoint).

Unit-style tests that don't actually hit Meta — we monkeypatch _wa_send_media
and httpx where needed.
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest
from PIL import Image

import server


@pytest.fixture
def watermarked_image(tmp_path: Path) -> Path:
    """Create a 600x400 red JPG and watermark it; return new file path."""
    src = tmp_path / "src.jpg"
    Image.new("RGB", (600, 400), color=(220, 30, 30)).save(src, "JPEG")
    out = server._wa_apply_image_watermark_qr(
        src,
        watermark_text="SAWALI SMART SYSTEMS",
        qr_payload="https://example.org",
    )
    return out


def test_watermark_creates_new_file(watermarked_image: Path):
    """Watermark + QR should produce a *new* file path (suffix _wm.jpg)."""
    assert watermarked_image.exists()
    assert watermarked_image.name.endswith("_wm.jpg")
    # File should be a valid JPEG
    img = Image.open(watermarked_image)
    img.verify()


def test_watermark_returns_original_when_nothing_to_do(tmp_path: Path):
    """When both watermark_text and qr_payload are empty/None, return source unchanged."""
    src = tmp_path / "plain.jpg"
    Image.new("RGB", (320, 240), color=(0, 0, 255)).save(src, "JPEG")
    out = server._wa_apply_image_watermark_qr(src, watermark_text=None, qr_payload=None)
    assert out == src


def test_wa_kind_for_mime():
    assert server._wa_kind_for_mime("image/jpeg") == "image"
    assert server._wa_kind_for_mime("image/png") == "image"
    assert server._wa_kind_for_mime("audio/ogg; codecs=opus") == "audio"
    assert server._wa_kind_for_mime("video/mp4") == "video"
    assert server._wa_kind_for_mime("application/pdf") == "document"
    assert server._wa_kind_for_mime("application/zip") == "document"  # fallback
    # Generic prefixes
    assert server._wa_kind_for_mime("image/heic") == "image"
    assert server._wa_kind_for_mime("audio/x-wav") == "audio"
    assert server._wa_kind_for_mime("video/quicktime") == "video"


def test_settings_update_accepts_wa_media_keys():
    """The Pydantic model should accept all new keys."""
    from models import SettingsUpdate
    s = SettingsUpdate(
        wa_allow_terminal_media=False,
        wa_voice_transcribe_enabled=False,
        wa_watermark_enabled=True,
        wa_watermark_text="Test Co.",
        wa_qr_enabled=True,
        wa_qr_payload="https://t.co/abc",
    )
    payload = s.model_dump(exclude_none=True)
    assert payload["wa_allow_terminal_media"] is False
    assert payload["wa_voice_transcribe_enabled"] is False
    assert payload["wa_watermark_text"] == "Test Co."
    assert payload["wa_qr_payload"] == "https://t.co/abc"


def test_wa_send_media_payload_shape(monkeypatch):
    """_wa_send_media must build a Meta Cloud API body with `type=image|...` and `{type}: {link, caption?, filename?}`."""
    captured = {}

    class FakeResp:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body
            self.text = ""

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None, headers=None):  # noqa: A002
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResp(200, {"messages": [{"id": "wamid.FAKE"}]})

    monkeypatch.setattr(server.httpx, "AsyncClient", FakeClient)

    # Patch settings (collection) — minimal mock
    async def fake_find_one(q):
        return {"wa_access_token": "tok", "wa_phone_number_id": "555"}

    monkeypatch.setattr(server.db.settings, "find_one", fake_find_one)

    res = asyncio.get_event_loop().run_until_complete(
        server._wa_send_media("+22899887766", "document", public_url="https://x.test/api/files/abc.pdf",
                              caption="Voici", filename="rapport.pdf")
    )
    assert res["ok"] is True
    assert res["message_id"] == "wamid.FAKE"
    body = captured["json"]
    assert body["messaging_product"] == "whatsapp"
    assert body["type"] == "document"
    assert body["document"]["link"] == "https://x.test/api/files/abc.pdf"
    assert body["document"]["caption"] == "Voici"
    assert body["document"]["filename"] == "rapport.pdf"


def test_wa_send_media_image_does_not_set_filename(monkeypatch):
    """Images don't accept `filename` per Meta spec — but they accept caption."""
    captured = {}

    class FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return {"messages": [{"id": "wamid.IMG"}]}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, json=None, headers=None):
            captured["body"] = json
            return FakeResp()

    monkeypatch.setattr(server.httpx, "AsyncClient", lambda *a, **kw: FakeClient())

    async def fake_find_one(q):
        return {"wa_access_token": "tok", "wa_phone_number_id": "555"}

    monkeypatch.setattr(server.db.settings, "find_one", fake_find_one)

    asyncio.get_event_loop().run_until_complete(
        server._wa_send_media("+22899887766", "image", public_url="https://x.test/api/files/abc.jpg", caption="Hi", filename="orig.png")
    )
    body = captured["body"]
    assert body["type"] == "image"
    assert "filename" not in body["image"]
    assert body["image"]["caption"] == "Hi"


def test_wa_send_media_rejects_unknown_kind(monkeypatch):
    async def fake_find_one(q):
        return {"wa_access_token": "tok", "wa_phone_number_id": "555"}
    monkeypatch.setattr(server.db.settings, "find_one", fake_find_one)
    res = asyncio.get_event_loop().run_until_complete(
        server._wa_send_media("+22899887766", "sticker", public_url="https://x.test/a.webp")
    )
    assert res["ok"] is False
    assert "non géré" in (res.get("error") or "").lower()


def test_extension_mapping_known_mime():
    """The internal _EXT_BY_MIME table should cover all common WA inbound MIMEs."""
    expected = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "audio/ogg": ".ogg",
        "video/mp4": ".mp4",
        "application/pdf": ".pdf",
    }
    for mime, ext in expected.items():
        assert server._EXT_BY_MIME[mime] == ext
