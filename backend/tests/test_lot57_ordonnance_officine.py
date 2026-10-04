"""Lot 57 — ordonnance VIDAL en A5 avec QR code vers la page de l'officine ;
l'officine indique ce qu'elle a servi (quantités), servi en partie ou « en
rupture » ; le médecin voit le retour. Base MongoDB locale jetable."""
import io
import os
import time

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from routes.vidal_ordonnance import attach_vidal_ordonnance_routes, build_ordonnance_pdf

MEDECIN = {"id": "lot57_med", "email": "med@exemple.test", "full_name": "Dr TEST Médecin", "role": "medecin"}
AUTRE = {"id": "lot57_autre", "email": "autre@exemple.test", "full_name": "Dr AUTRE", "role": "medecin"}
LIGNES = [
    {"label": "PRODUIT A 500 MG CP", "dose": "1", "unit": "comprimé", "frequency": "3 fois par jour", "duration": "5", "durationType": "jours"},
    {"label": "PRODUIT B SIROP", "dose": "5", "unit": "ml", "frequency": "2 fois par jour", "duration": "7", "durationType": "jours"},
]


@pytest.fixture()
def ctx(monkeypatch):
    nom_base = f"test_lot57_{time.time_ns()}"
    synchrone = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    monkeypatch.setenv("FRONTEND_PUBLIC_URL", "https://site.exemple")
    utilisateur = dict(MEDECIN)

    async def courant():
        return utilisateur

    db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[nom_base]
    app = FastAPI()
    api = APIRouter(prefix="/api")
    attach_vidal_ordonnance_routes(api=api, db=db, get_current_user=courant)
    app.include_router(api)
    try:
        with TestClient(app) as client:
            yield client, synchrone[nom_base], utilisateur
    finally:
        synchrone.drop_database(nom_base)


def _ordonnance(client):
    r = client.post("/api/vidal/ordonnance/generate", json={"patient_name": "PATIENT SECRET", "patient_whatsapp": "+22670000000",
                                                             "patient": {"gender": "FEMALE", "dateOfBirth": "1990-01-01"}, "lines": LIGNES})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    return r.headers["x-ordonnance-id"], r.content


def test_pdf_a5_avec_qr_vers_la_page_officine(ctx):
    client, base, _ = ctx
    oid, contenu = _ordonnance(client)
    from pypdf import PdfReader
    page = PdfReader(io.BytesIO(contenu)).pages[0]
    largeur, hauteur = float(page.mediabox.width), float(page.mediabox.height)
    assert round(largeur) == 420 and round(hauteur) == 595  # A5 en points
    doc = base.vidal_ordonnances.find_one({"id": oid})
    # L'ancien lien du QR renvoie vers la page de l'officine
    r = client.get(f"/api/vidal/ordonnance/verify/{doc['qr_token']}", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == f"https://site.exemple/officine/ordonnance/{doc['qr_token']}"
    # Rendu sans QR : jamais bloquant
    assert build_ordonnance_pdf({**doc, "lines": LIGNES * 6}, anonymized=True).startswith(b"%PDF")


def test_officine_voit_ordonnance_anonymisee_et_enregistre_service_et_rupture(ctx):
    client, base, utilisateur = ctx
    oid, _ = _ordonnance(client)
    jeton = base.vidal_ordonnances.find_one({"id": oid})["qr_token"]
    vue = client.get(f"/api/public/vidal-ordonnance/{jeton}").json()
    assert vue["reference"] == oid[:8].upper() and [l["libelle"] for l in vue["lignes"]] == [l["label"] for l in LIGNES]
    assert "PATIENT SECRET" not in str(vue) and "+22670000000" not in str(vue)
    assert vue["patient"]["sexe"] == "Femme"
    assert client.get("/api/public/vidal-ordonnance/inconnu").status_code == 404
    # Contrôles du formulaire
    url = f"/api/public/vidal-ordonnance/{jeton}/servir"
    assert client.post(url, json={"nom_officine": " ", "lignes": [{"index": 0, "statut": "servi", "quantite_servie": 1}]}).status_code == 422
    assert client.post(url, json={"nom_officine": "X", "lignes": [{"index": 5, "statut": "servi", "quantite_servie": 1}]}).status_code == 422
    assert client.post(url, json={"nom_officine": "X", "lignes": [{"index": 0, "statut": "servi"}]}).status_code == 422
    # Officine 1 : produit A servi, produit B en rupture
    r = client.post(url, json={"nom_officine": "pharmacie du centre", "ville": "Ouagadougou", "lignes": [
        {"index": 0, "statut": "servi", "quantite_servie": 2}, {"index": 1, "statut": "rupture", "quantite_servie": 3}]})
    assert r.status_code == 200 and r.json()["etat"] == "partielle"
    service = base.vidal_ordonnance_services.find_one({"ordonnance_id": oid})
    assert service["nom_officine"] == "PHARMACIE DU CENTRE" and service["lignes"][1]["quantite_servie"] is None
    # Le médecin voit le retour (rupture comprise) et une pastille « nouveau »
    retour = client.get("/api/vidal/ordonnances").json()
    o = retour["ordonnances"][0]
    assert retour["retours_non_lus"] == 1 and o["resume"]["etat"] == "partielle"
    assert o["resume"]["ruptures"] == [{"index": 1, "officine": "PHARMACIE DU CENTRE"}]
    # Officine 2 sert le produit B : ordonnance entièrement servie
    client.post(url, json={"nom_officine": "PHARMACIE 2", "lignes": [{"index": 1, "statut": "servi", "quantite_servie": 1}]})
    assert client.get("/api/vidal/ordonnances").json()["ordonnances"][0]["resume"]["etat"] == "servie"
    assert len(client.get(f"/api/public/vidal-ordonnance/{jeton}").json()["services"]) == 2
    client.post("/api/vidal/ordonnances/retours-lus")
    assert client.get("/api/vidal/ordonnances").json()["retours_non_lus"] == 0
    # Aperçu PDF réservé au médecin de l'ordonnance
    assert client.get(f"/api/vidal/ordonnances/{oid}/pdf").content.startswith(b"%PDF")
    utilisateur.clear(); utilisateur.update(AUTRE)
    assert client.get(f"/api/vidal/ordonnances/{oid}/pdf").status_code == 404
    assert client.get("/api/vidal/ordonnances").json()["ordonnances"] == []
