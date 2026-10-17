"""Lot 237 — résumés de presse : requête signée, résumés limités aux liens envoyés, plafond quotidien. IA simulée."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "sawali_test_lot237")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.formules_plateformes as fp  # noqa: E402
import routes.presse_plateformes as pp  # noqa: E402

CLE = "cle-de-test"
ARTICLES = [{"lien": "https://j.test/a", "titre": "Un titre d'article", "texte": "Texte de l'article."},
            {"lien": "https://j.test/b", "titre": "Un autre titre", "texte": ""}]


def appel(c, corps):
    brut = json.dumps(corps, ensure_ascii=False)
    ts = str(int(time.time()))
    h = {"Content-Type": "application/json", "X-Emetteur": "paiementmobile", "X-Timestamp": ts,
         "X-Signature": hmac.new(CLE.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()}
    return c.post("/api/presse-plateformes/resumer", content=brut, headers=h)


@pytest.fixture()
def env():
    db = mongomock_motor.AsyncMongoMockClient()["test"]

    async def faux(media, articles):
        # Réponse de l'IA : un résumé valide, un lien inventé (à écarter), un résumé trop court (à écarter)
        return '```json\n' + json.dumps([{"lien": articles[0].lien, "resume": "Résumé fidèle de l'article en deux phrases courtes."},
                                        {"lien": "https://inconnu.test/x", "resume": "Résumé d'un article jamais envoyé, à ignorer."},
                                        {"lien": articles[1].lien, "resume": "Court"}]) + '\n```'

    pp._resumer = faux
    api = APIRouter(prefix="/api")
    formules = fp.make_formules_plateformes(db=db, get_super_admin=lambda: {}, hooks_apres_paiement=[],
                                            pawapay={"jeton": lambda s: None, "hotes": {"sandbox": ""}, "devise": lambda p: "XOF"})
    api.include_router(pp.make_presse_plateformes(db=db, outils=formules.outils))
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app).__enter__()
    c.portal.call(db.liluvine_emetteurs.insert_one, {"code": "paiementmobile", "nom": "PM", "secret": CLE, "actif": True})
    c.db = db
    yield c
    pp._resumer = None


def test_resumes_filtres(env):
    r = appel(env, {"media": "Le Journal", "articles": ARTICLES})
    assert r.status_code == 200
    assert r.json()["resumes"] == [{"lien": "https://j.test/a", "resume": "Résumé fidèle de l'article en deux phrases courtes."}]


def test_signature_obligatoire(env):
    assert env.post("/api/presse-plateformes/resumer", json={"media": "X", "articles": ARTICLES}).status_code == 401


def test_corps_invalide_et_plafond(env):
    assert appel(env, {"media": "X", "articles": []}).status_code == 422
    env.portal.call(env.db.presse_appels.insert_one, {"plateforme": "paiementmobile", "jour": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat(), "n": pp.APPELS_PAR_JOUR})
    assert appel(env, {"media": "Média", "articles": ARTICLES}).status_code == 429
