"""Lot 350 — une question n'est plus prise pour une commande « ! » parce qu'elle contient un mot-clé."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routes.liluvine_reactions import _fuzzy_match_command as f  # noqa: E402


def test_questions_non_detournees_vers_une_commande():
    # cas réels du 29/10/2026 : ces questions doivent aller à l'IA et à la base de connaissances
    assert f("Quelle est ma disponibilité ?", 70) is None
    assert f("Comment connaître l'adresse IP d'une machine", 70) is None
    assert f("Je voudrais savoir quelles sont vos conditions de livraison et l'adresse de facturation", 70) is None
    assert f("Quel est le prix de la météo des champs pour mon exploitation", 70) is None


def test_vraies_commandes_toujours_reconnues():
    for texte, cmd in [("adresse", "adresse"), ("Adresse ?", "adresse"), ("votre adresse svp", "adresse"), ("pharmacie de garde", "garde"),
                       ("quelle pharmacie de garde", "garde"), ("pharmacies de garde ce soir", "garde"), ("météo", "meteo"),
                       ("meteo demain", "meteo"), ("horaires", "horaires"), ("heures d'ouverture", "horaires"), ("stock", "stock"),
                       ("où êtes vous", "adresse"), ("adres", "adresse")]:
        r = f(texte, 70)
        assert r and r[0] == cmd, (texte, r)
