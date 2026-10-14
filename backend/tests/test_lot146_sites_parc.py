"""Lot 146 — Parc informatique : site par défaut (libellé du client de la clé), complétion des fiches sans site, modification
du nom de site en lot, saisie manuelle protégée. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot146_sites_parc.py -q"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.versions_deployees as vd  # noqa: E402
from tests.test_lot66_inventaire_postes import client, inventaire, lancer, signal  # noqa: E402


def test_site_par_defaut_et_priorite_au_site_de_loois():
    inv = inventaire()
    # Loois annonce un site : il est utilisé
    assert vd.champs_parc_auto({"machine": "PC1", "site": "PHL"}, inv, "t", True, "Pharmacie X")["champs"]["site"] == "PHL"
    # Pas de site annoncé : libellé du client de la clé
    assert vd.champs_parc_auto({"machine": "PC1"}, inv, "t", True, "Ecole des Métiers")["champs"]["site"] == "Ecole des Métiers"
    # Ni l'un ni l'autre : vide
    assert vd.champs_parc_auto({"machine": "PC1"}, inv, "t", False)["champs"]["site"] is None


def test_modification_du_site_en_lot_et_saisie_protegee():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot146a"]
    c = client(db)
    c.post("/api/presence-logiciel", json=signal(machine="PC-A", inv=inventaire(mac="00-15-5D-0A-0B-01"), site=""))
    c.post("/api/presence-logiciel", json=signal(machine="PC-B", inv=inventaire(mac="00-15-5D-0A-0B-02"), site=""))
    equipements = lancer(db.parc_equipements.find({}, {"_id": 0}).to_list(10))
    assert len(equipements) == 2 and all(not e.get("site") for e in equipements)
    ids = [e["id"] for e in equipements]
    # Le groupe « sans site » reçoit un nom d'un coup
    r = c.post("/api/me/parc/equipements/site", json={"ids": ids, "vers": "  Ecole des   Métiers "})
    assert r.status_code == 200 and r.json()["modifies"] == 2 and r.json()["site"] == "Ecole des Métiers"
    assert {e["site"] for e in lancer(db.parc_equipements.find({}, {"_id": 0}).to_list(10))} == {"Ecole des Métiers"}
    # Un nouvel inventaire de Loois (site vide) n'efface pas la saisie manuelle
    c.post("/api/presence-logiciel", json=signal(machine="PC-A", inv=inventaire(mac="00-15-5D-0A-0B-01", ip="10.0.0.9"), site=""))
    e = lancer(db.parc_equipements.find_one({"loois_machine": "PC-A"}, {"_id": 0}))
    assert e["site"] == "Ecole des Métiers" and e["adresse_ip"] == "10.0.0.9"
    # Retirer le site : vers vide
    assert c.post("/api/me/parc/equipements/site", json={"ids": ids[:1], "vers": ""}).json()["site"] is None


def test_completion_des_sites_manquants_depuis_loois():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot146b"]
    c = client(db)
    c.post("/api/presence-logiciel", json=signal(machine="PC-A", inv=inventaire(mac="00-15-5D-0A-0B-01"), site=""))
    c.post("/api/presence-logiciel", json=signal(machine="PC-B", inv=inventaire(mac="00-15-5D-0A-0B-02"), site=""))
    # Fiches anciennes : Loois connaît désormais un site / le client de la clé pour ces machines
    lancer(db.presences_logiciels.update_many({"machine": "PC-A"}, {"$set": {"site": "EDM"}}))
    lancer(db.presences_logiciels.update_many({"machine": "PC-B"}, {"$set": {"verifie_client": "Ecole des Métiers"}}))
    lancer(db.parc_equipements.update_many({}, {"$set": {"site": None}}))
    r = c.post("/api/me/parc/equipements/sites/completer")
    assert r.status_code == 200 and r.json()["completes"] == 2
    sites = {e["loois_machine"]: e["site"] for e in lancer(db.parc_equipements.find({}, {"_id": 0}).to_list(10))}
    assert sites == {"PC-A": "EDM", "PC-B": "Ecole des Métiers"}
    # Rien à compléter la 2e fois ; un client (non admin) n'a pas accès à la complétion
    assert c.post("/api/me/parc/equipements/sites/completer").json()["completes"] == 0
    assert c.post("/api/me/parc/equipements/sites/completer", headers={"X-User": "phl"}).status_code in (403, 404)
