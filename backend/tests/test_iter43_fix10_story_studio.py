"""Iter43-fix10 — Smoke tests Story Studio (Phase 1 MVP).

Couvre :
- GET/PUT settings (admin only, masquage des secrets)
- POST manual social account
- GET library scoping
- POST publish stub (mock OK)
- GET whatsapp-share deep link

Ne teste PAS la génération AI réelle (Sora 2, Fal.ai, Nano Banana) car
appels externes coûteux. La logique est testée par mock direct des helpers.
"""
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient
import jwt
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001") + "/api"
JWT_SECRET = os.environ.get("JWT_SECRET", "sawali-jwt-secret-change-me")


def _forge_admin(uid: str) -> str:
    return jwt.encode(
        {"sub": uid, "user_id": uid, "id": uid, "role": "admin", "email": f"{uid}@admintest.com",
         "exp": datetime.now(timezone.utc).timestamp() + 3600},
        JWT_SECRET, algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_ctx(db):
    aid = f"iter43f10_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@admintest.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "headers": {"Authorization": f"Bearer {_forge_admin(aid)}"}}
    db.users.delete_one({"id": aid})


@pytest.fixture()
def cleanup(db):
    ids = {"assets": [], "social": [], "posts": []}
    yield ids
    if ids["assets"]:
        db.story_assets.delete_many({"id": {"$in": ids["assets"]}})
    if ids["social"]:
        db.social_accounts.delete_many({"id": {"$in": ids["social"]}})
    if ids["posts"]:
        db.story_posts.delete_many({"id": {"$in": ids["posts"]}})


class TestSettings:
    def test_get_settings(self, admin_ctx):
        r = requests.get(f"{API}/admin/story-studio/settings", headers=admin_ctx["headers"])
        assert r.status_code == 200, r.text
        data = r.json()
        # Champs présents (peuvent être null/false par défaut)
        assert "fal_api_key_set" in data
        assert "sora_enabled" in data
        assert "default_caption_template" in data

    def test_put_settings_and_mask(self, admin_ctx, db):
        # Set la clé Fal
        r = requests.put(
            f"{API}/admin/story-studio/settings",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"fal_api_key": "fal_test_iter43f10_key_secret123", "fal_default_model": "fal-ai/veo3/text-to-video"},
        )
        assert r.status_code == 200, r.text
        # Re-fetch et vérifier le masque
        r2 = requests.get(f"{API}/admin/story-studio/settings", headers=admin_ctx["headers"])
        d = r2.json()
        assert d["fal_api_key_set"] is True
        assert d["fal_api_key"].startswith("***")
        assert d["fal_api_key"].endswith("t123")  # last 4 chars
        assert d["fal_default_model"] == "fal-ai/veo3/text-to-video"
        # Vérifie en DB
        doc = db.settings.find_one({"_id": "global"})
        assert doc["story_studio"]["fal_api_key"] == "fal_test_iter43f10_key_secret123"

    def test_put_settings_masked_passthrough_keeps_secret(self, admin_ctx, db):
        # Ré-envoyer un masque ne doit pas écraser la vraie clé
        r = requests.put(
            f"{API}/admin/story-studio/settings",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"fal_api_key": "***t123", "fal_default_model": "fal-ai/veo3/text-to-video"},
        )
        assert r.status_code == 200
        doc = db.settings.find_one({"_id": "global"})
        # La vraie clé est restée
        assert doc["story_studio"]["fal_api_key"] == "fal_test_iter43f10_key_secret123"

    def test_put_settings_empty_400(self, admin_ctx):
        r = requests.put(
            f"{API}/admin/story-studio/settings",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"random_field": "ignored"},
        )
        assert r.status_code == 400


class TestSocialAccounts:
    def test_add_manual_and_list(self, admin_ctx, cleanup):
        # Add
        r = requests.post(
            f"{API}/admin/story-studio/social-accounts/manual",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={
                "tenant_id": "tenant_test_iter43f10",
                "provider": "instagram",
                "account_id": "17841400123456789",
                "account_label": "Liluvine IG Business",
                "access_token": "EAAB_test_long_lived_token_xyz",
            },
        )
        assert r.status_code == 200, r.text
        acc = r.json()["account"]
        cleanup["social"].append(acc["id"])
        # Le token ne doit PAS être dans la réponse
        assert "access_token" not in acc
        # List
        r2 = requests.get(
            f"{API}/admin/story-studio/social-accounts",
            headers=admin_ctx["headers"],
            params={"tenant_id": "tenant_test_iter43f10"},
        )
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert any(x["id"] == acc["id"] for x in items)
        # Aucun item ne doit exposer le token
        assert all("access_token" not in x for x in items)

    def test_add_manual_invalid_provider(self, admin_ctx):
        r = requests.post(
            f"{API}/admin/story-studio/social-accounts/manual",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"tenant_id": "t1", "provider": "twitter", "account_id": "x",
                  "account_label": "x", "access_token": "x"},
        )
        assert r.status_code == 400


