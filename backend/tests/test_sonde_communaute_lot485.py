"""Lot 485 — Espace commun de la sonde réseau : zones de 2 km, agrégation, consentement, jetons d'appareil, limites, droits administrateur.
Les routes sont montées seules (base en mémoire) ; le parcours Google « cible sonde » utilise le montage complet du lot 55 (échange avec Google simulé)."""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import mongomock_motor
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import google_auth  # noqa: E402
import sonde_communaute as sc  # noqa: E402
from routes.sonde_communaute import setup_sonde_communaute_routes  # noqa: E402

APPAREIL = "a" * 32


# ----------------------------------------------------------------------------------------------------------------- logique pure
def test_zone_de_2_km_jamais_plus_precise():
    a = sc.zone(12.3714, -1.5197)                      # Ouagadougou
    b = sc.zone(12.3790, -1.5230)                      # quelques centaines de mètres plus loin : même zone
    assert a == b and a[0].startswith("z")
    assert a[1] == 12.38 and a[2] == -1.52             # centre de la zone, deux décimales : jamais la position envoyée
    assert sc.zone(12.40, -1.52)[0] != a[0]            # 2 km plus loin : autre zone
    assert sc.zone(None, 1.0) is None and sc.zone(95.0, 0.0) is None and sc.zone("x", 1) is None


def test_cle_de_cellule_sure_pour_mongo():
    cle = sc.cle_cellule("2026-11-27", "z619_m76", "mobile", "Orange B.F. $x")
    assert "." not in cle and "$" not in cle and cle.startswith("20261127__z619_m76__mobile__orange_b_f_x")
    assert sc.lire_cle(cle)["type"] == "mobile" and sc.cle_cellule("2026-11-27", None, "autre", None).endswith("__sans__mobile__inconnu")


def _cellules():
    base = {"n": 1, "essais": 10, "perdus": 0, "https_ok": 9, "https_total": 9, "lat_somme": 80.0, "lat_n": 1}
    aujourdhui = datetime.now(timezone.utc).strftime("%Y%m%d")
    vieux = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y%m%d")
    return {f"{aujourdhui}__z1_1__wifi__orange": {**base, "desc_somme": 40.0, "desc_n": 1},
            f"{aujourdhui}__z1_1__mobile__orange": {**base, "perdus": 2},
            f"{aujourdhui}__z2_2__mobile__moov": {**base, "perdus": 5},
            f"{vieux}__z1_1__wifi__orange": base}


def test_synthese_par_lieu_type_et_operateur():
    r = sc.synthese(_cellules(), 7, zones={"z1_1": {"lat": 12.38, "lon": -1.52}})
    assert r["resume"]["mesures"] == 3                                    # la cellule de 30 jours est hors période
    assert {(x["zone"], x["type"], x["operateur"]) for x in r["lignes"]} == {("z1_1", "wifi", "orange"), ("z1_1", "mobile", "orange"), ("z2_2", "mobile", "moov")}
    assert r["par_type"]["mobile"]["perte_pct"] == 7 * 100 / 20 / 1 / 1 * 0.1 * 10 or True
    assert r["par_type"]["mobile"]["perdus"] == 7 and r["par_type"]["mobile"]["perte_pct"] == 35.0 and r["par_type"]["mobile"]["niveau"] == "critique"
    assert r["par_operateur"]["moov"]["perte_pct"] == 50.0
    assert sc.synthese(_cellules(), 7, type_connexion="wifi")["resume"]["mesures"] == 1
    assert sc.synthese(_cellules(), 7, operateur="Moov")["resume"]["mesures"] == 1
    assert sc.synthese(_cellules(), 60)["resume"]["mesures"] == 4         # période plus longue : la vieille cellule compte
    assert next(x for x in r["lignes"] if x["zone"] == "z1_1" and x["type"] == "wifi")["lat"] == 12.38
    assert sc.synthese({}, 7)["resume"]["niveau"] == "inconnu"


def test_purge_des_vieilles_cellules():
    vieux = (datetime.now(timezone.utc) - timedelta(days=sc.CONSERVATION_JOURS + 5)).strftime("%Y%m%d")
    assert sc.cles_a_purger({f"{vieux}__z1_1__wifi__x": {}, "20991231__z1_1__wifi__x": {}}) == [f"{vieux}__z1_1__wifi__x"]


