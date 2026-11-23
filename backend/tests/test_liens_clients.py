"""Lien client canonique : un lien inchangé n'est jamais re-vérifié (lot 451.2)."""
from liens_clients import lien_a_valider


def test_lien_inchange_non_reverifie():
    assert lien_a_valider("abc", "abc") is False          # fiche enregistrée sans toucher au lien : pas de contrôle, donc plus de « Client canonique introuvable »
    assert lien_a_valider(" abc ", "abc") is False        # espaces ignorés


def test_lien_nouveau_ou_change_est_verifie():
    assert lien_a_valider("abc", None) is True            # premier rattachement
    assert lien_a_valider("abc", "def") is True           # changement de client canonique


def test_lien_vide_rien_a_verifier():
    assert lien_a_valider("", "abc") is False             # détachement : géré à part
    assert lien_a_valider(None, None) is False
