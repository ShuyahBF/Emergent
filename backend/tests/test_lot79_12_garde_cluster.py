"""Lot 79.12 — Sauvegarde : refus d'une cible sur le même cluster Atlas que la production.
Lancer : cd backend && python -m pytest tests/test_lot79_12_garde_cluster.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mr = pytest.importorskip("routes.migration_render")
from fastapi import HTTPException  # noqa: E402


def test_meme_cluster_logique_pure():
    # Cas réel du 08/10/2026 : même hôte Cluster0, base « Clusterbkp » → refus
    assert mr.meme_cluster("cluster0.4hskkey.mongodb.net", "CLUSTER0.4hskkey.mongodb.net", None, None)
    # Hôtes différents mais même jeu de réplicas Atlas (alias) → refus
    assert mr.meme_cluster("a.mongodb.net", "b.mongodb.net", "atlas-x-shard-0", "atlas-x-shard-0")
    # Vrai cluster de sauvegarde → accepté
    assert not mr.meme_cluster("cluster0.4hskkey.mongodb.net", "clusterbkp.abcde.mongodb.net", "atlas-a", "atlas-b")
    assert not mr.meme_cluster("?", "?", None, None)


class _Admin:
    def __init__(self, nom):
        self.nom = nom

    async def command(self, _):
        return {"setName": self.nom}


class _Client:
    def __init__(self, nom):
        self.admin = _Admin(nom)


def test_verifier_cluster_different(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://u:p@cluster0.4hskkey.mongodb.net/?x=1")

    class _Db:
        client = _Client("atlas-prod")
    monkeypatch.setattr(mr, "db", _Db())
    boucle = asyncio.new_event_loop()
    # Même hôte que la production → HTTP 400 avec le message clair
    with pytest.raises(HTTPException) as e:
        boucle.run_until_complete(mr.verifier_cluster_different(_Client("atlas-prod"), "mongodb+srv://u:p@cluster0.4hskkey.mongodb.net/"))
    assert e.value.status_code == 400 and "MÊME cluster" in e.value.detail
    # Autre cluster → aucun refus
    boucle.run_until_complete(mr.verifier_cluster_different(_Client("atlas-bkp"), "mongodb+srv://u:p@clusterbkp.abcde.mongodb.net/"))
