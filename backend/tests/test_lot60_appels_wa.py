"""Lot 60 — Appels WhatsApp : webhook « calls » (sonnerie, fin d'appel, statuts d'un appel sortant),
décroché depuis le portail (pre_accept + accept), refus, raccroché, journal, autorisation d'appel
et appel sortant. MongoDB simulé, API Meta factice (aucun appel réseau).
Lancer : cd backend && python -m pytest tests/test_lot60_appels_wa.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.appels_wa as aw  # noqa: E402

REGLAGES = {
    "_id": "global", "wa_phone_number_id": "PN-STANDARD", "wa_access_token": "jeton-factice",
    "wa_numeros": [{"id": "PN-VIP", "libelle": "Liluvine VIP", "vip": True}],
}
UTILISATEURS = {
    "sup": {"id": "sup", "role": "superviseur", "full_name": "Superviseur", "client_id": "sawali"},
    "agent-a": {"id": "agent-a", "role": "client", "full_name": "Agent A", "client_id": "sawali",
                "tracked_user_id": "tu-a"},
    "agent-b": {"id": "agent-b", "role": "client", "full_name": "Agent B", "client_id": "sawali",
                "tracked_user_id": "tu-b", "wa_lignes_autorisees": ["principal"]},
    "autre": {"id": "autre", "role": "client", "full_name": "Autre entreprise", "client_id": "pharma-x"},
}
SDP = "v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\ns=-\r\n"


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


class FausseReponse:
    """Réponse HTTP factice de l'API Graph."""
    def __init__(self, code=200, donnees=None):
        self.status_code = code
        self._donnees = donnees or {}

    def json(self):
        return self._donnees


@pytest.fixture()
def env(monkeypatch):
    """Base simulée, API Meta factice (requêtes mémorisées) et application minimale."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot60"]
    lancer(db.settings.insert_one(dict(REGLAGES)))
    lancer(db.users.insert_one({"id": "sawali", "role": "superviseur"}))
    lancer(db.directory_contacts.insert_one(
        {"id": "c1", "client_id": "sawali", "name": "Awa Kaboré", "whatsapp": "+22670000001"}))
    requetes = []

    class FauxClient:
        """Remplace httpx.AsyncClient : mémorise les appels à Meta."""
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            requetes.append(("POST", url, json))
            if json and json.get("action") == "connect":
                return FausseReponse(200, {"calls": [{"id": "wacid.SORTANT"}]})
            return FausseReponse(200, {"success": True})

        async def get(self, url, params=None, headers=None):
            requetes.append(("GET", url, params))
            return FausseReponse(200, {"permission": {"status": "temporary", "expiration_time": 1999999999},
                                       "actions": [{"action_name": "start_call", "can_perform_action": True},
                                                   {"action_name": "send_call_permission_request",
                                                    "can_perform_action": False}]})

    monkeypatch.setattr(aw.httpx, "AsyncClient", FauxClient)

    async def utilisateur(request: Request):
        uid = request.headers.get("X-User")
        if uid not in UTILISATEURS:
            raise HTTPException(status_code=401)
        return UTILISATEURS[uid]

    async def perimetre(user):
        return [user.get("client_id") or user["id"]]

    api = APIRouter(prefix="/api")
    aw.setup_appels_wa_routes(db=db, api=api, get_current_user=utilisateur,
                              resolve_visible_client_ids=perimetre)
    app = FastAPI()
    app.include_router(api)
    return {"db": db, "client": TestClient(app), "requetes": requetes}


def appel_entrant(call_id="wacid.E1", numero="PN-STANDARD", de="22670000001"):
    """Évènement webhook « connect » d'un appel entrant."""
    return {"metadata": {"phone_number_id": numero}, "contacts": [{"wa_id": de, "profile": {"name": "Awa"}}],
            "calls": [{"id": call_id, "from": de, "to": "22625658165", "event": "connect",
                       "direction": "USER_INITIATED", "timestamp": "1790000000",
                       "session": {"sdp_type": "offer", "sdp": SDP}}]}


def fin_appel(call_id="wacid.E1", duree=95):
    """Évènement webhook « terminate »."""
    return {"metadata": {"phone_number_id": "PN-STANDARD"},
            "calls": [{"id": call_id, "event": "terminate", "status": "COMPLETED", "duration": duree,
                       "start_time": "1790000005", "end_time": "1790000100"}]}


