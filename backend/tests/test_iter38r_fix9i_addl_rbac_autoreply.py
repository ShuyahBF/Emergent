"""Iter38r-fix9i — Additional tests: RBAC 403, WA auto-reply takeover skip,
date_range filter on sessions-history.

These complement test_iter38r_fix9i_takeover_and_kb_split.py.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient


load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASS = "Admin@Sawali2026"


def _login(email: str, password: str) -> str | None:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=10).json()
    if r.get("needs_otp"):
        r = requests.post(
            f"{API}/auth/verify-otp",
            json={"session_token": r["session_token"], "code": r.get("dev_otp")},
            timeout=10,
        ).json()
    return r.get("access_token") or r.get("token")


@pytest.fixture(scope="module")
def admin_h():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    assert tok, "admin login failed"
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


# ----- RBAC: non-elevated tracked user gets 403 -----
def test_takeover_requires_elevated_role(admin_h, db_sync):
    """Create a tracked user with role 'member' and check 403 on takeover."""
    admin = db_sync.users.find_one({"email": ADMIN_EMAIL})
    sid = f"wa:{admin['id']}:99000{uuid.uuid4().hex[:6]}"
    phone = "".join(ch for ch in sid.split(":")[-1] if ch.isdigit())
    db_sync.liluvine_pro_sessions.insert_one({
        "id": sid, "client_id": admin["id"], "user_id": admin["id"],
        "title": "rbac test", "user_label": f"WA +{phone}",
        "created_at": "2026-05-30T10:00:00+00:00",
        "updated_at": "2026-05-30T10:00:00+00:00",
        "external_source": "whatsapp_native",
        "external_payload": {"phone_digits": phone},
    })
    # Create a member user belonging to admin's tenant
    member_email = f"TEST_member_{uuid.uuid4().hex[:6]}@sawali.local"
    member_password = "Member@Test123!"
    # Use admin endpoint to create a tracked user
    try:
        r = requests.post(
            f"{API}/admin/users",
            headers=admin_h,
            json={
                "email": member_email,
                "password": member_password,
                "name": "TEST RBAC Member",
                "role": "member",
                "tracked_role": "member",
            },
            timeout=10,
        )
        # If endpoint doesn't exist or fails, skip
        if r.status_code not in (200, 201):
            pytest.skip(f"Cannot create tracked user via /admin/users: {r.status_code} {r.text[:200]}")
    except Exception as e:
        pytest.skip(f"Cannot create tracked user: {e}")

    # Login as member
    member_tok = _login(member_email, member_password)
    if not member_tok:
        pytest.skip("Member login failed (possibly OTP path differs)")
    mh = {"Authorization": f"Bearer {member_tok}"}

    try:
        # Try takeover with member token → should be 403
        rk = requests.post(f"{API}/admin/liluvine-pro/sessions/{sid}/takeover",
                           headers=mh, json={}, timeout=10)
        assert rk.status_code == 403, f"Expected 403 for member, got {rk.status_code}: {rk.text}"

        # Release → also 403
        rr = requests.post(f"{API}/admin/liluvine-pro/sessions/{sid}/release",
                           headers=mh, timeout=10)
        assert rr.status_code == 403, f"Expected 403 for member on release, got {rr.status_code}"

        # sessions-history → 403
        rh = requests.get(f"{API}/admin/liluvine-pro/sessions-history",
                          headers=mh, timeout=10)
        assert rh.status_code == 403, f"Expected 403 for member on history, got {rh.status_code}"
    finally:
        db_sync.liluvine_pro_sessions.delete_one({"id": sid})
        db_sync.users.delete_one({"email": member_email})


# ----- WA auto-reply skips when human_takeover active -----
def test_wa_autoreply_skips_on_human_takeover(admin_h, db_sync):
    """Insert a session with human_takeover=True + future until, call the helper directly."""
    admin = db_sync.users.find_one({"email": ADMIN_EMAIL})
    phone = f"9900{uuid.uuid4().hex[:6]}"
    sid = f"wa:{admin['id']}:{phone}"
    until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    db_sync.liluvine_pro_sessions.insert_one({
        "id": sid, "client_id": admin["id"], "user_id": admin["id"],
        "title": "autoreply skip test", "user_label": f"WA +{phone}",
        "created_at": "2026-05-30T10:00:00+00:00",
        "updated_at": "2026-05-30T10:00:00+00:00",
        "external_source": "whatsapp_native",
        "external_payload": {"phone_digits": phone},
        "human_takeover": True,
        "human_takeover_until": until,
    })
    try:
        import sys
        sys.path.insert(0, "/app/backend")
        from routes.liluvine_wa_autoreply import autoreply_to_inbound

        # Use motor async client so the function gets the same driver shape it expects
        async def run():
            cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = cli[os.environ["DB_NAME"]]
            inbound = {
                "from": phone, "phone_digits": phone,
                "body": "hello, please help", "wa_message_id": "wamid.TEST",
                "client_id": admin["id"], "message_type": "text",
            }
            res = await autoreply_to_inbound(
                db=db, inbound_doc=inbound, contact=None,
                settings_doc={
                    "liluvine_wa_autoreply_enabled": True,
                    "liluvine_wa_autoreply_schedule": "always",
                    "liluvine_wa_autoreply_allow_mode": "any",
                    "liluvine_wa_autoreply_keywords": "",
                    "liluvine_wa_autoreply_allow_phones": "",
                    "liluvine_wa_autoreply_deny_phones": "",
                },
                wa_send_text=None,
            )
            cli.close()
            return res

        result = asyncio.get_event_loop().run_until_complete(run()) if False else asyncio.run(run())
        assert result.get("ok") is False, f"Expected ok=False, got {result}"
        assert result.get("reason") == "human_takeover_active", f"Wrong reason: {result}"
    finally:
        db_sync.liluvine_pro_sessions.delete_one({"id": sid})


# ----- date_range filter on sessions-history -----
def test_sessions_history_date_range_filter(admin_h, db_sync):
    """Insert one old session (40 days ago) and one recent (today). 7d filter should exclude old."""
    admin = db_sync.users.find_one({"email": ADMIN_EMAIL})
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=40)).isoformat()
    new_ts = now.isoformat()
    sid_old = f"wa:{admin['id']}:OLD{uuid.uuid4().hex[:6]}"
    sid_new = f"wa:{admin['id']}:NEW{uuid.uuid4().hex[:6]}"
    db_sync.liluvine_pro_sessions.insert_many([
        {"id": sid_old, "client_id": admin["id"], "user_id": admin["id"],
         "title": "OLD_DATE_RANGE_TEST", "user_label": "WA old",
         "created_at": old_ts, "updated_at": old_ts,
         "external_source": "whatsapp_native",
         "external_payload": {"phone_digits": "111"}},
        {"id": sid_new, "client_id": admin["id"], "user_id": admin["id"],
         "title": "NEW_DATE_RANGE_TEST", "user_label": "WA new",
         "created_at": new_ts, "updated_at": new_ts,
         "external_source": "whatsapp_native",
         "external_payload": {"phone_digits": "222"}},
    ])
    try:
        # 7d filter should exclude OLD
        r = requests.get(f"{API}/admin/liluvine-pro/sessions-history?date_range=7d",
                         headers=admin_h, timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        ids = {it["id"] for it in items}
        assert sid_new in ids, "recent session missing in 7d filter"
        assert sid_old not in ids, "old session leaked into 7d filter"

        # 'all' should include both
        r2 = requests.get(f"{API}/admin/liluvine-pro/sessions-history?date_range=all",
                          headers=admin_h, timeout=10)
        ids2 = {it["id"] for it in r2.json()["items"]}
        assert sid_new in ids2
        assert sid_old in ids2
    finally:
        db_sync.liluvine_pro_sessions.delete_many({"id": {"$in": [sid_old, sid_new]}})
