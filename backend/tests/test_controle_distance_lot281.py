"""Lot 281 — contrôle à distance : transferts de fichiers REPRENABLES, session jamais coupée en plein transfert, prolongation,
code de fermeture dans le journal.

Lancer : cd backend && python -m pytest tests/test_controle_distance_lot281.py -q
"""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes import controle_distance_outils as outils
from routes.controle_distance import (MESSAGES_POSTE, action_journal, commande_autorisee, creer_routeur)

CLE_A = "LOOIS-A"
TECH = {"x-test-user": "tech"}
UTILISATEURS = {"tech": {"id": "tech", "email": "admin@sawalismartsystems.com", "full_name": "Technicien SAWALI"}}
T0 = datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------------------------- fonctions pures
def test_session_jamais_coupee_en_plein_transfert_mais_plafonnee_a_12_heures():
    limite = T0 + timedelta(seconds=outils.DUREE_MAX_S)                       # 4 h
    assert not outils.session_expiree(T0, T0 + timedelta(hours=3), limite, None)
    assert outils.session_expiree(T0, limite + timedelta(seconds=1), limite, None)                       # 4 h, aucun fichier : fermée
    en_cours = limite + timedelta(minutes=10)
    assert not outils.session_expiree(T0, en_cours, limite, en_cours - timedelta(seconds=30))            # fichier passé il y a 30 s
    assert outils.session_expiree(T0, en_cours, limite, en_cours - timedelta(seconds=200))               # transfert arrêté depuis > 90 s
    tard = T0 + timedelta(hours=12, seconds=1)
    assert outils.session_expiree(T0, tard, limite, tard - timedelta(seconds=1))                         # plafond de 12 h : fermée quand même


def test_prolongation_de_2_heures_avec_plafond():
    limite = T0 + timedelta(hours=4)
    assert outils.prolonger_limite(T0, T0 + timedelta(hours=1), limite) == T0 + timedelta(hours=6)
    assert outils.prolonger_limite(T0, T0 + timedelta(hours=4, minutes=30), limite) == T0 + timedelta(hours=6, minutes=30)   # limite dépassée
    assert outils.prolonger_limite(T0, T0 + timedelta(hours=1), T0 + timedelta(hours=11)) == T0 + timedelta(hours=12)       # plafond
    assert outils.plafond_session(T0) == T0 + timedelta(hours=12)


def test_motif_de_deconnexion_avec_code_de_fermeture():
    assert outils.motif_deconnexion("poste", 1006) == "déconnexion du poste (code 1006)"
    assert outils.motif_deconnexion("technicien") == "déconnexion du technicien"
    assert outils.motif_deconnexion("technicien", "x") == "déconnexion du technicien"


def test_reprise_messages_et_commandes_autorises():
    assert "fichier_pret" in MESSAGES_POSTE
    assert commande_autorisee("controler", {"type": "fichier_debut", "id": 1, "nom": "a.rar", "taille": 5, "reprise": True})
    assert commande_autorisee("controler", {"type": "fichier_demander", "chemin": "C:\\a.rar", "depuis": 100, "modifie": 5})
    assert commande_autorisee("controler", {"type": "fichier_annuler", "id": 1})
    assert not commande_autorisee("voir", {"type": "fichier_debut", "id": 1})                           # mode « voir » : jamais
    assert not commande_autorisee("controler", {"type": "prolonger"})                                    # traité par le serveur, jamais relayé
    assert action_journal({"type": "fichier_demander", "chemin": "C:\\a.rar"})["type"] == "fichier_recupere"


# ---------------------------------------------------------------------------------------------- relais complet
class FauxTickets:
    async def cloturer_ticket(self, ticket, **kw):
        return {"intervention": {"id": "int-1", "intervention_number": "INT-1"}}


class FauxStockage:
    async def ecrire(self, chemin, donnees, type_mime):
        pass

    async def lire(self, chemin):
        return b""

    async def supprimer(self, chemin):
        pass


def _app():
    base = AsyncMongoMockClient()["test_controle_distance_281"]
    _run(base.users.insert_one({"id": "cli-1", "role": "client", "company": "Pharmacie A"}))
    _run(base.support_loois_postes.insert_many([
        {"id": "p1", "nom": "Pharmacie A — CAISSE-1 (marie)", "cle_client_code": "A", "ecole": "Pharmacie A",
         "poste": "CAISSE-1", "client_id": "cli-1"}]))

    async def courant(request: Request):
        uid = request.headers.get("x-test-user")
        if uid not in UTILISATEURS:
            raise HTTPException(status_code=401, detail="non connecté")
        return UTILISATEURS[uid]

    async def identifier(db, cle, **_):
        return {"type": "client", "code": "A"} if cle == CLE_A else None

    routeur = creer_routeur(db=base, get_current_user=courant, identifier_cle=identifier, decode_token=lambda t: {},
                            tickets=FauxTickets(), stockage=FauxStockage())
    api = APIRouter(prefix="/api")
    api.include_router(routeur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), base


def _ouvrir(client):
    r = client.post("/api/controle-distance/sessions", json={"poste_id": "p1", "mode": "controler"}, headers=TECH)
    sid = r.json()["session_id"]
    rep = client.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json={"accepte": True}, headers={"x-loois-cle": CLE_A}).json()
    jeton_tech = client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()["jeton"]
    return sid, rep["jeton"], jeton_tech


def test_relais_reprise_prolongation_et_motif_au_journal():
    client, base = _app()
    sid, jeton_poste, jeton_tech = _ouvrir(client)
    with client.websocket_connect("/api/ws/controle-distance") as poste:
        poste.send_json({"type": "auth", "role": "poste", "session_id": sid, "jeton": jeton_poste})
        assert poste.receive_json()["type"] == "pret"
        with client.websocket_connect("/api/ws/controle-distance") as tech:
            tech.send_json({"type": "auth", "role": "technicien", "session_id": sid, "jeton": jeton_tech})
            assert tech.receive_json()["type"] == "pret"
            assert tech.receive_json()["type"] == "debut" and poste.receive_json()["type"] == "debut"
            # Envoi avec reprise : « fichier_debut » relayé tel quel (champs de reprise conservés), « fichier_pret » revient
            tech.send_json({"type": "fichier_debut", "id": 9, "nom": "a.rar", "taille": 1000, "reprise": True, "modifie": 42})
            recu = poste.receive_json()
            assert recu["reprise"] is True and recu["modifie"] == 42
            poste.send_json({"type": "fichier_pret", "id": 9, "octets": 600})
            assert tech.receive_json() == {"type": "fichier_pret", "id": 9, "octets": 600}
            # Récupération avec reprise : « depuis » et « modifie » traversent le serveur
            tech.send_json({"type": "fichier_demander", "chemin": "C:\\Sauvegarde.rar", "depuis": 500, "modifie": 99})
            assert poste.receive_json() == {"type": "fichier_demander", "chemin": "C:\\Sauvegarde.rar", "depuis": 500, "modifie": 99}
            # Prolonger : traité par le SERVEUR (le poste ne reçoit rien), le technicien reçoit une information
            tech.send_json({"type": "prolonger"})
            info = tech.receive_json()
            assert info["type"] == "info" and "prolongée" in info["detail"] and info["reste_s"] > 4 * 3600
            # Coupure du poste : le motif garde la cause
    doc = _run(base.controle_distance_sessions.find_one({"id": sid}))
    assert doc["statut"] == "terminee"
    assert doc["motif_fin"].startswith("déconnexion du ") or doc["motif_fin"].startswith("liaison interrompue du ") or doc["motif_fin"] == "connexion fermée"
