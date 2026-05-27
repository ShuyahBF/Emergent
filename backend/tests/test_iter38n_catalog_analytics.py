"""Iter38n — Catalogue public analytics."""
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
    return pyjwt.encode({
        "sub": uid, "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def tenant(db):
    """Build a tenant with admin + sup + tracked user + outsider."""
    admin_id = f"cat_adm_{uuid.uuid4().hex[:6]}"
    sup_id = f"cat_sup_{uuid.uuid4().hex[:6]}"
    tracked_id = f"cat_trk_{uuid.uuid4().hex[:6]}"
    outsider_id = f"cat_out_{uuid.uuid4().hex[:6]}"
    regular_id = f"cat_reg_{uuid.uuid4().hex[:6]}"
    company = f"CAT-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
         "full_name": "Admin Cat", "company": company, "role": "admin",
         "account_status": "active", "created_at": now},
        {"id": sup_id, "email": f"{sup_id}@t.l", "password_hash": "x",
         "full_name": "Sup Cat", "company": company, "role": "superviseur",
         "account_status": "active", "created_at": now},
        {"id": tracked_id, "email": f"{tracked_id}@t.l", "password_hash": "x",
         "full_name": "Tracked Cat", "company": company, "role": "client",
         "tracked_user_id": admin_id, "tracked_role": "Caissier",
         "account_status": "active", "created_at": now},
        {"id": regular_id, "email": f"{regular_id}@t.l", "password_hash": "x",
         "full_name": "Regular Client", "company": company, "role": "client",
         "account_status": "active", "created_at": now},
        {"id": outsider_id, "email": f"{outsider_id}@t.l", "password_hash": "x",
         "full_name": "Outsider", "company": f"OTHER-{uuid.uuid4().hex[:4]}",
         "role": "admin", "account_status": "active", "created_at": now},
    ])
    # Insert a tenant-bound product (used to derive tenant_id)
    pid = f"prod_{uuid.uuid4().hex[:8]}"
    db.products.insert_one({
        "id": pid, "tenant_id": admin_id, "client_id": admin_id,
        "name": "Laptop ProBook", "sku": "CAT-PROD-001",
        "category": "Informatique", "unit": "pièce",
        "unit_price_ht": 450000, "tva_pct": 18,
        "is_public": True, "active": True, "deleted_at": None,
    })
    yield {
        "admin_id": admin_id, "admin_token": _forge(admin_id, "admin"),
        "sup_id": sup_id, "sup_token": _forge(sup_id, "superviseur"),
        "tracked_id": tracked_id, "tracked_token": _forge(tracked_id, "client"),
        "regular_id": regular_id, "regular_token": _forge(regular_id, "client"),
        "outsider_id": outsider_id, "outsider_token": _forge(outsider_id, "admin"),
        "product_id": pid, "company": company,
    }
    db.users.delete_many({"id": {"$in": [admin_id, sup_id, tracked_id, regular_id, outsider_id]}})
    db.products.delete_one({"id": pid})
    db.catalog_events.delete_many({"tenant_id": admin_id})


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ============================================================
# Tracking endpoint
# ============================================================
def test_track_anonymous_share_event(tenant, db):
    r = requests.post(
        f"{API}/public/catalog/track",
        json={"event_type": "product_share", "product_id": tenant["product_id"],
              "product_name": "Laptop ProBook", "product_sku": "CAT-PROD-001"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Resolved tenant_id should match the product's tenant
    ev = db.catalog_events.find_one(
        {"product_id": tenant["product_id"], "event_type": "product_share"},
        sort=[("created_at", -1)],
    )
    assert ev is not None
    assert ev["tenant_id"] == tenant["admin_id"]


def test_track_invalid_event_type(tenant):
    r = requests.post(
        f"{API}/public/catalog/track",
        json={"event_type": "garbage", "product_id": tenant["product_id"]},
    )
    assert r.status_code == 422


def test_track_unknown_product_resolves_no_tenant(db):
    r = requests.post(
        f"{API}/public/catalog/track",
        json={"event_type": "product_quote_click", "product_id": "ghost-xyz"},
    )
    assert r.status_code == 200
    ev = db.catalog_events.find_one({"product_id": "ghost-xyz"}, sort=[("created_at", -1)])
    assert ev is not None
    assert ev["tenant_id"] is None
    db.catalog_events.delete_many({"product_id": "ghost-xyz"})


# ============================================================
# Stats endpoint
# ============================================================
def test_stats_accessible_to_admin_sup_tracked(tenant):
    # Seed some events
    requests.post(f"{API}/public/catalog/track",
        json={"event_type": "product_og_fetch", "product_id": tenant["product_id"], "product_name": "Laptop ProBook"})
    requests.post(f"{API}/public/catalog/track",
        json={"event_type": "product_share", "product_id": tenant["product_id"], "product_name": "Laptop ProBook"})
    requests.post(f"{API}/public/catalog/track",
        json={"event_type": "product_quote_click", "product_id": tenant["product_id"], "product_name": "Laptop ProBook"})
    for role, tok in [("admin", tenant["admin_token"]), ("sup", tenant["sup_token"]), ("tracked", tenant["tracked_token"])]:
        r = requests.get(f"{API}/me/catalog/stats?days=7", headers=_h(tok))
        assert r.status_code == 200, f"{role} got {r.status_code}: {r.text}"
        data = r.json()
        assert data["days"] == 7
        # Tenant totals must include our seeded events
        assert data["tenant_event_totals"]["og_fetches"] >= 1
        assert data["tenant_event_totals"]["shares"] >= 1
        assert data["tenant_event_totals"]["quote_clicks"] >= 1


def test_stats_forbidden_for_regular_client(tenant):
    """Non-tracked, non-admin clients should not see analytics."""
    r = requests.get(f"{API}/me/catalog/stats", headers=_h(tenant["regular_token"]))
    assert r.status_code == 403


def test_stats_top_products(tenant):
    # Make sure our product shows up in top
    for _ in range(3):
        requests.post(f"{API}/public/catalog/track",
            json={"event_type": "product_og_fetch", "product_id": tenant["product_id"],
                  "product_name": "Laptop ProBook"})
    r = requests.get(f"{API}/me/catalog/stats?days=7", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    top = r.json()["top_products"]
    assert len(top) >= 1
    product_ids = [p["product_id"] for p in top]
    assert tenant["product_id"] in product_ids


def test_stats_tenant_isolated(tenant):
    """Outsider must not see this tenant's events in their totals."""
    requests.post(f"{API}/public/catalog/track",
        json={"event_type": "product_share", "product_id": tenant["product_id"],
              "product_name": "Laptop ProBook"})
    r = requests.get(f"{API}/me/catalog/stats?days=7", headers=_h(tenant["outsider_token"]))
    assert r.status_code == 200
    data = r.json()
    # Outsider's tenant has no products, so their tenant_event_totals should
    # not include our seeded events.
    # We can't assert == 0 (other tests may run on same db), but our specific
    # tenant_id should NOT appear in their top_products.
    top_ids = [p["product_id"] for p in data["top_products"]]
    assert tenant["product_id"] not in top_ids


def test_stats_funnel_ratios(tenant):
    r = requests.get(f"{API}/me/catalog/stats?days=7", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    funnel = r.json()["funnel"]
    assert "og_fetches" in funnel
    assert "shares" in funnel
    assert "quote_clicks" in funnel
    assert "share_rate" in funnel
    assert "quote_rate" in funnel


def test_stats_daily_timeline_dense(tenant):
    r = requests.get(f"{API}/me/catalog/stats?days=7", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200
    timeline = r.json()["timeline"]
    # days=7 → 8 entries (today + 7 days back)
    assert len(timeline) == 8
    # All entries must have date/og_fetches/shares/quotes
    for t in timeline:
        assert "date" in t
        assert "og_fetches" in t
        assert "shares" in t
        assert "quotes" in t


# ============================================================
# History endpoint
# ============================================================
def test_history_returns_recent_events(tenant):
    requests.post(f"{API}/public/catalog/track",
        json={"event_type": "product_share", "product_id": tenant["product_id"],
              "product_name": "Laptop ProBook"})
    r = requests.get(f"{API}/me/catalog/history?days=1&limit=20", headers=_h(tenant["admin_token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] >= 1
    # No ip_hash should leak
    for it in data["items"]:
        assert "ip_hash" not in it


def test_history_filter_by_event_type(tenant):
    r = requests.get(
        f"{API}/me/catalog/history?days=7&event_type=product_share",
        headers=_h(tenant["admin_token"]),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    for it in items:
        assert it["event_type"] == "product_share"


def test_history_forbidden_for_regular_client(tenant):
    r = requests.get(f"{API}/me/catalog/history", headers=_h(tenant["regular_token"]))
    assert r.status_code == 403


# ============================================================
# Implicit tracking via /public/products and /public/og/product/{id}
# ============================================================
def test_catalog_view_tracked_on_public_products(db):
    before = db.catalog_events.count_documents({"event_type": "catalog_view"})
    requests.get(f"{API}/public/products")
    after = db.catalog_events.count_documents({"event_type": "catalog_view"})
    assert after >= before + 1


def test_og_fetch_tracked_on_public_og_product(tenant, db):
    before = db.catalog_events.count_documents({
        "event_type": "product_og_fetch", "product_id": tenant["product_id"],
    })
    r = requests.get(f"{API}/public/og/product/{tenant['product_id']}")
    assert r.status_code == 200
    after = db.catalog_events.count_documents({
        "event_type": "product_og_fetch", "product_id": tenant["product_id"],
    })
    assert after == before + 1
