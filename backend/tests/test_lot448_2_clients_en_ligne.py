"""Lot 448.2 — « En ligne » d'un client pour les requêtes distantes : une machine qui interroge SAWALI (« prochaine ») est en ligne, même sans signal
de présence récent ; une machine interdite ne compte pas. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot448_2_clients_en_ligne.py -q
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

CLE = "cle-sql-proprietaire-123"
OWNER = {"X-Loois-Sql-Cle": CLE}
CLES_CLIENTS = {"LK-ipm": {"type": "client", "id": "k1", "code": "IPM"}}


def poste(machine, base="IPM"):
    return {"X-Loois-Cle": "LK-ipm", "X-Loois-Poste": machine, "X-Loois-Base": base}


async def faux_utilisateur(authorization: str = Header(default="")) -> dict:
    if authorization != "Bearer jeton-admin":
        raise HTTPException(status_code=401, detail="Token manquant")
    return {"id": "u1", "role": "admin", "email": "admin@sawali.test"}


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("LOOIS_SQL_DISTANT_CLE", CLE)
    db = mongomock_motor.AsyncMongoMockClient()["test"]

    async def identifier(_db, cle):
        return CLES_CLIENTS.get(cle or "")

    api = APIRouter(prefix="/api")
    sd.setup_loois_sql_distant_routes(db=db, api=api, get_current_user=faux_utilisateur, identifier_cle=identifier)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db


def test_machines_qui_scrutent_recentes_seulement():
    table = {"IPM": {"XERVEUR": 100.0, "VIEUX": 10.0}, "CMC": {"PC1": 99.0}}
    assert sd.machines_qui_scrutent(table, "IPM", 150.0) == ["XERVEUR"]          # VIEUX : plus de 90 s
    assert sd.machines_qui_scrutent(table, "IPM", 250.0) == []                   # plus personne
    assert sd.machines_qui_scrutent(table, "INCONNU", 150.0) == []


def test_client_sans_signal_de_presence_mais_qui_scrute_est_en_ligne(env):
    client, _db = env
    assert client.get("/api/loois-sql/clients", headers=OWNER).json()["clients"] == []   # rien tant que personne n'a interrogé
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("XERVEUR")).status_code == 204
    clients = client.get("/api/loois-sql/clients", headers=OWNER).json()["clients"]
    assert [c["code"] for c in clients] == ["IPM"]
    assert clients[0]["en_ligne"] is True and clients[0]["repond"] is True and clients[0]["machines"] == ["XERVEUR"]


def test_presence_ancienne_mais_machine_qui_scrute_reste_en_ligne(env):
    client, db = env
    import asyncio
    ancien = "2026-11-18T10:00:00+00:00"
    asyncio.get_event_loop().run_until_complete(db.presences_logiciels.insert_one(
        {"application": "LooisSyncService", "machine": "XERVEUR", "site": "IPM", "vu_le": ancien}))
    avant = client.get("/api/loois-sql/clients", headers=OWNER).json()["clients"]
    assert avant[0]["en_ligne"] is False                                        # signal de présence trop ancien
    client.get("/api/loois-sql/poste/prochaine", headers=poste("XERVEUR"))
    apres = client.get("/api/loois-sql/clients", headers=OWNER).json()["clients"]
    assert apres[0]["en_ligne"] is True and apres[0]["machines"] == ["XERVEUR"]  # la machine répond : en ligne, sans doublon de nom


def test_machine_interdite_ne_compte_pas_comme_en_ligne(env):
    client, _db = env
    client.put("/api/loois-sql/machines-interdites/IPM", headers=OWNER, json={"machines": ["XERVEUR"]})
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("XERVEUR")).status_code == 204
    assert client.get("/api/loois-sql/clients", headers=OWNER).json()["clients"] == [] or \
        all(not c.get("en_ligne") for c in client.get("/api/loois-sql/clients", headers=OWNER).json()["clients"])
