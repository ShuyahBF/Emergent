"""Lot 58 — Sessions d'assistance Loois : demande → acceptation (ticket) → fin (ticket clôturé, intervention),
refus, durée depuis l'acceptation, fichiers (documents, vidéos), Liluvine (réponse en attente, suggestion,
« Détails du Support »). MongoDB simulé, IA et stockage factices.
Lancer : cd backend && python -m pytest tests/test_lot58_sessions_support_loois.py -q
"""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
# tickets_clients ouvre une connexion (paresseuse) à l'import : adresse factice, remplacée ci-dessous
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "test_lot58")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.internal_chat as ic  # noqa: E402
import routes.support_loois as sl  # noqa: E402
import routes.support_loois_sessions as ss  # noqa: E402
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
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot58"]
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


def test_numero_de_ticket_et_textes():
    assert ss.prefixe_ticket({"company": "Ecole des Métiers"}) == "ECOLE DES M TIERS"
    assert ss.prefixe_ticket({}) == "TKT"
    s = {"fin_raison": "agent", "ticket_number": "ECOLE-2026-0001", "intervention_number": "INT-2026-X-0001"}
    assert "Ticket n° ECOLE-2026-0001 clôturé" in ss.texte_fin(s) and "INT-2026-X-0001" in ss.texte_fin(s)
    assert sl.type_fichier("application/octet-stream", "rapport.PDF")[2] == "document"
    assert sl.type_fichier("video/mp4", "ecran.mp4")[2] == "video"
    assert sl.type_fichier("application/x-msdownload", "virus.exe") is None
    assert sl.nom_fichier_propre("C:\\Users\\marie\\Bulletin <1>.pdf", ".pdf") == "Bulletin _1_.pdf"


def test_demande_acceptee_ticket_puis_fin_par_l_agent(env):
    client, db = env
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        pid, etat = ouvrir(ws)
        assert etat["statut"] == "attente" and etat["ticket_number"] is None

        # L'équipe voit la demande, le poste peut déjà écrire (en attente)
        liste = client.get("/api/support-loois/sessions", headers=H_ADMIN).json()
        sid = liste["en_cours"][0]["id"]
        assert liste["en_cours"][0]["poste_id"] == pid
        ws.send_json({"type": "message", "texte": "Le PDF des impayés ne s'ouvre pas"})
        assert attendre(ws, "message")["message"]["session_id"] == sid

        # Un client non choisi est refusé ; un compte client ne gère pas les sessions
        assert client.post(f"/api/support-loois/sessions/{sid}/accepter", headers=H_ADMIN, json={}).status_code == 400
        assert client.get("/api/support-loois/sessions", headers={"X-User": "cli-ecole"}).status_code == 403
        clients = client.get("/api/support-loois/clients", headers=H_ADMIN, params={"q": "ecole"}).json()
        assert [c["id"] for c in clients] == ["cli-ecole"]

        # Acceptation : ticket créé, numéro annoncé dans la discussion et dans l'état de la session
        r = client.post(f"/api/support-loois/sessions/{sid}/accepter", headers=H_ADMIN, json={"client_id": "cli-ecole"})
        assert r.status_code == 200, r.text
        numero = r.json()["ticket_number"]
        assert numero.startswith("ECOLE DES M TIERS-") and numero.endswith("-0001")
        annonce = attendre(ws, "message")["message"]
        assert f"Ticket n° {numero}" in annonce["text"]
        active = attendre(ws, "session", statut="active")
        assert active["ticket_number"] == numero and active["agent"] == "Jean-François"
        assert 1700 < active["restant_s"] <= 1800
        # Deux agents ne peuvent pas accepter la même demande
        assert client.post(f"/api/support-loois/sessions/{sid}/accepter", headers=H_ADMIN,
                           json={"client_id": "cli-ecole"}).status_code == 409
        ticket = client.portal.call(db.support_tickets.find_one, {"number": numero})
        assert ticket["client_id"] == "cli-ecole" and ticket["status"] == "open" and ticket["source"] == "support_loois"

        # Fin par l'agent : fin_session au poste, ticket clôturé, intervention créée
        r = client.post(f"/api/support-loois/sessions/{sid}/terminer", headers=H_ADMIN)
        assert r.status_code == 200, r.text
        fin = attendre(ws, "fin_session")
        assert "par le support SAWALI" in fin["detail"] and fin["ticket_number"] == numero
        assert fin["intervention_number"].startswith("INT-")

    ticket = client.portal.call(db.support_tickets.find_one, {"number": numero})
    assert ticket["status"] == "done" and ticket["intervention_id"]
    inter = client.portal.call(db.interventions.find_one, {"id": ticket["intervention_id"]})
    assert inter["source_ticket_number"] == numero and inter["client_id"] == "cli-ecole"
    # Le client est retenu pour ce poste et proposé la fois suivante
    info = client.get(f"/api/support-loois/postes/{pid}/session", headers=H_ADMIN).json()
    assert info["client_id_suggere"] == "cli-ecole" and info["session"]["statut"] == "terminee"


