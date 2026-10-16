"""Lot 213 — état des fichiers de la bibliothèque de médias : durable / à risque / perdu (sans lire le fichier)."""
from media_etat import a_copier, etat_fichier


def test_fichier_durable_survit_au_redeploiement():
    # Copie dans le stockage : jamais « perdu », même si le disque a été vidé par un redéploiement
    assert etat_fichier({"storage_path": "files/a.jpg"}, sur_disque=False) == (True, False)
    assert etat_fichier({"storage_path": "files/a.jpg"}, sur_disque=True) == (True, False)


def test_fichier_perdu_sans_copie_durable_ni_disque():
    # Cas des vignettes cassées : plus sur le disque (redéploiement) et jamais copié dans le stockage
    assert etat_fichier({"storage_path": None}, sur_disque=False) == (False, True)
    assert etat_fichier({}, sur_disque=False) == (False, True)
    assert etat_fichier(None, sur_disque=False) == (False, True)       # fiche de fichier absente : irrécupérable


def test_fichier_a_risque_est_copie_en_arriere_plan():
    # Sur le disque mais sans copie durable : pas encore perdu, à copier avant le prochain redéploiement
    assert etat_fichier({"storage_path": None}, sur_disque=True) == (False, False)
    assert a_copier({"id": "f1", "storage_path": None}, True) is True
    assert a_copier({"id": "f1", "storage_path": "files/f1.jpg"}, True) is False     # déjà durable
    assert a_copier({"id": "f1", "storage_path": None}, False) is False              # perdu : rien à copier
    assert a_copier(None, True) is False                                             # pas de fiche : rien à copier
