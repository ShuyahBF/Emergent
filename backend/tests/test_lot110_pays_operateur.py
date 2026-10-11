"""Lot 110 — pays et opérateur de l'adresse IP dans l'alerte WhatsApp de connexion et dans le journal.
Demande du propriétaire (11/10/2026) : « je constate que je ne connais ni le pays ni l'opérateur ».
Service de géolocalisation simulé (aucun appel réseau).
Lancer : cd backend && python -m pytest tests/test_lot110_pays_operateur.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.alertes_connexions as ac  # noqa: E402

# Réponse réelle d'ipwho.is (11/10/2026) pour une IP d'Onatel, réduite aux champs utiles
REPONSE_ONATEL = {"success": True, "country": "Burkina Faso", "country_code": "BF", "city": "Ouagadougou",
                  "flag": {"emoji": "🇧🇫"},
                  "connection": {"asn": 25543, "org": "ONATEL NETWORKS",
                                 "isp": "ONATEL Office National des Telecommunications, PTT"}}


def test_operateurs_reconnus():
    # Libellés techniques des fournisseurs → nom commercial
    assert ac.nom_operateur("ONATEL NETWORKS", "ONATEL Office National…") == "Moov Africa (Onatel)"
    assert ac.nom_operateur("ORANGE COTE D IVOIRE", "Orange Côte d Ivoire") == "Orange"
    assert ac.nom_operateur("Telecel Faso", None) == "Telecel"
    assert ac.nom_operateur("Sonatel", "Orange Senegal") == "Orange (Sonatel)"
    assert ac.nom_operateur("Hetzner Online GmbH", None) == "Hetzner Online GmbH"   # inconnu : libellé brut
    assert ac.nom_operateur(None, "") is None


def test_lecture_reponse_et_drapeau():
    geo = ac.lire_geo(REPONSE_ONATEL)
    assert geo["pays"] == "Burkina Faso" and geo["pays_code"] == "BF" and geo["drapeau"] == "🇧🇫"
    assert geo["operateur"] == "Moov Africa (Onatel)" and geo["ville"] == "Ouagadougou"
    assert ac.lire_geo({"success": False, "message": "Reserved range"}) == {}
    assert ac.drapeau("ci") == "🇨🇮" and ac.drapeau("XYZ") == ""
    assert ac.ip_privee("192.168.1.10") and ac.ip_privee("127.0.0.1") and not ac.ip_privee("154.66.162.235")


def test_texte_et_variable_du_modele():
    quand = datetime(2026, 10, 11, 1, 35, tzinfo=timezone.utc)
    evt = {"type": "connexion", "ip": "154.66.1.2", "utilisateur": "Awa", "pays": "Burkina Faso", "drapeau": "🇧🇫",
           "operateur": "Moov Africa (Onatel)"}
    texte = ac.texte_alerte("ZandGo", evt, quand)
    assert "📍 🇧🇫 Burkina Faso · Moov Africa (Onatel)" in texte
    # {{3}} du modèle Meta approuvé : l'IP suivie du pays et de l'opérateur (le modèle lui-même ne change pas)
    assert ac.variables_modele("ZandGo", evt, quand)[2] == "154.66.1.2 — 🇧🇫 Burkina Faso · Moov Africa (Onatel)"
    # Rien de connu : comportement du lot 109 inchangé
    nu = {"type": "visite", "ip": "41.1.1.1"}
    assert "📍" not in ac.texte_alerte("ZandGo", nu, quand) and ac.variables_modele("ZandGo", nu, quand)[2] == "41.1.1.1"


def test_geolocaliser_cache_et_panne(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    import asyncio
    import httpx

    db = mongomock_motor.AsyncMongoMockClient()["geo"]
    appels = []

    class Rep:
        status_code = 200

        def json(self):
            return REPONSE_ONATEL

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            appels.append(url)
            return Rep()

    monkeypatch.setattr(httpx, "AsyncClient", Client)

    async def scenario():
        g1 = await ac.geolocaliser(db, "154.66.162.235")
        g2 = await ac.geolocaliser(db, "154.66.162.235")      # 2e fois : cache Mongo, pas d'appel
        local = await ac.geolocaliser(db, "10.0.0.5")
        return g1, g2, local

    g1, g2, local = asyncio.run(scenario())
    assert g1["operateur"] == "Moov Africa (Onatel)" and g2 == g1 and len(appels) == 1
    assert local == {"pays": None, "operateur": "Réseau local"}

    class Panne(Client):
        async def get(self, url, params=None):
            raise httpx.ConnectTimeout("délai dépassé")

    monkeypatch.setattr(httpx, "AsyncClient", Panne)
    # Service injoignable : aucun plantage, l'alerte partira sans pays
    assert asyncio.run(ac.geolocaliser(db, "41.2.3.4")) == {}
