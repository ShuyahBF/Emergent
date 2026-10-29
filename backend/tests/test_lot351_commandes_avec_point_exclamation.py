"""Lot 351 — une commande n'est exécutée que si elle commence par « ! » ; sinon Liluvine dit quoi corriger."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routes.liluvine_wa_autoreply import message_commande_a_corriger as m  # noqa: E402


def test_message_de_correction():
    t = m("adresse ?", "adresse")
    assert "n'est pas une commande" in t and "!adresse" in t and "sans espace" in t
    assert "pharmacie de garde" in m("pharmacie de garde", "garde") and "!garde" in m("pharmacie de garde", "garde")
    assert len(m("x" * 500, "stock")) < 400            # le texte de l'utilisateur est tronqué à 60 caractères
    assert "\n" not in m("a\nb", "stock").split("»")[0]
