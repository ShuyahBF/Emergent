"""Lot 41 — Calendrier de la discussion WhatsApp : occupations et lien public sans détails.
MongoDB et Google simulés. Lancer : cd backend && python -m pytest tests/test_calendrier_partage.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.calendrier_partage as cp  # noqa: E402

USERS = {"cli": {"id": "cli", "role": "client", "full_name": "Dr Awa"},
         "autre": {"id": "autre", "role": "client"}, "admin": {"id": "admin", "role": "admin"}}
JOUR = "2026-10-05"


@pytest.fixture()
def env():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_cal"]
    appels_google = []

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def google(a, b):
        appels_google.append((a, b))
        return [{"start": f"{JOUR}T15:00:00Z", "end": f"{JOUR}T16:00:00Z"}]

    api = APIRouter(prefix="/api")
    cp.attach_calendrier_partage_routes(api=api, db=db, get_current_user=get_user,
                                        public_base_url=lambda: "https://sawali.bf", google_freebusy=google)
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app).__enter__()
    c.portal.call(db.appointments.insert_many, [
        {"client_id": "cli", "status": "confirmed", "scheduled_at": f"{JOUR}T09:00:00+00:00", "duration_min": 60,
         "subject": "Visite labo"},
        {"client_id": "cli", "status": "cancelled", "scheduled_at": f"{JOUR}T11:00:00+00:00", "duration_min": 60},
        {"client_id": "autre", "status": "confirmed", "scheduled_at": f"{JOUR}T12:00:00+00:00", "duration_min": 60}])
    c.portal.call(db.planning_appointments.insert_one, {
        "tenant_id": "cli", "start_at": f"{JOUR}T09:30:00+00:00", "end_at": f"{JOUR}T10:30:00+00:00",
        "medecin": "Dr Awa", "patient": "OUOBA Jean ; 77000155"})
    yield c, appels_google
    c.__exit__(None, None, None)


def h(u):
    return {"X-User": u}


def test_occupations_creneaux_et_partage(env):
    c, google = env
    r = c.get(f"/api/me/calendrier/occupations?debut={JOUR}&jours=1", headers=h("cli")).json()
    assert [(o["source"], o["debut"][11:16]) for o in r["occupations"]] == [("rdv", "09:00"), ("planning", "09:30")]
    assert r["occupations"][0]["libelle"] == "Visite labo" and google == []   # Google : Admin / Superviseur
    # Créneau bloqué à la main
    b = c.post("/api/me/calendrier/creneaux", headers=h("cli"),
               json={"debut": f"{JOUR}T14:00:00", "fin": f"{JOUR}T15:30:00", "libelle": "Pharmacie de garde"}).json()
    assert c.post("/api/me/calendrier/creneaux", headers=h("cli"),
                  json={"debut": f"{JOUR}T14:00:00", "fin": f"{JOUR}T13:00:00"}).status_code == 400
    r = c.get(f"/api/me/calendrier/occupations?debut={JOUR}&jours=1", headers=h("cli")).json()
    assert ("manuel", "14:00") in [(o["source"], o["debut"][11:16]) for o in r["occupations"]]
    assert c.delete(f"/api/me/calendrier/creneaux/{b['id']}", headers=h("autre")).status_code == 404
    # Lien public : seulement « occupé », blocs réunis, aucun détail
    p = c.post("/api/me/calendrier/partages", headers=h("cli"), json={"debut": JOUR, "jours": 1}).json()
    assert p["url"].startswith("https://sawali.bf/disponibilites/") and p["url"] in p["texte"]
    pub = c.get(f"/api/public/calendrier/{p['url'].rsplit('/', 1)[1]}").json()
    assert pub["titre"] == "Dr Awa"
    assert [(o["debut"][11:16], o["fin"][11:16]) for o in pub["occupations"]] == [("09:00", "10:30"), ("14:00", "15:30")]
    assert "Visite labo" not in str(pub) and "OUOBA" not in str(pub)
    assert c.get("/api/public/calendrier/inconnu").status_code == 404
    # Admin : Google Calendar de la plateforme inclus
    r = c.get(f"/api/me/calendrier/occupations?debut={JOUR}&jours=1", headers=h("admin")).json()
    assert r["google"] is True and any(o["source"] == "google" for o in r["occupations"])


def test_fusionner():
    assert cp.fusionner([{"debut": "a1", "fin": "a3"}, {"debut": "a2", "fin": "a4"}, {"debut": "a5", "fin": "a6"}]) == \
        [{"debut": "a1", "fin": "a4"}, {"debut": "a5", "fin": "a6"}]
