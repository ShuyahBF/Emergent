"""Iter38r-fix9u — AI subscription reminders.

Tests:
  - CRUD endpoints (admin only)
  - next_renewal_date auto-computed correctly
  - days_until_renewal returned in payload
  - process_due_reminders dispatches the reminder when within window
  - Idempotency: reminders skipped if last_reminder_at < 18 h ago
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge(uid: str, role: str = "admin") -> str:
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def tenant(db):
    admin_id = f"su_adm_{uuid.uuid4().hex[:6]}"
    client_id = f"su_cli_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "role": "admin", "account_status": "active", "created_at": now},
        {"id": client_id, "email": f"{client_id}@t.l", "password_hash": "x",
         "role": "client", "account_status": "active", "created_at": now},
    ])
    yield {
        "admin_id": admin_id,
        "admin_token": _forge(admin_id, "admin"),
        "client_token": _forge(client_id, "client"),
    }
    db.users.delete_many({"id": {"$in": [admin_id, client_id]}})
    db.ai_subscriptions.delete_many({"tenant_id": admin_id})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ----------------------------------------------------------------------------
# Pure function tests
# ----------------------------------------------------------------------------
def test_compute_next_renewal_today_or_future():
    from routes.ai_subscriptions import _compute_next_renewal
    # Subscribed 90 days ago → next renewal must be in [0, 30] days from today
    sub_date = (date.today() - timedelta(days=90)).isoformat()
    nxt = _compute_next_renewal(sub_date, 30)
    assert nxt is not None
    nxt_d = date.fromisoformat(nxt)
    today = date.today()
    assert (nxt_d - today).days >= 0
    assert (nxt_d - today).days <= 30


def test_compute_next_renewal_future_subscription_returns_date():
    """Subscription date in the future → first renewal IS that date."""
    from routes.ai_subscriptions import _compute_next_renewal
    sub_date = (date.today() + timedelta(days=5)).isoformat()
    assert _compute_next_renewal(sub_date, 30) == sub_date


# ----------------------------------------------------------------------------
# CRUD tests
# ----------------------------------------------------------------------------
def test_create_subscription_and_compute_renewal(tenant):
    sub_date = (date.today() - timedelta(days=20)).isoformat()
    r = requests.post(
        f"{API}/admin/ai-subscriptions",
        headers=_h(tenant["admin_token"]),
        json={
            "name": "Claude Haiku 4.5 PRO",
            "active": True,
            "monthly_cost": 20.0,
            "currency": "USD",
            "subscription_date": sub_date,
            "period_days": 30,
            "reminder_days_before": 7,
            "notify_email": "test@example.com",
            "notify_whatsapp": "+22670000000",
        },
    )
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["name"] == "Claude Haiku 4.5 PRO"
    assert item["next_renewal_date"] is not None
    # Renewal must be 10 days from today (30 - 20)
    expected = (date.today() + timedelta(days=10)).isoformat()
    assert item["next_renewal_date"] == expected
    assert item["days_until_renewal"] == 10


def test_create_requires_admin(tenant):
    r = requests.post(
        f"{API}/admin/ai-subscriptions",
        headers=_h(tenant["client_token"]),
        json={
            "name": "X", "subscription_date": date.today().isoformat(),
        },
    )
    assert r.status_code == 403


def test_list_subscriptions(tenant, db):
    db.ai_subscriptions.delete_many({"tenant_id": tenant["admin_id"]})
    requests.post(
        f"{API}/admin/ai-subscriptions",
        headers=_h(tenant["admin_token"]),
        json={
            "name": "Emergent",
            "subscription_date": date.today().isoformat(),
            "monthly_cost": 50, "currency": "EUR",
        },
    )
    r = requests.get(
        f"{API}/admin/ai-subscriptions",
        headers=_h(tenant["admin_token"]),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1
    assert any(s["name"] == "Emergent" for s in data["items"])


def test_update_and_delete_subscription(tenant):
    create = requests.post(
        f"{API}/admin/ai-subscriptions",
        headers=_h(tenant["admin_token"]),
        json={
            "name": "OpenAI", "subscription_date": date.today().isoformat(),
            "monthly_cost": 100,
        },
    ).json()
    sid = create["item"]["id"]
    upd = requests.put(
        f"{API}/admin/ai-subscriptions/{sid}",
        headers=_h(tenant["admin_token"]),
        json={"monthly_cost": 120.5, "active": False},
    )
    assert upd.status_code == 200
    assert upd.json()["item"]["monthly_cost"] == 120.5
    assert upd.json()["item"]["active"] is False
    delete = requests.delete(
        f"{API}/admin/ai-subscriptions/{sid}",
        headers=_h(tenant["admin_token"]),
    )
    assert delete.status_code == 200


def test_process_due_reminders_dispatches_when_within_window(tenant, db):
    """Insert a subscription whose next renewal is in 3 days and a 5-day window.
    The cron must dispatch the reminder."""
    from routes.ai_subscriptions import process_due_reminders
    sub_date = (date.today() - timedelta(days=27)).isoformat()
    sub_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.ai_subscriptions.insert_one({
        "id": sub_id,
        "tenant_id": tenant["admin_id"],
        "name": "Test Auto Reminder",
        "active": True,
        "monthly_cost": 10, "currency": "USD",
        "subscription_date": sub_date, "period_days": 30,
        "reminder_days_before": 5,
        "notify_email": "fake@example.com", "notify_whatsapp": None,
        "notes": "", "last_reminder_at": None,
        "created_at": now, "updated_at": now,
    })

    calls = []
    async def _stub_email(**kwargs):
        calls.append(("email", kwargs))
        return True
    async def _stub_wa(**kwargs):
        calls.append(("wa", kwargs))
        return True

    class _AsyncDb:
        def __init__(self, sync_db): self._db = sync_db
        def __getattr__(self, name):
            return _AsyncColl(self._db[name])

    class _AsyncColl:
        def __init__(self, c): self.c = c
        async def update_one(self, *a, **kw): return self.c.update_one(*a, **kw)
        def find(self, *a, **kw): return _Cur(self.c.find(*a, **kw))

    class _Cur:
        def __init__(self, c): self.c = c
        async def to_list(self, n): return list(self.c)

    result = asyncio.run(process_due_reminders(
        _AsyncDb(db),
        send_email_fn=_stub_email,
        send_whatsapp_fn=_stub_wa,
    ))
    assert result["dispatched"] >= 1
    assert any(c[0] == "email" for c in calls)
    # last_reminder_at must be set
    after = db.ai_subscriptions.find_one({"id": sub_id})
    assert after.get("last_reminder_at"), after


def test_process_due_reminders_idempotent_within_18h(tenant, db):
    """Same sub, reminded 1h ago, must NOT be re-reminded."""
    from routes.ai_subscriptions import process_due_reminders
    sub_date = (date.today() - timedelta(days=27)).isoformat()
    sub_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    db.ai_subscriptions.insert_one({
        "id": sub_id,
        "tenant_id": tenant["admin_id"],
        "name": "Already Reminded",
        "active": True, "monthly_cost": 5, "currency": "USD",
        "subscription_date": sub_date, "period_days": 30,
        "reminder_days_before": 5,
        "notify_email": "fake@example.com", "notify_whatsapp": None,
        "notes": "", "last_reminder_at": recent,
        "created_at": now, "updated_at": now,
    })

    sent = []
    async def _stub_email(**kwargs):
        sent.append(kwargs)
        return True

    class _AsyncDb:
        def __init__(self, sync_db): self._db = sync_db
        def __getattr__(self, name):
            return _AsyncColl(self._db[name])

    class _AsyncColl:
        def __init__(self, c): self.c = c
        async def update_one(self, *a, **kw): return self.c.update_one(*a, **kw)
        def find(self, *a, **kw): return _Cur(self.c.find(*a, **kw))

    class _Cur:
        def __init__(self, c): self.c = c
        async def to_list(self, n): return list(self.c)

    result = asyncio.run(process_due_reminders(
        _AsyncDb(db), send_email_fn=_stub_email,
    ))
    # The "Already Reminded" sub must NOT be in the dispatched count
    # (other test subs may exist — just verify our specific sub wasn't re-sent)
    for s in sent:
        assert "Already Reminded" not in (s.get("subject", "") + s.get("body_text", ""))
