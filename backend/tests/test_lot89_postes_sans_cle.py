"""Lot 89 — alerte « postes Loois sans clé client valable » (administrateur et superviseur).
Le signal de présence note l'état de la clé de chaque poste Loois ; la liste n'affiche que les postes à corriger.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot89_postes_sans_cle.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.loois_postes_sans_cle as psc  # noqa: E402
import routes.versions_deployees as vd  # noqa: E402

ROLE = {"role": "admin"}   # rôle de l'utilisateur factice (modifié par les tests)


def client(db):
    """Application minimale : signal de présence (lot 65) + routes du lot 89."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    async def utilisateur():
        return {"id": "u1", "email": "u1@test", **ROLE}

    api = APIRouter(prefix="/api")
    vd.setup_versions_deployees_routes(db=db, api=api, get_current_user=utilisateur)
    psc.setup_loois_postes_sans_cle_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_etat_de_la_cle():
    """client / commune / absente / refusée selon l'en-tête et l'identité trouvée."""
    assert psc.statut_cle("LK-x", {"type": "client"}) == "client"
    assert psc.statut_cle("commune", {"type": "commune"}) == "commune"
    assert psc.statut_cle(None, None) == "absente" and psc.statut_cle("  ", None) == "absente"
    assert psc.statut_cle("LK-revoquee", None) == "refusee"
    assert psc.est_application_loois("Loois Notification") and not psc.est_application_loois("WinDev Caisse")


def test_depuis_garde_tant_que_l_etat_ne_change_pas():
    """La date « depuis » ne bouge pas tant que l'état reste le même."""
    a = psc.champs_presence("absente", None, "2026-10-09T10:00:00+00:00")
    b = psc.champs_presence("absente", a, "2026-10-09T10:05:00+00:00")
    c = psc.champs_presence("refusee", b, "2026-10-09T10:10:00+00:00")
    assert b["cle_statut_depuis"] == "2026-10-09T10:00:00+00:00"
    assert c["cle_statut_depuis"] == "2026-10-09T10:10:00+00:00"


def test_regroupement_par_machine_pire_etat():
    """Une ligne par machine, pire état retenu ; machines « client » exclues ; en ligne d'abord."""
    m = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    vu = lambda minutes: (m - timedelta(minutes=minutes)).isoformat()  # noqa: E731
    fiches = [
        {"machine": "PC-A", "composant": "Loois", "cle_statut": "commune", "vu_le": vu(2)},
        {"machine": "pc-a", "composant": "Loois Notification", "cle_statut": "refusee", "vu_le": vu(3)},
        {"machine": "PC-B", "composant": "Loois", "cle_statut": "client", "vu_le": vu(1)},
        {"machine": "PC-C", "composant": "Loois", "cle_statut": "absente", "vu_le": vu(600)},
    ]
    postes = psc.regrouper(fiches, m)
    assert [p["machine"] for p in postes] == ["PC-A", "PC-C"]
    assert postes[0]["statut"] == "refusee" and postes[0]["en_ligne"] and len(postes[0]["composants"]) == 2
    assert postes[1]["en_ligne"] is False


def test_signal_puis_alerte_et_reglage(monkeypatch):
    """Postes sans clé / clé commune listés ; superviseur autorisé à lire, pas à régler ; autres rôles refusés."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot89"]
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-commune")
    ROLE["role"] = "admin"
    c = client(db)
    signal = lambda machine, **h: c.post("/api/presence-logiciel", headers=h,  # noqa: E731
                                         json={"application": "Loois", "version": "1.2", "machine": machine})
    assert signal("PC-SANS").status_code == 200
    assert signal("PC-COMMUNE", **{"X-Cle-Loois": "cle-commune"}).status_code == 200
    assert signal("PC-FAUSSE", **{"X-Cle-Loois": "LK-inconnue"}).status_code == 200
    r = c.get("/api/admin/loois-postes-sans-cle").json()
    assert r["actif"] is True and r["total"] == 3
    assert {p["machine"]: p["statut"] for p in r["postes"]} == {"PC-SANS": "absente", "PC-COMMUNE": "commune", "PC-FAUSSE": "refusee"}

    ROLE["role"] = "superviseur"
    assert c.get("/api/admin/loois-postes-sans-cle").status_code == 200
    assert c.put("/api/admin/loois-postes-sans-cle/reglage", json={"actif": False}).status_code == 403
    ROLE["role"] = "client"
    assert c.get("/api/admin/loois-postes-sans-cle").status_code == 403

    ROLE["role"] = "admin"
    assert c.put("/api/admin/loois-postes-sans-cle/reglage", json={"actif": False}).json()["actif"] is False
    assert c.get("/api/admin/loois-postes-sans-cle").json()["actif"] is False
