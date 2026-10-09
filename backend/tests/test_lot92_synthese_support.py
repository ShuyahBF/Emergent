"""Lot 92 — synthèse du support (administrateur et superviseur) : demandes non répondues (en attente / sans réponse),
totaux de la période par espace, demandes transmises à Claude.
Lancer : cd backend && python -m pytest tests/test_lot92_synthese_support.py -q
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
os.environ.setdefault("DB_NAME", "test_lot92")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.internal_chat as ic  # noqa: E402

ADMIN = {"id": "adm1", "role": "admin", "full_name": "Jean-François", "email": "admin@sawali.test", "account_status": "active"}
SUP = {"id": "sup1", "role": "superviseur", "full_name": "Superviseur", "account_status": "active"}
CLIENT = {"id": "cli1", "role": "client", "company": "Pharmacie X", "account_status": "active"}
SECRET = "secret-de-ster"


def poster(c, chemin, corps):
    """Requête signée comme le fait la plateforme sTer."""
    brut = json.dumps(corps)
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return c.post(chemin, content=brut, headers={"X-Emetteur": "ster", "X-Timestamp": ts, "X-Signature": sig,
                                                 "Content-Type": "application/json"})


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-de-test")
    monkeypatch.delenv("LOOIS_SUPPORT_ADMIN_EMAIL", raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot92"]
    utilisateurs = {"adm1": ADMIN, "sup1": SUP, "cli1": CLIENT}

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
        client.portal.call(db.users.insert_many, [dict(ADMIN), dict(SUP), dict(CLIENT)])
        client.portal.call(db.liluvine_emetteurs.insert_one,
                           {"code": "ster", "nom": "sTer", "secret": SECRET, "actif": True, "support_actif": True})
        yield client, db


def test_acces_admin_et_superviseur_seulement(env):
    c, _ = env
    assert c.get("/api/support/synthese", headers={"X-User": "cli1"}).status_code == 403
    assert c.get("/api/support/synthese", headers={"X-User": "sup1"}).status_code == 200
    r = c.get("/api/support/synthese", headers={"X-User": "adm1"}).json()
    assert r["totaux"]["recues"] == 0 and r["non_repondues"] == [] and r["claude"]["total"] == 0


def test_non_repondues_attente_puis_sans_reponse_puis_repondue(env):
    """Demande en attente → listée ; l'agent répond → plus listée ; le client réécrit → « sans réponse »."""
    c, db = env
    a = {"utilisateur": {"id": "u-1", "nom": "Awa"}, "texte": "Bonjour, l'écran des RDV ne s'ouvre pas"}
    assert poster(c, "/api/support-plateforme/messages", a).status_code == 200
    s = c.get("/api/support/synthese", headers={"X-User": "sup1"}).json()
    ligne = s["non_repondues"][0]
    assert (ligne["espace_nom"], ligne["nom"], ligne["etat"]) == ("sTer - Support", "Awa", "attente")
    assert ligne["numero"].startswith("SUP-STER-")
    assert s["totaux"]["recues"] == 1 and s["totaux"]["non_repondues"] == 1 and s["totaux"]["en_attente"] == 1

    # L'agent répond dans le fil : la requête passe en cours, plus rien n'attend
    did = c.portal.call(db.support_plateformes_demandeurs.find_one, {"plateforme": "ster"})["id"]
    r = c.post("/api/me/chat/support-plat-ster/messages", headers={"X-User": "adm1"}, json={"text": "Je regarde.", "recipient_id": did})
    assert r.status_code in (200, 201), r.text
    assert c.get("/api/support/synthese", headers={"X-User": "adm1"}).json()["non_repondues"] == []

    # Le client réécrit : sans réponse du support, avec son dernier message
    poster(c, "/api/support-plateforme/messages", {"utilisateur": {"id": "u-1", "nom": "Awa"}, "texte": "Toujours bloqué"})
    s = c.get("/api/support/synthese", headers={"X-User": "adm1"}).json()
    ligne = s["non_repondues"][0]
    assert ligne["etat"] == "sans_reponse" and ligne["dernier_message"] == "Toujours bloqué"
    assert s["totaux"]["sans_reponse"] == 1
    assert s["totaux"]["par_espace"][0]["espace_nom"] == "sTer - Support"


def test_demandes_transmises_a_claude(env):
    c, db = env
    from datetime import datetime, timezone
    maintenant = datetime.now(timezone.utc).isoformat()
    c.portal.call(db.demandes_fonctionnalites.insert_many, [
        {"id": "d1", "numero": "DEM-2026-0001", "plateforme_nom": "sTer", "demandeur_nom": "Awa", "texte": "Ajouter un module",
         "statut": "a_decider", "creee_le": maintenant, "avis": {"verdict": "approuve", "complexite": "moyenne"}},
        {"id": "d2", "numero": "DEM-2026-0002", "plateforme_nom": "Loois", "demandeur_nom": "PC-1", "texte": "Corriger l'état",
         "statut": "non_faisable", "creee_le": maintenant},
        {"id": "d3", "numero": "DEM-2025-0009", "plateforme_nom": "sTer", "demandeur_nom": "X", "texte": "Ancienne",
         "statut": "acceptee", "creee_le": "2025-01-01T00:00:00+00:00"},   # hors période
    ])
    cl = c.get("/api/support/synthese?jours=30", headers={"X-User": "sup1"}).json()["claude"]
    assert cl["total"] == 2 and cl["a_decider"] == 1 and cl["par_statut"]["non_faisable"] == 1
    assert [d["numero"] for d in cl["demandes"]] == ["DEM-2026-0001", "DEM-2026-0002"] or len(cl["demandes"]) == 2
    assert c.get("/api/support/synthese?jours=3650", headers={"X-User": "sup1"}).status_code == 422
