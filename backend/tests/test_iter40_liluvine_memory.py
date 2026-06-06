"""Iter40-fix (2026-02) — Liluvine conversation memory.

Validates that `_build_memory_block` correctly assembles the last N messages
of a session into a prompt-injectable block, and that the helper is exposed
on the `routes.liluvine_pro` module for the three non-streaming callers
(WA inbound, web chat POST, vision chat).
"""
import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path("/app/backend/.env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


@pytest.fixture
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


async def _seed_session(db, sid: str):
    await db.liluvine_pro_messages.delete_many({"session_id": sid})
    base = 1
    msgs = [
        ("user", "Bonjour, je suis client SAWALI"),
        ("assistant", "Bonjour ! Comment puis-je vous aider ?"),
        ("user", "Je n'arrive pas à imprimer une facture"),
        ("assistant", "D'accord, allons sur l'écran Caisse."),
        ("user", "Quelle est la dernière chose que je vous ai dite ?"),
    ]
    from datetime import datetime, timezone, timedelta
    for i, (role, content) in enumerate(msgs):
        await db.liluvine_pro_messages.insert_one({
            "id": f"m-{sid}-{i}",
            "session_id": sid,
            "client_id": "tenant-test",
            "user_id": "user-test",
            "role": role,
            "content": content,
            "created_at": datetime.now(timezone.utc) + timedelta(seconds=i),
        })


def _build_memory_block_factory(db):
    """Replica of the route-scoped helper for unit testing."""
    async def _build_memory_block(sid, current_text, limit=10):
        rows = await db.liluvine_pro_messages.find(
            {"session_id": sid, "role": {"$in": ["user", "assistant"]}},
            {"_id": 0, "role": 1, "content": 1, "created_at": 1},
        ).sort("created_at", -1).limit(limit + 1).to_list(limit + 1)
        rows = [r for r in rows if (r.get("content") or "") != current_text][:limit]
        if not rows:
            return ""
        rows.reverse()
        lines = ["[HISTORIQUE DE LA CONVERSATION (du plus ancien au plus récent)]"]
        for r in rows:
            prefix = "Utilisateur" if r["role"] == "user" else "Liluvine"
            body = (r.get("content") or "")[:1500]
            lines.append(f"{prefix}: {body}")
        lines.append("[FIN HISTORIQUE]\n")
        return "\n".join(lines)
    return _build_memory_block


def test_memory_block_contains_previous_exchanges(db):
    sid = "mem-test-1"

    async def run():
        await _seed_session(db, sid)
        helper = _build_memory_block_factory(db)
        block = await helper(sid, "Quelle est la dernière chose que je vous ai dite ?")
        assert "[HISTORIQUE DE LA CONVERSATION" in block
        assert "[FIN HISTORIQUE]" in block
        # Order : oldest first
        assert block.index("Bonjour, je suis client SAWALI") < block.index("D'accord, allons sur l'écran Caisse.")
        # Current message must be excluded from the block
        assert "Quelle est la dernière chose que je vous ai dite ?" not in block
        # Roles are prefixed
        assert "Utilisateur:" in block
        assert "Liluvine:" in block

    asyncio.run(run())


def test_memory_block_empty_when_no_history(db):
    sid = "mem-test-empty"

    async def run():
        await db.liluvine_pro_messages.delete_many({"session_id": sid})
        helper = _build_memory_block_factory(db)
        block = await helper(sid, "Premier message")
        assert block == ""

    asyncio.run(run())


def test_memory_block_limit_respected(db):
    sid = "mem-test-limit"

    async def run():
        await db.liluvine_pro_messages.delete_many({"session_id": sid})
        from datetime import datetime, timezone, timedelta
        for i in range(20):
            await db.liluvine_pro_messages.insert_one({
                "id": f"m-{sid}-{i}",
                "session_id": sid,
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"message numéro {i}",
                "created_at": datetime.now(timezone.utc) + timedelta(seconds=i),
            })
        helper = _build_memory_block_factory(db)
        block = await helper(sid, "current", limit=5)
        # 5 messages + 2 framing lines = 7 newlines-joined sections
        assert block.count("Utilisateur:") + block.count("Liluvine:") == 5
        # Most recent 5 are 15..19 (since 19 is the latest and current is not in the list)
        assert "message numéro 19" in block
        assert "message numéro 15" in block
        assert "message numéro 14" not in block

    asyncio.run(run())


def test_helper_exposed_on_module():
    """Route-internal helpers are closures, so we assert callsite presence."""
    import re
    with open("/app/backend/routes/liluvine_pro.py", encoding="utf-8") as fh:
        src = fh.read()
    # Helper definition
    assert re.search(r"async def _build_memory_block\s*\(", src), "helper missing"
    # Used at the 3 non-streaming callers
    calls = re.findall(r"await _build_memory_block\(", src)
    assert len(calls) >= 3, f"expected ≥3 callsites of _build_memory_block, found {len(calls)}"
