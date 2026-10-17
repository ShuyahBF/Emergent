"""Lot 225 — audit d'utilisation des collections MongoDB (lecture seule, en un clic).

  - statuts VIDE / ACTIVE / PEU ACTIVE / INACTIVE / INCONNUE d'après l'_id et les champs date (mises à jour comprises) ;
  - une collection citée dans le code n'est jamais proposée à la suppression ;
  - le calcul part en arrière-plan : la requête de lancement ne l'attend pas ;
  - le rapport est gardé dans `settings` (aucune nouvelle collection) et s'exporte en CSV ; accès réservé au super-admin.
"""
import asyncio
import time
from datetime import datetime, timezone

import mongomock_motor
import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routes import audit_collections_mongo as ac

MAINTENANT = datetime(2026, 10, 17, tzinfo=timezone.utc)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _base():
    cli = mongomock_motor.AsyncMongoMockClient()
    return cli["sawali"], cli


def _oid(annee, mois, jour):
    return ObjectId.from_datetime(datetime(annee, mois, jour))


def test_statuts_et_mise_a_jour_recente():
    db, _ = _base()
    run(db.vieille.insert_one({"_id": _oid(2025, 1, 1), "x": 1}))
    run(db.active.insert_one({"_id": _oid(2026, 10, 10), "x": 1}))
    run(db.peu.insert_one({"_id": _oid(2026, 6, 1), "x": 1}))
    # _id ancien MAIS mise à jour récente (texte ISO) → ACTIVE ; l'échéance future est ignorée
    run(db.maj.insert_one({"_id": _oid(2025, 1, 1), "updated_at": "2026-10-15T08:00:00Z", "echeance": "2027-01-01"}))
    run(db.sans_date.insert_one({"_id": "abc", "x": 1}))
    attendu = {"vieille": "INACTIVE", "active": "ACTIVE", "peu": "PEU ACTIVE", "maj": "ACTIVE", "sans_date": "INCONNUE"}
    for nom, statut in attendu.items():
        res = run(ac.analyser_collection(db, nom, MAINTENANT))
        assert ac.classer(res, MAINTENANT)[0] == statut, nom
    vide = {"collection": "v", "documents": 0, "derniere_insertion": None, "derniere_date_champ": None}
    assert ac.classer(vide, MAINTENANT)[0] == "VIDE"


def test_collection_citee_dans_le_code_jamais_candidate():
    # `settings` est citée partout dans le code : même vide, jamais « Candidate »
    assert ac.cite_dans_le_code("settings") is True
    assert ac.cite_dans_le_code("collection_qui_n_existe_nulle_part_xyz") is False
    assert ac.verdict("VIDE", True, None, True) == "Citée dans le code : à garder"
    assert ac.verdict("INACTIVE", False, None, True) == "Candidate à la suppression"
    assert ac.verdict("INACTIVE", False, 12, True).startswith("Candidate (lue récemment")
    assert ac.verdict("ACTIVE", False, None, True) == "À garder"
    # autre plateforme : le code n'est pas ici → jamais « Candidate »
    assert ac.verdict("INACTIVE", None, None, False).startswith("À vérifier")


def test_audit_complet_resume_et_csv():
    db, cli = _base()
    run(db.vieille_orpheline_xyz.insert_one({"_id": _oid(2025, 1, 1), "x": 1}))
    run(db.settings.insert_one({"_id": "global", "x": 1}))
    run(cli["albarka"].docs.insert_one({"_id": _oid(2024, 1, 1)}))
    rapport = run(ac.auditer(db, MAINTENANT))
    par = {(l["base"], l["collection"]): l for l in rapport["lignes"]}
    assert par[("sawali", "vieille_orpheline_xyz")]["verdict"] == "Candidate à la suppression"
    assert par[("albarka", "docs")]["verdict"].startswith("À vérifier")        # autre plateforme
    assert rapport["resume"]["total_collections"] == 3 and rapport["resume"]["plafond"] == 500
    assert rapport["resume"]["candidates"] == 1
    texte = ac.csv_rapport(rapport)
    assert texte.startswith("﻿") and "vieille_orpheline_xyz" in texte and ";" in texte


def _app(db, super_admin=True):
    async def sa():
        if not super_admin:
            raise HTTPException(403, "Réservé")
        return {"email": "x"}
    app = FastAPI()
    app.include_router(ac.make_audit_mongo_router(db=db, get_super_admin=sa), prefix="/api")
    return TestClient(app)


def test_lancement_en_arriere_plan_rapport_dans_settings_et_acces(monkeypatch):
    db, _ = _base()
    run(db.vieille_orpheline_xyz.insert_one({"_id": _oid(2025, 1, 1)}))
    # on ralentit l'audit pour prouver que la requête de lancement n'attend pas la fin du calcul
    vrai = ac.auditer

    async def lent(d, maintenant=None):
        await asyncio.sleep(0.4)
        return await vrai(d, maintenant)
    monkeypatch.setattr(ac, "auditer", lent)
    monkeypatch.delenv("ATLAS_API_KEYS", raising=False)
    ac._ETAT.update(en_cours=False)

    async def scenario():
        from httpx import ASGITransport, AsyncClient
        app = FastAPI()
        async def sa():
            return {"email": "x"}
        app.include_router(ac.make_audit_mongo_router(db=db, get_super_admin=sa), prefix="/api")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            t0 = time.monotonic()
            r = await c.post("/api/admin/audit-mongo/lancer")
            assert r.status_code == 200 and time.monotonic() - t0 < 0.3     # répond tout de suite
            assert (await c.get("/api/admin/audit-mongo/etat")).json()["en_cours"] is True
            await asyncio.sleep(0.9)
            assert (await c.get("/api/admin/audit-mongo/etat")).json()["en_cours"] is False
            rap = (await c.get("/api/admin/audit-mongo/rapport")).json()
            assert rap["rapport"]["resume"]["total_collections"] >= 1 and rap["atlas_configure"] is False
            assert (await c.get("/api/admin/audit-mongo/rapport.csv")).status_code == 200
    run(scenario())
    assert run(db.settings.find_one({"_id": ac.ID_RAPPORT}))["rapport"]["base_sawali"] == "sawali"   # dans `settings`
    # accès refusé à un compte qui n'est pas super-admin
    assert _app(db, super_admin=False).post("/api/admin/audit-mongo/lancer").status_code == 403


def test_cles_atlas_et_hote(monkeypatch):
    monkeypatch.setenv("ATLAS_API_KEYS", "pub1:priv1, pub2:priv2,invalide")
    assert ac._cles_atlas() == [("pub1", "priv1"), ("pub2", "priv2")]
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://user:secret@Cluster0.4hskkey.mongodb.net/?appName=Cluster0")
    assert ac._hote_courant() == "cluster0.4hskkey.mongodb.net"      # jamais d'identifiants
