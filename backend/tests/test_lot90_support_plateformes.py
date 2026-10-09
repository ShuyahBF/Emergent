"""Lot 90 — support SAWALI des plateformes web : requêtes signées de la plateforme, espace « sTer - Support » dans
le chat interne, requête numérotée (attente → en cours → terminée), demandes en attente, activation par plateforme.
Lancer : cd backend && python -m pytest tests/test_lot90_support_plateformes.py -q
"""
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
mongomock_motor = pytest.importorskip("mongomock_motor")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "test_lot90")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.internal_chat as ic  # noqa: E402
import routes.support_plateformes as sp  # noqa: E402

ADMIN = {"id": "adm1", "role": "admin", "full_name": "Jean-François", "email": "admin@sawali.test", "account_status": "active"}
CLIENT = {"id": "cli1", "role": "client", "company": "Pharmacie X", "account_status": "active"}
SECRET = "secret-de-ster"
H_ADMIN = {"X-User": "adm1"}
UTILISATEUR = {"id": "u-42", "nom": "Awa Traoré", "role": "dentiste", "contexte": "Cabinet du Centre"}


def signe(corps: dict, code: str = "ster", secret: str = SECRET) -> tuple:
    """Corps JSON + en-têtes signés comme le fait la plateforme (HMAC-SHA256 de « <ts>.<corps> »)."""
    brut = json.dumps(corps)
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return brut, {"X-Emetteur": code, "X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-de-test")
    monkeypatch.delenv("LOOIS_SUPPORT_ADMIN_EMAIL", raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot90"]
    utilisateurs = {"adm1": ADMIN, "cli1": CLIENT}

    async def get_user(request: Request):
        u = utilisateurs.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    api.include_router(ic.make_router(db=db, get_current_user=get_user, decode_token=lambda t: {}))
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as client:
        client.portal.call(db.users.insert_many, [dict(ADMIN), dict(CLIENT)])
        client.portal.call(db.liluvine_emetteurs.insert_one,
                           {"code": "ster", "nom": "sTer", "secret": SECRET, "actif": True, "support_actif": False})
        yield client, db


def poster(c, chemin, corps, **kw):
    brut, h = signe(corps, **kw)
    return c.post(chemin, content=brut, headers=h)


def test_signature_et_activation(env):
    """Support désactivé → 403 ; mauvaise signature → 401 ; activation par l'administrateur seulement."""
    c, _ = env
    corps = {"utilisateur": UTILISATEUR, "texte": "Bonjour"}
    assert poster(c, "/api/support-plateforme/messages", corps).status_code == 403
    assert poster(c, "/api/support-plateforme/messages", corps, secret="faux").status_code == 401
    assert c.put("/api/admin/support-plateformes/ster", json={"support_actif": True}, headers={"X-User": "cli1"}).status_code == 403
    assert c.put("/api/admin/support-plateformes/ster", json={"support_actif": True}, headers=H_ADMIN).json()["support_actif"]
    assert poster(c, "/api/support-plateforme/messages", corps).status_code == 200


def test_parcours_complet(env):
    """Message → requête en attente + espace « sTer - Support » ; réponse → en cours ; fil de l'utilisateur ; Terminer."""
    c, _ = env
    c.put("/api/admin/support-plateformes/ster", json={"support_actif": True}, headers=H_ADMIN)
    r = poster(c, "/api/support-plateforme/messages", {"utilisateur": UTILISATEUR, "texte": "Ma facture ne s'imprime pas"}).json()
    assert r["requete"]["statut"] == "attente" and r["requete"]["numero"].startswith("SUP-STER-")

    # Espace visible dans la liste déroulante, juste après le Support Loois
    espaces = c.get("/api/me/chat/clients", headers=H_ADMIN).json()
    assert [e["full_name"] for e in espaces[:2]] == ["Support Loois", "sTer - Support"]
    # Demande en attente (indicateur du chat) + fil + non-lus
    attente = c.get("/api/support/en-attente", headers=H_ADMIN).json()
    assert attente["total"] == 1 and attente["elements"][0]["espace_nom"] == "sTer - Support"
    fils = c.get("/api/me/chat/support-plat-ster/threads", headers=H_ADMIN).json()
    did = fils[0]["key"]
    assert fils[0]["unread"] == 1 and "Awa Traoré — Cabinet du Centre (dentiste)" in fils[0]["label"]
    assert c.get("/api/me/chat/unread-count", headers=H_ADMIN).json()["per_client"]["support-plat-ster"] == 1

    # Réponse de l'agent → requête « en cours », plus en attente
    rep = c.post("/api/me/chat/support-plat-ster/messages", json={"text": "Je regarde", "recipient_id": did}, headers=H_ADMIN)
    assert rep.status_code == 200
    assert c.get("/api/support/en-attente", headers=H_ADMIN).json()["total"] == 0
    fil = poster(c, "/api/support-plateforme/fil", {"utilisateur": {"id": "u-42"}}).json()
    assert [m["de"] for m in fil["messages"]] == ["moi", "support"] and fil["non_lus"] == 1
    assert fil["requete"]["statut"] == "active" and fil["requete"]["prise_par"] == "Jean-François"
    assert poster(c, "/api/support-plateforme/fil", {"utilisateur": {"id": "u-42"}}).json()["non_lus"] == 0   # marqué lu

    # Terminer → message système ; nouveau message → nouvelle requête
    assert c.post(f"/api/support-plateformes/ster/fils/{did}/terminer", headers=H_ADMIN).status_code == 200
    r2 = poster(c, "/api/support-plateforme/messages", {"utilisateur": UTILISATEUR, "texte": "Encore moi"}).json()
    assert r2["requete"]["numero"] != r["requete"]["numero"] and r2["requete"]["statut"] == "attente"
    # Un client ordinaire ne voit pas l'espace
    assert all(e["id"] != "support-plat-ster" for e in c.get("/api/me/chat/clients", headers={"X-User": "cli1"}).json())
    assert c.get("/api/support/en-attente", headers={"X-User": "cli1"}).status_code == 403