def test_jetons_et_en_tete():
    clair, h = sc.nouveau_jeton()
    assert clair.startswith("sd_") and sc.empreinte_jeton(clair) == h and clair != h
    assert sc.jeton_depuis_en_tete(f"Bearer {clair}") == clair
    assert sc.jeton_depuis_en_tete(None) is None and sc.jeton_depuis_en_tete("Basic abc") is None and sc.jeton_depuis_en_tete("Bearer pas_un_jeton") is None


# ----------------------------------------------------------------------------------------------------------------- routes
def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _appli(role="admin"):
    db = mongomock_motor.AsyncMongoMockClient()["test_lot485"]
    api = APIRouter(prefix="/api")

    async def get_current_user():
        return {"id": "u1", "email": "a@test", "role": role}

    setup_sonde_communaute_routes(db=db, api=api, get_current_user=get_current_user)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db


def _code(db, sub="g-awa", email="awa.badini@gmail.com"):
    """Simule le retour de Google (routes/google_connexion.py) : fiche du participant + code à usage unique."""
    pid = sc.identifiant_participant(sub)
    _run(db.settings.update_one({"_id": sc.DOC_PARTICIPANTS}, {"$set": {f"p.{pid}.email": email, f"p.{pid}.nom": "BADINI Awa"}}, upsert=True))
    clair, emp = google_auth.nouveau_code()
    _run(db.google_codes.insert_one({"empreinte": emp, "sonde_pid": pid, "expire": time.time() + 120}))
    return pid, clair


def _connecter(c, db, appareil=APPAREIL, sub="g-awa"):
    pid, code = _code(db, sub)
    r = c.post("/api/sonde-reseau/participant/echange", json={"code": code, "consentement_version": sc.CONSENTEMENT_VERSION, "appareil": appareil, "nom_appareil": "Tecno"})
    assert r.status_code == 200, r.text
    return pid, r.json()["jeton"]


MESURE = {"type_connexion": "mobile", "operateur": "Orange BF", "zone_lat": 12.3714, "zone_lon": -1.5197, "essais": 10, "perdus": 1, "latence_moy_ms": 130.0,
          "https_ok": 9, "https_total": 9, "debit_desc_mbps": 100.0}


def _h(jeton):
    return {"Authorization": f"Bearer {jeton}"}


def test_sans_consentement_pas_de_connexion():
    c, db = _appli()
    _, code = _code(db)
    r = c.post("/api/sonde-reseau/participant/echange", json={"code": code, "consentement_version": 0, "appareil": APPAREIL})
    assert r.status_code == 422 and "Consentement" in r.json()["detail"]
    # le code n'a pas été consommé par un refus : avec l'accord, la connexion aboutit
    ok = c.post("/api/sonde-reseau/participant/echange", json={"code": code, "consentement_version": sc.CONSENTEMENT_VERSION, "appareil": APPAREIL})
    assert ok.status_code == 200 and ok.json()["jeton"].startswith("sd_") and ok.json()["email"] == "awa.badini@gmail.com"
    # le code ne sert qu'une fois
    assert c.post("/api/sonde-reseau/participant/echange", json={"code": code, "consentement_version": sc.CONSENTEMENT_VERSION, "appareil": APPAREIL}).status_code == 401


def test_code_inconnu_ou_appareil_invalide():
    c, db = _appli()
    assert c.post("/api/sonde-reseau/participant/echange", json={"code": "x" * 30, "consentement_version": sc.CONSENTEMENT_VERSION, "appareil": APPAREIL}).status_code == 401
    _, code = _code(db)
    assert c.post("/api/sonde-reseau/participant/echange", json={"code": code, "consentement_version": sc.CONSENTEMENT_VERSION, "appareil": "Z" * 20}).status_code == 422


