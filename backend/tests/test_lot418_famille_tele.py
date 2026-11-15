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
import famille_tv_dossier as fd  # noqa: E402
from routes.ecran_tv import empreinte  # noqa: E402
from services import famille as fam  # noqa: E402

HOTES = {"sandbox": "https://pp.test", "production": "https://pp.test"}
MO = 1024 * 1024
ENVOYES: list = []          # e-mails « envoyés » par le banc d'essai : (destinataire, sujet, texte)


async def _faux_envoi(to, sujet, html, texte):
    ENVOYES.append((to, sujet, texte))
    return True


async def _faux_geo(ip):
    return {"pays": "Burkina Faso", "code_pays": "BF", "ville": "Ouagadougou", "fai": "Orange BF", "mobile": True, "proxy": False, "hebergeur": False}


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
    ENVOYES.clear()
    fd._localiser_remplace = _faux_geo
    ft.setup_famille_tv_routes(db=db, api=api, outils=routeur.outils, authentifier=fam.authentifier, get_current_admin=admin, envoyer_email=_faux_envoi)
    tv.setup_tv_video_routes(db=db, api=api, get_current_admin=admin)
    app = FastAPI(); app.include_router(api)
    return TestClient(app), db, hooks


def _approuver(db, *cids, etat="accepte"):
    """Demandes d'accès acceptées par l'administrateur de SAWALI (lot 419 : exigées même pour une seule télé)."""
    for cid in cids:
        _run(db.settings.update_one({"_id": "famille-tv-config"}, {"$push": {"demandes": {"id": cid, "compte_id": cid, "nom": cid, "lieu": "", "etat": etat, "cree_le": "2026-11-15T08:00:00+00:00", "decide_le": None}}}, upsert=True))


APPAREIL = {"marque": "samsung", "modele": "SM-A135F", "android": "14", "sdk": "34", "langue": "fr-FR", "fuseau": "Africa/Ouagadougou", "ecran": "1080x2408", "app_version": "1.32", "emulateur": False}


def _demande_complete(c, cid, lieu="Salon de Mme Awa", email="awa@example.com", tel="70 12 34 56", appareil=None, entetes=None):
    """Parcours complet du détenteur : captcha recopié, code reçu par e-mail, demande avec le dossier."""
    jeton, texte, _ = fd.fabriquer_captcha()
    r1 = c.post("/api/famille/tv/verification", headers={**_hdr(cid), **(entetes or {})}, json={"telephone": tel, "email": email, "captcha_jeton": jeton, "captcha_reponse": texte})
    assert r1.status_code == 200, r1.text
    code = ENVOYES[-1][2].split(" : ")[1].split(" ")[0]
    return c.post("/api/famille/tv/demander", headers={**_hdr(cid), **(entetes or {})}, json={"lieu": lieu, "code_email": code, "appareil": appareil or APPAREIL})


def _abonner(db, cid, fid="f-foyer", appareils=2, postes=2, jours=30):
    _run(db.membres_plateformes.insert_one({"id": "m-" + cid, "plateforme": "personnelmaison", "utilisateur_id": cid, "nom": cid, "telephone": "", "code_parrainage": "PM" + cid * 6,
                                            "abonnements": {fid: {"nom": "Télé foyer", "fonctions": ["tv_video"], "limites": {"appareils": appareils, "postes_tv": postes}, "expire_le": _futur(jours)}}}))


def _telé(c, db, secret, code):
    """Une télé affiche son code (page /tv) ; renvoie son secret."""
    _run(db.settings.update_one({"_id": "global"}, {"$push": {"tv_appairages": {"id": code.lower(), "code": code, "empreinte": empreinte(secret), "cree_le": datetime.now(timezone.utc).isoformat()}}}))
    return secret


