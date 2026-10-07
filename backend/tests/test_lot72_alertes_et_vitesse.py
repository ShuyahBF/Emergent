"""Lot 72 — accélérations : webhook WhatsApp (accusé de réception immédiat), statistiques des plateformes
(derniers chiffres tout de suite, rafraîchis en arrière-plan) ; les alertes d'appels sont testées avec l'agenda
(tests/test_lot70_agenda_liluvine.py)."""
import ast
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")


def _fonction_du_webhook():
    """Extrait `traiter_webhook_wa_en_arriere_plan` de server_parts/p12_sms.py (fichier exécuté dans server.py)."""
    source = (RACINE / "server_parts/p12_sms.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    noeud = next(n for n in arbre.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "traiter_webhook_wa_en_arriere_plan")
    return ast.get_source_segment(source, noeud), source


def test_webhook_wa_route_branchee_sur_la_reponse_immediate():
    # La route POST /whatsapp/webhook appelle bien la version « réponse immédiate »
    _, source = _fonction_du_webhook()
    arbre = ast.parse(source)
    route = next(n for n in arbre.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "whatsapp_webhook_reception")
    assert any(isinstance(d, ast.Call) and getattr(d.args[0], "value", "") == "/whatsapp/webhook" for d in route.decorator_list)
    traitement = next(n for n in arbre.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "whatsapp_webhook_incoming")
    assert not traitement.decorator_list, "le traitement complet ne doit plus être la route elle-même"


def test_webhook_wa_repond_tout_de_suite_et_traite_ensuite(monkeypatch):
    # Traitement simulé de 1 s : Meta reçoit « ok » en moins de 0,1 s, le traitement se termine ensuite
    code, _ = _fonction_du_webhook()
    traites = []

    async def whatsapp_webhook_incoming(request):
        await asyncio.sleep(1.0)
        traites.append(await request.body())
        return {"ok": True}

    class FausseRequete:
        async def body(self):
            return b'{"entry": []}'

    espace = {"asyncio": asyncio, "os": os, "logger": logging.getLogger("test"), "Dict": Dict, "Any": Any,
              "Request": object, "_TRAITEMENTS_WEBHOOK_WA": set(), "whatsapp_webhook_incoming": whatsapp_webhook_incoming}
    exec(compile(code, "p12_sms", "exec"), espace)   # noqa: S102 — fonction du projet, isolée pour le test

    async def scenario():
        t = time.perf_counter()
        reponse = await espace["traiter_webhook_wa_en_arriere_plan"](FausseRequete())
        delai = time.perf_counter() - t
        assert reponse == {"ok": True} and delai < 0.1 and traites == []
        await asyncio.sleep(1.2)
        assert traites == [b'{"entry": []}']
    asyncio.run(scenario())
    # Variable d'environnement : retour à l'ancien fonctionnement (attente du traitement complet)
    monkeypatch.setenv("WA_WEBHOOK_SYNCHRONE", "1")
    traites.clear()

    async def synchrone():
        t = time.perf_counter()
        await espace["traiter_webhook_wa_en_arriere_plan"](FausseRequete())
        assert time.perf_counter() - t >= 0.9 and len(traites) == 1
    asyncio.run(synchrone())


def test_stats_plateformes_chiffres_connus_tout_de_suite(monkeypatch):
    # Cache périmé : les derniers chiffres sont rendus sans attendre la plateforme, puis rafraîchis en arrière-plan
    import routes.stats_plateformes as sp
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot72"]
    appels = []

    async def lente(emetteur, debut, fin):
        appels.append(emetteur["code"])
        await asyncio.sleep(1.0)
        return {"ok": True, "indicateurs": [{"cle": "ventes", "libelle": "Ventes", "valeur": 9}], "faits_marquants": []}
    monkeypatch.setattr(sp, "interroger", lente)
    emetteur = {"code": "ster", "actif": True, "url_retour": "https://ster.test", "secret": "x"}
    debut, fin = "2026-10-06T08:00:00+00:00", "2026-10-07T08:00:00+00:00"
    vieux = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    async def scenario():
        await db.plateformes_stats.insert_one({"_id": f"ster|{debut[:13]}|{fin[:13]}", "code": "ster", "recu_le": vieux,
                                               "resultat": {"ok": True, "indicateurs": [{"libelle": "Ventes", "valeur": 4}],
                                                            "recu_le": vieux}})
        t = time.perf_counter()
        r = await sp.stats_plateforme(db, emetteur, debut, fin, duree_cache=timedelta(seconds=60), sans_attendre=True)
        assert time.perf_counter() - t < 0.2
        assert r["perime"] is True and r["indicateurs"][0]["valeur"] == 4
        # Second appel pendant le rafraîchissement : pas de deuxième interrogation de la plateforme
        await sp.stats_plateforme(db, emetteur, debut, fin, duree_cache=timedelta(seconds=60), sans_attendre=True)
        await asyncio.sleep(1.3)
        assert appels == ["ster"]
        frais = await sp.stats_plateforme(db, emetteur, debut, fin, duree_cache=timedelta(seconds=60), sans_attendre=True)
        assert frais["indicateurs"][0]["valeur"] == 9 and "perime" not in frais
        # Sans aucun chiffre connu : on attend la plateforme, comme avant (synthèse du matin)
        appels.clear()
        r2 = await sp.stats_plateforme(db, {**emetteur, "code": "adlyn"}, debut, fin, sans_attendre=True)
        assert r2["ok"] is True and appels == ["adlyn"]
    asyncio.run(scenario())
