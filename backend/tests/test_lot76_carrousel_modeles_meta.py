"""Lot 76 — création des 9 modèles du carrousel chez Meta (API Meta simulée par httpx.MockTransport)."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes import carrousel_modeles_meta as cmm  # noqa: E402
import routes.carrousel_whatsapp as cw  # noqa: E402

URL_BOUTON = "https://api.sawalismartsystems.com/api/public/carrousel/l/{{1}}"


def _variables(texte):
    return sorted(int(n) for n in re.findall(r"\{\{(\d+)\}\}", texte))


def test_definition_conforme_a_l_envoi_de_sawali():
    d = cmm.definition_modele("sawali_carrousel", 3, "fr", URL_BOUTON, "4::handle")
    assert d["name"] == "sawali_carrousel_3" == cw.nom_modele("sawali_carrousel", 3)
    assert d["category"] == "MARKETING" and d["language"] == "fr"
    bulle, carrousel = d["components"]
    # Bulle : 2 variables, comme composants() à l'envoi (expéditeur, message)
    envoi = cw.composants("X", "Y", [{"image_url": "https://a/b.jpg", "titre": "T", "texte": "t", "code_lien": "c"}] * 3)
    assert _variables(bulle["text"]) == [1, 2] == list(range(1, len(envoi[0]["parameters"]) + 1))
    assert len(carrousel["cards"]) == 3 == len(envoi[1]["cards"])
    carte = carrousel["cards"][0]["components"]
    assert carte[0] == {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::handle"]}}
    assert _variables(carte[1]["text"]) == [1, 2] == list(range(1, len(envoi[1]["cards"][0]["components"][1]["parameters"]) + 1))
    bouton = carte[2]["buttons"][0]
    assert bouton["type"] == "URL" and bouton["url"] == URL_BOUTON and len(bouton["example"]) == 1
    # Règle Meta : jamais de variable au tout début ni à la toute fin d'un texte
    for texte in (bulle["text"], carte[1]["text"]):
        assert not texte.startswith("{{") and not texte.endswith("}}") and not texte.rstrip(".").endswith("}}")


def test_image_exemple_png():
    octets = cmm.image_exemple()
    assert octets[:8] == b"\x89PNG\r\n\x1a\n" and len(octets) < 5 * 1024 * 1024


def test_creation_des_9_modeles_et_existants():
    appels = []

    def repondre(request: httpx.Request) -> httpx.Response:
        appels.append(request)
        chemin = request.url.path
        if chemin.endswith("/app123/uploads"):
            assert request.url.params["file_type"] == "image/png"
            return httpx.Response(200, json={"id": "upload:session1"})
        if chemin.endswith("/upload:session1"):
            assert request.headers["Authorization"] == "OAuth jeton" and request.headers["file_offset"] == "0"
            return httpx.Response(200, json={"h": "4::handle"})
        if chemin.endswith("/waba9/message_templates"):
            corps = json.loads(request.content)
            assert corps["components"][1]["cards"][0]["components"][0]["example"]["header_handle"] == ["4::handle"]
            if corps["name"].endswith("_2"):
                return httpx.Response(400, json={"error": {"message": "Content in this language already exists"}})
            if corps["name"].endswith("_10"):
                return httpx.Response(400, json={"error": {"message": "Invalid parameter", "error_user_msg": "Texte refusé"}})
            return httpx.Response(200, json={"id": "t", "status": "PENDING", "category": "MARKETING"})
        return httpx.Response(404)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as client:
            return await cmm.creer_modeles(version="v22.0", app_id="app123", waba_id="waba9", jeton="jeton",
                                           prefixe="sawali_carrousel", langue="fr", url_bouton=URL_BOUTON, client=client)
    res = asyncio.run(scenario())
    assert [r["nom"] for r in res] == [f"sawali_carrousel_{n}" for n in range(2, 11)]
    assert res[0]["statut"] == "existe déjà"
    assert all(r["statut"] == "soumis" for r in res[1:8])
    assert res[8] == {"nom": "sawali_carrousel_10", "statut": "erreur", "detail": "Texte refusé"}
    assert "jeton" not in json.dumps(res)                      # le jeton n'est jamais renvoyé


def test_depot_image_refuse_leve_une_erreur_claire():
    def repondre(request):
        return httpx.Response(400, json={"error": {"message": "Invalid app id"}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as client:
            return await cmm.creer_modeles(version="v22.0", app_id="mauvais", waba_id="w", jeton="j",
                                           prefixe="p", langue="fr", url_bouton=URL_BOUTON, client=client)
    with pytest.raises(RuntimeError, match="image d'exemple refusé : Invalid app id"):
        asyncio.run(scenario())


def test_app_id_retrouve_a_partir_du_jeton():
    # Lot 76.1 — sans App ID saisi, il est lu par /debug_token puis utilisé pour le dépôt de l'image
    vus = []

    def repondre(request):
        chemin = request.url.path
        vus.append(chemin)
        if chemin.endswith("/debug_token"):
            assert request.url.params["input_token"] == "jeton"
            return httpx.Response(200, json={"data": {"app_id": "987654", "is_valid": True}})
        if chemin.endswith("/987654/uploads"):
            return httpx.Response(200, json={"id": "upload:s"})
        if chemin.endswith("/upload:s"):
            return httpx.Response(200, json={"h": "4::h"})
        return httpx.Response(200, json={"status": "PENDING"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as client:
            return await cmm.creer_modeles(version="v22.0", app_id=None, waba_id="w", jeton="jeton",
                                           prefixe="p", langue="fr", url_bouton=URL_BOUTON, client=client)
    res = asyncio.run(scenario())
    assert all(r["statut"] == "soumis" for r in res) and any(c.endswith("/987654/uploads") for c in vus)


def test_app_id_introuvable_message_clair():
    def repondre(request):
        return httpx.Response(200, json={"data": {}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as client:
            return await cmm.creer_modeles(version="v22.0", app_id="", waba_id="w", jeton="j",
                                           prefixe="p", langue="fr", url_bouton=URL_BOUTON, client=client)
    with pytest.raises(RuntimeError, match="App ID Meta introuvable"):
        asyncio.run(scenario())
