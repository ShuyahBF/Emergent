"""Lot 96 — Liluvine anime la page Facebook de beAuthentik : candidats (photo masquée + bio) demandés à la plateforme,
bio relue par l'IA, file de validation, publication sur la Page et plateforme prévenue.
Plateforme, IA et Facebook simulés ; MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot96_facebook_animation.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.facebook_animation as fa  # noqa: E402

ORIGINAL_PUBLIER = fa.publier_sur_facebook   # lot 97 : la fixture la remplace, ce test appelle l'original

# m2 d'abord : sa bio est refusée par l'IA, la préparation passe alors au candidat suivant (m1)
CANDIDATS = [
    {"membre_id": "m2", "prenom": "Ali", "age": 30, "ville": None, "bio": "appelle moi au 70 00 00 00", "photo_url": "https://x/m2.jpg"},
    {"membre_id": "m1", "prenom": "Awa", "age": 28, "ville": "Ouagadougou", "bio": "j'aime la musique", "photo_url": "https://x/m1.jpg"},
]


@pytest.fixture
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_fb"]
    appels, posts = [], []

    async def plateforme(emetteur, corps):
        appels.append(corps)
        return {"candidats": CANDIDATS} if corps["type"] == "facebook_candidats" else {"ok": True}

    async def moderer(bio):
        if "70 00" in bio:
            return {"conforme": False, "texte": "", "raison": "numéro de téléphone"}
        return {"conforme": True, "texte": "J'aime la musique.", "raison": ""}

    async def facebook(db_, texte, image_url):
        posts.append({"texte": texte, "image_url": image_url})
        return f"page_{len(posts)}"

    monkeypatch.setattr(fa, "appel_plateforme", plateforme)
    monkeypatch.setattr(fa, "moderer_bio", moderer)
    monkeypatch.setattr(fa, "publier_sur_facebook", facebook)

    async def admin(request: Request):
        return {"id": "a", "role": "admin", "email": "admin@sawali"}

    api = APIRouter(prefix="/api")
    fa.attach_facebook_animation_routes(api=api, db=db, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.liluvine_emetteurs.insert_one, {"code": "beauthentik", "secret": "s", "url_retour": "https://b/x"})
    yield client, db, appels, posts
    client.__exit__(None, None, None)


def test_preparer_moderer_valider_publier(env):
    client, db, appels, posts = env
    r = client.post("/api/admin/facebook/animation/preparer").json()
    assert r["crees"] == 2
    file_ = client.get("/api/admin/facebook/animation").json()["publications"]
    ok = next(p for p in file_ if p["membre_id"] == "m1")
    ko = next(p for p in file_ if p["membre_id"] == "m2")
    assert ok["statut"] == "a_valider" and "Awa, 28 ans, Ouagadougou" in ok["texte"] and "J'aime la musique." in ok["texte"]
    assert ko["statut"] == "refuse_ia" and ko["avis_ia"]["raison"] == "numéro de téléphone" and not ko["texte"]
    assert not posts                                         # validation manuelle par défaut : rien publié

    # Validation : publié avec la photo MASQUÉE, plateforme prévenue
    v = client.post(f"/api/admin/facebook/animation/publications/{ok['id']}/valider").json()
    assert v["statut"] == "publie" and posts[0]["image_url"] == "https://x/m1.jpg"
    assert appels[-1] == {"type": "facebook_publie", "membre_id": "m1", "post_id": "page_1"}
    # Une bio refusée par l'IA ne peut pas être publiée
    assert client.post(f"/api/admin/facebook/animation/publications/{ko['id']}/valider").status_code == 409
    # m2 (refusé) n'est pas reproposé à la préparation suivante
    r2 = client.post("/api/admin/facebook/animation/preparer").json()
    assert [p["membre_id"] for p in r2["publications"]] == ["m1"]


def test_publication_directe_sans_validation(env):
    client, db, _, posts = env
    client.put("/api/admin/facebook/animation/reglages", json={"validation_manuelle": False})
    client.post("/api/admin/facebook/animation/preparer")
    assert len(posts) == 1


def test_avis_et_legende_et_planning():
    assert fa.lire_avis('Voici : {"conforme": true, "texte": "Bonjour", "raison": ""}')["conforme"] is True
    assert fa.lire_avis("pas de json")["conforme"] is False
    assert fa.legende("{prenom}{age_txt}{ville_txt} — {bio} {lien}", {"prenom": "Awa", "age": None, "ville": None},
                      "Salut", "https://b") == "Awa — Salut https://b"
    regl = {**fa.REGLAGES_DEFAUT, "actif": True, "jours": [3], "heure": "10:00"}
    jeudi_11h = datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc)      # jeudi = 3
    assert fa.doit_preparer(regl, jeudi_11h)
    assert not fa.doit_preparer({**regl, "dernier_jour": "2026-10-08"}, jeudi_11h)
    assert not fa.doit_preparer(regl, jeudi_11h.replace(hour=9))
    assert not fa.doit_preparer({**regl, "actif": False}, jeudi_11h)


def test_page_propre_a_l_animation(env, monkeypatch):
    """Lot 97 — la page de l'animation (ex. beAuthentik) est distincte de la page active de SAWALI ;
    son jeton reste côté serveur et sert à la publication."""
    client, db, _, _ = env
    import routes.facebook as fb

    async def pages(db_):
        return [{"id": "p_beauth", "nom": "beAuthentik", "jeton": "jeton-beauth"},
                {"id": "p_sawali", "nom": "SAWALI", "jeton": "jeton-sawali"}]

    vus = []

    async def poster(page_id, jeton, texte, image):
        vus.append((page_id, jeton))
        return {"post_id": "123"}

    monkeypatch.setattr(fa, "pages_du_compte", pages)
    monkeypatch.setattr(fb, "_post_to_page", poster)
    client.portal.call(lambda: db.settings.update_one({"_id": "global"}, {"$set": {
        "facebook_page_id": "p_sawali", "facebook_page_access_token": "jeton-sawali", "facebook_page_name": "SAWALI"}},
        upsert=True))

    liste = client.get("/api/admin/facebook/animation/pages").json()["pages"]
    assert liste == [{"id": "p_beauth", "nom": "beAuthentik"}, {"id": "p_sawali", "nom": "SAWALI"}]   # jamais de jeton
    assert client.put("/api/admin/facebook/animation/page", json={"page_id": "p_beauth"}).status_code == 200
    assert client.get("/api/admin/facebook/animation").json()["page"] == {"connectee": True, "nom": "beAuthentik", "propre": True}

    # La vraie fonction de publication (remplacée par la fixture) utilise la page de l'animation
    monkeypatch.setattr(fa, "publier_sur_facebook", ORIGINAL_PUBLIER)
    assert client.portal.call(lambda: fa.publier_sur_facebook(db, "Bonjour", "https://x/m.jpg")) == "123"
    assert vus[-1] == ("p_beauth", "jeton-beauth")
    # Retour à la page active de SAWALI
    client.put("/api/admin/facebook/animation/page", json={"page_id": ""})
    assert client.portal.call(lambda: fa.publier_sur_facebook(db, "Bonjour", "https://x/m.jpg")) == "123"
    assert vus[-1] == ("p_sawali", "jeton-sawali")
