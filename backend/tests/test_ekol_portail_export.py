"""Portail e-Kol — export signé des tables e-Kol synchronisées (routes/ekol_portail_export.py) :
signature valide / fausse / périmée / absente, clé non configurée, pagination par curseur (ordre, reprise des seules
lignes modifiées), colonnes binaires retirées, table non synchronisée signalée, table inconnue refusée.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_ekol_portail_export.py -q
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.ekol_portail_export as ex  # noqa: E402
import routes.loois_synchro as ls  # noqa: E402

CLE = "cle-portail-test"
CHEMIN = "/api/ekol-portail/export"


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db(monkeypatch):
    """Base simulée + clé partagée définie."""
    monkeypatch.setenv("EKOL_PORTAIL_HMAC", CLE)
    return mongomock_motor.AsyncMongoMockClient()["sawali_test"]


def client(db):
    """Application FastAPI minimale avec la seule route d'export."""
    from fastapi import APIRouter, FastAPI, Request
    from fastapi.testclient import TestClient
    api = APIRouter(prefix="/api")
    async def utilisateur(request: Request):
        """Lot 134 : utilisateur simulé (en-tête X-Role : admin par défaut)."""
        return {"id": "u", "role": request.headers.get("X-Role", "admin")}
    ex.setup_ekol_portail_export_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def appel(c, params, cle=CLE, decalage=0, signature=None):
    """GET signé comme le portail : X-Signature = HMAC(clé, "<ts>.GET <chemin>?<requête>")."""
    requete = urlencode(params)
    ts = str(int(time.time()) + decalage)
    sig = signature if signature is not None else ex.calculer_signature(cle, ts, "GET", CHEMIN, requete)
    return c.get(f"{CHEMIN}?{requete}", headers={"X-Timestamp": ts, "X-Signature": sig})


def remplir(db, n=5, site="ECOLE-X"):
    """n lignes ElèveEdu synchronisées (collection du lot 68) + entrée au catalogue."""
    nom = ls.nom_collection("eKol", site, "ElèveEdu")
    base = datetime(2026, 10, 1, 8, 0, 0)
    docs = [{"IDElève": f"E{i}", "Nom": f"NOM{i}", "Matricule": f"M{i}", "Photo": "AAAA",
             "_hf_cle": f"E{i}", "_hf_maj": base + timedelta(minutes=i // 2)} for i in range(n)]
    lancer(db[nom].insert_many(docs))
    lancer(db.loois_synchro_tables.insert_one({"application": "eKol", "site": site, "table": "ElèveEdu",
                                               "collection": nom, "nb_documents": n}))
    return nom


def test_signature_valide_et_pagination(db):
    remplir(db, 5)
    c = client(db)
    vus, depuis = [], ""
    for _ in range(5):
        r = appel(c, {"site": "Ecole X", "table": "EleveEdu", "depuis": depuis, "limite": 2})
        assert r.status_code == 200, r.text
        corps = r.json()
        assert corps["disponible"] is True and corps["table"] == "ElèveEdu" and corps["nb_documents"] == 5
        for ligne in corps["lignes"]:
            assert "Photo" not in ligne and "_id" not in ligne      # binaires et identifiant Mongo retirés
        vus += [l["IDElève"] for l in corps["lignes"]]
        depuis = corps["curseur_suivant"]
        if corps["termine"]:
            break
    assert vus == ["E0", "E1", "E2", "E3", "E4"]                    # ordre (_hf_maj, _hf_cle), sans doublon


def test_reprise_lignes_modifiees_seulement(db):
    nom = remplir(db, 4)
    c = client(db)
    corps = appel(c, {"site": "ECOLE-X", "table": "ElèveEdu", "limite": 100}).json()
    curseur = corps["curseur_suivant"]
    assert corps["termine"] is True and len(corps["lignes"]) == 4
    # Rien de neuf : page vide, curseur conservé
    vide = appel(c, {"site": "ECOLE-X", "table": "ElèveEdu", "depuis": curseur}).json()
    assert vide["lignes"] == [] and vide["curseur_suivant"] == curseur
    # Une ligne modifiée par la synchro Loois → seule elle revient
    lancer(db[nom].update_one({"_hf_cle": "E1"}, {"$set": {"Nom": "CHANGE", "_hf_maj": datetime(2026, 10, 2)}}))
    neuf = appel(c, {"site": "ECOLE-X", "table": "ElèveEdu", "depuis": curseur}).json()
    assert [l["Nom"] for l in neuf["lignes"]] == ["CHANGE"]


def test_signature_fausse_perimee_absente(db):
    remplir(db, 1)
    c = client(db)
    p = {"site": "ECOLE-X", "table": "ElèveEdu"}
    assert appel(c, p, cle="autre-cle").status_code == 401
    assert appel(c, p, decalage=-301).status_code == 401              # plus de 5 minutes
    assert appel(c, p, signature="00" * 32).status_code == 401
    assert c.get(f"{CHEMIN}?{urlencode(p)}").status_code == 401       # aucun en-tête
    # Signature d'une AUTRE requête (autre table) rejouée : refusée
    ts = str(int(time.time()))
    sig = ex.calculer_signature(CLE, ts, "GET", CHEMIN, urlencode({"site": "ECOLE-X", "table": "Paiements"}))
    r = c.get(f"{CHEMIN}?{urlencode(p)}", headers={"X-Timestamp": ts, "X-Signature": sig})
    assert r.status_code == 401


def test_cle_non_configuree(db, monkeypatch):
    monkeypatch.delenv("EKOL_PORTAIL_HMAC")
    r = appel(client(db), {"site": "ECOLE-X", "table": "ElèveEdu"})
    assert r.status_code == 503


def test_table_non_synchronisee_et_inconnue(db):
    c = client(db)
    r = appel(c, {"site": "ECOLE-Y", "table": "NotesExamens"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["disponible"] is False and "SAWALI" in corps["message"] and "NotesExamens" in corps["message"]
    assert appel(c, {"site": "ECOLE-Y", "table": "TableQuiNExistePas"}).status_code == 422
    assert appel(c, {"site": "ECOLE-Y", "table": "ElèveEdu", "depuis": "%%%"}).status_code == 422


def test_message_signe_logique_pure():
    assert ex.message_a_signer("123", "get", "/api/x", "a=1") == "123.GET /api/x?a=1"
    assert ex.message_a_signer("123", "GET", "/api/x", "") == "123.GET /api/x"
    assert ex.verifier_signature(CLE, "100", ex.calculer_signature(CLE, "100", "GET", "/p", "q=1"), "GET", "/p", "q=1",
                                 maintenant=200) is True
    assert ex.decoder_curseur(ex.coder_curseur(datetime(2026, 1, 1), "K")) == (datetime(2026, 1, 1), "K")


def test_etat_pour_la_rubrique_lot134(db):
    """Lot 134 : l'administrateur voit la clé configurée et les tables utiles synchronisées par école."""
    remplir(db, n=3, site="ECOLE-X")
    c = client(db)
    assert c.get("/api/admin/ekol-portail/etat", headers={"X-Role": "pharmacien"}).status_code == 403
    r = c.get("/api/admin/ekol-portail/etat").json()
    assert r["cle_configuree"] is True and "NotesExamens" in r["tables_utiles"]
    ecole = r["ecoles"][0]
    assert ecole["site"] == "ECOLE-X" and ecole["tables"]["ElèveEdu"]["nb_documents"] == 3
