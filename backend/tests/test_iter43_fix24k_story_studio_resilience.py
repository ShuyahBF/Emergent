"""Iter43-fix24k (2026-06) — Tests pour la résilience Story Studio :
- Stockage Emergent Object Storage en plus du disque local (persistance redéploiement)
- Re-download depuis source_url (Fal.ai CDN) si fichier manquant
- Marquage `expired` si tout échoue.
"""
import os
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sawalismartsystems.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@Sawali2026")

STORY_DIR = Path("/app/backend/uploads/stories")


@pytest_asyncio.fixture
async def db():
    c = AsyncIOMotorClient(MONGO_URL)
    database = c[DB_NAME]
    # cleanup any test assets
    await database.story_assets.delete_many({"id": {"$regex": "^test-fix24k-"}})
    yield database
    await database.story_assets.delete_many({"id": {"$regex": "^test-fix24k-"}})
    c.close()


@pytest.fixture(scope="module")
def admin_token():
    with httpx.Client(timeout=15) as client:
        r1 = client.post(
            f"{API_BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        data1 = r1.json()
        if not data1.get("needs_otp"):
            return data1.get("access_token") or data1.get("token")
        sess = data1["session_token"]
        otp = data1.get("dev_otp")
        r2 = client.post(
            f"{API_BASE}/auth/verify-otp",
            json={"session_token": sess, "code": otp},
        )
        return r2.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.mark.asyncio
async def test_ensure_local_file_returns_path_when_file_exists(db):
    """Cas 1 : le fichier existe localement → retourne directement."""
    asset_id = f"test-fix24k-{uuid.uuid4().hex[:8]}"
    STORY_DIR.mkdir(parents=True, exist_ok=True)
    test_file = STORY_DIR / f"fal_{asset_id}.mp4"
    test_file.write_bytes(b"fake-mp4-content")
    try:
        await db.story_assets.insert_one({
            "id": asset_id, "kind": "video", "engine": "fal",
            "status": "ready", "file_path": str(test_file),
            "tenant_id": "test", "created_at": "2026-06-16T01:00:00+00:00",
        })
        # Import depuis le module (la fonction est définie dans la closure setup_story_studio_routes,
        # donc on teste via le endpoint media qui l'utilise).
        # Login → fetch via signed-media n'est pas testable simplement. Test via library/media :
        with httpx.Client(timeout=15) as client:
            # GET library/{id}/media nécessite auth admin
            r1 = client.post(
                f"{API_BASE}/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            )
            data1 = r1.json()
            if data1.get("needs_otp"):
                otp = data1.get("dev_otp")
                r2 = client.post(
                    f"{API_BASE}/auth/verify-otp",
                    json={"session_token": data1["session_token"], "code": otp},
                )
                token = r2.json()["access_token"]
            else:
                token = data1.get("access_token") or data1.get("token")
            r = client.get(
                f"{API_BASE}/admin/story-studio/library/{asset_id}/media",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200, r.text[:200]
        assert r.content == b"fake-mp4-content"
    finally:
        if test_file.exists():
            test_file.unlink()


@pytest.mark.asyncio
async def test_ensure_local_file_marks_expired_when_all_sources_fail(db, auth_headers):
    """Cas 5 : pas de file_path valide, pas de storage_path, pas de source_url
    → l'asset doit être marqué `expired` et l'endpoint retourner 410."""
    asset_id = f"test-fix24k-{uuid.uuid4().hex[:8]}"
    await db.story_assets.insert_one({
        "id": asset_id, "kind": "video", "engine": "fal",
        "status": "ready",
        "file_path": "/tmp/nonexistent-deliberately.mp4",
        # NO storage_path, NO source_url
        "tenant_id": "test", "created_at": "2026-06-16T01:00:00+00:00",
    })
    with httpx.Client(timeout=15) as client:
        r = client.get(
            f"{API_BASE}/admin/story-studio/library/{asset_id}/media",
            headers=auth_headers,
        )
    assert r.status_code == 410, r.text[:200]
    body = r.json()
    assert "expirée" in body.get("detail", "").lower() or "régénérez" in body.get("detail", "").lower()
    # L'asset doit avoir été marqué expired
    fresh = await db.story_assets.find_one({"id": asset_id})
    assert fresh["status"] == "expired"
    assert "expired_at" in fresh
    assert "expired_reason" in fresh


@pytest.mark.asyncio
async def test_ensure_local_file_restores_from_source_url(db, auth_headers, monkeypatch):
    """Cas 4 : fichier local manquant mais source_url valide → re-download
    et retourne le contenu."""
    asset_id = f"test-fix24k-{uuid.uuid4().hex[:8]}"
    # On utilise httpbin pour faire un faux CDN qui renvoie des bytes connus
    source_url = "https://httpbin.org/bytes/64?seed=42"
    await db.story_assets.insert_one({
        "id": asset_id, "kind": "video", "engine": "fal",
        "status": "ready",
        "file_path": f"/app/backend/uploads/stories/fal_{asset_id}.mp4",
        "source_url": source_url,
        "tenant_id": "test", "created_at": "2026-06-16T01:00:00+00:00",
    })
    # Le fichier n'existe pas sur disque → le helper doit re-download depuis source_url
    target = Path(f"/app/backend/uploads/stories/fal_{asset_id}.mp4")
    if target.exists():
        target.unlink()
    try:
        with httpx.Client(timeout=30) as client:
            r = client.get(
                f"{API_BASE}/admin/story-studio/library/{asset_id}/media",
                headers=auth_headers,
            )
        assert r.status_code == 200, r.text[:200]
        # Le fichier doit avoir été restauré sur disque
        assert target.exists()
        # L'asset doit avoir status=ready avec restored_from=source_url
        fresh = await db.story_assets.find_one({"id": asset_id})
        assert fresh["status"] == "ready"
        assert fresh.get("restored_from") == "source_url"
    finally:
        if target.exists():
            target.unlink()


@pytest.mark.asyncio
async def test_library_lists_expired_assets(db, auth_headers):
    """La bibliothèque doit retourner aussi les assets `expired` (pas seulement `ready`).
    L'admin doit pouvoir les voir avec un badge pour les régénérer."""
    asset_id = f"test-fix24k-{uuid.uuid4().hex[:8]}"
    await db.story_assets.insert_one({
        "id": asset_id, "kind": "video", "engine": "fal",
        "status": "expired",
        "expired_reason": "Test expired",
        "tenant_id": "test",
        "title": "Test Expired Asset",
        "prompt": "test prompt",
        "created_at": "2026-06-16T01:00:00+00:00",
    })
    with httpx.Client(timeout=15) as client:
        r = client.get(
            f"{API_BASE}/admin/story-studio/library?limit=200",
            headers=auth_headers,
        )
    assert r.status_code == 200
    items = r.json().get("items", [])
    ids = [it["id"] for it in items]
    assert asset_id in ids, f"Asset expired pas dans la liste : {ids[:3]}"
    found = next(it for it in items if it["id"] == asset_id)
    assert found["status"] == "expired"
    assert found["expired_reason"] == "Test expired"
