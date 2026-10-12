"""Lot 125 — le résumé d'un appel décroché par Liluvine connaît l'appelant (fiche contact) et n'invente rien.
Cas réel du 12/10/2026 : « Flotte Pharmacie AMY », qui avait autorisé les appels, résumé en « Appelant non identifié ».
Lancer : cd backend && python -m pytest tests/test_resume_appel_lot125.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.liluvine_decroche as ld  # noqa: E402


def test_identite_appelant():
    appel = {"contact_nom": "Flotte Pharmacie AMY", "telephone": "22678836072"}
    assert ld.identite_appelant(appel, {"name": "Flotte Pharmacie AMY", "company": "Pharmacie AMY"}) == \
        "Flotte Pharmacie AMY (société : Pharmacie AMY, +22678836072)"
    assert ld.identite_appelant(appel) == "Flotte Pharmacie AMY (+22678836072)"
    # Un « nom » qui n'est qu'un numéro n'identifie personne
    assert ld.identite_appelant({"contact_nom": "+226 78 83 60 72", "telephone": "22678836072"}) is None


def test_consigne_resume():
    c = ld.consigne_resume("Flotte Pharmacie AMY (+22678836072)")
    assert "Flotte Pharmacie AMY" in c and "non identifié" in c and "UNIQUEMENT" in c
    assert "CONNU" not in ld.consigne_resume(None)


def test_resumer_transmet_l_identite(monkeypatch):
    vu = {}

    async def faux_llm(systeme, historique, texte):
        vu["systeme"], vu["texte"] = systeme, texte
        return {"texte": "ok", "entree": 1, "sortie": 1}

    monkeypatch.setattr(ld, "repondre_llm", faux_llm)
    asyncio.run(ld.resumer([{"qui": "appelant", "texte": "Bonjour"}, {"qui": "liluvine", "texte": "Bonjour !"}],
                           "Flotte Pharmacie AMY (+22678836072)"))
    assert "Flotte Pharmacie AMY" in vu["systeme"]
    assert vu["texte"].startswith("Flotte Pharmacie AMY : Bonjour")
