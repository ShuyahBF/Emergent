"""Iter37b — CHUNK 2: CSV import + tenant_snapshot on receipts/invoices."""
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

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sawali-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    d = r.json()
    if not d.get("needs_otp"):
        return d["access_token"]
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": d["session_token"], "code": d["dev_otp"]}, timeout=30)
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


class TestCsvFieldsEndpoints:
    def test_business_fields(self, admin_h):
        r = requests.get(f"{API}/cashier/import/business-clients/fields", headers=admin_h, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["order"][0] == "name"
        assert "whatsapp" in body["order"]
        assert body["delimiter"] == ";"
        assert "sample" in body

    def test_products_fields(self, admin_h):
        r = requests.get(f"{API}/cashier/import/products/fields", headers=admin_h, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["order"][0] == "name"
        assert "unit_price_ht" in body["order"]
        # SKU is NOT in the order list (auto-generated)
        assert "sku" not in body["order"]


class TestBusinessClientsImport:
    def test_simple_import_with_bom_header(self, admin_h, db):
        prefix = f"IMP{uuid.uuid4().hex[:5]}"
        csv = (
            "\ufeffname;legal_form;nif;ifu;rccm;phone;whatsapp;email;billing_address;shipping_address;notes\n"
            f"{prefix}-ACME;SARL;NIF123;IFU456;RC789;+242066111;+242077222;acme@test.local;BZV;BZV livraison;Test import\n"
            f"{prefix}-BETA;;;;;;+242077333;;Brazzaville;;\n"
        )
        r = requests.post(f"{API}/cashier/import/business-clients", headers=admin_h, json={"csv": csv}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 2
        assert body["skipped_duplicates"] == 0
        assert body["errors"] == []
        # Verify content
        bc = db.business_clients.find_one({"name": f"{prefix}-ACME"}, {"_id": 0})
        assert bc["legal_form"] == "SARL"
        assert bc["whatsapp"] == "+242077222"
        assert bc["auto_relance_enabled"] is False
        # Cleanup
        db.business_clients.delete_many({"name": {"$regex": f"^{prefix}-"}})

    def test_duplicate_name_skipped(self, admin_h, db):
        name = f"DUP-{uuid.uuid4().hex[:6]}"
        # Pre-create one
        r0 = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={"name": name}, timeout=15)
        assert r0.status_code == 200
        csv = f"name;legal_form;nif;ifu;rccm;phone;whatsapp;email;billing_address;shipping_address;notes\n{name};SARL;;;;;;;;;\n"
        r = requests.post(f"{API}/cashier/import/business-clients", headers=admin_h, json={"csv": csv}, timeout=15)
        body = r.json()
        assert body["created"] == 0
        assert body["skipped_duplicates"] == 1
        requests.delete(f"{API}/admin/business-clients/{r0.json()['id']}", headers=admin_h, timeout=10)

    def test_missing_name_returns_error(self, admin_h):
        csv = "name;legal_form\n;SARL\n"
        r = requests.post(f"{API}/cashier/import/business-clients", headers=admin_h, json={"csv": csv}, timeout=15)
        body = r.json()
        assert body["created"] == 0
        assert len(body["errors"]) == 1
        assert "Nom" in body["errors"][0]["error"]

    def test_empty_csv_rejected(self, admin_h):
        r = requests.post(f"{API}/cashier/import/business-clients", headers=admin_h, json={"csv": ""}, timeout=15)
        assert r.status_code == 400


class TestProductsImport:
    def test_products_imported_with_auto_sku_and_upper(self, admin_h, db):
        prefix = f"PIMP{uuid.uuid4().hex[:5]}"
        csv = (
            "name;category;unit;unit_price_ht;tva_pct;stock;description;active\n"
            f"{prefix} produit 1;Logiciel;forfait;50000;18;;Test description;true\n"
            f"{prefix} produit 2;Service;heure;10000;18;5;;false\n"
        )
        r = requests.post(f"{API}/cashier/import/products", headers=admin_h, json={"csv": csv}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 2
        # Verify name was uppercased + SKU auto
        p1 = db.products.find_one({"name": f"{prefix} PRODUIT 1".upper()}, {"_id": 0})
        assert p1 is not None
        assert p1["sku"]
        import re as _re
        assert _re.match(r"^[A-Z0-9 ]+-\d{8}$", p1["sku"])
        assert p1["category"] == "Logiciel"
        assert p1["unit_price_ht"] == 50000
        assert p1["active"] is True
        # Second product
        p2 = db.products.find_one({"name": f"{prefix} PRODUIT 2".upper()}, {"_id": 0})
        assert p2["active"] is False
        assert p2["stock"] == 5
        # Cleanup
        db.products.delete_many({"name": {"$regex": f"^{prefix} "}})


class TestTenantSnapshot:
    def test_receipt_has_tenant_snapshot(self, admin_h, db):
        bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
            "name": f"TS-{uuid.uuid4().hex[:6]}", "phone": "+242066444444",
        }, timeout=15).json()
        pm = requests.post(f"{API}/admin/payment-methods", headers=admin_h, json={
            "label": "Cash TS", "kind": "cash", "active": True, "sort_order": 1,
        }, timeout=15).json()
        rec = requests.post(f"{API}/cashier/receipts", headers=admin_h, json={
            "business_client_id": bc["id"], "amount": 1500, "motif": "TS test", "payment_method_id": pm["id"],
        }, timeout=15).json()
        # tenant_snapshot must be present
        full = requests.get(f"{API}/cashier/receipts/{rec['id']}", headers=admin_h, timeout=15).json()
        assert "tenant_snapshot" in full
        assert full["tenant_snapshot"]["name"]
        # Cleanup
        db.receipts.delete_one({"id": rec["id"]})
        requests.delete(f"{API}/admin/business-clients/{bc['id']}", headers=admin_h, timeout=10)
        requests.delete(f"{API}/admin/payment-methods/{pm['id']}", headers=admin_h, timeout=10)

    def test_invoice_has_tenant_snapshot(self, admin_h, db):
        bc = requests.post(f"{API}/admin/business-clients", headers=admin_h, json={
            "name": f"TSI-{uuid.uuid4().hex[:6]}",
        }, timeout=15).json()
        inv = requests.post(f"{API}/cashier/invoices", headers=admin_h, json={
            "kind": "invoice", "business_client_id": bc["id"],
            "items": [{"label": "Test", "quantity": 1, "unit_price_ht": 10000, "tva_pct": 18}],
        }, timeout=15).json()
        full = requests.get(f"{API}/cashier/invoices/{inv['id']}", headers=admin_h, timeout=15).json()
        assert "tenant_snapshot" in full
        assert full["tenant_snapshot"]["name"]
        db.invoices.delete_one({"id": inv["id"]})
        requests.delete(f"{API}/admin/business-clients/{bc['id']}", headers=admin_h, timeout=10)