def test_sans_abonnement_une_tele_offerte_la_deuxieme_demande_un_abonnement(banc):
    c, db, _ = banc
    _approuver(db, "A")
    r = c.get("/api/famille/tv/abonnement", headers=_hdr("A")).json()
    assert r["actif"] is False and [f["id"] for f in r["formules"]] == ["f-solo", "f-foyer"]            # la formule OCR n'est pas proposée ici
    assert r["formules"][1]["limites"] == {"appareils": 2, "postes_tv": 2} and r["formules"][1]["prix"] == 2500
    assert r["effectif"] == {"postes_tv": 1, "postes_utilises": 0, "abonne": False} and r["approbation"] == "accepte"
    _telé(c, db, "secret-tele-0123456789a", "ABC123"); _telé(c, db, "secret-tele-0123456789b", "DEF456")
    assert c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "abc-123", "nom": "Salon"}).status_code == 200      # la première télé est offerte
    e = c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "DEF456", "nom": "Chambre"})
    assert e.status_code == 402 and e.json()["detail"]["code"] == "abonnement_requis" and "Télé 1 appareil" in e.json()["detail"]["message"] and "2 télés simultanées" in e.json()["detail"]["message"]
    assert c.get("/api/famille/tv/abonnement").status_code == 401                                       # appareil non reconnu


def test_approbation_de_sawali_toujours_exigee_meme_pour_une_tele(banc):
    c, db, _ = banc
    _telé(c, db, "secret-tele-0123456789a", "AAAAAA")
    # sans demande : tout est refusé, avec le code « approbation_requise »
    for appel in (lambda: c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "AAAAAA"}), lambda: c.get("/api/famille/tv/videos", headers=_hdr("A")),
                  lambda: c.post("/api/famille/tv/acheter", headers=_hdr("A"), json={"formule_id": "f-foyer"})):
        r = appel()
        assert r.status_code == 403 and r.json()["detail"]["code"] == "approbation_requise" and r.json()["detail"]["etat"] == "aucune"
    assert c.get("/api/famille/tv/abonnement", headers=_hdr("A")).json()["approbation"] == "aucune"
    # le détenteur demande l'accès (en indiquant où est la télé) : en attente, toujours refusé
    assert _demande_complete(c, "A", lieu="Salon de Mme Awa").json()["etat"] == "attente"
    r = c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "AAAAAA"})
    assert r.status_code == 403 and r.json()["detail"]["etat"] == "attente"
    # l'administrateur voit la demande, l'accepte : la télé s'appaire
    etat = c.get("/api/admin/famille-tv/etat", headers={"x-admin": "1"}).json()
    assert etat["approbation"] is True and etat["postes_gratuits"] == 1 and [(d["id"], d["lieu"], d["etat"]) for d in etat["demandes"]] == [("A", "Salon de Mme Awa", "attente")]
    assert c.post("/api/admin/famille-tv/demandes/A", headers={"x-admin": "1"}, json={"decision": "accepte"}).json()["etat"] == "accepte"
    assert c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "AAAAAA", "nom": "Salon"}).status_code == 200
    # une demande acceptée n'est pas écrasée par une nouvelle demande
    assert c.post("/api/famille/tv/demander", headers=_hdr("A"), json={"lieu": "autre"}).json()["etat"] == "accepte"      # pas besoin de re-vérifier
    # refus ensuite : accès retiré et télés déliées
    assert c.post("/api/admin/famille-tv/demandes/A", headers={"x-admin": "1"}, json={"decision": "refuse"}).status_code == 200
    assert c.get("/api/famille/tv/ecrans", headers=_hdr("A")).json()["ecrans"] == []
    assert c.get("/api/famille/tv/videos", headers=_hdr("A")).json()["detail"]["etat"] == "refuse"
    # contrôles de l'administrateur
    assert c.post("/api/admin/famille-tv/demandes/A", json={"decision": "accepte"}).status_code == 403
    assert c.post("/api/admin/famille-tv/demandes/A", headers={"x-admin": "1"}, json={"decision": "peut-etre"}).status_code == 422
    assert c.post("/api/admin/famille-tv/demandes/inconnue", headers={"x-admin": "1"}, json={"decision": "accepte"}).status_code == 404


