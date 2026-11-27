"""Lot 482 — volumétrie des tables HFSQL : schémas (3 plateformes), requêtes COUNT en lecture seule, estimation de la taille du cache, routes administrateur. Aucun accès réseau (file SQL simulée)."""
import asyncio
import os
from datetime import date

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot482")

import pytest

import volumetrie_hfsql as vh


def test_schemas_des_trois_plateformes_et_tailles():
    p = {x["cle"]: x for x in vh.plateformes()}
    assert set(p) == {"biolog", "aizenta", "ekol"} and p["biolog"]["tables"] == 803 and p["aizenta"]["tables"] == 549 and p["ekol"]["tables"] == 89
    vc = vh.table_connue("biolog", "VenteClinique")
    assert vc["colonnes"] == 54 and vc["colonne_date"] == "Date Vente" and vc["octets_atlas"] > vc["octets_hfsql"] > 0 and vc["memos"] == 0       # un document Atlas pèse plus qu'une ligne HFSQL (noms des champs)
    assert vh.table_connue("biolog", "Clinique")["memos"] >= 1                                                                                  # champs mémo repérés : jamais mis en cache
    assert vh.table_connue("biolog", "N'existe pas") is None and vh.tables("inconnue") == []


def test_requetes_en_lecture_seule_acceptees_par_le_controle_prudent():
    from routes.loois_sql_distant import verifier
    for sql in (vh.sql_total("VenteClinique"), vh.sql_recents("VenteClinique", "Date Vente", date(2026, 11, 20)), vh.sql_total("A_Acheté")):
        ok, nature, raison = verifier(sql)
        assert ok and nature == "SELECT", raison
    assert vh.sql_recents("VenteClinique", "Date Vente", date(2026, 11, 20)) == "SELECT COUNT(*) FROM [VenteClinique] WHERE [Date Vente] >= '20261120'"


def test_lecture_des_valeurs_et_formats():
    assert vh.premiere_valeur([["1 234"]]) == 1234 and vh.premiere_valeur([["12 000"]]) == 12000 and vh.premiere_valeur([["7,0"]]) == 7
    assert vh.premiere_valeur([]) is None and vh.premiere_valeur([["abc"]]) is None
    assert vh.jours_valides("7") == 7 and vh.jours_valides(0) == 1 and vh.jours_valides(999) == vh.JOURS_MAX and vh.jours_valides("x") == 7
    assert vh.estimation_octets(1000, 2165) == 2_165_000 and vh.estimation_octets(None, 10) is None
    assert vh.formater_octets(512) == "512 o" and vh.formater_octets(2048) == "2,0 Ko" and vh.formater_octets(5 * (1 << 20)) == "5,0 Mo" and vh.formater_octets(None) == "—"


@pytest.fixture()
def banc():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import routes.loois_sql_distant as lsd
    import routes.volumetrie_hfsql as rv
    rv.PAS_S = 0.01
    rv.ATTENTE_S = 0.5
    envoyees = []
    etat = {"silence": False, "echec_recents": False}

    async def creer(corps, ip, auteur=""):
        envoyees.append((corps["client"], corps["sql"], auteur))
        return {"id": f"r{len(envoyees) - 1}"}

    async def detail(rid):
        client, sql, _ = envoyees[int(rid[1:])]
        if etat["silence"]:
            return {"etat": "attente"}
        if "WHERE" in sql and etat["echec_recents"]:
            return {"etat": "echec", "ok": False, "message": "70208 : colonne inconnue"}
        return {"etat": "terminee", "ok": True, "lignes": [["12 500"]] if "WHERE" not in sql else [["340"]]}

    async def clients():
        return {"clients": [{"code": "IPM", "en_ligne": False}, {"code": "CMC", "en_ligne": True}]}
    lsd.INTERNE.clear()
    lsd.INTERNE.update(creer=creer, detail=detail, clients=clients)
    admin = {"user": {"id": "u1", "role": "admin", "email": "a@x.bf"}}
    app = FastAPI()
    api = APIRouter(prefix="/api")

    async def utilisateur():
        return admin["user"]
    rv.setup_volumetrie_hfsql_routes(db=None, api=api, get_current_user=utilisateur)
    app.include_router(api)
    return TestClient(app), admin, envoyees, etat


def test_routes_plateformes_tables_et_comptage(banc):
    c, admin, envoyees, etat = banc
    p = c.get("/api/admin/volumetrie/plateformes").json()
    assert [x["code"] for x in p["clients"]] == ["CMC", "IPM"] and p["clients"][0]["en_ligne"] is True and len(p["plateformes"]) == 3          # les clients en ligne d'abord
    t = c.get("/api/admin/volumetrie/tables", params={"plateforme": "biolog"}).json()["tables"]
    assert len(t) == 803 and any(x["nom"] == "VenteClinique" for x in t) and c.get("/api/admin/volumetrie/tables", params={"plateforme": "x"}).status_code == 404
    r = c.post("/api/admin/volumetrie/compter", json={"client": "cmc", "plateforme": "biolog", "table": "VenteClinique", "jours": 7})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 12500 and d["recents"] == 340 and d["jours"] == 7 and d["colonne_date"] == "Date Vente" and d["erreur_total"] == "" and d["erreur_recents"] == ""
    assert d["taille_cache"] == 340 * d["octets_atlas"] and d["taille_totale"] == 12500 * d["octets_hfsql"]                                      # estimation du cache = lignes des 7 jours × taille d'un document
    assert [e[0] for e in envoyees] == ["CMC", "CMC"] and envoyees[0][1] == "SELECT COUNT(*) FROM [VenteClinique]" and "WHERE [Date Vente] >= '" in envoyees[1][1]
    assert envoyees[0][2].startswith("Volumétrie a@x.bf")
    # table sans colonne de date : seulement le total ; table ou client invalides refusés
    sans = c.post("/api/admin/volumetrie/compter", json={"client": "CMC", "plateforme": "biolog", "table": "Prestations"}).json()
    assert sans["total"] == 12500 and sans["recents"] is None and sans["taille_cache"] is None
    assert c.post("/api/admin/volumetrie/compter", json={"client": "CMC", "plateforme": "biolog", "table": "X'; DROP TABLE"}).status_code == 422
    assert c.post("/api/admin/volumetrie/compter", json={"client": "C M C!", "plateforme": "biolog", "table": "Prestations"}).status_code == 422


def test_erreurs_claires_delai_et_droits(banc):
    c, admin, envoyees, etat = banc
    etat["echec_recents"] = True
    d = c.post("/api/admin/volumetrie/compter", json={"client": "CMC", "plateforme": "biolog", "table": "VenteClinique"}).json()
    assert d["total"] == 12500 and d["recents"] is None and "70208" in d["erreur_recents"]                                                    # l'erreur HFSQL est montrée telle quelle
    etat["echec_recents"] = False; etat["silence"] = True
    d = c.post("/api/admin/volumetrie/compter", json={"client": "CMC", "plateforme": "biolog", "table": "VenteClinique"}).json()
    assert d["total"] is None and "n'a répondu" in d["erreur_total"]
    admin["user"] = {"id": "u2", "role": "client"}
    assert c.get("/api/admin/volumetrie/plateformes").status_code == 403
    assert c.post("/api/admin/volumetrie/compter", json={"client": "CMC", "plateforme": "biolog", "table": "Prestations"}).status_code == 403
