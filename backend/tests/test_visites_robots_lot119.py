"""Lot 119 — visites de robots venant d'un centre de données (Google Cloud, cleardocks…) : masquées (aucun WhatsApp),
mais comptées dans la synthèse quotidienne de Liluvine. Demande du 12/10/2026.
Lancer : cd backend && python -m pytest tests/test_visites_robots_lot119.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.alertes_connexions as ac  # noqa: E402
import routes.rapport_plateformes as rp  # noqa: E402


def test_centres_de_donnees_reconnus():
    # Les trois visites du 12/10/2026 au matin
    assert ac.est_centre_donnees("Google LLC") and ac.est_centre_donnees("cleardocks LLC")
    assert ac.est_centre_donnees("Amazon.com, Inc.") and ac.est_centre_donnees("Hetzner Online GmbH")
    # Vrais opérateurs : jamais masqués
    for op in ("Moov Africa (Onatel)", "Orange", "Telecel", "CanalBox", "Starlink", None, ""):
        assert not ac.est_centre_donnees(op)


def test_seules_les_visites_anonymes_sont_masquees():
    assert ac.robot_centre_donnees({"type": "visite", "operateur": "Google LLC"})
    # Une connexion à un compte (ou un visiteur identifié) n'est jamais masquée, même via un VPN / cloud
    assert not ac.robot_centre_donnees({"type": "connexion", "utilisateur": "Awa", "operateur": "Google LLC"})
    assert not ac.robot_centre_donnees({"type": "visite", "telephone": "22670000000", "operateur": "Google LLC"})
    assert not ac.robot_centre_donnees({"type": "visite", "operateur": "Orange"})


def test_synthese_compte_les_robots():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["robots119"]

    async def scenario():
        await db.alertes_connexions.insert_many([
            {"code": "zandgo", "le": "2026-10-12T09:02:00+00:00", "robot": True, "operateur": "Google LLC"},
            {"code": "zandgo", "le": "2026-10-12T09:03:00+00:00", "robot": True, "operateur": "cleardocks LLC"},
            {"code": "zandgo", "le": "2026-10-12T09:04:00+00:00", "raison": "robot (centre de données)", "operateur": "Google LLC"},
            {"code": "zandgo", "le": "2026-10-12T09:05:00+00:00", "statut": "envoyee", "operateur": "Orange"},   # vrai visiteur
            {"code": "adlyn", "le": "2026-10-12T09:12:00+00:00", "robot": True, "operateur": "Google LLC"},
        ])
        return await rp.robots_plateforme(db, "zandgo", {"$gte": "2026-10-12", "$lt": "2026-10-13"})

    r = asyncio.run(scenario())
    assert r["nombre"] == 3 and r["hebergeurs"] == ["Google LLC ×2", "cleardocks LLC"]
    ligne = rp.ligne_robots({"robots": r})
    assert "🤖 3 visite(s) de robots masquée(s) (Google LLC ×2, cleardocks LLC)" in ligne
    assert rp.ligne_robots({"robots": {"nombre": 0}}) == ""
