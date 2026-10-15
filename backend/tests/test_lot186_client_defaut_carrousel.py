"""Lot 186 — client par défaut (SAWALI-2S) pour les tickets de Liluvine et compte rendu WhatsApp des envois de carrousels.
Lancer : cd backend && python -m pytest tests/test_lot186_client_defaut_carrousel.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.offre_client as oc  # noqa: E402
from routes.carrousel_notification import texte_envoi_carrousel  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _db(comptes):
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    lancer(db.users.insert_many(comptes))
    return db


COMPTES = [
    {"id": "u-vieux", "company": "sawali-2s", "role": "client", "created_at": "2025-01-01"},
    {"id": "u-admin", "company": "SAWALI-2S", "role": "admin", "created_at": "2026-01-01",
     "offre_client": [{"nom": "Aizenta", "type": "logiciel"}]},
    {"id": "u-primaire", "company": "SAWALI-2S", "role": "superviseur", "is_primary_client": True, "created_at": "2026-02-01"},
    {"id": "u-autre", "company": "Autre SA", "role": "admin", "created_at": "2024-01-01"},
]


def test_client_par_defaut_est_le_client_primaire():
    db = _db(COMPTES)
    c = lancer(oc.client_par_defaut(db, {}, None))
    assert c["id"] == "u-primaire" and c["company"] == "SAWALI-2S"             # le client primaire désigné en base
    # société réglée : prioritaire sur le client primaire ; compte qui reçoit la conversation d'abord
    assert lancer(oc.client_par_defaut(db, {"liluvine_wa_client_defaut": "autre sa"}, None))["id"] == "u-autre"
    assert lancer(oc.client_par_defaut(db, {"liluvine_wa_client_defaut": "sawali-2s"}, "u-vieux"))["id"] == "u-vieux"
    assert lancer(oc.client_par_defaut(db, {"liluvine_wa_client_defaut": "Inconnue"}, None)) is None


def test_client_par_defaut_sans_client_primaire_repli_sur_sawali_2s():
    db = _db([c for c in COMPTES if not c.get("is_primary_client")])
    c = lancer(oc.client_par_defaut(db, {}, None))
    assert c["id"] == "u-admin" and c["offre_client"][0]["nom"] == "Aizenta"    # administrateur avant le plus ancien
    assert lancer(oc.client_par_defaut(_db([{"id": "x", "company": "Autre"}]), {}, None)) is None


def test_texte_compte_rendu_carrousel():
    c = {"id": "abcdef1234567", "perimetre": "admin", "expediteur": "SAWALI", "cree_par_nom": "Admin", "modele": "sawali_carrousel_v4",
         "cartes": [{}, {}, {}], "compte": {"total": 10, "envoyes": 8, "echecs": 2}}
    t = texte_envoi_carrousel(c)
    assert "Carrousel WhatsApp envoyé" in t and "administration SAWALI" in t and "3 carte(s)" in t
    assert "envoyés 8" in t and "échecs 2" in t and "Des envois ont échoué" in t and "abcdef12" in t
    ok = texte_envoi_carrousel({**c, "perimetre": "client", "compte": {"total": 4, "envoyes": 4, "echecs": 0}})
    assert "un client" in ok and "Des envois ont échoué" not in ok
    assert "—" in texte_envoi_carrousel({})                                   # campagne incomplète : jamais d'exception
