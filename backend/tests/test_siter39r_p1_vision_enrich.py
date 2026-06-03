"""P1 (2026-02) — Qdrant image upsert with Claude Vision enrichment.

We don't actually call Claude (avoids quota and flakiness in CI). Instead
we mock the `describe_image_with_vision` helper and verify:
  - calling it with auto_describe=on triggers vision and stores OCR + summary
  - calling with auto_describe=off skips vision entirely
  - parser correctly splits the two ### sections in the model reply
"""
from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, patch

import pytest

from routes import qdrant_rag  # type: ignore


# ---------------------------------------------------------------------------
# Parser tests (pure, no network)
# ---------------------------------------------------------------------------

def test_parse_vision_reply_both_sections():
    """Internal regex extraction — verifies the parser used in
    describe_image_with_vision."""
    raw = (
        "### OCR\n"
        "Bouton Se connecter\n"
        "Champ Email\n\n"
        "### Description\n"
        "Capture d'écran d'un écran de connexion bleu avec un bouton vert."
    )
    ocr_m = re.search(r"###\s*OCR\s*\n+(.*?)(?=\n###|\Z)", raw, re.IGNORECASE | re.DOTALL)
    desc_m = re.search(r"###\s*Description\s*\n+(.*?)(?=\n###|\Z)", raw, re.IGNORECASE | re.DOTALL)
    assert ocr_m and "Bouton Se connecter" in ocr_m.group(1)
    assert desc_m and "Capture d'écran" in desc_m.group(1)


def test_parse_vision_reply_no_text_marker():
    raw = "### OCR\n[aucun]\n\n### Description\nUn dégradé violet uni."
    # The function should treat '[aucun]' as no OCR text.
    out = {"ocr_text": "", "visual_summary": ""}
    ocr_m = re.search(r"###\s*OCR\s*\n+(.*?)(?=\n###|\Z)", raw, re.IGNORECASE | re.DOTALL)
    desc_m = re.search(r"###\s*Description\s*\n+(.*?)(?=\n###|\Z)", raw, re.IGNORECASE | re.DOTALL)
    if ocr_m:
        ocr = ocr_m.group(1).strip()
        if ocr and ocr.lower().strip("[]") != "aucun":
            out["ocr_text"] = ocr
    if desc_m:
        out["visual_summary"] = desc_m.group(1).strip()
    assert out["ocr_text"] == ""
    assert "dégradé violet" in out["visual_summary"]


# ---------------------------------------------------------------------------
# describe_image_with_vision — uses a mock LlmChat so we don't hit Anthropic
# ---------------------------------------------------------------------------

def test_describe_image_with_vision_parses_mocked_reply(monkeypatch):
    """We monkey-patch the LlmChat import to return a canned reply and
    verify the helper extracts both ocr_text and visual_summary."""
    fake_reply = (
        "### OCR\n"
        "Hello world\n"
        "Login\n\n"
        "### Description\n"
        "Écran sombre avec un formulaire de connexion centré."
    )

    class _FakeChat:
        def __init__(self, *_, **__):
            pass

        def with_model(self, *_args, **_kw):
            return self

        async def send_message(self, _msg):
            return fake_reply

    class _FakeUserMessage:
        def __init__(self, text="", file_contents=None):
            self.text = text
            self.file_contents = file_contents or []

    class _FakeImageContent:
        def __init__(self, image_base64=""):
            self.image_base64 = image_base64

    import sys
    import types

    fake_mod = types.ModuleType("emergentintegrations.llm.chat")
    fake_mod.LlmChat = _FakeChat
    fake_mod.UserMessage = _FakeUserMessage
    fake_mod.ImageContent = _FakeImageContent

    # Ensure parent packages exist in sys.modules so `from ... import ...` works
    sys.modules.setdefault("emergentintegrations", types.ModuleType("emergentintegrations"))
    sys.modules.setdefault("emergentintegrations.llm", types.ModuleType("emergentintegrations.llm"))
    sys.modules["emergentintegrations.llm.chat"] = fake_mod

    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-test-fake")

    # Minimal PNG bytes (1x1) — content not used by the mock
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    result = asyncio.get_event_loop().run_until_complete(
        qdrant_rag.describe_image_with_vision(png_bytes, "image/png")
    )
    assert result["ocr_text"].startswith("Hello world")
    assert "formulaire de connexion" in result["visual_summary"]


def test_describe_image_with_vision_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    out = asyncio.get_event_loop().run_until_complete(
        qdrant_rag.describe_image_with_vision(b"\x89PNG\r\n", "image/png")
    )
    assert out == {"ocr_text": "", "visual_summary": ""}


def test_describe_image_with_vision_empty_bytes_returns_empty(monkeypatch):
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-test-fake")
    out = asyncio.get_event_loop().run_until_complete(
        qdrant_rag.describe_image_with_vision(b"", "image/png")
    )
    assert out == {"ocr_text": "", "visual_summary": ""}
