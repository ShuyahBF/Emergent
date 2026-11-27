"""Lot 474 — le VRAI serveur : objets du stockage externe gardés en mémoire, noms utilisés au démarrage présents."""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_lot474")
os.environ.setdefault("JWT_SECRET", "x")


@pytest.fixture(scope="module")
def serveur():
    boucle = asyncio.new_event_loop()
    asyncio.set_event_loop(boucle)

    async def charger():
        import server
        return server
    return boucle.run_until_complete(charger())


def test_noms_utilises_au_demarrage_et_caches_presents(serveur):
    for nom in ("_roadmap_synchroniser", "_ROADMAP_VERROU", "_CACHE_OBJETS", "proxy_file_download", "logger", "asyncio"):
        assert hasattr(serveur, nom), nom
    import performance_serveur as ps
    assert callable(ps.demarrer_surveillance_boucle) and ps.RETARD.resume()["mesures"] >= 0


def test_un_objet_du_stockage_externe_n_est_telecharge_qu_une_fois(serveur, monkeypatch):
    import mongomock_motor
    from fastapi.testclient import TestClient
    from cache_court import CacheOctets

    monkeypatch.setattr(serveur, "db", mongomock_motor.AsyncMongoMockClient()["test_lot474"])
    monkeypatch.setattr(serveur, "_CACHE_OBJETS", CacheOctets(duree_s=600, max_total=1024, max_objet=512))
    appels = {"n": 0}

    async def faux_get_object(chemin):
        appels["n"] += 1
        return b"\x89PNG-contenu", "image/png"
    monkeypatch.setattr(serveur._obj_storage, "get_object", faux_get_object)
    c = TestClient(serveur.app)
    r1 = c.get("/api/files/bannieres/pub.png")
    r2 = c.get("/api/files/bannieres/pub.png")
    assert r1.status_code == 200 and r2.status_code == 200 and r1.content == r2.content == b"\x89PNG-contenu"
    assert appels["n"] == 1                                              # le 2e affichage ne retélécharge rien
    assert r2.headers["cache-control"] == "public, max-age=3600" and r2.headers["content-type"] == "image/png"
    c.get("/api/files/bannieres/autre.png")
    assert appels["n"] == 2                                              # un autre objet est téléchargé normalement
