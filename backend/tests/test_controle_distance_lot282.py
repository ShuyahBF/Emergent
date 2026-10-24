"""Lot 282 — contrôle à distance : motif du ticket modifiable, note d'intervention rappelée à la prochaine prise en main du poste.

Lancer : cd backend && python -m pytest tests/test_controle_distance_lot282.py -q
"""
import asyncio
import time

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.controle_distance import creer_routeur

CLE_A = "LOOIS-A"
TECH = {"x-test-user": "tech"}
AUTRE = {"x-test-user": "autre"}
UTILISATEURS = {"tech": {"id": "tech", "email": "admin@sawalismartsystems.com", "full_name": "Technicien SAWALI"},
                "autre": {"id": "autre", "email": "support2@sawalismartsystems.com", "full_name": "Autre technicien"}}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FauxTickets:
    def __init__(self):
        self.notes = []

    async def cloturer_ticket(self, ticket, **kw):
        self.notes.append(kw.get("note"))
        return {"intervention": {"id": "int-1", "intervention_number": "INT-1"}}


class FauxStockage:
    async def ecrire(self, chemin, donnees, type_mime):
        pass

    async def lire(self, chemin):
        return b""

    async def supprimer(self, chemin):
        pass


def _app():
    base = AsyncMongoMockClient()["test_controle_distance_282"]
    _run(base.users.insert_one({"id": "cli-1", "role": "client", "company": "Clinique A"}))
    _run(base.support_loois_postes.insert_many([
        {"id": "p1", "nom": "Clinique A — XERVEUR (admin)", "cle_client_code": "A", "ecole": "Clinique A", "poste": "XERVEUR", "client_id": "cli-1"}]))

    async def courant(request: Request):
        uid = request.headers.get("x-test-user")
        if uid not in UTILISATEURS:
            raise HTTPException(status_code=401, detail="non connecté")
        return UTILISATEURS[uid]

    async def identifier(db, cle, **_):
        return {"type": "client", "code": "A"} if cle == CLE_A else None

    tickets = FauxTickets()
    routeur = creer_routeur(db=base, get_current_user=courant, identifier_cle=identifier, decode_token=lambda t: {},
                            tickets=tickets, stockage=FauxStockage())
    api = APIRouter(prefix="/api")
    api.include_router(routeur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), base, tickets


def _session(client, ticket=True):
    """Prise en main acceptée, les deux bouts connectés (le ticket automatique est créé au début)."""
    r = client.post("/api/controle-distance/sessions", json={"poste_id": "p1", "mode": "controler"}, headers=TECH)
    sid = r.json()["session_id"]
    rep = client.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json={"accepte": True}, headers={"x-loois-cle": CLE_A}).json()
    jeton_tech = client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()["jeton"]
    return sid, rep["jeton"], jeton_tech


def _attendre_ticket(client, sid):
    """Le ticket automatique est créé par le serveur juste APRÈS l'annonce du début : on patiente brièvement."""
    for _ in range(100):
        etat = client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()
        if etat.get("ticket_number"):
            return etat
        time.sleep(0.02)
    return etat


def test_motif_et_note_du_ticket_puis_rappel_a_la_prochaine_prise_en_main():
    client, base, tickets = _app()
    sid, jeton_poste, jeton_tech = _session(client)
    with client.websocket_connect("/api/ws/controle-distance") as poste:
        poste.send_json({"type": "auth", "role": "poste", "session_id": sid, "jeton": jeton_poste})
        assert poste.receive_json()["type"] == "pret"
        with client.websocket_connect("/api/ws/controle-distance") as tech:
            tech.send_json({"type": "auth", "role": "technicien", "session_id": sid, "jeton": jeton_tech})
            assert tech.receive_json()["type"] == "pret"
            assert tech.receive_json()["type"] == "debut" and poste.receive_json()["type"] == "debut"
            etat = _attendre_ticket(client, sid)
            assert etat["ticket_number"] and etat["note_intervention"] == ""
            assert etat["ticket_motif"].startswith("Prise en main CD-")          # motif d'origine, à corriger
            # Aucun rappel avant la première note
            assert client.get("/api/controle-distance/postes/p1", headers=TECH).json()["rappel"] is None
            # Le technicien corrige le motif et laisse une note
            r = client.put(f"/api/controle-distance/sessions/{sid}/ticket",
                           json={"motif": "  Réparation de la sauvegarde HFSQL  ", "note": "Refaire la sauvegarde sur le disque D vendredi."}, headers=TECH)
            assert r.status_code == 200
            assert r.json()["ticket_motif"] == "Réparation de la sauvegarde HFSQL"
            ticket = _run(base.support_tickets.find_one({"id": _run(base.controle_distance_sessions.find_one({"id": sid}))["ticket_id"]}))
            assert ticket["motif"] == "Réparation de la sauvegarde HFSQL" and ticket["notes"].startswith("Refaire la sauvegarde")
            tech.send_json({"type": "arreter"})
            assert poste.receive_json()["type"] == "fin"
    # La note est dans l'intervention créée à la clôture
    assert any("Refaire la sauvegarde sur le disque D vendredi." in (n or "") for n in tickets.notes)
    doc = _run(base.controle_distance_sessions.find_one({"id": sid}))
    assert any(a["type"] == "ticket_modifie" for a in doc["actions"])
    # À la prochaine prise en main du même poste : le rappel est proposé avec son auteur et le numéro du ticket
    rappel = client.get("/api/controle-distance/postes/p1", headers=TECH).json()["rappel"]
    assert rappel["note"] == "Refaire la sauvegarde sur le disque D vendredi." and rappel["par"] == "Technicien SAWALI"
    assert rappel["session_id"] == sid and rappel["ticket_number"]
    # Supprimer le rappel
    assert client.delete("/api/controle-distance/postes/p1/rappel", headers=TECH).status_code == 200
    assert client.get("/api/controle-distance/postes/p1", headers=TECH).json()["rappel"] is None


def test_note_vide_retire_le_rappel_motif_vide_refuse_et_session_d_un_autre_technicien():
    client, base, _ = _app()
    sid, _, _ = _session(client)           # session seulement demandée / acceptée : pas de ticket, la note et le rappel fonctionnent quand même
    assert client.put(f"/api/controle-distance/sessions/{sid}/ticket", json={"note": "À revoir"}, headers=TECH).status_code == 200
    assert client.get("/api/controle-distance/postes/p1", headers=TECH).json()["rappel"]["note"] == "À revoir"
    assert client.put(f"/api/controle-distance/sessions/{sid}/ticket", json={"note": "   "}, headers=TECH).status_code == 200   # note vidée
    assert client.get("/api/controle-distance/postes/p1", headers=TECH).json()["rappel"] is None
    assert client.put(f"/api/controle-distance/sessions/{sid}/ticket", json={"motif": "   "}, headers=TECH).status_code == 422
    assert client.put(f"/api/controle-distance/sessions/{sid}/ticket", json={"motif": "x" * 301}, headers=TECH).status_code == 422
    assert client.put(f"/api/controle-distance/sessions/{sid}/ticket", json={"motif": "Autre"}, headers=AUTRE).status_code == 403   # pas du support
    assert client.put(f"/api/controle-distance/sessions/{sid}/ticket", json={"motif": "Autre"}).status_code in (401, 403)           # connexion obligatoire
