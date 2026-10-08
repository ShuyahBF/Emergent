"""Lot 82 — bandeau limité à ± N jours de l'échéance et services de la plateforme suspendus automatiquement.
Lancer : cd backend && python -m pytest tests/test_lot82_services_suspendus.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import contrats_plateformes as cp  # noqa: E402
from tests.test_lot81_contrats_plateformes import _signer  # noqa: E402


def test_fenetre_du_bandeau():
    # Hors de la fenêtre ± 5 jours : aucune couleur, donc aucun bandeau chez la plateforme
    assert cp.etat_contrat("2026-10-15", "2027-10-15", date(2027, 10, 9))["couleur"] is None    # J-6
    assert cp.etat_contrat("2026-10-15", "2027-10-15", date(2027, 10, 21))["couleur"] is None   # J+6
    assert cp.etat_contrat("2026-10-15", "2027-10-15", date(2028, 3, 1))["niveau"] == "echu"
    # Délais réglables : rouge jusqu'à J+2 seulement
    assert cp.etat_contrat(None, "2027-10-15", date(2027, 10, 17), 5, 2)["couleur"] == "rouge"
    assert cp.etat_contrat(None, "2027-10-15", date(2027, 10, 18), 5, 2)["niveau"] == "echu"


def test_services_coches_et_suspension():
    assert cp.nettoyer_services(["WA", "cr", "wa", ""]) == ["wa", "cr"]   # ordre du catalogue, sans doublon
    with pytest.raises(ValueError):
        cp.nettoyer_services(["inconnu"])
    assert cp.date_suspension("2027-10-15", 5) == "2027-10-21"
    echu = cp.etat_contrat(None, "2027-10-15", date(2027, 10, 21))
    rouge = cp.etat_contrat(None, "2027-10-15", date(2027, 10, 20))
    assert cp.services_suspendus(echu, ["wa", "cr"]) == ["wa", "cr"]
    assert cp.services_suspendus(rouge, ["wa", "cr"]) == []   # pas encore : seulement annoncés en rouge


def test_parcours_suspension():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot82"]
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.liluvine_emetteurs.insert_one(
        {"code": "albarka", "nom": "ALBARKA", "secret": "cle-albarka", "actif": True}))
    boucle.run_until_complete(db.users.insert_one({"id": "t1", "company": "Cabinet ALBARKA", "role": "client"}))
    app, api = FastAPI(), APIRouter(prefix="/api")
    cp.setup_contrats_plateformes_routes(db=db, api=api, get_current_user=lambda: {"role": "admin"})
    app.include_router(api)
    c = TestClient(app)
    assert c.put("/api/admin/plateformes/albarka/contrat", json={"client_id": "t1", "services_suspendus": ["xx"]}).status_code == 422
    # Contrat échu depuis longtemps, WA et CR cochés : la plateforme reçoit la liste à bloquer
    r = c.put("/api/admin/plateformes/albarka/contrat", json={
        "client_id": "t1", "debut": "2024-01-01", "fin": "2025-01-01", "services_suspendus": ["cr", "wa"]})
    assert r.status_code == 200, r.text
    assert r.json()["services_a_suspendre"] == ["wa", "cr"] and r.json()["services_suspendus"] == ["wa", "cr"]
    assert c.get("/api/admin/plateformes/contrats").json()["services_catalogue"][0]["code"] == "wa"
    corps = b"{}"
    e = c.post("/api/webhook/plateforme-contrat", content=corps, headers=_signer("cle-albarka", corps)).json()
    assert e["etat"]["niveau"] == "echu" and e["etat"]["couleur"] is None
    assert e["services_suspendus"] == ["wa", "cr"] and e["suspension_le"] == "2025-01-07"
    # Échéance repoussée (renouvellement) : plus rien de suspendu, automatiquement
    c.put("/api/admin/plateformes/albarka/contrat", json={"fin": "2099-01-01"})
    e = c.post("/api/webhook/plateforme-contrat", content=corps, headers=_signer("cle-albarka", corps)).json()
    assert e["services_suspendus"] == [] and e["services_a_suspendre"] == ["wa", "cr"]


def test_lot_et_carte():
    import lot
    import nouveautes
    assert int(lot.LOT.split(".")[0]) >= 82
    assert any(str(n.get("lot")) == "82" for n in nouveautes.NOUVEAUTES)


def test_deux_plateformes_meme_client_ne_s_ecrasent_plus():
    """Lot 82.4 : ALBARKA et Ster rattachées au même client gardent chacune LEUR contrat."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot82_4"]
    boucle = asyncio.new_event_loop()
    for code in ("albarka", "ster"):
        boucle.run_until_complete(db.liluvine_emetteurs.insert_one({"code": code, "nom": code.upper(), "secret": "s", "actif": True}))
    # Ancien contrat rangé sur la fiche client : repris comme valeur de départ
    boucle.run_until_complete(db.users.insert_one({"id": "t1", "company": "Client commun", "role": "client",
                                                   "contract_number": "ANCIEN", "contract_end_at": "2027-01-01"}))
    app, api = FastAPI(), APIRouter(prefix="/api")
    cp.setup_contrats_plateformes_routes(db=db, api=api, get_current_user=lambda: {"role": "admin"})
    app.include_router(api)
    c = TestClient(app)
    assert c.put("/api/admin/plateformes/albarka/contrat", json={"client_id": "t1", "debut": "2026-10-15", "fin": "2027-10-15",
                                                                 "alerte_apres_jours": 0}).status_code == 200
    assert c.put("/api/admin/plateformes/ster/contrat", json={"client_id": "t1", "debut": "2026-08-05", "fin": "2026-09-06",
                                                              "numero": "STER-1"}).status_code == 200
    contrats = {x["code"]: x for x in c.get("/api/admin/plateformes/contrats").json()["contrats"]}
    assert contrats["albarka"]["fin"] == "2027-10-15" and contrats["albarka"]["numero"] == "ANCIEN"
    assert contrats["albarka"]["alerte_apres_jours"] == 0          # 0 jour gardé (plus remplacé par 5)
    assert contrats["ster"]["fin"] == "2026-09-06" and contrats["ster"]["numero"] == "STER-1"


