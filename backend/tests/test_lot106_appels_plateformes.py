"""Lot 106 — une plateforme (ZandGo) demande à Liluvine d'appeler un client : fiche déposée dans l'agenda d'appels
(type « Relance »), une seule fiche active par référence, état relu par la plateforme (et par elle seule).
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot106_appels_plateformes.py -q
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.appels_plateformes as apl  # noqa: E402


def signe(cle: str, corps: dict, code: str = "zandgo") -> tuple:
    """Corps brut + en-têtes signés comme le fait la plateforme."""
    brut = json.dumps(corps, ensure_ascii=False)
    ts = str(int(time.time()))
    sig = hmac.new(cle.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return brut.encode(), {"Content-Type": "application/json", "X-Emetteur": code, "X-Timestamp": ts, "X-Signature": sig}


@pytest.fixture
def env():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_appels"]
    api = APIRouter(prefix="/api")
    apl.setup_appels_plateformes_routes(api=api, db=db)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.liluvine_emetteurs.insert_many, [
        {"code": "zandgo", "nom": "ZandGo", "secret": "cle-zg", "actif": True, "client_id": "espace-1"},
        {"code": "adlyn", "nom": "adLyn", "secret": "cle-ad", "actif": True}])
    yield client, db
    client.__exit__(None, None, None)


DEMANDE = {"ref": "ZG-261010-ABCD", "telephone": "22670000001", "nom": "Awa",
           "objectif": "Comprendre pourquoi la commande n'a pas été payée et proposer de l'aide.",
           "contexte": "Commande ZG-261010-ABCD, 25 000 F CFA, paiement Mobile Money indisponible.",
           "questions": ["Souhaitez-vous toujours cette commande ?", {"libelle": "Moyen de paiement préféré", "type": "texte"}]}


def test_signature_obligatoire(env):
    client, _ = env
    brut, entetes = signe("mauvaise-cle", DEMANDE)
    assert client.post("/api/webhook/plateforme-appel", content=brut, headers=entetes).status_code == 401


def test_demande_puis_etat(env):
    client, db = env
    brut, entetes = signe("cle-zg", DEMANDE)
    r = client.post("/api/webhook/plateforme-appel", content=brut, headers=entetes)
    assert r.status_code == 200 and r.json()["statut"] == "planifie" and r.json()["deja"] is False
    ev = client.portal.call(db.liluvine_agenda.find_one, {"id": "plat-zandgo-ZG-261010-ABCD"})
    assert ev["type"] == "relance" and ev["telephone"] == "22670000001" and ev["client_id"] == "espace-1"
    assert ev["plateforme"] == {"code": "zandgo", "nom": "ZandGo", "ref": "ZG-261010-ABCD"}
    assert len(ev["questions"]) == 2 and ev["titre"] == "Relance ZandGo — Awa"

    # Nouvelle demande pour la même référence tant que la fiche est active : pas de doublon
    brut, entetes = signe("cle-zg", DEMANDE)
    assert client.post("/api/webhook/plateforme-appel", content=brut, headers=entetes).json()["deja"] is True
    assert client.portal.call(db.liluvine_agenda.count_documents, {}) == 1

    # Appel terminé : la plateforme lit le résumé et les informations
    client.portal.call(lambda: db.liluvine_agenda.update_one({"id": ev["id"]}, {"$set": {
        "statut": "termine", "resultat": {"resume": "La cliente paiera demain par Orange Money.",
                                          "informations": {"q1": "oui"}, "transcription": ["…"], "cout": 12}}}))
    brut, entetes = signe("cle-zg", {"ref": "ZG-261010-ABCD"})
    etat = client.post("/api/webhook/plateforme-appel/etat", content=brut, headers=entetes).json()
    assert etat["statut"] == "termine" and etat["resume"].startswith("La cliente") and "transcription" not in etat

    # Une autre plateforme ne voit pas cet appel
    brut, entetes = signe("cle-ad", {"ref": "ZG-261010-ABCD"}, code="adlyn")
    assert client.post("/api/webhook/plateforme-appel/etat", content=brut, headers=entetes).status_code == 404

    # Fiche terminée : une nouvelle demande relance un appel (même identifiant, statut planifié)
    brut, entetes = signe("cle-zg", DEMANDE)
    r = client.post("/api/webhook/plateforme-appel", content=brut, headers=entetes).json()
    assert r["deja"] is False and r["statut"] == "planifie"
    assert client.portal.call(db.liluvine_agenda.count_documents, {}) == 1


def test_numero_obligatoire(env):
    client, _ = env
    brut, entetes = signe("cle-zg", {**DEMANDE, "telephone": "12"})
    r = client.post("/api/webhook/plateforme-appel", content=brut, headers=entetes)
    assert r.status_code == 422 and "Numéro" in r.json()["detail"]
