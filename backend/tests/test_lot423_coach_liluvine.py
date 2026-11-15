"""Lot 423 — Liluvine, ma coach : essais gratuits, abonnement, plafond par jour, détresse (réponse fixe, sans IA), rien n'est conservé. IA simulée."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "sawali_test_lot423")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.coach_plateformes as cp  # noqa: E402
import routes.formules_plateformes as fp  # noqa: E402

CLE = "cle-de-test"
UTIL = {"id": "u1", "nom": "Awa Badini", "telephone": "+22670000000"}
APPELS: list = []


async def faux_ia(systeme, historique):
    APPELS.append((systeme, historique))
    return "Je comprends que cette journée a été longue. Qu'est-ce qui vous ferait du bien ce soir ?"


def appel(c, messages, utilisateur=None, signer=True):
    brut = json.dumps({"utilisateur": utilisateur or UTIL, "messages": messages}, ensure_ascii=False)
    ts = str(int(time.time()))
    h = {"Content-Type": "application/json", "X-Emetteur": "paiementmobile", "X-Timestamp": ts,
         "X-Signature": hmac.new((CLE if signer else "autre").encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()}
    return c.post("/api/coach-plateformes/repondre", content=brut.encode("utf-8"), headers=h)


@pytest.fixture()
def env():
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    APPELS.clear()
    cp._repondre_remplace = faux_ia
    api = APIRouter(prefix="/api")
    formules = fp.make_formules_plateformes(db=db, get_super_admin=lambda: {}, hooks_apres_paiement=[],
                                            pawapay={"jeton": lambda s: None, "hotes": {"sandbox": ""}, "devise": lambda p: "XOF"})
    api.include_router(cp.make_coach_plateformes(db=db, outils=formules.outils))
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app).__enter__()
    c.portal.call(db.liluvine_emetteurs.insert_one, {"code": "paiementmobile", "nom": "PM", "secret": CLE, "actif": True})
    c.portal.call(db.formules_plateformes.insert_one, {"id": "f-coach", "plateforme": "paiementmobile", "nom": "Liluvine ma coach", "prix": 2000,
                                                       "duree_jours": 30, "fonctions": ["coach_liluvine"], "actif": True})
    c.db = db
    yield c
    cp._repondre_remplace = None


def abonner(c):
    fin = (fp._maintenant() + timedelta(days=10)).isoformat()
    c.portal.call(c.db.membres_plateformes.update_one, {"plateforme": "paiementmobile", "utilisateur_id": "u1"},
                  {"$set": {"abonnements": {"f-coach": {"expire_le": fin, "fonctions": ["coach_liluvine"]}}}})


MSG = [{"role": "user", "content": "Aujourd'hui j'ai eu une longue journée au marché et je suis fatiguée."}]


def test_essais_gratuits_puis_abonnement_exige(env):
    c = env
    restes = []
    for _ in range(cp.COACH_ESSAIS_DEFAUT):
        r = appel(c, MSG)
        assert r.status_code == 200 and r.json()["urgence"] is False and "journée" in r.json()["reponse"]
        restes.append(r.json()["essais_restants"])
    assert restes == [4, 3, 2, 1, 0]
    r = appel(c, MSG)
    assert r.status_code == 402 and r.json()["detail"]["formule"]["nom"] == "Liluvine ma coach" and "essai" in r.json()["detail"]["message"]
    abonner(c)
    r = appel(c, MSG)
    assert r.status_code == 200 and r.json()["essais_restants"] is None


def test_detresse_reponse_fixe_sans_ia_sans_decompte_meme_sans_abonnement(env):
    c = env
    for _ in range(cp.COACH_ESSAIS_DEFAUT):
        appel(c, MSG)                                                     # essais épuisés
    r = appel(c, [{"role": "user", "content": "Je n'en peux plus, j'ai envie de mourir"}])
    assert r.status_code == 200 and r.json()["urgence"] is True and "Votre vie compte" in r.json()["reponse"]
    assert len(APPELS) == cp.COACH_ESSAIS_DEFAUT                            # l'IA n'a pas été appelée pour ce message
    assert cp.detresse("Je veux en finir avec la vie") and cp.detresse("ME SUICIDER") and not cp.detresse("Je suis fatiguée de cette journée")


def test_plafond_par_jour_et_signature_et_validation(env):
    c = env
    abonner_apres = appel(c, MSG)
    abonner(c)
    c.portal.call(c.db.settings.update_one, {"_id": "global"}, {"$set": {"coach_plateformes_par_jour": 2}}, True)
    assert appel(c, MSG).status_code == 200
    r = appel(c, MSG)
    assert r.status_code == 429 and "reprenez demain" in r.json()["detail"]
    assert appel(c, MSG, signer=False).status_code == 401                   # signature invalide
    assert appel(c, [{"role": "assistant", "content": "Bonjour"}]).status_code == 422            # le dernier message doit être de l'utilisateur
    assert abonner_apres.status_code == 200


def test_consigne_gardes_fous_et_historique_borne(env):
    c = env
    long = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"} for i in range(30)] + [{"role": "user", "content": "x" * 5000}]
    assert appel(c, long).status_code == 200
    systeme, hist = APPELS[-1]
    assert "pas une thérapeute" in systeme and "AUCUN diagnostic" in systeme and "JAMAIS de mot de passe" in systeme and "intelligence artificielle" in systeme
    assert len(hist) <= cp.HISTORIQUE_MAX and hist[0]["role"] == "user" and hist[-1]["role"] == "user" and len(hist[-1]["content"]) == cp.MESSAGE_MAX


def test_aucun_texte_conserve_seulement_des_compteurs(env):
    c = env
    appel(c, [{"role": "user", "content": "Mon secret très personnel : je doute de mon mariage."}])
    fiche = c.portal.call(c.db.membres_plateformes.find_one, {"utilisateur_id": "u1"})
    assert fiche["coach_total"] == 1 and fiche["coach_essais"] == 1
    assert "secret" not in json.dumps(fiche, default=str) and "mariage" not in json.dumps(fiche, default=str)
