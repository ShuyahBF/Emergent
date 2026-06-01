"""S-iter39b — PV de réunions internes (Meeting Minutes) CRUD + PDF export."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
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


def test_meeting_crud_and_pdf(admin_h, db_sync):
    created_ids = []
    try:
        # 1) Create
        payload = {
            "meeting_date": "2026-02-15",
            "started_at": "2026-02-15T14:00:00Z",
            "title": f"Test S-iter39b {uuid.uuid4().hex[:6]}",
            "attendees": "Alice, Bob, Charlie",
            "body_html": "<p>Ordre du jour : <b>budget</b> et planning.</p>",
        }
        r = requests.post(f"{API}/me/meetings", headers=admin_h, json=payload, timeout=30)
        assert r.status_code == 201, r.text
        m = r.json()
        created_ids.append(m["id"])
        assert m["numero"].startswith("PV-2026-")
        assert m["ended_at"]  # auto-set to NOW on save
        assert m["title"] == payload["title"]

        # 2) List (should include it)
        r = requests.get(f"{API}/me/meetings", headers=admin_h, timeout=30)
        assert r.status_code == 200
        ids = [it["id"] for it in r.json()["items"]]
        assert m["id"] in ids

        # 3) Get by id
        r = requests.get(f"{API}/me/meetings/{m['id']}", headers=admin_h, timeout=30)
        assert r.status_code == 200
        assert r.json()["body_html"] == payload["body_html"]

        # 4) Update title
        r = requests.put(f"{API}/me/meetings/{m['id']}", headers=admin_h, json={"title": "Titre modifié"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Titre modifié"

        # 5) PDF export
        r = requests.get(f"{API}/me/meetings/{m['id']}/pdf", headers=admin_h, timeout=30)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"

        # 6) Search filter
        r = requests.get(f"{API}/me/meetings", headers=admin_h, params={"q": "Titre modifié"}, timeout=30)
        assert r.status_code == 200
        assert any(it["id"] == m["id"] for it in r.json()["items"])

        # 7) Numero auto-increments
        r = requests.post(f"{API}/me/meetings", headers=admin_h, json={**payload, "title": "Second PV"}, timeout=30)
        assert r.status_code == 201
        m2 = r.json()
        created_ids.append(m2["id"])
        n1 = int(m["numero"].split("-")[-1])
        n2 = int(m2["numero"].split("-")[-1])
        assert n2 > n1

        # 8) 404 on unknown id
        r = requests.get(f"{API}/me/meetings/does-not-exist", headers=admin_h, timeout=30)
        assert r.status_code == 404

        # 9) Delete (soft)
        r = requests.delete(f"{API}/me/meetings/{m['id']}", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        r = requests.get(f"{API}/me/meetings/{m['id']}", headers=admin_h, timeout=30)
        assert r.status_code == 404  # filtered by deleted_at
    finally:
        if created_ids:
            db_sync.meeting_minutes.delete_many({"id": {"$in": created_ids}})


def test_meeting_unauthenticated_blocked():
    r = requests.get(f"{API}/me/meetings", timeout=30)
    assert r.status_code == 401
