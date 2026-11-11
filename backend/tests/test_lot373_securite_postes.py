"""Lot 373 — Sécurité des postes clients : alertes du service Windows Loois, approbation par le propriétaire.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot373_securite_postes.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.securite_postes as sp  # noqa: E402

CLE = {"X-Loois-Cle": "cle-commune-test"}


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def client(db, role="admin"):
    """Application minimale avec les routes du lot 373 (utilisateur factice)."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    async def utilisateur():
        return {"id": "adm", "role": role, "full_name": "Admin SAWALI"}

    api = APIRouter(prefix="/api")
    sp.setup_securite_postes_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def envoi(*evenements, poste="PC-ACCUEIL", site="CMC"):
    return {"poste": poste, "site": site, "version": "1.2611.0.1", "evenements": list(evenements)}


def alerte(type_, cle, detail="d", gravite=None):
    e = {"type": type_, "cle": cle, "detail": detail}
    if gravite:
        e["gravite"] = gravite
    return e


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-commune-test")


def test_nettoyage_de_l_envoi():
    poste, site, version, alertes = sp.nettoyer_envoi(envoi(
        alerte("logiciel_nouveau", "logiciel|anydesk", "x" * 900),
        alerte("type_inconnu", "k"),                         # type inconnu : ignoré
        alerte("usb_nouveau", ""),                           # sans clé : ignoré
        alerte("port_hfsql_occupe", "port|4900|c:\\a.exe", "d", "pirate"),   # gravité invalide : celle du type
        "pas un objet"))
    assert (poste, site, version) == ("PC-ACCUEIL", "CMC", "1.2611.0.1")
    assert [a["type"] for a in alertes] == ["logiciel_nouveau", "port_hfsql_occupe"]
    assert len(alertes[0]["detail"]) == 400 and alertes[1]["gravite"] == "haute"
    with pytest.raises(ValueError):
        sp.nettoyer_envoi({"evenements": []})                 # poste obligatoire
    with pytest.raises(ValueError):
        sp.nettoyer_envoi("x")


def test_fusion_sans_doublon_et_plafond(monkeypatch):
    monkeypatch.setattr(sp, "MAX_PAR_POSTE", 3)
    a = [{"cle": f"k{i}", "type": "usb_nouveau", "gravite": "moyenne", "detail": ""} for i in range(2)]
    liste = sp.fusionner_alertes([], a, "t1")
    assert [x["statut"] for x in liste] == ["nouvelle", "nouvelle"]
    assert len(sp.fusionner_alertes(liste, a, "t2")) == 2                  # mêmes clés : rien d'ajouté
    liste[0]["statut"] = "ignoree"
    plus = sp.fusionner_alertes(liste, [{"cle": "k2", "type": "usb_nouveau", "gravite": "moyenne", "detail": ""},
                                        {"cle": "k3", "type": "usb_nouveau", "gravite": "moyenne", "detail": ""}], "t3")
    assert [x["cle"] for x in plus] == ["k1", "k2", "k3"]                   # la plus ancienne alerte TRAITÉE part d'abord


def test_valeurs_approuvables():
    f = sp.valeur_approuvable
    assert f({"type": "logiciel_nouveau", "cle": "logiciel|anydesk"}) == ("logiciels", "anydesk")
    assert f({"type": "programme_inconnu_reseau", "cle": "reseau|c:\\outils\\a.exe"}) == ("chemins", "c:\\outils\\a.exe")
    assert f({"type": "port_hfsql_occupe", "cle": "port|4900|c:\\outils\\p.exe"}) == ("chemins", "c:\\outils\\p.exe")
    assert f({"type": "usb_nouveau", "cle": "usb|disk&ven_a\\111"}) == ("usb", "disk&ven_a\\111")
    assert f({"type": "usb_politique_modifiee", "cle": "usbpolitique|2026"}) is None
    assert f({"type": "reference_creee", "cle": "reference|creee"}) is None


def test_decisions():
    s = {"evenements": [
        {"cle": "logiciel|anydesk", "type": "logiciel_nouveau", "statut": "nouvelle"},
        {"cle": "usbpolitique|1", "type": "usb_politique_modifiee", "statut": "nouvelle"}], "approuves": {"logiciels": [], "chemins": [], "usb": []}}
    sp.appliquer_decision(s, "logiciel|anydesk", "approuver", "Admin", "t")
    assert s["approuves"]["logiciels"] == ["anydesk"] and s["evenements"][0]["statut"] == "approuvee" and s["evenements"][0]["decide_par"] == "Admin"
    with pytest.raises(ValueError):
        sp.appliquer_decision(s, "usbpolitique|1", "approuver", "Admin", "t")       # non approuvable
    sp.appliquer_decision(s, "usbpolitique|1", "ignorer", "Admin", "t")
    sp.appliquer_decision(s, "usbpolitique|1", "reouvrir", "Admin", "t")
    assert s["evenements"][1]["statut"] == "nouvelle" and s["evenements"][1]["decide_le"] is None
    with pytest.raises(ValueError):
        sp.appliquer_decision(s, "logiciel|anydesk", "reouvrir", "Admin", "t")      # une approbation n'est pas révocable à distance
    with pytest.raises(ValueError):
        sp.appliquer_decision(s, "inconnue", "ignorer", "Admin", "t")


