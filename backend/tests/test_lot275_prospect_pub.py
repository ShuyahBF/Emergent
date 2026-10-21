"""Lot 275 — les contacts qui répondent à une publicité Facebook sont marqués « Prospect ».
Lancer : cd backend && python -m pytest tests/test_lot275_prospect_pub.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from routes import marquage_prospect_pub as m  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_reponse_publicitaire():
    assert m.reponse_publicitaire({"referral": {"source_type": "ad", "headline": "Promo"}})
    assert m.reponse_publicitaire({"type": "text"}, sur_ligne_prospects=True)
    assert not m.reponse_publicitaire({"type": "text"})
    assert not m.reponse_publicitaire(None)


def test_reglage_actif_par_defaut():
    assert m.actif({}) and m.actif(None)
    assert not m.actif({"liluvine_wa_prospect_pub_marquage": False})


def test_marquage_contact_sans_doublon_ni_utilisateur_systeme():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot275"]
    lancer(db.directory_contacts.insert_many([
        {"id": "a", "name": "Awa", "tags": []},
        {"id": "b", "name": "Boni", "tags": ["vip"]},
        {"id": "c", "name": "Déjà", "tags": ["prospect"]},
        {"id": "d", "name": "Équipe", "tags": ["utilisateur-système"], "wa_user_link": "u1"},
        {"id": "e", "name": "Sans tags"},
    ]))
    assert lancer(m.marquer_contact(db, "a")) is True
    assert lancer(m.marquer_contact(db, "b")) is True
    assert lancer(m.marquer_contact(db, "c")) is False          # déjà marqué : aucun doublon
    assert lancer(m.marquer_contact(db, "d")) is False          # utilisateur du système : jamais
    assert lancer(m.marquer_contact(db, "e")) is True
    assert lancer(m.marquer_contact(db, None)) is False
    tags = {c["id"]: c.get("tags") for c in lancer(db.directory_contacts.find({}, {"_id": 0}).to_list(10))}
    assert tags["a"] == ["prospect"] and tags["b"] == ["vip", "prospect"] and tags["c"] == ["prospect"]
    assert tags["d"] == ["utilisateur-système"]
