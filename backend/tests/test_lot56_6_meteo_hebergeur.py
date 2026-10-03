"""Lot 56.6 — météo : une IP d'hébergeur (Render, AWS...) ne donne jamais la ville du visiteur."""
from routes.weather import _ip_d_hebergeur


def test_ip_render_reconnue_comme_hebergeur():
    # Réponse réelle d'ipwho.is pour l'IP de relais de Render (ville « Boardman, US »)
    assert _ip_d_hebergeur({"connection": {"org": "Render", "isp": "Amazon.com, Inc.", "domain": "render.com"}})


def test_operateur_mobile_burkinabe_accepte():
    # Un opérateur grand public : la ville trouvée est gardée
    assert not _ip_d_hebergeur({"connection": {"org": "Orange Burkina Faso", "isp": "Orange Burkina Faso", "domain": "orange.bf"}})
    assert not _ip_d_hebergeur({})
