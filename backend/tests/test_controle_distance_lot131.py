"""Lot 131 — contrôle à distance : droits, consentement du poste, jetons à usage unique, relais, mode imposé, journal."""
import asyncio

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.controle_distance import commande_autorisee, creer_routeur, empreinte

CLE_A, CLE_B = "LOOIS-A", "LOOIS-B"
UTILISATEURS = {
    "tech": {"id": "tech", "email": "admin@sawalismartsystems.com", "full_name": "Technicien SAWALI"},
    "client": {"id": "client", "email": "client@exemple.bf", "full_name": "Client"},
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _app():
    base = AsyncMongoMockClient()["test_controle_distance"]
    _run(base.support_loois_postes.insert_many([
        {"id": "p1", "nom": "Pharmacie A — Caisse 1", "cle_client_code": "A"},
        {"id": "p2", "nom": "Poste sans clé client", "cle_client_code": None},
    ]))

    async def courant(request: Request):
        uid = request.headers.get("x-test-user")
        if uid not in UTILISATEURS:
            raise HTTPException(status_code=401, detail="non connecté")
        return UTILISATEURS[uid]

    async def identifier(db, cle, **_):
        return {CLE_A: {"type": "client", "code": "A"}, CLE_B: {"type": "client", "code": "B"},
                "COMMUNE": {"type": "commune"}}.get(cle)

    routeur = creer_routeur(db=base, get_current_user=courant, identifier_cle=identifier, decode_token=lambda t: {})
    api = APIRouter(prefix="/api")
    api.include_router(routeur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), base


TECH = {"x-test-user": "tech"}


def _demander(client, mode="controler"):
    r = client.post("/api/controle-distance/sessions", json={"poste_id": "p1", "mode": mode}, headers=TECH)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _accepter(client, sid, mode=None):
    corps = {"accepte": True} | ({"mode": mode} if mode else {})
    r = client.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json=corps, headers={"x-loois-cle": CLE_A})
    assert r.status_code == 200, r.text
    return r.json()


def test_droits_du_technicien_et_du_poste():
    client, _ = _app()
    # Un utilisateur qui n'est pas du support SAWALI ne peut rien demander
    r = client.post("/api/controle-distance/sessions", json={"poste_id": "p1"}, headers={"x-test-user": "client"})
    assert r.status_code == 403
    # Poste sans clé client : refus
    r = client.post("/api/controle-distance/sessions", json={"poste_id": "p2"}, headers=TECH)
    assert r.status_code == 403
    # Poste inconnu
    assert client.post("/api/controle-distance/sessions", json={"poste_id": "zz"}, headers=TECH).status_code == 404
    sid = _demander(client)
    # Une seule session ouverte par poste
    assert client.post("/api/controle-distance/sessions", json={"poste_id": "p1"}, headers=TECH).status_code == 409
    # Le poste doit présenter SA clé client : clé commune, absente ou d'un autre client refusées
    assert client.get("/api/controle-distance/poste/demande?poste_id=p1",
                      headers={"x-loois-cle": "COMMUNE"}).status_code == 401
    assert client.get("/api/controle-distance/poste/demande?poste_id=p1").status_code == 401
    assert client.get("/api/controle-distance/poste/demande?poste_id=p1",
                      headers={"x-loois-cle": CLE_B}).json()["demande"] is None
    d = client.get("/api/controle-distance/poste/demande?poste_id=p1", headers={"x-loois-cle": CLE_A}).json()
    assert d["demande"]["session_id"] == sid and d["demande"]["technicien"] == "Technicien SAWALI"


def test_refus_par_le_poste_et_journal():
    client, _ = _app()
    sid = _demander(client)
    r = client.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json={"accepte": False},
                    headers={"x-loois-cle": CLE_A})
    assert r.json()["statut"] == "refusee"
    assert client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()["statut"] == "refusee"
    j = client.get("/api/controle-distance/journal", headers=TECH).json()["sessions"]
    assert j[0]["statut"] == "refusee" and "jeton_poste_hash" not in j[0]


