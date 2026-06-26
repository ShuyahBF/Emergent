"""Iter43-fix24at (2026-02-26) — VIDAL favorites endpoints.

Validates `/api/vidal/favorites` :
  - GET returns the current user's favorites (most recent first)
  - POST is idempotent on `(user_id, vidal_id)` (upsert refreshes title/summary)
  - DELETE removes the exact (user, vidal_id) pair
  - Authentication is enforced

Pattern: hits the running backend at `http://localhost:8001` like the rest of
this folder (motor + async backend can't share an event loop with sync
TestClient — see test_iter43_fix24ar_simulate_inbound.py).
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login_admin() -> str:
    """Return a fresh JWT for the seeded admin (internal account, dev_otp)."""
    r = requests.post(
        f"{BACKEND_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    session, otp = body["session_token"], body.get("dev_otp")
    assert otp, "internal account should expose dev_otp"
    v = requests.post(
        f"{BACKEND_URL}/api/auth/verify-otp",
        json={"session_token": session, "code": otp},
        timeout=8,
    )
    assert v.status_code == 200, v.text
    return v.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_favorites_full_lifecycle():
    token = _login_admin()
    vid = f"test{uuid.uuid4().hex[:8]}"

    # 1) List initially should not include this id
    r = requests.get(f"{BACKEND_URL}/api/vidal/favorites", headers=_auth(token), timeout=8)
    assert r.status_code == 200
    initial_ids = [it["vidal_id"] for it in r.json()["items"]]
    assert vid not in initial_ids

    # 2) Add a favorite
    r = requests.post(
        f"{BACKEND_URL}/api/vidal/favorites",
        headers=_auth(token),
        json={"vidal_id": vid, "title": "Doliprane TEST", "type": "product", "summary": "paracétamol"},
        timeout=8,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["favorite"]["vidal_id"] == vid
    assert body["favorite"]["title"] == "Doliprane TEST"

    # 3) List should now include it
    r = requests.get(f"{BACKEND_URL}/api/vidal/favorites", headers=_auth(token), timeout=8)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["vidal_id"] == vid for it in items)

    # 4) Add same id again → upsert (no error, title refreshed)
    r = requests.post(
        f"{BACKEND_URL}/api/vidal/favorites",
        headers=_auth(token),
        json={"vidal_id": vid, "title": "Doliprane REFRESHED", "type": "product"},
        timeout=8,
    )
    assert r.status_code == 200
    assert r.json()["favorite"]["title"] == "Doliprane REFRESHED"

    # Ensure dedup (still only one entry for that vid)
    r = requests.get(f"{BACKEND_URL}/api/vidal/favorites", headers=_auth(token), timeout=8)
    matches = [it for it in r.json()["items"] if it["vidal_id"] == vid]
    assert len(matches) == 1
    assert matches[0]["title"] == "Doliprane REFRESHED"

    # 5) Delete
    r = requests.delete(f"{BACKEND_URL}/api/vidal/favorites/{vid}", headers=_auth(token), timeout=8)
    assert r.status_code == 200
    assert r.json()["deleted"] == 1

    # 6) List should not contain it anymore
    r = requests.get(f"{BACKEND_URL}/api/vidal/favorites", headers=_auth(token), timeout=8)
    final_ids = [it["vidal_id"] for it in r.json()["items"]]
    assert vid not in final_ids

    # 7) Re-delete (idempotent) → ok with deleted=0
    r = requests.delete(f"{BACKEND_URL}/api/vidal/favorites/{vid}", headers=_auth(token), timeout=8)
    assert r.status_code == 200
    assert r.json()["deleted"] == 0


def test_favorites_requires_auth():
    """All endpoints reject unauthenticated requests."""
    r = requests.get(f"{BACKEND_URL}/api/vidal/favorites", timeout=8)
    assert r.status_code in (401, 403)
    r = requests.post(
        f"{BACKEND_URL}/api/vidal/favorites",
        json={"vidal_id": "1234"},
        timeout=8,
    )
    assert r.status_code in (401, 403)
    r = requests.delete(f"{BACKEND_URL}/api/vidal/favorites/1234", timeout=8)
    assert r.status_code in (401, 403)


def test_favorites_validates_vidal_id():
    """Empty vidal_id must be rejected (pydantic min_length=1 → 422 or our 400)."""
    token = _login_admin()
    r = requests.post(
        f"{BACKEND_URL}/api/vidal/favorites",
        headers=_auth(token),
        json={"vidal_id": "", "title": "x"},
        timeout=8,
    )
    assert r.status_code in (400, 422)
