"""Lot 274 — hors heures de service, Liluvine n'appelle le propriétaire que pour les clients sous contrat.
Relais écrit inchangé. Réutilise la base simulée du lot 67.
Lancer : cd backend && python -m pytest tests/test_lot274_appel_hors_service.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest  # noqa: E402

pytest.importorskip("mongomock_motor")
import routes.appel_proprietaire as ap  # noqa: E402
from tests.test_lot67_appel_proprietaire import env, lancer, message, relais_envoyes  # noqa: E402,F401

NUIT = datetime(2026, 10, 6, 20, 30, tzinfo=timezone.utc)      # mardi 20:30 : fermé (18:00)


def _regler(db, **champs):
    lancer(db.settings.update_one({"_id": "global"}, {"$set": champs}))


def test_reglage_par_defaut_actif():
    assert ap.reglages({})["hors_service_contrat_seul"] is True
    assert ap.reglages({"appel_proprio_hors_service_contrat_seul": False})["hors_service_contrat_seul"] is False


def test_pendant_les_heures_de_service_appel_normal(env):
    r = message(env["db"])
    assert env["appels"] and r["raison"] is None


def test_hors_service_sans_contrat_relais_seul(env):
    env["horloge"]["t"] = NUIT
    r = message(env["db"])
    assert not env["appels"] and relais_envoyes(env["requetes"])
    assert "clients sous contrat" in r["raison"]


def test_hors_service_client_sous_contrat_appel(env):
    env["horloge"]["t"] = NUIT
    lancer(env["db"].users.update_one({"id": "sawali"}, {"$set": {"contract_number": "CT-001"}}))
    message(env["db"])
    assert env["appels"]


def test_hors_service_contrat_suspendu_pas_d_appel(env):
    env["horloge"]["t"] = NUIT
    lancer(env["db"].users.update_one({"id": "sawali"}, {"$set": {
        "contract_number": "CT-001", "cycle_vie": {"statut": "SUSPENDU"}}}))
    message(env["db"])
    assert not env["appels"]


def test_reglage_desactive_ancien_comportement(env):
    env["horloge"]["t"] = NUIT
    _regler(env["db"], appel_proprio_hors_service_contrat_seul=False)
    message(env["db"])
    assert env["appels"]
