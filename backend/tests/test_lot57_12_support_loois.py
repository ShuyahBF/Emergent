"""Lot 57.12 — « Support Loois » : bouton « Ecrire Support » de Loois relié au chat interne SAWALI.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot57_12_support_loois.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.internal_chat as ic  # noqa: E402
import routes.support_loois as sl  # noqa: E402

ADMIN = {"id": "adm1", "role": "admin", "full_name": "Jean-François", "email": "admin@sawali.test",
         "account_status": "active", "created_at": "2026-01-01T00:00:00+00:00"}
ADMIN2 = {"id": "adm2", "role": "admin", "full_name": "Compte Support", "email": "support@sawali.test",
          "account_status": "active", "created_at": "2026-02-01T00:00:00+00:00"}
SUPERVISEUR = {"id": "sup1", "role": "superviseur", "full_name": "Jean-François (superviseur)",
               "email": "Proprio@Sawali.test", "account_status": "active", "created_at": "2026-03-01T00:00:00+00:00"}
CLIENT = {"id": "cli1", "role": "client", "full_name": "Pharmacie X", "account_status": "active"}
URL_WS = "/api/ws/support-loois?cle={cle}&ecole=Ecole%20des%20M%C3%A9tiers&poste=PC-SECRETARIAT&utilisateur=marie&version=1.0"


@pytest.fixture()
def env(monkeypatch):
    """Application minimale : chat interne + base simulée + utilisateur choisi par l'en-tête X-User."""
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-de-test")
    monkeypatch.delenv("LOOIS_SUPPORT_ADMIN_EMAIL", raising=False)
    monkeypatch.setenv("LOOIS_SUPPORT_LILUVINE", "0")      # lot 58 : pas d'appel IA dans ces tests
    db = mongomock_motor.AsyncMongoMockClient()["sawali_support"]
    utilisateurs = {"adm1": ADMIN, "adm2": ADMIN2, "sup1": SUPERVISEUR, "cli1": CLIENT}

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
        # Comptes réels dans la base simulée (l'administrateur reçoit les messages des postes)
        client.portal.call(db.users.insert_many, [dict(ADMIN), dict(ADMIN2), dict(SUPERVISEUR), dict(CLIENT)])
        yield client, db


def test_fonctions_pures():
    # Même école + même poste + même utilisateur = même fil (l'historique est retrouvé)
    assert sl.poste_id("Ecole", "PC1", "marie") == sl.poste_id(" ecole ", "pc1", "MARIE")
    assert sl.poste_id("Ecole", "PC1", "marie") != sl.poste_id("Ecole", "PC2", "marie")
    assert sl.nom_affiche("Ecole des Métiers", "PC1", "marie") == "Ecole des Métiers — PC1 (marie)"
    assert sl.nettoyer("  a\r\nb   c ", 80) == "a b c"
    limite = sl.LimiteDebit(maximum=2, fenetre=60)
    assert limite.autorise(0) and limite.autorise(1) and not limite.autorise(2) and limite.autorise(61)


def test_cle_absente_ou_fausse_ferme_le_support(env, monkeypatch):
    client, _ = env
    with client.websocket_connect(URL_WS.format(cle="mauvaise")) as ws:
        assert ws.receive_json()["type"] == "erreur"
    monkeypatch.delenv("LOOIS_SUPPORT_CLE")
    with client.websocket_connect(URL_WS.format(cle="cle-de-test")) as ws:
        assert ws.receive_json()["type"] == "erreur"
    # Support fermé : l'espace n'apparaît pas pour l'administrateur
    ids = [c["id"] for c in client.get("/api/me/chat/clients", headers={"X-User": "adm1"}).json()]
    assert sl.ESPACE_ID not in ids


