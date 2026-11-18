"""Lot 439 — Requêtes SQL à distance : contrôle « Prudent », clé du propriétaire, UNE SEULE machine exécute, résultat avec le nom de la machine,
délais (expirée, sans réponse), résultat borné. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot439_loois_sql_distant.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.loois_sql_distant as sd  # noqa: E402

CLE = "cle-sql-proprietaire-123"
OWNER = {"X-Loois-Sql-Cle": CLE}
CLES_CLIENTS = {"LK-ipm-1": {"type": "client", "id": "k1", "code": "IPM"}, "LK-ipm-2": {"type": "client", "id": "k2", "code": "IPM"},
                "LK-cmc": {"type": "client", "id": "k3", "code": "CMC"}, "commune": {"type": "commune"}}


def poste(cle, machine, base):
    return {"X-Loois-Cle": cle, "X-Loois-Poste": machine, "X-Loois-Base": base}


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("LOOIS_SQL_DISTANT_CLE", CLE)
    db = mongomock_motor.AsyncMongoMockClient()["test"]

    async def identifier(_db, cle):
        return CLES_CLIENTS.get(cle or "")

    api = APIRouter(prefix="/api")
    sd.setup_loois_sql_distant_routes(db=db, api=api, identifier_cle=identifier)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db


def deposer(client, sql="UPDATE VenteClinique SET Montant = 5000 WHERE NumFacture = 'F001'", cible="IPM"):
    return client.post("/api/loois-sql/requetes", headers=OWNER, json={"client": cible, "sql": sql})


# ------------------------------------------------------------------ contrôle des requêtes (même règle que Loois)
@pytest.mark.parametrize("sql,nature", [("SELECT * FROM VenteClinique WHERE NumFacture = 'F001'", "SELECT"), ("select Nom from [Patient] where id = 5;", "SELECT"),
                                         ("UPDATE VenteClinique SET Montant = 5000 WHERE NumFacture = 'F001'", "MODIF"), ("DELETE FROM Recu WHERE Numero = 12", "MODIF"),
                                         ("INSERT INTO Journal (Texte) VALUES ('ok')", "MODIF"), ("UPDATE Client SET Note = 'DROP; -- l''été' WHERE Id = 3", "MODIF"),
                                         ("SELECT Create_Date FROM Client WHERE Id = 1", "SELECT")])
def test_requetes_autorisees(sql, nature):
    ok, n, _ = sd.verifier(sql)
    assert ok and n == nature


@pytest.mark.parametrize("sql,raison", [("", "Saisissez"), ("DROP TABLE Patient", "Seules"), ("TRUNCATE TABLE Recu", "Seules"), ("UPDATE Recu SET Montant = 0", "WHERE"),
                                         ("DELETE FROM Recu", "WHERE"), ("SELECT 1; DROP TABLE Patient", "Une seule instruction"), ("SELECT * FROM Recu -- x", "commentaires"),
                                         ("SELECT * FROM Recu WHERE Nom = 'abc", "non fermé"), ("SELECT * FROM Recu WHERE 1=1 AND EXEC xp", "EXEC"),
                                         ("SELECT " + "a" * 4001, "trop longue")])
def test_requetes_refusees(sql, raison):
    ok, _, texte = sd.verifier(sql)
    assert not ok and raison in texte


# ------------------------------------------------------------------ clé du propriétaire
def test_cle_proprietaire_exigee(env, monkeypatch):
    client, _ = env
    assert client.get("/api/loois-sql/requetes").status_code == 401                       # sans clé
    assert client.get("/api/loois-sql/requetes", headers={"X-Loois-Sql-Cle": "mauvaise"}).status_code == 401
    assert client.get("/api/loois-sql/requetes", headers=OWNER).status_code == 200
    monkeypatch.delenv("LOOIS_SQL_DISTANT_CLE")
    assert client.get("/api/loois-sql/requetes", headers=OWNER).status_code == 503        # fonction non activée : jamais ouverte par défaut


def test_essais_de_cle_limites(env):
    client, _ = env
    for _ in range(sd.ESSAIS_CLE_MAX):
        assert client.get("/api/loois-sql/requetes", headers={"X-Loois-Sql-Cle": "x" * 20}).status_code == 401
    assert client.get("/api/loois-sql/requetes", headers=OWNER).status_code == 429        # même la bonne clé attend


def test_depot_refuse_une_requete_dangereuse(env):
    client, _ = env
    assert deposer(client, "DROP TABLE VenteClinique").status_code == 422
    assert deposer(client, "UPDATE VenteClinique SET Montant = 0").status_code == 422
    assert deposer(client, cible="client invalide!").status_code == 422
    r = deposer(client)
    assert r.status_code == 201 and r.json()["etat"] == "attente" and r.json()["client"] == "IPM"
    assert "cree_ip" not in r.json() and "cle_id" not in r.json()                          # jamais exposés


# ------------------------------------------------------------------ UNE SEULE machine exécute
def test_une_seule_machine_prend_la_requete(env):
    client, _ = env
    rid = deposer(client).json()["id"]
    a = client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"))
    assert a.status_code == 200 and a.json()["id"] == rid and "UPDATE VenteClinique" in a.json()["sql"]
    b = client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-2", "PC-IPM-2", "IPM"))
    assert b.status_code == 204                                                           # la seconde machine ne la voit plus
    c = client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"))
    assert c.status_code == 204                                                           # même la première ne la reçoit pas deux fois
    d = client.get(f"/api/loois-sql/requetes/{rid}", headers=OWNER).json()
    assert d["etat"] == "prise" and d["machine"] == "PC-IPM-1"                            # le retour dit QUELLE machine


def test_un_autre_client_ne_prend_pas_la_requete(env):
    client, _ = env
    deposer(client)
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-cmc", "PC-CMC", "CMC")).status_code == 204
    assert client.get("/api/loois-sql/requetes", headers=OWNER).json()["requetes"][0]["etat"] == "attente"


def test_poste_sans_cle_client_refuse(env):
    client, _ = env
    deposer(client)
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("commune", "PC", "IPM")).status_code == 401      # la clé commune ne suffit pas
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("inconnue", "PC", "IPM")).status_code == 401
    assert client.get("/api/loois-sql/poste/prochaine", headers={"X-Loois-Cle": "LK-ipm-1"}).status_code == 422       # machine et base requises


# ------------------------------------------------------------------ résultat
def test_resultat_d_une_modification(env):
    client, _ = env
    rid = deposer(client).json()["id"]
    client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"))
    # une autre machine ne peut pas répondre à sa place
    r = client.post("/api/loois-sql/poste/resultat", headers=poste("LK-ipm-2", "PC-IPM-2", "IPM"), json={"id": rid, "ok": True, "message": "x"})
    assert r.status_code == 409
    ok = client.post("/api/loois-sql/poste/resultat", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"),
                     json={"id": rid, "ok": True, "message": "1 ligne(s) modifiée(s).", "lignes_affectees": 1, "base": "myAurora-IPM", "duree_ms": 42})
    assert ok.status_code == 200
    d = client.get(f"/api/loois-sql/requetes/{rid}", headers=OWNER).json()
    assert d["etat"] == "terminee" and d["ok"] is True and d["machine"] == "PC-IPM-1" and d["base"] == "myAurora-IPM"
    assert d["message"] == "1 ligne(s) modifiée(s)." and d["lignes_affectees"] == 1
    # une requête terminée ne peut plus recevoir de résultat
    assert client.post("/api/loois-sql/poste/resultat", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"), json={"id": rid, "ok": False}).status_code == 409


def test_resultat_d_erreur_hfsql_et_select(env):
    client, _ = env
    r1 = deposer(client, "SELECT * FROM Inconnue WHERE 1 = 1").json()["id"]
    client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"))
    client.post("/api/loois-sql/poste/resultat", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"), json={"id": r1, "ok": False, "message": "70016 : table inconnue"})
    d1 = client.get(f"/api/loois-sql/requetes/{r1}", headers=OWNER).json()
    assert d1["etat"] == "echec" and d1["message"] == "70016 : table inconnue" and d1["machine"] == "PC-IPM-1"
    r2 = deposer(client, "SELECT NumFacture, Montant FROM VenteClinique WHERE 1 = 1").json()["id"]
    client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-2", "PC-IPM-2", "IPM"))
    client.post("/api/loois-sql/poste/resultat", headers=poste("LK-ipm-2", "PC-IPM-2", "IPM"),
                json={"id": r2, "ok": True, "message": "2 ligne(s) lue(s).", "colonnes": ["NumFacture", "Montant"], "lignes": [["F001", "5000"], ["F002", None]]})
    d2 = client.get(f"/api/loois-sql/requetes/{r2}", headers=OWNER).json()
    assert d2["colonnes"] == ["NumFacture", "Montant"] and d2["lignes"] == [["F001", "5000"], ["F002", ""]] and d2["machine"] == "PC-IPM-2"
    # l'historique est léger : sans les lignes
    assert all(r["lignes"] == [] for r in client.get("/api/loois-sql/requetes", headers=OWNER).json()["requetes"])


def test_resultat_borne():
    gros = {"ok": True, "colonnes": ["c"] * 150, "lignes": [["x" * 900] * 3 for _ in range(500)], "message": "m" * 5000}
    r = sd.resultat_borne(gros)
    assert len(r["colonnes"]) == sd.COLONNES_MAX and len(r["lignes"]) <= sd.LIGNES_MAX and r["tronque"] is True
    assert all(len(c) <= sd.CELLULE_MAX for ligne in r["lignes"] for c in ligne) and len(r["message"]) == 2000


# ------------------------------------------------------------------ délais : jamais rejouée, jamais exécutée trop tard
def test_delais():
    maintenant = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    vieille_attente = {"etat": "attente", "cree_le": (maintenant - timedelta(minutes=31)).isoformat()}
    assert sd.vieillir(vieille_attente, maintenant)["etat"] == "expiree"
    assert sd.vieillir({"etat": "attente", "cree_le": (maintenant - timedelta(minutes=5)).isoformat()}, maintenant) == {}
    muette = {"etat": "prise", "prise_le": (maintenant - timedelta(minutes=11)).isoformat()}
    assert sd.vieillir(muette, maintenant)["etat"] == "sans_reponse"
    assert sd.vieillir({"etat": "prise", "prise_le": (maintenant - timedelta(minutes=2)).isoformat()}, maintenant) == {}
    assert sd.vieillir({"etat": "terminee"}, maintenant) == {}


def test_requete_expiree_jamais_donnee_a_une_machine(env):
    client, db = env
    import asyncio
    rid = deposer(client).json()["id"]
    vieux = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    asyncio.get_event_loop().run_until_complete(db.loois_reglages.update_one({"id": sd.ID_DOC, "requetes.id": rid}, {"$set": {"requetes.$.cree_le": vieux}}))
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM")).status_code == 204
    assert client.get(f"/api/loois-sql/requetes/{rid}", headers=OWNER).json()["etat"] == "expiree"


def test_requete_sans_reponse_jamais_rejouee(env):
    client, db = env
    import asyncio
    rid = deposer(client).json()["id"]
    client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"))
    vieux = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    asyncio.get_event_loop().run_until_complete(db.loois_reglages.update_one({"id": sd.ID_DOC, "requetes.id": rid}, {"$set": {"requetes.$.prise_le": vieux}}))
    d = client.get(f"/api/loois-sql/requetes/{rid}", headers=OWNER).json()
    assert d["etat"] == "sans_reponse" and d["machine"] == "PC-IPM-1"
    assert client.get("/api/loois-sql/poste/prochaine", headers=poste("LK-ipm-2", "PC-IPM-2", "IPM")).status_code == 204      # pas rejouée ailleurs
    # une réponse tardive de la machine est refusée (état figé)
    assert client.post("/api/loois-sql/poste/resultat", headers=poste("LK-ipm-1", "PC-IPM-1", "IPM"), json={"id": rid, "ok": True}).status_code == 409


# ------------------------------------------------------------------ clients en ligne
def test_clients_en_ligne():
    maintenant = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    fiches = [{"site": "ipm", "machine": "PC1", "vu_le": (maintenant - timedelta(minutes=2)).isoformat()},
              {"site": "IPM", "machine": "PC2", "vu_le": (maintenant - timedelta(hours=3)).isoformat()},
              {"site": "CMC", "machine": "PC3", "vu_le": (maintenant - timedelta(days=2)).isoformat()},
              {"site": "école bizarre!", "machine": "PCX", "vu_le": maintenant.isoformat()}, {"machine": "PCY"}]
    r = sd.clients_en_ligne(fiches, maintenant)
    assert [c["code"] for c in r] == ["CMC", "IPM"]
    assert r[1]["machines"] == ["PC1", "PC2"] and r[1]["en_ligne"] is True and r[0]["en_ligne"] is False


def test_resultat_borne_garde_la_description_des_champs():
    """Lot 443 : la description des champs (clé / automatique / calculé) est conservée, bornée et nettoyée."""
    r = sd.resultat_borne({"ok": True, "colonnes": ["Id", "Nom"], "lignes": [["1", "A"]],
                           "schema": [{"nom": "Id", "cle": True, "auto": True, "type": "Int32", "table": "Client"}, {"nom": "Nom", "type": "String"}, "pas un dict"]})
    assert r["schema"][0] == {"nom": "Id", "cle": True, "auto": True, "calcule": False, "type": "Int32", "table": "Client"}
    assert r["schema"][1]["cle"] is False and len(r["schema"]) == 2


def test_vue_requete_expose_le_schema():
    assert sd.vue_requete({"id": "x", "schema": [{"nom": "Id"}]})["schema"] == [{"nom": "Id"}]
    assert sd.vue_requete({"id": "x"})["schema"] == []
