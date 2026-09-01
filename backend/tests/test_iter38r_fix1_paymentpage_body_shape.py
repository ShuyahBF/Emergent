"""Iter38r-fix1 — Validate the exact JSON body sent to PawaPay /v2/paymentpage.

After the user reported "Paramètre non supporté — please remove unsupported
parameter from request body", we audit the body shape against PawaPay's v2
schema:
    - depositId (UUIDv4)
    - returnUrl
    - amountDetails: { amount: str, currency: ISO-4217 }     ⚠️ not flat `amount`
    - phoneNumber (digits only, no '+')                       ⚠️ not `msisdn`
    - country (ISO-3, optional)
    - reason (1..50 chars, optional)

We use httpx mocking via respx to intercept the call and verify the shape.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def env(db):
    admin_id = f"fix1_adm_{uuid.uuid4().hex[:6]}"
    company = f"FX-{uuid.uuid4().hex[:4]}"
    now = datetime.now(timezone.utc).isoformat()
    db.users.insert_one({
        "id": admin_id, "email": f"{admin_id}@t.l", "password_hash": "x",
        "full_name": "Admin FX", "company": company, "role": "admin",
        "account_status": "active", "created_at": now,
        "features": {"payments": True}, "whatsapp": "+22675009988",
        "pawapay_fix_msisdn": True,
    })
    original = db.settings.find_one({"_id": "global"}) or {}
    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "pawapay_enabled": True,
            "pawapay_environment": "sandbox",
            "pawapay_api_token_sandbox": "fake-token-fix1",
            "pawapay_country": "BFA",
        }},
        upsert=True,
    )
    yield {"admin_id": admin_id}
    db.users.delete_many({"id": admin_id})
    db.payments.delete_many({"user_id": admin_id})
    if original:
        db.settings.replace_one({"_id": "global"}, original, upsert=True)
    else:
        db.settings.delete_one({"_id": "global"})


@pytest.mark.asyncio
async def test_body_shape_matches_pawapay_v2(env, monkeypatch):
    """Validates the exact JSON body sent to PawaPay /v2/paymentpage:
    - `amountDetails: {amount, currency}` (not flat `amount`)
    - `phoneNumber` (not `msisdn`)
    - `country`, `reason`, `depositId`, `returnUrl`
    - No legacy v1 fields like `correspondent`, `statementDescription`, `payer`
    Also checks that omitting amount drops `amountDetails` entirely.
    """
    captured = []

    class _FakeResponse:
        def __init__(self): self.status_code = 200
        def json(self): return {"redirectUrl": "https://pay.pawapay/test"}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def post(self, url, headers=None, json=None):  # noqa: F811 - `json` is a kwarg name required by aiohttp signature
            captured.append({"url": url, "json": json})
            return _FakeResponse()

    import sys, importlib
    sys.path.insert(0, "/app/backend")
    server = importlib.import_module("server")
    monkeypatch.setattr(server.httpx, "AsyncClient", _FakeAsyncClient)

    class _FakeReq:
        headers = {"origin": "https://test.example.com"}
        client = type("c", (), {"host": "127.0.0.1"})()
    user = await server.db.users.find_one({"id": env["admin_id"]}, {"_id": 0})

    # Case 1 — with amount
    res = await server.me_pawapay_payment_page(
        server.PawaPayPaymentPageCreate(amount=1500, country="BFA", reason="Test"),
        _FakeReq(), user,
    )
    assert res["ok"] is True
    body = captured[-1]["json"]
    assert captured[-1]["url"].endswith("/v2/paymentpage")
    assert "amount" not in body, f"flat amount forbidden by v2; got {body}"
    assert "msisdn" not in body, f"msisdn renamed to phoneNumber in v2; got {body}"
    assert body["amountDetails"] == {"amount": "1500", "currency": "XOF"}
    assert body["phoneNumber"] == "22675009988"
    assert body["country"] == "BFA"
    assert body["depositId"]
    assert body["returnUrl"].endswith(f"depositId={body['depositId']}")
    assert body["reason"] == "Test"
    for forbidden in ("statementDescription", "correspondent", "payer"):
        assert forbidden not in body

    # Case 2 — no amount → amountDetails must be absent
    await server.me_pawapay_payment_page(
        server.PawaPayPaymentPageCreate(amount=None),
        _FakeReq(), user,
    )
    body2 = captured[-1]["json"]
    assert "amountDetails" not in body2
    assert "amount" not in body2

    # Case 3 — decimal amount preserves 2 decimals
    await server.me_pawapay_payment_page(
        server.PawaPayPaymentPageCreate(amount=12.5, country="CIV"),
        _FakeReq(), user,
    )
    body3 = captured[-1]["json"]
    assert body3["amountDetails"] == {"amount": "12.50", "currency": "XOF"}
    assert body3["country"] == "CIV"
