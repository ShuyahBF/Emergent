"""Lot 133 — sauvegarde complète en mode « R2 seulement » (sans base de secours Atlas).
La base est archivée dans R2 (une archive EJSON compressée par collection), aucune connexion Atlas n'est ouverte,
et le contrôle compare les documents archivés aux documents lus.
Lancer : cd backend && python -m pytest tests/test_sauvegarde_r2_seulement_lot133.py -q
"""
import asyncio
import gzip
import os

import pytest
from mongomock_motor import AsyncMongoMockClient

# db.py lit ces variables à l'import (aucune connexion n'est ouverte)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot133")

import routes.migration_render as mr  # noqa: E402
import routes.migration_programmation as mp  # noqa: E402


class FauxR2:
    """R2 simulé : garde en mémoire les objets envoyés."""
    def __init__(self):
        self.objets = {}

    def upload_fileobj(self, Fileobj, Bucket, Key, **_):  # noqa: N803
        self.objets[Key] = Fileobj.read()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def base(monkeypatch):
    b = AsyncMongoMockClient()["test_lot133"]
    monkeypatch.setattr(mr, "db", b)
    _run(b.clients.insert_many([{"_id": i, "nom": f"Client {i}"} for i in range(5)]))
    _run(b.migration_jobs.insert_one({"id": "j1", "statut": "EN_COURS", "resultats_collections": []}))
    return b


def _cible(**champs):
    valeurs = dict(mongo_uri="", mongo_db="sawali", r2_account_id="abcd", r2_access_key_id="abcd",
                   r2_secret_access_key="abcd", r2_bucket="seau", copier_base=True)
    valeurs.update(champs)
    return mr.Cible(**valeurs)


def test_archive_r2_sans_atlas(base):
    r2 = FauxR2()
    manifeste = {"collections": []}
    anomalies = _run(mr._copier_base("j1", _cible(), None, r2, "p", {}, manifeste))
    assert anomalies == 0
    # Une archive par collection, contenant tous les documents
    cle = next(k for k in r2.objets if k.endswith("/mongo/clients.jsonl.gz"))
    lignes = gzip.decompress(r2.objets[cle]).decode().strip().splitlines()
    assert len(lignes) == 5
    resultat = next(c for c in manifeste["collections"] if c["nom"] == "clients")
    assert resultat["ok"] and resultat["source"] == 5 and resultat["cible"] == 5 and resultat["index"] == 0


def test_programmation_acceptee_sans_uri():
    """La sauvegarde programmée n'exige plus d'URI Atlas : la base part en R2 seulement."""
    cfg = {"base": True, "fichiers": True, "medias": False}
    ids = {"r2_account_id": "abcd", "r2_access_key_id": "abcd", "r2_secret_access_key": "abcd", "r2_bucket": "seau"}
    cible = mp._cible_programmee({**mp.DEFAUT, **cfg}, ids)
    assert cible.copier_base and cible.mongo_uri == ""
