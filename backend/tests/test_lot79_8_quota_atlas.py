"""Lot 79.8 — jauge des collections du cluster Atlas (limite 500) et alerte au-delà du seuil.
Lancer : cd backend && python -m pytest tests/test_lot79_8_quota_atlas.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.appel_proprietaire as ap  # noqa: E402
import routes.quota_atlas as qa  # noqa: E402


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def client():
    """Cluster simulé : 3 bases applicatives + la base interne « local » (ignorée)."""
    c = mongomock_motor.AsyncMongoMockClient()

    async def remplir():
        for base, n in (("sawali", 5), ("albarka", 3), ("telecom_boutique", 2), ("local", 4)):
            for i in range(n):
                await c[base][f"c{i}"].insert_one({"x": 1})
    lancer(remplir())
    return c


def test_reglages_et_niveaux():
    assert qa.reglages_quota({}) == {"limite": 500, "seuil": 450}
    assert qa.reglages_quota({"atlas_limite_collections": 300, "atlas_seuil_alerte": 900}) == {"limite": 300, "seuil": 300}
    # Lot 79.9 : orange dès 45 %, rouge quand il ne reste que 10 % (≥ 90 %)
    assert qa.niveau(224, 500) == "ok" and qa.niveau(225, 500) == "attention"
    assert qa.niveau(449, 500) == "attention" and qa.niveau(450, 500) == "plein" and qa.niveau(500, 500) == "plein"


def test_compte_toutes_les_bases_sauf_internes(client):
    m = lancer(qa.compter(client, "sawali"))
    assert m["total"] == 10 and m["methode"] == "cluster"
    assert [b["nom"] for b in m["bases"]] == ["sawali", "albarka", "telecom_boutique"]
    assert m["bases"][0]["sawali"] is True


def test_mesure_gardee_et_pourcentage(client):
    db = client["sawali"]
    lancer(db.settings.insert_one({"_id": "global", "atlas_limite_collections": 20, "atlas_seuil_alerte": 15}))
    m = lancer(qa.mesurer(db, client, "sawali"))
    # la mesure compte aussi la collection settings créée ci-dessus (sawali : 6 collections)
    assert m["total"] == 11 and m["limite"] == 20 and m["restantes"] == 9 and m["niveau"] == "attention"   # 55 %
    assert lancer(db.settings.find_one({"_id": qa.DOC_ID}))["derniere_mesure"]["total"] == 11


def test_alerte_une_fois_par_jour_au_dela_du_seuil(client, monkeypatch):
    db = client["sawali"]
    lancer(db.settings.insert_one({"_id": "global", "atlas_limite_collections": 12, "atlas_seuil_alerte": 10,
                                   "super_admin_phone": "22670000001", "wa_access_token": "t",
                                   "wa_phone_number_id": "1"}))
    envois = []

    async def faux_relais(db_, s, cfg, numero_id, proprio, texte, variables, maintenant):
        envois.append(texte)
        return {"ok": True}
    monkeypatch.setattr(ap, "envoyer_relais", faux_relais)
    r = lancer(qa.surveiller(db, client, "sawali"))
    assert r["alerte"] is True and "11 collections sur 12" in envois[0]
    assert lancer(qa.surveiller(db, client, "sawali"))["alerte"] is False      # pas deux fois le même jour
    assert len(envois) == 1


def test_base_seule_si_liste_refusee(client):
    class Refus:
        async def list_database_names(self):
            raise PermissionError("pas le droit")

        def __getitem__(self, nom):
            return client[nom]
    m = lancer(qa.compter(Refus(), "sawali"))
    assert m["methode"] == "base seule" and m["total"] == 5


def test_lot85_bases_protegees():
    """Lot 85 : les bases en service ne sont jamais supprimables ; une base obsolète l'est."""
    from routes import quota_atlas as qa
    for nom in ("sawali", "albarka", "sawali_dentalcare", "telecom_boutique", "admin"):
        assert qa.base_protegee(nom, "sawali")
    assert qa.base_protegee("autre", "autre")                      # base courante de SAWALI
    assert qa.base_protegee("beauthentik", "sawali", ["beauthentik"])  # réglage atlas_bases_protegees
    assert not qa.base_protegee("smartsystems", "sawali")
    assert not qa.base_protegee("multiplatforms", "sawali")
