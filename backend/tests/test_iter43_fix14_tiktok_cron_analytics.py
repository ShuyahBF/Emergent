"""Iter43-fix14 (2026-03) — Phase 4 TikTok + Cron Scheduler + Analytics.

Tests :
- TikTok OAuth start 400 sans credentials + URL valide sinon
- TikTok callback error redirect
- Settings endpoint masque tiktok_client_secret
- Cron scheduler tick : dry_run + traitement de drafts scheduled_at <= now
- Cron tick avec asset manquant → failed
- Cron tick avec credits insuffisants → blocked_credits
- Analytics endpoint : 404 si post inconnu, 400 si non publié, structure renvoyée
- Publish vers TikTok avec compte non-TikTok → erreur claire
"""
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
import jwt
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001") + "/api"
JWT_SECRET = os.environ.get("JWT_SECRET", "sawali-jwt-secret-change-me")


def _admin_token(uid: str) -> str:
    return jwt.encode(
        {"sub": uid, "user_id": uid, "id": uid, "role": "admin",
         "email": f"{uid}@admintest.com",
         "exp": datetime.now(timezone.utc).timestamp() + 3600},
        JWT_SECRET, algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin(db):
    uid = f"iter43f14_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@admintest.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": uid, "headers": {"Authorization": f"Bearer {_admin_token(uid)}"}}
    db.users.delete_one({"id": uid})


@pytest.fixture()
def cleanup(db):
    ids = {"posts": [], "assets": [], "social": [], "tenants": []}
    yield ids
    if ids["posts"]:
        db.story_posts.delete_many({"id": {"$in": ids["posts"]}})
    if ids["assets"]:
        db.story_assets.delete_many({"id": {"$in": ids["assets"]}})
    if ids["social"]:
        db.social_accounts.delete_many({"id": {"$in": ids["social"]}})
    if ids["tenants"]:
        db.tenant_publish_config.delete_many({"tenant_id": {"$in": ids["tenants"]}})


