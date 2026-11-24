"""Lot 454 — consignes à Liluvine : compréhension validée par le code, activation après accord, application dans le prompt, accès. Aucun accès réseau."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot454")
from datetime import datetime

import mongomock_motor
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

import consignes_liluvine as cl


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db():
    return mongomock_motor.AsyncMongoMockClient()["test_lot454"]


T0 = datetime(2026, 11, 25, 8, 0)


def test_proposition_toujours_sure():
    """L'IA transcrit, le code décide : nature inconnue -> réponse, dates absurdes -> de maintenant à la fin de la journée, texte borné."""
    p = cl.valider_proposition({"nature": "pirate", "debut": "n'importe quoi", "fin": "2026-11-25T07:00", "instruction": "x" * 5000}, "t", T0)
    assert p["nature"] == "reponse" and p["debut"] == "2026-11-25T08:00" and p["fin"] == "2026-11-25T23:59" and len(p["instruction"]) == cl.MAX_TEXTE
    p = cl.valider_proposition(None, "Je ne suis pas disponible ce matin", T0)
    assert p["instruction"] == "Je ne suis pas disponible ce matin" and p["nature"] == "reponse"


def test_fenetre_d_activite():
    c = {"statut": "active", "debut": "2026-11-25T08:00", "fin": "2026-11-25T12:00"}
    assert cl.est_active(c, datetime(2026, 11, 25, 8, 0)) and cl.est_active(c, datetime(2026, 11, 25, 12, 0))
    assert not cl.est_active(c, datetime(2026, 11, 25, 7, 59)) and not cl.est_active(c, datetime(2026, 11, 25, 12, 1))
    assert not cl.est_active({**c, "statut": "arretee"}, datetime(2026, 11, 25, 9, 0))


def test_bloc_prompt_seulement_les_consignes_de_reponse_actives():
    actives = [{"statut": "active", "nature": "reponse", "instruction": "Dis que je ne suis pas disponible pour les RDV.", "debut": "2026-11-25T08:00", "fin": "2026-11-25T12:00"},
               {"statut": "active", "nature": "blocage", "instruction": "bloc", "debut": "2026-11-25T08:00", "fin": "2026-11-25T12:00"},
               {"statut": "active", "nature": "reponse", "instruction": "périmée", "debut": "2026-11-24T08:00", "fin": "2026-11-24T12:00"},
               {"statut": "active", "nature": "reponse", "instruction": "autre client", "tenant": "AUTRE", "debut": "2026-11-25T08:00", "fin": "2026-11-25T12:00"}]
    b = cl.bloc_prompt(actives, "", datetime(2026, 11, 25, 9, 0))
    assert "pas disponible pour les RDV" in b and "bloc" not in b and "périmée" not in b and "autre client" not in b and "25/11/2026 à 12:00" in b
    assert cl.bloc_prompt([], "", T0) == ""


def test_activation_apres_validation_refuse_les_natures_non_appliquees(db):
    f = run(cl.creer(db, {"nature": "reponse", "instruction": "Pas de RDV ce matin", "debut": "2026-11-25T08:00", "fin": "2026-11-25T12:00"}, "texte", "Superviseur"))
    assert f["statut"] == "active" and run(cl.charger(db))[0]["id"] == f["id"]
    with pytest.raises(ValueError):
        run(cl.creer(db, {"nature": "blocage", "instruction": "12h-13h"}, "texte", "Sup"))
    assert len(run(cl.charger(db))) == 1                      # la consigne refusée n'a RIEN enregistré
    assert run(cl.arreter(db, f["id"], "Sup")) and not run(cl.arreter(db, f["id"], "Sup"))


def test_interpretation_sans_ia_repli_sur_la_phrase(db, monkeypatch):
    monkeypatch.setattr("ia_client.cle_ia", lambda *_a, **_k: "")
    r = run(cl.interpreter("Ce matin, pour tout appel au sujet de RDV, je ne suis pas disponible", T0))
    assert r["ia"] is False and r["nature"] == "reponse" and r["appliquee"] and "RDV" in r["instruction"]
    with pytest.raises(ValueError):
        run(cl.interpreter("   "))


