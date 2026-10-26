"""Lot 289 — écrans TV : appairage par code, flux messagerie + support, masquage des numéros, révocation."""
import asyncio

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.ecran_tv import forme_message, forme_ticket, masquer_numero, nouveau_code, setup_ecran_tv_routes

SECRET = "secret-de-la-tele-0123456789"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_numero_masque_et_nom_prefere():
    assert masquer_numero("22670001122") == "•••• 1122"
    assert masquer_numero("12") == "Contact"
    m = forme_message({"id": "1", "direction": "inbound", "body": "Bonjour", "phone_digits": "22670001122", "created_at": "2026-10-24T10:00:00+00:00"})
    assert m["nom"] == "•••• 1122" and m["sens"] == "entrant" and "70001122" not in str(m)
    assert forme_message({"direction": "outbound", "body": "", "message_type": "image", "contact_name": "Dr Kane"})["texte"] == "📷 Image"
    assert forme_ticket({"id": "t", "number": "TKT-1", "motif": "Imprimante", "status": "open"})["numero"] == "TKT-1"


def test_code_lisible_sans_caracteres_ambigus():
    for _ in range(50):
        c = nouveau_code()
        assert len(c) == 6 and not set(c) & set("ILO01")


def _app():
    base = AsyncMongoMockClient()["test_tv_289"]
    _run(base.users.insert_one({"id": "cli-1", "company": "Clinique A"}))
    _run(base.whatsapp_messages.insert_many([
        {"id": "m1", "client_id": "cli-1", "direction": "inbound", "body": "Bonjour", "phone_digits": "22670001122", "created_at": "2026-10-24T10:00:00+00:00"},
        {"id": "m2", "client_id": "cli-1", "direction": "outbound", "body": "Réponse", "contact_name": "Fatimata", "created_at": "2026-10-24T10:01:00+00:00"},
        {"id": "m3", "client_id": "autre", "direction": "inbound", "body": "Secret d'un autre client", "created_at": "2026-10-24T10:02:00+00:00"},
    ]))
    _run(base.support_tickets.insert_many([
        {"id": "t1", "client_id": "cli-1", "number": "TKT-1", "motif": "Imprimante", "status": "open", "opened_at": "2026-10-24T09:00:00+00:00"},
        {"id": "t2", "client_id": "cli-1", "number": "TKT-2", "motif": "Réglé", "status": "closed", "opened_at": "2026-10-24T08:00:00+00:00"},
    ]))

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"email": "admin@test"}

    api = APIRouter(prefix="/api")
    setup_ecran_tv_routes(db=base, api=api, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), base


def test_appairage_flux_et_revocation():
    c, _ = _app()
    adm = {"x-admin": "1"}
    # La télé demande un code ; avant l'accord elle est « en attente » et le flux lui est refusé
    d = c.post("/api/tv/appairage", json={"secret": SECRET}).json()
    assert c.get(f"/api/tv/appairage/{d['appairage_id']}", headers={"x-tv-secret": SECRET}).json()["etat"] == "attente"
    assert c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).status_code == 401
    # L'administrateur saisit le code (avec un tiret et en minuscules : toléré) ; client inconnu refusé, code inconnu refusé
    assert c.post("/api/admin/tv/appairer", headers=adm, json={"code": d["code"], "nom": "Hall", "client_id": "nope"}).status_code == 404
    assert c.post("/api/admin/tv/appairer", headers=adm, json={"code": "ZZZZZZ", "nom": "Hall", "client_id": "cli-1"}).status_code == 404
    assert c.post("/api/admin/tv/appairer", headers={}, json={"code": d["code"], "nom": "Hall", "client_id": "cli-1"}).status_code == 403
    r = c.post("/api/admin/tv/appairer", headers=adm, json={"code": d["code"].lower(), "nom": "Hall", "client_id": "cli-1"})
    assert r.status_code == 200 and "empreinte" not in r.json()["ecran"]
    ecran_id = r.json()["ecran"]["id"]
    assert c.get(f"/api/tv/appairage/{d['appairage_id']}", headers={"x-tv-secret": SECRET}).json()["etat"] == "ok"
    # Le flux ne contient que les messages et tickets OUVERTS de CE client, sans numéro complet
    f = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert [m["id"] for m in f["messages"]] == ["m1", "m2"]
    assert f["messages"][0]["nom"] == "•••• 1122" and f["messages"][1]["nom"] == "Fatimata"
    assert [t["numero"] for t in f["support"]] == ["TKT-1"]
    assert "70001122" not in str(f) and "autre client" not in str(f)
    # Un secret quelconque est refusé ; décocher « support » le retire du flux
    assert c.get("/api/tv/flux", headers={"x-tv-secret": "autre-secret-0123456789"}).status_code == 401
    assert c.put(f"/api/admin/tv/ecrans/{ecran_id}", headers=adm, json={"modules": {"messagerie": True, "support": False}}).status_code == 200
    f2 = c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).json()
    assert "support" not in f2 and "messages" in f2
    # La liste admin ne révèle jamais l'empreinte ; la révocation refuse aussitôt la télé
    liste = c.get("/api/admin/tv/ecrans", headers=adm).json()["ecrans"]
    assert len(liste) == 1 and "empreinte" not in liste[0] and liste[0]["vu_le"]
    assert c.delete(f"/api/admin/tv/ecrans/{ecran_id}", headers=adm).status_code == 200
    assert c.get("/api/tv/flux", headers={"x-tv-secret": SECRET}).status_code == 401
    assert c.get(f"/api/tv/appairage/{d['appairage_id']}", headers={"x-tv-secret": SECRET}).json()["etat"] == "expire"