def test_demande_refusee_puis_nouvelle_demande(env):
    client, _ = env
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        _, etat = ouvrir(ws)
        sid = etat["session_id"]
        r = client.post(f"/api/support-loois/sessions/{sid}/refuser", headers=H_ADMIN, json={"motif": "Rappel demain 8 h"})
        assert r.status_code == 200, r.text
        refus = attendre(ws, "session", statut="refusee")
        assert refus["motif_refus"] == "Rappel demain 8 h"
    # Nouvelle demande (« Nouvelle session » dans Loois) : nouvelle session en attente
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        _, etat2 = ouvrir(ws)
        assert etat2["statut"] == "attente" and etat2["session_id"] != sid


def test_reconnexion_reprend_la_session_et_fermeture_en_attente_l_abandonne(env):
    client, db = env
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        _, etat = ouvrir(ws)
        sid = etat["session_id"]
        client.post(f"/api/support-loois/sessions/{sid}/accepter", headers=H_ADMIN, json={"client_id": "cli-ecole"})
        attendre(ws, "session", statut="active")
    # Coupure réseau pendant une session active : la reconnexion reprend la MÊME session
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        _, etat2 = ouvrir(ws)
        assert etat2["session_id"] == sid and etat2["statut"] == "active"
    # Une demande encore en attente est abandonnée quand le poste ferme sa fenêtre
    client.portal.call(db.support_loois_sessions.update_one, {"id": sid}, {"$set": {"statut": "terminee", "en_cours": False}})
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        _, etat3 = ouvrir(ws)
    time.sleep(0.2)
    assert client.portal.call(db.support_loois_sessions.find_one, {"id": etat3["session_id"]})["statut"] == "abandonnee"


def test_duree_maximale_comptee_depuis_l_acceptation(env, monkeypatch):
    client, db = env
    monkeypatch.setenv("LOOIS_SUPPORT_SESSION_MINUTES", "0.01")   # 0,6 s
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        _, etat = ouvrir(ws)
        time.sleep(0.8)                                            # l'attente ne compte pas
        sid = etat["session_id"]
        assert client.post(f"/api/support-loois/sessions/{sid}/accepter", headers=H_ADMIN,
                           json={"client_id": "cli-ecole"}).status_code == 200
        fin = attendre(ws, "fin_session")
        assert "minutes maximum" in fin["detail"] and fin["intervention_number"]
    s = client.portal.call(db.support_loois_sessions.find_one, {"id": sid})
    assert s["statut"] == "terminee" and s["fin_raison"] == "duree"


