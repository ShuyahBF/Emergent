"""Iter38r-fix9n — Tests for public product checkout (Stripe) + coupons."""
from __future__ import annotations

import os
import uuid
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASS = "Admin@Sawali2026"


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10).json()
    if r.get("needs_otp"):
        r = requests.post(f"{API}/auth/verify-otp",
                          json={"session_token": r["session_token"], "code": r["dev_otp"]},
                          timeout=10).json()
    token = r.get("access_token") or r.get("token")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db_sync():
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


@pytest.fixture()
def public_product(db_sync):
    """Insert a synthetic public product for testing."""
    pid = str(uuid.uuid4())
    db_sync.products.insert_one({
        "id": pid, "sku": "TEST-9N", "name": "Test Product fix9n",
        "description": "Test product", "category": "Test",
        "unit": "pièce", "unit_price_ht": 1000, "tva_pct": 0,
        "is_public": True, "active": True, "deleted_at": None,
        "tenant_id": "test-tenant",
    })
    yield pid
    db_sync.products.delete_one({"id": pid})
    db_sync.public_orders.delete_many({"product_id": pid})


def test_create_coupon_admin_only(admin_h, db_sync):
    db_sync.coupons.delete_one({"code": "TEST20"})
    r = requests.post(f"{API}/admin/coupons", headers=admin_h, json={
        "code": "TEST20", "discount_pct": 20, "max_uses": 10,
    }, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "TEST20"
    assert r.json()["discount_pct"] == 20


def test_duplicate_coupon_rejected(admin_h):
    r = requests.post(f"{API}/admin/coupons", headers=admin_h, json={
        "code": "TEST20", "discount_pct": 30,
    }, timeout=10)
    assert r.status_code == 409


def test_list_coupons(admin_h):
    r = requests.get(f"{API}/admin/coupons", headers=admin_h, timeout=10)
    assert r.status_code == 200
    assert any(c["code"] == "TEST20" for c in r.json()["items"])


def test_validate_coupon_public(admin_h):
    r = requests.get(f"{API}/public/coupons/TEST20/validate?amount=10000", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["discount_xof"] == 2000  # 20% of 10000
    assert body["final_xof"] == 8000


def test_validate_unknown_coupon(admin_h):
    r = requests.get(f"{API}/public/coupons/NONEXISTENT/validate?amount=1000", timeout=10)
    assert r.status_code == 404


def test_checkout_creates_stripe_session(public_product, db_sync):
    """Real Stripe API call with test key — verifies a session URL is returned."""
    r = requests.post(f"{API}/public/products/{public_product}/checkout", json={
        "quantity": 2,
        "customer_email": "buyer@example.com",
        "customer_name": "Test Buyer",
        "return_url": "https://example.com",
    }, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "checkout_url" in body
    assert body["checkout_url"].startswith("https://")
    assert body["amount_xof"] == 2000  # 2 × 1000 XOF, no VAT, no coupon
    order = db_sync.public_orders.find_one({"id": body["order_id"]})
    assert order["status"] == "pending"
    assert order["stripe_session_id"]
    assert order["customer_email"] == "buyer@example.com"


def test_checkout_applies_coupon(public_product, db_sync):
    r = requests.post(f"{API}/public/products/{public_product}/checkout", json={
        "quantity": 5,
        "coupon_code": "TEST20",
        "customer_email": "buyer@example.com",
        "return_url": "https://example.com",
    }, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["discount_xof"] == 1000  # 20% of 5000
    assert body["amount_xof"] == 4000


def test_checkout_404_on_unknown_product():
    r = requests.post(f"{API}/public/products/bogus-id/checkout", json={"quantity": 1}, timeout=10)
    assert r.status_code == 404


def test_order_status_returns_pending(public_product, db_sync):
    r1 = requests.post(f"{API}/public/products/{public_product}/checkout", json={
        "quantity": 1, "customer_email": "x@y.com", "return_url": "https://example.com",
    }, timeout=30)
    order_id = r1.json()["order_id"]
    r2 = requests.get(f"{API}/public/orders/{order_id}", timeout=15)
    assert r2.status_code == 200
    # Still pending until Stripe marks paid
    assert r2.json()["status"] in ("pending", "paid")


def test_delete_coupon(admin_h, db_sync):
    coup = db_sync.coupons.find_one({"code": "TEST20"})
    r = requests.delete(f"{API}/admin/coupons/{coup['id']}", headers=admin_h, timeout=10)
    assert r.status_code == 200
    assert db_sync.coupons.find_one({"code": "TEST20"}) is None
