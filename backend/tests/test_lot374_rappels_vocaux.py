"""Lot 374 — rappels vocaux programmés sur Alexa : validation, prochaine occurrence, exécution à l'heure dite, API.
Sans réseau ni vraie base (mongomock_motor) ; l'annonce Alexa est simulée.
Lancer : cd backend && python -m pytest tests/test_lot374_rappels_vocaux.py -q
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import httpx  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from services import alexa, rappels_vocaux as rv  # noqa: E402

UTC = timezone.utc
MAINTENANT = datetime(2026, 11, 13, 9, 0, 30, tzinfo=UTC)


def _db():
    return mongomock_motor.AsyncMongoMockClient()[f"lot374_{time.time_ns()}"]


def test_validation_texte_date_et_repetition():
    ok = rv.valider_rappel({"texte": "  Remarques   VIDAL ", "quand": "2026-11-13T09:00", "repetition": "jour"}, MAINTENANT - timedelta(hours=1))
    assert ok["texte"] == "Remarques VIDAL" and ok["quand"] == datetime(2026, 11, 13, 9, 0, tzinfo=UTC) and ok["repetition"] == "jour"
    for mauvais, message in [
        ({"texte": "", "quand": "2026-11-13T09:00"}, "phrase"),
        ({"texte": "x" * 181, "quand": "2026-11-13T09:00"}, "trop longue"),
        ({"texte": "ok", "quand": "demain"}, "illisibles"),
        ({"texte": "ok", "quand": ""}, "obligatoires"),
        ({"texte": "ok", "quand": "2026-01-01T09:00"}, "passée"),
        ({"texte": "ok", "quand": "2026-11-14T09:00", "repetition": "mois"}, "Répétition"),
    ]:
        with pytest.raises(ValueError, match=message):
            rv.valider_rappel(mauvais, MAINTENANT)
    # un fuseau explicite est converti en GMT
    assert rv.lire_date("2026-11-13T10:00:00+01:00") == datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def test_prochaine_occurrence_et_rappels_dus():
    debut = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    assert rv.prochaine_occurrence(debut, "jour", MAINTENANT) == datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    assert rv.prochaine_occurrence(debut, "semaine", MAINTENANT) == datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
    assert rv.prochaine_occurrence(debut, "aucune", MAINTENANT) is None
    liste = [{"id": "a", "statut": "en_attente", "quand": "2026-11-13T09:00:00+00:00"},
             {"id": "b", "statut": "en_attente", "quand": "2026-11-13T09:05:00+00:00"},          # pas encore l'heure
             {"id": "c", "statut": "annonce", "quand": "2026-11-13T08:00:00+00:00"},              # déjà terminé
             {"id": "d", "statut": "en_attente", "quand": "illisible"}]
    assert [r["id"] for r in rv.rappels_dus(liste, MAINTENANT)] == ["a"]


def test_rappel_unique_annonce_a_l_heure_dite_puis_termine():
    async def scenario():
        db = _db()
        dit = []

        async def annoncer(texte):
            dit.append(texte)
            return True, ""
        r = await rv.ajouter(db, {"texte": "Remarques VIDAL", "quand": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}, "moi@test")
        assert await rv.executer_rappels_dus(db, datetime.now(UTC), annoncer) == []                    # pas encore l'heure
        cr = await rv.executer_rappels_dus(db, datetime.now(UTC) + timedelta(minutes=6), annoncer)
        assert cr == [{"id": r["id"], "statut": "annonce", "motif": ""}] and dit == ["Remarques VIDAL"]
        assert await rv.executer_rappels_dus(db, datetime.now(UTC) + timedelta(minutes=7), annoncer) == []    # jamais annoncé deux fois
        (fait,) = await rv.lister(db)
        assert fait["statut"] == "annonce" and fait["termine_le"]
    asyncio.run(scenario())


def test_rappel_repete_est_reporte_et_un_rappel_manque_n_est_pas_annonce_en_retard():
    async def scenario():
        db = _db()
        dit = []

        async def annoncer(texte):
            dit.append(texte)
            return True, ""
        r = await rv.ajouter(db, {"texte": "Point quotidien", "quand": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(), "repetition": "jour"})
        t = datetime.now(UTC) + timedelta(minutes=2)
        await rv.executer_rappels_dus(db, t, annoncer)
        (rep,) = await rv.lister(db)
        assert rep["statut"] == "en_attente" and rv.lire_date(rep["quand"]) > t and dit == ["Point quotidien"]
        # serveur arrêté pendant 3 h : rien n'est annoncé en retard, le rappel répété passe à la prochaine occurrence
        cr = await rv.executer_rappels_dus(db, rv.lire_date(rep["quand"]) + timedelta(hours=3), annoncer)
        assert cr[0]["statut"] == "manque" and dit == ["Point quotidien"]
        (rep2,) = await rv.lister(db)
        assert rep2["statut"] == "en_attente" and rv.lire_date(rep2["quand"]) > rv.lire_date(rep["quand"]) + timedelta(hours=3)
    asyncio.run(scenario())


def test_echec_d_alexa_est_note_avec_son_motif():
    async def scenario():
        db = _db()

        async def hors_service(texte):
            return False, "Alexa n'est pas activée dans les Paramètres."
        await rv.ajouter(db, {"texte": "Essai", "quand": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()})
        cr = await rv.executer_rappels_dus(db, datetime.now(UTC) + timedelta(minutes=2), hors_service)
        assert cr[0]["statut"] == "echec"
        (r,) = await rv.lister(db)
        assert r["statut"] == "echec" and "Alexa" in r["motif"]
    asyncio.run(scenario())


def test_annonce_alexa_sans_abonnement_a_un_evenement_mais_avec_alexa_activee(monkeypatch):
    async def scenario():
        db = _db()
        assert await alexa.alexa_annoncer(db, "x") == (False, "Alexa n'est pas activée dans les Paramètres.")
        await db.settings.update_one({"_id": "global"}, {"$set": {"alexa_enabled": True, "alexa_webhook_url": ""}}, upsert=True)
        ok, motif = await alexa.alexa_annoncer(db, "x")
        assert not ok and "Voice Monkey" in motif
        await db.settings.update_one({"_id": "global"}, {"$set": {"alexa_webhook_url": "https://voicemonkey.test/annonce?token=t"}})      # alexa_events vide : sans importance
        vus = []

        def gestionnaire(requete: httpx.Request) -> httpx.Response:
            vus.append(requete)
            return httpx.Response(200, json={"success": True})
        vrai = httpx.AsyncClient
        monkeypatch.setattr(alexa.httpx, "AsyncClient", lambda *a, **k: vrai(*a, transport=httpx.MockTransport(gestionnaire), **k))
        assert await alexa.alexa_annoncer(db, "Bonjour") == (True, "")
        assert b"Bonjour" in vus[0].content and b"rappel_vocal" in vus[0].content
    asyncio.run(scenario())


def test_api_reservee_aux_administrateurs_programmer_lister_supprimer():
    db = _db()
    utilisateur = {"role": "admin", "id": "u1", "email": "moi@test"}
    from routes.rappels_vocaux import setup_rappels_vocaux_routes
    routeur = APIRouter(prefix="/api")
    setup_rappels_vocaux_routes(app=routeur, db=db, get_current_user=lambda: utilisateur)
    app = FastAPI()
    app.include_router(routeur)
    c = TestClient(app)
    futur = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    r = c.post("/api/admin/rappels-vocaux", json={"texte": "Remarques VIDAL", "quand": futur, "repetition": "aucune"})
    assert r.status_code == 200 and r.json()["statut"] == "en_attente"
    assert c.post("/api/admin/rappels-vocaux", json={"texte": "", "quand": futur}).status_code == 422
    liste = c.get("/api/admin/rappels-vocaux").json()
    assert liste["alexa_pret"] is False and len(liste["rappels"]) == 1 and "jour" in liste["repetitions"]
    assert c.post("/api/admin/rappels-vocaux/tester", json={}).status_code == 502                       # Alexa non configurée : motif renvoyé
    assert c.delete(f"/api/admin/rappels-vocaux/{r.json()['id']}").status_code == 200
    assert c.delete("/api/admin/rappels-vocaux/inconnu").status_code == 404
    utilisateur["role"] = "client"
    assert c.get("/api/admin/rappels-vocaux").status_code == 403
