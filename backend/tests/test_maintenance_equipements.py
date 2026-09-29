"""Lot 41 — Maintenance des équipements confiés.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_maintenance_equipements.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.maintenance_equipements as me  # noqa: E402

USERS = {"sav": {"id": "sav", "role": "client", "client_code": "SAV"},
         "tech": {"id": "tech", "role": "client", "parent_client_id": "sav", "client_id": "sav", "full_name": "Tech"},
         "autre": {"id": "autre", "role": "client", "client_code": "AUT"},
         "sans": {"id": "sans", "role": "client"}, "admin": {"id": "admin", "role": "admin"}}


@pytest.fixture()
def c():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_mnt"]

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def fonction_active(user, cle):
        assert cle == "maintenance_equipements"
        return user["id"] != "sans"

    api = APIRouter(prefix="/api")
    me.attach_maintenance_routes(api=api, db=db, get_current_user=get_user, fonction_active=fonction_active)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
    client.portal.call(db.directory_contacts.insert_one, {"id": "k1", "client_id": "sav", "name": "Pharmacie A",
                                                          "whatsapp": "+226 70 00 00 01"})
    yield client
    client.__exit__(None, None, None)


def h(u):
    return {"X-User": u}


FICHE = {"contact_id": "k1", "type_materiel": "Imprimante", "marque_modele": "HP LaserJet 1020",
         "etat_materiel": "mauvais", "motif": "Bourrage papier permanent", "date_reception": "2026-09-29",
         "date_entree": "2026-09-29"}


def test_fiche_complete(c):
    assert c.get("/api/me/maintenance", headers=h("sans")).status_code == 403
    f = c.post("/api/me/maintenance", headers=h("tech"), json=FICHE).json()
    assert f["numero"].startswith("MNT-SAV-") and f["numero"].endswith("-0001") and f["statut"] == "recu"
    assert f["client_nom"] == "Pharmacie A" and f["client_telephone"] == "+226 70 00 00 01" and f["tenant_id"] == "sav"
    f2 = c.post("/api/me/maintenance", headers=h("sav"),
                json={**FICHE, "contact_id": None, "client_nom": "M. OUEDRAOGO", "client_telephone": "76000000",
                      "type_materiel": "Onduleur", "etat_materiel": "bon"}).json()
    assert f2["numero"].endswith("-0002")
    # Contact d'un autre client refusé ; client obligatoire
    assert c.post("/api/me/maintenance", headers=h("autre"), json=FICHE).status_code == 400
    assert c.post("/api/me/maintenance", headers=h("sav"), json={**FICHE, "contact_id": None}).status_code == 400
    assert c.post("/api/me/maintenance", headers=h("sav"), json={**FICHE, "etat_materiel": "neuf"}).status_code == 422
    # Diagnostic, pièces à remplacer, en réparation puis restitution
    maj = c.put(f"/api/me/maintenance/{f['id']}", headers=h("tech"), json={
        **FICHE, "diagnostic": "Rouleau d'entraînement usé", "remplacement_pieces": True,
        "pieces": "Rouleau d'entraînement", "statut": "reparation"}).json()
    assert maj["statut"] == "reparation" and maj["remplacement_pieces"] is True and maj["numero"] == f["numero"]
    assert c.put(f"/api/me/maintenance/{f['id']}", headers=h("tech"),
                 json={**FICHE, "date_sortie": "2026-09-01"}).status_code == 400
    rendu = c.put(f"/api/me/maintenance/{f['id']}", headers=h("tech"), json={**FICHE, "date_sortie": "2026-10-02"}).json()
    assert rendu["statut"] == "rendu"
    # Liste, recherche, filtre, cloisonnement
    lst = c.get("/api/me/maintenance?q=pharmacie", headers=h("sav")).json()
    assert [x["numero"] for x in lst["fiches"]] == [f["numero"]] and lst["compte"]["rendu"] == 1
    assert c.get("/api/me/maintenance?statut=recu", headers=h("sav")).json()["fiches"][0]["type_materiel"] == "Onduleur"
    assert c.get("/api/me/maintenance", headers=h("autre")).json()["fiches"] == []
    assert c.get(f"/api/me/maintenance/{f['id']}", headers=h("autre")).status_code == 404
    assert len(c.get("/api/me/maintenance", headers=h("admin")).json()["fiches"]) == 2
    # Suppression : compte client ou Admin, pas l'utilisateur suivi
    assert c.delete(f"/api/me/maintenance/{f2['id']}", headers=h("tech")).status_code == 403
    assert c.delete(f"/api/me/maintenance/{f2['id']}", headers=h("sav")).status_code == 200


def test_types_extensibles(c):
    t = c.get("/api/me/maintenance-types", headers=h("sav")).json()
    assert "Imprimante" in t["tous"] and t["tous"][-1] == "Autre"
    n = c.post("/api/me/maintenance-types", headers=h("tech"), json={"libelle": "Vidéoprojecteur"}).json()
    assert c.post("/api/me/maintenance-types", headers=h("sav"), json={"libelle": "vidéoprojecteur"}).status_code == 409
    assert c.post("/api/me/maintenance-types", headers=h("sav"), json={"libelle": "imprimante"}).status_code == 409
    t = c.get("/api/me/maintenance-types", headers=h("sav")).json()
    assert "Vidéoprojecteur" in t["tous"] and t["tous"][-1] == "Autre"
    assert "Vidéoprojecteur" not in c.get("/api/me/maintenance-types", headers=h("autre")).json()["tous"]
    assert c.delete(f"/api/me/maintenance-types/{n['id']}", headers=h("autre")).status_code == 404
    assert c.delete(f"/api/me/maintenance-types/{n['id']}", headers=h("sav")).status_code == 200
