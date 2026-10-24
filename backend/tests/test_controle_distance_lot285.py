"""Lot 285 — le technicien peut arrêter la récupération d'un fichier par le poste (« fichier_arreter »)."""
from routes.controle_distance import commande_autorisee


def test_fichier_arreter_autorise_en_mode_controler_seulement():
    assert commande_autorisee("controler", {"type": "fichier_arreter", "id": 3})
    assert not commande_autorisee("voir", {"type": "fichier_arreter", "id": 3})
