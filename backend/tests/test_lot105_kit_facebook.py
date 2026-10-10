"""Lot 105 — Kit de lancement de la Page Facebook beAuthentik : visuels servis publiquement (liste blanche),
textes « À propos », 8 publications chargées dans la file (une seule fois) et publiées uniquement sur la Page
propre de la plateforme, sans prévenir la plateforme (aucun membre concerné).
Facebook et MongoDB simulés.
Lancer : cd backend && python -m pytest tests/test_lot105_kit_facebook.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.facebook_animation as fa  # noqa: E402
import routes.facebook_kit as kit  # noqa: E402


@pytest.fixture
def env(monkeypatch):
    # --- base simulée, Facebook et plateforme imités ---
    db = mongomock_motor.AsyncMongoMockClient()["sawali_kit"]
    posts, appels = [], []

    async def facebook(db_, texte, image_url):
        posts.append(image_url)
        return f"post_{len(posts)}"

    async def plateforme(emetteur, corps):
        appels.append(corps)
        return {"ok": True}

    monkeypatch.setattr(fa, "publier_sur_facebook", facebook)
    monkeypatch.setattr(fa, "appel_plateforme", plateforme)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.exemple.test")

    async def admin(request: Request):
        return {"id": "a", "role": "admin", "email": "admin@sawali"}

    api = APIRouter(prefix="/api")
    fa.attach_facebook_animation_routes(api=api, db=db, get_current_admin=admin)
    kit.attach_facebook_kit_routes(api=api, db=db, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.liluvine_emetteurs.insert_one, {"code": "beauthentik", "secret": "s", "url_retour": "https://b/x"})
    yield client, db, posts, appels
    client.__exit__(None, None, None)


def test_visuels_publics_en_liste_blanche(env):
    client, _, _, _ = env
    for f in ["photo-profil.jpg", "couverture.jpg"] + [f"publication-{i}.jpg" for i in range(1, 9)]:
        r = client.get(f"/api/facebook/kit/beauthentik/{f}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and len(r.content) > 10_000
    # Aucun autre fichier du serveur n'est accessible
    assert client.get("/api/facebook/kit/beauthentik/..%2F..%2Flot.py").status_code == 404
    assert client.get("/api/facebook/kit/autre/couverture.jpg").status_code == 404


def test_textes_a_propos():
    assert len(kit.A_PROPOS["presentation"]) <= 101       # limite de Facebook
    assert len(kit.PUBLICATIONS) == 8
    assert all("https://beauthentik.net" in p["texte"] for p in kit.PUBLICATIONS)


def test_charger_puis_publier_sur_la_page_propre(env):
    client, db, posts, appels = env
    # Sans page propre : refus clair (jamais sur la page de SAWALI)
    r = client.post("/api/admin/facebook/animation/kit/charger")
    assert r.status_code == 400 and "Page de la plateforme" in r.json()["detail"]

    client.portal.call(lambda: db.settings.update_one({"_id": "global"}, {"$set": {
        "fb_animation_page": {"id": "p_beauth", "nom": "beAuthentik", "jeton": "j"}}}, upsert=True))
    assert client.post("/api/admin/facebook/animation/kit/charger").json() == {"crees": 8, "total": 8}
    assert client.post("/api/admin/facebook/animation/kit/charger").json()["crees"] == 0   # jamais en double

    etat = client.get("/api/admin/facebook/animation/kit").json()
    assert etat["charges"] == 8 and etat["publies"] == 0
    assert etat["couverture"] == "https://api.exemple.test/api/facebook/kit/beauthentik/couverture.jpg"

    # La file affiche le kit dans l'ordre 1 → 8
    pubs = client.get("/api/admin/facebook/animation").json()["publications"]
    assert [p["rang"] for p in pubs] == list(range(1, 9))

    r = client.post(f"/api/admin/facebook/animation/publications/{pubs[0]['id']}/valider").json()
    assert r["statut"] == "publie" and posts[-1].endswith("/publication-1.jpg")
    assert appels == []   # la plateforme n'est pas prévenue pour une publication de kit

    # Page propre retirée : la publication suivante échoue au lieu de partir sur la page de SAWALI
    client.portal.call(lambda: db.settings.update_one({"_id": "global"}, {"$unset": {"fb_animation_page": ""}}))
    r = client.post(f"/api/admin/facebook/animation/publications/{pubs[1]['id']}/valider").json()
    assert r["statut"] == "echec" and len(posts) == 1
