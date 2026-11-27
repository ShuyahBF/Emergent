"""Lot 484 — connexion rapide de Loois Mobile : biométrie, compte Google, clé d'accès (aucun accès réseau : Google et le client sont simulés)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import android_loois as al  # noqa: E402
import connexion_rapide as cr  # noqa: E402
import routes.connexion_rapide as rcr  # noqa: E402
from test_android_loois_lot475 import construire_banc, entetes, se_connecter, run  # noqa: E402
from test_passkeys_lot369 import FauxAuthentificateur, b64  # noqa: E402

RP = rcr.RP_PAR_DEFAUT
ORIGINE = cr.origine_android(cr.EMPREINTE_APK_DEFAUT)


@pytest.fixture()
def banc():
    return construire_banc()


def session(c, b):
    return se_connecter(c, b).json()["session"]


# ------------------------------------------------------------------------------------------------------------------ logique pure
def test_secret_empreinte_et_comparaison():
    s = cr.nouveau_secret()
    assert len(s) >= 40 and cr.secret_correspond(s, cr.empreinte(s)) and not cr.secret_correspond(s + "x", cr.empreinte(s)) and not cr.secret_correspond("", "")


def test_jeton_google_controles():
    ok = {"aud": "cid", "iss": "https://accounts.google.com", "exp": "9999999999", "sub": "123", "email_verified": "true"}
    assert cr.verifier_jeton_google(ok, "cid")[0]
    assert not cr.verifier_jeton_google({**ok, "aud": "autre"}, "cid")[0]
    assert not cr.verifier_jeton_google({**ok, "iss": "evil.com"}, "cid")[0]
    assert not cr.verifier_jeton_google({**ok, "exp": "1"}, "cid")[0]
    assert not cr.verifier_jeton_google({**ok, "email_verified": "false"}, "cid")[0]
    assert not cr.verifier_jeton_google(ok, "")[0]
    assert cr.masquer_email("awa.badini@gmail.com") == "a***@gmail.com"


def test_origine_android_et_assetlinks():
    assert ORIGINE.startswith("android:apk-key-hash:") and "=" not in ORIGINE
    a = cr.assetlinks(cr.empreintes_apk())[0]
    assert a["target"]["package_name"] == "bf.sawali.loois.mobile" and cr.EMPREINTE_APK_DEFAUT in a["target"]["sha256_cert_fingerprints"]
    assert len(cr.empreintes_apk("AA:BB, " + cr.EMPREINTE_APK_DEFAUT)) == 1                  # invalide ignorée, doublon ignoré


def test_assetlinks_public():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    rcr.attacher_assetlinks(app)
    r = TestClient(app).get("/.well-known/assetlinks.json")
    assert r.status_code == 200 and r.json()[0]["relation"] == ["delegate_permission/common.get_login_creds"]


# ------------------------------------------------------------------------------------------------------------------ biométrie
def test_biometrie_activation_puis_connexion(banc):
    c, b = banc
    s = session(c, b)
    r = c.post("/api/android/rapide/biometrie/activer", headers=entetes(b, s))
    assert r.status_code == 200
    secret = r.json()["secret"]
    stock = run(b["db"].settings.find_one({"_id": "android_rapide"}))
    assert secret not in str(stock) and cr.empreinte(secret) in str(stock)                       # seule l'empreinte est gardée
    r = c.post("/api/android/rapide/connexion", json={"methode": "biometrie", "login": "tassembh", "secret": secret}, headers=entetes(b))
    assert r.status_code == 200 and r.json()["session"] and r.json()["utilisateur"]["login"] == "tassembh"
    # la session obtenue ouvre bien le reste de l'application
    assert c.get("/api/android/moi", headers=entetes(b, r.json()["session"])).status_code == 200
    assert not any("Mot_de_Passe" in sql for sql, _ in b["envoyees"][-3:])                        # aucune requête avec mot de passe pour la connexion rapide


def test_biometrie_mauvais_secret_et_limite_d_essais(banc):
    c, b = banc
    c.post("/api/android/rapide/biometrie/activer", headers=entetes(b, session(c, b)))
    for _ in range(al.ESSAIS_MAX):
        assert c.post("/api/android/rapide/connexion", json={"methode": "biometrie", "login": "tassembh", "secret": "faux"}, headers=entetes(b)).status_code == 401
    assert c.post("/api/android/rapide/connexion", json={"methode": "biometrie", "login": "tassembh", "secret": "faux"}, headers=entetes(b)).status_code == 429


def test_utilisateur_supprime_chez_le_client_refuse(banc):
    c, b = banc
    secret = c.post("/api/android/rapide/biometrie/activer", headers=entetes(b, session(c, b))).json()["secret"]
    b["etat"]["mdp_ok"] = False                                                                    # le client ne connaît plus cet utilisateur
    r = c.post("/api/android/rapide/connexion", json={"methode": "biometrie", "login": "tassembh", "secret": secret}, headers=entetes(b))
    assert r.status_code == 401 and "n'existe plus" in r.json()["detail"]


def test_appareil_interdit_refuse_la_connexion_rapide(banc):
    c, b = banc
    secret = c.post("/api/android/rapide/biometrie/activer", headers=entetes(b, session(c, b))).json()["secret"]
    run(b["db"].settings.update_one({"_id": "android_appareils"}, {"$set": {f"appareils.{b['fiche']['id']}.etat": "interdit"}}))
    r = c.post("/api/android/rapide/connexion", json={"methode": "biometrie", "login": "tassembh", "secret": secret}, headers=entetes(b))
    assert r.status_code == 403


def test_reactiver_remplace_l_ancien_secret_et_retrait(banc):
    c, b = banc
    s = session(c, b)
    s1 = c.post("/api/android/rapide/biometrie/activer", headers=entetes(b, s)).json()["secret"]
    r2 = c.post("/api/android/rapide/biometrie/activer", headers=entetes(b, s)).json()
    assert c.post("/api/android/rapide/connexion", json={"methode": "biometrie", "login": "tassembh", "secret": s1}, headers=entetes(b)).status_code == 401
    liste = c.get("/api/android/rapide/liste", headers=entetes(b, s)).json()["liaisons"]
    assert len(liste) == 1 and liste[0]["methode"] == "biometrie"
    assert c.delete(f"/api/android/rapide/{r2['id']}", headers=entetes(b, s)).status_code == 200
    assert c.post("/api/android/rapide/connexion", json={"methode": "biometrie", "login": "tassembh", "secret": r2["secret"]}, headers=entetes(b)).status_code == 401


# ------------------------------------------------------------------------------------------------------------------ Google
class FauxHttp:
    """Remplace httpx.AsyncClient : renvoie les « informations » d'un jeton Google simulé."""
    infos = {"aud": "cid.apps.googleusercontent.com", "iss": "https://accounts.google.com", "exp": "9999999999", "sub": "google-1", "email": "awa.badini@gmail.com", "email_verified": "true"}
    statut = 200

    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, params=None):
        class R:  # noqa: D401
            status_code = FauxHttp.statut
            def json(self_): return dict(FauxHttp.infos)
        return R()