def test_reglages_de_l_approbation_et_des_postes_offerts(banc):
    c, db, _ = banc
    assert c.put("/api/admin/famille-tv/reglages", headers={"x-admin": "1"}, json={"postes_gratuits": 0}).status_code == 422
    assert c.put("/api/admin/famille-tv/reglages", headers={"x-admin": "1"}, json={"postes_gratuits": 2}).json()["postes_gratuits"] == 2
    _approuver(db, "A")
    _telé(c, db, "secret-tele-0123456789a", "AAAAAA"); _telé(c, db, "secret-tele-0123456789b", "BBBBBB"); _telé(c, db, "secret-tele-0123456789c", "CCCCCC")
    assert [c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": k}).status_code for k in ("AAAAAA", "BBBBBB", "CCCCCC")] == [200, 200, 402]     # 2 offertes
    # approbation désactivée : plus de demande à faire
    assert c.put("/api/admin/famille-tv/reglages", headers={"x-admin": "1"}, json={"approbation": False}).json()["approbation"] is False
    assert c.get("/api/famille/tv/abonnement", headers=_hdr("D")).json()["approbation"] == "accepte"


def test_appairage_limite_de_postes_tv_et_retrait(banc):
    c, db, _ = banc
    _approuver(db, "A")
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
    _approuver(db, "A", "B", "C", "D")
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
    assert c.post("/api/famille/tv/appairer", headers=_hdr("C"), json={"code": "DDDDDD"}).status_code == 200      # C n'est pas couvert : il garde sa télé offerte
    _telé(c, db, "secret-tele-0123456789y", "EEEEEE")
    assert c.post("/api/famille/tv/appairer", headers=_hdr("C"), json={"code": "EEEEEE"}).status_code == 402      # …mais pas une 2e sans abonnement


def test_abonnement_expire_retombe_sur_l_offre_de_base(banc):
    c, db, _ = banc
    _approuver(db, "A")
    _abonner(db, "A", jours=-1)
    assert c.get("/api/famille/tv/abonnement", headers=_hdr("A")).json()["actif"] is False
    _telé(c, db, "secret-tele-0123456789a", "AAAAAA"); _telé(c, db, "secret-tele-0123456789b", "BBBBBB")
    assert c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "AAAAAA"}).status_code == 200      # la télé offerte
    assert c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": "BBBBBB"}).status_code == 402      # la 2e demande un abonnement actif


def test_abonnement_arrete_suspend_les_telés_au_dela_de_l_offre(banc):
    c, db, _ = banc
    _approuver(db, "A")
    _abonner(db, "A", appareils=1, postes=2)
    ids, secrets_ = [], []
    for k, code in enumerate(("AAAAAA", "BBBBBB")):
        secrets_.append(_telé(c, db, f"secret-tele-0123456789{k}", code))
        ids.append(c.post("/api/famille/tv/appairer", headers=_hdr("A"), json={"code": code}).json()["ecran"]["id"])
        _run(db.settings.update_one({"_id": "global", "tv_ecrans.id": ids[-1]}, {"$set": {"tv_ecrans.$.cree_le": f"2026-11-1{k}T08:00:00+00:00"}}))     # ordre d'ancienneté
    stop = lambda i: c.post("/api/famille/tv/commande", headers=_hdr("A"), json={"ecran_id": i, "action": "stop"}).status_code
    assert [stop(i) for i in ids] == [200, 200]
    _run(db.membres_plateformes.update_one({"utilisateur_id": "A"}, {"$set": {"abonnements.f-foyer.expire_le": _futur(-1)}}))       # l'abonnement s'arrête
    assert [stop(i) for i in ids] == [200, 402]                                                                    # la plus ancienne reste utilisable (offre de base)


