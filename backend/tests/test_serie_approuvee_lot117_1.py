"""Lot 117.1 — série de carrousel déjà approuvée : détection et adresse réelle du bouton."""
from routes.carrousel_whatsapp import series_carrousel_approuvees, url_bouton_reelle

CARROUSEL = [{"type": "BODY", "text": "x"},
             {"type": "CAROUSEL", "cards": [{"components": [
                 {"type": "HEADER", "format": "IMAGE"},
                 {"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://s.com/api/public/carrousel/l/{{1}}"}]}]}]}]


def _m(nom, statut="APPROVED", langue="fr", comps=CARROUSEL):
    return {"name": nom, "status": statut, "language": langue, "components": comps}


def test_series_approuvees():
    modeles = [_m("swl_00001_2"), _m("swl_00001_3"), _m("v3_2", "REJECTED"), _m("swl_00001_4", langue="en"),
               _m("bienvenue_2", comps=[{"type": "BODY", "text": "y"}]),   # pas un carrousel
               _m("v4_2")]
    assert series_carrousel_approuvees(modeles, "fr") == {"swl_00001": 2, "v4": 1}
    # La série en cours de dépôt n'est jamais proposée à elle-même
    assert series_carrousel_approuvees(modeles, "fr", sauf="v4") == {"swl_00001": 2}


def test_url_bouton_reelle():
    assert url_bouton_reelle([_m("swl_00001_2")], "swl_00001") == "https://s.com/api/public/carrousel/l/{{1}}"
    assert url_bouton_reelle([_m("swl_00001_2")], "autre") is None
