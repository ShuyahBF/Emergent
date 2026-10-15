"""Lot 164 — page d'accord WhatsApp (lien personnel par contact) : jeton signé, lecture, accord, retrait, falsification.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot164_accord_page.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.accord_page as ap  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secret-de-test")


def test_jeton_signe_et_infalsifiable():
    j = ap.creer_jeton("contact-1")
    assert ap.lire_jeton(j) == "contact-1"
    brut, sig = j.split(".")
    assert ap.lire_jeton(ap.creer_jeton("contact-2").split(".")[0] + "." + sig) is None     # signature d'un autre contact
    assert ap.lire_jeton(brut + ".0000") is None and ap.lire_jeton("n'importe quoi") is None and ap.lire_jeton("") is None
    assert ap.lien_personnel("https://sawali.test/", "contact-1") == f"https://sawali.test/accord/{j}"


def test_sans_secret_pas_de_lien(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(RuntimeError):
        ap.creer_jeton("x")


@pytest.fixture()
def client_http():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    base = mongomock_motor.AsyncMongoMockClient()["sawali_t164"]
    lancer(base.users.insert_many([{"id": "t1", "company": "Pharmacie Amitié", "role": "client"}]))
    lancer(base.directory_contacts.insert_many([
        {"id": "c1", "name": "Awa Ouedraogo", "whatsapp": "+226 70 11 22 33", "client_id": "t1"},
        {"id": "c2", "name": "Sans Numero", "client_id": "t1"}]))
    app, api = FastAPI(), APIRouter(prefix="/api")
    ap.setup_accord_page_routes(db=base, api=api)
    app.include_router(api)
    return TestClient(app), base


def test_page_lit_prenom_et_expediteur_sans_donnees_sensibles(client_http):
    c, _ = client_http
    r = c.get(f"/api/public/accord/{ap.creer_jeton('c1')}").json()
    assert r == {"prenom": "Awa", "expediteur": "Pharmacie Amitié", "fin_numero": "33", "accepte": None, "accepte_le": None}


def test_accord_puis_retrait(client_http):
    c, base = client_http
    j = ap.creer_jeton("c1")
    r = c.post(f"/api/public/accord/{j}", json={"accepte": True}).json()
    assert r["ok"] and r["accepte"] is True
    fiche = lancer(base.directory_contacts.find_one({"id": "c1"}))
    assert fiche["accepte_whatsapp"] is True and fiche["accepte_whatsapp_le"] and fiche["accepte_whatsapp_moyen"] == "page web"
    # preuve : journal des accords (lot 208 : document `settings`, plus de collection dédiée)
    from routes import accord_whatsapp as _aw
    assert len([e for e in lancer(_aw.lire_journal(base)) if e.get("moyen") == "page web" and e.get("accepte") is True]) == 1
    assert c.get(f"/api/public/accord/{j}").json()["accepte"] is True
    assert c.post(f"/api/public/accord/{j}", json={"accepte": False}).json()["accepte"] is False
    fiche = lancer(base.directory_contacts.find_one({"id": "c1"}))
    assert fiche["accepte_whatsapp"] is False and fiche["accepte_whatsapp_le"] is None


def test_refus_jeton_invalide_contact_inconnu_sans_numero(client_http):
    c, _ = client_http
    assert c.get("/api/public/accord/faux.jeton").status_code == 404
    assert c.post("/api/public/accord/faux.jeton", json={"accepte": True}).status_code == 404
    assert c.get(f"/api/public/accord/{ap.creer_jeton('inconnu')}").status_code == 404
    assert c.post(f"/api/public/accord/{ap.creer_jeton('c2')}", json={"accepte": True}).status_code == 422
