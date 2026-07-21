"""Iter43-fix24az-v (2026-07-22) — WhatsApp text length safety net.

Verify that :
  1. `_wa_split_long_text` returns a single chunk when the input fits under
     the WhatsApp 4096-char cap.
  2. It splits at explicit `_WA_SPLIT_HINT` markers first (semantic split).
  3. It splits at paragraph / line boundaries when no hint is provided.
  4. Each returned chunk stays under `_WA_TEXT_MAX` (3800).
  5. `_build_garde_reply()` inserts a split hint between main and assist
     officines blocks so the auto-splitter breaks at the right seam.
  6. `_build_garde_reply()` applies a soft cap and appends the site link
     when the officines list is too long.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

from routes.whatsapp_helpers import (  # noqa: E402
    _WA_SPLIT_HINT,
    _WA_TEXT_MAX,
    _wa_split_long_text,
)


# =============================================================================
# 1. Pure split helper
# =============================================================================
def test_split_short_text_returns_single_chunk():
    txt = "Hello world"
    chunks = _wa_split_long_text(txt)
    assert chunks == [txt]


def test_split_respects_explicit_hint():
    """The `_WA_SPLIT_HINT` sentinel MUST be honored as a preferred split seam
    whenever the combined text exceeds the cap."""
    part_a = "A" * 3000
    part_b = "B" * 3000
    combined = part_a + _WA_SPLIT_HINT + part_b
    chunks = _wa_split_long_text(combined)
    assert len(chunks) == 2
    assert chunks[0].strip("A") == ""
    assert chunks[1].strip("B") == ""
    assert all(_WA_SPLIT_HINT not in c for c in chunks)


def test_split_at_paragraph_boundaries():
    """Without an explicit hint, the splitter prefers `\\n\\n` breaks."""
    para = "This is a paragraph. " * 40  # ~840 chars
    text = "\n\n".join([para] * 8)  # ~6700 chars
    chunks = _wa_split_long_text(text)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= _WA_TEXT_MAX, f"chunk exceeds cap: {len(c)}"


def test_split_hard_cut_when_no_boundary():
    """Fallback: hard cut at max_len when no boundary can be found."""
    text = "X" * 5000
    chunks = _wa_split_long_text(text)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= _WA_TEXT_MAX


def test_split_preserves_content():
    """Every officine bullet must be preserved across chunks (no drops)."""
    text = ("• Officine A\n" * 300) + "\n\n" + ("• Officine B\n" * 300)
    chunks = _wa_split_long_text(text)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= _WA_TEXT_MAX
    total_a = sum(c.count("• Officine A") for c in chunks)
    total_b = sum(c.count("• Officine B") for c in chunks)
    assert total_a == 300
    assert total_b == 300


# =============================================================================
# 2. _build_garde_reply integration — hint + soft cap
# =============================================================================
@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_bulk_officines_sync(db, count: int, groupe: int, prefix: str) -> None:
    """Sync helper (pymongo) to seed officines. Idempotent by name prefix."""
    db.officines.delete_many({"name": {"$regex": f"^{prefix}-"}})
    if count <= 0:
        return
    docs = [
        {
            "id": f"off-{prefix}-{i:04d}",
            "name": f"{prefix}-{i:04d}",
            "intitule": f"Pharmacie {prefix} {i}",
            "groupe_garde": str(groupe),
            "status": "active",
            "phone": f"+22670{i:06d}",
            "whatsapp": f"+22670{i:06d}",
            "city": "Ouagadougou",
            "location_hint": f"Zone {i}",
            "latitude": 12.3 + i * 0.001,
            "longitude": -1.5 - i * 0.001,
            "contact_name": f"Contact {i}",
            "email": f"off{i}@example.com",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for i in range(count)
    ]
    db.officines.insert_many(docs)


def _run_async(coro):
    """Fresh event loop wrapper — avoids DeprecationWarning on get_event_loop()."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fresh_async_db():
    """Create a motor client bound to the current event loop (motor is
    strict about loop affinity — a module-level client would explode)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_build_garde_reply_uses_split_hint_between_main_and_assist(db):
    """When BOTH a main groupe AND a distinct assist group are configured for
    the current week, the reply must contain `_WA_SPLIT_HINT` so downstream
    `_wa_send_text` breaks the payload into 2 WhatsApp messages."""
    from routes.garde_planning import _current_garde_period
    from routes.liluvine_wa_autoreply import _build_garde_reply

    # Sync seeding via pymongo.
    _seed_bulk_officines_sync(db, count=40, groupe=7, prefix="TEST-BULK-MAIN")
    _seed_bulk_officines_sync(db, count=30, groupe=8, prefix="TEST-BULK-ASSIST")

    async def _run():
        async_db = _fresh_async_db()
        period = await _current_garde_period(async_db, now=datetime.now(timezone.utc))
        await async_db.garde_planning.update_one(
            {"year": period["year"], "week_number": period["week"]},
            {"$set": {
                "year": period["year"], "week_number": period["week"],
                "groupe_garde": "7", "assist_group": "8",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return await _build_garde_reply(async_db)

    try:
        reply = _run_async(_run())
        assert _WA_SPLIT_HINT in reply, (
            "Reply must contain the invisible split hint between main and "
            "assist officines blocks."
        )
        halves = reply.split(_WA_SPLIT_HINT)
        assert len(halves) == 2
        for i, half in enumerate(halves):
            assert len(half) <= _WA_TEXT_MAX + 400, (
                f"Half {i} too long: {len(half)} chars"
            )
    finally:
        db.officines.delete_many({"name": {"$regex": "^TEST-BULK-"}})


def test_build_garde_reply_appends_site_link_when_officines_exceed_budget(db):
    """When the officines list would exceed the per-section budget, the
    builder must stop and append the site link so users see the full list."""
    from routes.garde_planning import _current_garde_period
    from routes.liluvine_wa_autoreply import _build_garde_reply

    # Sync seeding: 100 officines with LONG mentions to force overflow.
    db.officines.delete_many({"name": {"$regex": "^TEST-OVFL-"}})
    docs = [
        {
            "id": f"off-ovfl-{i:04d}",
            "name": f"TEST-OVFL-{i:04d}",
            "intitule": f"Pharmacie Grande Longue Ouagadougou {i}",
            "groupe_garde": "9",
            "status": "active",
            "phone": f"+22670{i:06d}",
            "whatsapp": f"+22670{i:06d}",
            "city": "Ouagadougou Secteur 30 très longue mention pour gonfler",
            "location_hint": f"Zone longue mention adresse détaillée {i}",
            "latitude": 12.3, "longitude": -1.5,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for i in range(100)
    ]
    db.officines.insert_many(docs)

    async def _run():
        async_db = _fresh_async_db()
        period = await _current_garde_period(async_db, now=datetime.now(timezone.utc))
        await async_db.garde_planning.update_one(
            {"year": period["year"], "week_number": period["week"]},
            {"$set": {
                "year": period["year"], "week_number": period["week"],
                "groupe_garde": "9",
                "assist_group": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return await _build_garde_reply(async_db)

    try:
        reply = _run_async(_run())
        assert "liste complète" in reply.lower(), (
            "Overflow message must mention 'liste complète' + site link"
        )
        assert "/garde" in reply, "Site URL must be included when list is truncated"
        chunks = _wa_split_long_text(reply)
        for i, c in enumerate(chunks):
            assert len(c) <= _WA_TEXT_MAX, f"Chunk {i} exceeds cap: {len(c)}"
    finally:
        db.officines.delete_many({"name": {"$regex": "^TEST-OVFL-"}})
        db.garde_planning.update_many(
            {"groupe_garde": "9"},
            {"$unset": {"assist_group": ""}},
        )
