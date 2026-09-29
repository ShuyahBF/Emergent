"""Lot 41 — Inbox unifiée : un long fil affiche ses DERNIERS messages (avant : les 50 plus
anciens), dans l'ordre chronologique ; l'annuaire n'est plus relu à chaque rafraîchissement.

MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_inbox_lot41.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.unified_inbox as ui  # noqa: E402


def test_long_fil_derniers_messages_et_cache_annuaire():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_inbox"]
    user = {"id": "cli", "role": "client"}

    async def get_user():
        return user

    api = APIRouter(prefix="/api")
    ui.setup_unified_inbox_routes(db=db, api=api, get_current_user=get_user, _normalize_features=lambda f: f or {})
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app).__enter__()
    c.portal.call(db.whatsapp_messages.insert_many, [
        {"id": f"m{i:03d}", "client_id": "cli", "direction": "inbound", "from": "22670000001",
         "text": f"message {i}", "created_at": f"2026-09-29T10:{i // 60:02d}:{i % 60:02d}+00:00"} for i in range(120)])
    c.portal.call(db.directory_contacts.insert_one, {"id": "k1", "owner_id": "cli", "name": "Awa", "phone": "+226 70 00 00 01"})
    msgs = c.get("/api/me/inbox/unified/whatsapp/22670000001?limit=50").json()["messages"]
    assert len(msgs) == 50 and msgs[-1]["text"] == "message 119" and msgs[0]["text"] == "message 70"
    fils = c.get("/api/me/inbox/unified").json()["items"]
    assert fils[0]["peer_name"] == "Awa"
    # Annuaire gardé 60 s : un renommage n'apparaît qu'au prochain rechargement de l'index
    c.portal.call(db.directory_contacts.update_one, {"id": "k1"}, {"$set": {"name": "Awa K."}})
    assert c.get("/api/me/inbox/unified").json()["items"][0]["peer_name"] == "Awa"
    ui._CACHE_ANNUAIRE.clear()
    assert c.get("/api/me/inbox/unified").json()["items"][0]["peer_name"] == "Awa K."
    c.__exit__(None, None, None)
