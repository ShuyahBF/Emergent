"""Lot 69.1 — la page Qdrant ne doit plus bloquer le serveur : lecture des collections hors de la boucle
principale, comptages en parallèle, résultat gardé 60 s."""
import asyncio
import time

import pytest

import routes.qdrant_rag as q


class _Coll:
    def __init__(self, name):
        self.name = name


class _FauxClient:
    """Client Qdrant simulé : chaque appel prend 0,2 s (comme un aller-retour réseau bloquant)."""
    def __init__(self, n=10):
        self.n = n
        self.appels = 0

    def get_collections(self):
        self.appels += 1
        time.sleep(0.2)
        return type("R", (), {"collections": [_Coll(f"c{i}") for i in range(self.n)]})()

    def count(self, nom, exact=False):
        self.appels += 1
        time.sleep(0.2)
        return type("C", (), {"count": 7})()


class _FauxDb:
    """Base simulée : paramètres Qdrant renseignés."""
    class settings:
        @staticmethod
        async def find_one(*_a, **_k):
            return {"qdrant_url": "https://exemple", "qdrant_api_key": "cle-test"}


@pytest.fixture(autouse=True)
def _client(monkeypatch):
    client = _FauxClient()
    monkeypatch.setattr(q, "_make_client", lambda url, key: client)
    q._vider_cache_liste()
    return client


@pytest.mark.asyncio
async def test_la_boucle_principale_reste_libre(_client):
    # Un « battement » toutes les 50 ms doit continuer pendant la lecture (avant : boucle figée 6 à 10 s)
    battements = 0
    fini = False

    async def coeur():
        nonlocal battements
        while not fini:
            battements += 1
            await asyncio.sleep(0.05)

    tache = asyncio.create_task(coeur())
    debut = time.monotonic()
    liste = await q.list_collections(_FauxDb())
    duree = time.monotonic() - debut
    fini = True
    await tache
    assert len(liste) == 10 and all(c["vectors_count"] == 7 for c in liste)
    assert battements >= int(duree / 0.05) - 2      # la boucle a continué de tourner
    assert duree < 1.5                               # 10 comptages en parallèle (pas 10 × 0,2 s à la suite)


@pytest.mark.asyncio
async def test_cache_partage_entre_liste_stockage_et_test(_client):
    # Les trois appels de la page n'interrogent Qdrant qu'une seule fois
    await q.list_collections(_FauxDb())
    appels = _client.appels
    stockage = await q.get_storage_info(_FauxDb())
    test = await q.test_connection(_FauxDb())
    assert _client.appels == appels
    assert stockage["total_points"] == 70 and stockage["collections"] == 10
    assert test["ok"] and test["collections"] == 10


@pytest.mark.asyncio
async def test_cache_vide_relit_qdrant(_client):
    # Après une modification (création, suppression, ajout), la lecture suivante repart de Qdrant
    await q.list_collections(_FauxDb())
    appels = _client.appels
    q._vider_cache_liste()
    await q.list_collections(_FauxDb())
    assert _client.appels > appels
