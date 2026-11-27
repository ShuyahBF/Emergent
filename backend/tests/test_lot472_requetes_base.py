"""Lot 472 — requêtes à la base comptées et chronométrées PAR APPEL (Paramètres → Performance du serveur → « Appels les plus lents »)."""
import asyncio
import sys
from pathlib import Path

import motor.frameworks.asyncio as cadre
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import performance_serveur as ps  # noqa: E402


@pytest.fixture
def crochet(monkeypatch):
    """Pose le crochet sur Motor pour la durée d'un test, puis remet la fonction d'origine (aucune fuite entre les tests)."""
    monkeypatch.setattr(cadre, "run_on_executor", cadre.run_on_executor)
    monkeypatch.setattr(ps, "_CROCHET_POSE", False)
    assert ps.installer_mesure_base() is True
    return cadre.run_on_executor


def test_le_suivi_garde_ops_et_temps_de_base_par_route():
    s = ps.SuiviAppels()
    s.enregistrer("GET", "/api/x", 300, 200, ops=20, base_ms=240)
    s.enregistrer("GET", "/api/x", 100, 200, ops=10, base_ms=100)
    s.enregistrer("GET", "/api/y", 50, 200)                                  # appel sans requête à la base
    x = {l["route"]: l for l in s.classement()}["/api/x"]
    assert x["ops_moy"] == 15.0 and x["ops_max"] == 20 and x["base_ms_moy"] == 170
    y = {l["route"]: l for l in s.classement()}["/api/y"]
    assert y["ops_moy"] == 0.0 and y["base_ms_moy"] == 0


def test_le_crochet_compte_chaque_requete_de_l_appel_en_cours_et_rend_le_meme_resultat(crochet):
    async def scenario():
        compteur = ps.CompteurBase()
        jeton = ps.COMPTEUR_BASE.set(compteur)
        loop = asyncio.get_running_loop()
        resultats = [await cadre.run_on_executor(loop, lambda a, b: a + b, 1, 2),
                     await cadre.run_on_executor(loop, lambda: "x")]
        parallele = await asyncio.gather(*[cadre.run_on_executor(loop, lambda i=i: i * 2) for i in range(5)])      # 5 requêtes en parallèle
        ps.COMPTEUR_BASE.reset(jeton)
        sans_compteur = await cadre.run_on_executor(loop, lambda: "libre")                                          # hors appel : rien n'est compté
        return compteur, resultats, parallele, sans_compteur

    compteur, resultats, parallele, libre = asyncio.run(scenario())
    assert resultats == [3, "x"] and parallele == [0, 2, 4, 6, 8] and libre == "libre"      # le crochet ne change JAMAIS le résultat
    assert compteur.ops == 7 and compteur.ms >= 0


def test_installation_idempotente_et_prudente(crochet, monkeypatch):
    assert ps.installer_mesure_base() is True and cadre.run_on_executor is crochet          # 2e installation : rien de plus
    # Motor de forme inattendue : on ne touche à rien et on le dit (le serveur démarre normalement)
    monkeypatch.setattr(ps, "_CROCHET_POSE", False)
    monkeypatch.setattr(cadre, "run_on_executor", lambda pas_la_bonne_signature: None)
    avant = cadre.run_on_executor
    assert ps.installer_mesure_base() is False and cadre.run_on_executor is avant


def test_de_bout_en_bout_l_intergiciel_compte_les_requetes_de_chaque_appel(crochet):
    suivi = ps.SuiviAppels()
    app = FastAPI()

    @app.get("/api/lourde")
    async def lourde():
        loop = asyncio.get_running_loop()
        for _ in range(12):                                                    # 12 requêtes l'une après l'autre : le défaut qu'on cherche à repérer
            await cadre.run_on_executor(loop, lambda: None)
        return {"ok": True}

    @app.get("/api/legere")
    async def legere():
        await cadre.run_on_executor(asyncio.get_running_loop(), lambda: None)
        return {"ok": True}

    app.add_middleware(ps.MesureAppels, suivi=suivi)
    c = TestClient(app)
    assert c.get("/api/lourde").status_code == 200 and c.get("/api/lourde").status_code == 200 and c.get("/api/legere").status_code == 200
    lignes = {l["route"]: l for l in suivi.classement()}
    assert lignes["/api/lourde"]["ops_moy"] == 12.0 and lignes["/api/lourde"]["appels"] == 2
    assert lignes["/api/legere"]["ops_moy"] == 1.0
    assert lignes["/api/lourde"]["base_ms_moy"] >= 0