def test_seul_le_detenteur_lance_la_projection(banc):
    c, db, _ = banc
    _approuver(db, "A", "B")
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
    # sans l'approbation de SAWALI, plus d'ordre possible
    _run(db.settings.update_one({"_id": "famille-tv-config"}, {"$set": {"demandes.0.etat": "refuse"}}))
    r = c.post("/api/famille/tv/commande", headers=_hdr("A"), json=ordre)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "approbation_requise"
    _run(db.settings.update_one({"_id": "famille-tv-config"}, {"$set": {"demandes.0.etat": "accepte"}}))
    # état renvoyé par la télé, lu par le détenteur
    _run(db.settings.update_one({"_id": "tv-video:" + ecran_id}, {"$set": {"etat": {"lecture": "lecture", "position": 5, "duree": 60, "maj": datetime.now(timezone.utc).isoformat()}}}))
    e = c.get(f"/api/famille/tv/etat/{ecran_id}", headers=_hdr("A")).json()
    assert e["etat"]["position"] == 5 and e["en_ligne"] is True


def test_videos_proposees_aux_familles(banc):
    c, db, _ = banc
    _approuver(db, "A")
    assert [v["id"] for v in c.get("/api/famille/tv/videos", headers=_hdr("A")).json()["videos"]] == ["v-fam"]
    assert c.put("/api/admin/tv/video/v-adm/familles", headers={"x-admin": "1"}, json={"actif": True}).json()["pour_familles"] is True
    assert {v["id"] for v in c.get("/api/famille/tv/videos", headers=_hdr("A")).json()["videos"]} == {"v-fam", "v-adm"}
    assert c.put("/api/admin/tv/video/v-adm/familles", headers={"x-admin": "1"}, json={"actif": False}).status_code == 200
    assert c.put("/api/admin/tv/video/inconnue/familles", headers={"x-admin": "1"}, json={"actif": True}).status_code == 404
    assert c.put("/api/admin/tv/video/v-adm/familles", json={"actif": True}).status_code == 403


def test_achat_d_une_formule_tele_puis_activation_avec_limites(banc):
    c, db, hooks = banc
    _approuver(db, "A")
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


# ---------- Lot 420 : dossier du demandeur (captcha, e-mail vérifié, IP, appareil, indicateurs) ----------
def _verif(c, cid, **corps):
    jeton, texte, _ = fd.fabriquer_captcha()
    base = {"telephone": "70 12 34 56", "email": "awa@example.com", "captcha_jeton": jeton, "captcha_reponse": texte}
    return c.post("/api/famille/tv/verification", headers=_hdr(cid), json={**base, **corps})


def test_captcha_image_signee_a_usage_unique(banc):
    c, db, _ = banc
    g = c.get("/api/famille/tv/captcha", headers=_hdr("A")).json()
    assert g["image"].startswith("data:image/png;base64,") and len(g["jeton"].split(".")) == 3 and g["validite_s"] == 600
    assert c.get("/api/famille/tv/captcha").status_code == 401
    jeton, texte, _ = fd.fabriquer_captcha()
    ok = {"telephone": "70123456", "email": "awa@example.com", "captcha_jeton": jeton}
    assert c.post("/api/famille/tv/verification", headers=_hdr("A"), json={**ok, "captcha_reponse": "XXXXX"}).status_code == 422                 # mauvaise réponse
    assert c.post("/api/famille/tv/verification", headers=_hdr("A"), json={**ok, "captcha_reponse": " " + texte.lower() + " "}).status_code == 200  # casse et espaces tolérés
    r = c.post("/api/famille/tv/verification", headers=_hdr("A"), json={**ok, "captcha_reponse": texte})
    assert r.status_code == 422 and "déjà servi" in r.json()["detail"]                                                                           # usage unique
    vieux, texte2, _ = fd.fabriquer_captcha(maintenant=1_000_000_000)
    assert c.post("/api/famille/tv/verification", headers=_hdr("A"), json={**ok, "captcha_jeton": vieux, "captcha_reponse": texte2}).status_code == 422   # expiré


