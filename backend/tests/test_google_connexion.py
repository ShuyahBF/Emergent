"""Connexion par compte Google (SAWALI) : aucun accès réseau, l'échange du code avec Google est simulé.
Montage : celui du lot 55 (comptes, code e-mail, IP bloquées, maintenance)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

# Le montage du lot 55 est importé EN PREMIER : il pose les variables d'environnement de la base avant tout autre import du serveur.
from test_lot55_connexions_ip import SUPER, env, h, jeton  # noqa: E402,F401  (« env » est une fixture)

import auth  # noqa: E402
import google_auth  # noqa: E402
from routes import google_connexion  # noqa: E402

CLIENT = "client-test.apps.googleusercontent.com"


def _actif(monkeypatch, identite):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-test")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://api.test/api/auth/google/retour")
    monkeypatch.setenv("GOOGLE_RETOUR_SITE", "https://site.test")

    async def faux(code, uri, cid, secret):
        return identite
    monkeypatch.setattr(google_connexion, "echanger_code", faux)


def _etat(cible="web", lier=None):
    return google_auth.signer_etat(cible, lier, auth.JWT_SECRET)


def test_inactif_sans_configuration(env, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert env.client.get("/api/auth/google/config").json() == {"disponible": False}
    assert env.client.get("/api/auth/google/demarrer", follow_redirects=False).status_code == 503


def test_la_configuration_de_google_agenda_est_reutilisee(env, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    env.run(env.db.settings.update_one({"_id": "global"}, {"$set": {"google_client_id": "deja-saisi", "google_client_secret": "secret"}}, upsert=True))
    assert env.client.get("/api/auth/google/config").json() == {"disponible": True}


def test_liaison_puis_connexion_avec_code_de_verification(env, monkeypatch):
    _actif(monkeypatch, {"sub": "g-pharma", "email": "pharma@gmail.com", "nom": "Pharmacie"})
    tok = jeton("pharma")
    url = env.client.post("/api/auth/google/lier-url", json={"cible": "web"}, headers=h(tok)).json()["url"]
    assert url.startswith("https://accounts.google.com/")
    r = env.client.get("/api/auth/google/retour", params={"code": "c", "state": _etat("web", "pharma")}, follow_redirects=False)
    assert r.status_code == 302 and "lie=1" in r.headers["location"] and r.headers["location"].startswith("https://site.test/connexion-google")
    assert env.client.get("/api/auth/google/etat", headers=h(tok)).json()["lie"] is True
    # Connexion : code à usage unique → même réponse que /auth/login (un code de vérification est demandé)
    r = env.client.get("/api/auth/google/retour", params={"code": "c", "state": _etat()}, follow_redirects=False)
    code = r.headers["location"].split("code=")[1]
    ok = env.client.post("/api/auth/google/echange", json={"code": code}, headers=h())
    assert ok.status_code == 200 and ok.json()["needs_otp"] is True and ok.json()["session_token"]
    # le code Google ne sert qu'une fois
    assert env.client.post("/api/auth/google/echange", json={"code": code}, headers=h()).status_code == 401
    # le code de vérification ouvre la session (comme pour un mot de passe)
    fin = env.client.post("/api/auth/verify-otp", json={"session_token": ok.json()["session_token"], "code": "123456"}, headers=h())
    assert fin.status_code == 200 and fin.json()["access_token"]


def test_identite_inconnue_ne_cree_aucun_compte(env, monkeypatch):
    _actif(monkeypatch, {"sub": "g-inconnu", "email": "inconnu@gmail.com", "nom": "X"})
    r = env.client.get("/api/auth/google/retour", params={"code": "c", "state": _etat()}, follow_redirects=False)
    assert "erreur=aucun_compte" in r.headers["location"]
    assert env.run(env.db.users.count_documents({"email": "inconnu@gmail.com"})) == 0


def test_un_etat_falsifie_est_refuse(env, monkeypatch):
    _actif(monkeypatch, None)
    r = env.client.get("/api/auth/google/retour", params={"code": "c", "state": "faux.faux"}, follow_redirects=False)
    assert "erreur=etat" in r.headers["location"]


def test_compte_desactive_refuse_apres_google(env, monkeypatch):
    _actif(monkeypatch, {"sub": "g-compta", "email": "compta@gmail.com", "nom": "C"})
    env.client.get("/api/auth/google/retour", params={"code": "c", "state": _etat("web", "compta")}, follow_redirects=False)
    env.run(env.db.users.update_one({"id": "compta"}, {"$set": {"account_status": "disabled"}}))
    r = env.client.get("/api/auth/google/retour", params={"code": "c", "state": _etat()}, follow_redirects=False)
    code = r.headers["location"].split("code=")[1]
    assert env.client.post("/api/auth/google/echange", json={"code": code}, headers=h()).status_code == 403


def test_delier_exige_le_mot_de_passe_et_etat_admin(env, monkeypatch):
    _actif(monkeypatch, {"sub": "g-sup", "email": "sup@gmail.com", "nom": "S"})
    tok = jeton("sup", "superviseur")
    env.client.get("/api/auth/google/retour", params={"code": "c", "state": _etat("web", "sup")}, follow_redirects=False)
    assert env.client.post("/api/auth/google/delier", json={"mot_de_passe": "faux"}, headers=h(tok)).status_code == 400
    assert env.client.post("/api/auth/google/delier", json={"mot_de_passe": "bon-mot-de-passe"}, headers=h(tok)).status_code == 200
    assert env.client.get("/api/admin/google-connexion", headers=h(tok)).status_code == 403      # réservé à l'administrateur
    adm = env.client.get("/api/admin/google-connexion", headers=h(jeton("super", "admin"))).json()
    assert adm["configure"] is True and adm["adresse_retour"].endswith("/api/auth/google/retour") and adm["comptes_lies"] >= 0
