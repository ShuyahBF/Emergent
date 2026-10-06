"""Lot 62 — Statistiques internes de chaque plateforme : appel signé « stats_du_jour »
(même clé et même schéma de signature que les retours du lot 57.5), nettoyage de la réponse,
cache de 10 minutes, intégration au tableau et à la synthèse. MongoDB simulé, plateforme factice.
Lancer : cd backend && python -m pytest tests/test_lot62_stats_plateformes.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.rapport_plateformes as rp  # noqa: E402
import routes.stats_plateformes as sp  # noqa: E402


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


class Reponse:
    def __init__(self, code, donnees):
        self.status_code = code
        self._d = donnees

    def json(self):
        return self._d


@pytest.fixture()
def env(monkeypatch):
    """Base simulée + plateforme factice qui VÉRIFIE la signature comme le ferait adLyn."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot62"]
    appels = []

    class FauxClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, content=None, headers=None):
            appels.append(url)
            attendu = hmac.new(b"cle-adlyn", f"{headers['X-Timestamp']}.{content.decode()}".encode(),
                               hashlib.sha256).hexdigest()
            if headers.get("X-Signature") != attendu:
                return Reponse(401, {"detail": "signature"})
            corps = json.loads(content)
            assert corps["type"] == "stats_du_jour" and corps["debut"] and corps["fin"]
            if "panne" in url:
                return Reponse(500, {})
            return Reponse(200, {"indicateurs": [
                {"cle": "connexions", "libelle": "Connexions", "valeur": 42},
                {"cle": "ventes", "libelle": "Ventes", "valeur": 12},
                {"libelle": "ignoré", "valeur": {"objet": 1}},          # valeur invalide : ignorée
            ], "faits_marquants": ["3 nouvelles boutiques"]})

    monkeypatch.setattr(sp.httpx, "AsyncClient", FauxClient)
    lancer(db.liluvine_emetteurs.insert_many([
        {"code": "adlyn", "nom": "adLyn", "actif": True, "secret": "cle-adlyn",
         "url_retour": "https://adlyn.test/api/webhooks/liluvine-retour"},
        {"code": "panne", "nom": "Plateforme en panne", "actif": True, "secret": "cle-adlyn",
         "url_stats": "https://panne.test/stats"},
        {"code": "nonbranchee", "nom": "Non branchée", "actif": True, "secret": "x"},
    ]))
    return db, appels


def test_appel_signe_nettoyage_et_cache(env):
    db, appels = env
    adlyn = lancer(db.liluvine_emetteurs.find_one({"code": "adlyn"}, {"_id": 0}))
    r = lancer(sp.stats_plateforme(db, adlyn, "2026-10-05T00:00:00", "2026-10-06T00:00:00"))
    assert r["ok"] and [i["libelle"] for i in r["indicateurs"]] == ["Connexions", "Ventes"]
    assert r["faits_marquants"] == ["3 nouvelles boutiques"]
    assert appels == ["https://adlyn.test/api/webhooks/liluvine-retour"]   # URL de retour par défaut
    # Deuxième lecture : cache (aucun nouvel appel), puis appel forcé
    lancer(sp.stats_plateforme(db, adlyn, "2026-10-05T00:00:00", "2026-10-06T00:00:00"))
    assert len(appels) == 1
    lancer(sp.stats_plateforme(db, adlyn, "2026-10-05T00:00:00", "2026-10-06T00:00:00", forcer=True))
    assert len(appels) == 2
    assert lancer(db.liluvine_emetteurs.find_one({"code": "adlyn"}))["derniere_stats_ok"]
    # Mauvaise clé : refus de la plateforme
    r = lancer(sp.interroger({**adlyn, "secret": "autre"}, "a", "b"))
    assert not r["ok"] and "401" in r["erreur"]


def test_tableau_et_synthese(env):
    db, _ = env
    items = lancer(rp.activite_plateformes(db, "2026-10-05T00:00:00", "2026-10-06T00:00:00"))
    par_code = {p["code"]: p for p in items}
    assert par_code["adlyn"]["interne"]["ok"]
    assert par_code["panne"]["interne"] == {**par_code["panne"]["interne"], "ok": False}
    assert par_code["nonbranchee"]["interne"] is None and not par_code["nonbranchee"]["stats_configurees"]
    assert "secret" not in par_code["adlyn"]
    texte = rp.bloc_plateformes(items)
    assert "Activité interne : Connexions 42 · Ventes 12" in texte
    assert "◦ 3 nouvelles boutiques" in texte
    assert "statistiques internes indisponibles (HTTP 500)" in texte
