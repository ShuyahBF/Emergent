"""Lot 328 — page /suivi-rdv en mode administrateur : MÊME flux que la télé (médecins, photos, Suivi Support) mais noms et téléphones en clair."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.ecran_tv import forme_hall, setup_ecran_tv_routes


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


def _app():
    db = AsyncMongoMockClient()["test_suivi_admin_328"]

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"id": "adm-1", "email": "a@test"}
    api = APIRouter(prefix="/api")
    setup_ecran_tv_routes(db=db, api=api, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db


def test_forme_hall_clair_ou_anonymise():
    maintenant = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
    docs = [{"medecin": "DR X", "patient": "KANE Fatimata : 70001122 : R-1", "patient_phone": "70001122", "is_rdv": 1, "start_at": "2026-10-27T10:20:00+00:00"}]
    clair = forme_hall(docs, {}, maintenant, clair=True)["medecins"][0]["rdv"][0]
    anonyme = forme_hall(docs, {}, maintenant)["medecins"][0]["rdv"][0]
    assert (clair["qui"], clair["tel"]) == ("KANE Fatimata", "70001122")
    assert "KANE" not in str(anonyme) and "70001122" not in str(anonyme)             # la télé du hall reste masquée


def test_flux_admin_reserve_aux_admins_et_en_clair():
    c, db = _app()
    assert c.get("/api/admin/suivi-rdv/flux").status_code == 403
    maintenant = datetime.now(timezone.utc)
    _run(db.settings.update_one({"_id": "global"}, {"$set": {"tv_portes": [{"medecin": "DR X", "porte": "Salle 2", "profession": "Dentiste"}]}}, upsert=True))
    _run(db.planning_appointments.insert_one({"id": "p1", "medecin": "DR X", "patient": "OUEDRAOGO Alphonse : 70001122", "patient_phone": "70001122",
                                             "is_rdv": 1, "start_at": (maintenant + timedelta(minutes=30)).isoformat()}))
    _run(db.support_tickets.insert_one({"id": "t1", "client_id": "adm-1", "number": "T-1", "motif": "Imprimante", "status": "open", "opened_at": maintenant.isoformat()}))
    d = c.get("/api/admin/suivi-rdv/flux?photos=1&jours=3", headers={"x-admin": "1"}).json()
    assert d["ecran"]["admin"] and d["ecran"]["suivi_ouvert"] and all(d["ecran"]["modules"].values())     # rien n'est verrouillé : pas de PIN
    assert d["hall"]["horizon"] == 3
    m = d["hall"]["medecins"][0]
    assert (m["medecin"], m["porte"], m["profession"]) == ("DR X", "Salle 2", "Dentiste")
    assert (m["rdv"][0]["qui"], m["rdv"][0]["tel"]) == ("OUEDRAOGO Alphonse", "70001122")                # en clair
    assert "messages" in d and "fils" in d and "support" in d                                            # Suivi Support
