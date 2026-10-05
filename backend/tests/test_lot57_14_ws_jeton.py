"""Lot 57.14 — jeton des WebSockets hors de l'adresse (premier message {"type":"auth","token":…}).
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot57_14_ws_jeton.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.internal_chat as ic  # noqa: E402
import ws_auth  # noqa: E402

ADMIN = {"id": "adm1", "role": "admin", "full_name": "Admin", "account_status": "active"}


def _decode(jeton):
    """Jeton de test : « bon » = l'administrateur, tout le reste est refusé."""
    if jeton != "bon":
        raise ValueError("jeton invalide")
    return {"sub": "adm1", "role": "admin"}


@pytest.fixture()
def client(monkeypatch):
    # maintenance_plateforme a besoin de la vraie base : remplacé par une version « jamais en maintenance »
    import types
    faux = types.ModuleType("maintenance_plateforme")
    faux.jamais_bloque = lambda user, jeton: True

    async def en_maintenance():
        return False

    faux.en_maintenance = en_maintenance
    monkeypatch.setitem(sys.modules, "maintenance_plateforme", faux)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_ws"]

    async def get_user(request: Request):
        raise HTTPException(status_code=401)

    api = APIRouter(prefix="/api")
    api.include_router(ic.make_router(db=db, get_current_user=get_user, decode_token=_decode))
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as c:
        c.portal.call(db.users.insert_one, dict(ADMIN))
        yield c


def test_jeton_dans_le_premier_message(client):
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"type": "auth", "token": "bon"})
        bonjour = ws.receive_json()
        assert bonjour["type"] == "hello" and bonjour["user_id"] == "adm1"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_ancienne_adresse_encore_acceptee(client):
    with client.websocket_connect("/api/ws/chat?token=bon") as ws:
        assert ws.receive_json()["type"] == "hello"


def test_jeton_faux_ou_absent_refuse(client, monkeypatch):
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"type": "auth", "token": "faux"})
        assert ws.receive_json()["type"] == "error"
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"type": "ping"})                 # premier message qui n'est pas « auth »
        assert ws.receive_json()["detail"] == "token manquant"
    monkeypatch.setattr(ws_auth, "DELAI_AUTH_SECONDES", 0.2)
    with client.websocket_connect("/api/ws/chat") as ws:   # rien envoyé : délai dépassé
        assert ws.receive_json()["detail"] == "token manquant"
