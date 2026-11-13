"""Lot 387 — présence et parcours par balises Bluetooth : zone par signal le plus fort, anti-rebond, sorties, contrat v1, vie privée.
Lancer : cd backend && python -m pytest tests/test_lot387_presence_balises.py -q -p no:xdist
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import presence_balises as pb  # noqa: E402


# ----------------------------------------------------------------- logique pure
def test_validations():
    assert pb.badge_valide(" ib:UUID:1:2 ") == "ib:UUID:1:2"
    for mauvais in ("ab", "x" * 81, "avec espace", "", None, "<script>"):
        assert pb.badge_valide(mauvais) is None
    assert pb.rssi_valide("-67") == -67 and pb.rssi_valide(5) is None and pb.rssi_valide("fort") is None and pb.rssi_valide(-200) is None


def test_zone_la_plus_forte_et_expiration():
    recepteurs = {"r1": "A", "r2": "B"}
    vus = {"r1": {"t": 100, "rssi": -80}, "r2": {"t": 100, "rssi": -60}}
    assert pb.zone_courante(vus, recepteurs, 110, 60) == "B"                       # le plus fort gagne
    assert pb.zone_courante(vus, recepteurs, 200, 60) is None                      # tout est périmé : absent
    vus["r2"]["t"] = 10
    assert pb.zone_courante(vus, recepteurs, 110, 60) == "A"                       # B périmé : A reste
    assert pb.zone_courante({"inconnu": {"t": 100, "rssi": -50}}, recepteurs, 110, 60) is None   # récepteur supprimé : ignoré


def test_anti_rebond_entre_zones_voisines():
    recepteurs = {"r1": "A", "r2": "B"}
    vus = {"r1": {"t": 100, "rssi": -70}, "r2": {"t": 100, "rssi": -66}}           # B plus fort de 4 dB seulement
    assert pb.zone_courante(vus, recepteurs, 105, 60, zone_actuelle="A") == "A"    # marge de 6 dB non atteinte : on reste
    vus["r2"]["rssi"] = -60                                                       # B plus fort de 10 dB
    assert pb.zone_courante(vus, recepteurs, 105, 60, zone_actuelle="A") == "B"
    vus["r1"]["t"] = 10                                                           # A ne l'entend plus : on change sans marge
    vus["r2"]["rssi"] = -69
    assert pb.zone_courante(vus, recepteurs, 105, 60, zone_actuelle="A") == "B"


def _site():
    return {"id": "s1", "nom": "Siège", "zones": [{"id": "A", "nom": "Accueil"}, {"id": "B", "nom": "Salle 1"}],
            "badges": [{"id": "ib:aaa:1:1", "libelle": "Visiteur 1"}], "delai_absence_s": 60,
            "recepteurs": [{"id": "r1", "nom": "Accueil", "zone_id": "A", "cle_hash": "x"}, {"id": "r2", "nom": "Salle", "zone_id": "B", "cle_hash": "y"}],
            "evenements": [], "etat": {"badges": {}}}


def test_entree_changement_de_zone_et_sortie():
    site = _site()
    r = pb.appliquer_detections(site, "r1", [{"badge": "ib:aaa:1:1", "rssi": -60}], 1000)
    assert r["acceptees"] == 1 and [(e["de"], e["vers"]) for e in r["evenements"]] == [(None, "A")]          # entrée à l'accueil
    r = pb.appliquer_detections(site, "r2", [{"badge": "ib:aaa:1:1", "rssi": -50}], 1010)
    assert [(e["de"], e["vers"]) for e in r["evenements"]] == [("A", "B")]                                      # passage en salle (10 dB de mieux)
    assert pb.balayer(site, 1050) == []                                                                          # encore là
    sorties = pb.balayer(site, 1200)                                                                              # plus rien depuis > 60 s
    assert [(e["de"], e["vers"]) for e in sorties] == [("B", None)]
    v = pb.vue_etat(site, 1200)
    assert [z["presents"] for z in v["zones"]] == [[], []] and v["absents"][0]["libelle"] == "Visiteur 1"


def test_detections_invalides_et_badges_inconnus_plafonnes():
    site = _site()
    r = pb.appliquer_detections(site, "r1", [{"badge": "x", "rssi": -50}, {"badge": "ib:bbb:1:1", "rssi": 3}, {"badge": "ib:ccc:1:1", "rssi": -70}, "n'importe quoi"], 100)
    assert (r["acceptees"], r["ignorees"]) == (1, 3)
    assert pb.vue_etat(site, 101)["inconnus"][0]["badge"] == "ib:ccc:1:1"
    gros = [{"badge": f"inconnu-{i:04d}", "rssi": -60} for i in range(200)]
    for k in range(3):
        pb.appliquer_detections(site, "r1", gros, 200 + k)
    assert len(site["etat"]["badges"]) <= pb.MAX_INCONNUS + 1                                                      # pas de croissance illimitée


def test_conservation_des_evenements():
    anciens = [{"t": 1000, "badge": "b1", "de": None, "vers": "A"}, {"t": 1000 + 40 * 86400, "badge": "b1", "de": "A", "vers": None}]
    gardes = pb.purger_evenements(anciens, 1000 + 41 * 86400, 30)
    assert [e["t"] for e in gardes] == [1000 + 40 * 86400]


# ----------------------------------------------------------------- routes (contrat v1)
def _app():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot387"]
    horloge = {"t": 1_000_000.0}
    qui = {"role": "admin"}
    app, api = FastAPI(), APIRouter(prefix="/api")

    async def utilisateur():
        return {"role": qui["role"]}
    pb.setup_presence_balises_routes(db=db, api=api, get_current_user=utilisateur, maintenant=lambda: horloge["t"])
    app.include_router(api)
    return db, horloge, qui, TestClient(app)


def test_parcours_complet_du_contrat():
    db, horloge, qui, c = _app()
    site = c.post("/api/admin/presence-balises/sites", json={"nom": "Siège client"}).json()
    sid = site["id"]
    cfg = c.put(f"/api/admin/presence-balises/sites/{sid}", json={"zones": [{"nom": "Accueil"}, {"nom": "Salle 1"}], "badges": [{"id": "ib:aaa:1:1", "libelle": "Visiteur 1"}]}).json()
    za, zb = cfg["zones"][0]["id"], cfg["zones"][1]["id"]
    r1 = c.post(f"/api/admin/presence-balises/sites/{sid}/recepteurs", json={"nom": "Tel accueil", "zone_id": za}).json()
    r2 = c.post(f"/api/admin/presence-balises/sites/{sid}/recepteurs", json={"nom": "Tel salle", "zone_id": zb}).json()
    assert r1["cle"] and r1["identifiant"] == f"{sid}:{r1['id']}"
    # La clé n'est jamais relue ensuite
    assert "cle" not in str(c.get("/api/admin/presence-balises/sites").json())

    def envoyer(r, badge, rssi, cle=None):
        return c.post("/api/presence-balises/v1/detections", json={"detections": [{"badge": badge, "rssi": rssi}]},
                      headers={"X-Recepteur": r["identifiant"], "X-Cle": cle or r["cle"]})
    assert envoyer(r1, "ib:aaa:1:1", -60, cle="mauvaise").status_code == 401
    assert c.post("/api/presence-balises/v1/detections", json={"detections": []}, headers={"X-Recepteur": "zzz:zzz", "X-Cle": "x"}).status_code == 401
    assert c.post("/api/presence-balises/v1/detections", json={"detections": "pas une liste"}, headers={"X-Recepteur": r1["identifiant"], "X-Cle": r1["cle"]}).status_code == 422
    assert envoyer(r1, "ib:aaa:1:1", -60).json() == {"acceptees": 1, "ignorees": 0}
    etat = c.get(f"/api/admin/presence-balises/sites/{sid}/etat").json()
    assert [p["libelle"] for p in etat["zones"][0]["presents"]] == ["Visiteur 1"] and etat["zones"][1]["presents"] == []
    horloge["t"] += 10
    envoyer(r2, "ib:aaa:1:1", -45)                                                                     # le visiteur passe en salle
    etat = c.get(f"/api/admin/presence-balises/sites/{sid}/etat").json()
    assert etat["zones"][1]["presents"][0]["libelle"] == "Visiteur 1" and etat["zones"][0]["presents"] == []
    envoyer(r2, "ib:zzz:9:9", -70)                                                                     # un badge non enregistré apparaît à part
    assert c.get(f"/api/admin/presence-balises/sites/{sid}/etat").json()["inconnus"][0]["badge"] == "ib:zzz:9:9"
    horloge["t"] += 300                                                                                # plus aucun signal : sortie détectée à la lecture
    etat = c.get(f"/api/admin/presence-balises/sites/{sid}/etat").json()
    assert etat["zones"][1]["presents"] == [] and etat["absents"][0]["libelle"] == "Visiteur 1"
    trajet = c.get(f"/api/admin/presence-balises/sites/{sid}/parcours", params={"badge": "ib:aaa:1:1"}).json()["passages"]
    assert [(p["de"], p["vers"]) for p in trajet] == [("Salle 1", None), ("Accueil", "Salle 1"), (None, "Accueil")]   # du plus récent au plus ancien


def test_droits_et_configuration():
    db, horloge, qui, c = _app()
    sid = c.post("/api/admin/presence-balises/sites", json={"nom": "S"}).json()["id"]
    zid = c.put(f"/api/admin/presence-balises/sites/{sid}", json={"zones": [{"nom": "Z"}]}).json()["zones"][0]["id"]
    rec = c.post(f"/api/admin/presence-balises/sites/{sid}/recepteurs", json={"nom": "R", "zone_id": zid}).json()
    assert c.put(f"/api/admin/presence-balises/sites/{sid}", json={"zones": []}).status_code == 422      # zone encore utilisée
    assert c.put(f"/api/admin/presence-balises/sites/{sid}", json={"delai_absence_s": 5}).status_code == 422
    assert c.put(f"/api/admin/presence-balises/sites/{sid}", json={"badges": [{"id": "ab"}]}).status_code == 422
    assert c.put(f"/api/admin/presence-balises/sites/{sid}", json={"badges": [{"id": "ib:a:1:1"}, {"id": "ib:a:1:1"}]}).status_code == 422
    assert c.post(f"/api/admin/presence-balises/sites/{sid}/recepteurs", json={"nom": "R", "zone_id": "inconnue"}).status_code == 422
    qui["role"] = "client"
    for chemin in (f"/api/admin/presence-balises/sites", f"/api/admin/presence-balises/sites/{sid}/etat"):
        assert c.get(chemin).status_code == 403
    qui["role"] = "admin"
    assert c.delete(f"/api/admin/presence-balises/sites/{sid}/recepteurs/{rec['id']}").status_code == 200
    assert c.delete(f"/api/admin/presence-balises/sites/{sid}").status_code == 200
    assert c.get(f"/api/admin/presence-balises/sites/{sid}/etat").status_code == 404
