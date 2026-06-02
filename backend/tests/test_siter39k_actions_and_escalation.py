"""S035 — WA cockpit action commands (close ticket, mute/unmute alerts).
   S036 — Liluvine PRO escalation to admin via WhatsApp.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30).json()
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


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


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


def _enable_cockpit(async_db, phone="+22501020304"):
    async def go():
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {"llm_budget_wa_query_enabled": True, "llm_budget_notify_wa_phone": phone}},
            upsert=True,
        )
    _run(go())


# ===========================================================================
# S035 — Action commands
# ===========================================================================

def test_close_ticket_action_marks_resolved(async_db, db_sync):
    """RESOLU #NUMBER must transition the ticket to status=resolved."""
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db)
    tnum = f"T-{uuid.uuid4().hex[:6].upper()}"
    tid = str(uuid.uuid4())
    db_sync.support_tickets.insert_one({
        "id": tid, "number": tnum, "status": "open", "priority": "normal",
        "title": "Bug imprimante", "contact_name": "Alice",
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "archived_at": None,
    })
    sent = []

    async def go():
        ok = await handle_wa_admin_command(
            async_db, text=f"RESOLU #{tnum}", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=lambda: _stub_balance(),
        )
        assert ok is True
        assert "✅" in sent[0]["text"]
        assert tnum in sent[0]["text"]

    async def _stub_balance():
        return "stub"

    try:
        _run(go())
        # DB updated
        doc = db_sync.support_tickets.find_one({"id": tid})
        assert doc["status"] == "resolved"
        assert doc.get("closed_via") == "wa_cockpit_s035"
        assert doc.get("closed_by_wa") == "+22501020304"
    finally:
        db_sync.support_tickets.delete_one({"id": tid})


def test_close_ticket_unknown_returns_friendly_error(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command
    _enable_cockpit(async_db)
    sent = []

    async def stub_balance():
        return "stub"

    async def go():
        ok = await handle_wa_admin_command(
            async_db, text="FERMER #DOES-NOT-EXIST", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=stub_balance,
        )
        assert ok is True
        assert "introuvable" in sent[0]["text"].lower()

    _run(go())


def test_mute_and_unmute_alerts(async_db):
    from routes.wa_admin_cockpit import handle_wa_admin_command, alerts_are_muted
    _enable_cockpit(async_db)
    sent = []

    async def stub_balance():
        return "stub"

    async def go():
        # Initially not muted
        assert await alerts_are_muted(async_db) is False
        # MUTE
        ok = await handle_wa_admin_command(
            async_db, text="MUTE", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=stub_balance,
        )
        assert ok is True and "pause" in sent[0]["text"].lower()
        assert await alerts_are_muted(async_db) is True
        # NOTIF STOP also works (alias)
        sent.clear()
        ok = await handle_wa_admin_command(
            async_db, text="NOTIF STOP", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=stub_balance,
        )
        assert ok is True
        assert await alerts_are_muted(async_db) is True
        # UNMUTE
        sent.clear()
        ok = await handle_wa_admin_command(
            async_db, text="UNMUTE", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=stub_balance,
        )
        assert ok is True and "réactivées" in sent[0]["text"].lower()
        assert await alerts_are_muted(async_db) is False
        # NOTIF ON alias
        sent.clear()
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {"llm_alerts_muted_until": (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()}},
        )
        assert await alerts_are_muted(async_db) is True
        ok = await handle_wa_admin_command(
            async_db, text="NOTIF ON", from_digits="22501020304",
            send_wa=_make_send_wa(sent), build_balance_text=stub_balance,
        )
        assert ok is True
        assert await alerts_are_muted(async_db) is False

    _run(go())


def test_mute_skips_budget_alert_email():
    """S031 daily alert email must NOT fire while muted."""
    from routes.llm_health import maybe_send_budget_alert_email

    async def go():
        async_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        # Force budget_exceeded state + mute for 1h
        await async_db.llm_health_state.update_one(
            {"_id": "current"},
            {"$set": {"status": "budget_exceeded", "current_cost": 3.5, "max_budget": 3.0},
             "$unset": {"last_alert_email_at": ""}},
            upsert=True,
        )
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {"llm_alerts_muted_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}},
            upsert=True,
        )
        called = []

        async def fake_email(**kwargs):
            called.append(kwargs)
            return True

        sent = await maybe_send_budget_alert_email(async_db, fake_email)
        assert sent is False
        assert called == []

        # Unmute → should now allow sending
        await async_db.settings.update_one(
            {"_id": "global"}, {"$unset": {"llm_alerts_muted_until": ""}},
        )
        sent = await maybe_send_budget_alert_email(async_db, fake_email)
        assert sent is True
        assert len(called) == 1
        # Reset state
        await async_db.llm_health_state.update_one(
            {"_id": "current"}, {"$set": {"status": "ok"}, "$unset": {"last_alert_email_at": ""}},
        )

    _run(go())


# ===========================================================================
# S036 — Liluvine escalation
# ===========================================================================

