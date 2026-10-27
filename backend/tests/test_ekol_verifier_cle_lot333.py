"""Lot 333 — POST /api/ekol-portail/verifier-cle : le portail e-Kol fait vérifier par SAWALI la clé client Loois (« LK-… »).
Signature sur l'empreinte du corps, clé inconnue / révoquée / commune refusées (valide=false), clé client reconnue avec son code,
son libellé et ses applications. MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_ekol_verifier_cle_lot333.py -q"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.ekol_portail_export as ex  # noqa: E402
import routes.loois_cles_clients as cles  # noqa: E402

HMAC = "cle-portail-test"
CHEMIN = "/api/ekol-portail/verifier-cle"


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("EKOL_PORTAIL_HMAC", HMAC)
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-commune")
    monkeypatch.delenv("LOOIS_CLES_PEPPER", raising=False)
    yield
    cles.ETAT["clients_actifs"] = False


def application(db):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    api = APIRouter(prefix="/api")
    ex.setup_ekol_portail_export_routes(db=db, api=api, get_current_user=lambda: {"id": "u", "role": "admin"})
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def appel(c, cle_loois, cle_hmac=HMAC, decalage=0, corps=None):
    """POST signé comme le portail : HMAC(clé, « <ts>.POST <chemin>?sha256=<empreinte du corps> »)."""
    brut = corps if corps is not None else json.dumps({"cle": cle_loois}).encode()
    ts = str(int(time.time()) + decalage)
    sig = ex.calculer_signature(cle_hmac, ts, "POST", CHEMIN, ex.requete_du_corps(brut))
    return c.post(CHEMIN, content=brut, headers={"X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"})


def creer_client(db, code="LYCEE-PRIVE-X", applications=("eKol",)):
    propre = cles.nettoyer_fiche({"code": code, "libelle": "Lycée Privé X", "applications": list(applications)}, creation=True)
    return lancer(cles.creer_fiche_cle(db, propre, "test"))


def test_cle_client_reconnue_avec_son_code_et_ses_applications(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_test"]
    cle, _ = creer_client(db, applications=("eKol", "Biolog"))
    r = appel(application(db), cle)
    assert r.status_code == 200
    assert r.json() == {"valide": True, "code": "LYCEE-PRIVE-X", "libelle": "Lycée Privé X", "applications": ["eKol", "Biolog"]}


def test_cle_inconnue_commune_ou_revoquee_est_refusee_sans_detail(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_test"]
    c = application(db)
    cle, fiche = creer_client(db)
    assert appel(c, "LK-inconnue").json() == {"valide": False}
    assert appel(c, "cle-commune").json() == {"valide": False}          # la clé commune n'identifie aucun client
    lancer(db.loois_cles_clients.update_one({"id": fiche["id"]}, {"$set": {"actif": False}}))
    assert appel(c, cle).json() == {"valide": False}                    # révoquée : refusée aussitôt


def test_signature_obligatoire_et_liee_au_corps(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_test"]
    c = application(db)
    cle, _ = creer_client(db)
    assert appel(c, cle, cle_hmac="autre-cle").status_code == 401
    assert appel(c, cle, decalage=-900).status_code == 401              # périmée (plus de 5 minutes)
    assert c.post(CHEMIN, json={"cle": cle}).status_code == 401         # sans signature
    # Signature d'un AUTRE corps rejouée avec la clé à tester : refusée
    ts = str(int(time.time()))
    sig = ex.calculer_signature(HMAC, ts, "POST", CHEMIN, ex.requete_du_corps(b'{"cle": "autre"}'))
    r = c.post(CHEMIN, content=json.dumps({"cle": cle}).encode(), headers={"X-Timestamp": ts, "X-Signature": sig})
    assert r.status_code == 401


def test_route_desactivee_sans_cle_partagee(monkeypatch):
    monkeypatch.delenv("EKOL_PORTAIL_HMAC", raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_test"]
    assert application(db).post(CHEMIN, json={"cle": "LK-x"}).status_code == 503
