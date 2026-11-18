"""Lot 441 — type d'un règlement (contractuelle / prestations / achats) : seul « contractuelle » compte dans la couverture du contrat.
Lancer : cd backend && python -m pytest tests/test_lot441_type_reglement.py -q
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from couverture_paiements import _est_paiement_de_contrat, couvert_jusqu_au  # noqa: E402


def pay(d, deb, fin, **extra):
    return {"payment_date": d, "periode_debut": deb, "periode_fin": fin, "created_at": d, **extra}


def test_ancien_paiement_sans_type_compte_comme_avant():
    assert _est_paiement_de_contrat(pay("2026-03-16", "2026-03-16", "2026-04-14"))


def test_types_reglement():
    assert _est_paiement_de_contrat(pay("2026-03-16", None, None, type_reglement="contractuelle"))
    assert not _est_paiement_de_contrat(pay("2026-03-16", None, None, type_reglement="prestations"))
    assert not _est_paiement_de_contrat(pay("2026-03-16", None, None, type_reglement="achats"))


def test_ligne_typee_historique_reste_exclue():
    assert not _est_paiement_de_contrat({"type": "reouverture", "payment_date": "2026-03-16"})


def test_reclasser_un_paiement_retire_sa_couverture():
    a = pay("2026-03-16", "2026-03-16", "2026-04-14")
    b = pay("2026-04-20", "2026-04-15", "2026-05-14")
    assert couvert_jusqu_au([a, b], 30) == date(2026, 5, 14)
    b["type_reglement"] = "achats"                      # ce règlement n'était pas une facture du contrat
    assert couvert_jusqu_au([a, b], 30) == date(2026, 4, 14)
