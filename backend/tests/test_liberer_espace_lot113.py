"""Lot 113 — « 🧹 Libérer l'Espace » : analyse (R2 de migration, R2 quotidiennes, bases Atlas) et exécution
avec re-vérification des protections. MongoDB et R2 simulés.
Lancer : cd backend && python -m pytest tests/test_liberer_espace_lot113.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
pytest.importorskip("cryptography")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot113")

from fastapi import HTTPException  # noqa: E402

import routes.liberer_espace as le  # noqa: E402
import routes.migration_programmation as mp  # noqa: E402
import routes.migration_render as mr  # noqa: E402
import routes.sauvegarde_complete as sc  # noqa: E402
from tests.test_migration_render_programmation import FauxR2  # noqa: E402

ADMIN = {"email": "admin@test", "role": "admin"}
MAINTENANT = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
BUCKET = "sawali-migration"


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def env(monkeypatch):
    """Cluster simulé (sawali + 2 bases obsolètes), bucket de migration simulé, rapports simulés."""
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["sawali"]
    monkeypatch.setattr(mr, "db", db)
    for nom in ("R2_SAUVEGARDES_ACCOUNT_ID", "R2_SAUVEGARDES_ACCESS_KEY_ID", "R2_SAUVEGARDES_SECRET_ACCESS_KEY",
                "R2_STOCKS_ACCOUNT_ID", "R2_STOCKS_ACCESS_KEY_ID", "R2_STOCKS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(nom, raising=False)

    r2 = FauxR2(page=3)                                       # petites pages : la pagination est éprouvée
    r2.ajouter("migration-20260801-030000", 5, 1000)          # ancienne réussie → rétention : à supprimer
    r2.ajouter("migration-20260815-030000", 2, 500)           # ancienne en échec → à supprimer
    r2.ajouter("migration-20260901-030000", 4, 2000)          # réussie, parmi les 3 dernières → gardée
    r2.ajouter("migration-20260920-030000", 1, 100)           # réussie, parmi les 3 dernières → gardée
    r2.ajouter("migration-20261001-030000", 3, 3000)          # dernière réussie → protégée
    r2.ajouter("migration-20261011-030000", 2, 10)            # en cours → protégée
    r2.objets["note-a-la-racine.txt"] = 7                     # fichier à la racine → protégé

    async def ids():
        return {"r2_account_id": "a", "r2_access_key_id": "b", "r2_secret_access_key": "c", "r2_bucket": BUCKET}
    monkeypatch.setattr(mp, "charger_identifiants", ids)
    monkeypatch.setattr(mp, "_client_r2", lambda _ids: r2)

    rapports = []

    async def faux_rapport(sujet, texte, cfg, important, maintenant=None):
        rapports.append((sujet, texte))
        return {"envoye": True}
    monkeypatch.setattr(mp, "envoyer_rapport", faux_rapport)

    async def remplir():
        jobs = [("j1", "migration-20260801-030000", "TERMINEE"), ("j2", "migration-20260815-030000", "ECHEC"),
                ("j3", "migration-20260901-030000", "TERMINEE"), ("j4", "migration-20260920-030000", "TERMINEE"),
                ("j5", "migration-20261001-030000", "TERMINEE"), ("j6", "migration-20261011-030000", "EN_COURS")]
        await db.migration_jobs.insert_many([{"id": i, "statut": s, "programmee": True,
                                              "cible": {"prefixe": p, "r2_bucket": BUCKET}} for i, p, s in jobs])
        await db.migration_programmation.insert_one({"_id": mp.DOC_ID, "retention_jours": 14, "garder_min": 3,
                                                     "purge_manuelles": True})
        for i in range(3):
            await client["smartsystems"][f"c{i}"].insert_one({"x": i})       # base obsolète
        await client["copie_essai"]["a"].insert_many([{"x": 1}, {"x": 2}])  # autre base obsolète
        await client["albarka"]["patients"].insert_one({"x": 1})            # base en service (protégée)
        await db.settings.insert_one({"_id": "global", "atlas_bases_protegees": "copie_essai"})
    lancer(remplir())
    return db, client, r2, rapports


def test_classement_r2_migration(env):
    """Rétention → coché ; gardée par la règle → non coché ; en cours / dernière réussie / racine → protégés."""
    db, client, _r2, _ = env
    a = lancer(le.analyser(db, client, "sawali", MAINTENANT))
    par = {e["prefixe"]: e for e in a["migration"]["elements"]}
    assert a["migration"]["disponible"] is True
    assert par["migration-20260801-030000"]["classe"] == "a_supprimer" and par["migration-20260801-030000"]["coche"]
    assert par["migration-20260815-030000"]["classe"] == "a_supprimer"
    assert par["migration-20260901-030000"]["classe"] == "garde" and not par["migration-20260901-030000"]["coche"]
    assert par["migration-20261001-030000"]["classe"] == "protege"
    assert par["migration-20261001-030000"]["raison"] == "dernière sauvegarde réussie"
    assert par["migration-20261011-030000"]["raison"] == "sauvegarde en cours"
    assert par["(racine)"]["classe"] == "protege" and not par["(racine)"]["coche"]
    # Exactement ce que la purge programmée choisirait
    cfg = lancer(mp.lire_reglage())
    jobs = lancer(le._jobs_par_prefixe(BUCKET))
    attendus, _ = mp.choisir_a_purger([p for p in par if p != "(racine)"], jobs, cfg, MAINTENANT)
    assert sorted(attendus) == sorted(p for p, e in par.items() if e["coche"])
    # Synthèse : gains de la sélection par défaut, Atlas jamais coché
    assert a["synthese"]["octets_liberes"] == 5 * 1000 + 2 * 500
    assert a["synthese"]["collections_liberees"] == 0
    noms = {b["nom"]: b for b in a["atlas"]["bases"]}
    assert set(noms) == {"smartsystems"}                      # albarka, sawali et copie_essai (réglage) protégées
    assert noms["smartsystems"]["collections"] == 3 and noms["smartsystems"]["documents"] == 3
    assert not noms["smartsystems"]["coche"]
    assert {b["nom"] for b in a["atlas"]["protegees"]} >= {"albarka", "copie_essai", "sawali"}
    assert a["jauge"]["total"] >= 5 and a["quotidiennes"]["disponible"] is False


def test_classement_quotidiennes():
    """Au-delà de la rotation → coché ; la plus récente et les noms hors motif → protégés."""
    p = "sauvegardes-completes/"
    objets = [{"cle": f"{p}sawali-2026{m:02d}{j:02d}-030000.sawali", "taille": 10}
              for m in range(1, 11) for j in (1, 8, 15, 22)]
    objets.append({"cle": f"{p}notes.txt", "taille": 3})
    lignes = {x["cle"]: x for x in le.classer_quotidiennes(objets, p)}
    plus_recente = lignes[f"{p}sawali-20261022-030000.sawali"]
    assert plus_recente["classe"] == "protege" and not plus_recente["coche"]
    assert lignes[f"{p}notes.txt"]["classe"] == "protege"
    decision = sc.retention([o["cle"] for o in objets])
    assert {c for c, x in lignes.items() if x["coche"]} == set(decision["supprimer"])
    assert all(not x["coche"] for x in lignes.values() if x["classe"] != "a_supprimer")


def test_analyse_sans_identifiants_r2(env, monkeypatch):
    """Sans identifiants R2, la partie R2 donne un message clair et la partie Atlas fonctionne."""
    db, client, _r2, _ = env

    async def aucun():
        raise RuntimeError("Aucun identifiant enregistré pour les sauvegardes programmées")
    monkeypatch.setattr(mp, "charger_identifiants", aucun)
    a = lancer(le.analyser(db, client, "sawali", MAINTENANT))
    assert a["migration"]["disponible"] is False and "Sauvegardes programmées" in a["migration"]["message"]
    assert [b["nom"] for b in a["atlas"]["bases"]] == ["smartsystems"]
    assert a["synthese"]["octets_liberes"] == 0


def test_confirmation_obligatoire(env):
    db, client, r2, _ = env
    for mot in ("", "oui", "SUPPRIMER"):
        with pytest.raises(HTTPException) as e:
            lancer(le.executer(db, client, "sawali", le.ExecutionIn(r2_prefixes=["migration-20260801-030000"],
                                                                    confirmation=mot), ADMIN))
        assert e.value.status_code == 400
    assert any(k.startswith("migration-20260801") for k in r2.objets)
    for mot in ("LIBERER", " libérer ", "Libérer", "LIBÉRER"):
        assert le.mot_confirme(mot)


def test_refus_des_elements_proteges(env):
    """Un seul élément protégé : refus complet, rien n'est supprimé (on ne fait pas confiance à l'écran)."""
    db, client, r2, _ = env
    avant = dict(r2.objets)
    for corps in (le.ExecutionIn(r2_prefixes=["migration-20260801-030000", "migration-20261001-030000"],
                                 confirmation="LIBERER"),
                  le.ExecutionIn(r2_prefixes=["migration-20261011-030000"], confirmation="LIBERER"),
                  le.ExecutionIn(r2_prefixes=["(racine)"], confirmation="LIBERER"),
                  le.ExecutionIn(r2_prefixes=["migration-20260801-030000"], bases=["albarka"], confirmation="LIBERER"),
                  le.ExecutionIn(bases=["sawali"], confirmation="LIBERER"),
                  le.ExecutionIn(bases=["copie_essai"], confirmation="LIBERER")):
        with pytest.raises(HTTPException) as e:
            lancer(le.executer(db, client, "sawali", corps, ADMIN))
        assert e.value.status_code == 409
    assert r2.objets == avant
    assert "copie_essai" in lancer(client.list_database_names())
    with pytest.raises(HTTPException) as e:
        lancer(le.executer(db, client, "sawali", le.ExecutionIn(bases=["inexistante"], confirmation="LIBERER"), ADMIN))
    assert e.value.status_code == 404


def test_execution_supprime_marque_et_trace(env):
    db, client, r2, rapports = env
    corps = le.ExecutionIn(r2_prefixes=["migration-20260801-030000", "migration-20260901-030000"],
                           bases=["smartsystems"], confirmation="libérer")
    r = lancer(le.executer(db, client, "sawali", corps, ADMIN, MAINTENANT))
    assert r["erreurs"] == 0 and r["octets_liberes"] == 5000 + 8000 and r["collections_liberees"] == 3
    assert not any(k.startswith(("migration-20260801", "migration-20260901")) for k in r2.objets)
    assert any(k.startswith("migration-20261001") for k in r2.objets)            # le reste est intact
    assert "smartsystems" not in lancer(client.list_database_names())
    j1 = lancer(db.migration_jobs.find_one({"id": "j1"}))
    assert j1["purgee"] is True and j1["purge"]["manuelle"] is True and j1["purge"]["par"] == "admin@test"
    assert r["jauge_apres"]["total"] >= 1
    trace = lancer(db.settings.find_one({"_id": le.DOC_ID}))["derniere_execution"]
    assert trace["par"] == "admin@test" and trace["collections_liberees"] == 3
    assert rapports and rapports[0][0] == "Libération d'espace" and "smartsystems" in rapports[0][1]
    purges = lancer(db.settings.find_one({"_id": "quota_atlas"}))["purges"]
    assert purges[-1]["base"] == "smartsystems" and purges[-1]["par"] == "admin@test"


def test_execution_rapport_en_echec_ne_bloque_pas(env, monkeypatch):
    db, client, r2, _ = env

    async def rapport_en_panne(*a, **k):
        raise RuntimeError("SMTP en panne")
    monkeypatch.setattr(mp, "envoyer_rapport", rapport_en_panne)
    r = lancer(le.executer(db, client, "sawali", le.ExecutionIn(r2_prefixes=["migration-20260815-030000"],
                                                                confirmation="LIBERER"), ADMIN, MAINTENANT))
    assert r["erreurs"] == 0 and r["rapport"]["envoye"] is False


def test_quotidiennes_analyse_et_execution(env, monkeypatch):
    """Lot 49 : sauvegardes quotidiennes dans un autre bucket ; la plus récente ne peut jamais être supprimée."""
    db, client, _r2, _ = env
    monkeypatch.setenv("R2_SAUVEGARDES_ACCOUNT_ID", "0" * 32)
    monkeypatch.setenv("R2_SAUVEGARDES_ACCESS_KEY_ID", "cle")
    monkeypatch.setenv("R2_SAUVEGARDES_SECRET_ACCESS_KEY", "secret")
    r2q = FauxR2(page=5)
    p = "sauvegardes-completes/"
    for j in range(1, 31):
        r2q.objets[f"{p}sawali-202609{j:02d}-030000.sawali"] = 100
    monkeypatch.setitem(sc._FABRIQUE_R2, "client", lambda cfg: r2q)
    a = lancer(le.analyser(db, client, "sawali", MAINTENANT))
    q = {e["cle"]: e for e in a["quotidiennes"]["elements"]}
    assert a["quotidiennes"]["disponible"] is True
    assert q[f"{p}sawali-20260930-030000.sawali"]["classe"] == "protege"
    coches = [c for c, e in q.items() if e["coche"]]
    assert coches and a["synthese"]["octets_liberes"] == 6000 + 100 * len(coches)
    with pytest.raises(HTTPException) as e:
        lancer(le.executer(db, client, "sawali", le.ExecutionIn(quotidiennes=[f"{p}sawali-20260930-030000.sawali"],
                                                                confirmation="LIBERER"), ADMIN))
    assert e.value.status_code == 409
    r = lancer(le.executer(db, client, "sawali", le.ExecutionIn(quotidiennes=coches, confirmation="LIBERER"),
                           ADMIN, MAINTENANT))
    assert r["erreurs"] == 0 and r["octets_liberes"] == 100 * len(coches)
    assert not any(c in r2q.objets for c in coches) and f"{p}sawali-20260930-030000.sawali" in r2q.objets


def test_admin_strict():
    with pytest.raises(HTTPException) as e:
        le._admin_strict({"role": "superviseur"})
    assert e.value.status_code == 403
    le._admin_strict({"role": "admin"})


def test_route_lot85_inchangee_apres_refactorisation(env):
    """La route de suppression de base du lot 85 garde son comportement (fonctions partagées du lot 113)."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import routes.quota_atlas as qa
    db, client, _r2, _ = env
    api = APIRouter(prefix="/api")
    qa.setup_quota_atlas_routes(db=db, client=client, api=api, get_current_user=lambda: ADMIN, base_courante="sawali")
    app = FastAPI()
    app.include_router(api)
    http = TestClient(app)
    assert http.post("/api/admin/atlas/bases/albarka/supprimer", json={"confirmation": "albarka"}).status_code == 409
    assert http.post("/api/admin/atlas/bases/smartsystems/supprimer", json={"confirmation": "x"}).status_code == 422
    r = http.post("/api/admin/atlas/bases/smartsystems/supprimer", json={"confirmation": "smartsystems"})
    assert r.status_code == 200 and r.json()["collections_liberees"] == 3 and r.json()["refusees"] == []
    assert lancer(db.settings.find_one({"_id": "quota_atlas"}))["purges"][-1]["base"] == "smartsystems"