def test_le_poste_peut_reduire_le_mode_et_les_jetons_ne_servent_qu_une_fois():
    client, base = _app()
    sid = _demander(client, mode="controler")
    rep = _accepter(client, sid, mode="voir")
    assert rep["mode"] == "voir" and rep["jeton"]
    # Le jeton du technicien n'est remis qu'une fois ; seule son empreinte est en base
    e1 = client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()
    e2 = client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()
    assert e1.get("jeton") and "jeton" not in e2
    doc = _run(base.controle_distance_sessions.find_one({"id": sid}))
    assert doc["jeton_poste_hash"] == empreinte(rep["jeton"]) and rep["jeton"] not in str(doc)
    # Connexion avec le jeton du poste : acceptée une fois, refusée la seconde
    with client.websocket_connect("/api/ws/controle-distance") as ws:
        ws.send_json({"type": "auth", "role": "poste", "session_id": sid, "jeton": rep["jeton"]})
        assert ws.receive_json()["type"] == "pret"
    with client.websocket_connect("/api/ws/controle-distance") as ws:
        ws.send_json({"type": "auth", "role": "poste", "session_id": sid, "jeton": rep["jeton"]})
        assert ws.receive_json()["type"] == "erreur"


def test_relais_et_mode_voir_seulement_impose_par_le_serveur():
    client, base = _app()
    sid = _demander(client, mode="controler")
    rep = _accepter(client, sid, mode="voir")
    jeton_tech = client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()["jeton"]
    with client.websocket_connect("/api/ws/controle-distance") as poste:
        poste.send_json({"type": "auth", "role": "poste", "session_id": sid, "jeton": rep["jeton"]})
        assert poste.receive_json()["type"] == "pret"
        with client.websocket_connect("/api/ws/controle-distance") as tech:
            tech.send_json({"type": "auth", "role": "technicien", "session_id": sid, "jeton": jeton_tech})
            assert tech.receive_json() == {"type": "pret", "mode": "voir", "role": "technicien"}
            assert tech.receive_json()["type"] == "debut"
            assert poste.receive_json()["type"] == "debut"
            # Images : du poste vers le technicien
            poste.send_bytes(b"\x01\x00\x00tuile-jpeg")
            assert tech.receive_bytes() == b"\x01\x00\x00tuile-jpeg"
            # Informations du poste vers le technicien
            poste.send_json({"type": "ecrans", "liste": [{"index": 0, "largeur": 1920, "hauteur": 1080}]})
            assert tech.receive_json()["type"] == "ecrans"
            # Mode « voir seulement » : la souris du technicien est REFUSÉE par le serveur
            tech.send_json({"type": "souris", "x": 10, "y": 10, "action": "clic"})
            assert tech.receive_json()["type"] == "refuse"
            # Une commande d'affichage passe
            tech.send_json({"type": "choix_ecran", "index": 0})
            assert poste.receive_json() == {"type": "choix_ecran", "index": 0}
            # Le poste arrête : le technicien est prévenu
            poste.send_json({"type": "arreter"})
            assert tech.receive_json()["type"] == "fin"
    doc = _run(base.controle_distance_sessions.find_one({"id": sid}))
    assert doc["statut"] == "terminee" and "poste" in doc["motif_fin"] and doc["duree_s"] >= 0


def test_commandes_selon_le_mode():
    assert commande_autorisee("controler", {"type": "clavier", "touche": "A"})
    assert not commande_autorisee("voir", {"type": "clavier", "touche": "A"})
    assert not commande_autorisee("voir", {"type": "presse_papiers", "texte": "x"})
    assert commande_autorisee("voir", {"type": "qualite", "valeur": 60})
    assert not commande_autorisee("controler", {"type": "executer", "commande": "cmd.exe"})   # type inconnu


def test_demande_expiree():
    client, base = _app()
    sid = _demander(client)
    _run(base.controle_distance_sessions.update_one({"id": sid}, {"$set": {"expire_le": "2000-01-01T00:00:00+00:00"}}))
    assert client.get("/api/controle-distance/poste/demande?poste_id=p1",
                      headers={"x-loois-cle": CLE_A}).json()["demande"] is None
    r = client.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json={"accepte": True},
                    headers={"x-loois-cle": CLE_A})
    assert r.status_code == 409


def test_demande_trouvee_par_les_en_tetes_du_poste():
    """Loois ne connaît pas son identifiant : il est déduit de l'école, du poste et de l'utilisateur (comme le support)."""
    from routes.support_loois import poste_id
    client, base = _app()
    pid = poste_id("Pharmacie A", "CAISSE-1", "marie")
    _run(base.support_loois_postes.insert_one({"id": pid, "nom": "Pharmacie A — CAISSE-1 (marie)", "cle_client_code": "A"}))
    r = client.post("/api/controle-distance/sessions", json={"poste_id": pid}, headers=TECH)
    sid = r.json()["session_id"]
    en_tetes = {"x-loois-cle": CLE_A, "x-loois-ecole": "Pharmacie%20A", "x-loois-poste": "CAISSE-1",
                "x-loois-utilisateur": "marie"}
    d = client.get("/api/controle-distance/poste/demande", headers=en_tetes).json()
    assert d["demande"]["session_id"] == sid