def test_poste_sans_cle_ou_avec_fausse_cle_refuse(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot373a"]
    c = client(db)
    assert c.post("/api/securite-poste/evenements", json=envoi()).status_code == 401
    assert c.post("/api/securite-poste/evenements", json=envoi(), headers={"X-Loois-Cle": "faux"}).status_code == 401
    assert c.post("/api/securite-poste/evenements", json={"evenements": []}, headers=CLE).status_code == 422
    assert lancer(db.inventaires_postes.count_documents({})) == 0


def test_flux_complet_alerte_approbation_et_reponse_au_poste(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot373b"]
    c = client(db)
    r = c.post("/api/securite-poste/evenements", headers=CLE, json=envoi(
        alerte("logiciel_nouveau", "logiciel|anydesk", "Nouveau logiciel installé : AnyDesk"),
        alerte("port_hfsql_occupe", "port|4900|c:\\outils\\proxy.exe", "Port 4900 occupé")))
    assert r.status_code == 200 and r.json()["approuves"] == {"logiciels": [], "chemins": [], "usb": []}
    # Renvoi des mêmes alertes : pas de doublon
    c.post("/api/securite-poste/evenements", headers=CLE, json=envoi(alerte("logiciel_nouveau", "logiciel|anydesk")))
    liste = c.get("/api/admin/securite-postes").json()
    assert liste["nouvelles"] == 2
    [p] = liste["postes"]
    assert p["machine"] == "PC-ACCUEIL" and p["gravite_max"] == "haute" and p["nouvelles"] == 2
    assert p["alertes"][0]["type"] == "port_hfsql_occupe"                    # la plus grave d'abord
    # Le propriétaire approuve AnyDesk : la réponse suivante au poste le contient
    d = c.post("/api/admin/securite-postes/decision", json={"machine": "pc-accueil", "cle": "logiciel|anydesk", "decision": "approuver"})
    assert d.status_code == 200 and d.json()["alerte"]["statut"] == "approuvee"
    r = c.post("/api/securite-poste/evenements", headers=CLE, json=envoi())            # corps vide (toutes les 10 minutes)
    assert r.json()["approuves"]["logiciels"] == ["anydesk"]
    assert c.get("/api/admin/securite-postes").json()["nouvelles"] == 1
    # Décision impossible : 409 ; poste inconnu : 404
    assert c.post("/api/admin/securite-postes/decision", json={"machine": "PC-ACCUEIL", "cle": "x", "decision": "ignorer"}).status_code == 409
    assert c.post("/api/admin/securite-postes/decision", json={"machine": "AUTRE", "cle": "x", "decision": "ignorer"}).status_code == 404
    # La fiche d'inventaire du poste n'est pas écrasée (même collection, autre champ)
    lancer(db.inventaires_postes.update_one({"machine_cle": "PC-ACCUEIL"}, {"$set": {"inventaire": {"systeme": "Windows"}}}))
    c.post("/api/securite-poste/evenements", headers=CLE, json=envoi())
    assert lancer(db.inventaires_postes.find_one({"machine_cle": "PC-ACCUEIL"}))["inventaire"] == {"systeme": "Windows"}


def test_export_csv_et_droits(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot373c"]
    c = client(db)
    c.post("/api/securite-poste/evenements", headers=CLE, json=envoi(alerte("usb_nouveau", "usb|disk&ven_a\\1", "Clé A")))
    r = c.get("/api/admin/securite-postes/export.csv")
    assert r.status_code == 200 and "PC-ACCUEIL" in r.text and "Nouvelle clé USB" in r.text and r.text.startswith("\ufeff")
    autre = client(db, role="client")
    assert autre.get("/api/admin/securite-postes").status_code == 403
    assert autre.post("/api/admin/securite-postes/decision", json={}).status_code == 403
    assert autre.get("/api/admin/securite-postes/export.csv").status_code == 403


def test_plafond_de_postes(env, monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot373d"]
    monkeypatch.setattr(sp, "MAX_POSTES", 1)
    c = client(db)
    assert c.post("/api/securite-poste/evenements", headers=CLE, json=envoi(poste="A")).status_code == 200
    assert c.post("/api/securite-poste/evenements", headers=CLE, json=envoi(poste="B")).status_code == 429
    assert c.post("/api/securite-poste/evenements", headers=CLE, json=envoi(poste="A")).status_code == 200
