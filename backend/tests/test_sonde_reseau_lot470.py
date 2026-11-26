"""Lot 470 — Sonde réseau : statistiques, verdict, rapport HTML et routes (administrateur seul, anti-abus, plafond)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mongomock_motor
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sonde_reseau as sr  # noqa: E402
from routes.sonde_reseau import setup_sonde_reseau_routes  # noqa: E402


def _m(minutes_avant=0, perdus=0, essais=10, lat=80.0, desc=None, poste="PC box"):
    """Mesure fabriquée, datée de `minutes_avant` minutes."""
    le = (datetime.now(timezone.utc) - timedelta(minutes=minutes_avant)).isoformat()
    return {"le": le, "poste": poste, "type": "pc", "essais": essais, "perdus": perdus, "latence_moy_ms": lat,
            "https_ok": 9, "https_total": 9, "debit_desc_mbps": desc, "debit_mont_mbps": None}


def test_resume_perte_et_verdict():
    r = sr.resume([_m(30, perdus=5), _m(15, perdus=4), _m(0, perdus=0)])
    assert r["essais"] == 30 and r["perdus"] == 9 and r["perte_pct"] == 30.0
    assert r["niveau"] == "critique"
    assert sr.resume([_m(0, perdus=0)])["niveau"] == "ok"
    assert sr.resume([_m(0, perdus=1)])["niveau"] == "critique"       # 1 sur 10 = 10 %
    assert sr.verdict(None, None)[0] == "inconnu"
    assert sr.verdict(0.0, 0.9)[0] == "attention"                     # pas de perte mais débit très bas


def test_filtre_periode_et_poste():
    vieux = _m(60 * 24 * 10)                                          # il y a 10 jours
    recent = _m(5)
    autre = _m(5, poste="Téléphone")
    assert sr.filtrer([vieux, recent, autre], 7) == sorted([recent, autre], key=lambda m: m["le"])
    assert sr.filtrer([vieux, recent, autre], 7, "Téléphone") == [autre]


def test_centile_et_nom_de_poste():
    assert sr._centile([1, 2, 3, 4, 100], 95) == 100.0
    assert sr.nom_poste("PC <script>box.1") == "PC scriptbox1"       # caractères dangereux retirés
    assert sr.nom_poste("   ") == "Poste"


def test_rapport_html_autonome_et_echappe():
    html = sr.rapport_html([_m(30, perdus=5, desc=0.9), _m(15, perdus=4, desc=1.2), _m(0, perdus=6, desc=0.8)], 7, "PC <b>x</b>")
    assert "Rapport de la sonde réseau" in html and "Connexion très dégradée" in html
    assert "<polyline" in html                                        # courbes SVG intégrées
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html   # nom du poste échappé
    assert "http://" not in html.replace("http://www.w3.org", "") and "src=" not in html   # aucune ressource externe


def _appli(role="admin"):
    db = mongomock_motor.AsyncMongoMockClient()["test_lot470"]
    api = APIRouter(prefix="/api")

    async def get_current_user():
        return {"id": "u1", "email": "a@test", "role": role}

    setup_sonde_reseau_routes(db=db, api=api, get_current_user=get_current_user)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


CORPS = {"poste": "PC box", "type": "pc", "essais": 10, "perdus": 4, "latence_moy_ms": 83.2, "https_ok": 8, "https_total": 9, "debit_desc_mbps": 0.9}


def test_routes_envoi_lecture_rapport_effacement():
    c = _appli()
    assert c.post("/api/sonde-reseau/mesures", json=CORPS).status_code == 200
    lu = c.get("/api/sonde-reseau/mesures?jours=7").json()
    assert lu["resume"]["perte_pct"] == 40.0 and lu["postes"] == ["PC box"] and lu["mesures"][0]["perte_pct"] == 40.0
    r = c.get("/api/sonde-reseau/rapport?jours=7")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and "Rapport de la sonde réseau" in r.text
    assert c.delete("/api/sonde-reseau/mesures").status_code == 200
    assert c.get("/api/sonde-reseau/mesures").json()["resume"]["mesures"] == 0


def test_anti_abus_incoherence_et_droits():
    c = _appli()
    assert c.post("/api/sonde-reseau/mesures", json=CORPS).status_code == 200
    assert c.post("/api/sonde-reseau/mesures", json=CORPS).status_code == 429          # 2e envoi immédiat refusé
    assert c.post("/api/sonde-reseau/mesures", json={**CORPS, "poste": "Autre", "perdus": 11}).status_code == 422   # plus de pertes que d'essais
    assert c.post("/api/sonde-reseau/mesures", json={**CORPS, "poste": "Autre", "debit_desc_mbps": -5}).status_code == 422
    assert _appli("client").get("/api/sonde-reseau/mesures").status_code == 403         # réservé à l'administrateur


def test_plafond_des_mesures():
    c = _appli()
    old = sr.MAX_MESURES
    sr.MAX_MESURES = 3
    try:
        for i in range(5):
            sr.DELAI_MIN_S = 0
            assert c.post("/api/sonde-reseau/mesures", json={**CORPS, "poste": f"P{i}"}).status_code == 200
        assert c.get("/api/sonde-reseau/mesures").json()["total_en_base"] == 3
    finally:
        sr.MAX_MESURES = old
        sr.DELAI_MIN_S = 50
