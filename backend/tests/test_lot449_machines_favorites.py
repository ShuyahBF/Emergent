"""Lot 449 — Machines FAVORITES par client pour les requêtes SQL distantes : une favorite en ligne a la priorité pendant 4 s, puis la requête passe à la
prochaine machine disponible ; sans favorite en ligne, aucun délai ; une machine interdite n'est jamais favorite. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot449_machines_favorites.py -q
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


def deposer(client, sql="SELECT * FROM Recu WHERE Numero = 3"):
    return client.post("/api/loois-sql/requetes", headers=OWNER, json={"client": "IPM", "sql": sql})


def favorites(client, machines):
    return client.put("/api/loois-sql/machines-favorites/IPM", headers=OWNER, json={"machines": machines})


# ----------------------------------------------------------------- logique pure
def test_rang_machine_ordre_de_la_liste_et_non_favorites_a_egalite():
    fav = ["SERVEUR", "PC2"]
    assert sd.rang_machine("serveur ", fav) == 0 and sd.rang_machine("PC2", fav) == 1
    assert sd.rang_machine("PC9", fav) == sd.rang_machine("PC8", fav) == 2


def test_doit_attendre_seulement_si_une_favorite_plus_haut_placee_est_en_ligne_et_le_delai_pas_ecoule():
    fav, vus = ["SERVEUR"], {"SERVEUR": 100.0, "PC9": 100.0}
    assert sd.doit_attendre("PC9", fav, [], vus, 105.0, 1.0) is True              # favorite en ligne (5 s), requête récente : PC9 laisse la main
    assert sd.doit_attendre("PC9", fav, [], vus, 105.0, 4.0) is False             # délai écoulé : PC9 la prend
    assert sd.doit_attendre("PC9", fav, [], vus, 130.0, 1.0) is False             # favorite pas vue depuis 30 s : pas d'attente
    assert sd.doit_attendre("SERVEUR", fav, [], vus, 105.0, 1.0) is False         # la favorite ne s'attend jamais elle-même
    assert sd.doit_attendre("PC9", fav, ["SERVEUR"], vus, 105.0, 1.0) is False    # favorite INTERDITE : ignorée
    assert sd.doit_attendre("PC9", [], [], vus, 105.0, 1.0) is False              # aucune favorite : aucun délai
    assert sd.doit_attendre("PC9", fav, [], {"PC9": 100.0}, 105.0, 1.0) is False  # favorite jamais vue


def test_entre_deux_favorites_la_mieux_classee_a_la_priorite():
    fav, vus = ["SERVEUR", "PC2"], {"SERVEUR": 100.0, "PC2": 100.0}
    assert sd.doit_attendre("PC2", fav, [], vus, 102.0, 1.0) is True
    assert sd.doit_attendre("SERVEUR", fav, [], vus, 102.0, 1.0) is False


# ----------------------------------------------------------------- comportement par les routes
def test_requete_gardee_pour_la_favorite_puis_donnee_a_la_suivante(env, monkeypatch):
    client, db = env
    favorites(client, ["SERVEUR"])
    client.get("/api/loois-sql/poste/prochaine", headers=poste("SERVEUR"))         # la favorite est en ligne (rien à faire)
    rid = deposer(client).json()["id"]
    r = client.get("/api/loois-sql/poste/prochaine", headers=poste("PC9"))
    assert r.status_code == 204                                                    # PC9 laisse la requête à SERVEUR
    r = client.get("/api/loois-sql/poste/prochaine", headers=poste("SERVEUR"))
    assert r.status_code == 200 and r.json()["id"] == rid                          # SERVEUR la prend


def test_apres_le_delai_la_machine_suivante_prend_la_requete(env, monkeypatch):
    client, db = env
    favorites(client, ["SERVEUR"])
    client.get("/api/loois-sql/poste/prochaine", headers=poste("SERVEUR"))
    rid = deposer(client).json()["id"]
    monkeypatch.setattr(sd, "DELAI_FAVORITE_S", 0)                                 # délai écoulé tout de suite (équivaut à 4 s d'attente)
    r = client.get("/api/loois-sql/poste/prochaine", headers=poste("PC9"))
    assert r.status_code == 200 and r.json()["id"] == rid


def test_sans_favorite_en_ligne_la_requete_passe_tout_de_suite(env):
    client, _db = env
    favorites(client, ["SERVEUR"])                                                 # SERVEUR n'a jamais interrogé : pas en ligne
    rid = deposer(client).json()["id"]
    r = client.get("/api/loois-sql/poste/prochaine", headers=poste("PC9"))
    assert r.status_code == 200 and r.json()["id"] == rid


def test_gestion_par_loois_et_par_l_administrateur_ordre_conserve(env):
    client, _db = env
    r = favorites(client, [" Serveur ", "pc2", "SERVEUR", ""])                     # doublon (casse) et vide retirés, ordre gardé
    assert r.status_code == 200 and r.json() == {"client": "IPM", "machines": ["Serveur", "pc2"]}
    assert client.get("/api/loois-sql/machines-favorites", headers=OWNER).json()["clients"] == {"IPM": ["Serveur", "pc2"]}
    r = client.put("/api/admin/loois-sql/machines-favorites/IPM", headers=ADMIN, json={"machines": ["pc2"]})
    assert r.status_code == 200 and r.json()["machines"] == ["pc2"]
    assert client.get("/api/admin/loois-sql/machines-favorites", headers=ADMIN).json()["clients"] == {"IPM": ["pc2"]}
    assert client.put("/api/loois-sql/machines-favorites/IPM", headers={"X-Loois-Sql-Cle": "mauvaise-cle-xxxxxxxx"}, json={"machines": []}).status_code == 401
    assert client.put("/api/loois-sql/machines-favorites/IPM", headers=OWNER, json={"machines": "x"}).status_code == 422


def test_liste_des_clients_porte_les_favorites(env):
    client, _db = env
    favorites(client, ["SERVEUR"])
    clients = client.get("/api/loois-sql/clients", headers=OWNER).json()["clients"]
    assert clients[0]["code"] == "IPM" and clients[0]["favorites"] == ["SERVEUR"]


# ----------------------------------------------------------------- lot 449.1 : en-tête « rapide » aussi sur la réponse 200
def test_reponse_avec_requete_porte_l_en_tete_rapide_quand_une_session_est_ouverte(env):
    client, _db = env
    deposer(client)                                            # déposer une requête vaut signal de session
    r = client.get("/api/loois-sql/poste/prochaine", headers=poste("SERVEUR"))
    assert r.status_code == 200 and r.json()["sql"].startswith("SELECT")
    assert r.headers.get("X-Sql-Rapide") == "1"                # le service garde l'intervalle d'1 s après avoir exécuté (avant : retombait à 5 s)
