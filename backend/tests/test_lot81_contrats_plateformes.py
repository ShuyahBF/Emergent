"""Lot 81 — contrat de chaque plateforme cliente (ALBARKA…) : état, finances, lecture signée par la plateforme.
Lancer : cd backend && python -m pytest tests/test_lot81_contrats_plateformes.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import contrats_plateformes as cp  # noqa: E402


@pytest.mark.parametrize("aujourdhui, niveau, couleur", [
    (date(2026, 10, 1), "a_venir", None),        # avant le 15 octobre 2026
    (date(2027, 3, 1), "ok", None),
    (date(2027, 10, 9), "ok", None),             # J-6
    (date(2027, 10, 10), "bientot", "orange"),   # J-5 : bandeau orange
    (date(2027, 10, 15), "bientot", "orange"),   # jour de l'échéance
    (date(2027, 10, 16), "expire", "orange"),    # J+1
    (date(2027, 10, 19), "expire", "orange"),    # J+4
    (date(2027, 10, 20), "critique", "rouge"),   # J+5 : barre rouge
])
def test_etat_du_contrat(aujourdhui, niveau, couleur):
    e = cp.etat_contrat("2026-10-15", "2027-10-15", aujourdhui)
    assert (e["niveau"], e["couleur"]) == (niveau, couleur)


def test_sans_echeance():
    assert cp.etat_contrat("2026-10-15", None, date(2026, 11, 1))["niveau"] == "aucun"


def test_lignes_et_finances():
    lignes = cp.nettoyer_lignes([{"type": "prestation", "libelle": "Développement", "montant": "1500000"},
                                 {"type": "service", "libelle": "Hébergement", "montant": 300000},
                                 {"type": "service", "libelle": "", "montant": 5}])
    assert len(lignes) == 2
    for mauvais in ([{"type": "autre", "libelle": "x"}], [{"libelle": "x", "montant": -1}]):
        with pytest.raises(ValueError):
            cp.nettoyer_lignes(mauvais)
    paiements = [{"payment_date": "2026-10-20", "amount_paid": 1000000}, {"payment_date": "2026-09-01", "amount_paid": 999}]
    f = cp.resume_financier(None, lignes, paiements, "2026-10-15")
    assert f == {"montant": 1800000.0, "somme_lignes": 1800000.0, "paye": 1000000.0, "du": 800000.0,
                 "prestations": 1500000.0, "services": 300000.0, "paiements_retenus": 1}
    # Montant saisi prioritaire sur la somme des lignes
    assert cp.resume_financier(2000000, lignes, [], "2026-10-15")["du"] == 2000000.0


def _signer(cle: str, corps: bytes) -> dict:
    ts = str(int(time.time()))
    sig = hmac.new(cle.encode(), f"{ts}.{corps.decode()}".encode(), hashlib.sha256).hexdigest()
    return {"X-Emetteur": "albarka", "X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}


def test_parcours_complet():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot81"]
    asyncio.get_event_loop().run_until_complete(db.liluvine_emetteurs.insert_one(
        {"code": "albarka", "nom": "ALBARKA", "secret": "cle-albarka", "actif": True}))
    asyncio.get_event_loop().run_until_complete(db.users.insert_one(
        {"id": "t1", "company": "Cabinet ALBARKA", "role": "client"}))
    asyncio.get_event_loop().run_until_complete(db.tenant_payments.insert_one(
        {"tenant_id": "t1", "payment_date": "2026-10-16", "amount_paid": 500000}))
    role = {"v": "admin"}
    app, api = FastAPI(), APIRouter(prefix="/api")
    cp.setup_contrats_plateformes_routes(db=db, api=api, get_current_user=lambda: {"role": role["v"]})
    app.include_router(api)
    c = TestClient(app)
    # Paramétrage du contrat (administrateur seulement)
    role["v"] = "client"
    assert c.put("/api/admin/plateformes/albarka/contrat", json={"client_id": "t1"}).status_code == 403
    role["v"] = "admin"
    r = c.put("/api/admin/plateformes/albarka/contrat", json={
        "client_id": "t1", "numero": "CTR-ALB-2026-01", "debut": "2026-10-15", "fin": "2027-10-14",
        "lignes": [{"type": "prestation", "libelle": "Développement", "montant": 1500000},
                   {"type": "service", "libelle": "Coûts Meta / WhatsApp", "montant": 200000}]})
    assert r.status_code == 200, r.text
    assert r.json()["finances"]["du"] == 1200000.0 and r.json()["paiements"][0]["amount_paid"] == 500000
    assert c.put("/api/admin/plateformes/albarka/contrat", json={"fin": "2026-01-01"}).status_code == 422
    liste = c.get("/api/admin/plateformes/contrats").json()["contrats"]
    assert liste[0]["numero"] == "CTR-ALB-2026-01"
    # La plateforme lit son état avec sa clé ; mauvaise clé refusée
    corps = b"{}"
    assert c.post("/api/webhook/plateforme-contrat", content=corps, headers=_signer("mauvaise", corps)).status_code == 401
    e = c.post("/api/webhook/plateforme-contrat", content=corps, headers=_signer("cle-albarka", corps)).json()
    assert e["numero"] == "CTR-ALB-2026-01" and e["du"] == 1200000.0 and e["etat"]["niveau"] in ("a_venir", "ok")
    assert "paiements" not in e