def test_verification_valide_les_coordonnees_et_envoie_le_code_par_email(banc):
    c, db, _ = banc
    assert _verif(c, "A", telephone="12").status_code == 422
    assert _verif(c, "A", email="pas-un-email").status_code == 422
    r = _verif(c, "A")
    assert r.status_code == 200 and r.json()["email_masque"] == "aw•••@example.com" and r.json()["validite_minutes"] == 15
    to, sujet, texte = ENVOYES[-1]
    assert to == "awa@example.com" and "SAWALI" in sujet and "15 minutes" in texte
    # plus de 5 codes par heure et par compte
    for _ in range(4):
        assert _verif(c, "A").status_code == 200
    assert _verif(c, "A").status_code == 429


def test_demande_refusee_sans_le_bon_code(banc):
    c, db, _ = banc
    demande = lambda code: c.post("/api/famille/tv/demander", headers=_hdr("A"), json={"lieu": "Salon", "code_email": code, "appareil": APPAREIL})
    assert demande("123456").status_code == 422 and "Vérifiez d'abord" in demande("123456").json()["detail"]     # sans code demandé
    assert _verif(c, "A").status_code == 200
    vrai = ENVOYES[-1][2].split(" : ")[1].split(" ")[0]
    faux = "000000" if vrai != "000000" else "111111"
    for _ in range(5):
        assert demande(faux).status_code == 422
    assert demande(vrai).status_code == 429                                                                       # 5 essais ratés : il faut un nouveau code
    assert _verif(c, "A").status_code == 200
    assert demande(ENVOYES[-1][2].split(" : ")[1].split(" ")[0]).status_code == 200


def test_le_dossier_du_demandeur_est_enregistre_et_evalue(banc):
    c, db, _ = banc
    _run(db.famille_comptes.update_one({"_id": "A"}, {"$set": {"cree_le": datetime.now(timezone.utc) - timedelta(days=30)}}))
    assert _demande_complete(c, "A", entetes={"x-forwarded-for": "41.138.1.2, 10.0.0.1"}).status_code == 200
    assert _demande_complete(c, "A").status_code == 409                                                         # déjà en attente
    adm = {"x-admin": "1"}
    liste = c.get("/api/admin/famille-tv/etat", headers=adm).json()["demandes"][0]
    assert liste["tel"] == "+22670123456" and liste["email_verifie"] is True and liste["pays_ip"] == "BF" and liste["appareil_resume"] == "samsung SM-A135F · Android 14"
    d = c.get("/api/admin/famille-tv/demandes/A/dossier", headers=adm).json()
    assert d["ip"] == "41.138.1.2" and d["ip_infos"]["ville"] == "Ouagadougou" and d["telephone"] == {"e164": "+22670123456", "pays": "BF", "indicatif": "226"}
    assert d["email"] == "awa@example.com" and d["appareil"]["modele"] == "SM-A135F" and d["lieu"] == "Salon de Mme Awa" and d["liens_verifies"] == 2
    codes = {i["code"] for i in d["indicateurs"]}
    assert {"email_verifie", "pays_coherent", "avec_liens"} <= codes and d["niveau"] == "faible" and d["score"] == 0
    assert c.get("/api/admin/famille-tv/demandes/A/dossier").status_code == 403
    assert c.get("/api/admin/famille-tv/demandes/zzz/dossier", headers=adm).status_code == 404


def test_doublons_et_signaux_de_risque_remontent_au_niveau_eleve(banc):
    c, db, _ = banc
    async def vpn(ip):
        return {"pays": "France", "code_pays": "FR", "ville": "Paris", "fai": "OVH", "mobile": False, "proxy": True, "hebergeur": True}
    adm = {"x-admin": "1"}
    assert _demande_complete(c, "A", email="un@example.com", tel="70 11 11 11", entetes={"x-forwarded-for": "41.138.1.2"}).status_code == 200
    c.post("/api/admin/famille-tv/demandes/A", headers=adm, json={"decision": "refuse"})                      # A est refusé
    fd._localiser_remplace = vpn
    # D (compte créé à l'instant, sans proche) redemande avec le MÊME téléphone, la même IP, un e-mail jetable et un émulateur, derrière un VPN
    r = _demande_complete(c, "D", email="x@mailinator.com", tel="+226 70 11 11 11", appareil={**APPAREIL, "emulateur": True}, entetes={"x-forwarded-for": "41.138.1.2"})
    assert r.status_code == 200
    d = c.get("/api/admin/famille-tv/demandes/D/dossier", headers=adm).json()
    codes = {i["code"] for i in d["indicateurs"]}
    assert {"email_jetable", "ip_proxy", "pays_different", "emulateur", "tel_double", "deja_refuse", "sans_lien", "ip_partagee"} <= codes
    assert d["niveau"] == "eleve" and d["score"] >= 6 and [x["id"] for x in d["demandes_liees"]] == ["A"] and set(d["demandes_liees"][0]["raison"]) == {"même IP", "même téléphone"}
    assert [x["niveau"] for x in c.get("/api/admin/famille-tv/etat", headers=adm).json()["demandes"] if x["id"] == "D"] == ["eleve"]


