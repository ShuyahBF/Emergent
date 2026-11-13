"""Lot 386 — paiement mobile au comptoir des officines : séquences USSD (Orange, Moov, Telecel), jeton public, QR.
Lancer : cd backend && python -m pytest tests/test_lot386_paiement_officine.py -q -p no:xdist
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import paiement_officine as po  # noqa: E402


def test_sequences_validees_par_le_proprietaire():
    # Séquences confirmées le 13/11/2026 (catalogue mobile-payments-web)
    assert po.construire_code("Orange", "123456", 5000) == "*144*10*123456*5000#"
    assert po.construire_code("Moov Africa", "98765", 250) == "*555*2*98765*250#"
    assert po.construire_code("Telecel Faso", "4455", 10000) == "*133*3*4455*10000#"


def test_lien_tel_encode_le_diese():
    assert po.lien_tel("*144*10*123456*5000#") == "tel:*144*10*123456*5000%23"


@pytest.mark.parametrize("brut,attendu", [("5000", 5000), (" 12 500 ", 12500), (7500, 7500), ("0005000", 5000)])
def test_montant_valide(brut, attendu):
    assert po.montant_valide(brut) == attendu


@pytest.mark.parametrize("brut", ["", "abc", "0", "-5", "12,5", "10000001", None])
def test_montant_refuse(brut):
    with pytest.raises(ValueError):
        po.montant_valide(brut)


def test_nettoyage_des_codes():
    ok = po.nettoyer_codes([{"operateur": "Orange", "code": " 123 456 "}, {"operateur": "Moov Africa", "code": ""}])
    assert ok == [{"operateur": "Orange", "code": "123456"}]            # ligne vide ignorée
    for mauvais in ([{"operateur": "MTN", "code": "1234"}], [{"operateur": "Orange", "code": "12"}], [{"operateur": "Orange", "code": "12ab34"}],
                    [{"operateur": "Orange", "code": "1234"}, {"operateur": "Orange", "code": "5678"}]):
        with pytest.raises(ValueError):
            po.nettoyer_codes(mauvais)


def _app():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot386"]
    asyncio.get_event_loop().run_until_complete(db.officines.insert_many([
        {"id": "o1", "name": "Pharmacie Amitié", "city": "Ouagadougou", "status": "active"},
        {"id": "o2", "name": "Pharmacie Suspendue", "city": "Bobo", "status": "suspended"}]))
    qui = {"o": "o1", "role": "admin"}

    async def officine_courante():
        return await db.officines.find_one({"id": qui["o"]}, {"_id": 0})

    async def utilisateur():
        return {"role": qui["role"]}
    app, api = FastAPI(), APIRouter(prefix="/api")
    po.setup_paiement_officine_routes(db=db, api=api, get_current_officine=officine_courante, get_current_user=utilisateur)
    app.include_router(api)
    return db, qui, TestClient(app)


def test_parcours_complet():
    db, qui, c = _app()
    # Avant configuration : rien de public, pas de QR
    assert c.get("/api/officines-portal/me/paiement").json()["jeton"] is None
    assert c.get("/api/officines-portal/me/paiement/qr.png").status_code == 404
    # Codes invalides refusés ; valides enregistrés, jeton créé une seule fois
    assert c.put("/api/officines-portal/me/paiement", json={"operateurs": [{"operateur": "Orange", "code": "12"}]}).status_code == 422
    r = c.put("/api/officines-portal/me/paiement", json={"operateurs": [{"operateur": "Orange", "code": "123456"}, {"operateur": "Telecel Faso", "code": "778899"}]})
    assert r.status_code == 200 and len(r.json()["jeton"]) == 32 and r.json()["url_publique"].endswith("/officine/payer/" + r.json()["jeton"])
    jeton = r.json()["jeton"]
    r2 = c.put("/api/officines-portal/me/paiement", json={"operateurs": [{"operateur": "Orange", "code": "123456"}]})
    assert r2.json()["jeton"] == jeton
    # QR : une vraie image PNG
    qr = c.get("/api/officines-portal/me/paiement/qr.png")
    assert qr.status_code == 200 and qr.headers["content-type"] == "image/png" and qr.content[:8] == b"\x89PNG\r\n\x1a\n"
    # Page publique : nom et opérateurs, jamais le code marchand
    p = c.get(f"/api/officine-paiement/{jeton}")
    assert p.status_code == 200 and p.json() == {"nom": "Pharmacie Amitié", "operateurs": ["Orange"]}
    # Séquence demandée par le client
    u = c.post(f"/api/officine-paiement/{jeton}/ussd", json={"operateur": "Orange", "montant": "5 000"})
    assert u.status_code == 200 and u.json()["code_ussd"] == "*144*10*123456*5000#" and u.json()["lien_tel"] == "tel:*144*10*123456*5000%23"
    # Opérateur non accepté, montant faux, jeton inconnu ou mal formé
    assert c.post(f"/api/officine-paiement/{jeton}/ussd", json={"operateur": "Moov Africa", "montant": 100}).status_code == 422
    assert c.post(f"/api/officine-paiement/{jeton}/ussd", json={"operateur": "Orange", "montant": "abc"}).status_code == 422
    assert c.get("/api/officine-paiement/" + "0" * 32).status_code == 404
    assert c.get("/api/officine-paiement/pas-un-jeton").status_code == 404
    # Pharmacie suspendue : le QR cesse de fonctionner
    asyncio.get_event_loop().run_until_complete(db.officines.update_one({"id": "o1"}, {"$set": {"status": "suspended"}}))
    assert c.get(f"/api/officine-paiement/{jeton}").status_code == 404


def test_resume_admin():
    db, qui, c = _app()
    c.put("/api/officines-portal/me/paiement", json={"operateurs": [{"operateur": "Moov Africa", "code": "4455"}]})
    r = c.get("/api/admin/officines-paiement").json()
    assert r["configurees"] == 1 and r["total"] == 2 and r["officines"][0]["operateurs"] == ["Moov Africa"] and "4455" not in str(r["officines"])
    qui["role"] = "client"
    assert c.get("/api/admin/officines-paiement").status_code == 403
