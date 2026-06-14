"""Iter60 extras — Phase 2 Story Studio additional checks.

- social-accounts GET never exposes access_token / encrypted token fields (pages incl.)
- POST /posts/{post_id}/publish-now relaunches draft/failed posts
- GET /library/{asset_id}/signed-media?token=invalid -> 400 (covered) ; also test signed token roundtrip via real endpoint cannot
  be done without OAuth — we test the failure path only.
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


def _admin_jwt(uid: str) -> str:
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
def admin_ctx(db):
    aid = f"iter60_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": aid, "email": f"{aid}@admintest.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": aid, "headers": {"Authorization": f"Bearer {_admin_jwt(aid)}"}}
    db.users.delete_one({"id": aid})


@pytest.fixture()
def cleanup(db):
    ids = {"social": [], "posts": [], "assets": []}
    yield ids
    if ids["social"]:
        db.social_accounts.delete_many({"id": {"$in": ids["social"]}})
    if ids["posts"]:
        db.story_posts.delete_many({"id": {"$in": ids["posts"]}})
    if ids["assets"]:
        db.story_assets.delete_many({"id": {"$in": ids["assets"]}})


SENSITIVE_TOP = {"access_token", "long_lived_user_token_encrypted"}
SENSITIVE_PAGE = {"access_token", "page_access_token_encrypted"}


class TestSocialAccountsNoTokenLeak:
    def test_list_does_not_expose_tokens(self, admin_ctx, db, cleanup):
        acc_id = f"iter60_acc_{uuid.uuid4().hex[:8]}"
        cleanup["social"].append(acc_id)
        db.social_accounts.insert_one({
            "id": acc_id, "tenant_id": "tenant_iter60", "provider": "meta",
            "status": "connected", "meta_user_id": "fb_user_iter60",
            "long_lived_user_token_encrypted": "encrypted_blob_user_xxx",
            "pages": [{
                "page_id": "p1", "page_name": "Page 1", "is_active": True,
                "page_access_token_encrypted": "encrypted_blob_page_xxx",
                "ig_business_id": "ig_123",
            }],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.get(
            f"{API}/admin/story-studio/social-accounts",
            headers=admin_ctx["headers"],
            params={"tenant_id": "tenant_iter60"},
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        target = next((x for x in items if x["id"] == acc_id), None)
        assert target is not None, f"Inserted account not found in list: {items}"
        # Top-level: no sensitive fields
        leaked_top = SENSITIVE_TOP & set(target.keys())
        assert not leaked_top, f"Sensitive top-level fields leaked: {leaked_top}"
        # Pages: no sensitive fields
        for pg in target.get("pages", []):
            leaked_pg = SENSITIVE_PAGE & set(pg.keys())
            assert not leaked_pg, f"Sensitive page fields leaked: {leaked_pg}"


class TestPublishNow:
    def test_publish_now_relaunches_draft(self, admin_ctx, db, cleanup, tmp_path):
        # Insert an asset (video, ready) + a draft post
        aid = f"iter60_asset_{uuid.uuid4().hex[:8]}"
        cleanup["assets"].append(aid)
        vfile = tmp_path / "t.mp4"
        vfile.write_bytes(b"\x00" * 64)
        db.story_assets.insert_one({
            "id": aid, "tenant_id": "tenant_iter60", "kind": "video",
            "engine": "sora-2", "prompt": "p", "title": "x",
            "status": "ready",
            "url": f"/admin/story-studio/library/{aid}/media",
            "file_path": str(vfile),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        post_id = f"iter60_post_{uuid.uuid4().hex[:8]}"
        cleanup["posts"].append(post_id)
        db.story_posts.insert_one({
            "id": post_id, "asset_id": aid, "tenant_id": "tenant_iter60",
            "caption": "draft to relaunch", "mode": "immediate",
            "status": "draft",
            "targets": [{"social_account_id": "missing", "page_id": "missing",
                         "target": "fb_feed"}],
            "results": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "admin",
        })
        r = requests.post(
            f"{API}/admin/story-studio/posts/{post_id}/publish-now",
            headers=admin_ctx["headers"],
        )
        # Acceptable outcomes: 200 (with status updated) — should not 404/500
        assert r.status_code == 200, r.text
        d = r.json()
        # Final status must be one of failed/published/partial — but NOT draft anymore.
        assert d.get("status") in {"failed", "published", "partial"}, d
        # Re-check DB
        post = db.story_posts.find_one({"id": post_id})
        assert post["status"] != "draft"

    def test_publish_now_404_unknown(self, admin_ctx):
        r = requests.post(
            f"{API}/admin/story-studio/posts/unknown_iter60_xx/publish-now",
            headers=admin_ctx["headers"],
        )
        assert r.status_code == 404
