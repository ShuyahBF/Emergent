"""Lot 88 — Support Loois : sondages « Evaluation Loois » (envoi numéroté, carte dans le fil, blocage des demandes,
réponse du poste, remerciement de Liluvine, liste d'évaluation) et session/ticket à l'initiative du support.
Lancer : cd backend && python -m pytest tests/test_lot88_sondages_support_loois.py -q
"""
from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "test_lot88")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.internal_chat as ic  # noqa: E402
import routes.support_loois as sl  # noqa: E402
import routes.support_loois_sondages as so  # noqa: E402
import tickets_clients  # noqa: E402

ADMIN = {"id": "adm1", "role": "admin", "full_name": "Jean-François", "email": "admin@sawali.test",
         "account_status": "active", "created_at": "2026-01-01T00:00:00+00:00"}
ECOLE = {"id": "cli-ecole", "role": "client", "company": "Ecole des Métiers", "full_name": "Direction",
         "account_status": "active"}
AUTRE = {"id": "cli2", "role": "client", "company": "Pharmacie X", "account_status": "active"}
URL_WS = "/api/ws/support-loois?ecole=Ecole%20des%20M%C3%A9tiers&poste=PC-SECRETARIAT&utilisateur=marie&version=1.0"
ENTETES_POSTE = {"X-Loois-Cle": "cle-de-test", "X-Loois-Ecole": "Ecole%20des%20M%C3%A9tiers",
                 "X-Loois-Poste": "PC-SECRETARIAT", "X-Loois-Utilisateur": "marie"}
H_ADMIN = {"X-User": "adm1"}


@pytest.fixture()
def env(monkeypatch):
    """Application minimale (chat interne + support Loois), base simulée, stockage et IA factices."""
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-de-test")
    monkeypatch.delenv("LOOIS_SUPPORT_ADMIN_EMAIL", raising=False)
    monkeypatch.setenv("LOOIS_SUPPORT_LILUVINE", "0")
    monkeypatch.setattr(sl, "VERIFICATION_S", 0.1)        # relecture rapide de l'état de la session
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot88"]
    monkeypatch.setattr(tickets_clients, "db", db)        # clôture du ticket → base simulée

    # Stockage R2 en mémoire
    fichiers = {}
    faux = types.ModuleType("storage")

    async def astorage_available():
        return True

    async def aupload_bytes(path, data, content_type="application/octet-stream"):
        fichiers[path] = (data, content_type)
        return path

    async def afetch_bytes(path):
        return fichiers[path]

    faux.astorage_available, faux.aupload_bytes, faux.afetch_bytes = astorage_available, aupload_bytes, afetch_bytes
    monkeypatch.setitem(sys.modules, "storage", faux)

    utilisateurs = {"adm1": ADMIN, "cli-ecole": ECOLE}

    async def get_user(request: Request):
        u = utilisateurs.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    api.include_router(ic.make_router(db=db, get_current_user=get_user, decode_token=lambda t: {}))
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as client:
        client.portal.call(db.users.insert_many, [dict(ADMIN), dict(ECOLE), dict(AUTRE)])
        yield client, db


def ouvrir(ws):
    """hello + historique + état de la session ; renvoie (poste_id, trame session)."""
    pid = ws.receive_json()["poste_id"]
    assert ws.receive_json()["type"] == "historique"
    return pid, ws.receive_json()


def attendre(ws, genre, **egal):
    """Lit les trames jusqu'à celle du type voulu (les messages intermédiaires sont ignorés)."""
    for _ in range(30):
        t = ws.receive_json()
        if t.get("type") == genre and all(t.get(k) == v for k, v in egal.items()):
            return t
    raise AssertionError(f"trame {genre} {egal} non reçue")


SONDAGE = {"id": "s1", "title": "Évaluation Loois — fin de session", "status": "active", "description": "Votre avis",
           "questions": [{"id": "q1", "type": "rating", "label": "Note du support", "required": True, "options": []},
                         {"id": "q2", "type": "text", "label": "Commentaire", "required": False, "options": []}]}