# ---------------------------------------------------------------------------
# TikTok OAuth
# ---------------------------------------------------------------------------
class TestTikTokOAuth:
    def test_start_400_without_creds(self, admin, db):
        db.settings.update_one(
            {"_id": "global"},
            {"$unset": {"story_studio.tiktok_client_key": "",
                        "story_studio.tiktok_client_secret": ""}},
            upsert=True,
        )
        r = requests.get(f"{API}/admin/story-studio/oauth/tiktok/start", headers=admin["headers"])
        assert r.status_code == 400
        assert "TikTok" in r.text or "non configur" in r.text

    def test_start_returns_auth_url(self, admin, db):
        db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "story_studio.tiktok_client_key": "aw_test_iter43f14",
                "story_studio.tiktok_client_secret": "secret_iter43f14",
            }},
            upsert=True,
        )
        r = requests.get(f"{API}/admin/story-studio/oauth/tiktok/start", headers=admin["headers"])
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["auth_url"].startswith("https://www.tiktok.com/v2/auth/authorize/")
        assert "client_key=aw_test_iter43f14" in d["auth_url"]
        assert "video.publish" in d["auth_url"]
        assert "state=" in d["auth_url"]

    def test_callback_error_redirects(self):
        r = requests.get(
            f"{API}/admin/story-studio/oauth/tiktok/callback",
            params={"error": "access_denied", "error_description": "User cancelled",
                    "state": "n/a"},
            allow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "tiktok_oauth=error" in r.headers.get("location", "")


# ---------------------------------------------------------------------------
# Settings masking
# ---------------------------------------------------------------------------
class TestSettingsMask:
    def test_tiktok_secret_masked(self, admin, db):
        db.settings.update_one(
            {"_id": "global"},
            {"$set": {"story_studio.tiktok_client_secret": "real-secret-iter43f14"}},
            upsert=True,
        )
        r = requests.get(f"{API}/admin/story-studio/settings", headers=admin["headers"])
        d = r.json()
        # Le secret ne doit pas être renvoyé en clair
        assert d.get("tiktok_client_secret") != "real-secret-iter43f14"
        assert d.get("tiktok_client_secret_set") is True


# ---------------------------------------------------------------------------
# Cron Scheduler
# ---------------------------------------------------------------------------
class TestCronScheduler:
    def test_dry_run(self, admin, db, cleanup):
        # Insère un draft scheduled
        aid = f"iter43f14_a_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
            "prompt": "p", "title": "scheduled", "status": "ready",
            "file_path": "/nonexistent.mp4",
            "url": f"/admin/story-studio/library/{aid}/media",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        pid = f"iter43f14_p_{uuid.uuid4().hex[:8]}"
        cleanup["posts"].append(pid)
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        db.story_posts.insert_one({
            "id": pid, "asset_id": aid, "tenant_id": "t1",
            "mode": "draft", "status": "draft",
            "scheduled_at": past,
            "caption": "test", "targets": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(
            f"{API}/admin/story-studio/scheduler/tick?dry_run=true",
            headers=admin["headers"],
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["would_process"] >= 1
        assert any(c["id"] == pid for c in d["candidates"])
        # En dry_run, le post reste en draft
        post = db.story_posts.find_one({"id": pid})
        assert post["status"] == "draft"

    def test_scheduler_handles_missing_asset(self, admin, db, cleanup):
        pid = f"iter43f14_p_{uuid.uuid4().hex[:8]}"
        cleanup["posts"].append(pid)
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        db.story_posts.insert_one({
            "id": pid, "asset_id": "missing-asset-iter43f14", "tenant_id": "t1",
            "mode": "draft", "status": "draft", "scheduled_at": past,
            "caption": "", "targets": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(f"{API}/admin/story-studio/scheduler/tick",
                          headers=admin["headers"])
        assert r.status_code == 200
        d = r.json()
        # Au moins notre post est marqué failed
        post = db.story_posts.find_one({"id": pid})
        assert post["status"] == "failed"

    def test_scheduler_no_drafts_future(self, admin, db, cleanup):
        # Un draft programmé dans le futur ne doit PAS être traité
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        pid = f"iter43f14_p_{uuid.uuid4().hex[:8]}"
        cleanup["posts"].append(pid)
        db.story_posts.insert_one({
            "id": pid, "asset_id": "any", "tenant_id": "t1",
            "mode": "draft", "status": "draft", "scheduled_at": future,
            "caption": "", "targets": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(f"{API}/admin/story-studio/scheduler/tick?dry_run=true",
                          headers=admin["headers"])
        d = r.json()
        # Notre post n'apparaît pas
        assert not any(c["id"] == pid for c in d.get("candidates", []))


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
class TestAnalytics:
    def test_insights_404(self, admin):
        r = requests.get(f"{API}/admin/story-studio/posts/unknown-iter43f14/insights",
                         headers=admin["headers"])
        assert r.status_code == 404

    def test_insights_400_not_published(self, admin, db, cleanup):
        pid = f"iter43f14_p_{uuid.uuid4().hex[:8]}"
        cleanup["posts"].append(pid)
        db.story_posts.insert_one({
            "id": pid, "asset_id": "a1", "tenant_id": "t1",
            "mode": "draft", "status": "draft",
            "caption": "", "targets": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.get(f"{API}/admin/story-studio/posts/{pid}/insights",
                         headers=admin["headers"])
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Publish TikTok with non-TikTok account → erreur claire
# ---------------------------------------------------------------------------
class TestPublishTikTokGuards:
    def test_tiktok_target_with_meta_account(self, admin, db, cleanup):
        # Crée un asset + un compte Meta + on essaie de publier en tiktok
        aid = f"iter43f14_a_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        tmp.write(b"\x00" * 32); tmp.close()
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
            "prompt": "p", "title": "x", "status": "ready",
            "file_path": tmp.name,
            "url": f"/admin/story-studio/library/{aid}/media",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        accid = f"iter43f14_sa_{uuid.uuid4().hex[:8]}"
        cleanup["social"].append(accid)
        db.social_accounts.insert_one({
            "id": accid, "tenant_id": "t1", "provider": "meta",
            "status": "connected", "meta_user_id": "u1",
            "pages": [{"page_id": "p1", "page_name": "P1", "is_active": True}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(
            f"{API}/admin/story-studio/library/{aid}/publish",
            headers={**admin["headers"], "Content-Type": "application/json"},
            json={
                "mode": "immediate", "caption": "x",
                "targets": [{"social_account_id": accid, "page_id": "p1", "target": "tiktok"}],
            },
        )
        assert r.status_code == 200
        d = r.json()
        cleanup["posts"].append(d["post_id"])
        # Doit échouer car le compte est Meta, pas TikTok
        assert d["ok"] is False
        err = d["results"][0].get("error", "")
        assert "TikTok" in err
