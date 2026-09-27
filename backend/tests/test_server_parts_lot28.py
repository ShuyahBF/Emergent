"""Lot 28 — garde du découpage physique de server.py en server_parts/.

Vérifie, sans démarrer le serveur :
  - chaque ligne _inclure_partie("x.py") de server.py désigne un fichier existant ;
  - chaque fichier de server_parts/ est inclus exactement une fois, dans l'ordre p01…p20 ;
  - la source recollée est du Python valide et contient les routes clés ;
  - aucun module du projet n'importe une partie directement.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from _source_serveur import BACKEND, source_serveur

PARTS = BACKEND / "server_parts"
INCL = re.compile(r'^_inclure_partie\("([A-Za-z0-9_]+\.py)"\)', re.M)


def test_chaque_inclusion_designe_un_fichier_et_dans_l_ordre():
    noms = INCL.findall((BACKEND / "server.py").read_text(encoding="utf-8"))
    fichiers = sorted(p.name for p in PARTS.glob("p*.py"))
    assert noms == fichiers, "server.py doit inclure toutes les parties, une fois chacune, dans l'ordre"
    assert len(noms) == 20


def test_source_recollee_valide_et_complete():
    src = source_serveur()
    tree = ast.parse(src)                                  # Python valide
    noms = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    # quelques fonctions clés, réparties dans plusieurs parties
    for f in ("admin_scheduler_status", "me_list_contacts", "health_check", "_compute_deploy_fingerprint"):
        assert f in noms, f
    assert src.count("app.include_router(api)") == 1


def test_parties_jamais_importees_directement():
    for p in list(BACKEND.glob("*.py")) + list((BACKEND / "routes").glob("*.py")):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        assert not re.search(r"^\s*(from|import)\s+server_parts\b", txt, re.M), p.name
