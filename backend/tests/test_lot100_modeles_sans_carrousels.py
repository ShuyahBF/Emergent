"""Lot 100 — les listes de modèles WhatsApp approuvés n'affichent pas les carrousels (sauf ?carrousels=true).
Lancer : cd backend && python -m pytest tests/test_lot100_modeles_sans_carrousels.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.whatsapp_helpers import est_modele_carrousel  # noqa: E402


def test_detection_du_carrousel():
    carrousel = {"name": "promo_3_cartes", "components": [{"type": "BODY", "text": "Nos offres"},
                                                          {"type": "CAROUSEL", "cards": [{}, {}, {}]}]}
    simple = {"name": "rappel_rdv", "components": [{"type": "BODY", "text": "Bonjour {{1}}"}, {"type": "BUTTONS"}]}
    assert est_modele_carrousel(carrousel) is True
    assert est_modele_carrousel(simple) is False
    # Modèle incomplet (sans composants) : pas un carrousel, jamais d'erreur
    assert est_modele_carrousel({}) is False and est_modele_carrousel(None) is False


def test_routes_filtrent_les_carrousels():
    """Les deux listes (administration et portail) écartent les carrousels sauf demande explicite."""
    racine = Path(__file__).resolve().parents[1] / "server_parts"
    for fichier, route in (("p13_whatsapp_supervision.py", "admin_list_wa_templates"), ("p12_sms.py", "me_list_wa_templates")):
        source = (racine / fichier).read_text(encoding="utf-8")
        debut = source.index(f"async def {route}(")
        corps = source[debut:debut + 2500]
        assert "carrousels: bool = False" in corps and "est_modele_carrousel(t)" in corps