AUTRE_SONDAGE = {"id": "s2", "title": "Satisfaction clients", "status": "active", "questions": []}


def attendre(ws, genre, **egal):
    """Lit les trames jusqu'à celle du type voulu."""
    for _ in range(40):
        t = ws.receive_json()
        if t.get("type") == genre and all(t.get(k) == v for k, v in egal.items()):
            return t
    raise AssertionError(f"trame {genre} {egal} non reçue")


def test_fonctions_pures():
    assert so.est_sondage_loois("Évaluation LOOIS — session")
    assert so.est_sondage_loois("evaluation loois")
    assert not so.est_sondage_loois("Satisfaction — Evaluation Loois")
    assert so.numero_envoi(2026, 7) == "EVL-2026-0007"
    assert so.phrase_remerciement("Merci ({numero}) !", "EVL-2026-0001") == "Merci (EVL-2026-0001) !"
    assert "EVL-2026-0002" in so.phrase_remerciement("", "EVL-2026-0002")
    t = so.trame_requis([{"id": "e1", "numero": "EVL-2026-0001", "titre": "Evaluation Loois", "survey_id": "s1"}])
    assert t["type"] == "sondage_requis" and "EVL-2026-0001" in t["detail"] and t["sondages"][0]["statut"] == "en_attente"


def test_sondage_bloque_puis_reponse_et_remerciement(env):
    client, db = env
    client.portal.call(db.wa_surveys.insert_many, [dict(SONDAGE), dict(AUTRE_SONDAGE)])
    # 1re connexion : le poste est connu (demande abandonnée à la fermeture)
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        pid = ws.receive_json()["poste_id"]
    # Seuls les sondages « Evaluation Loois… » sont proposés
    dispo = client.get("/api/support-loois/sondages-disponibles", headers=H_ADMIN).json()["sondages"]
    assert [s["id"] for s in dispo] == ["s1"]
    assert client.post(f"/api/support-loois/postes/{pid}/sondages", headers=H_ADMIN,
                       json={"survey_id": "s2"}).status_code == 400
    r = client.post(f"/api/support-loois/postes/{pid}/sondages", headers=H_ADMIN, json={"survey_id": "s1"})
    assert r.status_code == 200, r.text
    envoi = r.json()["envoi"]
    assert envoi["numero"] == f"EVL-{datetime.now(timezone.utc).year}-0001" and envoi["statut"] == "en_attente"

    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        assert ws.receive_json()["type"] == "hello"
        hist = ws.receive_json()
        carte = [m for m in hist["messages"] if m.get("sondage")][0]
        assert carte["sondage"]["numero"] == envoi["numero"] and carte["sondage"]["statut"] == "en_attente"
        # Pas de nouvelle demande : le poste doit d'abord répondre
        requis = ws.receive_json()
        assert requis["type"] == "sondage_requis" and envoi["numero"] in requis["detail"]
        ws.send_json({"type": "message", "texte": "J'ai encore un souci"})
        assert "répondre au sondage" in attendre(ws, "erreur")["detail"]
        assert client.get("/api/support-loois/sessions", headers=H_ADMIN).json()["en_cours"] == []

        # Le poste lit le sondage (questions telles quelles) puis répond
        lu = client.get(f"/api/support-loois/sondages/{envoi['envoi_id']}", headers=ENTETES_POSTE).json()
        assert [q["id"] for q in lu["questions"]] == ["q1", "q2"] and lu["statut"] == "en_attente"
        assert client.post(f"/api/support-loois/sondages/{envoi['envoi_id']}", headers=ENTETES_POSTE,
                           json={"answers": {}}).status_code == 400          # question obligatoire
        r = client.post(f"/api/support-loois/sondages/{envoi['envoi_id']}", headers=ENTETES_POSTE,
                        json={"answers": {"q1": 5, "q2": "Très rapide"}})
        assert r.status_code == 200, r.text
        assert r.json()["debloque"] is True and r.json()["sondage"]["statut"] == "repondu"
        maj = attendre(ws, "message_maj")
        assert maj["message"]["sondage"]["statut"] == "repondu"
        merci = attendre(ws, "message")["message"]
        assert merci["sender_id"] == "liluvine" and envoi["numero"] in merci["text"]
        attendre(ws, "sondage_debloque")
        assert attendre(ws, "session")["statut"] == "attente"          # la demande part enfin

    # Fenêtre d'évaluation : réponse liée au numéro, détail lisible ; modification = révision
    liste = client.get("/api/support-loois/sondages-envois", headers=H_ADMIN).json()
    ligne = liste["envois"][0]
    assert ligne["statut"] == "repondu" and ligne["numero"] == envoi["numero"] and liste["resume"]["taux"] == 100.0
    assert {"question": "Note du support", "type": "rating", "reponse": 5} in ligne["reponses"]
    rep = client.portal.call(db.wa_survey_responses.find_one, {"invite_id": envoi["envoi_id"]})
    assert rep["survey_id"] == "s1" and rep["numero"] == envoi["numero"]
    assert client.post(f"/api/support-loois/sondages/{envoi['envoi_id']}", headers=ENTETES_POSTE,
                       json={"answers": {"q1": 4}}).status_code == 200
    assert client.portal.call(db.wa_survey_responses.find_one, {"invite_id": envoi["envoi_id"]})["revisions"] == 1
    # Un autre poste ne lit pas ce sondage ; un compte client ne voit pas la liste
    autre = {**ENTETES_POSTE, "X-Loois-Poste": "PC-AUTRE"}
    assert client.get(f"/api/support-loois/sondages/{envoi['envoi_id']}", headers=autre).status_code == 404
    assert client.get("/api/support-loois/sondages-envois", headers={"X-User": "cli-ecole"}).status_code == 403


