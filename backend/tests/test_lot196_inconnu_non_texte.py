# Lot 196 — un expéditeur inconnu qui envoie autre chose que du texte (bouton, image, vocal) est ajouté au carnet.
import ast
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "server_parts/p12_sms.py").read_text(encoding="utf-8")


def test_le_fichier_est_valide_python():
    ast.parse(SOURCE)


def test_ajout_automatique_applique_aux_messages_non_texte_avant_la_reponse_automatique():
    # le bloc du lot 196 existe, vise les messages non texte sans fiche, et précède le contrôle de la ligne VIP
    i = SOURCE.index("Lot 196 — expéditeur INCONNU")
    bloc = SOURCE[i:i + 1400]
    assert "not contact and mtype != \"text\"" in bloc
    assert "auto_add_new_contact_if_enabled" in bloc
    assert i < SOURCE.index("Lot 158 — message reçu sur la ligne VIP")
