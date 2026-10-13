"""Lot 137 — Enrôlement d'une école e-Kol en un geste (clé + école du portail + suivi).
Vérifie : checklist (fonction pure), création de la clé (montrée une fois), appel signé vers le portail (simulé),
portail injoignable → école quand même enrôlée + message, réessai, accès réservé à l'administrateur.
Lancer : cd backend && python -m pytest tests/test_ekol_enrolement.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.ekol_enrolement as enr  # noqa: E402
import routes.loois_cles_clients as cles  # noqa: E402

UTILISATEURS = {"admin": {"id": "a", "role": "admin", "full_name": "Admin"}, "autre": {"id": "b", "role": "pharmacien"}}


def test_etapes_et_prochaine_action():
    """Sans rien : la 1re étape manquante est « clé » ; tout fait → None."""
    liste = enr.etapes("X", None, None, 0, None)
    assert not liste[0]["fait"] and "clé" in enr.prochaine_action(liste).lower()
    cle = {"actif": True, "derniere_utilisation": "2026-10-13"}
    portail = (True, {"enregistree": True, "lignes": 42})
    complet = enr.etapes("X", cle, "2026-10-13", 5, portail)
    assert all(e["fait"] for e in complet) and enr.prochaine_action(complet) is None


@pytest.fixture()
def client(monkeypatch):
    """Application minimale + faux portail qui vérifie la signature et mémorise les appels."""
    monkeypatch.setenv("EKOL_PORTAIL_HMAC", "secret-test")
    monkeypatch.delenv("LOOIS_CLES_PEPPER", raising=False)
    appels = []

    def faux(request: httpx.Request) -> httpx.Response:
        corps = request.content
        attendu = enr.signer("secret-test", request.headers["X-Timestamp"], corps)
        assert request.headers["X-Signature"] == attendu
        appels.append((request.url.path, json.loads(corps)))
        if request.url.path.endswith("/etat"):
            return httpx.Response(200, json={"enregistree": True, "lignes": 0})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(enr, "_transport", httpx.MockTransport(faux))
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    api = APIRouter(prefix="/api")

    async def user(request: Request):
        u = UTILISATEURS.get(request.headers.get("X-User", "admin"))
        if not u:
            raise HTTPException(status_code=401)
        return u

    enr.setup_ekol_enrolement_routes(db=db, api=api, get_current_user=user)
    app = FastAPI()
    app.include_router(api)
    yield TestClient(app), db, appels, monkeypatch
    cles.ETAT["clients_actifs"] = False


def test_enrolement_cree_cle_et_ecole(client):
    c, db, appels, _ = client
    r = c.post("/api/admin/ekol-enrolement", json={"code": "Lycée Test", "nom": "Lycée Test", "ville": "Ouaga"})
    assert r.status_code == 200
    j = r.json()
    assert j["code"] == "LYCEE-TEST" and j["cle"].startswith("LK-") and j["portail"]["ok"]
    assert appels[0][0] == "/api/import-ekol/ecole" and appels[0][1]["site"] == "LYCEE-TEST"
    # 2e passage : la clé n'est ni recréée ni réaffichée
    j2 = c.post("/api/admin/ekol-enrolement", json={"code": "LYCEE-TEST", "nom": "Lycée Test"}).json()
    assert j2["cle"] is None and j2["cle_deja_existante"]
    suivi = c.get("/api/admin/ekol-enrolement").json()
    assert suivi["ecoles"][0]["code"] == "LYCEE-TEST" and suivi["ecoles"][0]["etapes"][0]["fait"]


def test_portail_injoignable_puis_reessai(client):
    c, db, appels, mp = client

    def panne(request):
        raise httpx.ConnectError("hors ligne")

    mp.setattr(enr, "_transport", httpx.MockTransport(panne))
    j = c.post("/api/admin/ekol-enrolement", json={"code": "ECOLE-B", "nom": "École B"}).json()
    assert j["cle"] and not j["portail"]["ok"] and "injoignable" in j["portail"]["message"]
    mp.setattr(enr, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))
    assert c.post("/api/admin/ekol-enrolement/ECOLE-B/portail").json()["ok"]


def test_reserve_admin_et_validation(client):
    c, *_ = client
    assert c.post("/api/admin/ekol-enrolement", json={"code": "Z", "nom": "Z"}, headers={"X-User": "autre"}).status_code == 403
    assert c.post("/api/admin/ekol-enrolement", json={"code": "A", "nom": "x"}).status_code == 422
