"""Lot 41 — Bulles « nouvelles données » des formulaires (verte) et des sondages (bleue).

MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_nouveautes_formulaires.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.nouveautes_formulaires as nf  # noqa: E402

USERS = {
    "pha": {"id": "pha", "role": "client"},
    "suivi": {"id": "suivi", "role": "pharmacien", "parent_client_id": "pha", "client_id": "pha"},
    "autre": {"id": "autre", "role": "client"},
    "sans": {"id": "sans", "role": "client"},
    "admin": {"id": "admin", "role": "admin"},
}
AVANT = "2020-01-01T00:00:00+00:00"


def maintenant():
    """Date de réception réelle (après le point de départ et avant la consultation suivante)."""
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def env():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_nf"]

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def fonction_active(user, cle):
        assert cle == "forms_surveys"
        return user["id"] != "sans"

    api = APIRouter(prefix="/api")
    nf.attach_nouveautes_formulaires_routes(api=api, db=db, get_current_user=get_user, fonction_active=fonction_active)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    run = client.portal.call
    run(db.forms.insert_many, [{"id": "f1", "client_id": "pha"}, {"id": "f2", "client_id": "pha"},
                               {"id": "fx", "client_id": "autre"}])
    run(db.wa_surveys.insert_many, [{"id": "s1", "client_id": "pha"}, {"id": "sx", "client_id": "autre"}])
    yield client, db, run
    client.__exit__(None, None, None)


def h(uid):
    return {"X-User": uid}


def test_bulles_puces_et_consultation(env):
    client, db, run = env
    # Première lecture : point de départ = maintenant, les données anciennes ne comptent pas
    run(db.form_submissions.insert_one, {"form_id": "f1", "created_at": AVANT})
    assert client.get("/api/me/formulaires-sondages/nouveautes", headers=h("pha")).json()["formulaires"] == 0
    # Nouvelles données (dates futures = reçues après le point de départ)
    run(db.form_submissions.insert_many, [
        {"form_id": "f1", "created_at": maintenant()}, {"form_id": "f1", "created_at": maintenant()},
        {"form_id": "f2", "created_at": AVANT, "updated_at": maintenant()},     # réponse modifiée
        {"form_id": "fx", "created_at": maintenant()}])                           # autre client
    run(db.wa_survey_responses.insert_many, [{"survey_id": "s1", "created_at": maintenant()},
                                             {"survey_id": "sx", "created_at": maintenant()}])
    r = client.get("/api/me/formulaires-sondages/nouveautes", headers=h("pha")).json()
    assert r == {"formulaires": 3, "sondages": 1, "par_formulaire": {"f1": 2, "f2": 1}, "par_sondage": {"s1": 1}}
    # Chacun a son propre point de départ et ses propres consultations
    client.get("/api/me/formulaires-sondages/nouveautes", headers=h("suivi"))
    # Consultation des données de f1 : sa puce disparaît, la bulle diminue
    assert client.post("/api/me/formulaires-sondages/vu", headers=h("pha"),
                       json={"type": "formulaire", "id": "f1"}).status_code == 200
    r = client.get("/api/me/formulaires-sondages/nouveautes", headers=h("pha")).json()
    assert r["par_formulaire"] == {"f2": 1} and r["formulaires"] == 1
    client.post("/api/me/formulaires-sondages/vu", headers=h("pha"), json={"type": "sondage", "id": "s1"})
    assert client.get("/api/me/formulaires-sondages/nouveautes", headers=h("pha")).json()["sondages"] == 0
    # Une donnée arrivée après la consultation rallume la puce
    run(db.form_submissions.insert_one, {"form_id": "f1", "created_at": maintenant()})
    assert client.get("/api/me/formulaires-sondages/nouveautes", headers=h("pha")).json()["par_formulaire"]["f1"] == 1


def test_perimetre_admin_et_fonction_inactive(env):
    client, db, run = env
    client.get("/api/me/formulaires-sondages/nouveautes", headers=h("admin"))
    client.get("/api/me/formulaires-sondages/nouveautes", headers=h("sans"))
    run(db.form_submissions.insert_many, [{"form_id": "f1", "created_at": maintenant()},
                                          {"form_id": "fx", "created_at": maintenant()}])
    assert client.get("/api/me/formulaires-sondages/nouveautes", headers=h("admin")).json()["formulaires"] == 2
    vide = client.get("/api/me/formulaires-sondages/nouveautes", headers=h("sans")).json()
    assert vide == {"formulaires": 0, "sondages": 0, "par_formulaire": {}, "par_sondage": {}}
    assert client.post("/api/me/formulaires-sondages/vu", headers=h("pha"),
                       json={"type": "autre", "id": "f1"}).status_code == 422
