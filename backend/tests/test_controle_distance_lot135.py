"""Lot 135 — extensions du contrôle à distance : commandes système, fichiers, identifiants Windows injectés par le serveur,
numéro + ticket automatique, mesures, vidéo par lien signé, agent du service Windows."""
import asyncio

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes import controle_distance_outils as outils
from routes.controle_distance import action_journal, commande_autorisee, creer_routeur, trame_binaire_autorisee

CLE_A = "LOOIS-A"
TECH = {"x-test-user": "tech"}
UTILISATEURS = {"tech": {"id": "tech", "email": "admin@sawalismartsystems.com", "full_name": "Technicien SAWALI"}}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FauxTickets:
    """Remplace tickets_clients.cloturer_ticket : note la clôture et renvoie une intervention."""

    def __init__(self, base):
        self.base, self.clotures = base, []

    async def cloturer_ticket(self, ticket, **kw):
        self.clotures.append((ticket["id"], kw.get("note")))
        await self.base.support_tickets.update_one({"id": ticket["id"]}, {"$set": {"status": "done"}})
        return {"intervention": {"id": "int-1", "intervention_number": "INT-1"}}


class FauxStockage:
    def __init__(self):
        self.objets = {}

    async def ecrire(self, chemin, donnees, type_mime):
        self.objets[chemin] = donnees

    async def lire(self, chemin):
        return self.objets[chemin]

    async def supprimer(self, chemin):
        if "refus" in chemin:
            raise RuntimeError("R2 indisponible")
        self.objets.pop(chemin, None)


def _app():
    base = AsyncMongoMockClient()["test_controle_distance_135"]
    _run(base.users.insert_one({"id": "cli-1", "role": "client", "company": "Pharmacie A"}))
    _run(base.support_loois_postes.insert_many([
        {"id": "p1", "nom": "Pharmacie A — CAISSE-1 (marie)", "cle_client_code": "A", "ecole": "Pharmacie A",
         "poste": "CAISSE-1", "client_id": "cli-1"},
    ]))

    async def courant(request: Request):
        uid = request.headers.get("x-test-user")
        if uid not in UTILISATEURS:
            raise HTTPException(status_code=401, detail="non connecté")
        return UTILISATEURS[uid]

    async def identifier(db, cle, **_):
        return {"type": "client", "code": "A"} if cle == CLE_A else None

    tickets, stockage = FauxTickets(base), FauxStockage()
    routeur = creer_routeur(db=base, get_current_user=courant, identifier_cle=identifier, decode_token=lambda t: {},
                            tickets=tickets, stockage=stockage)
    api = APIRouter(prefix="/api")
    api.include_router(routeur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), base, tickets, stockage


def _ouvrir(client):
    """Demande + accord + jetons des deux bouts."""
    r = client.post("/api/controle-distance/sessions", json={"poste_id": "p1", "mode": "controler"}, headers=TECH)
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    rep = client.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json={"accepte": True},
                      headers={"x-loois-cle": CLE_A}).json()
    jeton_tech = client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()["jeton"]
    return sid, rep["jeton"], jeton_tech


def test_numero_et_client_de_la_prise_en_main():
    client, base, _, _ = _app()
    r = client.post("/api/controle-distance/sessions", json={"poste_id": "p1"}, headers=TECH).json()
    assert r["numero"].startswith("CD-") and r["numero"].endswith("-00001") and r["client_nom"] == "Pharmacie A"
    client.post(f"/api/controle-distance/sessions/{r['session_id']}/arreter", headers=TECH)
    r2 = client.post("/api/controle-distance/sessions", json={"poste_id": "p1"}, headers=TECH).json()
    assert r2["numero"].endswith("-00002")


def test_commandes_systeme_fichiers_et_trames():
    assert commande_autorisee("controler", {"type": "systeme", "action": "redemarrer"})
    assert not commande_autorisee("voir", {"type": "systeme", "action": "redemarrer"})
    assert not commande_autorisee("controler", {"type": "systeme", "action": "formater"})   # action inconnue
    # Lot 135.2 : bureaux virtuels Windows, mode « contrôler » seulement
    for action in ("bureau_suivant", "bureau_precedent", "bureau_nouveau"):
        assert commande_autorisee("controler", {"type": "systeme", "action": action})
        assert not commande_autorisee("voir", {"type": "systeme", "action": action})
    assert commande_autorisee("controler", {"type": "bloquer_entrees", "valeur": 1})
    assert commande_autorisee("voir", {"type": "echelle", "valeur": 50})
    assert not commande_autorisee("controler", {"type": "saisir_identifiants", "mot_de_passe": "x"})   # jamais du navigateur
    # Trames binaires : tuiles (1) et fichiers (3) du poste ; fichiers (2) du technicien en mode « contrôler » seulement
    assert trame_binaire_autorisee("poste", "voir", b"\x01abc") and trame_binaire_autorisee("poste", "voir", b"\x03abc")
    assert not trame_binaire_autorisee("poste", "controler", b"\x02abc")
    assert trame_binaire_autorisee("technicien", "controler", b"\x02abc")
    assert not trame_binaire_autorisee("technicien", "voir", b"\x02abc")
    assert action_journal({"type": "systeme", "action": "eteindre"}) == {"type": "systeme", "detail": "eteindre"}
    assert action_journal({"type": "souris"}) is None


