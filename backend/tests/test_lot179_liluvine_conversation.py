"""Lot 179 — Liluvine : délai anti-répétition plafonné (plus de silence à la 2e question) et consignes de conversation.
Lancer : cd backend && python -m pytest tests/test_lot179_liluvine_conversation.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.liluvine_wa_autoreply import (  # noqa: E402
    COOLDOWN_DEFAUT_SECONDS, COOLDOWN_MAX_SECONDS, consignes_conversation, delai_anti_repetition,
)


def test_delai_plafonne_et_zero_respecte():
    assert delai_anti_repetition(60) == COOLDOWN_MAX_SECONDS      # l'ancien défaut de 60 s ne bloque plus la conversation
    assert delai_anti_repetition("120") == COOLDOWN_MAX_SECONDS
    assert delai_anti_repetition(0) == 0                          # 0 = pas de délai (avant : retombait à 60)
    assert delai_anti_repetition(3) == 3
    assert delai_anti_repetition(None) == COOLDOWN_DEFAUT_SECONDS
    assert delai_anti_repetition("abc") == COOLDOWN_DEFAUT_SECONDS
    assert delai_anti_repetition(-5) == 0


def test_consignes_sans_re_presentation_ni_catalogue():
    for connue in (True, False):
        t = consignes_conversation(connue)
        assert "ne te présente" in t.lower() and "JAMAIS la liste de tous les logiciels" in t
    assert "offre de ce client" in consignes_conversation(True)
    assert "UNE seule question" in consignes_conversation(False)
