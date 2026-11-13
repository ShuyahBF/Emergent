"""Lot 384 — demandes des plateformes (ALBARKA…) : numéro attribué, relecture signée, traitement par l'administrateur.
Lancer : cd backend && python -m pytest tests/test_lot384_demandes_plateformes.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import time
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import demandes_plateformes as dp  # noqa: E402


def test_numero_et_nettoyage():
    assert dp.numero_demande("albarka", 7) == "DEM-ALBARKA-0007"
    brut = [{"ref_locale": "a", "type": "correction", "texte": " Bug "}, {"ref_locale": "", "type": "correction", "texte": "x"},
            {"ref_locale": "b", "type": "autre", "texte": "x"}, {"ref_locale": "c", "type": "nouveaute", "texte": ""}, "n'importe quoi"]
    assert [d["ref_locale"] for d in dp.nettoyer_envoi(brut)] == ["a"]


def test_traitement_valide():
    j = date(2026, 11, 14)
    assert dp.valider_traitement({"statut": "realisee"}, j)["realisee_le"] == "2026-11-14"        # date du jour par défaut
    assert dp.valider_traitement({"statut": "remontee", "prevue_le": "2026-12-01"}, j)["prevue_le"] == "2026-12-01"
    with pytest.raises(ValueError):
        dp.valider_traitement({"statut": "refusee"}, j)                                           # raison obligatoire
    with pytest.raises(ValueError):
        dp.valider_traitement({"statut": "realisee", "realisee_le": "demain"}, j)
    with pytest.raises(ValueError):
        dp.valider_traitement({"statut": "inconnu"}, j)


def _signer(cle: str, corps: bytes, code: str = "albarka") -> dict:
    ts = str(int(time.time()))
    sig = hmac.new(cle.encode(), f"{ts}.{corps.decode()}".encode(), hashlib.sha256).hexdigest()
    return {"X-Emetteur": code, "X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}


def _appel(c, demandes, cle="cle-albarka"):
    corps = json.dumps({"demandes": demandes}, ensure_ascii=False).encode()
    return c.post("/api/webhook/plateforme-demandes", content=corps, headers=_signer(cle, corps))


def test_parcours_complet():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot384"]
    asyncio.get_event_loop().run_until_complete(db.liluvine_emetteurs.insert_one(
        {"code": "albarka", "nom": "ALBARKA", "secret": "cle-albarka", "actif": True}))
    role = {"v": "admin"}
    app, api = FastAPI(), APIRouter(prefix="/api")
    dp.setup_demandes_plateformes_routes(db=db, api=api, get_current_user=lambda: {"role": role["v"]})
    app.include_router(api)
    c = TestClient(app)
    # Signature obligatoire
    corps = b'{"demandes": []}'
    assert c.post("/api/webhook/plateforme-demandes", content=corps, headers=_signer("mauvaise", corps)).status_code == 401
    # Remontée : numéros attribués dans l'ordre
    r = _appel(c, [{"ref_locale": "l1", "type": "correction", "texte": "Le bulletin déborde", "demandee_le": "2026-11-13T10:00:00+00:00"},
                   {"ref_locale": "l2", "type": "nouveaute", "texte": "Signature électronique"}])
    assert r.status_code == 200, r.text
    assert [(d["ref_locale"], d["numero"], d["statut"]) for d in r.json()["demandes"]] == [("l1", "DEM-ALBARKA-0001", "remontee"), ("l2", "DEM-ALBARKA-0002", "remontee")]
    # Renvoyer la même demande ne crée pas de doublon ; une nouvelle reçoit le numéro suivant
    r = _appel(c, [{"ref_locale": "l1", "type": "correction", "texte": "Le bulletin déborde"}, {"ref_locale": "l3", "type": "correction", "texte": "Autre"}])
    assert [d["numero"] for d in r.json()["demandes"]] == ["DEM-ALBARKA-0001", "DEM-ALBARKA-0002", "DEM-ALBARKA-0003"]
    # Traitement par l'administrateur seulement
    role["v"] = "client"
    assert c.put("/api/admin/plateformes/albarka/demandes/DEM-ALBARKA-0001", json={"statut": "realisee"}).status_code == 403
    role["v"] = "admin"
    assert c.put("/api/admin/plateformes/albarka/demandes/DEM-ALBARKA-0001", json={"statut": "realisee", "realisee_le": "2026-11-15", "commentaire": "Corrigé au lot 385"}).status_code == 200
    assert c.put("/api/admin/plateformes/albarka/demandes/DEM-ALBARKA-0002", json={"statut": "refusee"}).status_code == 422
    assert c.put("/api/admin/plateformes/albarka/demandes/DEM-ALBARKA-0002", json={"statut": "refusee", "commentaire": "Hors périmètre"}).status_code == 200
    assert c.put("/api/admin/plateformes/albarka/demandes/DEM-ALBARKA-0003", json={"statut": "remontee", "prevue_le": "2026-12-01"}).status_code == 200
    assert c.put("/api/admin/plateformes/albarka/demandes/DEM-ALBARKA-0099", json={"statut": "realisee"}).status_code == 404
    # La plateforme relit numéro, statut, commentaire et dates
    d = {x["numero"]: x for x in _appel(c, []).json()["demandes"]}
    assert d["DEM-ALBARKA-0001"]["statut"] == "realisee" and d["DEM-ALBARKA-0001"]["realisee_le"] == "2026-11-15" and d["DEM-ALBARKA-0001"]["commentaire"] == "Corrigé au lot 385"
    assert d["DEM-ALBARKA-0002"]["statut"] == "refusee" and d["DEM-ALBARKA-0003"]["prevue_le"] == "2026-12-01"
    # Recherche côté SAWALI, refusées comprises
    assert [x["numero"] for x in c.get("/api/admin/plateformes/demandes", params={"q": "hors périmètre"}).json()["demandes"]] == ["DEM-ALBARKA-0002"]
    assert len(c.get("/api/admin/plateformes/demandes").json()["demandes"]) == 3