class TestLibrary:
    def test_list_empty(self, admin_ctx):
        r = requests.get(f"{API}/admin/story-studio/library", headers=admin_ctx["headers"])
        assert r.status_code == 200
        assert "items" in r.json()

    def test_list_with_assets(self, admin_ctx, db, cleanup):
        # Insert manuellement 2 assets
        aid1 = f"iter43f10_asset_{uuid.uuid4().hex[:8]}"
        aid2 = f"iter43f10_asset_{uuid.uuid4().hex[:8]}"
        cleanup["assets"] += [aid1, aid2]
        for i, aid in enumerate([aid1, aid2]):
            db.story_assets.insert_one({
                "id": aid, "tenant_id": "t1",
                "kind": "video" if i == 0 else "image",
                "engine": "sora-2", "prompt": f"test prompt {i}",
                "title": f"Asset {i}", "status": "ready", "url": f"/uploads/stories/x{i}.mp4",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by_id": admin_ctx["id"],
            })
        r = requests.get(f"{API}/admin/story-studio/library", headers=admin_ctx["headers"])
        ids = [x["id"] for x in r.json()["items"]]
        assert aid1 in ids and aid2 in ids
        # Filtre kind=image
        r2 = requests.get(f"{API}/admin/story-studio/library", headers=admin_ctx["headers"], params={"kind": "image"})
        ids2 = [x["id"] for x in r2.json()["items"]]
        assert aid2 in ids2 and aid1 not in ids2

    def test_stream_media_404(self, admin_ctx):
        r = requests.get(f"{API}/admin/story-studio/library/unknown_fix10a/media", headers=admin_ctx["headers"])
        assert r.status_code == 404

    def test_stream_media_410_when_file_missing(self, admin_ctx, db, cleanup):
        aid = f"iter43f10a_asset_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
            "prompt": "p", "title": "x", "status": "ready",
            "url": f"/admin/story-studio/library/{aid}/media",
            "file_path": "/nonexistent/path.mp4",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.get(f"{API}/admin/story-studio/library/{aid}/media", headers=admin_ctx["headers"])
        assert r.status_code == 410

    def test_stream_media_returns_file(self, admin_ctx, db, cleanup, tmp_path):
        aid = f"iter43f10a_asset_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        # Crée un faux fichier mp4 sur disque
        from pathlib import Path as _P
        upload_dir = _P(os.environ.get("UPLOAD_DIR", "/app/backend/uploads")) / "stories"
        upload_dir.mkdir(parents=True, exist_ok=True)
        fpath = upload_dir / f"sora_{aid}.mp4"
        fpath.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        try:
            db.story_assets.insert_one({
                "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
                "prompt": "p", "title": "x", "status": "ready",
                "url": f"/admin/story-studio/library/{aid}/media",
                "file_path": str(fpath),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = requests.get(f"{API}/admin/story-studio/library/{aid}/media", headers=admin_ctx["headers"])
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("video/mp4")
            assert len(r.content) == 12  # len(b"\x00\x00\x00\x18ftypmp42")
        finally:
            if fpath.exists():
                fpath.unlink()

    def test_library_migrates_old_uploads_url(self, admin_ctx, db, cleanup):
        """L'ancienne URL `/uploads/stories/...` doit être migrée à la lecture."""
        aid = f"iter43f10a_oldurl_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2-pro",
            "prompt": "p", "title": "old", "status": "ready",
            "url": "/uploads/stories/sora_old.mp4",  # ancienne forme
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.get(f"{API}/admin/story-studio/library", headers=admin_ctx["headers"])
        item = next((x for x in r.json()["items"] if x["id"] == aid), None)
        assert item is not None
        assert item["url"] == f"/admin/story-studio/library/{aid}/media"

    def test_whatsapp_share_link(self, admin_ctx, db, cleanup):
        aid = f"iter43f10_asset_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
            "prompt": "p", "title": "Story Test WA", "status": "ready",
            "url": "/uploads/stories/wa_test.mp4",
            "caption": "Bonjour 👋",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by_id": admin_ctx["id"],
        })
        r = requests.get(f"{API}/admin/story-studio/library/{aid}/whatsapp-share", headers=admin_ctx["headers"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["deep_link"].startswith("whatsapp://send?text=")
        assert data["web_fallback"].startswith("https://wa.me/?text=")
        assert "/uploads/stories/wa_test.mp4" in data["media_url"]
        assert "Bonjour" in data["caption"]

    def test_whatsapp_share_unknown_asset_404(self, admin_ctx):
        r = requests.get(f"{API}/admin/story-studio/library/nonexistent_iter43f10/whatsapp-share", headers=admin_ctx["headers"])
        assert r.status_code == 404

    def test_delete_asset(self, admin_ctx, db, cleanup):
        aid = f"iter43f10_asset_{uuid.uuid4().hex[:8]}"
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "t1", "kind": "image", "engine": "nano-banana",
            "prompt": "p", "title": "to-delete", "status": "ready", "url": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.delete(f"{API}/admin/story-studio/library/{aid}", headers=admin_ctx["headers"])
        assert r.status_code == 200
        assert db.story_assets.find_one({"id": aid}) is None


class TestPublishStub:
    def test_publish_no_targets_400(self, admin_ctx, db, cleanup):
        aid = f"iter43f10_asset_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
            "prompt": "p", "title": "to-publish", "status": "ready", "url": "/x.mp4",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Phase 2: empty targets must be rejected.
        r = requests.post(
            f"{API}/admin/story-studio/library/{aid}/publish",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"targets": [], "caption": "Test"},
        )
        assert r.status_code == 400, r.text
        assert "cible" in r.text.lower()

    def test_publish_draft_mode_persists_post(self, admin_ctx, db, cleanup):
        aid = f"iter43f10_asset_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
            "prompt": "p", "title": "draft", "status": "ready",
            "url": f"/admin/story-studio/library/{aid}/media",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(
            f"{API}/admin/story-studio/library/{aid}/publish",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={
                "mode": "draft",
                "caption": "Brouillon test",
                "targets": [
                    {"social_account_id": "fake-acc-id", "page_id": "fake-page",
                     "target": "fb_feed"}
                ],
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "draft"
        cleanup["posts"].append(d["post_id"])
        # Vérifie en DB
        post = db.story_posts.find_one({"id": d["post_id"]})
        assert post["status"] == "draft"
        assert post["caption"] == "Brouillon test"