def test_relais_fichiers_identifiants_ticket_et_journal():
    client, base, tickets, _ = _app()
    # Identifiant Windows mémorisé : la page ne voit jamais le mot de passe
    r = client.put("/api/controle-distance/postes/p1/identifiants",
                   json={"utilisateur": "marie", "domaine": "PHARMA", "mot_de_passe": "S3cret!"}, headers=TECH)
    assert r.status_code == 200 and r.json()["enregistre"] and "S3cret" not in r.text
    assert "S3cret" not in str(_run(base.controle_distance_identifiants.find_one({})))
    # Fiche « service Windows » : seule la saisie automatique de l'agent système a un sens à l'écran de connexion
    _run(base.support_loois_postes.update_one({"id": "p1"}, {"$set": {"agent_service": True}}))
    sid, jeton_poste, jeton_tech = _ouvrir(client)
    with client.websocket_connect("/api/ws/controle-distance") as poste:
        poste.send_json({"type": "auth", "role": "poste", "session_id": sid, "jeton": jeton_poste})
        assert poste.receive_json()["type"] == "pret"
        with client.websocket_connect("/api/ws/controle-distance") as tech:
            tech.send_json({"type": "auth", "role": "technicien", "session_id": sid, "jeton": jeton_tech})
            assert tech.receive_json()["type"] == "pret"
            assert tech.receive_json()["type"] == "debut" and poste.receive_json()["type"] == "debut"
            # Ticket du client ouvert au début
            doc = _run(base.controle_distance_sessions.find_one({"id": sid}))
            assert doc["ticket_number"] and _run(base.support_tickets.count_documents({"source": "controle_distance"})) == 1
            # Fichier du technicien vers le poste (trame binaire de type 2)
            tech.send_json({"type": "fichier_debut", "id": 7, "nom": "outil.exe", "taille": 3})
            assert poste.receive_json()["type"] == "fichier_debut"
            tech.send_bytes(b"\x02\x07\x00\x00\x00abc")
            assert poste.receive_bytes() == b"\x02\x07\x00\x00\x00abc"
            # Commande système relayée et notée au journal
            tech.send_json({"type": "systeme", "action": "redemarrer"})
            assert poste.receive_json() == {"type": "systeme", "action": "redemarrer"}
            # Écran de connexion signalé → le SERVEUR saisit l'identifiant (domaine\\utilisateur) une seule fois
            poste.send_json({"type": "bureau", "nom": "Winlogon", "securise": True})
            assert tech.receive_json()["type"] == "bureau"
            saisie = poste.receive_json()
            assert saisie == {"type": "saisir_identifiants", "utilisateur": "PHARMA\\marie", "mot_de_passe": "S3cret!"}
            assert tech.receive_json()["type"] == "info"
            # À la demande du technicien
            tech.send_json({"type": "identifiants_windows"})
            assert poste.receive_json()["type"] == "saisir_identifiants"
            assert tech.receive_json()["type"] == "info"
            tech.send_json({"type": "arreter"})
            assert poste.receive_json()["type"] == "fin"
    doc = _run(base.controle_distance_sessions.find_one({"id": sid}))
    assert doc["statut"] == "terminee" and doc["delai_accord_s"] is not None and doc["intervention_number"] == "INT-1"
    assert [a["type"] for a in doc["actions"]] == ["fichier_envoye", "systeme", "identifiants_windows", "identifiants_windows"]
    assert "S3cret" not in str(doc) and len(tickets.clotures) == 1
    # Journal d'activités du client : ticket créé + temps de connexion
    kinds = [e["kind"] for e in _run(base.activity_events.find({"client_id": "cli-1"}).to_list(10))]
    assert "ticket" in kinds and "controle_distance" in kinds
    # Mesures de la visionneuse (valeurs absurdes ignorées)
    m = client.post(f"/api/controle-distance/sessions/{sid}/mesures",
                    json={"premiere_image_ms": 850, "latence_moy_ms": 64, "ips_moyen": 12.5, "capture": "dxgi",
                          "debit_moy_ko": -5}, headers=TECH).json()
    assert m["mesures"] == {"premiere_image_ms": 850, "latence_moy_ms": 64, "ips_moyen": 12.5, "capture": "dxgi"}
    assert "CD-" in m["resume"] and "capture DXGI" in m["resume"]
    # Historique du client (fiche client)
    h = client.get("/api/controle-distance/clients/cli-1/sessions", headers=TECH).json()["sessions"]
    assert h[0]["id"] == sid and "jeton_tech_hash" not in h[0]