def test_message_du_support_ouvre_ticket_et_fenetre(env):
    client, db = env
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        pid = ws.receive_json()["poste_id"]
    # Loois fermé : l'agent écrit au poste → session ouverte par le support, ticket créé (client trouvé par le nom)
    r = client.post("/api/me/chat/support-loois/messages", headers=H_ADMIN,
                    json={"text": "Bonjour, la mise à jour est prête", "recipient_id": pid})
    assert r.status_code == 200, r.text
    session = client.portal.call(db.support_loois_sessions.find_one, {"poste_id": pid, "en_cours": True})
    assert session["statut"] == "active" and session["initiee_par_support"] is True
    assert session["ticket_number"].startswith("ECOLE DES M TIERS-")
    # L'icône Loois voit des messages non lus : elle ouvre la fenêtre
    etat = client.get("/api/support-loois/etat", headers=ENTETES_POSTE).json()
    assert etat["ouvrir"] is True and etat["non_lus"] >= 2 and etat["en_ligne"] is False
    # Un 2e message ne crée pas de 2e ticket
    client.post("/api/me/chat/support-loois/messages", headers=H_ADMIN, json={"text": "Êtes-vous là ?", "recipient_id": pid})
    assert client.portal.call(db.support_tickets.count_documents, {"poste_id": pid}) == 1
    # Le poste se connecte : session active avec le ticket, messages marqués lus
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        ws.receive_json()
        hist = ws.receive_json()
        assert any("Ticket n°" in (m.get("text") or "") for m in hist["messages"])
        etat_ws = ws.receive_json()
        assert etat_ws["type"] == "session" and etat_ws["statut"] == "active" and etat_ws["ticket_number"]
        assert client.get("/api/support-loois/etat", headers=ENTETES_POSTE).json()["non_lus"] == 0


def test_reglages_phrase_de_remerciement(env):
    client, _ = env
    r = client.get("/api/admin/support-loois/reglages", headers=H_ADMIN).json()
    assert "{numero}" in r["remerciement_defaut"] and r["stats"]["envoyes"] == 0
    r = client.put("/api/admin/support-loois/reglages", headers=H_ADMIN, json={"remerciement_sondage": "Merci beaucoup ({numero}) !"})
    assert r.json()["remerciement_sondage"] == "Merci beaucoup ({numero}) !"
