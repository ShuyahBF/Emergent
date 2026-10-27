"""Lot 332 — presse-papiers du poste vers le technicien : relayé seulement en mode « contrôler » ; commande « presse_papiers_demander »."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot332")

from routes.controle_distance import commande_autorisee, message_poste_autorise  # noqa: E402


def test_presse_papiers_du_poste_relaye_seulement_en_mode_controler():
    msg = {"type": "presse_papiers", "texte": "Logs : 22 factures"}
    assert message_poste_autorise(msg, "controler") is True
    assert message_poste_autorise(msg) is True                      # valeur par défaut = contrôler (appels existants inchangés)
    assert message_poste_autorise(msg, "voir") is False             # voir seulement : rien du presse-papiers ne sort du poste
    assert message_poste_autorise({"type": "stats"}, "voir") is True    # les autres messages du poste ne changent pas
    assert message_poste_autorise({"type": "inconnu"}, "controler") is False


def test_le_technicien_peut_demander_le_presse_papiers_seulement_en_mode_controler():
    demande = {"type": "presse_papiers_demander"}
    assert commande_autorisee("controler", demande) is True
    assert commande_autorisee("voir", demande) is False