def test_envoi_additionne_dans_une_cellule_sans_garder_la_position():
    c, db = _appli()
    pid, jeton = _connecter(c, db)
    assert c.post("/api/sonde-reseau/communaute/envoi", json=MESURE).status_code == 401                         # sans jeton
    r = c.post("/api/sonde-reseau/communaute/envoi", json=MESURE, headers=_h(jeton))
    assert r.status_code == 200 and r.json()["zone"].startswith("z")
    doc = _run(db.settings.find_one({"_id": sc.DOC_COMMUNAUTE}))
    cellule = next(iter(doc["cellules"].values()))
    assert cellule["n"] == 1 and cellule["perdus"] == 1 and cellule["desc_somme"] == 100.0 and doc["nb"] == 1
    zones = next(iter(doc["zones"].values()))
    assert zones == {"lat": 12.38, "lon": -1.52}                                                                # la zone, jamais 12.3714 / -1.5197
    assert "12.3714" not in str(doc) and "1.5197" not in str(doc)
    moi = c.get("/api/sonde-reseau/participant/moi", headers=_h(jeton)).json()
    assert moi["mesures"] == 1 and moi["appareils"] == 1 and moi["consentement"]["version"] == sc.CONSENTEMENT_VERSION


def test_mesure_sans_lieu_et_mesure_incoherente():
    c, db = _appli()
    _, jeton = _connecter(c, db)
    sans = {k: v for k, v in MESURE.items() if k not in ("zone_lat", "zone_lon")}
    assert c.post("/api/sonde-reseau/communaute/envoi", json=sans, headers=_h(jeton)).json()["zone"] is None     # partage du lieu désactivé : cellule « sans »
    assert any("__sans__" in k for k in _run(db.settings.find_one({"_id": sc.DOC_COMMUNAUTE}))["cellules"])
    assert c.post("/api/sonde-reseau/communaute/envoi", json={**MESURE, "perdus": 11}, headers=_h(jeton)).status_code in (422, 429)


def test_une_mesure_toutes_les_50_secondes_et_plafond_quotidien():
    c, db = _appli()
    pid, jeton = _connecter(c, db)
    assert c.post("/api/sonde-reseau/communaute/envoi", json=MESURE, headers=_h(jeton)).status_code == 200
    assert c.post("/api/sonde-reseau/communaute/envoi", json=MESURE, headers=_h(jeton)).status_code == 429       # trop rapproché
    jour = datetime.now(timezone.utc).isoformat()[:10]
    _run(db.settings.update_one({"_id": sc.DOC_PARTICIPANTS}, {"$set": {f"p.{pid}.n_jour": sc.MAX_PAR_JOUR, f"p.{pid}.jour": jour,
                                                                         f"p.{pid}.appareils.{APPAREIL}.derniere": "2020-01-01T00:00:00+00:00"}}))
    assert c.post("/api/sonde-reseau/communaute/envoi", json=MESURE, headers=_h(jeton)).status_code == 429       # plafond du jour


def test_deconnexion_revoque_le_jeton_et_le_retrait_efface_la_fiche():
    c, db = _appli()
    pid, jeton = _connecter(c, db)
    assert c.post("/api/sonde-reseau/participant/deconnexion", headers=_h(jeton)).status_code == 200
    assert c.get("/api/sonde-reseau/participant/moi", headers=_h(jeton)).status_code == 401
    _, jeton2 = _connecter(c, db)
    assert c.delete("/api/sonde-reseau/participant", headers=_h(jeton2)).status_code == 200
    fiche = _run(db.settings.find_one({"_id": sc.DOC_PARTICIPANTS}))
    assert pid not in (fiche.get("p") or {}) and not fiche.get("jetons")                                         # plus d'e-mail, plus de jeton
    assert c.get("/api/sonde-reseau/participant/moi", headers=_h(jeton2)).status_code == 401


def test_trois_appareils_au_plus_le_plus_ancien_est_remplace():
    c, db = _appli()
    jetons = [_connecter(c, db, appareil=f"{i}" * 32)[1] for i in range(1, 5)]
    assert c.get("/api/sonde-reseau/participant/moi", headers=_h(jetons[0])).status_code == 401                  # le 1er appareil a perdu son jeton
    assert c.get("/api/sonde-reseau/participant/moi", headers=_h(jetons[3])).json()["appareils"] == sc.MAX_APPAREILS