def test_aller_retour_poste_loois_et_administrateur(env):
    client, db = env
    with client.websocket_connect(URL_WS.format(cle="cle-de-test")) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        pid = hello["poste_id"]
        assert ws.receive_json() == {"type": "historique", "messages": []}
        assert ws.receive_json()["statut"] == "attente"       # lot 58 : demande en attente d'un agent

        # 1) Le poste écrit : message rangé dans le chat interne, adressé à l'administrateur
        ws.send_json({"type": "message", "texte": "Bonjour, le PDF ne s'ouvre pas"})
        recu = ws.receive_json()
        assert recu["type"] == "message" and recu["client_id"] == sl.ESPACE_ID
        msg = recu["message"]
        assert msg["sender_id"] == pid and msg["recipient_id"] == "adm1"
        assert msg["sender_name"] == "Ecole des Métiers — PC-SECRETARIAT (marie)"

        # 2) L'administrateur voit l'espace « Support Loois » et le fil du poste
        h = {"X-User": "adm1"}
        ids = [c["id"] for c in client.get("/api/me/chat/clients", headers=h).json()]
        assert sl.ESPACE_ID in ids
        fils = client.get(f"/api/me/chat/{sl.ESPACE_ID}/threads", headers=h).json()
        fil = next(f for f in fils if f["key"] == pid)
        assert fil["label"].startswith("Ecole des Métiers") and fil["unread"] == 1
        membres = client.get(f"/api/me/chat/{sl.ESPACE_ID}/members", headers=h).json()
        assert any(m["id"] == pid and m["online"] for m in membres)

        # 3) L'administrateur répond depuis le portail : la réponse arrive EN DIRECT dans Loois
        r = client.post(f"/api/me/chat/{sl.ESPACE_ID}/messages", headers=h,
                        json={"text": "Je regarde tout de suite", "recipient_id": pid})
        assert r.status_code == 200, r.text
        reponse = ws.receive_json()
        assert reponse["type"] == "message" and reponse["message"]["text"] == "Je regarde tout de suite"

        # 4) Ping / pong (maintien de la connexion)
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"

    # 5) Reconnexion du même poste : l'historique revient (2 messages)
    with client.websocket_connect(URL_WS.format(cle="cle-de-test")) as ws:
        ws.receive_json()
        historique = ws.receive_json()
        assert [m["text"] for m in historique["messages"]] == ["Bonjour, le PDF ne s'ouvre pas", "Je regarde tout de suite"]


def test_un_client_ne_voit_pas_le_support(env):
    client, _ = env
    h = {"X-User": "cli1"}
    ids = [c["id"] for c in client.get("/api/me/chat/clients", headers=h).json()]
    assert sl.ESPACE_ID not in ids
    assert client.get(f"/api/me/chat/{sl.ESPACE_ID}/threads", headers=h).status_code == 403


def test_trop_de_messages_refuses(env, monkeypatch):
    client, db = env
    monkeypatch.setattr(sl, "MESSAGES_PAR_MINUTE", 2)
    monkeypatch.setattr(sl.LimiteDebit.__init__, "__defaults__", (2, 60.0))
    with client.websocket_connect(URL_WS.format(cle="cle-de-test")) as ws:
        ws.receive_json(); ws.receive_json(); ws.receive_json()
        for i in range(2):
            ws.send_json({"type": "message", "texte": f"m{i}"})
            assert ws.receive_json()["type"] == "message"
        ws.send_json({"type": "message", "texte": "m3"})
        assert ws.receive_json()["type"] == "erreur"