def test_strip_escalation_marker_finds_and_removes():
    from routes.liluvine_escalation import strip_escalation_marker
    raw = "Je suis désolé je ne peux pas vous aider.\n[ESCALATE: client demande remboursement]"
    cleaned, reason = strip_escalation_marker(raw)
    assert "ESCALATE" not in cleaned
    assert reason == "client demande remboursement"
    assert cleaned.endswith("aider.") or cleaned.endswith("aider")
    # No marker → unchanged
    cleaned2, reason2 = strip_escalation_marker("Bonjour !")
    assert cleaned2 == "Bonjour !"
    assert reason2 is None


def test_strip_escalation_marker_tolerates_spacing():
    from routes.liluvine_escalation import strip_escalation_marker
    raw = "Réponse.\n[  ESCALATE :  cas complexe  ]"
    cleaned, reason = strip_escalation_marker(raw)
    assert "ESCALATE" not in cleaned
    assert "cas complexe" in (reason or "")


def test_notify_admin_disabled_skips(async_db):
    from routes.liluvine_escalation import notify_admin
    sent = []

    async def go():
        await async_db.settings.update_one(
            {"_id": "global"}, {"$set": {"liluvine_escalation_enabled": False}}, upsert=True,
        )
        res = await notify_admin(
            async_db,
            contact_name="Bob", contact_phone_digits="22577665544",
            last_user_message="hello", reason="test",
            send_wa=_make_send_wa(sent),
        )
        assert res["sent"] is False
        assert res["skipped_reason"] == "disabled"
        assert sent == []

    _run(go())


def test_notify_admin_no_phone_skips(async_db):
    from routes.liluvine_escalation import notify_admin
    sent = []

    async def go():
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {"liluvine_escalation_enabled": True},
             "$unset": {"liluvine_escalation_wa_phone": "", "llm_budget_notify_wa_phone": ""}},
            upsert=True,
        )
        res = await notify_admin(
            async_db,
            contact_name="Bob", contact_phone_digits="22577665544",
            last_user_message="hello", reason="test",
            send_wa=_make_send_wa(sent),
        )
        assert res["sent"] is False
        assert res["skipped_reason"] == "no_admin_phone"

    _run(go())


def test_notify_admin_sends_with_context(async_db, db_sync):
    from routes.liluvine_escalation import notify_admin
    sent = []

    async def go():
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "liluvine_escalation_enabled": True,
                "liluvine_escalation_wa_phone": "+22501020304",
                "liluvine_escalation_cooldown_minutes": 30,
            }}, upsert=True,
        )
        # Clean previous logs for this contact
        await async_db.liluvine_escalations.delete_many({"contact_phone_digits": "22577665544"})
        res = await notify_admin(
            async_db,
            contact_name="Alice Dupont", contact_phone_digits="22577665544",
            last_user_message="Je veux résilier mon contrat immédiatement",
            reason="Demande administrative complexe — résiliation",
            send_wa=_make_send_wa(sent),
        )
        assert res["sent"] is True
        assert res["to"] == "+22501020304"
        assert len(sent) == 1
        body = sent[0]["text"]
        assert "Liluvine PRO demande de l'aide" in body
        assert "Alice Dupont" in body
        assert "résiliation" in body.lower()
        assert "22577665544" in body
        # Log persisted
        log = await async_db.liluvine_escalations.find_one({"contact_phone_digits": "22577665544"})
        assert log is not None and log.get("sent_ok") is True

        # Throttle: a second call within cooldown is skipped
        sent.clear()
        res2 = await notify_admin(
            async_db,
            contact_name="Alice Dupont", contact_phone_digits="22577665544",
            last_user_message="même message", reason="même raison",
            send_wa=_make_send_wa(sent),
        )
        assert res2["sent"] is False
        assert res2["skipped_reason"] == "throttled"
        assert sent == []

    try:
        _run(go())
    finally:
        db_sync.liluvine_escalations.delete_many({"contact_phone_digits": "22577665544"})


def test_admin_test_endpoint(admin_h, async_db, db_sync):
    """POST /admin/liluvine-escalation/test must call notify_admin with
    realistic synthetic data."""

    async def setup():
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "liluvine_escalation_enabled": True,
                "liluvine_escalation_wa_phone": "+22500000000",
                "liluvine_escalation_cooldown_minutes": 30,
            }}, upsert=True,
        )
        # Reset throttle for the synthetic contact
        await async_db.liluvine_escalations.delete_many({"contact_phone_digits": "22500000000"})

    _run(setup())
    try:
        r = requests.post(f"{API}/admin/liluvine-escalation/test", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # WA may fail in preview (no live token) — the helper still returns
        # a structured response. We only care that the route + DB log work.
        assert body.get("to") == "+22500000000"
        # Throttle should now skip a second call
        r2 = requests.post(f"{API}/admin/liluvine-escalation/test", headers=admin_h, timeout=30)
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2.get("sent") is False
        assert body2.get("skipped_reason") == "throttled"
    finally:
        db_sync.liluvine_escalations.delete_many({"contact_phone_digits": "22500000000"})
