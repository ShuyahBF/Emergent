"""Lot 373.1 — le rapport « /alerts/full/html » de VIDAL doit être demandé avec un en-tête Accept HTML
(avec l'Accept XML seul, VIDAL répondait « 406 Not Acceptable » et le portail affichait une erreur 502).
Test sans base de données : l'appel HTTP vers VIDAL est simulé."""
import asyncio
from datetime import timedelta

import httpx

from routes import vidal

CFG = {"app_id": "id", "app_key": "cle", "base_url": "https://vidal.test/rest/api", "http_timeout": 5, "mode": "test"}


def _appel(chemin):
    """Exécute `_vidal_call` (POST XML) vers le chemin donné et retourne l'en-tête Accept réellement envoyé."""
    vus = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vus.append(requete)
        reponse = httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})
        reponse.elapsed = timedelta(milliseconds=5)          # le client SAWALI lit `elapsed` (comme dans les autres tests VIDAL)
        return reponse

    vrai_client = httpx.AsyncClient

    class ClientSimule(vrai_client):
        def __init__(self, *a, **k):
            super().__init__(*a, transport=httpx.MockTransport(gestionnaire), **k)

    original = vidal.httpx.AsyncClient
    vidal.httpx.AsyncClient = ClientSimule
    try:
        asyncio.run(vidal._vidal_call(CFG, "POST", chemin, body="<x/>"))
    finally:
        vidal.httpx.AsyncClient = original
    return vus[0].headers["accept"]


def test_le_rapport_html_demande_du_html():
    assert "text/html" in _appel("/alerts/full/html")
    assert "text/html" in _appel("/alerts/full/html/")          # barre finale tolérée


def test_les_autres_appels_post_restent_en_xml():
    accept = _appel("/alerts/full")
    assert "atom+xml" in accept and "text/html" not in accept
