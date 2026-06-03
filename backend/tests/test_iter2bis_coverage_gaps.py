"""#2bis (2026-02) — Coverage gaps endpoint.

Test that:
  * 403 for client role
  * Returns 200 with the right shape (items, total_screenshots, blindspot_rate)
  * Messages with no matched_images appear as no_match gaps
  * Messages whose best score is below min_score appear as low_score gaps
  * Messages with a strong match are excluded
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
def tenant_with_gap_messages(db):
    sup_id = f"gsup_{uuid.uuid4().hex[:6]}"
    sid = f"gss_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
        "full_name": "Gap Boss", "role": "superviseur",
        "account_status": "active", "created_at": now.isoformat(),
    })
    db.liluvine_pro_sessions.insert_one({
        "id": sid, "client_id": sup_id, "user_id": sup_id,
        "user_label": "Boss", "created_at": now.isoformat(), "updated_at": now.isoformat(),
    })
    # 1 — no_match
    db.liluvine_pro_messages.insert_one({
        "id": f"g1-{uuid.uuid4().hex[:6]}", "session_id": sid,
        "client_id": sup_id, "user_id": sup_id, "role": "user",
        "content": "Question A", "user_image_url": "https://example.com/a.jpg",
        "matched_images": [], "created_at": now.isoformat(),
    })
    # 2 — low_score (max 0.3 < 0.5)
    db.liluvine_pro_messages.insert_one({
        "id": f"g2-{uuid.uuid4().hex[:6]}", "session_id": sid,
        "client_id": sup_id, "user_id": sup_id, "role": "user",
        "content": "Question B", "user_image_url": "https://example.com/b.jpg",
        "matched_images": [
            {"image_url": "https://example.com/x.png", "score": 0.3, "title": "Weak"},
        ],
        "created_at": (now - timedelta(hours=1)).isoformat(),
    })
    # 3 — strong match (excluded)
    db.liluvine_pro_messages.insert_one({
        "id": f"g3-{uuid.uuid4().hex[:6]}", "session_id": sid,
        "client_id": sup_id, "user_id": sup_id, "role": "user",
        "content": "Question C", "user_image_url": "https://example.com/c.jpg",
        "matched_images": [
            {"image_url": "https://example.com/y.png", "score": 0.9, "title": "Strong"},
        ],
        "created_at": (now - timedelta(hours=2)).isoformat(),
    })
    yield {"sup_id": sup_id, "sid": sid, "headers": {"Authorization": f"Bearer {_forge(sup_id)}"}}
    db.users.delete_many({"id": sup_id})
    db.liluvine_pro_sessions.delete_many({"id": sid})
    db.liluvine_pro_messages.delete_many({"session_id": sid})


def test_coverage_gaps_returns_no_match_and_low_score(tenant_with_gap_messages):
    h = tenant_with_gap_messages["headers"]
    r = requests.get(f"{API}/admin/liluvine-pro/coverage-gaps?days=7&min_score=0.5", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_screenshots"] == 3
    assert data["gaps_count"] == 2  # no_match + low_score, strong is excluded
    assert data["blindspot_rate"] == round(2 / 3, 3)
    reasons = sorted(g["gap_reason"] for g in data["items"])
    assert reasons == ["low_score", "no_match"]


def test_coverage_gaps_403_for_client(db):
    cli_id = f"gcli_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({
        "id": cli_id, "email": f"{cli_id}@t.l", "password_hash": "x",
        "role": "client", "account_status": "active",
        "full_name": "X", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    headers = {"Authorization": f"Bearer {_forge(cli_id, role='client')}"}
    r = requests.get(f"{API}/admin/liluvine-pro/coverage-gaps", headers=headers, timeout=10)
    assert r.status_code == 403
    db.users.delete_many({"id": cli_id})


def test_coverage_gaps_min_score_threshold(tenant_with_gap_messages):
    """With min_score=0.95, the strong match (0.9) also becomes a gap."""
    h = tenant_with_gap_messages["headers"]
    r = requests.get(f"{API}/admin/liluvine-pro/coverage-gaps?days=7&min_score=0.95", headers=h, timeout=10)
    assert r.status_code == 200
    assert r.json()["gaps_count"] == 3  # all 3 below 0.95
