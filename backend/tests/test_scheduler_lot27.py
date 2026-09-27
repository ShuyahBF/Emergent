"""Lot 27 — réactivation des tâches planifiées, avec garde-fous.

- le planificateur démarre enfin (26 tâches), sauf dans l'environnement PREVIEW
  (sa base contient des copies de la production) ou si DISABLE_SCHEDULER=1 ;
- envois WhatsApp / SMS programmés en retard de plus de 3 h : annulés avec un
  motif, jamais envoyés d'un coup ;
- suspension automatique des comptes en retard : seulement si l'interrupteur
  général est activé, jamais pour le super-admin.
Tests autonomes : MongoDB simulé (mongomock-motor), aucun envoi réel.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test")
os.environ.setdefault("JWT_SECRET", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
pytest.importorskip("apscheduler")

# num2words n'est pas indispensable à ces tests : module de remplacement si absent
if "num2words" not in sys.modules:
    try:
        import num2words  # noqa: F401
    except ImportError:
        _m = types.ModuleType("num2words")
        _m.num2words = lambda *a, **k: ""
        sys.modules["num2words"] = _m


@pytest.fixture(scope="module")
def server_mod():
    """server.py importé dans une boucle (il crée des tâches à l'import)."""
    loop = asyncio.new_event_loop()

    async def _imp():
        import server
        return server
    mod = loop.run_until_complete(_imp())
    yield mod, loop
    loop.close()


@pytest.fixture()
def mdb(server_mod, monkeypatch):
    server, _loop = server_mod
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot27"]
    monkeypatch.setattr(server, "db", db)
    return db


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_stale_schedules_are_cancelled_not_sent(server_mod, mdb):
    server, loop = server_mod

    async def scenario():
        await mdb.whatsapp_schedules.insert_many([
            {"id": "vieux", "status": "pending", "scheduled_at": _iso(24 * 90)},   # 3 mois de retard
            {"id": "recent", "status": "pending", "scheduled_at": _iso(1)},        # 1 h : encore envoyable
            {"id": "futur", "status": "pending", "scheduled_at": _iso(-2)},
            {"id": "fait", "status": "done", "scheduled_at": _iso(24 * 90)},
        ])
        n = await server._expire_stale_schedules(mdb.whatsapp_schedules, "wa")
        docs = {d["id"]: d async for d in mdb.whatsapp_schedules.find({}, {"_id": 0})}
        return n, docs
    n, docs = loop.run_until_complete(scenario())
    assert n == 1
    assert docs["vieux"]["status"] == "cancelled" and "en retard" in docs["vieux"]["result_summary"]["error"]
    assert docs["recent"]["status"] == "pending" and docs["futur"]["status"] == "pending"
    assert docs["fait"]["status"] == "done"


def test_scheduler_block_is_no_longer_dead_code(server_mod):
    import inspect
    server, _loop = server_mod
    src = inspect.getsource(server.admin_run_contract_overdue_now)
    assert "add_job" not in src and "AsyncIOScheduler" not in src
    hook = inspect.getsource(server._start_scheduler)
    assert hook.count("_safe_add_job(") == 26 + 1          # 26 tâches + la définition
    assert 'CronTrigger(minute="*/15"' not in hook           # test LLM passé à 1 fois par heure


def _run_hook(server, loop, monkeypatch, env: dict):
    for k in ("DISABLE_SCHEDULER", "SCHEDULER_IN_PREVIEW", "PUBLIC_BASE_URL", "preview_endpoint", "REACT_APP_BACKEND_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(server, "_scheduler", None)
    loop.run_until_complete(server._start_scheduler())
    sched = server._scheduler
    state = server._SCHEDULER_STATE
    if sched is not None and sched.running:
        sched.shutdown(wait=False)
    return sched, state


def test_scheduler_starts_with_all_jobs(server_mod, monkeypatch):
    server, loop = server_mod
    sched, state = _run_hook(server, loop, monkeypatch, {"PUBLIC_BASE_URL": "https://sawalismartsystems.com"})
    assert sched is not None and state.startswith("démarré")
    ids = {j.id for j in sched.get_jobs()}
    assert len(ids) == 26 and {"whatsapp_scheduler_minutely", "sms_scheduler_minutely",
                               "appointment_reminder_hourly", "db_auto_snapshot_weekly"} <= ids


def test_scheduler_never_starts_in_preview(server_mod, monkeypatch):
    server, loop = server_mod
    sched, state = _run_hook(server, loop, monkeypatch,
                             {"REACT_APP_BACKEND_URL": "https://sawali-portal.preview.emergentagent.com"})
    assert sched is None and "PREVIEW" in state
    sched, state = _run_hook(server, loop, monkeypatch, {"DISABLE_SCHEDULER": "1"})
    assert sched is None and "désactivé" in state


def test_auto_suspend_requires_global_switch(server_mod, mdb, monkeypatch):
    server, loop = server_mod
    sent = []

    async def fake_email(*a, **k):
        sent.append("email")
        return True

    async def fake_wa(*a, **k):
        sent.append("wa")
        return {"ok": True}
    monkeypatch.setattr(server, "send_email", fake_email)
    monkeypatch.setattr(server, "_wa_send_template", fake_wa)
    old = (datetime.now(timezone.utc) - timedelta(days=60)).date().isoformat()
    super_email = getattr(server, "SUPER_ADMIN_EMAIL", "admin@sawalismartsystems.com")

    async def scenario(switch: bool):
        await mdb.users.delete_many({})
        await mdb.settings.delete_many({})
        await mdb.settings.insert_one({"_id": "global", "contract_auto_suspend_enabled": switch})
        await mdb.users.insert_many([
            {"id": "c1", "email": "client@x.bf", "role": "client", "last_payment_at": old,
             "auto_suspend_after_overdue_days": 30, "account_status": "active"},
            {"id": "sa", "email": super_email, "role": "admin", "last_payment_at": old,
             "auto_suspend_after_overdue_days": 30, "account_status": "active"},
        ])
        await server._run_contract_overdue_alerts()
        return {u["id"]: u.get("account_status") async for u in mdb.users.find({}, {"_id": 0})}
    off = loop.run_until_complete(scenario(False))
    assert off == {"c1": "active", "sa": "active"}           # interrupteur coupé : aucune suspension
    on = loop.run_until_complete(scenario(True))
    assert on["c1"] == "suspended" and on["sa"] == "active"   # jamais le super-admin