def test_acces_par_numero_whatsapp(db):
    run(cl.enregistrer_acces(db, [{"numero": "+226 70 12 34 56", "nom": "Superviseur 1", "tenant": "T1", "actif": True},
                                  {"numero": "70123456", "tenant": "T1"}, {"numero": "123"}, {"numero": "+226 71 00 00 01", "actif": False}]))
    assert len(run(cl.lister_acces(db))) == 2                  # doublon et numéro trop court ignorés
    assert run(cl.numero_autorise(db, "22670123456"))["nom"] == "Superviseur 1"
    assert run(cl.numero_autorise(db, "+226 71 00 00 01")) is None      # numéro désactivé
    assert run(cl.numero_autorise(db, "0000")) is None


def _app(db, role, partage=None):
    from routes.consignes_liluvine import setup_consignes_liluvine_routes
    run(db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_partage": partage or {}}}, upsert=True))
    app = FastAPI(); api = APIRouter(prefix="/api")

    async def get_current_user():
        return {"role": role, "email": "sup@sawali.test", "full_name": "Sup"}
    setup_consignes_liluvine_routes(db=db, api=api, get_current_user=get_current_user)
    app.include_router(api)
    return TestClient(app)


def test_routes_droits_et_parcours(db, monkeypatch):
    monkeypatch.setattr("ia_client.cle_ia", lambda *_a, **_k: "")
    c = _app(db, "superviseur")
    prop = c.post("/api/admin/liluvine-consignes/interpreter", json={"texte": "Jusqu'à lundi, pas de RDV"}).json()
    assert prop["nature"] == "reponse"
    assert c.get("/api/admin/liluvine-consignes").json()["consignes"] == []      # l'interprétation n'active RIEN
    r = c.post("/api/admin/liluvine-consignes", json={**prop, "texte": "Jusqu'à lundi, pas de RDV"})
    assert r.status_code == 200 and c.get("/api/admin/liluvine-consignes").json()["consignes"][0]["active_maintenant"] in (True, False)
    cid = r.json()["consigne"]["id"]
    assert c.post(f"/api/admin/liluvine-consignes/{cid}/arreter").status_code == 200
    assert c.post("/api/admin/liluvine-consignes", json={"nature": "masse", "instruction": "x", "texte": "x"}).status_code == 422
    # le superviseur ne règle PAS les numéros autorisés (administrateur seul)
    assert c.get("/api/admin/liluvine-consignes-acces").status_code == 403
    assert c.put("/api/admin/liluvine-consignes-acces", json={"acces": []}).status_code == 403
    # un superviseur restreint sans l'élément « consignes » est refusé
    c2 = _app(db, "superviseur", {"sup@sawali.test": ["agenda"]})
    assert c2.get("/api/admin/liluvine-consignes").status_code == 403
    # l'administrateur voit tout et règle les numéros
    ca = _app(db, "admin")
    assert ca.put("/api/admin/liluvine-consignes-acces", json={"acces": [{"numero": "+226 70 12 34 56", "nom": "A"}]}).json()["acces"][0]["cle"] == "70123456"
    assert _app(db, "client").get("/api/admin/liluvine-consignes").status_code == 403


def test_prompt_de_liluvine_recoit_les_consignes(db):
    from routes.liluvine_pro import _resolve_base_system_prompt
    run(db.users.insert_one({"id": "U1"}))
    avant = run(_resolve_base_system_prompt(db, "U1"))
    now = cl.maintenant()
    run(cl.creer(db, {"nature": "reponse", "instruction": "Dis que le responsable est absent aujourd'hui.", "debut": cl.texte_date(now - cl.timedelta(hours=1)), "fin": cl.texte_date(now + cl.timedelta(hours=1))}, "t", "Sup"))
    apres = run(_resolve_base_system_prompt(db, "U1"))
    assert apres.startswith(avant) and "responsable est absent aujourd'hui" in apres and "CONSIGNES DU MOMENT" in apres
