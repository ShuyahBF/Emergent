"""Lot 456 — envois en masse : destinataires choisis, aperçu, confirmation liée à l'aperçu, envoi en arrière-plan. Aucun accès réseau."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot456")
from datetime import datetime, timedelta, timezone

import mongomock_motor
import pytest

import consignes_masse as cm


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot456"]
    run(d.appointments.insert_many([
        {"id": "1", "scheduled_at": "2026-11-25T09:00:00", "phone": "+226 70 11 22 33", "name": "A"},
        {"id": "2", "scheduled_at": "2026-11-25T10:00:00", "phone": "22670112233", "name": "A bis"},       # doublon
        {"id": "3", "scheduled_at": "2026-11-25T11:00:00", "phone": "22671000000", "name": "B", "status": "cancelled"},
        {"id": "4", "scheduled_at": "2026-11-25T12:00:00", "phone": "22672000000", "name": "C"},
        {"id": "5", "scheduled_at": "2026-12-25T12:00:00", "phone": "22673000000", "name": "D"},           # hors période
    ]))
    return d


def test_apercu_ne_garde_que_les_destinataires_valables(db):
    ap = run(cm.apercu(db, "Votre RDV est décalé d'une heure.", "2026-11-25", "2026-11-25", "admin"))
    assert [d["nom"] for d in ap["destinataires"]] == ["A", "C"]
    assert ap["exclus"]["doublons"] == 1 and ap["exclus"]["annules"] == 1


def test_apercu_refuse_sans_destinataire_ou_periode_trop_longue(db):
    with pytest.raises(ValueError):
        run(cm.apercu(db, "Bonjour à tous", "2027-01-01", "2027-01-01", "admin"))
    with pytest.raises(ValueError):
        run(cm.apercu(db, "Bonjour à tous", "2026-11-01", "2026-12-31", "admin"))


def test_confirmation_exige_l_apercu_vu_et_envoie_en_arriere_plan(db):
    ap = run(cm.apercu(db, "Votre RDV est décalé d'une heure.", "2026-11-25", "2026-11-25", "admin"))
    envoyes = []

    async def envoyeur(tel, texte):
        envoyes.append(tel)
        return {"ok": True}

    async def fenetre(tel):
        return tel.endswith("33")                  # seul « A » a écrit depuis moins de 24 h

    with pytest.raises(ValueError):
        run(cm.confirmer(db, ap["id"], "mauvaise-empreinte", "admin", envoyeur, fenetre))
    assert envoyes == []

    async def scenario():
        lot = await cm.confirmer(db, ap["id"], ap["empreinte"], "admin", envoyeur, fenetre)
        assert envoyes == []                       # la requête n'attend pas l'envoi
        await asyncio.sleep(1.2)
        return lot

    loop = asyncio.new_event_loop()
    lot = loop.run_until_complete(scenario())
    assert lot["total"] == 2
    assert envoyes == ["22670112233"]
    final = loop.run_until_complete(cm.lots(db))[0]
    assert final["envoyes"] == 1 and final["hors_fenetre"] == 1 and final["termine"]
    with pytest.raises(ValueError):                # un aperçu ne sert qu'une fois
        loop.run_until_complete(cm.confirmer(db, ap["id"], ap["empreinte"], "admin", envoyeur, fenetre))


def test_apercu_expire(db):
    ap = run(cm.apercu(db, "Votre RDV est décalé d'une heure.", "2026-11-25", "2026-11-25", "admin"))
    with pytest.raises(ValueError):
        run(cm.confirmer(db, ap["id"], ap["empreinte"], "admin", None, None, instant=datetime.now(timezone.utc) + timedelta(minutes=30)))
