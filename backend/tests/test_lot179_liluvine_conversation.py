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


def test_historique_rejoue_au_modele_lot182():
    """Lot 182 — la question précédente de Liluvine est rejouée, sinon « Koloko » est pris pour une nouvelle salutation."""
    from routes.liluvine_wa_autoreply import historique_pour_llm
    docs = [
        {"role": "assistant", "content": "message orphelin"},                   # ne peut pas ouvrir l'historique
        {"role": "user", "content": "Problème avec mon logiciel"},
        {"role": "assistant", "content": "Quel est le nom de votre logiciel ?"},
        {"role": "user", "content": "Koloko"},                                 # sans réponse : retiré (c'est le nouveau message)
        {"role": "tool", "content": "x"}, {"role": "user", "content": "  "},
    ]
    h = historique_pour_llm(docs)
    assert h == [{"role": "user", "content": "Problème avec mon logiciel"},
                 {"role": "assistant", "content": "Quel est le nom de votre logiciel ?"}]
    assert historique_pour_llm([]) == [] and historique_pour_llm(None) == []
    fusion = historique_pour_llm([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}])
    assert fusion == [{"role": "user", "content": "a\nb"}, {"role": "assistant", "content": "c"}]
    assert len(historique_pour_llm([{"role": "user", "content": "x" * 5000}, {"role": "assistant", "content": "y"}])[0]["content"]) == 1200


def test_prompt_selon_contrat_lot183():
    from routes.liluvine_wa_autoreply import prompt_selon_contrat
    s = {"liluvine_wa_client_prompt": " À JOUR ", "liluvine_wa_client_retard_prompt": "RETARD"}
    assert prompt_selon_contrat(s, "valide") == "À JOUR"
    assert prompt_selon_contrat(s, "retard") == "RETARD" and prompt_selon_contrat(s, "aucun") == "RETARD"
    assert prompt_selon_contrat(s, None) == "" and prompt_selon_contrat(s, "inconnu") == ""   # état inconnu : prompt du compte
    assert prompt_selon_contrat({}, "valide") == "" and prompt_selon_contrat(None, "retard") == ""