def test_chaque_plateforme_declare_ses_services():
    """Lot 82.5 : la plateforme déclare ses services suspendables en lisant son contrat ; le formulaire n'accepte
    que ceux-là. Une plateforme qui n'a rien déclaré n'a pas de cases à cocher."""
    import json as _json
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot82_5"]
    boucle = asyncio.new_event_loop()
    for code in ("albarka", "ster"):
        boucle.run_until_complete(db.liluvine_emetteurs.insert_one({"code": code, "nom": code.upper(), "secret": "cle-albarka", "actif": True}))
    boucle.run_until_complete(db.users.insert_one({"id": "t1", "company": "Client", "role": "client"}))
    app, api = FastAPI(), APIRouter(prefix="/api")
    cp.setup_contrats_plateformes_routes(db=db, api=api, get_current_user=lambda: {"role": "admin"})
    app.include_router(api)
    c = TestClient(app)
    corps = _json.dumps({"services": [{"code": "ordonnances", "libelle": "Ordonnances", "description": "Lecture"},
                                      {"code": "wa", "libelle": "WhatsApp"}]}).encode()
    r = c.post("/api/webhook/plateforme-contrat", content=corps, headers=_signer("cle-albarka", corps))
    assert r.status_code == 200 and [x["code"] for x in r.json()["services_catalogue"]] == ["ordonnances", "wa"]
    contrats = {x["code"]: x for x in c.get("/api/admin/plateformes/contrats").json()["contrats"]}
    assert contrats["albarka"]["services_catalogue"][0]["libelle"] == "Ordonnances"
    assert contrats["ster"]["services_catalogue"] is None                 # rien déclaré : pas de cases
    assert c.put("/api/admin/plateformes/albarka/contrat", json={"client_id": "t1", "services_suspendus": ["cr"]}).status_code == 422
    assert c.put("/api/admin/plateformes/albarka/contrat", json={"client_id": "t1", "services_suspendus": ["ordonnances"]}).status_code == 200
    mauvais = _json.dumps({"services": [{"code": "Pas bon !"}]}).encode()
    assert c.post("/api/webhook/plateforme-contrat", content=mauvais, headers=_signer("cle-albarka", mauvais)).status_code == 422
