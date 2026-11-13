"""Lot 388 — « Vous êtes ici » : pages publiques par lieu, QR, résolution par balise, statistiques, droits administrateur / superviseur.
Lancer : cd backend && python -m pytest tests/test_lot388_lieux_balises.py -q -p no:xdist
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import lieux_balises as lb  # noqa: E402


# ----------------------------------------------------------------- logique pure
def test_codes_et_validations():
    code = lb.nouveau_code()
    assert len(code) == 6 and all(c in lb.ALPHABET_CODE for c in code)
    assert lb.nettoyer_lieu({"nom": " Rayon frais ", "texte": " Bienvenue ", "balise": " ib:U:1:2 "}) == {
        "nom": "Rayon frais", "texte": "Bienvenue", "balise": "ib:U:1:2", "liens": []}
    for mauvais in ({"nom": "a"}, {"nom": "Salle", "balise": "avec espace"}, "pas un dict"):
        with pytest.raises(ValueError):
            lb.nettoyer_lieu(mauvais)


def test_liens_http_seulement():
    assert lb.nettoyer_liens([{"libelle": "Menu", "url": "https://exemple.bf/menu"}]) == [{"libelle": "Menu", "url": "https://exemple.bf/menu"}]
    for dangereux in ("javascript:alert(1)", "ftp://x.y/z", "data:text/html,x", "exemple.bf"):
        with pytest.raises(ValueError):
            lb.nettoyer_liens([{"libelle": "x", "url": dangereux}])
    assert lb.nettoyer_liens([{"libelle": "", "url": ""}]) == []                       # ligne vide ignorée
    assert len(lb.nettoyer_liens([{"url": "https://a.bf/%d" % i} for i in range(30)])) == lb.MAX_LIENS


def test_modification_garde_les_champs_absents():
    ancien = {"nom": "Salle 1", "texte": "Infos", "balise": "mac:AA", "liens": [{"libelle": "L", "url": "https://a.bf"}]}
    assert lb.nettoyer_lieu({"texte": "Nouveau"}, ancien) == {"nom": "Salle 1", "texte": "Nouveau", "balise": "mac:AA", "liens": ancien["liens"]}
    assert lb.nettoyer_lieu({"balise": ""}, ancien)["balise"] is None                    # balise retirée


def test_visites_par_jour_et_purge():
    lieu = {}
    t0 = 1_700_000_000.0
    lb.compter_visite(lieu, "qr", t0)
    lb.compter_visite(lieu, "app", t0)
    lb.compter_visite(lieu, "inconnue", t0)                                            # source inconnue → « qr »
    assert lieu["visites_total"] == 3 and lieu["visites_sources"] == {"qr": 2, "app": 1}
    lb.compter_visite(lieu, "qr", t0 + 40 * 86400)                                     # 40 jours plus tard : l'ancien jour est purgé
    assert list(lieu["visites_jours"]) == [lb.jour_de(t0 + 40 * 86400)] and lieu["visites_total"] == 4
    assert lb.visites_recentes(lieu, 7, t0 + 40 * 86400) == 1


def test_vue_publique_cache_balise_et_stats():
    lieu = {"code": "abc234", "nom": "Rayon", "texte": "T", "balise": "ib:secret", "visites_total": 9, "liens": []}
    vue = lb.vue_publique(lieu, [lieu, {"code": "zzz999", "nom": "Couloir"}])
    assert "balise" not in vue and "visites_total" not in vue and vue["autres"] == [{"code": "zzz999", "nom": "Couloir"}]


def test_trouver_par_balise_sans_casse():
    lieux = [{"code": "a", "balise": "MAC:AA:BB"}, {"code": "b", "balise": None}]
    assert lb.trouver_par_balise(lieux, "mac:aa:bb")["code"] == "a"
    assert lb.trouver_par_balise(lieux, "") is None and lb.trouver_par_balise(lieux, "ib:x") is None


# ----------------------------------------------------------------- routes
def _app():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot388"]
    horloge = {"t": 1_700_000_000.0}
    qui = {"role": "superviseur"}
    app, api = FastAPI(), APIRouter(prefix="/api")

    async def utilisateur():
        return {"role": qui["role"]}
    lb.setup_lieux_balises_routes(db=db, api=api, get_current_user=utilisateur, maintenant=lambda: horloge["t"])
    app.include_router(api)
    return qui, TestClient(app)


def test_parcours_superviseur_et_visiteur():
    qui, c = _app()
    # le superviseur crée deux lieux
    r = c.post("/api/admin/lieux-balises", json={"nom": "Rayon frais", "texte": "Fruits et légumes", "balise": "mac:AA:BB",
                                                  "liens": [{"libelle": "Promos", "url": "https://exemple.bf/promos"}]})
    assert r.status_code == 200
    code = r.json()["code"]
    assert r.json()["adresse"].endswith("/lieu/" + code)
    c.post("/api/admin/lieux-balises", json={"nom": "Couloir 2"})
    # le visiteur (sans compte) ouvre la page, la résolution trouve le lieu, le QR est une image PNG
    qui["role"] = "client"
    page = c.get(f"/api/lieux-balises/{code}").json()
    assert page["nom"] == "Rayon frais" and page["liens"][0]["libelle"] == "Promos" and [a["nom"] for a in page["autres"]] == ["Couloir 2"]
    assert "balise" not in page
    assert c.get("/api/lieux-balises-resolution", params={"balise": "MAC:aa:bb"}).json() == {"code": code, "nom": "Rayon frais"}
    assert c.get("/api/lieux-balises-resolution", params={"balise": "ib:inconnue"}).status_code == 404
    png = c.get(f"/api/lieux-balises/{code}/qr.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    # visites comptées (QR puis application) ; corps absent toléré
    assert c.post(f"/api/lieux-balises/{code}/visite", json={"source": "qr"}).status_code == 200
    assert c.post(f"/api/lieux-balises/{code}/visite", json={"source": "app"}).status_code == 200
    assert c.post(f"/api/lieux-balises/{code}/visite").status_code == 200
    # le visiteur n'accède pas à la gestion ; le superviseur y lit les statistiques
    assert c.get("/api/admin/lieux-balises").status_code == 403
    qui["role"] = "superviseur"
    liste = c.get("/api/admin/lieux-balises").json()
    rayon = next(l for l in liste["lieux"] if l["code"] == code)
    assert rayon["visites_total"] == 3 and rayon["visites_7j"] == 3 and rayon["visites_sources"] == {"qr": 2, "app": 1}
    assert liste["total_visites"] == 3


def test_droits_et_conflits():
    qui, c = _app()
    for role in ("client", "team", "officine"):
        qui["role"] = role
        assert c.post("/api/admin/lieux-balises", json={"nom": "Salle"}).status_code == 403
    qui["role"] = "admin"                                                              # l'administrateur a les mêmes droits
    a = c.post("/api/admin/lieux-balises", json={"nom": "Salle A", "balise": "ib:U:1:1"}).json()
    # une balise ne marque qu'un seul lieu
    assert c.post("/api/admin/lieux-balises", json={"nom": "Salle B", "balise": "IB:u:1:1"}).status_code == 409
    b = c.post("/api/admin/lieux-balises", json={"nom": "Salle B", "balise": "ib:U:1:2"}).json()
    assert c.put(f"/api/admin/lieux-balises/{b['code']}", json={"balise": "ib:U:1:1"}).status_code == 409
    assert c.put(f"/api/admin/lieux-balises/{a['code']}", json={"texte": "Modifié"}).json()["texte"] == "Modifié"   # sa propre balise : pas de conflit
    # validation et suppression
    assert c.post("/api/admin/lieux-balises", json={"nom": "x"}).status_code == 422
    assert c.post("/api/admin/lieux-balises", json={"nom": "Salle C", "liens": [{"url": "javascript:x"}]}).status_code == 422
    assert c.delete(f"/api/admin/lieux-balises/{a['code']}").status_code == 200
    assert c.get(f"/api/lieux-balises/{a['code']}").status_code == 404
    assert c.get("/api/lieux-balises/%3Cscript%3E").status_code == 404                 # code invalide : jamais d'erreur serveur
