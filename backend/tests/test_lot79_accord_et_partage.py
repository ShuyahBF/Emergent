"""Lot 79 — accord WhatsApp recueilli auprès de la personne (boutons, mot-clé, lien) et partage des carrousels."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
mongomock_motor = pytest.importorskip("mongomock_motor")

from routes import accord_whatsapp as aw  # noqa: E402
from test_carrousel_whatsapp import env, h  # noqa: E402,F401

CARTES = [{"source": "libre", "image_url": "https://exemple.bf/a.jpg", "titre": "A", "texte": "a", "lien": "https://exemple.bf/a"},
          {"source": "libre", "image_url": "https://exemple.bf/b.jpg", "titre": "B", "texte": "b", "lien": "https://exemple.bf/b"}]



# --- Accord : fonctions pures -------------------------------------------------------------------
def test_intention_stricte():
    assert aw.intention("Oui, nouveautés !") is True
    assert aw.intention("OUI NOUVEAUTES") is True
    assert aw.intention("stop") is False
    assert aw.intention("oui") is None                 # un simple « oui » en conversation ne vaut pas accord
    assert aw.intention("Bonjour") is None
    assert aw.intention(None, aw.BOUTON_OUI) is True
    assert aw.intention(None, aw.BOUTON_NON) is False


def test_lien_et_corps_de_la_demande():
    assert aw.lien_accord("+226 70 00 00 01") == "https://wa.me/22670000001?text=OUI%20NOUVEAUTES"
    corps = aw.corps_demande("22670000001")
    ids = [b["reply"]["id"] for b in corps["interactive"]["action"]["buttons"]]
    assert ids == [aw.BOUTON_OUI, aw.BOUTON_NON] and corps["type"] == "interactive"


# --- Accord : enregistrement selon le numéro qui reçoit ----------------------------------------
def test_accord_note_sur_les_fiches_du_bon_numero():
    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["l79_accord"]
        await db.tenant_smart_comm.insert_one({"tenant_id": "cli_b", "wa_phone_number_id": "NUM_B"})
        await db.directory_contacts.insert_many([
            {"id": "c1", "client_id": "cli_a", "whatsapp": "+226 76 11 11 11"},     # client sans numéro propre
            {"id": "c2", "client_id": "cli_b", "phone": "0022676111111"},           # client avec son numéro
        ])
        await db.tracked_users.insert_one({"id": "t1", "client_id": "cli_a", "whatsapp_number": "76111111"})
        # Message reçu sur le numéro de la plateforme : fiches de cli_a seulement
        rep = await aw.traiter_message_entrant(db, "22676111111", "Oui nouveautés", None, "NUM_SAWALI")
        assert rep and rep[1] is None and "Merci" in rep[0]
        assert (await db.directory_contacts.find_one({"id": "c1"}))["accepte_whatsapp"] is True
        assert (await db.tracked_users.find_one({"id": "t1"}))["accepte_whatsapp_moyen"] == "mot-clé"
        assert "accepte_whatsapp" not in (await db.directory_contacts.find_one({"id": "c2"}))
        # Bouton « Non merci » reçu sur le numéro de cli_b : retrait chez cli_b seulement
        rep = await aw.traiter_message_entrant(db, "22676111111", None, aw.BOUTON_NON, "NUM_B")
        assert rep[1] == "cli_b"
        assert (await db.directory_contacts.find_one({"id": "c2"}))["accepte_whatsapp"] is False
        assert (await db.directory_contacts.find_one({"id": "c1"}))["accepte_whatsapp"] is True
        assert await db.accords_whatsapp_journal.count_documents({}) == 2
        # Message ordinaire : rien
        assert await aw.traiter_message_entrant(db, "22676111111", "Bonjour", None, "NUM_SAWALI") is None
    asyncio.run(scenario())


def test_demande_envoyee_seulement_si_fenetre_24h_ouverte():
    class FauxHttp:
        def __init__(self):
            self.envois = []

        async def post(self, url, json=None, headers=None):
            self.envois.append(json["to"])

            class R:
                status_code = 200
            return R()

    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["l79_fenetre"]
        await db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": "22676111111",
                                               "created_at": datetime.now(timezone.utc).isoformat(), "wa_numero_id": "1"})
        http = FauxHttp()
        res = await aw.envoyer_demandes(db, [{"nom": "Awa", "telephone": "+226 76 11 11 11"},
                                             {"nom": "Boris", "telephone": "+226 76 22 22 22"}],
                                        {"access_token": "t", "phone_number_id": "1"}, http=http)
        assert res["envoyees"] == 1 and res["fenetre_fermee"] == ["Boris"] and http.envois == ["22676111111"]
    asyncio.run(scenario())


def test_route_demande_accord_ignore_ceux_qui_ont_deja_accepte(env):
    client, db, _ = env
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    # Aucune fenêtre ouverte : rien n'est envoyé, la personne sans accord est signalée
    r = client.post("/api/me/whatsapp/carrousel/demande-accord", headers=h("cli_a"), json={"ids": ["c1", "c2"]})
    assert r.status_code == 200, r.text
    assert r.json()["deja"] == 1 and r.json()["envoyees"] == 0 and len(r.json()["fenetre_fermee"]) == 1


# --- Partage des carrousels ------------------------------------------------------------------------
def test_partage_admin_vers_un_client(env):
    client, _, _ = env
    bid = client.post("/api/admin/whatsapp/carrousel/brouillons", headers=h("admin"),
                      json={"nom": "Offre octobre", "message": "M", "cartes": CARTES}).json()["id"]
    # Adresse inconnue refusée
    r = client.put(f"/api/admin/whatsapp/carrousel/brouillons/{bid}/partages", headers=h("admin"), json={"emails": ["x@inconnu.bf"]})
    assert r.status_code == 400
    r = client.put(f"/api/admin/whatsapp/carrousel/brouillons/{bid}/partages", headers=h("admin"), json={"emails": ["A@X.BF"]})
    assert r.status_code == 200 and r.json()["partages"][0]["tenant_id"] == "cli_a"
    # Le client (et son utilisateur suivi) le voit, marqué « partagé »
    for qui in ("cli_a", "suivi_a"):
        liste = client.get("/api/me/whatsapp/carrousel/brouillons", headers=h(qui)).json()["carrousels"]
        assert [(b["nom"], b.get("partage")) for b in liste] == [("Offre octobre", True)]
        assert "partages" not in liste[0]
    # Il peut le dupliquer (la copie est à lui), pas le modifier ni le supprimer
    copie = client.post(f"/api/me/whatsapp/carrousel/brouillons/{bid}/dupliquer", headers=h("cli_a")).json()
    assert copie["nom"] == "Copie de Offre octobre"
    assert client.delete(f"/api/me/whatsapp/carrousel/brouillons/{bid}", headers=h("cli_a")).status_code == 404
    assert client.put(f"/api/me/whatsapp/carrousel/brouillons/{bid}", headers=h("cli_a"),
                      json={"nom": "X", "cartes": CARTES}).status_code == 404
    # Un client ne partage pas (réservé admin / superviseur)
    r = client.put(f"/api/me/whatsapp/carrousel/brouillons/{copie['id']}/partages", headers=h("cli_a"), json={"emails": ["b@x.bf"]})
    assert r.status_code == 403
    # L'admin voit à qui il a partagé
    adm = client.get("/api/admin/whatsapp/carrousel/brouillons", headers=h("admin")).json()["carrousels"]
    assert adm[0]["partages"][0]["email"] == "a@x.bf"
