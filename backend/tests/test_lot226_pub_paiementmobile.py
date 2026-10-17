"""Lot 226 — emplacement « Paiement Mobile » de la régie publicitaire : liste publique des annonces actives,
exclusion de la rotation des bannières du site, comptage des impressions et des clics.
Lancer : cd backend && python -m pytest tests/test_lot226_pub_paiementmobile.py -q
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes.ad_banners import setup_ad_banners_routes  # noqa: E402


def _banniere(identifiant, placement="paiementmobile", **plus):
    base = {"id": identifiant, "tenant_id": "t", "name": identifiant, "advertiser_name": "Annonceur",
            "image_url": f"https://exemple.bf/{identifiant}.jpg", "target_url": "https://exemple.bf", "placement": placement,
            "active": True, "budget_amount": 1000, "amount_spent": 0, "cost_per_impression": 2, "cost_per_click": 50,
            "total_impressions": 0, "total_clicks": 0}
    base.update(plus)
    return base


@pytest.fixture()
def client():
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    api = APIRouter(prefix="/api")
    setup_ad_banners_routes(app=api, db=db, get_current_user=lambda: {"role": "admin", "id": "a"})
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as c:
        c.db = db
        yield c


def test_liste_ne_renvoie_que_les_annonces_paiement_mobile_valides(client):
    hier = (date.today() - timedelta(days=1)).isoformat()
    client.portal.call(client.db.ad_banners.insert_many, [
        _banniere("pm1"), _banniere("pm2"),
        _banniere("expiree", expiration_date=hier),          # échue : exclue
        _banniere("epuisee", amount_spent=1000),             # budget épuisé : exclue
        _banniere("pause", active=False),                    # en pause : exclue
        _banniere("site", placement="public"),               # autre emplacement : exclue
    ])
    r = client.get("/api/public/ad-banners/liste")
    assert r.status_code == 200
    assert sorted(b["id"] for b in r.json()["banners"]) == ["pm1", "pm2"]


def test_rotation_du_site_ne_sert_jamais_une_annonce_paiement_mobile(client):
    client.portal.call(client.db.ad_banners.insert_one, _banniere("pm1"))
    for emplacement in ("public", "portal"):
        assert client.get(f"/api/public/ad-banners/active?placement={emplacement}").json() == {"banner": None}


def test_impression_et_clic_sont_comptes_et_factures(client):
    client.portal.call(client.db.ad_banners.insert_one, _banniere("pm1"))
    assert client.post("/api/public/ad-banners/pm1/impression").json() == {"ok": True}
    assert client.post("/api/public/ad-banners/pm1/click").json()["ok"] is True
    b = client.portal.call(client.db.ad_banners.find_one, {"id": "pm1"})
    assert b["total_impressions"] == 1 and b["total_clicks"] == 1 and b["amount_spent"] == 52


def test_emplacement_inconnu_refuse_par_la_liste(client):
    assert client.get("/api/public/ad-banners/liste?placement=autre").status_code == 422