def test_fichiers_document_et_video(env):
    client, _ = env
    # Sans session en cours : refusé
    r0 = client.post("/api/support-loois/fichier", headers=ENTETES_POSTE,
                     files={"fichier": ("a.pdf", b"%PDF", "application/pdf")})
    assert r0.status_code == 409
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        pid, _ = ouvrir(ws)
        video = client.post("/api/support-loois/fichier", headers=ENTETES_POSTE,
                            files={"fichier": ("ecran.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
                            data={"caption": "Voici le problème"})
        assert video.status_code == 200, video.text
        assert video.json()["media_kind"] == "video" and video.json()["file_name"] == "ecran.mp4"
        assert attendre(ws, "message")["message"]["media_kind"] == "video"
        # Type refusé
        exe = client.post("/api/support-loois/fichier", headers=ENTETES_POSTE,
                          files={"fichier": ("x.exe", b"MZ", "application/octet-stream")})
        assert exe.status_code == 400
        # L'agent envoie un document au poste, qui le reçoit et le télécharge
        doc = client.post(f"/api/support-loois/postes/{pid}/fichier", headers=H_ADMIN,
                          files={"fichier": ("procedure.pdf", b"%PDF-1.7", "application/pdf")})
        assert doc.status_code == 200, doc.text
        recu = attendre(ws, "message")["message"]
        assert recu["media_kind"] == "document" and recu["file_name"] == "procedure.pdf"
        assert client.get(f"/api/support-loois/media/{recu['id']}", headers=ENTETES_POSTE).content == b"%PDF-1.7"


def test_liluvine_repond_en_attente_suggere_et_resume(env, monkeypatch):
    client, db = env
    monkeypatch.setenv("LOOIS_SUPPORT_LILUVINE", "1")
    monkeypatch.setattr(ss, "liluvine_active", lambda: True)
    appels = []

    async def fausse_ia(systeme, texte, modele):
        appels.append((systeme, texte, modele))
        if "Détails du Support" in systeme:
            return "Problème signalé : PDF des impayés\nRésolution : réinstallation du lecteur PDF"
        return "Bonjour, je suis Liluvine. Pouvez-vous envoyer une capture ?"

    monkeypatch.setattr(ss, "appeler_ia", fausse_ia)
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        pid, etat = ouvrir(ws)
        sid = etat["session_id"]
        ws.send_json({"type": "message", "texte": "Le PDF ne s'ouvre pas"})
        attendre(ws, "message")                                  # écho du message du poste
        rep = attendre(ws, "message")["message"]                 # réponse de Liluvine
        assert rep["sender_id"] == "liluvine" and rep["sender_name"] == "🤖 Liluvine" and "capture" in rep["text"]
        assert "Le PDF ne s'ouvre pas" in appels[0][1]

        client.post(f"/api/support-loois/sessions/{sid}/accepter", headers=H_ADMIN, json={"client_id": "cli-ecole"})
        attendre(ws, "session", statut="active")
        # Session active : Liluvine se tait, mais propose une réponse à l'agent
        nb = len(appels)
        ws.send_json({"type": "message", "texte": "Toujours bloqué"})
        attendre(ws, "message", )
        time.sleep(0.2)
        assert len(appels) == nb
        sug = client.post(f"/api/support-loois/postes/{pid}/suggestion", headers=H_ADMIN)
        assert sug.status_code == 200 and sug.json()["texte"]

        client.post(f"/api/support-loois/sessions/{sid}/terminer", headers=H_ADMIN)
        attendre(ws, "fin_session")
    # « Détails du Support » rangés sur la session, le ticket et l'intervention
    for _ in range(30):
        s = client.portal.call(db.support_loois_sessions.find_one, {"id": sid})
        if s.get("details_support"):
            break
        time.sleep(0.1)
    assert "PDF des impayés" in s["details_support"]
    t = client.portal.call(db.support_tickets.find_one, {"id": s["ticket_id"]})
    i = client.portal.call(db.interventions.find_one, {"id": s["intervention_id"]})
    assert t["details_support"] == s["details_support"] == i["details_support"]
    assert "Détails du Support (Liluvine)" in i["description"]


# ----------------------------------------------------------------------
# Lot 58.1 — Liluvine avec le prompt du client lié, accès « Restreint », sans recherche sémantique
# ----------------------------------------------------------------------
def test_association_automatique_par_le_nom_de_l_ecole(env):
    client, db = env
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        pid, etat = ouvrir(ws)
    poste = client.portal.call(db.support_loois_postes.find_one, {"id": pid})
    assert poste["client_id"] == "cli-ecole" and poste["client_associe_auto"] is True   # « Ecole des Métiers »
    s = client.portal.call(db.support_loois_sessions.find_one, {"id": etat["session_id"]})
    assert s["client_id_suggere"] == "cli-ecole"
    assert ss._normaliser("  École des MÉTIERS ") == "ecole des metiers"


def test_liluvine_utilise_le_prompt_du_client_et_l_acces_restreint(env, monkeypatch):
    client, db = env
    monkeypatch.setattr(ss, "liluvine_active", lambda: True)
    systemes = []

    async def fausse_ia(systeme, texte, modele):
        systemes.append(systeme)
        return "Réponse Liluvine"

    monkeypatch.setattr(ss, "appeler_ia", fausse_ia)
    # Lot 58.2 — la recherche Qdrant reçoit la question du poste (base de connaissances + Qdrant)
    import routes.qdrant_rag as qr
    questions = []

    async def faux_rag(db_, *, query, max_chars=6000):
        questions.append(query)
        return "[Qdrant] Procédure : réinstaller le lecteur PDF."

    monkeypatch.setattr(qr, "build_rag_context", faux_rag)
    client.portal.call(db.users.update_one, {"id": "cli2"},
                       {"$set": {"liluvine_pro_system_prompt": "Tu es l'assistante de la Pharmacie X."}})
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        pid, _ = ouvrir(ws)
        # L'agent associe le poste à un AUTRE client dès la demande : son prompt est utilisé
        r = client.post(f"/api/support-loois/postes/{pid}/client", headers=H_ADMIN, json={"client_id": "cli2"})
        assert r.status_code == 200, r.text
        ws.send_json({"type": "message", "texte": "Bonjour"})
        attendre(ws, "message")
        assert attendre(ws, "message")["message"]["sender_id"] == "liluvine"
        assert systemes[-1].startswith("Tu es l'assistante de la Pharmacie X.")
        assert "Client SAWALI de ce poste : Pharmacie X" in systemes[-1]
        assert "Bonjour" in questions[-1] and "[Qdrant] Procédure" in systemes[-1]

        # Accès « Restreint » hors heures ouvrées (aucun jour ouvré) : un seul message d'information, puis silence
        client.portal.call(db.users.update_one, {"id": "cli2"}, {"$set": {"contract_access_mode": "restricted"}})
        client.portal.call(db.settings.insert_one, {"_id": "global", "business_days": [9],
                                                    "contract_min_amount_full_access": 0})
        nb = len(systemes)
        ws.send_json({"type": "message", "texte": "Vous êtes là ?"})
        attendre(ws, "message")
        info = attendre(ws, "message")["message"]
        assert info["sender_id"] == "liluvine" and "heures/jours ouvrés" in info["text"] and "Pharmacie X" in info["text"]
        ws.send_json({"type": "message", "texte": "Allô ?"})
        attendre(ws, "message")
        time.sleep(0.3)
        assert len(systemes) == nb                                  # aucun appel IA en accès restreint
        msgs = client.portal.call(db.internal_chat_messages.count_documents, {"sender_id": "liluvine"})
        assert msgs == 2


def test_qdrant_suspendu_si_memoire_insuffisante(monkeypatch):
    """Lot 58.2 — serveur de 512 Mo : le modèle d'indexation n'est jamais chargé (plus d'arrêt « mémoire dépassée »)."""
    import asyncio
    import routes.qdrant_rag as qr
    monkeypatch.delenv("QDRANT_EMBED_FORCE", raising=False)
    monkeypatch.delenv("QDRANT_MEMOIRE_MIN_MO", raising=False)
    monkeypatch.setattr(qr, "memoire_conteneur_octets", lambda: 512 * 1024 * 1024)
    assert qr.embeddings_autorises() is False
    with pytest.raises(RuntimeError, match="mémoire du serveur insuffisante"):
        qr._get_embedder()
    db = mongomock_motor.AsyncMongoMockClient()["qdrant_memoire"]

    async def scenario():
        await db.settings.insert_one({"_id": "global", "qdrant_enabled": True,
                                      "qdrant_collection_settings": {"docs": {"enabled_for_liluvine": True}}})
        return await qr.build_rag_context(db, query="PDF")

    assert asyncio.run(scenario()) == ""
    # Offre Render de 2 Go : autorisé ; forçage possible par variable d'environnement
    monkeypatch.setattr(qr, "memoire_conteneur_octets", lambda: 2 * 1024 * 1024 * 1024)
    assert qr.embeddings_autorises() is True
    monkeypatch.setattr(qr, "memoire_conteneur_octets", lambda: 512 * 1024 * 1024)
    monkeypatch.setenv("QDRANT_EMBED_FORCE", "1")
    assert qr.embeddings_autorises() is True


def test_details_du_support_regeneres(env, monkeypatch):
    client, db = env
    monkeypatch.setattr(ss, "liluvine_active", lambda: True)

    async def fausse_ia(systeme, texte, modele):
        return "Problème signalé : écran figé"

    monkeypatch.setattr(ss, "appeler_ia", fausse_ia)
    with client.websocket_connect(URL_WS, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        _, etat = ouvrir(ws)
        sid = etat["session_id"]
        assert client.post(f"/api/support-loois/sessions/{sid}/details", headers=H_ADMIN).status_code == 409
        ws.send_json({"type": "message", "texte": "L'écran est figé"})
        attendre(ws, "message")
        client.post(f"/api/support-loois/sessions/{sid}/accepter", headers=H_ADMIN, json={"client_id": "cli-ecole"})
        client.post(f"/api/support-loois/sessions/{sid}/terminer", headers=H_ADMIN)
        attendre(ws, "fin_session")
    r = client.post(f"/api/support-loois/sessions/{sid}/details", headers=H_ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["details_support"] == "Problème signalé : écran figé"
    t = client.portal.call(db.support_tickets.find_one, {"id": r.json()["ticket_id"]})
    assert t["details_support"] == "Problème signalé : écran figé" and t["status"] == "done"