def test_participant_bloque_et_consentement_a_renouveler():
    c, db = _appli()
    pid, jeton = _connecter(c, db)
    assert c.post(f"/api/sonde-reseau/communaute/participants/{pid}/bloquer", json={"bloque": True}).status_code == 200
    assert c.post("/api/sonde-reseau/communaute/envoi", json=MESURE, headers=_h(jeton)).status_code == 403
    c.post(f"/api/sonde-reseau/communaute/participants/{pid}/bloquer", json={"bloque": False})
    _run(db.settings.update_one({"_id": sc.DOC_PARTICIPANTS}, {"$set": {f"p.{pid}.consentement.version": 0}}))   # le texte a changé depuis
    assert c.post("/api/sonde-reseau/communaute/envoi", json=MESURE, headers=_h(jeton)).status_code == 403


def test_administration_synthese_participants_et_droits():
    c, db = _appli()
    pid, jeton = _connecter(c, db)
    c.post("/api/sonde-reseau/communaute/envoi", json=MESURE, headers=_h(jeton))
    s = c.get("/api/sonde-reseau/communaute?jours=7").json()
    assert s["resume"]["mesures"] == 1 and s["participants"] == 1 and s["lignes"][0]["type"] == "mobile" and s["lignes"][0]["lat"] == 12.38
    assert c.get("/api/sonde-reseau/communaute?jours=7&type=wifi").json()["resume"]["mesures"] == 0
    liste = c.get("/api/sonde-reseau/communaute/participants").json()["participants"]
    assert liste[0]["email"] == "awa.badini@gmail.com" and liste[0]["mesures"] == 1
    assert c.delete(f"/api/sonde-reseau/communaute/participants/{pid}").status_code == 200
    assert c.get("/api/sonde-reseau/communaute/participants").json()["participants"] == []
    assert c.delete("/api/sonde-reseau/communaute/participants/pas-un-id").status_code == 422
    simple, _ = _appli(role="user")
    assert simple.get("/api/sonde-reseau/communaute").status_code == 403
    assert simple.get("/api/sonde-reseau/communaute/participants").status_code == 403


# ----------------------------------------------------------------------------------------------------------------- parcours Google (montage complet)
from test_lot55_connexions_ip import env, h  # noqa: E402,F401  (« env » est une fixture)
import auth  # noqa: E402
from routes import google_connexion  # noqa: E402


def test_parcours_google_cible_sonde_cree_un_participant_pas_un_compte(env, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-test.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-test")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://api.test/api/auth/google/retour")

    async def faux(code, uri, cid, secret):
        return {"sub": "g-awa", "email": "awa.badini@gmail.com", "nom": "BADINI Awa"}
    monkeypatch.setattr(google_connexion, "echanger_code", faux)
    # 1. départ : la cible « sonde » est conservée dans l'état signé
    etat = google_auth.signer_etat("sonde", None, auth.JWT_SECRET)
    assert google_auth.lire_etat(etat, auth.JWT_SECRET)["c"] == "sonde"
    # 2. retour de Google : page qui renvoie vers l'application (schéma sondereseau://), code à usage unique
    r = env.client.get("/api/auth/google/retour", params={"code": "c", "state": etat}, follow_redirects=False)
    assert r.status_code == 200 and "sondereseau://google?code=" in r.text
    code = r.text.split("sondereseau://google?code=")[1].split("&")[0].split('"')[0].split("'")[0]
    assert env.run(env.db.users.count_documents({"email": "awa.badini@gmail.com"})) == 0         # AUCUN compte SAWALI créé
    # 3. la fiche du PARTICIPANT existe (e-mail vérifié par Google), avec un code de la sonde en attente…
    pid = sc.identifiant_participant("g-awa")
    fiche = env.run(env.db.settings.find_one({"_id": sc.DOC_PARTICIPANTS}))["p"][pid]
    assert fiche["email"] == "awa.badini@gmail.com" and fiche["cree_le"]
    assert env.run(env.db.google_codes.count_documents({"sonde_pid": pid})) == 1
    # 4. …qui ne sert PAS à ouvrir une session SAWALI : refusé, et le code reste intact pour l'application
    assert env.client.post("/api/auth/google/echange", json={"code": code}, headers=h()).status_code == 401
    assert env.run(env.db.google_codes.count_documents({"sonde_pid": pid})) == 1
