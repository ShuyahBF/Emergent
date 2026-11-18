"""Lot 446 — Page d'administration « SQL Distant » (téléphone) : réservée à l'administrateur (compte, pas de clé), confirmation renforcée des
modifications, requêtes déposées pour UNE machine, auteur noté. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot446_sql_distant_admin.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.loois_sql_distant as sd  # noqa: E402

UTILISATEURS = {"jeton-admin": {"id": "u1", "role": "admin", "email": "admin@sawali.test"}, "jeton-client": {"id": "u2", "role": "client", "email": "c@x.test"}}


async def faux_utilisateur(authorization: str = Header(default="")) -> dict:
    """Remplace get_current_user : « Bearer <jeton> » → compte, sinon 401."""
    u = UTILISATEURS.get(authorization.replace("Bearer ", ""))
    if not u:
        raise HTTPException(status_code=401, detail="Token manquant")
    return u


@pytest.fixture()
def env():
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    api = APIRouter(prefix="/api")
    sd.setup_loois_sql_distant_routes(db=db, api=api, get_current_user=faux_utilisateur, identifier_cle=None)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db


ADMIN = {"Authorization": "Bearer jeton-admin"}
CLIENT = {"Authorization": "Bearer jeton-client"}


def test_sans_compte_ou_non_admin_refuse(env):
    client, _ = env
    assert client.get("/api/admin/loois-sql/clients").status_code == 401
    assert client.get("/api/admin/loois-sql/clients", headers=CLIENT).status_code == 403
    assert client.post("/api/admin/loois-sql/requetes", headers=CLIENT, json={"client": "IPM", "sql": "SELECT 1"}).status_code == 403


def test_lecture_deposee_sans_confirmation(env):
    client, db = env
    r = client.post("/api/admin/loois-sql/requetes", headers=ADMIN, json={"client": "ipm", "sql": "SELECT * FROM Recu WHERE Numero = 3"})
    assert r.status_code == 201 and r.json()["etat"] == "attente" and r.json()["client"] == "IPM"
    doc = client.get("/api/admin/loois-sql/requetes", headers=ADMIN).json()
    assert len(doc["requetes"]) == 1


def test_modification_exige_la_confirmation_renforcee(env):
    client, _ = env
    sql = "UPDATE Recu SET Montant = 10 WHERE Numero = 3"
    # sans confirmation (ou confirmation non booléenne) : refusée et RIEN n'est déposé
    for corps in ({"client": "IPM", "sql": sql}, {"client": "IPM", "sql": sql, "confirme_modification": "oui"}, {"client": "IPM", "sql": sql, "confirme_modification": False}):
        r = client.post("/api/admin/loois-sql/requetes", headers=ADMIN, json=corps)
        assert r.status_code == 422 and "Confirmation renforcée" in r.json()["detail"]
    assert client.get("/api/admin/loois-sql/requetes", headers=ADMIN).json()["requetes"] == []
    # avec confirmation explicite : déposée
    r = client.post("/api/admin/loois-sql/requetes", headers=ADMIN, json={"client": "IPM", "sql": sql, "confirme_modification": True})
    assert r.status_code == 201


def test_la_confirmation_ne_contourne_pas_le_controle_prudent(env):
    client, _ = env
    r = client.post("/api/admin/loois-sql/requetes", headers=ADMIN, json={"client": "IPM", "sql": "DROP TABLE Recu", "confirme_modification": True})
    assert r.status_code == 422 and "Seules" in r.json()["detail"]
    r = client.post("/api/admin/loois-sql/requetes", headers=ADMIN, json={"client": "IPM", "sql": "DELETE FROM Recu", "confirme_modification": True})
    assert r.status_code == 422 and "WHERE" in r.json()["detail"]


def test_auteur_note_et_jamais_renvoye(env):
    client, db = env
    r = client.post("/api/admin/loois-sql/requetes", headers=ADMIN, json={"client": "IPM", "sql": "SELECT 1 FROM Recu"})
    rid = r.json()["id"]
    import asyncio
    doc = asyncio.get_event_loop().run_until_complete(db.loois_reglages.find_one({"id": sd.ID_DOC}))
    assert doc["requetes"][0]["cree_par"] == "admin@sawali.test"            # gardé pour l'audit
    corps = client.get(f"/api/admin/loois-sql/requetes/{rid}", headers=ADMIN).text
    assert "admin@sawali.test" not in corps and "cree_ip" not in corps        # jamais renvoyé à l'écran
    assert client.get("/api/admin/loois-sql/requetes/inconnue", headers=ADMIN).status_code == 404
