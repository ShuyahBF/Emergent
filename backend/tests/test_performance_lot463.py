"""Lot 463 — mémoire du serveur, appels les plus lents, alerte WhatsApp, appels refusés du webhook en pause, suivi horaire du modèle Meta. Aucun accès réseau."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot463")
from datetime import datetime, timezone

import mongomock_motor
import pytest

import consignes_masse as cm
import performance_serveur as ps
from routes import error_registry as er


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


MO = 1024 * 1024


# ---------------------------------------------------------------- mémoire
def test_lecture_cgroup_v2_memoire_de_travail_et_limite(tmp_path):
    (tmp_path / "memory.current").write_text(str(490 * MO))
    (tmp_path / "memory.stat").write_text(f"anon 1\ninactive_file {40 * MO}\nactive_file 5\n")
    (tmp_path / "memory.max").write_text(str(512 * MO))
    statut = tmp_path / "status"
    statut.write_text("Name: python\nVmRSS:\t  262144 kB\n")
    brut = ps.lire_memoire(str(statut), str(tmp_path))
    assert brut["conteneur"] == 450 * MO and brut["limite_conteneur"] == 512 * MO and brut["processus"] == 256 * MO   # cache de fichiers retiré


def test_cgroup_sans_limite_ou_absent(tmp_path):
    (tmp_path / "memory.current").write_text(str(100 * MO))
    (tmp_path / "memory.max").write_text("max")
    assert ps.lire_memoire(str(tmp_path / "rien"), str(tmp_path))["limite_conteneur"] is None
    vide = ps.lire_memoire(str(tmp_path / "rien"), str(tmp_path / "absent"))
    assert vide == {"processus": None, "conteneur": None, "limite_conteneur": None}                  # poste de développement : rien de lisible, pas d'erreur


def test_mesure_niveaux_seuil_et_origine_de_la_limite():
    brut = {"processus": 300 * MO, "conteneur": 480 * MO, "limite_conteneur": 512 * MO}
    m = ps.calculer_mesure(brut, ps.reglages_memoire({}))
    assert m["utilise_mo"] == 480 and m["limite_mo"] == 512 and m["pourcentage"] == 93.8 and m["niveau"] == "plein" and m["alerte"] and m["origine_limite"] == "conteneur"
    m = ps.calculer_mesure(brut, ps.reglages_memoire({"perf_memoire_limite_mo": 2048, "perf_memoire_seuil_pct": 70}))   # offre agrandie : le réglage prime
    assert m["limite_mo"] == 2048 and m["pourcentage"] == 23.4 and m["niveau"] == "ok" and not m["alerte"] and m["origine_limite"] == "réglage" and m["seuil_mo"] == 1433.6
    assert ps.niveau(69.9) == "ok" and ps.niveau(70) == "attention" and ps.niveau(90) == "plein"
    sans_conteneur = ps.calculer_mesure({"processus": 200 * MO, "conteneur": None, "limite_conteneur": None}, ps.reglages_memoire({}))
    assert sans_conteneur["utilise_mo"] == 200 and sans_conteneur["limite_mo"] == 512 and sans_conteneur["origine_limite"] == "défaut"
    assert ps.calculer_mesure({"processus": None, "conteneur": None, "limite_conteneur": None}, {})["lisible"] is False


@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot463"]
    run(d["settings"].insert_one({"_id": "global", "perf_memoire_seuil_pct": 85}))
    return d


def lecteur(mo):
    return lambda: {"processus": mo * MO, "conteneur": mo * MO, "limite_conteneur": 512 * MO}


def test_surveillance_horaire_echantillon_et_alerte_une_fois_par_jour(db):
    envois = []

    async def envoyer(texte):
        envois.append(texte)
        return True

    t0 = datetime(2026, 11, 26, 9, 12, tzinfo=timezone.utc)
    run(ps.surveiller(db, t0, lecteur(300), envoyer))                                   # 58 % : pas d'alerte
    assert envois == []
    r = run(ps.surveiller(db, t0.replace(hour=10), lecteur(480), envoyer))               # 93,8 % : alerte
    assert r["alerte"] is True and len(envois) == 1 and "480" in envois[0] and "512" in envois[0]
    run(ps.surveiller(db, t0.replace(hour=11), lecteur(490), envoyer))                   # même jour : pas de 2e message
    assert len(envois) == 1
    run(ps.surveiller(db, t0.replace(day=27), lecteur(490), envoyer))                    # le lendemain : une nouvelle alerte
    assert len(envois) == 2
    m = run(ps.mesurer(db, lecteur=lecteur(100)))
    assert [h["utilise_mo"] for h in m["historique"]] == [300, 480, 490, 490]            # un échantillon par passage horaire


# ---------------------------------------------------------------- appels lents
def test_chemin_sans_identifiant():
    assert ps.normaliser_chemin("/api/clients/5f3a9c2e7b1d/documents?x=1") == "/api/clients/{id}/documents"
    assert ps.normaliser_chemin("/api/a/12/b/123e4567-e89b-12d3-a456-426614174000") == "/api/a/{id}/b/{id}"
    assert ps.normaliser_chemin("/api/version") == "/api/version"


def test_classement_moyenne_cinq_derniers_maximum_lents_erreurs():
    s = ps.SuiviAppels()
    for ms in (100, 200, 300, 400, 500, 3000):
        s.enregistrer("GET", "/api/lente", ms, 200)
    s.enregistrer("GET", "/api/lente", 50, 503)
    s.enregistrer("GET", "/api/rapide", 10, 200)
    c = s.classement()
    assert [x["route"] for x in c] == ["/api/lente", "/api/rapide"]                         # tri par moyenne décroissante
    lente = c[0]
    assert lente["appels"] == 7 and lente["moyenne_ms"] == 650 and lente["maximum_ms"] == 3000 and lente["dernier_ms"] == 50
    assert lente["derniers_ms"] == [300, 400, 500, 3000, 50] and lente["lents"] == 1 and lente["erreurs"] == 1
    assert s.resume()["appels"] == 8 and s.resume()["lents"] == 1
    s.reinitialiser()
    assert s.classement() == [] and s.resume()["appels"] == 0


def test_trop_de_routes_sont_regroupees():
    s = ps.SuiviAppels(max_routes=2)
    for i in range(5):
        s.enregistrer("GET", f"/api/r{i}", 10, 200)
    assert len(s.routes) == 3 and sum(f["n"] for f in s.routes.values()) == 5               # 2 routes + « autres »


def test_intergiciel_mesure_les_appels_api_et_ignore_le_reste():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse, StreamingResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def lente(request):
        await asyncio.sleep(0.05)
        return PlainTextResponse("ok")

    async def flux(request):
        return StreamingResponse(iter([b"data: 1\n\n"]), media_type="text/event-stream")

    async def erreur(request):
        return PlainTextResponse("panne", status_code=503)

    suivi = ps.SuiviAppels()
    app = Starlette(routes=[Route("/api/lente/{n}", lente), Route("/api/flux", flux), Route("/api/health", lente), Route("/api/panne", erreur), Route("/site", lente)])
    app.add_middleware(ps.MesureAppels, suivi=suivi)
    c = TestClient(app)
    c.get("/api/lente/12"); c.get("/api/lente/13"); c.get("/api/flux"); c.get("/api/health"); c.get("/api/panne"); c.get("/site"); c.options("/api/lente/1")
    r = {x["route"]: x for x in suivi.classement()}
    assert set(r) == {"/api/lente/{n}", "/api/panne"}                                       # route déclarée (pas l'identifiant) ; flux, sonde, hors /api et OPTIONS ignorés
    assert r["/api/lente/{n}"]["appels"] == 2 and r["/api/lente/{n}"]["moyenne_ms"] >= 45 and r["/api/panne"]["erreurs"] == 1


def test_apres_redemarrage_le_dernier_releve_horaire_est_rendu_et_signale(db):
    ps.SUIVI.reinitialiser()
    ps.SUIVI.enregistrer("GET", "/api/x", 1200, 200)
    run(ps.surveiller(db, datetime(2026, 11, 26, 9, 12, tzinfo=timezone.utc), lecteur(100), None))
    assert run(ps.appels(db))["source"] == "direct"
    ps.SUIVI.reinitialiser()                                                                  # redémarrage : plus rien en mémoire
    r = run(ps.appels(db))
    assert r["source"] == "releve" and r["classement"][0]["route"] == "/api/x" and r["releve_le"]
    assert run(ps.appels(mongomock_motor.AsyncMongoMockClient()["vide"]))["source"] == "vide"


# ---------------------------------------------------------------- webhook en pause
def test_appels_refuses_comptes_par_adresse_et_bornes():
    er._REFUSES.clear()
    for _ in range(3):
        er.noter_appel_refuse("185.124.200.63")
    er.noter_appel_refuse("41.138.98.178")
    r = er.appels_refuses()
    assert r["total"] == 4 and r["adresses"][0]["ip"] == "185.124.200.63" and r["adresses"][0]["nombre"] == 3
    for i in range(er.MAX_ADRESSES_REFUSEES + 20):
        er.noter_appel_refuse(f"10.0.{i // 250}.{i % 250}")
    assert len(er._REFUSES) <= er.MAX_ADRESSES_REFUSEES
    er._REFUSES.clear()


# ---------------------------------------------------------------- modèle Meta : suivi horaire
class MetaFaux:
    def __init__(self, statut):
        self.statut, self.appels = statut, 0

    async def __call__(self, methode, url, jeton, json=None, params=None):
        self.appels += 1
        return 200, {"data": [{"id": "t1", "name": "information_rdv", "language": "fr", "category": "UTILITY", "status": self.statut}]}


def test_suivi_horaire_active_a_l_approbation_et_ne_fait_rien_sinon(db):
    run(db["settings"].update_one({"_id": "global"}, {"$set": {"wa_access_token": "x", "wa_business_account_id": "1"}}))
    meta = MetaFaux("PENDING")
    assert run(cm.surveiller_modele(db, meta)) is None and meta.appels == 0                 # jamais soumis : aucun appel à Meta
    run(db["settings"].update_one({"_id": cm.ID_FICHE}, {"$set": {"soumission": {"nom": "information_rdv", "langue": "fr", "statut": "PENDING"}}}, upsert=True))
    v = run(cm.surveiller_modele(db, meta))
    assert v["statut"] == "PENDING" and v["active"] is False and meta.appels == 1           # toujours en attente : pas activé
    meta.statut = "APPROVED"
    v = run(cm.surveiller_modele(db, meta))
    assert v["statut"] == "APPROVED" and v["active"] is True and v["active_auto_le"]        # approuvé : activé tout seul
    assert run(cm.surveiller_modele(db, meta)) is None and meta.appels == 2                  # approuvé : plus aucun appel horaire
