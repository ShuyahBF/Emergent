"""S038 — Qdrant RAG: connection, collection CRUD, upsert, search,
Liluvine integration."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

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


def test_qdrant_test_connection_ok(admin_h):
    r = requests.post(f"{API}/admin/qdrant/test-connection", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert "url" in body
    assert isinstance(body.get("collections"), int)


def test_qdrant_collection_full_lifecycle(admin_h):
    """Create → upsert text → search → browse → delete."""
    coll_name = f"test_{uuid.uuid4().hex[:8]}"
    # CREATE
    r = requests.post(f"{API}/admin/qdrant/collections", headers=admin_h,
                      json={"name": coll_name, "description": "Test collection"}, timeout=30)
    assert r.status_code == 200, r.text
    try:
        # LIST (must include our coll)
        r = requests.get(f"{API}/admin/qdrant/collections", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        names = [c["name"] for c in r.json().get("items", [])]
        assert coll_name in names

        # UPSERT TEXT
        r = requests.post(
            f"{API}/admin/qdrant/collections/{coll_name}/points/text",
            headers=admin_h,
            json={
                "title": "Présentation SAWALI",
                "text": ("SAWALI Smart Systems est une entreprise basée en Côte d'Ivoire spécialisée "
                         "dans le développement de solutions logicielles et CRM. Liluvine PRO est leur "
                         "assistant IA intégré qui aide à gérer contacts, tickets et facturation."),
                "source": "fixture-test",
                "tags": ["test", "presentation"],
            }, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("inserted_chunks", 0) >= 1

        # SEARCH (French semantic query)
        r = requests.post(
            f"{API}/admin/qdrant/collections/{coll_name}/search",
            headers=admin_h,
            json={"query": "Que fait l'entreprise SAWALI ?", "top_k": 3}, timeout=30,
        )
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        assert len(items) >= 1
        # Score should be reasonably high (>0.3) for direct query
        assert items[0]["score"] > 0.3
        assert "SAWALI" in items[0]["text"]

        # BROWSE
        r = requests.get(
            f"{API}/admin/qdrant/collections/{coll_name}/points?limit=10",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("total", 0) >= 1
        assert len(r.json().get("items", [])) >= 1

        # PATCH (toggle enabled_for_liluvine)
        r = requests.patch(
            f"{API}/admin/qdrant/collections/{coll_name}",
            headers=admin_h,
            json={"enabled_for_liluvine": True, "description": "Updated"}, timeout=30,
        )
        assert r.status_code == 200, r.text
    finally:
        # DELETE
        r = requests.delete(f"{API}/admin/qdrant/collections/{coll_name}",
                            headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text


def test_qdrant_create_rejects_invalid_name(admin_h):
    r = requests.post(f"{API}/admin/qdrant/collections", headers=admin_h,
                      json={"name": "invalid name with spaces!"}, timeout=30)
    assert r.status_code == 400


def test_qdrant_search_empty_query_400(admin_h):
    # Need an existing collection
    coll = f"qs_{uuid.uuid4().hex[:6]}"
    requests.post(f"{API}/admin/qdrant/collections", headers=admin_h, json={"name": coll}, timeout=30)
    try:
        r = requests.post(f"{API}/admin/qdrant/collections/{coll}/search",
                          headers=admin_h, json={"query": "  "}, timeout=30)
        assert r.status_code == 400
    finally:
        requests.delete(f"{API}/admin/qdrant/collections/{coll}", headers=admin_h, timeout=30)


def test_qdrant_403_for_non_admin(admin_h):
    """Non-admin must be blocked from any Qdrant endpoint."""
    from pymongo import MongoClient
    from datetime import datetime, timezone
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    uid = str(uuid.uuid4())
    email = f"qdrant-block-{uuid.uuid4().hex[:6]}@test.com"
    password = "QdrantBlock!2026"
    from auth import hash_password
    db.users.insert_one({
        "id": uid, "email": email, "full_name": "Block",
        "password_hash": hash_password(password),
        "role": "client", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        tok = _login(email, password)
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.post(f"{API}/admin/qdrant/test-connection", headers=h, timeout=30)
        assert r.status_code == 403
        r = requests.get(f"{API}/admin/qdrant/collections", headers=h, timeout=30)
        assert r.status_code == 403
    finally:
        db.users.delete_one({"id": uid})


def test_build_rag_context_returns_relevant_chunk():
    """End-to-end: enable Qdrant in settings, seed a collection, then call
    build_rag_context. The result must contain the seeded info."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from routes.qdrant_rag import (
        build_rag_context, create_collection, upsert_text_documents, delete_collection,
    )
    coll = f"rag_{uuid.uuid4().hex[:6]}"

    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"qdrant_enabled": True}}, upsert=True,
        )
        await create_collection(db, name=coll, description="rag test")
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {f"qdrant_collection_settings.{coll}.enabled_for_liluvine": True}},
        )
        await upsert_text_documents(db, collection=coll, docs=[{
            "title": "Horaires",
            "text": "Les bureaux SAWALI sont ouverts du lundi au vendredi de 8h à 18h. "
                    "Le samedi de 9h à 13h. Fermé le dimanche.",
            "source": "fixture",
            "tags": ["horaires"],
        }])
        ctx = await build_rag_context(db, query="À quelle heure fermez-vous le samedi ?", max_chars=2000)
        assert "Horaires" in ctx or "samedi" in ctx.lower()
        assert "lundi" in ctx.lower() or "13h" in ctx.lower()
        # Cleanup
        await delete_collection(db, name=coll)

    try:
        asyncio.get_event_loop().run_until_complete(go())
    except RuntimeError:
        asyncio.run(go())
