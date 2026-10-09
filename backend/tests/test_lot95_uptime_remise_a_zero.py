"""Lot 95 — page /uptime (« /health ») : sondes de disponibilité et remise à zéro du journal.

Cause des 13 % / « Incident en cours » : depuis la bascule vers Render (03/10/2026), les sondes HTTP interrogeaient
http://127.0.0.1:8001 (port d'Emergent) alors que le serveur écoute sur $PORT → « All connection attempts failed ».
Lancer : cd backend && python -m pytest tests/test_lot95_uptime_remise_a_zero.py -q
"""
from __future__ import annotations

import ast
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "server_parts" / "p09_supervision_parametres.py").read_text(encoding="utf-8")


def _fonction(nom: str):
    """Fonction `nom` du fichier p09, compilée seule (le fichier s'exécute normalement dans l'espace de server.py)."""
    arbre = ast.parse(SOURCE)
    noeud = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == nom)
    espace = {"os": __import__("os")}
    exec(compile(ast.Module(body=[noeud], type_ignores=[]), "p09", "exec"), espace)
    return espace[nom]


def test_sondes_sur_le_port_reel(monkeypatch):
    url = _fonction("_url_locale_sondes")
    monkeypatch.setenv("PORT", "10000")          # Render
    assert url() == "http://127.0.0.1:10000"
    monkeypatch.delenv("PORT", raising=False)    # Emergent / poste local
    assert url() == "http://127.0.0.1:8001"
    assert 'base_url="http://127.0.0.1:8001"' not in SOURCE   # plus aucun port figé dans les sondes


def test_route_de_remise_a_zero():
    assert '@api.post("/admin/health/uptime/reset"' in SOURCE
    assert "db.uptime_checks.delete_many({})" in SOURCE
    assert "_ensure_super_admin(user)" in SOURCE.split('"/admin/health/uptime/reset"')[1][:1500]
