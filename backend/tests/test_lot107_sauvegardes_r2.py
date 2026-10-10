"""Lot 107 — Sauvegardes de migration dans R2 : liste (taille, fichiers, statut) et suppression à la main,
avec garde-fous (sauvegarde en cours et dernière sauvegarde réussie jamais supprimées, confirmation SUPPRIMER).
MongoDB et R2 simulés. Lancer : cd backend && python -m pytest tests/test_lot107_sauvegardes_r2.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
pytest.importorskip("cryptography")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot107")

from fastapi import HTTPException  # noqa: E402

import routes.migration_programmation as mp  # noqa: E402
import routes.migration_render as mr  # noqa: E402
from tests.test_migration_render_programmation import FauxR2  # noqa: E402

ADMIN = {"email": "admin@test", "role": "admin"}


@pytest.fixture()
def env(monkeypatch):
    base = mongomock_motor.AsyncMongoMockClient()["sawali_lot107"]
    monkeypatch.setattr(mr, "db", base)
    r2 = FauxR2(page=3)                       # petites pages : la pagination est éprouvée
    r2.ajouter("migration-20260901-030000", 5, 1000)
    r2.ajouter("migration-20260915-030000", 4, 2000)
    r2.ajouter("migration-20261001-030000", 3, 3000)
    r2.ajouter("migration-20261005-030000", 2, 10)    # en cours

    async def ids():
        return {"r2_account_id": "a", "r2_access_key_id": "b", "r2_secret_access_key": "c", "r2_bucket": "sawali-migration"}
    monkeypatch.setattr(mp, "charger_identifiants", ids)
    monkeypatch.setattr(mp, "_client_r2", lambda _ids: r2)
    jobs = [("j1", "migration-20260901-030000", "TERMINEE"), ("j2", "migration-20260915-030000", "ECHEC"),
            ("j3", "migration-20261001-030000", "TERMINEE"), ("j4", "migration-20261005-030000", "EN_COURS")]
    asyncio.run(base.migration_jobs.insert_many([{"id": i, "statut": s, "cible": {"prefixe": p, "r2_bucket": "sawali-migration"}}
                                                 for i, p, s in jobs]))
    return base, r2


def test_liste_tailles_et_protections(env):
    r = asyncio.run(mp.lister_sauvegardes(ADMIN))
    assert r["bucket"] == "sawali-migration" and r["objets_total"] == 14
    par = {x["prefixe"]: x for x in r["sauvegardes"]}
    assert par["migration-20260901-030000"]["octets"] == 5000 and par["migration-20260901-030000"]["objets"] == 5
    assert par["migration-20261001-030000"]["raison"] == "dernière sauvegarde réussie"
    assert par["migration-20261005-030000"]["raison"] == "sauvegarde en cours"
    assert not par["migration-20260901-030000"]["protegee"] and not par["migration-20260915-030000"]["protegee"]
    assert r["sauvegardes"][0]["prefixe"] == "migration-20261005-030000"     # plus récente d'abord


def test_suppression_avec_garde_fous(env):
    base, r2 = env
    corps = mp.SuppressionIn(prefixes=["migration-20260901-030000"], confirmation="")
    with pytest.raises(HTTPException) as e:
        asyncio.run(mp.supprimer_sauvegardes(corps, ADMIN))
    assert e.value.status_code == 400                                  # confirmation obligatoire
    for protege in ("migration-20261001-030000", "migration-20261005-030000"):
        with pytest.raises(HTTPException) as e:
            asyncio.run(mp.supprimer_sauvegardes(mp.SuppressionIn(prefixes=[protege], confirmation="SUPPRIMER"), ADMIN))
        assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        asyncio.run(mp.supprimer_sauvegardes(mp.SuppressionIn(prefixes=["inexistant"], confirmation="SUPPRIMER"), ADMIN))
    assert e.value.status_code == 404

    r = asyncio.run(mp.supprimer_sauvegardes(mp.SuppressionIn(
        prefixes=["migration-20260901-030000", "migration-20260915-030000"], confirmation="supprimer"), ADMIN))
    assert r["octets"] == 13000 and r["erreurs"] == 0
    assert not any(k.startswith(("migration-20260901", "migration-20260915")) for k in r2.objets)
    assert any(k.startswith("migration-20261001") for k in r2.objets)     # les autres restent
    j1 = asyncio.run(base.migration_jobs.find_one({"id": "j1"}))
    assert j1["purgee"] is True and j1["purge"]["manuelle"] is True and j1["purge"]["par"] == "admin@test"


def test_sans_identifiants(monkeypatch, env):
    async def aucun():
        raise RuntimeError("Aucun identifiant enregistré pour les sauvegardes programmées")
    monkeypatch.setattr(mp, "charger_identifiants", aucun)
    with pytest.raises(HTTPException) as e:
        asyncio.run(mp.lister_sauvegardes(ADMIN))
    assert e.value.status_code == 400 and "Sauvegardes programmées" in e.value.detail
