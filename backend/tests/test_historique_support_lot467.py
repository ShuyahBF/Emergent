"""Lot 467 — bloc « Chat interne » de l'Historique Conversation : sessions d'assistance avec durée, messages rattachés à leur session, PDF et CSV, droits.
Aucun accès réseau (Mongo simulé)."""
import asyncio
import os
import shutil
import subprocess
from datetime import datetime, timezone

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot467")

import mongomock_motor
import pytest

import historique_support as hs


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_duree_lisible_et_calcul():
    assert hs.duree_fr(None) == "—" and hs.duree_fr(45) == "45 s" and hs.duree_fr(754) == "12 min 34 s" and hs.duree_fr(3725) == "1 h 02 min"
    s = {"acceptee_le": "2026-11-26T09:00:00+00:00", "terminee_le": "2026-11-26T09:12:34+00:00"}
    assert hs.duree_session(s, datetime.now(timezone.utc)) == 754
    assert hs.duree_session({"acceptee_le": None}, datetime.now(timezone.utc)) is None                   # jamais acceptée : pas de durée


@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot467"]
    run(d.support_loois_sessions.insert_many([
        {"id": "s1", "poste_id": "p1", "poste_nom": "XERVEUR", "client_nom": "Ecole des Métiers", "statut": "terminee", "ticket_number": "EDM-2026-0001", "acceptee_par_nom": "Admin",
         "demande_le": "2026-11-25T09:00:00+00:00", "acceptee_le": "2026-11-25T09:01:00+00:00", "terminee_le": "2026-11-25T09:13:00+00:00"},
        {"id": "s2", "poste_id": "p1", "poste_nom": "XERVEUR", "client_nom": "ecole des métiers", "statut": "terminee", "ticket_number": "EDM-2026-0002", "acceptee_par_nom": "Admin",
         "demande_le": "2026-11-26T10:00:00+00:00", "acceptee_le": "2026-11-26T10:02:00+00:00", "terminee_le": "2026-11-26T10:32:00+00:00"},
        {"id": "s3", "poste_id": "p2", "poste_nom": "PC-DIALYSE", "client_nom": "Ecole des Métiers", "statut": "refusee", "demande_le": "2026-11-26T11:00:00+00:00",
         "refusee_le": "2026-11-26T11:01:00+00:00"},
        {"id": "s4", "poste_id": "p9", "poste_nom": "AUTRE", "client_nom": "Autre client", "statut": "terminee", "demande_le": "2026-11-26T11:00:00+00:00"},
    ]))
    run(d.internal_chat_messages.insert_many([
        {"id": "m1", "client_id": "support-loois", "sender_id": "p1", "recipient_id": "x", "text": "Bonjour, aide svp", "created_at": "2026-11-25T09:00:30+00:00"},
        {"id": "m2", "client_id": "support-loois", "sender_id": "u-admin", "sender_name": "Administrateur SAWALI", "recipient_id": "p1", "text": "Je prends la main", "created_at": "2026-11-25T09:02:00+00:00"},
        {"id": "m3", "client_id": "support-loois", "sender_id": "p1", "text": "Merci", "created_at": "2026-11-26T10:05:00+00:00"},
        {"id": "m4", "client_id": "support-loois", "sender_id": "p1", "text": "message hors session", "created_at": "2026-11-20T10:05:00+00:00"},
        {"id": "m5", "client_id": "support-loois", "sender_id": "p9", "text": "autre client", "created_at": "2026-11-26T11:05:00+00:00"},
        {"id": "m6", "client_id": "autre-espace", "sender_id": "p1", "text": "autre espace", "created_at": "2026-11-26T10:06:00+00:00"},
    ]))
    return d


def test_postes_du_client_sans_casse(db):
    assert run(hs.postes_du_client(db, "ECOLE DES METIERS")) == []              # accents : comparaison stricte sur le libellé enregistré (majuscules indifférentes)
    assert run(hs.postes_du_client(db, "")) == []
    p = run(hs.postes_du_client(db, "ecole des métiers"))
    assert [(x["nom"], x["sessions"]) for x in p] == [("PC-DIALYSE", 1), ("XERVEUR", 2)]