def test_appel_entrant_decroche_puis_termine(env):
    db, c, req = env["db"], env["client"], env["requetes"]
    assert lancer(aw.traiter_webhook_appels(db, appel_entrant())) == 1
    lancer(aw.traiter_webhook_appels(db, appel_entrant()))   # webhook répété : ignoré
    assert lancer(db.wa_appels.count_documents({})) == 1
    # La sonnerie apparaît chez l'agent, avec le nom du contact et la pastille de ligne
    r = c.get("/api/me/wa-appels/en-cours", headers={"X-User": "agent-a"}).json()
    assert r["sonnent"][0]["contact_nom"] == "Awa Kaboré"
    assert r["sonnent"][0]["ligne"]["libelle"] == "Liluvine Standard"
    # Une autre entreprise ne voit rien
    assert c.get("/api/me/wa-appels/en-cours", headers={"X-User": "autre"}).json()["sonnent"] == []
    # L'offre SDP est lisible, puis l'agent A décroche (pre_accept + accept envoyés à Meta)
    assert c.get("/api/me/wa-appels/wacid.E1/offre", headers={"X-User": "agent-a"}).json()["sdp"] == SDP
    assert c.post("/api/me/wa-appels/wacid.E1/decrocher", json={"sdp": SDP}, headers={"X-User": "agent-a"}).status_code == 200
    actions = [j["action"] for (_, url, j) in req if url.endswith("/PN-STANDARD/calls")]
    assert actions == ["pre_accept", "accept"]
    # Le superviseur arrive trop tard : appel déjà pris
    r2 = c.post("/api/me/wa-appels/wacid.E1/decrocher", json={"sdp": SDP}, headers={"X-User": "sup"})
    assert r2.status_code == 409
    assert c.get("/api/me/wa-appels/en-cours", headers={"X-User": "agent-a"}).json()["mon_appel"]["statut"] == "en_cours"
    # Fin d'appel : durée enregistrée, journal
    lancer(aw.traiter_webhook_appels(db, fin_appel()))
    j = c.get("/api/me/wa-appels", headers={"X-User": "sup"}).json()
    assert j["items"][0]["statut"] == "termine" and j["items"][0]["duree_s"] == 95
    assert j["items"][0]["decroche_par_nom"] == "Agent A" and j["duree_totale_s"] == 95


def test_appel_manque_et_refuse(env):
    db, c = env["db"], env["client"]
    lancer(aw.traiter_webhook_appels(db, appel_entrant("wacid.M")))
    lancer(aw.traiter_webhook_appels(db, fin_appel("wacid.M", 0)))
    assert lancer(db.wa_appels.find_one({"id": "wacid.M"}))["statut"] == "manque"
    lancer(aw.traiter_webhook_appels(db, appel_entrant("wacid.R")))
    assert c.post("/api/me/wa-appels/wacid.R/refuser", headers={"X-User": "agent-a"}).status_code == 200
    assert env["requetes"][-1][2]["action"] == "reject"
    lancer(aw.traiter_webhook_appels(db, fin_appel("wacid.R", 0)))
    assert lancer(db.wa_appels.find_one({"id": "wacid.R"}))["statut"] == "refuse"


def test_ligne_vip_invisible_pour_agent_standard(env):
    db, c = env["db"], env["client"]
    lancer(aw.traiter_webhook_appels(db, appel_entrant("wacid.V", numero="PN-VIP", de="22670000009")))
    assert c.get("/api/me/wa-appels/en-cours", headers={"X-User": "agent-b"}).json()["sonnent"] == []
    assert c.get("/api/me/wa-appels/en-cours", headers={"X-User": "agent-a"}).json()["sonnent"][0]["ligne"]["libelle"] == "Liluvine VIP"
    assert c.post("/api/me/wa-appels/wacid.V/decrocher", json={"sdp": SDP}, headers={"X-User": "agent-b"}).status_code == 404


