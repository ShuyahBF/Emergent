"""Lot 65 — Versions déployées : signal de présence des logiciels de bureau (Loois…),
regroupement par application et par poste, version des plateformes web via leurs statistiques.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot65_versions_deployees.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.stats_plateformes as sp  # noqa: E402
import routes.versions_deployees as vd  # noqa: E402


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


def client(db):
    """Application FastAPI minimale avec les routes du lot 65 (administrateur factice)."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    async def utilisateur():
        return {"id": "adm", "role": "admin"}

    async def version():
        return {"version": "1.131", "lot": "65", "git_sha": "abc1234"}

    api = APIRouter(prefix="/api")
    vd.setup_versions_deployees_routes(db=db, api=api, get_current_user=utilisateur, lire_version=version)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_nettoyage_du_signal():
    """Champs connus seulement, textes coupés, champs obligatoires contrôlés."""
    f = vd.nettoyer_presence({"application": "Loois", "version": "1.2610.610.44", "machine": "PC-1",
                              "inconnu": "x", "site": "S" * 500})
    assert f["composant"] == "Loois" and "inconnu" not in f and len(f["site"]) == 120
    for mauvais in ({}, {"application": "Loois", "version": "1"}, {"application": "<script>", "version": "1", "machine": "m"}):
        with pytest.raises(ValueError):
            vd.nettoyer_presence(mauvais)


def test_regroupement_en_ligne_et_a_jour():
    """Une entrée par application ; poste en ligne si vu depuis moins de 12 min ; à jour = dernière version."""
    maintenant = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)
    fiches = [
        {"application": "Loois", "machine": "B", "composant": "Loois", "version": "1.2610.610.44",
         "vu_le": (maintenant - timedelta(minutes=3)).isoformat()},
        {"application": "Loois", "machine": "A", "composant": "Loois", "version": "1.2610.610.20",
         "vu_le": (maintenant - timedelta(hours=2)).isoformat()},
        {"application": "Loois", "machine": "C", "composant": "Loois", "version": "1.2609.3012.5",
         "vu_le": (maintenant - timedelta(minutes=1)).isoformat()},
    ]
    [loois] = vd.regrouper_logiciels(fiches, maintenant)
    assert loois["derniere_version"] == "1.2610.610.44"           # comparaison numérique, pas alphabétique
    assert loois["en_ligne"] == 2 and loois["a_jour"] == 1
    assert [p["machine"] for p in loois["postes"]] == ["B", "C", "A"]   # en ligne d'abord, puis par nom


def test_signal_puis_tableau(monkeypatch):
    """Le signal crée puis met à jour UNE fiche par poste ; la clé facultative marque « vérifié »."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot65"]
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-test")
    c = client(db)
    corps = {"application": "Loois", "version": "1.2610.610.20", "machine": "PC-ACCUEIL", "utilisateur": "secretariat"}
    assert c.post("/api/presence-logiciel", json=corps).status_code == 200
    corps["version"] = "1.2610.610.44"
    assert c.post("/api/presence-logiciel", json=corps, headers={"X-Cle-Loois": "cle-test"}).status_code == 200
    assert c.post("/api/presence-logiciel", json={"application": "Loois"}).status_code == 422
    assert lancer(db.presences_logiciels.count_documents({})) == 1
    r = c.get("/api/admin/versions-deployees").json()
    assert r["sawali"]["version"] == "1.131"
    [poste] = r["logiciels"][0]["postes"]
    assert poste["version"] == "1.2610.610.44" and poste["verifie"] is True and poste["en_ligne"] is True
    assert "adresse_ip" not in poste


def test_plafond_des_postes(monkeypatch):
    """Au-delà du plafond, un poste inconnu est refusé ; un poste connu continue de se signaler."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot65b"]
    monkeypatch.setattr(vd, "MAX_POSTES", 1)
    c = client(db)
    assert c.post("/api/presence-logiciel", json={"application": "Loois", "version": "1", "machine": "A"}).status_code == 200
    assert c.post("/api/presence-logiciel", json={"application": "Loois", "version": "1", "machine": "B"}).status_code == 429
    assert c.post("/api/presence-logiciel", json={"application": "Loois", "version": "2", "machine": "A"}).status_code == 200


def test_version_dans_les_statistiques():
    """Une plateforme peut joindre sa version à ses statistiques (facultatif)."""
    r = sp._nettoyer({"indicateurs": [{"cle": "c", "libelle": "Connexions", "valeur": 3}],
                      "version": "1.84", "deploye_le": "2026-10-04T01:35:00Z"})
    assert r["version"] == "1.84" and r["deploye_le"].startswith("2026-10-04")
    assert sp._nettoyer({"indicateurs": [{"cle": "c", "libelle": "C", "valeur": 1}]})["version"] is None
