"""Lot 122 — jauge de TAILLE du cluster de copie (Clusterbkp, 512 Mo en gratuit) et alerte WhatsApp à 90 %.
Clients MongoDB simulés (aucun appel réseau). Lancer : cd backend && python -m pytest tests/test_jauge_secours_lot122.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.quota_atlas as qa  # noqa: E402

MO = 1024 * 1024


class BaseSimulee:
    """Base dont dbStats renvoie des tailles fixes (octets)."""
    def __init__(self, data, index):
        self.data, self.index = data, index

    async def command(self, nom):
        assert nom == "dbStats"
        return {"dataSize": self.data, "indexSize": self.index}


class ClientSimule:
    def __init__(self, bases):
        self.bases = bases

    async def list_database_names(self):
        return list(self.bases) + ["admin", "local", "config"]

    def __getitem__(self, nom):
        return self.bases[nom]


def test_reglages_par_defaut_et_bornes():
    assert qa.reglages_secours({}) == {"limite_mo": 512, "seuil_pct": 90}
    assert qa.reglages_secours({"atlas_secours_limite_mo": 1024, "atlas_secours_seuil_pct": 80}) == {"limite_mo": 1024, "seuil_pct": 80}
    assert qa.reglages_secours({"atlas_secours_seuil_pct": 150, "atlas_secours_limite_mo": -3}) == {"limite_mo": 512, "seuil_pct": 90}


def test_taille_et_niveau():
    # Situation du 12/10/2026 : 342 Mo sur 512 Mo (67 %) → orange, pas d'alerte
    client = ClientSimule({"sawali_copie": BaseSimulee(300 * MO, 22 * MO), "albarka_copie": BaseSimulee(18 * MO, 2 * MO)})
    t = asyncio.run(qa.taille_cluster(client))
    assert t["total_mo"] == 342 and [b["nom"] for b in t["bases"]] == ["sawali_copie", "albarka_copie"]
    m = qa.mesure_secours(t, qa.reglages_secours({}))
    assert m["pourcentage"] == 66.8 and m["niveau"] == "attention" and m["alerte"] is False and m["restant_mo"] == 170
    # 470 Mo (91,8 %) → rouge et alerte
    m2 = qa.mesure_secours({"total_mo": 470, "bases": []}, qa.reglages_secours({}))
    assert m2["niveau"] == "plein" and m2["alerte"] is True
    assert "470 Mo sur 512 Mo" in qa.texte_alerte_secours({**m2, "hote": "clusterbkp.x.mongodb.net"})


def test_alerte_une_seule_fois_par_jour(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["lot122"]
    envois = []

    async def mesure(_db):
        return {"configure": True, "total_mo": 470, "limite_mo": 512, "pourcentage": 91.8, "restant_mo": 42,
                "alerte": True, "hote": "clusterbkp"}

    async def envoyer(_db, texte, _quand):
        envois.append(texte)
        return True

    monkeypatch.setattr(qa, "mesurer_secours", mesure)
    monkeypatch.setattr(qa, "_envoyer_alerte", envoyer)
    quand = datetime(2026, 10, 12, 10, 7, tzinfo=timezone.utc)
    assert asyncio.run(qa.surveiller_secours(db, quand))["alerte"] is True
    assert asyncio.run(qa.surveiller_secours(db, quand))["alerte"] is False   # même jour : pas de 2e message
    assert len(envois) == 1


def test_sans_cluster_de_copie_aucune_alerte(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["lot122b"]

    async def mesure(_db):
        return {"configure": False, "limite_mo": 512, "seuil_pct": 90}

    monkeypatch.setattr(qa, "mesurer_secours", mesure)
    assert asyncio.run(qa.surveiller_secours(db))["alerte"] is False