@pytest.fixture()
def google(monkeypatch, banc):
    c, b = banc
    run(b["db"].settings.update_one({"_id": "global"}, {"$set": {"google_client_id": "cid.apps.googleusercontent.com"}}, upsert=True))
    monkeypatch.setattr(rcr.httpx, "AsyncClient", FauxHttp)
    FauxHttp.statut = 200
    FauxHttp.infos = {**FauxHttp.infos, "sub": "google-1", "aud": "cid.apps.googleusercontent.com"}
    return c, b


def test_config_annonce_google(google):
    c, b = google
    cfg = c.get("/api/android/rapide/config", headers=entetes(b)).json()
    assert cfg["google"] and cfg["google_client_id"].startswith("cid") and cfg["rp_id"] == RP


def test_google_liaison_puis_connexion(google):
    c, b = google
    r = c.post("/api/android/rapide/google/activer", json={"id_token": "x" * 30}, headers=entetes(b, session(c, b)))
    assert r.status_code == 200 and r.json()["detail"] == "a***@gmail.com"
    r = c.post("/api/android/rapide/connexion", json={"methode": "google", "id_token": "y" * 30}, headers=entetes(b))
    assert r.status_code == 200 and r.json()["utilisateur"]["login"] == "tassembh"


def test_google_compte_non_lie_refuse(google):
    c, b = google
    c.post("/api/android/rapide/google/activer", json={"id_token": "x" * 30}, headers=entetes(b, session(c, b)))
    FauxHttp.infos = {**FauxHttp.infos, "sub": "google-autre"}
    assert c.post("/api/android/rapide/connexion", json={"methode": "google", "id_token": "y" * 30}, headers=entetes(b)).status_code == 401


