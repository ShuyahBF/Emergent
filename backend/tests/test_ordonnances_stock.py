"""Lot 39 — Stock par client/dépôt (envoi Loois) et vérification des ordonnances.

Lecture IA et VIDAL simulés, MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_ordonnances_stock.py -q
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.ordonnances_stock as os_mod  # noqa: E402
import stock_produits as sp  # noqa: E402

USERS = {
    "pharma_phl": {"id": "pharma_phl", "role": "pharmacien", "client_code": "PHL", "company": "Clinique Philadelphie"},
    "pharma_amy": {"id": "pharma_amy", "role": "pharmacien", "client_code": "AMY"},
    "sans_fonction": {"id": "sans_fonction", "role": "pharmacien", "client_code": "WDD"},
    "admin": {"id": "admin", "role": "admin"},
}
JETON = "jeton-loois-test"


def _png() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("STOCK_SYNC_TOKEN", JETON)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_ordo"]
    lu = {"lignes": []}
    vidal = {"actif": True, "appels": []}

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def fonction_active(user, cle):
        assert cle == "ordonnances_stock"
        return user["id"] != "sans_fonction"

    async def lire(images):
        assert images
        return lu

    async def vidal_rechercher(user, q):
        vidal["appels"].append(q)
        if not vidal["actif"]:
            raise HTTPException(status_code=403, detail="VIDAL non activé")
        return {"results": [{"title": "DOLIPRANE 1000 mg cp", "vidal_id": "1", "vmp_id": "77"}]}

    async def vidal_equivalents(user, vmp_id):
        assert vmp_id == "77"
        return {"equivalents": [{"title": "EFFERALGAN 1 g cp eff", "vidal_id": "2"},
                                {"title": "DAFALGAN 1 g cp", "vidal_id": "3"}]}

    api = APIRouter(prefix="/api")
    os_mod.attach_ordonnances_stock_routes(api=api, db=db, get_current_user=get_user,
                                           fonction_active=fonction_active, vidal_rechercher=vidal_rechercher,
                                           vidal_equivalents=vidal_equivalents, lire_ordonnance=lire)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
    yield type("E", (), {"c": client, "db": db, "lu": lu, "vidal": vidal,
                         "run": lambda self, f: client.portal.call(f)})()
    client.__exit__(None, None, None)


def _h(u):
    return {"X-User": u}


def _sync(env, depot, produits, client="PHL", complet=False, jeton=JETON):
    return env.c.post("/api/stock-produits/sync", headers={"X-Sync-Token": jeton}, json={
        "code_client": client, "code_depot": depot, "complet": complet, "produits": produits})


def _stock_phm(env):
    assert _sync(env, "PPH", [
        {"code_produit": "P1", "libelle": "DOLIPRANE 1G CP", "mesure": "B/8", "isalle": 3, "imagasin": 10,
         "peremption": "20280601", "prix_public": 900},
        {"code_produit": "P2", "libelle": "DOLIPRANE 500MG CP", "mesure": "B/16", "isalle": 5, "imagasin": 0},
        {"code_produit": "P3", "libelle": "EFFERALGAN 1G CP EFF", "mesure": "B/8", "isalle": 4, "imagasin": 0,
         "peremption": "20401101"},
        {"code_produit": "P4", "libelle": "AMOXICILLINE 500MG GELULE", "mesure": "B/12", "isalle": 0, "imagasin": 0},
        {"code_produit": "P5", "libelle": "SPASFON 40MG INJ", "mesure": "B/1", "isalle": 1, "imagasin": 0,
         "peremption": "20240101"},
    ]).status_code == 200
    assert _sync(env, "PLB", [{"code_produit": "L1", "libelle": "TUBE EDTA VIOLET", "mesure": "B/100",
                               "isalle": 0, "imagasin": 20}]).status_code == 200
    assert _sync(env, "AMY", [{"code_produit": "A1", "libelle": "DOLIPRANE 1G CP", "isalle": 99}],
                 client="AMY").status_code == 200


def test_sync_loois_et_filtrage_par_client(env):
    # Jeton obligatoire
    assert _sync(env, "PPH", [], jeton="faux").status_code == 401
    _stock_phm(env)
    # Le pharmacien de PHL voit ses 2 dépôts (PPH, PLB), jamais le stock d'AMY
    d = env.c.get("/api/stock-produits/depots", headers=_h("pharma_phl")).json()
    assert [x["code_depot"] for x in d["depots"]] == ["PLB", "PPH"] and d["code_client"] == "PHL"
    r = env.c.get("/api/stock-produits?q=doliprane&code_client=AMY", headers=_h("pharma_phl")).json()
    assert r["code_client"] == "PHL" and {p["code_produit"] for p in r["produits"]} == {"P1", "P2"}
    assert env.c.get("/api/stock-produits?depot=PLB", headers=_h("pharma_phl")).json()["produits"][0]["stock"] == 20
    # L'Admin peut choisir le client
    assert len(env.c.get("/api/stock-produits?code_client=AMY", headers=_h("admin")).json()["produits"]) == 1
    # Envoi complet : les produits absents de la liste sont retirés du dépôt
    j = _sync(env, "PLB", [{"code_produit": "L2", "libelle": "TUBE SEC ROUGE", "imagasin": 3}], complet=True).json()
    assert j["retires"] == 1
    assert _sync(env, "PLB", [], complet=True).status_code == 400
    # Fonction non activée
    assert env.c.get("/api/stock-produits", headers=_h("sans_fonction")).status_code == 403


def test_alerte_peremption():
    from datetime import date
    j = date(2026, 9, 29)
    assert sp.alerte_peremption("20260801", j) == "perime"
    assert sp.alerte_peremption("20261201", j) == "proche"
    assert sp.alerte_peremption("20270101", j) is None
    assert sp.alerte_peremption(None, j) is None


def test_rapprochement():
    produits = [sp.document_produit(p, code_client="X", code_depot="D", source="t") for p in [
        {"code_produit": "1", "libelle": "DOLIPRANE 1G CP"},
        {"code_produit": "2", "libelle": "DOLIPRANE 500MG CP"},
        {"code_produit": "3", "libelle": "AMOXICILLINE 500MG GELULE"}]]
    r = os_mod.rapprocher({"nom": "Doliprane", "dosage": "1000 mg"}, produits)
    assert r["produit_id"] == "X:D:1" and r["confiance"] == "sure"          # 1000 mg = 1 g
    assert os_mod.rapprocher({"nom": "Doliprane"}, produits)["confiance"] == "a_confirmer"   # dosage non précisé
    assert os_mod.rapprocher({"nom": "Augmentin", "dosage": "1g"}, produits)["candidats"] == []


def test_ordonnance_complete(env):
    _stock_phm(env)
    env.lu.update({"date_ordonnance": "29/09/2026", "lignes": [
        {"nom": "Doliprane", "dosage": "1000 mg", "forme": "comprimé", "quantite": 2, "posologie": "1 cp x 3/j"},
        {"nom": "Amoxicilline", "dosage": "500 mg", "quantite": 1},
        {"nom": "Spasfon", "dosage": "40 mg", "forme": "injectable", "quantite": 1},
        {"nom": "Augmentin", "dosage": "1 g", "quantite": 1},
    ]})
    r = env.c.post("/api/ordonnances-stock", headers=_h("pharma_phl"), data={"depots": "PPH"},
                   files=[("photos", ("o.png", _png(), "image/png"))])
    assert r.status_code == 200, r.text
    o = r.json()
    doli, amox, spas, aug = o["lignes"]
    assert doli["statut"] == "disponible" and doli["produit"]["libelle"] == "DOLIPRANE 1G CP"
    assert (doli["produit"]["isalle"], doli["produit"]["imagasin"], doli["produit"]["disponible"]) == (3, 10, 13)
    assert amox["statut"] == "rupture"
    assert spas["statut"] == "disponible" and spas["produit"]["alerte_peremption"] == "perime"
    assert aug["statut"] == "absent" and aug["candidats"] == []
    # Le nom du patient n'est jamais stocké (seules les lignes le sont)
    stocke = env.run(lambda: env.db.ordonnances_stock.find_one({"id": o["id"]}))
    assert set(stocke) >= {"lignes", "code_client"} and "patient" not in stocke

    # Équivalents VIDAL pour la rupture : EFFERALGAN 1G est en stock, DAFALGAN non
    env.lu["lignes"] = [{"nom": "Doliprane", "dosage": "1000 mg", "quantite": 1}]
    o2 = env.c.post(f"/api/ordonnances-stock/{o['id']}/lignes/1/equivalents", headers=_h("pharma_phl")).json()
    eq = o2["lignes"][1]
    assert eq["equivalents_etat"] == "ok" and [e["libelle"] for e in eq["equivalents"]] == \
        ["DOLIPRANE 1G CP", "EFFERALGAN 1G CP EFF"]
    assert eq["equivalents"][1]["alerte_peremption"] is None
    # Le pharmacien choisit l'équivalent
    o3 = env.c.put(f"/api/ordonnances-stock/{o['id']}/lignes/1", headers=_h("pharma_phl"),
                   json={"produit_id": "PHL:PPH:P3", "quantite": 1}).json()
    assert o3["lignes"][1]["statut"] == "disponible"
    # Produit d'un autre client : refusé
    assert env.c.put(f"/api/ordonnances-stock/{o['id']}/lignes/1", headers=_h("pharma_phl"),
                     json={"produit_id": "AMY:AMY:A1"}).status_code == 400

    # Réservation : disponible diminue pour les AUTRES ordonnances
    res = env.c.post(f"/api/ordonnances-stock/{o['id']}/reserver", headers=_h("pharma_phl")).json()
    # SPASFON (périmé 01/2024) n'est jamais réservé
    assert {(r["libelle"], r["quantite"]) for r in res["reservations"]} == \
        {("DOLIPRANE 1G CP", 2), ("EFFERALGAN 1G CP EFF", 1)}
    assert env.c.post(f"/api/ordonnances-stock/{o['id']}/reserver", headers=_h("pharma_phl")).json()["reservations"] == []
    stock = {p["code_produit"]: p for p in env.c.get("/api/stock-produits?depot=PPH", headers=_h("pharma_phl")).json()["produits"]}
    assert (stock["P1"]["reserve"], stock["P1"]["disponible"]) == (2, 11)
    # Vendue / annulée
    rid = next(r["id"] for r in res["reservations"] if r["libelle"] == "EFFERALGAN 1G CP EFF")
    assert env.c.post(f"/api/ordonnances-stock/{o['id']}/reservations/{rid}/vendue", headers=_h("pharma_phl")).status_code == 200
    assert env.c.post(f"/api/ordonnances-stock/{o['id']}/reservations/{rid}/annuler", headers=_h("pharma_phl")).status_code == 404
    # Autre client : aucun accès ; suppression : réservations actives annulées
    assert env.c.get(f"/api/ordonnances-stock/{o['id']}", headers=_h("pharma_amy")).status_code == 403
    assert env.c.delete(f"/api/ordonnances-stock/{o['id']}", headers=_h("pharma_phl")).status_code == 200
    actives = env.run(lambda: env.db.stock_reservations.count_documents({"statut": "active"}))
    assert actives == 0


def test_vidal_refuse_et_limites(env):
    _stock_phm(env)
    env.lu["lignes"] = [{"nom": "Amoxicilline", "dosage": "500 mg"}]
    o = env.c.post("/api/ordonnances-stock", headers=_h("pharma_phl"),
                   files=[("photos", ("o.png", _png(), "image/png"))]).json()
    env.vidal["actif"] = False
    l = env.c.post(f"/api/ordonnances-stock/{o['id']}/lignes/0/equivalents", headers=_h("pharma_phl")).json()["lignes"][0]
    assert l["equivalents_etat"] == "vidal_refuse" and l["equivalents"] == []
    trop = [("photos", (f"{i}.png", _png(), "image/png")) for i in range(5)]
    assert env.c.post("/api/ordonnances-stock", headers=_h("pharma_phl"), files=trop).status_code == 400
    assert env.c.post("/api/ordonnances-stock", headers=_h("pharma_phl"),
                      files=[("photos", ("o.txt", b"x", "text/plain"))]).status_code == 400
    assert env.c.post("/api/ordonnances-stock", headers=_h("sans_fonction"),
                      files=[("photos", ("o.png", _png(), "image/png"))]).status_code == 403
