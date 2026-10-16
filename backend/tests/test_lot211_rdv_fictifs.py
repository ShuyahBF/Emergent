"""Lot 211 — rendez-vous fictifs préparés chaque matin par Liluvine : 2 à 4 par jour ouvré, sans chevauchement, reproductibles,
sans invité, jamais sur un autre agenda que celui visé, jamais en double, suppression limitée à ce que le module a créé.
Lancer : cd backend && python -m pytest tests/test_lot211_rdv_fictifs.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.rdv_fictifs as rf  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_entre_2_et_4_rendez_vous_dans_les_horaires_sans_chevauchement():
    for k in range(60):                                       # 60 jours différents
        jour = date(2026, 10, 19).fromordinal(date(2026, 10, 19).toordinal() + k)
        evs = rf.generer_jour(jour, 2, 4, "09:00", "18:00")
        assert 2 <= len(evs) <= 4, jour
        for e in evs:
            assert e["debut"].date() == jour and e["debut"].hour >= 9 and (e["fin"].hour < 18 or (e["fin"].hour == 18 and e["fin"].minute == 0))
            assert e["debut"] < e["fin"] and e["debut"].minute % 15 == 0
        evs.sort(key=lambda e: e["debut"])
        for a, b in zip(evs, evs[1:]):
            assert (b["debut"] - a["fin"]).total_seconds() >= 15 * 60, "15 minutes au moins entre deux rendez-vous"


def test_programme_reproductible_et_varie():
    j = date(2026, 10, 20)
    assert rf.generer_jour(j) == rf.generer_jour(j)           # même jour → même programme (pas de doublon si on relance)
    assert rf.generer_jour(j) != rf.generer_jour(date(2026, 10, 21))
    types = {e["type"] for k in range(30) for e in rf.generer_jour(date(2026, 11, 1 + k % 28))}
    assert {"réunion", "formation", "dépannage", "suivi", "assistance"} <= types


def test_journee_trop_courte_un_seul_rendez_vous_jamais_de_chevauchement():
    evs = rf.generer_jour(date(2026, 10, 20), 4, 4, "09:00", "10:30")
    assert len(evs) >= 1
    evs.sort(key=lambda e: e["debut"])
    assert all(b["debut"] >= a["fin"] for a, b in zip(evs, evs[1:]))


def test_jours_a_generer_ouvres_seulement_et_sans_doublon():
    lundi = date(2026, 10, 19)
    assert [d.isoformat() for d in rf.jours_a_generer(lundi, 7, [0, 1, 2, 3, 4], {})] == [
        "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]           # samedi et dimanche écartés
    assert [d.isoformat() for d in rf.jours_a_generer(lundi, 7, [0, 1, 2, 3, 4], {"2026-10-20": [], "2026-10-22": []})] == ["2026-10-19", "2026-10-21", "2026-10-23"]
    assert len(rf.jours_a_generer(lundi, 7, [0, 1, 2, 3, 4, 5, 6], {})) == 7


def test_corps_sans_invite_ni_notification_disponible_par_defaut():
    ev = rf.generer_jour(date(2026, 10, 20))[0]
    c = rf.corps_evenement(ev, False)
    assert "attendees" not in c and c["reminders"] == {"useDefault": False}
    assert c["transparency"] == "transparent" and "fictif" in c["description"].lower()
    assert c["extendedProperties"]["private"]["sawali_fictif"] == "1"
    assert rf.corps_evenement(ev, True)["transparency"] == "opaque"


def test_reglages_par_defaut_desactives_et_bornes():
    r = rf.reglages({})
    assert r["actif"] is False and (r["mini"], r["maxi"], r["jours"]) == (2, 4, 7) and r["agenda"] == "sup.alphasofti@gmail.com" and r["bloquent"] is False
    assert rf.reglages({"rdv_fictifs_min": 9, "rdv_fictifs_max": 1, "rdv_fictifs_jours": 99})["mini"] == 6
    assert rf.reglages({"rdv_fictifs_jours": 99})["jours"] == 14


# ---------------------------------------------------------------------------------------------------------------------
# Passage du matin (MongoDB et Google simulés)
# ---------------------------------------------------------------------------------------------------------------------
LUNDI_6H = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)


def base(actif=True, relie="sup.alphasofti@gmail.com"):
    db = mongomock_motor.AsyncMongoMockClient()["rdv"]
    lancer(db.settings.insert_one({"_id": "global", "rdv_fictifs_actif": actif, "google_calendar_email": relie,
                                   "business_days": [0, 1, 2, 3, 4], "business_open_time": "09:00", "business_close_time": "18:00"}))
    return db


def faux_google(journal):
    async def creer(calendrier, corps):
        journal.append((calendrier, corps))
        return {"id": f"ev{len(journal)}"}
    return creer


def test_la_semaine_est_preparee_une_seule_fois():
    db, creations = base(), []
    b = lancer(rf.generer(db, LUNDI_6H, faux_google(creations)))
    assert b["jours"] == 5 and 10 <= b["evenements"] <= 20 and len(creations) == b["evenements"]
    assert all(c[0] == "sup.alphasofti@gmail.com" for c in creations)
    # Un second passage (le lendemain 6 h) ne refait pas les jours déjà préparés et n'ajoute que le jour entré dans la fenêtre
    b2 = lancer(rf.generer(db, datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc), faux_google(creations)))
    assert b2["jours"] == 1 and b2["details"][0]["jour"] == "2026-10-26"                  # lundi suivant (samedi/dimanche sautés)
    assert lancer(rf.generer(db, datetime(2026, 10, 20, 6, 5, tzinfo=timezone.utc), faux_google(creations)))["jours"] == 0


def test_desactive_rien_ne_part_sauf_bouton_manuel():
    db, creations = base(actif=False), []
    assert lancer(rf.generer(db, LUNDI_6H, faux_google(creations)))["evenements"] == 0 and creations == []
    assert lancer(rf.generer(db, LUNDI_6H, faux_google(creations), forcer=True))["evenements"] > 0


def test_jamais_sur_un_autre_agenda():
    db, creations = base(relie="autre.compte@gmail.com"), []
    b = lancer(rf.generer(db, LUNDI_6H, faux_google(creations)))
    assert creations == [] and b["evenements"] == 0 and "autre.compte@gmail.com" in b["erreur"]


def test_erreur_google_arrete_le_passage_sans_exception():
    db = base()

    async def refus(calendrier, corps):
        return {"erreur": "jeton expiré"}
    b = lancer(rf.generer(db, LUNDI_6H, refus))
    assert b["evenements"] == 0 and "jeton expiré" in b["erreur"]


def test_suppression_limitee_aux_rendez_vous_crees_par_le_module():
    db, creations, supprimes = base(), [], []
    lancer(rf.generer(db, LUNDI_6H, faux_google(creations)))

    async def supprimer(calendrier, event_id):
        supprimes.append(event_id); return True
    r = lancer(rf.supprimer_tout(db, supprimer))
    assert r["supprimes"] == len(creations) and r["restants"] == 0 and sorted(supprimes) == sorted(f"ev{i + 1}" for i in range(len(creations)))
    assert lancer(db.settings.find_one({"_id": rf.DOC_ID}))["evenements"] == {}
    # Un échec de suppression conserve l'événement dans le suivi (il sera réessayé)
    lancer(rf.generer(db, LUNDI_6H, faux_google([])))

    async def echec(calendrier, event_id):
        return False
    assert lancer(rf.supprimer_tout(db, echec))["restants"] > 0


def test_la_tache_ne_leve_jamais():
    class Casse:
        settings = None
    assert "erreur" in lancer(rf.generer(Casse(), LUNDI_6H, faux_google([])))


def test_routes_reglages():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    db = base(actif=False)
    app, api = FastAPI(), APIRouter(prefix="/api")
    rf.setup_rdv_fictifs_routes(db=db, api=api, get_current_admin=lambda: {"role": "admin"})
    app.include_router(api)
    c = TestClient(app)
    assert c.get("/api/admin/rdv-fictifs").json()["actif"] is False
    assert c.put("/api/admin/rdv-fictifs", json={"actif": True, "mini": 4, "maxi": 2, "jours": 7, "bloquent": False, "agenda": ""}).status_code == 422
    r = c.put("/api/admin/rdv-fictifs", json={"actif": True, "mini": 2, "maxi": 4, "jours": 7, "bloquent": False, "agenda": ""}).json()
    assert r["actif"] is True and r["agenda"] == "sup.alphasofti@gmail.com" and r["agenda_relie"] == "sup.alphasofti@gmail.com"