def test_google_mauvaise_audience_ou_refus_de_google(google):
    c, b = google
    FauxHttp.infos = {**FauxHttp.infos, "aud": "autre-application"}
    assert c.post("/api/android/rapide/google/activer", json={"id_token": "x" * 30}, headers=entetes(b, session(c, b))).status_code == 401
    FauxHttp.statut = 400
    assert c.post("/api/android/rapide/connexion", json={"methode": "google", "id_token": "y" * 30}, headers=entetes(b)).status_code == 401


def test_google_non_configure(banc, monkeypatch):
    c, b = banc
    monkeypatch.setattr(rcr.httpx, "AsyncClient", FauxHttp)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert not c.get("/api/android/rapide/config", headers=entetes(b)).json()["google"]
    assert c.post("/api/android/rapide/google/activer", json={"id_token": "x" * 30}, headers=entetes(b, session(c, b))).status_code == 503


# ------------------------------------------------------------------------------------------------------------------ clé d'accès
def activer_cle(c, b, auth, origine=ORIGINE):
    s = session(c, b)
    o = c.post("/api/android/rapide/cle/options", headers=entetes(b, s)).json()
    cred = auth.enregistrer(o["options"], origine=origine, rp=RP)
    return c.post("/api/android/rapide/cle/activer", json={"challenge_id": o["challenge_id"], "credential": cred, "nom": "Pixel"}, headers=entetes(b, s))


def test_cle_d_acces_enregistrement_et_connexion(banc):
    c, b = banc
    auth = FauxAuthentificateur()
    assert activer_cle(c, b, auth).status_code == 200
    o = c.post("/api/android/rapide/cle/options-connexion", json={"login": "tassembh"}, headers=entetes(b)).json()
    cred = auth.signer(o["options"], origine=ORIGINE, rp=RP)
    r = c.post("/api/android/rapide/connexion", json={"methode": "cle", "challenge_id": o["challenge_id"], "credential": cred}, headers=entetes(b))
    assert r.status_code == 200 and r.json()["utilisateur"]["login"] == "tassembh"
    # un défi ne sert qu'une fois
    assert c.post("/api/android/rapide/connexion", json={"methode": "cle", "challenge_id": o["challenge_id"], "credential": cred}, headers=entetes(b)).status_code == 400


def test_cle_d_acces_mauvaise_origine_ou_signature_refusees(banc):
    c, b = banc
    assert activer_cle(c, b, FauxAuthentificateur(), origine="https://evil.example").status_code == 400    # origine d'une autre application
    auth = FauxAuthentificateur()
    assert activer_cle(c, b, auth).status_code == 200
    o = c.post("/api/android/rapide/cle/options-connexion", json={"login": "tassembh"}, headers=entetes(b)).json()
    pirate = FauxAuthentificateur()
    pirate.identifiant = auth.identifiant                                                                  # même identifiant, autre clé privée
    cred = pirate.signer(o["options"], origine=ORIGINE, rp=RP)
    assert c.post("/api/android/rapide/connexion", json={"methode": "cle", "challenge_id": o["challenge_id"], "credential": cred}, headers=entetes(b)).status_code == 401


def test_cle_d_acces_sans_cle_enregistree(banc):
    c, b = banc
    assert c.post("/api/android/rapide/cle/options-connexion", json={"login": "tassembh"}, headers=entetes(b)).status_code == 404


# ------------------------------------------------------------------------------------------------------------------ administrateur
def test_administrateur_liste_et_revoque(banc):
    c, b = banc
    r = c.post("/api/android/rapide/biometrie/activer", headers=entetes(b, session(c, b))).json()
    liste = c.get("/api/admin/android-rapide", headers=entetes(b)).json()
    assert len(liste["liaisons"]) == 1 and "secret" not in str(liste) and "empreinte" not in str(liste)
    assert c.delete(f"/api/admin/android-rapide/{r['id']}", headers=entetes(b)).status_code == 200
    assert c.get("/api/admin/android-rapide", headers=entetes(b)).json()["liaisons"] == []
    b["admin"]["user"] = {"id": "u2", "role": "client"}
    assert c.get("/api/admin/android-rapide", headers=entetes(b)).status_code == 403
