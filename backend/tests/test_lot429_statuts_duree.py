"""Lot 429 — statuts « en cours » / « point mort » et DURÉE estimée qui organise l'enchaînement des demandes (diagramme de Gantt).
Lancer : cd backend && python -m pytest tests/test_lot429_statuts_duree.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import demandes_plateformes as dp  # noqa: E402
from tests.test_lot384_demandes_plateformes import _appel  # noqa: E402

J = date(2026, 11, 17)


def test_duree_en_jours():
    assert dp.duree_en_jours(2, "semaine") == 14 and dp.duree_en_jours(1, "mois") == 30 and dp.duree_en_jours(1, "annee") == 365 and dp.duree_en_jours(3, "jour") == 3
    assert dp.duree_en_jours(0, "jour") is None and dp.duree_en_jours("x", "jour") is None and dp.duree_en_jours(2, "siecle") is None


def d(cle, statut, recue, valeur=None, unite=None, debut=None):
    return {"cle": cle, "statut": statut, "recue_le": recue, "duree_valeur": valeur, "duree_unite": unite, "debut_le": debut}


def test_planning_enchaine_les_demandes_en_file():
    plan = dp.planifier([d("A", "remontee", "2026-11-10", 1, "semaine"), d("B", "remontee", "2026-11-11", 3, "jour"), d("C", "remontee", "2026-11-12")], J)
    assert plan["A"] == {"debut": "2026-11-17", "fin": "2026-11-24", "jours": 7, "retard_jours": 0}
    assert plan["B"]["debut"] == "2026-11-24" and plan["B"]["fin"] == "2026-11-27"          # B commence quand A finit
    assert "C" not in plan                                                                  # sans durée : pas de place dans la file


def test_la_file_attend_la_demande_en_cours():
    plan = dp.planifier([d("E", "en_cours", "2026-11-01", 2, "semaine", "2026-11-15"), d("A", "remontee", "2026-11-10", 5, "jour")], J)
    assert plan["E"]["fin"] == "2026-11-29" and plan["A"]["debut"] == "2026-11-29" and plan["A"]["fin"] == "2026-12-04"


def test_en_cours_en_retard_et_sans_duree():
    plan = dp.planifier([d("E", "en_cours", "2026-10-01", 1, "semaine", "2026-11-01"), d("F", "en_cours", "2026-10-02")], J)
    assert plan["E"]["retard_jours"] == 9 and plan["E"]["fin"] == "2026-11-08"
    assert plan["F"]["fin"] is None and plan["F"]["debut"] == "2026-11-17"


def test_point_mort_sort_de_la_file_et_ne_decale_personne():
    plan = dp.planifier([d("P", "point_mort", "2026-11-01", 1, "mois", "2026-11-05"), d("A", "remontee", "2026-11-10", 2, "jour"),
                         d("R", "realisee", "2026-11-02", 1, "jour")], J)
    assert plan["P"] == {"debut": "2026-11-05", "fin": None, "jours": 30, "retard_jours": 0}
    assert plan["A"]["debut"] == "2026-11-17" and "R" not in plan


def test_validation_des_nouveaux_statuts():
    assert dp.valider_traitement({"statut": "en_cours", "duree_valeur": "2", "duree_unite": "semaine"}, J) == {
        "statut": "en_cours", "commentaire": None, "realisee_le": None, "prevue_le": None, "duree_valeur": 2, "duree_unite": "semaine", "debut_le": "2026-11-17"}
    assert dp.valider_traitement({"statut": "en_cours", "debut_le": "2026-11-10"}, J)["debut_le"] == "2026-11-10"
    with pytest.raises(ValueError):
        dp.valider_traitement({"statut": "point_mort"}, J)                                   # raison obligatoire
    assert dp.valider_traitement({"statut": "point_mort", "commentaire": "Attente de la maquette"}, J)["statut"] == "point_mort"
    for mauvais in ({"duree_valeur": 2, "duree_unite": "siecle"}, {"duree_valeur": "deux", "duree_unite": "jour"}, {"duree_valeur": 0, "duree_unite": "jour"}, {"duree_valeur": 1000, "duree_unite": "jour"}):
        with pytest.raises(ValueError):
            dp.valider_traitement({"statut": "remontee", **mauvais}, J)
    assert dp.valider_traitement({"statut": "remontee", "duree_valeur": "", "duree_unite": ""}, J)["duree_valeur"] is None


def test_parcours_avec_duree_historique_et_planning_retourne_a_la_plateforme():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot429"]
    asyncio.get_event_loop().run_until_complete(db.liluvine_emetteurs.insert_one({"code": "albarka", "nom": "ALBARKA", "secret": "cle-albarka", "actif": True}))
    app, api = FastAPI(), APIRouter(prefix="/api")
    dp.setup_demandes_plateformes_routes(db=db, api=api, get_current_user=lambda: {"role": "admin"})
    app.include_router(api)
    c = TestClient(app)
    _appel(c, [{"ref_locale": "l1", "type": "correction", "texte": "Un"}, {"ref_locale": "l2", "type": "nouveaute", "texte": "Deux"}])
    url = "/api/admin/plateformes/albarka/demandes/"
    assert c.put(url + "DEM-ALBARKA-0001", json={"statut": "en_cours", "duree_valeur": 1, "duree_unite": "semaine"}).status_code == 200
    assert c.put(url + "DEM-ALBARKA-0002", json={"statut": "remontee", "duree_valeur": 3, "duree_unite": "jour"}).status_code == 200
    d = {x["numero"]: x for x in _appel(c, []).json()["demandes"]}
    # La plateforme reçoit statut, durée et dates du PLANNING : la 2e commence quand la 1re finit
    assert d["DEM-ALBARKA-0001"]["statut"] == "en_cours" and d["DEM-ALBARKA-0001"]["duree_valeur"] == 1
    assert d["DEM-ALBARKA-0002"]["debut_prevu_le"] == d["DEM-ALBARKA-0001"]["prevue_le"]
    # Point mort puis reprise : l'historique garde les deux changements
    assert c.put(url + "DEM-ALBARKA-0001", json={"statut": "point_mort", "commentaire": "Attente des données"}).status_code == 200
    assert c.put(url + "DEM-ALBARKA-0001", json={"statut": "en_cours", "duree_valeur": 1, "duree_unite": "semaine"}).status_code == 200
    h = {x["numero"]: x for x in _appel(c, []).json()["demandes"]}["DEM-ALBARKA-0001"]["historique"]
    assert [e["statut"] for e in h] == ["en_cours", "point_mort", "en_cours"]
    liste = {x["numero"]: x for x in c.get("/api/admin/plateformes/demandes").json()["demandes"]}
    assert liste["DEM-ALBARKA-0001"]["fin_prevue_le"] and liste["DEM-ALBARKA-0002"]["debut_prevu_le"] == liste["DEM-ALBARKA-0001"]["fin_prevue_le"]
