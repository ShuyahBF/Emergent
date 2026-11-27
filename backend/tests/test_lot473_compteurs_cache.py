"""Lot 473 — compteurs de la barre latérale : le VRAI serveur, une base simulée.

Vérifie que les compteurs de modules sont gardés (une 2e lecture ne retourne pas à la base), que « marquer comme vu » les invalide tout de suite, que le non-lu
WhatsApp reste recalculé à chaque appel, et que chaque utilisateur a ses propres compteurs."""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_lot473")
os.environ.setdefault("JWT_SECRET", "x")


@pytest.fixture(scope="module")
def serveur():
    """Importe le vrai serveur DANS une boucle d'événements (comme uvicorn) : certains modules y lancent des tâches au chargement."""
    boucle = asyncio.new_event_loop()
    asyncio.set_event_loop(boucle)

    async def charger():
        import server
        return server
    return boucle.run_until_complete(charger())


@pytest.fixture
def client(serveur, monkeypatch):
    import mongomock_motor
    from fastapi.testclient import TestClient
    import cache_court

    class Horloge:
        t = 1000.0
        def __call__(self): return self.t

    horloge = Horloge()
    reelle = mongomock_motor.AsyncMongoMockClient()["test_lot473"]
    lectures = {"visites": 0, "wa": 0}

    class CollectionEspionne:
        """Compte les lectures de la collection des visites (celle que lit la route des compteurs à chaque calcul)."""
        def __init__(self, vraie): self._vraie = vraie
        def find(self, *a, **k):
            lectures["visites"] += 1
            return self._vraie.find(*a, **k)
        def __getattr__(self, nom): return getattr(self._vraie, nom)

    class BaseEspionne:
        """Remplace la base : tout passe à la base simulée, sauf que les lectures des visites sont comptées."""
        def __getattr__(self, nom):
            coll = getattr(reelle, nom)
            return CollectionEspionne(coll) if nom == "user_module_visits" else coll
        def __getitem__(self, nom): return reelle[nom]

    monkeypatch.setattr(serveur, "db", BaseEspionne())
    monkeypatch.setattr(serveur, "_CACHE_COMPTEURS", cache_court.CacheCourt(duree_s=45, horloge=horloge))
    monkeypatch.setattr(serveur, "_CACHE_RESUME_WA", cache_court.CacheCourt(duree_s=5, horloge=horloge))
    utilisateur = {"id": "u1", "email": "a@test", "role": "admin"}
    serveur.app.dependency_overrides[serveur.get_current_user] = lambda: dict(utilisateur)

    vrai_index = serveur._wa_visible_contact_index                 # appelé UNE fois par calcul réel du résumé WhatsApp
    async def index_espion(user):
        lectures["wa"] += 1
        return await vrai_index(user)
    monkeypatch.setattr(serveur, "_wa_visible_contact_index", index_espion)
    c = TestClient(serveur.app)
    yield c, lectures, horloge, utilisateur
    serveur.app.dependency_overrides.pop(serveur.get_current_user, None)


def _compteurs(c):
    r = c.get("/api/me/notifications/counts")
    assert r.status_code == 200, r.text
    return r.json()["counts"]


def test_les_compteurs_de_modules_sont_gardes_mais_pas_le_non_lu_whatsapp(client):
    c, lectures, horloge, _ = client
    premier = _compteurs(c)
    assert lectures["visites"] == 1 and "contacts_unread" in premier and "appointments" in premier
    horloge.t += 10                                             # 10 s plus tard : compteurs de modules encore frais, mais le résumé WhatsApp (5 s) a expiré
    deuxieme = _compteurs(c)
    assert lectures["visites"] == 1                             # AUCUNE nouvelle lecture des visites : servi par le cache
    assert lectures["wa"] == 2                                  # le non-lu WhatsApp, lui, a été recalculé
    assert {k: v for k, v in deuxieme.items() if k != "contacts_unread"} == {k: v for k, v in premier.items() if k != "contacts_unread"}


def test_apres_45_secondes_tout_est_relu(client):
    c, lectures, horloge, _ = client
    _compteurs(c); horloge.t += 46; _compteurs(c)
    assert lectures["visites"] == 2


def test_marquer_comme_vu_invalide_aussitot_les_compteurs_de_cet_utilisateur(client):
    c, lectures, horloge, _ = client
    _compteurs(c)
    assert c.post("/api/me/notifications/mark-seen", json={"module": "appointments"}).status_code == 200
    _compteurs(c)
    assert lectures["visites"] == 2                             # relus tout de suite : le badge de ce module tombe à zéro sans attendre 45 s


def test_chaque_utilisateur_a_ses_propres_compteurs(client, serveur):
    c, lectures, horloge, utilisateur = client
    _compteurs(c)
    serveur.app.dependency_overrides[serveur.get_current_user] = lambda: {"id": "u2", "email": "b@test", "role": "admin"}
    _compteurs(c)
    assert lectures["visites"] == 2                             # u2 n'est pas servi avec le cache de u1


def test_le_resume_whatsapp_est_garde_5_secondes(client):
    c, lectures, horloge, _ = client
    assert c.get("/api/me/whatsapp/unread").status_code == 200
    assert c.get("/api/me/whatsapp/unread").status_code == 200
    assert lectures["wa"] == 1                                  # deux appels, un seul calcul
    horloge.t += 5.1
    c.get("/api/me/whatsapp/unread")
    assert lectures["wa"] == 2
