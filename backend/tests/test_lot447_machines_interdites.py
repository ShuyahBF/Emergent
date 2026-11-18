"""Lot 447 — Machines INTERDITES par client pour les requêtes SQL distantes : une machine interdite ne reçoit jamais de requête (les autres machines
du client, si), son résultat tardif est refusé, gestion par la clé de Loois ET par le compte administrateur de SAWALI. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot447_machines_interdites.py -q
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
ADMIN = {"Authorization": "Bearer jeton-admin"}
SIMPLE = {"Authorization": "Bearer jeton-client"}
CLES_CLIENTS = {"LK-ipm": {"type": "client", "id": "k1", "code": "IPM"}, "LK-cmc": {"type": "client", "id": "k3", "code": "CMC"}}
UTILISATEURS = {"jeton-admin": {"id": "u1", "role": "admin", "email": "admin@sawali.test"}, "jeton-client": {"id": "u2", "role": "client", "email": "c@x.test"}}


def poste(machine, base="IPM"):
    return {"X-Loois-Cle": "LK-ipm" if base == "IPM" else "LK-cmc", "X-Loois-Poste": machine, "X-Loois-Base": base}


async def faux_utilisateur(authorization: str = Header(default="")) -> dict:
    u = UTILISATEURS.get(authorization.replace("Bearer ", ""))
    if not u:
        raise HTTPException(status_code=401, detail="Token manquant")
    return u


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


def deposer(client, sql="SELECT * FROM Recu WHERE Numero = 3", cible="IPM"):
    return client.post("/api/loois-sql/requetes", headers=OWNER, json={"client": cible, "sql": sql})


def interdire(client, machines, cible="IPM"):
    return client.put(f"/api/loois-sql/machines-interdites/{cible}", headers=OWNER, json={"machines": machines})


# ------------------------------------------------------------------ fonctions pures
def test_noms_nettoyes_sans_doublon():
    assert sd.normaliser_machines(["  PC-1 ", "pc-1", "PC-2", "", None, "PC\x00-3"]) == ["PC-1", "PC-2", "PC-3"]
    assert sd.normaliser_machines("pas une liste") == []
    assert len(sd.normaliser_machines([f"M{i}" for i in range(500)])) == sd.MACHINES_INTERDITES_MAX
    assert len(sd.nom_machine("x" * 500)) == sd.NOM_MACHINE_MAX


def test_machine_interdite_casse_et_espaces_ignores():
    assert sd.machine_interdite(" pc-caisse ", ["PC-CAISSE"])
    assert not sd.machine_interdite("PC-AUTRE", ["PC-CAISSE"])
    assert not sd.machine_interdite("", ["PC-CAISSE"])
    assert not sd.machine_interdite("PC-1", None)


# ------------------------------------------------------------------ application sur les machines
def test_machine_interdite_ne_recoit_rien_les_autres_oui(env):
    client, _ = env
    assert interdire(client, ["PC-CAISSE"]).status_code == 200
    rid = deposer(client).json()["id"]
    # La machine interdite (casse différente) voit « rien à faire » : la requête reste en attente
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("pc-caisse")).status_code == 204
    assert client.get(f"/api/loois-sql/requetes/{rid}", headers=OWNER).json()["etat"] == "attente"
    # Une autre machine du même client la reçoit
    r = client.get("/api/loois-sql/poste/prochaine", headers=poste("PC-LABO"))
    assert r.status_code == 200 and r.json()["id"] == rid
    assert client.get(f"/api/loois-sql/requetes/{rid}", headers=OWNER).json()["machine"] == "PC-LABO"


def test_interdiction_propre_a_chaque_client(env):
    client, _ = env
    interdire(client, ["PC-1"], "IPM")
    deposer(client, cible="CMC")
    # « PC-1 » est interdite chez IPM seulement : chez CMC elle reçoit la requête
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("PC-1", "CMC")).status_code == 200


def test_resultat_d_une_machine_interdite_apres_prise_est_refuse(env):
    client, _ = env
    rid = deposer(client).json()["id"]
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("PC-X")).status_code == 200      # prise avant l'interdiction
    interdire(client, ["PC-X"])
    r = client.post("/api/loois-sql/poste/resultat", headers=poste("PC-X"), json={"id": rid, "ok": True, "message": "ok", "colonnes": [], "lignes": []})
    assert r.status_code == 403
    assert client.get(f"/api/loois-sql/requetes/{rid}", headers=OWNER).json()["etat"] == "prise"       # jamais rejouée, ira « sans réponse »


def test_liste_videe_leve_l_interdiction(env):
    client, _ = env
    interdire(client, ["PC-1"])
    deposer(client)
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("PC-1")).status_code == 204
    assert interdire(client, []).json() == {"client": "IPM", "machines": []}
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("PC-1")).status_code == 200


# ------------------------------------------------------------------ gestion : clé de Loois et compte administrateur
def test_gestion_par_la_cle_de_loois(env):
    client, _ = env
    assert client.get("/api/loois-sql/machines-interdites").status_code == 401                          # sans clé
    assert client.put("/api/loois-sql/machines-interdites/IPM", headers={"X-Loois-Sql-Cle": "fausse"}, json={"machines": ["A"]}).status_code == 401
    assert interdire(client, [" PC-1 ", "pc-1", "PC-2"]).json() == {"client": "IPM", "machines": ["PC-1", "PC-2"]}
    assert client.get("/api/loois-sql/machines-interdites", headers=OWNER).json() == {"clients": {"IPM": ["PC-1", "PC-2"]}}
    assert client.put("/api/loois-sql/machines-interdites/bad code!", headers=OWNER, json={"machines": []}).status_code in (404, 422)
    assert client.put("/api/loois-sql/machines-interdites/IPM", headers=OWNER, json={"machines": "PC-1"}).status_code == 422


def test_gestion_par_le_compte_administrateur(env):
    client, db = env
    assert client.get("/api/admin/loois-sql/machines-interdites").status_code == 401
    assert client.get("/api/admin/loois-sql/machines-interdites", headers=SIMPLE).status_code == 403
    assert client.put("/api/admin/loois-sql/machines-interdites/IPM", headers=SIMPLE, json={"machines": ["A"]}).status_code == 403
    r = client.put("/api/admin/loois-sql/machines-interdites/ipm", headers=ADMIN, json={"machines": ["PC-9"]})
    assert r.status_code == 200 and r.json() == {"client": "IPM", "machines": ["PC-9"]}                 # code du client mis en majuscules
    assert client.get("/api/admin/loois-sql/machines-interdites", headers=ADMIN).json() == {"clients": {"IPM": ["PC-9"]}}
    import asyncio
    doc = asyncio.new_event_loop().run_until_complete(db.loois_reglages.find_one({"id": sd.ID_INTERDITES}))
    assert doc["modifie_par"] == "admin@sawali.test"                                                    # auteur gardé pour l'audit


def test_liste_des_clients_porte_les_interdictions(env):
    client, db = env
    import asyncio
    from datetime import datetime, timezone
    asyncio.new_event_loop().run_until_complete(db.presences_logiciels.insert_one(
        {"application": "LooisSyncService", "site": "IPM", "machine": "PC-1", "vu_le": datetime.now(timezone.utc).isoformat()}))
    interdire(client, ["PC-1", "PC-FANTOME"])
    interdire(client, ["PC-Z"], "CMC")                                  # client jamais vu récemment : reste visible pour pouvoir être modifié
    liste = {c["code"]: c for c in client.get("/api/loois-sql/clients", headers=OWNER).json()["clients"]}
    assert liste["IPM"]["interdites"] == ["PC-1", "PC-FANTOME"] and liste["IPM"]["machines"] == ["PC-1"]
    assert liste["CMC"]["interdites"] == ["PC-Z"] and liste["CMC"]["machines"] == []
    assert client.get("/api/admin/loois-sql/clients", headers=ADMIN).json()["clients"][0]["interdites"] is not None
