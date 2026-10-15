"""Lot 170 — services à renouveler : montants par service, formule, plateforme et cluster ; échéances, rappels, lectures
automatiques d'Atlas (facture en cours) et de Cloudflare R2 (estimation). Réseau et MongoDB simulés.
Lancer : cd backend && python -m pytest tests/test_lot170_services_renouveler.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.services_renouveler as sr  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


AUJOURDHUI = date(2026, 10, 15)


def test_echeances_et_montants_mensuels():
    assert sr.ajouter_mois(date(2026, 1, 31), 1) == date(2026, 2, 28)             # le 31 devient le dernier jour du mois suivant
    assert sr.ajouter_mois(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert sr.echeance_suivante("2026-10-20", "mensuel", AUJOURDHUI) == "2026-11-20"
    assert sr.echeance_suivante("2026-01-10", "annuel", AUJOURDHUI) == "2027-01-10"   # ancienne échéance passée : on avance jusqu'au futur
    assert sr.echeance_suivante("2026-10-20", "unique", AUJOURDHUI) is None
    assert sr.mensualise(120, "annuel") == 10 and sr.mensualise(30, "trimestriel") == 10 and sr.mensualise(50, "unique") == 0
    assert [sr.niveau_echeance(j) for j in (None, -1, 0, 7, 8, 30, 31)] == ["inconnu", "echu", "urgent", "urgent", "bientot", "bientot", "ok"]


def test_normalisation_des_services():
    brut = [{"nom": "Render — Ster", "montant": "7,5", "periodicite": "annuel", "plateformes": ["Ster", "Ster", ""], "source": "n'importe quoi",
             "prochaine_echeance": "2026-13-45", "rappels_jours": [7, 30, 999, "x"]}, {"nom": ""}, "pas un dict"]
    (s,) = sr.normaliser_services(brut)
    assert s["montant"] == 7.5 and s["plateformes"] == ["Ster"] and s["source"] == "saisi" and s["prochaine_echeance"] is None
    assert s["rappels_jours"] == [30, 7] and s["devise"] == "USD" and s["id"]


def test_lignes_par_cluster_atlas_et_totaux_par_plateforme():
    services = sr.normaliser_services([
        {"id": "a", "nom": "MongoDB Atlas", "source": "atlas", "montant": 99, "prochaine_echeance": "2026-10-20"},
        {"id": "r", "nom": "Render", "formule": "Starter", "montant": 24, "periodicite": "annuel", "plateformes": ["ZandGo", "adLyn"]},
        {"id": "d", "nom": "Domaine sawali", "montant": 15, "devise": "EUR", "periodicite": "annuel", "actif": False}])
    lectures = {"atlas": {"le": "2026-10-15T08:00:00+00:00", "erreur": None, "devise": "USD",
                          "clusters": [{"nom": "Cluster0", "montant": 40.0}, {"nom": "ekol", "montant": 9.0}]}}
    clusters = {"Cluster0": ["SAWALI", "ZandGo", "Ster", "adLyn"], "ekol": ["e-Kol"]}
    lignes = sr.lignes_calculees(services, lectures, clusters, AUJOURDHUI)
    assert [l["nom"] for l in lignes] == ["MongoDB Atlas — Cluster0", "MongoDB Atlas — ekol", "Render", "Domaine sawali"]
    assert lignes[0]["origine"] == "atlas" and lignes[0]["montant"] == 40 and lignes[0]["cluster"] == "Cluster0" and lignes[0]["jours"] == 5
    assert lignes[0]["niveau"] == "urgent" and lignes[3]["niveau"] == "inactif"
    t = sr.totaux(lignes)
    assert t["mensuel"] == {"USD": 51.0} and t["annuel"] == {"USD": 612.0}                      # 40 + 9 + 24/12 ; le domaine inactif ne compte pas
    assert t["plateformes"]["SAWALI"] == {"USD": 10.0} and t["plateformes"]["e-Kol"] == {"USD": 9.0}   # Cluster0 : 40 ÷ 4 plateformes
    assert t["plateformes"]["ZandGo"] == {"USD": 11.0} and t["plateformes"]["adLyn"] == {"USD": 11.0}   # 10 (cluster) + 1 (moitié de Render)
    assert t["clusters"] == {"Cluster0": {"USD": 40.0}, "ekol": {"USD": 9.0}}
    # Ligne sans plateforme : « Commun »
    assert sr.totaux(sr.lignes_calculees(sr.normaliser_services([{"nom": "X", "montant": 5}]), {}, {}, AUJOURDHUI))["plateformes"] == {sr.COMMUN: {"USD": 5.0}}


def test_lecture_en_echec_garde_le_montant_saisi_et_signale_l_erreur():
    services = sr.normaliser_services([{"nom": "MongoDB Atlas", "source": "atlas", "montant": 30}])
    lignes = sr.lignes_calculees(services, {"atlas": {"le": "x", "erreur": "Clés Atlas non saisies"}}, {}, AUJOURDHUI)
    assert lignes[0]["montant"] == 30 and lignes[0]["erreur"] == "Clés Atlas non saisies" and lignes[0]["origine"] == "saisi"


def test_estimation_r2():
    e = sr.estimer_r2(stockage_go=60, operations_a=3_000_000, operations_b=25_000_000)
    assert e["montant"] == round(50 * 0.015 + 2 * 4.5 + 15 * 0.36, 2) and e["devise"] == "USD"
    assert sr.estimer_r2(5, 100, 100)["montant"] == 0                                             # sous les seuils gratuits
    rep = {"data": {"viewer": {"accounts": [{
        "stockage": [{"max": {"payloadSize": 30 * 1024 ** 3, "metadataSize": 0}, "dimensions": {"bucketName": "a"}},
                     {"max": {"payloadSize": 20 * 1024 ** 3, "metadataSize": 0}, "dimensions": {"bucketName": "b"}}],
        "operations": [{"sum": {"requests": 2_000_000}, "dimensions": {"actionType": "PutObject"}},
                       {"sum": {"requests": 11_000_000}, "dimensions": {"actionType": "GetObject"}}]}]}}}
    a = sr.analyser_reponse_r2(rep)
    assert a["buckets"] == 2 and a["montant"] == round(40 * 0.015 + 1 * 4.5 + 1 * 0.36, 2)


def test_lecture_atlas_authentification_digest_et_erreurs(monkeypatch):
    for k in ("ATLAS_API_PUBLIC_KEY", "ATLAS_API_PRIVATE_KEY", "ATLAS_ORG_ID"):
        monkeypatch.delenv(k, raising=False)
    assert "non saisies" in lancer(sr.lire_atlas())["erreur"]
    monkeypatch.setenv("ATLAS_API_PUBLIC_KEY", "pub")
    monkeypatch.setenv("ATLAS_API_PRIVATE_KEY", "priv-secret")
    monkeypatch.setenv("ATLAS_ORG_ID", "org1")
    facture = {"startDate": "2026-10-01T00:00:00Z", "endDate": "2026-11-01T00:00:00Z", "lineItems": [
        {"clusterName": "Cluster0", "totalPriceCents": 2500}, {"clusterName": "Cluster0", "totalPriceCents": 1500},
        {"clusterName": "ekol", "totalPriceCents": 900}, {"groupName": "Projet", "totalPriceCents": 100}]}

    def serveur(requete: httpx.Request) -> httpx.Response:
        assert requete.url.path == "/api/atlas/v2/orgs/org1/invoices/pending"
        if "authorization" not in requete.headers:        # premier appel : défi Digest
            return httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="MMS Public API", nonce="abc", qop="auth", algorithm=MD5'})
        return httpx.Response(200, json=facture)

    async def essai(handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await sr.lire_atlas(c)

    r = lancer(essai(serveur))
    assert r["erreur"] is None and r["total"] == 50.0 and r["clusters"][0] == {"nom": "Cluster0", "montant": 40.0}
    assert {c["nom"] for c in r["clusters"]} == {"Cluster0", "ekol", "Projet"}
    refus = lancer(essai(lambda req: httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="x", nonce="n", qop="auth"'})))
    assert "HTTP 401" in refus["erreur"] and "priv-secret" not in str(refus)                       # jamais la clé dans le message


def test_rappels_une_seule_fois_par_palier():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_t170"]
    lancer(db.settings.insert_one({"_id": sr.DOC_ID, "services": [
        {"id": "a", "nom": "Render", "formule": "Starter", "montant": 7, "devise": "USD", "periodicite": "mensuel",
         "prochaine_echeance": "2026-10-22", "plateformes": ["ZandGo"], "lien_paiement": "https://dashboard.render.com"},
        {"id": "b", "nom": "Domaine", "montant": 15, "prochaine_echeance": "2026-12-31"}]}))
    envois = []

    async def envoyer(_db, texte, _maintenant):
        envois.append(texte)
        return True

    jour = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)                 # 7 jours avant le 22 : palier 7
    assert lancer(sr.rappeler(db, jour, envoyer)) == 1
    assert "dans 7 jour(s)" in envois[0] and "Render (Starter)" in envois[0] and "https://dashboard.render.com" in envois[0]
    assert lancer(sr.rappeler(db, jour, envoyer)) == 0                       # même jour : pas de doublon
    assert lancer(sr.rappeler(db, datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc), envoyer)) == 0   # 6 jours : pas un palier
    assert lancer(sr.rappeler(db, datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc), envoyer)) == 1   # le jour même : palier 0
    assert "aujourd'hui" in envois[1]


def test_routes_liste_totaux_et_renouvellement(monkeypatch):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    for k in ("ATLAS_API_PUBLIC_KEY", "ATLAS_API_PRIVATE_KEY", "ATLAS_ORG_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        monkeypatch.delenv(k, raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_t170r"]
    app, api = FastAPI(), APIRouter(prefix="/api")
    sr.setup_services_renouveler_routes(db=db, api=api, get_current_admin=lambda: {"id": "a"})
    app.include_router(api)
    c = TestClient(app)
    v = c.put("/api/admin/services-renouveler", json={"services": [
        {"nom": "Render ZandGo", "montant": 7, "periodicite": "mensuel", "prochaine_echeance": "2026-10-20", "plateformes": ["ZandGo"]},
        {"nom": "Cloudflare R2", "source": "r2", "montant": 3, "plateformes": ["SAWALI", "Ster"]},
        {"nom": "MongoDB Atlas", "source": "atlas", "montant": 30, "plateformes": ["SAWALI"], "cluster": "Cluster0"}],
        "clusters": {"Cluster0": ["SAWALI", "ZandGo"]}}).json()
    assert len(v["lignes"]) == 3 and v["clusters"] == {"Cluster0": ["SAWALI", "ZandGo"]}
    # Clés absentes : le montant saisi reste affiché et l'erreur de lecture est signalée (jamais une erreur du serveur)
    atlas = next(l for l in v["lignes"] if l["nom"] == "MongoDB Atlas")
    assert atlas["montant"] == 30 and "non saisies" in atlas["erreur"] and v["totaux"]["clusters"] == {"Cluster0": {"USD": 30.0}}
    assert v["totaux"]["mensuel"] == {"USD": 40.0} and {"SAWALI", "Ster", "ZandGo"} <= set(v["plateformes"])
    assert v["lectures"]["atlas"]["erreur"] and v["lectures"]["r2"]["erreur"]
    assert v["lignes"][0]["nom"] == "Render ZandGo" and v["lignes"][0]["jours"] is not None      # échéance connue d'abord
    sid = next(s for s in v["services"] if s["nom"] == "Render ZandGo")["id"]
    apres = c.post(f"/api/admin/services-renouveler/{sid}/renouveler").json()
    assert next(s for s in apres["services"] if s["id"] == sid)["prochaine_echeance"] > "2026-10-20"
    assert c.post("/api/admin/services-renouveler/zz/renouveler").status_code == 404
