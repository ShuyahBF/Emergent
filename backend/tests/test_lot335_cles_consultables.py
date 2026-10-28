"""Lot 335 — clé client Loois CONSULTABLE par le super-admin : stockage chiffré (secret hors base), bouton « Afficher » réservé au super-admin,
journal des affichages, jamais d'empreinte ni de jeton chiffré dans les réponses, clés anciennes à régénérer.
Lancer : cd backend && python -m pytest tests/test_lot335_cles_consultables.py -q"""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")   # la liste des clés calcule le contrat (modules du serveur)
os.environ.setdefault("DB_NAME", "sawali_test_lot335")

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import routes.loois_cles_clients as cles

SUPER = {"id": "sa", "role": "admin", "email": "admin@sawalismartsystems.com", "full_name": "Super-admin"}
ADMIN = {"id": "ad", "role": "admin", "email": "autre.admin@exemple.bf", "full_name": "Autre admin"}
UTILISATEURS = {"sa": SUPER, "ad": ADMIN}
SECRET = "secret-de-test-0123456789-abcdefghijklmnop"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.delenv("LOOIS_CLES_PEPPER", raising=False)
    monkeypatch.delenv("LOOIS_SUPPORT_CLE", raising=False)
    monkeypatch.setenv("SUPER_ADMIN_EMAIL", "admin@sawalismartsystems.com")
    monkeypatch.setenv("LOOIS_CLES_CHIFFREMENT", SECRET)
    yield
    cles.ETAT["clients_actifs"] = False


def _app():
    base = AsyncMongoMockClient()["test_lot335"]

    async def courant(request: Request):
        u = UTILISATEURS.get(request.headers.get("x-user", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    cles.setup_loois_cles_clients_routes(db=base, api=api, get_current_user=courant)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), base


SA, AD = {"x-user": "sa"}, {"x-user": "ad"}


def test_chiffrement_aller_retour_et_secret_change(monkeypatch, env):
    jeton = cles.chiffrer_cle("LK-exemple")
    assert jeton and "LK-exemple" not in jeton and cles.dechiffrer_cle(jeton) == "LK-exemple"
    monkeypatch.setenv("LOOIS_CLES_CHIFFREMENT", "un-autre-secret-0123456789-abcdefghijklmnop")
    assert cles.dechiffrer_cle(jeton) is None                    # secret changé : illisible, jamais d'exception
    monkeypatch.delenv("LOOIS_CLES_CHIFFREMENT")
    assert not cles.chiffrement_configure() and cles.chiffrer_cle("LK-x") is None and cles.dechiffrer_cle(jeton) is None


def test_afficher_la_cle_super_admin_seulement_et_journal(env):
    c, base = _app()
    r = c.post("/api/admin/loois-cles-clients", json={"code": "SCF", "libelle": "SCF"}, headers=SA).json()
    fid, cle = r["fiche"]["id"], r["cle"]
    # Rien de sensible dans les réponses : ni empreinte, ni jeton chiffré, ni clé ; seulement l'indicateur « consultable »
    assert r["fiche"]["cle_consultable"] is True and "cle_chiffree" not in r["fiche"] and "cle_hash" not in r["fiche"]
    liste = c.get("/api/admin/loois-cles-clients", headers=SA)
    assert cle not in liste.text and liste.json()["chiffrement_configure"] is True and liste.json()["cles"][0]["cle_consultable"] is True
    stockee = _run(base.loois_cles_clients.find_one({"id": fid}))
    assert cle not in str(stockee)                                # jamais en clair dans la base
    # Un autre administrateur : refusé ; le super-admin : la clé, puis une ligne d'historique SANS la clé
    assert c.post(f"/api/admin/loois-cles-clients/{fid}/afficher", json={}, headers=AD).status_code == 403
    a = c.post(f"/api/admin/loois-cles-clients/{fid}/afficher", json={"type": "cle"}, headers=SA)
    assert a.status_code == 200 and a.json()["cle"] == cle and a.headers["cache-control"] == "no-store"
    histo = _run(base.loois_cles_clients.find_one({"id": fid}))["historique"]
    assert histo[-1]["action"] == "affichage_cle" and histo[-1]["par"] and cle not in str(histo)
    # La clé affichée est bien celle qui s'identifie
    assert _run(cles.identifier_cle(base, cle))["code"] == "SCF"


def test_cle_sans_surveillance_et_revocation(env):
    c, base = _app()
    r = c.post("/api/admin/loois-cles-clients", json={"code": "SCF"}, headers=SA).json()
    fid = r["fiche"]["id"]
    lks = c.post(f"/api/admin/loois-cles-clients/{fid}/sans-surveillance", headers=SA).json()["cle"]
    assert c.post(f"/api/admin/loois-cles-clients/{fid}/afficher", json={"type": "sans_surveillance"}, headers=SA).json()["cle"] == lks
    assert c.post(f"/api/admin/loois-cles-clients/{fid}/afficher", json={"type": "autre"}, headers=SA).status_code == 422
    # Clé révoquée : plus d'affichage
    c.post(f"/api/admin/loois-cles-clients/{fid}/revoquer", headers=SA)
    assert c.post(f"/api/admin/loois-cles-clients/{fid}/afficher", json={"type": "cle"}, headers=SA).status_code == 409


def test_cle_ancienne_sans_secret_et_regeneration(monkeypatch, env):
    c, base = _app()
    monkeypatch.delenv("LOOIS_CLES_CHIFFREMENT")                  # clé créée AVANT l'activation du chiffrement
    r = c.post("/api/admin/loois-cles-clients", json={"code": "SCF"}, headers=SA).json()
    fid = r["fiche"]["id"]
    assert r["fiche"]["cle_consultable"] is False
    a = c.post(f"/api/admin/loois-cles-clients/{fid}/afficher", json={}, headers=SA)
    assert a.status_code == 409 and "LOOIS_CLES_CHIFFREMENT" in a.json()["detail"]
    assert c.get("/api/admin/loois-cles-clients", headers=SA).json()["chiffrement_configure"] is False
    # Secret défini : la clé ancienne reste non consultable tant qu'on ne l'a pas régénérée
    monkeypatch.setenv("LOOIS_CLES_CHIFFREMENT", SECRET)
    a = c.post(f"/api/admin/loois-cles-clients/{fid}/afficher", json={}, headers=SA)
    assert a.status_code == 409 and "régénérez" in a.json()["detail"]
    nouvelle = c.post(f"/api/admin/loois-cles-clients/{fid}/regenerer", headers=SA).json()["cle"]
    assert c.post(f"/api/admin/loois-cles-clients/{fid}/afficher", json={}, headers=SA).json()["cle"] == nouvelle
