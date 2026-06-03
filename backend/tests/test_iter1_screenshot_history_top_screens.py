"""#1 (2026-02 — suite S044) — Screenshot history + Top SAWALI screens analytics.

Tests:
  * GET /api/admin/liluvine-pro/screenshots-history returns only role=user
    messages with user_image_url set, within `days`.
  * Enriches each message with sender_label from the session.
  * GET /api/admin/liluvine-pro/top-screens aggregates matched_images and
    returns counts sorted descending.
  * 403 for non-admin users.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
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


def _forge(uid: str, role: str = "superviseur") -> str:
    return pyjwt.encode(
        {"sub": uid, "role": role,
         "iat": int(datetime.now(timezone.utc).timestamp()),
         "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())},
        JWT_SECRET, algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def scoped_tenant_with_screenshots(db):
    """Create a sup user + seed 3 screenshot messages with matched_images."""
    sup_id = f"shsup_{uuid.uuid4().hex[:6]}"
    sid = f"shs_{uuid.uuid4().hex[:6]}"
    company = f"Sh-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
        "full_name": "Boss Screenshots", "company": company, "role": "superviseur",
        "account_status": "active", "created_at": now.isoformat(),
    })
    db.liluvine_pro_sessions.insert_one({
        "id": sid, "client_id": sup_id, "user_id": sup_id,
        "user_label": "Boss Screenshots", "title": "Demo session",
        "external_source": "web",
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "message_count": 6,
    })
    # 3 user screenshots (different matches) + 3 assistant replies
    img1 = "https://example.com/sawali_login.png"
    img2 = "https://example.com/sawali_dashboard.png"
    for i, m_imgs in enumerate([
        [{"image_url": img1, "title": "Login", "score": 0.9, "collection": "sawali_docs"}],
        [{"image_url": img1, "title": "Login", "score": 0.85, "collection": "sawali_docs"}],
        [{"image_url": img2, "title": "Dashboard", "score": 0.75, "collection": "sawali_docs"}],
    ]):
        db.liluvine_pro_messages.insert_one({
            "id": f"msg-{uuid.uuid4().hex[:6]}", "session_id": sid, "client_id": sup_id, "user_id": sup_id,
            "role": "user", "content": f"Help me with screen #{i+1}",
            "user_image_url": f"https://example.com/client_shot_{i}.jpg",
            "image_analysis": {"ocr_text": "test text", "visual_summary": f"Captured screen #{i+1}"},
            "matched_images": m_imgs,
            "created_at": (now - timedelta(hours=i)).isoformat(),
        })
        db.liluvine_pro_messages.insert_one({
            "id": f"msg-a-{uuid.uuid4().hex[:6]}", "session_id": sid, "client_id": sup_id, "user_id": sup_id,
            "role": "assistant", "content": "Reply", "vision_used": True,
            "created_at": (now - timedelta(hours=i)).isoformat(),
        })
    yield {"sup_id": sup_id, "sid": sid, "headers": {"Authorization": f"Bearer {_forge(sup_id)}"}}
    db.users.delete_many({"id": sup_id})
    db.liluvine_pro_sessions.delete_many({"id": sid})
    db.liluvine_pro_messages.delete_many({"session_id": sid})


def test_screenshots_history_returns_user_messages_only(scoped_tenant_with_screenshots):
    h = scoped_tenant_with_screenshots["headers"]
    r = requests.get(f"{API}/admin/liluvine-pro/screenshots-history?days=7", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 3
    items = data["items"]
    # Each item: role=user, has user_image_url, has image_analysis, has matched_images, has sender_label
    for it in items:
        assert it["role"] == "user"
        assert it["user_image_url"]
        assert "image_analysis" in it
        assert "matched_images" in it
        assert it["sender_label"] == "Boss Screenshots"
        assert it["session_channel"] == "web"


def test_top_screens_aggregates_by_image_url(scoped_tenant_with_screenshots):
    h = scoped_tenant_with_screenshots["headers"]
    r = requests.get(f"{API}/admin/liluvine-pro/top-screens?days=7", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_screenshots"] == 3
    items = data["items"]
    # 2 unique image URLs: login (2 hits), dashboard (1 hit)
    assert len(items) == 2
    # First entry should be login with count=2
    assert items[0]["count"] == 2
    assert items[0]["title"] == "Login"
    assert items[1]["count"] == 1
    assert items[1]["title"] == "Dashboard"


def test_screenshots_history_403_for_regular_client(db):
    """A 'client' role cannot access admin endpoints."""
    cli_id = f"shcli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": cli_id, "email": f"{cli_id}@t.l", "password_hash": "x",
        "full_name": "Regular Client", "role": "client",
        "account_status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    headers = {"Authorization": f"Bearer {_forge(cli_id, role='client')}"}
    r1 = requests.get(f"{API}/admin/liluvine-pro/screenshots-history", headers=headers, timeout=10)
    r2 = requests.get(f"{API}/admin/liluvine-pro/top-screens", headers=headers, timeout=10)
    assert r1.status_code == 403
    assert r2.status_code == 403
    db.users.delete_many({"id": cli_id})


def test_screenshots_history_days_filter(scoped_tenant_with_screenshots, db):
    """Insert one old message (60 days ago) and verify it's excluded with days=30."""
    sup_id = scoped_tenant_with_screenshots["sup_id"]
    sid = scoped_tenant_with_screenshots["sid"]
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    db.liluvine_pro_messages.insert_one({
        "id": f"msg-old-{uuid.uuid4().hex[:6]}", "session_id": sid,
        "client_id": sup_id, "user_id": sup_id, "role": "user",
        "content": "OLD", "user_image_url": "https://example.com/old.jpg",
        "matched_images": [], "created_at": old,
    })
    h = scoped_tenant_with_screenshots["headers"]
    r = requests.get(f"{API}/admin/liluvine-pro/screenshots-history?days=30", headers=h, timeout=10)
    assert r.status_code == 200
    # Should still be 3 (old one excluded). Note: cleanup happens in fixture.
    assert r.json()["count"] == 3
    r2 = requests.get(f"{API}/admin/liluvine-pro/screenshots-history?days=90", headers=h, timeout=10)
    assert r2.json()["count"] == 4  # old message included
