"""Lot 66 — Inventaire des postes : objet « inventaire » du signal de présence (nettoyage, taille),
dernier inventaire conservé, détails d'un poste (admin), fiche « Parc informatique » créée puis
complétée sans écraser la saisie à la main, affectation de la fiche à un compte client.
MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot66_inventaire_postes.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import Request  # noqa: E402  (au niveau du module : annotation résolue malgré « from __future__ »)

import routes.parc_informatique as pi  # noqa: E402
import routes.versions_deployees as vd  # noqa: E402

UTILISATEURS = {"admin": {"id": "admin", "role": "admin", "full_name": "Admin SAWALI"},
                "phl": {"id": "phl", "role": "pharmacien", "company": "Pharmacie PHL", "client_code": "PHL"}}


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


def client(db):
    """Application FastAPI minimale : routes du lot 65/66 et du parc (lot 47), utilisateur choisi par en-tête."""
    from fastapi import APIRouter, FastAPI, HTTPException
    from fastapi.testclient import TestClient

    async def utilisateur(request: Request):
        u = UTILISATEURS.get(request.headers.get("X-User", "admin"))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    vd.setup_versions_deployees_routes(db=db, api=api, get_current_user=utilisateur)
    pi.attach_parc_routes(api=api, db=db, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    lancer(db.users.insert_many([dict(u) for u in UTILISATEURS.values()]))
    return TestClient(app)


def inventaire(mac="00-15-5D-0A-0B-0C", ip="192.168.1.20", systeme="Windows 11 Pro", type_poste="poste"):
    """Inventaire tel que l'envoie Loois (InventairePoste.Construire)."""
    return {
        "collecte_le": "2026-10-06T12:00:00Z", "type_poste": type_poste,
        "systeme": {"nom": systeme, "version": "23H2 (build 22631)", "architecture": "X64",
                    "fabricant": "Dell Inc.", "modele": "OptiPlex 7070", "demarre_depuis_min": 180},
        "processeur": {"nom": "Intel(R) Core(TM) i5-8500", "coeurs_logiques": 6},
        "memoire": {"totale_go": 8.0, "disponible_go": 2.0, "utilisee_pct": 75},
        "disques": [{"lettre": "C:", "format": "NTFS", "total_go": 237.9, "libre_go": 12.4, "libre_pct": 5}],
        "reseau": [{"nom": "Wi-Fi", "mac": "AA:BB:CC:00:00:01", "ipv4": ["169.254.3.4"], "passerelles": []},
                   {"nom": "Ethernet", "mac": mac, "ipv4": [ip], "passerelles": ["192.168.1.1"], "dns": ["8.8.8.8"]}],
        "processus_total": 2,
        "processus": [{"nom": "Loois", "pid": 1200, "memoire_mo": 180.5}, {"nom": "explorer", "pid": 4, "memoire_mo": 90.0}],
    }


def signal(machine="PC-ACCUEIL", application="Loois", inv=None, site="Clinique X"):
    """Corps du signal de présence (avec inventaire facultatif)."""
    corps = {"application": application, "version": "1.2610.610.44", "machine": machine,
             "utilisateur": "secretariat", "site": site}
    if inv is not None:
        corps["inventaire"] = inv
    return corps


# ---------------------------------------------------------------------------
# Logique pure
# ---------------------------------------------------------------------------
def test_nettoyage_de_l_inventaire():
    """Clés dangereuses retirées, textes et listes bornés, types inattendus neutralisés, taille plafonnée."""
    propre = vd.nettoyer_inventaire({"$where": "x", "a.b": 1, "ok": "t" * 1000, "liste": list(range(1000)),
                                     "n": float("inf"), "profond": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}})
    assert "$where" not in propre and "a.b" not in propre
    assert len(propre["ok"]) == 300 and len(propre["liste"]) == 300 and propre["n"] is None
    assert propre["profond"]["a"]["b"]["c"]["d"] is None          # au-delà de 5 niveaux
    assert vd.nettoyer_inventaire(None) is None and vd.nettoyer_inventaire([1, 2]) is None
    assert vd.nettoyer_inventaire({"gros": "x" * (vd.MAX_INVENTAIRE_OCTETS + 10)}) is None


def test_carte_principale_et_champs_auto():
    """La carte avec IPv4 + passerelle passe d'abord ; APIPA ignorée ; catégorie selon le type."""
    cartes = vd.cartes_principales(inventaire())
    assert cartes[0]["mac"] == "00:15:5D:0A:0B:0C" and cartes[0]["ip"] == "192.168.1.20"
    assert cartes[1]["ip"] is None                               # 169.254.x.x ignorée
    auto = vd.champs_parc_auto(signal(), inventaire(type_poste="serveur"), "2026-10-06T12:00:00+00:00")
    assert auto["categorie"] == "Serveur"
    assert auto["champs"]["systeme_exploitation"] == "Windows 11 Pro 23H2 (build 22631)"
    assert auto["champs"]["nom_hote"] == "PC-ACCUEIL" and auto["loois"]["ram_go"] == 8.0


