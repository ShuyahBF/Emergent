"""Lot 171 — pause temporaire du webhook « Incidents serveur » (mot de passe conservé). Base MongoDB simulée.
Lancer : cd backend && python -m pytest tests/test_lot171_pause_webhook_incidents.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes.iter42d_incidents_and_lookup import attach_iter42d_routes  # noqa: E402


def construire():
    """Mini-application : l'admin est simulé, la base est en mémoire."""
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    api = APIRouter(prefix="/api")

    async def admin():
        return {"email": "admin@test"}

    async def officine():
        return {}

    attach_iter42d_routes(api, db=db, get_current_admin=admin, get_current_officine=officine)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db


def test_pause_refuse_puis_retablit():
    c, _ = construire()
    mdp = c.post("/api/admin/incidents-webhook/regenerate-password").json()["password"]
    corps = {"title": "Disque plein"}
    ent = {"X-Webhook-Password": mdp}
    assert c.post("/api/public/incidents", json=corps, headers=ent).status_code == 200
    # pause : refus 503 avec Retry-After, même avec le bon mot de passe
    assert c.put("/api/admin/incidents-webhook/pause", json={"pause": True}).json()["pause"] is True
    r = c.post("/api/public/incidents", json=corps, headers=ent)
    assert r.status_code == 503 and "temporairement" in r.json()["detail"] and r.headers["retry-after"]
    etat = c.get("/api/admin/incidents-webhook").json()
    assert etat["pause"] is True and etat["configured"] is True                # le mot de passe est conservé
    # rétablissement : le même mot de passe refonctionne
    c.put("/api/admin/incidents-webhook/pause", json={"pause": False})
    assert c.post("/api/public/incidents", json=corps, headers=ent).status_code == 200
