"""S034 — WhatsApp Admin Cockpit (mobile command center)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path("/app/backend/.env"))


def _run(coro):
    try:
        return asyncio.get_event_loop().run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@pytest.fixture
def async_db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _make_send_wa(sent):
    async def fake(to, text):
        sent.append({"to": to, "text": text})
        return {"ok": True}
    return fake


def _make_balance():
    async def fake():
        return "🟢 *Universal Key — OK*\n[balance summary stub]"
    return fake


def _enable_cockpit(async_db, phone="+22501020304"):
    async def go():
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "llm_budget_wa_query_enabled": True,
                "llm_budget_notify_wa_phone": phone,
            }}, upsert=True,
        )
    _run(go())


def _disable_cockpit(async_db):
    async def go():
        await async_db.settings.update_one(
            {"_id": "global"}, {"$set": {"llm_budget_wa_query_enabled": False}}, upsert=True,
        )
    _run(go())


def test_help_command_returns_menu(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db)
    sent = []

    async def go():
        ok = await handle_wa_admin_command(
            async_db, text="AIDE", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=_make_balance(),
        )
        assert ok is True
        assert len(sent) == 1
        body = sent[0]["text"]
        assert "Cockpit" in body
        assert "SOLDE" in body and "STATS" in body and "INCIDENTS" in body and "AIDE" in body

    _run(go())
    _disable_cockpit(async_db)


def test_stats_command_returns_kpis(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db)
    sent = []

    async def go():
        ok = await handle_wa_admin_command(
            async_db, text="STATS", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=_make_balance(),
        )
        assert ok is True
        body = sent[0]["text"]
        assert "STATS temps réel" in body
        assert "WhatsApp reçus" in body
        assert "SMS envoyés" in body
        assert "Tickets ouverts" in body

    _run(go())
    _disable_cockpit(async_db)


def test_incidents_command_handles_empty_and_open_tickets(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db)
    sent = []

    async def go():
        # No constraint on what tickets exist; just assert formatting works
        ok = await handle_wa_admin_command(
            async_db, text="incidents", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=_make_balance(),
        )
        assert ok is True
        body = sent[0]["text"]
        # Either "Aucun ticket ouvert" (empty case) or KPI list with #ticket-number
        assert ("Aucun ticket ouvert" in body) or ("Tickets de support" in body and "#" in body)

    _run(go())
    _disable_cockpit(async_db)


def test_balance_command_delegates_to_injected_function(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db)
    sent = []
    balance_called = []

    async def balance_fn():
        balance_called.append(True)
        return "🟢 *MOCKED BALANCE*"

    async def go():
        ok = await handle_wa_admin_command(
            async_db, text="solde", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=balance_fn,
        )
        assert ok is True
        assert balance_called == [True]
        assert "MOCKED BALANCE" in sent[0]["text"]

    _run(go())
    _disable_cockpit(async_db)


def test_unknown_keyword_returns_false(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db)
    sent = []

    async def go():
        ok = await handle_wa_admin_command(
            async_db, text="bonjour", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=_make_balance(),
        )
        assert ok is False
        assert sent == []

    _run(go())
    _disable_cockpit(async_db)


def test_disabled_master_toggle_blocks_all_commands(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _disable_cockpit(async_db)
    sent = []

    async def go():
        for kw in ("SOLDE", "STATS", "INCIDENTS", "AIDE"):
            ok = await handle_wa_admin_command(
                async_db, text=kw, from_digits="22501020304",
                send_wa=_make_send_wa(sent), build_balance_text=_make_balance(),
            )
            assert ok is False, f"kw {kw} should be blocked when toggle is off"
        assert sent == []

    _run(go())


def test_unauthorized_phone_blocked(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db, phone="+22501020304")
    sent = []

    async def go():
        ok = await handle_wa_admin_command(
            async_db, text="STATS", from_digits="22599887766",
            send_wa=_make_send_wa(sent), build_balance_text=_make_balance(),
        )
        assert ok is False
        assert sent == []

    _run(go())
    _disable_cockpit(async_db)


def test_aliases_resolve_correctly(async_db):
    """BUDGET/KPI/TICKETS/HELP/MENU must all resolve like their primaries."""
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db)
    sent = []
    aliases = [
        ("BUDGET", "Universal Key"),  # balance handler stub
        ("KPI", "STATS temps réel"),
        ("TICKETS", "Tickets de support"),
        ("HELP", "Cockpit"),
        ("MENU", "Cockpit"),
    ]

    async def go():
        for kw, expected in aliases:
            sent.clear()
            ok = await handle_wa_admin_command(
                async_db, text=kw, from_digits="22501020304",
                send_wa=_make_send_wa(sent), build_balance_text=_make_balance(),
            )
            assert ok is True, f"alias {kw} not handled"
            assert expected in sent[0]["text"], f"alias {kw} → unexpected reply: {sent[0]['text'][:120]}"

    _run(go())
    _disable_cockpit(async_db)
