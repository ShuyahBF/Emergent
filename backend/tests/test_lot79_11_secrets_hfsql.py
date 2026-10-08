"""Lot 79.11 — Mots de passe HFSQL saisis dans SAWALI (chiffrés) et remis à Loois avec sa clé client.
Vérifie : stockage chiffré, jamais réaffiché, champ vide = inchangé, effacement, clé commune refusée, clé client
acceptée, remise notée sans mot de passe. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot79_11_secrets_hfsql.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.loois_cles_clients as cles  # noqa: E402
import routes.loois_secrets_hfsql as sec  # noqa: E402

UTILISATEURS = {"admin": {"id": "admin", "role": "admin", "email": "admin@sawali"},
                "phl": {"id": "phl", "role": "pharmacien"}}


@pytest.fixture()
def client(monkeypatch):
    """Application minimale : clés clients + secrets HFSQL ; utilisateur choisi par l'en-tête X-User."""
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-commune")
    monkeypatch.setenv("JWT_SECRET", "secret-de-test")
    monkeypatch.delenv("LOOIS_CLES_PEPPER", raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["test"]

    async def utilisateur(request: Request):
        u = UTILISATEURS.get(request.headers.get("X-User", "admin"))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    cles.setup_loois_cles_clients_routes(db=db, api=api, get_current_user=utilisateur)
    sec.setup_loois_secrets_hfsql_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    yield TestClient(app), db
    cles.ETAT["clients_actifs"] = False


def test_chiffrement_et_saisie(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secret-de-test")
    c = sec.chiffrer("X-secret")
    assert c and "X-secret" not in c and sec.dechiffrer(c) == "X-secret"
    assert sec.dechiffrer("illisible") is None
    # Champ vide = inchangé ; effacement explicite ; texte trop long refusé
    existant = {"mdp_serveur": "ancien", "mdp_fichiers": "ancienF"}
    v = sec.valeurs_a_enregistrer({"mot_de_passe_serveur": "", "effacer_fichiers": True}, existant)
    assert v == {"mdp_serveur": "ancien", "mdp_fichiers": None}
    with pytest.raises(ValueError):
        sec.valeurs_a_enregistrer({"mot_de_passe_serveur": "x" * 500}, {})


def test_parcours_complet(client):
    c, db = client
    # Rien de défini : la remise répond 404 (avec une clé client)
    cle = c.post("/api/admin/loois-cles-clients", json={"code": "CMC", "applications": ["Biolog"]}).json()["cle"]
    assert c.get("/api/loois/secrets-hfsql", headers={"X-Cle-Loois": cle}).status_code == 404

    # Saisie par l'administrateur : l'état ne montre JAMAIS les mots de passe
    r = c.put("/api/admin/loois-secrets-hfsql", json={"mot_de_passe_serveur": "X-serv", "mot_de_passe_fichiers": "Y-fic"})
    assert r.status_code == 200 and r.json()["serveur_defini"] and r.json()["fichiers_defini"]
    assert "X-serv" not in r.text and "Y-fic" not in r.text
    assert c.put("/api/admin/loois-secrets-hfsql", headers={"X-User": "phl"}, json={}).status_code == 403

    # Stockés chiffrés en base
    import asyncio
    doc = asyncio.new_event_loop().run_until_complete(db.loois_reglages.find_one({"id": sec.ID_DOC}))
    assert doc["mdp_serveur"] != "X-serv" and sec.dechiffrer(doc["mdp_serveur"]) == "X-serv"

    # Clé absente ou commune : refusée ; clé client : remise des deux mots de passe
    assert c.get("/api/loois/secrets-hfsql").status_code == 401
    assert c.get("/api/loois/secrets-hfsql", headers={"X-Cle-Loois": "cle-commune"}).status_code == 401
    r = c.get("/api/loois/secrets-hfsql?machine=SRV-2012", headers={"X-Cle-Loois": cle})
    assert r.status_code == 200 and r.json() == {"mot_de_passe_serveur": "X-serv", "mot_de_passe_fichiers": "Y-fic"}

    # Remise notée (client, machine), sans aucun mot de passe
    etat = c.get("/api/admin/loois-secrets-hfsql").json()
    assert etat["livraisons"][0]["client"] == "CMC" and etat["livraisons"][0]["machine"] == "SRV-2012"
    assert "X-serv" not in str(etat)

    # Champ vide = inchangé
    c.put("/api/admin/loois-secrets-hfsql", json={"mot_de_passe_serveur": "", "mot_de_passe_fichiers": ""})
    assert c.get("/api/loois/secrets-hfsql", headers={"X-Cle-Loois": cle}).json()["mot_de_passe_serveur"] == "X-serv"
