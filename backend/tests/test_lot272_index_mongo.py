"""Lot 272 — index MongoDB recommandés (conseiller Atlas), créés en un clic par l'administrateur principal.

  - état réel de chaque index : présent / manquant / collection absente (lecture seule) ;
  - création des seuls index MANQUANTS de la liste fermée, en arrière-plan : la requête répond tout de suite ;
  - aucun index hors liste, aucun doublon, aucune nouvelle collection ; accès réservé au super-admin.
"""
import asyncio
import time

import mongomock_motor
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from routes import index_mongo_recommandes as im

HF = "hf_ekol_ECOLE_DES_METIERS_NotesExamens"


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _db():
    return mongomock_motor.AsyncMongoMockClient()["sawali"]


@pytest.fixture(autouse=True)
def _remise_a_zero():
    im._ETAT.update(en_cours=False, fait=0, total=0, courant="", crees=0, erreurs=[], demarre_le=None, termine_le=None)


def _app(db, super_admin=True):
    async def sa():
        if not super_admin:
            raise HTTPException(403, "Réservé")
        return {"email": "x"}
    app = FastAPI()
    app.include_router(im.make_index_mongo_router(db=db, get_super_admin=sa), prefix="/api")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def test_liste_fermee_bien_formee():
    ids = [im.identifiant(r) for r in im.INDEX_RECOMMANDES]
    assert len(ids) == len(set(ids)) == 10                         # pas de doublon
    assert all(r["cles"] and all(s == 1 for _, s in r["cles"]) for r in im.INDEX_RECOMMANDES)
    assert im.nom_index({"cles": [("_hf_maj", 1), ("_hf_cle", 1)]}) == "sawali__hf_maj__hf_cle"


def test_constat_present_manquant_et_collection_absente():
    db = _db()
    run(db[HF].insert_one({"_hf_cle": "a", "_hf_maj": 1}))
    run(db.visits.insert_one({"id": "v1"}))
    run(db.visits.create_index([("id", 1)]))                       # déjà présent
    lignes = {l["id"]: l for l in run(im.constater(db))}
    assert lignes[f"{HF}:_hf_maj+_hf_cle"]["statut"] == "manquant" and lignes[f"{HF}:_hf_maj+_hf_cle"]["documents"] == 1
    assert lignes["visits:id"]["statut"] == "present"
    assert lignes["incidents_webhook_log:created_at"]["statut"] == "collection_absente"
    assert lignes["incidents_webhook_log:created_at"]["documents"] is None


def test_creation_en_arriere_plan_sans_doublon_ni_nouvelle_collection():
    db = _db()
    run(db[HF].insert_one({"_hf_cle": "a", "_hf_maj": 1}))
    run(db.whatsapp_messages.insert_one({"id": "m", "contact_id": "c", "client_id": "k", "created_at": "2026", "phone_digits": "1"}))
    avant = set(run(db.list_collection_names()))

    async def scenario():
        async with _app(db) as c:
            e = (await c.get("/api/admin/index-mongo/etat")).json()
            assert e["manquants"] == 3                              # NotesExamens + 2 index de whatsapp_messages
            # on ralentit la création pour prouver que la requête n'attend pas
            vraie = db[HF].create_index

            r0 = time.monotonic()
            r = await c.post("/api/admin/index-mongo/creer", json={})
            assert r.status_code == 200 and time.monotonic() - r0 < 0.5 and r.json()["rien_a_creer"] is False
            for _ in range(50):                                     # suivi de l'avancement
                s = (await c.get("/api/admin/index-mongo/etat")).json()
                if not s["creation"]["en_cours"]:
                    break
                await asyncio.sleep(0.05)
            assert s["creation"]["crees"] == 3 and s["creation"]["erreurs"] == [] and s["manquants"] == 0
            # une seconde demande ne recrée rien
            assert (await c.post("/api/admin/index-mongo/creer", json={})).json()["rien_a_creer"] is True
    run(scenario())
    assert set(run(db.list_collection_names())) == avant           # aucune collection créée
    noms = [i for i in run(db[HF].index_information())]
    assert "sawali__hf_maj__hf_cle" in noms


def test_ids_restreints_et_index_inconnu_refuse():
    db = _db()
    run(db[HF].insert_one({"_hf_cle": "a", "_hf_maj": 1}))
    run(db.visits.insert_one({"id": "v1"}))

    async def scenario():
        async with _app(db) as c:
            assert (await c.post("/api/admin/index-mongo/creer", json={"ids": ["users:password"]})).status_code == 422
            assert (await c.post("/api/admin/index-mongo/creer", json={"ids": "visits:id"})).status_code == 422
            r = await c.post("/api/admin/index-mongo/creer", json={"ids": ["visits:id"]})
            assert r.status_code == 200
            await asyncio.sleep(0.3)
            lignes = {l["id"]: l["statut"] for l in (await c.get("/api/admin/index-mongo/etat")).json()["index"]}
            assert lignes["visits:id"] == "present" and lignes[f"{HF}:_hf_maj+_hf_cle"] == "manquant"   # seul l'index demandé
    run(scenario())


def test_une_erreur_n_arrete_pas_les_autres(monkeypatch):
    db = _db()
    run(db.visits.insert_one({"id": "v1"}))
    run(db.incidents_webhook_log.insert_one({"created_at": "2026"}))

    class Casse:                                                    # simule un refus d'Atlas sur « visits »
        def __init__(self, vraie):
            self.vraie = vraie

        def __getattr__(self, nom):
            return getattr(self.vraie, nom)

        async def create_index(self, *a, **k):
            raise RuntimeError("quota")
    vrai_getitem = type(db).__getitem__

    async def scenario():
        monkeypatch.setattr(type(db), "__getitem__", lambda self, n: Casse(vrai_getitem(self, n)) if n == "visits" else vrai_getitem(self, n))
        async with _app(db) as c:
            await c.post("/api/admin/index-mongo/creer", json={})
            await asyncio.sleep(0.3)
            s = (await c.get("/api/admin/index-mongo/etat")).json()["creation"]
            assert s["crees"] == 1 and len(s["erreurs"]) == 1 and s["erreurs"][0]["id"] == "visits:id"
            assert "quota" not in str(s["erreurs"])                  # aucun détail technique renvoyé
    run(scenario())


def test_acces_reserve_au_super_admin():
    async def scenario():
        async with _app(_db(), super_admin=False) as c:
            assert (await c.get("/api/admin/index-mongo/etat")).status_code == 403
            assert (await c.post("/api/admin/index-mongo/creer", json={})).status_code == 403
    run(scenario())
