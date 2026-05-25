"""Iter37h — DELETE receipt/invoice (admin/sup only) + Duplicate invoice."""
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
def tenant_with_docs(db):
    """Tenant + 2 cashier users (sup + plain client+can_cash) + a receipt + an invoice."""
    sup_id = f"sup_{uuid.uuid4().hex[:6]}"
    ca_id = f"ca_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_many([
        {"id": sup_id, "email": f"{sup_id}@test.local", "password_hash": "x",
         "full_name": "Boss", "company": f"CO-{uuid.uuid4().hex[:4]}",
         "role": "superviseur", "account_status": "active", "can_cash": True,
         "created_at": now},
        {"id": ca_id, "email": f"{ca_id}@test.local", "password_hash": "x",
         "full_name": "Plain Cashier", "parent_client_id": sup_id,
         "role": "client", "account_status": "active", "can_cash": True,
         "created_at": now},
    ])
    sh = {"Authorization": f"Bearer {_forge(sup_id)}"}
    bc = requests.post(f"{API}/admin/business-clients", headers=sh, json={
        "name": f"BC-{uuid.uuid4().hex[:6]}", "phone": "+22600000001",
    }, timeout=15).json()
    pm = requests.post(f"{API}/admin/payment-methods", headers=sh, json={
        "label": "Cash", "kind": "cash", "active": True, "sort_order": 1,
    }, timeout=15).json()
    rr = requests.post(f"{API}/cashier/receipts", headers=sh, json={
        "business_client_id": bc["id"], "amount": 5000, "motif": "Test",
        "payment_method_id": pm["id"],
    }, timeout=15).json()
    inv = requests.post(f"{API}/cashier/invoices", headers=sh, json={
        "business_client_id": bc["id"], "kind": "invoice",
        "items": [
            {"label": "Service A", "quantity": 2, "unit_price_ht": 1000, "tva_pct": 0},
            {"label": "Service B", "quantity": 1, "unit_price_ht": 3000, "tva_pct": 0},
        ],
        "discount_kind": "value", "discount_value": 500, "notes": "Notes test",
    }, timeout=15).json()
    proforma = requests.post(f"{API}/cashier/invoices", headers=sh, json={
        "business_client_id": bc["id"], "kind": "proforma",
        "items": [{"label": "Devis", "quantity": 1, "unit_price_ht": 10000, "tva_pct": 0}],
        "discount_kind": "none", "discount_value": 0,
    }, timeout=15).json()
    yield {
        "sup_id": sup_id, "ca_id": ca_id, "sh": sh,
        "ca_h": {"Authorization": f"Bearer {_forge(ca_id, role='client')}"},
        "bc": bc, "pm": pm, "receipt": rr, "invoice": inv, "proforma": proforma,
    }
    db.users.delete_many({"id": {"$in": [sup_id, ca_id]}})
    db.business_clients.delete_many({"tenant_id": sup_id})
    db.payment_methods.delete_many({"tenant_id": sup_id})
    db.receipts.delete_many({"tenant_id": sup_id})
    db.invoices.delete_many({"tenant_id": sup_id})


class TestDeleteReceipt:
    def test_superviseur_can_delete_receipt(self, tenant_with_docs):
        ctx = tenant_with_docs
        rid = ctx["receipt"]["id"]
        r = requests.delete(f"{API}/cashier/receipts/{rid}", headers=ctx["sh"], timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        # The receipt is no longer in the listing
        lr = requests.get(f"{API}/cashier/receipts", headers=ctx["sh"], timeout=15)
        ids = {x["id"] for x in lr.json()}
        assert rid not in ids

    def test_plain_cashier_cannot_delete_receipt(self, tenant_with_docs):
        ctx = tenant_with_docs
        rid = ctx["receipt"]["id"]
        r = requests.delete(f"{API}/cashier/receipts/{rid}", headers=ctx["ca_h"], timeout=15)
        assert r.status_code in (401, 403), f"Plain cashier should NOT delete, got {r.status_code}"


class TestDeleteInvoice:
    def test_superviseur_can_delete_invoice(self, tenant_with_docs):
        ctx = tenant_with_docs
        iid = ctx["invoice"]["id"]
        r = requests.delete(f"{API}/cashier/invoices/{iid}", headers=ctx["sh"], timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert r.json()["kind"] == "invoice"
        # Hidden from listings
        lr = requests.get(f"{API}/cashier/invoices", headers=ctx["sh"], timeout=15)
        ids = {x["id"] for x in lr.json()}
        assert iid not in ids
        # Public PDF now returns 404
        token = ctx["invoice"]["qr_token"]
        pr = requests.get(f"{API}/public/invoice-pdf/{token}", timeout=15)
        assert pr.status_code == 404

    def test_superviseur_can_delete_proforma(self, tenant_with_docs):
        ctx = tenant_with_docs
        pid = ctx["proforma"]["id"]
        r = requests.delete(f"{API}/cashier/invoices/{pid}", headers=ctx["sh"], timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "proforma"

    def test_plain_cashier_cannot_delete_invoice(self, tenant_with_docs):
        ctx = tenant_with_docs
        iid = ctx["invoice"]["id"]
        r = requests.delete(f"{API}/cashier/invoices/{iid}", headers=ctx["ca_h"], timeout=15)
        assert r.status_code in (401, 403)


class TestDuplicateInvoice:
    def test_duplicate_returns_draft_without_client(self, tenant_with_docs):
        ctx = tenant_with_docs
        iid = ctx["invoice"]["id"]
        r = requests.post(f"{API}/cashier/invoices/{iid}/duplicate",
                          headers=ctx["sh"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        draft = body["draft"]
        assert draft["business_client_id"] is None, "Client must be reset"
        assert draft["kind"] == "invoice"
        assert len(draft["items"]) == 2
        # Items keep label/qty/price/tva, not line totals
        assert draft["items"][0]["label"] == "Service A"
        assert "line_total_ttc" not in draft["items"][0]
        assert draft["discount_kind"] == "value"
        assert float(draft["discount_value"]) == 500
        assert draft["notes"] == "Notes test"
        assert draft["due_date"] is None
        assert body["source_id"] == iid
        assert body["source_number"] == ctx["invoice"]["number"]

    def test_duplicate_proforma(self, tenant_with_docs):
        ctx = tenant_with_docs
        pid = ctx["proforma"]["id"]
        r = requests.post(f"{API}/cashier/invoices/{pid}/duplicate",
                          headers=ctx["sh"], timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["draft"]["kind"] == "proforma"

    def test_duplicate_works_for_plain_cashier(self, tenant_with_docs):
        """can_cash=true users CAN duplicate (it's not a destructive op)."""
        ctx = tenant_with_docs
        iid = ctx["invoice"]["id"]
        r = requests.post(f"{API}/cashier/invoices/{iid}/duplicate",
                          headers=ctx["ca_h"], timeout=15)
        assert r.status_code == 200, r.text