def test_fusion_ne_touche_pas_la_saisie_manuelle():
    """Champ vide ou encore égal à la valeur de Loois : mis à jour ; modifié à la main : conservé."""
    existant = {"modele": "OptiPlex 7070", "site": "Bloc B (saisi)", "adresse_ip": None,
                "loois_auto": {"modele": "OptiPlex 7070", "site": "Clinique X"}}
    a_ecrire = vd.fusion_parc(existant, {"modele": "OptiPlex 7080", "site": "Clinique X", "adresse_ip": "192.168.1.30"})
    assert a_ecrire["modele"] == "OptiPlex 7080" and a_ecrire["adresse_ip"] == "192.168.1.30"
    assert "site" not in a_ecrire                                 # saisi à la main : jamais écrasé
    assert a_ecrire["loois_auto"]["modele"] == "OptiPlex 7080"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def test_inventaire_conserve_et_details_du_poste():
    """L'inventaire est gardé quand un signal léger arrive ; les détails réunissent tous les composants."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot66a"]
    c = client(db)
    r = c.post("/api/presence-logiciel", json=signal(inv=inventaire()))
    assert r.status_code == 200 and r.json()["inventaire"] is True
    # Signal léger d'un autre composant de la même machine : l'inventaire reste
    assert c.post("/api/presence-logiciel", json=signal(application="LooisSyncService")).json()["inventaire"] is False
    # Inventaire trop gros : ignoré, signal accepté
    r = c.post("/api/presence-logiciel", json=signal(inv={"gros": "x" * (vd.MAX_INVENTAIRE_OCTETS + 1)}))
    assert r.status_code == 200 and r.json()["inventaire"] is False

    d = c.get("/api/admin/versions-deployees/poste-details", params={"machine": "pc-accueil", "application": "LooisSyncService"})
    assert d.status_code == 200
    d = d.json()
    assert [x["application"] for x in d["composants"]] == ["LooisSyncService", "Loois"]   # application demandée d'abord
    assert d["inventaire"]["processeur"]["coeurs_logiques"] == 6 and d["inventaire_le"]
    assert d["equipement"]["numero_inventaire"] == "PARC-LOOIS-0001" and d["equipement"]["a_affecter"] is True
    assert "adresse_ip" not in d["composants"][0]
    # La liste générale n'embarque pas l'inventaire (page légère)
    assert "inventaire" not in c.get("/api/admin/versions-deployees").json()["logiciels"][0]["postes"][0]
    # Droits et poste inconnu
    assert c.get("/api/admin/versions-deployees/poste-details", params={"machine": "PC-ACCUEIL"},
                 headers={"X-User": "phl"}).status_code == 403
    assert c.get("/api/admin/versions-deployees/poste-details", params={"machine": "INCONNU"}).status_code == 404


def test_fiche_du_parc_creee_puis_completee_et_affectee():
    """Fiche créée au premier inventaire, mise à jour ensuite sans écraser la saisie ; affectation au client."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot66b"]
    c = client(db)
    c.post("/api/presence-logiciel", json=signal(inv=inventaire()))
    [e] = lancer(db.parc_equipements.find({}, {"_id": 0}).to_list(10))
    assert e["categorie"] == "PC de bureau" and e["tenant_id"] is None and e["source"] == "loois"
    assert e["adresse_mac"] == "00:15:5D:0A:0B:0C" and e["adresse_ip"] == "192.168.1.20"
    assert e["fabricant"] == "Dell Inc." and e["loois"]["disques"][0]["libre_pct"] == 5

    # Visible dans « Parc informatique » (Admin, tous les clients)
    liste = c.get("/api/me/parc/equipements").json()
    assert [x["numero_inventaire"] for x in liste["equipements"]] == ["PARC-LOOIS-0001"]
    # Une intervention exige d'abord l'affectation à un client
    r = c.post("/api/me/parc/interventions", json={"equipement_ids": [e["id"]], "type_intervention": "audit"})
    assert r.status_code == 400 and "Affectez" in r.json()["detail"]

    # Le propriétaire saisit le lieu et des notes, puis affecte la fiche au client PHL
    formulaire = {k: e.get(k) for k in ("categorie", "fabricant", "modele", "adresse_ip", "adresse_mac", "nom_hote",
                                        "systeme_exploitation")}
    formulaire.update({"site": "Bloc B", "notes": "Poste de l'accueil", "compte_client_id": "phl"})
    r = c.put(f"/api/me/parc/equipements/{e['id']}", json=formulaire)
    assert r.status_code == 200 and r.json()["tenant_id"] == "phl" and r.json()["client_nom"] == "Pharmacie PHL"

    # Nouvel inventaire : IP changée (mise à jour), site / notes / client conservés, pas de doublon
    c.post("/api/presence-logiciel", json=signal(inv=inventaire(ip="192.168.1.45")))
    [e] = lancer(db.parc_equipements.find({}, {"_id": 0}).to_list(10))
    assert e["adresse_ip"] == "192.168.1.45"
    assert e["site"] == "Bloc B" and e["notes"] == "Poste de l'accueil" and e["tenant_id"] == "phl"
    # Le client voit désormais la fiche dans son parc
    assert c.get("/api/me/parc/equipements", headers={"X-User": "phl"}).json()["total"] == 1


def test_fiche_existante_liee_par_adresse_mac():
    """Un équipement déjà saisi à la main avec la même adresse MAC est lié (pas de doublon)."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot66c"]
    c = client(db)
    r = c.post("/api/me/parc/equipements", json={"categorie": "PC portable", "adresse_mac": "00155D0A0B0C",
                                                 "compte_client_id": "phl", "modele": "Latitude (saisi)"})
    assert r.status_code == 200
    c.post("/api/presence-logiciel", json=signal(inv=inventaire()))
    [e] = lancer(db.parc_equipements.find({}, {"_id": 0}).to_list(10))
    assert e["loois_machine"] == "PC-ACCUEIL" and e["categorie"] == "PC portable"
    assert e["modele"] == "Latitude (saisi)" and e["nom_hote"] == "PC-ACCUEIL"   # vide → rempli ; saisi → conservé