def test_permission_et_appel_sortant(env):
    db, c, req = env["db"], env["client"], env["requetes"]
    # État de l'autorisation lu chez Meta
    etat = c.get("/api/me/wa-appels-permission", params={"telephone": "+22670000001"}, headers={"X-User": "agent-a"}).json()
    assert etat["statut"] == "temporary" and etat["peut_appeler"] is True
    # Demande d'autorisation : message interactif call_permission_request
    assert c.post("/api/me/wa-appels-permission", json={"telephone": "+22670000001", "contact_id": "c1"},
                  headers={"X-User": "agent-a"}).status_code == 200
    assert req[-1][2]["interactive"]["type"] == "call_permission_request"
    assert lancer(db.whatsapp_messages.count_documents({"message_type": "call_permission_request"})) == 1
    # Réponse du client (webhook messages)
    txt = lancer(aw.noter_reponse_permission(db, "22670000001", {"response": "accept", "is_permanent": False,
                                                                  "expiration_timestamp": "1790600000"}))
    assert "acceptée" in txt
    # Appel sortant : connect avec l'offre du navigateur
    r = c.post("/api/me/wa-appels/appeler", json={"telephone": "+22670000001", "sdp": SDP}, headers={"X-User": "agent-a"})
    assert r.status_code == 200 and r.json()["id"] == "wacid.SORTANT"
    assert req[-1][2]["action"] == "connect" and req[-1][2]["session"]["sdp_type"] == "offer"
    # Sonnerie chez le client puis réponse SDP de Meta
    lancer(aw.traiter_webhook_appels(db, {"statuses": [{"id": "wacid.SORTANT", "type": "call", "status": "RINGING"}]}))
    lancer(aw.traiter_webhook_appels(db, {"calls": [{"id": "wacid.SORTANT", "event": "connect",
                                                     "direction": "BUSINESS_INITIATED",
                                                     "session": {"sdp_type": "answer", "sdp": SDP}}]}))
    etat = c.get("/api/me/wa-appels/wacid.SORTANT", headers={"X-User": "agent-a"}).json()
    assert etat["statut"] == "en_cours" and etat["sdp_reponse"] == SDP
    # Un collègue ne reçoit pas la réponse SDP
    assert "sdp_reponse" not in c.get("/api/me/wa-appels/wacid.SORTANT", headers={"X-User": "sup"}).json()
    # Raccrocher
    assert c.post("/api/me/wa-appels/wacid.SORTANT/raccrocher", headers={"X-User": "agent-a"}).status_code == 200
    assert req[-1][2]["action"] == "terminate"


def test_appel_sortant_refuse_vers_ligne_non_autorisee(env):
    db, c = env["db"], env["client"]
    lancer(db.directory_contacts.insert_one({"id": "c-vip", "client_id": "sawali", "name": "VIP",
                                             "whatsapp": "+22670000005", "wa_ligne": "PN-VIP"}))
    r = c.post("/api/me/wa-appels/appeler", json={"telephone": "+22670000005", "sdp": SDP}, headers={"X-User": "agent-b"})
    assert r.status_code == 403


def test_appels_non_repondus_titre_onglet(env):
    """Lot 64.2 — compteur du titre de l'onglet : appels manqués non rattrapés, un par numéro."""
    db, c = env["db"], env["client"]
    # Deux appels manqués du même numéro : comptés une seule fois
    for cid in ("wacid.N1", "wacid.N2"):
        lancer(aw.traiter_webhook_appels(db, appel_entrant(cid)))
        lancer(aw.traiter_webhook_appels(db, fin_appel(cid, 0)))
    assert c.get("/api/me/wa-appels/non-repondus", headers={"X-User": "sup"}).json()["total"] == 1
    # Une autre entreprise ne voit pas cet appel
    assert c.get("/api/me/wa-appels/non-repondus", headers={"X-User": "autre"}).json()["total"] == 0
    # Le client rappelle et l'appel aboutit : le manqué est rattrapé
    lancer(aw.traiter_webhook_appels(db, appel_entrant("wacid.N3")))
    assert c.post("/api/me/wa-appels/wacid.N3/decrocher", json={"sdp": SDP}, headers={"X-User": "agent-a"}).status_code == 200
    lancer(aw.traiter_webhook_appels(db, fin_appel("wacid.N3", 40)))
    assert c.get("/api/me/wa-appels/non-repondus", headers={"X-User": "sup"}).json()["total"] == 0
