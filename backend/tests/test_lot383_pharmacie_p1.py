"""Lot 383 — pharmacie, lot P1 : validité, révocation, clôture, journal d'accès et lien NFC de l'ordonnance sécurisée.
Logique pure + routes (mongomock_motor, sans réseau). Lancer : cd backend && python -m pytest tests/test_lot383_pharmacie_p1.py -q
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vidal_v2 import ordonnance_acces as oa  # noqa: E402

UTC = timezone.utc
MAINTENANT = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
LIGNES = [{"label": "PRODUIT A 500 MG CP", "dose": "1", "unit": "comprimé", "frequency": "3 fois par jour", "duration": "5", "durationType": "jours"},
          {"label": "PRODUIT B SIROP", "dose": "5", "unit": "ml", "frequency": "2 fois par jour", "duration": "7", "durationType": "jours"}]


# ---------------------------------------------------------------- logique pure
def test_etat_acces_priorites_et_messages():
    base = {"created_at": MAINTENANT - timedelta(days=1)}
    assert oa.etat_acces(base, MAINTENANT)["code"] == "ok"
    assert oa.etat_acces({**base, "etat_service": "servie"}, MAINTENANT)["code"] == "cloturee"
    expiree = oa.etat_acces({"created_at": MAINTENANT - timedelta(days=31)}, MAINTENANT)             # ordonnance sans date limite : émission + 30 jours
    assert expiree["code"] == "expiree" and "expiré le" in expiree["message"]
    assert oa.etat_acces({**base, "expire_le": MAINTENANT + timedelta(days=2)}, MAINTENANT)["code"] == "ok"
    revoquee = oa.etat_acces({**base, "revoquee": True, "etat_service": "servie", "expire_le": MAINTENANT - timedelta(days=1)}, MAINTENANT)
    assert revoquee["code"] == "revoquee" and "annulée" in revoquee["message"]                      # la révocation prime sur tout


def test_validite_configurable(monkeypatch):
    assert oa.validite_jours() == 30
    monkeypatch.setenv("ORDONNANCE_VALIDITE_JOURS", "7"); assert oa.validite_jours() == 7
    monkeypatch.setenv("ORDONNANCE_VALIDITE_JOURS", "9999"); assert oa.validite_jours() == 365
    monkeypatch.setenv("ORDONNANCE_VALIDITE_JOURS", "abc"); assert oa.validite_jours() == 30


def test_adresses_masquees_et_canal():
    assert oa.masquer_ip("41.202.10.57") == "41.202.10.x" and oa.masquer_ip("2001:db8:85a3:8d3:1319") == "2001:db8:85a3::x"
    assert oa.masquer_ip("") == "inconnue" and oa.masquer_ip("pas une ip") == "inconnue"
    assert oa.adresse_client("41.202.10.57, 10.0.0.1", "10.0.0.9") == "41.202.10.57" and oa.adresse_client(None, "10.0.0.9") == "10.0.0.9"
    assert oa.canal("nfc") == "nfc" and oa.canal("NFC") == "nfc" and oa.canal("autre") == "qr" and oa.canal(None) == "qr"


def test_reutilisation_suspecte():
    def acces(ip, minutes): return {"action": "lecture", "ip_masquee": ip, "date": MAINTENANT - timedelta(minutes=minutes)}
    calme = [acces("1.1.1.x", 5), acces("1.1.1.x", 50)]
    assert oa.analyse_acces(calme, MAINTENANT)["suspect"] is False and oa.analyse_acces(calme, MAINTENANT)["nombre"] == 2
    beaucoup_d_adresses = [acces(f"1.1.{i}.x", i + 1) for i in range(7)]
    r = oa.analyse_acces(beaucoup_d_adresses, MAINTENANT)
    assert r["suspect"] and "7 adresses" in r["motif"]
    assert oa.analyse_acces([acces("2.2.2.x", 1)] * 31, MAINTENANT)["suspect"]                              # 31 lectures en 1 h
    assert oa.analyse_acces([], MAINTENANT) == {"nombre": 0, "dernier": None, "adresses_24h": 0, "suspect": False, "motif": None}
    assert oa.analyse_acces([{"action": "refus_expiree", "ip_masquee": "9.9.9.x", "date": MAINTENANT}], MAINTENANT)["nombre"] == 0      # un refus n'est pas une lecture


def test_lien_nfc_tient_sur_une_ntag213():
    url_qr = "https://sawalismartsystems.com/officine/ordonnance/" + "a" * 32
    url = oa.url_nfc(url_qr)
    assert url == url_qr + "?src=nfc" and oa.url_nfc(url_qr + "?x=1").endswith("&src=nfc")
    n = oa.taille_ndef_url(url)
    assert 60 < n < 144                                                                                      # tient dans les 144 octets d'une NTAG213
    comp = oa.compatibilite_etiquettes(url)
    assert comp["etiquettes"]["NTAG213"]["tient"] and comp["etiquettes"]["NTAG216"]["capacite"] == 888
    assert not oa.compatibilite_etiquettes("https://exemple.com/" + "x" * 200)["etiquettes"]["NTAG213"]["tient"]


# ---------------------------------------------------------------- routes
@pytest.fixture()
def ctx(monkeypatch):
    pytest.importorskip("reportlab")
    monkeypatch.setenv("FRONTEND_PUBLIC_URL", "https://site.exemple")
    from routes.vidal_ordonnance import attach_vidal_ordonnance_routes
    db = mongomock_motor.AsyncMongoMockClient()[f"lot383_{time.time_ns()}"]
    utilisateur = {"id": "med1", "email": "med@exemple.test", "full_name": "Dr TEST", "role": "medecin"}

    async def courant():
        return utilisateur

    app = FastAPI(); api = APIRouter(prefix="/api")
    attach_vidal_ordonnance_routes(api=api, db=db, get_current_user=courant)
    app.include_router(api)
    with TestClient(app) as client:
        yield client, db, utilisateur


def _emettre(client, db):
    r = client.post("/api/vidal/ordonnance/generate", json={"patient_name": "PATIENT SECRET", "patient": {"gender": "FEMALE"}, "lines": LIGNES})
    assert r.status_code == 200
    oid = r.headers["x-ordonnance-id"]
    import asyncio
    doc = asyncio.get_event_loop().run_until_complete(db.vidal_ordonnances.find_one({"id": oid}))
    return oid, doc["qr_token"]


def _journal(client, oid):
    return client.get(f"/api/vidal/ordonnances/{oid}/acces").json()


def test_emission_validite_lecture_et_journal_des_canaux(ctx):
    client, db, _ = ctx
    oid, jeton = _emettre(client, db)
    import asyncio
    doc = asyncio.get_event_loop().run_until_complete(db.vidal_ordonnances.find_one({"id": oid}))
    assert doc["revoquee"] is False and (doc["expire_le"] - doc["created_at"]).days == 30                    # validité de 30 jours
    vue = client.get(f"/api/public/vidal-ordonnance/{jeton}?src=nfc").json()                                # lecture par étiquette NFC
    assert vue["etat_acces"]["code"] == "ok" and vue["cloturee"] is False and "PATIENT SECRET" not in str(vue)
    client.get(f"/api/public/vidal-ordonnance/{jeton}", headers={"x-forwarded-for": "41.202.10.57, 10.0.0.1"})   # lecture par QR
    j = _journal(client, oid)
    assert [e["canal"] for e in reversed(j["evenements"])] == ["nfc", "qr"] and j["evenements"][0]["ip_masquee"] == "41.202.10.x"
    assert j["resume"]["nombre"] == 2 and not j["resume"]["suspect"]


def test_expiration_revocation_retablissement(ctx):
    client, db, _ = ctx
    oid, jeton = _emettre(client, db)
    import asyncio
    boucle = asyncio.get_event_loop()
    # expirée : 410 + journal
    boucle.run_until_complete(db.vidal_ordonnances.update_one({"id": oid}, {"$set": {"expire_le": datetime.now(UTC) - timedelta(days=1)}}))
    r = client.get(f"/api/public/vidal-ordonnance/{jeton}")
    assert r.status_code == 410 and "expiré" in r.json()["detail"]
    assert client.get(f"/api/vidal/ordonnances/{oid}/nfc").status_code == 409                                  # pas d'étiquette pour une ordonnance expirée
    boucle.run_until_complete(db.vidal_ordonnances.update_one({"id": oid}, {"$set": {"expire_le": datetime.now(UTC) + timedelta(days=5)}}))
    assert client.get(f"/api/public/vidal-ordonnance/{jeton}").status_code == 200
    # révoquée par le médecin : lecture et service refusés (410)
    assert client.post(f"/api/vidal/ordonnances/{oid}/revoquer", json={"motif": "perdue"}).status_code == 200
    assert client.get(f"/api/public/vidal-ordonnance/{jeton}").status_code == 410
    corps = {"nom_officine": "Pharmacie TEST", "lignes": [{"index": 0, "statut": "servi", "quantite_servie": 1}]}
    r = client.post(f"/api/public/vidal-ordonnance/{jeton}/servir", json=corps)
    assert r.status_code == 410 and "annulée" in r.json()["detail"]
    lst = client.get("/api/vidal/ordonnances").json()["ordonnances"][0]
    assert lst["revoquee"] and lst["etat_acces"]["code"] == "revoquee"
    # rétablie
    assert client.post(f"/api/vidal/ordonnances/{oid}/retablir").status_code == 200
    assert client.get(f"/api/public/vidal-ordonnance/{jeton}").status_code == 200
    actions = [e["action"] for e in _journal(client, oid)["evenements"]]
    assert {"refus_expiree", "refus_revoquee", "revoquee", "retablie", "lecture"} <= set(actions)


def test_cloture_quand_entierement_servie(ctx):
    client, db, _ = ctx
    oid, jeton = _emettre(client, db)
    partiel = {"nom_officine": "Pharmacie A", "lignes": [{"index": 0, "statut": "servi", "quantite_servie": 1}]}
    r = client.post(f"/api/public/vidal-ordonnance/{jeton}/servir?src=nfc", json=partiel).json()
    assert r["etat"] == "partielle" and r["cloturee"] is False                                                # une ligne sur deux : encore servable
    reste = {"nom_officine": "Pharmacie B", "lignes": [{"index": 1, "statut": "servi", "quantite_servie": 1}]}
    r = client.post(f"/api/public/vidal-ordonnance/{jeton}/servir", json=reste).json()
    assert r["etat"] == "servie" and r["cloturee"] is True
    refus = client.post(f"/api/public/vidal-ordonnance/{jeton}/servir", json=reste)
    assert refus.status_code == 409 and "entièrement servie" in refus.json()["detail"]
    lecture = client.get(f"/api/public/vidal-ordonnance/{jeton}")
    assert lecture.status_code == 200 and lecture.json()["cloturee"] is True                                   # toujours lisible
    j = _journal(client, oid)
    assert [e["officine"] for e in j["evenements"] if e["action"] == "service"] == ["PHARMACIE B", "PHARMACIE A"]


def test_lien_nfc_et_acces_reserves_au_medecin(ctx):
    client, db, utilisateur = ctx
    oid, jeton = _emettre(client, db)
    nfc = client.get(f"/api/vidal/ordonnances/{oid}/nfc").json()
    assert nfc["url"] == f"https://site.exemple/officine/ordonnance/{jeton}?src=nfc" and nfc["etiquettes"]["NTAG213"]["tient"]
    assert client.post(f"/api/vidal/ordonnances/{oid}/nfc-ecrite").status_code == 200
    assert "etiquette_ecrite" in [e["action"] for e in _journal(client, oid)["evenements"]]
    utilisateur["id"] = "autre_medecin"                                                                       # un autre médecin n'a accès à rien
    for methode, chemin in [("get", f"/api/vidal/ordonnances/{oid}/nfc"), ("get", f"/api/vidal/ordonnances/{oid}/acces"), ("post", f"/api/vidal/ordonnances/{oid}/revoquer"), ("post", f"/api/vidal/ordonnances/{oid}/retablir")]:
        assert getattr(client, methode)(chemin).status_code == 404