def test_mode_voir_refuse_identifiants_et_fichiers():
    client, base, _, _ = _app()
    r = client.post("/api/controle-distance/sessions", json={"poste_id": "p1", "mode": "voir"}, headers=TECH).json()
    sid = r["session_id"]
    rep = client.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json={"accepte": True},
                      headers={"x-loois-cle": CLE_A}).json()
    jeton_tech = client.get(f"/api/controle-distance/sessions/{sid}", headers=TECH).json()["jeton"]
    with client.websocket_connect("/api/ws/controle-distance") as poste:
        poste.send_json({"type": "auth", "role": "poste", "session_id": sid, "jeton": rep["jeton"]})
        poste.receive_json()
        with client.websocket_connect("/api/ws/controle-distance") as tech:
            tech.send_json({"type": "auth", "role": "technicien", "session_id": sid, "jeton": jeton_tech})
            tech.receive_json(), tech.receive_json(), poste.receive_json()
            tech.send_json({"type": "identifiants_windows"})
            assert tech.receive_json()["type"] == "refuse"
            tech.send_json({"type": "systeme", "action": "eteindre"})
            assert tech.receive_json()["type"] == "refuse"


def test_video_par_parties_et_lien_signe():
    client, base, _, stockage = _app()
    sid, _, _ = _ouvrir(client)
    assert client.post(f"/api/controle-distance/sessions/{sid}/video/1", content=b"BBB", headers=TECH).status_code == 200
    assert client.post(f"/api/controle-distance/sessions/{sid}/video/0", content=b"AAA", headers=TECH).status_code == 200
    url = client.get(f"/api/controle-distance/sessions/{sid}/video/lien", headers=TECH).json()["url"]
    assert client.get(url).content == b"AAABBB"   # parties lues dans l'ordre
    assert client.get(url.replace("sig=", "sig=0")).status_code == 403
    assert not outils.lien_video_valide(sid, 10, outils.signer_video(sid, 10))   # expiré


def test_agent_du_service_windows_a_sa_fiche_machine():
    from routes.support_loois import poste_id
    client, base, _, _ = _app()
    en_tetes = {"x-loois-cle": CLE_A, "x-loois-ecole": "Pharmacie%20A", "x-loois-poste": "CAISSE-1",
                "x-loois-utilisateur": "SYSTEM", "x-loois-agent": "service"}
    assert client.get("/api/controle-distance/poste/demande", headers=en_tetes).json()["demande"] is None
    pid = poste_id("Pharmacie A", "CAISSE-1", "")
    fiche = _run(base.support_loois_postes.find_one({"id": pid}))
    assert fiche["agent_service"] and fiche["nom"].endswith("service Windows")
    # Le chat de la fiche « service » est celui de l'utilisateur du même ordinateur ; identifiants communs à l'ordinateur
    client.put("/api/controle-distance/postes/p1/identifiants", json={"utilisateur": "marie", "mot_de_passe": "x"}, headers=TECH)
    etat = client.get(f"/api/controle-distance/postes/{pid}", headers=TECH).json()
    assert etat["agent_service"] and etat["fil_id"] == "p1" and etat["identifiants"]["enregistre"]


def test_reglages_et_outils_purs():
    client, _, _, _ = _app()
    r = client.put("/api/controle-distance/reglages", json={"enregistrement_video": False, "video_ips": 99}, headers=TECH).json()
    assert r["enregistrement_video"] is False and r["video_ips"] == 15
    assert outils.numero_session(2026, 42) == "CD-2026-00042"
    assert outils.delais_session({"cree_le": "2026-10-12T10:00:00+00:00", "accepte_le": "2026-10-12T10:00:08+00:00",
                                  "debut_le": "2026-10-12T10:00:10+00:00"}, "2026-10-12T10:12:10+00:00") == \
        {"delai_accord_s": 8, "delai_connexion_s": 2, "duree_s": 720}
    assert outils.dechiffrer(outils.chiffrer("é-mot")) == "é-mot" and outils.dechiffrer("abîmé") is None


