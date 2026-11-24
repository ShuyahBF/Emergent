"""Lot 455 — consignes de BLOCAGE de créneaux : validation, application à l'heure dite, exceptions (admin / superviseur). Aucun accès réseau."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot455")
from datetime import datetime

import mongomock_motor
import pytest
from fastapi import HTTPException

import consignes_liluvine as cl


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db():
    return mongomock_motor.AsyncMongoMockClient()["test_lot455"]


def _instant(h, m=0):
    return datetime(2026, 11, 25, h, m)


def _proposition(**plus):
    base = {"nature": "blocage", "instruction": "Aucune intervention entre 12h et 13h", "debut": "2026-11-24T00:00", "fin": "2026-11-30T23:59",
            "creneau_debut": "12:00", "creneau_fin": "13:00"}
    base.update(plus)
    return base


def test_creneau_incoherent_est_vide():
    p = cl.valider_proposition(_proposition(creneau_debut="13:00", creneau_fin="12:00"), "x", _instant(8))
    assert p["creneau_debut"] == "" and p["creneau_fin"] == ""


def test_activation_exige_un_creneau(db):
    with pytest.raises(ValueError):
        run(cl.creer(db, _proposition(creneau_debut="", creneau_fin=""), "x", "admin"))


def test_blocage_applique_dans_le_creneau_seulement(db):
    run(cl.creer(db, _proposition(), "x", "admin"))
    toutes = run(cl.charger(db))
    assert cl.creneau_bloque(toutes, _instant(12, 30)) is not None
    assert cl.creneau_bloque(toutes, _instant(13, 0)) is None      # fin exclue
    assert cl.creneau_bloque(toutes, _instant(11, 59)) is None


def test_verifier_demande_refuse_le_client_mais_pas_le_superviseur(db, monkeypatch):
    run(cl.creer(db, _proposition(), "x", "admin"))
    monkeypatch.setattr(cl, "maintenant", lambda: _instant(12, 15))
    with pytest.raises(HTTPException) as e:
        run(cl.verifier_demande(db, {"role": "client"}))
    assert e.value.status_code == 409 and "12:00" in e.value.detail
    run(cl.verifier_demande(db, {"role": "superviseur"}))          # ne lève rien
