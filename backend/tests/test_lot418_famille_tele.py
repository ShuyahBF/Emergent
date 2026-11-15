"""Lot 418 — Télé des familles : abonnement par foyer (appareils, postes TV), appairage et ordres réservés au détenteur de l'appareil."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "sawali_test_lot418")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.formules_plateformes as fp  # noqa: E402
from routes import famille_tv as ft  # noqa: E402
from routes import tv_video as tv  # noqa: E402
from routes.ecran_tv import empreinte  # noqa: E402
from services import famille as fam  # noqa: E402

HOTES = {"sandbox": "https://pp.test", "production": "https://pp.test"}
MO = 1024 * 1024


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


def _hdr(cid):
    return {"x-famille-compte": cid, "x-famille-jeton": "jeton-" + cid}


def _futur(jours=30):
    return (datetime.now(timezone.utc) + timedelta(days=jours)).isoformat()


@pytest.fixture()
def banc():
    db = mongomock_motor.AsyncMongoMockClient()["test_418"]
    hooks: list = []
    fp._transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"redirectUrl": "https://pay.pawapay.test/x"}))
    for cid, nom in (("A", "Awa"), ("B", "Boureima"), ("C", "Clarisse"), ("D", "Dominique")):
        _run(db.famille_comptes.insert_one({"_id": cid, "nom": nom, "jeton_hash": fam.empreinte_jeton("jeton-" + cid)}))
    # liens vérifiés A-B puis A-C (ordre de création), D sans lien
    _run(db.famille_liens.insert_many([{"_id": "l1", "comptes": ["A", "B"], "statut": "verifie", "cree_le": "2026-01-01"},
                                       {"_id": "l2", "comptes": ["A", "C"], "statut": "verifie", "cree_le": "2026-02-01"}]))
    _run(db.formules_plateformes.insert_many([
        {"id": "f-solo", "plateforme": "personnelmaison", "nom": "Télé 1 appareil", "prix": 1000, "duree_jours": 30, "fonctions": ["tv_video"], "limites": {"appareils": 1, "postes_tv": 1}, "actif": True, "ordre": 1},
        {"id": "f-foyer", "plateforme": "personnelmaison", "nom": "Télé foyer", "prix": 2500, "duree_jours": 30, "fonctions": ["tv_video"], "limites": {"appareils": 2, "postes_tv": 2}, "actif": True, "ordre": 2},
        {"id": "f-ocr", "plateforme": "personnelmaison", "nom": "OCR", "prix": 500, "duree_jours": 30, "fonctions": ["ocr_ordonnances"], "actif": True, "ordre": 3}]))
    _run(db.settings.insert_one({"_id": "global", "pawapay_enabled": True, "tv_appairages": [], "tv_ecrans": []}))
    _run(db.media_library.insert_many([
        {"id": "v-fam", "kind": "video", "title": "Gym douce", "size": 5 * MO, "storage_path": "sawali/g.mp4", "pour_familles": True, "created_at": "2026-11-01"},
        {"id": "v-adm", "kind": "video", "title": "Interne", "size": 5 * MO, "storage_path": "sawali/i.mp4", "created_at": "2026-11-02"}]))

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"email": "admin@test", "id": "adm"}
    api = APIRouter(prefix="/api")
    routeur = fp.make_formules_plateformes(db=db, get_super_admin=lambda: {"role": "admin"}, hooks_apres_paiement=hooks,
                                           pawapay={"jeton": lambda s: "jeton", "hotes": HOTES, "devise": lambda pays: "XOF"})
    api.include_router(routeur)
    ft.setup_famille_tv_routes(db=db, api=api, outils=routeur.outils, authentifier=fam.authentifier)
    tv.setup_tv_video_routes(db=db, api=api, get_current_admin=admin)
    app = FastAPI(); app.include_router(api)
    return TestClient(app), db, hooks


def _abonner(db, cid, fid="f-foyer", appareils=2, postes=2, jours=30):
    _run(db.membres_plateformes.insert_one({"id": "m-" + cid, "plateforme": "personnelmaison", "utilisateur_id": cid, "nom": cid, "telephone": "", "code_parrainage": "PM" + cid * 6,
                                            "abonnements": {fid: {"nom": "Télé foyer", "fonctions": ["tv_video"], "limites": {"appareils": appareils, "postes_tv": postes}, "expire_le": _futur(jours)}}}))


def _telé(c, db, secret, code):
    """Une télé affiche son code (page /tv) ; renvoie son secret."""
    _run(db.settings.update_one({"_id": "global"}, {"$push": {"tv_appairages": {"id": code.lower(), "code": code, "empreinte": empreinte(secret), "cree_le": datetime.now(timezone.utc).isoformat()}}}))
    return secret


def test_sans_abonnement_402_et_catalogue_des_formules_tele(banc):
    c, db, _ = banc
    r = c.get("/api/famille/tv/abonnement", headers=_hdr("A")).json()
    assert r["actif"] is False and [f["id"] for f in r["formules"]] == ["f-solo", "f-foyer"]            # la formule OCR n'est pas proposée ici
    assert r["formules"][1]["limites"] == {"appareils": 2, "postes_tv": 2} and r["formules"][1]["prix"] == 2500
    _telé(c, db, "secret-tele-0123456789a", "ABC123")
    e = c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "abc-123", "nom": "Salon"})
    assert e.status_code == 402 and e.json()["detail"]["code"] == "abonnement_requis" and "Télé 1 appareil" in e.json()["detail"]["message"]
    assert c.get("/api/famille/tv/abonnement").status_code == 401                                       # appareil non reconnu


def test_appairage_limite_de_postes_tv_et_retrait(banc):
    c, db, _ = banc
    _abonner(db, "A", appareils=1, postes=1)
    _telé(c, db, "secret-tele-0123456789a", "AAAAAA"); _telé(c, db, "secret-tele-0123456789b", "BBBBBB")
    r = c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "aaaaaa", "nom": "Salon"})
    assert r.status_code == 200
    ecran_id = r.json()["ecran"]["id"]
    assert c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "BBBBBB"}).status_code == 409        # 1 poste TV seulement
    assert c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "ZZZZZZ"}).status_code in (404, 409)
    assert [x["id"] for x in c.get("/api/famille/tv/ecrans", headers=_hdr("A")).json()["ecrans"]] == [ecran_id]
    assert c.delete(f"/api/famille/tv/ecrans/{ecran_id}", headers=_hdr("A")).status_code == 200                    # on libère le poste
    assert c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "BBBBBB", "nom": "Chambre"}).status_code == 200


def test_foyer_appareils_couverts_selon_la_formule(banc):
    c, db, _ = banc
    _abonner(db, "A", appareils=2, postes=2)                      # A + 1 appareil couvert : B (premier lien vérifié) ; C n'est pas couvert
    r = c.get("/api/famille/tv/abonnement", headers=_hdr("B")).json()
    assert r["actif"] is True and r["role"] == "couvert" and r["titulaire"] == "Awa" and r["appareils_couverts"] == ["Awa", "Boureima"]
    assert c.get("/api/famille/tv/abonnement", headers=_hdr("C")).json()["actif"] is False
    assert c.get("/api/famille/tv/abonnement", headers=_hdr("D")).json()["actif"] is False
    assert c.get("/api/famille/tv/abonnement", headers=_hdr("A")).json()["limites"] == {"appareils": 2, "postes_tv": 2}
    # les postes TV sont partagés par le foyer : A puis B appairent, ensuite plus de poste
    for i, (cid, code) in enumerate((("A", "AAAAAA"), ("B", "BBBBBB"), ("A", "CCCCCC"))):
        _telé(c, db, f"secret-tele-0123456789{i}", code)
        assert c.post("/api/famille/tv/appairer", headers=_hdr(cid), json={"code": code}).status_code == (200 if i < 2 else 409)
    assert c.get("/api/famille/tv/abonnement", headers=_hdr("B")).json()["postes_utilises"] == 2
    _telé(c, db, "secret-tele-0123456789z", "DDDDDD")
    assert c.post("/api/famille/tv/appairer", headers=_hdr("C"), json={"code": "DDDDDD"}).status_code == 402      # C n'est pas couvert


def test_abonnement_expire_refuse(banc):
    c, db, _ = banc
    _abonner(db, "A", jours=-1)
    assert c.get("/api/famille/tv/abonnement", headers=_hdr("A")).json()["actif"] is False
    _telé(c, db, "secret-tele-0123456789a", "AAAAAA")
    assert c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "AAAAAA"}).status_code == 402


def test_seul_le_detenteur_lance_la_projection(banc):
    c, db, _ = banc
    _abonner(db, "A", appareils=2, postes=2)
    secret = _telé(c, db, "secret-tele-0123456789a", "AAAAAA")
    ecran_id = c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "AAAAAA", "nom": "Salon"}).json()["ecran"]["id"]
    ordre = {"ecran_id": ecran_id, "action": "lire", "video_id": "v-fam"}
    # le détenteur lance ; la télé reçoit l'ordre avec l'adresse signée du flux
    assert c.post("/api/famille/tv/commande", headers=_hdr("A"), json=ordre).json()["seq"] == 1
    d = c.get("/api/tv/video/commande?seq=0", headers={"x-tv-secret": secret}).json()
    assert d["commande"]["action"] == "lire" and d["commande"]["url"].startswith("/api/tv/video/flux/v-fam?e=")
    # un proche (même couvert), un inconnu et l'administrateur sont refusés
    assert c.post("/api/famille/tv/commande", headers=_hdr("B"), json=ordre).status_code == 403
    assert c.get(f"/api/famille/tv/etat/{ecran_id}", headers=_hdr("B")).status_code == 403
    assert c.delete(f"/api/famille/tv/ecrans/{ecran_id}", headers=_hdr("B")).status_code == 403
    assert c.post("/api/admin/tv/video/commande", headers={"x-admin": "1"}, json={"ecran_id": ecran_id, "action": "stop"}).status_code == 403
    assert c.get("/api/admin/tv/video/ecrans", headers={"x-admin": "1"}).json()["ecrans"] == []                  # invisible pour la télécommande de l'administrateur
    # seules les vidéos proposées aux familles sont lisibles ; actions et limites contrôlées
    assert c.post("/api/famille/tv/commande", headers=_hdr("A"), json={**ordre, "video_id": "v-adm"}).status_code == 404
    assert c.post("/api/famille/tv/commande", headers=_hdr("A"), json={"ecran_id": ecran_id, "action": "danser"}).status_code == 422
    assert c.post("/api/famille/tv/commande", headers=_hdr("A"), json={"ecran_id": ecran_id, "action": "avancer", "delta": 99999}).status_code == 200
    assert c.get("/api/tv/video/commande?seq=1", headers={"x-tv-secret": secret}).json()["commande"]["delta"] == tv.DELTA_MAX_S
    # sans abonnement actif, plus d'ordre possible
    _run(db.membres_plateformes.update_one({"utilisateur_id": "A"}, {"$set": {"abonnements.f-foyer.expire_le": _futur(-1)}}))
    assert c.post("/api/famille/tv/commande", headers=_hdr("A"), json=ordre).status_code == 402
    # état renvoyé par la télé, lu par le détenteur
    _run(db.settings.update_one({"_id": "tv-video:" + ecran_id}, {"$set": {"etat": {"lecture": "lecture", "position": 5, "duree": 60, "maj": datetime.now(timezone.utc).isoformat()}}}))
    e = c.get(f"/api/famille/tv/etat/{ecran_id}", headers=_hdr("A")).json()
    assert e["etat"]["position"] == 5 and e["en_ligne"] is True


def test_videos_proposees_aux_familles(banc):
    c, db, _ = banc
    assert [v["id"] for v in c.get("/api/famille/tv/videos", headers=_hdr("A")).json()["videos"]] == ["v-fam"]
    assert c.put("/api/admin/tv/video/v-adm/familles", headers={"x-admin": "1"}, json={"actif": True}).json()["pour_familles"] is True
    assert {v["id"] for v in c.get("/api/famille/tv/videos", headers=_hdr("A")).json()["videos"]} == {"v-fam", "v-adm"}
    assert c.put("/api/admin/tv/video/v-adm/familles", headers={"x-admin": "1"}, json={"actif": False}).status_code == 200
    assert c.put("/api/admin/tv/video/inconnue/familles", headers={"x-admin": "1"}, json={"actif": True}).status_code == 404
    assert c.put("/api/admin/tv/video/v-adm/familles", json={"actif": True}).status_code == 403


def test_achat_d_une_formule_tele_puis_activation_avec_limites(banc):
    c, db, hooks = banc
    assert c.post("/api/famille/tv/acheter", headers=_hdr("A"), json={"formule_id": "f-ocr"}).status_code == 422      # pas une formule télé
    r = c.post("/api/famille/tv/acheter", headers=_hdr("A"), json={"formule_id": "f-foyer", "retour": "https://app.test/retour"})
    assert r.status_code == 200 and r.json()["redirect_url"].startswith("https://pay.pawapay.test") and r.json()["total"] == 2500
    dep = r.json()["deposit_id"]
    paiement = _run(db.payments.find_one({"deposit_id": dep}))
    _run(db.payments.update_one({"deposit_id": dep}, {"$set": {"status": "completed"}}))
    _run(hooks[0]({**paiement, "status": "completed"}))                                                              # le crochet « après paiement » active la formule
    a = c.get("/api/famille/tv/abonnement", headers=_hdr("A")).json()
    assert a["actif"] is True and a["limites"] == {"appareils": 2, "postes_tv": 2} and a["formule"] == "Télé foyer" and a["jours_restants"] >= 29
    assert c.post("/api/famille/tv/achat", headers=_hdr("A"), json={"deposit_id": dep}).json()["statut"] == "paye"
    assert c.post("/api/famille/tv/achat", headers=_hdr("B"), json={"deposit_id": dep}).status_code == 404          # le paiement d'un autre compte n'est pas lisible


def test_meilleur_abonnement_prend_le_plus_grand_foyer():
    m = {"abonnements": {"a": {"fonctions": ["tv_video"], "limites": {"appareils": 1, "postes_tv": 1}, "expire_le": _futur(90)},
                         "b": {"fonctions": ["tv_video"], "limites": {"appareils": 3, "postes_tv": 2}, "expire_le": _futur(10)},
                         "c": {"fonctions": ["ocr_ordonnances"], "expire_le": _futur(500)}}}
    assert ft.meilleur_abonnement(m)["appareils"] == 3
    assert ft.meilleur_abonnement({"abonnements": {"x": {"fonctions": ["tv_video"], "expire_le": _futur(-1)}}}) is None
    assert ft.meilleur_abonnement({"abonnements": {"x": {"fonctions": ["tv_video"], "expire_le": _futur(5)}}})["postes_tv"] == 1    # limites absentes : 1 et 1
