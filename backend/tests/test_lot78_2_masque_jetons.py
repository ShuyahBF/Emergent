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


def test_jetons_reconnus_a_leur_forme():
    """Lot 79.2 — un jeton Cloudflare glissé dans une adresse (variable mal remplie) est masqué."""
    texte = "ValueError: Invalid endpoint: https://cfat_AbCdEf0123456789XyZ0123456789ab.r2.cloudflarestorage.com"
    propre = masque_jetons.masquer(texte)
    assert "AbCdEf0123456789" not in propre and "cfat_***" in propre
    assert "EAA***" in masque_jetons.masquer("jeton EAAPpgnU9rWABR9EEy4h55g3Wl5c6N6I14")


def test_identifiant_r2_invalide_refuse_sans_le_recopier(monkeypatch):
    import r2_vidal_client as rv
    monkeypatch.setattr(rv, "_client", None)
    monkeypatch.setenv("R2_VIDAL_ACCOUNT_ID", "cfat_secret0123456789secret0123456789")
    monkeypatch.setenv("R2_VIDAL_ACCESS_KEY_ID", "a")
    monkeypatch.setenv("R2_VIDAL_SECRET_ACCESS_KEY", "b")
    try:
        rv._get_client()
        assert False, "aurait dû refuser"
    except RuntimeError as exc:
        assert "R2_VIDAL_ACCOUNT_ID invalide" in str(exc) and "secret0123" not in str(exc)