def test_espace_partage_entre_tous_les_administrateurs(env, monkeypatch):
    """Lot 57.12.1 — messages adressés au compte « support » (LOOIS_SUPPORT_ADMIN_EMAIL) : un AUTRE
    administrateur voit aussi le fil, ses messages non lus, et peut répondre (cas réel du 05/10/2026)."""
    client, _ = env
    monkeypatch.setenv("LOOIS_SUPPORT_ADMIN_EMAIL", "support@sawali.test")
    with client.websocket_connect(URL_WS.format(cle="cle-de-test")) as ws:
        pid = ws.receive_json()["poste_id"]
        ws.receive_json()
        ws.receive_json()                             # lot 58 : état de la session
        ws.send_json({"type": "message", "texte": "Bonjour support"})
        msg = ws.receive_json()["message"]
        assert msg["recipient_id"] == "adm2"          # destinataire = compte support

        h = {"X-User": "adm1"}                        # l'AUTRE administrateur
        fils = client.get(f"/api/me/chat/{sl.ESPACE_ID}/threads", headers=h).json()
        fil = next(f for f in fils if f["key"] == pid)
        assert fil["unread"] == 1
        assert client.get("/api/me/chat/unread-count", headers=h).json()["per_client"][sl.ESPACE_ID] == 1
        msgs = client.get(f"/api/me/chat/{sl.ESPACE_ID}/messages", headers=h, params={"with_user": pid}).json()
        assert [m["text"] for m in msgs] == ["Bonjour support"]
        client.post(f"/api/me/chat/{sl.ESPACE_ID}/threads/{pid}/mark-all-read", headers=h)
        assert client.get("/api/me/chat/unread-count", headers=h).json()["per_client"][sl.ESPACE_ID] == 0

        # adm1 répond : le poste la reçoit en direct, et le fil complet contient les 2 messages
        r = client.post(f"/api/me/chat/{sl.ESPACE_ID}/messages", headers=h, json={"text": "Réponse de adm1", "recipient_id": pid})
        assert r.status_code == 200, r.text
        assert ws.receive_json()["message"]["text"] == "Réponse de adm1"
        msgs2 = client.get(f"/api/me/chat/{sl.ESPACE_ID}/messages", headers={"X-User": "adm2"}, params={"with_user": pid}).json()
        assert [m["text"] for m in msgs2] == ["Bonjour support", "Réponse de adm1"]


# ----------------------------------------------------------------------
# Lot 57.13 — images échangées avec les postes Loois (stockage simulé)
# ----------------------------------------------------------------------
ENTETES_POSTE = {"X-Loois-Cle": "cle-de-test", "X-Loois-Ecole": "Ecole%20des%20M%C3%A9tiers",
                 "X-Loois-Poste": "PC-SECRETARIAT", "X-Loois-Utilisateur": "marie"}


@pytest.fixture()
def stockage(monkeypatch):
    """Remplace le module storage (R2) par un dictionnaire en mémoire."""
    import types
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
    return fichiers


def test_images_aller_retour_poste_et_administrateur(env, stockage):
    client, _ = env
    with client.websocket_connect(URL_WS.format(cle="cle-de-test")) as ws:
        pid = ws.receive_json()["poste_id"]
        ws.receive_json()
        ws.receive_json()                             # lot 58 : état de la session

        # 1) Le poste envoie une capture : message image dans le chat interne, poussé en direct
        r = client.post("/api/support-loois/photo", headers=ENTETES_POSTE,
                        files={"photo": ("capture.png", b"\x89PNG-image", "image/png")}, data={"caption": "Erreur ici"})
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["media_kind"] == "image" and doc["sender_id"] == pid and doc["text"] == "Erreur ici"
        assert ws.receive_json()["message"]["id"] == doc["id"]

        # 2) Le poste relit son image ; l'administrateur la voit dans le fil
        img = client.get(f"/api/support-loois/media/{doc['id']}", headers=ENTETES_POSTE)
        assert img.status_code == 200 and img.content == b"\x89PNG-image"
        msgs = client.get(f"/api/me/chat/{sl.ESPACE_ID}/messages", headers={"X-User": "adm1"}, params={"with_user": pid}).json()
        assert msgs[-1]["media_kind"] == "image"

        # 3) L'administrateur renvoie une image annotée : le poste la reçoit et peut la télécharger
        r2 = client.post(f"/api/me/chat/{sl.ESPACE_ID}/messages/photo", headers={"X-User": "adm1"},
                         files={"photo": ("annotee.jpg", b"JPEG-annotee", "image/jpeg")}, data={"recipient_id": pid})
        assert r2.status_code == 200, r2.text
        recu = ws.receive_json()["message"]
        assert recu["media_kind"] == "image"
        assert client.get(f"/api/support-loois/media/{recu['id']}", headers=ENTETES_POSTE).content == b"JPEG-annotee"


