"""Lot 80 — Équipements : découverte du réseau par Loois, appareils « À valider », n° de série du BIOS.
Lancer : cd backend && python -m pytest tests/test_lot80_equipements.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import decouverte_reseau as dr  # noqa: E402
from routes import versions_deployees as vd  # noqa: E402


# ------------------------------------------------------------------ logique pure ----------

def test_mac_normalisee_et_aleatoire():
    # Format commun du parc ; adresses nulle et de diffusion refusées
    assert dr.normaliser_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert dr.normaliser_mac("00:00:00:00:00:00") is None
    assert dr.normaliser_mac("FF:FF:FF:FF:FF:FF") is None
    # Bit « administré localement » : MAC aléatoire d'un téléphone
    assert dr.mac_aleatoire("DA:A1:19:00:00:01") is True
    assert dr.mac_aleatoire("3C:D9:2B:00:00:01") is False


def test_ipv4_privee_seulement():
    # Seules les adresses du réseau local sont gardées
    assert dr.normaliser_ipv4("192.168.1.20") == "192.168.1.20"
    assert dr.normaliser_ipv4("8.8.8.8") is None
    assert dr.normaliser_ipv4("169.254.3.4") is None
    assert dr.normaliser_ipv4("pas une ip") is None


def test_nettoyer_appareil_garde_snmp_et_rejette_le_vide():
    a = dr.nettoyer_appareil({"ip": "192.168.1.30", "mac": "3c-d9-2b-11-22-33", "nom_hote": "IMP-ACCUEIL",
                              "categorie": "imprimante",
                              "snmp": {"description": "HP LaserJet\x00 M404", "modele": "M404dn", "numero_serie": "VNB3K12345",
                                       "pages": "15230", "consommables": [{"nom": "Toner noir", "pct": 42}, {"x": 1}]}})
    assert a["mac"] == "3C:D9:2B:11:22:33" and a["categorie"] == "imprimante"
    assert a["snmp"]["pages"] == 15230 and a["snmp"]["consommables"] == [{"nom": "Toner noir", "pct": 42}]
    assert "\x00" not in a["snmp"]["description"]
    # Ni IP privée ni MAC valable : ignoré
    assert dr.nettoyer_appareil({"ip": "8.8.8.8"}) is None
    # Catégorie inconnue : pas de proposition
    assert dr.nettoyer_appareil({"ip": "192.168.1.9", "categorie": "fusée"})["categorie"] is None


def test_nettoyer_envoi_fusionne_les_doublons_et_borne():
    envoi = dr.nettoyer_envoi({"machine": "SRV-CLINIQUE", "sous_reseaux": ["192.168.1.0/24", "x"],
                               "appareils": [{"ip": "192.168.1.5", "mac": "AA:BB:CC:00:00:01"},
                                             {"ip": "192.168.1.6", "mac": "aa-bb-cc-00-00-01"},
                                             {"ip": "192.168.1.7"}]})
    assert len(envoi["appareils"]) == 2 and envoi["sous_reseaux"] == ["192.168.1.0/24"]
    with pytest.raises(ValueError):
        dr.nettoyer_envoi({"machine": "", "appareils": []})
    with pytest.raises(ValueError):
        dr.nettoyer_envoi({"machine": "SRV", "appareils": [{}] * (dr.MAX_APPAREILS + 1)})


def test_reglages_valides():
    r = dr.nettoyer_reglages({"actif": 0, "heure": "03:15", "jours_absence": "10", "postes": "srv-a, SRV-B;srv-a",
                              "communaute": "Clinique2026"})
    assert r == {"actif": False, "heure": "03:15", "jours_absence": 10, "postes": ["SRV-A", "SRV-B"],
                 "communaute": "Clinique2026"}
    for mauvais in ({"heure": "25:00"}, {"jours_absence": 0}, {"communaute": "avec espace"}, {"postes": ["a b"]}):
        with pytest.raises(ValueError):
            dr.nettoyer_reglages(mauvais)
    # Communauté vide : inchangée (aucune clé renvoyée)
    assert dr.nettoyer_reglages({"communaute": ""}) == {}


def test_doit_lancer():
    midi = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    defaut = {"heure": "02:30"}
    # Par défaut : seulement un Windows Server
    assert dr.doit_lancer(defaut, "PC-ACCUEIL", "poste", None, midi)["lancer"] is False
    assert dr.doit_lancer(defaut, "SRV", "serveur", None, midi)["lancer"] is True
    # Déjà balayé après 02:30 aujourd'hui → non ; balayé hier → oui
    assert dr.doit_lancer(defaut, "SRV", "serveur", "2026-10-08T02:31:00+00:00", midi)["lancer"] is False
    assert dr.doit_lancer(defaut, "SRV", "serveur", "2026-10-07T02:31:00+00:00", midi)["lancer"] is True
    # Avant l'heure du jour : le créneau en cours est celui de la veille
    tot = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)
    assert dr.doit_lancer(defaut, "SRV", "serveur", "2026-10-07T02:31:00+00:00", tot)["lancer"] is False
    # « Lancer maintenant » après la dernière exécution → oui, même déjà fait aujourd'hui
    assert dr.doit_lancer({**defaut, "demande_le": "2026-10-08T11:00:00+00:00"}, "SRV", "serveur",
                          "2026-10-08T02:31:00+00:00", midi)["lancer"] is True
    # Machine choisie explicitement (un PC) ; les autres non ; découverte désactivée
    assert dr.doit_lancer({"postes": ["PC-ADMIN"]}, "pc-admin", "poste", None, midi)["lancer"] is True
    assert dr.doit_lancer({"postes": ["PC-ADMIN"]}, "SRV", "serveur", None, midi)["lancer"] is False
    assert dr.doit_lancer({"actif": False}, "SRV", "serveur", None, midi)["lancer"] is False


def test_completer_fiche_ne_touche_jamais_une_saisie():
    champs = dr.champs_parc_reseau({"ip": "192.168.1.30", "mac": "AA:BB:CC:00:00:01",
                                    "snmp": {"modele": "M404dn", "numero_serie": "VNB3", "nom": "IMP"}})
    assert champs["nom_hote"] == "IMP" and champs["numero_serie"] == "VNB3"
    assert dr.completer_fiche({"modele": "Saisi à la main", "numero_serie": None}, champs) == {
        "adresse_ip": "192.168.1.30", "adresse_mac": "AA:BB:CC:00:00:01", "nom_hote": "IMP", "numero_serie": "VNB3"}


def test_absents_seulement_si_le_reseau_a_ete_balaye_depuis():
    appareils = [
        {"id": "1", "statut": "valide", "cle_client": "c1", "derniere_vue": "2026-09-20T02:30:00+00:00"},
        {"id": "2", "statut": "connu", "cle_client": "c1", "derniere_vue": "2026-10-08T02:30:00+00:00"},
        {"id": "3", "statut": "a_valider", "cle_client": "c1", "derniere_vue": "2026-09-01T02:30:00+00:00"},
        {"id": "4", "statut": "valide", "cle_client": "c2", "derniere_vue": "2026-09-01T02:30:00+00:00"},
    ]
    # c2 n'a plus été balayé depuis : pas d'alerte pour son appareil
    absents = dr.appareils_absents(appareils, {"c1": "2026-10-08T02:30:00+00:00", "c2": "2026-09-01T02:30:00+00:00"}, 7)
    assert [a["id"] for a in absents] == ["1"] and absents[0]["absent_jours"] == 18


def test_serie_bios_bidon_ignoree_et_reelle_gardee():
    assert vd.serie_valable("To be filled by O.E.M.") is None
    assert vd.serie_valable("Default string") is None
    assert vd.serie_valable("0000000") is None
    assert vd.serie_valable("  5CG1234XYZ ") == "5CG1234XYZ"
    auto = vd.champs_parc_auto({"machine": "PC-1"}, {"systeme": {"numero_serie": "5CG1234XYZ"}}, "2026-10-08T00:00:00+00:00")
    assert auto["champs"]["numero_serie"] == "5CG1234XYZ"


# ------------------------------------------------------------------ routes ---------------

CLIENT = {"type": "client", "id": "cli1", "code": "CMC", "libelle": "Clinique Centre d'Or", "applications": ["Biolog"]}


@pytest.fixture()
def appli(monkeypatch):
    """Application FastAPI avec les seules routes du lot 80, base en mémoire et clé client simulée."""
    monkeypatch.setenv("JWT_SECRET", "secret-de-test")
    from routes import loois_cles_clients as cles

    async def identifier(db, cle, machine=None):
        return CLIENT if cle == "LK-bonne" else None
    monkeypatch.setattr(cles, "identifier_cle", identifier)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot80"]
    role = {"valeur": "admin"}
    app, api = FastAPI(), APIRouter(prefix="/api")
    dr.setup_decouverte_reseau_routes(db=db, api=api, get_current_user=lambda: {"role": role["valeur"], "email": "a@b.c"})
    app.include_router(api)
    with TestClient(app) as client:
        yield client, db, role


def test_parcours_complet(appli):
    client, db, role = appli
    import asyncio
    # Une fiche du parc existe déjà pour l'imprimante (MAC connue), sans n° de série
    asyncio.get_event_loop().run_until_complete(db.parc_equipements.insert_one(
        {"id": "f1", "tenant_id": "t1", "adresse_mac": "3C:D9:2B:11:22:33", "modele": "Saisi", "numero_serie": None,
         "numero_inventaire": "PARC-CMC-0001"}))
    cle = {"X-Cle-Loois": "LK-bonne"}
    # Sans clé client : refus ; serveur autorisé par défaut, avec la communauté « public »
    assert client.get("/api/loois/decouverte-reseau/consigne?machine=SRV&type_poste=serveur").status_code == 401
    c = client.get("/api/loois/decouverte-reseau/consigne?machine=SRV&type_poste=serveur", headers=cle).json()
    assert c["lancer"] is True and c["communaute"] == "public"
    # Envoi : une imprimante connue + un appareil nouveau
    r = client.post("/api/loois/decouverte-reseau", headers=cle, json={"machine": "SRV", "appareils": [
        {"ip": "192.168.1.30", "mac": "3C:D9:2B:11:22:33", "categorie": "imprimante",
         "snmp": {"modele": "M404dn", "numero_serie": "VNB3K"}},
        {"ip": "192.168.1.40", "mac": "AA:BB:CC:00:00:09", "categorie": "switch"}]}).json()
    assert r == {"ok": True, "total": 2, "nouveaux": 1, "connus": 1}
    fiche = asyncio.get_event_loop().run_until_complete(db.parc_equipements.find_one({"id": "f1"}))
    assert fiche["numero_serie"] == "VNB3K" and fiche["modele"] == "Saisi"   # saisie à la main conservée
    # Juste après le balayage, la consigne dit « déjà fait »
    assert client.get("/api/loois/decouverte-reseau/consigne?machine=SRV&type_poste=serveur", headers=cle).json()["lancer"] is False
    # Écran d'administration : un appareil à valider
    role["valeur"] = "client"
    assert client.get("/api/admin/equipements/reseau").status_code == 403
    role["valeur"] = "admin"
    liste = client.get("/api/admin/equipements/reseau?statut=a_valider").json()
    assert liste["compteurs"]["a_valider"] == 1 and liste["compteurs"]["connu"] == 1
    nouveau = liste["appareils"][0]
    v = client.post(f"/api/admin/equipements/reseau/{nouveau['id']}/valider", json={"categorie": "switch"}).json()
    assert v["numero_inventaire"].startswith("PARC-LOOIS-")
    cree = asyncio.get_event_loop().run_until_complete(db.parc_equipements.find_one({"id": v["equipement_id"]}))
    assert cree["categorie"] == "Switch" and cree["adresse_mac"] == "AA:BB:CC:00:00:09" and cree["tenant_id"] is None
    # Réglages : communauté jamais réaffichée, « Lancer maintenant »
    e = client.put("/api/admin/equipements/decouverte-reglages", json={"communaute": "Secrete1"}).json()
    assert e["communaute_personnalisee"] is True and "Secrete1" not in str(e)
    client.post("/api/admin/equipements/decouverte-lancer")
    c = client.get("/api/loois/decouverte-reseau/consigne?machine=SRV&type_poste=serveur", headers=cle).json()
    assert c["lancer"] is True and c["communaute"] == "Secrete1"
