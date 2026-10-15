# Lot 195 — un seul flux Liluvine → Requêtes des clients (requête liée au ticket, lien Loois ou WhatsApp).
import asyncio
from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from routes import liluvine_requete as lr

BASE = "https://exemple.test"
CLIENT = {"id": "c1", "company": "Clinique Alpha", "client_code": "ALPHA"}


def _db():
    return AsyncMongoMockClient()["t"]


def _run(c):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


def test_categorie_technique_seulement():
    assert lr.categorie_requete("Technique") == "dysfonctionnement"
    assert lr.categorie_requete("Comptabilité") is None


def test_creation_une_seule_requete_par_ticket_lien_whatsapp():
    db = _db()
    r1 = _run(lr.requete_depuis_classement(db, client=CLIENT, contact_nom="Awa", categorie_classement="Technique",
                                           motif="Imprimante bloquée", texte="elle ne marche plus",
                                           ticket_numero="TK-1", base_url=BASE))
    assert r1["numero"] == "REQ-ALPHA-0001" and r1["nouvelle"] and not r1["via_loois"]
    assert r1["url"].startswith(BASE + "/requete/")
    r2 = _run(lr.requete_depuis_classement(db, client=CLIENT, contact_nom="Awa", categorie_classement="Technique",
                                           motif="Imprimante bloquée", texte="toujours rien",
                                           ticket_numero="TK-1", base_url=BASE))
    assert r2["numero"] == r1["numero"] and not r2["nouvelle"] and r2["url"] == r1["url"]
    assert _run(db.requetes_clients.count_documents({})) == 1
    doc = _run(db.requetes_clients.find_one({}))
    assert doc["origine"] == "liluvine" and doc["etat"] == "nouvelle" and len(doc["observations"]) == 1


def test_autre_categorie_pas_de_requete():
    db = _db()
    assert _run(lr.requete_depuis_classement(db, client=CLIENT, contact_nom="x", categorie_classement="Commercial",
                                             motif="m", texte="t", ticket_numero="TK-2", base_url=BASE)) is None
    assert _run(db.requetes_clients.count_documents({})) == 0


def test_lien_vers_loois_si_poste_en_ligne():
    db = _db()
    _run(db.support_loois_postes.insert_one({"id": "p1", "nom": "POSTE-ACCUEIL", "client_id": "c1",
                                             "dernier_contact": datetime.now(timezone.utc).isoformat()}))
    r = _run(lr.requete_depuis_classement(db, client=CLIENT, contact_nom="Awa", categorie_classement="Technique",
                                          motif="m", texte="t", ticket_numero="TK-3", base_url=BASE))
    assert r["via_loois"]
    carte = _run(db.internal_chat_messages.find_one({"recipient_id": "p1"}))
    assert carte["lien_requete"]["url"] == r["url"] and carte["lien_requete"]["ouvert"] is False
    assert "Loois" in lr.texte_lien(r["numero"], r["url"], True)


def test_poste_hors_ligne_ou_ambigu_repli_whatsapp():
    db = _db()
    vieux = "2020-01-01T00:00:00+00:00"
    maintenant = datetime.now(timezone.utc).isoformat()
    _run(db.support_loois_postes.insert_many([
        {"id": "p1", "nom": "A", "client_id": "c1", "dernier_contact": vieux},
        {"id": "p2", "nom": "B", "client_id": "c1", "dernier_contact": maintenant},
        {"id": "p3", "nom": "C", "client_id": "c1", "dernier_contact": maintenant}]))
    assert _run(lr.poste_loois_en_ligne(db, "c1")) is None             # deux postes en ligne : on ne devine pas
    assert _run(lr.poste_loois_en_ligne(db, "c1", "b"))["id"] == "p2"   # poste nommé par le contact
    assert _run(lr.poste_loois_en_ligne(db, "c1", "A")) is None         # nommé mais hors ligne