def test_images_protegees(env, stockage):
    client, _ = env
    # Clé absente ou fausse : refusé
    assert client.post("/api/support-loois/photo", files={"photo": ("a.png", b"x", "image/png")}).status_code == 401
    mauvais = {**ENTETES_POSTE, "X-Loois-Cle": "faux"}
    assert client.post("/api/support-loois/photo", headers=mauvais, files={"photo": ("a.png", b"x", "image/png")}).status_code == 401
    # Type refusé
    r = client.post("/api/support-loois/photo", headers=ENTETES_POSTE, files={"photo": ("a.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    # Un AUTRE poste ne peut pas lire l'image du premier
    doc = client.post("/api/support-loois/photo", headers=ENTETES_POSTE, files={"photo": ("a.png", b"img", "image/png")}).json()
    autre = {**ENTETES_POSTE, "X-Loois-Poste": "PC-AUTRE"}
    assert client.get(f"/api/support-loois/media/{doc['id']}", headers=autre).status_code == 404


def test_cle_dans_l_en_tete_du_websocket(env):
    client, _ = env
    url = "/api/ws/support-loois?ecole=E&poste=P&utilisateur=U"
    with client.websocket_connect(url, headers={"X-Loois-Cle": "cle-de-test"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_compte_superviseur_designe_voit_et_repond(env, monkeypatch, stockage):
    """Lot 57.13.1 — cas réel : le propriétaire est connecté avec un compte « superviseur » désigné dans
    LOOIS_SUPPORT_ADMIN_EMAIL (majuscules indifférentes) : il voit l'espace, reçoit en direct et répond."""
    client, _ = env
    monkeypatch.setenv("LOOIS_SUPPORT_ADMIN_EMAIL", "proprio@sawali.test")
    h = {"X-User": "sup1"}
    ids = [c["id"] for c in client.get("/api/me/chat/clients", headers=h).json()]
    assert ids[0] == sl.ESPACE_ID
    with client.websocket_connect(URL_WS.format(cle="cle-de-test")) as ws:
        pid = ws.receive_json()["poste_id"]
        ws.receive_json()
        ws.receive_json()                             # lot 58 : état de la session
        ws.send_json({"type": "message", "texte": "Bonjour"})
        msg = ws.receive_json()["message"]
        assert msg["recipient_id"] == "sup1"          # destinataire = le compte superviseur désigné
        fils = client.get(f"/api/me/chat/{sl.ESPACE_ID}/threads", headers=h).json()
        assert any(f["key"] == pid and f["unread"] == 1 for f in fils)
        r = client.post(f"/api/me/chat/{sl.ESPACE_ID}/messages", headers=h, json={"text": "Réponse", "recipient_id": pid})
        assert r.status_code == 200, r.text
        assert ws.receive_json()["message"]["text"] == "Réponse"
        # Le superviseur voit aussi l'image envoyée par un administrateur au poste
        doc = client.post(f"/api/me/chat/{sl.ESPACE_ID}/messages/photo", headers={"X-User": "adm1"},
                          files={"photo": ("a.jpg", b"JPG", "image/jpeg")}, data={"recipient_id": pid}).json()
        assert client.get(f"/api/me/chat/media/{doc['id']}", headers=h).status_code == 200


def test_superviseur_non_designe_ne_voit_rien(env, monkeypatch):
    client, _ = env
    monkeypatch.setenv("LOOIS_SUPPORT_ADMIN_EMAIL", "autre@sawali.test")
    h = {"X-User": "sup1"}
    assert sl.ESPACE_ID not in [c["id"] for c in client.get("/api/me/chat/clients", headers=h).json()]
    assert client.get(f"/api/me/chat/{sl.ESPACE_ID}/threads", headers=h).status_code == 403


def test_duree_de_session_configurable(monkeypatch):
    """Lot 57.16 — durée maximale (30 min par défaut) ; lot 58 : comptée depuis l'acceptation (voir test_lot58)."""
    monkeypatch.setenv("LOOIS_SUPPORT_SESSION_MINUTES", "0.01")
    assert sl.duree_session_secondes() == pytest.approx(0.6)
    monkeypatch.delenv("LOOIS_SUPPORT_SESSION_MINUTES")
    assert sl.duree_session_secondes() == 1800
