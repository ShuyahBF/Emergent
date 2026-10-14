"""Lot 135.3 — statut du contrat fourni à Loois (anonymisation des états PDF si le contrat n'est pas actif).
Lancer : cd backend && python -m pytest tests/test_lot135_3_contrat_loois.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot135_3")

from routes.loois_synchro import statut_contrat_loois  # noqa: E402

AUJOURDHUI = datetime(2026, 10, 13, tzinfo=timezone.utc)


def test_aucun_compte_lie_est_anonymise():
    # Clé commune ou clé sans compte client : on masque par prudence
    r = statut_contrat_loois(None, AUJOURDHUI)
    assert r["statut"] == "non_lie" and r["anonymiser"] is True and r["actif"] is False


def test_contrat_sans_periodicite_est_actif():
    r = statut_contrat_loois({"id": "c1"}, AUJOURDHUI)
    assert r["statut"] == "sans_echeance" and r["anonymiser"] is False


def test_contrat_a_jour_et_en_retard_de_paiement_restent_clairs():
    a_jour = {"id": "c1", "contract_billing_period": "annual", "last_payment_at": "2026-06-01"}
    assert statut_contrat_loois(a_jour, AUJOURDHUI)["anonymiser"] is False
    expire = {"id": "c1", "contract_billing_period": "monthly", "last_payment_at": "2025-01-01"}
    r = statut_contrat_loois(expire, AUJOURDHUI)
    assert r["statut"] == "expire" and r["actif"] is False and r["anonymiser"] is False   # lot 147 : retard = encore sous contrat


def test_client_suspendu_ou_archive_anonymise():
    for statut, attendu in (("ARCHIVE", "archive"),):
        r = statut_contrat_loois({"id": "c1", "cycle_vie": {"statut": statut}}, AUJOURDHUI)
        assert r["statut"] == attendu and r["anonymiser"] is True