def test_dossiers_des_transferts_memorises_par_ordinateur():
    from routes.support_loois import poste_id
    client, base, _, _ = _app()
    r = client.put("/api/controle-distance/postes/p1/dossiers", json={"dossier_base": "D:\\Partage\\Support"}, headers=TECH).json()
    assert r == {"dossier_base": "D:\\Partage\\Support", "dernier_chemin": ""}
    # Le dernier chemin est ajouté sans effacer le dossier de base
    client.put("/api/controle-distance/postes/p1/dossiers", json={"dernier_chemin": "C:\\Temp"}, headers=TECH)
    # Même ordinateur vu par le service Windows : mêmes dossiers
    _run(base.support_loois_postes.insert_one({"id": poste_id("Pharmacie A", "CAISSE-1", ""), "ecole": "Pharmacie A",
                                               "poste": "CAISSE-1", "agent_service": True, "cle_client_code": "A"}))
    r = client.get(f"/api/controle-distance/postes/{poste_id('Pharmacie A', 'CAISSE-1', '')}/dossiers", headers=TECH).json()
    assert r == {"dossier_base": "D:\\Partage\\Support", "dernier_chemin": "C:\\Temp"}
    assert action_journal({"type": "fichier_debut", "nom": "a.pdf", "taille": 3, "chemin": "D:\\X"})["detail"].endswith("→ D:\\X")


def test_purge_automatique_des_videos_apres_la_conservation():
    """Lot 135.1 — vidéos supprimées après N jours (réglage) ; journal conservé ; échec réessayé la nuit suivante."""
    from datetime import datetime, timezone
    from routes.controle_distance import purger_videos
    client, base, _, stockage = _app()
    for sid, fin in (("vieille", "2026-01-01T10:00:00+00:00"), ("recente", "2026-10-10T10:00:00+00:00")):
        _run(base.controle_distance_sessions.insert_one({"id": sid, "numero": f"CD-{sid}", "video": True, "video_parties": [0, 1],
                                                         "video_octets": 300, "fin_le": fin, "cree_le": fin}))
        for i in (0, 1):
            stockage.objets[outils.chemin_partie_video(sid, i)] = b"x"
    quand = datetime(2026, 10, 12, tzinfo=timezone.utc)
    bilan = _run(purger_videos(base, stockage, quand=quand))   # réglage par défaut : 90 jours
    assert bilan == {"jours": 90, "sessions": 1, "octets": 300, "erreurs": 0}
    vieille = _run(base.controle_distance_sessions.find_one({"id": "vieille"}))
    assert vieille["video"] is False and vieille["video_purgee"] and vieille["numero"] == "CD-vieille"
    assert not any("vieille" in c for c in stockage.objets) and outils.chemin_partie_video("recente", 0) in stockage.objets
    # Durée de conservation réglée à 1 jour : la session récente est purgée à son tour ; une purge déjà faite n'est pas refaite
    client.put("/api/controle-distance/reglages", json={"conservation_jours": 1}, headers=TECH)
    assert _run(purger_videos(base, stockage, quand=quand))["sessions"] == 1
    assert _run(purger_videos(base, stockage, quand=quand))["sessions"] == 0
    # Partie impossible à supprimer : la session garde sa vidéo (nouvel essai la nuit suivante)
    _run(base.controle_distance_sessions.insert_one({"id": "refus", "video": True, "video_parties": [0], "fin_le": "2026-01-01T00:00:00+00:00"}))
    bilan = _run(purger_videos(base, stockage, quand=quand))
    assert bilan["erreurs"] == 1 and _run(base.controle_distance_sessions.find_one({"id": "refus"}))["video"] is True
    # Bouton « Purger maintenant » de la rubrique
    assert client.post("/api/controle-distance/videos/purger", headers=TECH).json()["jours"] == 1


def test_identifiants_separes_entre_clients_pour_des_machines_de_meme_nom():
    """Lot 135.7 : « XVERSER » chez deux clients (l'école = le nom de la machine) ne doit pas partager les identifiants."""
    client, base, _, _ = _app()
    _run(base.support_loois_postes.insert_many([
        {"id": "m1", "nom": "XVERSER — XVERSER (Admin)", "cle_client_code": "MARTIN", "ecole": "XVERSER", "poste": "XVERSER"},
        {"id": "m1s", "nom": "XVERSER — XVERSER · service Windows", "cle_client_code": "MARTIN", "ecole": "XVERSER",
         "poste": "XVERSER", "agent_service": True},
        {"id": "p2", "nom": "XVERSER — XVERSER (Admin)", "cle_client_code": "PHL", "ecole": "XVERSER", "poste": "XVERSER"},
    ]))
    r = client.put("/api/controle-distance/postes/m1/identifiants",
                   json={"utilisateur": "Administrateur", "domaine": "MARTIN", "mot_de_passe": "x1"}, headers=TECH)
    assert r.status_code == 200
    # Même client, même machine (fiche du service Windows) : l'identifiant est partagé
    assert client.get("/api/controle-distance/postes/m1s/identifiants", headers=TECH).json()["utilisateur"] == "Administrateur"
    # Autre client, machine de même nom : rien (avant : les identifiants de MARTIN s'affichaient)
    autre = client.get("/api/controle-distance/postes/p2/identifiants", headers=TECH).json()
    assert not autre["enregistre"] and not autre.get("utilisateur")
