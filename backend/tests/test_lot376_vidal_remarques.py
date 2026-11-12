"""Lot 376 — remarques de la démonstration VIDAL : recherche d'une pathologie par son CODE CIM-10 (n°2) (logique pure, sans réseau ni base).
Lancer : cd backend && python -m pytest tests/test_lot376_vidal_remarques.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vidal_v2.referentiels import requete_est_code_cim10, trier_par_code  # noqa: E402

PATHOLOGIES = [
    {"label": "Diabète de type 2 sans complication", "code": "E11.9"},
    {"label": "Hypertension essentielle (primitive)", "code": "I10"},
    {"label": "Hypertension secondaire", "code": "I15.9"},
    {"label": "Infarctus du myocarde", "code": "I21.9"},
    {"label": "Paludisme à Plasmodium falciparum", "code": "B50.9"},
]


def test_une_saisie_qui_ressemble_a_un_code_est_reconnue():
    for ok in ["I10", "i10", "E11", "E11.9", "e119", "B50.9", "A00.1", " I21 "]:
        assert requete_est_code_cim10(ok), ok
    for ko in ["diabète", "hypertension", "paludisme", "12", "I", "ABC", "", "I10 bis", "type 2"]:
        assert not requete_est_code_cim10(ko), ko


def test_les_pathologies_dont_le_code_commence_par_la_saisie_passent_en_premier():
    assert [p["code"] for p in trier_par_code(PATHOLOGIES, "I1")][:2] == ["I10", "I15.9"]
    assert trier_par_code(PATHOLOGIES, "i10")[0]["code"] == "I10"                       # casse ignorée
    assert trier_par_code(PATHOLOGIES, "E119")[0]["code"] == "E11.9"                    # point ignoré
    assert trier_par_code(PATHOLOGIES, "e11.9")[0]["code"] == "E11.9"
    # un mot (pas un code) : liste inchangée, dans l'ordre de VIDAL
    assert trier_par_code(PATHOLOGIES, "diabète") == PATHOLOGIES
    # les autres pathologies ne disparaissent pas : seul l'ordre change
    assert len(trier_par_code(PATHOLOGIES, "I10")) == len(PATHOLOGIES)
