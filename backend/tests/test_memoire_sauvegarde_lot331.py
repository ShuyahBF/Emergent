"""Lot 331 — la mémoire d'une sauvegarde / d'un export est rendue au serveur à la fin (le serveur a été arrêté par Render, limite 512 Mo)."""
import os
from pathlib import Path

# db.py lit ces variables à l'import (aucune connexion n'est ouverte)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot331")

from routes import sauvegarde_complete as sc  # noqa: E402


def test_liberer_memoire_ne_plante_jamais():
    assert isinstance(sc.liberer_memoire(), int)


def test_effacer_un_export_libere_la_memoire(tmp_path, monkeypatch):
    appels = []
    monkeypatch.setattr(sc, "liberer_memoire", lambda: appels.append(1) or 0)
    fichier: Path = tmp_path / "export.sawali"
    fichier.write_bytes(b"x")
    sc._effacer(fichier)
    assert not fichier.exists() and appels == [1]                    # fichier effacé, mémoire rendue
    sc._effacer(tmp_path / "absent.sawali")                           # fichier déjà parti : aucune erreur
    assert appels == [1, 1]
