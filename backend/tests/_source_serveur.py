"""Source complète de server.py pour les tests qui lisent son texte (ast).

Lot 28 : server.py est découpé en morceaux (server_parts/*.py) qu'il exécute
à la place de chaque ligne `_inclure_partie("xx.py")`. Ici on recolle ces
morceaux à leur place pour retrouver l'équivalent de l'ancien fichier unique.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
_INCLUSION = re.compile(r'^_inclure_partie\("([A-Za-z0-9_]+\.py)"\)')


def source_serveur() -> str:
    """server.py avec chaque partie recollée à la place de sa ligne d'inclusion."""
    lignes = []
    for ligne in (BACKEND / "server.py").read_text(encoding="utf-8").split("\n"):
        m = _INCLUSION.match(ligne)
        lignes.append((BACKEND / "server_parts" / m.group(1)).read_text(encoding="utf-8") if m else ligne)
    return "\n".join(lignes)


def lire_source(chemin) -> str:
    """Texte d'un fichier du backend ; pour server.py, la source complète recollée."""
    chemin = Path(chemin)
    if chemin.resolve() == (BACKEND / "server.py").resolve():
        return source_serveur()
    return chemin.read_text(encoding="utf-8")
