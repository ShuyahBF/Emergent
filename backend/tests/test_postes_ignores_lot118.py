"""Lot 118 — « Ignorer ce poste » : un poste Loois ignoré ne déclenche plus l'alerte mais reste listé (grisé).
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_postes_ignores_lot118.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.loois_postes_sans_cle as psc  # noqa: E402
from tests.test_lot89_postes_sans_cle import ROLE, client  # noqa: E402  (même application de test que le lot 89)


def test_separer_ignores_cle_normalisee():
    """Comparaison en majuscules ; « . » et « $ » remplacés comme dans la clé enregistrée."""
    postes = [{"machine": "pc-diane"}, {"machine": "srv.local"}, {"machine": "PC-X"}]
    alertent, ignores = psc.separer_ignores(postes, {"PC-DIANE": {"le": "x", "par": "a"}, "SRV_LOCAL": {"le": "y"}})
    assert [p["machine"] for p in alertent] == ["PC-X"]
    assert {p["machine"] for p in ignores} == {"pc-diane", "srv.local"} and all(p["ignore"] for p in ignores)


def test_ignorer_puis_reactiver(monkeypatch):
    """Ignorer retire le poste de l'alerte (il reste dans postes_ignores) ; Réactiver le remet ; admin seulement."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot118"]
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-commune")
    ROLE["role"] = "admin"
    c = client(db)
    for m in ("PC-DIANE", "XERVEUR"):
        c.post("/api/presence-logiciel", json={"application": "Loois", "version": "1.2", "machine": m})

    ROLE["role"] = "superviseur"
    assert c.put("/api/admin/loois-postes-sans-cle/ignorer", json={"machine": "XERVEUR"}).status_code == 403
    ROLE["role"] = "admin"
    assert c.put("/api/admin/loois-postes-sans-cle/ignorer", json={"machine": ""}).status_code == 422
    assert c.put("/api/admin/loois-postes-sans-cle/ignorer", json={"machine": "XERVEUR", "ignorer": True}).status_code == 200
    r = c.get("/api/admin/loois-postes-sans-cle").json()
    assert [p["machine"] for p in r["postes"]] == ["PC-DIANE"] and r["total"] == 1
    assert [p["machine"] for p in r["postes_ignores"]] == ["XERVEUR"] and r["postes_ignores"][0]["ignore_par"] == "u1@test"

    c.put("/api/admin/loois-postes-sans-cle/ignorer", json={"machine": "XERVEUR", "ignorer": False})
    r = c.get("/api/admin/loois-postes-sans-cle").json()
    assert r["total"] == 2 and r["postes_ignores"] == []