def test_collecte_sessions_durees_et_messages_rattaches(db):
    sessions, lignes, tronque = run(hs.collecter(db, client="Ecole des Métiers", poste_ids=["p1", "p2"]))
    assert [s["id"] for s in sessions] == ["s3", "s2", "s1"]                                                  # plus récente d'abord
    assert {s["id"]: s["duree"] for s in sessions} == {"s1": "12 min 00 s", "s2": "30 min 00 s", "s3": "—"}
    assert [m["id"] for m in lignes] == ["m3", "m2", "m1"] and tronque is False                               # plus récent d'abord ; m4 hors session, m5 autre client, m6 autre espace
    assert lignes[0]["session"] == "EDM-2026-0002" and lignes[0]["sens"] == "Poste" and lignes[1]["sens"] == "Administrateur SAWALI"
    assert hs.total_durees(sessions) == 12 * 60 + 30 * 60
    _, l2, _ = run(hs.collecter(db, client="Ecole des Métiers", poste_ids=["p1"], du="2026-11-26", au="2026-11-26"))
    assert [m["id"] for m in l2] == ["m3"]                                                                    # période = date de la demande de la session


def test_csv_et_neutralisation(db):
    sessions, lignes, _ = run(hs.collecter(db, client="Ecole des Métiers", poste_ids=["p1"]))
    lignes[0]["message"] = "=1+1"
    texte = hs.construire_csv(lignes, sessions).decode("utf-8")
    assert texte.startswith("﻿Date et heure;") and "'=1+1" in texte and "RÉCAPITULATIF" in texte and "Total;2 session(s)" in texte and "42 min 00 s" in texte


@pytest.fixture()
def client_http(db):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    from routes.historique_conversations import setup_historique_conversations_routes
    etat = {"user": {"id": "u1", "role": "admin", "email": "a@x.bf"}}
    app = FastAPI()
    api = APIRouter(prefix="/api")

    async def utilisateur():
        return etat["user"]

    async def perimetre(user):
        return ["t1"]

    async def restrictions(user):
        return {}
    setup_historique_conversations_routes(db=db, api=api, get_current_user=utilisateur, resolve_visible_client_ids=perimetre, resolve_content_restrictions=restrictions)
    app.include_router(api)
    return TestClient(app), etat, db


def test_routes_json_pdf_csv_et_droits(client_http):
    c, etat, db = client_http
    corps = {"client": "Ecole des Métiers", "poste_ids": ["p1", "p2"]}
    r = c.post("/api/me/liluvine-historique-support", json=corps)
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 3 and d["duree_totale"] == "42 min 00 s" and len(d["sessions"]) == 3 and d["postes"] == ["PC-DIALYSE", "XERVEUR"]
    assert c.get("/api/me/liluvine-historique-support/postes", params={"client": "Ecole des Métiers"}).json()[0]["nom"] == "PC-DIALYSE"
    assert c.get("/api/me/liluvine-historique-support/clients").json() == [{"client": "Autre client", "sessions": 1}, {"client": "Ecole des Métiers", "sessions": 3}]
    pdf = c.post("/api/me/liluvine-historique-support/pdf", json=corps)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    if shutil.which("pdftotext"):
        t = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf.content, capture_output=True).stdout.decode("utf-8", "ignore")
        assert "chat interne" in t and "42 min 00 s" in t and "EDM-2026-0002" in t and "Liluvine" in t
    csv = c.post("/api/me/liluvine-historique-support/csv", json=corps)
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf")
    assert c.post("/api/me/liluvine-historique-support", json={"client": "", "poste_ids": []}).status_code == 422
    etat["user"] = {"id": "u2", "role": "client", "email": "c@x.bf"}
    assert c.post("/api/me/liluvine-historique-support", json=corps).status_code == 403
    assert c.get("/api/me/liluvine-historique-support/postes", params={"client": "x"}).status_code == 403
