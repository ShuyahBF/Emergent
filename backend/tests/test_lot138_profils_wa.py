"""Lot 138 — nom de profil WhatsApp transmis (signé) à une plateforme. Lancer : cd backend && python -m pytest tests/test_lot138_profils_wa.py -q"""
import asyncio
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.profils_wa as pw  # noqa: E402


def _entetes(cle, corps: bytes, code="zandgo"):
    ts = str(int(time.time()))
    sig = hmac.new(cle.encode(), f"{ts}.{corps.decode()}".encode(), hashlib.sha256).hexdigest()
    return {"X-Emetteur": code, "X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}


def test_profils_signes():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot138"]
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.liluvine_emetteurs.insert_one({"code": "zandgo", "secret": "cle-zg", "actif": True}))
    boucle.run_until_complete(db.whatsapp_messages.insert_many([
        {"direction": "inbound", "phone_digits": "22670000001", "from_profile_name": "Ancien", "created_at": "2026-10-01T10:00:00"},
        {"direction": "inbound", "phone_digits": "22670000001", "from_profile_name": "Awa 🌸", "created_at": "2026-10-12T10:00:00"},
        {"direction": "inbound", "phone_digits": "22670000003", "from_profile_name": "", "created_at": "2026-10-12T10:00:00"},
        {"direction": "outbound", "phone_digits": "22670000004", "from_profile_name": "Nous", "created_at": "2026-10-12T10:00:00"}]))
    app, api = FastAPI(), APIRouter(prefix="/api")
    pw.setup_profils_wa_routes(db=db, api=api)
    app.include_router(api)
    c = TestClient(app)
    corps = json.dumps({"telephones": ["+226 70 00 00 01", "+22670000002", "22670000003", "22670000004"]}).encode()
    # Mauvaise clé et émetteur inconnu refusés
    assert c.post("/api/webhook/plateforme-profils-wa", content=corps, headers=_entetes("mauvaise", corps)).status_code == 401
    assert c.post("/api/webhook/plateforme-profils-wa", content=corps, headers=_entetes("cle-zg", corps, "inconnu")).status_code == 401
    r = c.post("/api/webhook/plateforme-profils-wa", content=corps, headers=_entetes("cle-zg", corps))
    assert r.status_code == 200
    # Seul le dernier nom connu du numéro 1 ; ni nom vide, ni message sortant, ni numéro inconnu
    assert r.json()["profils"] == {"22670000001": {"nom": "Awa 🌸", "vu_le": "2026-10-12T10:00:00"}}
    mauvais = b'{"telephones": "x"}'
    assert c.post("/api/webhook/plateforme-profils-wa", content=mauvais, headers=_entetes("cle-zg", mauvais)).status_code == 422
