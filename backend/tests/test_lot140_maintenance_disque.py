"""Lot 140 — maintenance du disque depuis le contrôle à distance : commande reconstruite par le serveur, liste fermée,
mode « voir » refusé, avancement relayé, tâches terminées inscrites dans la session puis transmises à l'intervention.
Lancer : cd backend && python -m pytest tests/test_lot140_maintenance_disque.py -q"""
from routes.controle_distance import (ACTIONS_MAINTENANCE, action_journal, commande_autorisee, commande_maintenance_propre,
                                      tache_depuis_etat, taches_effectuees)
from tests.test_controle_distance_lot135 import TECH, _app, _ouvrir, _run


def test_commande_reconstruite_et_liste_fermee():
    assert commande_maintenance_propre({"type": "maintenance", "id": 5, "action": "chkdsk_scan", "chemin": "d",
                                        "extra": "rm -rf"}) == {"type": "maintenance", "id": 5, "action": "chkdsk_scan", "chemin": "D:"}
    assert commande_maintenance_propre({"action": "sfc_scan"})["chemin"] == "C:"
    for mauvais in ({"action": "format"}, {"action": "chkdsk_scan", "chemin": "C:; shutdown"}, {"action": "chkdsk_scan", "chemin": "C:\\Windows"}):
        assert commande_maintenance_propre(mauvais) is None
    assert commande_autorisee("controler", {"type": "maintenance", "action": "defrag_optimiser"})
    assert not commande_autorisee("voir", {"type": "maintenance", "action": "defrag_optimiser"})
    assert not commande_autorisee("controler", {"type": "maintenance", "action": "format"})
    assert "defrag /O" in action_journal({"type": "maintenance", "action": "defrag_optimiser", "chemin": "C"})["detail"]
    assert set(ACTIONS_MAINTENANCE) == {"chkdsk_scan", "defrag_analyser", "defrag_optimiser", "sfc_scan"}


def test_taches_terminees_seulement():
    assert tache_depuis_etat({"type": "maintenance_etat", "action": "sfc_scan", "etat": "en_cours"}, "t") is None
    assert tache_depuis_etat({"type": "maintenance_etat", "action": "inconnue", "etat": "termine"}, "t") is None
    t = tache_depuis_etat({"type": "maintenance_etat", "id": 2, "action": "chkdsk_scan", "volume": "C:", "etat": "termine",
                           "code": 0, "resume": "Aucune erreur trouvée sur le disque.\nligne 2"}, "2026-10-13T10:00:00")
    assert t["ok"] is True and t["libelle"].startswith("Analyse du disque")
    lignes = taches_effectuees([t, {**t, "ok": False, "resume": "échec"}])
    assert lignes[0]["resultat"] == "Aucune erreur trouvée sur le disque." and lignes[1]["ok"] is False


def test_parcours_maintenance_jusqu_a_l_intervention():
    client, base, tickets, _ = _app()
    sid, jeton_poste, jeton_tech = _ouvrir(client)
    with client.websocket_connect("/api/ws/controle-distance") as poste:
        poste.send_json({"type": "auth", "role": "poste", "session_id": sid, "jeton": jeton_poste})
        assert poste.receive_json()["type"] == "pret"
        with client.websocket_connect("/api/ws/controle-distance") as tech:
            tech.send_json({"type": "auth", "role": "technicien", "session_id": sid, "jeton": jeton_tech})
            assert tech.receive_json()["type"] == "pret"
            assert tech.receive_json()["type"] == "debut" and poste.receive_json()["type"] == "debut"
            # Commande reconstruite : le champ « extra » du navigateur n'atteint pas le poste
            tech.send_json({"type": "maintenance", "id": 9, "action": "chkdsk_scan", "chemin": "c", "extra": "x"})
            assert poste.receive_json() == {"type": "maintenance", "id": 9, "action": "chkdsk_scan", "chemin": "C:"}
            # Action inconnue : refusée au technicien, rien n'est relayé
            tech.send_json({"type": "maintenance", "id": 10, "action": "format", "chemin": "C:"})
            assert tech.receive_json()["type"] == "refuse"
            # Avancement puis fin réussie, puis une 2e tâche en échec
            poste.send_json({"type": "maintenance_etat", "id": 9, "action": "chkdsk_scan", "volume": "C:", "etat": "en_cours",
                             "resume": "25 %"})
            assert tech.receive_json()["etat"] == "en_cours"
            poste.send_json({"type": "maintenance_etat", "id": 9, "action": "chkdsk_scan", "volume": "C:", "etat": "termine",
                             "code": 0, "resume": "Aucune erreur trouvée sur le disque.\nWindows a analysé le système de fichiers."})
            assert tech.receive_json()["etat"] == "termine"
            poste.send_json({"type": "maintenance_etat", "id": 11, "action": "sfc_scan", "volume": "C:", "etat": "echec",
                             "code": 1, "resume": "Terminé avec une erreur (code 1)."})
            assert tech.receive_json()["etat"] == "echec"
            tech.send_json({"type": "arreter"})
            assert poste.receive_json()["type"] == "fin"
    doc = _run(base.controle_distance_sessions.find_one({"id": sid}))
    assert [t["action"] for t in doc["taches"]] == ["chkdsk_scan", "sfc_scan"]
    assert [a["type"] for a in doc["actions"]] == ["maintenance", "maintenance_fin", "maintenance_fin"]
    assert "Aucune erreur" in tickets.dernieres_taches[0]["resultat"] and tickets.dernieres_taches[1]["ok"] is False
