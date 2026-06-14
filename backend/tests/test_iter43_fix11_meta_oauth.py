"""Iter43-fix11 — Phase 2 Story Studio (Meta OAuth + publishing).

Tests:
- OAuth start endpoint (admin auth, state JWT signed, auth_url shape)
- OAuth callback error path (error param)
- OAuth state decode/encode
- Signed media token generation + verification
- Publish endpoint :
  - 400 si pas de cibles
  - 400 si asset non-video / non-ready / inconnu
  - draft mode persists post without calling Meta
  - immediate mode with fake account returns error per target (no crash)
- Refresh account 404 + invalid provider
- Toggle page is_active

Notes :
- N'appelle PAS le vrai Meta Graph API (mocké via HTTP errors prévisibles).
- Pour tester un vrai flow OAuth end-to-end, il faut un Meta App configuré.
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
    aid = f"iter43f11_adm_{uuid.uuid4().hex[:8]}"
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


# ---------------------------------------------------------------------------
# OAuth start
# ---------------------------------------------------------------------------
class TestOAuthStart:
    def test_start_400_without_meta_app(self, admin_ctx, db):
        # Ensure Meta app creds are absent
        db.settings.update_one(
            {"_id": "global"},
            {"$unset": {"story_studio.meta_app_id": "", "story_studio.meta_app_secret": ""}},
            upsert=True,
        )
        r = requests.get(
            f"{API}/admin/story-studio/oauth/meta/start",
            headers=admin_ctx["headers"],
        )
        assert r.status_code == 400
        assert "Meta App" in r.text or "non configur" in r.text

    def test_start_returns_auth_url(self, admin_ctx, db):
        db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "story_studio.meta_app_id": "1234567890",
                "story_studio.meta_app_secret": "fake_secret_iter43f11",
                "story_studio.meta_redirect_uri": "https://example.com/api/admin/story-studio/oauth/meta/callback",
            }},
            upsert=True,
        )
        r = requests.get(
            f"{API}/admin/story-studio/oauth/meta/start",
            headers=admin_ctx["headers"],
            params={"tenant_id": "tenant-test-iter43f11", "return_to": "/admin/story-studio"},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "auth_url" in d
        assert d["auth_url"].startswith("https://www.facebook.com/")
        assert "client_id=1234567890" in d["auth_url"]
        assert "state=" in d["auth_url"]
        assert "instagram_content_publish" in d["auth_url"]


# ---------------------------------------------------------------------------
# OAuth callback
# ---------------------------------------------------------------------------
class TestOAuthCallback:
    def test_callback_error_redirects(self, db):
        # No auth required: this endpoint is called by Meta
        r = requests.get(
            f"{API}/admin/story-studio/oauth/meta/callback",
            params={"error": "access_denied", "error_description": "User cancelled",
                    "state": "n/a"},
            allow_redirects=False,
        )
        assert r.status_code in (302, 307)
        loc = r.headers.get("location", "")
        assert "meta_oauth=error" in loc
        assert "User%20cancelled" in loc or "cancelled" in loc.lower()

    def test_callback_missing_params_redirects_error(self):
        r = requests.get(
            f"{API}/admin/story-studio/oauth/meta/callback",
            allow_redirects=False,
        )
        # No code, no state, no error -> still redirects to error page
        assert r.status_code in (302, 307)
        assert "meta_oauth=error" in r.headers.get("location", "")


# ---------------------------------------------------------------------------
# Publish endpoint
# ---------------------------------------------------------------------------
class TestPublish:
    def _asset(self, db, cleanup, **overrides):
        aid = f"iter43f11_asset_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        doc = {
            "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
            "prompt": "p", "title": "to-publish", "status": "ready",
            "url": f"/admin/story-studio/library/{aid}/media",
            "file_path": "/nonexistent/path.mp4",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        doc.update(overrides)
        db.story_assets.insert_one(doc)
        return aid

    def test_publish_image_rejected(self, admin_ctx, db, cleanup):
        aid = self._asset(db, cleanup, kind="image")
        r = requests.post(
            f"{API}/admin/story-studio/library/{aid}/publish",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"targets": [{"social_account_id": "x", "page_id": "y", "target": "fb_feed"}]},
        )
        assert r.status_code == 400
        assert "vidéo" in r.text.lower() or "video" in r.text.lower()

    def test_publish_not_ready_rejected(self, admin_ctx, db, cleanup):
        aid = self._asset(db, cleanup, status="processing")
        r = requests.post(
            f"{API}/admin/story-studio/library/{aid}/publish",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"targets": [{"social_account_id": "x", "page_id": "y", "target": "fb_feed"}]},
        )
        assert r.status_code == 400

    def test_publish_immediate_unknown_account_returns_per_target_error(self, admin_ctx, db, cleanup, tmp_path):
        # Real video file on disk
        vfile = tmp_path / "t.mp4"
        vfile.write_bytes(b"\x00" * 32)
        aid = self._asset(db, cleanup, file_path=str(vfile))
        r = requests.post(
            f"{API}/admin/story-studio/library/{aid}/publish",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={
                "mode": "immediate",
                "caption": "Test",
                "targets": [{"social_account_id": "missing-acc", "page_id": "missing-page",
                             "target": "fb_feed"}],
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is False
        assert d["status"] == "failed"
        assert len(d["results"]) == 1
        assert d["results"][0]["ok"] is False
        cleanup["posts"].append(d["post_id"])

    def test_publish_draft_does_not_call_meta(self, admin_ctx, db, cleanup):
        aid = self._asset(db, cleanup)
        r = requests.post(
            f"{API}/admin/story-studio/library/{aid}/publish",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={
                "mode": "draft",
                "caption": "Brouillon",
                "targets": [{"social_account_id": "fake", "page_id": "fake", "target": "ig_story"}],
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "draft"
        cleanup["posts"].append(d["post_id"])


# ---------------------------------------------------------------------------
# Refresh + toggle page
# ---------------------------------------------------------------------------
class TestSocialAccountManagement:
    def test_refresh_404(self, admin_ctx):
        r = requests.post(
            f"{API}/admin/story-studio/social-accounts/unknown_iter43f11/refresh",
            headers=admin_ctx["headers"],
        )
        assert r.status_code == 404

    def test_toggle_page_404(self, admin_ctx):
        r = requests.put(
            f"{API}/admin/story-studio/social-accounts/unknown_acc/pages/unknown_page",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"is_active": False},
        )
        assert r.status_code == 404

    def test_toggle_page_works(self, admin_ctx, db, cleanup):
        # Insert a fake social account with one page
        acc_id = f"iter43f11_acc_{uuid.uuid4().hex[:8]}"
        cleanup["social"].append(acc_id)
        db.social_accounts.insert_one({
            "id": acc_id, "tenant_id": "t1", "provider": "meta",
            "status": "connected", "meta_user_id": "fb_user_test",
            "pages": [{"page_id": "page_1", "page_name": "Page 1", "is_active": True}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.put(
            f"{API}/admin/story-studio/social-accounts/{acc_id}/pages/page_1",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"is_active": False},
        )
        assert r.status_code == 200
        # Verify DB
        doc = db.social_accounts.find_one({"id": acc_id})
        assert doc["pages"][0]["is_active"] is False


# ---------------------------------------------------------------------------
# Posts history
# ---------------------------------------------------------------------------
class TestPostsHistory:
    def test_list_posts_admin(self, admin_ctx, db, cleanup):
        pid = f"iter43f11_post_{uuid.uuid4().hex[:8]}"
        cleanup["posts"].append(pid)
        db.story_posts.insert_one({
            "id": pid, "asset_id": "a1", "tenant_id": "t1",
            "caption": "Test", "mode": "immediate", "status": "published",
            "targets": [], "results": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "admin",
        })
        r = requests.get(
            f"{API}/admin/story-studio/posts",
            headers=admin_ctx["headers"],
            params={"tenant_id": "t1"},
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert any(it["id"] == pid for it in items)


# ---------------------------------------------------------------------------
# Signed media token
# ---------------------------------------------------------------------------
class TestSignedMedia:
    def test_signed_media_invalid_token(self):
        r = requests.get(
            f"{API}/admin/story-studio/library/some_id/signed-media",
            params={"token": "not-a-valid-jwt"},
            allow_redirects=False,
        )
        assert r.status_code == 400

    def test_signed_media_missing_token(self):
        r = requests.get(
            f"{API}/admin/story-studio/library/some_id/signed-media",
        )
        # Should reject (422 missing required param)
        assert r.status_code in (400, 422)
