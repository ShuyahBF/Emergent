"""Lot 86.3 — requêtes clients : accès des superviseurs de SAWALI et saisie d'une requête au nom d'un client.
Lancer : cd backend && python -m pytest tests/test_lot86_3_requetes_superviseur.py -q
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


def test_equipe_sawali():
    assert rc.est_admin_sawali({"role": "admin"})
    assert rc.est_admin_sawali({"role": "superviseur"})                       # ex. support@sawalismartsystems.co
    assert rc.est_admin_sawali({"role": "user", "tracked_role": "Superviseur"})
    assert not rc.est_admin_sawali({"role": "superviseur", "parent_client_id": "t1"})   # rattaché à un client
    assert not rc.est_admin_sawali({"role": "client"})


def test_superviseur_saisit_une_requete_pour_un_client():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot863"]
    asyncio.new_event_loop().run_until_complete(db.users.insert_one({"id": "t1", "company": "AL BARKA", "client_code": "ALBRK", "role": "client"}))
    utilisateur = {"v": {"id": "s1", "role": "superviseur", "full_name": "Support"}}
    app, api = FastAPI(), APIRouter(prefix="/api")
    rc.setup_requetes_clients_routes(db=db, api=api, get_current_user=lambda: utilisateur["v"], upload_dir="/tmp")
    app.include_router(api)
    c = TestClient(app)
    r = c.post("/api/admin/requetes", data={"tenant_id": "t1", "categorie": "remarque", "titre": "Appel du DG"},
               files=[("images", ("c.png", b"\x89PNG" + b"0" * 50, "image/png"))])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["numero"] == "REQ-ALBRK-0001" and d["origine"] == "sawali" and d["auteur_nom"] == "Support (SAWALI)"
    assert len(d["images"]) == 1
    assert c.get("/api/admin/requetes").json()["resume"]["total"] == 1
    assert c.post("/api/admin/requetes", data={"tenant_id": "inconnu", "categorie": "remarque", "titre": "x"}).status_code == 404
    # Un client ne peut ni lister toutes les requêtes ni en saisir pour un autre client
    utilisateur["v"] = {"id": "u9", "role": "client"}
    assert c.get("/api/admin/requetes").status_code == 403
    assert c.post("/api/admin/requetes", data={"tenant_id": "t1", "categorie": "remarque", "titre": "x"}).status_code == 403
