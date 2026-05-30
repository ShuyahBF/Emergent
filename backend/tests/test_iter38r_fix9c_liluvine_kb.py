"""Iter38r-fix9c — Liluvine PRO Knowledge Base tests.

Validates: CRUD endpoints, PDF/TXT upload + chunking, and that
build_kb_context() correctly aggregates active entries with the budget cap.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
import pytest_asyncio
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30).json()
    if not r.get("needs_otp"):
        return r["access_token"]
    return requests.post(f"{API}/auth/verify-otp", json={
        "session_token": r["session_token"], "code": r["dev_otp"],
    }, timeout=30).json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db_sync():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_kb_crud_cycle(admin_h, db_sync):
    # CREATE
    r = requests.post(f"{API}/admin/liluvine-pro/kb", headers=admin_h, json={
        "title": "Test entry — iter38r-fix9c",
        "content": "Le port commun WhatsApp est le 8001. Liluvine PRO utilise Claude Sonnet 4.6.",
        "tags": ["test", "fix9c"],
    }, timeout=30)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    try:
        # LIST
        r2 = requests.get(f"{API}/admin/liluvine-pro/kb", headers=admin_h, timeout=30)
        assert r2.status_code == 200
        body = r2.json()
        assert any(it["id"] == eid for it in body["items"])
        assert body["stats"]["total"] >= 1

        # UPDATE
        r3 = requests.put(f"{API}/admin/liluvine-pro/kb/{eid}", headers=admin_h, json={
            "content": "Le port commun est le 8001. Mise à jour iter38r-fix9c.",
            "enabled": False,
        }, timeout=30)
        assert r3.status_code == 200
        doc = db_sync.liluvine_knowledge.find_one({"id": eid})
        assert doc["enabled"] is False
        assert "Mise à jour" in doc["content"]
    finally:
        # DELETE (soft)
        r4 = requests.delete(f"{API}/admin/liluvine-pro/kb/{eid}", headers=admin_h, timeout=30)
        assert r4.status_code == 200
        doc = db_sync.liluvine_knowledge.find_one({"id": eid})
        assert doc["is_deleted"] is True


def test_kb_txt_upload_chunks(admin_h, db_sync):
    # Build a long-ish TXT to force chunking
    content = ("Paragraphe " + ("alpha beta gamma " * 30) + "\n\n") * 5
    files = {"file": ("test.txt", content.encode("utf-8"), "text/plain")}
    r = requests.post(
        f"{API}/admin/liluvine-pro/kb/upload",
        headers=admin_h,
        files=files,
        data={"title": "Doc TXT iter38r-fix9c"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["chunks"] >= 1
    batch = body["batch"]
    try:
        rows = list(db_sync.liluvine_knowledge.find({"upload_batch": batch}))
        assert len(rows) == body["chunks"]
        assert all(r["kind"] == "txt" for r in rows)
        # Stored content total ~= input length (within reason)
        total = sum(len(r["content"]) for r in rows)
        assert total >= int(len(content) * 0.5)
    finally:
        for r in db_sync.liluvine_knowledge.find({"upload_batch": batch}):
            requests.delete(f"{API}/admin/liluvine-pro/kb/{r['id']}", headers=admin_h, timeout=10)


def test_kb_upload_rejects_oversized(admin_h):
    big = b"A" * (6 * 1024 * 1024)
    files = {"file": ("big.txt", big, "text/plain")}
    r = requests.post(
        f"{API}/admin/liluvine-pro/kb/upload",
        headers=admin_h,
        files=files,
        data={"title": "Should fail"},
        timeout=60,
    )
    assert r.status_code in (413, 400)


def test_kb_upload_rejects_unsupported(admin_h):
    # Now images ARE supported (fix9h). Test with an unsupported binary type.
    files = {"file": ("blob.bin", b"\x00" * 100, "application/octet-stream")}
    r = requests.post(
        f"{API}/admin/liluvine-pro/kb/upload",
        headers=admin_h,
        files=files,
        data={"title": "Should fail"},
        timeout=30,
    )
    assert r.status_code == 415


def test_kb_endpoints_require_admin():
    r = requests.get(f"{API}/admin/liluvine-pro/kb", timeout=30)
    assert r.status_code in (401, 403)
    r2 = requests.post(f"{API}/admin/liluvine-pro/kb",
                       json={"title": "x", "content": "y"}, timeout=30)
    assert r2.status_code in (401, 403)


@pytest.mark.asyncio
async def test_build_kb_context_respects_budget():
    """build_kb_context must aggregate enabled entries and stay within budget."""
    from routes.liluvine_kb import build_kb_context
    motor = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    # Seed 3 entries
    seed_ids = []
    for i in range(3):
        eid = f"_test_kb_ctx_{i}"
        seed_ids.append(eid)
        await motor.liluvine_knowledge.update_one(
            {"id": eid},
            {"$set": {
                "id": eid,
                "title": f"Entrée test {i}",
                "content": ("Important: " + ("contenu utile " * 60)).strip(),
                "enabled": True,
                "is_deleted": False,
                "priority": 0,
                "updated_at": "2026-05-29T00:00:00Z",
                "kind": "text",
            }},
            upsert=True,
        )
    try:
        ctx = await build_kb_context(motor, max_chars=2500)
        assert "Base de connaissance" in ctx
        assert "Entrée test" in ctx
        # Must respect budget (within 5% margin for header)
        assert len(ctx) <= 2500 + 200
        # Disabled entries must NOT appear
        await motor.liluvine_knowledge.update_one({"id": seed_ids[0]}, {"$set": {"enabled": False}})
        ctx2 = await build_kb_context(motor, max_chars=2500)
        assert "Entrée test 0" not in ctx2
    finally:
        await motor.liluvine_knowledge.delete_many({"id": {"$in": seed_ids}})
