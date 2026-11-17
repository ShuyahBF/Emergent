"""Lot 430 — pièces jointes des demandes : validation stricte, rangement sans nouvelle collection, contenu servi à l'administrateur seulement.
Lancer : cd backend && python -m pytest tests/test_lot430_pieces_jointes.py -q
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import demandes_plateformes as dp  # noqa: E402
from tests.test_lot384_demandes_plateformes import _signer  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100
JPEG = b"\xff\xd8\xff\xe0" + b"y" * 100
PDF = b"%PDF-1.4 " + b"z" * 100


def b64(o: bytes) -> str:
    return base64.b64encode(o).decode()


def piece(octets=PNG, type_="image/png", nom="capture.png"):
    return {"nom": nom, "type": type_, "data": b64(octets)}


def test_pieces_valides_et_refus_stricts():
    ok, motif = dp.nettoyer_pieces([piece(), piece(JPEG, "image/jpeg", "photo.jpg"), piece(PDF, "application/pdf", "cahier.pdf")])
    assert motif is None and [p["taille"] for p in ok] == [len(PNG), len(JPEG), len(PDF)] and all(p["id"] for p in ok)
    assert dp.nettoyer_pieces([])[0] == [] and dp.nettoyer_pieces(None) == ([], None)
    for mauvais, mot in [([piece(PDF, "application/x-msdownload", "a.exe")], "type non accepté"),           # type inconnu
                         ([piece(b"MZ" + b"0" * 50, "image/png", "faux.png")], "ne correspond pas"),         # signature qui ment
                         ([piece(b"x" * (dp.PIECE_MAX_OCTETS + 1), "application/pdf")], "Ko au plus"),       # trop lourde
                         ([{"nom": "a", "type": "image/png", "data": "%%%"}], "illisible"),
                         ([piece()] * (dp.PIECES_MAX + 1), "au plus par demande"),
                         (["texte"], "illisible")]:
        assert dp.nettoyer_pieces(mauvais)[0] == [] and mot in (dp.nettoyer_pieces(mauvais)[1] or "")
    # une seule mauvaise pièce refuse toute la liste
    assert dp.nettoyer_pieces([piece(), piece(b"MZ", "image/png")])[0] == []


def test_nom_nettoye():
    ok, _ = dp.nettoyer_pieces([piece(nom="../../etc/passwd<script>.png")])
    assert "/" not in ok[0]["nom"] and "<" not in ok[0]["nom"]


def _env():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot430"]
    asyncio.get_event_loop().run_until_complete(db.liluvine_emetteurs.insert_one({"code": "albarka", "nom": "ALBARKA", "secret": "cle-albarka", "actif": True}))
    role = {"v": "admin"}
    app, api = FastAPI(), APIRouter(prefix="/api")
    dp.setup_demandes_plateformes_routes(db=db, api=api, get_current_user=lambda: {"role": role["v"]})
    app.include_router(api)
    return TestClient(app), role, db


def envoi(c, corps):
    brut = json.dumps(corps, ensure_ascii=False).encode()
    return c.post("/api/webhook/plateforme-demandes", content=brut, headers=_signer("cle-albarka", brut))


def test_demande_avec_pieces_listes_sans_contenu_et_telechargement_admin():
    c, role, _ = _env()
    r = envoi(c, {"demandes": [{"ref_locale": "l1", "type": "correction", "texte": "Bug d'affichage", "pieces": [piece(), piece(PDF, "application/pdf", "doc.pdf")]}]})
    assert r.status_code == 200 and r.json()["refus"] == []
    vue = r.json()["demandes"][0]
    assert [p["nom"] for p in vue["pieces"]] == ["capture.png", "doc.pdf"] and all("data" not in p for p in vue["pieces"])      # la plateforme ne reçoit pas le contenu en retour
    liste = c.get("/api/admin/plateformes/demandes").json()["demandes"][0]
    assert len(liste["pieces"]) == 2 and all("data" not in p for p in liste["pieces"])
    pid = liste["pieces"][0]["id"]
    f = c.get(f"/api/admin/plateformes/albarka/demandes/{liste['numero']}/pieces/{pid}")
    assert f.status_code == 200 and f.content == PNG and f.headers["content-type"] == "image/png" and f.headers["x-content-type-options"] == "nosniff"
    assert c.get(f"/api/admin/plateformes/albarka/demandes/{liste['numero']}/pieces/inconnue").status_code == 404
    role["v"] = "client"
    assert c.get(f"/api/admin/plateformes/albarka/demandes/{liste['numero']}/pieces/{pid}").status_code == 403


def test_pieces_refusees_la_demande_est_quand_meme_enregistree():
    c, _, _ = _env()
    r = envoi(c, {"demandes": [{"ref_locale": "l1", "type": "nouveaute", "texte": "Idée", "pieces": [piece(b"MZ", "image/png")]}]})
    assert r.json()["demandes"][0]["numero"] == "DEM-ALBARKA-0001" and r.json()["demandes"][0]["pieces"] == []
    assert r.json()["refus"][0]["ref_locale"] == "l1" and "Pièces jointes refusées" in r.json()["refus"][0]["motif"]


def test_modification_remplace_les_pieces_et_plafond_par_plateforme(monkeypatch):
    c, _, _ = _env()
    envoi(c, {"demandes": [{"ref_locale": "l1", "type": "correction", "texte": "Un", "pieces": [piece()]}]})
    r = envoi(c, {"modifications": [{"ref_locale": "l1", "type": "correction", "texte": "Un modifié", "pieces": [piece(JPEG, "image/jpeg", "b.jpg")]}]})
    assert [p["nom"] for p in r.json()["demandes"][0]["pieces"]] == ["b.jpg"]
    r = envoi(c, {"modifications": [{"ref_locale": "l1", "type": "correction", "texte": "Un modifié", "pieces": []}]})        # liste vide = pièces retirées
    assert r.json()["demandes"][0]["pieces"] == []
    monkeypatch.setattr(dp, "PIECES_TOTAL_MAX", 150)                                                                          # plafond minuscule pour le test
    envoi(c, {"demandes": [{"ref_locale": "l2", "type": "correction", "texte": "Deux", "pieces": [piece()]}]})
    r = envoi(c, {"demandes": [{"ref_locale": "l3", "type": "correction", "texte": "Trois", "pieces": [piece()]}]})
    assert "épuisée" in r.json()["refus"][0]["motif"] and r.json()["demandes"][-1]["pieces"] == []
