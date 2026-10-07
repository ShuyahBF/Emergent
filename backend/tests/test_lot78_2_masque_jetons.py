"""Lot 78.2 — aucun jeton en clair dans les journaux du serveur."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import masque_jetons  # noqa: E402


def test_masquer_les_parametres_sensibles():
    url = ("POST https://graph.facebook.com/v22.0/1/uploads?file_name=a.png&file_length=3&access_token=EAAsecret123"
           "&input_token=EAAautre")
    propre = masque_jetons.masquer(url)
    assert "EAAsecret123" not in propre and "EAAautre" not in propre
    assert "access_token=***" in propre and "file_name=a.png" in propre


def test_filtre_sur_le_journal_httpx(caplog):
    masque_jetons.installer()
    journal = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        journal.info('HTTP Request: %s %s "%s"', "GET", "https://x/y?access_token=EAAsecret&limit=2", "HTTP/1.1 200 OK")
    texte = caplog.text
    assert "EAAsecret" not in texte and "access_token=***" in texte and "limit=2" in texte
