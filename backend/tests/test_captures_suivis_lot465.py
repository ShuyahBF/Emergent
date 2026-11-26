"""Lot 465 — réglages des captures d'écran annotées dans les suivis : valeurs par défaut, bornes, désactivation. Aucun accès réseau."""
from captures_suivis import LARGEUR_DEFAUT, LARGEUR_MAX, LARGEUR_MIN, reglages_captures


def test_par_defaut_la_fonction_est_active_a_1600_pixels():
    assert reglages_captures({}) == {"actives": True, "largeur_max": LARGEUR_DEFAUT}
    assert reglages_captures(None) == {"actives": True, "largeur_max": LARGEUR_DEFAUT}


def test_desactivation_et_valeurs_absurdes():
    assert reglages_captures({"suivis_captures_actives": False})["actives"] is False
    assert reglages_captures({"suivis_captures_actives": None})["actives"] is True                    # absent / vide = actif
    assert reglages_captures({"suivis_captures_largeur_max": "abc"})["largeur_max"] == LARGEUR_DEFAUT
    assert reglages_captures({"suivis_captures_largeur_max": -5})["largeur_max"] == LARGEUR_DEFAUT
    assert reglages_captures({"suivis_captures_largeur_max": 0})["largeur_max"] == LARGEUR_DEFAUT


def test_la_largeur_est_bornee():
    assert reglages_captures({"suivis_captures_largeur_max": 100})["largeur_max"] == LARGEUR_MIN
    assert reglages_captures({"suivis_captures_largeur_max": 99999})["largeur_max"] == LARGEUR_MAX
    assert reglages_captures({"suivis_captures_largeur_max": "1200.7"})["largeur_max"] == 1200
