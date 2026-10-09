"""Lot 86 — requêtes des clients : dépôt écrit ou vocal numéroté par client, traitement, lots, évaluation.
Lancer : cd backend && python -m pytest tests/test_lot86_requetes_clients.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import requetes_clients as rc  # noqa: E402


def test_logique_pure():
    assert rc.code_client({"client_code": "albrk"}) == "ALBRK"
    assert rc.code_client({"company": "Cabinet Al Barka"}) == "CAB"
    assert rc.code_client({}) == "CLI"
    assert rc.numero_requete("ALBRK", 7) == "REQ-ALBRK-0007"
    assert rc.tenant_de({"id": "u2", "parent_client_id": "t1"}) == "t1"
    assert rc.est_admin_sawali({"role": "admin"}) and not rc.est_admin_sawali({"role": "admin", "parent_client_id": "t1"})
    with pytest.raises(ValueError):
        rc.nettoyer_requete("inconnue", "x", "", False)
    with pytest.raises(ValueError):
        rc.nettoyer_requete("remarque", "", "", False)
    assert rc.nettoyer_requete("remarque", "", "", True)["titre"] == "Message vocal"
    with pytest.raises(ValueError):
        rc.evaluation_valide(6, "")
    assert rc.resume([{"etat": "terminee", "evaluation": {"note": 4}}, {"etat": "nouvelle"}])["moyenne"] == 4.0


def test_parcours_complet():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot86"]
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.users.insert_one({"id": "t1", "company": "AL BARKA", "client_code": "ALBRK",
                                                   "email": "dg@albarka.bf", "role": "client"}))
    utilisateur = {"v": {"id": "u1", "parent_client_id": "t1", "role": "client", "full_name": "Agent"}}
    envois = []

    async def faux_email(to, sujet, html, texte=""):
        envois.append(("email", to, sujet))
        return True

    async def fausse_transcription(chemin, langue="fr"):
        return "texte dicté"
    app, api = FastAPI(), APIRouter(prefix="/api")
    rc.setup_requetes_clients_routes(db=db, api=api, get_current_user=lambda: utilisateur["v"],
                                     send_email=faux_email, transcrire=fausse_transcription, upload_dir="/tmp")
    app.include_router(api)
    c = TestClient(app)
    # Client : requête écrite puis vocale, numérotées 0001 puis 0002
    r1 = c.post("/api/me/requetes", data={"categorie": "logiciel", "titre": "Facture bloquée", "logiciel": "ALBARKA"})
    assert r1.status_code == 200 and r1.json()["numero"] == "REQ-ALBRK-0001"
    r2 = c.post("/api/me/requetes", data={"categorie": "equipement"},
                files={"audio": ("note.webm", b"0" * 500, "audio/webm")})
    assert r2.json()["numero"] == "REQ-ALBRK-0002" and r2.json()["a_audio"] and r2.json()["transcription"] == "texte dicté"
    assert c.get(f"/api/requetes/{r2.json()['id']}/audio").content == b"0" * 500
    assert c.post(f"/api/me/requetes/{r1.json()['id']}/evaluation", json={"note": 5}).status_code == 409
    assert c.get("/api/admin/requetes").status_code == 403
    # SAWALI : observation, lot, déploiement du lot
    utilisateur["v"] = {"id": "adm", "role": "admin", "full_name": "SAWALI"}
    lot = c.post("/api/admin/requetes-lots", json={"titre": "Corrections factures"}).json()
    p = c.patch(f"/api/admin/requetes/{r1.json()['id']}", json={"observation": "Reproduit", "etat": "en_cours",
                                                                 "lot_id": lot["id"]}).json()
    assert p["etat"] == "en_cours" and p["observations"][0]["texte"] == "Reproduit" and p["lot_numero"] == 1
    d = c.patch(f"/api/admin/requetes-lots/{lot['id']}", json={"etat": "deploye"}).json()
    assert d["clients_prevenus"] == 1 and envois and envois[-1][1] == "dg@albarka.bf"
    liste = c.get("/api/admin/requetes").json()
    assert liste["resume"]["par_etat"]["deployee"] == 1 and liste["resume"]["a_evaluer"] == 1
    # Client : évaluation
    utilisateur["v"] = {"id": "u1", "parent_client_id": "t1", "role": "client", "full_name": "Agent"}
    ev = c.post(f"/api/me/requetes/{r1.json()['id']}/evaluation", json={"note": 4, "commentaire": "Merci"})
    assert ev.status_code == 200
    mes = c.get("/api/me/requetes").json()
    assert mes["resume"]["moyenne"] == 4.0 and mes["resume"]["a_evaluer"] == 0
    # Un autre client ne voit rien
    utilisateur["v"] = {"id": "x", "role": "client"}
    assert c.get("/api/me/requetes").json()["requetes"] == []
    assert c.get(f"/api/requetes/{r2.json()['id']}/audio").status_code == 404
