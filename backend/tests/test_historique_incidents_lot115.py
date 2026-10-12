"""Lot 115 — historique des incidents de /uptime : résoudre, supprimer, réinitialiser (confirmation exigée)."""
import asyncio

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.admin_settings import attach_admin_settings_routes


def _app():
    """Application minimale : routes d'administration des paramètres sur une base simulée, admin toujours connecté."""
    db = AsyncMongoMockClient()["test_incidents_lot115"]
    api = APIRouter(prefix="/api")

    async def admin():
        return {"id": "a1", "email": "admin@sawali.test", "role": "admin"}

    async def reglages():
        return {}
    attach_admin_settings_routes(api=api, db=db, get_current_admin=admin, get_settings_doc=reglages)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _incident(db, iid, statut="ongoing"):
    _run(db.incidents.insert_one({"id": iid, "severity": "warning", "message": "Panne", "status": statut,
                                  "started_at": "2026-10-12T00:00:00+00:00", "updates": []}))


def test_resoudre_un_incident():
    client, db = _app()
    _incident(db, "i1")
    r = client.post("/api/admin/incidents/i1/resoudre")
    assert r.status_code == 200, r.text
    doc = _run(db.incidents.find_one({"id": "i1"}))
    assert doc["status"] == "resolved" and doc["resolved_at"] and doc["resolved_by"] == "admin@sawali.test"
    # Déjà résolu → 409 ; inconnu → 404
    assert client.post("/api/admin/incidents/i1/resoudre").status_code == 409
    assert client.post("/api/admin/incidents/zz/resoudre").status_code == 404


def test_reinitialiser_exige_la_confirmation():
    client, db = _app()
    _incident(db, "a"), _incident(db, "b", "resolved")
    assert client.post("/api/admin/incidents/reinitialiser", json={"confirmation": "oui"}).status_code == 400
    assert _run(db.incidents.count_documents({})) == 2
    r = client.post("/api/admin/incidents/reinitialiser", json={"confirmation": "réinitialiser"})
    assert r.status_code == 200 and r.json()["supprimes"] == 2
    assert _run(db.incidents.count_documents({})) == 0
