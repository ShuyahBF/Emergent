"""Lot 192 — publier un carrousel sur une Page Facebook choisie : images remplaçables, légende, publication à plusieurs photos
ou lien, trace sur l'envoi. Graph API simulée, MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot192_carrousel_facebook.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.carrousel_facebook as cf  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


CARTES = [
    {"titre": "Paracétamol", "texte": "Boîte de 20", "image_url": "https://x.test/a.jpg"},
    {"titre": "Vitamine C", "texte": "", "image_url": "/api/files/b.jpg"},          # adresse relative : inutilisable par Facebook
    {"titre": "", "texte": "Sirop", "image_url": "https://x.test/c.png"},
]


def test_images_retenues_remplacement_par_position():
    assert cf.images_retenues(CARTES, None) == ["https://x.test/a.jpg", "https://x.test/c.png"]      # carte sans image publique ignorée
    r = cf.images_retenues(CARTES, [None, "https://y.test/new.jpg", "n'importe quoi"])
    assert r == ["https://x.test/a.jpg", "https://y.test/new.jpg", "https://x.test/c.png"]           # remplacement valide uniquement
    assert len(cf.images_retenues([{"image_url": "https://x.test/i.jpg"}] * 14, None)) == cf.MAX_PHOTOS


def test_legende_de_la_publication():
    t = cf.texte_publication("Nouveautés", CARTES, "https://s.test/p/abc", True)
    assert t.startswith("Nouveautés") and "1. Paracétamol — Boîte de 20" in t and "2. Vitamine C" in t and "3. Sirop" in t
    assert t.endswith("👉 Tout voir : https://s.test/p/abc")
    assert cf.texte_publication("Salut", CARTES, "https://s.test/p/abc", False) == "Salut\n\n👉 Tout voir : https://s.test/p/abc"
    assert cf.texte_publication("", [], "", True) == ""


@pytest.fixture()
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["t192"]
    lancer(db.carrousel_campagnes.insert_one({"id": "camp1", "cartes": CARTES, "message": "Bonjour", "id_public": "pub1"}))
    appels = []

    async def faux_graph(chemin, donnees):
        appels.append((chemin, dict(donnees)))
        return {"id": f"id-{len(appels)}"}

    async def fausse_page(_db, page_id):
        if page_id != "P1":
            raise HTTPException(status_code=404, detail="Cette Page n'est pas gérée par le compte Facebook connecté")
        return {"id": "P1", "nom": "Page beAuthentik", "jeton": "JETON_SECRET"}

    monkeypatch.setattr(cf, "_graph_post", faux_graph)
    monkeypatch.setattr(cf, "_page_choisie", fausse_page)
    return db, appels


def test_publication_photos_sur_la_page_choisie(env):
    db, appels = env
    c = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))
    res = lancer(cf.publier(db, c, "P1", "Bonjour", "photos", [None, "https://y.test/new.jpg", None], "https://s.test/p/pub1", "admin@x"))
    photos = [a for a in appels if a[0] == "P1/photos"]
    assert len(photos) == 3 and photos[1][1]["url"] == "https://y.test/new.jpg" and photos[0][1]["published"] == "false"
    feed = [a for a in appels if a[0] == "P1/feed"][0][1]
    assert "attached_media[0]" in feed and "attached_media[2]" in feed and "1. Paracétamol" in feed["message"]
    assert res["page_nom"] == "Page beAuthentik" and res["nb_images"] == 3 and res["url"].startswith("https://www.facebook.com/")
    trace = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))["publications_facebook"]
    assert len(trace) == 1 and trace[0]["page_id"] == "P1" and "jeton" not in str(trace[0]).lower()    # jamais de jeton sur l'envoi


def test_publication_lien_et_refus(env):
    db, appels = env
    c = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))
    lancer(cf.publier(db, c, "P1", "Bonjour", "lien", None, "https://s.test/p/pub1", "admin"))
    assert appels[-1][0] == "P1/feed" and appels[-1][1]["link"] == "https://s.test/p/pub1" and "attached_media[0]" not in appels[-1][1]
    for args, code in [(("P2", "x", "photos", None, "", "a"), 404), (("P1", "x", "autre", None, "", "a"), 422),
                       (("P1", "x", "lien", None, "", "a"), 422), (("P1", "x", "photos", None, "ftp://nope", "a"), 422)]:
        with pytest.raises(HTTPException) as e:
            lancer(cf.publier(db, c, *args))
        assert e.value.status_code == code
    sans_image = {"id": "camp1", "cartes": [{"titre": "A", "image_url": "/api/x.jpg"}]}
    with pytest.raises(HTTPException) as e:
        lancer(cf.publier(db, sans_image, "P1", "x", "photos", None, "", "a"))
    assert e.value.status_code == 422
