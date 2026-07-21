"""Iter43-fix24az-q (2026-07-22) — WhatsApp helpers extraction tests (Phase A).

Validates that :
  1. Pure helpers work identically after extraction to routes/whatsapp_helpers.py
  2. Factory attaches db-bound helpers successfully
  3. server.py exposes _wa_send_text, _wa_send_media, _wa_send_template as before
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_normalize_wa_phone_strips_non_digits():
    from routes.whatsapp_helpers import _normalize_wa_phone
    assert _normalize_wa_phone("+225 07 07 07 07") == "225070707"[:9] + "07"  # 11 digits
    assert _normalize_wa_phone("+225 07 07 07 07") == "22507070707"
    assert _normalize_wa_phone("(226) 76-11-22-33") == "22676112233"
    assert _normalize_wa_phone("00229 91 02 03 04") == "0022991020304"
    assert _normalize_wa_phone("") == ""
    assert _normalize_wa_phone(None) == ""


def test_wa_kind_for_mime_covers_meta_types():
    from routes.whatsapp_helpers import _wa_kind_for_mime
    assert _wa_kind_for_mime("image/jpeg") == "image"
    assert _wa_kind_for_mime("image/webp") == "image"
    assert _wa_kind_for_mime("audio/ogg; codecs=opus") == "audio"
    assert _wa_kind_for_mime("video/mp4") == "video"
    assert _wa_kind_for_mime("application/pdf") == "document"
    assert _wa_kind_for_mime("text/plain") == "document"  # fallback


def test_wa_window_open_boundary():
    from routes.whatsapp_helpers import _wa_window_open
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(hours=1)).isoformat()
    stale = (now - timedelta(hours=25)).isoformat()
    assert _wa_window_open(fresh) is True
    assert _wa_window_open(stale) is False
    assert _wa_window_open(None) is False
    assert _wa_window_open("not-an-iso") is False


def test_wa_apply_image_watermark_qr_noop_without_inputs(tmp_path):
    from routes.whatsapp_helpers import _wa_apply_image_watermark_qr
    p = tmp_path / "x.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0dummy")  # not a real JPEG but tests no-op path
    out = _wa_apply_image_watermark_qr(p, watermark_text=None, qr_payload=None)
    assert out == p


def test_server_module_reexports_helpers():
    """After Phase A extraction, server.py must expose the same helper names
    at module level so existing call sites work unchanged."""
    import asyncio
    async def _load():
        import server
        for name in [
            "_normalize_wa_phone",
            "_wa_kind_for_mime",
            "_wa_window_open",
            "_wa_apply_image_watermark_qr",
            "_wa_send_template",
            "_wa_send_text",
            "_wa_send_media",
            "_wa_download_inbound_media",
            "_wa_transcribe_audio_file",
            "_wa_compute_reply_window",
            "_wa_last_inbound_iso",
        ]:
            assert hasattr(server, name), f"server.py must expose {name}"
            assert callable(getattr(server, name)), f"{name} must be callable"
    asyncio.run(_load())


def test_factory_returns_all_helpers():
    from routes.whatsapp_helpers import attach_whatsapp_helpers
    # Minimal fake db (only used at call time — factory doesn't invoke it).
    class _FakeColl:
        async def find_one(self, *a, **k):
            return {}
        async def insert_one(self, *a, **k):
            return None
    class _FakeDb:
        settings = _FakeColl()
        whatsapp_messages = _FakeColl()
        files = _FakeColl()

    def _fake_uuid():
        return "fake-uuid"
    def _fake_now():
        return "2026-07-22T00:00:00+00:00"

    helpers = attach_whatsapp_helpers(
        db=_FakeDb(),
        wa_graph_version="v21.0",
        wa_media_max_bytes=64 * 1024 * 1024,
        upload_dir=Path("/tmp"),
        uuid_fn=_fake_uuid,
        now_fn=_fake_now,
    )
    expected_callables = {
        "_wa_send_template", "_wa_send_text", "_wa_send_media",
        "_wa_download_inbound_media", "_wa_transcribe_audio_file",
        "_wa_compute_reply_window", "_wa_last_inbound_iso",
        # Iter43-fix24az-u — Underscore neutraliser (avoids WA italic blank bug).
        "_wa_neutralize_underscores",
        # Iter43-fix24az-v — Long-text auto-split safety net.
        "_wa_split_long_text",
    }
    expected_constants = {
        # Iter43-fix24az-v — Constants exposed for callers that build long
        # messages and want to insert semantic split hints (e.g. `_build_garde_reply`).
        "_WA_SPLIT_HINT", "_WA_TEXT_MAX",
    }
    exported = set(helpers.keys())
    missing_callables = expected_callables - exported
    missing_constants = expected_constants - exported
    assert not missing_callables, f"missing callables: {missing_callables}"
    assert not missing_constants, f"missing constants: {missing_constants}"
    for name in expected_callables:
        assert callable(helpers[name]), f"{name} not callable"
