"""Lot 457 — consignes données par WhatsApp : numéro autorisé seulement, déclencheur explicite, confirmation OUI, envoi en masse en deux temps. Aucun accès réseau."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot457")
from datetime import datetime, timedelta

import mongomock_motor
import pytest

import consignes_liluvine as cl
import consignes_whatsapp as cw

NUM = "22670112233"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot457"]
    run(cl.enregistrer_acces(d, [{"numero": "+226 70 11 22 33", "nom": "Directeur", "actif": True}, {"numero": "22671000000", "nom": "Client X", "tenant": "t1", "actif": True}]))
    run(d.appointments.insert_many([{"id": "1", "scheduled_at": "2026-11-25T09:00:00", "phone": "22675000001", "name": "A"}]))
    return d


def fausse_ia(nature="blocage", **plus):
    async def f(phrase):
        base = {"nature": nature, "resume": phrase, "instruction": phrase, "debut": "2026-11-24T00:00", "fin": "2026-11-30T23:59", "creneau_debut": "12:00", "creneau_fin": "13:00",
                "appliquee": nature in cl.NATURES_APPLIQUEES, "envoi_masse": nature == "masse", "ia": True}
        base.update(plus)
        return base
    return f


def test_numero_non_autorise_ou_phrase_ordinaire_ne_fait_rien(db):
    assert run(cw.traiter(db, "22699999999", "consigne : aucune intervention", interpreter=fausse_ia())) is None
    assert run(cw.traiter(db, NUM, "Bonjour Liluvine, quelle heure ?", interpreter=fausse_ia())) is None


def test_consigne_proposee_puis_activee_apres_oui(db):
    rep = run(cw.traiter(db, NUM, "consigne : jusqu'à lundi, aucune intervention entre 12h et 13h", interpreter=fausse_ia()))
    assert "OUI" in rep and "12:00" in rep
    assert run(cl.charger(db)) == []                                  # rien d'actif avant la confirmation
    rep = run(cw.traiter(db, NUM, "Oui"))
    assert "activée" in rep and len(run(cl.charger(db))) == 1


def test_non_annule(db):
    run(cw.traiter(db, NUM, "consigne : aucune intervention entre 12h et 13h", interpreter=fausse_ia()))
    assert "annulée" in run(cw.traiter(db, NUM, "non"))
    assert run(cl.charger(db)) == []
    assert run(cw.traiter(db, NUM, "oui")) is None                    # plus rien en attente : le « oui » est ignoré


def test_proposition_expiree(db):
    t0 = datetime(2026, 11, 24, 10, 0)
    run(cw.traiter(db, NUM, "consigne : aucune intervention entre 12h et 13h", instant=t0, interpreter=fausse_ia()))
    assert run(cw.traiter(db, NUM, "oui", instant=t0 + timedelta(minutes=30))) is None
    assert run(cl.charger(db)) == []


def test_masse_en_deux_temps_et_interdite_a_un_numero_client(db):
    ia = fausse_ia("masse", message="Votre RDV est décalé d'une heure.", rdv_du="2026-11-25", rdv_au="2026-11-25")
    rep = run(cw.traiter(db, NUM, "consigne : écris à tous les RDV de demain", interpreter=ia))
    assert "Rien n'est envoyé" in rep
    rep = run(cw.traiter(db, NUM, "oui"))                              # 1er oui : la liste
    assert "1 destinataire" in rep and "ENVOYER" in rep
    envoyes = []

    async def envoyeur(tel, texte):
        envoyes.append(tel)
        return {"ok": True}

    async def fenetre(tel):
        return True

    async def scenario():
        rep2 = await cw.traiter(db, NUM, "oui", envoyeurs=(envoyeur, fenetre, None))     # 2e oui : envoi
        await asyncio.sleep(0.8)
        return rep2

    loop = asyncio.new_event_loop()
    assert "Envoi lancé" in loop.run_until_complete(scenario())
    assert envoyes == ["22675000001"]
    rep = run(cw.traiter(db, "22671000000", "consigne : écris à tous les RDV de demain", interpreter=ia))
    assert "pas permis" in rep