def test_demande_refusee_puis_nouvelle_demande_seulement_apres_24_heures(banc):
    c, db, _ = banc
    assert _demande_complete(c, "A").status_code == 200
    c.post("/api/admin/famille-tv/demandes/A", headers={"x-admin": "1"}, json={"decision": "refuse"})
    r = _demande_complete(c, "A", email="autre@example.com")
    assert r.status_code == 429 and "24 heures" in r.json()["detail"]


def test_limite_de_demandes_par_adresse_ip(banc):
    c, db, _ = banc
    _run(db.famille_comptes.insert_many([{"_id": f"X{i}", "nom": f"X{i}", "jeton_hash": fam.empreinte_jeton(f"jeton-X{i}")} for i in range(7)]))
    statuts = [_demande_complete(c, f"X{i}", email=f"x{i}@example.com", tel=f"70 00 00 0{i}", entetes={"x-forwarded-for": "41.0.0.9"}).status_code for i in range(7)]
    assert statuts == [200] * 5 + [429] * 2                                                                    # 5 comptes déjà vus avec cette IP en 24 h : le 6e et le 7e sont bloqués


def test_fonctions_pures_du_dossier():
    assert fd.normaliser_telephone("70 12 34 56") == {"e164": "+22670123456", "pays": "BF", "indicatif": "226"}
    assert fd.normaliser_telephone("+33 6 12 34 56 78")["pays"] == "FR" and fd.normaliser_telephone("0022507123456")["pays"] == "CI"
    assert fd.normaliser_telephone("123") is None and fd.normaliser_telephone("abc") is None
    assert fd.email_valide("awa.badini@gmail.com") and not fd.email_valide("awa@") and fd.email_jetable("a@YOPMAIL.com") and not fd.email_jetable("a@gmail.com")
    assert fd.masquer_email("awa.badini@gmail.com") == "aw•••@gmail.com"
    assert fd.ip_client({"x-forwarded-for": "41.1.1.1, 10.0.0.1"}, "10.0.0.2") == "41.1.1.1" and fd.ip_client({}, "10.0.0.2") == "10.0.0.2"
    assert fd.ip_publique("41.138.1.2") and not fd.ip_publique("192.168.1.5") and not fd.ip_publique("127.0.0.1") and not fd.ip_publique("pas-une-ip")
    assert fd.nettoyer_appareil({"marque": "x" * 99, "modele": "A\nB", "serie": "SECRET", "emulateur": 1}) == {"marque": "x" * 40, "modele": "AB", "emulateur": True}
    assert fd.empreinte_code("A", "123456") != fd.empreinte_code("B", "123456")                                  # un code ne vaut que pour son compte
    ev = fd.evaluer({"id": "A", "email": "a@mailinator.com", "email_verifie": True, "telephone": {"e164": "+1", "pays": "BF"}, "ip": "1.1.1.1", "ip_infos": {"code_pays": "BF"}, "appareil": {}, "liens_verifies": 1}, [], "2026-11-15T10:00:00+00:00")
    assert ev["score"] == 2 and ev["niveau"] == "faible" and ev["indicateurs"][0]["code"] == "email_jetable"
