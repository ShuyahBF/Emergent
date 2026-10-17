"""Lot 235 — annonceurs des plateformes : devis, médias chiffrés, paiement, publication dans la régie, statistiques.
MongoDB simulé, PawaPay simulé. Lancer : cd backend && python -m pytest tests/test_lot235_annonceurs_plateformes.py -q"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "sawali_test_lot235")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.annonceurs_plateformes as ap  # noqa: E402
import routes.formules_plateformes as fp  # noqa: E402

CLE = "cle-de-test"
HOTES = {"sandbox": "https://pp.test", "production": "https://pp.test"}
ETAT = {"status": "PROCESSING"}
STOCK: dict = {}
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 500


def url_png(octets=PNG, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(octets).decode()


def entetes(corps: dict):
    brut = json.dumps(corps, ensure_ascii=False)
    ts = str(int(time.time()))
    return brut, {"Content-Type": "application/json", "X-Emetteur": "paiementmobile", "X-Timestamp": ts,
                  "X-Signature": hmac.new(CLE.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()}


def U(i="u1", libre=False):
    return {"id": i, "nom": f"Nom {i}", "telephone": "70 11 22 33", "acces_libre": libre}


def appel(c, chemin, corps):
    brut, h = entetes(corps)
    return c.post(f"/api/annonceurs-plateformes/{chemin}", content=brut, headers=h)


def demain(n=1):
    return (date.today() + timedelta(days=n)).isoformat()


@pytest.fixture()
def env():
    hooks: list = []
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    STOCK.clear()
    ETAT["status"] = "PROCESSING"

    def pp(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/paymentpage"):
            return httpx.Response(200, json={"redirectUrl": "https://pay.pawapay.test/x"})
        return httpx.Response(200, json={"status": "FOUND", "data": {"status": ETAT["status"]}})

    async def ecrire(chemin, octets):
        STOCK[chemin] = octets

    async def lire(chemin):
        return STOCK[chemin]

    ap._transport, ap._ecrire, ap._lire = httpx.MockTransport(pp), ecrire, lire
    pw = {"jeton": lambda s: "jeton", "hotes": HOTES, "devise": lambda pays: "XOF"}
    api = APIRouter(prefix="/api")
    formules = fp.make_formules_plateformes(db=db, get_super_admin=lambda: {"role": "admin"}, hooks_apres_paiement=hooks, pawapay=pw)
    api.include_router(formules)
    api.include_router(ap.make_annonceurs_plateformes(db=db, get_super_admin=lambda: {"role": "admin", "email": "a@b.c"}, hooks_apres_paiement=hooks,
                                                      pawapay=pw, outils=formules.outils))
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app).__enter__()
    c.portal.call(db.liluvine_emetteurs.insert_one, {"code": "paiementmobile", "nom": "PM", "secret": CLE, "actif": True})
    c.portal.call(db.settings.insert_one, {"_id": "global", "pawapay_enabled": True, "pawapay_environment": "sandbox"})
    # u1 est abonné (abonnement actif) ; u2 ne l'est pas
    futur = (date.today() + timedelta(days=10)).isoformat() + "T00:00:00+00:00"
    c.portal.call(db.membres_plateformes.insert_one, {"id": "m1", "plateforme": "paiementmobile", "utilisateur_id": "u1", "nom": "Nom u1", "telephone": "70 11 22 33",
                                                      "code_parrainage": "PM111111", "abonnements": {"f1": {"nom": "Annonceur", "fonctions": ["annonceur_pm"], "expire_le": futur}}})
    c.db, c.hooks = db, hooks
    yield c
    ap._transport = ap._ecrire = ap._lire = None


def creer(c, **plus):
    corps = {"utilisateur": U(), "nom": "Pub test", "annonceur": "Boutique Awa", "format": "banniere_image", "debut": demain(1), "fin": demain(7),
             "options": [], "lien": "https://exemple.bf/promo", "media": url_png(), **plus}
    return appel(c, "creer", corps)


def test_calcul_devis_pur():
    t = ap.valider_tarifs(ap.TARIFS_DEFAUT)
    d = ap.calculer_devis(t, "banniere_image", demain(1), demain(7), [])          # 7 jours : remise 5 %
    assert d["jours"] == 7 and d["base"] == 7000 and d["remise_pct"] == 5 and d["total"] == 6650
    d = ap.calculer_devis(t, "banniere_video", demain(1), demain(1), ["avant"])    # 1 jour + 30 % de mise en avant
    assert d["total"] == 3250
    with pytest.raises(ValueError):
        ap.calculer_devis(t, "banniere_image", demain(5), demain(2), [])
    with pytest.raises(ValueError):
        ap.calculer_devis(t, "banniere_image", demain(1), demain(200), [])
    with pytest.raises(ValueError):
        ap.calculer_devis(t, "inconnu", demain(1), demain(2), [])


def test_non_abonne_refuse(env):
    r = appel(env, "devis", {"utilisateur": U("u2"), "format": "banniere_image", "debut": demain(1), "fin": demain(2), "options": []})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "abonnement_requis"
    r = appel(env, "devis", {"utilisateur": U("u2", libre=True), "format": "banniere_image", "debut": demain(1), "fin": demain(2), "options": []})
    assert r.status_code == 200


def test_autre_abonnement_ne_suffit_pas_et_offre_proposee(env):
    futur = (date.today() + timedelta(days=10)).isoformat() + "T00:00:00+00:00"
    env.portal.call(env.db.membres_plateformes.insert_one, {"id": "m3", "plateforme": "paiementmobile", "utilisateur_id": "u3", "nom": "N", "telephone": "70 11 22 33",
                    "code_parrainage": "PM333333", "abonnements": {"f9": {"nom": "OCR", "fonctions": ["ocr_ordonnances"], "expire_le": futur}}})
    env.portal.call(env.db.formules_plateformes.insert_one, {"id": "fa", "plateforme": "paiementmobile", "nom": "Annonceur", "prix": 5000, "duree_jours": 30,
                    "fonctions": ["annonceur_pm"], "actif": True, "ordre": 0})
    r = appel(env, "devis", {"utilisateur": U("u3"), "format": "banniere_image", "debut": demain(1), "fin": demain(2), "options": []})
    assert r.status_code == 402 and "5 000" in r.json()["detail"]["message"] and r.json()["detail"]["formule"]["nom"] == "Annonceur"
    t = appel(env, "tarifs", {"utilisateur": U("u3")}).json()
    assert t["est_abonne"] is False and t["formules"][0]["prix"] == 5000


def test_devis_en_direct_et_creation(env):
    r = appel(env, "devis", {"utilisateur": U(), "format": "banniere_image", "debut": demain(1), "fin": demain(2), "options": ["avant"]})
    assert r.status_code == 200 and r.json()["devis"]["total"] == 2600
    r = creer(env)
    assert r.status_code == 200
    c = r.json()["campagne"]
    assert c["montant"] == 6650 and c["statut"] == "devis"
    # Le média est stocké CHIFFRÉ : ni le contenu clair ni la signature PNG n'apparaissent
    stocke = next(iter(STOCK.values()))
    assert PNG not in stocke and not stocke.startswith(b"\x89PNG") and ap.dechiffrer(stocke) == PNG


def test_media_refuses(env):
    assert creer(env, media=url_png(b"pas une image" * 20)).status_code == 422                       # signature incorrecte
    assert creer(env, media=url_png(b"\x89PNG" + b"x" * 700_000)).status_code == 422                  # trop lourd (600 Ko)
    assert creer(env, media=url_png(PNG, "video/mp4")).status_code == 422                            # vidéo pour un format image
    assert creer(env, lien="http://non-securise.bf/x").status_code == 422
    assert creer(env, debut=demain(-2)).status_code == 422


def test_paiement_pawapay_publie_et_statistiques(env):
    cid = creer(env).json()["campagne"]["id"]
    # Le média n'est pas public avant paiement
    jeton = env.portal.call(env.db.annonceurs_campagnes.find_one, {"id": cid})["media"]["jeton"]
    assert env.get(f"/api/public/annonceurs-plateformes/media/{jeton}").status_code == 404
    r = appel(env, "payer", {"utilisateur": U(), "campagne_id": cid, "mode": "pawapay", "retour": "https://pm.test/annonceur"})
    assert r.status_code == 200 and r.json()["redirect_url"].startswith("https://pay.pawapay")
    dep = r.json()["deposit_id"]
    assert appel(env, "etat", {"utilisateur": U(), "campagne_id": cid}).json()["campagne"]["statut"] == "paiement_en_cours"
    ETAT["status"] = "COMPLETED"
    assert appel(env, "etat", {"utilisateur": U(), "campagne_id": cid}).json()["campagne"]["statut"] == "active"
    # Publiée dans la régie, une seule fois
    bannieres = env.portal.call(lambda: env.db.ad_banners.find({}).to_list(10))
    assert len(bannieres) == 1 and bannieres[0]["placement"] == "paiementmobile" and bannieres[0]["start_date"] == demain(1)
    for p in env.portal.call(lambda: env.db.payments.find({}).to_list(5)):
        for h in env.hooks:
            env.portal.call(h, p)
    assert env.portal.call(env.db.ad_banners.count_documents, {}) == 1
    # Le média est maintenant servi, déchiffré
    r = env.get(f"/api/public/annonceurs-plateformes/media/{jeton}")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    # Statistiques : lues dans la régie
    env.portal.call(env.db.ad_banners.update_one, {"id": bannieres[0]["id"]}, {"$set": {"total_impressions": 200, "total_clicks": 10,
                    "daily_stats": [{"date": demain(1), "impressions": 200, "clicks": 10}]}})
    s = appel(env, "stats", {"utilisateur": U(), "campagne_id": cid}).json()
    assert s["impressions"] == 200 and s["clics"] == 10 and s["taux_clic"] == 5.0 and s["campagne"]["statut"] == "programmee"      # débute demain
    # Un autre utilisateur ne voit pas cette campagne
    assert appel(env, "stats", {"utilisateur": U("u2", libre=True), "campagne_id": cid}).status_code == 404


def test_admin_corrige_montant_avant_paiement(env):
    cid = creer(env).json()["campagne"]["id"]
    admin = env.put(f"/api/admin/annonceurs-plateformes/campagnes/{cid}/montant", json={"montant": 5000, "motif": "geste commercial"})
    assert admin.status_code == 200
    c = appel(env, "campagnes", {"utilisateur": U()}).json()["campagnes"][0]
    assert c["montant"] == 5000 and c["montant_corrige"] is True and c["devis"]["total"] == 6650
    # Montant à 0 : publication directe
    env.put(f"/api/admin/annonceurs-plateformes/campagnes/{cid}/montant", json={"montant": 0})
    assert appel(env, "payer", {"utilisateur": U(), "campagne_id": cid, "mode": "pawapay"}).json()["statut"] == "paye"
    assert env.put(f"/api/admin/annonceurs-plateformes/campagnes/{cid}/montant", json={"montant": 10}).status_code == 409


def test_tarifs_admin_et_validation(env):
    t = env.get("/api/admin/annonceurs-plateformes/tarifs").json()["tarifs"]
    t["formats"][0]["prix_jour"] = 2000
    assert env.put("/api/admin/annonceurs-plateformes/tarifs", json=t).status_code == 200
    r = appel(env, "devis", {"utilisateur": U(), "format": "banniere_image", "debut": demain(1), "fin": demain(1), "options": []})
    assert r.json()["devis"]["total"] == 2000
    t["formats"] = []
    assert env.put("/api/admin/annonceurs-plateformes/tarifs", json=t).status_code == 422


def test_suspension(env):
    cid = creer(env).json()["campagne"]["id"]
    env.put(f"/api/admin/annonceurs-plateformes/campagnes/{cid}/montant", json={"montant": 0})
    appel(env, "payer", {"utilisateur": U(), "campagne_id": cid, "mode": "pawapay"})
    assert env.post(f"/api/admin/annonceurs-plateformes/campagnes/{cid}/suspendre").status_code == 200
    b = env.portal.call(lambda: env.db.ad_banners.find({}).to_list(2))[0]
    assert b["active"] is False
    assert env.post(f"/api/admin/annonceurs-plateformes/campagnes/{cid}/reactiver").status_code == 200
