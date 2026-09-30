"""Lot 41 — webhook du planning des médecins : numéro collé au nom du patient.
Lancer : cd backend && python -m pytest tests/test_planning_lot41.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes.planning import separer_patient_telephone as separer  # noqa: E402


def test_deux_points_inseres_devant_le_numero():
    # Lot 42 — le séparateur attendu est « : » (et non « ; »)
    assert separer("OUOBA JF 77000155") == ("OUOBA JF : 77000155", "77000155")
    assert separer("OUOBA Jean 77 00 01 55") == ("OUOBA Jean : 77 00 01 55", "77 00 01 55")
    assert separer("OUOBA Jean +226 77000155") == ("OUOBA Jean : +226 77000155", "+226 77000155")
    # Déjà séparé par « : » : inchangé, numéro repris ; « ; » (lot 41) ramené à « : »
    assert separer("OUOBA JF : 77000155") == ("OUOBA JF : 77000155", "77000155")
    assert separer("OUOBA JF:77000155") == ("OUOBA JF : 77000155", "77000155")
    assert separer("OUOBA Jean ; 77000155") == ("OUOBA Jean : 77000155", "77000155")
    # Sans numéro (ou nombre trop court) : inchangé
    assert separer("Fatimata KANE") == ("Fatimata KANE", None)
    assert separer("Chambre 12") == ("Chambre 12", None)
    assert separer("77000155") == ("77000155", None)
